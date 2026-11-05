"""Version-aware runtime settings layered over environment defaults."""

import threading

from app.core.config import Settings, get_settings
from app.repositories.app_settings_repository import AppSettingsRepository

_lock = threading.Lock()
_cached_version = -1
_cached_settings: Settings | None = None


def get_runtime_settings() -> Settings:
    global _cached_version, _cached_settings
    repository = AppSettingsRepository(get_settings().sqlite_db_path)
    version = repository.get_version()
    if _cached_settings is not None and version == _cached_version:
        return _cached_settings
    with _lock:
        if _cached_settings is None or version != _cached_version:
            _cached_settings = get_settings().model_copy(update=repository.get_all())
            _cached_version = version
        return _cached_settings


def invalidate_runtime_settings() -> None:
    global _cached_version, _cached_settings
    with _lock:
        _cached_version = -1
        _cached_settings = None


def get_runtime_settings_version() -> int:
    return AppSettingsRepository(get_settings().sqlite_db_path).get_version()
