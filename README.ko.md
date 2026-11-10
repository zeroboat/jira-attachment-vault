# Jira Attachment Vault

[English](README.md) · **한국어**

Jira Cloud 첨부파일을 **사내 서버 하드디스크에 백업**하고, 오래되거나 큰 첨부를 **백업을 확인한 뒤에만** Jira에서 정리하는 독립 웹 도구입니다.

- **동기화**: 30분마다 바뀐 이슈의 첨부 목록을 DB에 반영하고, 하루 한 번 전체 대조로 Jira에서 사라진 첨부를 찾아요.
- **백업**: 새 첨부를 내려받아 sha256으로 저장해요. 같은 파일은 한 번만 저장돼요.
- **정리**: 조건(업로드 경과일, 크기, 프로젝트, 완료 이슈, 형식)으로 대상을 미리 보고, 작업을 만들고, **승인해야** 실행돼요.
- **복원**: 정리된 첨부를 원래 이슈에 다시 올려요.
- **기록**: 누가 무엇을 언제 했는지 모두 남겨요.
- **언어**: 화면은 영어가 기본이고, 오른쪽 위 사용자 메뉴(또는 로그인 화면 아래)에서 한국어로 바꿀 수 있어요. 선택은 브라우저에 저장돼요.

## 구성

| 영역 | 기술 |
|---|---|
| 프런트 | React 19 + TypeScript + Vite, Tailwind CSS v4 + shadcn/ui, TanStack Query, React Router |
| 백엔드 | Python 3.12 + FastAPI (JSON API, `/api/docs`에 API 문서), SQLAlchemy 2 |
| DB | PostgreSQL 16 |
| 실행 | Docker Compose |

```
jira-attachment-vault/
├── frontend/                 React 앱
│   └── src/
│       ├── pages/            화면 (대시보드, 첨부, 정리, 작업, 기록, 로그인)
│       ├── components/ui/    shadcn/ui 컴포넌트
│       ├── components/       레이아웃, 공용 컴포넌트
│       ├── lib/api.ts        API 타입과 호출 함수
│       └── lib/i18n.ts       화면 문구 (영어 · 한국어)
├── backend/
│   ├── app/
│   │   ├── main.py           JSON API + 빌드된 프런트 서빙
│   │   ├── auth.py           쿠키 세션 로그인
│   │   ├── schemas.py        API 요청/응답 모델
│   │   ├── sync.py           Jira → DB 동기화, 디스크 백업
│   │   ├── jobs.py           정리 · 복원 작업과 안전장치
│   │   ├── notice.py         이슈에 남기는 알림 없는 안내 댓글
│   │   ├── worker.py         백그라운드 워커
│   │   ├── jira.py           Jira Cloud API 클라이언트
│   │   ├── storage.py        백업 저장소 (local / seaweedfs / s3)
│   │   ├── copy_storage.py   저장소 간 복사 (방식 바꿀 때)
│   │   └── db.py, config.py
│   └── tests/
├── Dockerfile                프런트 빌드 → 백엔드 이미지에 포함 (멀티 스테이지)
└── docker-compose.yml        web · worker · db (+ SeaweedFS 프로필)
```

```
docker compose
├── web     API + 화면 (같은 포트)                    :8080
├── worker  동기화 · 백업 · 승인된 작업 실행
└── db      PostgreSQL (메타데이터, 작업, 기록)
첨부 보관 폴더 (VAULT_DIR) → 컨테이너의 /vault
```

백업 디스크 안 구조:

```
objects/ab/cd/<sha256>                       파일 본문 (내용 기준 저장, 중복 제거)
manifest/<PROJECT>/<ISSUE-KEY>/<id>.json     원래 파일명·이슈·업로더·업로드일·sha256
```

`manifest`가 있어서 **DB를 잃어도** 어떤 파일이 어느 이슈의 무엇이었는지 백업 디스크만으로 알 수 있어요.

## 설치

