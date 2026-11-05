# 2026.06.16(sooyeon.choi) 추가 - SCR-006 관리자 통계 대시보드 API
"""
관리자 전용 통계 API.

GET /api/admin/stats/summary           — 요약 카드 4종 + 전기간 대비 증감
GET /api/admin/stats/usage-trend       — 일별 질의수·비용 콤보 차트
GET /api/admin/stats/top-keywords      — 인기 키워드 Top 5
GET /api/admin/stats/top-documents     — 최다 참조 문서 Top 5
GET /api/admin/stats/flagged-queries   — 주의 요망 질의 목록
GET /api/admin/stats/departments       — 부서별 질의수·비중·만족도
GET /api/admin/stats/departments/weekly-trend — 부서별 주간 추이
GET /api/admin/stats/top-users         — 사용자별 활동 Top 10
GET /api/admin/stats/document-health   — 장기간 미참조 문서
"""

from fastapi import APIRouter, Depends, Query

from app.models.stats_models import (
    AdminFlaggedQueryListResponse,
    AdminSummaryResponse,
    DepartmentUsageResponse,
    DepartmentWeeklyTrendResponse,
    DocumentHealthResponse,
    KeywordListResponse,
    StatsPeriodValue,
    TopDocumentListResponse,
    TopUserListResponse,
    UsageTrendResponse,
)
from app.services.stats_service import StatsService
from app.utils.security import get_current_admin

router = APIRouter(prefix="/admin/stats", tags=["Admin Statistics"])

_stats = StatsService()


@router.get("/summary", response_model=AdminSummaryResponse)
async def admin_summary(
    # 2026.06.19(sooyeon.choi) 추가 - 허용 통계 기간만 FastAPI 단계에서 검증
    period: StatsPeriodValue = Query(default="7"),
    _: dict = Depends(get_current_admin),
):
    """총 질의 수, 만족도, API 비용, 주의 질의 수와 전기간 대비 증감."""
    return _stats.get_admin_summary(period)


@router.get("/usage-trend", response_model=UsageTrendResponse)
async def admin_usage_trend(
    period: StatsPeriodValue = Query(default="7"),
    _: dict = Depends(get_current_admin),
):
    """일별 질의수·비용 콤보 차트 데이터."""
    return _stats.get_admin_usage_trend(period)


@router.get("/top-keywords", response_model=KeywordListResponse)
async def admin_top_keywords(
    period: StatsPeriodValue = Query(default="7"),
    limit: int = Query(default=5, ge=1, le=20),
    _: dict = Depends(get_current_admin),
):
    """인기 키워드 Top N."""
    return {"items": _stats.get_top_keywords(period, limit)}


@router.get("/top-documents", response_model=TopDocumentListResponse)
async def admin_top_documents(
    period: StatsPeriodValue = Query(default="7"),
    limit: int = Query(default=5, ge=1, le=20),
    _: dict = Depends(get_current_admin),
):
    """최다 참조 문서 Top N."""
    return {"items": _stats.get_top_documents(period, limit)}


@router.get(
    "/flagged-queries",
    response_model=AdminFlaggedQueryListResponse,
)
async def admin_flagged_queries(
    period: StatsPeriodValue = Query(default="7"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: dict = Depends(get_current_admin),
):
    """주의 요망 질의 목록 (검색 실패 + 부정 피드백)."""
    # 2026.06.19(sooyeon.choi) 추가 - 관리자 주의 질의 페이지네이션
    return _stats.get_admin_flagged_queries(period, page, page_size)


@router.get("/departments", response_model=DepartmentUsageResponse)
async def admin_department_stats(
    period: StatsPeriodValue = Query(default="7"),
    _: dict = Depends(get_current_admin),
):
    """부서별 질의 수, 비중, 만족도."""
    # 2026.06.19(sooyeon.choi) 추가 - 부서 현황과 주간 추이 API 분리
    return _stats.get_department_usage(period)


@router.get(
    "/departments/weekly-trend",
    response_model=DepartmentWeeklyTrendResponse,
)
async def admin_department_weekly_trend(
    weeks: int = Query(default=4, ge=1, le=12),
    _: dict = Depends(get_current_admin),
):
    """월요일 시작 기준 부서별 주간 질의 추이."""
    # 2026.06.19(sooyeon.choi) 추가 - 독립적인 주차 수 파라미터 적용
    return _stats.get_department_weekly_trend(weeks)


@router.get("/top-users", response_model=TopUserListResponse)
async def admin_top_users(
    period: StatsPeriodValue = Query(default="7"),
    limit: int = Query(default=10, ge=1, le=100),
    _: dict = Depends(get_current_admin),
):
    """사용자별 활동 Top N."""
    # 2026.06.19(sooyeon.choi) 추가 - 공통 목록 응답 키 items 적용
    return {"items": _stats.get_top_users(period, limit)}


@router.get("/document-health", response_model=DocumentHealthResponse)
async def admin_document_health(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: dict = Depends(get_current_admin),
):
    """장기간 미참조 문서 요약과 목록."""
    # 2026.06.19(sooyeon.choi) 추가 - 관리자 문서 상태 페이지네이션 API
    return _stats.get_document_health(page, page_size)

