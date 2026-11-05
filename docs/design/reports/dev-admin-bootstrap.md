# dev 관리자 자동 생성 + 최초 설치 안내 정비 (2026-10-20, D-19)

## 1. 요약

- dev 컨테이너 기동 시(`init_database.py`, alembic upgrade head 다음) **활성 관리자가 없을 때만** `.env`의 `ADMIN_PASSWORD`로 관리자를 만든다. `docker-compose.dev.yml`에서만 `DEV_BOOTSTRAP_ADMIN=true`.
- 마이그레이션·운영 DB에는 관리자 시드를 넣지 않는다(Q-15.6 유지). 연결 DB가 `rag_chatbot_prod`이면 거부.
- 비밀번호 없음·10자 미만·같은 아이디의 일반 사용자 → 경고 로그(다음에 할 일 포함)만 남기고 기동 계속. 비밀번호는 로그에 남기지 않는다.
- 최초 설치자를 위해 `.env.example`(이름만) 추가, README 빠른 시작을 현재 구성(외부 GPU 서버, docker-compose v1, 관리자 단계)에 맞게 수정, 운영 이관 절차서에 관리자 단계(6-1) 추가.
- `.env`는 이미지에 들어가지 않는다(`adrag_backend/.dockerignore`가 제외, 루트 `.env`는 빌드 경로 밖). 컨테이너 기동 때 `env_file`로만 전달.

## 2. 변경 파일

| 파일 | 내용 |
|---|---|
| `adrag_backend/app/services/admin_bootstrap.py` (신규) | `ensure_dev_admin()`·`PROD_DATABASE_NAME`·`MIN_PASSWORD_LENGTH` (처음엔 scripts/create_admin.py에 두었다가 앱 코드가 scripts를 import하지 않도록 이동) |
| `adrag_backend/scripts/create_admin.py` | 명령행 도구만 남김, `MIN_PASSWORD_LENGTH`는 위 모듈에서 가져옴. 명령행 동작 변경 없음 |
| `adrag_backend/init_database.py` | `DEV_BOOTSTRAP_ADMIN`이 켜져 있으면 `app.services.admin_bootstrap.ensure_dev_admin()` 호출, 예외는 경고 후 기동 계속 |
| `docker-compose.dev.yml` | backend `environment`에 `DEV_BOOTSTRAP_ADMIN=true`, 머리 주석 명령을 v1 표기로 통일 |
| `adrag_backend/tests/test_dev_admin_bootstrap.py` (신규) | 7건: 생성 / 관리자 있음 / 비밀번호 없음·빈 값·짧음 / 일반 사용자 승격 안 함 / 운영 DB 거부 |
| `.env.example` (신규) | `.env`의 변수 이름 전부 + `ADMIN_PASSWORD`·`DEV_BOOTSTRAP_ADMIN_ID`·`EXCEL_PARSE_MODE`. 실제 값 없음(필수/선택 표시) |
| `README.md` | 빠른 시작 2~4절, 접속 정보 표 |
| `docs/design/phase-1_5_PostgreSQL_전환_설계.md` | 4.4 시드 보충, 6.2 이관 절차 6-1단계 |
| `docs/design/01_결정사항_변경로그.md` | D-19 |
| `CLAUDE.md` §5 | `create_admin.py` 줄 보충 |

## 3. 설정값

| 이름 | 기본값 | 위치 |
|---|---|---|
| `DEV_BOOTSTRAP_ADMIN` | 꺼짐 | dev compose만 `true` |
| `DEV_BOOTSTRAP_ADMIN_ID` | `admin` | `.env`(선택) |
| `ADMIN_PASSWORD` | 없음 | `.env` |

## 4. 완료 근거

- 새 테스트: 컨테이너(`rag-backend-dev`, bcrypt 4.0.1)에서 **7 passed**.
- 전체 회귀(로컬, `-m "not e2e and not voice"`): **472 passed / 12 failed / 17 skipped / 3 errors**. 기준선 466/11/3 대비 +6 passed는 새 테스트, 실패 +1은 `test_creates_admin_when_none_exists` — 로컬 Python의 bcrypt 5.0.0이 `requirements.txt`(`bcrypt>=4.0.1,<4.1.0`)를 벗어나 passlib 해시가 실패하는 환경 문제(컨테이너 통과). 나머지 실패 11·오류 3은 기준선 목록과 같음.
- 실제 기동: dev backend 재생성 후 로그 `✓ Database ready … @ 0005_document_version_replace`, `[dev 관리자] 활성 관리자가 이미 있어 자동 생성을 건너뜁니다.` (기존 dev DB에 관리자 있음 — 비밀번호 덮어쓰지 않음 확인)
- 빈 DB 기동(10-20, dev 볼륨은 그대로 두고 postgres-dev에 임시 DB `rag_chatbot_bootcheck`를 만들어 컨테이너에서 `init_database.py` 실행 후 삭제): 1차 `관리자 계정을 만들었습니다: admin`, 사용자 1명·비밀번호 일치 / 2차(다른 비밀번호) `활성 관리자가 이미 있어 … 건너뜁니다` / 비밀번호 없음 → 경고 후 정상 종료.
- 최종 회귀(10-20, 서비스 이동·API 제거 후, 로컬 bcrypt 4.0.1): **473 passed / 11 failed / 17 skipped / 3 errors** — 실패·오류 목록은 기준선과 동일.

