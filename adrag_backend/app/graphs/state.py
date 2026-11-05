"""
RAG Query 파이프라인 상태 정의.

모든 LangGraph 노드가 공유하는 PipelineState 및 ChunkResult TypedDict를 정의한다.
"""

from typing import Any, Dict, List, Optional, TypedDict


class ChunkResult(TypedDict):
    """검색된 청크 정보."""

    chunk_id: str          # 청크 고유 ID
    document_id: str       # 소속 문서 ID
    text: str              # 청크 텍스트 내용
    score: float           # 관련성 점수
    metadata: Dict[str, Any]  # 메타데이터 (filename, section_name, header_path 등)


class PipelineState(TypedDict):
    """RAG Query 파이프라인 상태 — 모든 Node가 공유."""

    # ── 입력 (API 요청에서 초기화) ──
    user_id: str                                          # 사용자 ID (필수)
    session_id: Optional[str]                             # 세션 ID (멀티턴)
    original_query: str                                   # 사용자 원본 질의 (필수)
    collection_filters: Optional[List[str]]               # 요청 시 명시된 컬렉션 필터
    # 2026.04.01(sooyeon.choi) 수정 - 멀티컬렉션 관리 기능 추가
    collection_name: Optional[str]                        # 채팅 시 사용자가 선택한 단일 컬렉션 이름
    conversation_history: Optional[List[Dict[str, Any]]]  # 대화 히스토리 (멀티턴 컨텍스트)
    # 2026.07.08(sooyeon.choi) 수정 - None이면 단계별 검색 설정 사용, 명시값은 legacy 호환 override
    top_k: Optional[int]                                  # 검색 결과 수 override
    citation_limit: int                                   # 응답에 포함할 최대 인용 수

    # 2026.04.10(sooyeon.choi) 추가 - LLM 제공자 설정 (None이면 로컬 vLLM 사용)
    llm_provider: Optional[str]                           # "local" | "openai"
    llm_model: Optional[str]                              # "gpt-4.1", "gpt-4o-mini"
    llm_api_key: Optional[str]                            # OpenAI API 키

    # ── 질의 분석 결과 ──
    # To-do: query_type(factual/procedural/comparative/definitional),
    #   inferred_doc_type(law/manual/safety_guide/general) 분류를 활용할 계획이 생기면
    #   아래 두 필드를 다시 추가할 것. 현재는 미사용으로 제거(2026.05.22).
    # query_type: Optional[str]                             # 질의 유형 (factual/procedural/comparative/definitional)
    # inferred_doc_type: Optional[str]                      # 추론된 문서 유형 (law/manual/safety_guide/general)
    query_embedding: Optional[List[float]]                # 원본 질의 임베딩 벡터

    # ── 질의 재작성 ──
    rewritten_queries: List[str]                          # 검색 최적화 재작성 질의 목록
    rewritten_query_embeddings: Optional[List[List[float]]]  # rewritten_queries 순서와 1:1 대응하는 사전 계산 임베딩

    # ── 메타데이터 필터 ──
    filters: Dict[str, Any]                               # Qdrant 필터 조건

    # ── 검색 결과 ──
    retrieved_chunks: List[ChunkResult]                   # 벡터 검색으로 가져온 청크 목록
    reranked_chunks: List[ChunkResult]                    # 리랭킹 후 최종 청크 목록 (재순위화 결과)

    # ── 컨텍스트 ──
    final_context: Optional[str]                          # LLM에 전달할 조합된 컨텍스트 문자열
    # 2026.07.10(sooyeon.choi) 수정 - LLM에 실제 부여한 [N] 번호와 Citation 매핑 기준 보존
    context_chunks: List[ChunkResult]                    # final_context에 실제 포함된 번호 순서의 청크

    # ── LLM 생성 ──
    generated_answer: Optional[str]                       # LLM이 생성한 최종 답변
    thinking: Optional[str]                               # LLM 내부 추론 과정 (<think> 블록)
    citations: List[Dict[str, Any]]                       # 답변에서 인용된 문서 정보 목록
    # 2026.10.19 추가 - 사진 답변: LLM에 보여준 후보, 검증 후 표시할 사진(응답 images)
    image_candidates: List[Dict[str, Any]]
    answer_images: List[Dict[str, Any]]

    # ── 폴백/재시도 ──
    retry_count: int                                      # 폴백 재시도 횟수
    retry_target: Optional[str]                           # retrieve | generate_answer
    error: Optional[str]                                  # 오류 메시지 (없으면 None)
    # 2026.07.16(sooyeon.choi) 추가 - 스키마 누락 필드 보강 (B12)
    #   rerank(degraded 폴백)·fallback_handler·assemble_context·check_relevance가
    #   읽고 쓰는 필드인데 TypedDict 스키마에 선언되지 않아 초기 state의 키가
    #   그래프 채널 정의와 어긋나 있었음
    relevance_threshold: Optional[float]                  # rerank 후 컨텍스트 포함 최소 점수 (None이면 settings 값)
    # 2026.07.16(sooyeon.choi) 추가 - fallback 재시도용 단계별 top_k override (B4)
    #   기존에는 fallback이 legacy top_k에 값을 써서 from_legacy_top_k()가 candidate=×4,
    #   context=×0.5로 재해석 → 재시도부터 top_k 배분 체계가 변질되던 문제를 분리
    retrieval_override: Optional[Dict[str, int]]          # {"candidate_top_k","rerank_top_k","context_top_k"}
    # 2026.07.16(sooyeon.choi) 추가 - 시스템 폴백 전용 임계값 우회 (B5)
    #   기존에는 rerank degraded 폴백이 relevance_threshold=0.0을 사용자 설정 필드에
    #   덮어써 이후 파이프라인 전체가 오염되던 것을 별도 필드로 분리.
    #   정상 rerank가 None으로 재설정하므로 degraded 통과분에만 일시 적용된다.
    threshold_override: Optional[float]                   # None이 아니면 relevance_threshold보다 우선

    # ── 메타데이터 필터링 ──
    enable_metadata_filtering: Optional[bool]             # None이면 config 설정 따름
    preprocess_result: Dict[str, Any]                     # 규칙 기반 전처리 결과 (정규화·약어확장·명사추출)

    # ── 컨텍스트 메타 ──
    context_chunk_count: Optional[int]                   # assemble_context에 실제 포함된 청크 수

    # ── 가드레일 ──
    intent: Optional[str]            # 질의 의도 유형 (greeting/smalltalk/irrelevant/unsafe/empty_or_invalid/rag_query)
    should_retrieve: Optional[bool]  # RAG 파이프라인 수행 여부 (False면 build_response로 분기)
    guardrail_reason: Optional[str]  # 가드레일 처리 사유
    response_type: Optional[str]     # 응답 유형 (rag/guardrail)

    # ── 관측성 ──
    timing: Dict[str, float]                              # 각 노드별 처리 시간 (s)

    # ── SCR-006 통계 ──
    # 2026.06.16(sooyeon.choi) 추가 - LLM 토큰 사용량 (비스트리밍 generate_answer에서 설정)
    usage: Optional[dict]  # {"prompt_tokens": int, "completion_tokens": int}
    # 2026.06.19(sooyeon.choi) 추가 - 질의 처리 최종 결과 코드
    outcome_code: str


