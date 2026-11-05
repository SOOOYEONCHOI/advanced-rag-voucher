"""
질의 재작성 노드.

LLM 1회 호출로 검색 최적화 재작성(rewritten_queries)을 수행한다.
임베딩 생성은 LLM 호출과 병렬로 실행하여 지연 시간을 최소화한다.

ENABLE_QUERY_PREPROCESSING=true 시 규칙 기반 전처리 결과를 LLM 힌트로 포함한다.
LLM 호출 실패 시 기본값([원본 질의])을 설정한다.

# To-do: query_type(factual/procedural/comparative/definitional),
#   inferred_doc_type(law/manual/safety_guide/general) 분류를 활용할 계획이 생기면
#   프롬프트와 파싱 로직에 다시 추가할 것. 현재는 미사용으로 제거(2026.05.22)
"""

import asyncio
import json
from typing import Any, Dict, List

from app.core.config import get_settings
from app.graphs.preprocessing import QueryPreprocessor
from app.graphs.state import PipelineState
from app.graphs.dependencies import GraphDependencies
from app.graphs.utils import preview_list, rag_diag, timed_node
# 2026.07.16(sooyeon.choi) 수정 - 요청마다 EmbeddingClient를 생성하던 것을
#   retrieve 노드와 동일한 싱글턴을 공유하도록 변경 (B8)
from app.graphs.nodes.retrieve import get_embedding_client
from app.services.llm_service import get_local_llm_service
from app.utils.log.log import LoggingLogger
from app.prompts.pipeline import REWRITE_PROMPT

# 로거 초기화
logger = LoggingLogger().getLogger(__name__)

# 2026.07.16(sooyeon.choi) 추가 - QueryPreprocessor 모듈 수준 싱글턴 (B8)
# 2026.07.16(sooyeon.choi) 수정 - 조립 지점을 컨테이너로 이동, getter는 호환용 유지 (3단계)
def get_query_preprocessor() -> QueryPreprocessor:
    """QueryPreprocessor 싱글턴을 반환한다 (컨테이너 위임)."""
    from app.core.container import get_container
    return get_container().query_preprocessor

# To-do: query_type/inferred_doc_type 분류를 활용할 계획이 생기면
#   프롬프트 항목과 JSON 스키마에 다시 추가할 것."""

# VALID_QUERY_TYPES = {"factual", "procedural", "comparative", "definitional"}
# VALID_DOC_TYPES = {"law", "manual", "safety_guide", "general"}


def parse_rewrite_response(response: Any) -> List[str]:
    """LLM 응답에서 rewritten_queries를 파싱한다. 실패 시 빈 리스트 반환.

    # To-do: query_type/inferred_doc_type 분류를 추가할 경우
    #   파싱 로직과 반환 타입을 Dict[str, Any]로 확장할 것.
    """
    try:
        # 2026.07.16(sooyeon.choi) 수정 - LLMService.chat()에서 이미 strip_thinking 처리되므로
        #   이중 적용 제거 (B14)
        raw_text = response.choices[0].message.content if response.choices else ""

        text = raw_text.strip()
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                text = text[start:end]

        parsed = json.loads(text)
        queries = parsed.get("rewritten_queries", [])
        return [q.strip() for q in queries if isinstance(q, str) and q.strip()]
    except (json.JSONDecodeError, KeyError, IndexError, AttributeError) as e:
        logger.error(f"질의 재작성 응답 파싱 실패: {e}")
        return []


