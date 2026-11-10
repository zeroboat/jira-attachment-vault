"""Settings from environment variables.

Settings marked "web" below can also be changed on the Settings page; once saved there, the
DB value wins (see settings_store.py). The env var only seeds the DB on first start.
"""
import os
import secrets


def _list(value: str | None) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


class Settings:
    def __init__(self) -> None:
        e = os.environ.get
        # Jira Cloud (web)
        self.jira_base_url = e("JIRA_BASE_URL", "").rstrip("/")
        self.jira_email = e("JIRA_EMAIL", "")
        self.jira_api_token = e("JIRA_API_TOKEN", "")
        self.jira_projects = _list(e("JIRA_PROJECTS"))
        self.jira_extra_jql = e("JIRA_EXTRA_JQL", "")
        # JQL date conditions are interpreted in the API account's Jira profile timezone.
        self.jira_user_timezone = e("JIRA_USER_TIMEZONE", "UTC")
        # Leave a silent notice comment on issues whose attachments were cleaned up / restored
        self.jira_comment = _bool(e("JIRA_COMMENT"), default=True)
        # Language of that comment: en | ko
        self.jira_comment_lang = e("JIRA_COMMENT_LANG", "en").lower()

        # DB
        self.database_url = e("DATABASE_URL", "sqlite:///./data/vault.db")

        # Backup storage: local (disk) | seaweedfs (self-hosted SeaweedFS) | s3 (any S3-compatible)
        self.storage_backend = e("STORAGE_BACKEND", "local").lower()
        self.storage_local_path = e("STORAGE_LOCAL_PATH", "./data/vault")
        self.s3_endpoint_url = e("S3_ENDPOINT_URL") or None
        self.s3_bucket = e("S3_BUCKET", "jira-attachments")
        self.s3_prefix = e("S3_PREFIX", "").strip("/")
        self.s3_region = e("S3_REGION") or None
        self.s3_access_key = e("S3_ACCESS_KEY") or None
        self.s3_secret_key = e("S3_SECRET_KEY") or None

        # Worker intervals (web)
        self.sync_interval_minutes = int(e("SYNC_INTERVAL_MINUTES", "30"))
        self.full_reconcile_hours = int(e("FULL_RECONCILE_HOURS", "24"))
        self.sync_overlap_minutes = int(e("SYNC_OVERLAP_MINUTES", "60"))
        self.tmp_dir = e("TMP_DIR") or None

        # Web login
        self.admin_user = e("ADMIN_USER", "admin")
        # Initial admin password. Once changed on the Settings page, a hash in the DB is used instead.
        self.admin_password = e("ADMIN_PASSWORD", "")
        self.admin_password_hash: str | None = None
        # Signs login sessions and encrypts the Jira API token stored in the DB.
        # If empty, a random key is used for this process only: sessions and the saved token
        # won't survive a restart. Always set it in production.
        self.secret_key = e("SECRET_KEY", "") or secrets.token_hex(32)
        self.secret_key_ephemeral = not e("SECRET_KEY")
        self.session_hours = int(e("SESSION_HOURS", "12"))
        self.cookie_secure = _bool(e("COOKIE_SECURE"), default=False)  # true behind HTTPS
        # Path to the built frontend (frontend/dist). If set, the same server serves the UI.
        self.frontend_dist = e("FRONTEND_DIST", "")

        # (web) If true, cleanup jobs only log what they would delete and never delete from Jira.
        self.dry_run = _bool(e("DRY_RUN"), default=True)


settings = Settings()
