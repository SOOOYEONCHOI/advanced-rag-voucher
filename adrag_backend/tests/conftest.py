"""테스트 공통 설정 — PostgreSQL 테스트 DB (2026.09.29 Phase 1.5).

- 테스트 DB: 환경변수 TEST_DATABASE_URL, 없으면 .env의 POSTGRES_*로 접속하되 DB 이름은
  POSTGRES_TEST_DB(기본 ``{POSTGRES_DB}_test``). 운영·개발 DB는 건드리지 않는다.
- 세션 시작 시 테스트 DB가 없으면 만들고, Alembic으로 스키마를 base → head 재생성한다.
- 테스트마다 업무 테이블을 비우고(TRUNCATE … RESTART IDENTITY) 기본 시드(LLM 모델)를 다시 넣어 격리한다.
- PostgreSQL에 접속할 수 없으면 세션을 실패시킨다(작업지시서: DB 테스트는 PostgreSQL에서 실행).
로컬 실행: WSL에서 ``docker-compose -f docker-compose.dev.yml up -d postgres-dev`` 후 pytest.
"""

import os
from pathlib import Path

import pytest
from dotenv import dotenv_values
from sqlalchemy.engine import URL, make_url

BACKEND_ROOT = Path(__file__).resolve().parents[1]
_ENV = {**dotenv_values(BACKEND_ROOT.parent / ".env"), **os.environ}

# 2026.10.16 추가 - Phase 1.5 재구현(설계 8.1): 아직 재구현하지 않은 Phase의 코드를 전제로 한 테스트는
#   해당 Phase까지 수집하지 않는다(app.ingest·문서 버전 테이블·음성 설정 없음).
collect_ignore = [
    # 2026.10.16 - 옛 계보 Phase 2 설계(해시 공유 asset·placement 분해, 그 계보의 0002) 명세라 현행 결정(P2-4·P2-5)과 다름.
    #   현행 Phase 2 검증은 test_excel_ingest_pipeline_sample.py·test_ingest_records.py가 대체한다.
    "test_excel_ingest_indexing.py",
    "test_excel_ingest_sample.py",
    "test_spreadsheet_pipeline_integration.py",
    "test_ingest_queue_versions.py",   # Phase 3 (작업 큐·버전 전환)
    # 2026.10.19 - test_answer_images.py는 Phase 4-A에서 현행 테이블 기준으로 다시 써서 수집한다
]


def _test_database_url() -> URL:
    if _ENV.get("TEST_DATABASE_URL"):
        return make_url(_ENV["TEST_DATABASE_URL"])
    # 2026.10.16 수정 - DB 이름 규칙(설계 3.7): 테스트 DB 기본값 rag_chatbot_test
    return URL.create(
        "postgresql+psycopg",
        username=_ENV.get("POSTGRES_USER") or "rag_chatbot",
        password=_ENV.get("POSTGRES_PASSWORD") or None,
        host=_ENV.get("POSTGRES_HOST") or "localhost",
        port=int(_ENV.get("POSTGRES_PORT") or 5432),
        database=_ENV.get("POSTGRES_TEST_DB") or "rag_chatbot_test",
    )


TEST_DB_URL = _test_database_url()
if not TEST_DB_URL.database or not TEST_DB_URL.database.endswith("_test"):
    raise RuntimeError(f"테스트 DB 이름은 '_test'로 끝나야 합니다: {TEST_DB_URL.database!r}")
# 앱 설정(get_settings)이 테스트 DB를 보도록 설정 로드 전에 주입한다.
os.environ["DATABASE_URL"] = TEST_DB_URL.render_as_string(hide_password=False)

# 2026.10.01 수정 - Phase 2: 비울 테이블을 고정 목록 대신 현재 스키마에서 찾는다
#   (마이그레이션 버전을 내렸다 올리는 테스트에서도 존재하는 테이블만 비운다).
_BUSINESS_TABLES_SQL = (
    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename ~ '^tb_' ORDER BY tablename"
)


