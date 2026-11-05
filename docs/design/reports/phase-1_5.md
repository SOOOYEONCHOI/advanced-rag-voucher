# Phase 1.5 보고서 — SQLite → PostgreSQL 전환 (재구현)

> 작성 2026-10-16 · 설계: `docs/design/phase-1_5_PostgreSQL_전환_설계.md`(Q-15.1~15.8 승인) · 관련 ID: DB-01, F-2-06(일부), N-9, N-10, DB-ENV-1·2
> 기준 소스: 10-15 SQLite판(착수 점검 Q-0 = 재구현)

## 1. 요약

- 앱 DB를 SQLite에서 **PostgreSQL 16.14**(`rag_chatbot_dev`)로 바꿨다. 저장소 코드가 쓰던 `DatabaseManager` 인터페이스는 그대로 두고, 그 아래를 SQLAlchemy 커넥션 풀 + psycopg로 교체했다.
- 스키마는 **Alembic `0001_baseline`**(24테이블)으로만 만든다. 앱 기동 때마다 돌던 SQLite 런타임 마이그레이션 8종과 `schema.sql`은 없앴다.
- 앱이 받는 값 형식(KST ISO 시각 문자열, JSON 문자열, 1/0)은 그대로다. 저장소 쪽은 SQLite 전용 문법만 고쳤다.
- 로컬 SQLite 데이터를 이관 스크립트로 `rag_chatbot_dev`에 옮겼고(24테이블 건수 일치), dev 컨테이너가 PostgreSQL로 기동한다.

## 2. 환경 작업 (사용자 승인 후 수행)

| 작업 | 내용 |
|---|---|
| dev 백엔드 중지 | `rag-backend-dev` 중지 후 새 이미지로 재기동(`--no-deps`, PostgreSQL·Qdrant 컨테이너는 건드리지 않음) |
| DB 생성 | `rag_chatbot_dev` 생성. 테스트 DB `rag_chatbot_test`는 conftest가 생성. 기존 `neocon_rag`·`neocon_rag_test`는 **그대로 보존** |
| **DB 계정** | 신규 롤 **`rag_chatbot`**(LOGIN, CREATEDB), `rag_chatbot_dev` 소유자. 이유: `rag-postgres-dev` 컨테이너가 빈 환경변수로 다시 만들어져 있었고(컨테이너 안 `POSTGRES_USER/DB/PASSWORD` 길이 0), 기존 `neocon` 롤의 비밀번호가 `.env`·컨테이너 어디에도 남아 있지 않았다. 외부 접속은 `scram-sha-256`이라 비밀번호가 필요해, `neocon`을 바꾸지 않고 새 롤을 만들었다. 비밀번호는 무작위 생성해 `.env`에만 기록(화면·로그 출력 없음) |
| `.env` | 끝에 `POSTGRES_HOST/PORT/DB/TEST_DB/USER/PASSWORD` 블록 추가(기존 줄은 수정하지 않음). `HOST=localhost`(로컬 실행), dev 컨테이너는 compose가 `postgres-dev`로 덮어씀 |
| 이미지 | `rag-backend-dev` 재빌드(psycopg·alembic 추가). WSL에는 compose 플러그인이 없어 `docker-compose`(v1) 사용 |

## 3. 변경 파일

