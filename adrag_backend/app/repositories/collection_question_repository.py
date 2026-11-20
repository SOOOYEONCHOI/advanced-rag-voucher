# 2026.11.12(woojin.jung) 추가 - 채팅 시작 화면 질문 Repository (tb_collection_questions + tb_query_logs 집계)
"""
Collection start-question repository.

- tb_collection_questions: 추천 질문(recommended)·숨긴 질문(hidden) 조회/일괄 저장
- tb_query_logs: 많이 찾는 질문 집계
"""

import logging
from typing import Any, Dict, List

from app.repositories.database import get_database_manager
from app.utils.datetime import now_kst_iso

logger = logging.getLogger(__name__)

# 2026.11.12(woojin.jung) 추가 - 로그 질문 묶음 기준(공백·문장부호 제거 + 소문자)
_GROUP_KEY_SQL = "lower(regexp_replace(query_text, '[[:space:][:punct:]]+', '', 'g'))"


class CollectionQuestionRepository:
    """tb_collection_questions Read/Write + 많이 찾는 질문 집계 Repository."""

    def __init__(self):
        self.db = get_database_manager()

    def list_by_collection(self, collection_id: int) -> List[Dict[str, Any]]:
        """대화 주제의 추천·숨김 질문을 유형별 sort_order 순으로 반환한다."""
        rows = self.db.execute_query(
            """
            SELECT question_id, question_type, question_text, normalized_text, sort_order
            FROM tb_collection_questions
            WHERE collection_id = ?
            ORDER BY question_type, sort_order, question_id
            """,
            (collection_id,),
        )
        return [dict(row) for row in rows]

    def replace_all(
        self,
        collection_id: int,
        recommended: List[Dict[str, str]],
        hidden: List[Dict[str, str]],
        user_id: str,
    ) -> None:
        """추천·숨김 질문을 한 트랜잭션에서 통째로 교체한다.

        recommended·hidden 항목은 question_text, normalized_text 키를 포함해야 한다.
        recommended는 목록 순서가 노출 순서(sort_order)가 된다.
        """
        now = now_kst_iso()
        rows = [
            (collection_id, question_type, item["question_text"], item["normalized_text"], order, user_id, now, now)
            for question_type, items in (("recommended", recommended), ("hidden", hidden))
            for order, item in enumerate(items)
        ]
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM tb_collection_questions WHERE collection_id = ?", (collection_id,))
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO tb_collection_questions
                        (collection_id, question_type, question_text, normalized_text,
                         sort_order, created_by, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    row,
                )

    def get_popular_queries(self, collection_id: int, days: int, limit: int) -> List[Dict[str, Any]]:
        """최근 days일 동안 답변에 성공한 직접 입력(text·voice) 질문을 묶어 많이 물은 순으로 반환한다.

        '별로예요'(feedback=0) 평가를 받은 질의는 제외한다.
        같은 묶음에서 가장 많이 쓰인 문장을 대표 질문으로 쓴다.
        """
        rows = self.db.execute_query(
            f"""
            SELECT mode() WITHIN GROUP (ORDER BY query_text) AS question_text,
                   COUNT(*) AS query_count
            FROM tb_query_logs
            WHERE collection_id = ?
              AND created_at >= now() - (? * interval '1 day')
              AND outcome_code = 'success'
              AND input_mode IN ('text', 'voice')
              AND feedback IS DISTINCT FROM 0
              AND {_GROUP_KEY_SQL} <> ''
            GROUP BY {_GROUP_KEY_SQL}
            ORDER BY query_count DESC, MAX(created_at) DESC
            LIMIT ?
            """,
            (collection_id, days, limit),
        )
        return [{"question_text": row["question_text"], "query_count": row["query_count"]} for row in rows]
