"""Settings editable from the web UI, stored in the DB (sync_state table, keys "setting:<name>").

- On first start, any of these present in the environment is copied into the DB once.
  After that the DB is the source of truth and the env var is ignored.
- Values are applied onto the shared `settings` object, so the rest of the code keeps reading
  `settings.<name>`. The web process applies on save; the worker reloads on every tick.
- The Jira API token is encrypted with SECRET_KEY (Fernet) and never returned to the browser.
- The admin password is stored as a scrypt hash.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets

from cryptography.fernet import Fernet, InvalidToken

from sqlalchemy.exc import IntegrityError

from .config import settings
from .db import SyncState, get_state, set_state

log = logging.getLogger(__name__)

PREFIX = "setting:"
# name -> type. Secrets are stored encrypted.
EDITABLE: dict[str, type | str] = {
    "jira_base_url": str,
    "jira_email": str,
    "jira_api_token": "secret",
    "jira_projects": list,
    "jira_extra_jql": str,
    "jira_user_timezone": str,
    "jira_comment": bool,
    "jira_comment_lang": str,
    "sync_interval_minutes": int,
    "full_reconcile_hours": int,
    "dry_run": bool,
}
PASSWORD_KEY = PREFIX + "admin_password_hash"

_fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest()))


# ---------- encode / decode ----------
def _encode(name: str, value) -> str:
    if EDITABLE[name] == "secret":
        return "enc:" + _fernet.encrypt(str(value).encode()).decode() if value else ""
    return json.dumps(value)


def _decode(name: str, raw: str):
    if EDITABLE[name] == "secret":
        if not raw:
            return ""
        try:
            return _fernet.decrypt(raw.removeprefix("enc:").encode()).decode()
        except InvalidToken:
            log.warning("Cannot decrypt %s (SECRET_KEY changed?). Re-enter it in Settings.", name)
            return ""
    return json.loads(raw)


# ---------- load / save ----------
def seed_from_env(session) -> None:
    """Copy env values into the DB once, for settings that have no DB row yet."""
    for name in EDITABLE:
        if os.environ.get(name.upper()) and get_state(session, PREFIX + name) is None:
            set_state(session, PREFIX + name, _encode(name, getattr(settings, name)))
    try:
        session.commit()
    except IntegrityError:  # web and worker seeding at the same moment; the other one won
        session.rollback()


def load(session) -> None:
    """Apply DB values onto `settings`."""
    rows = session.query(SyncState).filter(SyncState.key.startswith(PREFIX)).all()
    for row in rows:
        name = row.key.removeprefix(PREFIX)
        if name in EDITABLE and row.value is not None:
            setattr(settings, name, _decode(name, row.value))
        elif row.key == PASSWORD_KEY:
            settings.admin_password_hash = row.value


def save(session, values: dict) -> list[str]:
    """Persist and apply changed values. Returns the names that actually changed."""
    changed = []
    for name, value in values.items():
        if name not in EDITABLE or value is None:
            continue
        if EDITABLE[name] == "secret" and value == "":
            continue  # empty secret field = keep current
        if getattr(settings, name) == value:
            continue
        set_state(session, PREFIX + name, _encode(name, value))
        setattr(settings, name, value)
        changed.append(name)
    return changed


def public_values() -> dict:
    out = {name: getattr(settings, name) for name in EDITABLE if EDITABLE[name] != "secret"}
    out["jira_api_token_set"] = bool(settings.jira_api_token)
    return out


def jira_configured() -> bool:
    return bool(settings.jira_base_url and settings.jira_email and settings.jira_api_token)


# ---------- admin password ----------
def _hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password: str) -> bool:
    stored = getattr(settings, "admin_password_hash", None)
    if stored:
        _, salt, digest = stored.split("$")
        return hmac.compare_digest(_hash(password, bytes.fromhex(salt)).split("$")[2], digest)
    return bool(settings.admin_password) and secrets.compare_digest(password.encode(), settings.admin_password.encode())


def set_password(session, password: str) -> None:
    settings.admin_password_hash = _hash(password)
    set_state(session, PASSWORD_KEY, settings.admin_password_hash)
