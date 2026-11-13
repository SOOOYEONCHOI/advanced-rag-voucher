"""0008_query_feedback_detail (2026.11.09 답변 피드백 의견 — 사유 선택·자유 의견).

근거: adrag_frontend/docs/chat_UI-02-08_20261104.html ANS-07(답변 피드백 의견 패널)
- tb_query_logs.feedback_reasons: 선택한 사유 코드 배열(jsonb). 코드 목록은 app/routes/query.py FEEDBACK_REASONS.
- tb_query_logs.feedback_comment: 자유 의견(최대 1000자).
- 좋아요/별로에요를 바꾸거나 취소하면 두 컬럼도 함께 비운다(이전 평가의 사유가 남지 않도록).

downgrade: 두 컬럼 삭제(입력된 사유·의견은 사라진다).

Revision ID: 0008_query_feedback_detail
Revises: 0007_activation_fk_cascade
Create Date: 2026-11-09
"""
from alembic import op

revision = "0008_query_feedback_detail"
down_revision = "0007_activation_fk_cascade"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tb_query_logs "
        "ADD COLUMN feedback_reasons jsonb CHECK (jsonb_typeof(feedback_reasons) = 'array'), "
        "ADD COLUMN feedback_comment text CHECK (char_length(feedback_comment) <= 1000)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE tb_query_logs "
        "DROP COLUMN IF EXISTS feedback_comment, "
        "DROP COLUMN IF EXISTS feedback_reasons"
    )
