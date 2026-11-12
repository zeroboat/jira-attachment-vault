"""End-to-end sync → backup → cleanup → restore flow and web API, against a fake Jira.

Run: python -m pytest tests -q   (or python tests/test_flow.py)
"""
import hashlib
import io
import os
import sys
import tempfile
from datetime import datetime, timezone

TMP = tempfile.mkdtemp()
os.environ.update({
    "DATABASE_URL": f"sqlite:///{TMP}/vault.db",
    "STORAGE_LOCAL_PATH": f"{TMP}/backup",
    "JIRA_BASE_URL": "https://example.atlassian.net",
    "JIRA_EMAIL": "bot@example.com",
    "JIRA_API_TOKEN": "seed-token",
    "ADMIN_PASSWORD": "pw",
    "DRY_RUN": "false",
    "JIRA_USER_TIMEZONE": "Asia/Seoul",
})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import (ACTIVE, DELETED_BY_VAULT, MISSING_IN_JIRA, RESTORED,  # noqa: E402
                    Attachment, Job, SessionLocal, init_db)
from app.jira import JiraError  # noqa: E402
from app.jobs import Policy, create_cleanup_job, create_restore_job, run_job  # noqa: E402
from app.storage import get_storage  # noqa: E402
from app.sync import backup_pending, build_jql, sync  # noqa: E402


class FakeResp:
    def __init__(self, data: bytes):
        self.data = data

    def iter_content(self, n):
        buf = io.BytesIO(self.data)
        while chunk := buf.read(n):
            yield chunk

    def close(self):
        pass


class FakeJira:
    def __init__(self):
        self.files = {
            "100": b"A" * 5000, "101": b"B" * 300, "102": b"A" * 5000,  # 102 has the same content as 100
            "103": b"inline image", "104": b"gone before backup",
        }
        self.issues = [
            self._issue("10", "OPS-1", "done", [("100", "big.log", "2023-01-01T09:00:00.000+0900"),
                                                 ("103", "screen.png", "2023-01-02T09:00:00.000+0900")]),
            self._issue("11", "OPS-2", "indeterminate", [("101", "notes.txt", "2023-01-01T09:00:00.000+0900")]),
            self._issue("12", "DEV-7", "done", [("102", "copy.log", "2022-06-01T09:00:00.000+0900"),
                                                 ("104", "x.bin", "2022-06-01T09:00:00.000+0900")]),
        ]
        self.deleted, self.uploaded, self.next_id = [], [], 900
        self.comments = []          # (issue_id, adf)
        self.comment_status = None  # set to e.g. 403 to make comments fail
        self.texts = {"10": "see screen !screen.png|thumbnail!", "12": ""}
        self.jql_seen = []

    def _issue(self, iid, key, cat, atts):
        return {"id": iid, "key": key, "fields": {
            "summary": f"{key} summary", "project": {"key": key.split("-")[0]},
            "status": {"name": cat, "statusCategory": {"key": cat}},
            "attachment": [{"id": a, "filename": fn, "created": c, "mimeType": "application/octet-stream",
                            "size": len(self.files[a]) if a in self.files else 0,
                            "author": {"accountId": "u1", "displayName": "홍길동"}} for a, fn, c in atts]}}

    def search_issues(self, jql, fields=None):
        self.jql_seen.append(jql)
        yield from self.issues

    def download_attachment(self, att_id):
        if att_id == "104":  # someone deleted it between sync and backup
            self.delete_attachment(att_id)
            self.deleted.remove(att_id)
            raise JiraError("not found", 404)
        return FakeResp(self.files[att_id])

    def delete_attachment(self, att_id):
        self.deleted.append(att_id)
        for i in self.issues:
            i["fields"]["attachment"] = [a for a in i["fields"]["attachment"] if a["id"] != att_id]

    def add_silent_comment(self, issue_id, adf, internal=True):
        if self.comment_status:
            raise JiraError("forbidden", self.comment_status)
        self.comments.append((issue_id, adf))

    def get_issue_text(self, issue_id):
        return self.texts.get(issue_id, "")

    def upload_attachment(self, issue_id, filename, path, mime):
        with open(path, "rb") as f:
            self.uploaded.append((issue_id, filename, hashlib.sha256(f.read()).hexdigest()))
        self.next_id += 1
        return [{"id": str(self.next_id)}]


