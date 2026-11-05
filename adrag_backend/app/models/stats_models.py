"""Statistics API common models."""

# 2026.06.19(sooyeon.choi) 추가 - 통계 API 공통 기간·지표·페이지 응답 모델

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


StatsPeriodValue = Literal["7", "30", "month"]


class StatsPeriod(BaseModel):
    """통계 집계 기간."""

    value: StatsPeriodValue
    start_at: str
    end_at: str
    timezone: str = "Asia/Seoul"


class CountMetric(BaseModel):
    """건수형 지표와 이전 기간 비교값."""

    value: int
    previous_value: int
    change_count: int
    change_pct: Optional[float] = None


class PercentageMetric(BaseModel):
    """비율형 지표와 퍼센트포인트 비교값."""

    value_pct: Optional[float] = None
    previous_value_pct: Optional[float] = None
    change_point: Optional[float] = None


class CostMetric(BaseModel):
    """비용 지표와 이전 기간 비교값."""

    total_usd: float
    daily_average_usd: float
    previous_total_usd: float
    change_usd: float
    change_pct: Optional[float] = None


class DailyUsageItem(BaseModel):
    """일별 질의 수와 API 비용."""

    date: str
    query_count: int = 0
    cost_usd: float = 0.0


class UsageTrendResponse(BaseModel):
    """일별 사용 추이 공통 응답."""

    period: StatsPeriod
    items: List[DailyUsageItem]
    total_query_count: int
    total_cost_usd: float


class Pagination(BaseModel):
    """목록 API 공통 페이지 정보."""

    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_count: int = Field(ge=0)
    total_pages: int = Field(ge=0)


# 2026.06.19(sooyeon.choi) 추가 - 사용자 통계 대시보드 응답 모델
class ActiveDaysMetric(BaseModel):
    value: int
    period_days: int
    previous_value: int
    change_count: int


class SatisfactionMetric(PercentageMetric):
    feedback_count: int
    like_count: int
    dislike_count: int


class SuccessRateMetric(PercentageMetric):
    success_count: int
    failure_count: int


class UserSummaryResponse(BaseModel):
    period: StatsPeriod
    query_count: CountMetric
    active_days: ActiveDaysMetric
    satisfaction: SatisfactionMetric
    success_rate: SuccessRateMetric


class KeywordItem(BaseModel):
    rank: int
    keyword: str
    count: int
    ratio_pct: float


class KeywordListResponse(BaseModel):
    items: List[KeywordItem]


class TopDocumentItem(BaseModel):
    rank: int
    document_id: str
    document_name: str
    collection_id: Optional[int] = None
    collection_name: Optional[str] = None
    citation_count: int
    last_cited_at: Optional[str] = None


class TopDocumentListResponse(BaseModel):
    items: List[TopDocumentItem]


class FlaggedQueryItem(BaseModel):
    log_id: int
    query_text: str
    issue_types: List[str]
    issue_label: str
    outcome_code: str
    feedback: Optional[str] = None
    model_id: Optional[str] = None
    created_at: str


class FlaggedQueryListResponse(BaseModel):
    items: List[FlaggedQueryItem]


# 2026.06.19(sooyeon.choi) 추가 - 관리자 기본 통계 대시보드 응답 모델
class AdminSummaryResponse(BaseModel):
    period: StatsPeriod
    query_count: CountMetric
    satisfaction: SatisfactionMetric
    cost: CostMetric
    flagged_queries: CountMetric


class AdminFlaggedQueryItem(FlaggedQueryItem):
    user_id: str
    user_name: Optional[str] = None
    department: str


class AdminFlaggedQueryListResponse(BaseModel):
    items: List[AdminFlaggedQueryItem]
    pagination: Pagination


# 2026.06.19(sooyeon.choi) 추가 - 관리자 조직 통계 응답 모델
class DepartmentUsageItem(BaseModel):
    department: str
    query_count: int
    query_ratio_pct: float
    satisfaction_pct: Optional[float] = None
    feedback_count: int


class DepartmentUsageResponse(BaseModel):
    items: List[DepartmentUsageItem]
    total_query_count: int


class DepartmentWeekItem(BaseModel):
    key: str
    label: str
    start_date: str
    end_date: str


class DepartmentWeeklySeries(BaseModel):
    department: str
    values: List[int]


class DepartmentWeeklyTrendResponse(BaseModel):
    weeks: List[DepartmentWeekItem]
    series: List[DepartmentWeeklySeries]


class TopUserItem(BaseModel):
    rank: int
    user_id: str
    user_name: Optional[str] = None
    department: str
    query_count: int
    satisfaction_pct: Optional[float] = None
    feedback_count: int


class TopUserListResponse(BaseModel):
    items: List[TopUserItem]


# 2026.06.19(sooyeon.choi) 추가 - 관리자 문서 상태 응답·수정 모델
DocumentHealthStatus = Literal["uncited", "review_overdue", "review_overdue_and_uncited"]


class DocumentHealthSummary(BaseModel):
    review_overdue_count: int
    uncited_count: int
    total_document_count: int


class DocumentHealthThresholds(BaseModel):
    uncited_days: int
    review_reference_at: Optional[str] = None


class DocumentHealthItem(BaseModel):
    document_id: str
    document_name: str
    collection_id: int
    collection_name: Optional[str] = None
    health_status: DocumentHealthStatus
    last_cited_at: Optional[str] = None
    days_since_last_citation: int
    content_updated_at: Optional[str] = None
    review_due_at: Optional[str] = None


class DocumentHealthResponse(BaseModel):
    summary: DocumentHealthSummary
    thresholds: DocumentHealthThresholds
    items: List[DocumentHealthItem]
    pagination: Pagination


