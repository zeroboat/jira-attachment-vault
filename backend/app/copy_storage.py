"""Copy between backup stores. Use it when switching storage (local → seaweedfs, etc.).

  python -m app.copy_storage --from local --to seaweedfs
  python -m app.copy_storage --from local --to seaweedfs --dry-run   # only show what would be copied

- Files already in the target are skipped (safe to run repeatedly).
- objects/ files are re-hashed while copying and checked against their name (the hash).
- The source is never deleted. When done, change STORAGE_BACKEND in .env and restart.
"""
import argparse
import hashlib
import logging
import os
import sys
import tempfile

from .config import settings
from .storage import BACKENDS, Storage, make_storage

log = logging.getLogger("copy_storage")


def copy_all(src: Storage, dst: Storage, dry_run: bool = False) -> dict:
    stats = {"copied": 0, "skipped": 0, "bytes": 0, "failed": 0, "bad_hash": 0}
    for key in src.list_keys():
        if not (key.startswith("objects/") or key.startswith("manifest/")):
            continue
        if dst.exists(key):
            stats["skipped"] += 1
            continue
        if dry_run:
            stats["copied"] += 1
            continue
        fd, tmp = tempfile.mkstemp(prefix="copy-", dir=settings.tmp_dir)
        os.close(fd)
        try:
            sha = src.download_to(key, tmp)
            if key.startswith("objects/") and sha != key.rsplit("/", 1)[-1]:
                stats["bad_hash"] += 1
                log.error("Hash mismatch, skipped: %s", key)
                continue
            dst.put_file(tmp, key)
            stats["copied"] += 1
            stats["bytes"] += os.path.getsize(tmp)
            if stats["copied"] % 100 == 0:
                log.info("Progress: %s", stats)
        except Exception:  # noqa: BLE001
            stats["failed"] += 1
            log.exception("Copy failed: %s", key)
        finally:
            os.unlink(tmp)
    return stats


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Copy between backup stores")
    ap.add_argument("--from", dest="src", required=True, choices=BACKENDS)
    ap.add_argument("--to", dest="dst", required=True, choices=BACKENDS)
    ap.add_argument("--dry-run", action="store_true", help="Only count, do not copy")
    args = ap.parse_args(argv)
    if args.src == args.dst:
        ap.error("--from and --to are the same")
    src, dst = make_storage(args.src), make_storage(args.dst)
    log.info("%s → %s%s", src.describe(), dst.describe(), " (dry-run)" if args.dry_run else "")
    stats = copy_all(src, dst, dry_run=args.dry_run)
    log.info("Done: %s", stats)
    return 1 if stats["failed"] or stats["bad_hash"] else 0


if __name__ == "__main__":
    sys.exit(main())
