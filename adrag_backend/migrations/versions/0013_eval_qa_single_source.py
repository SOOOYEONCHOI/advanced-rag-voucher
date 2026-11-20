"""0013_eval_qa_single_source (2026.11.19(sooyeon.choi) 추가 - 단일 출처 평가 데이터셋 문항 유형).

근거: docs/design/reports/eval-law-testset-design-v1.0.md 3장
- tb_eval_qa_items.question_type 에 'law'(법령 조항 단일 출처), 'general'(일반 문서 단일 출처) 추가
  (기존 factual/procedural/comparative/multihop 유형별 생성은 그대로)

downgrade: 'law'/'general' 문항이 남아 있으면 중단한다(먼저 해당 데이터셋을 삭제한 뒤 재실행).

Revision ID: 0013_eval_qa_single_source
Revises: 0012_eval_batch_query
Create Date: 2026-11-19
"""
from alembic import op
from sqlalchemy import text

revision = "0013_eval_qa_single_source"
down_revision = "0012_eval_batch_query"
branch_labels = None
depends_on = None

_CONSTRAINT = "tb_eval_qa_items_question_type_check"
_TYPES_0001 = "('factual', 'procedural', 'comparative', 'multihop')"
_TYPES_0013 = "('factual', 'procedural', 'comparative', 'multihop', 'law', 'general')"


def upgrade() -> None:
    op.execute(f"ALTER TABLE tb_eval_qa_items DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE tb_eval_qa_items ADD CONSTRAINT {_CONSTRAINT} CHECK (question_type IN {_TYPES_0013})"
    )


def downgrade() -> None:
    remaining = op.get_bind().execute(
        text("SELECT COUNT(*) FROM tb_eval_qa_items WHERE question_type IN ('law', 'general')")
    ).scalar()
    if remaining:
        raise RuntimeError(
            f"단일 출처 문항(law/general) {remaining}건이 남아 있어 downgrade를 중단합니다. "
            "해당 평가 데이터셋을 먼저 삭제하세요."
        )
    op.execute(f"ALTER TABLE tb_eval_qa_items DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE tb_eval_qa_items ADD CONSTRAINT {_CONSTRAINT} CHECK (question_type IN {_TYPES_0001})"
    )
