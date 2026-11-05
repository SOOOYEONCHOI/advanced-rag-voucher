# 2026.09.17(woojin.jung) 수정 - UI 설정 처리를 routes, services, repositories 계층으로 분리
"""로그인 사용자의 UI 연동 방식 설정 API."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.services.ui_settings_service import (
    InvalidUiTypeError,
    UiTypeAlreadyConfiguredError,
    UiSettingsNotFoundError,
    UiSettingsService,
    UiType,
)
from app.utils.security import get_current_user

router = APIRouter(prefix="/user/ui-settings", tags=["User UI Settings"])


class UpdateUiSettingsRequest(BaseModel):
    ui_type: UiType


class UiSettingsResponse(BaseModel):
    ui_type: Optional[UiType] = None


def _service() -> UiSettingsService:
    return UiSettingsService()


@router.get("", response_model=UiSettingsResponse)
async def get_ui_settings(
    current_user: dict = Depends(get_current_user),
):
    """현재 사용자의 UI 연동 방식을 반환한다."""
    try:
        ui_type = _service().get_ui_type(current_user["user_id"])
    except UiSettingsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return UiSettingsResponse(ui_type=ui_type)


@router.put("", response_model=UiSettingsResponse)
async def update_ui_settings(
    body: UpdateUiSettingsRequest,
    current_user: dict = Depends(get_current_user),
):
    """현재 사용자의 UI 연동 방식을 수정한다."""
    try:
        ui_type = _service().update_ui_type(
            user_id=current_user["user_id"],
            ui_type=body.ui_type,
        )
    except InvalidUiTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UiTypeAlreadyConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UiSettingsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return UiSettingsResponse(ui_type=ui_type)
