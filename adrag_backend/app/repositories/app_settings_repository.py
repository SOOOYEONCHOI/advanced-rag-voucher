"""Repository for administrator-controlled runtime tuning settings."""

import json
from typing import Any, Dict

from app.repositories.database import get_database_manager


SETTING_TYPES = {
    "candidate_top_k": "int",
    "reranker_top_k": "int",
    "context_top_k": "int",
    "relevance_threshold": "float",
    "fallback_relevance_threshold": "float",
    "hybrid_rrf_k": "int",
    "bm25_k1": "float",
    "bm25_b": "float",
    "soft_boost_keyword": "float",
    "soft_boost_tag": "float",
    "soft_boost_document_type": "float",
    "soft_boost_intent": "float",
    "menu_hint_terms": "json",
    "narrative_hint_terms": "json",
    "embedding_provider": "str",
    "vector_store_provider": "str",
    "reranker_provider": "str",
}


class AppSettingsRepository:
    def __init__(self) -> None:
        self.db = get_database_manager()

    def get_all(self) -> Dict[str, Any]:
        rows = self.db.execute_query(
            "SELECT setting_key, setting_value, value_type FROM tb_app_settings"
        )
        return {row["setting_key"]: _decode(row["setting_value"], row["value_type"]) for row in rows}

    def get_version(self) -> int:
        rows = self.db.execute_query("SELECT COALESCE(MAX(version), 0) AS version FROM tb_app_settings")
        return int(rows[0]["version"]) if rows else 0

    def set_many(self, values: Dict[str, Any], updated_by: str) -> int:
        unknown = set(values) - set(SETTING_TYPES)
        if unknown:
            raise ValueError(f"지원하지 않는 설정: {', '.join(sorted(unknown))}")
        _validate(values)
        version = self.get_version() + 1
        with self.db.get_connection() as conn:
            for key, value in values.items():
                value_type = SETTING_TYPES[key]
                conn.execute(
                    """
                    INSERT INTO tb_app_settings(setting_key, setting_value, value_type, version, updated_by)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(setting_key) DO UPDATE SET
                        setting_value=excluded.setting_value,
                        value_type=excluded.value_type,
                        version=excluded.version,
                        updated_by=excluded.updated_by,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (key, _encode(value, value_type), value_type, version, updated_by),
                )
        return version


def _encode(value: Any, value_type: str) -> str:
    return json.dumps(value, ensure_ascii=False) if value_type == "json" else str(value)


def _decode(value: str, value_type: str) -> Any:
    if value_type == "int":
        return int(value)
    if value_type == "float":
        return float(value)
    if value_type == "json":
        return json.loads(value)
    return value


def _validate(values: Dict[str, Any]) -> None:
    positive_ints = {"candidate_top_k", "reranker_top_k", "context_top_k", "hybrid_rrf_k"}
    for key in positive_ints & values.keys():
        if not isinstance(values[key], int) or values[key] < 1:
            raise ValueError(f"{key}는 1 이상의 정수여야 합니다.")
    for key in {"relevance_threshold", "fallback_relevance_threshold"} & values.keys():
        if not isinstance(values[key], (int, float)) or not 0 <= values[key] <= 1:
            raise ValueError(f"{key}는 0~1 범위여야 합니다.")
    for key in {"bm25_k1", "bm25_b", "soft_boost_keyword", "soft_boost_tag", "soft_boost_document_type", "soft_boost_intent"} & values.keys():
        if not isinstance(values[key], (int, float)) or values[key] < 0:
            raise ValueError(f"{key}는 0 이상의 숫자여야 합니다.")
    for key in {"menu_hint_terms", "narrative_hint_terms"} & values.keys():
        if not isinstance(values[key], list) or not all(isinstance(item, str) for item in values[key]):
            raise ValueError(f"{key}는 문자열 배열이어야 합니다.")
