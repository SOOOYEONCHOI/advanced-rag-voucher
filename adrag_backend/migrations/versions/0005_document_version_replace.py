"""0005 document version replace (2026.10.19 UI-12 최신본 변경·버전 이력, SC-06, D-01).

근거: docs/design/문서 관리 모델명·버전 관리 개선 요청서.md 4절·9.2(5단계)
- tb_document_versions.vectors_purged_at: 활성 버전이 아닌 버전(retired·failed)의 Qdrant 포인트를 지운 시각.
  NULL이면 아직 포인트가 남아 있을 수 있으므로 검색에서 제외 필터를 건다(app/services/version_visibility.py).
- 문서마다 처리 중(building·ready) 버전은 1개만: 부분 유일 인덱스(동시 교체 방지, 409 JOB_IN_PROGRESS).
- 기존 retired 버전(문서 삭제 시 retire — 포인트도 함께 삭제됨)은 retired_at으로 채운다.

downgrade: 인덱스·컬럼 삭제. 버전 행(v2 이상 포함)은 그대로 둔다(0003 스키마에서도 유효).

Revision ID: 0005_document_version_replace
Revises: 0004_document_model_name
Create Date: 2026-10-19
"""
from alembic import op

revision = "0005_document_version_replace"
down_revision = "0004_document_model_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tb_document_versions ADD COLUMN vectors_purged_at timestamptz")
    op.execute(
        "UPDATE tb_document_versions SET vectors_purged_at = coalesce(retired_at, updated_at) "
        "WHERE status IN ('retired', 'failed')"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_doc_versions_in_progress ON tb_document_versions (document_id) "
        "WHERE status IN ('building', 'ready')"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_doc_versions_in_progress")
    op.execute("ALTER TABLE tb_document_versions DROP COLUMN IF EXISTS vectors_purged_at")