def test_full_flow():
    init_db()
    jira, storage = FakeJira(), get_storage()
    with SessionLocal() as s:
        st = sync(s, jira, full=True)
        assert st["new"] == 5, st
        assert 'created >= "2000-01-01"' in jira.jql_seen[-1]

        b = backup_pending(s, jira, storage)
        assert b["ok"] == 4 and b["missing"] == 1, b
        a100, a102 = s.get(Attachment, "100"), s.get(Attachment, "102")
        assert a100.sha256 == a102.sha256 and a100.storage_key == a102.storage_key  # dedup
        assert s.get(Attachment, "104").state == MISSING_IN_JIRA
        assert os.path.exists(os.path.join(storage.root, "manifest/OPS/OPS-1/100.json"))
        objects = [f for _, _, fs in os.walk(os.path.join(storage.root, "objects")) for f in fs]
        assert len(objects) == 3, objects  # 100/102 share content → 3 objects

        # incremental sync JQL uses an updated condition
        sync(s, jira)
        assert "updated >=" in jira.jql_seen[-1]

        # cleanup: done issues + older than 1y → 100, 102, 103; 103 is embedded so skipped
        job = create_cleanup_job(s, Policy(older_than_days=365, only_done=True), "admin")
        assert sorted(job.attachment_ids) == ["100", "102", "103"], job.attachment_ids
        job.status, job.approved_by = "approved", "admin"
        s.commit()
        run_job(s, jira, storage, job)
        assert job.status == "done", job.result
        assert job.result["deleted"] == 2 and job.result["skipped"] == 1, job.result
        assert sorted(jira.deleted) == ["100", "102"]
        # one comment per issue (100 on OPS-1, 102 on DEV-7); skipped 103 is not mentioned
        assert job.result["comments"]["ok"] == 2, job.result
        assert sorted(i for i, _ in jira.comments) == ["10", "12"]
        ops_text = str(dict(jira.comments)["10"])
        assert "big.log" in ops_text and "screen.png" not in ops_text and "#" + str(job.id) in ops_text
        assert s.get(Attachment, "100").state == DELETED_BY_VAULT
        assert s.get(Attachment, "103").state == ACTIVE
        from app.db import JobLog
        events = [(l.event, l.attachment_id) for l in s.query(JobLog).filter_by(job_id=job.id).order_by(JobLog.id)]
        assert events[0][0] == "cleanup_started" and events[-1][0] == "job_done", events
        assert ("skipped", "103") in events and ("deleted", "100") in events
        assert sum(e == "commented" for e, _ in events) == 2, events

        # a corrupted backup prevents deletion
        a101 = s.get(Attachment, "101")
        with open(os.path.join(storage.root, a101.storage_key), "wb") as f:
            f.write(b"corrupted")
        job2 = create_cleanup_job(s, Policy(older_than_days=None, only_done=False, filename_contains="notes"), "admin")
        job2.status = "approved"
        s.commit()
        run_job(s, jira, storage, job2)
        assert job2.result["deleted"] == 0 and "backup_verify_failed" in job2.result["reasons"], job2.result
        assert job2.result["comments"]["ok"] == 0 and len(jira.comments) == 2  # nothing deleted → no comment
        assert "101" not in jira.deleted

        # cleaned-up attachments stay deleted_by_vault after a full reconcile
        sync(s, jira, full=True)
        assert s.get(Attachment, "100").state == DELETED_BY_VAULT

        # restore
        rjob = create_restore_job(s, ["100"], "admin")
        rjob.status = "approved"
        s.commit()
        run_job(s, jira, storage, rjob)
        assert rjob.result["restored"] == 1, rjob.result
        assert rjob.result["comments"]["ok"] == 1 and "big.log" in str(jira.comments[-1][1])
        assert jira.uploaded[0][:2] == ("10", "big.log")
        assert jira.uploaded[0][2] == hashlib.sha256(b"A" * 5000).hexdigest()
        a100 = s.get(Attachment, "100")
        assert a100.state == RESTORED and a100.restored_as_id == "901"
        assert s.query(Job).count() == 3


