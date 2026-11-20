"""
컨텍스트 구성 노드.

재순위화된 청크에서 텍스트 해시 기반 중복을 제거하고,
토큰 제한 내에서 "[번호] [문서명] header_path\n청크텍스트" 형태로
컨텍스트 문자열을 조립한다.

context_chunk_count를 함께 반환하여 generate_answer가
실제 컨텍스트에 포함된 청크 수 기준으로 available_numbers를 계산하도록 한다.
이 값이 어긋나면 LLM이 컨텍스트에 없는 번호를 인용하는 환각이 발생한다.
"""

import json
import re

from app.core.config import get_settings
from app.graphs.dependencies import GraphDependencies
from app.graphs.retrieval_engine import get_retrieval_config
from app.graphs.state import PipelineState
from app.prompts.templates import build_rag_messages
# 2026.07.16(sooyeon.choi) 수정 - 중복 제거 로직 공통 헬퍼, 임계값 우선순위 헬퍼
from app.graphs.utils import (
    chunk_log_payload,
    dedup_chunks_by_text,
    effective_threshold,
    rag_diag,
    timed_node,
)
from app.utils.log.log import LoggingLogger

# 로거 초기화
logger = LoggingLogger().getLogger(__name__)


_TOKEN_PATTERN = re.compile(r"[가-힣]|[A-Za-z0-9_]+|[^\s]")
_CONTEXT_TOKEN_SAFETY_MARGIN = 512


