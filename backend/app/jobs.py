"""Jobs that need approval: cleanup (delete) and restore."""
import logging
import os
from collections import OrderedDict
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import timedelta

from sqlalchemy import Select, func, select

from .config import settings
from .db import (ACTIVE, DELETED_BY_VAULT, RESTORED, Attachment, Job, audit,
                 utcnow)
from .jira import JiraClient, JiraError
from .notice import cleanup_comment, post_notices, restore_comment
from .storage import Storage
from .sync import backup_one, sync

log = logging.getLogger(__name__)


# ---------- cleanup policy ----------
@dataclass
class Policy:
    older_than_days: int | None = 365      # by attachment upload date (not issue update date)
    min_size_mb: float | None = None
    projects: list[str] = field(default_factory=list)
    only_done: bool = True                  # only issues whose status category is Done
    mime_prefix: str | None = None          # e.g. image/, video/, application/zip
    filename_contains: str | None = None
    skip_embedded: bool = True              # skip attachments referenced as !filename! in description/comments

    def describe(self) -> str:
        bits = []
        if self.projects:
            bits.append("projects " + ",".join(self.projects))
        if self.older_than_days:
            bits.append(f"older than {self.older_than_days}d")
        if self.min_size_mb:
            bits.append(f">= {self.min_size_mb:g}MB")
        if self.only_done:
            bits.append("done issues")
        if self.mime_prefix:
            bits.append(f"type {self.mime_prefix}*")
        if self.filename_contains:
            bits.append(f"name contains '{self.filename_contains}'")
        return " · ".join(bits) or "no filters"


def candidates_query(policy: Policy) -> Select:
    q = select(Attachment).where(Attachment.state == ACTIVE)
    if policy.older_than_days:
        q = q.where(Attachment.created_at < utcnow() - timedelta(days=policy.older_than_days))
    if policy.min_size_mb:
        q = q.where(Attachment.size >= int(policy.min_size_mb * 1024 * 1024))
    if policy.projects:
        q = q.where(Attachment.project_key.in_(policy.projects))
    if policy.only_done:
        q = q.where(Attachment.issue_status_category == "done")
    if policy.mime_prefix:
        q = q.where(Attachment.mime_type.like(f"{policy.mime_prefix}%"))
    if policy.filename_contains:
        q = q.where(Attachment.filename.contains(policy.filename_contains))
    return q.order_by(Attachment.size.desc())


def candidates_summary(session, policy: Policy) -> dict:
    sub = candidates_query(policy).subquery()
    count, total = session.execute(
        select(func.count(), func.coalesce(func.sum(sub.c.size), 0)).select_from(sub)).one()
    not_backed = session.execute(
        select(func.count()).select_from(sub).where(sub.c.sha256.is_(None))).scalar_one()
    return {"count": count, "bytes": int(total), "not_backed_up": not_backed}


def create_cleanup_job(session, policy: Policy, actor: str) -> Job:
    ids = [a.id for a in session.scalars(candidates_query(policy)).all()]
    job = Job(kind="cleanup", status="pending_approval", title=policy.describe(),
              params=asdict(policy), attachment_ids=ids, created_by=actor)
    session.add(job)
    session.flush()
    audit(session, actor, "cleanup_requested", detail={"job": job.id, "count": len(ids)})
    session.commit()
    return job


def create_restore_job(session, attachment_ids: list[str], actor: str) -> Job:
    job = Job(kind="restore", status="pending_approval",
              title=f"Restore {len(attachment_ids)} attachment(s)", attachment_ids=attachment_ids,
              created_by=actor)
    session.add(job)
    session.flush()
    audit(session, actor, "restore_requested", detail={"job": job.id, "ids": attachment_ids})
    session.commit()
    return job


# ---------- execution ----------
def _is_embedded(filename: str, text: str) -> bool:
    return re.search(r"!" + re.escape(filename) + r"(\|[^!\n]*)?!", text) is not None


