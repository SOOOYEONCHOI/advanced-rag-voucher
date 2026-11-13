# 2026.04.01(sooyeon.choi) 수정 - 멀티컬렉션 관리 기능 추가
# 2026.06.16(sooyeon.choi) 수정 - v4 스키마 반영
#   _add_to_user_accessible(): tb_user_permissions → PermissionsRepository.grant() (collection_id 기반)
#   _remove_collection_from_all_permissions(): 제거 (ON DELETE CASCADE가 자동 처리)
#   list_collections(): tb_ingest_documents → tb_documents, collection_name → display_name
#   CollectionConfigResponse: collection_name/collection_desc → display_name/description 매핑
# 2026.06.29(sooyeon.choi) 수정 - 사용자 권한 관리
#   CollectionCreateRequest: topic_name 필드 추가
#   create_collection(): _add_to_user_accessible() 제거 (topic 기반 권한으로 교체)
#   create_collection(): topic_name ∈ effective_topics 검증 추가
"""
컬렉션 관리 API 엔드포인트.

컬렉션 CRUD 및 목록 조회를 제공한다.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.utils.log.log import LoggingLogger
from app.services.collection_service import (
    CollectionDeletionConflict,
    CollectionService,
)
# 2026.11.12(woojin.jung) 추가 - 채팅 시작 화면 질문(추천 질문·숨긴 질문) 설정
from app.services.start_question_service import StartQuestionService
from app.repositories.collection_repository import CollectionRepository
from app.repositories.department_repository import DepartmentRepository
# 2026.11.09(sooyeon.choi) 삭제 - 미사용 import(PermissionsRepository)
from app.repositories.vector_repository import VectorRepository
from app.repositories.database import get_database_manager
from app.core.config import get_settings
from app.utils.datetime import format_kst_datetime
from app.utils.security import get_current_principal

# 로거 초기화
# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용
logger = LoggingLogger().getLogger(__name__)

router = APIRouter(prefix="/collections", tags=["collections"])


# ── Pydantic 요청/응답 모델 ──────────────────────────────────────────────────

class CollectionCreateRequest(BaseModel):
    name: str
    description: str = ""
    # 2026.06.29(sooyeon.choi) 추가 - 컬렉션 대화 주제 (부서 허용 주제 중 하나)
    topic_name: Optional[str] = None


class CollectionUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class CollectionConfigResponse(BaseModel):
    collection_id: int
    collection_name: str   # 표시명 (display_name 매핑)
    collection_desc: str   # 설명 (description 매핑)
    qdrant_name: str = ""
    # 2026.06.18(sooyeon.choi) 수정 - Qdrant 컬렉션 존재 여부 추가
    qdrant_exists: bool = False
    document_count: int = 0
    created_by: str = ""
    # 2026.06.30(sooyeon.choi) 추가 - 조회 권한과 컬렉션 관리 권한 분리
    owned_by_me: bool = False
    can_update: bool = False
    can_delete: bool = False
    other_user_document_count: int = 0
    created_at: str
    updated_at: str


class CollectionListResponse(BaseModel):
    collections: List[CollectionConfigResponse]
    total: int


# 2026.11.12(woojin.jung) 추가 - 채팅 시작 화면 질문 저장 요청 (개수·길이 상세 검증은 StartQuestionService)
class StartQuestionSettingsRequest(BaseModel):
    recommended: List[str] = Field(default_factory=list, max_length=20)
    hidden: List[str] = Field(default_factory=list, max_length=100)


# 2026.06.30(sooyeon.choi) 추가 - 컬렉션 수정·삭제는 생성자 또는 관리자만 허용
def _require_collection_manager(
    collection_id: int,
    principal: dict,
    repo: CollectionRepository,
):
    collection = repo.get_by_id(collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="대화 주제를 찾을 수 없습니다.")
    if (
        not principal.get("is_admin")
        and collection.created_by != principal["user_id"]
    ):
        raise HTTPException(
            status_code=403,
            detail="본인이 생성한 대화 주제만 수정하거나 삭제할 수 있습니다.",
        )
    return collection


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.post("", status_code=201, response_model=CollectionConfigResponse)
async def create_collection(
    request: CollectionCreateRequest,
    principal: dict = Depends(get_current_principal),
):
    """컬렉션을 생성한다.

    2026.06.29(sooyeon.choi) 수정 -
    - _add_to_user_accessible() 제거 (컬렉션 권한은 topic 기반으로 자동 결정됨)
    - topic_name이 주어진 경우 effective_topics 범위 내인지 검증
    """
    try:
        topic_name = request.topic_name or None
        department_id: Optional[str] = None
        # 2026.06.30(sooyeon.choi) 추가 - 컬렉션에 생성자 부서 ID와 부서명 함께 저장
        department_name = ""

        # 생성자 부서 ID 조회 (department_id 스냅샷 저장용)
        if principal["user_id"]:
            db = get_database_manager()
            user_rows = db.execute_query(
                "SELECT department_id, department_name FROM tb_users WHERE user_id = ?",
                (principal["user_id"],),
            )
            if user_rows and user_rows[0]["department_id"]:
                department_id = user_rows[0]["department_id"]
                department_name = user_rows[0]["department_name"] or ""

        service = CollectionService()
        config = service.create_collection(
            name=request.name,
            description=request.description,
            created_by=principal["user_id"],
            topic_name=topic_name,
            department_id=department_id,
            department_name=department_name,
        )

        # 비관리자가 topic_name을 지정한 경우 부서 allowed_topics에 자동 반영
        if topic_name and department_id and not principal.get("is_admin"):
            dept_repo = DepartmentRepository()
            dept = dept_repo.get_by_id(department_id)
            if dept and topic_name not in dept["allowed_topics"]:
                dept_repo.update(
                    department_id=department_id,
                    allowed_topics=dept["allowed_topics"] + [topic_name],
                )
                logger.info("부서 allowed_topics 자동 반영: dept=%s topic=%s", department_id, topic_name)

        logger.info("컬렉션 생성 완료: %s (topic=%s)", config.display_name, topic_name)

        return CollectionConfigResponse(
            collection_id=config.collection_id,
            collection_name=config.display_name,
            collection_desc=config.description,
            qdrant_name=config.qdrant_name,
            qdrant_exists=True,
            document_count=0,
            created_by=config.created_by or "",
            # 2026.06.30(sooyeon.choi) 추가 - 생성 직후 관리 권한 응답
            owned_by_me=True,
            can_update=True,
            can_delete=True,
            created_at=format_kst_datetime(config.created_at),
            updated_at=format_kst_datetime(config.updated_at),
        )
    except HTTPException:
        raise
    except ValueError as e:
        msg = str(e)
        if "유효한 컬렉션 이름을 입력해주세요" in msg:
            raise HTTPException(status_code=400, detail=msg)
        elif "최대" in msg and "등록 가능합니다" in msg:
            raise HTTPException(status_code=400, detail=msg)
        elif "이미 등록된 컬렉션 이름입니다" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        logger.error(f"컬렉션 생성 실패: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="벡터 데이터베이스 연결에 실패했습니다")


@router.get("", response_model=CollectionListResponse)
async def list_collections(
    include_all: bool = Query(False, description="True면 사용자 필터 없이 전체 반환"),
    principal: dict = Depends(get_current_principal),
):
    """등록된 컬렉션 목록을 조회한다."""
    try:
        settings = get_settings()
        repo = CollectionRepository()

        # 2026.06.30(sooyeon.choi) 추가 - 일반 사용자는 실질 접근 컬렉션만 조회
        if principal.get("is_admin"):
            collections = repo.get_all() if include_all else repo.get_by_owner(principal["user_id"])
        else:
            if include_all:
                raise HTTPException(
                    status_code=403,
                    detail="전체 대화 주제 조회 권한이 없습니다.",
                )
            collections = repo.get_accessible_by_user(principal["user_id"])

        db = get_database_manager()
        # 2026.06.18(sooyeon.choi) 수정 - 등록 컬렉션과 Qdrant 컬렉션 상태 비교
        qdrant_names = set(VectorRepository(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
        ).list_collections())

        result: List[CollectionConfigResponse] = []
        for col in collections:
            # 2026.06.25(sooyeon.choi) - tb_collections와 실제 Qdrant 컬렉션 교집합만 노출
            if col.qdrant_name not in qdrant_names:
                logger.warning(
                    "SQLite 컬렉션이 Qdrant에 없어 목록에서 제외: collection_id=%s qdrant_name=%s",
                    col.collection_id,
                    col.qdrant_name,
                )
                continue
            document_count = 0
            other_user_document_count = 0
            try:
                # 2026.06.30(sooyeon.choi) 추가 - 삭제 확인용 전체·타인 업로드 문서 수 조회
                rows = db.execute_query(
                    """
                    SELECT COUNT(*) AS document_count,
                           SUM(CASE
                               WHEN uploaded_by IS NULL OR uploaded_by <> ? THEN 1
                               ELSE 0
                           END) AS other_user_document_count
                    FROM tb_documents
                    WHERE collection_id = ? AND deleted_at IS NULL
                    """,
                    (principal["user_id"], col.collection_id),
                )
                if rows:
                    document_count = rows[0]["document_count"]
                    other_user_document_count = rows[0]["other_user_document_count"] or 0
            except Exception:
                pass
            # 2026.06.30(sooyeon.choi) 추가 - 현재 사용자가 수행 가능한 기능
            owned_by_me = col.created_by == principal["user_id"]
            can_manage = bool(principal.get("is_admin") or owned_by_me)
            result.append(CollectionConfigResponse(
                collection_id=col.collection_id,
                collection_name=col.display_name,
                collection_desc=col.description,
                qdrant_name=col.qdrant_name,
                qdrant_exists=True,
                document_count=document_count,
                created_by=col.created_by or "",
                owned_by_me=owned_by_me,
                can_update=can_manage,
                can_delete=can_manage,
                other_user_document_count=other_user_document_count,
                created_at=format_kst_datetime(col.created_at),
                updated_at=format_kst_datetime(col.updated_at),
            ))

        return CollectionListResponse(collections=result, total=len(result))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"컬렉션 목록 조회 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다")


@router.put("/{collection_id}", response_model=CollectionConfigResponse)
async def update_collection(
    collection_id: int,
    request: CollectionUpdateRequest,
    principal: dict = Depends(get_current_principal),
):
    """컬렉션 설정을 수정한다."""
    try:
        # 2026.06.30(sooyeon.choi) 추가 - 서비스 변경 전에 컬렉션 관리 권한 검증
        repo = CollectionRepository()
        existing = _require_collection_manager(collection_id, principal, repo)
        service = CollectionService()
        config = service.update_collection(
            collection_id=collection_id,
            name=request.name,
            description=request.description,
        )
        return CollectionConfigResponse(
            collection_id=config.collection_id,
            collection_name=config.display_name,
            collection_desc=config.description,
            qdrant_name=config.qdrant_name,
            qdrant_exists=config.qdrant_name in set(service.vector_repo.list_collections()),
            document_count=0,
            created_by=existing.created_by or "",
            owned_by_me=existing.created_by == principal["user_id"],
            can_update=True,
            can_delete=True,
            created_at=format_kst_datetime(config.created_at),
            updated_at=format_kst_datetime(config.updated_at),
        )
    except HTTPException:
        raise
    except ValueError as e:
        msg = str(e)
        if "컬렉션을 찾을 수 없습니다" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        logger.error(f"컬렉션 수정 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다")


# 2026.11.12(woojin.jung) 추가 - 대화 주제 설정: 추천 질문·숨긴 질문·많이 찾는 질문 미리보기 조회
@router.get("/{collection_id}/start-questions")
async def get_start_question_settings(
    collection_id: int,
    principal: dict = Depends(get_current_principal),
):
    """대화 주제의 채팅 시작 화면 질문 설정을 조회한다 (생성자 또는 관리자)."""
    _require_collection_manager(collection_id, principal, CollectionRepository())
    try:
        return StartQuestionService().get_settings(collection_id)
    except Exception as e:
        logger.error(f"시작 화면 질문 조회 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다")


# 2026.11.12(woojin.jung) 추가 - 대화 주제 설정: 추천 질문·숨긴 질문 일괄 저장
@router.put("/{collection_id}/start-questions")
async def save_start_question_settings(
    collection_id: int,
    request: StartQuestionSettingsRequest,
    principal: dict = Depends(get_current_principal),
):
    """추천 질문(등록 순서 = 노출 순서)과 숨긴 질문을 통째로 교체 저장한다 (생성자 또는 관리자)."""
    _require_collection_manager(collection_id, principal, CollectionRepository())
    try:
        result = StartQuestionService().save_settings(
            collection_id,
            recommended=request.recommended,
            hidden=request.hidden,
            user_id=principal["user_id"],
        )
        logger.info(
            "시작 화면 질문 저장: collection_id=%s actor=%s recommended=%s hidden=%s",
            collection_id,
            principal["user_id"],
            len(result["recommended"]),
            len(result["hidden"]),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"시작 화면 질문 저장 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다")


# 2026.05.04(sooyeon.choi) 수정 - Qdrant 벡터 데이터 + SQLite 레코드 함께 삭제
# 2026.06.16(sooyeon.choi) 수정 - _remove_collection_from_all_permissions 제거
#   tb_user_collection_permissions.collection_id ON DELETE CASCADE가 자동 처리
@router.delete("/{collection_id}")
async def delete_collection(
    collection_id: int,
    principal: dict = Depends(get_current_principal),
):
    """컬렉션을 완전 삭제한다. Qdrant 벡터 데이터 + SQLite 레코드를 모두 제거한다."""
    try:
        # 2026.06.30(sooyeon.choi) 추가 - 생성자는 타인 업로드 문서를 포함해 컬렉션 전체 삭제 가능
        settings = get_settings()
        repo = CollectionRepository()
        _require_collection_manager(collection_id, principal, repo)
        db = get_database_manager()
        count_rows = db.execute_query(
            """
            SELECT SUM(CASE
                       WHEN uploaded_by IS NULL OR uploaded_by <> ? THEN 1
                       ELSE 0
                   END) AS other_user_document_count
            FROM tb_documents
            WHERE collection_id = ? AND deleted_at IS NULL
            """,
            (principal["user_id"], collection_id),
        )
        deleted_other_user_document_count = (
            (count_rows[0]["other_user_document_count"] or 0) if count_rows else 0
        )
        service = CollectionService()
        result = service.delete_collection(collection_id)
        # 2026.06.30(sooyeon.choi) 추가 - 삭제 수행자와 영향받은 문서 수 감사 로그
        logger.info(
            "컬렉션 삭제 완료: collection=%s actor=%s documents=%s other_user_documents=%s",
            result["collection_name"],
            principal["user_id"],
            result["deleted_document_count"],
            deleted_other_user_document_count,
        )
        return {
            "status": "deleted",
            "message": "대화 주제가 삭제되었습니다.",
            "collection_id": result["collection_id"],
            "deleted_document_count": result["deleted_document_count"],
            "deleted_other_user_document_count": deleted_other_user_document_count,
            "qdrant_collection_deleted": result["qdrant_collection_deleted"],
            "remaining_qdrant_collection": result["remaining_qdrant_collection"],
            "reconciled": result["reconciled"],
        }
    except HTTPException:
        raise
    except CollectionDeletionConflict as e:
        logger.info(
            "컬렉션 삭제 차단: collection_id=%s code=%s details=%s",
            collection_id,
            e.error_code,
            e.details,
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": e.message,
                "error_code": e.error_code,
                **e.details,
                "retryable": e.error_code == "COLLECTION_HAS_RUNNING_JOB",
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        logger.error(f"컬렉션 삭제 실패: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"컬렉션 삭제 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다")
