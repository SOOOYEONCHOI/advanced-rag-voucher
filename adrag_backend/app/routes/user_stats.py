# 2026.06.16(sooyeon.choi) 추가 - SCR-006 사용자 통계 대시보드 API
"""
사용자 전용 통계 API (본인 데이터만 반환).

GET /api/stats/me/summary         — 요약 카드 4종 (내 질의수, 활동일수, 만족도, 성공률)
GET /api/stats/me/usage-trend     — 내 일별 질의수·비용 콤보 차트
GET /api/stats/me/top-keywords    — 내 인기 키워드 Top N
GET /api/stats/me/top-documents   — 내 최다 참조 문서 Top N
GET /api/stats/me/flagged-queries — 내 주의 요망 질의 목록
"""

from fastapi import APIRouter, Depends, Query

from app.models.stats_models import (
    FlaggedQueryListResponse,
    KeywordListResponse,
    StatsPeriodValue,
    TopDocumentListResponse,
    UsageTrendResponse,
    UserSummaryResponse,
)
from app.services.stats_service import StatsService
from app.utils.security import get_current_user

router = APIRouter(prefix="/stats", tags=["User Statistics"])

_stats = StatsService()

# 2026.06.19(sooyeon.choi) 추가 - 모든 사용자 통계 API에 user_access 인증 적용

@router.get("/me/summary", response_model=UserSummaryResponse)
async def get_my_summary(
    # 2026.06.19(sooyeon.choi) 추가 - 허용 통계 기간만 FastAPI 단계에서 검증
    period: StatsPeriodValue = Query(default="7"),
    current_user: dict = Depends(get_current_user),
):
    """내 요약 카드 4종 + 전기간 대비 증감."""
    return _stats.get_user_summary(period, current_user["user_id"])


@router.get("/me/usage-trend", response_model=UsageTrendResponse)
async def get_my_usage_trend(
    period: StatsPeriodValue = Query(default="7"),
    current_user: dict = Depends(get_current_user),
):
    """내 일별 질의수·비용 콤보 차트."""
    return _stats.get_user_usage_trend(period, current_user["user_id"])


@router.get("/me/top-keywords", response_model=KeywordListResponse)
async def get_my_top_keywords(
    period: StatsPeriodValue = Query(default="7"),
    limit: int = Query(default=5, ge=1, le=20),
    current_user: dict = Depends(get_current_user),
):
    """내 인기 키워드 Top N."""
    return {
        "items": _stats.get_top_keywords(
            period,
            limit,
            user_id=current_user["user_id"],
        )
    }


@router.get("/me/top-documents", response_model=TopDocumentListResponse)
async def get_my_top_documents(
    period: StatsPeriodValue = Query(default="7"),
    limit: int = Query(default=5, ge=1, le=20),
    current_user: dict = Depends(get_current_user),
):
    """내 최다 참조 문서 Top N."""
    return {
        "items": _stats.get_top_documents(
            period,
            limit,
            user_id=current_user["user_id"],
        )
    }


@router.get("/me/flagged-queries", response_model=FlaggedQueryListResponse)
async def get_my_flagged_queries(
    period: StatsPeriodValue = Query(default="7"),
    limit: int = Query(default=10, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """내 주의 요망 질의 목록."""
    return {
        "items": _stats.get_flagged_queries(
            period,
            limit,
            user_id=current_user["user_id"],
        )
    }
