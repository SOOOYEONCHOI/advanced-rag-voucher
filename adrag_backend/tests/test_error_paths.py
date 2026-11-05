# -*- coding: utf-8 -*-
"""
2026.07.16(sooyeon.choi) 추가 - 2단계 오류 경로 재설계(B2/B5) 단위 테스트.

- effective_threshold: threshold_override > relevance_threshold > settings 우선순위
- check_retrieval: 검색 시스템 오류 시 재시도 없이 build_response 직행
"""

from types import SimpleNamespace

from app.graphs.edges import check_retrieval
from app.graphs.utils import effective_threshold


class _Settings(SimpleNamespace):
    pass


def _settings(threshold: float = 0.3) -> _Settings:
    return _Settings(relevance_threshold=threshold)


# ── effective_threshold (B5) ────────────────────────────────────────────────

def test_effective_threshold_uses_settings_default():
    state = {"relevance_threshold": None, "threshold_override": None}
    assert effective_threshold(state, _settings(0.3)) == 0.3


def test_effective_threshold_prefers_user_threshold_over_settings():
    state = {"relevance_threshold": 0.5, "threshold_override": None}
    assert effective_threshold(state, _settings(0.3)) == 0.5


def test_effective_threshold_override_wins_even_at_zero():
    # degraded 폴백의 0.0 우회가 사용자/기본값보다 우선해야 함
    state = {"relevance_threshold": 0.5, "threshold_override": 0.0}
    assert effective_threshold(state, _settings(0.3)) == 0.0


def test_effective_threshold_cleared_override_restores_user_threshold():
    # 정상 rerank가 override를 None으로 재설정하면 사용자 임계값 복원 (잔류 오염 방지)
    state = {"relevance_threshold": 0.5, "threshold_override": None}
    assert effective_threshold(state, _settings(0.3)) == 0.5


# ── check_retrieval (B2) ────────────────────────────────────────────────────

def test_check_retrieval_routes_error_to_build_response():
    state = {"error": "검색 타임아웃 (90초 초과)"}
    assert check_retrieval(state) == "build_response"


def test_check_retrieval_routes_success_to_rerank():
    state = {"error": None, "retrieved_chunks": []}
    assert check_retrieval(state) == "rerank"
