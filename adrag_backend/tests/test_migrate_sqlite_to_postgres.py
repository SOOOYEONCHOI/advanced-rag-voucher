"""이관 스크립트(scripts/migrate_sqlite_to_postgres.py) 테스트 (2026.09.29 Phase 1.5).

원본 파일 DB는 테스트 안에서 최소 스키마로 만든다(24개 테이블 존재, 데이터가 있는 테이블만 컬럼 정의).
"""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

from app.core.db_config import get_database_settings
from app.repositories.database import build_database_url, get_database_manager

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_sqlite_to_postgres.py"
spec = importlib.util.spec_from_file_location("migrate_script", SCRIPT)
migrate_script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate_script)

DATA_TABLES = {
    "tb_departments": "department_id TEXT PRIMARY KEY, department_name TEXT, allowed_topics TEXT, is_active INTEGER, created_at TEXT, updated_at TEXT",
    "tb_users": "user_id TEXT PRIMARY KEY, user_pwd TEXT, user_name TEXT, department_id TEXT, blocked_topics TEXT, role TEXT, is_active INTEGER, created_at TEXT, updated_at TEXT",
    "tb_collections": "collection_id INTEGER PRIMARY KEY AUTOINCREMENT, display_name TEXT, qdrant_name TEXT, is_active INTEGER, created_at TEXT, updated_at TEXT",
    "tb_ingest_jobs": "job_id TEXT PRIMARY KEY, status TEXT, current_step TEXT, request_json TEXT, created_by TEXT, created_at TEXT, updated_at TEXT",
    "tb_query_logs": "log_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, query_text TEXT, answer_generated INTEGER, extracted_keywords TEXT, created_at TEXT",
    "tb_llm_models": "model_id TEXT PRIMARY KEY, model_name TEXT, provider TEXT, requires_api_key INTEGER, is_enabled INTEGER, sort_order INTEGER",
}


def _build_source(path: Path, keywords_json: str = '["검사"]') -> Path:
    conn = sqlite3.connect(path)
    for table in migrate_script.TABLE_ORDER:
        conn.execute(f"CREATE TABLE {table} ({DATA_TABLES.get(table, 'placeholder_id INTEGER')})")
    conn.execute("INSERT INTO tb_departments VALUES ('D001', '품질팀', '[\"안전\"]', 1, '2026-08-01T09:00:00+09:00', '2026-08-01T09:00:00+09:00')")
    conn.execute("INSERT INTO tb_users VALUES ('u1', 'hash', '홍', 'D001', '[]', 'user', 1, '2026-08-01T09:00:00+09:00', '2026-08-01T09:00:00+09:00')")
    conn.execute("INSERT INTO tb_collections VALUES (3, 'c', 'q_c', 1, '2026-08-01T09:00:00+09:00', '2026-08-01T09:00:00+09:00')")
    conn.execute("UPDATE sqlite_sequence SET seq = 7 WHERE name = 'tb_collections'")
    # SQLite CURRENT_TIMESTAMP(UTC, 오프셋 없음) 형식
    conn.execute("INSERT INTO tb_ingest_jobs VALUES ('j1', 'completed', 'completed', '{\"a\": 1}', 'u1', '2026-08-01 00:30:00', '2026-08-01 00:30:00')")
    conn.execute(f"INSERT INTO tb_query_logs VALUES (1, 'u1', 'q', 1, ?, '2026-08-01T23:59:59+09:00')", (keywords_json,))
    conn.execute("INSERT INTO tb_llm_models VALUES ('local', 'Local-LLM', 'local', 0, 1, 0)")
    conn.commit()
    conn.close()
    return path


@pytest.fixture(scope="module", autouse=True)
def _baseline_schema(postgres_schema):
    # 2026.10.01 추가 - 이관은 0001 구조에 한 뒤 head로 올린다(0002가 resource를 분해·이관).
    from alembic import command

    command.downgrade(postgres_schema, migrate_script.EXPECTED_REVISION)
    yield
    command.upgrade(postgres_schema, "head")


@pytest.fixture(autouse=True)
def _empty_target(_baseline_schema):
    # conftest가 넣는 테스트 전용 admin 계정 제거 → alembic upgrade 직후와 같은 빈 상태
    get_database_manager().execute_update("DELETE FROM tb_users")


@pytest.fixture(autouse=True)
def _no_placeholder_column(monkeypatch):
    original = migrate_script.pg_columns

    def pg_columns(conn, table):
        columns = original(conn, table)
        columns.setdefault("placeholder_id", "integer")
        return columns

    monkeypatch.setattr(migrate_script, "pg_columns", pg_columns)


def _url():
    return build_database_url(get_database_settings())


def test_migration_converts_types_and_resets_identity(tmp_path):
    source = _build_source(tmp_path / "src.db")
    report = migrate_script.migrate(source, _url(), dry_run=False)
    assert "이관 커밋 완료" in report[-1]

    db = get_database_manager()
    job = db.execute_query("SELECT created_at, request_json FROM tb_ingest_jobs WHERE job_id = 'j1'")[0]
    assert job["created_at"] == "2026-08-01T09:30:00+09:00"      # UTC 문자열 → 같은 시각의 KST
    log = db.execute_query("SELECT created_at, answer_generated, extracted_keywords FROM tb_query_logs")[0]
    assert log["created_at"] == "2026-08-01T23:59:59+09:00"      # KST ISO는 그대로
    assert log["answer_generated"] == 1
    assert db.execute_query("SELECT jsonb_typeof(extracted_keywords) FROM tb_query_logs")[0][0] == "array"
    assert db.execute_query("SELECT is_active FROM tb_departments")[0][0] == 1
    # identity: sqlite_sequence(7) 기준 → 다음 ID 8 (삭제된 ID 재사용 방지)
    new_id = db.execute_query(
        "INSERT INTO tb_collections (display_name, qdrant_name) VALUES ('n', 'q_n') RETURNING collection_id"
    )[0][0]
    assert new_id == 8
    assert db.execute_query("SELECT COUNT(*) FROM tb_llm_models")[0][0] == 1  # 시드는 원본 데이터로 교체


def test_migration_failure_rolls_back_everything(tmp_path):
    source = _build_source(tmp_path / "bad.db", keywords_json="not json")
    with pytest.raises(migrate_script.MigrationError, match="tb_query_logs.extracted_keywords"):
        migrate_script.migrate(source, _url(), dry_run=False)
    db = get_database_manager()
    for table in ("tb_departments", "tb_users", "tb_collections", "tb_ingest_jobs"):
        assert db.execute_query(f"SELECT COUNT(*) FROM {table}")[0][0] == 0
    assert db.execute_query("SELECT COUNT(*) FROM tb_llm_models")[0][0] == 4  # 시드 원상 유지


def test_dry_run_leaves_target_unchanged(tmp_path):
    source = _build_source(tmp_path / "src.db")
    report = migrate_script.migrate(source, _url(), dry_run=True)
    assert "dry-run" in report[-1]
    assert get_database_manager().execute_query("SELECT COUNT(*) FROM tb_users")[0][0] == 0


def test_migration_refuses_non_empty_target(tmp_path):
    get_database_manager().execute_update("INSERT INTO tb_departments (department_id, department_name) VALUES ('X', 'x')")
    with pytest.raises(migrate_script.MigrationError, match="비어 있지 않습니다"):
        migrate_script.migrate(_build_source(tmp_path / "src.db"), _url(), dry_run=False)
