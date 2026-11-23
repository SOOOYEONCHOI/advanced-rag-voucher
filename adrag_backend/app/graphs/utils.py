"""
LangGraph 파이프라인 공통 유틸리티.

timed_node 데코레이터: 노드 실행 시간을 timing 딕셔너리에 기록하고 로그를 출력한다.
"""

import functools
import hashlib
import time
from typing import Any, Dict, Iterable, List

from app.core.config import get_settings
from app.utils.log.log import LoggingLogger

# 로거 초기화
logger = LoggingLogger().getLogger(__name__)


# 2026.07.16(sooyeon.choi) 추가 - 텍스트 해시 기반 청크 중복 제거 공통 헬퍼
#   기존: rerank.py(_dedup_chunks)와 assemble_context.py에 동일 로직이 중복 구현됨
#   동일 본문 청크 중 score가 가장 높은 청크를 유지한다 (첫 등장 위치 보존).
#   SHA256 사용: 재시작·분산 환경에서도 결정적.
# [AI+ 시험] NDCG@5 - 4) 하이브리드 검색 결과를 Reranker 모델에 입력하여 질의와 문서 청크 간 관련도를 평가하고 검색 결과를 재정렬하는 코드 (Reranker 입력 전 같은 본문 중복 제거)
def dedup_chunks_by_text(chunks: List[Dict]) -> List[Dict]:
    """텍스트 해시 기반 중복 제거 — 동일 본문 중 score 최고 청크 유지."""
    seen: Dict[str, int] = {}  # text_hash → result 인덱스
    result: List[Dict] = []
    for chunk in chunks:
        text_hash = hashlib.sha256(chunk["text"].strip().encode()).hexdigest()
        if text_hash not in seen:
            seen[text_hash] = len(result)
            result.append(chunk)
        else:
            existing_idx = seen[text_hash]
            if chunk.get("score", 0.0) > result[existing_idx].get("score", 0.0):
                result[existing_idx] = chunk
    return result


# 2026.07.16(sooyeon.choi) 추가 - 유효 관련성 임계값 계산 헬퍼
#   우선순위: threshold_override(시스템 폴백 전용) > relevance_threshold(사용자/요청) > settings 기본값
#   check_relevance 엣지·assemble_context·스트리밍 경로가 동일 규칙을 공유한다.
def effective_threshold(state, settings) -> float:
    """현재 state에 적용할 관련성 임계값을 반환한다."""
    override = state.get("threshold_override")
    if override is not None:
        return override
    threshold = state.get("relevance_threshold")
    if threshold is not None:
        return threshold
    return settings.relevance_threshold


def rag_diag_enabled() -> bool:
    """RAG 디버깅 로그 출력 활성화 여부 반환 (.env)"""
    return bool(get_settings().rag_diagnostic_log)


def rag_diag(log, message: str, *args, **kwargs) -> None:
    """RAG 디버그 로그가 활성화된 경우만 로그 출력"""
    if rag_diag_enabled():
        log.info(message, *args, **kwargs)


def preview_list(items: Iterable[Any] | None, limit: int = 10, max_len: int = 80) -> list[str]:
    """로그 출력용으로 일부 데이터만 잘라서 문자열 목록으로 반환"""
    if not items:
        return []
    return [str(item)[:max_len] for item in list(items)[:limit]]


def chunk_log_payload(chunks: Iterable[dict] | None, text_limit: int = 500) -> list[dict]:
    """Build a compact, structured chunk payload for RAG result logs."""
    payload: list[dict] = []
    for idx, chunk in enumerate(chunks or [], start=1):
        metadata = chunk.get("metadata") or {}
        text = chunk.get("text") or ""
        payload.append(
            {
                "rank": idx,
                "chunk_id": chunk.get("chunk_id"),
                "document_id": chunk.get("document_id"),
                "filename": metadata.get("filename"),
                "section_name": metadata.get("section_name"),
                "page_number": metadata.get("page_number"),
                "score": chunk.get("score"),
                "text_preview": text[:text_limit],
                "text_length": len(text),
            }
        )
    return payload


def timed_node(node_name: str):
    """노드 실행 시간을 timing 딕셔너리에 기록하는 데코레이터.

    Args:
        node_name: 노드 이름 (timing 키 및 로그에 사용)
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(state, *args, **kwargs):
            start = time.perf_counter()
            logger.info("[RAG][node=%s] 시작", node_name)
            try:
                result = await func(state, *args, **kwargs)
                elapsed_seconds = time.perf_counter() - start
                # 기존 timing 딕셔너리에 현재 노드 실행 시간 추가
                timing = state.get("timing", {})
                timing[f"{node_name}_s"] = elapsed_seconds
                result["timing"] = timing
                logger.info("[RAG][node=%s] 완료 elapsed=%.1fs", node_name, elapsed_seconds)
                return result
            except Exception as e:
                elapsed_seconds = time.perf_counter() - start
                logger.error(
                    "[RAG][node=%s] 오류 elapsed=%.1fs error=%s",
                    node_name,
                    elapsed_seconds,
                    e,
                )
                raise
        return wrapper
    return decorator
