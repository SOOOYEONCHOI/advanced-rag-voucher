# 2026.06.16(sooyeon.choi) 추가 - SCR-006 통계 대시보드 집계 전담 Repository
"""
통계 집계 Repository — tb_query_logs, tb_query_citations, tb_users, tb_documents JOIN.

읽기 전용. user_id 파라미터로 관리자(전체)/사용자(본인) 공통 처리한다.
"""

import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.repositories.database import get_database_manager

logger = logging.getLogger(__name__)

# 2026.11.18(sooyeon.choi) 추가 - 시험용 일괄 질의(batch_eval) 제외(통계·순위·문서 참조 집계 공통 조건)
BATCH_EVAL_EXCLUDE = "input_mode <> 'batch_eval'"

KST = timezone(timedelta(hours=9))


def _kst_now() -> datetime:
    return datetime.now(KST)


def _date_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S+09:00")


class StatsRepository:
    """집계 쿼리 전담 (읽기 전용)."""

    def __init__(self):
        self.db = get_database_manager()

    # ── 기간 필터 헬퍼 ──────────────────────────────────────────────────────

    def _where(
        self,
        start: str,
        end: str,
        user_id: Optional[str] = None,
        table_alias: str = "l",
    ) -> Tuple[str, list]:
        """created_at 범위 + 선택적 user_id 조건 문자열과 파라미터를 반환한다."""
        cond = [f"{table_alias}.created_at >= ?", f"{table_alias}.created_at < ?"]
        # 2026.11.18(sooyeon.choi) 추가 - 시험용 일괄 질의(batch_eval) 제외
        cond.append(f"{table_alias}.{BATCH_EVAL_EXCLUDE}")
        params: list = [start, end]
        if user_id:
            cond.append(f"{table_alias}.user_id = ?")
            params.append(user_id)
        return "WHERE " + " AND ".join(cond), params

    # ── 요약 카드 집계 ──────────────────────────────────────────────────────

    def count_queries(
        self, start: str, end: str, user_id: Optional[str] = None
    ) -> int:
        """기간 내 총 질의 수."""
        where, params = self._where(start, end, user_id)
        rows = self.db.execute_query(
            f"SELECT COUNT(*) AS cnt FROM tb_query_logs l {where}", tuple(params)
        )
        return rows[0]["cnt"] if rows else 0

    def count_active_days(self, start: str, end: str, user_id: str) -> int:
        """사용자의 기간 내 질의 발생 일수 (사용자 전용)."""
        rows = self.db.execute_query(
            """
            -- 2026.10.16 Phase 1.5 - timestamptz의 KST 날짜로 집계(기존: ISO KST 문자열 앞 10자)
            SELECT COUNT(DISTINCT (created_at AT TIME ZONE 'Asia/Seoul')::date) AS cnt
            FROM tb_query_logs
            WHERE created_at >= ? AND created_at < ? AND user_id = ?
              AND input_mode <> 'batch_eval'  -- 2026.11.18(sooyeon.choi) 추가 - 시험용 일괄 질의(batch_eval) 제외
            """,
            (start, end, user_id),
        )
        return rows[0]["cnt"] if rows else 0

    def count_problem_queries(
        self, start: str, end: str, user_id: Optional[str] = None
    ) -> int:
        """검색·생성 실패 또는 부정 피드백 질의 수."""
        # 2026.06.19(sooyeon.choi) 추가 - outcome_code 기반 주의 질의 집계
        where, params = self._where(start, end, user_id)
        rows = self.db.execute_query(
            f"""
            SELECT COUNT(*) AS cnt FROM tb_query_logs l {where}
              AND (
                outcome_code IN (
                  'no_context', 'retrieval_error', 'llm_error', 'system_error'
                )
                OR feedback = 0
              )
            """,
            tuple(params),
        )
        return rows[0]["cnt"] if rows else 0

    def feedback_counts(
        self, start: str, end: str, user_id: Optional[str] = None
    ) -> Dict[str, int]:
        """좋아요(1), 별로에요(0), 응답 수 반환."""
        where, params = self._where(start, end, user_id)
        rows = self.db.execute_query(
            f"""
            SELECT
              SUM(CASE WHEN feedback = 1 THEN 1 ELSE 0 END) AS likes,
              SUM(CASE WHEN feedback = 0 THEN 1 ELSE 0 END) AS dislikes,
              SUM(CASE WHEN feedback IS NOT NULL THEN 1 ELSE 0 END) AS responded
            FROM tb_query_logs l {where}
            """,
            tuple(params),
        )
        if not rows:
            return {"likes": 0, "dislikes": 0, "responded": 0}
        r = rows[0]
        return {
            "likes": int(r["likes"] or 0),
            "dislikes": int(r["dislikes"] or 0),
            "responded": int(r["responded"] or 0),
        }

    def success_counts(
        self, start: str, end: str, user_id: Optional[str] = None
    ) -> Dict[str, int]:
        """성공률 계산용 성공·실패·완료 질의 수."""
        # 2026.06.19(sooyeon.choi) 추가 - 가드레일·검증·취소를 성공률 분모에서 제외
        where, params = self._where(start, end, user_id)
        rows = self.db.execute_query(
            f"""
            SELECT
              SUM(CASE WHEN outcome_code = 'success' THEN 1 ELSE 0 END) AS success_count,
              SUM(
                CASE WHEN outcome_code IN (
                  'no_context', 'retrieval_error', 'llm_error', 'system_error'
                ) THEN 1 ELSE 0 END
              ) AS failure_count
            FROM tb_query_logs l {where}
            """,
            tuple(params),
        )
        if not rows:
            return {
                "success_count": 0,
                "failure_count": 0,
                "completed_count": 0,
            }
        success_count = int(rows[0]["success_count"] or 0)
        failure_count = int(rows[0]["failure_count"] or 0)
        return {
            "success_count": success_count,
            "failure_count": failure_count,
            "completed_count": success_count + failure_count,
        }

    def sum_cost(
        self, start: str, end: str, user_id: Optional[str] = None
    ) -> Dict[str, float]:
        """총 비용 + 일평균 비용 (USD)."""
        where, params = self._where(start, end, user_id)
        rows = self.db.execute_query(
            f"SELECT SUM(cost_usd) AS total FROM tb_query_logs l {where}",
            tuple(params),
        )
        total = float(rows[0]["total"] or 0) if rows else 0.0
        # 일수 계산
        try:
            d_start = datetime.fromisoformat(start)
            d_end = datetime.fromisoformat(end)
            days = max((d_end - d_start).days, 1)
        except Exception:
            days = 1
        return {"total": round(total, 4), "daily_avg": round(total / days, 4)}

    # ── 시계열 ─────────────────────────────────────────────────────────────

    def daily_usage_trend(
        self, start: str, end: str, user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """일별 질의수 + 비용 시계열."""
        where, params = self._where(start, end, user_id)
        rows = self.db.execute_query(
            f"""
            SELECT
              -- 2026.10.16 Phase 1.5 - timestamptz → KST 날짜 문자열(YYYY-MM-DD)
              to_char(l.created_at AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD') AS day,
              COUNT(*) AS query_count,
              COALESCE(SUM(l.cost_usd), 0) AS cost_usd
            FROM tb_query_logs l {where}
            GROUP BY 1
            ORDER BY day
            """,
            tuple(params),
        )
        return [
            {
                "date": r["day"],
                "query_count": r["query_count"],
                "cost_usd": round(float(r["cost_usd"] or 0), 4),
            }
            for r in rows
        ]

    # ── 키워드 ────────────────────────────────────────────────────────────

    def top_keywords(
        self,
        start: str,
        end: str,
        limit: int = 5,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """인기 키워드 Top N. jsonb_array_elements_text 실패 시 Python Counter 폴백."""
        where, params = self._where(start, end, user_id)
        # 2026.10.16 Phase 1.5 - json_each → jsonb_array_elements_text
        try:
            rows = self.db.execute_query(
                f"""
                SELECT keyword, COUNT(*) AS cnt
                FROM (
                  SELECT DISTINCT l.log_id, k.value AS keyword
                  FROM tb_query_logs l, jsonb_array_elements_text(l.extracted_keywords) AS k(value)
                  {where} AND l.extracted_keywords IS NOT NULL
                ) AS kw
                GROUP BY keyword
                ORDER BY cnt DESC, keyword ASC
                LIMIT ?
                """,
                tuple(params) + (limit,),
            )
            return [{"keyword": r["keyword"], "count": r["cnt"]} for r in rows]
        except Exception:
            pass  # 집계 쿼리 실패 → Python 폴백

        rows = self.db.execute_query(
            f"""
            SELECT extracted_keywords FROM tb_query_logs l
            {where} AND extracted_keywords IS NOT NULL
            """,
            tuple(params),
        )
        counter: Counter = Counter()
        for r in rows:
            try:
                # 2026.06.19(sooyeon.choi) 추가 - 동일 질의 내 키워드는 1회만 집계
                counter.update(set(json.loads(r["extracted_keywords"])))
            except Exception:
                pass
        return [
            {"keyword": kw, "count": cnt}
            for kw, cnt in counter.most_common(limit)
        ]

    # ── 최다 참조 문서 ────────────────────────────────────────────────────

    def top_cited_documents(
        self,
        start: str,
        end: str,
        limit: int = 5,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """최다 참조 문서 Top N."""
        # 2026.06.19(sooyeon.choi) 추가 - 질의 단위 참조 수와 컬렉션 스냅샷 반환
        user_cond = "AND l.user_id = ?" if user_id else ""
        params: list = [start, end]
        if user_id:
            params.append(user_id)
        params.append(limit)
        rows = self.db.execute_query(
            f"""
            SELECT
              c.document_id,
              c.original_filename AS document_name,
              c.collection_id,
              MAX(c.collection_name_snapshot) AS collection_name,
              COUNT(DISTINCT c.log_id) AS citation_count,
              MAX(c.cited_at) AS last_cited_at
            FROM tb_query_citations c
            JOIN tb_query_logs l ON c.log_id = l.log_id
            WHERE l.created_at >= ? AND l.created_at < ?
              AND l.input_mode <> 'batch_eval'  -- 2026.11.18(sooyeon.choi) 추가 - 시험용 일괄 질의(batch_eval) 제외
              {user_cond}
            GROUP BY c.document_id, c.original_filename, c.collection_id
            ORDER BY citation_count DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return [
            {
                "document_id": r["document_id"],
                "document_name": r["document_name"],
                "collection_id": r["collection_id"],
                "collection_name": r["collection_name"],
                "citation_count": r["citation_count"],
                "last_cited_at": r["last_cited_at"],
            }
            for r in rows
        ]

    # ── 주의 요망 질의 ────────────────────────────────────────────────────

    def flagged_queries(
        self,
        start: str,
        end: str,
        limit: int = 10,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """검색·생성 실패 또는 부정 피드백 질의 목록."""
        # 2026.06.19(sooyeon.choi) 추가 - 사용자 통계용 outcome_code·피드백 반환
        where, params = self._where(start, end, user_id)
        params.append(limit)
        rows = self.db.execute_query(
            f"""
            SELECT
              l.log_id, l.user_id, l.query_text, l.outcome_code,
              l.feedback, l.created_at, l.model_id
            FROM tb_query_logs l {where}
              AND (
                l.outcome_code IN (
                  'no_context', 'retrieval_error', 'llm_error', 'system_error'
                )
                OR l.feedback = 0
              )
            ORDER BY l.created_at DESC LIMIT ?
            """,
            tuple(params),
        )
        return [
            {
                "log_id": r["log_id"],
                "user_id": r["user_id"],
                "query_text": r["query_text"],
                "outcome_code": r["outcome_code"],
                "feedback": (
                    "like" if r["feedback"] == 1
                    else "dislike" if r["feedback"] == 0
                    else None
                ),
                "created_at": r["created_at"],
                "model_id": r["model_id"],
            }
            for r in rows
        ]

    # 2026.06.19(sooyeon.choi) 추가 - 관리자 주의 질의 전체 건수
    def count_admin_flagged_queries(self, start: str, end: str) -> int:
        rows = self.db.execute_query(
            """
            SELECT COUNT(*) AS cnt
            FROM tb_query_logs l
            WHERE l.created_at >= ? AND l.created_at < ?
              AND l.input_mode <> 'batch_eval'  -- 2026.11.18(sooyeon.choi) 추가 - 시험용 일괄 질의(batch_eval) 제외
              AND (
                l.outcome_code IN (
                  'no_context', 'retrieval_error', 'llm_error', 'system_error'
                )
                OR l.feedback = 0
              )
            """,
            (start, end),
        )
        return int(rows[0]["cnt"] or 0) if rows else 0

    # 2026.06.19(sooyeon.choi) 추가 - 관리자 주의 질의 사용자 정보·페이지 조회
    def admin_flagged_queries(
        self,
        start: str,
        end: str,
        limit: int,
        offset: int,
    ) -> List[Dict[str, Any]]:
        rows = self.db.execute_query(
            """
            SELECT
              l.log_id,
              l.user_id,
              u.user_name,
              COALESCE(NULLIF(l.department_snapshot, ''), '미지정') AS department,
              l.query_text,
              l.outcome_code,
              l.feedback,
              l.feedback_reasons,
              l.feedback_comment,
              l.model_id,
              l.created_at
            FROM tb_query_logs l
            LEFT JOIN tb_users u ON l.user_id = u.user_id
            WHERE l.created_at >= ? AND l.created_at < ?
              AND l.input_mode <> 'batch_eval'  -- 2026.11.18(sooyeon.choi) 추가 - 시험용 일괄 질의(batch_eval) 제외
              AND (
                l.outcome_code IN (
                  'no_context', 'retrieval_error', 'llm_error', 'system_error'
                )
                OR l.feedback = 0
              )
            ORDER BY l.created_at DESC, l.log_id DESC
            LIMIT ? OFFSET ?
            """,
            (start, end, limit, offset),
        )
        return [
            {
                "log_id": r["log_id"],
                "user_id": r["user_id"],
                "user_name": r["user_name"],
                "department": r["department"],
                "query_text": r["query_text"],
                "outcome_code": r["outcome_code"],
                "feedback": (
                    "like" if r["feedback"] == 1
                    else "dislike" if r["feedback"] == 0
                    else None
                ),
                # 2026.11.05(woojin.jung) 추가 - 부정 피드백 사유·의견
                "feedback_reasons": json.loads(r["feedback_reasons"]) if r["feedback_reasons"] else [],
                "feedback_comment": r["feedback_comment"],
                "model_id": r["model_id"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # ── 부서별 통계 (관리자 전용) ─────────────────────────────────────────

    def department_usage(
        self, start: str, end: str
    ) -> List[Dict[str, Any]]:
        """부서별 질의수 + 만족도 (관리자 전용)."""
        rows = self.db.execute_query(
            """
            -- 2026.06.19(sooyeon.choi) 추가 - 질의 당시 부서 스냅샷 기준 집계
            SELECT
              COALESCE(NULLIF(TRIM(l.department_snapshot), ''), '미지정') AS department,
              COUNT(*) AS query_count,
              SUM(CASE WHEN l.feedback = 1 THEN 1 ELSE 0 END) AS likes,
              SUM(CASE WHEN l.feedback IS NOT NULL THEN 1 ELSE 0 END) AS responded
            FROM tb_query_logs l
            WHERE l.created_at >= ? AND l.created_at < ?
              AND l.input_mode <> 'batch_eval'  -- 2026.11.18(sooyeon.choi) 추가 - 시험용 일괄 질의(batch_eval) 제외
            GROUP BY COALESCE(NULLIF(TRIM(l.department_snapshot), ''), '미지정')
            ORDER BY query_count DESC, department ASC
            """,
            (start, end),
        )
        result = []
        for r in rows:
            resp = r["responded"] or 0
            likes = r["likes"] or 0
            satisfaction_pct = round(likes / resp * 100, 1) if resp > 0 else None
            result.append(
                {
                    "department": r["department"],
                    "query_count": r["query_count"],
                    "satisfaction_pct": satisfaction_pct,
                    "feedback_count": resp,
                }
            )
        return result

    def department_weekly_trend(self, weeks: int = 4) -> Dict[str, Any]:
        """부서별 주간 추이 (관리자 전용)."""
        # 2026.06.19(sooyeon.choi) 추가 - 월요일 시작·일요일 종료 주차 계산
        now = _kst_now()
        current_monday = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        week_items: List[Dict[str, str]] = []
        periods: List[Tuple[str, str]] = []
        for i in range(weeks - 1, -1, -1):
            week_start = current_monday - timedelta(weeks=i)
            week_end = week_start + timedelta(days=7)
            iso_year, iso_week, _ = week_start.isocalendar()
            month_start = week_start.replace(day=1)
            month_week = ((week_start.day + month_start.weekday() - 1) // 7) + 1
            week_items.append({
                "key": f"{iso_year}-W{iso_week:02d}",
                "label": f"{week_start.month}월 {month_week}주",
                "start_date": week_start.date().isoformat(),
                "end_date": (week_end - timedelta(days=1)).date().isoformat(),
            })
            periods.append((_date_str(week_start), _date_str(week_end)))

        dept_rows = self.db.execute_query(
            """
            -- 2026.06.19(sooyeon.choi) 추가 - 주간 추이도 부서 스냅샷 사용
            SELECT DISTINCT
              COALESCE(NULLIF(TRIM(department_snapshot), ''), '미지정') AS department
            FROM tb_query_logs
            WHERE created_at >= ?
              AND input_mode <> 'batch_eval'  -- 2026.11.18(sooyeon.choi) 추가 - 시험용 일괄 질의(batch_eval) 제외
            ORDER BY department ASC
            """,
            (periods[0][0],),
        )
        departments = [r["department"] for r in dept_rows]

        series = []
        for dept in departments:
            data = []
            for start, end in periods:
                rows = self.db.execute_query(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM tb_query_logs
                    WHERE created_at >= ? AND created_at < ?
                      AND input_mode <> 'batch_eval'  -- 2026.11.18(sooyeon.choi) 추가 - 시험용 일괄 질의(batch_eval) 제외
                      AND COALESCE(
                        NULLIF(TRIM(department_snapshot), ''),
                        '미지정'
                      ) = ?
                    """,
                    (start, end, dept),
                )
                data.append(rows[0]["cnt"] if rows else 0)
            series.append({"department": dept, "values": data})

        return {"weeks": week_items, "series": series}

    # ── 사용자 활동 Top N (관리자 전용) ──────────────────────────────────

    def top_users_by_activity(
        self, start: str, end: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """사용자별 질의수·만족도 Top N (관리자 전용)."""
        rows = self.db.execute_query(
            """
            -- 2026.06.19(sooyeon.choi) 추가 - 사용자 순위 동률 정렬 및 최신 부서 스냅샷 적용
            SELECT
              l.user_id,
              u.user_name,
              COALESCE(
                NULLIF(TRIM((
                  SELECT latest.department_snapshot
                  FROM tb_query_logs latest
                  WHERE latest.user_id = l.user_id
                    AND latest.created_at >= ?
                    AND latest.created_at < ?
                    AND latest.input_mode <> 'batch_eval'  -- 2026.11.18(sooyeon.choi) 추가 - 시험용 일괄 질의(batch_eval) 제외
                  ORDER BY latest.created_at DESC, latest.log_id DESC
                  LIMIT 1
                )), ''),
                '미지정'
              ) AS department,
              COUNT(*) AS query_count,
              SUM(CASE WHEN l.feedback = 1 THEN 1 ELSE 0 END) AS likes,
              SUM(CASE WHEN l.feedback IS NOT NULL THEN 1 ELSE 0 END) AS responded
            FROM tb_query_logs l
            LEFT JOIN tb_users u ON l.user_id = u.user_id
            WHERE l.created_at >= ? AND l.created_at < ?
              AND l.input_mode <> 'batch_eval'  -- 2026.11.18(sooyeon.choi) 추가 - 시험용 일괄 질의(batch_eval) 제외
            GROUP BY l.user_id, u.user_name  -- 2026.10.16 Phase 1.5: PostgreSQL은 비집계 컬럼을 GROUP BY에 명시
            ORDER BY
              query_count DESC,
              CASE
                WHEN SUM(CASE WHEN l.feedback IS NOT NULL THEN 1 ELSE 0 END) = 0
                  THEN -1
                ELSE 1.0 * SUM(CASE WHEN l.feedback = 1 THEN 1 ELSE 0 END)
                  / SUM(CASE WHEN l.feedback IS NOT NULL THEN 1 ELSE 0 END)
              END DESC,
              l.user_id ASC
            LIMIT ?
            """,
            (start, end, start, end, limit),
        )
        result = []
        for r in rows:
            resp = r["responded"] or 0
            likes = r["likes"] or 0
            satisfaction_pct = round(likes / resp * 100, 1) if resp > 0 else None
            result.append(
                {
                    "user_id": r["user_id"],
                    "user_name": r["user_name"],
                    "department": r["department"],
                    "query_count": r["query_count"],
                    "satisfaction_pct": satisfaction_pct,
                    "feedback_count": resp,
                }
            )
        return result

    # ── 미참조·검토 기한 초과 문서 (관리자 전용) ────────────────────────

    def document_health_summary(
        self,
        review_reference_at: str,
        uncited_before: str,
    ) -> Dict[str, int]:
        """준비 완료 문서 전체 및 미참조 건수를 반환한다."""
        # 2026.06.19(sooyeon.choi) 추가 - 문서 상태 요약과 목록의 동일 기준 적용
        rows = self.db.execute_query(
            """
            WITH document_health AS (
              SELECT
                d.document_id,
                d.created_at,
                d.review_due_at,
                MAX(cit.cited_at) AS last_cited_at
              FROM tb_documents d
              LEFT JOIN tb_query_citations cit
                ON cit.document_id = d.document_id
               -- 2026.11.18(sooyeon.choi) 추가 - 시험용 일괄 질의(batch_eval) 제외(일괄 질의 인용은 문서 참조로 보지 않음)
               AND NOT EXISTS (
                 SELECT 1 FROM tb_query_logs bl
                 WHERE bl.log_id = cit.log_id AND bl.input_mode = 'batch_eval'
               )
              WHERE d.deleted_at IS NULL AND d.status = 'ready'
              GROUP BY d.document_id
            )
            SELECT
              COUNT(*) AS total_document_count,
              SUM(
                CASE WHEN COALESCE(last_cited_at, created_at) < ?
                  THEN 1 ELSE 0 END
              ) AS uncited_count,
              SUM(CASE WHEN review_due_at IS NOT NULL AND review_due_at < ? THEN 1 ELSE 0 END)
                AS review_overdue_count
            FROM document_health
            """,
            (uncited_before, review_reference_at),
        )
        row = rows[0] if rows else {}
        return {
            "review_overdue_count": row["review_overdue_count"] or 0,
            "uncited_count": row["uncited_count"] or 0,
            "total_document_count": row["total_document_count"] or 0,
        }

    def count_document_health_items(
        self,
        review_reference_at: str,
        uncited_before: str,
    ) -> int:
        """미참조 문서 건수."""
        rows = self.db.execute_query(
            """
            WITH document_health AS (
              SELECT
                d.document_id,
                d.created_at,
                d.review_due_at,
                MAX(cit.cited_at) AS last_cited_at
              FROM tb_documents d
              LEFT JOIN tb_query_citations cit
                ON cit.document_id = d.document_id
               -- 2026.11.18(sooyeon.choi) 추가 - 시험용 일괄 질의(batch_eval) 제외(일괄 질의 인용은 문서 참조로 보지 않음)
               AND NOT EXISTS (
                 SELECT 1 FROM tb_query_logs bl
                 WHERE bl.log_id = cit.log_id AND bl.input_mode = 'batch_eval'
               )
              WHERE d.deleted_at IS NULL AND d.status = 'ready'
              GROUP BY d.document_id
            )
            SELECT COUNT(*) AS cnt
            FROM document_health
            WHERE COALESCE(last_cited_at, created_at) < ?
               OR (review_due_at IS NOT NULL AND review_due_at < ?)
            """,
            (uncited_before, review_reference_at),
        )
        return rows[0]["cnt"] if rows else 0

    def document_health_items(
        self,
        review_reference_at: str,
        uncited_before: str,
        limit: int,
        offset: int,
    ) -> List[Dict[str, Any]]:
        """미참조 문서 페이지를 반환한다."""
        rows = self.db.execute_query(
            """
            WITH document_health AS (
              SELECT
                d.document_id,
                COALESCE(NULLIF(d.original_filename, ''), d.title, d.document_id)
                  AS document_name,
                d.collection_id,
                c.display_name AS collection_name,
                d.content_updated_at,
                d.review_due_at,
                d.created_at,
                MAX(cit.cited_at) AS last_cited_at
              FROM tb_documents d
              LEFT JOIN tb_collections c
                ON c.collection_id = d.collection_id
              LEFT JOIN tb_query_citations cit
                ON cit.document_id = d.document_id
               -- 2026.11.18(sooyeon.choi) 추가 - 시험용 일괄 질의(batch_eval) 제외(일괄 질의 인용은 문서 참조로 보지 않음)
               AND NOT EXISTS (
                 SELECT 1 FROM tb_query_logs bl
                 WHERE bl.log_id = cit.log_id AND bl.input_mode = 'batch_eval'
               )
              WHERE d.deleted_at IS NULL AND d.status = 'ready'
              GROUP BY d.document_id, c.display_name  -- 2026.10.16 Phase 1.5: 조인 테이블 컬럼은 GROUP BY에 명시
            )
            SELECT *, CASE
              WHEN review_due_at IS NOT NULL AND review_due_at < ?
                   AND COALESCE(last_cited_at, created_at) < ?
                THEN 'review_overdue_and_uncited'
              WHEN review_due_at IS NOT NULL AND review_due_at < ? THEN 'review_overdue'
              ELSE 'uncited'
            END AS health_status
            FROM document_health
            WHERE COALESCE(last_cited_at, created_at) < ?
               OR (review_due_at IS NOT NULL AND review_due_at < ?)
            ORDER BY
              COALESCE(last_cited_at, created_at) ASC,
              document_id ASC
            LIMIT ? OFFSET ?
            """,
            (
                review_reference_at,
                uncited_before,
                review_reference_at,
                uncited_before,
                review_reference_at,
                limit,
                offset,
            ),
        )
        return [
            {
                "document_id": row["document_id"],
                "document_name": row["document_name"],
                "collection_id": row["collection_id"],
                "collection_name": row["collection_name"],
                "health_status": row["health_status"],
                "last_cited_at": row["last_cited_at"],
                "citation_reference_at": (
                    row["last_cited_at"] or row["created_at"]
                ),
                "content_updated_at": (
                    row["content_updated_at"] or row["created_at"]
                ),
                "review_due_at": row["review_due_at"],
            }
            for row in rows
        ]
