"""문서 모델명(tb_documents.product_model) 기본값·검증 (2026.10.19 UI-12 모델명 관리 1단계).

근거: docs/design/문서 관리 모델명·버전 관리 개선 요청서.md 3.1·9.1
- 화면 표기는 "모델명", 저장 컬럼·API 키는 기존 ``product_model``을 그대로 쓴다(``model_name`` 컬럼 없음).
  LLM 모델명(tb_llm_models.model_name)·대화 주제(권한 그룹, D-15)와는 별개다.
- 앞뒤 공백 제거 후 1~100자. 조용히 잘라내지 않고 오류를 낸다(호출자가 422로 응답).
- 기본값은 원본 파일명에서 마지막 확장자만 뺀 값(예: ``C2.assembly.rev2.pdf`` → ``C2.assembly.rev2``).
  프런트(useDocumentUpload.js)와 Alembic 0004 백필도 같은 규칙을 쓴다.
"""
from __future__ import annotations

import re
from typing import Optional

MAX_MODEL_NAME_LENGTH = 100
MODEL_NAME_ERROR = f"모델명은 앞뒤 공백을 제외하고 1~{MAX_MODEL_NAME_LENGTH}자로 입력하세요."

_LAST_EXTENSION = re.compile(r"\.[^.]+$")


def default_model_name(filename: Optional[str]) -> str:
    """파일명에서 마지막 확장자만 뺀 값(앞뒤 공백 제거). 검증은 하지 않는다."""
    return _LAST_EXTENSION.sub("", filename or "").strip()


def validate_model_name(value: Optional[str]) -> str:
    """앞뒤 공백을 뺀 모델명을 돌려준다. 비었거나 100자를 넘으면 ValueError."""
    normalized = (value or "").strip()
    if not normalized or len(normalized) > MAX_MODEL_NAME_LENGTH:
        raise ValueError(MODEL_NAME_ERROR)
    return normalized


def resolve_upload_model_name(value: Optional[str], filename: Optional[str], *, provided: bool) -> str:
    """업로드 요청의 모델명. 필드가 없으면(구 클라이언트) 파일명 기본값, 있으면 그 값을 검증한다."""
    return validate_model_name(value if provided else default_model_name(filename))
