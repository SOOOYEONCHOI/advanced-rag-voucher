"""
통계 서비스 — SCR-006 통계 대시보드.

# 2026.06.09(sooyeon.choi) 추가 - estimate_cost 정적 메서드 (Step 6 rag_service 연동용)
# 2026.06.16(sooyeon.choi) 추가 - 관리자/사용자 집계 메서드 추가 (StatsRepository 기반)
"""

from datetime import datetime, timedelta
from math import ceil
from typing import Any, Dict, List, Optional

from app.core.config import get_settings
from app.models.stats_models import StatsPeriodValue
from app.services.stats_common import (
    KST,
    fill_daily_usage,
    percentage_change,
    percentage_point_change,
    resolve_stats_period,
)


class StatsService:
    """통계 서비스 — 집계 로직 및 비용 계산 담당."""

    def __init__(self, db_path: Optional[str] = None):
        from app.repositories.stats_repository import StatsRepository
        self.repo = StatsRepository(db_path or get_settings().sqlite_db_path)
        self._settings = get_settings()

    @staticmethod
    def estimate_cost(
        model_id: Optional[str],
        prompt_tokens: Optional[int],
        completion_tokens: Optional[int],
    ) -> float:
        """모델별 단가 × 토큰 수로 추정 API 비용(USD)을 계산한다.

        model_pricing_usd에 없는 model_id는 0으로 처리한다.
        """
        pricing = get_settings().model_pricing_usd.get(
            model_id or "", {"input": 0.0, "output": 0.0}
        )
        pt = prompt_tokens or 0
        ct = completion_tokens or 0
        return round(pt / 1000 * pricing["input"] + ct / 1000 * pricing["output"], 6)

    # ── 관리자 대시보드 ──────────────────────────────────────────────────────

    def get_admin_summary(self, period: StatsPeriodValue) -> Dict[str, Any]:
        """관리자 요약 지표를 반환한다."""
        # 2026.06.19(sooyeon.choi) 추가 - 공통 KST 기간과 증감 계산 적용
        period_range = resolve_stats_period(period)
        start = period_range.start.isoformat(timespec="seconds")
        end = period_range.end.isoformat(timespec="seconds")
        ps = period_range.previous_start.isoformat(timespec="seconds")
        pe = period_range.previous_end.isoformat(timespec="seconds")

        cur_q = self.repo.count_queries(start, end)
        prev_q = self.repo.count_queries(ps, pe)

        fb_cur = self.repo.feedback_counts(start, end)
        fb_prev = self.repo.feedback_counts(ps, pe)
        cur_sat = (
            round(fb_cur["likes"] / fb_cur["responded"] * 100, 1)
            if fb_cur["responded"] else None
        )
        prev_sat = (
            round(fb_prev["likes"] / fb_prev["responded"] * 100, 1)
            if fb_prev["responded"] else None
        )

        cost_cur = self.repo.sum_cost(start, end)
        cost_prev = self.repo.sum_cost(ps, pe)
        period_days = (period_range.end.date() - period_range.start.date()).days + 1

        prob_cur = self.repo.count_problem_queries(start, end)
        prob_prev = self.repo.count_problem_queries(ps, pe)

        return {
            "period": period_range.as_response(),
            "query_count": {
                "value": cur_q,
                "previous_value": prev_q,
                "change_count": cur_q - prev_q,
                "change_pct": percentage_change(cur_q, prev_q),
            },
            "satisfaction": {
                "value_pct": cur_sat,
                "feedback_count": fb_cur["responded"],
                "like_count": fb_cur["likes"],
                "dislike_count": fb_cur["dislikes"],
                "previous_value_pct": prev_sat,
                "change_point": percentage_point_change(cur_sat, prev_sat),
            },
            "cost": {
                "total_usd": cost_cur["total"],
                "daily_average_usd": round(
                    cost_cur["total"] / period_days,
                    4,
                ),
                "previous_total_usd": cost_prev["total"],
                "change_usd": round(
                    cost_cur["total"] - cost_prev["total"],
                    4,
                ),
                "change_pct": percentage_change(
                    cost_cur["total"],
                    cost_prev["total"],
                ),
            },
            "flagged_queries": {
                "value": prob_cur,
                "previous_value": prob_prev,
                "change_count": prob_cur - prob_prev,
                "change_pct": percentage_change(prob_cur, prob_prev),
            },
        }

    def get_admin_usage_trend(
        self,
        period: StatsPeriodValue,
    ) -> Dict[str, Any]:
        """일별 질의수·비용 콤보 차트 데이터."""
        period_range = resolve_stats_period(period)
        trend = fill_daily_usage(
            period_range,
            self.repo.daily_usage_trend(
                period_range.start.isoformat(timespec="seconds"),
                period_range.end.isoformat(timespec="seconds"),
            ),
        )
        return {
            "period": period_range.as_response(),
            "items": trend,
            "total_query_count": sum(t["query_count"] for t in trend),
            "total_cost_usd": round(
                sum(t["cost_usd"] for t in trend),
                4,
            ),
        }

    # 2026.06.19(sooyeon.choi) 추가 - 관리자 주의 질의 페이지 응답
    def get_admin_flagged_queries(
        self,
        period: StatsPeriodValue,
        page: int,
        page_size: int,
    ) -> Dict[str, Any]:
        period_range = resolve_stats_period(period)
        start = period_range.start.isoformat(timespec="seconds")
        end = period_range.end.isoformat(timespec="seconds")
        total_count = self.repo.count_admin_flagged_queries(start, end)
        rows = self.repo.admin_flagged_queries(
            start,
            end,
            page_size,
            (page - 1) * page_size,
        )
        items = []
        for row in rows:
            issue_types = []
            if row["outcome_code"] in {
                "no_context",
                "retrieval_error",
                "llm_error",
                "system_error",
            }:
                issue_types.append(row["outcome_code"])
            if row["feedback"] == "dislike":
                issue_types.append("negative_feedback")

            if row["outcome_code"] == "no_context":
                issue_label = "검색 실패"
            elif row["outcome_code"] in {
                "retrieval_error",
                "llm_error",
                "system_error",
            }:
                issue_label = "답변 실패"
            else:
                issue_label = "부정 피드백"

            items.append({
                **row,
                "issue_types": issue_types,
                "issue_label": issue_label,
            })

        return {
            "items": items,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_count": total_count,
                "total_pages": ceil(total_count / page_size)
                if total_count else 0,
            },
        }

    def get_top_keywords(
        self,
        period: StatsPeriodValue,
        limit: int = 5,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """인기 키워드 Top N."""
        period_range = resolve_stats_period(period)
        rows = self.repo.top_keywords(
            period_range.start.isoformat(timespec="seconds"),
            period_range.end.isoformat(timespec="seconds"),
            limit,
            user_id,
        )
        top_count = rows[0]["count"] if rows else 0
        # 2026.06.19(sooyeon.choi) 추가 - 키워드 순위와 1위 기준 막대 비율 계산
        return [
            {
                "rank": index,
                "keyword": row["keyword"],
                "count": row["count"],
                "ratio_pct": (
                    round(row["count"] / top_count * 100, 1)
                    if top_count else 0.0
                ),
            }
            for index, row in enumerate(rows, start=1)
        ]

    def get_top_documents(
        self,
        period: StatsPeriodValue,
        limit: int = 5,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """최다 참조 문서 Top N."""
        period_range = resolve_stats_period(period)
        rows = self.repo.top_cited_documents(
            period_range.start.isoformat(timespec="seconds"),
            period_range.end.isoformat(timespec="seconds"),
            limit,
            user_id,
        )
        return [
            {"rank": index, **row}
            for index, row in enumerate(rows, start=1)
        ]

    def get_flagged_queries(
        self,
        period: StatsPeriodValue,
        limit: int = 10,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """주의 요망 질의 목록 (검색 실패 + 부정 피드백)."""
        period_range = resolve_stats_period(period)
        rows = self.repo.flagged_queries(
            period_range.start.isoformat(timespec="seconds"),
            period_range.end.isoformat(timespec="seconds"),
            limit,
            user_id,
        )
        # 2026.06.19(sooyeon.choi) 추가 - 화면 표시용 주의 유형과 라벨 구성
        result = []
        for row in rows:
            issue_types = []
            if row["outcome_code"] in {
                "no_context",
                "retrieval_error",
                "llm_error",
                "system_error",
            }:
                issue_types.append(row["outcome_code"])
            if row["feedback"] == "dislike":
                issue_types.append("negative_feedback")

            if row["outcome_code"] == "no_context":
                issue_label = "검색 실패"
            elif row["outcome_code"] in {
                "retrieval_error",
                "llm_error",
                "system_error",
            }:
                issue_label = "답변 실패"
            else:
                issue_label = "부정 피드백"

            result.append({
                **row,
                "issue_types": issue_types,
                "issue_label": issue_label,
            })
        return result

    def get_department_usage(
        self,
        period: StatsPeriodValue,
    ) -> Dict[str, Any]:
        """부서별 질의수·비중·만족도 (관리자 전용)."""
        # 2026.06.19(sooyeon.choi) 추가 - 부서 현황 응답 계약 적용
        period_range = resolve_stats_period(period)
        items = self.repo.department_usage(
            period_range.start.isoformat(timespec="seconds"),
            period_range.end.isoformat(timespec="seconds"),
        )
        total = sum(item["query_count"] for item in items)
        for item in items:
            item["query_ratio_pct"] = (
                round(item["query_count"] / total * 100, 1)
                if total else 0.0
            )
        return {"items": items, "total_query_count": total}

    def get_department_weekly_trend(self, weeks: int = 4) -> Dict[str, Any]:
        """부서별 주간 질의 추이 (관리자 전용)."""
        # 2026.06.19(sooyeon.choi) 추가 - 주간 추이 전용 서비스 분리
        return self.repo.department_weekly_trend(weeks)

    def get_top_users(
        self,
        period: StatsPeriodValue,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """사용자별 활동 Top N (관리자 전용)."""
        period_range = resolve_stats_period(period)
        rows = self.repo.top_users_by_activity(
            period_range.start.isoformat(timespec="seconds"),
            period_range.end.isoformat(timespec="seconds"),
            limit,
        )
        # 2026.06.19(sooyeon.choi) 추가 - 사용자 활동 순위 응답에 rank 부여
        return [
            {"rank": rank, **row}
            for rank, row in enumerate(rows, start=1)
        ]

    def get_document_health(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """장기간 미참조 문서 목록 (관리자 전용)."""
        # 2026.06.19(sooyeon.choi) 추가 - 관리자 문서 상태 요약·페이지 응답
        now = datetime.now(KST)
        uncited_before = (
            now - timedelta(days=self._settings.stats_dead_days)
        ).isoformat(timespec="seconds")
        summary = self.repo.document_health_summary(
            now.isoformat(timespec="seconds"),
            uncited_before,
        )
        total_count = self.repo.count_document_health_items(
            now.isoformat(timespec="seconds"),
            uncited_before,
        )
        rows = self.repo.document_health_items(
            now.isoformat(timespec="seconds"),
            uncited_before,
            page_size,
            (page - 1) * page_size,
        )
        items = []
        for row in rows:
            reference_at = datetime.fromisoformat(
                row.pop("citation_reference_at")
            )
            if reference_at.tzinfo is None:
                reference_at = reference_at.replace(tzinfo=KST)
            days_since = max(0, (now.date() - reference_at.date()).days)
            items.append({
                **row,
                "days_since_last_citation": days_since,
            })
        return {
            "summary": summary,
            "thresholds": {
                "uncited_days": self._settings.stats_dead_days,
                "review_reference_at": now.isoformat(timespec="seconds"),
            },
            "items": items,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_count": total_count,
                "total_pages": (
                    (total_count + page_size - 1) // page_size
                    if total_count else 0
                ),
            },
        }

    # ── 사용자 대시보드 ──────────────────────────────────────────────────────

    def get_user_summary(
        self,
        period: StatsPeriodValue,
        user_id: str,
    ) -> Dict[str, Any]:
        """요약 카드 4종: 내 총 질의수, 내 활동 일수, 내 만족도, 내 답변 성공률 + 증감."""
        # 2026.06.19(sooyeon.choi) 추가 - 사용자 요약에 공통 기간·증감 단위 적용
        period_range = resolve_stats_period(period)
        start = period_range.start.isoformat(timespec="seconds")
        end = period_range.end.isoformat(timespec="seconds")
        ps = period_range.previous_start.isoformat(timespec="seconds")
        pe = period_range.previous_end.isoformat(timespec="seconds")

        cur_q = self.repo.count_queries(start, end, user_id)
        prev_q = self.repo.count_queries(ps, pe, user_id)

        cur_days = self.repo.count_active_days(start, end, user_id)
        prev_days = self.repo.count_active_days(ps, pe, user_id)

        fb_cur = self.repo.feedback_counts(start, end, user_id)
        fb_prev = self.repo.feedback_counts(ps, pe, user_id)
        cur_sat = (
            round(fb_cur["likes"] / fb_cur["responded"] * 100, 1)
            if fb_cur["responded"] else None
        )
        prev_sat = (
            round(fb_prev["likes"] / fb_prev["responded"] * 100, 1)
            if fb_prev["responded"] else None
        )

        success_cur = self.repo.success_counts(start, end, user_id)
        success_prev = self.repo.success_counts(ps, pe, user_id)
        cur_sr = (
            round(
                success_cur["success_count"]
                / success_cur["completed_count"]
                * 100,
                1,
            )
            if success_cur["completed_count"] else None
        )
        prev_sr = (
            round(
                success_prev["success_count"]
                / success_prev["completed_count"]
                * 100,
                1,
            )
            if success_prev["completed_count"] else None
        )

        return {
            "period": period_range.as_response(),
            "query_count": {
                "value": cur_q,
                "previous_value": prev_q,
                "change_count": cur_q - prev_q,
                "change_pct": percentage_change(cur_q, prev_q),
            },
            "active_days": {
                "value": cur_days,
                "period_days": (
                    period_range.end.date() - period_range.start.date()
                ).days + 1,
                "previous_value": prev_days,
                "change_count": cur_days - prev_days,
            },
            "satisfaction": {
                "value_pct": cur_sat,
                "feedback_count": fb_cur["responded"],
                "like_count": fb_cur["likes"],
                "dislike_count": fb_cur["dislikes"],
                "previous_value_pct": prev_sat,
                "change_point": percentage_point_change(cur_sat, prev_sat),
            },
            "success_rate": {
                "value_pct": cur_sr,
                "success_count": success_cur["success_count"],
                "failure_count": success_cur["failure_count"],
                "previous_value_pct": prev_sr,
                "change_point": percentage_point_change(cur_sr, prev_sr),
            },
        }

    def get_user_usage_trend(
        self,
        period: StatsPeriodValue,
        user_id: str,
    ) -> Dict[str, Any]:
        """내 일별 질의수·비용 콤보 차트 데이터."""
        period_range = resolve_stats_period(period)
        trend = fill_daily_usage(
            period_range,
            self.repo.daily_usage_trend(
                period_range.start.isoformat(timespec="seconds"),
                period_range.end.isoformat(timespec="seconds"),
                user_id,
            ),
        )
        return {
            "period": period_range.as_response(),
            "items": trend,
            "total_query_count": sum(t["query_count"] for t in trend),
            "total_cost_usd": round(
                sum(t["cost_usd"] for t in trend),
                4,
            ),
        }
