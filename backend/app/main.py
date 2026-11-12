"""JSON API + static serving of the built frontend. Run: uvicorn app.main:app"""
import json
import math
import urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select

from . import auth, settings_store
from .config import settings
from .db import (ACTIVE, DELETED_BY_VAULT, MISSING_IN_JIRA, Attachment,
                 AuditLog, Job, JobLog, SessionLocal, audit, get_state, init_db)
from .jira import JiraClient, JiraError
from .jobs import (Policy, job_progress, candidates_query, candidates_summary,
                   create_cleanup_job, create_manual_cleanup_job, create_restore_job)
from .schemas import (AppConfig, AttachmentDetail, AttachmentOut, AuditOut,
                      CleanupPreview, Dashboard, JobDetail, JobLogOut, JobOut, LoginIn,
                      JiraTestIn, ManualCleanupIn, Page, PasswordIn, PolicyIn, ProjectUsage,
                      SettingsIn, SettingsOut, SyncIn, SyncInfo, Totals)
from .storage import get_storage, make_storage


@asynccontextmanager
async def lifespan(_app):
    init_db()
    with SessionLocal() as s:
        settings_store.seed_from_env(s)
        settings_store.load(s)
    yield


app = FastAPI(title="Jira Attachment Vault API", lifespan=lifespan, docs_url="/api/docs",
              openapi_url="/api/openapi.json", redoc_url=None)


def get_db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


# ---------- auth ----------
public = APIRouter(prefix="/api")


@public.post("/auth/login")
def login(body: LoginIn, response: Response):
    if not auth.check_password(body.username, body.password):
        raise HTTPException(401, "Incorrect username or password.")
    auth.set_cookie(response, body.username)
    return {"ok": True}


@public.post("/auth/logout")
def logout(response: Response):
    auth.clear_cookie(response)
    return {"ok": True}


api = APIRouter(prefix="/api", dependencies=[Depends(auth.require_user)])


@api.get("/config", response_model=AppConfig)
def config(user: str = Depends(auth.require_user)):
    return AppConfig(user=user, dry_run=settings.dry_run, jira_base_url=settings.jira_base_url,
                     timezone=settings.jira_user_timezone, storage_backend=settings.storage_backend,
                     jira_configured=settings_store.jira_configured(), lang=settings.jira_comment_lang)


# ---------- settings ----------
def _settings_out() -> SettingsOut:
    return SettingsOut(**settings_store.public_values(), storage_backend=settings.storage_backend,
                       storage_location=make_storage(settings.storage_backend, check_only=True).describe(),
                       secret_key_ephemeral=settings.secret_key_ephemeral)


@api.get("/settings", response_model=SettingsOut)
def get_settings():
    return _settings_out()


@api.put("/settings", response_model=SettingsOut)
def put_settings(body: SettingsIn, db=Depends(get_db), user: str = Depends(auth.require_user)):
    changed = settings_store.save(db, body.model_dump(exclude_none=True))
    if changed:
        detail = {"keys": changed}
        if "dry_run" in changed:
            detail["dry_run"] = settings.dry_run
        audit(db, user, "settings_changed", detail=detail)
    db.commit()
    return _settings_out()


@api.get("/settings/storage-check")
def storage_check():
    """Local: write+delete a temp file. S3: HEAD the bucket with short timeouts. Never creates the bucket."""
    try:
        make_storage(settings.storage_backend, check_only=True).probe()
    except Exception as exc:  # noqa: BLE001 - any failure is reported, never raised
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    return {"ok": True}


@api.post("/settings/test-jira")
def test_jira(body: JiraTestIn):
    url = body.jira_base_url.strip().rstrip("/")
    if url and url != settings.jira_base_url and not body.jira_api_token:
        # don't send the saved token to a host it wasn't saved for
        return {"ok": False, "error": "Enter the API token to test a different URL."}
    try:
        me = JiraClient(base_url=body.jira_base_url or None, email=body.jira_email or None,
                        token=body.jira_api_token or None).myself()
    except JiraError as exc:
        status = getattr(exc, "status", None)
        reason = {401: "Authentication failed: check the email and API token.",
                  403: "The account has no access.",
                  404: "Not a Jira Cloud site: check the URL.",
                  None: "Could not reach the server: check the URL."}.get(status, str(exc)[:300])
        return {"ok": False, "error": reason}
    return {"ok": True, "account": me.get("displayName") or me.get("emailAddress") or ""}


