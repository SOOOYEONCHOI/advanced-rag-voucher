"""
재순위화 노드.

# 2026.04.21(sooyeon.choi) 수정 - FlagEmbedding 로컬 추론 → vLLM /v1/score HTTP API 방식으로 전환
#   compute_metadata_match_score, QUERY_TYPE_WEIGHTS 제거 (CE + 메타 가중합 방식 폐기)
#   vLLM CE score만 사용하는 방식으로 단순화
# 2026.07.07(sooyeon.choi) 수정 - rerank 전 중복 제거, 메타데이터 prefix 구성,
#   RerankerResponseError 폴백 처리, 장애 시 degraded_top_k 상위 청크만 통과
RerankerClient(vLLM /v1/score API)를 사용하여 검색된 청크의 관련성 점수를 재계산한다.
"""

import asyncio
import json
from typing import Dict, List

import httpx

from app.clients.reranker_client import RerankerResponseError
from app.core.config import get_settings
# 2026.07.16(sooyeon.choi) 수정 - 모듈 전역 싱글턴을 컨테이너 조립으로 단일화 (3단계)
from app.core.container import get_container
from app.graphs.retrieval_engine import get_retrieval_config
from app.graphs.state import ChunkResult, PipelineState
from app.graphs.dependencies import GraphDependencies
# 2026.07.16(sooyeon.choi) 수정 - 중복 제거 로직을 공통 헬퍼로 이동
from app.graphs.utils import chunk_log_payload, dedup_chunks_by_text, rag_diag, timed_node
from app.interfaces import Reranker
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)


def get_reranker_client() -> Reranker:
    """리랭커를 반환한다 (컨테이너 위임). 구현 교체는 컨테이너에서 수행한다."""
    return get_container().reranker


# 2026.07.07(sooyeon.choi) 수정 - rerank 호출 전 텍스트 해시 기반 중복 제거
# 동일 본문이 여러 chunk_id로 검색되면 reranker 입력 슬롯을 낭비하고
# context 단계에서 중복 제거 후 context_top_k에 못 미칠 수 있음
# 2026.07.16(sooyeon.choi) 수정 - 로직을 graphs/utils.dedup_chunks_by_text로 이동


# 2026.07.07(sooyeon.choi) 수정 - 메타데이터 prefix 포함 reranker 입력 구성
# 문서명·섹션 정보를 prefix로 붙이면 CE 모델이 맥락을 파악해 관련성 점수 품질이 향상됨
# 단, 이 포맷 변경 후 relevance_threshold를 평가셋 기준으로 재보정 필요
def _build_rerank_text(chunk: Dict) -> str:
    """reranker 입력용 텍스트: 문서명·섹션 prefix + 본문."""
    metadata = chunk.get("metadata", {})
    # 2026.11.10(sooyeon.choi) 수정 - payload 파일명 키는 original_filename(리랭커 입력에 문서명·시트명)
    doc_name = metadata.get("original_filename") or metadata.get("filename") or ""
    header_path = metadata.get("header_path") or []
    section = (
        metadata.get("section_title")
        or metadata.get("section_name")
        or ""
    )

    prefix_parts = []
    if doc_name:
        prefix_parts.append(f"[문서명] {doc_name}")
    # 2026.11.10(sooyeon.choi) 추가 - 엑셀 청크는 header_path가 비어 있으므로 시트명을 위치로 붙인다
    sheet_name = metadata.get("sheet_name")
    if metadata.get("document_type") == "spreadsheet" and sheet_name:
        prefix_parts.append(f"[시트] {sheet_name}")
    location = " > ".join(header_path) if header_path else section
    if location:
        prefix_parts.append(f"[섹션] {location}")

    if prefix_parts:
        return "\n".join(prefix_parts) + f"\n[본문] {chunk['text']}"
    return chunk["text"]


def _make_passthrough(chunks: List[Dict], limit: int) -> List[ChunkResult]:
    """ChunkResult 변환 + 상위 limit개 슬라이스."""
    return [
        ChunkResult(
            chunk_id=c["chunk_id"],
            document_id=c["document_id"],
            text=c["text"],
            score=c.get("score", 0.0),
            metadata=c["metadata"],
        )
        for c in chunks[:limit]
    ]


