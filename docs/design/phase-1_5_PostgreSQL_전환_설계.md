# Phase 1.5 — SQLite → PostgreSQL 전환 설계 (현재 소스 기준)

> 작성 2026-10-16 · 상태: **구현 완료(2026-10-16) — 결과 `reports/phase-1_5.md`** · Q-15.1~15.8 제안대로 승인 · 관련 ID: DB-01, F-2-06(일부), N-9, N-10, DB-ENV-1·2
> 근거: 착수 점검 Q-0 결정(점검 보고서는 삭제, 미결 항목은 `06_미결_이슈_목록.md`) — 소실된 Phase 1~3 소스를 복구하지 않고, **현재 작업 폴더(10-15 SQLite판)를 기준으로 다시 구현**한다. 이 문서는 그 첫 단계인 Phase 1.5 설계다.
> 범위: 현재 SQLite 메타 DB(테이블 24개)를 **같은 구조 그대로** PostgreSQL 16로 옮기고, 저장소(repository) 코드는 최소한만 바꾼다. 문서 버전·청크·이미지 테이블(DB-02)과 작업 큐 재설계는 Phase 2·3에서 별도 revision으로 한다.

---

## 0. 결론 요약

| 항목 | 결정(안) |
|---|---|
| 접속 방식 | SQLAlchemy 2.x 엔진(`postgresql+psycopg`, 커넥션 풀) 위에 **기존 `DatabaseManager` 인터페이스를 그대로 유지하는 호환 계층**. 저장소 31개 파일은 SQL 방언만 고친다 |
| 스키마 관리 | Alembic. `0001_baseline` = 현재 `schema.sql`(24테이블)의 PostgreSQL 판. 앱 기동 시 실행되던 SQLite 런타임 마이그레이션 8종은 삭제 |
| 값 형식 | DB는 `timestamptz`·`jsonb`·`boolean`, **앱이 받는 값은 지금과 같게**(KST ISO 문자열, JSON 문자열, 1/0) — 호환 계층에서 변환 |
| SQL 방언 | `?` 자리표시자는 호환 계층이 변환. 직접 고칠 곳은 약 40곳(5장 표) |
| 데이터 이관 | 남아 있는 `scripts/migrate_sqlite_to_postgres.py` 재사용(소폭 수정). 운영 이관은 절차서로만(N-10) |
| 테스트 | 남아 있는 `tests/conftest.py`(PostgreSQL 테스트 DB)·`tests/test_database_migrations.py`를 **이 설계의 계약(spec)**으로 쓰고 기준값만 0001에 맞춘다 |
| SQLite | 앱 실행 경로에서 제거. 이관 원본으로만 읽는다(CLAUDE.md 절대 규칙 4) |

---

## 1. 현재 상태 (2026-10-16 조사)

### 1.1 DB 계층

- `app/repositories/database.py` — `DatabaseManager` 싱글톤, **스레드별 sqlite3 연결**(`threading.local`), `PRAGMA foreign_keys=ON`·`journal_mode=WAL`, `row_factory=sqlite3.Row`.
  - 공개 메서드: `get_connection()`(컨텍스트, 정상 종료 시 commit·예외 시 rollback), `execute_query`, `execute_update`(rowcount), `execute_many`, `close_all_connections`, `get_database_manager(db_path)`, `initialize_database(db_path)`.
  - 기동 시 런타임 마이그레이션 8종: `_drop_obsolete_tables`, `_drop_obsolete_columns`, `_backfill_document_event_collections`, `_migrate_query_citation_filename`, `_migrate_eval_run_metrics`, `_sync_schema`(schema.sql을 정규식으로 읽어 누락 컬럼 ADD), `_backfill_document_type_tracking`, `_migrate_answer_correctness_columns` → `PRAGMA table_info`, `sqlite_master` 의존.
- `app/repositories/schema.sql` — 테이블 24개, 인덱스 59개 + 유니크 인덱스 1개, 시드(관리자 계정 1, LLM 모델 4).
- 사용처: `get_database_manager`/`DatabaseManager` 사용 파일 31개, `get_connection()` 직접 사용 16곳, `sqlite_db_path` 참조 77곳(33개 파일 — 대부분 저장소 생성자에 경로를 넘기는 용도).
- `init_database.py` — SQLite 초기화만 한다. dev 이미지 CMD가 `python init_database.py && uvicorn … --reload`.

### 1.2 남아 있는 Phase 1.5 자산 (이전 구현에서 살아남은 파일)

