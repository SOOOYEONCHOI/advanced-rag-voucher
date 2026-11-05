"""0002 schema hardening - constraints, FK, access-pattern indexes, updated_at trigger (2026.10.16).

근거: 스키마 보완 지시서(2026-10-16) 검토 결과 → 채택 범위와 보류·불채택 사유는 docs/design/05_DB_스키마_보완안_v1.0.md
원칙: 0001_baseline은 수정하지 않는다. 기존 컬럼 삭제·이름 변경·타입 변경 없음(CHECK 추가, FK 추가, 인덱스 교체만).
운영 영향: 신규 CHECK·FK는 기존 데이터 검증을 동반한다(사전 점검 0건 확인). 운영 대형 테이블 인덱스는
          이관 직후(데이터 소량) 적용을 전제로 일반 CREATE INDEX를 쓴다. 운영 데이터가 많아진 뒤 적용한다면
          CREATE INDEX CONCURRENTLY로 바꿔 DBA와 실행한다.

Revision ID: 0002_schema_hardening
Revises: 0001_baseline
Create Date: 2026-10-16
"""
from alembic import op

revision = "0002_schema_hardening"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

# ── P1 데이터 제약: (테이블, 제약 이름, 조건) ─────────────────────────────────────
CHECKS = [
    ("tb_documents", "ck_tb_documents_counts_nonneg",
     "(total_pages IS NULL OR total_pages >= 0) AND (chunk_count IS NULL OR chunk_count >= 0)"),
    ("tb_documents", "ck_tb_documents_version_no", "version_no >= 1"),
    ("tb_query_logs", "ck_tb_query_logs_metrics_nonneg",
     "(response_time_s IS NULL OR response_time_s >= 0) AND (response_time_ms IS NULL OR response_time_ms >= 0)"
     " AND (chunks_retrieved IS NULL OR chunks_retrieved >= 0) AND (prompt_tokens IS NULL OR prompt_tokens >= 0)"
     " AND (completion_tokens IS NULL OR completion_tokens >= 0) AND (cost_usd IS NULL OR cost_usd >= 0)"),
    ("tb_eval_datasets", "ck_tb_eval_datasets_progress_nonneg", "progress_done >= 0 AND progress_total >= 0"),
    ("tb_eval_runs", "ck_tb_eval_runs_progress_nonneg", "progress_done >= 0 AND progress_total >= 0"),
    ("tb_eval_goldsets", "ck_tb_eval_goldsets_counts", "item_count >= 0 AND version >= 1"),
    ("tb_eval_run_metrics", "ck_tb_eval_run_metrics_counts_nonneg",
     "evaluated_count >= 0 AND excluded_count >= 0 AND error_count >= 0 AND total_count >= 0"),
    ("tb_eval_item_results", "ck_tb_eval_item_results_latency_nonneg", "latency_ms IS NULL OR latency_ms >= 0"),
    ("tb_spreadsheet_resource_analyses", "ck_tb_resource_analyses_confidence",
     "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)"),
    ("tb_spreadsheet_resource_analyses", "ck_tb_resource_analyses_version", "analysis_version >= 1"),
    # 현재 코드가 쓰는 단계(services/ingest_jobs.py·ingest_pipeline.py). Phase 3 큐 재설계 때 함께 넓힌다.
    ("tb_ingest_jobs", "ck_tb_ingest_jobs_current_step",
     "current_step IN ('queued', 'validate', 'parse', 'chunk', 'embed', 'index', 'completed')"),
    # value_type='json'이면 유효한 JSON이어야 한다(PostgreSQL 16 pg_input_is_valid)
    ("tb_app_settings", "ck_tb_app_settings_json_valid",
     "value_type <> 'json' OR pg_input_is_valid(setting_value, 'jsonb')"),
]

# ── P0-2 참조 무결성: 분석 결과 → 리소스(리소스 삭제·staging rollback 시 분석 행도 삭제) ──
FK_ANALYSES_RESOURCE = (
    "ALTER TABLE tb_spreadsheet_resource_analyses ADD CONSTRAINT fk_tb_resource_analyses_resource "
    "FOREIGN KEY (resource_id) REFERENCES tb_spreadsheet_resources(resource_id) ON DELETE CASCADE"
)