| 파일 | 내용 | 관련 |
|---|---|---|
| `adrag_backend/app/repositories/database.py` | 전면 재작성: 엔진·풀, `?`→`%s` 변환(`to_driver_sql`), 값 로더(timestamptz→KST ISO, jsonb→문자열, bool→1/0), `Row`, 중첩 트랜잭션 공유(ContextVar, 스레드 구분), `lastrowid` 거부, 드라이버 예외 → SQLAlchemy 예외, `ensure_schema_ready`·`initialize_database`·`close_database_manager` | 설계 3장 |
| `adrag_backend/migrations/env.py`, `script.py.mako`, `versions/0001_baseline.py` | 신규. 24테이블·인덱스 57개(+유니크 1, 작업 큐 인덱스 2개 신규 포함)·LLM 시드 4행. 중복 인덱스 3개 제외, 관리자 시드 없음 | 설계 4장 |
| `adrag_backend/alembic.ini` | `path_separator = os` 추가(경고 제거, ASCII 유지) | |
| `adrag_backend/app/core/db_config.py` | 기본값 `rag_chatbot_dev`/`rag_chatbot`, `DB_STATEMENT_TIMEOUT_MS`(0)·`DB_APPLICATION_NAME` 추가 | N-9, 설계 3.6 |
| `adrag_backend/app/core/config.py` | `sqlite_db_path`에 기본값(필수 → 선택) | Q-15.7 |
| `adrag_backend/init_database.py` | SQLite 초기화 → `alembic upgrade head` + 버전 확인 | 설계 7.2 |
| `adrag_backend/main.py` | 기동 시 `ensure_schema_ready()`(head 아니면 기동 실패), 종료 시 풀 닫기 | N-10 |
| `adrag_backend/requirements.txt` | `psycopg[binary]==3.3.6`, `SQLAlchemy>=2.0.48,<2.2`, `alembic==1.20.0` | |
| 저장소·라우트 9개 | 5절 SQL 방언 수정 | 설계 5장 |
| `adrag_backend/app/repositories/schema.sql` | **삭제**(평문 비밀번호 주석 포함, Q-15.6). SVN에서는 삭제 반영 필요 | Q-15.6 |
| `adrag_backend/scripts/migrate_sqlite_to_postgres.py` | 머리말만 정리(동작 변경 없음) | 설계 6.1 |
| `adrag_backend/tests/conftest.py` | 테스트 DB 기본값 `rag_chatbot_test`, 미구현 Phase 테스트 10개 파일 `collect_ignore`(사유 주석) | 설계 8.1 |
| `adrag_backend/tests/test_database_migrations.py` | 기준값 `TABLE_COUNT=24`, `HEAD="0001_baseline"` | 설계 3.5 |
| `adrag_backend/tests/test_collection_service.py`, `test_deletion_consistency.py`, `test_multi_document_upload.py`, `test_stats_api.py` | 설정 stub에 `sqlite_db_path` 추가(코드가 아직 읽음, Q-15.7) | |
| `.env.example` | 신규. 이름만(DB 항목은 비밀 아닌 기본값) | DB-ENV-2 |
| `.env` | 2절 | |
| `CLAUDE.md` 5절 | 실제 명령으로 갱신 | |
| `docs/design/phase-1_5_PostgreSQL_전환_설계.md` | 상태·계정 이름 반영 | |

## 4. 마이그레이션

- 신규 리비전 `0001_baseline`(down_revision 없음). `rag_chatbot_dev`에 적용됨(`init_database.py`).
- 데이터 이관: 로컬 SQLite(`instance/db/db_rag_metadata.db`) → `rag_chatbot_dev` 커밋. 24테이블 건수 모두 일치(부서 1, 사용자 2, 로그인 이력 2, 컬렉션 1, 문서 1, 보안 정책 1, 작업 1, LLM 모델 4, 나머지 0). SQLite 파일은 수정하지 않음.

## 5. SQL 방언 수정 (설계 5장 B-항목)