| 파일 | 상태 | 이 설계에서 |
|---|---|---|
| `app/core/db_config.py` | `DatabaseSettings`(POSTGRES_HOST/PORT/DB/USER/PASSWORD, DATABASE_URL, DB_POOL_SIZE=10, DB_MAX_OVERFLOW=20). 아무도 import하지 않음 | 그대로 사용 |
| `scripts/migrate_sqlite_to_postgres.py` | 24테이블 FK 순서 복사, 한 트랜잭션, 타입 변환, 건수·KST 일별 건수 비교, identity 재설정, `--dry-run`·`--report`. `database.build_database_url`이 없어 현재 import 실패 | 소폭 수정 후 사용(6장) |
| `tests/conftest.py` | `*_test` DB 생성, 세션마다 Alembic base→head, 테스트마다 TRUNCATE + LLM 시드·`admin` 테스트 계정 | 그대로 사용 |
| `tests/test_database_migrations.py` | 호환 계층 계약 테스트(아래 3.4) | 기준값만 수정 |
| `tests/test_migrate_sqlite_to_postgres.py` | 이관 스크립트 테스트 | 그대로 사용(실행 후 판단) |
| `docker-compose*.yml` | `postgres:16.14` 서비스, `POSTGRES_*` 주입 | 그대로 사용 |

### 1.3 환경·의존성

- `requirements.txt`(08-05)에 **psycopg·alembic 없음**. dev 이미지에는 SQLAlchemy 2.1.4만 설치돼 있음.
- 루트 `.env`(09-22)에 `POSTGRES_*` 이름이 **없다**(`SQLITE_DB_PATH`만). 실행 중인 `rag-postgres-dev`는 예전 값으로 만들어져 동작 중이지만, compose를 다시 올리면 `${POSTGRES_DB}` 등이 비게 된다. `.env.example` 없음.
- 현재 로컬 SQLite(`instance/db/db_rag_metadata.db`)는 행 13개 수준(10-15 새로 생성) → 로컬 이관은 리허설 용도.
- dev PostgreSQL `neocon_rag`는 **소실된 구현의 0005 스키마**(29테이블, 문서 63건)를 담고 있다 → 새 0001과 리비전 계보가 다르다(7.3).

### 1.4 보안 지적 (전환과 함께 정리)

- `schema.sql` 288~296행: 고정 관리자 계정 시드에 **bcrypt 해시와 평문 비밀번호 주석**이 들어 있다. 0001_baseline에는 관리자 시드를 넣지 않고 기존 `scripts/create_admin.py`로 만든다(이전 구현의 F01 결정과 같음, `test_database_migrations`가 `tb_users` 0건을 확인). 평문 주석이 있는 `schema.sql`은 0001 작성 후 저장소에서 제거한다(Q-15.6 결정).

---

## 2. 설계 원칙

1. **저장소 코드 변경 최소화** — `DatabaseManager`의 메서드 이름·반환 형태를 유지한다. 저장소는 SQLite 전용 문법만 고친다.
2. **DB는 제대로 된 타입, 앱은 지금 값 형식** — 통계·정렬·인덱스를 위해 DB는 `timestamptz`/`jsonb`/`boolean`, 앱에는 지금과 같은 문자열·정수를 돌려준다. 값 형식을 바꾸는 리팩터링은 이후 Phase에서 필요할 때만.
3. **스키마는 Alembic으로만**(절대 규칙 4) — 앱 기동 시 DDL을 실행하지 않는다. 운영은 마이그레이션·이관 스크립트로만 반영(N-10).
4. **이중 지원하지 않는다** — SQLite·PostgreSQL 선택 설정을 두지 않는다. SQLite는 이관 원본으로만 읽는다.
5. **MES 공용 서버 보호(N-9)** — 풀 크기·쿼리 시간 제한을 설정값으로 둔다.

---

## 3. DB 계층 설계 — `app/repositories/database.py` 재작성

### 3.1 구성

```
Settings(db_config.DatabaseSettings)
  └─ build_database_url() ─→ SQLAlchemy Engine (postgresql+psycopg, QueuePool, pool_pre_ping)
        └─ connect 이벤트: SET TIME ZONE 'Asia/Seoul', application_name, statement_timeout(설정 시),
                           psycopg 로더 등록(timestamptz·jsonb·boolean)
DatabaseManager (싱글톤, 공개 API 유지)
  ├─ get_connection()  → _Conn 래퍼 (contextvar로 중첩 호출 시 같은 트랜잭션 공유)
  ├─ execute_query / execute_update / execute_many
  └─ close_all_connections()
모듈 함수: get_database_manager(), close_database_manager(), initialize_database(),
          build_database_url(), to_driver_sql(), ensure_schema_ready(), Row
```

### 3.2 공개 API

