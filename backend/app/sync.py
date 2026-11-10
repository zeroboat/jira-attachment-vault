"""Jira → DB metadata sync, and DB → storage backup."""
import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .config import settings
from .db import (ACTIVE, MISSING_IN_JIRA, Attachment, as_utc, audit, get_state, job_log,
                 set_state, utcnow)
from .jira import JiraClient, JiraError
from .storage import Storage, manifest_key, object_key

log = logging.getLogger(__name__)
MAX_BACKUP_ATTEMPTS = 5


def parse_jira_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt).astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def build_jql(since_utc: datetime | None) -> str:
    parts = ["attachments IS NOT EMPTY"]
    if settings.jira_projects:
        parts.append("project in (" + ", ".join(f'"{p}"' for p in settings.jira_projects) + ")")
    if since_utc is not None:
        local = since_utc.astimezone(ZoneInfo(settings.jira_user_timezone))
        parts.append(f'updated >= "{local:%Y-%m-%d %H:%M}"')
    else:
        # /search/jql may reject unbounded JQL, so add a lower bound.
        parts.append('created >= "2000-01-01"')
    if settings.jira_extra_jql:
        parts.append(f"({settings.jira_extra_jql})")
    return " AND ".join(parts) + " ORDER BY updated ASC"


def sync(session, client: JiraClient, full: bool = False, job_id: int | None = None) -> dict:
    """Upsert the attachment list into the DB.

    Incremental: only issues updated since the last sync.
    Full: scan every issue and mark active attachments not seen this time as missing_in_jira.
    """
    started = utcnow()
    since = None
    if not full:
        last = get_state(session, "last_sync_started")
        if last:
            since = datetime.fromisoformat(last) - timedelta(minutes=settings.sync_overlap_minutes)
    jql = build_jql(since)
    log.info("Sync started (full=%s): %s", full, jql)
    job_log(session, job_id, "sync_started", full=full, jql=jql)

    stats = {"issues": 0, "new": 0, "updated": 0, "reappeared": 0, "missing": 0, "full": full}
    for issue in client.search_issues(jql):
        stats["issues"] += 1
        f = issue.get("fields") or {}
        status = f.get("status") or {}
        project = f.get("project") or {}
        issue_key = issue["key"]
        for a in f.get("attachment") or []:
            obj = session.get(Attachment, a["id"])
            if obj is None:
                obj = Attachment(id=a["id"], state=ACTIVE, first_seen_at=started)
                session.add(obj)
                stats["new"] += 1
                job_log(session, job_id, "found", issue=issue_key, file=a.get("filename"),
                        size=int(a.get("size") or 0))
            else:
                stats["updated"] += 1
                if obj.state == MISSING_IN_JIRA:
                    obj.state = ACTIVE
                    stats["reappeared"] += 1
                    job_log(session, job_id, "reappeared", obj)
            author = a.get("author") or {}
            obj.issue_id = str(issue["id"])
            obj.issue_key = issue_key
            obj.project_key = project.get("key") or issue_key.split("-")[0]
            obj.issue_summary = f.get("summary")
            obj.issue_status = status.get("name")
            obj.issue_status_category = (status.get("statusCategory") or {}).get("key")
            obj.filename = a.get("filename") or f"attachment-{a['id']}"
            obj.mime_type = a.get("mimeType")
            obj.size = int(a.get("size") or 0)
            obj.author_account_id = author.get("accountId")
            obj.author_name = author.get("displayName")
            obj.created_at = parse_jira_dt(a.get("created")) or started
            obj.last_seen_at = started
        if stats["issues"] % 50 == 0:
            job_log(session, job_id, "sync_progress", issues=stats["issues"])
            session.commit()

    if full:
        stale = session.scalars(select(Attachment).where(
            Attachment.state == ACTIVE, Attachment.last_seen_at < started)).all()
        for obj in stale:
            obj.state = MISSING_IN_JIRA
            audit(session, "system", "missing_in_jira", obj)
            job_log(session, job_id, "missing", obj, level="warn")
            stats["missing"] += 1
        set_state(session, "last_full_sync", started.isoformat())

    set_state(session, "last_sync_started", started.isoformat())
    set_state(session, "last_sync_result", json.dumps(stats))
    job_log(session, job_id, "sync_finished", **stats)
    session.commit()
    log.info("Sync finished: %s", stats)
    return stats


