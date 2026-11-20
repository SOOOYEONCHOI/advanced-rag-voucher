"""Persist RAG query results without leaking repository argument lists."""

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.repositories.metadata_repository import MetadataRepository
from app.services.stats_service import StatsService


@dataclass
class QueryRecord:
    query: str
    user_id: str
    started_at: float
    session_id: Optional[str] = None
    collection_id: Optional[int] = None
    collection_name: Optional[str] = None
    model_id: str = "local"
    # 2026.11.12(woojin.jung) 추가 - 질문 입력 경로(text·voice·recommended·popular)
    input_mode: str = "text"


class QueryRecorder:
    def __init__(self, repository: MetadataRepository) -> None:
        self._repository = repository

    async def record(
        self,
        request: QueryRecord,
        state: Dict[str, Any],
        *,
        answer: Optional[str] = None,
        citations: Optional[List[Dict[str, Any]]] = None,
        outcome_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Optional[int]:
        usage = state.get("usage") or {}
        elapsed_ms = (time.time() - request.started_at) * 1000
        context_text, context_meta = _serialize_context(state.get("context_chunks", []))
        cost = StatsService.estimate_cost(
            request.model_id,
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
        ) if usage else (0.0 if request.model_id == "local" else None)

        log_id = await asyncio.to_thread(
            self._repository.log_query,
            query_text=request.query,
            user_id=request.user_id,
            session_id=request.session_id,
            collection_id=request.collection_id,
            answer_text=answer,
            context_text=context_text,
            context_meta=context_meta,
            response_time_s=elapsed_ms / 1000.0,
            response_time_ms=elapsed_ms,
            chunks_retrieved=len(state.get("reranked_chunks", [])),
            answer_generated=bool(state.get("generated_answer")),
            outcome_code=outcome_code or state.get("outcome_code", "unknown"),
            error_message=error_message or state.get("error"),
            model_id=request.model_id,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            cost_usd=cost,
            extracted_keywords=(state.get("preprocess_result") or {}).get("extracted_keywords"),
            collection_name_snapshot=request.collection_name,
            input_mode=request.input_mode,  # 2026.11.12(woojin.jung) 추가 - 질문 입력 경로
        )
        if log_id and citations:
            rows = [
                {
                    "document_id": item.get("document_id", ""),
                    "original_filename": item.get("original_filename", ""),
                    "collection_id": request.collection_id,
                    "collection_name_snapshot": request.collection_name,
                }
                for item in citations
                if item.get("document_id")
            ]
            await asyncio.to_thread(self._repository.store_query_citations, log_id, rows)
        return log_id


def _serialize_context(chunks: List[Dict[str, Any]]) -> tuple[List[str], List[Dict[str, Any]]]:
    text: List[str] = []
    metadata: List[Dict[str, Any]] = []
    for number, chunk in enumerate(chunks, start=1):
        meta = chunk.get("metadata") or {}
        text.append(chunk.get("text", ""))
        metadata.append({
            "citation_no": number,
            "chunk_id": chunk.get("chunk_id"),
            "document_id": chunk.get("document_id"),
            "document_name": meta.get("filename", ""),
            "score": chunk.get("score"),
            "section_name": meta.get("section_name"),
            "header_path": meta.get("header_path", []),
            "page_number": meta.get("page_number"),
        })
    return text, metadata
