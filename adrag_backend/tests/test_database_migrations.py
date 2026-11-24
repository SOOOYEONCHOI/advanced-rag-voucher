"""PostgreSQL 스키마(Alembic)와 DB 계층 호환 동작 테스트 (2026.09.29 Phase 1.5, 2026.10.16 재구현 기준으로 갱신).

이전 파일 DB 기동 시 마이그레이션 테스트를 대체한다.
"""

import json
import re

import pytest
from alembic import command
from sqlalchemy.exc import IntegrityError

from app.repositories import database
from app.repositories.database import Row, get_database_manager, to_driver_sql

# 2026.10.16 수정 - Phase 1.5 재구현(설계 docs/design/phase-1_5_PostgreSQL_전환_설계.md 3.5):
#   현재 소스 기준 0001_baseline = SQLite schema.sql 24테이블
# 2026.10.16 수정 - 0002_schema_hardening(테이블 추가 없음), 0003(Phase 2): 버전·청크·청크↔사진·흐름도·staging +5
# 2026.10.19 수정 - 0004(UI-12 모델명)·0005(최신본 변경): 테이블 추가 없음
# 2026.11.06(sooyeon.choi) 수정 - 0006(이전 버전 복원): tb_embedding_profiles·tb_document_version_activations +2
# 2026.11.06(sooyeon.choi) 수정 - 0007(적용 이력 FK ON DELETE CASCADE): 테이블 추가 없음
# 2026.11.12(sooyeon.choi) 도면 파싱 기능 추가 - 0008(답변 피드백 의견): 테이블 추가 없음,
#   0009(채팅 시작 화면 질문): tb_collection_questions +1, 0010(도면 작업 단계): 테이블 추가 없음
TABLE_COUNT = 32
HEAD = "0010_drawing_ingest_steps"


def _tables(db):
    return {
        r["table_name"]
        for r in db.execute_query(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name LIKE 'tb!_%' ESCAPE '!'"
        )
    }


def test_upgrade_downgrade_upgrade_roundtrip(postgres_schema):
    db = get_database_manager()
    assert len(_tables(db)) == TABLE_COUNT

    command.downgrade(postgres_schema, "base")
    assert _tables(db) == set()

    command.upgrade(postgres_schema, "head")
    assert len(_tables(db)) == TABLE_COUNT
    assert db.execute_query("SELECT version_num FROM alembic_version")[0][0] == HEAD
    assert database.ensure_schema_ready() == HEAD
    # 새로 만든 스키마: LLM 모델 시드 4건, 고정 관리자 계정 시드 없음(F01)
    assert db.execute_query("SELECT COUNT(*) FROM tb_llm_models")[0][0] == 4
    assert db.execute_query("SELECT COUNT(*) FROM tb_users")[0][0] == 0


def test_duplicate_indexes_removed():
    names = {r[0] for r in get_database_manager().execute_query("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")}
    assert not {"idx_collections_qdrant", "idx_depts_department_name", "idx_llm_settings_user_collection"} & names
    assert "idx_logs_feedback" in names


def _insert_user(db, user_id="u1"):
    db.execute_update(
        "INSERT INTO tb_users (user_id, user_pwd, role, is_active) VALUES (?, 'x', 'user', TRUE)", (user_id,)
    )


@pytest.mark.parametrize(
    "sql,params",
    [
        ("INSERT INTO tb_departments (department_id, department_name, allowed_topics) VALUES ('D1', 'd', ?)", ('{"a": 1}',)),
        ("INSERT INTO tb_departments (department_id, department_name, allowed_topics) VALUES ('D1', 'd', ?)", ("not json",)),
        ("INSERT INTO tb_ingest_jobs (job_id, status, request_json) VALUES ('j', 'unknown', '{}')", ()),
        ("INSERT INTO tb_ingest_jobs (job_id, status, request_json) VALUES ('j', 'queued', '[]')", ()),
        ("INSERT INTO tb_documents (document_id, collection_id, source_path, file_size) VALUES ('d', 1, 'p', -1)", ()),
    ],
)
def test_constraints_reject_invalid_rows(sql, params):
    with pytest.raises(Exception):
        get_database_manager().execute_update(sql, params)