def test_api():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        assert c.get("/api/dashboard").status_code == 401
        assert c.post("/api/auth/login", json={"username": "admin", "password": "x"}).status_code == 401
        assert c.post("/api/auth/login", json={"username": "admin", "password": "pw"}).status_code == 200
        assert c.get("/api/config").json()["user"] == "admin"
        d = c.get("/api/dashboard").json()
        assert d["freed"]["count"] >= 1 and d["errors"]["count"] == 0, d
        for path in ["/api/attachments", "/api/attachments?backup=yes&q=log&sort=size_desc",
                     "/api/attachments/100", "/api/projects", "/api/jobs", "/api/jobs/1", "/api/audit"]:
            r = c.get(path)
            assert r.status_code == 200, (path, r.status_code, r.text[:300])
        assert c.get("/api/attachments/100").json()["attachment"]["created_at"].endswith(("Z", "+00:00"))
        r = c.post("/api/cleanup/preview", json={"older_than_days": 30, "only_done": False})
        assert r.status_code == 200 and r.json()["count"] >= 1, r.text
        r = c.get("/api/attachments/100/backup")
        assert r.status_code == 200 and r.content == b"A" * 5000
        assert "big.log" in r.headers["content-disposition"]
        r = c.post("/api/cleanup/jobs", json={"older_than_days": 1, "only_done": False})
        assert r.status_code == 200, r.text
        jid = r.json()["id"]
        assert r.json()["attachment_count"] >= 1
        assert c.post(f"/api/jobs/{jid}/approve?lang=fr").status_code == 422
        r = c.post(f"/api/jobs/{jid}/approve?lang=ko").json()
        assert r["status"] == "approved" and r["params"]["lang"] == "ko", r
        assert c.post(f"/api/jobs/{jid}/approve").status_code == 400
        # hand-picked cleanup: only backed-up attachments still in Jira
        assert c.post("/api/cleanup/manual", json={"attachment_ids": []}).status_code == 422
        r = c.post("/api/cleanup/manual", json={"attachment_ids": ["101", "104"]})
        assert r.status_code == 400 and "104" in r.json()["detail"], r.text
        r = c.post("/api/cleanup/manual", json={"attachment_ids": ["101"], "skip_embedded": False})
        assert r.json()["params"]["skip_embedded"] is False, r.text
        r = c.post("/api/cleanup/manual", json={"attachment_ids": ["101", "101"]})
        assert r.status_code == 200 and r.json()["attachment_count"] == 1 and r.json()["status"] == "pending_approval", r.text
        log = c.get("/api/jobs/1/log").json()
        assert log and log[0]["event"] == "cleanup_started", log
        assert c.get(f"/api/jobs/1/log?after={log[-1]['id']}").json() == []
        assert c.post("/api/sync", json={"full": True}).status_code == 200
        assert c.post("/api/sync", json={}).status_code == 409
        assert c.get("/api/settings/storage-check").json() == {"ok": True}
        # settings: token is write-only and stored encrypted; changes are audited
        st = c.get("/api/settings").json()
        assert st["jira_base_url"] == "https://example.atlassian.net" and "jira_api_token" not in st
        r = c.put("/api/settings", json={"jira_api_token": "tok-123", "sync_interval_minutes": 15,
                                         "jira_projects": [" ops ", ""], "dry_run": True})
        assert r.status_code == 200 and r.json()["jira_api_token_set"] and r.json()["jira_projects"] == ["OPS"], r.text
        from app.db import get_state
        with SessionLocal() as s:
            raw = get_state(s, "setting:jira_api_token")
        assert raw.startswith("enc:") and "tok-123" not in raw
        assert c.get("/api/audit").json()[0]["action"] == "settings_changed"
        assert c.put("/api/settings", json={"jira_comment_lang": "fr"}).status_code == 422
        assert c.put("/api/settings", json={"jira_base_url": "http://x"}).status_code == 422
        assert c.put("/api/settings", json={"jira_user_timezone": "Mars/Base"}).status_code == 422
        assert not c.post("/api/settings/test-jira", json={"jira_base_url": "https://evil.example"}).json()["ok"]
        c.put("/api/settings", json={"dry_run": False})
        # password change
        assert c.post("/api/auth/password", json={"current": "nope", "new": "newpass123"}).status_code == 400
        assert c.post("/api/auth/password", json={"current": "pw", "new": "short"}).status_code == 422
        assert c.post("/api/auth/password", json={"current": "pw", "new": "newpass123"}).status_code == 200
        c.post("/api/auth/logout")
        assert c.get("/api/config").status_code == 401
        assert c.post("/api/auth/login", json={"username": "admin", "password": "pw"}).status_code == 401
        assert c.post("/api/auth/login", json={"username": "admin", "password": "newpass123"}).status_code == 200


