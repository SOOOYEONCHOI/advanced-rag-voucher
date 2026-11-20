"""평가 시스템 API 요청/응답 Pydantic 모델.

(reference app/evaluation/schemas.py 이식 + ①축 필드 expected_behavior/tags 확장)
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ── 데이터셋 ────────────────────────────────────────────────────────────────

class DatasetCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    collection_id: int
    gen_config: Dict[str, Any] = Field(default_factory=dict)
    # gen_config 예: {"target_count": 50, "max_per_doc": 5, "min_chunk_chars": 200,
    #                "sampling_seed": 42,
    #                "type_ratio": {"factual": 5, "procedural": 3, "comparative": 1, "multihop": 1}}
    # 2026.11.19(sooyeon.choi) 추가 - 단일 출처 생성(유형 구분 없음)
    #   {"generation_mode": "law_article" | "single_section" (기본 "typed"),
    #    "target_count": 60, "include_annex": false, "article_ref_ratio": 0.3,
    #    "max_questions_per_chunk": 2, "query_id_prefix": "산안", "llm_model": "gemma-4-31B-it-FP8"}


class QaItemUpdateRequest(BaseModel):
    question: Optional[str] = None
    gold_answer: Optional[str] = None
    gold_chunk_ids: Optional[List[str]] = None
    gold_document_ids: Optional[List[str]] = None
    # ①축 확장 — 가드레일/거절 분기와 한국어 세그먼트 태그를 검수 화면에서 편집
    expected_behavior: Optional[
        Literal["answer", "not_enough_info", "guardrail", "permission_denied"]
    ] = None
    tags: Optional[List[str]] = None


class BulkReviewRequest(BaseModel):
    qa_ids: List[int]
    action: Literal["approve", "reject"]


class FinalizeRequest(BaseModel):
    note: str = ""


# 2026.11.20(sooyeon.choi) 수정 - 합본 데이터셋 생성(확정 데이터셋 2개 이상, 고른 순서대로 이어 붙임)
class DatasetMergeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    dataset_ids: List[int] = Field(min_length=2, max_length=10)


# ── 골드셋 수동 등록 (검증·초기 구축용) ─────────────────────────────────────

class GoldsetImportItem(BaseModel):
    question: str
    gold_answer: str = ""
    gold_chunk_ids: List[str] = Field(default_factory=list)
    gold_document_ids: List[str] = Field(default_factory=list)
    question_type: Literal["factual", "procedural", "comparative", "multihop"] = "factual"
    # ①축 확장
    expected_behavior: Literal[
        "answer", "not_enough_info", "guardrail", "permission_denied"
    ] = "answer"
    tags: List[str] = Field(default_factory=list)


class GoldsetImportRequest(BaseModel):
    dataset_id: int
    note: str = ""
    items: List[GoldsetImportItem]


# ── 평가 실행 ────────────────────────────────────────────────────────────────

class RuleEvaluationConfig(BaseModel):
    """신규 규칙 기반 평가 실행 설정.

    임베딩 모델과 지표 버전은 클라이언트가 선택하지 않고 실행 생성 시 서버가
    snapshot으로 보강한다.
    """

    model_config = ConfigDict(extra="forbid")

    retrieval_top_n: int = Field(default=10, ge=1)
    rerank_top_k: int = Field(default=5, ge=1)
    retrieval_channel: Literal["rrf"] = "rrf"

    @model_validator(mode="after")
    def validate_cutoffs(self) -> "RuleEvaluationConfig":
        if self.rerank_top_k > self.retrieval_top_n:
            raise ValueError("최종 문서 수 K는 검색 후보 수 N보다 클 수 없습니다.")
        return self


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goldset_id: int
    scope: Literal["retrieval", "full"]
    config: RuleEvaluationConfig = Field(default_factory=RuleEvaluationConfig)


# ── 평가 전용 설정 ───────────────────────────────────────────────────────────

class EvalOpenAIKeyRequest(BaseModel):
    # 2026.07.24(sychoi) 추가 - 평가 전용 OpenAI 키 1회 저장(관리자 계정 단위)
    openai_api_key: str = Field(..., min_length=1)

