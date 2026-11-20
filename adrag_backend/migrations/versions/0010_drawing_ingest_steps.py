"""0010_drawing_ingest_steps (2026.11.12(sooyeon.choi) 도면 파싱 기능 추가).

- tb_ingest_jobs.current_step 제약에 도면 처리 단계 4개를 추가한다(0006 제약 확장, 값 추가만):
  drawing_convert · drawing_extract · drawing_render · drawing_store

downgrade: 도면 단계에 머문 작업 행을 기존 단계로 바꾼 뒤(완료 → completed, 그 밖 → parse) 0006 제약으로 되돌린다.
  도면 작업을 그 단계부터 재시도하는 정보는 사라진다(재시도 시 원본 저장부터 다시 처리).

Revision ID: 0010_drawing_ingest_steps
Revises: 0009_collection_start_questions
Create Date: 2026-11-12
"""
from alembic import op

revision = "0010_drawing_ingest_steps"
down_revision = "0009_collection_start_questions"
branch_labels = None
depends_on = None

STEPS_BEFORE = ("queued", "validate", "parse", "chunk", "embed", "index", "completed", "snapshot", "activate")
DRAWING_STEPS = ("drawing_convert", "drawing_extract", "drawing_render", "drawing_store")
STEPS_AFTER = STEPS_BEFORE + DRAWING_STEPS


def _set_step_constraint(steps) -> None:
    values = ", ".join(f"'{s}'" for s in steps)
    op.execute(
        "ALTER TABLE tb_ingest_jobs DROP CONSTRAINT IF EXISTS ck_tb_ingest_jobs_current_step; "
        "ALTER TABLE tb_ingest_jobs ADD CONSTRAINT ck_tb_ingest_jobs_current_step "
        f"CHECK (current_step IN ({values}))"
    )


def upgrade() -> None:
    _set_step_constraint(STEPS_AFTER)


def downgrade() -> None:
    drawing = ", ".join(f"'{s}'" for s in DRAWING_STEPS)
    op.execute(
        "UPDATE tb_ingest_jobs SET current_step = CASE WHEN status = 'completed' THEN 'completed' ELSE 'parse' END "
        f"WHERE current_step IN ({drawing})"
    )
    _set_step_constraint(STEPS_BEFORE)
