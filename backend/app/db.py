"""DB models: attachment metadata + jobs + audit log."""
import os
from datetime import datetime, timezone

from sqlalchemy import (JSON, BigInteger, DateTime, Integer, String, Text,
                        create_engine, select)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite drops tz info, so normalize to UTC on read."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


# Attachment.state values
ACTIVE = "active"                      # present in Jira
DELETED_BY_VAULT = "deleted_by_vault"  # deleted by a cleanup job (backup exists)
MISSING_IN_JIRA = "missing_in_jira"    # gone from Jira (deleted by someone else, or issue deleted)
RESTORED = "restored"                  # re-uploaded (see restored_as_id)


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # Jira attachment id
    issue_id: Mapped[str] = mapped_column(String(32), index=True)
    issue_key: Mapped[str] = mapped_column(String(64), index=True)
    project_key: Mapped[str] = mapped_column(String(64), index=True)
    issue_summary: Mapped[str | None] = mapped_column(Text)
    issue_status: Mapped[str | None] = mapped_column(String(128))
    issue_status_category: Mapped[str | None] = mapped_column(String(32))  # new|indeterminate|done

    filename: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    author_account_id: Mapped[str | None] = mapped_column(String(128))
    author_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    # backup
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    storage_key: Mapped[str | None] = mapped_column(Text)
    backed_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    backup_error: Mapped[str | None] = mapped_column(Text)
    backup_attempts: Mapped[int] = mapped_column(Integer, default=0)

    # state
    state: Mapped[str] = mapped_column(String(32), default=ACTIVE, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restored_as_id: Mapped[str | None] = mapped_column(String(32))


class Job(Base):
    """Jobs that need human approval (cleanup, restore) plus manual syncs."""
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32))  # cleanup | restore | sync | full_sync
    status: Mapped[str] = mapped_column(String(32), index=True)
    # pending_approval -> approved -> running -> done | failed ; cancelled
    title: Mapped[str] = mapped_column(Text, default="")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    attachment_ids: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[dict | None] = mapped_column(JSON)
    created_by: Mapped[str | None] = mapped_column(String(128))
    approved_by: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64), index=True)
    attachment_id: Mapped[str | None] = mapped_column(String(32), index=True)
    issue_key: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict | None] = mapped_column(JSON)


class JobLog(Base):
    """Step-by-step log of a job. `event` is a code the UI translates; `data` holds its values."""
    __tablename__ = "job_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    level: Mapped[str] = mapped_column(String(8), default="info")  # info | warn | error
    event: Mapped[str] = mapped_column(String(64))
    attachment_id: Mapped[str | None] = mapped_column(String(32))
    issue_key: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict | None] = mapped_column(JSON)


class SyncState(Base):
    __tablename__ = "sync_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)


def _make_engine():
    url = settings.database_url
    if url.startswith("sqlite:///"):
        path = url.removeprefix("sqlite:///")
        if path and path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    return create_engine(url, pool_pre_ping=True)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_state(session, key: str) -> str | None:
    row = session.get(SyncState, key)
    return row.value if row else None


def set_state(session, key: str, value: str | None) -> None:
    row = session.get(SyncState, key)
    if row is None:
        session.add(SyncState(key=key, value=value))
    else:
        row.value = value


def audit(session, actor: str, action: str, att: "Attachment | None" = None,
          detail: dict | None = None) -> None:
    session.add(AuditLog(
        actor=actor, action=action,
        attachment_id=att.id if att else None,
        issue_key=att.issue_key if att else None,
        detail=detail,
    ))


def job_log(session, job_id: int | None, event: str, att: "Attachment | None" = None,
            level: str = "info", **data) -> None:
    """Add a line to a job's log (no-op outside a job). Committed with the caller's next commit."""
    if job_id is None:
        return
    if att is not None:
        data.setdefault("file", att.filename)
    session.add(JobLog(job_id=job_id, event=event, level=level, data=data or None,
                       attachment_id=att.id if att else None,
                       issue_key=att.issue_key if att else None))


__all__ = ["Attachment", "Job", "JobLog", "AuditLog", "job_log", "SyncState", "SessionLocal", "engine",
           "init_db", "get_state", "set_state", "audit", "utcnow", "as_utc", "select",
           "ACTIVE", "DELETED_BY_VAULT", "MISSING_IN_JIRA", "RESTORED"]
