"""
RAG Query API.

2026.04.09(sooyeon.choi) 추가
- 채팅용 컬렉션 API, 세션 ID 자동 생성, 토큰 주체 추출, 접근 가능한 컬렉션 필터링 기능 추가
"""

import json
import logging
from dataclasses import asdict
from typing import List, Literal, Optional

# 2026.05.27(sooyeon.choi) 스트리밍 기능 추가 - StreamingResponse import 추가
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.user_messages import UserMessageType, get_user_message
from app.repositories.collection_repository import CollectionRepository
from app.repositories.metadata_repository import MetadataRepository
from app.repositories.user_llm_settings_repository import UserLlmSettingsRepository
from app.services.rag_service import RAGService
# 2026.11.12(woojin.jung) 추가 - 채팅 시작 화면 질문(추천 질문·많이 찾는 질문) 조회
from app.services.start_question_service import StartQuestionService
from app.utils.encryption import decrypt_api_key
from app.utils.security import decode_optional_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/query", tags=["RAG Query"])
_rag_service = RAGService()


class QueryRequestBody(BaseModel):
    """RAG 질의 요청 모델."""

    query: str
    # 2026.07.08(sooyeon.choi) 수정 - 미지정 시 단계별 candidate/reranker/context 설정을 사용
    top_k: Optional[int] = Field(default=None, ge=1, le=20)
    enable_reranking: bool = True
    collection_filters: Optional[List[str]] = None
    collection_name: Optional[str] = None
    # 2026.04.10(sooyeon.choi) 추가 - LLM 모델 선택 파라미터
    llm_provider: Optional[str] = None   # "local" | "openai"
    llm_model: Optional[str] = None      # 예: "gpt-4.1", "gpt-4o-mini"
    openai_api_key: Optional[str] = None
    enable_metadata_filtering: Optional[bool] = None  # None이면 config 설정 따름
    # 2026.11.12(woojin.jung) 추가 - 질문 입력 경로(직접 입력·음성·시작 화면 추천/많이 찾는 질문), tb_query_logs.input_mode에 기록
    input_mode: Literal["text", "voice", "recommended", "popular"] = "text"


