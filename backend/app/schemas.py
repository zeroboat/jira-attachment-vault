"""API request/response models."""
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_validator("*", mode="after")
    @classmethod
    def _utc(cls, v):
        # SQLite drops tz info, so always return UTC.
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class AttachmentOut(_Out):
    id: str
    issue_id: str
    issue_key: str
    project_key: str
    issue_summary: str | None
    issue_status: str | None
    issue_status_category: str | None
    filename: str
    mime_type: str | None
    size: int
    author_name: str | None
    created_at: datetime
    sha256: str | None
    backed_up_at: datetime | None
    backup_error: str | None
    backup_attempts: int
    state: str
    last_seen_at: datetime
    deleted_at: datetime | None
    restored_as_id: str | None


class AuditOut(_Out):
    id: int
    at: datetime
    actor: str
    action: str
    attachment_id: str | None
    issue_key: str | None
    detail: dict[str, Any] | None


class JobLogOut(_Out):
    id: int
    at: datetime
    level: str
    event: str
    attachment_id: str | None
    issue_key: str | None
    data: dict[str, Any] | None


class JobOut(_Out):
    id: int
    kind: str
    status: str
    title: str
    params: dict[str, Any] | None
    attachment_count: int = 0
    result: dict[str, Any] | None
    created_by: str | None
    approved_by: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class Page(BaseModel):
    items: list[AttachmentOut]
    total: int
    page: int
    pages: int


class AttachmentDetail(BaseModel):
    attachment: AttachmentOut
    logs: list[AuditOut]
    duplicates: list[AttachmentOut]


class Totals(BaseModel):
    count: int
    bytes: int


class ProjectUsage(BaseModel):
    project: str
    count: int
    bytes: int


class SyncInfo(BaseModel):
    last_sync: datetime | None
    last_full_sync: datetime | None
    sync_result: dict[str, Any] | None
    backup_result: dict[str, Any] | None
    last_error: str | None


class Dashboard(BaseModel):
    active: Totals
    backed: Totals
    pending: Totals
    errors: Totals
    freed: Totals
    missing: Totals
    stored_bytes: int
    by_project: list[ProjectUsage]
    largest: list[AttachmentOut]
    sync: SyncInfo
    pending_jobs: int


class PolicyIn(BaseModel):
    older_than_days: int | None = Field(365, ge=0)
    min_size_mb: float | None = Field(None, ge=0)
    projects: list[str] = []
    only_done: bool = True
    mime_prefix: str | None = None
    filename_contains: str | None = None
    skip_embedded: bool = True


class CleanupPreview(BaseModel):
    count: int
    bytes: int
    not_backed_up: int
    items: list[AttachmentOut]


class JobDetail(BaseModel):
    job: JobOut
    total_bytes: int
    progress: dict | None = None


class ManualCleanupIn(BaseModel):
    attachment_ids: list[str] = Field(min_length=1, max_length=5000)
    skip_embedded: bool = True


class LoginIn(BaseModel):
    username: str
    password: str


class SyncIn(BaseModel):
    full: bool = False


class AppConfig(BaseModel):
    user: str
    dry_run: bool
    jira_base_url: str
    timezone: str
    storage_backend: str
    jira_configured: bool
    lang: str  # app-wide UI language (also the Jira comment fallback), stored in the DB


class SettingsOut(BaseModel):
    jira_base_url: str
    jira_email: str
    jira_api_token_set: bool
    jira_projects: list[str]
    jira_extra_jql: str
    jira_user_timezone: str
    jira_comment: bool
    jira_comment_lang: str
    sync_interval_minutes: int
    full_reconcile_hours: int
    dry_run: bool
    # read-only, from .env
    storage_backend: str
    storage_location: str
    secret_key_ephemeral: bool


class SettingsIn(BaseModel):
    """Partial update: omitted fields are left unchanged. Empty jira_api_token = keep current."""
    jira_base_url: str | None = None
    jira_email: str | None = None
    jira_api_token: str | None = None
    jira_projects: list[str] | None = None
    jira_extra_jql: str | None = None
    jira_user_timezone: str | None = None
    jira_comment: bool | None = None
    jira_comment_lang: str | None = Field(None, pattern="^(en|ko)$")
    sync_interval_minutes: int | None = Field(None, ge=1, le=1440)
    full_reconcile_hours: int | None = Field(None, ge=1, le=720)
    dry_run: bool | None = None

    @field_validator("jira_base_url")
    @classmethod
    def _url(cls, v):
        if v is None:
            return v
        v = v.strip().rstrip("/")
        if v and not v.startswith("https://"):
            raise ValueError("must start with https://")
        return v

    @field_validator("jira_user_timezone")
    @classmethod
    def _tz(cls, v):
        if v is not None:
            from zoneinfo import ZoneInfo
            try:
                ZoneInfo(v)
            except (KeyError, ValueError):  # ZoneInfoNotFoundError is a KeyError
                raise ValueError("unknown timezone") from None
        return v

    @field_validator("jira_projects")
    @classmethod
    def _projects(cls, v):
        return None if v is None else [p.strip().upper() for p in v if p.strip()]


class JiraTestIn(BaseModel):
    """Unsaved form values to test; empty fields fall back to the saved ones."""
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""


class PasswordIn(BaseModel):
    current: str
    new: str = Field(min_length=8)
