"""
RAG 서비스.

LangGraph RAG 파이프라인 그래프를 실행하고,
PipelineState 결과를 QueryResponse로 변환하여 반환한다.
"""

import asyncio
import json
import time
from dataclasses import asdict
from datetime import timedelta
# 2026.05.27(sooyeon.choi) 스트리밍 기능 추가 - AsyncGenerator import 추가
from typing import Any, AsyncGenerator, Dict, List, Optional
from uuid import uuid4

from app.core.config import get_settings
from app.core.runtime_settings import get_runtime_settings_version
from app.graphs.rag_graph import build_rag_graph
# 2026.07.16(sooyeon.choi) 수정 - 초기 state 40줄 dict 중복 제거용 팩토리 import
from app.graphs.state import PipelineState, make_initial_state
# 2026.07.16(sooyeon.choi) 추가 - 스트리밍 fallback 확장 규칙 공유, 임계값 헬퍼
from app.core.user_messages import UserMessageType, get_user_message
from app.models.data_models import ChunkSummary, Citation, QueryContext, QueryResponse
from app.repositories.metadata_repository import MetadataRepository
# 2026.06.16(sooyeon.choi) 수정 - collection_id 조회를 위해 CollectionRepository import
from app.repositories.collection_repository import CollectionRepository
# 2026.06.16(sooyeon.choi) 추가 - SCR-006 API 비용 계산
# 2026.06.19(sooyeon.choi) 추가 - 비스트리밍 질의 결과 코드 확정
from app.services.query_outcome import resolve_query_outcome
from app.services.query_recorder import QueryRecord, QueryRecorder
# 2026.05.27(sooyeon.choi) 스트리밍 기능 추가 - 노드 직접 호출용 import

from app.utils.log.log import LoggingLogger
from app.utils.datetime import now_kst

# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용
logger = LoggingLogger().getLogger(__name__)


def _sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _resolve_collection_id(qdrant_name: Optional[str]) -> Optional[int]:
    """qdrant_name → collection_id 변환. 미등록이면 None 반환."""
    # 2026.06.16(sooyeon.choi) 추가 - QueryContext.collection_id(int) 대입용 헬퍼
    if not qdrant_name:
        return None
    col = CollectionRepository().get_by_qdrant_name(qdrant_name)
    return col.collection_id if col else None


# 2026.11.09(sooyeon.choi) 추가 - 대화 이력 1턴 저장(query·query_stream 공통)
#   저장 조건·실패 시 로그 문구는 호출하는 쪽이 정한다(query: collection_name 기준, stream: collection_id 기준).
async def _store_history_turn(
    meta_repo: MetadataRepository,
    *,
    session_id: str,
    collection_id: Optional[int],
    user_id: str,
    query: str,
    answer: str,
    citations: list,
    images: Optional[list],
    images_total: Optional[int],
) -> None:
    """기존 대화 이력(같은 사용자일 때만)에 질문·답변 1턴을 붙여 최근 20개를 14일 보관으로 저장한다."""
    # 2026.07.16(sooyeon.choi) 수정 - 동기 SQLite 조회/기록을 to_thread로 이동
    stored_history: List[Dict[str, Any]] = []
    stored_context = await asyncio.to_thread(meta_repo.get_query_context, session_id)
    if stored_context and stored_context.user_id == user_id:
        stored_history = list(stored_context.conversation_history or [])

    stored_history.append({"role": "user", "content": query})
    stored_history.append({
        "role": "assistant",
        "content": answer,
        "citations": citations,
        # 2026.10.19 추가 - Phase 4-A: 대화 이력 복원 시 사진도 다시 표시
        "images": images or [],
        # 2026.11.06(sooyeon.choi) 추가 - 이력 복원 시 "전체 N장 보기" 표시용
        "images_total": images_total if images_total is not None else len(images or []),
    })

    now = now_kst()
    await asyncio.to_thread(
        meta_repo.store_query_context,
        QueryContext(
            session_id=session_id,
            user_id=user_id,
            conversation_history=stored_history[-20:],
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(days=14),
            collection_id=collection_id,
        ),
    )