# 2026.07.16(sooyeon.choi) 추가 - 초기 state 팩토리 (B12)
#   기존: RAGService.query()와 query_stream()에 동일한 40줄 dict 리터럴이 복붙되어
#   필드 추가 시 한쪽 누락이 그대로 버그가 됨 (context_chunks 추가 시 양쪽 수정 이력 존재)
#   미사용 키(query_type/inferred_doc_type/selected_strategy)는 스키마와 일치하도록 제거함
def make_initial_state(
    *,
    user_id: str,
    session_id: Optional[str],
    original_query: str,
    collection_filters: Optional[List[str]],
    collection_name: Optional[str],
    top_k: Optional[int],
    citation_limit: int,
    llm_provider: Optional[str],
    llm_model: Optional[str],
    llm_api_key: Optional[str],
    enable_metadata_filtering: Optional[bool],
    relevance_threshold: Optional[float],
) -> PipelineState:
    """RAG 파이프라인 초기 PipelineState를 생성한다 (query/query_stream 공용)."""
    return {
        "user_id": user_id,
        "session_id": session_id,
        "original_query": original_query,
        "collection_filters": collection_filters,
        "collection_name": collection_name,
        "conversation_history": None,
        "top_k": top_k,
        "citation_limit": citation_limit,
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "llm_api_key": llm_api_key,
        "enable_metadata_filtering": enable_metadata_filtering,
        "intent": None,
        "should_retrieve": None,
        "guardrail_reason": None,
        "response_type": None,
        "query_embedding": None,
        "rewritten_queries": [],
        "rewritten_query_embeddings": None,
        "filters": {},
        "retrieved_chunks": [],
        "reranked_chunks": [],
        "final_context": None,
        "context_chunks": [],
        "context_chunk_count": None,
        "generated_answer": None,
        "thinking": None,
        "citations": [],
        "image_candidates": [],
        "answer_images": [],
        "relevance_threshold": relevance_threshold,
        # 2026.07.16(sooyeon.choi) 추가 - B4/B5 override 필드 초기화
        "retrieval_override": None,
        "threshold_override": None,
        "retry_count": 0,
        "retry_target": None,
        "error": None,
        "preprocess_result": {},
        "timing": {},
        "usage": None,
        "outcome_code": "unknown",
    }
