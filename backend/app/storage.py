"""Backup storage, selected by STORAGE_BACKEND.

  local      local folder (disk, including NAS mounts)
  seaweedfs  self-hosted SeaweedFS (S3 API). Can be started with docker compose --profile seaweedfs.
  s3         any other S3-compatible store (AWS S3, Cloudflare R2, Garage, ...)

Layout
  objects/ab/cd/<sha256>                         file content (content-addressed, identical files stored once)
  manifest/<PROJECT>/<ISSUE-KEY>/<att_id>.json   original filename, issue, uploader, etc.
Even if the DB is lost, the manifests alone tell which file belonged to which issue.
"""
import hashlib
import json
import os
import shutil
import tempfile
from typing import Iterator

from .config import settings

CHUNK = 1024 * 1024


def object_key(sha256: str) -> str:
    return f"objects/{sha256[:2]}/{sha256[2:4]}/{sha256}"


def manifest_key(project_key: str, issue_key: str, attachment_id: str) -> str:
    return f"manifest/{project_key}/{issue_key}/{attachment_id}.json"


class Storage:
    name = "base"

    def exists(self, key: str) -> bool: ...
    def put_file(self, local_path: str, key: str) -> None: ...
    def put_bytes(self, data: bytes, key: str) -> None: ...
    def iter_chunks(self, key: str) -> Iterator[bytes]: ...
    def list_keys(self, prefix: str = "") -> Iterator[str]: ...

    def describe(self) -> str:
        return self.name

    def probe(self) -> None:
        """Raise if the store can't be used right now. Used by the Settings status check."""
        raise NotImplementedError

    def put_json(self, obj: dict, key: str) -> None:
        self.put_bytes(json.dumps(obj, ensure_ascii=False, indent=2, default=str).encode(), key)

    def verify(self, key: str, sha256: str) -> bool:
        """Read the stored file in full and recompute its hash. Safeguard before deletion."""
        h = hashlib.sha256()
        try:
            for chunk in self.iter_chunks(key):
                h.update(chunk)
        except Exception:
            return False
        return h.hexdigest() == sha256

    def download_to(self, key: str, local_path: str) -> str:
        """Download to a file and return its sha256."""
        h = hashlib.sha256()
        with open(local_path, "wb") as f:
            for chunk in self.iter_chunks(key):
                f.write(chunk)
                h.update(chunk)
        return h.hexdigest()


class LocalStorage(Storage):
    name = "local"

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    def _path(self, key: str) -> str:
        p = os.path.abspath(os.path.join(self.root, key))
        if not p.startswith(self.root + os.sep):
            raise ValueError(f"Invalid key: {key}")
        return p

    def exists(self, key: str) -> bool:
        return os.path.isfile(self._path(key))

    def _atomic_write(self, key: str, writer) -> None:
        dest = self._path(key)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest), prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as f:
                writer(f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, dest)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def put_file(self, local_path: str, key: str) -> None:
        def w(f):
            with open(local_path, "rb") as src:
                shutil.copyfileobj(src, f, CHUNK)
        self._atomic_write(key, w)

    def put_bytes(self, data: bytes, key: str) -> None:
        self._atomic_write(key, lambda f: f.write(data))

    def iter_chunks(self, key: str) -> Iterator[bytes]:
        with open(self._path(key), "rb") as f:
            while chunk := f.read(CHUNK):
                yield chunk

    def list_keys(self, prefix: str = "") -> Iterator[str]:
        for dirpath, _dirs, files in os.walk(self.root):
            for name in files:
                if name.startswith(".tmp-"):
                    continue
                key = os.path.relpath(os.path.join(dirpath, name), self.root).replace(os.sep, "/")
                if key.startswith(prefix) and not key.startswith("."):
                    yield key

    def describe(self) -> str:
        return f"local:{self.root}"

    def probe(self) -> None:
        # Existence alone says nothing (the folder is auto-created); prove we can write and sync.
        with tempfile.NamedTemporaryFile(dir=self.root, prefix=".tmp-probe-") as f:
            f.write(b"ok")
            f.flush()
            os.fsync(f.fileno())


class S3Storage(Storage):
    name = "s3"

    def __init__(self, name: str = "s3", endpoint_url: str | None = None, bucket: str | None = None,
                 prefix: str | None = None, region: str | None = None, access_key: str | None = None,
                 secret_key: str | None = None, create_bucket: bool = True, fast_fail: bool = False):
        import boto3
        from botocore.config import Config
        self.name = name
        self.endpoint_url = endpoint_url if endpoint_url is not None else settings.s3_endpoint_url
        self.bucket = bucket or settings.s3_bucket
        self.prefix = (prefix if prefix is not None else settings.s3_prefix).strip("/")
        self.client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            region_name=region or settings.s3_region or "us-east-1",
            aws_access_key_id=access_key or settings.s3_access_key,
            aws_secret_access_key=secret_key or settings.s3_secret_key,
            config=Config(
                # Self-hosted stores (SeaweedFS etc.) only understand path-style http://host:port/bucket/key.
                s3={"addressing_style": "path" if self.endpoint_url else "auto"},
                # Some S3-compatible stores reject the CRC checksums newer boto3 adds by default, so only send them when required.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                # Backups retry patiently; a status check must answer within seconds.
                **({"connect_timeout": 3, "read_timeout": 5, "retries": {"max_attempts": 1, "mode": "standard"}}
                   if fast_fail else {"retries": {"max_attempts": 8, "mode": "standard"}}),
            ),
        )
        if create_bucket:
            self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchBucket", "NotFound"):
                self.client.create_bucket(Bucket=self.bucket)
            else:
                raise

    def describe(self) -> str:
        where = self.endpoint_url or "AWS"
        return f"{self.name}:{where}/{self.bucket}" + (f"/{self.prefix}" if self.prefix else "")

    def probe(self) -> None:
        # Checks endpoint, credentials and bucket; the worker creates the bucket when it starts.
        self.client.head_bucket(Bucket=self.bucket)

    def _k(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._k(key))
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def put_file(self, local_path: str, key: str) -> None:
        self.client.upload_file(local_path, self.bucket, self._k(key))

    def put_bytes(self, data: bytes, key: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=self._k(key), Body=data)

    def iter_chunks(self, key: str) -> Iterator[bytes]:
        body = self.client.get_object(Bucket=self.bucket, Key=self._k(key))["Body"]
        try:
            yield from body.iter_chunks(CHUNK)
        finally:
            body.close()

    def list_keys(self, prefix: str = "") -> Iterator[str]:
        strip = len(self.prefix) + 1 if self.prefix else 0
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self._k(prefix)):
            for obj in page.get("Contents", []):
                yield obj["Key"][strip:]


_storage: Storage | None = None


BACKENDS = ("local", "seaweedfs", "s3")


def make_storage(backend: str, check_only: bool = False) -> Storage:
    """check_only: no network on construction (no bucket creation) and short timeouts, no retries."""
    s3 = {"create_bucket": False, "fast_fail": True} if check_only else {}
    if backend == "local":
        return LocalStorage(settings.storage_local_path)
    if backend == "seaweedfs":
        return S3Storage(name="seaweedfs", endpoint_url=settings.s3_endpoint_url or "http://seaweedfs-filer:8333", **s3)
    if backend == "s3":
        return S3Storage(name="s3", **s3)
    raise ValueError(f"Unknown STORAGE_BACKEND: {backend} (local | seaweedfs | s3)")


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        _storage = make_storage(settings.storage_backend)
    return _storage
