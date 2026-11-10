"""Jira Cloud REST API client (API token, Basic auth)."""
import logging
import time
from typing import Callable, Iterator

import requests

from .config import settings

log = logging.getLogger(__name__)


class JiraError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class JiraClient:
    SEARCH_FIELDS = "attachment,status,project,summary,updated"

    def __init__(self, base_url: str | None = None, email: str | None = None,
                 token: str | None = None):
        self.base = (base_url or settings.jira_base_url).rstrip("/")
        if not self.base:
            raise JiraError("JIRA_BASE_URL is not set.")
        self.s = requests.Session()
        self.s.auth = (email or settings.jira_email, token or settings.jira_api_token)
        self.s.headers.update({"Accept": "application/json"})

    # ---- shared request (retries on 429/5xx) ----
    def _request(self, method: str, path: str, *, retries: int = 6,
                 files_factory: Callable[[], dict] | None = None, **kw) -> requests.Response:
        url = path if path.startswith("http") else f"{self.base}{path}"
        kw.setdefault("timeout", 120)
        for attempt in range(retries):
            opened = files_factory() if files_factory else None
            try:
                if opened is not None:
                    kw["files"] = opened
                r = self.s.request(method, url, **kw)
            except requests.RequestException as exc:
                wait = min(2 ** attempt, 60)
                log.warning("%s %s network error (%s), retrying in %ss", method, url, exc, wait)
                time.sleep(wait)
                continue
            finally:
                if opened:
                    for v in opened.values():
                        f = v[1] if isinstance(v, tuple) else v
                        if hasattr(f, "close"):
                            f.close()
            if r.status_code == 429 or r.status_code >= 500:
                retry_after = r.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt, 60)
                log.warning("%s %s -> %s, retrying in %ss", method, url, r.status_code, wait)
                r.close()
                time.sleep(wait)
                continue
            if r.status_code >= 400:
                raise JiraError(f"{method} {url} -> {r.status_code}: {r.text[:500]}", r.status_code)
            return r
        raise JiraError(f"{method} {url}: failed after {retries} retries")

    def myself(self) -> dict:
        """Current account; used by the connection test."""
        return self._request("GET", "/rest/api/3/myself", retries=1).json()

    # ---- search ----
    def search_issues(self, jql: str, fields: str = SEARCH_FIELDS) -> Iterator[dict]:
        """/rest/api/3/search/jql (nextPageToken pagination)."""
        token = None
        while True:
            params = {"jql": jql, "fields": fields, "maxResults": 100}
            if token:
                params["nextPageToken"] = token
            data = self._request("GET", "/rest/api/3/search/jql", params=params).json()
            yield from data.get("issues", [])
            token = data.get("nextPageToken")
            if data.get("isLast") or not token:
                break

    # ---- attachments ----
    def download_attachment(self, attachment_id: str) -> requests.Response:
        """Streaming response. Jira redirects to its media server; requests strips the auth header when the host changes."""
        return self._request("GET", f"/rest/api/3/attachment/content/{attachment_id}",
                             stream=True, allow_redirects=True)

    def delete_attachment(self, attachment_id: str) -> None:
        self._request("DELETE", f"/rest/api/3/attachment/{attachment_id}")

    def upload_attachment(self, issue_id_or_key: str, filename: str, path: str,
                          mime_type: str | None) -> list[dict]:
        r = self._request(
            "POST", f"/rest/api/3/issue/{issue_id_or_key}/attachments",
            headers={"X-Atlassian-Token": "no-check"},
            files_factory=lambda: {"file": (filename, open(path, "rb"),
                                            mime_type or "application/octet-stream")},
        )
        return r.json()

    def add_silent_comment(self, issue_id_or_key: str, adf_body: dict, internal: bool = True) -> None:
        """Add a comment without notifications. The comment API has no notifyUsers option, so it goes through the issue edit API.
        internal=True makes it an internal note in JSM projects, hidden from customers (no effect elsewhere).
        notifyUsers=false requires the Administer Jira or Administer Projects permission."""
        comment: dict = {"body": adf_body}
        if internal:
            comment["properties"] = [{"key": "sd.public.comment", "value": {"internal": True}}]
        self._request("PUT", f"/rest/api/3/issue/{issue_id_or_key}",
                      params={"notifyUsers": "false"},
                      json={"update": {"comment": [{"add": comment}]}})

    def get_issue_text(self, issue_id_or_key: str) -> str:
        """Fetch description and comments as wiki markup (v2), to detect inline !filename! image references."""
        data = self._request("GET", f"/rest/api/2/issue/{issue_id_or_key}",
                             params={"fields": "description,comment"}).json()
        f = data.get("fields") or {}
        parts = [f.get("description") or ""]
        for c in ((f.get("comment") or {}).get("comments") or []):
            parts.append(c.get("body") or "")
        return "\n".join(parts)