# ── P1 실제 조회 패턴 인덱스: (새 인덱스 DDL, 대체되어 지울 인덱스 이름, 복원 DDL) ─────────────
#   - 문서 목록: WHERE deleted_at IS NULL [AND collection_id=?] ORDER BY created_at DESC (ingest_service.list_documents)
#   - 질의 이력: WHERE user_id=? [AND session_id=?][AND collection_id=?] ORDER BY created_at DESC LIMIT n
#     (query_log_repository.get_history)
#   - 적재 작업: WHERE status IN ('queued','running') (ingest_job_repository.requeue_interrupted, collection_service)
#   idx_docs_collection은 유지: 컬렉션 삭제 FK(RESTRICT) 확인이 삭제 문서까지 포함해 collection_id로 찾는다.
#   (collection_id, created_at) 복합 인덱스는 합성 데이터 EXPLAIN에서 이득이 없어 넣지 않았다(05 보완안 4절).
INDEXES = [
    ("CREATE INDEX idx_docs_active_created ON tb_documents (created_at DESC) WHERE deleted_at IS NULL",
     None, None),
    ("CREATE INDEX idx_logs_user_created ON tb_query_logs (user_id, created_at DESC)",
     "idx_logs_user", "CREATE INDEX idx_logs_user ON tb_query_logs(user_id)"),
    ("CREATE INDEX idx_logs_session_created ON tb_query_logs (session_id, created_at DESC) "
     "WHERE session_id IS NOT NULL",
     "idx_logs_session", "CREATE INDEX idx_logs_session ON tb_query_logs(session_id)"),
    ("CREATE INDEX idx_logs_collection_created ON tb_query_logs (collection_id, created_at DESC) "
     "WHERE collection_id IS NOT NULL",
     "idx_logs_collection", "CREATE INDEX idx_logs_collection ON tb_query_logs(collection_id)"),
    ("CREATE INDEX idx_ingest_jobs_active_created ON tb_ingest_jobs (status, created_at) "
     "WHERE status IN ('queued', 'running')",
     "idx_ingest_jobs_status", "CREATE INDEX idx_ingest_jobs_status ON tb_ingest_jobs(status)"),
]

# ── P1 updated_at 자동 갱신: 애플리케이션이 값을 써도 DB가 최종 값을 보장한다 ───────────────
UPDATED_AT_TABLES = [
    "tb_departments", "tb_users", "tb_collections", "tb_documents", "tb_user_security_policies",
    "tb_query_sessions", "tb_llm_models", "tb_user_llm_settings", "tb_app_settings", "tb_ingest_jobs",
    "tb_spreadsheet_resources", "tb_spreadsheet_resource_analyses", "tb_eval_datasets", "tb_eval_settings",
]
TOUCH_FUNCTION = """
CREATE FUNCTION fn_touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$
"""


def _index_name(ddl: str) -> str:
    return ddl.split("INDEX", 1)[1].split(" ON ", 1)[0].strip()


def upgrade() -> None:
    for table, name, condition in CHECKS:
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({condition})")
    op.execute(FK_ANALYSES_RESOURCE)
    for ddl, replaced, _restore in INDEXES:
        op.execute(ddl)
        if replaced:
            op.execute(f"DROP INDEX {replaced}")
    op.execute(TOUCH_FUNCTION)
    for table in UPDATED_AT_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_touch_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION fn_touch_updated_at()"
        )


def downgrade() -> None:
    for table in reversed(UPDATED_AT_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_touch_updated_at ON {table}")
    op.execute("DROP FUNCTION IF EXISTS fn_touch_updated_at()")
    for ddl, replaced, restore in reversed(INDEXES):
        if replaced:
            op.execute(restore)
        op.execute(f"DROP INDEX IF EXISTS {_index_name(ddl)}")
    op.execute("ALTER TABLE tb_spreadsheet_resource_analyses DROP CONSTRAINT IF EXISTS fk_tb_resource_analyses_resource")
    for table, name, _condition in reversed(CHECKS):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
