"""Storage backend tests. The S3 path is exercised against a local fake S3 server (moto).
It connects the same way as SeaweedFS (http://host:port endpoint, path-style addressing).

Run: python -m pytest tests -q   (needs moto[server]: pip install "moto[server]")
"""
import hashlib
import os
import socket
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
moto_server = pytest.importorskip("moto.server")

from app.copy_storage import copy_all  # noqa: E402
from app.storage import LocalStorage, S3Storage, object_key  # noqa: E402


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def s3_endpoint():
    port = _free_port()
    server = moto_server.ThreadedMotoServer(ip_address="127.0.0.1", port=port)
    server.start()
    yield f"http://127.0.0.1:{port}"
    server.stop()


def _seaweed_like(endpoint: str, bucket: str, prefix: str = "") -> S3Storage:
    return S3Storage(name="seaweedfs", endpoint_url=endpoint, bucket=bucket, prefix=prefix,
                     region="us-east-1", access_key="test", secret_key="test")


def _put(storage, data: bytes) -> str:
    sha = hashlib.sha256(data).hexdigest()
    fd, tmp = tempfile.mkstemp()
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    storage.put_file(tmp, object_key(sha))
    os.unlink(tmp)
    return sha


def test_s3_backend_roundtrip(s3_endpoint):
    st = _seaweed_like(s3_endpoint, "vault-roundtrip", prefix="jira")  # bucket auto-created
    data = os.urandom(3 * 1024 * 1024 + 17)  # crosses a chunk boundary
    sha = _put(st, data)
    key = object_key(sha)
    assert st.exists(key)
    assert not st.exists(object_key("0" * 64))
    assert st.verify(key, sha)
    assert not st.verify(key, "f" * 64)
    st.put_json({"filename": "회의록.docx"}, "manifest/OPS/OPS-1/1.json")
    assert sorted(st.list_keys()) == sorted([key, "manifest/OPS/OPS-1/1.json"])
    assert b"".join(st.iter_chunks(key)) == data
    # prefix is applied to the real key
    raw = st.client.list_objects_v2(Bucket="vault-roundtrip")["Contents"]
    assert all(o["Key"].startswith("jira/") for o in raw)
    # re-creating with the same bucket is fine
    _seaweed_like(s3_endpoint, "vault-roundtrip", prefix="jira")


def test_copy_local_to_seaweed_and_back(s3_endpoint, tmp_path):
    local = LocalStorage(str(tmp_path / "disk"))
    shas = [_put(local, f"file-{i}".encode() * 1000) for i in range(5)]
    local.put_json({"a": 1}, "manifest/DEV/DEV-1/10.json")
    # one corrupted file: name (hash) != content → must not be copied
    local.put_bytes(b"corrupted", object_key("a" * 64))

    sw = _seaweed_like(s3_endpoint, "vault-copy")
    stats = copy_all(local, sw)
    assert stats["copied"] == 6 and stats["bad_hash"] == 1 and stats["failed"] == 0, stats
    assert all(sw.verify(object_key(s), s) for s in shas)
    assert not sw.exists(object_key("a" * 64))

    again = copy_all(local, sw)  # safe to re-run
    assert again["copied"] == 0 and again["skipped"] == 6, again

    back = LocalStorage(str(tmp_path / "restore"))
    stats = copy_all(sw, back)
    assert stats["copied"] == 6, stats
    assert all(back.verify(object_key(s), s) for s in shas)
    assert os.path.exists(tmp_path / "restore/manifest/DEV/DEV-1/10.json")


def test_dry_run(tmp_path, s3_endpoint):
    local = LocalStorage(str(tmp_path / "d"))
    _put(local, b"x" * 10)
    sw = _seaweed_like(s3_endpoint, "vault-dry")
    assert copy_all(local, sw, dry_run=True)["copied"] == 1
    assert list(sw.list_keys()) == []


def test_probe(tmp_path, s3_endpoint):
    local = LocalStorage(str(tmp_path / "p"))
    local.probe()
    assert list(local.list_keys()) == []  # probe leaves nothing behind
    os.chmod(local.root, 0o500)
    try:
        if os.geteuid() != 0:  # root ignores permissions
            with pytest.raises(OSError):
                local.probe()
    finally:
        os.chmod(local.root, 0o700)

    _seaweed_like(s3_endpoint, "vault-probe").probe()  # created by the normal constructor
    missing = S3Storage(name="seaweedfs", endpoint_url=s3_endpoint, bucket="vault-nope", region="us-east-1",
                        access_key="test", secret_key="test", create_bucket=False, fast_fail=True)
    with pytest.raises(Exception):
        missing.probe()
    dead = S3Storage(name="seaweedfs", endpoint_url="http://127.0.0.1:9", bucket="b", region="us-east-1",
                     access_key="test", secret_key="test", create_bucket=False, fast_fail=True)
    start = time.monotonic()
    with pytest.raises(Exception):
        dead.probe()
    assert time.monotonic() - start < 10
