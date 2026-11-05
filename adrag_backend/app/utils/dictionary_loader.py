"""
한국어 검색 사전 로더.

YAML 기반 사전을 한 번만 로드해 Kiwi 사용자 사전, QueryPreprocessor 약어 확장,
검색 불용어 정책이 동일한 데이터 원천을 참조하도록 한다.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class KoreanSearchDictionary:
    abbreviations: dict[str, str] = field(default_factory=dict)
    compound_terms: list[str] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)
    stopwords_query_functional: frozenset[str] = frozenset()
    stopwords_domain_weak: frozenset[str] = frozenset()
    protected_patterns: list[str] = field(default_factory=list)


def _default_dictionary_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "korean_search_dictionary.yaml"


def _as_str_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items()}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def load_korean_search_dictionary(path: str | None = None) -> KoreanSearchDictionary:
    """한국어 검색 사전을 로드한다.

    2026.06.26(sooyeon.choi) 수정 - 하드코딩 사전을 YAML 단일 원천으로 통합.
    """
    dictionary_path = Path(path) if path else _default_dictionary_path()
    return _load_dictionary_version(str(dictionary_path), dictionary_path.stat().st_mtime_ns)


@lru_cache(maxsize=4)
def _load_dictionary_version(path: str, version: int) -> KoreanSearchDictionary:
    dictionary_path = Path(path)
    with dictionary_path.open(encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}

    stopwords = raw.get("stopwords") if isinstance(raw, dict) else {}
    if not isinstance(stopwords, dict):
        stopwords = {}

    return KoreanSearchDictionary(
        abbreviations=_as_str_dict(raw.get("abbreviations")),
        compound_terms=_as_str_list(raw.get("compound_terms")),
        aliases=_as_str_dict(raw.get("aliases")),
        stopwords_query_functional=frozenset(_as_str_list(stopwords.get("query_functional"))),
        stopwords_domain_weak=frozenset(_as_str_list(stopwords.get("domain_weak"))),
        protected_patterns=_as_str_list(raw.get("protected_patterns")),
    )


# Backward-compatible test/administration hook.
load_korean_search_dictionary.cache_clear = _load_dictionary_version.cache_clear