| 항목 | 위치 | 내용 |
|---|---|---|
| B-1 | `collection_repository`, `evaluation_repository`(6), `query_log_repository` | `lastrowid` → `RETURNING` |
| B-2 | `evaluation_repository` | `INSERT OR REPLACE` → `ON CONFLICT (run_id, metric_key, segment) DO UPDATE` |
| B-3 | `query_log_repository` | `INSERT OR IGNORE` → `ON CONFLICT (log_id, document_id) DO NOTHING` |
| B-4 | `evaluation_repository`(8) | `strftime(… 'now', '+9 hours')` → `now()` |
| B-5 | `stats_repository`(2) | `substr(created_at,1,10)` → KST 날짜(`AT TIME ZONE 'Asia/Seoul'`) |
| B-6 | `collection_repository`(2), `stats_repository` | `json_each` → `jsonb_array_elements_text` (FROM 서브쿼리 별칭 추가) |
| B-7 | `collection_repository`, `metadata_repository`, `model_repository`, `department_repository`, `login_history_repository`, `query_log_repository`, `routes/admin_departments`, `routes/admin_users`, `routes/auth` | 플래그 `= 1`/리터럴 `1` → `TRUE`, 정수 파라미터 → `bool()` |
| B-8 | `department_repository`, `routes/admin_users` | `LIKE` → `ILIKE` |
| B-9 | `stats_repository`(2) | `GROUP BY`에 조인 테이블 컬럼 추가(`u.user_name`, `c.display_name`) |

검색 결과 0건 확인(`app/`·`main.py`): `import sqlite3`, `PRAGMA`, `sqlite_master`, `.lastrowid`, `'now', '+9 hours'`, `json_each(`, `INSERT OR `, `executescript`.

## 6. 완료 기준 충족 근거

| 기준(설계 8.2) | 결과 |
|---|---|
| 1. DB 계층 계약 테스트 | `tests/test_database_migrations.py` **14 passed** (upgrade↔downgrade 왕복, 제약 거부, 값 형식, 자리표시자, 중첩 트랜잭션 롤백, `lastrowid` 거부) |
| 2. 단위 테스트 기준선 | `pytest -m "not e2e and not voice"`: **363 passed / 10 failed / 4 errors / 11 skipped**(collect_ignore 10개 파일 제외). 실패·오류 14건은 모두 Phase 1.5와 무관(7절). 전환 후 처음 돌렸을 때 51 failed → 원인별 정리 |
| 3. 이관 dry-run | 24테이블 건수 일치, KST 일별 건수 일치 → 실제 이관 커밋 |
| 4. dev 컨테이너 기동 | `[DB] PostgreSQL 스키마 확인 완료 (revision=0001_baseline)`, `Application startup complete` |
| 4. API 스모크(실행 중 서버) | 파라미터 없는 GET 전부(관리자·사용자 토큰): **200 50건, 500 0건**(401은 역할 불일치, 422는 필수 파라미터). 쓰기 경로: 부서 생성·수정·검색(ILIKE), 사용자 생성·검색·비활성화(boolean), 로그인 성공·실패(로그인 이력 1/0), 질의 로그 INSERT RETURNING, 통계(키워드 jsonb·사용자 Top GROUP BY·일별 추이) **전부 정상**, 임시 데이터 삭제 확인 |
| 5. SQLite 구문 검색 0건 | 5절 |
| 미확인 | **문서 업로드 → 처리 → 질의 응답**은 GPU 서버(docling·임베딩·LLM)가 필요해 이번에 실행하지 않음. 이 경로의 DB 쓰기(`tb_documents`·`tb_ingest_jobs`·`tb_query_logs`)는 단위 테스트로만 확인 |

## 7. 남은 실패·이슈

**테스트 실패 14건(전부 기존 문제, 전환과 무관)**

| 구분 | 테스트 | 원인 |
|---|---|---|
| 순서 의존(단독 실행 시 통과) | `test_eval_e2e`, `test_eval_kiwi_direct_search`(2), `test_eval_routes`, `test_rule_based_metric_regressions`(2), `test_spreadsheet_payload`, `test_deletion_consistency::test_vector_repository_counts…` | 다른 테스트가 `sys.modules`의 설정·저장소 모듈을 stub으로 바꿔 끼움(기존에 알려진 문제) |
| 순서 의존 | `test_stats_api`(수집 오류), `test_multi_document_upload`(setup 오류 3) | 같은 원인. 단독 실행 시 `test_stats_api` 20 passed, multi upload 2 passed |
| 소실된 Phase 3 API | `test_multi_document_upload::test_job_owner_permissions_and_retry_contract` | `IngestJobRepository.requeue_failed` 없음 |
| 테스트가 옛 응답 기준 | `test_unified_auth_routes::test_admin_uses_unified_auth_login_me_and_logout` | 10-15 소스가 로그인 응답에 `ui_type`을 추가 |
| 기존 실패 | `parsers/test_parse_regression::test_no_fixture_disappeared_silently` | 이전부터 있던 실패 |