def test_eval_item_results_unique_per_run_and_question():
    db = get_database_manager()
    with db.get_connection() as conn:
        cid = conn.execute("INSERT INTO tb_collections (display_name, qdrant_name) VALUES ('c', 'c') RETURNING collection_id").fetchone()[0]
        did = conn.execute("INSERT INTO tb_eval_datasets (name, collection_id) VALUES ('d', ?) RETURNING dataset_id", (cid,)).fetchone()[0]
        gid = conn.execute(
            "INSERT INTO tb_eval_goldsets (dataset_id, version, item_count, items_snapshot_json) VALUES (?, 1, 0, '[]') RETURNING goldset_id",
            (did,),
        ).fetchone()[0]
        rid = conn.execute("INSERT INTO tb_eval_runs (goldset_id) VALUES (?) RETURNING run_id", (gid,)).fetchone()[0]
        conn.execute("INSERT INTO tb_eval_item_results (run_id, qa_id) VALUES (?, 1)", (rid,))
    with pytest.raises(IntegrityError):
        db.execute_update("INSERT INTO tb_eval_item_results (run_id, qa_id) VALUES (?, 1)", (rid,))


def test_ingest_job_creator_fk_sets_null_on_user_delete():
    db = get_database_manager()
    _insert_user(db)
    db.execute_update("INSERT INTO tb_ingest_jobs (job_id, status, request_json, created_by) VALUES ('j1', 'queued', '{}', 'u1')")
    db.execute_update("DELETE FROM tb_users WHERE user_id = 'u1'")
    assert db.execute_query("SELECT created_by FROM tb_ingest_jobs WHERE job_id = 'j1'")[0][0] is None


# ── DB 계층 호환 동작 ────────────────────────────────────────────────────────────

def test_rows_keep_legacy_value_formats():
    db = get_database_manager()
    db.execute_update(
        "INSERT INTO tb_departments (department_id, department_name, allowed_topics, is_active, created_at) "
        "VALUES ('D1', '품질팀', ?, TRUE, ?)",
        (json.dumps(["안전"], ensure_ascii=False), "2026-09-29T01:02:03+00:00"),
    )
    row = db.execute_query("SELECT * FROM tb_departments WHERE department_id = ?", ("D1",))[0]
    assert row["created_at"] == "2026-09-29T10:02:03+09:00"          # timestamptz → KST ISO 문자열
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+09:00", row["updated_at"])
    assert json.loads(row["allowed_topics"]) == ["안전"]              # jsonb → JSON 문자열
    assert row["is_active"] == 1                                       # boolean → 1/0
    assert dict(row)["department_name"] == "품질팀" and row[1] == "품질팀"
    assert "department_id" in row.keys()


def test_placeholder_translation_keeps_literals():
    assert to_driver_sql("SELECT '%?' , ? WHERE a LIKE ?") == "SELECT '%%?' , %s WHERE a LIKE %s"
    db = get_database_manager()
    db.execute_update("INSERT INTO tb_departments (department_id, department_name) VALUES ('D1', '100% 품질')")
    assert db.execute_query("SELECT COUNT(*) FROM tb_departments WHERE department_name LIKE '100%'")[0][0] == 1
    assert db.execute_query("SELECT COUNT(*) FROM tb_departments WHERE department_name ILIKE ?", ("%품질",))[0][0] == 1


def test_nested_calls_share_transaction_and_roll_back_together():
    db = get_database_manager()
    with pytest.raises(RuntimeError):
        with db.get_connection() as conn:
            conn.execute("INSERT INTO tb_departments (department_id, department_name) VALUES ('D1', 'a')")
            db.execute_update("INSERT INTO tb_departments (department_id, department_name) VALUES ('D2', 'b')")
            # 같은 트랜잭션이므로 바깥 블록 커밋 전에도 보인다
            assert db.execute_query("SELECT COUNT(*) FROM tb_departments")[0][0] == 2
            raise RuntimeError("rollback")
    assert db.execute_query("SELECT COUNT(*) FROM tb_departments")[0][0] == 0