## 5. 마이그레이션

없음(스키마 변경 없음).

## 6. 되돌리는 방법

`docker-compose.dev.yml`의 `DEV_BOOTSTRAP_ADMIN=true` 줄 삭제 후 backend 재생성 → 이전 동작. 이미 만들어진 계정은 남는다. 코드 되돌림은 위 변경 파일을 SVN 기준으로 revert.

## 7. 남은 이슈

- (해결 10-20) 로컬 Python bcrypt를 4.0.1로 맞춤 → 로컬에서도 새 테스트 통과. 회귀 기준선은 473 passed / 11 failed / 3 errors로 본다.
- (해결 10-20, 사용자 결정=제거) `POST /api/admin/init` — 관리자가 0명이면 인증 없이 누구나 관리자를 만들 수 있던 기존 API. `app/routes/admin_auth.py` 삭제, `main.py` 라우터 등록 제거, `tests/test_unified_auth_routes.py`는 모듈이 없음을 확인하도록 변경, 테이블 정의서·`gen_table_definition.py`의 사용 코드 목록에서 삭제. 실행 중 dev 백엔드에서 `POST /api/admin/init` → 404, `/health` 200 확인. 되돌리기: SVN에서 `admin_auth.py`·`main.py` revert.
- (해결 10-20) 빈 DB 기동 확인 — 임시 DB로 대체 확인(4절). dev 볼륨 삭제 후 `up -d --build` 전체 경로는 하지 않음.
- `init_database.py`의 켜기/끄기 분기 자체는 단위 테스트 없음(환경변수 확인 한 줄, 실제 기동 로그로 확인).

## 7-1. scripts 정리 (10-20, 사용자 요청)

- 삭제: `adrag_backend/scripts/relocate_image_assets.py` — 옛 계보 Phase 2 설계(`tb_image_assets`, `spreadsheet_resource_service.ASSET_DIR`) 기준. 현행 스키마에 테이블이 없고 import 대상도 없어 실행 불가, 호출하는 곳 없음.
- 유지: `create_admin`·`migrate_sqlite_to_postgres`·`check_sqlite_quality`(운영 이관), `eval_excel_retrieval`·`eval_image_answer`·`verify_multi_upload`(실서버 검증), `gen_table_definition`(테이블 정의서) — import·API 경로가 현행 코드와 맞음.
- 참고: `tests/test_excel_ingest_indexing.py`·`test_excel_ingest_sample.py`도 `tb_image_assets` 기준이지만 conftest `collect_ignore` 대상(옛 계보)이라 이번에 건드리지 않음.

## 7-2. dev Qdrant 저장소 named volume 전환 (10-20, 사용자 승인)

- 증상: 대화 주제(컬렉션) 추가 저장이 약 34초. 로그상 컬렉션 생성 후 `create_payload_index`(wait=true) 16회가 회당 약 2초.
- 원인: `qdrant-dev`가 `./adrag_backend/instance/qdrant_storage`(WSL에서 `/mnt/d/...`, Windows 드라이브)에 바인드 마운트 → 디스크 기록이 느림. 측정(인덱스 5개): 바인드 마운트 9.9초 / Linux 파일시스템 1.1초.
- 조치: `docker-compose.dev.yml`의 qdrant-dev를 기존에 정의돼 있던 named volume `qdrant-dev-storage`로 변경(바인드 마운트 줄은 주석으로 남김). 코드 변경 없음.
- 영향: 기존 바인드 마운트의 Qdrant 데이터는 새 볼륨으로 옮겨지지 않는다(폴더는 남음). dev DB와 맞추려면 dev DB 볼륨도 함께 초기화. Qdrant 초기화는 `docker volume rm advanced-rag-voucher_qdrant-dev-storage`.
- 되돌리기: 두 volumes 줄의 주석을 서로 바꾼 뒤 `up -d qdrant-dev`.

## 8. 요구사항 정의서·기능 목록에 반영할 것

- 설치·운영 절차(비기능): "dev 환경은 최초 기동 시 관리자 자동 생성, 운영은 관리자 생성 스크립트 1회 실행" 문구.
