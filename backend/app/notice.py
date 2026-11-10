"""Leave a silent comment on Jira issues whose attachments were cleaned up or restored.

The Jira Cloud comment API cannot suppress notifications, so the comment is sent through the
issue edit API (PUT /rest/api/3/issue/{key}?notifyUsers=false) as update.comment.add.
The API account needs Administer Jira, or Administer Projects on that project.

If notifications can't be suppressed (e.g. missing permission), the comment is skipped rather
than posted in a way that notifies people.

Comment language: the approver's UI language (saved on the job at approval);
JIRA_COMMENT_LANG (default en) is the fallback.
"""
import logging
from collections import OrderedDict
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import settings
from .db import Attachment, as_utc, audit, job_log, utcnow
from .jira import JiraClient, JiraError

log = logging.getLogger(__name__)


# ---------- ADF (Atlassian Document Format) pieces ----------
def _text(t: str, strong: bool = False, code: bool = False) -> dict:
    node = {"type": "text", "text": t or "-"}
    marks = ([{"type": "strong"}] if strong else []) + ([{"type": "code"}] if code else [])
    if marks:
        node["marks"] = marks
    return node


def _para(*nodes: dict) -> dict:
    return {"type": "paragraph", "content": list(nodes)}


def _cell(t: str, header: bool = False) -> dict:
    return {"type": "tableHeader" if header else "tableCell", "attrs": {},
            "content": [_para(_text(t))]}


def _table(header: list[str], rows: list[list[str]]) -> dict:
    return {
        "type": "table",
        "attrs": {"isNumberColumnEnabled": False, "layout": "default"},
        "content": [{"type": "tableRow", "content": [_cell(h, True) for h in header]}]
        + [{"type": "tableRow", "content": [_cell(c) for c in row]} for row in rows],
    }


def _doc(*content: dict) -> dict:
    return {"type": "doc", "version": 1, "content": list(content)}


def human_size(n: int | None) -> str:
    v = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024 or unit == "TB":
            return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} TB"


def _local(dt: datetime | None, with_time: bool = False) -> str:
    dt = as_utc(dt)
    if dt is None:
        return "-"
    return dt.astimezone(ZoneInfo(settings.jira_user_timezone)).strftime("%Y-%m-%d %H:%M" if with_time else "%Y-%m-%d")


TEXT = {
    "en": {
        "auto": " (automated)",
        "cleanup_title": "🗄️ Attachment archive notice",
        "cleanup_body": "The {n} attachment(s) below ({size}) were moved to the internal archive to free up Jira storage. "
                        "Ask an administrator if you need them restored.",
        "cols": ["File", "Size", "Uploaded", "Uploader"],
        "cleanup_footer": "Cleanup job #{job} · {now} · Archive IDs ",
        "restore_title": "🗄️ Attachment restore notice",
        "restore_body": "Re-uploaded attachments from the archive: {names}",
        "restore_footer": "Restore job #{job} · {now} · Uploader and upload time show the restoring account and time.",
    },
    "ko": {
        "auto": " (자동 작성)",
        "cleanup_title": "🗄️ 첨부파일 보관 안내",
        "cleanup_body": "아래 첨부파일 {n}개({size})는 Jira 용량 정리를 위해 사내 보관소로 옮겨졌어요. "
                        "필요하면 관리자에게 복원을 요청하세요.",
        "cols": ["파일", "크기", "업로드", "업로더"],
        "cleanup_footer": "정리 작업 #{job} · {now} · 보관소 ID ",
        "restore_title": "🗄️ 첨부파일 복원 안내",
        "restore_body": "보관소에 있던 첨부파일을 다시 올렸어요: {names}",
        "restore_footer": "복원 작업 #{job} · {now} · 업로더와 업로드 시각은 복원 계정·시점으로 표시돼요.",
    },
}


def _t(lang: str | None = None) -> dict:
    return TEXT.get(lang or settings.jira_comment_lang, TEXT["en"])


def cleanup_comment(items: list[Attachment], job_id: int, lang: str | None = None) -> dict:
    total = sum(a.size or 0 for a in items)
    rows = [[a.filename, human_size(a.size), _local(a.created_at), a.author_name or "-"] for a in items]
    t = _t(lang)
    return _doc(
        _para(_text(t["cleanup_title"], strong=True), _text(t["auto"])),
        _para(_text(t["cleanup_body"].format(n=len(items), size=human_size(total)))),
        _table(t["cols"], rows),
        _para(_text(t["cleanup_footer"].format(job=job_id, now=_local(utcnow(), True))),
              _text(", ".join(a.id for a in items), code=True)),
    )


def restore_comment(items: list[tuple[Attachment, str | None]], job_id: int,
                    lang: str | None = None) -> dict:
    names = ", ".join(a.filename for a, _ in items)
    t = _t(lang)
    return _doc(
        _para(_text(t["restore_title"], strong=True), _text(t["auto"])),
        _para(_text(t["restore_body"].format(names=names))),
        _para(_text(t["restore_footer"].format(job=job_id, now=_local(utcnow(), True)))),
    )


# ---------- posting ----------
def _reason(exc: Exception) -> str:
    status = getattr(exc, "status", None)
    if status in (401, 403):
        return "Permission denied (silent comments need Administer Projects)"
    if status == 404:
        return "Issue not found"
    if status == 400:
        return "Request rejected (400)"
    return f"Error: {type(exc).__name__}"


def post_notices(session, client: JiraClient, groups: "OrderedDict[str, tuple[str, dict]]",
                 actor: str, job_id: int) -> dict:
    """groups: issue_id -> (issue_key, ADF body). One silent comment per issue."""
    res = {"enabled": settings.jira_comment, "ok": 0, "failed": 0, "errors": {}}
    if not settings.jira_comment or not groups:
        return res
    for issue_id, (issue_key, body) in groups.items():
        try:
            client.add_silent_comment(issue_id, body)
            res["ok"] += 1
            audit(session, actor, "issue_commented", detail={"job": job_id, "issue_key": issue_key})
            job_log(session, job_id, "commented", issue=issue_key)
        except JiraError as exc:
            res["failed"] += 1
            res["errors"][issue_key] = _reason(exc)
            job_log(session, job_id, "comment_failed", level="warn", issue=issue_key, error=_reason(exc))
            log.warning("Comment failed %s: %s", issue_key, exc)
        session.commit()
    return res