def test_lastrowid_is_rejected_in_favor_of_returning():
    with get_database_manager().get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO tb_collections (display_name, qdrant_name) VALUES ('c', 'c') RETURNING collection_id")
        assert cursor.fetchone()["collection_id"] == 1
        with pytest.raises(NotImplementedError):
            _ = cursor.lastrowid


def test_row_object_supports_legacy_row_protocol():
    row = Row(["a", "b"], [1, True])
    assert row["a"] == 1 and row[1] == 1 and list(row) == [1, 1] and dict(row) == {"a": 1, "b": 1}


# ── 0002 스키마 보완 (2026.10.16, docs/design/05_DB_스키마_보완안_v1.0.md) ─────────────────────

# 2026.10.16 수정 - 0003부터 확정 리소스는 문서 FK·staging 금지 → 문서와 committed 리소스를 함께 만든다
_DOC_AND_RESOURCE_SQL = (
    "INSERT INTO tb_collections (display_name, qdrant_name) VALUES ('c', 'c');"
    "INSERT INTO tb_documents (document_id, collection_id, source_path) VALUES ('d', 1, 'p');"
    "INSERT INTO tb_spreadsheet_resources (resource_id, document_id, parse_job_id, resource_type, resource_path,"
    " content_hash, mime_type, file_size, status) VALUES ('r', 'd', 'p', 'image', 'x', 'h', 'image/png', 1, 'committed')"
)

@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO tb_collections (display_name, qdrant_name) VALUES ('c', 'c');"
        "INSERT INTO tb_documents (document_id, collection_id, source_path, chunk_count) VALUES ('d', 1, 'p', -1)",
        "INSERT INTO tb_collections (display_name, qdrant_name) VALUES ('c', 'c');"
        "INSERT INTO tb_documents (document_id, collection_id, source_path, version_no) VALUES ('d', 1, 'p', 0)",
        "INSERT INTO tb_users (user_id, user_pwd) VALUES ('u', 'x');"
        "INSERT INTO tb_query_logs (user_id, query_text, response_time_ms) VALUES ('u', 'q', -5)",
        "INSERT INTO tb_ingest_jobs (job_id, status, current_step, request_json) VALUES ('j', 'queued', 'warp', '{}')",
        "INSERT INTO tb_app_settings (setting_key, setting_value, value_type) VALUES ('k', 'not json', 'json')",
        _DOC_AND_RESOURCE_SQL + ";"
        "INSERT INTO tb_spreadsheet_resource_analyses (analysis_id, resource_id, document_id, analysis_version, method,"
        " status, confidence) VALUES ('a', 'r', 'd', 1, 'ocr', 'completed', 1.5)",
        "INSERT INTO tb_spreadsheet_resource_analyses (analysis_id, resource_id, document_id, analysis_version, method,"
        " status) VALUES ('a', 'no-such-resource', 'd', 1, 'ocr', 'pending')",
    ],
)
def test_hardening_constraints_reject_invalid_rows(sql):
    with pytest.raises(Exception):
        with get_database_manager().get_connection() as conn:
            for statement in sql.split(";"):
                conn.execute(statement)


def test_hardening_allows_valid_rows_and_json_setting():
    db = get_database_manager()
    db.execute_update("INSERT INTO tb_app_settings (setting_key, setting_value, value_type) VALUES ('k', '[\"a\"]', 'json')")
    db.execute_update("INSERT INTO tb_app_settings (setting_key, setting_value, value_type) VALUES ('n', 'not json', 'str')")
    assert db.execute_query("SELECT count(*) FROM tb_app_settings")[0][0] == 2


def test_resource_delete_cascades_to_analyses():
    db = get_database_manager()
    with db.get_connection() as conn:
        for statement in _DOC_AND_RESOURCE_SQL.split(";"):
            conn.execute(statement)
    db.execute_update(
        "INSERT INTO tb_spreadsheet_resource_analyses (analysis_id, resource_id, document_id, analysis_version, method,"
        " status) VALUES ('a', 'r', 'd', 1, 'ocr', 'pending')"
    )
    db.execute_update("DELETE FROM tb_spreadsheet_resources WHERE resource_id = 'r'")
    assert db.execute_query("SELECT count(*) FROM tb_spreadsheet_resource_analyses")[0][0] == 0