@api.post("/auth/password")
def change_password(body: PasswordIn, db=Depends(get_db), user: str = Depends(auth.require_user)):
    if not settings_store.check_password(body.current):
        raise HTTPException(400, "Current password is incorrect.")
    settings_store.set_password(db, body.new)
    audit(db, user, "password_changed")
    db.commit()
    return {"ok": True}


# ---------- dashboard ----------
def _totals(db, *conds) -> Totals:
    count, total = db.execute(select(func.count(), func.coalesce(func.sum(Attachment.size), 0))
                              .where(*conds)).one()
    return Totals(count=count, bytes=int(total))


def _json_state(db, key):
    raw = get_state(db, key)
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def _dt_state(db, key):
    raw = get_state(db, key)
    return datetime.fromisoformat(raw) if raw else None


@api.get("/dashboard", response_model=Dashboard)
def dashboard(db=Depends(get_db)):
    stored = db.execute(select(func.coalesce(func.sum(Attachment.size), 0)).where(
        Attachment.id.in_(select(func.min(Attachment.id)).where(Attachment.sha256.is_not(None))
                          .group_by(Attachment.sha256)))).scalar_one()
    by_project = db.execute(
        select(Attachment.project_key, func.count(), func.sum(Attachment.size))
        .where(Attachment.state == ACTIVE).group_by(Attachment.project_key)
        .order_by(func.sum(Attachment.size).desc()).limit(15)).all()
    largest = db.scalars(select(Attachment).where(Attachment.state == ACTIVE)
                         .order_by(Attachment.size.desc()).limit(8)).all()
    return Dashboard(
        active=_totals(db, Attachment.state == ACTIVE),
        backed=_totals(db, Attachment.state == ACTIVE, Attachment.sha256.is_not(None)),
        pending=_totals(db, Attachment.state == ACTIVE, Attachment.sha256.is_(None)),
        errors=_totals(db, Attachment.state == ACTIVE, Attachment.backup_error.is_not(None),
                       Attachment.sha256.is_(None)),
        freed=_totals(db, Attachment.state == DELETED_BY_VAULT),
        missing=_totals(db, Attachment.state == MISSING_IN_JIRA),
        stored_bytes=int(stored),
        by_project=[ProjectUsage(project=p, count=c, bytes=int(s or 0)) for p, c, s in by_project],
        largest=largest,
        sync=SyncInfo(last_sync=_dt_state(db, "last_sync_started"), last_full_sync=_dt_state(db, "last_full_sync"),
                      sync_result=_json_state(db, "last_sync_result"),
                      backup_result=_json_state(db, "last_backup_result"),
                      last_error=get_state(db, "last_error")),
        pending_jobs=db.scalar(select(func.count()).where(Job.status == "pending_approval")),
    )


# ---------- attachments ----------
SORTS = {
    "created_desc": Attachment.created_at.desc(), "created_asc": Attachment.created_at.asc(),
    "size_desc": Attachment.size.desc(), "size_asc": Attachment.size.asc(),
}


@api.get("/attachments", response_model=Page)
def list_attachments(q: str = "", project: str = "", state: str = "", backup: str = "",
                     sort: str = "created_desc", page: int = Query(1, ge=1),
                     page_size: int = Query(50, ge=1, le=200), db=Depends(get_db)):
    stmt = select(Attachment)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Attachment.filename.ilike(like), Attachment.issue_key.ilike(like),
                              Attachment.issue_summary.ilike(like), Attachment.author_name.ilike(like)))
    if project:
        stmt = stmt.where(Attachment.project_key == project)
    if state:
        stmt = stmt.where(Attachment.state == state)
    if backup == "yes":
        stmt = stmt.where(Attachment.sha256.is_not(None))
    elif backup == "no":
        stmt = stmt.where(Attachment.sha256.is_(None))
    elif backup == "error":
        stmt = stmt.where(Attachment.state == ACTIVE, Attachment.backup_error.is_not(None),
                          Attachment.sha256.is_(None))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    pages = max(1, math.ceil(total / page_size))
    page = min(page, pages)
    items = db.scalars(stmt.order_by(SORTS.get(sort, SORTS["created_desc"]), Attachment.id)
                       .offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=items, total=total, page=page, pages=pages)


