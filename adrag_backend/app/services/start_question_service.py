# 2026.11.12(woojin.jung) 추가 - 채팅 시작 화면 질문(추천 질문 + 많이 찾는 질문) 서비스
"""
채팅 시작 화면 질문 서비스.

- 추천 질문: 대화 주제 설정에서 등록한 질문(최대 MAX_RECOMMENDED개, 등록 순서대로 노출)
- 많이 찾는 질문: tb_query_logs 최근 POPULAR_DAYS일 집계 상위 POPULAR_LIMIT개
  (숨긴 질문·추천 질문과 같은 질문은 제외)
"""

import re
from typing import Any, Dict, List

from app.repositories.collection_question_repository import CollectionQuestionRepository

MAX_RECOMMENDED = 5
MAX_QUESTION_LENGTH = 100
MAX_HIDDEN = 50
POPULAR_LIMIT = 5
POPULAR_DAYS = 30


def normalize_question(text: str) -> str:
    """중복 판정용 키: 공백·문장부호를 지우고 소문자로 바꾼다."""
    return re.sub(r"[\W_]+", "", text or "").lower()


def _clean_questions(texts: List[str], label: str, max_count: int) -> List[Dict[str, str]]:
    """앞뒤 공백 제거·빈 값 제외·길이 검증 후 중복(정규화 기준)을 제거한다."""
    cleaned: List[Dict[str, str]] = []
    seen = set()
    for text in texts:
        question = (text or "").strip()
        if not question:
            continue
        if len(question) > MAX_QUESTION_LENGTH:
            raise ValueError(f"{label}은 {MAX_QUESTION_LENGTH}자까지 입력할 수 있습니다.")
        key = normalize_question(question)
        if not key:
            raise ValueError(f"{label}에 글자나 숫자를 입력해주세요.")
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"question_text": question, "normalized_text": key})
    if len(cleaned) > max_count:
        raise ValueError(f"{label}은 최대 {max_count}개까지 등록할 수 있습니다.")
    return cleaned


class StartQuestionService:
    """대화 주제별 채팅 시작 화면 질문 조회·저장."""

    def __init__(self) -> None:
        self.repo = CollectionQuestionRepository()

    def get_settings(self, collection_id: int) -> Dict[str, Any]:
        """대화 주제 설정 화면용: 추천 질문, 숨긴 질문, 현재 노출 중인 많이 찾는 질문."""
        rows = self.repo.list_by_collection(collection_id)
        recommended = [r for r in rows if r["question_type"] == "recommended"]
        hidden = [r for r in rows if r["question_type"] == "hidden"]
        return {
            "recommended": [r["question_text"] for r in recommended],
            "hidden": [r["question_text"] for r in hidden],
            "popular": self._popular(collection_id, recommended + hidden),
            "max_recommended": MAX_RECOMMENDED,
            "popular_days": POPULAR_DAYS,
        }

    def get_start_questions(self, collection_id: int) -> Dict[str, Any]:
        """채팅 시작 화면용: 추천 질문과 많이 찾는 질문."""
        rows = self.repo.list_by_collection(collection_id)
        return {
            "recommended": [r["question_text"] for r in rows if r["question_type"] == "recommended"],
            "popular": self._popular(collection_id, rows),
            "popular_days": POPULAR_DAYS,
        }

    def save_settings(
        self,
        collection_id: int,
        recommended: List[str],
        hidden: List[str],
        user_id: str,
    ) -> Dict[str, Any]:
        """추천 질문·숨긴 질문을 통째로 교체 저장한 뒤 최신 설정을 반환한다."""
        cleaned_recommended = _clean_questions(recommended, "추천 질문", MAX_RECOMMENDED)
        cleaned_hidden = _clean_questions(hidden, "숨긴 질문", MAX_HIDDEN)
        self.repo.replace_all(collection_id, cleaned_recommended, cleaned_hidden, user_id)
        return self.get_settings(collection_id)

    def _popular(self, collection_id: int, excluded_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """숨긴 질문·추천 질문과 같은 질문을 뺀 많이 찾는 질문 상위 POPULAR_LIMIT개."""
        excluded = {r["normalized_text"] for r in excluded_rows}
        candidates = self.repo.get_popular_queries(
            collection_id,
            days=POPULAR_DAYS,
            limit=POPULAR_LIMIT + len(excluded),
        )
        popular = [
            {"question": c["question_text"], "count": c["query_count"]}
            for c in candidates
            if normalize_question(c["question_text"]) not in excluded
        ]
        return popular[:POPULAR_LIMIT]
