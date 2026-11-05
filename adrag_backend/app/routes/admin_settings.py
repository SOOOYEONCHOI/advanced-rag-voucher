"""Administrator API for runtime RAG tuning settings."""

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.runtime_settings import get_runtime_settings, invalidate_runtime_settings
from app.repositories.app_settings_repository import AppSettingsRepository
from app.utils.security import get_current_admin

router = APIRouter(prefix="/admin/settings", tags=["Admin Settings"])


class SettingsUpdateRequest(BaseModel):
    values: Dict[str, Any]


@router.get("")
async def read_settings(_: dict = Depends(get_current_admin)):
    repository = AppSettingsRepository()
    overrides = await asyncio.to_thread(repository.get_all)
    return {
        "version": await asyncio.to_thread(repository.get_version),
        "overrides": overrides,
        "effective": get_runtime_settings().model_dump(include=set(overrides)),
    }


@router.put("")
async def update_settings(body: SettingsUpdateRequest, admin: dict = Depends(get_current_admin)):
    repository = AppSettingsRepository()
    try:
        version = await asyncio.to_thread(
            repository.set_many,
            body.values,
            str(admin.get("user_id") or admin.get("sub") or "admin"),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    invalidate_runtime_settings()
    return {"version": version, "values": body.values}