def test_comment_rules(tmp_path):
    """No comments in dry run; on missing permission the comment is skipped and reported."""
    from app.config import settings
    from app.db import Attachment as A
    jira, storage = FakeJira(), get_storage()
    with SessionLocal() as s:
        s.add(A(id="500", issue_id="50", issue_key="ZZ-1", project_key="ZZ", filename="old.zip", size=10,
                created_at=datetime(2020, 1, 1, tzinfo=timezone.utc), state="active", issue_status_category="done"))
        jira.files["500"] = b"z" * 10
        jira.texts["50"] = ""
        s.commit()

        def run(policy_name):
            job = create_cleanup_job(s, Policy(older_than_days=None, only_done=False, filename_contains=policy_name), "admin")
            job.status = "approved"
            s.commit()
            run_job(s, jira, storage, job)
            return job

        settings.dry_run = True
        try:
            j = run("old.zip")
            assert j.result["dry_run"] and j.result["deleted"] == 1 and j.result["comments"]["ok"] == 0
            assert jira.comments == []
        finally:
            settings.dry_run = False

        jira.comment_status = 403
        j = run("old.zip")
        assert j.status == "done" and j.result["deleted"] == 1, j.result
        assert j.result["comments"]["failed"] == 1 and "Permission" in j.result["comments"]["errors"]["ZZ-1"]
        assert jira.comments == []  # never falls back to a notifying comment