@api.get("/projects", response_model=list[str])
def projects(db=Depends(get_db)):
    return db.scalars(select(Attachment.project_key).distinct().order_by(Attachment.project_key)).all()


@api.get("/attachments/{att_id}", response_model=AttachmentDetail)
def attachment_detail(att_id: str, db=Depends(get_db)):
    obj = db.get(Attachment, att_id)
    if not obj:
        raise HTTPException(404, "Attachment not found.")
    logs = db.scalars(select(AuditLog).where(AuditLog.attachment_id == att_id).order_by(AuditLog.at.desc())).all()
    dups = db.scalars(select(Attachment).where(Attachment.sha256 == obj.sha256, Attachment.id != obj.id)
                      .limit(20)).all() if obj.sha256 else []
    return AttachmentDetail(attachment=obj, logs=logs, duplicates=dups)


@api.get("/attachments/{att_id}/backup")
def download_backup(att_id: str, db=Depends(get_db), user: str = Depends(auth.require_user)):
    obj = db.get(Attachment, att_id)
    if not obj or not obj.storage_key:
        raise HTTPException(404, "No backup exists.")
    audit(db, user, "downloaded_backup", obj)
    db.commit()
    return StreamingResponse(
        get_storage().iter_chunks(obj.storage_key),
        media_type=obj.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(obj.filename)}"},
    )


def job_out(job: Job) -> JobOut:
    out = JobOut.model_validate(job)
    out.attachment_count = len(job.attachment_ids or [])
    return out


@api.post("/attachments/{att_id}/restore", response_model=JobOut)
def request_restore(att_id: str, db=Depends(get_db), user: str = Depends(auth.require_user)):
    obj = db.get(Attachment, att_id)
    if not obj or not obj.storage_key:
        raise HTTPException(400, "Attachments without a backup cannot be restored.")
    if obj.state == ACTIVE:
        raise HTTPException(400, "This attachment is still in Jira.")
    return job_out(create_restore_job(db, [att_id], user))


# ---------- cleanup ----------
@api.post("/cleanup/preview", response_model=CleanupPreview)
def cleanup_preview(body: PolicyIn, db=Depends(get_db)):
    policy = Policy(**body.model_dump())
    summary = candidates_summary(db, policy)
    items = db.scalars(candidates_query(policy).limit(50)).all()
    return CleanupPreview(**summary, items=items)


@api.post("/cleanup/jobs", response_model=JobOut)
def cleanup_create(body: PolicyIn, db=Depends(get_db), user: str = Depends(auth.require_user)):
    policy = Policy(**body.model_dump())
    if candidates_summary(db, policy)["count"] == 0:
        raise HTTPException(400, "No attachments match these rules.")
    return job_out(create_cleanup_job(db, policy, user))


@api.post("/cleanup/manual", response_model=JobOut)
def cleanup_manual(body: ManualCleanupIn, db=Depends(get_db), user: str = Depends(auth.require_user)):
    try:
        return job_out(create_manual_cleanup_job(db, body.attachment_ids, user, body.skip_embedded))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# ---------- jobs ----------
@api.get("/jobs", response_model=list[JobOut])
def list_jobs(status: str = "", db=Depends(get_db)):
    stmt = select(Job).order_by(Job.id.desc()).limit(200)
    if status:
        stmt = stmt.where(Job.status == status)
    return [job_out(j) for j in db.scalars(stmt).all()]


