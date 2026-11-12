"""Cookie session login. A signed token (HMAC-SHA256) is stored in an HttpOnly cookie."""
import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import HTTPException, Request, Response

from . import settings_store
from .config import settings
from .db import SessionLocal, User

COOKIE = "vault_session"
_secret = settings.secret_key.encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue(username: str) -> str:
    payload = _b64(json.dumps({"u": username, "exp": int(time.time()) + settings.session_hours * 3600}).encode())
    sig = _b64(hmac.new(_secret, payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    expected = _b64(hmac.new(_secret, payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(_unb64(payload))
    except ValueError:
        return None
    if data.get("exp", 0) < time.time():
        return None
    return data.get("u")


def is_admin(username: str) -> bool:
    return secrets.compare_digest(username.encode(), settings.admin_user.encode())


def _find(username: str) -> User | None:
    with SessionLocal() as s:
        return s.get(User, username)


def check_password(username: str, password: str) -> bool:
    if is_admin(username):
        if not settings.admin_password and not settings.admin_password_hash:
            raise HTTPException(500, "ADMIN_PASSWORD is not set on the server.")
        return settings_store.check_password(password)
    user = _find(username)
    return bool(user) and settings_store.verify_hash(user.password_hash, password)


def set_cookie(response: Response, username: str) -> None:
    response.set_cookie(COOKIE, issue(username), max_age=settings.session_hours * 3600,
                        httponly=True, samesite="strict", secure=settings.cookie_secure, path="/")


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def require_user(request: Request) -> str:
    user = verify(request.cookies.get(COOKIE))
    if not user or not (is_admin(user) or _find(user)):  # a deleted account's cookie stops working
        raise HTTPException(401, "Login required.")
    return user


# viewer: look, download, request cleanups/restores, sync
# approver: + approve and cancel jobs
# admin: + settings (incl. dry run) and users
ROLES = ("viewer", "approver", "admin")


def role_of(username: str) -> str:
    if is_admin(username):
        return "admin"
    user = _find(username)
    return user.role if user and user.role in ROLES else "viewer"


def can(username: str, role: str) -> bool:
    return ROLES.index(role_of(username)) >= ROLES.index(role)


def require_role(role: str):
    def dep(request: Request) -> str:
        user = require_user(request)
        if not can(user, role):
            raise HTTPException(403, "Your role doesn't allow this.")
        return user
    return dep


require_approver = require_role("approver")
require_admin = require_role("admin")