def test_updated_at_trigger_overrides_stale_application_value():
    db = get_database_manager()
    db.execute_update("INSERT INTO tb_departments (department_id, department_name) VALUES ('D1', '품질팀')")
    db.execute_update(
        "UPDATE tb_departments SET department_name = '품질1팀', updated_at = ? WHERE department_id = 'D1'",
        ("2000-01-01T00:00:00+09:00",),
    )
    row = db.execute_query("SELECT updated_at, created_at FROM tb_departments WHERE department_id = 'D1'")[0]
    assert row["updated_at"] != "2000-01-01T00:00:00+09:00" and row["updated_at"] >= row["created_at"]


def test_access_pattern_indexes_replace_single_column_ones():
    names = {r[0] for r in get_database_manager().execute_query("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")}
    assert {
        "idx_docs_active_created", "idx_logs_user_created",
        "idx_logs_session_created", "idx_logs_collection_created", "idx_ingest_jobs_active_created",
    } <= names
    assert not {"idx_logs_user", "idx_logs_session", "idx_logs_collection", "idx_ingest_jobs_status"} & names
    assert "idx_docs_collection" in names  # 컬렉션 삭제 FK 확인용으로 유지


def test_hardening_downgrade_restores_baseline_and_upgrades_again(postgres_schema):
    db = get_database_manager()
    command.downgrade(postgres_schema, "0001_baseline")
    names = {r[0] for r in db.execute_query("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")}
    assert {"idx_logs_user", "idx_ingest_jobs_status"} <= names and "idx_logs_user_created" not in names
    assert db.execute_query("SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'trg_tb_%_touch_updated_at'")[0][0] == 0
    command.upgrade(postgres_schema, "head")
    assert database.ensure_schema_ready() == HEAD


# ── 0003 버전·청크·사진·흐름도·staging 분리 (2026.10.16 Phase 2, reports/phase-2-plan.md) ──────────

def _seed_0002_rows(db):
    with db.get_connection() as conn:
        conn.execute("INSERT INTO tb_collections (display_name, qdrant_name) VALUES ('c', 'c')")
        conn.execute("INSERT INTO tb_documents (document_id, collection_id, source_path, parser_type) "
                     "VALUES ('d1', 1, 'instance/data/d1.xlsx', 'excel_ingest')")
        conn.execute("INSERT INTO tb_documents (document_id, collection_id, source_path, deleted_at) "
                     "VALUES ('d2', 1, 'instance/data/d2.pdf', now())")
        for rid, status in (("s1", "staging"), ("c1", "committed")):
            conn.execute(
                "INSERT INTO tb_spreadsheet_resources (resource_id, document_id, parse_job_id, resource_type,"
                " resource_path, content_hash, mime_type, file_size, status)"
                " VALUES (?, 'd1', 'p1', 'image', 'x', 'h', 'image/png', 1, ?)", (rid, status))


def test_0003_migrates_documents_and_moves_staging_both_ways(postgres_schema):
    db = get_database_manager()
    command.downgrade(postgres_schema, "0002_schema_hardening")
    _seed_0002_rows(db)
    command.upgrade(postgres_schema, "head")
    versions = {r["document_id"]: (r["version_no"], r["status"], r["processing_engine"])
                for r in db.execute_query("SELECT * FROM tb_document_versions")}
    assert versions == {"d1": (1, "active", "excel_ingest"), "d2": (1, "retired", "docling")}
    assert [r[0] for r in db.execute_query("SELECT resource_id FROM tb_spreadsheet_staging_resources")] == ["s1"]
    assert [r[0] for r in db.execute_query("SELECT resource_id FROM tb_spreadsheet_resources")] == ["c1"]
    command.downgrade(postgres_schema, "0002_schema_hardening")
    rows = db.execute_query("SELECT resource_id, status FROM tb_spreadsheet_resources ORDER BY 1")
    assert [(r[0], r[1]) for r in rows] == [("c1", "committed"), ("s1", "staging")]
    command.upgrade(postgres_schema, "head")