def _estimate_messages_tokens(messages: list[dict[str, str]]) -> int:
    """외부 tokenizer 없이 최종 chat 메시지의 토큰 수를 보수적으로 추정한다."""
    content_tokens = sum(
        sum(
            max(1, (len(token) + 3) // 4) if token.isascii() else 1
            for token in _TOKEN_PATTERN.findall(message.get("content", ""))
        )
        for message in messages
    )
    # role 구분자와 chat template 특수 토큰에 대한 소량의 고정 오버헤드.
    return content_tokens + (len(messages) * 4) + 2


def _prompt_tokens(question: str, context: str, context_count: int) -> int:
    available_numbers = ", ".join(f"[{i + 1}]" for i in range(context_count))
    messages = build_rag_messages(
        question=question,
        context=context,
        available_numbers=available_numbers,
    )
    return _estimate_messages_tokens(messages)


def _max_prompt_tokens(settings) -> int:
    max_model_tokens = getattr(settings, "vllm_max_model_len", 8192)
    max_output_tokens = getattr(settings, "vllm_max_tokens", 2048)
    return max(1, max_model_tokens - max_output_tokens - _CONTEXT_TOKEN_SAFETY_MARGIN)


# 2026.10.19 추가 - 사진 답변·출처 패널·이미지 뷰어(collect_answer_images)
def prompt_fits(settings, question: str, context: str, context_count: int) -> bool:
    return _prompt_tokens(question, context, context_count) <= _max_prompt_tokens(settings)


@timed_node("assemble_context")
async def assemble_context(state: PipelineState, deps: GraphDependencies | None = None) -> dict:
    """중복 제거 + 문자 수 제한 내 컨텍스트 문자열 구성."""
    settings = deps.settings if deps else get_settings()
    max_context_chars = settings.max_context_chars
    max_model_tokens = getattr(settings, "vllm_max_model_len", 8192)
    max_output_tokens = getattr(settings, "vllm_max_tokens", 2048)
    max_prompt_tokens = _max_prompt_tokens(settings)
    question = state.get("original_query", "")
    # 2026.06.29(sooyeon.choi) 추가 - Task 7: assemble_context 단계는 context_top_k만 사용
    retrieval_config = get_retrieval_config(state, settings)
    citation_limit = state.get("citation_limit")
    context_top_k = retrieval_config.context_top_k
    if citation_limit:
        context_top_k = min(context_top_k, max(1, int(citation_limit)))

    # relevance_threshold 미달 청크 선제 제거
    # 2026.07.16(sooyeon.choi) 수정 - threshold_override 우선순위 헬퍼 적용
    threshold = effective_threshold(state, settings)
    qualified_chunks = [
        c for c in state.get("reranked_chunks", [])
        if c.get("score", 0.0) >= threshold
    ]
    if len(qualified_chunks) < len(state.get("reranked_chunks", [])):
        pass

    # 텍스트 해시 기반 중복 제거 (SHA256: 재시작·분산 환경에서도 결정적)
    # 2026.07.16(sooyeon.choi) 수정 - rerank.py와 중복이던 로직을 공통 헬퍼로 통합
    #   입력이 score 내림차순 정렬 상태이므로 '첫 등장 유지'와 'score 최고 유지'는 동일 결과
    unique_chunks = dedup_chunks_by_text(qualified_chunks)

    # 2026.07.08(sooyeon.choi) 수정 - 동일 문서 편중을 제한한 뒤 context_top_k 적용
    max_per_document = max(1, settings.context_max_chunks_per_document)
    document_counts: dict[str, int] = {}
    diverse_chunks = []
    for chunk in unique_chunks:
        document_key = chunk.get("document_id") or chunk.get("chunk_id")
        if document_counts.get(document_key, 0) >= max_per_document:
            continue
        document_counts[document_key] = document_counts.get(document_key, 0) + 1
        diverse_chunks.append(chunk)
        if len(diverse_chunks) >= context_top_k:
            break

    # 문자 수 제한 내에서 컨텍스트 문자열 구성 (context_top_k 청크 이내)
    context_parts: list[str] = []
    included_chunks: list[dict] = []
    total_chars = 0

    for chunk in diverse_chunks:
        # 문서 구조 정보 추출
        metadata = chunk["metadata"]
        doc_name = metadata.get("original_filename") or metadata.get("filename", "문서")
        if metadata.get("document_type") == "spreadsheet":
            # 2026.08.27(sooyeon.choi) 수정 - Excel citation 문맥은 시트/범위와 표시용 Markdown 사용
            location = " ".join(
                str(value) for value in (metadata.get("sheet_name"), metadata.get("source_range")) if value
            )
            header = f"[{doc_name}] {location}".rstrip()
            display_text = metadata.get("display_markdown") or chunk["text"]
        else:
            header_path = " > ".join(metadata.get("header_path", []))
            section = metadata.get("section_name", "")
            header = (
                f"[{doc_name}] {header_path or section}"
                if (header_path or section)
                else f"[{doc_name}]"
            )
            display_text = chunk["text"]

        # "[번호] [문서명] header_path\n청크텍스트" 포맷
        chunk_text = f"[{len(context_parts) + 1}] {header}\n{display_text}"

        candidate_parts = [*context_parts, chunk_text]
        candidate_context = "\n\n".join(candidate_parts)
        candidate_prompt_tokens = _prompt_tokens(
            question,
            candidate_context,
            len(candidate_parts),
        )

        if (
            len(candidate_context) > max_context_chars
            or candidate_prompt_tokens > max_prompt_tokens
        ):
            logger.warning(
                "[RAG][context_budget] skipped_chunk=%s text_chars=%s display_chars=%s "
                "candidate_chars=%s max_context_chars=%s prompt_tokens_estimate=%s "
                "max_prompt_tokens=%s max_model_tokens=%s max_output_tokens=%s",
                chunk.get("chunk_id"), len(chunk["text"]), len(display_text),
                len(candidate_context), max_context_chars, candidate_prompt_tokens,
                max_prompt_tokens, max_model_tokens, max_output_tokens,
            )
            continue

        context_parts.append(chunk_text)
        included_chunks.append(chunk)
        total_chars = len(candidate_context)

    final_context = "\n\n".join(context_parts)
    context_chunk_count = len(context_parts)
    prompt_tokens = _prompt_tokens(question, final_context, context_chunk_count)
    logger.info(
        "[RAG][results][final_context] included=%s chars=%s chunks=%s context=%s",
        context_chunk_count,
        total_chars,
        json.dumps(chunk_log_payload(included_chunks), ensure_ascii=False),
        final_context,
    )
    rag_diag(
        logger,
        "[RAG][diag][node=assemble_context] threshold=%.4f reranked=%s qualified=%s unique=%s diverse=%s context_top_k=%s included=%s chars=%s max_context_chars=%s prompt_tokens_estimate=%s max_prompt_tokens=%s max_model_tokens=%s max_output_tokens=%s",
        threshold,
        len(state.get("reranked_chunks", [])),
        len(qualified_chunks),
        len(unique_chunks),
        len(diverse_chunks),
        context_top_k,
        context_chunk_count,
        total_chars,
        max_context_chars,
        prompt_tokens,
        max_prompt_tokens,
        max_model_tokens,
        max_output_tokens,
    )
    # 2026.07.10(sooyeon.choi) 수정 - Citation 생성도 LLM에 실제 전달한 청크 순서를 사용
    return {
        "final_context": final_context,
        "context_chunk_count": context_chunk_count,
        "context_chunks": included_chunks,
    }
