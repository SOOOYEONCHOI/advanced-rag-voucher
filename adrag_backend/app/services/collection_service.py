# 2026.04.01(sooyeon.choi) 수정 - 멀티컬렉션 관리 기능 추가
# 2026.06.16(sooyeon.choi) 수정
#   collection_name → display_name, collection_desc → description
#   get_by_name() → get_by_display_name()
#   delete_collection(): tb_ingest_documents → tb_documents (RESTRICT FK 처리)
"""
컬렉션 관리 비즈니스 로직 서비스.

CollectionRepository와 VectorRepository를 조합하여
컬렉션 CRUD 및 유효성 검증을 수행한다.
"""

import json
from typing import List

from app.utils.log.log import LoggingLogger
from app.core.config import get_settings
from app.models.data_models import CollectionConfig
from app.repositories.collection_repository import CollectionRepository
from app.repositories.database import get_database_manager
from app.repositories.department_repository import DepartmentRepository
from app.repositories.vector_repository import VectorRepository

# 로거 초기화
# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용
logger = LoggingLogger().getLogger(__name__)


class CollectionDeletionConflict(Exception):
    """Raised when a collection has references or jobs that block deletion."""

    def __init__(self, error_code: str, message: str, **details):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = details


class CollectionService:
    """컬렉션 설정 관리 서비스."""

    def __init__(self) -> None:
        """CollectionRepository, VectorRepository 초기화."""
        self.settings = get_settings()
        self.collection_repo = CollectionRepository()
        self.vector_repo = VectorRepository(
            host=self.settings.qdrant_host,
            port=self.settings.qdrant_port,
            sparse_encoder_type=self.settings.sparse_encoder_type,
        )
        logger.info("CollectionService initialized")

    def create_collection(
        self,
        name: str,
        description: str = "",
        created_by: str = "",
        # 2026.06.29(sooyeon.choi) 추가 - 대화 주제 + 생성자 부서 스냅샷
        topic_name: str = None,
        department_id: str = None,
        # 2026.06.30(sooyeon.choi) 추가 - 생성자 부서명 동기화 값
        department_name: str = "",
    ) -> CollectionConfig:
        """
        컬렉션 생성.

        검증: 빈 이름, 사용자별 최대 개수, 사용자 내 중복.
        Qdrant 컬렉션 생성(qdrant_name 사용) + SQLite 저장.
        """
        if not name or not name.strip():
            raise ValueError("유효한 컬렉션 이름을 입력해주세요")

        display_name = name.strip()
        qdrant_name = f"{created_by}_{display_name}" if created_by else display_name
        # 2026.06.25(sooyeon.choi) 수정 - Qdrant Dashboard에서 직접 삭제된 컬렉션의 SQLite 잔여 메타데이터 정리
        self._cleanup_missing_qdrant_collection(qdrant_name, display_name, created_by)

        # 사용자별 최대 개수 검증
        owner_count = (
            self.collection_repo.count_by_owner(created_by)
            if created_by else self.collection_repo.count()
        )
        if owner_count >= self.settings.max_collections:
            raise ValueError(f"최대 {self.settings.max_collections}개까지 등록 가능합니다")

        # 2026.06.16(sooyeon.choi) 수정 - collection_name → display_name, get_by_name → get_by_display_name
        existing = (
            [
                c for c in self.collection_repo.get_by_owner(created_by)
                if c.display_name == display_name
            ]
            if created_by
            else (
                [self.collection_repo.get_by_display_name(display_name)]
                if self.collection_repo.get_by_display_name(display_name) else []
            )
        )
        if existing:
            raise ValueError("이미 등록된 컬렉션 이름입니다")

        # 2026.06.25(sooyeon.choi) - Qdrant 생성 성공 시에만 tb_collections 저장
        # Qdrant 생성 실패 후 SQLite에만 남는 불일치 상태를 방지한다.
        if not self.vector_repo.create_collection(
            collection_name=qdrant_name,
            vector_size=self.settings.embedding_dim,
        ):
            raise RuntimeError(f"Qdrant 컬렉션 생성 실패: '{qdrant_name}'")

        # 2026.06.25(sooyeon.choi) 수정 - SQLite 저장 실패 시 Qdrant 롤백
        try:
            config = self.collection_repo.create(
                display_name, description,
                created_by=created_by,
                qdrant_name=qdrant_name,
                # 2026.06.29(sooyeon.choi) 추가
                topic_name=topic_name,
                department_id=department_id,
                department_name=department_name,
            )
        except Exception:
            self.vector_repo.delete_collection(qdrant_name)
            raise
        logger.info(f"컬렉션 생성 완료: display='{display_name}', qdrant='{qdrant_name}'")
        return config

    # 2026.06.25(sooyeon.choi) 수정 - Qdrant에는 없고 SQLite에만 남은 컬렉션 메타데이터 정리
    def _cleanup_missing_qdrant_collection(
        self,
        qdrant_name: str,
        display_name: str,
        created_by: str = "",
    ) -> None:
        """Remove stale SQLite metadata when its Qdrant collection was deleted directly."""
        existing = self.collection_repo.get_by_qdrant_name(qdrant_name)
        if existing is None:
            return
        if existing.display_name != display_name or existing.created_by != created_by:
            return
        if self.vector_repo.collection_exists(qdrant_name):
            return

        db = get_database_manager()
        deleted_docs = db.execute_update(
            "DELETE FROM tb_documents WHERE collection_id = ?",
            (existing.collection_id,),
        )
        if not self.collection_repo.delete(existing.collection_id):
            raise RuntimeError(
                f"SQLite 컬렉션 삭제 실패: collection_id={existing.collection_id}"
            )
        logger.warning(
            "Qdrant에서 삭제된 컬렉션의 SQLite 메타데이터 정리: "
            "collection_id=%s qdrant_name=%s deleted_docs=%s",
            existing.collection_id,
            qdrant_name,
            deleted_docs,
        )

    def list_collections(self) -> List[CollectionConfig]:
        """등록된 컬렉션 목록 반환."""
        return self.collection_repo.get_all()

    def update_collection(
        self,
        collection_id: int,
        name: str = None,
        description: str = None,
    ) -> CollectionConfig:
        """컬렉션 설정 수정."""
        existing = self.collection_repo.get_by_id(collection_id)
        if existing is None:
            raise ValueError("컬렉션을 찾을 수 없습니다")

        # 2026.06.16(sooyeon.choi) 수정 - get_by_name → get_by_display_name
        if name is not None:
            if not name.strip():
                raise ValueError("유효한 컬렉션 이름을 입력해주세요")
            duplicate = self.collection_repo.get_by_display_name(name.strip())
            if duplicate is not None and duplicate.collection_id != collection_id:
                raise ValueError("이미 등록된 컬렉션 이름입니다")

        updated = self.collection_repo.update(
            collection_id,
            display_name=name.strip() if name is not None else None,
            description=description,
        )
        logger.info(f"컬렉션 수정 완료: id={collection_id}")
        return updated

    # 2026.05.04(sooyeon.choi) 수정 - Qdrant 벡터 데이터 + SQLite 레코드 함께 삭제
    # 2026.06.16(sooyeon.choi) 수정 - tb_ingest_documents → tb_documents (v4 스키마)
    #   tb_documents.collection_id FK ON DELETE RESTRICT 이므로
    #   tb_collections 삭제 전에 tb_documents 레코드를 먼저 삭제해야 한다.
    def delete_collection(self, collection_id: int) -> dict:
        """컬렉션을 완전 삭제한다. Qdrant 벡터 데이터 + SQLite 레코드 모두 제거."""
        existing = self.collection_repo.get_by_id(collection_id)
        if existing is None:
            raise ValueError("컬렉션을 찾을 수 없습니다")

        qdrant_name = existing.qdrant_name
        self._ensure_collection_deletable(collection_id, qdrant_name)

        # 1. Qdrant 컬렉션이 존재하는 경우 삭제 후 실제 부재를 검증한다.
        try:
            qdrant_existed = self.vector_repo.collection_exists(qdrant_name)
        except Exception as e:
            raise RuntimeError(
                f"Qdrant 컬렉션 상태 확인 실패: '{qdrant_name}'"
            ) from e

        reconciled = not qdrant_existed
        if qdrant_existed:
            qdrant_ok = self.vector_repo.delete_collection(qdrant_name)
            if not qdrant_ok:
                raise RuntimeError(
                    f"Qdrant 컬렉션 삭제 실패: '{qdrant_name}'. "
                    "Qdrant 서버 상태를 확인하세요."
                )
            try:
                still_exists = self.vector_repo.collection_exists(qdrant_name)
            except Exception as e:
                raise RuntimeError(
                    f"Qdrant 컬렉션 삭제 검증 실패: '{qdrant_name}'"
                ) from e
            if still_exists:
                raise RuntimeError(
                    f"Qdrant 컬렉션 삭제 검증 실패: '{qdrant_name}' 컬렉션이 남아 있습니다."
                )
            logger.info(f"Qdrant 컬렉션 삭제 완료: '{qdrant_name}'")
        else:
            logger.warning(
                "Qdrant에 없는 컬렉션의 SQLite 메타데이터 정리: "
                "collection_id=%s qdrant_name=%s",
                collection_id,
                qdrant_name,
            )

        # 2. SQLite 관련 삭제와 권한 정리를 하나의 트랜잭션으로 수행한다.
        db = get_database_manager()
        department_repo = DepartmentRepository()
        with db.get_connection() as conn:
            deleted_docs = conn.execute(
                "DELETE FROM tb_documents WHERE collection_id = ?",
                (collection_id,),
            ).rowcount

            if not self.collection_repo.delete(collection_id, conn=conn):
                raise RuntimeError(
                    f"SQLite 컬렉션 삭제 실패: collection_id={collection_id}"
                )

            if existing.department_id and existing.topic_name:
                remaining = conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM tb_collections
                    WHERE department_id = ? AND topic_name = ?
                    """,
                    (existing.department_id, existing.topic_name),
                ).fetchone()["count"]
                if remaining == 0:
                    department_repo.remove_topic_and_clean_users(
                        existing.department_id,
                        existing.topic_name,
                        conn=conn,
                    )
                    logger.info(
                        "마지막 컬렉션 삭제에 따른 부서 주제 권한 정리 완료: "
                        "department_id=%s topic=%s",
                        existing.department_id,
                        existing.topic_name,
                    )

        logger.info(
            "컬렉션 SQLite 삭제 완료: id=%s display='%s' documents=%s",
            collection_id,
            existing.display_name,
            deleted_docs,
        )

        return {
            "collection_id": collection_id,
            "collection_name": existing.display_name,
            "qdrant_name": qdrant_name,
            "deleted_document_count": deleted_docs,
            "qdrant_collection_deleted": qdrant_existed,
            "remaining_qdrant_collection": False,
            "reconciled": reconciled,
        }

    def _ensure_collection_deletable(
        self,
        collection_id: int,
        qdrant_name: str,
    ) -> None:
        """Validate deletion blockers before changing Qdrant or SQLite."""
        db = get_database_manager()

        active_ingest_jobs = 0
        job_rows = db.execute_query(
            """
            SELECT request_json
            FROM tb_ingest_jobs
            WHERE status IN ('queued', 'running')
            """
        )
        for row in job_rows:
            try:
                request = json.loads(row["request_json"])
            except (TypeError, ValueError):
                logger.warning(
                    "삭제 사전 검사 중 ingest request_json 파싱 실패: %s",
                    row["request_json"],
                )
                continue
            if request.get("collection_name") == qdrant_name:
                active_ingest_jobs += 1

        generating_rows = db.execute_query(
            """
            SELECT COUNT(*) AS count
            FROM tb_eval_datasets
            WHERE collection_id = ? AND status = 'generating'
            """,
            (collection_id,),
        )
        generating_datasets = generating_rows[0]["count"] if generating_rows else 0

        running_rows = db.execute_query(
            """
            SELECT COUNT(*) AS count
            FROM tb_eval_runs r
            JOIN tb_eval_goldsets g ON g.goldset_id = r.goldset_id
            JOIN tb_eval_datasets d ON d.dataset_id = g.dataset_id
            WHERE d.collection_id = ? AND r.status IN ('pending', 'running')
            """,
            (collection_id,),
        )
        running_eval_runs = running_rows[0]["count"] if running_rows else 0

        if active_ingest_jobs or generating_datasets or running_eval_runs:
            raise CollectionDeletionConflict(
                "COLLECTION_HAS_RUNNING_JOB",
                "진행 중인 문서 업로드 또는 평가 작업이 있어 대화 주제를 삭제할 수 없습니다.",
                active_ingest_job_count=active_ingest_jobs,
                generating_dataset_count=generating_datasets,
                running_eval_run_count=running_eval_runs,
            )

        dataset_rows = db.execute_query(
            """
            SELECT COUNT(*) AS count
            FROM tb_eval_datasets
            WHERE collection_id = ?
            """,
            (collection_id,),
        )
        evaluation_dataset_count = dataset_rows[0]["count"] if dataset_rows else 0
        if evaluation_dataset_count:
            raise CollectionDeletionConflict(
                "COLLECTION_HAS_EVALUATION_DATA",
                "이 대화 주제를 사용하는 평가 데이터셋이 있어 삭제할 수 없습니다.",
                evaluation_dataset_count=evaluation_dataset_count,
            )

    def validate_collection_name(self, name: str) -> bool:
        """컬렉션 이름(qdrant_name 또는 display_name)이 등록되어 있는지 확인."""
        # 2026.06.16(sooyeon.choi) 수정 - get_by_name → get_by_display_name
        return (
            self.collection_repo.get_by_qdrant_name(name) is not None
            or self.collection_repo.get_by_display_name(name) is not None
        )

