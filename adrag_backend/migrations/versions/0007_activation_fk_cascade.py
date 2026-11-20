"""0007 적용 이력 FK ON DELETE CASCADE (2026.11.06 대화 주제 삭제 실패 수정, UI-12, D-22).

2026.11.06(sooyeon.choi) 추가 - 신규
- 0006에서 만든 tb_document_version_activations.document_id FK에 ON DELETE CASCADE가 빠져 있었다.
  0006 업그레이드가 문서마다 baseline 이력을 넣으므로, 문서가 있는 대화 주제 삭제
  (collection_service: DELETE FROM tb_documents WHERE collection_id = ?)가 ForeignKeyViolation으로 실패했다.
- 다른 문서 하위 테이블(tb_document_versions·tb_chunks 등, 0003)과 같이 문서 물리 삭제 시 이력도 함께 지운다.
- 데이터 변경 없음. 제약만 다시 만든다.

downgrade: CASCADE 없는 원래 FK로 되돌린다(데이터 변경 없음).

Revision ID: 0007_activation_fk_cascade
Revises: 0006_document_version_restore
Create Date: 2026-11-06
"""
from alembic import op

revision = "0007_activation_fk_cascade"
down_revision = "0006_document_version_restore"
branch_labels = None
depends_on = None

FK_NAME = "tb_document_version_activations_document_id_fkey"


def _recreate_fk(on_delete: str) -> None:
    op.execute(
        f"ALTER TABLE tb_document_version_activations DROP CONSTRAINT IF EXISTS {FK_NAME}; "
        f"ALTER TABLE tb_document_version_activations ADD CONSTRAINT {FK_NAME} "
        f"FOREIGN KEY (document_id) REFERENCES tb_documents(document_id){on_delete}"
    )


def upgrade() -> None:
    _recreate_fk(" ON DELETE CASCADE")


def downgrade() -> None:
    _recreate_fk("")
