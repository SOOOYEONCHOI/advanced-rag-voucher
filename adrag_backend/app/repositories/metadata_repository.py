# 2026.06.16(sooyeon.choi) 수정
#   기존 직접 SQL 로직을 전문 Repository에 위임한다.
#   routes/services가 순차적으로 전문 Repository로 교체되면 이 파일은 제거된다.
#
#   위임 매핑:
#     list_documents           → DocumentRepository.list_by_collection()
#     delete_document          → DocumentRepository.soft_delete()
#     store_user_permission    → PermissionsRepository.grant() + upsert_policy()
#     get_user_permissions     → PermissionsRepository.get_user_permission()
#     log_query                → QueryLogRepository.log_query()
#     get_query_history        → QueryLogRepository.get_history()
#     store_query_context      → SessionRepository.upsert()
#     get_query_context        → SessionRepository.get_by_id()
#     get_session_by_collection→ SessionRepository.get_by_user_collection() (qdrant_name 룩업 포함)
#     reset_session_by_collection → SessionRepository.reset()
#     delete_expired_query_contexts → SessionRepository.delete_expired()
"""
MetadataRepository

routes/services 교체 완료 전까지 하위 호환성을 유지한다.
"""

import logging
from typing import Any, Dict, List, Optional

from app.models.data_models import (
    QueryContext,
    UserPermission,
    UserSecurityPolicy,
)
from app.repositories.database import get_database_manager
from app.repositories.document_repository import DocumentRepository
from app.repositories.permissions_repository import PermissionsRepository
from app.repositories.query_log_repository import QueryLogRepository
from app.repositories.session_repository import SessionRepository

logger = logging.getLogger(__name__)


