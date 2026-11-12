# Jira Attachment Vault

**English** · [한국어](README.ko.md)

A standalone web tool that **backs up Jira Cloud attachments to your own server** and frees Jira storage by deleting old or large attachments **only after their backup has been verified**.

- **Sync**: every 30 minutes, attachment lists of changed issues are written to the DB. Once a day a full reconcile finds attachments that disappeared from Jira.
- **Backup**: new attachments are downloaded and stored by sha256. Identical files are stored once.
- **Cleanup**: preview targets by rules (age, size, project, done issues, file type), or hand-pick attachments on the Attachments page, create a job, and it runs **only after approval**.
- **Restore**: re-upload cleaned-up attachments to their original issue.
- **Job log**: every job keeps a step-by-step log (per file: backed up, deleted, skipped and why, failed, notice comments).
- **Audit log**: who did what, and when.
- **Language**: the UI is English by default. Switch to Korean on the Settings page or from the user menu (top right). The choice is saved on the server, so every browser follows it. Before logging in, the login page uses the browser's language (or the switch below the form).

## Stack

| Area | Tech |
|---|---|
| Frontend | React 19 + TypeScript + Vite, Tailwind CSS v4 + shadcn/ui, TanStack Query, React Router |
| Backend | Python 3.12 + FastAPI (JSON API, docs at `/api/docs`), SQLAlchemy 2 |
| DB | PostgreSQL 16 |
| Runtime | Docker Compose |

```
jira-attachment-vault/
├── frontend/                 React app
│   └── src/
│       ├── pages/            dashboard, attachments, cleanup, jobs, audit, settings, login
│       ├── components/ui/    shadcn/ui components
│       ├── components/       layout, shared components
│       ├── lib/api.ts        API types and calls
│       └── lib/i18n.ts       UI strings (English · Korean)
├── backend/
│   ├── app/
│   │   ├── main.py           JSON API + serves the built frontend
│   │   ├── auth.py           cookie session login
│   │   ├── settings_store.py settings saved from the web UI (DB)
│   │   ├── schemas.py        API request/response models
│   │   ├── sync.py           Jira → DB sync, backup
│   │   ├── jobs.py           cleanup/restore jobs and safeguards
│   │   ├── notice.py         silent notice comments on issues
│   │   ├── worker.py         background worker
│   │   ├── jira.py           Jira Cloud API client
│   │   ├── storage.py        backup storage (local / seaweedfs / s3)
│   │   ├── copy_storage.py   copy between storages (when switching)
│   │   └── db.py, config.py
│   └── tests/
├── Dockerfile                frontend build → bundled into backend image (multi-stage)
└── docker-compose.yml        web · worker · db (+ SeaweedFS profile)
```

```
docker compose
├── web     API + UI (same port)                    :8080
├── worker  sync · backup · runs approved jobs
└── db      PostgreSQL (metadata, jobs, audit log)
Vault folder (VAULT_DIR) → /vault in the container
```

Layout inside the backup storage:

```
objects/ab/cd/<sha256>                       file content (content-addressed, deduplicated)
manifest/<PROJECT>/<ISSUE-KEY>/<id>.json     original filename, issue, uploader, upload date, sha256
```

Thanks to `manifest/`, **even if the DB is lost** the backup alone tells you which file belonged to which issue.

## Install

1. **Prepare a Jira API account.** A dedicated backup account is recommended.
   - Permissions on target projects: *Browse projects*, *Create attachments* (restore), *Delete all attachments* (cleanup),
     *Administer Projects* (silent notice comments, see below)
   - Give it a recognizable display name such as "Attachment Vault" so its comments are easy to identify.
   - Create a token: https://id.atlassian.com/manage-profile/security/api-tokens
   - Note the account's Jira profile timezone; you'll enter the same one on the Settings page. Incremental sync date conditions are interpreted in it.