@timed_node("analyze_and_rewrite")
async def analyze_and_rewrite(state: PipelineState, deps: GraphDependencies | None = None) -> dict:
    """LLM 1회 호출로 질의 재작성, 전처리·임베딩은 병렬 실행."""
    settings = deps.settings if deps else get_settings()

    # 질의 분석·재작성은 항상 로컬 vLLM을 사용한다.
    # 사용자가 OpenAI를 선택했더라도 analyze_and_rewrite는 내부 파이프라인 단계이므로
    # 로컬 싱글턴을 재사용하여 객체 생성 오버헤드를 제거한다.
    llm_service = deps.container.local_llm if deps else get_local_llm_service()
    # 2026.07.16(sooyeon.choi) 수정 - retrieve 노드와 동일한 EmbeddingClient 싱글턴 공유 (B8)
    embedding_client = deps.container.embedding if deps else get_embedding_client()

    original_query = state["original_query"]

    # ── 규칙 기반 전처리 ──
    preprocess_result: Dict[str, Any] = {}
    if settings.enable_query_preprocessing:
        try:
            # 2026.07.16(sooyeon.choi) 수정 - 요청마다 생성 → 싱글턴 재사용 (B8)
            preprocessor = deps.container.query_preprocessor if deps else get_query_preprocessor()
            pp_result = preprocessor.preprocess(original_query)
            preprocess_result = {
                "normalized_query": pp_result.normalized_query,
                "expanded_terms": pp_result.expanded_terms,
                "matched_patterns": pp_result.matched_patterns,
                "extracted_keywords": pp_result.extracted_keywords,
            }
        except Exception as e:
            logger.warning(f"규칙 기반 전처리 실패, 건너뜁니다: {e}")
    else:
        # logger.info("ENABLE_QUERY_PREPROCESSING=false: 규칙 기반 전처리 비활성화됨")
        pass

    # ── 사용자 메시지 구성 (전처리 힌트 포함) ──
    user_message = original_query
    if preprocess_result:
        hint_parts: List[str] = []
        if preprocess_result.get("expanded_terms"):
            hint_parts.append(f"확장된 약어: {', '.join(preprocess_result['expanded_terms'])}")
        if preprocess_result.get("matched_patterns"):
            patterns = preprocess_result["matched_patterns"]
            if patterns.get("law_references"):
                hint_parts.append(f"법령 조문 패턴: {', '.join(patterns['law_references'])}")
        if preprocess_result.get("extracted_keywords"):
            hint_parts.append(f"추출된 키워드: {', '.join(preprocess_result['extracted_keywords'])}")

        if hint_parts:
            hints_text = "\n".join(hint_parts)
            user_message = f"{original_query}\n\n[전처리 힌트]\n{hints_text}"

    llm_messages = [
        {"role": "system", "content": REWRITE_PROMPT},
        {"role": "user", "content": user_message},
    ]

    async def call_llm():
        try:
            response = await llm_service.chat(llm_messages)
            return parse_rewrite_response(response)
        except Exception as e:
            logger.error(f"질의 재작성 LLM 호출 실패, 원본 질의 사용: {e}")
            return []

    async def call_embedding():
        return await embedding_client.embed_query(original_query)

    # Phase 1: LLM 호출과 original_query 임베딩을 병렬로 실행 (지연 시간 최소화)
    rewritten_raw, original_embedding = await asyncio.gather(
        call_llm(), call_embedding()
    )

    # 2026.05.22(sooyeon.choi) 수정 - original_query를 항상 첫 번째에 포함
    # LLM 재작성 쿼리만 사용하면 원본 질의가 검색에서 누락될 수 있음.
    # original 우선 배치 → retrieve 단계에서 정확한 표현으로 반드시 검색,
    # 나머지 확장 쿼리는 recall 보완 역할만 담당.
    if original_query in (rewritten_raw or []):
        rewritten = rewritten_raw
    else:
        rewritten = [original_query] + (rewritten_raw or [])

    # Phase 2: 재작성 쿼리 중 original_query와 다른 쿼리만 추가 배치 임베딩.
    # original_query 임베딩은 Phase 1에서 이미 계산했으므로 재사용한다.
    embedding_map: dict[str, List[float]] = {original_query: original_embedding}
    queries_to_embed = [q for q in rewritten if q not in embedding_map]
    if queries_to_embed:
        try:
            extra = await embedding_client.embed_queries(queries_to_embed)
            embedding_map.update(dict(zip(queries_to_embed, extra)))
        except Exception as e:
            logger.error(f"재작성 쿼리 배치 임베딩 실패, original 임베딩으로 대체: {e}")
            for q in queries_to_embed:
                embedding_map[q] = original_embedding

    rewritten_query_embeddings = [embedding_map[q] for q in rewritten]

    rag_diag(
        logger,
        "[RAG][diag][node=analyze_and_rewrite] query_len=%s preprocessing=%s expanded_terms=%s keywords=%s matched_law_refs=%s rewritten=%s embedded=%s",
        len(original_query),
        bool(preprocess_result),
        len(preprocess_result.get("expanded_terms") or []),
        len(preprocess_result.get("extracted_keywords") or []),
        len((preprocess_result.get("matched_patterns") or {}).get("law_references") or []),
        len(rewritten),
        len(rewritten_query_embeddings),
    )
    rag_diag(
        logger,
        "[RAG][diag][node=analyze_and_rewrite] keywords_preview=%s rewritten_preview=%s",
        preview_list(preprocess_result.get("extracted_keywords"), limit=10, max_len=40),
        preview_list(rewritten, limit=5, max_len=120),
    )

    # logger.info(
    #     f"임베딩 완료: original 1건(Phase1) + 추가 {len(queries_to_embed)}건(Phase2) → "
    #     f"총 {len(rewritten_query_embeddings)}건 사전 계산"
    # )
    # 2026.05.22(sooyeon.choi) 추가 - 노드 출력 로깅
    # logger.info(
    #     f"[analyze_and_rewrite 출력] rewritten_queries({len(rewritten)}건): "
    #     + " | ".join(f"[{i+1}] {q!r}" for i, q in enumerate(rewritten))
    # )

    # To-do: query_type/inferred_doc_type를 활용할 계획이 생기면
    #   반환 dict에 "query_type", "inferred_doc_type" 키를 다시 추가할 것.
    return {
        "query_embedding": original_embedding,
        "rewritten_queries": rewritten,
        "rewritten_query_embeddings": rewritten_query_embeddings,
        "preprocess_result": preprocess_result,
    }