def test_silent_comment_request():
    """Actual HTTP shape: PUT issue edit + notifyUsers=false + update.comment.add (+ JSM internal-note property)."""
    from app.jira import JiraClient
    from app.notice import cleanup_comment
    from app.db import Attachment as A
    c = JiraClient(base_url="https://example.atlassian.net", email="a", token="b")
    sent = {}

    class R:
        status_code = 204
        headers = {}
        text = ""

    def fake_request(method, url, **kw):
        sent.update(method=method, url=url, **kw)
        return R()

    c.s.request = fake_request
    a = A(id="1", issue_id="9", issue_key="X-1", filename="파일.mp4", size=3 * 1024 ** 3,
          created_at=datetime(2024, 1, 2, tzinfo=timezone.utc), author_name="홍길동")
    c.add_silent_comment("9", cleanup_comment([a], 7))
    assert sent["method"] == "PUT" and sent["url"].endswith("/rest/api/3/issue/9")
    assert sent["params"] == {"notifyUsers": "false"}
    add = sent["json"]["update"]["comment"][0]["add"]
    assert add["properties"][0] == {"key": "sd.public.comment", "value": {"internal": True}}
    body = add["body"]
    assert body["type"] == "doc" and body["version"] == 1
    flat = str(body)
    assert "파일.mp4" in flat and "3.0 GB" in flat and "홍길동" in flat and "Cleanup job #7" in flat
    # ADF: Jira rejects empty text nodes
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "text":
                assert n["text"], n
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(body)

    # Korean comment text: per job (approver's UI language) or JIRA_COMMENT_LANG fallback
    assert "정리 작업 #7" in str(cleanup_comment([a], 7, "ko"))
    from app.config import settings
    settings.jira_comment_lang = "ko"
    try:
        assert "정리 작업 #7" in str(cleanup_comment([a], 7))
    finally:
        settings.jira_comment_lang = "en"

    # Jira's own 400 reason is shown
    from app.jira import JiraError
    from app.notice import _reason
    err = JiraError('PUT https://x/rest/api/3/issue/9 -> 400: {"errorMessages":[],"errors":{"commentLevel":"not a member: R"}}', 400)
    assert _reason(err) == "Request rejected: not a member: R"
    assert _reason(JiraError("PUT https://x -> 400: <html>", 400)) == "Request rejected (400)"


def test_jql():
    from app.config import settings
    from datetime import datetime, timezone
    settings.jira_projects = ["OPS", "DEV"]
    jql = build_jql(datetime(2026, 11, 9, 1, 0, tzinfo=timezone.utc))
    assert 'project in ("OPS", "DEV")' in jql and 'updated >= "2026-11-09 10:00"' in jql, jql
    settings.jira_projects = []


if __name__ == "__main__":
    test_full_flow()
    test_api()
    test_comment_rules(None)
    test_silent_comment_request()
    test_jql()
    print("ALL OK")


def test_job_outcome():
    from app.jobs import _outcome
    assert _outcome({"deleted": 3, "failed": 0}) == "done"
    assert _outcome({"deleted": 2, "failed": 1}) == "partial"
    assert _outcome({"deleted": 0, "failed": 2}) == "failed"  # e.g. no Delete all attachments permission
    assert _outcome({"restored": 0, "failed": 0}) == "done"
    assert _outcome({"sync": {}, "backup": {"ok": 0, "failed": 4}}) == "failed"


def test_periodic_sync_is_a_job(monkeypatch):
    """The worker's interval sync runs as a job with a log; a cycle where nothing happened leaves no job."""
    from sqlalchemy import select
    from app import worker
    from app.db import JobLog
    init_db()
    jira = FakeJira()
    jira.files["700"] = b"periodic"  # a file earlier tests haven't backed up
    jira.issues.append(jira._issue("70", "OPS-70", "done", [("700", "p.txt", "2024-01-01T09:00:00.000+0900")]))
    monkeypatch.setattr(worker, "JiraClient", lambda: jira)
    storage = get_storage()
    with SessionLocal() as s:
        before = s.scalar(select(Job.id).order_by(Job.id.desc()).limit(1)) or 0
    with SessionLocal() as s:  # earlier tests leave queued jobs; the worker would run those first
        for j in s.scalars(select(Job).where(Job.status == "approved")):
            j.status = "cancelled"
        s.commit()
    worker.tick(storage, 0.0)
    with SessionLocal() as s:
        jobs = s.scalars(select(Job).where(Job.id > before)).all()
        assert len(jobs) == 1 and jobs[0].title == "Automatic sync" and jobs[0].status == "done"
        events = [r.event for r in s.scalars(select(JobLog).where(JobLog.job_id == jobs[0].id))]
        assert events[0] == "sync_started" and "backed_up" in events and events[-1] == "job_done"
    worker.tick(storage, 0.0)  # nothing new → no job kept
    with SessionLocal() as s:
        assert s.scalar(select(Job.id).order_by(Job.id.desc()).limit(1)) == jobs[0].id
        assert not s.scalars(select(JobLog).where(JobLog.job_id > jobs[0].id)).all()
