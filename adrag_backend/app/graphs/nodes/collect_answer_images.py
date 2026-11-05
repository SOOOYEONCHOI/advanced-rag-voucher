"""
답변 사진 후보 수집 노드 - 2026.10.19(sooyeon.choi) 추가

assemble_context가 LLM에 넘기기로 정한 context_chunks에 연결된 사진을 후보로 모은다(app/graphs/images.py).
후보는 generate_answer가 컨텍스트 뒤에 "[관련 이미지 후보]" 목록으로 붙이고, format_citations가 답변의
[IMG:ref] 인용을 후보 기준으로 검증한다. 후보 블록을 붙이면 프롬프트 예산을 넘는 경우 뒤 후보부터 뺀다.
설정 answer_images_enabled=false이거나 후보가 없으면 빈 목록 → 프롬프트·답변은 기존과 같다.
"""

import asyncio

from app.core.config import get_settings
from app.graphs.dependencies import GraphDependencies
from app.graphs.images import collect_image_candidates, image_prompt_block
from app.graphs.nodes.assemble_context import prompt_fits
from app.graphs.state import PipelineState
from app.graphs.utils import timed_node
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)


def context_with_images(final_context: str, candidates: list) -> str:
    """LLM에 넘길 컨텍스트: 문서 컨텍스트 + (후보가 있으면) 사진 후보 목록."""
    block = image_prompt_block(candidates or [])
    return f"{final_context}\n\n{block}" if block else (final_context or "")


@timed_node("collect_answer_images")
async def collect_answer_images(state: PipelineState, deps: GraphDependencies | None = None) -> dict:
    settings = deps.settings if deps else get_settings()
    context_chunks = state.get("context_chunks") or []
    if not getattr(settings, "answer_images_enabled", False) or not context_chunks:
        return {"image_candidates": []}

    candidates = await asyncio.to_thread(
        collect_image_candidates,
        context_chunks,
        limit=getattr(settings, "rag_image_candidates", 8),
        query=state.get("original_query"),
    )
    question = state.get("original_query", "")
    final_context = state.get("final_context") or ""
    count = state.get("context_chunk_count") or len(context_chunks)
    while candidates and not prompt_fits(settings, question, context_with_images(final_context, candidates), count):
        candidates = candidates[:-1]
    logger.info(
        "[RAG][images] 후보=%s %s",
        len(candidates),
        [(c["ref"], c["resource_id"], c["context_no"]) for c in candidates],
    )
    return {"image_candidates": candidates}
