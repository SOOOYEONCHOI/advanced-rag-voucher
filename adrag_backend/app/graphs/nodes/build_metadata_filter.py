"""
메타데이터 필터 구성 노드.

사용자 권한(UserPermission)을 기반으로 Qdrant 검색 필터를 구성한다.

필터 구성 흐름:
  1. UserPermission 기반 필터 (must) — 항상 적용, DB 데이터 기반
       - security_level : 보안등급 계층 적용 (상위 등급은 하위 등급 포함)
       - source_collection: 접근 가능 컬렉션 교집합
       - metadata_filters: 사용자별 추가 동적 필터

보안 정책:
  - 요청 collection_filters ∩ accessible_collections = ∅ → PermissionError
  - anonymous 사용자 → anonymous_default_collections 정책 적용

Qdrant payload 필드명:
  must  — source_collection, security_level
"""

import json
from typing import Any, Dict, List, Optional

from app.core.config import get_settings
from app.graphs.dependencies import GraphDependencies
from app.graphs.state import PipelineState
from app.graphs.utils import timed_node
from app.repositories.metadata_repository import MetadataRepository
# 2026.07.16(sooyeon.choi) 수정 - 중복 정의 제거, 공통 모듈의 보안등급 계층 사용
from app.utils.security import SECURITY_HIERARCHY as _SECURITY_HIERARCHY
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)

def _build_permission_filters(
    permissions,
    request_filters: Optional[List[str]],
    settings=None,
) -> Dict[str, Any]:
    """UserPermission 기반 필터를 구성한다.

    요청 collection_filters와 권한의 교집합이 빈 경우 PermissionError를 발생시킨다.
    permissions이 None(anonymous)인 경우 anonymous_default_collections 정책을 적용한다.
    permissions.metadata_filters를 추가 must 조건으로 병합한다.
    """
    permission_filters: Dict[str, Any] = {}

    if permissions:
        # source_collection — accessible_collections 비어 있으면 필터 미적용(전체 허용)
        if permissions.accessible_collections:
            permission_filters["source_collection"] = permissions.accessible_collections

        # security_level 계층 적용
        max_level = permissions.max_security_level or "public"
        permission_filters["security_level"] = _SECURITY_HIERARCHY.get(max_level, ["public"])

        # metadata_filters 동적 병합
        if permissions.metadata_filters:
            for k, v in permissions.metadata_filters.items():
                if k not in permission_filters:  # 핵심 필드(security_level 등) 덮어쓰기 방지
                    permission_filters[k] = v

    else:
        # permissions=None: anonymous 사용자
        permission_filters["security_level"] = ["public"]

        # anonymous_default_collections 정책
        if settings:
            try:
                anon_collections = json.loads(settings.anonymous_default_collections)
            except (json.JSONDecodeError, TypeError):
                anon_collections = []

            if anon_collections:
                permission_filters["source_collection"] = anon_collections
            else:
                raise PermissionError(
                    "anonymous_default_collections가 비어 있어 anonymous 검색을 허용하지 않습니다."
                )

    # 요청 collection_filters ∩ accessible_collections 교집합 검증
    if request_filters:
        if permissions and permissions.accessible_collections:
            allowed = set(permissions.accessible_collections)
            intersected = [c for c in request_filters if c in allowed]
            if not intersected:
                raise PermissionError(
                    f"요청 컬렉션 {request_filters}이 허용 컬렉션 "
                    f"{permissions.accessible_collections}과 교집합이 없습니다."
                )
            permission_filters["source_collection"] = intersected
        elif permissions and not permissions.accessible_collections:
            # accessible_collections=[] → 전체 허용이므로 요청 필터 그대로 적용
            permission_filters["source_collection"] = request_filters
        else:
            # anonymous → 요청 collection_filters 무시
            pass

    return permission_filters


@timed_node("build_metadata_filter")
async def build_metadata_filter(state: PipelineState, deps: GraphDependencies | None = None) -> dict:
    """UserPermission + 규칙 기반 전처리 결과로 Qdrant 검색 필터 구성."""
    settings = deps.settings if deps else get_settings()
    meta_repo = MetadataRepository()

    # 사용자 권한 조회
    try:
        permissions = meta_repo.get_user_permissions(state["user_id"])
    except Exception as e:
        logger.error(f"사용자 권한 조회 실패, public 기본 필터 적용: {e}")
        permissions = None

    # ── 0단계: collection_name 권한 이중 검증 ──
    # 라우터(query.py)에서 1차 검증을 하지만, 파이프라인 내부에서도 방어적으로 확인한다.
    # anonymous 사용자는 anonymous_default_collections 정책으로 제어되므로 별도 처리.
    collection_name = state.get("collection_name")
    if collection_name and permissions and permissions.accessible_collections:
        if collection_name not in permissions.accessible_collections:
            logger.warning(
                f"파이프라인 내부 컬렉션 권한 차단: "
                f"user={state['user_id']}, collection={collection_name}, "
                f"accessible={permissions.accessible_collections}"
            )
            # 2026.06.19(sooyeon.choi) 추가 - 검색 준비 단계 실패 결과 코드 기록
            return {
                "error": f"'{collection_name}' 컬렉션에 접근 권한이 없습니다.",
                "outcome_code": "retrieval_error",
            }

    # ── 1단계: UserPermission 기반 필터 구성 ──
    try:
        permission_filters = _build_permission_filters(
            permissions,
            state.get("collection_filters"),
            settings=settings,
        )
    except PermissionError as e:
        # 허용 컬렉션 교집합 없음 → error 설정 후 build_response로 단락
        logger.warning(f"컬렉션 권한 차단: {e}")
        return {
            "error": f"요청 컬렉션에 대한 접근 권한이 없습니다: {e}",
            "outcome_code": "retrieval_error",
        }

    flag = state.get("enable_metadata_filtering")
    if flag is None:
        flag = settings.enable_metadata_filtering

    if not flag:
        return {"filters": {"must": permission_filters}}

    structured_filters: Dict[str, Any] = {"must": permission_filters}

    return {"filters": structured_filters}
