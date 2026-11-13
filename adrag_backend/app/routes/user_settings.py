"""
사용자별/컬렉션별 LLM 설정 API.

GET  /api/user/llm-settings                — 현재 사용자의 LLM 설정 조회 (컬렉션별)
POST /api/user/llm-settings                — LLM 설정 저장 (모델 선택 + API 키)
DELETE /api/user/llm-settings              — LLM 설정 초기화
"""
# 2026.06.16(sooyeon.choi) 수정
#   UserLlmSettingsRepository.get/save/delete 가 collection_id(int)로 변경됨
#   API 계약은 collection_name(qdrant_name:str) 유지, 내부에서 collection_id로 변환
#   collection_name == "" (전체 기본값) 은 v4에서 미지원 (NOT NULL FK) → None 반환

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.repositories.collection_repository import CollectionRepository
from app.repositories.user_llm_settings_repository import UserLlmSettingsRepository
from app.repositories.model_repository import ModelRepository
from app.utils.encryption import encrypt_api_key
from app.utils.security import get_current_principal
from app.core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/user/llm-settings", tags=["User LLM Settings"])


class SaveLlmSettingRequest(BaseModel):
    collection_name: str = Field(default="", description="qdrant_name, 빈 문자열 = 전체 기본값")
    model_id: str = Field(..., description="선택한 모델 ID")
    api_key: Optional[str] = Field(default=None, description="OpenAI API 키 (필요한 모델만)")


def _resolve_collection_id(qdrant_name: str) -> Optional[int]:
    """qdrant_name → collection_id 변환. 빈 문자열이거나 미등록이면 None 반환."""
    if not qdrant_name:
        return None
    col = CollectionRepository().get_by_qdrant_name(qdrant_name)
    return col.collection_id if col else None


@router.get("")
async def get_llm_setting(
    collection_name: str = "",
    current_user: dict = Depends(get_current_principal),
):
    """현재 사용자+컬렉션의 저장된 LLM 설정을 반환한다.

    api_key 값은 저장 여부(has_api_key)만 반환하고 복호화 값은 노출하지 않는다.
    """
    user_id = current_user["user_id"]
    # 2026.06.16(sooyeon.choi) 수정 - collection_name → collection_id 변환
    collection_id = _resolve_collection_id(collection_name)
    if collection_id is None:
        return {"setting": None}

    setting = UserLlmSettingsRepository().get(user_id, collection_id)

    if not setting:
        return {"setting": None}

    return {
        "setting": {
            "collection_name": collection_name,   # API 응답은 qdrant_name 유지
            "model_id": setting.model_id,
            "has_api_key": setting.api_key_enc is not None,
        }
    }


@router.post("")
async def save_llm_setting(
    body: SaveLlmSettingRequest,
    current_user: dict = Depends(get_current_principal),
):
    """모델 선택과 API 키를 저장한다."""
    user_id = current_user["user_id"]

    # 모델 유효성 검증
    model = ModelRepository().get_by_id(body.model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"모델을 찾을 수 없습니다: {body.model_id}")
    if not model.is_enabled:
        raise HTTPException(status_code=400, detail="비활성화된 모델입니다.")

    # 2026.06.16(sooyeon.choi) 수정 - collection_name → collection_id 변환
    collection_id = _resolve_collection_id(body.collection_name)
    if collection_id is None:
        raise HTTPException(status_code=400, detail="유효하지 않은 컬렉션입니다.")

    repo = UserLlmSettingsRepository()
    existing = repo.get(user_id, collection_id)

    # API 키 처리: 새로 입력된 키 우선, 없으면 기존 유지
    if body.api_key:
        api_key_enc = encrypt_api_key(body.api_key)
    elif existing and existing.api_key_enc:
        api_key_enc = existing.api_key_enc
    else:
        api_key_enc = None

    repo.save(
        user_id=user_id,
        collection_id=collection_id,
        model_id=body.model_id,
        api_key_enc=api_key_enc,
    )

    logger.info("LLM 설정 저장: user=%s collection=%s model=%s", user_id, body.collection_name, body.model_id)
    return {
        "collection_name": body.collection_name,
        "model_id": body.model_id,
        "has_api_key": api_key_enc is not None,
    }


@router.delete("")
async def delete_llm_setting(
    collection_name: str = "",
    current_user: dict = Depends(get_current_principal),
):
    """현재 사용자+컬렉션의 LLM 설정을 초기화한다."""
    user_id = current_user["user_id"]
    # 2026.06.16(sooyeon.choi) 수정 - collection_name → collection_id 변환
    collection_id = _resolve_collection_id(collection_name)
    if collection_id is not None:
        UserLlmSettingsRepository().delete(user_id, collection_id)
    logger.info("LLM 설정 초기화: user=%s collection=%s", user_id, collection_name)
    return {"success": True}