def test_0003_stops_on_committed_resource_without_document(postgres_schema):
    db = get_database_manager()
    command.downgrade(postgres_schema, "0002_schema_hardening")
    db.execute_update(
        "INSERT INTO tb_spreadsheet_resources (resource_id, document_id, parse_job_id, resource_type,"
        " resource_path, content_hash, mime_type, file_size, status)"
        " VALUES ('o1', 'no-doc', 'p', 'image', 'x', 'h', 'image/png', 1, 'committed')")
    with pytest.raises(RuntimeError, match="문서 행이 없는 확정 리소스 1건"):
        command.upgrade(postgres_schema, "head")
    db.execute_update("DELETE FROM tb_spreadsheet_resources WHERE resource_id = 'o1'")
    command.upgrade(postgres_schema, "head")
    assert database.ensure_schema_ready() == HEAD


def test_document_physical_delete_cascades_phase2_rows():
    db = get_database_manager()
    with db.get_connection() as conn:
        conn.execute("INSERT INTO tb_collections (display_name, qdrant_name) VALUES ('c', 'c')")
        conn.execute("INSERT INTO tb_documents (document_id, collection_id, source_path) VALUES ('d', 1, 'p')")
        conn.execute("INSERT INTO tb_document_versions (document_id, version_no, source_path) VALUES ('d', 1, 'p')")
        conn.execute(
            "INSERT INTO tb_chunks (chunk_id, document_id, version_no, collection_id, point_id, source_key, chunk_text)"
            " VALUES ('d:1:k#0', 'd', 1, 1, '00000000-0000-0000-0000-000000000001', 'k', 't')")
        conn.execute(
            "INSERT INTO tb_spreadsheet_resources (resource_id, document_id, parse_job_id, resource_type,"
            " resource_path, content_hash, mime_type, file_size, status)"
            " VALUES ('r', 'd', 'p', 'image', 'x', 'h', 'image/png', 1, 'committed')")
        conn.execute("INSERT INTO tb_chunk_resources (chunk_id, resource_id) VALUES ('d:1:k#0', 'r')")
        conn.execute("INSERT INTO tb_flow_graphs (document_id, version_no, sheet_name) VALUES ('d', 1, 's')")
        # 2026.11.06(sooyeon.choi) 추가 - 0006 적용 이력(baseline)이 있어도 대화 주제 삭제가 막히지 않아야 한다(0007)
        conn.execute(
            "INSERT INTO tb_document_version_activations (document_id, to_version_no, activation_revision, operation_type)"
            " VALUES ('d', 1, 1, 'baseline')")
    db.execute_update("DELETE FROM tb_documents WHERE collection_id = 1")  # 대화 주제 삭제 경로(물리 삭제, collection_service)
    counts = db.execute_query(
        "SELECT (SELECT count(*) FROM tb_document_versions) + (SELECT count(*) FROM tb_chunks)"
        " + (SELECT count(*) FROM tb_chunk_resources) + (SELECT count(*) FROM tb_flow_graphs)"
        " + (SELECT count(*) FROM tb_spreadsheet_resources)"
        " + (SELECT count(*) FROM tb_document_version_activations)")[0][0]
    assert counts == 0


def test_only_one_active_version_per_document():
    db = get_database_manager()
    with db.get_connection() as conn:
        conn.execute("INSERT INTO tb_collections (display_name, qdrant_name) VALUES ('c', 'c')")
        conn.execute("INSERT INTO tb_documents (document_id, collection_id, source_path) VALUES ('d', 1, 'p')")
        conn.execute("INSERT INTO tb_document_versions (document_id, version_no, source_path) VALUES ('d', 1, 'p')")
    with pytest.raises(IntegrityError):
        db.execute_update("INSERT INTO tb_document_versions (document_id, version_no, source_path) VALUES ('d', 2, 'p')")
