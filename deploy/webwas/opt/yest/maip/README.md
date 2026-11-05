# 제조AI플랫폼 (Manufacturing AI Platform)

제조 현장의 **비전 검사**, **비전 데이터**, **디지털 입력 전환**을 하나의 웹 플랫폼에서 처리합니다.

이 문서는 무엇인지와 어떻게 띄우는지의 요약과 길잡이입니다. 자세한 내용은 [문서](#문서) 에 있습니다.

| 이런 분은 | 여기부터 읽습니다 |
|---|---|
| 개발 PC 에 처음 띄우는 개발자 | [개발 — 빠른 시작](#개발--빠른-시작) |
| 서버에 설치·운영하는 운영자 | [운영 — 설치 순서](#운영--설치-순서) → [운영 명령](#운영-명령) |
| 무언가 동작하지 않을 때 | [막힐 때](#막힐-때) |
| 코드를 고치려는 개발자 | [AGENTS.md](AGENTS.md) — 지켜야 할 규칙 |
| 팀원으로 개발에 참여할 때 | [문서](#문서) 의 소스 관리 문서 — 브랜치·push·공유 개발 DB 규칙 |

## 무엇을 하는 시스템인가

| 일 | 누가 | 무엇을 |
|---|---|---|
| **비전 검사** | 고정 거치대 PC 의 비전검사 클라이언트 | 부품 사진을 찍어 보내면 AI 가 판정하고 검사 기록으로 남깁니다 |
| **비전 데이터** | 라벨러·검수자 | 모인 사진을 라벨링·검수해 AI 학습 데이터(스냅샷)로 만듭니다 |
| **디지털 입력 전환** (개발 중) | 현장 검사원(태블릿·PC) | 엑셀로 출력해 쓰던 검사 성적서·체크리스트를 화면 양식에 바로 입력합니다 |

```text
비전검사 클라이언트(현장 PC) ──검사 이미지──▶ 제조AI플랫폼 ──추론 요청──▶ Wezard
                                              │    ▲                       │
                                              │    └──── 판정 결과 ─────────┘
                                              ▼
                              비전검사항목 데이터 → 라벨링 → 검수 → 스냅샷
                                                                  │
                                    Wezard 가 스냅샷을 가져가 학습 ◀┘
```

검사 이미지는 곧바로 그 비전검사항목의 데이터로 저장됩니다. 치수 측정 항목은 추론하지 않고, 클라이언트가 잰 값을 서버가 측정점 규격(하한~상한)으로 판정합니다.
디지털 양식의 이미지 칸을 비전검사항목과 이으면 검사작성에서 넣은 사진이 그 항목의 비전 데이터가 됩니다. 화면별 흐름은 [docs/FEATURES.md](docs/FEATURES.md) 에 있습니다.

## 할 수 있는 것

| 영역 | 기능 |
|---|---|
| **대시보드** | 로그인 첫 화면. 검사 작업·비전 데이터 현황을 실제 데이터로 보입니다 |
| **비전 검사** | 검사 이력, 비전검사 클라이언트·Overlay 관리, 비전검사항목 관리(검사 분류 트리, AI 모델 매핑) |
| **비전 데이터** | 데이터 목록·업로드·정제, 라벨링(분류·객체 탐지·이상 탐지), 검수, 스냅샷(워커가 zip 을 만듭니다) |
| **디지털 입력 전환** (개발 중) | 검사양식 관리, 수입검사 품목 지정, 검사양식 코드 관리, 수입·품질검사 작성·결과. 고객 양식 15종(DF0012~DF0026)을 기본으로 넣습니다 |
| **기준정보** | 품목·BOM 조회, 입고 내역(조회 전용) |
| **시스템** | 인터페이스 이력·부서·사용자·그룹·메뉴 권한, 메뉴명, 로그. 화면은 한국어만 제공합니다 |

## 구성 요소

Python 3.12 / Django 5.2 LTS(5.2.18) / PostgreSQL 16. 화면은 Django Template + jQuery + Bootstrap 5 + WeZonGrid 입니다.

| 구성 요소 | 하는 일 | 없거나 멈추면 |
|---|---|---|
| **웹** (개발 `runserver` 8123 / 운영 gunicorn 8080, 앞에 nginx 80) | 화면·API 전부 | 서비스가 뜨지 않습니다 |
| **워커** (`manage.py run_worker`) | 스냅샷 Export(zip) · DB 로그·만료 세션 정리 | 버튼은 눌리지만 작업이 대기로 남습니다 |
| **nginx** (운영) | 80 을 받아 앱 8080 으로(지금 ALB HTTP, HTTPS 는 ALB 에 붙일 예정), 큰 파일 전송(`X-Accel-Redirect`) | — |
| **PostgreSQL 16** | 데이터. 데이터 관리 테이블에 RLS 가 걸려 있습니다 | — |
| **비전검사 클라이언트** (현장 PC, 별도 프로젝트) | `/api/v1` 로 카탈로그를 받고 검사 이미지를 보냅니다 | 검사가 들어오지 않습니다 |
| **Wezard** (학습·추론 서버, 별도 플랫폼) | ① 스냅샷을 가져가 학습합니다(`/api/v1/datasets`) ② 플랫폼이 추론을 요청합니다 | ② 가 없으면 검사는 저장되고 판정만 비어 `접수됨 (추론 미실행 · Wezard 미설정)` 으로 남습니다 |

## 개발 — 빠른 시작

**준비물:** Python 3.12, 접속 가능한 PostgreSQL 16 DB, (화면 JS 검증용) Node.

### 1. 설치

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt     # 개발 PC 용. 운영 서버는 requirements.txt
.venv/bin/python -m playwright install chromium   # e2e·화면 검증 스크립트를 돌릴 때만
cp .env.example .env
```

`.env` 에서 `DB_HOST`·`DB_NAME`·`DB_USER`·`DB_PASSWORD` 를 개발 DB 로 맞추고 `DB_CONN_MAX_AGE` 를 **`0`** 으로 바꿉니다(예시 파일 값 60 은 운영용이라 개발 서버에서는 커넥션이 쌓입니다).
`WEZARD_BASE_URL`·`WEZARD_API_KEY` 는 비우면 추론하지 않으므로 화면·데이터 관리만 볼 때는 비워도 됩니다. 나머지 키는 [문서](#문서) 의 개발 문서에 있습니다.

### 2. DB 준비

> **팀원은 이 단계를 건너뜁니다.** 공유 개발 DB 는 담당자가 준비하고, 팀원이 돌리면 다른 사람의 메뉴·비밀번호가 바뀝니다. [문서](#문서) 의 소스 관리 문서를 봅니다.

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_initial --admin-password '<비밀번호>'   # 그룹·메뉴·관리자(admin)
.venv/bin/python manage.py seed_vision_items                           # 검사 분류(고정 대분류)·NEOCON C2 비전검사항목
.venv/bin/python manage.py seed_dig_form                               # 고객 양식(디지털 양식)·비전 연결·분류 매핑. seed_vision_items 다음
.venv/bin/python manage.py seed_demo                                   # 개발 전용 표본. 운영에서 돌리지 않습니다
```

`seed_demo` 는 표본 비전검사항목·이미지와 비전검사 클라이언트를 만들고 클라이언트 API Key 를 콘솔에 출력하므로 개발 DB 에서만 씁니다.

### 3. 실행

```bash
.venv/bin/python scripts/maipctl.py start      # 웹(127.0.0.1:8123)·워커를 백그라운드로 띄웁니다
.venv/bin/python scripts/maipctl.py status     # 실행 중이면 PID·주소를 보입니다
.venv/bin/python scripts/maipctl.py stop       # 둘 다 멈춥니다
```

`http://127.0.0.1:8123/` 에서 `admin` 으로 로그인하면 대시보드가 열립니다. 다른 PC 에서 열기 등 옵션은 `--help` 와 `docs/DEVELOPMENT.md` 에 있습니다.

## 운영 — 설치 순서

명령·설정 파일·환경변수 뜻은 [문서](#문서) 의 운영 문서(`docs/DEPLOYMENT.md`)에 있고, 여기에는 순서만 적습니다.
운영 서버(Rocky 9.6, nginx 80 → 앱 8080)는 `deploy/build_package.sh` 로 만든 파일 3개를 올려 `deploy.sh` 로 배포합니다 — 운영 문서 §0.

| 순서 | 할 일 (운영 문서 §2) |
|---|---|
| 1 | **서버 준비** — Python 3.12, 서비스 계정 `maip`, 경로·권한, 배포 파일 올리기 |
| 2 | **DB 확인** — 전용 계정이 DB 소유자이고 superuser·`BYPASSRLS` 가 아닌지 |
| 3 | **`.env`** — 배포 묶음의 `.env.example` 로 만들고 `yhan:maip` 640 으로 둡니다 |
| 4 | **`deploy.sh`** — 소스·의존성·`migrate`·기본 데이터·`collectstatic`·점검. 첫 배포에만 관리자 계정과 다국어 SQL |
| 5 | **서비스 등록** — `scripts/systemd/` 의 `maip.service`·`maip-worker.service` 를 복사하고 `maip` 을 켭니다(워커가 함께 뜹니다) |
| 6 | **nginx·ALB** — 80 → 앱 8080, ACL·방화벽, ALB 헬스체크 `/lb-health` |
| 7 | **배포물 · 기준정보 · 점검** — 배포물 반입, 기준정보 인터페이스, 점검 목록 |

운영 `.env` 에서 반드시 정할 값은 보안(`DEBUG=False`·`SECRET_KEY`·`ALLOWED_HOSTS`·`CSRF_TRUSTED_ORIGINS`·`HTTPS_ENABLED`), DB, 파일 경로(`FILE_ACCEL_REDIRECT=True` 는 nginx 와 함께), Wezard 두 키(연동할 때)입니다 — 의미는 운영 문서 §3.

> **`seed_demo` 는 운영에서 초기 세팅 때 데이터 파이프라인 점검으로만 한 번 돌리고 바로 정리합니다**(운영 문서 §2-9). 클라이언트 API Key 를 콘솔에 출력합니다.

## 운영 명령

```bash
sudo systemctl start|stop|restart maip           # 워커(maip-worker)도 함께 움직입니다
sudo systemctl status maip maip-worker           # 둘 다 active 여야 합니다
curl -s -H 'Host: <접속 주소>' http://127.0.0.1/api/v1/health   # DB·Storage 점검. 실패하면 503 입니다
tail -f /mnt/a/maip/logs/app-$(date +%F).log     # 시스템 로그(오류 트레이스 포함). LOG_DIR
journalctl -u maip-worker -f                     # 워커 표준 출력
```

**업데이트** — 서버는 인터넷에 못 나가 `git pull`·`pip install` 을 하지 않습니다. 개발 PC 에서 배포 파일을 만들어 올리고 `deploy.sh` 로 반영합니다(운영 문서 §0).

```bash
deploy/build_package.sh <커밋>                   # 개발 PC — deploy/dist/ 에 파일 3개(인자 없으면 origin main, 원격 인증 필요)
# 로컬 PC 로 받아 서버 /home/yhan/dist/ 에 바이너리 모드로 올린 뒤(서버, yhan)
cd /home/yhan/dist && chmod +x deploy.sh && ./deploy.sh
sudo systemctl restart maip
```

클라이언트 배포본 교체는 인증 없이 공개되는 폴더라 운영 문서의 "배포물 반입"에 절차가 있습니다.

| 키 | 관리 방법 |
|---|---|
| 비전검사 클라이언트 API Key | 화면 "비전검사 클라이언트 관리"에서 발급·재발급합니다 |
| Wezard 연동 키(`maip_…`) | `manage.py integration_key` 로 발급·재발급·폐기합니다(`--help`). 화면에는 없습니다 |

## 막힐 때

| 증상 | 먼저 볼 것 |
|---|---|
| 스냅샷이 계속 대기 상태입니다 | 워커가 떠 있는지 확인합니다 — 운영은 `systemctl status maip-worker`, 개발은 `scripts/maipctl.py status worker` |
| 데이터 화면 조회가 0건입니다 | `TENANT_RLS_ENABLED=True` 인지 확인합니다(False 면 전부 0건입니다) |
| 다른 PC·클라이언트가 400 을 받습니다 | 그 이름·IP 가 `ALLOWED_HOSTS` 에 없습니다 |
| 이미지·zip 이 빈 파일로 받아집니다 | nginx `/_protected/` 없이 `FILE_ACCEL_REDIRECT=True` 를 켰습니다 |
| 화면은 열리는데 API 가 403 입니다 | 메뉴 권한 또는 권한 매핑이 없습니다(`verify_permission_map`) |
| 검사가 판정 없이 `접수됨` 입니다 | 아래 표를 봅니다 |

| 검사 상태 | 원인 |
|---|---|
| `접수됨 (추론 미실행 · Wezard 미설정)` | `WEZARD_BASE_URL`·`WEZARD_API_KEY` 가 비어 있습니다 |
| `접수됨 (… · 배포 모델 없음)` | Wezard 에 매핑한 이름의 배포 모델이 없습니다 |
| `접수됨` (괄호 없음) | 모델 매핑이 없거나 매핑한 모델이 비활성입니다 |
| `실패` | Wezard 시간 초과·연결·인증 오류입니다. 시스템 로그를 봅니다 |

서버 배포·nginx 문제는 운영 문서 §10, 개발 중 자주 빠지는 함정은 개발 문서 §5 에 있습니다.

## 문서

| 문서 | 내용 | 이럴 때 봅니다 |
|---|---|---|
| [AGENTS.md](AGENTS.md) | 지켜야 할 규칙 | 코드를 고칠 때, 테스트를 어디까지 어떤 설정으로 돌릴지 정할 때 |
| [docs/README.md](docs/README.md) | 문서 지도 | 어느 문서를 볼지 모를 때 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 구성 요소·API 규약·인가·RLS·추론 경계 | 구조를 이해할 때 |
| [docs/FEATURES.md](docs/FEATURES.md) | 메뉴·역할·화면별 기능·데이터 흐름 | 화면이 무엇을 하는지 볼 때 |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | 개발 환경·테스트·검증 스크립트·함정 | `.env` 개발값, 검증 스크립트가 잡는 것, 개발 중 막혔을 때 |
| [docs/SOURCE_CONTROL.md](docs/SOURCE_CONTROL.md) | 브랜치·push·공유 개발 DB 규칙 | 팀원으로 개발에 참여할 때, push 하기 전 |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | 서버 배포·운영 | 설치 단계별 명령, 환경변수 의미, 업데이트, 배포본 반입 |
| [distribution/README.md](distribution/README.md) | 배포물 폴더 규칙 | 클라이언트 zip·`SHA256SUMS.txt` 를 넣을 때 |
| [docs/client/SERVER_API_CONTRACT.md](docs/client/SERVER_API_CONTRACT.md) | 비전검사 클라이언트 계약(`/api/v1`) | 이 API 응답을 바꾸거나 배포본을 반입할 때 |
| [docs/Wezard/maip-api.md](docs/Wezard/maip-api.md) | Wezard 계약(`/api/v1/datasets`) | 이 API 응답을 바꿀 때 |
| [docs/DECISIONS.md](docs/DECISIONS.md) | 유효한 결정 | 왜 이렇게 만들었는지 볼 때 |
| [docs/STATUS.md](docs/STATUS.md) | 지금 되는 것·제약·남은 일 | 알려진 제약 전체를 볼 때 |

## 알려진 제약

전체 목록과 남은 일은 [문서](#문서) 의 상태 문서에 있습니다. 운영자가 특히 알아야 할 것 하나만 적습니다.

- **이미지 보존정책이 없습니다.** `STORAGE_ROOT` 용량이 계속 늘어나므로 디스크를 지켜봐야 합니다.