def _extract_principal(request: Request) -> dict:
    """JWT Bearer 토큰에서 현재 주체를 추출한다."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        payload = decode_optional_token(auth_header[7:])
        if payload and payload.get("sub"):
            token_type = payload.get("type", "unknown")
            return {
                "user_id": payload["sub"],
                "token_type": token_type,
                "is_admin": token_type == "admin_access",
            }
    return {"user_id": "anonymous", "token_type": "anonymous", "is_admin": False}


def _get_accessible_collections(user_id: str) -> List[str]:
    """현재 사용자 기준 접근 가능한 qdrant_name 목록을 반환한다."""
    # 2026.06.16(sooyeon.choi) 수정 - collection_name → qdrant_name
    settings = get_settings()
    active_collections = {
        collection.qdrant_name
        for collection in CollectionRepository().get_all()
    }

    if user_id == "anonymous":
        try:
            anon_collections = set(json.loads(settings.anonymous_default_collections))
        except Exception:
            anon_collections = set()
        return sorted(active_collections & anon_collections)

    meta_repo = MetadataRepository()
    permissions = meta_repo.get_user_permissions(user_id)
    if not permissions or not permissions.accessible_collections:
        return []
    return sorted(active_collections & set(permissions.accessible_collections))


@router.get("/collections")
async def get_query_collections(request: Request):
    """채팅 사용자가 조회 가능한 컬렉션 목록을 반환한다."""
    principal = _extract_principal(request)
    if principal.get("is_admin"):
        qdrant_names = sorted(
            collection.qdrant_name
            for collection in CollectionRepository().get_all()
        )
    else:
        qdrant_names = _get_accessible_collections(principal["user_id"])

    # qdrant_name → display_name 매핑 (2026.06.16 수정: collection_name → display_name)
    settings = get_settings()
    all_cols = {
        c.qdrant_name: c.display_name
        for c in CollectionRepository().get_all()
    }
    return {
        "collections": [
            {
                "collection_name": all_cols.get(qn, qn),  # display name
                "qdrant_name": qn,                         # Qdrant 내부 식별자
            }
            for qn in qdrant_names
        ],
        "user_id": principal["user_id"],
    }


# 2026.11.09(sooyeon.choi) 추가 - rag_query·rag_query_stream 공통 처리(권한 확인·API 키 조회·서비스 인자)
def _authorize_query_collection(principal: dict, body: QueryRequestBody) -> None:
    """비관리자가 접근 권한 없는 대화 주제로 질의하면 403."""
    if body.collection_name and not principal.get("is_admin"):
        accessible = _get_accessible_collections(principal["user_id"])
        if body.collection_name not in accessible:
            raise HTTPException(
                status_code=403,
                detail=f"'{body.collection_name}' 컬렉션에 접근 권한이 없습니다.",
            )


def _resolve_openai_api_key(user_id: str, body: QueryRequestBody) -> Optional[str]:
    """openai_api_key가 요청에 없으면 DB에서 사용자 저장 키를 조회한다(없거나 복호화 실패면 None)."""
    # 2026.06.16(sooyeon.choi) 수정 - UserLlmSettingsRepository.get(user_id, collection_id:int)
    resolved_api_key = body.openai_api_key
    if not resolved_api_key and body.llm_provider == "openai" and body.collection_name:
        col = CollectionRepository().get_by_qdrant_name(body.collection_name)
        if col:
            saved = UserLlmSettingsRepository().get(user_id, col.collection_id)
            if saved and saved.api_key_enc:
                try:
                    resolved_api_key = decrypt_api_key(saved.api_key_enc)
                except Exception:
                    logger.warning("저장된 API 키 복호화 실패: user=%s", user_id)
    return resolved_api_key


def _service_kwargs(user_id: str, body: QueryRequestBody) -> dict:
    """RAGService.query / query_stream 공통 인자."""
    return dict(
        query=body.query,
        user_id=user_id,
        collection_filters=body.collection_filters,
        collection_name=body.collection_name,
        top_k=body.top_k,
        llm_provider=body.llm_provider,
        llm_model=body.llm_model,
        openai_api_key=_resolve_openai_api_key(user_id, body),
        enable_metadata_filtering=body.enable_metadata_filtering,
        # 2026.11.12(woojin.jung) 추가 - 질문 입력 경로 기록
        input_mode=body.input_mode,
    )


# 2026.11.12(woojin.jung) 추가 - 채팅 시작 화면: 대화 주제의 추천 질문 + 많이 찾는 질문
@router.get("/start-questions")
async def get_start_questions(request: Request, collection_name: str):
    """채팅 시작 화면에 보여 줄 추천 질문과 많이 찾는 질문을 반환한다."""
    principal = _extract_principal(request)
    if not principal.get("is_admin") and collection_name not in _get_accessible_collections(principal["user_id"]):
        raise HTTPException(status_code=403, detail=f"'{collection_name}' 컬렉션에 접근 권한이 없습니다.")
    collection = CollectionRepository().get_by_qdrant_name(collection_name)
    if collection is None:
        raise HTTPException(status_code=404, detail="대화 주제를 찾을 수 없습니다.")
    return StartQuestionService().get_start_questions(collection.collection_id)


@router.post("/")
async def rag_query(request: Request, body: QueryRequestBody):
    """RAG 질의를 실행한다."""
    principal = _extract_principal(request)
    user_id = principal["user_id"]
    # 2026.05.07(sooyeon.choi) 추가 - session_id 제거, 서버가 (user_id, collection_name)으로 세션 직접 관리
    logger.info("쿼리 요청 user_id=%s, collection=%s", user_id, body.collection_name)

    # 2026.11.09(sooyeon.choi) 수정 - 공통 처리 함수 사용
    _authorize_query_collection(principal, body)
    kwargs = _service_kwargs(user_id, body)

    try:
        response = await _rag_service.query(**kwargs)
        return asdict(response)
    except Exception as e:
        logger.error("RAG 쿼리 처리 중 오류 발생: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=get_user_message(UserMessageType.TEMPORARY_ERROR),
        )


# 2026.05.27(sooyeon.choi) 스트리밍 기능 추가 - SSE 스트리밍 엔드포인트
@router.post("/stream")
async def rag_query_stream(request: Request, body: QueryRequestBody):
    """RAG 질의 SSE 스트리밍 응답."""
    principal = _extract_principal(request)
    user_id = principal["user_id"]
    logger.info("스트리밍 쿼리 요청 user_id=%s, collection=%s", user_id, body.collection_name)

    # 2026.11.09(sooyeon.choi) 수정 - 공통 처리 함수 사용
    _authorize_query_collection(principal, body)

    return StreamingResponse(
        _rag_service.query_stream(**_service_kwargs(user_id, body)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# 2026.05.07(sooyeon.choi) 추가 - 컬렉션별 대화 이력 조회 (대화방 재입장 시 이전 대화 복원)
@router.get("/history")
async def get_chat_history(request: Request, collection_name: str):
    """(user_id, collection_name) 기준으로 저장된 대화 이력을 반환한다."""
    principal = _extract_principal(request)
    user_id = principal["user_id"]
    settings = get_settings()
    meta_repo = MetadataRepository()

    context = meta_repo.get_session_by_collection(user_id, collection_name)
    if not context:
        return {"history": [], "collection_name": collection_name}

    # 2026.06.24(woojin.jung) 수정 - 히스토리 응답에 피드백 대상 로그 ID와 저장 상태 포함
    history = [dict(message) for message in (context.conversation_history or [])]
    query_logs = list(reversed(meta_repo.get_query_history(
        user_id=user_id,
        session_id=context.session_id,
        limit=max(50, len(history)),
    )))
    unused_logs = list(query_logs)

    for index, message in enumerate(history):
        if message.get("role") != "assistant" or index == 0:
            continue

        user_message = history[index - 1]
        if user_message.get("role") != "user":
            continue

        query_text = user_message.get("content", "")
        answer_text = message.get("content", "")
        matched_log = next(
            (
                log for log in unused_logs
                if log.get("query_text") == query_text
                and log.get("answer_text") == answer_text
            ),
            None,
        )
        if matched_log is None:
            matched_log = next(
                (log for log in unused_logs if log.get("query_text") == query_text),
                None,
            )
        if matched_log is None:
            continue

        unused_logs.remove(matched_log)
        feedback = matched_log.get("feedback")
        message["log_id"] = matched_log.get("log_id")
        message["feedback"] = (
            "like" if feedback == 1
            else "dislike" if feedback == 0
            else None
        )

    return {
        "history": history,
        "collection_name": collection_name,
    }


# 2026.05.07(sooyeon.choi) 추가 - "새 채팅 시작": 컬렉션별 대화 이력 초기화
class ResetRequest(BaseModel):
    collection_name: str


@router.post("/reset")
async def reset_chat_history(request: Request, body: ResetRequest):
    """(user_id, collection_name) 기준으로 대화 이력을 초기화한다."""
    principal = _extract_principal(request)
    user_id = principal["user_id"]
    settings = get_settings()
    meta_repo = MetadataRepository()

    success = meta_repo.reset_session_by_collection(user_id, body.collection_name)
    return {"success": success, "collection_name": body.collection_name}


# 2026.06.16(sooyeon.choi) 추가 - SCR-006 피드백 API
class FeedbackRequest(BaseModel):
    feedback: Optional[Literal["like", "dislike"]] = None  # None = 취소(토글 해제)
    # 2026.11.05(woojin.jung) 추가 - 피드백 의견 패널의 사유 코드·자유 의견 (평가만 바꿀 때는 생략)
    reasons: List[str] = Field(default_factory=list, max_length=10)
    comment: Optional[str] = Field(default=None, max_length=1000)


# 2026.11.05(woojin.jung) 추가 - 평가별 허용 사유 코드 (화면 라벨: adrag_frontend/src/constants/feedbackReasons.js)
FEEDBACK_REASONS = {
    "like": {"accurate", "source_clear", "image_helpful", "actionable", "other"},
    "dislike": {"incorrect", "wrong_source", "wrong_image", "irrelevant", "insufficient", "other"},
}


@router.patch("/{log_id}/feedback")
async def submit_query_feedback(log_id: int, body: FeedbackRequest, request: Request):
    """채팅 응답에 좋아요(like)/별로에요(dislike) 피드백과 사유·의견을 저장한다.

    None을 전달하면 기존 피드백(사유·의견 포함)을 취소한다.
    본인이 발생시킨 쿼리 로그에만 적용 가능하다.
    """
    principal = _extract_principal(request)
    user_id = principal["user_id"]
    reasons = list(dict.fromkeys(body.reasons))
    comment = (body.comment or "").strip() or None
    if body.feedback is None and (reasons or comment):
        raise HTTPException(status_code=422, detail="평가를 선택한 뒤 의견을 남길 수 있습니다.")
    invalid = [r for r in reasons if r not in FEEDBACK_REASONS.get(body.feedback, set())]
    if invalid:
        raise HTTPException(status_code=422, detail=f"허용되지 않는 피드백 사유입니다: {', '.join(invalid)}")
    value = {"like": 1, "dislike": 0, None: None}[body.feedback]
    meta_repo = MetadataRepository()
    ok = meta_repo.set_query_feedback(log_id, user_id, value, reasons, comment)
    if not ok:
        raise HTTPException(status_code=404, detail="대상 로그를 찾을 수 없거나 접근 권한이 없습니다.")
    return {"log_id": log_id, "feedback": body.feedback, "reasons": reasons, "comment": comment}
