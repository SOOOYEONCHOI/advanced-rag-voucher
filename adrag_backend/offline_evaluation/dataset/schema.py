"""
Golden 데이터셋 스키마 정의.

GoldenRecord: 평가 케이스 1건의 완전한 표현.
GoldenEvidence: 정답을 뒷받침하는 chunk 단위 근거.

chunk_id가 retrieve/rerank 평가의 핵심 비교 키다.
expected_behavior가 threshold_fallback / guardrail 평가의 분기 기준이다.
"""

from typing import List, Literal, Optional
from typing_extensions import TypedDict


class GoldenEvidence(TypedDict):
    """정답 근거 chunk 1건."""

    document_id: str
    chunk_id: str        # retrieved_chunks / reranked_chunks 비교 키
    filename: str
    page_number: Optional[int]
    evidence_text: str   # 검수용 원문 발췌 — LLM 생성 금지, 청크 원문 그대로


class GoldenRecord(TypedDict):
    """평가 케이스 1건."""

    id: str              # "gold_0001" 형식, 컬렉션 내 유일
    collection_name: str
    user_id: str         # 보통 "eval_user"
    question: str
    expected_answer: str
    expected_evidence: List[GoldenEvidence]

    expected_behavior: Literal[
        "answer",            # 문서 기반 정상 답변
        "not_enough_info",   # 근거 없음 → 거절 답변
        "guardrail",         # 가드레일 차단 (greeting/smalltalk/unsafe 등)
        "permission_denied", # 권한 필터 차단
    ]

    question_type: Literal[
        "factual",        # 단일 사실 확인
        "procedural",     # 절차·순서
        "comparative",    # 비교·대조
        "multi_evidence", # 여러 chunk·문서 조합
        "unanswerable",   # 문서에 근거 없음
    ]

    difficulty: Literal["easy", "normal", "hard"]

    split: Literal["tune", "test"]  # tune: 파라미터 튜닝용 / test: 최종 평가용

    # 선택 필드
    tags: List[str]      # 예: ["near_miss", "fallback", "citation"]
    notes: Optional[str] # 검수자 메모