class RAGService:
    """LangGraph RAG 파이프라인 실행 서비스."""

    def __init__(self):
        self.graph = build_rag_graph()
        self._graph_settings_version = get_runtime_settings_version()

    def _current_graph(self):
        version = get_runtime_settings_version()
        if version != self._graph_settings_version:
            self.graph = build_rag_graph()
            self._graph_settings_version = version
        return self.graph

    async def query(
        self,
        query: str,
        user_id: str,
        collection_filters: Optional[List[str]] = None,
        collection_name: Optional[str] = None,
        top_k: Optional[int] = None,
        relevance_threshold: Optional[float] = None,
        # 2026.04.10(sooyeon.choi) 추가 - LLM 모델 선택 파라미터
        llm_provider: Optional[str] = None,
        llm_model: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        enable_metadata_filtering: Optional[bool] = None,
        # 2026.11.12(woojin.jung) 추가 - 질문 입력 경로(text·voice·recommended·popular), 질의 로그에 기록
        input_mode: str = "text",
    ) -> QueryResponse:
        """RAG 질의를 실행하고 구조화된 응답을 반환한다."""
        start = time.time()
        logger.info("[RAG][pipeline] 시작 mode=query")
        settings = get_settings()
        meta_repo = MetadataRepository()
        # 2026.07.08(sooyeon.choi) 수정 - top_k 생략과 명시를 구분해 단계별 설정 우선순위 보장
        normalized_top_k = (
            max(1, min(top_k, settings.max_query_top_k))
            if top_k is not None
            else None
        )
        resolved_threshold = relevance_threshold if relevance_threshold is not None else settings.relevance_threshold
        citation_limit = min(
            normalized_top_k or settings.context_top_k,
            settings.max_citation_results,
        )

        # 2026.05.07(sooyeon.choi) 추가 - (user_id, collection_name)으로 기존 세션 조회/재사용
        # 2026.06.16(sooyeon.choi) 수정 - collection_id(int) 파악 후 QueryContext에 전달
        # 2026.07.16(sooyeon.choi) 수정 - 동기 SQLite 조회를 to_thread로 이동해 이벤트 루프 블로킹 방지
        collection_id: Optional[int] = None
        if collection_name:
            existing = await asyncio.to_thread(
                meta_repo.get_session_by_collection, user_id, collection_name
            )
            session_id = existing.session_id if existing else str(uuid4())
            collection_id = (
                existing.collection_id
                if existing
                else await asyncio.to_thread(
                    _resolve_collection_id, collection_name
                )
            )
        else:
            session_id = None

        recorder = QueryRecorder(meta_repo)
        record = QueryRecord(
            query=query,
            user_id=user_id,
            started_at=start,
            session_id=session_id,
            collection_id=collection_id,
            model_id=llm_model or "local",
            input_mode=input_mode,  # 2026.11.12(woojin.jung) 추가 - 질문 입력 경로
        )

        # 2026.07.16(sooyeon.choi) 수정 - 중복 dict 리터럴 제거, 공용 팩토리 사용
        initial_state: PipelineState = make_initial_state(
            user_id=user_id,
            session_id=session_id,
            original_query=query,
            collection_filters=collection_filters,
            collection_name=collection_name,
            top_k=normalized_top_k,
            citation_limit=citation_limit,
            llm_provider=llm_provider,
            llm_model=llm_model,
            llm_api_key=openai_api_key,
            enable_metadata_filtering=enable_metadata_filtering,
            relevance_threshold=resolved_threshold,
        )

        try:
            result = await self._current_graph().ainvoke(initial_state)
        except Exception as exc:
            elapsed_ms = (time.time() - start) * 1000
            logger.error(
                "[RAG][pipeline] 오류 mode=query elapsed=%.2fs error=%s",
                time.time() - start,
                exc,
            )
            # 2026.06.19(sooyeon.choi) 추가 - 그래프 미처리 예외도 질의 로그에 1회 기록
            # 2026.07.16(sooyeon.choi) 수정 - 동기 SQLite 기록을 to_thread로 이동
            try:
                await recorder.record(
                    record,
                    initial_state,
                    outcome_code="system_error",
                    error_message=str(exc),
                )
            except Exception as log_exc:
                logger.warning(f"시스템 오류 질의 로그 기록 실패 (무시): {log_exc}")
            raise
        elapsed_ms = (time.time() - start) * 1000

        logger.info(
            "[RAG][pipeline] 완료 mode=query elapsed=%.2fs",
            elapsed_ms / 1000,
        )

        chunks = [
            ChunkSummary(
                chunk_id=c["chunk_id"],
                document_id=c["document_id"],
                document_name=c["metadata"].get("filename", ""),
                text=c["text"],
                score=c["score"],
                section_name=c["metadata"].get("section_name"),
                page_number=c["metadata"].get("page_number"),
            )
            for c in result.get("reranked_chunks", [])
        ]

        citations = [
            Citation(
                citation_id=str(c.get("citation_id", "")),
                document_id=c.get("document_id", ""),
                original_filename=c.get("original_filename", ""),
                chunk_text=c.get("chunk_text", ""),
                section_name=c.get("section_name"),
                header_path=c.get("header_path", []),
                page_number=c.get("page_number"),
                title=c.get("title", ""),
                document_type=c.get("document_type"),
                score=c.get("score"),
                referenced_in_answer=c.get("referenced_in_answer", False),
                # 2026.08.27(sooyeon.choi) 추가 - spreadsheet citation API 필드 전달
                sheet_name=c.get("sheet_name"),
                source_range=c.get("source_range"),
                display_markdown=c.get("display_markdown"),
                resource_ids=c.get("resource_ids", []),
            )
            for c in result.get("citations", [])
        ]

        response = QueryResponse(
            query=query,
            answer=result.get("generated_answer") or result.get("error") or "",
            chunks=chunks,
            citations=citations,
            processing_time_ms=elapsed_ms,
            # 2026.10.19 추가 - Phase 4-A 답변 사진
            images=list(result.get("answer_images") or []),
            # 2026.11.06(sooyeon.choi) 추가 - 출처 사진 전체 장수(같은 그림 1장)
            images_total=result.get("answer_images_total") or len(result.get("answer_images") or []),
            timing=dict(result.get("timing") or {}),
        )

        # 2026.11.05(woojin.jung) 수정 - 대화 이력(세션) 저장을 쿼리 로그 기록보다 먼저 수행
        #   (세션 행이 없으면 log_query가 FK 때문에 session_id를 비움 → 새로고침 시 피드백 복원 불가)
        # 2026.05.07(sooyeon.choi) 추가 - collection_name 있을 때만 대화 이력 저장
        # 2026.06.16(sooyeon.choi) 수정 - QueryContext.collection_id(int) 사용
        # 2026.11.09(sooyeon.choi) 수정 - _store_history_turn 사용(저장 조건: collection_name 있음)
        if session_id and collection_name:
            try:
                await _store_history_turn(
                    meta_repo,
                    session_id=session_id,
                    collection_id=collection_id,
                    user_id=user_id,
                    query=query,
                    answer=response.answer,
                    citations=[asdict(c) for c in (response.citations or [])],
                    images=response.images,
                    images_total=response.images_total,
                )
            except Exception as e:
                logger.warning(f"세션 히스토리 저장 실패 (무시): {e}")

        try:
            # 2026.06.16(sooyeon.choi) 수정 - SCR-006 통계 컬럼 추가 (usage, cost, keywords, answer_text)
            # 2026.06.19(sooyeon.choi) 추가 - 정상 답변의 결과 코드와 컬렉션 스냅샷 저장
            # 2026.07.16(sooyeon.choi) 수정 - 동기 SQLite 조회/기록을 to_thread로 이동
            collection_name_snapshot = None
            if collection_id is not None:
                collection = await asyncio.to_thread(
                    CollectionRepository().get_by_id,
                    collection_id,
                )
                collection_name_snapshot = (
                    collection.display_name if collection else None
                )
            record.collection_name = collection_name_snapshot
            citation_rows = [asdict(c) for c in citations]
            log_id = await recorder.record(
                record,
                result,
                answer=response.answer,
                citations=citation_rows,
                outcome_code=resolve_query_outcome(result),
            )
            if log_id:
                response.log_id = log_id
        except Exception as e:
            logger.warning(f"쿼리 로그 기록 실패 (무시): {e}")

        return response

    # 2026.06.05(sooyeon.choi) 추가 - 대화 이력 저장 공동 헬퍼
    # 2026.06.16(sooyeon.choi) 수정 - collection_name → collection_id(int) 파라미터 변경
    #   query_stream의 정상/가드레일·no_result 세 경로에서 중복 없이 호출
    async def _save_stream_history(
            self,
            meta_repo: MetadataRepository,
            session_id: str,
            collection_id: Optional[int],
            user_id: str,
            query: str,
            answer: str,
            citation: list,
            images: Optional[list] = None,
            images_total: Optional[int] = None,  # 2026.11.06(sooyeon.choi) 추가
    ) -> None:
        """(session_id, collection_id)이 유효한 경우에만 대화 이력을 저장한다."""
        if not (session_id and collection_id is not None):
            return
        try:
            # 2026.11.09(sooyeon.choi) 수정 - _store_history_turn 사용(저장 조건: collection_id 있음)
            await _store_history_turn(
                meta_repo,
                session_id=session_id,
                collection_id=collection_id,
                user_id=user_id,
                query=query,
                answer=answer,
                citations=citation,
                images=images,
                images_total=images_total,
            )
        except Exception as e:
            logger.warning(f"스트리밍 세션 히스토리 저장 실패 (무시): {e}")


    async def _query_stream_from_graph(
        self,
        *,
        query: str,
        user_id: str,
        collection_filters: Optional[List[str]],
        collection_name: Optional[str],
        top_k: Optional[int],
        relevance_threshold: Optional[float],
        llm_provider: Optional[str],
        llm_model: Optional[str],
        openai_api_key: Optional[str],
        enable_metadata_filtering: Optional[bool],
        input_mode: str = "text",  # 2026.11.12(woojin.jung) 추가 - 질문 입력 경로
    ) -> AsyncGenerator[str, None]:
        """Run the compiled graph once and translate its events to SSE."""
        settings = get_settings()
        repository = MetadataRepository()
        started_at = time.time()
        normalized_top_k = max(1, min(top_k, settings.max_query_top_k)) if top_k is not None else None
        collection_id = None
        session_id = None
        collection_snapshot = None
        if collection_name:
            existing = await asyncio.to_thread(repository.get_session_by_collection, user_id, collection_name)
            session_id = existing.session_id if existing else str(uuid4())
            collection_id = existing.collection_id if existing else await asyncio.to_thread(
                _resolve_collection_id, collection_name
            )
            if collection_id is not None:
                collection = await asyncio.to_thread(
                    CollectionRepository().get_by_id, collection_id
                )
                collection_snapshot = collection.display_name if collection else None

        state = make_initial_state(
            user_id=user_id,
            session_id=session_id,
            original_query=query,
            collection_filters=collection_filters,
            collection_name=collection_name,
            top_k=normalized_top_k,
            citation_limit=min(normalized_top_k or settings.context_top_k, settings.max_citation_results),
            llm_provider=llm_provider,
            llm_model=llm_model,
            llm_api_key=openai_api_key,
            enable_metadata_filtering=enable_metadata_filtering,
            relevance_threshold=relevance_threshold if relevance_threshold is not None else settings.relevance_threshold,
        )
        record = QueryRecord(
            query=query,
            user_id=user_id,
            started_at=started_at,
            session_id=session_id,
            collection_id=collection_id,
            collection_name=collection_snapshot,
            model_id=llm_model or "local",
            input_mode=input_mode,  # 2026.11.12(woojin.jung) 추가 - 질문 입력 경로
        )
        recorder = QueryRecorder(repository)
        final_state: Dict[str, Any] = dict(state)
        emitted_stage = None
        accumulated = ""

        try:
            async for event in self._current_graph().astream_events(state, version="v2"):
                event_type = event.get("event")
                name = event.get("name")
                metadata = event.get("metadata") or {}
                node = metadata.get("langgraph_node") or name
                stage = None
                if event_type == "on_chain_start" and node in {
                    "analyze_and_rewrite", "build_metadata_filter", "retrieve", "rerank"
                }:
                    stage = "searching"
                elif event_type == "on_chain_start" and node == "generate_answer":
                    stage = "generating"
                    # 2026.11.11(sooyeon.choi) 추가 - LLM 재시도로 generate_answer가 다시 시작되면
                    #   앞서 보낸(실패한) 토큰을 화면이 지우도록 reset을 보낸다(이어 붙임 방지)
                    if name == "generate_answer" and accumulated:
                        accumulated = ""
                        yield _sse({"type": "reset"})
                if stage and stage != emitted_stage:
                    emitted_stage = stage
                    yield _sse({"type": "progress", "stage": stage})

                if event_type == "on_custom_event" and name == "rag_token":
                    token = (event.get("data") or {}).get("token", "")
                    accumulated += token
                    yield _sse({"type": "token", "content": token})

                if event_type == "on_chain_end" and not event.get("parent_ids"):
                    output = (event.get("data") or {}).get("output")
                    if isinstance(output, dict):
                        final_state = output

            answer = final_state.get("generated_answer") or final_state.get("error") or accumulated
            # 2026.11.11(sooyeon.choi) 추가 - LLM이 토큰을 보내다 끝내 실패하면 잘린 답변 대신
            #   오류 안내를 보여 준다(대화 이력에 저장되는 answer와 화면을 일치)
            if accumulated and final_state.get("outcome_code") == "llm_error":
                accumulated = ""
                yield _sse({"type": "reset"})
            if answer and not accumulated:
                yield _sse({"type": "token", "content": answer})
            citations = final_state.get("citations") or []
            yield _sse({"type": "citations", "data": citations})
            # 2026.10.19 추가 - Phase 4-A 답변 사진: 검증된 사진 목록. 화면은 이 목록에 없는 [IMG:ref]를 지운다
            images = list(final_state.get("answer_images") or [])
            # 2026.11.06(sooyeon.choi) 수정 - total(출처 사진 전체 장수) 추가. data 모양은 그대로(기존 화면 호환)
            images_total = final_state.get("answer_images_total") or len(images)
            if images:
                yield _sse({"type": "images", "data": images, "total": images_total})
            # 2026.11.05(woojin.jung) 수정 - 세션(대화 이력)을 먼저 저장해야 새 대화의 첫 질의 로그에도
            #   session_id가 남는다(세션 행이 없으면 log_query가 FK 때문에 session_id를 비움 → 새로고침 시 피드백 복원 불가)
            if session_id and collection_name:
                await self._save_stream_history(
                    repository, session_id, collection_id, user_id, query, answer, citations, images, images_total
                )
            log_id = await recorder.record(record, final_state, answer=answer, citations=citations)
            if log_id:
                yield _sse({"type": "meta", "log_id": log_id})
            yield _sse({"type": "done"})
        except asyncio.CancelledError:
            await recorder.record(
                record, final_state, answer=accumulated or None,
                outcome_code="cancelled", error_message="stream_cancelled",
            )
            raise
        except Exception as exc:
            logger.error("query_stream 그래프 처리 오류: %s", exc, exc_info=True)
            await recorder.record(
                record, final_state, answer=accumulated or None,
                outcome_code="system_error", error_message=str(exc),
            )
            yield _sse({
                "type": "error",
                "message": get_user_message(UserMessageType.TEMPORARY_ERROR),
            })

    # 2026.05.27(sooyeon.choi) 스트리밍 기능 추가 - SSE 실시간 스트리밍 응답 생성기
    async def query_stream(
        self,
        query: str,
        user_id: str,
        collection_filters: Optional[List[str]] = None,
        collection_name: Optional[str] = None,
        top_k: Optional[int] = None,
        relevance_threshold: Optional[float] = None,
        llm_provider: Optional[str] = None,
        llm_model: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        enable_metadata_filtering: Optional[bool] = None,
        # 2026.11.12(woojin.jung) 추가 - 질문 입력 경로(text·voice·recommended·popular), 질의 로그에 기록
        input_mode: str = "text",
    ) -> AsyncGenerator[str, None]:
        """
        단일 LangGraph 실행에서 발생한 이벤트를 SSE로 변환한다.

        처리 흐름:
          1) 세션·컬렉션 정보를 조회하고 초기 state와 QueryRecord를 구성한다.
          2) 컴파일된 그래프를 astream_events(version="v2")로 한 번 실행한다.
             그래프 내부에서 입력 검증, 가드레일, 질의 분석, 메타데이터 필터,
             검색·재검색, 리랭킹, 컨텍스트 구성, 답변 생성과 인용 정리를 수행한다.
          3) 검색 관련 노드가 시작되면 progress(searching), 답변 생성 노드가
             시작되면 progress(generating) 이벤트를 단계별로 한 번 전송한다.
          4) generate_answer 노드가 발행한 rag_token custom event를 token SSE로
             변환하면서 답변을 누적한다.
          5) 최상위 그래프 종료 output을 final_state로 저장한다. 토큰이 한 번도
             발행되지 않았다면 generated_answer 또는 error를 token으로 전송한다.
          6) final_state의 citations(와 검증된 사진이 있으면 images)를 전송하고 QueryRecorder로 질의 결과를 기록한다.
             로그 ID가 생성되면 meta 이벤트를 전송한다.
          7) 세션과 컬렉션이 있는 요청만 대화 이력을 저장한 뒤 done을 전송한다.
          8) 클라이언트 취소 시 cancelled 결과를 기록하고 취소를 다시 발생시킨다.
             그 외 예외는 system_error로 기록하고 error SSE를 전송한다.
        """
        async for event in self._query_stream_from_graph(
            query=query,
            user_id=user_id,
            collection_filters=collection_filters,
            collection_name=collection_name,
            top_k=top_k,
            relevance_threshold=relevance_threshold,
            llm_provider=llm_provider,
            llm_model=llm_model,
            openai_api_key=openai_api_key,
            enable_metadata_filtering=enable_metadata_filtering,
            input_mode=input_mode,  # 2026.11.12(woojin.jung) 추가 - 질문 입력 경로
        ):
            yield event
        return