| 이름 | 동작 | 비고 |
|---|---|---|
| `get_database_manager(db_path=None)` | 싱글톤 반환 | `db_path`는 **무시**(하위 호환용 인자). 저장소 생성자의 `sqlite_db_path` 전달 77곳은 Phase 1.5에서 손대지 않는다 |
| `DatabaseManager.get_connection()` | 컨텍스트 매니저. 바깥 블록이 끝날 때 commit, 예외 시 rollback | 같은 실행 흐름(ContextVar) 안의 중첩 호출은 **같은 연결·트랜잭션**을 쓴다. `asyncio.to_thread` 작업은 스레드마다 별도 컨텍스트 → 별도 연결 |
| `_Conn.execute(sql, params=())` | `to_driver_sql` 변환 후 실행, 커서 반환 | params는 항상 튜플로 넘긴다(아래 3.3) |
| `_Conn.cursor()` | 래핑된 커서: `execute`, `executemany`, `fetchone`, `fetchall`, `rowcount` | **`lastrowid` 접근 시 `NotImplementedError`** → `RETURNING` 사용 |
| `execute_query(sql, params)` | `list[Row]` | |
| `execute_update(sql, params)` | rowcount | |
| `execute_many(sql, params_list)` | rowcount 합 | |
| `build_database_url(settings=None)` | `DATABASE_URL`이 있으면 그것, 없으면 `POSTGRES_*`로 `postgresql+psycopg://…` | 이관 스크립트·Alembic `env.py`·conftest가 같이 씀 |
| `ensure_schema_ready()` | `alembic_version`이 코드의 head와 같으면 head 반환, 다르면 예외 | 앱 기동(lifespan) 시 호출. **운영은 자동 upgrade 하지 않고 기동 실패**로 알린다 |
| `close_database_manager()` | 엔진 dispose, 싱글톤 해제 | 테스트 종료·앱 종료 |
| `initialize_database()` | dev 전용: `alembic upgrade head` 실행 후 `ensure_schema_ready()` | `init_database.py`가 호출 |
| `Row` | 이름·순번 접근, `keys()`, `dict(row)`, 순회 | `sqlite3.Row` 사용 패턴(`row["c"]`, `row[0]`, `dict(row)`) 호환 |

### 3.3 자리표시자 변환 `to_driver_sql(sql)`

- 작은따옴표 문자열·큰따옴표 식별자·`--`/`/* */` 주석을 건너뛰는 간단한 토크나이저.
- 문자열·주석 **밖**의 `?` → `%s`, **모든** `%` → `%%`(문자열 안 포함).
- psycopg는 params가 주어질 때만 `%`를 해석하므로, 래퍼는 params가 없어도 **빈 튜플을 넘겨** 항상 같은 규칙으로 실행한다.
- 계약 예: `SELECT '%?' , ? WHERE a LIKE ?` → `SELECT '%%?' , %s WHERE a LIKE %s`.

### 3.4 값 변환 (psycopg 로더, 연결마다 등록)

| DB 타입 | 앱이 받는 값 | 이유 |
|---|---|---|
| `timestamptz` | `YYYY-MM-DDTHH:MM:SS+09:00` 문자열(초 단위, KST) | 현재 저장 형식과 같음. `format_kst_datetime`, 문자열 비교 코드 유지 |
| `jsonb` | JSON **문자열** | `json.loads(row[...])` 19곳 유지 |
| `boolean` | `1`/`0` | `row["is_active"] == 1` 등 유지 |
| `double precision`/`integer`/`bigint`/`text` | 기본 | |

파라미터 쪽:
- Python `str`은 psycopg 기본 동작대로 타입 미지정(unknown)으로 보내 PostgreSQL이 컬럼 타입으로 변환한다 → `'…+09:00'` 문자열 비교·저장, JSON 문자열 → `jsonb` 저장이 그대로 동작.
- Python `int`는 정수 타입으로 가므로 **`boolean` 컬럼에 0/1을 넣는 곳은 `bool(...)`로 고친다**(5장 B-7).

### 3.5 계약 테스트 (`tests/test_database_migrations.py`, 기존 파일)

롤백 왕복(upgrade→downgrade base→upgrade), 중복 인덱스 제거, 제약 위반 거부(잘못된 JSON 형태·작업 상태·음수 파일 크기), 평가 결과 `(run_id, qa_id)` 유일, 작업 생성자 FK `SET NULL`, 값 형식 유지(3.4), 자리표시자 변환, 중첩 트랜잭션 공동 롤백, `lastrowid` 거부, `Row` 프로토콜. **기준값만** `TABLE_COUNT = 24`, `HEAD = "0001_baseline"`으로 바꾼다.

### 3.6 운영 설정 (N-9)