def run_cleanup(session, client: JiraClient, storage: Storage, job: Job) -> dict:
    skip_embedded = (job.params or {}).get("skip_embedded", True)
    text_cache: dict[str, str] = {}
    res = {"deleted": 0, "freed_bytes": 0, "skipped": 0, "failed": 0,
           "dry_run": settings.dry_run, "reasons": {}}
    deleted_by_issue: "OrderedDict[str, list[Attachment]]" = OrderedDict()

    def skip(reason: str, att_id: str) -> None:
        res["skipped"] += 1
        res["reasons"].setdefault(reason, []).append(att_id)

    for att_id in job.attachment_ids:
        obj = session.get(Attachment, att_id)
        if obj is None or obj.state != ACTIVE:
            skip("not_in_jira", att_id)
            continue
        try:
            # 1) back up now if there is no backup yet
            if not obj.sha256:
                backup_one(session, client, storage, obj)
                session.commit()
            # 2) re-read the stored file and verify its hash
            if not storage.verify(obj.storage_key, obj.sha256):
                skip("backup_verify_failed", att_id)
                continue
            # 3) is it an image used inline in the description/comments?
            if skip_embedded:
                if obj.issue_id not in text_cache:
                    text_cache[obj.issue_id] = client.get_issue_text(obj.issue_id)
                if _is_embedded(obj.filename, text_cache[obj.issue_id]):
                    skip("embedded", att_id)
                    continue
            # 4) delete
            if settings.dry_run:
                audit(session, job.approved_by or "system", "dry_run_delete", obj, {"job": job.id})
                res["deleted"] += 1
                res["freed_bytes"] += obj.size or 0
                session.commit()
                continue
            try:
                client.delete_attachment(obj.id)
            except JiraError as exc:
                if exc.status != 404:
                    raise
            obj.state = DELETED_BY_VAULT
            obj.deleted_at = utcnow()
            audit(session, job.approved_by or "system", "deleted", obj,
                  {"job": job.id, "sha256": obj.sha256})
            deleted_by_issue.setdefault(obj.issue_id, []).append(obj)
            res["deleted"] += 1
            res["freed_bytes"] += obj.size or 0
            session.commit()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            log.exception("Delete failed %s", att_id)
            res["failed"] += 1
            res["reasons"].setdefault(f"error:{type(exc).__name__}", []).append(att_id)

    # 5) one silent notice comment per issue that actually lost attachments (none in dry run)
    groups = OrderedDict((iid, (items[0].issue_key, cleanup_comment(items, job.id)))
                         for iid, items in deleted_by_issue.items())
    res["comments"] = post_notices(session, client, groups, job.approved_by or "system", job.id)
    return res


def run_restore(session, client: JiraClient, storage: Storage, job: Job) -> dict:
    res = {"restored": 0, "failed": 0, "errors": {}}
    restored_by_issue: "OrderedDict[str, list[tuple[Attachment, str | None]]]" = OrderedDict()
    for att_id in job.attachment_ids:
        obj = session.get(Attachment, att_id)
        fd, tmp = tempfile.mkstemp(prefix="restore-", dir=settings.tmp_dir)
        os.close(fd)
        try:
            if obj is None or not obj.storage_key:
                raise ValueError("No backup exists")
            sha = storage.download_to(obj.storage_key, tmp)
            if sha != obj.sha256:
                raise ValueError("Backup hash mismatch")
            created = client.upload_attachment(obj.issue_id, obj.filename, tmp, obj.mime_type)
            new_id = str(created[0]["id"]) if created else None
            obj.state = RESTORED
            obj.restored_as_id = new_id
            audit(session, job.approved_by or "system", "restored", obj,
                  {"job": job.id, "new_attachment_id": new_id})
            restored_by_issue.setdefault(obj.issue_id, []).append((obj, new_id))
            res["restored"] += 1
            session.commit()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            log.exception("Restore failed %s", att_id)
            res["failed"] += 1
            res["errors"][att_id] = str(exc)[:300]
        finally:
            os.unlink(tmp)

    groups = OrderedDict((iid, (items[0][0].issue_key, restore_comment(items, job.id)))
                         for iid, items in restored_by_issue.items())
    res["comments"] = post_notices(session, client, groups, job.approved_by or "system", job.id)
    return res


def run_job(session, client: JiraClient, storage: Storage, job: Job) -> None:
    job.status = "running"
    job.started_at = utcnow()
    session.commit()
    try:
        if job.kind == "cleanup":
            result = run_cleanup(session, client, storage, job)
        elif job.kind == "restore":
            result = run_restore(session, client, storage, job)
        elif job.kind in ("sync", "full_sync"):
            from .sync import backup_pending
            result = {"sync": sync(session, client, full=job.kind == "full_sync"),
                      "backup": backup_pending(session, client, storage)}
        else:
            raise ValueError(f"Unknown job kind: {job.kind}")
        job.status = "done"
        job.result = result
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        log.exception("Job %s failed", job.id)
        job.status = "failed"
        job.result = {"error": f"{type(exc).__name__}: {exc}"[:2000]}
    job.finished_at = utcnow()
    session.commit()