def _ensure_database_exists() -> None:
    import psycopg
    from psycopg import sql

    admin = TEST_DB_URL.set(drivername="postgresql", database="postgres")
    with psycopg.connect(admin.render_as_string(hide_password=False), autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB_URL.database,)).fetchone()
        if not exists:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB_URL.database)))


def _alembic_config():
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    # ConfigParser 보간 문자(%) 이스케이프
    config.set_main_option("sqlalchemy.url", TEST_DB_URL.render_as_string(hide_password=False).replace("%", "%%"))
    return config


@pytest.fixture(scope="session", autouse=True)
def postgres_schema():
    from alembic import command

    try:
        _ensure_database_exists()
    except Exception as exc:  # pragma: no cover - 환경 문제
        pytest.exit(f"PostgreSQL 테스트 DB에 접속할 수 없습니다({TEST_DB_URL.render_as_string()}): {exc}", returncode=2)
    config = _alembic_config()
    # 2026.11.19(sooyeon.choi) 추가 - 이전 세션이 남긴 행 때문에 downgrade 보호 조건
    #   (0012 batch_eval 질의 로그, 0013 law/general 문항)이 막히지 않도록 테스트 DB 업무 테이블을 먼저 비운다
    _truncate_leftover_rows()
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield config
    from app.repositories.database import close_database_manager

    close_database_manager()


_clean_engine = None


def _truncate_leftover_rows() -> None:
    with _test_engine().begin() as conn:
        if not conn.exec_driver_sql("SELECT current_database()").scalar().endswith("_test"):
            raise RuntimeError("테스트 DB가 아닌 곳을 비우려 했습니다")
        tables = [row[0] for row in conn.exec_driver_sql(_BUSINESS_TABLES_SQL)]
        if tables:
            conn.exec_driver_sql(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")


def _test_engine():
    """2026.10.07 수정 - 정리용 엔진은 앱 설정이 아니라 TEST_DB_URL로 고정한다.
    (일부 테스트가 app.core.config를 stub으로 바꿔 끼우면 앱 설정이 다른 DB를 가리킬 수 있다.)"""
    global _clean_engine
    if _clean_engine is None:
        from sqlalchemy import create_engine

        _clean_engine = create_engine(TEST_DB_URL, pool_size=1, max_overflow=0, pool_pre_ping=True)
    return _clean_engine


@pytest.fixture(autouse=True)
def clean_tables(postgres_schema):
    """테스트마다 업무 테이블을 비우고 기본 시드를 복원한다."""
    with _test_engine().begin() as conn:
        database = conn.exec_driver_sql("SELECT current_database()").scalar()
        if not database.endswith("_test"):
            raise RuntimeError(f"테스트 DB가 아닌 곳을 비우려 했습니다: {database!r}")
        tables = [row[0] for row in conn.exec_driver_sql(_BUSINESS_TABLES_SQL)]
        if not tables:
            raise RuntimeError("테스트 DB에 업무 테이블이 없습니다(스키마가 head가 아님).")
        conn.exec_driver_sql(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")
        conn.exec_driver_sql(
            "INSERT INTO tb_llm_models (model_id, model_name, provider, requires_api_key, is_enabled, sort_order) VALUES "
            "('local', 'Local-LLM', 'local', FALSE, TRUE, 0),"
            "('gpt-4o-mini', 'OpenAI GPT-4o-mini', 'openai', TRUE, TRUE, 1),"
            "('gpt-4.1', 'OpenAI GPT-4.1', 'openai', TRUE, TRUE, 2),"
            "('gpt-4.1-mini', 'OpenAI GPT-4.1-mini', 'openai', TRUE, TRUE, 3)"
        )
        # 기존 테스트는 이전 스키마가 자동 생성하던 'admin' 계정을 전제로 작성되어 있어 테스트 DB에만 재현한다.
        # (운영 기준 스키마에서는 고정 관리자 시드를 제거했다 — scripts/create_admin.py 사용)
        conn.exec_driver_sql(
            "INSERT INTO tb_users (user_id, user_pwd, user_name, role) VALUES ('admin', '!test-only-unusable', '관리자', 'admin')"
        )
    yield