1. **Jira API 계정을 준비해요.** 백업 전용 계정을 하나 만들어 쓰는 걸 권장해요.
   - 필요한 권한: 대상 프로젝트의 *Browse projects*, *Create attachments*(복원), *Delete all attachments*(정리),
     *Administer Projects*(알림 없는 안내 댓글, 아래 참고)
   - 계정 표시 이름을 "첨부파일 보관소"처럼 지어 두면 댓글 작성자로 알아보기 쉬워요.
   - 토큰 발급: https://id.atlassian.com/manage-profile/security/api-tokens
   - 계정의 Jira 프로필 시간대를 확인해 두세요(예: `Asia/Seoul`). 설정 화면에 같은 값을 넣어요. 증분 동기화의 날짜 조건이 이 시간대로 해석돼요.

2. **저장 방식을 고르고 디스크를 준비해요.** 아래 [저장 방식 고르기](#저장-방식-고르기)를 보세요.
   ```bash
   # 첨부 보관 폴더: local 모드에서는 첨부 사본, 다른 모드에서는 임시 파일
   sudo mkdir -p /mnt/vault-disk/jira-attachments
   sudo chown 1000:1000 /mnt/vault-disk/jira-attachments   # 앱 컨테이너가 uid 1000으로 실행돼요
   ```
   macOS의 Docker Desktop이나 rootless Podman에서는 `chown`이 VM 안에 반영되지 않아요. 대신 폴더에 `chmod 777`을 주세요
   (로컬에서 시험할 때만. 여러 사람이 쓰는 서버에서는 쓰지 마세요).

3. **설정 파일을 만들어요.**
   ```bash
   cp .env.example .env
   # VAULT_DIR, POSTGRES_PASSWORD, SECRET_KEY, ADMIN_PASSWORD 를 채워요
   ```

4. **실행해요.**
   ```bash
   docker compose up -d --build                       # local 모드
   docker compose --profile seaweedfs up -d --build   # seaweedfs 모드
   docker compose logs -f worker
   ```
   `http://서버:8080`에 `admin`으로 로그인하면 **설정** 화면이 열려요. Jira 주소, 이메일, API 토큰을 넣고
   **연결 테스트**를 누른 뒤 저장하세요. 그다음 대시보드에서 **지금 동기화**를 누르면 첫 전체 백업이 시작돼요. 첨부가 많으면 첫 백업은 몇 시간 걸릴 수 있어요. Jira Cloud 호출 제한(429)에 걸리면 알아서 기다렸다 이어가요.

## 설정

**설정 화면 (DB에 저장).** Jira 연결(주소, 이메일, API 토큰, 프로젝트, 추가 JQL, 시간대), 안내 댓글(켜기/끄기, 언어),
동기화 주기, 시험 모드, 관리자 비밀번호는 웹 화면에서 바꿔요. 재시작 없이 바로 적용되고 기록 화면에 남아요.
API 토큰은 `SECRET_KEY`로 암호화해 저장하고, 브라우저로 다시 보내지 않아요.

자동 설치용으로 `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECTS`, `JIRA_EXTRA_JQL`, `JIRA_USER_TIMEZONE`,
`JIRA_COMMENT`, `JIRA_COMMENT_LANG`, `SYNC_INTERVAL_MINUTES`, `FULL_RECONCILE_HOURS`, `DRY_RUN`을 `.env`에 넣을 수도 있어요.
이 값들은 **처음 시작할 때 한 번만** DB로 옮겨지고, 그 뒤로는 설정 화면의 값이 기준이에요.

**`.env` (서버·인프라).** 필수 값은 `.env.example`에 있어요. 선택 항목:

| 변수 | 기본값 | 설명 |
|---|---|---|
| `STORAGE_BACKEND` | `local` | `local`, `seaweedfs`, `s3` (아래 참고) |
| `WEB_PORT` | `8080` | 웹 화면 포트 |
| `ADMIN_USER` | `admin` | 로그인 아이디 |
| `SESSION_HOURS` | `12` | 로그인 유지 시간 |
| `COOKIE_SECURE` | `false` | HTTPS 리버스 프록시 뒤에 둘 때 `true` |
| `DB_DIR` | `./data/postgres` | PostgreSQL 데이터 경로 |
| `S3_ACCESS_KEY`, `S3_SECRET_KEY` | | `seaweedfs` / `s3` 모드에서 필수 |
| `S3_BUCKET` | `jira-attachments` | 버킷 이름 |
| `S3_ENDPOINT_URL` | seaweedfs: `http://seaweedfs-filer:8333` | S3 호환 저장소 주소 |
| `S3_REGION` | `us-east-1` | 리전 |
| `COMPOSE_PROFILES` | | `seaweedfs`로 두면 `docker compose up -d`만으로 SeaweedFS도 함께 떠요 |
| `SEAWEEDFS_SSD_DIR` | `./data/seaweedfs-ssd` | master·filer 메타데이터를 둘 SSD 경로 |
| `SEAWEEDFS_HDD_DIR` | `./data/seaweedfs-hdd` | 파일 내용을 둘 HDD 경로 |
| `SEAWEEDFS_TAG` | `latest` | SeaweedFS 이미지 태그. 운영에서는 버전을 고정하세요 |
| `SEAWEEDFS_REPLICATION` | `000` | `000` = 복제 없음 |

## 저장 방식 고르기

`.env`의 `STORAGE_BACKEND` 한 줄로 골라요. 코드는 같고, 저장되는 파일 구조(`objects/`, `manifest/`)도 같아요.

| | `local` (하드디스크) | `seaweedfs` |
|---|---|---|
| 구성 | 앱 + DB | 앱 + DB + SeaweedFS(master · volume · filer) |
| 파일 저장 위치 | `VAULT_DIR` 폴더에 일반 파일로 | HDD의 SeaweedFS 볼륨 파일(`.dat`) 안에 |
| 장점 | 단순함. 파일을 바로 열고 rsync로 복사 가능 | S3 API로 다른 시스템도 함께 쓸 수 있음. 나중에 서버·디스크를 늘리기 쉬움 |
| 주의 | 디스크 하나면 고장 대비 필요 (RAID1/ZFS 미러) | 관리할 서비스가 늘어남. 백업은 S3 API로 떠야 함(아래) |
| 실행 | `docker compose up -d` | `docker compose --profile seaweedfs up -d` |

### local
```bash
STORAGE_BACKEND=local
VAULT_DIR=/mnt/vault-disk/jira-attachments
```

### seaweedfs (SSD + HDD)
master와 filer 메타데이터는 SSD에, 실제 파일 내용(volume)은 HDD에 둬요. S3 요청은 filer를 거치기 때문에 SSD 효과는 filer에서 가장 커요.
```bash
STORAGE_BACKEND=seaweedfs
COMPOSE_PROFILES=seaweedfs            # 이 줄이 있으면 docker compose up -d 만으로 함께 떠요
SEAWEEDFS_SSD_DIR=/mnt/ssd/seaweedfs  # → master/, filer/ 하위 폴더가 생겨요
SEAWEEDFS_HDD_DIR=/mnt/hdd1/seaweedfs
SEAWEEDFS_TAG=latest                  # 운영에서는 버전을 고정하세요
S3_ACCESS_KEY=아무-긴-문자열
S3_SECRET_KEY=아무-긴-문자열
```
- S3 계정은 위 값으로 자동 생성되고, 버킷(`S3_BUCKET`)은 앱이 처음 시작할 때 만들어요.
- 관리 화면은 서버 안에서만 열려요: master `http://127.0.0.1:9333`, 파일 브라우저 `http://127.0.0.1:8888`.
- 기본 복제는 `000`(복제 없음)이에요. HDD 하나가 고장 나면 그 안의 파일을 잃으니, HDD 두 개를 RAID1이나 ZFS 미러로 묶고 그 위를 `SEAWEEDFS_HDD_DIR`로 쓰는 걸 권장해요.

### 방식 바꾸기 (local ↔ seaweedfs)
기존 백업을 새 저장소로 복사한 뒤 설정을 바꿔요. 이미 있는 파일은 건너뛰니 여러 번 돌려도 안전하고, 원본은 지우지 않아요.
```bash
# 1) SeaweedFS를 먼저 띄우고 (.env에 SEAWEEDFS_*, S3_* 설정)
docker compose --profile seaweedfs up -d seaweedfs-master seaweedfs-volume seaweedfs-filer
# 2) 무엇을 옮길지 확인 → 복사 (파일마다 sha256을 다시 확인해요)
docker compose run --rm worker python -m app.copy_storage --from local --to seaweedfs --dry-run
docker compose run --rm worker python -m app.copy_storage --from local --to seaweedfs
# 3) .env 에서 STORAGE_BACKEND=seaweedfs 로 바꾸고 다시 띄우기
docker compose --profile seaweedfs up -d
```
반대 방향(`--from seaweedfs --to local`)도 같은 방법이에요.

## 정리를 안전하게 시작하는 순서

1. 시험 모드가 켜진 상태(기본값, 설정 화면에서 바꿈)로 정리 작업을 만들고 승인해요. 실제로 지우지 않고 **무엇을 지웠을지**만 기록돼요.
2. 작업 결과와 `기록` 화면을 확인해요.
3. 괜찮으면 설정 화면에서 시험 모드를 꺼요. 바로 적용돼요.

정리 작업은 첨부마다 이 순서로 처리돼요.
1. 백업이 없으면 먼저 백업해요.
2. **백업 디스크의 파일을 끝까지 다시 읽어 sha256을 검증해요.** 불일치하면 건너뛰어요.
3. 본문·댓글에 `!파일명!`으로 삽입된 이미지는 건너뛰어요(옵션). 지우면 Jira 화면에 "미리보기 불가"가 뜨기 때문이에요.
4. Jira에서 삭제해요.

## Jira 안내 댓글 (알림 없음)

정리로 첨부를 **실제로 지운** 이슈와 **복원한** 이슈에 안내 댓글을 이슈당 하나씩 남겨요. 사용자가 "첨부가 어디 갔지?" 할 때 이슈 안에서 바로 알 수 있게요.

> 🗄️ **첨부파일 보관 안내** (자동 작성)
> 아래 첨부파일 2개(3.6 GB)는 Jira 용량 정리를 위해 사내 보관소로 옮겨졌어요. 필요하면 관리자에게 복원을 요청하세요.
> | 파일 | 크기 | 업로드 | 업로더 |
> |---|---|---|---|
> | 녹화_7.mp4 | 2.2 GB | 2024-12-29 | 이서연 |
> | heapdump-26.hprof | 1.4 GB | 2025-03-10 | 강하은 |
>
> 정리 작업 #4 · 2026-11-09 21:10 · 보관소 ID `10103, 10141`

- **알림을 보내지 않아요.** Jira Cloud 댓글 API에는 알림을 끄는 옵션이 없어서, 알림을 끌 수 있는 이슈 수정 API(`PUT /rest/api/3/issue/{key}?notifyUsers=false`)에 댓글을 실어 보내요. 이 방식은 API 계정에 **Administer Projects**(또는 Administer Jira) 권한이 있어야 동작해요.
- **권한이 없으면 건너뛰어요.** 알림이 나가는 방식으로 대신 쓰지 않고, 작업 결과에 "권한 부족"으로 표시해요.
- 웹 링크는 넣지 않아요. 관리자에게 요청하라는 문구만 넣어요.
- 시험 모드에서는 쓰지 않아요. 백업만 할 때도 쓰지 않아요.
- JSM 프로젝트에서는 고객에게 보이지 않는 내부 메모로 남기도록 요청해요.
- 켜기/끄기와 언어(영어/한국어)는 설정 화면에서 정해요.

**처음 한 번 꼭 확인하세요.** 알림은 프로젝트의 알림 체계 설정에 따라 달라서, 테스트 프로젝트에서 직접 확인하는 게 확실해요.
1. 테스트 이슈에 큰 첨부를 올리고, 본인 계정을 지켜보는 사람(watcher)으로 걸어요.
2. 시험 모드를 끄고 그 이슈만 대상인 정리 작업을 만들어 승인해요(예: 파일명 조건).
3. 메일이나 Jira 알림이 왔는지 확인해요.
   - **댓글 알림**은 오지 않아야 해요.
   - **첨부 삭제 알림**은 올 수 있어요. 첨부 삭제 API에는 알림을 끄는 옵션이 없어서, 알림 체계의 "Issue Updated" 이벤트 설정을 따라요.
4. JSM 프로젝트라면 댓글이 고객 포털에 보이지 않는지(내부 메모인지)도 확인해요.

## 백업의 백업

정리 기능으로 Jira에서 지운 파일은 **이 저장소가 유일한 사본**이 돼요. 저장 방식과 상관없이 두 번째 사본을 꼭 두세요.

**local 모드**: 내용 기준 저장이라 새 파일만 추가되고 기존 파일은 바뀌지 않아요. 그래서 `rsync`가 잘 맞아요.
```bash
# crontab 예시: 매일 03:00
0 3 * * * rsync -a /mnt/vault-disk/jira-attachments/ nas:/backups/jira-attachments/
```

**seaweedfs 모드**: HDD의 `.dat` 볼륨 파일을 rsync로 복사하면 쓰는 중인 파일이 깨질 수 있어요. 대신 S3 API로 복사해요.
```bash
# 앱의 복사 도구로 NAS에 마운트한 폴더에 일반 파일로 떠 두기 (local 경로를 NAS로 지정)
docker compose run --rm -e STORAGE_LOCAL_PATH=/nas -v /mnt/nas/jira:/nas worker \
  python -m app.copy_storage --from seaweedfs --to local
# 또는 rclone sync seaweed:jira-attachments /mnt/nas/jira  (rclone 의 S3 원격 설정 필요)
```

**DB**도 매일 덤프해요. 덤프가 없어도 `manifest/`로 복구할 수 있지만, 덤프가 있으면 훨씬 빨라요.
```bash
docker compose exec -T db pg_dump -U vault vault | gzip > /mnt/vault-disk/db-$(date +%F).sql.gz
```

## 그 밖의 S3 호환 저장소

`STORAGE_BACKEND=s3`과 `S3_ENDPOINT_URL`, `S3_*`를 채우면 AWS S3, Cloudflare R2, Garage 등에도 저장할 수 있어요. 옮기는 방법은 위의 `copy_storage`와 같아요(`--to s3`).

## 알아둘 한계

- **복원하면 업로더와 업로드 시각이** API 계정과 복원 시점으로 바뀌어요(Jira API 제약). 원래 정보는 이 도구의 DB와 manifest에 남아요.
- 복원된 첨부는 Jira에서 새 id를 받아요. 다음 동기화 때 새 항목으로 들어오고, 내용이 같아서 디스크를 더 쓰지 않아요.
- 전체 대조는 현재 설정(`JIRA_PROJECTS`, `JIRA_EXTRA_JQL`) 범위 안만 봐요. 범위를 줄이면 빠진 쪽 첨부가 "Jira에서 사라짐"으로 표시돼요(백업은 그대로 있어요).
- 로그인은 관리자 계정 하나예요(서명된 HttpOnly 쿠키 세션). 사내망에서만 열고, 외부에 노출하려면 앞단에 리버스 프록시와 SSO를 붙이세요.

## 화면 디자인

디자인 토큰은 `frontend/src/index.css`에서 shadcn/ui 변수 이름에 연결돼 있고, 글꼴은 Wanted Sans(OFL)예요.

## 개발

백엔드와 프런트를 따로 띄우고, 프런트 개발 서버가 `/api` 요청을 백엔드로 넘겨줘요.

```bash
# 백엔드 (터미널 1) — DATABASE_URL을 비우면 SQLite를 써요
cd backend
pip install -r requirements.txt httpx pytest "moto[server]"
ADMIN_PASSWORD=dev JIRA_BASE_URL=https://your-company.atlassian.net uvicorn app.main:app --reload --port 8000

# 프런트 (터미널 2)
cd frontend
npm install
npm run dev            # http://localhost:5173

# 워커 (터미널 3, Jira 토큰이 있을 때)
cd backend && python -m app.worker
```

테스트와 빌드 확인:
```bash
cd backend && python -m pytest tests -q     # 가짜 Jira·가짜 S3로 동기화→백업→정리→복원, API, 저장소 복사
cd frontend && npm run build                # 타입 검사 + 빌드
```

## 라이선스

[MIT](LICENSE)
