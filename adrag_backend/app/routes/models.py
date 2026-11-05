"""
LLM 모델 관리 API.

GET    /api/models                                    — 활성 모델 목록 (인증 불필요)
GET    /api/admin/models                              — 전체 모델 목록 (관리자)
POST   /api/admin/models                              — 모델 추가 (관리자)
PUT    /api/admin/models/{id}                         — 모델 수정 (관리자)
DELETE /api/admin/models/{id}                         — 모델 삭제 (관리자)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.repositories.model_repository import ModelRepository
from app.utils.security import get_current_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["LLM Models"])


def _repo() -> ModelRepository:
    return ModelRepository()


def _to_dict(model) -> dict:
    return {
        "model_id": model.model_id,
        "model_name": model.model_name,
        "provider": model.provider,
        "requires_api_key": model.requires_api_key,
        "is_enabled": model.is_enabled,
        "sort_order": model.sort_order,
    }


# ── Pydantic 모델 ──────────────────────────────────────────────────────────────

class ModelCreateRequest(BaseModel):
    model_id: str = Field(..., description="고유 식별자 (예: gpt-4o)")
    model_name: str = Field(..., description="화면 표시명")
    provider: str = Field(..., description="'local' 또는 'openai'")
    requires_api_key: bool = Field(default=False)
    is_enabled: bool = Field(default=True)
    sort_order: int = Field(default=0)


class ModelUpdateRequest(BaseModel):
    model_name: Optional[str] = None
    provider: Optional[str] = None
    requires_api_key: Optional[bool] = None
    is_enabled: Optional[bool] = None
    sort_order: Optional[int] = None


# ── Public 엔드포인트 ──────────────────────────────────────────────────────────

@router.get("/models")
async def get_enabled_models():
    """채팅 UI에서 사용할 활성화된 모델 목록을 반환한다."""
    return {"models": [_to_dict(m) for m in _repo().get_enabled()]}


# ── 관리자 엔드포인트 ──────────────────────────────────────────────────────────

@router.get("/admin/models")
async def get_all_models(_: dict = Depends(get_current_admin)):
    """전체 모델 목록 (비활성 포함)."""
    models = _repo().get_all()
    return {"models": [_to_dict(m) for m in models]}


@router.post("/admin/models", status_code=status.HTTP_201_CREATED)
async def create_model(body: ModelCreateRequest, _: dict = Depends(get_current_admin)):
    """새 모델을 추가한다."""
    if body.provider not in ("local", "openai"):
        raise HTTPException(status_code=400, detail="provider는 'local' 또는 'openai'여야 합니다.")

    repo = _repo()
    if repo.get_by_id(body.model_id):
        raise HTTPException(status_code=409, detail=f"이미 존재하는 model_id입니다: {body.model_id}")

    model = repo.create(
        model_id=body.model_id,
        model_name=body.model_name,
        provider=body.provider,
        requires_api_key=body.requires_api_key,
        is_enabled=body.is_enabled,
        sort_order=body.sort_order,
    )
    logger.info("모델 추가: %s", body.model_id)
    return _to_dict(model)


@router.put("/admin/models/{model_id}")
async def update_model(
    model_id: str,
    body: ModelUpdateRequest,
    _: dict = Depends(get_current_admin),
):
    """모델 정보를 수정한다 (is_enabled로 활성/비활성 토글 가능)."""
    if body.provider is not None and body.provider not in ("local", "openai"):
        raise HTTPException(status_code=400, detail="provider는 'local' 또는 'openai'여야 합니다.")

    model = _repo().update(
        model_id=model_id,
        model_name=body.model_name,
        provider=body.provider,
        requires_api_key=body.requires_api_key,
        is_enabled=body.is_enabled,
        sort_order=body.sort_order,
    )
    if not model:
        raise HTTPException(status_code=404, detail=f"모델을 찾을 수 없습니다: {model_id}")

    logger.info("모델 수정: %s", model_id)
    return _to_dict(model)


@router.delete("/admin/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(model_id: str, _: dict = Depends(get_current_admin)):
    """모델을 삭제한다."""
    if not _repo().delete(model_id):
        raise HTTPException(status_code=404, detail=f"모델을 찾을 수 없습니다: {model_id}")
    logger.info("모델 삭제: %s", model_id)
