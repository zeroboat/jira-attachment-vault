"""Background worker: periodic sync/backup + running approved jobs.

Run: python -m app.worker
"""
import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import select

from . import settings_store
from .config import settings
from .db import Job, SessionLocal, get_state, init_db, set_state, utcnow
from .jira import JiraClient
from .jobs import run_job
from .storage import get_storage
from .sync import backup_pending, sync

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
        try:
            sync(s, client, full=_full_due(s))
            backup_pending(s, client, storage)
            set_state(s, "last_error", None)
        except Exception as exc:  # noqa: BLE001
            s.rollback()
            log.exception("Periodic sync failed")
            set_state(s, "last_error", f"{utcnow().isoformat()} {type(exc).__name__}: {exc}"[:2000])
        s.commit()
        return time.time()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()
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