def _manifest(obj: Attachment) -> dict:
    return {
        "attachment_id": obj.id, "issue_id": obj.issue_id, "issue_key": obj.issue_key,
        "project_key": obj.project_key, "issue_summary": obj.issue_summary,
        "filename": obj.filename, "mime_type": obj.mime_type, "size": obj.size,
        "author_account_id": obj.author_account_id, "author_name": obj.author_name,
        "created_at": as_utc(obj.created_at).isoformat() if obj.created_at else None,
        "sha256": obj.sha256, "object_key": obj.storage_key,
        "backed_up_at": as_utc(obj.backed_up_at).isoformat() if obj.backed_up_at else None,
    }


def backup_one(session, client: JiraClient, storage: Storage, obj: Attachment) -> None:
    fd, tmp = tempfile.mkstemp(prefix="att-", dir=settings.tmp_dir)
    try:
        h = hashlib.sha256()
        n = 0
        with os.fdopen(fd, "wb") as out:
            r = client.download_attachment(obj.id)
            try:
                for chunk in r.iter_content(1024 * 1024):
                    out.write(chunk)
                    h.update(chunk)
                    n += len(chunk)
            finally:
                r.close()
        if obj.size and n != obj.size:
            raise ValueError(f"Size mismatch: Jira {obj.size}B, downloaded {n}B")
        sha = h.hexdigest()
        key = object_key(sha)
        if not storage.exists(key):
            storage.put_file(tmp, key)
        obj.sha256 = sha
        obj.storage_key = key
        obj.backed_up_at = utcnow()
        obj.backup_error = None
        storage.put_json(_manifest(obj), manifest_key(obj.project_key, obj.issue_key, obj.id))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def backup_pending(session, client: JiraClient, storage: Storage, limit: int | None = None,
                   job_id: int | None = None) -> dict:
    q = (select(Attachment)
         .where(Attachment.state == ACTIVE, Attachment.sha256.is_(None),
                Attachment.backup_attempts < MAX_BACKUP_ATTEMPTS)
         .order_by(Attachment.created_at))
    if limit:
        q = q.limit(limit)
    stats = {"ok": 0, "failed": 0, "bytes": 0, "missing": 0}
    todo = session.scalars(q).all()
    job_log(session, job_id, "backup_started", count=len(todo))
    for obj in todo:
        obj.backup_attempts = (obj.backup_attempts or 0) + 1
        try:
            backup_one(session, client, storage, obj)
            audit(session, "system", "backed_up", obj, {"sha256": obj.sha256})
            job_log(session, job_id, "backed_up", obj, size=obj.size)
            stats["ok"] += 1
            stats["bytes"] += obj.size or 0
        except JiraError as exc:
            if exc.status == 404:
                obj.state = MISSING_IN_JIRA
                obj.backup_error = "Not found in Jira (deleted before backup)"
                audit(session, "system", "missing_in_jira", obj)
                job_log(session, job_id, "missing", obj, level="warn")
                stats["missing"] += 1
            else:
                obj.backup_error = str(exc)[:1000]
                job_log(session, job_id, "backup_failed", obj, level="error", error=obj.backup_error[:300])
                stats["failed"] += 1
            log.warning("Backup failed %s (%s): %s", obj.id, obj.filename, exc)
        except Exception as exc:  # noqa: BLE001
            obj.backup_error = f"{type(exc).__name__}: {exc}"[:1000]
            job_log(session, job_id, "backup_failed", obj, level="error", error=obj.backup_error[:300])
            stats["failed"] += 1
            log.exception("Backup failed %s (%s)", obj.id, obj.filename)
        session.commit()
    job_log(session, job_id, "backup_finished", **stats)
    set_state(session, "last_backup_result", json.dumps(stats))
    session.commit()
    return stats
