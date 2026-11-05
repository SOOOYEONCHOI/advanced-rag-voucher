"""0004 document model name backfill + 'update' document event (2026.10.19 UI-12 모델명 1단계).

근거: docs/design/문서 관리 모델명·버전 관리 개선 요청서.md 5절·9.2(4단계)
- 컬럼 추가 없음. 기존 tb_documents.product_model을 화면의 "모델명"으로 쓴다(model_name 컬럼을 만들지 않음).
- 백필: 삭제되지 않은 문서 중 product_model이 NULL이거나 공백뿐인 행만, 원본 파일명에서 마지막 확장자를 뺀 값으로 채운다
  (app/ingest/model_name.py·프런트와 같은 규칙). 이미 입력된 값은 바꾸지 않는다.
- 기본값이 비거나 100자를 넘는 행은 잘라내지 않고 그대로 둔다(NULL 유지). 건수를 경고로 남기며,
  관리자가 문서 목록의 모델명 수정으로 정리한다.
- tb_document_events.event_type에 'update'(문서 정보 수정 — 모델명 변경 이력)를 추가한다.

downgrade 데이터 범위: 백필한 모델명은 되돌리지 않는다(0003 스키마에서도 유효한 값이고, 백필값과
사용자 입력값을 구분할 수 없기 때문). 'update' 이벤트 행은 CHECK를 되돌리기 위해 삭제한다.

Revision ID: 0004_document_model_name
Revises: 0003_versions_chunks_images
Create Date: 2026-10-19
"""
import logging

from alembic import op
from sqlalchemy import text

logger = logging.getLogger("alembic.runtime.migration")

revision = "0004_document_model_name"
down_revision = "0003_versions_chunks_images"
branch_labels = None
depends_on = None

MAX_MODEL_NAME_LENGTH = 100
# 파일명에서 마지막 확장자(.xxx)만 제거하고 앞뒤 공백을 뺀 값 — JS /\.[^.]+$/ 와 같은 규칙
_STEM = r"btrim(regexp_replace(coalesce(original_filename, ''), '\.[^.]+$', ''))"
_NEEDS_BACKFILL = "deleted_at IS NULL AND (product_model IS NULL OR btrim(product_model) = '')"

EVENT_TYPES_BEFORE = ("upload", "parse", "embed", "delete", "reindex", "fail")
EVENT_TYPES_AFTER = EVENT_TYPES_BEFORE + ("update",)


def _event_check(types) -> str:
    values = ", ".join(f"'{t}'" for t in types)
    return (
        "ALTER TABLE tb_document_events DROP CONSTRAINT IF EXISTS tb_document_events_event_type_check; "
        "ALTER TABLE tb_document_events ADD CONSTRAINT tb_document_events_event_type_check "
        f"CHECK (event_type IN ({values}))"
    )


def upgrade() -> None:
    bind = op.get_bind()
    skipped = bind.execute(text(
        f"SELECT count(*) FROM tb_documents WHERE {_NEEDS_BACKFILL} "
        f"AND char_length({_STEM}) NOT BETWEEN 1 AND {MAX_MODEL_NAME_LENGTH}"
    )).scalar()
    if skipped:
        # 운영 이관 시 사전 점검 대상: 해당 문서는 모델명이 비어 있는 채로 남는다(목록에서 직접 입력)
        logger.warning("[0004] 모델명 기본값이 비었거나 %s자를 넘어 백필하지 않은 문서: %s건",
                       MAX_MODEL_NAME_LENGTH, skipped)
    # 백필은 사용자의 문서 변경이 아니므로 최근 변경일(updated_at, 0002 트리거)을 바꾸지 않는다
    op.execute("ALTER TABLE tb_documents DISABLE TRIGGER trg_tb_documents_touch_updated_at")
    op.execute(
        f"UPDATE tb_documents SET product_model = {_STEM} "
        f"WHERE {_NEEDS_BACKFILL} AND char_length({_STEM}) BETWEEN 1 AND {MAX_MODEL_NAME_LENGTH}"
    )
    op.execute("ALTER TABLE tb_documents ENABLE TRIGGER trg_tb_documents_touch_updated_at")
    op.execute(_event_check(EVENT_TYPES_AFTER))


def downgrade() -> None:
    op.execute("DELETE FROM tb_document_events WHERE event_type = 'update'")
    op.execute(_event_check(EVENT_TYPES_BEFORE))