@timed_node("rerank")
async def rerank(state: PipelineState, deps: GraphDependencies | None = None) -> dict:
    """vLLM /v1/score 기반 쿼리-청크 관련성 재평가."""
    if not state.get("retrieved_chunks"):
        rag_diag(logger, "[RAG][diag][node=rerank] 건너뜀 reason=청크없음")
        return {"reranked_chunks": [], "rerank_status": "empty"}

    settings = deps.settings if deps else get_settings()
    # 2026.06.29(sooyeon.choi) 수정 - Task 7: rerank 단계는 reranker_top_k만 사용
    retrieval_config = get_retrieval_config(state, settings)
    final_top_k = retrieval_config.rerank_top_k
    # 2026.07.07(sooyeon.choi) 수정 - reranker 장애 시 RRF 점수 상위 N개만 통과 (CE threshold 비교 금지)
    degraded_top_k = settings.reranker_degraded_top_k

    # 2026.07.07(sooyeon.choi) 수정 - rerank 전 텍스트 해시 중복 제거로 후보 슬롯 낭비 방지
    # 2026.07.16(sooyeon.choi) 수정 - 공통 헬퍼 사용
    deduped_chunks = dedup_chunks_by_text(state["retrieved_chunks"])

    def _degraded_fallback(reason: str) -> dict:
        """reranker 장애 시 deduped 상위 degraded_top_k 청크만 반환.
        RRF score에 CE threshold(0.3)를 적용하면 척도 불일치로 전부 탈락하므로
        임계값 우회가 필요하다.
        2026.07.16(sooyeon.choi) 수정 - relevance_threshold(사용자 설정)에 0.0을
        덮어쓰면 이후 파이프라인 전체에 영구 잔류하므로, 시스템 폴백 전용
        threshold_override 필드로 분리. 정상 rerank가 None으로 재설정한다.
        """
        passthrough = _make_passthrough(deduped_chunks, degraded_top_k)
        logger.info(
            "[RAG][results][post_rerank] mode=degraded reason=%s count=%s chunks=%s",
            reason,
            len(passthrough),
            json.dumps(chunk_log_payload(passthrough), ensure_ascii=False),
        )
        rag_diag(
            logger,
            "[RAG][diag][node=rerank] 폴백 reason=%s input=%s deduped=%s output=%s degraded_top_k=%s threshold_override=0.0000",
            reason,
            len(state["retrieved_chunks"]),
            len(deduped_chunks),
            len(passthrough),
            degraded_top_k,
        )
        return {
            "reranked_chunks": passthrough,
            "threshold_override": 0.0,
            "rerank_status": "error",
        }

    # 2026.04.21(sooyeon.choi) reranker api 호출 분기 처리 추가
    if not settings.enable_reranking:
        passthrough = _make_passthrough(deduped_chunks, final_top_k)
        logger.info(
            "[RAG][results][post_rerank] mode=disabled count=%s chunks=%s",
            len(passthrough),
            json.dumps(chunk_log_payload(passthrough), ensure_ascii=False),
        )
        rag_diag(
            logger,
            "[RAG][diag][node=rerank] 건너뜀 reason=비활성화 input=%s deduped=%s output=%s threshold_override=0.0000",
            len(state["retrieved_chunks"]),
            len(deduped_chunks),
            len(passthrough),
        )
        # 2026.07.16(sooyeon.choi) 수정 - RRF 점수는 CE 임계값과 척도가 달라
        #   임계값 우회가 필요하며, 사용자 설정 대신 override 필드 사용
        return {
            "reranked_chunks": passthrough,
            "threshold_override": 0.0,
            "rerank_status": "skipped",
        }

    # 2026.07.07(sooyeon.choi) 수정 - 메타데이터 prefix 포함 텍스트를 reranker에 전달
    # ChunkResult에는 원본 텍스트를 유지하고 reranker 입력용 텍스트는 별도 생성
    rerank_texts = [_build_rerank_text(c) for c in deduped_chunks]

    try:
        ranked = await asyncio.wait_for(
            (deps.container.reranker if deps else get_reranker_client()).rerank(
                state["original_query"], rerank_texts, top_k=final_top_k
            ),
            timeout=settings.reranker_timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Reranker 타임아웃 (%ss) — deduped 상위 %s개 반환",
            settings.reranker_timeout,
            degraded_top_k,
        )
        return _degraded_fallback("타임아웃")
    except httpx.HTTPError as e:
        logger.warning("Reranker API 통신 실패 (%s) — deduped 상위 %s개 반환", e, degraded_top_k)
        return _degraded_fallback("통신 오류")
    # 2026.07.07(sooyeon.choi) 수정 - 응답 형식·검증 오류도 동일한 degraded 폴백 적용
    except RerankerResponseError as e:
        logger.warning("Reranker 응답 검증 실패 (%s) — deduped 상위 %s개 반환", e, degraded_top_k)
        return _degraded_fallback("응답 오류")

    # 2026.07.07(sooyeon.choi) 수정 - (orig_idx, ce_score) 튜플 사용, 원본 텍스트 유지
    reranked: List[ChunkResult] = []
    for orig_idx, ce_score in ranked:
        original = deduped_chunks[orig_idx]
        reranked.append(
            ChunkResult(
                chunk_id=original["chunk_id"],
                document_id=original["document_id"],
                text=original["text"],
                score=ce_score,
                metadata=original["metadata"],
            )
        )

    # 2026.07.16(sooyeon.choi) 수정 - 정상 rerank 완료 시점 기준의 임계값으로 진단
    #   이 노드가 threshold_override=None을 반환해 이전 degraded 잔류를 해제하므로,
    #   진단 계산에도 override를 제외한 사용자/기본 임계값을 사용한다.
    threshold = state.get("relevance_threshold")
    if threshold is None:
        threshold = settings.relevance_threshold
    scores = [c.get("score", 0.0) for c in reranked]
    logger.info(
        "[RAG][results][post_rerank] mode=reranked count=%s chunks=%s",
        len(reranked),
        json.dumps(chunk_log_payload(reranked), ensure_ascii=False),
    )
    # diag_qualified는 실제 필터링이 아닌 진단 전용 — 필터링은 check_relevance edge와 assemble_context에서 수행
    diag_qualified = sum(1 for s in scores if s >= threshold)
    rag_diag(
        logger,
        "[RAG][diag][node=rerank] input=%s deduped=%s output=%s threshold=%.4f diag_qualified=%s max_score=%.4f min_score=%.4f",
        len(state["retrieved_chunks"]),
        len(deduped_chunks),
        len(reranked),
        threshold,
        diag_qualified,
        max(scores, default=0.0),
        min(scores, default=0.0),
    )
    # 2026.07.16(sooyeon.choi) 수정 - 정상 rerank 성공 시 이전 degraded 폴백의
    #   임계값 우회(threshold_override)를 해제해 잔류 오염 방지
    return {"reranked_chunks": reranked, "threshold_override": None, "rerank_status": "ok"}
