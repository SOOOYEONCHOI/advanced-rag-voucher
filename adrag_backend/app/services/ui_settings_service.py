# 2026.09.17(woojin.jung) 추가 - 사용자 UI 연동 설정 비즈니스 로직 Service 추가
"""사용자 UI 연동 설정 비즈니스 로직."""

import logging
from typing import Literal

from app.repositories.ui_settings_repository import UiSettingsRepository
from app.utils.datetime import now_kst_iso

logger = logging.getLogger(__name__)

UiType = Literal["standalone", "menu_linked", "layout_linked"]
ALLOWED_UI_TYPES = frozenset({"standalone", "menu_linked", "layout_linked"})


class UiSettingsNotFoundError(Exception):
    """사용자 UI 설정을 찾을 수 없을 때 발생한다."""


class InvalidUiTypeError(ValueError):
    """지원하지 않는 UI 연동 방식일 때 발생한다."""


class UiTypeAlreadyConfiguredError(Exception):
    """UI 연동 방식이 이미 확정된 사용자일 때 발생한다."""


class UiSettingsService:
    """현재 사용자의 UI 연동 설정 조회 및 수정을 처리한다."""

    def __init__(self, repository: UiSettingsRepository | None = None) -> None:
        self.repository = repository or UiSettingsRepository()

    def get_ui_type(self, user_id: str) -> UiType | None:
        found, ui_type = self.repository.get_ui_type(user_id)
        if not found:
            raise UiSettingsNotFoundError("사용자 정보를 찾을 수 없습니다.")
        return ui_type

    def update_ui_type(self, user_id: str, ui_type: str) -> str:
        if ui_type not in ALLOWED_UI_TYPES:
            raise InvalidUiTypeError("지원하지 않는 UI 연동 방식입니다.")

        updated = self.repository.select_ui_type(
            user_id=user_id,
            ui_type=ui_type,
            updated_at=now_kst_iso(),
        )
        if not updated:
            if self.repository.user_exists(user_id):
                raise UiTypeAlreadyConfiguredError(
                    "이미 UI 연동 방식이 확정되어 변경할 수 없습니다."
                )
            raise UiSettingsNotFoundError("사용자 정보를 찾을 수 없습니다.")

        logger.info("UI 연동 방식 최초 확정: user=%s ui_type=%s", user_id, ui_type)
        return ui_type
