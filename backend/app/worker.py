"""Background worker: periodic sync/backup + running approved jobs.

Run: python -m app.worker
"""
import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import delete, select

from . import settings_store
from .config import settings
from .db import Job, JobLog, SessionLocal, get_state, init_db, set_state, utcnow
from .jira import JiraClient
from .jobs import run_job
from .storage import get_storage

log = logging.getLogger("worker")


def _full_due(session) -> bool:
    last = get_state(session, "last_full_sync")
    if not last:
        return True
    return utcnow() - datetime.fromisoformat(last) >= timedelta(hours=settings.full_reconcile_hours)


def tick(storage, last_cycle: float) -> float:
    with SessionLocal() as s:
        settings_store.load(s)  # pick up changes made on the Settings page
        if not settings_store.jira_configured():
            return last_cycle
        client = JiraClient()
        job = s.scalars(select(Job).where(Job.status == "approved").order_by(Job.id).limit(1)).first()
        if job:
            log.info("Running job %s (%s)", job.id, job.kind)
            run_job(s, client, storage, job)
            return last_cycle

        if time.time() - last_cycle < settings.sync_interval_minutes * 60:
            return last_cycle
        # Run as a job so it shows up (with its log) on the Jobs page and blocks "Sync now" while running.
        job = Job(kind="full_sync" if _full_due(s) else "sync", status="approved", title="Automatic sync",
                  created_by="system", approved_by="system", params={}, attachment_ids=[])
        s.add(job)
        s.commit()
        run_job(s, client, storage, job)
        if job.status == "failed" and "error" in job.result:
            set_state(s, "last_error", f"{utcnow().isoformat()} {job.result['error']}"[:2000])
        else:
            set_state(s, "last_error", None)
            if _quiet(job.result):  # nothing happened: don't fill the Jobs page every interval
                s.execute(delete(JobLog).where(JobLog.job_id == job.id))
                s.delete(job)
        s.commit()
        return time.time()


def _quiet(result: dict) -> bool:
    sy, b = result["sync"], result["backup"]
    return not (sy["new"] or sy["reappeared"] or sy["missing"] or b["ok"] or b["failed"] or b["missing"])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()
    settings.ensure_tmp_dir()
    with SessionLocal() as s:
        settings_store.seed_from_env(s)
        settings_store.load(s)
    storage = get_storage()
    log.info("Worker started (storage=%s, dry_run=%s, interval=%s min)",
             storage.name, settings.dry_run, settings.sync_interval_minutes)
    last_cycle = 0.0
    while True:
        try:
            last_cycle = tick(storage, last_cycle)
        except Exception:  # noqa: BLE001
            log.exception("Worker loop error")
        time.sleep(5)


if __name__ == "__main__":
    main()