@api.get("/jobs/{job_id}", response_model=JobDetail)
def job_detail(job_id: int, db=Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    ids = job.attachment_ids or []
    total = db.scalar(select(func.coalesce(func.sum(Attachment.size), 0))
                      .where(Attachment.id.in_(ids))) if ids else 0
    return JobDetail(job=job_out(job), total_bytes=int(total or 0),
                     progress=job_progress(db, job.id) if job.status in ("approved", "running") else None)


@api.get("/jobs/{job_id}/items", response_model=Page)
def job_items(job_id: int, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), db=Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    ids = job.attachment_ids or []
    total = len(ids)
    pages = max(1, math.ceil(total / page_size))
    page = min(page, pages)
    items = db.scalars(select(Attachment).where(Attachment.id.in_(ids))
                       .order_by(Attachment.size.desc(), Attachment.id)
                       .offset((page - 1) * page_size).limit(page_size)).all() if ids else []
    return Page(items=items, total=total, page=page, pages=pages)


@api.get("/jobs/{job_id}/log", response_model=list[JobLogOut])
def job_log_list(job_id: int, after: int = 0, limit: int = Query(1000, ge=1, le=5000), db=Depends(get_db)):
    """after=0: the latest `limit` lines (oldest first). after=N: up to `limit` lines following line N."""
    if after:
        return db.scalars(select(JobLog).where(JobLog.job_id == job_id, JobLog.id > after)
                          .order_by(JobLog.id).limit(limit)).all()
    return list(reversed(db.scalars(select(JobLog).where(JobLog.job_id == job_id)
                                    .order_by(JobLog.id.desc()).limit(limit)).all()))


@api.post("/jobs/{job_id}/approve", response_model=JobOut)
def job_approve(job_id: int, lang: str = Query("", pattern="^(en|ko)?$"), db=Depends(get_db),
                user: str = Depends(auth.require_user)):
    job = db.get(Job, job_id)
    if not job or job.status != "pending_approval":
        raise HTTPException(400, "This job cannot be approved in its current state.")
    job.status, job.approved_by = "approved", user
    if lang:  # notice comments follow the approver's UI language
        job.params = {**(job.params or {}), "lang": lang}
    audit(db, user, f"{job.kind}_approved", detail={"job": job.id})
    db.commit()
    return job_out(job)


@api.post("/jobs/{job_id}/cancel", response_model=JobOut)
def job_cancel(job_id: int, db=Depends(get_db), user: str = Depends(auth.require_user)):
    job = db.get(Job, job_id)
    if not job or job.status not in ("pending_approval", "approved"):
        raise HTTPException(400, "This job cannot be cancelled in its current state.")
    job.status = "cancelled"
    audit(db, user, f"{job.kind}_cancelled", detail={"job": job.id})
    db.commit()
    return job_out(job)


@api.post("/sync", response_model=JobOut)
def sync_now(body: SyncIn, db=Depends(get_db), user: str = Depends(auth.require_user)):
    running = db.scalar(select(func.count()).where(Job.kind.in_(["sync", "full_sync"]),
                                                   Job.status.in_(["approved", "running"])))
    if running:
        raise HTTPException(409, "A sync is already queued or running.")
    if not settings_store.jira_configured():
        raise HTTPException(400, "Set up the Jira connection in Settings first.")
    kind = "full_sync" if body.full else "sync"
    job = Job(kind=kind, status="approved", approved_by=user, created_by=user,
              title="Full sync" if body.full else "Sync now", params={}, attachment_ids=[])
    db.add(job)
    db.commit()
    return job_out(job)


@api.get("/audit", response_model=list[AuditOut])
def audit_log(limit: int = Query(300, ge=1, le=2000), action: str = "", db=Depends(get_db)):
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    return db.scalars(stmt).all()


app.include_router(public)
app.include_router(api)


# ---------- frontend (build output) ----------
_dist = Path(settings.frontend_dist) if settings.frontend_dist else None
if _dist and (_dist / "index.html").is_file():
    if (_dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = (_dist / path).resolve()
        if path and f.is_file() and _dist.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(_dist / "index.html")