class MetadataRepository:
    """내부적으로 전문 Repository에 위임한다."""

    def __init__(self):
        self._db = get_database_manager()
        self._doc = DocumentRepository()
        self._perm = PermissionsRepository()
        self._session = SessionRepository()
        self._log = QueryLogRepository()
        logger.debug("MetadataRepository (facade) initialized")

    # ── 문서 ────────────────────────────────────────────────────────────────

    def list_documents(
        self,
        collection_id: Optional[int] = None,
        doc_type: Optional[str] = None,
        security_level: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        if collection_id is None:
            rows = self._db.execute_query(
                "SELECT * FROM tb_documents WHERE deleted_at IS NULL "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            return [dict(r) for r in rows]
        return self._doc.list_by_collection(
            collection_id=collection_id,
            doc_type=doc_type,
            security_level=security_level,
            limit=limit,
            offset=offset,
        )

    def delete_document(self, document_id: str) -> bool:
        """논리 삭제 (Soft Delete)."""
        return self._doc.soft_delete(document_id)

    # ── 권한 ────────────────────────────────────────────────────────────────

    def store_user_permission(self, permission: UserPermission) -> bool:
        """UserPermission (qdrant_name 목록)을 tb_user_collection_permissions + tb_user_security_policies로 분산 저장.

        qdrant_name → collection_id 변환을 위해 tb_collections 조회가 필요하다.
        """
        # 1. 기존 권한 전체 회수
        self._perm.revoke_all(permission.user_id)

        # 2. qdrant_name → collection_id 변환 후 권한 부여
        for qdrant_name in permission.accessible_collections:
            rows = self._db.execute_query(
                "SELECT collection_id FROM tb_collections WHERE qdrant_name=? AND is_active=TRUE",
                (qdrant_name,),
            )
            if rows:
                self._perm.grant(
                    user_id=permission.user_id,
                    collection_id=rows[0]["collection_id"],
                )

        # 3. 보안 정책 갱신
        self._perm.upsert_policy(
            UserSecurityPolicy(
                user_id=permission.user_id,
                max_security_level=permission.max_security_level,
                allowed_doc_types=permission.allowed_document_types,
                metadata_filters=permission.metadata_filters,
            )
        )
        return True

    def get_user_permissions(self, user_id: str) -> Optional[UserPermission]:
        """RAG 파이프라인용 UserPermission 반환."""
        return self._perm.get_user_permission(user_id)

    # ── 질의 로그 ───────────────────────────────────────────────────────────

    def log_query(
        self,
        query_text: str,
        user_id: str,
        session_id: Optional[str] = None,
        collection_id: Optional[int] = None,
        answer_text: Optional[str] = None,
        context_text: Optional[List[str]] = None,
        context_meta: Optional[List[Dict[str, Any]]] = None,
        response_time_s: Optional[float] = None,
        response_time_ms: Optional[float] = None,
        chunks_retrieved: Optional[int] = None,
        answer_generated: bool = False,
        outcome_code: str = "unknown",
        error_message: Optional[str] = None,
        model_id: Optional[str] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        cost_usd: Optional[float] = None,
        extracted_keywords: Optional[List[str]] = None,
        department_snapshot: Optional[str] = None,
        collection_name_snapshot: Optional[str] = None,
        input_mode: str = "text",  # 2026.11.12(woojin.jung) 추가 - 질문 입력 경로
    ) -> Optional[int]:
        """질의 로그를 INSERT하고 log_id를 반환한다."""
        # 2026.06.19(sooyeon.choi) 추가 - 결과 코드·응답 본문·통계 스냅샷 위임
        return self._log.log_query(
            query_text=query_text,
            user_id=user_id,
            session_id=session_id,
            collection_id=collection_id,
            answer_text=answer_text,
            context_text=context_text,
            context_meta=context_meta,
            response_time_s=response_time_s,
            response_time_ms=response_time_ms,
            chunks_retrieved=chunks_retrieved,
            answer_generated=answer_generated,
            outcome_code=outcome_code,
            error_message=error_message,
            model_id=model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            extracted_keywords=extracted_keywords,
            department_snapshot=department_snapshot,
            collection_name_snapshot=collection_name_snapshot,
            input_mode=input_mode,
        )

    def set_query_feedback(
        self,
        log_id: int,
        user_id: str,
        feedback: Optional[int],
        reasons: Optional[List[str]] = None,
        comment: Optional[str] = None,
    ) -> bool:
        """피드백 저장 (1=좋아요, 0=별로에요, None=취소).
        user_id 조건으로 본인 로그만 수정 가능하다.
        """
        # 2026.06.16(sooyeon.choi) 추가 - SCR-006 피드백 API facade
        # 2026.11.05(woojin.jung) 수정 - 피드백 사유·의견 전달
        return self._log.set_feedback(log_id, user_id, feedback, reasons, comment)

    def store_query_citations(
        self, log_id: int, citations: List[Dict[str, Any]]
    ) -> None:
        """인용 문서 목록을 tb_query_citations에 일괄 기록한다."""
        # 2026.06.16(sooyeon.choi) 추가 - SCR-006 인용 저장 facade
        self._log.store_citations(log_id, citations)

    def get_query_history(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        return self._log.get_history(user_id=user_id, session_id=session_id, limit=limit)

    # ── 대화 세션 ───────────────────────────────────────────────────────────

    def store_query_context(self, context: QueryContext) -> bool:
        return self._session.upsert(context)

    def get_query_context(self, session_id: str) -> Optional[QueryContext]:
        return self._session.get_by_id(session_id)

    def get_session_by_collection(
        self, user_id: str, qdrant_name: str
    ) -> Optional[QueryContext]:
        """qdrant_name으로 세션 조회 (qdrant_name → collection_id 변환 포함)."""
        rows = self._db.execute_query(
            "SELECT collection_id FROM tb_collections WHERE qdrant_name=? AND is_active=TRUE",
            (qdrant_name,),
        )
        if not rows:
            return None
        collection_id = rows[0]["collection_id"]
        return self._session.get_by_user_collection(user_id, collection_id)

    def reset_session_by_collection(
        self, user_id: str, qdrant_name: str
    ) -> bool:
        """qdrant_name으로 세션 초기화 (qdrant_name → collection_id 변환 포함)."""
        rows = self._db.execute_query(
            "SELECT collection_id FROM tb_collections WHERE qdrant_name=? AND is_active=TRUE",
            (qdrant_name,),
        )
        if not rows:
            return False
        collection_id = rows[0]["collection_id"]
        return self._session.reset(user_id, collection_id)

    def delete_expired_query_contexts(self) -> int:
        return self._session.delete_expired()