2. **Pick a storage mode and prepare disks.** See [Choosing storage](#choosing-storage).
   ```bash
   # Vault folder: attachment copies in local mode, temp files in other modes
   sudo mkdir -p /mnt/vault-disk/jira-attachments
   sudo chown 1000:1000 /mnt/vault-disk/jira-attachments   # the app container runs as uid 1000
   ```
   On macOS with Docker Desktop or rootless Podman, `chown` has no effect inside the VM; use `chmod 777` on the folder instead
   (fine for a local trial, not for a shared server).

3. **Create the config file.**
   ```bash
   cp .env.example .env
   # fill in VAULT_DIR, POSTGRES_PASSWORD, SECRET_KEY, ADMIN_PASSWORD
   ```

4. **Run.**
   ```bash
   docker compose up -d --build                       # local mode
   docker compose --profile seaweedfs up -d --build   # seaweedfs mode
   docker compose logs -f worker
   ```
   Open `http://<server>:8080` and log in as `admin`. You'll land on **Settings**: enter the Jira URL, email and API token,
   press **Test connection**, and save. Then press **Sync now** on the dashboard to start the first full backup. With many attachments it can take hours. Jira Cloud rate limits (429) are waited out automatically.

## Configuration

**Settings page (stored in the DB).** Jira connection (URL, email, API token, projects, extra JQL, timezone),
notice comments (on/off), sync intervals, dry run, and the admin password are changed in the web UI.
Changes apply without a restart and are recorded in the Audit log. The API token is encrypted with `SECRET_KEY`
and never sent back to the browser.

**`.env` (server and infrastructure).** `.env.example` lists the required values. Optional:

| Variable | Default | Description |
|---|---|---|
| `STORAGE_BACKEND` | `local` | `local`, `seaweedfs` or `s3` (see below) |
| `WEB_PORT` | `8080` | Port the web UI listens on |
| `ADMIN_USER` | `admin` | Login username |
| `SESSION_HOURS` | `12` | Login session lifetime |
| `COOKIE_SECURE` | `false` | Set `true` behind an HTTPS reverse proxy |
| `DB_DIR` | `./data/postgres` | PostgreSQL data directory |
| `TZ` | `UTC` | Timezone for container logs, e.g. `Asia/Seoul`. The web UI and Jira comments use the Settings page timezone |
| `S3_ACCESS_KEY`, `S3_SECRET_KEY` | | Required for `seaweedfs` / `s3` |
| `S3_BUCKET` | `jira-attachments` | Bucket name |
| `S3_PREFIX` | | Optional key prefix inside the bucket |
| `S3_ENDPOINT_URL` | seaweedfs: `http://seaweedfs-filer:8333` | Endpoint for S3-compatible storage |
| `S3_REGION` | `us-east-1` | Region |
| `COMPOSE_PROFILES` | | Set `seaweedfs` so plain `docker compose up -d` starts SeaweedFS too |
| `SEAWEEDFS_SSD_DIR` | `./data/seaweedfs-ssd` | SSD path for master/filer metadata |
| `SEAWEEDFS_HDD_DIR` | `./data/seaweedfs-hdd` | HDD path for file content |
| `SEAWEEDFS_TAG` | `latest` | SeaweedFS image tag. Pin a version in production |
| `SEAWEEDFS_REPLICATION` | `000` | `000` = no replication |
| `SEAWEEDFS_VOLUME_SIZE_MB` | `30000` | Size limit of one SeaweedFS volume file |

## Choosing storage

Pick with one line, `STORAGE_BACKEND` in `.env`. The code and the stored layout (`objects/`, `manifest/`) are the same.

| | `local` (disk) | `seaweedfs` |
|---|---|---|
| Services | app + DB | app + DB + SeaweedFS (master · volume · filer) |
| Where files live | plain files in `VAULT_DIR` | inside SeaweedFS volume files (`.dat`) on HDD |
| Pros | Simple. Open files directly, copy with rsync | S3 API usable by other systems. Easier to add servers/disks later |
| Caveats | A single disk needs failure protection (RAID1/ZFS mirror) | More services to run. Back it up via the S3 API (below) |
| Run | `docker compose up -d` | `docker compose --profile seaweedfs up -d` |

### local
```bash
STORAGE_BACKEND=local
VAULT_DIR=/mnt/vault-disk/jira-attachments
```

### seaweedfs (SSD + HDD)
Master and filer metadata go on SSD, file content (volumes) on HDD. S3 requests go through the filer, so the SSD helps most there.
```bash
STORAGE_BACKEND=seaweedfs
COMPOSE_PROFILES=seaweedfs            # with this, plain `docker compose up -d` starts SeaweedFS too
SEAWEEDFS_SSD_DIR=/mnt/ssd/seaweedfs  # → master/, filer/ subfolders are created
SEAWEEDFS_HDD_DIR=/mnt/hdd1/seaweedfs
SEAWEEDFS_TAG=latest                  # pin a version in production
S3_ACCESS_KEY=any-long-string
S3_SECRET_KEY=any-long-string
```
- The S3 account is created from these values, and the bucket (`S3_BUCKET`) is created on first app start.
- Admin UIs are bound to localhost only: master `http://127.0.0.1:9333`, file browser `http://127.0.0.1:8888`.
- Default replication is `000` (none). Losing an HDD loses its files, so mirror two HDDs (RAID1 or ZFS) and point `SEAWEEDFS_HDD_DIR` at that.

### Switching (local ↔ seaweedfs)
Copy existing backups to the new storage, then change the setting. Existing files are skipped, so it's safe to run repeatedly, and the source is never deleted.
```bash
# 1) Start SeaweedFS first (set SEAWEEDFS_*, S3_* in .env)
docker compose --profile seaweedfs up -d seaweedfs-master seaweedfs-volume seaweedfs-filer
# 2) See what would move → copy (every file's sha256 is re-checked)
docker compose run --rm worker python -m app.copy_storage --from local --to seaweedfs --dry-run
docker compose run --rm worker python -m app.copy_storage --from local --to seaweedfs
# 3) Set STORAGE_BACKEND=seaweedfs in .env and restart
docker compose --profile seaweedfs up -d
```
The reverse direction (`--from seaweedfs --to local`) works the same way.

## Starting cleanup safely

1. With dry run on (the default; toggle on the Settings page), create and approve a cleanup job. Nothing is deleted; only **what would have been deleted** is logged.
2. Review the job result, its log, and the Audit log page.
3. If it looks right, turn dry run off on the Settings page. It takes effect immediately.

A cleanup job processes each attachment in this order:
1. Back it up first if there is no backup.
2. **Re-read the stored file in full and verify its sha256.** Skip on mismatch.
3. Skip images embedded in descriptions/comments as `!filename!` (on by default; can be turned off per job), since deleting them shows "preview unavailable" in Jira.
4. Delete it from Jira.

## Jira notice comments (silent)

Issues whose attachments were **actually deleted** by cleanup, or **restored**, get one notice comment per issue, so people asking "where did my attachment go?" find the answer in the issue itself.
Comments are written in the UI language of the person who approved the job (English or Korean).

> 🗄️ **Attachment archive notice** (automated)
> The 2 attachment(s) below (3.6 GB) were moved to the internal archive to free up Jira storage. Ask an administrator if you need them restored.
> | File | Size | Uploaded | Uploader |
> |---|---|---|---|
> | recording_7.mp4 | 2.2 GB | 2024-12-29 | Jane Doe |
> | heapdump-26.hprof | 1.4 GB | 2025-03-10 | John Roe |
>
> Cleanup job #4 · 2026-11-09 21:10 · Archive IDs `10103, 10141`

- **No Jira notifications are sent.** The Jira Cloud comment API can't suppress notifications, so the comment is sent through the issue edit API (`PUT /rest/api/3/issue/{key}?notifyUsers=false`). This requires **Administer Projects** (or Administer Jira) on the API account.
- **Without that permission the comment is skipped**, never posted in a way that notifies people. The job result and log show "Permission denied".
- No web link is included, only a note to ask an administrator.
- Not posted in dry run, nor for backups.
- In JSM projects the comment is requested as an internal note, hidden from customers.
- Turn them on/off on the Settings page. If a comment fails, the job log shows Jira's reason.
- **Jira Cloud for Slack still notifies.** The Slack app ignores `notifyUsers=false`, so Slack subscribers may get both the comment and the attachment change. There is no API to mute it; adjust the Slack subscription (`/jira manage`, `/jira notify`) if needed.

**Verify once before relying on it.** Notifications depend on each project's notification scheme, so test in a test project:
1. Upload a large attachment to a test issue and add yourself as a watcher.
2. With dry run off, select only that attachment on the Attachments page, create a delete job and approve it.
3. Check email/Jira notifications.
   - There should be **no comment notification**.
   - An **attachment deletion notification may arrive.** The delete API has no option to suppress it; it follows the "Issue Updated" event in the notification scheme.
   - If Jira Cloud for Slack is connected, Slack notifications arrive regardless (see above).
4. For JSM projects, also check the comment isn't visible on the customer portal (internal note).

## Backing up the backup

Files deleted from Jira by cleanup exist **only in this storage**. Keep a second copy regardless of storage mode.

**local mode**: content-addressed storage only adds new files and never modifies existing ones, so `rsync` fits well.
```bash
# crontab example: daily at 03:00
0 3 * * * rsync -a /mnt/vault-disk/jira-attachments/ nas:/backups/jira-attachments/
```

**seaweedfs mode**: rsyncing the `.dat` volume files can copy them mid-write and corrupt the copy. Copy through the S3 API instead.
```bash
# Dump plain files to a NAS-mounted folder with the app's copy tool (point the local path at the NAS)
docker compose run --rm -e STORAGE_LOCAL_PATH=/nas -v /mnt/nas/jira:/nas worker \
  python -m app.copy_storage --from seaweedfs --to local
# or: rclone sync seaweed:jira-attachments /mnt/nas/jira  (needs an rclone S3 remote)
```

Dump the **DB** daily too. You can recover from `manifest/` without it, but a dump is much faster.
```bash
docker compose exec -T db pg_dump -U vault vault | gzip > /mnt/vault-disk/db-$(date +%F).sql.gz
```

## Other S3-compatible storage

Set `STORAGE_BACKEND=s3` with `S3_ENDPOINT_URL` and `S3_*` to store in AWS S3, Cloudflare R2, Garage, etc. Migrate with `copy_storage` as above (`--to s3`).

## Known limitations

- **Restoring changes the uploader and upload time** to the API account and restore time (Jira API constraint). The originals stay in this tool's DB and manifest.
- A restored attachment gets a new id in Jira. It shows up as a new entry on the next sync and, having the same content, uses no extra disk.
- Full reconcile only looks within the current scope (Projects and Extra JQL on the Settings page). Narrowing the scope marks attachments outside it as "Gone from Jira" (backups are kept).
- Login is a single admin account (signed HttpOnly cookie session). Keep it on the internal network; to expose it, put a reverse proxy with SSO in front.
- API error messages from the backend are in English regardless of the UI language.

## Design

Design tokens are mapped onto shadcn/ui variable names in `frontend/src/index.css`. The font is Wanted Sans (OFL).

## Development

Run backend and frontend separately; the frontend dev server proxies `/api` to the backend.

```bash
# Backend (terminal 1) — empty DATABASE_URL uses SQLite
cd backend
pip install -r requirements.txt httpx pytest "moto[server]"
ADMIN_PASSWORD=dev JIRA_BASE_URL=https://your-company.atlassian.net uvicorn app.main:app --reload --port 8000

# Frontend (terminal 2)
cd frontend
npm install
npm run dev            # http://localhost:5173

# Worker (terminal 3, with a Jira token)
cd backend && python -m app.worker
```

Tests and build:
```bash
cd backend && python -m pytest tests -q     # fake Jira + fake S3: sync→backup→cleanup→restore, API, storage copy
cd frontend && npm run build                # type check + build
```

### Adding a UI language

UI strings live in `frontend/src/lib/i18n.ts`. Add a dictionary typed as `Record<Key, string>` (TypeScript flags any missing key) and register it in `LANGS`.

## License

[MIT](LICENSE)