**수집 제외(conftest `collect_ignore`)** — 해당 Phase 재구현 때 되살린다: excel_ingest 3개·`test_ingest_queue_versions`(Phase 1~3), 스프레드시트 resource 3개(Phase 2 asset/placement·버전 테이블 전제), `test_answer_images`(Phase 4), `test_voice_*` 2개(Phase 4.5).

**이슈**
1. **`sqlite_db_path`가 DB 말고도 쓰인다**: 업로드 대기 파일 폴더가 `Path(sqlite_db_path).parent / "ingest_jobs"`(`routes/ingest.py:191`). 그래서 `SQLITE_DB_PATH` 설정은 당분간 지우면 안 된다. Q-15.7 정리(Phase 2) 때 `instance_dir` 기준으로 옮긴다. (테스트 중 이 경로 때문에 작업 폴더에 테스트 파일이 생겨 삭제했고, 테스트 stub을 tmp 경로로 고쳤다.)
2. **`rag-postgres-dev`의 컨테이너 환경변수가 비어 있다**: 데이터 볼륨은 정상. 다음에 compose로 다시 만들면 `.env`의 `POSTGRES_USER=rag_chatbot`·`POSTGRES_DB=rag_chatbot_dev`가 들어가며(기존 볼륨이라 DB·롤은 새로 만들지 않음), healthcheck도 그 값으로 동작한다.
3. `tb_eval_item_results UNIQUE(run_id, qa_id)`: 평가 실행은 항목마다 1회 INSERT라 문제없으나, 골드셋 스냅샷 항목에 `qa_id`가 없으면 0으로 들어가 두 번째부터 충돌한다. 현재 스냅샷은 `tb_eval_qa_items`에서 만들어 `qa_id`가 항상 있다.
4. 기존 `neocon_rag`(소실 계보 0005, 문서 63건)·`neocon_rag_test`는 보존 중. 필요 없다고 판단되면 `pg_dump` 후 삭제(사용자 확인).
5. 운영 이관(12월, `rag_chatbot_prod`)은 설계 6.2 절차서 기준. 운영 SQLite는 이관 전 현행 앱으로 한 번 기동된 상태여야 한다(옛 컬럼이 있으면 스크립트가 중단).

## 8. 되돌리는 방법

1. 3절 파일을 이전 판으로 되돌린다(SVN 작업 폴더: `svn revert`; 신규 파일 `migrations/`·`.env.example`·이 보고서는 삭제, `schema.sql` 복구).
2. `.env` 끝의 `2026.10.16 추가 - Phase 1.5` 블록 삭제.
3. `rag-backend-dev` 이미지 재빌드 후 재기동 → SQLite(`instance/db/db_rag_metadata.db`, 수정되지 않음)로 동작.
4. (선택) `rag_chatbot_dev`·`rag_chatbot_test` DB와 `rag_chatbot` 롤 삭제. `neocon_rag`는 건드리지 않았다.

## 9. 요구사항 정의서·기능 목록에 반영할 것

- DB 이름 규칙: 개발 `rag_chatbot_dev`, 테스트 `rag_chatbot_test`, 운영 `rag_chatbot_prod`. 개발 계정 `rag_chatbot`.
- DB-01 산출물: `migrations/versions/0001_baseline.py`(24테이블), `scripts/migrate_sqlite_to_postgres.py`, 설계 6.2 이관 절차.
- 신규 설정: `DB_STATEMENT_TIMEOUT_MS`, `DB_APPLICATION_NAME`(N-9).
- 고정 관리자 계정 시드 제거 → 관리자는 `scripts/create_admin.py`로 생성(운영 절차).