| 설정(환경변수) | 기본값 | 내용 |
|---|---|---|
| `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | `localhost`/`5432`/`rag_chatbot_dev`/`rag_chatbot`/(없음) | 기존 `db_config.py`. 기본값을 `neocon_rag`/`neocon` → `rag_chatbot_dev`/`rag_chatbot`로 변경(3.7) |
| `POSTGRES_TEST_DB` | `rag_chatbot_test` | 기존 conftest 변수. 지금은 미지정 시 `{POSTGRES_DB}_test`이므로 `.env`·conftest 기본값을 `rag_chatbot_test`로 명시 |
| `DATABASE_URL` | 없음 | 있으면 위 값보다 우선 |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `10` / `20` | 기존. 운영 계정 접속 수 제한보다 작게(풀 합계 30) |
| `DB_STATEMENT_TIMEOUT_MS` | `0`(미적용) | **신규**. 운영에서 계정 단위 제한과 함께 쓸 값. 0이면 설정하지 않음 |
| `DB_APPLICATION_NAME` | `adrag-backend` | **신규**. MES DBA가 세션을 구분할 수 있게 |
| `SQLITE_DB_PATH` | 기존 | 앱은 더 이상 쓰지 않음. 이관 스크립트 원본 경로로만 |

### 3.7 DB 이름 규칙 (2026-10-16 결정)

| 환경 | DB 이름 | 위치 | 만드는 시점 |
|---|---|---|---|
| 개발 | `rag_chatbot_dev` | 로컬 `rag-postgres-dev` | Phase 1.5 착수 시(7.3) |
| 테스트 | `rag_chatbot_test` | 로컬 `rag-postgres-dev` | conftest가 자동 생성(이름이 `_test`로 끝나야 함 — 기존 안전장치) |
| 운영 | `rag_chatbot_prod` | MES 공용 PostgreSQL 서버, 전용 DB·전용 계정(N-9) | 운영 이관 시(12월, DB-ENV-7~9). 고객 DBA 명명 규칙이 있으면 그에 따름(Q-15.8, 이관 협의 때 확인) |

- 코드에는 DB 이름을 넣지 않는다. 환경 구분은 `POSTGRES_DB`(또는 `DATABASE_URL`) 값으로만 한다. `db_config.py`·conftest·`scripts/eval_excel_retrieval.py`의 기본값만 위 표로 맞춘다.
- 같은 서버에 개발·운영 DB를 함께 두지 않는다. 운영 DB는 운영 서버에만 있고, 이관 스크립트는 대상 URL을 명시적으로 받는다.
- N-9의 "검증 DB 이관 리허설"이 운영 서버에서 필요하면 같은 규칙으로 `rag_chatbot_stg`를 추가한다(필요할 때 결정).

---

## 4. 스키마 설계 — `0001_baseline`

### 4.1 타입 변환 규칙

| SQLite | PostgreSQL | 대상 |
|---|---|---|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `bigint GENERATED BY DEFAULT AS IDENTITY` | 12개 테이블의 정수 PK. `BY DEFAULT`라 이관 시 기존 ID를 넣을 수 있고, 이관 후 시퀀스를 MAX(id)로 재설정 |
| `TEXT PRIMARY KEY` | `text` | 사용자·문서·세션·작업 ID 등 |
| `TEXT … DEFAULT (strftime(… '+9 hours'))`, `DEFAULT CURRENT_TIMESTAMP` | `timestamptz NOT NULL DEFAULT now()` | 모든 `created_at`·`updated_at`·`event_at`·`cited_at` |
| 그 밖의 `*_at TEXT` | `timestamptz NULL` | `deleted_at`, `expires_at`, `feedback_at`, `reviewed_at`, `started_at`, `finished_at`, `content_updated_at`, `review_due_at` |
| JSON을 담는 `TEXT` | `jsonb` + `CHECK (jsonb_typeof(col) = 'array'|'object')` | 4.2 표 |
| 0/1 플래그 `INTEGER` | `boolean` | `is_active`(부서·사용자·컬렉션), `is_enabled`, `requires_api_key`, `success`, `answer_generated` |
| `feedback INTEGER CHECK IN (0,1)` | `smallint CHECK IN (0,1)` 유지 | 플래그가 아니라 평가값이다(Q-15.4 결정: D-12의 `rating ±1` 정리는 Phase 4) |
| `REAL` | `double precision` | |
| `file_size INTEGER` | `bigint CHECK (file_size >= 0)` | |
| 기존 `CHECK`·`UNIQUE`·FK(ON DELETE) | 그대로 | |

### 4.2 jsonb 컬럼

| 테이블 | 배열(`array`) | 객체(`object`) |
|---|---|---|
| tb_departments | allowed_topics | |
| tb_users | blocked_topics | |
| tb_document_events | | snapshot_json(NULL 허용) |
| tb_user_security_policies | allowed_doc_types | metadata_filters |
| tb_query_sessions | conversation_history | |
| tb_query_logs | context_text, context_meta, extracted_keywords(모두 NULL 허용) | |
| tb_ingest_jobs | | request_json, result_json(NULL 허용) |
| tb_spreadsheet_resources | linked_record_ids | |
| tb_eval_datasets | | gen_config_json |
| tb_eval_qa_items | gold_chunk_ids, gold_document_ids, gold_chunk_texts, tags | source_meta_json |
| tb_eval_goldsets | items_snapshot_json | |
| tb_eval_runs | | config_json |
| tb_eval_item_results | | `*_json` 15개(NULL 허용, 형태 CHECK 없음 — 값 구조가 지표마다 다름) |

`tb_app_settings.setting_value`는 `value_type`에 따라 int·float·str이 섞이므로 **`text` 유지**.
착수 시 확인: 코드가 이 컬럼들에 빈 문자열(`''`)을 쓰는 곳이 있으면 `jsonb`에서 오류 → 이관 스크립트 dry-run과 테스트로 찾는다.

### 4.3 제약·인덱스 정리

- 추가: `tb_ingest_jobs.status CHECK IN ('queued','running','completed','failed')`(현재 코드가 쓰는 값만), `tb_ingest_jobs.created_by → tb_users ON DELETE SET NULL`, `tb_eval_item_results UNIQUE(run_id, qa_id)`(착수 시 평가 재실행이 같은 run에 같은 qa를 두 번 넣지 않는지 확인).
- 제거(UNIQUE 제약과 중복): `idx_collections_qdrant`, `idx_depts_department_name`, `idx_llm_settings_user_collection`.
- 나머지 인덱스는 이름·컬럼 그대로. `idx_logs_feedback`의 부분 인덱스(`WHERE feedback IS NOT NULL`) 유지.

### 4.4 시드

- `tb_llm_models` 4행은 0001에 포함(현재 동작 유지, conftest도 같은 4행을 다시 넣음). 단 OpenAI 모델 3행은 절대 규칙 7(외부 AI API 금지)과 맞지 않는다 → Q-15.5 결정: Phase 1.5는 유지, 비활성화는 Phase 7에서.
- 관리자 계정 시드는 넣지 않는다(1.4).
- (2026.10.20 추가, D-19) dev 컨테이너만 기동 시 활성 관리자가 없으면 `.env`의 `ADMIN_PASSWORD`로 관리자를 만든다(`DEV_BOOTSTRAP_ADMIN`, 마이그레이션 아님). 운영은 6.2 6-1단계.

### 4.5 런타임 마이그레이션 8종의 처리

0001_baseline은 **현재 `schema.sql`의 최종 형태**를 만든다. 런타임 마이그레이션은 옮기지 않는다. 대신 이관 스크립트는 원본에 대상 스키마에 없는 컬럼(옛 `answer_metric_*`, `permission_level`, `document_name` 등)이 있으면 **이관을 멈춘다**(현재 구현, 엄격 모드 유지). 그래서 운영 SQLite가 현행 앱으로 한 번 기동돼 런타임 마이그레이션(옛 컬럼 정리·값 변환)을 마친 상태여야 한다 → 이관 절차서 1단계(6.2).

---

## 5. SQL 방언 변경 목록

| # | 내용 | 위치(현재 소스) | 변경 |
|---|---|---|---|
| B-1 | `cursor.lastrowid` | `collection_repository.py:87`, `evaluation_repository.py:43·171·312·338·384·479`, `query_log_repository.py:137` (8곳) | `INSERT … RETURNING <pk>` + `fetchone()[0]` |
| B-2 | `INSERT OR REPLACE` | `evaluation_repository.py:582` | `ON CONFLICT (run_id, metric_key, segment) DO UPDATE SET …` |
| B-3 | `INSERT OR IGNORE` | `query_log_repository.py:258` | `ON CONFLICT (log_id, document_id) DO NOTHING` |
| B-4 | `strftime('%Y-%m-%dT…', 'now', '+9 hours')` | `evaluation_repository.py` 8곳 | `now()` |
| B-5 | `substr(created_at, 1, 10)`(날짜 자르기) | `stats_repository.py:70·185·189` | `to_char(created_at AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD')` |
| B-6 | `json_each(...)` | `collection_repository.py:162·167`, `stats_repository.py:221`(+Python 폴백 유지) | `jsonb_array_elements_text(...)` |
| B-7 | 플래그 비교 `= 1`/`= 0` | `collection_repository.py` 6, `metadata_repository.py` 3, `model_repository.py` 1, `routes/admin_departments.py` 1 (11곳) | `= TRUE`/`= FALSE` |
| B-7' | 플래그 컬럼에 정수 파라미터 | `model_repository.py:91·116·117·126`, `department_repository.py:136`, `routes/admin_users.py:276` 외 INSERT문(로그인 이력 `success`, 질의 로그 `answer_generated`, 사용자 `is_active`) | `int(x)` → `bool(x)`. 착수 시 `grep -nE "(is_active\|is_enabled\|requires_api_key\|success\|answer_generated)"`로 전수 확인 |
| B-8 | `LIKE` 대소문자 | `department_repository.py:71`, `routes/admin_users.py:95` | SQLite `LIKE`는 영문 대소문자 무시 → `ILIKE` |
| B-9 | `GROUP BY`의 비집계 컬럼 | `stats_repository.py` GROUP BY 8곳 | PostgreSQL은 SELECT의 비집계 컬럼이 GROUP BY에 있어야 한다. 테스트로 확인하고 필요한 곳만 보정 |
| B-10 | NULL 정렬 순서 | `ORDER BY …_at` 15곳 | SQLite는 ASC에서 NULL이 먼저, PostgreSQL은 나중. NULL 허용 컬럼 정렬만 `NULLS FIRST/LAST` 명시 |
| B-11 | 런타임 마이그레이션·`PRAGMA`·`sqlite_master`·`executescript` | `database.py` | 삭제(4.5) |
| B-12 | `CURRENT_TIMESTAMP` in SQL | 5곳 | PostgreSQL에서도 동작(timestamptz) — 유지 |
| B-13 | 기존 `ON CONFLICT … DO UPDATE` | `app_settings`·`evaluation`·`permissions`(2)·`session` 저장소 | 문법 호환. 충돌 대상이 실제 UNIQUE/PK인지만 확인 |
| B-14 | `scripts/check_sqlite_quality.py` | SQLite 전용 점검 스크립트 | 이관 원본 점검용으로 유지(앱 경로 아님) |

완료 시 앱 코드(`app/`, `main.py`)에서 `import sqlite3`, `PRAGMA`, `sqlite_master`, `lastrowid`, `strftime('`…`'now'`, `json_each`, `INSERT OR` 검색 결과 0건.

---

## 6. 데이터 이관

### 6.1 스크립트 (`scripts/migrate_sqlite_to_postgres.py`, 기존 파일 재사용)

이미 있는 동작: 24테이블 FK 순서·한 트랜잭션, 오프셋 있는 ISO 문자열은 그대로·`CURRENT_TIMESTAMP` 형식(오프셋 없음)은 UTC로 해석, JSON 파싱 검증 후 `jsonb`, 0/1 → boolean, 테이블별 건수 비교, identity 재설정(`sqlite_sequence` 또는 MAX), 질의 로그 KST 일별 건수 비교, `--dry-run`·`--report`.

수정할 것:
1. `from app.repositories.database import build_database_url` — 새 `database.py`가 제공하면 그대로 동작.
2. 머리말의 "Phase 2 이후 0002가 resource를 분해" 문구 삭제(아직 없음). `EXPECTED_REVISION = "0001_baseline"` 유지.
3. 그 밖의 현재 동작은 유지: 대상 리비전이 `0001_baseline`이 아니면 중단, 대상 테이블이 비어 있지 않으면 중단(시드 테이블 `tb_llm_models`는 지우고 원본 행으로 교체), 원본 FK 위반(`PRAGMA foreign_key_check`)이 있으면 중단, 대상에 없는 원본 컬럼이 있으면 중단(4.5).

### 6.2 이관 절차 (운영은 사용자가 실행, N-9·N-10)

| 단계 | 내용 | 확인 |
|---|---|---|
| 1 | 현행 앱으로 운영 SQLite 1회 기동(런타임 마이그레이션 완료 상태 보장) 후 서비스 중지, SQLite 파일 백업 | 파일 해시 기록 |
| 2 | DBA: 전용 DB `rag_chatbot_prod`·전용 계정 생성, 계정 단위 접속 수·쿼리 시간 제한(MES 서버 설정 변경 없음) | |
| 3 | `alembic upgrade 0001_baseline` | `alembic_version` |
| 4 | `migrate_sqlite_to_postgres.py --dry-run --report …` | 건수·일별 건수 일치, 중단 사유(옛 컬럼·FK 위반·JSON 오류) 없음 |
| 5 | 실제 이관 | 같은 보고서 |
| 6 | 앱 환경변수를 PostgreSQL로 전환, 새 이미지 기동 | `ensure_schema_ready()` 통과, 로그인·질의·통계 화면 확인 |
| 6-1 | (2026.10.20 추가, D-19) 관리자 계정 — 운영은 자동 생성하지 않는다. SQLite에서 넘어온 `admin`은 옛 고정 비밀번호이므로 `python scripts/create_admin.py --user-id admin --reset-password`로 바로 변경. 관리자가 없으면(새로 설치) `python scripts/create_admin.py --user-id <아이디> --name <이름>` 1회 실행 | 새 비밀번호로 관리자 로그인, 옛 비밀번호 로그인 실패 |
| 되돌리기 | 이전 이미지 + 1단계 SQLite 백업으로 복귀(새 앱은 SQLite를 지원하지 않으므로 **이미지 단위로 되돌림**) | |

운영 이관 실행은 12월(DB-ENV-7~9) 일정이다. Phase 1.5에서는 절차서와 로컬 리허설 결과만 만든다.

---

## 7. Alembic·기동·개발 환경

### 7.1 파일

- `adrag_backend/migrations/env.py` — `build_database_url()` 사용, `alembic.ini`의 URL은 비워 둔다. `alembic.ini`는 **ASCII만**(Windows cp949로 읽힘).
- `migrations/versions/0001_baseline.py` — 명시적 DDL(`op.execute`)로 24테이블·인덱스·LLM 시드 생성, `downgrade()`는 전부 DROP.
- 이후 Phase 2·3 revision은 `0002_…`부터.

### 7.2 기동

- dev: 이미지 CMD는 그대로(`python init_database.py && uvicorn --reload`). `init_database.py`가 `alembic upgrade head` → `ensure_schema_ready()`.
- 운영 이미지: CMD에 마이그레이션 없음. `main.py` lifespan에서 `ensure_schema_ready()`만 호출해 head가 아니면 기동 실패(자동 변경 금지, N-10).
- `requirements.txt`에 `psycopg[binary]`, `SQLAlchemy`, `alembic` 추가(버전은 착수 시 dev 이미지 기준으로 고정). 이미지 재빌드 필요.
- `.env.example` 신규(이름과 비밀 아닌 기본값만, DB-ENV-2). 루트 `.env`에 `POSTGRES_*` 값 추가는 **사용자가** 한다.

### 7.3 dev DB 정리 (착수 전 필수)

`rag-postgres-dev`의 기존 `neocon_rag`는 소실된 계보의 `0005_citation_images`다. **결정(2026-10-16): 새 계보는 새 DB `rag_chatbot_dev`에서 시작하고, `neocon_rag`는 지우지 않고 그대로 둔다**(3.7). 파괴적 작업이 없다.

절차:
1. `rag-backend-dev` 중지(기동 시 자동 `upgrade head`가 돌기 때문).
2. **새 DB 수동 생성** — `postgres-dev` 볼륨은 이미 초기화돼 있어 `POSTGRES_DB` 값만 바꿔서는 DB가 생기지 않는다(공식 이미지는 빈 볼륨일 때만 `POSTGRES_DB`를 만든다). `docker exec rag-postgres-dev createdb -U <POSTGRES_USER> rag_chatbot_dev`를 1회 실행.
3. 루트 `.env`에 `POSTGRES_DB=rag_chatbot_dev`, `POSTGRES_TEST_DB=rag_chatbot_test`(값은 사용자가 입력).
4. 이미지 재빌드 후 `rag-backend-dev` 기동 → `init_database.py`가 `rag_chatbot_dev`에 0001 적용.
5. 테스트 DB `rag_chatbot_test`는 처음 pytest 실행 때 conftest가 만든다. 옛 `neocon_rag_test`(소실 계보)는 쓰지 않는다.

- `neocon_rag`·`neocon_rag_test`는 참고용으로 남겨 두고, 필요 없다고 판단되면 `pg_dump` 백업 후 삭제(사용자 확인 후).
- compose healthcheck(`pg_isready -d ${POSTGRES_DB}`)는 서버 접속 가능 여부만 보므로 DB 생성 전에도 동작한다.

---

## 8. 테스트·완료 기준

### 8.1 테스트 정비

- `test_database_migrations.py`: 기준값 수정(3.5).
- Phase 2 이후 기능을 전제로 한 파일은 해당 Phase까지 **수집 제외**(`collect_ignore` 목록에 사유와 함께): `test_excel_ingest_indexing.py`, `test_excel_ingest_routing.py`, `test_excel_ingest_sample.py`, `test_ingest_queue_versions.py`, `test_answer_images.py`. 음성 2개(`test_voice_*`)는 Phase 4.5.
- SQLite 임시 파일 경로를 쓰던 테스트(13개 파일에서 `sqlite`/`db_path` 언급)는 conftest의 PostgreSQL 테스트 DB를 쓰도록 바꾼다.
- 실행 규칙: `--basetemp` 지정, 테스트 DB를 쓰는 pytest를 동시에 두 개 돌리지 않는다.

### 8.2 완료 기준

1. `test_database_migrations.py` 전부 통과(왕복·제약·값 형식·자리표시자·트랜잭션).
2. 저장소·라우트 단위 테스트: 수집 오류 0(제외 목록 외), 실패 목록을 보고서에 기준선으로 기록.
3. `migrate_sqlite_to_postgres.py --dry-run`이 로컬 SQLite에서 24테이블 건수 일치.
4. dev 컨테이너가 PostgreSQL로 기동, 수동 확인: 로그인(관리자·사용자) → 대화 주제 생성 → 문서 업로드·처리 완료 → 질의·인용 → 👍/👎 → 관리자 통계·내 활동 현황 → 평가 데이터셋 목록.
5. 5장 끝의 검색어가 앱 코드에서 0건.

---

## 9. 작업 순서·변경 파일

| 순서 | 파일 | 내용 |
|---|---|---|
| 0 | (사용자) | dev 컨테이너 중지, `rag_chatbot_dev` 생성(7.3), `.env`에 `POSTGRES_*`·`POSTGRES_TEST_DB` 추가 |
| 0' | `app/core/db_config.py`, `tests/conftest.py`, `scripts/eval_excel_retrieval.py` | DB 이름 기본값 변경(3.7) |
| 1 | `requirements.txt`, `Dockerfile*` | 의존성 추가, 이미지 재빌드 |
| 2 | `app/repositories/database.py` | 3장 전체 재작성 |
| 3 | `alembic.ini`, `migrations/env.py`, `migrations/versions/0001_baseline.py` | 4장 |
| 4 | `init_database.py`, `main.py`(lifespan), `app/core/config.py` | 7.2, `sqlite_db_path`를 선택값으로 |
| 5 | 저장소·라우트 | 5장 B-1~B-10 |
| 6 | `tests/` | 8.1 |
| 7 | `scripts/migrate_sqlite_to_postgres.py` | 6.1 |
| 8 | `app/repositories/schema.sql` 제거, `.env.example` 신규 | 1.4, 7.2 |
| 9 | `docs/design/reports/phase-1_5.md`, 이관 절차서 | 완료 기준 근거·되돌리는 방법 |

되돌리기(개발): 변경 파일을 이전 판으로 되돌리고 dev 컨테이너를 SQLite판으로 재기동하면 SQLite 파일은 그대로 남아 있다(이번 단계는 SQLite 파일을 수정하지 않음).

---

## 10. 위험

| 위험 | 대응 |
|---|---|
| 스레드별 연결 → 풀로 바뀌면서 동시 실행 수 증가(`asyncio.to_thread`) | 풀 합계 30, 운영 계정 제한 이하로. 풀 고갈 시 대기 시간(`pool_timeout`) 로그 |
| `GROUP BY`·NULL 정렬·대소문자 차이로 통계 값이 달라짐 | B-8~B-10, 통계 테스트(`test_stats_api`, `test_admin_stats_service`, `test_user_stats_service`)로 비교 |
| JSON 컬럼에 JSON이 아닌 값이 저장돼 있음 | 이관 dry-run이 행 단위로 보고, 정제 규칙은 보고 후 결정 |
| 시각 해석 차이(오프셋 없는 `CURRENT_TIMESTAMP` 값) | 스크립트 규칙(UTC 해석) + KST 일별 건수 비교 |
| 중첩 `get_connection()` 의미 변화(SQLite는 스레드당 연결 1개라 자동 공유) | ContextVar 공유로 같은 의미 유지, 계약 테스트로 확인 |

---

## 11. 결정 사항 (Q-15.1~15.8)

모두 2026-10-16 사용자 승인(제안대로). ⏳는 결정 방향은 정했으나 값·확인이 나중 단계에 남은 항목.

| ID | 질문 | 결정 |
|---|---|---|
| Q-15.1 ✅ | dev DB 처리 | **결정 10-16**: 새 DB `rag_chatbot_dev`(테스트 `rag_chatbot_test`), 기존 `neocon_rag`는 보존(3.7·7.3) |
| Q-15.2 ✅ | 플래그 컬럼을 `boolean`으로 바꿀지, `smallint 0/1`로 둘지 | `boolean` + 앱에는 1/0(3.4). 바꿀 곳 약 20곳 |
| Q-15.3 ⏳ | `DB_STATEMENT_TIMEOUT_MS` 운영 값 | MES DBA와 협의, 기본 0 |
| Q-15.4 ✅ | `tb_query_logs.feedback`를 지금 `smallint`로 두고 D-12(`rating ±1`) 정리는 Phase 4로 미룰지 | 미룸 |
| Q-15.5 ✅ | LLM 모델 시드의 OpenAI 3행(외부 AI API, 절대 규칙 7과 충돌) 유지 여부 | Phase 1.5는 현재 동작 유지(시드 4행). 이관 스크립트는 시드를 원본 행으로 교체하므로 시드를 빼도 운영 데이터에는 영향 없음 — OpenAI 모델 비활성화는 Phase 7 모델 관리(D-10)에서 결정 |
| Q-15.6 ✅ | `schema.sql`(평문 비밀번호 주석 포함)을 저장소에서 제거해도 되는지 | 제거. 관리자는 `scripts/create_admin.py` |
| Q-15.7 ✅ | 저장소 생성자의 `sqlite_db_path` 인자 77곳 정리 시점 | Phase 1.5에서는 무시만, 정리는 Phase 2 착수 때 |
| Q-15.8 ⏳ | 운영 DB 이름 `rag_chatbot_prod`와 운영 계정 이름을 고객 DBA 명명 규칙과 맞출지 | 이관 협의 때 확인. 계정도 환경별로 분리. 개발은 신규 롤 `rag_chatbot`(구현 시 결정 — 기존 `neocon` 비밀번호가 어디에도 남아 있지 않아 새 롤을 만듦, 보고서 2절) |

---

## 12. 요구사항 정의서·기능 목록에 반영할 것

- DB 이름 규칙: 개발 `rag_chatbot_dev`, 테스트 `rag_chatbot_test`, 운영 `rag_chatbot_prod`(N-9 전용 DB).
- DB-01(PostgreSQL 전환)의 산출물: `0001_baseline`(24테이블), 이관 스크립트, 이관 절차서.
- 신규 설정 `DB_STATEMENT_TIMEOUT_MS`, `DB_APPLICATION_NAME`(N-9 대응).
- 고정 관리자 계정 시드 제거 → 관리자 생성은 스크립트로(운영 절차).
