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


def check_password(username: str, password: str) -> bool:
    if not settings.admin_password and not settings.admin_password_hash:
        raise HTTPException(500, "ADMIN_PASSWORD is not set on the server.")
    ok_user = secrets.compare_digest(username.encode(), settings.admin_user.encode())
    return settings_store.check_password(password) and ok_user


def set_cookie(response: Response, username: str) -> None:
    response.set_cookie(COOKIE, issue(username), max_age=settings.session_hours * 3600,
                        httponly=True, samesite="strict", secure=settings.cookie_secure, path="/")


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def require_user(request: Request) -> str:
    user = verify(request.cookies.get(COOKIE))
    if not user:
        raise HTTPException(401, "Login required.")
    return user
