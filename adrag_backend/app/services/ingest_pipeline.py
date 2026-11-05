"""Checkpointed step pipeline for document ingestion."""

import asyncio
import hashlib
import logging
import os
import pickle
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from app.parsers.metadata_extractor import detect_file_format, extract_doc_title
# 2026.08.28(sooyeon.choi) 추가 - pull 방식 resource 회수
from app.core.config import get_settings
from app.services.parser_resource_puller import pull_parser_resources
# 2026.10.16 추가 - Phase 1 엑셀 전용 처리기 분기
from app.ingest.excel_chunks import EXCEL_ENGINE, excel_chunks_to_documents
from app.ingest.excel_images import link_excel_images, plan_excel_images, resource_ids_for, write_excel_images
from app.ingest.excel_runner import doc_key_for, run_excel_ingest
from app.ingest.records import (
    INITIAL_VERSION,
    assign_chunk_identity,
    chunk_resource_links,
    chunk_rows,
    flow_graph_rows,
)
from app.repositories.database import get_database_manager
from app.repositories.ingest_record_repository import IngestRecordRepository
from app.ingest.file_router import ROUTE_EXCEL_INGEST, resolve_parse_route

logger = logging.getLogger(__name__)

_LOG_STEP_NAMES = {
    "parse": "file_save",
    "chunk": "parse_chunk",
    "embed": "embed",
    "index": "index",
}


def _sha256_of(path: str) -> Optional[str]:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


# 2026.10.19 추가 - 최신본 변경: 요청에 target_document_id가 있으면 기존 문서의 다음 버전으로 적재한다.
#   새 버전 포인트는 저장 직후 검증하고, 활성 전환(tb_documents.version_no)은 IndexStep의 한 트랜잭션에서만 한다.
#   전환 전·실패 시에는 검색 제외 조건(version_visibility)이 새 버전 포인트를 가리므로 기존 최신본으로 검색된다.
def _version_of(request: Dict[str, Any]) -> int:
    return int(request.get("version_no") or INITIAL_VERSION)


def _is_new_version(request: Dict[str, Any]) -> bool:
    return bool(request.get("target_document_id"))


def _record_repo(service) -> IngestRecordRepository:
    return getattr(service, "record_repo", None) or IngestRecordRepository(
        getattr(service, "db", None) or get_database_manager()
    )


# 2026.08.27(sooyeon.choi) 추가 - resource service가 없는 stub service에서도 rollback이 원인 예외를 가리지 않는다.
def _resource_service(service):
    return getattr(service, "resource_service", None)


@dataclass
class IngestContext:
    request: Dict[str, Any]
    document_id: str = field(default_factory=lambda: str(uuid4()))
    data: Dict[str, Any] = field(default_factory=dict)


class ParseStep:
    name = "parse"

    async def run(self, service, context: IngestContext) -> None:
        request = context.request
        if context.data.get("stored_path"):
            return
        config = service._validate_collection(request["collection_name"])
        # 2026.10.19 수정 - 최신본 변경은 버전별 원본 파일명(이전 버전 원본 보존)
        save_args = (request["file_path"], request["filename"], context.document_id)
        if _is_new_version(request):
            save_args += (_version_of(request),)
        stored_filename, stored_path, file_size = await service._file_manager.save(*save_args)
        context.data.update(
            collection_config=config,
            stored_filename=stored_filename,
            stored_path=stored_path,
            file_size=file_size,
            # 2026.10.16 추가 - Phase 2: 버전 행의 원본 해시(중복 업로드 확인은 Phase 3)
            file_sha256=await asyncio.to_thread(_sha256_of, request["file_path"]),
        )


class ChunkStep:
    name = "chunk"

    async def run(self, service, context: IngestContext) -> None:
        request = context.request
        # 2026.10.16 추가 - Phase 1: EXCEL_PARSE_MODE=backend이면 엑셀은 excel_ingest로 처리(docling 미호출, D-16)
        settings = get_settings()
        route = resolve_parse_route(request["file_path"], settings.excel_parse_mode, request["filename"])
        if route.handler == ROUTE_EXCEL_INGEST:
            await self._run_excel_ingest(request, context, settings)
            return
        result = await asyncio.to_thread(
            service._parse_and_chunk,
            request["file_path"],
            request["filename"],
            request.get("parser_type", "docling"),
            request.get("chunk_size"),
            context.document_id,
            request.get("document_type", "auto"),
        )
        context.data["parse_result"] = result
        # 2026.08.27(sooyeon.choi) 추가 - resource commit/rollback 대상 job을 실행 중으로 표시
        parse_job_ids = sorted({
            chunk.metadata.get("parse_job_id")
            for chunk in result.get("chunks", [])
            if chunk.metadata.get("parse_job_id")
        })
        context.data["parse_job_ids"] = parse_job_ids
        resource_service = _resource_service(service)
        for parse_job_id in parse_job_ids if resource_service else []:
            resource_service.mark_job_active(parse_job_id)
            # 2026.08.28(sooyeon.choi) 추가 - pull 모드에서는 파서 보관본을 직접 회수한다.
            #   백엔드가 사설망/루프백이라 파서가 push할 수 없는 토폴로지를 지원한다.
            if get_settings().resource_delivery == "pull":
                await pull_parser_resources(
                    resource_service, parse_job_id, context.document_id
                )
        # parsing과 resource 전송이 끝난 뒤의 embed/vector 실패는 staging을 보존한다.
        # 재시도 시 ChunkStep을 건너뛰어도 IndexStep이 기존 resource를 commit할 수 있다.
        context.data["resource_transfer_completed"] = True

    # 2026.10.16 추가 - Phase 1: excel_ingest 결과를 기존 임베딩·적재 단계가 쓰는 parse_result 형식으로 바꾼다.
    async def _run_excel_ingest(self, request, context: IngestContext, settings) -> None:
        output = await asyncio.to_thread(
            run_excel_ingest,
            request["file_path"],
            request["filename"],
            request.get("job_id") or context.document_id,
            settings.md_save_dir,
            keep_last=settings.excel_md_keep_last,
            convert_timeout=settings.excel_xls_convert_timeout,
            model=request.get("product_model"),
        )
        # 2026.10.16 추가 - Phase 2: 사진 배치(resource_id 발급)·청크↔사진 연결·긴 청크 분할(P2-4·8·9)
        # 2026.10.19 수정 - 사진 ID·청크 ID에 실제 버전 사용(최신본 변경)
        image_plan = plan_excel_images(
            output.result, context.document_id, _version_of(request),
            parse_job_id=f"excel-{request.get('job_id') or context.document_id}",
        )
        # 2026.10.22(sooyeon.choi) 추가 - EXCEL_IMAGE_LINK_ALL: 장식·양식 머리글을 뺀 모든 사진을 셀 위치 기준으로 청크에 연결
        image_links = (
            link_excel_images(output.result, image_plan)
            if getattr(settings, "excel_image_link_all", False) else None
        )
        if image_links and image_links.summary["unlinked"]:
            logger.warning("[INGEST][excel] 청크에 연결하지 못한 사진 %d건: %s",
                           image_links.summary["unlinked"], image_links.summary["unlinked_resource_ids"])
        chunks = excel_chunks_to_documents(
            output.result.chunks,
            max_chunk_size=getattr(settings, "max_chunk_size", 0) or 0,
            resource_lookup=lambda sheet, image_ids: resource_ids_for(image_plan, sheet, image_ids),
            resource_ids_by_index=image_links.by_chunk if image_links else None,
            keep_indexes=image_links.keep_image_chunks if image_links else (),
        )
        context.data["excel_image_plan"] = image_plan
        context.data["excel_flow_graphs"] = flow_graph_rows(output.result.ir)
        context.data["doc_key"] = output.doc_key
        if not chunks:
            raise ValueError("엑셀에서 적재할 내용을 찾지 못했습니다. 시트 내용을 확인해 주세요.")
        summary = output.summary()
        if image_links:
            summary["image_links"] = image_links.summary
        context.data["parse_result"] = {
            "chunks": chunks,
            "doc_type": "spreadsheet",
            "requested_doc_type": request.get("document_type", "auto"),
            "doc_type_source": EXCEL_ENGINE,
            "detection_details": None,
            "is_law": False,
            "is_manual": False,
            "total_pages": summary["sheet_count"],
            "chunk_count": len(chunks),
        }
        context.data["processing_engine"] = EXCEL_ENGINE
        context.data["excel_ingest"] = summary
        context.data["parse_job_ids"] = []
        context.data["resource_transfer_completed"] = True


class EmbedStep:
    name = "embed"

    async def run(self, service, context: IngestContext) -> None:
        chunks = context.data["parse_result"]["chunks"]
        embeddings, sparse, kiwi = await asyncio.gather(
            service._embed(chunks),
            service._encode_sparse(chunks),
            asyncio.to_thread(service._encode_kiwi_bm25, chunks),
        )
        enrich = context.request.get("enable_enrichment")
        if enrich is None:
            enrich = service.settings.enable_semantic_enrichment
        semantic = await service._enrich([c.page_content for c in chunks]) if enrich else None
        context.data.update(
            embeddings=embeddings,
            sparse_vectors=sparse,
            kiwi_bm25_documents=kiwi,
            semantic_results=semantic,
        )


class IndexStep:
    name = "index"

    async def run(self, service, context: IngestContext) -> None:
        request = context.request
        data = context.data
        parse_result = data["parse_result"]
        chunks = parse_result["chunks"]
        config = data["collection_config"]
        title = extract_doc_title(chunks[0].page_content, parse_result["doc_type"]) if chunks else ""
        file_format = detect_file_format(request["file_path"])
        # 2026.10.16 추가 - Phase 2(P2-7): 청크 식별자·결정적 포인트 ID(uuid5) — 재시도해도 같은 포인트
        # 2026.10.19 수정 - 최신본 변경이면 다음 버전 번호(포인트 ID·payload version_no가 버전별로 다름)
        version_no = _version_of(request)
        new_version = _is_new_version(request)
        assign_chunk_identity(chunks, context.document_id, version_no)
        points = service._build_points(
            chunks=chunks,
            embeddings=data["embeddings"],
            semantic_results=data["semantic_results"],
            document_id=context.document_id,
            source_path=data["stored_path"],
            filename=request["filename"],
            collection_name=config.qdrant_name,
            parse_result=parse_result,
            doc_title=title,
            file_fmt=file_format,
            kiwi_bm25_documents=data["kiwi_bm25_documents"],
            security_level=request.get("security_level", "public"),
            sparse_vectors=data["sparse_vectors"],
        )
        await asyncio.to_thread(
            service._store_vector, config.qdrant_name, len(data["embeddings"][0]), points
        )
        data["vector_stored"] = True
        db = getattr(service, "db", None) or get_database_manager()
        record_repo = getattr(service, "record_repo", None) or IngestRecordRepository(db)
        if new_version:
            # 2026.10.19 추가 - 검증: 새 버전 포인트가 모두 저장됐는지 확인한 뒤 ready(전환 대기)
            stored = await asyncio.to_thread(
                service.vector_repo.count_document_version_points, context.document_id, version_no, config.qdrant_name
            )
            if stored != len(points):
                raise RuntimeError(f"새 버전 검색 데이터 검증 실패: 저장 {stored}건 / 청크 {len(points)}건")
            await asyncio.to_thread(
                record_repo.set_version_status, context.document_id, version_no, "ready",
                from_statuses=("building", "ready"),
            )
        service._chunk_writer.write(
            filename=request["filename"],
            document_id=context.document_id,
            doc_type=parse_result["doc_type"],
            collection_name=config.qdrant_name,
            total_pages=parse_result["total_pages"],
            points=points,
        )
        resource_service = _resource_service(service)
        processing_engine = data.get("processing_engine") or "docling"
        parser_type = data.get("processing_engine") or request.get("parser_type", "docling")
        version_fields = dict(
            processing_engine=processing_engine,
            file_sha256=data.get("file_sha256"),
            original_filename=request["filename"],
            stored_filename=data["stored_filename"],
            source_path=data["stored_path"],
            file_size=data["file_size"],
            file_format=file_format,
            parser_type=parser_type,
            total_pages=parse_result.get("total_pages"),
            chunk_count=len(chunks),
            md_dir=(data.get("excel_ingest") or {}).get("md_dir"),
            summary_json=data.get("excel_ingest") or {},
        )
        # 2026.10.16 수정 - Phase 2: 문서 행·리소스 확정·버전·청크·사진·흐름도를 한 트랜잭션으로 기록(P2-6~P2-13).
        #   실패하면 DB는 함께 롤백되고, 파이프라인 보상 단계가 Qdrant 포인트·리소스 파일을 지운다.
        with db.get_connection():
            if new_version:
                # 2026.10.19 추가 - 최신본 전환: 이전 active → retired, 새 버전 → active, 문서 행 표시 정보·version_no 갱신
                #   (모델명·doc_key·업로더·대화 주제는 유지). 이 트랜잭션이 실패하면 기존 최신본이 그대로 남는다.
                record_repo.activate_version(
                    context.document_id, version_no, **version_fields,
                    doc_type=parse_result.get("doc_type"),
                    requested_doc_type=parse_result.get("requested_doc_type", "auto"),
                    doc_type_source=parse_result.get("doc_type_source"),
                    title=title,
                )
            else:
                self._store_new_document(service, request, data, context, config, parse_result, title, file_format)
            self._commit_resources(service, resource_service, record_repo, data, context, new_version)
            if not new_version:
                record_repo.create_active_version(
                    context.document_id,
                    INITIAL_VERSION,
                    **version_fields,
                    job_id=request.get("job_id"),
                    uploaded_by=request.get("uploaded_by"),
                )
            record_repo.insert_chunks(chunk_rows(chunks, context.document_id, version_no, config.collection_id))
            record_repo.insert_chunk_resources(chunk_resource_links(chunks))
            record_repo.insert_flow_graphs(context.document_id, version_no, data.get("excel_flow_graphs") or [])
        data["activated"] = True
        if new_version:
            # 2026.10.19 추가 - 전환 후 이전 버전 포인트 정리(실패해도 검색 제외 조건이 가리고, 주기 작업이 다시 시도)
            purged = await asyncio.to_thread(
                service.vector_repo.delete_document_version_points,
                context.document_id, config.qdrant_name, keep_version_no=version_no,
            )
            if purged:
                await asyncio.to_thread(record_repo.mark_inactive_versions_purged, context.document_id)
        data["result"] = service._build_response(
            context.document_id, request["filename"], parse_result, request["collection_name"]
        )
        # 2026.10.16 추가 - Phase 1: 처리기·확인용 md 위치를 작업 결과(tb_ingest_jobs.result_json)에 남긴다
        data["result"]["processing_engine"] = data.get("processing_engine") or "docling"
        # 2026.10.19 추가 - 적용된 버전(최신본 변경 결과 표시)
        data["result"]["version_no"] = version_no
        if data.get("excel_ingest"):
            data["result"]["excel_ingest"] = data["excel_ingest"]

    @staticmethod
    def _store_new_document(service, request, data, context, config, parse_result, title, file_format) -> None:
        """새 문서(v1): 문서 행 INSERT + doc_key·모델명."""
        service._save_history(
            document_id=context.document_id,
            source_path=data["stored_path"],
            filename=request["filename"],
            stored_filename=data["stored_filename"],
            file_size=data["file_size"],
            uploaded_by=request.get("uploaded_by", ""),
            collection_id=config.collection_id,
            parse_result=parse_result,
            doc_title=title,
            file_fmt=file_format,
            # 2026.10.16 수정 - Phase 1: excel_ingest로 처리한 문서는 처리기 이름을 기록(파서 선택 무시, D-16)
            parser_type=data.get("processing_engine") or request.get("parser_type", "docling"),
            security_level=request.get("security_level", "public"),
        )
        _record_repo(service).update_document_info(
            context.document_id,
            doc_key=data.get("doc_key") or doc_key_for(request["filename"]),
            product_model=request.get("product_model"),
        )

    @staticmethod
    def _commit_resources(service, resource_service, record_repo, data, context, new_version: bool) -> None:
        """파서 staging 리소스 확정·엑셀 사진 저장. 최신본 변경이면 이 버전 리소스 ID를 기록(실패 시 이것만 삭제)."""
        if not resource_service:
            return
        new_resource_ids = data.setdefault("new_resource_ids", [])
        # 2026.08.27(sooyeon.choi) 추가 - ingest 성공 후 parser staging resource commit
        for parse_job_id in data.get("parse_job_ids") or []:
            data["resource_commit_started"] = True
            if new_version:
                new_resource_ids.extend(
                    item["resource_id"] for item in resource_service.repository.list_by_parse_job(parse_job_id)
                )
            resource_service.commit_parse_job(parse_job_id, context.document_id)
        image_plan = data.get("excel_image_plan")
        if image_plan and image_plan.rows:
            data["resource_commit_started"] = True  # 실패 시 보상 단계가 리소스 파일을 지운다
            if new_version:
                new_resource_ids.extend(row["resource_id"] for row in image_plan.rows)
            write_excel_images(image_plan, resource_service)
            record_repo.insert_resources(image_plan.rows)



class IngestPipeline:
    steps = (ParseStep(), ChunkStep(), EmbedStep(), IndexStep())

    async def run(
        self,
        service,
        request: Dict[str, Any],
        *,
        checkpoint_path: Optional[str] = None,
        resume_from: Optional[str] = None,
        progress_callback=None,
    ) -> Dict[str, Any]:
        # 2026.10.19 수정 - 최신본 변경은 기존 document_id를 그대로 쓴다
        if resume_from:
            context = self._load(checkpoint_path)
        elif _is_new_version(request):
            context = IngestContext(request=request, document_id=request["target_document_id"])
        else:
            context = IngestContext(request=request)
        start = next((i for i, step in enumerate(self.steps) if step.name == resume_from), 0)
        try:
            for step in self.steps[start:]:
                log_step = _LOG_STEP_NAMES[step.name]
                started = time.perf_counter()
                logger.info(
                    "event=ingest_step step=%s status=started document_id=%s",
                    log_step,
                    context.document_id,
                )
                if progress_callback:
                    await progress_callback(step.name)
                await step.run(service, context)
                self._save(checkpoint_path, context)
                logger.info(
                    "event=ingest_step step=%s status=completed document_id=%s "
                    "parse_job_ids=%s elapsed_ms=%s",
                    log_step,
                    context.document_id,
                    ",".join(context.data.get("parse_job_ids") or []),
                    int((time.perf_counter() - started) * 1000),
                )
            self._remove_checkpoint(checkpoint_path)
            return context.data["result"]
        except Exception:
            data = context.data
            # 2026.10.19 추가 - 최신본 변경 실패는 이 버전만 정리(기존 최신본의 포인트·리소스·문서 행은 그대로)
            if _is_new_version(context.request):
                self._compensate_new_version(service, context)
                self._save(checkpoint_path, context)
                raise
            resource_service = _resource_service(service)
            compensation_status = "not_required"
            if resource_service:
                if not data.get("resource_transfer_completed"):
                    compensation_status = "rolled_back"
                    for parse_job_id in data.get("parse_job_ids") or []:
                        resource_service.rollback_parse_job(parse_job_id)
                elif data.get("resource_commit_started"):
                    compensation_status = "rolled_back"
                    for parse_job_id in data.get("parse_job_ids") or []:
                        resource_service.rollback_parse_job(parse_job_id)
                    resource_service.delete_document_resources(context.document_id)
                else:
                    compensation_status = "preserved_for_retry"
            if data.get("vector_stored"):
                config = data.get("collection_config")
                service.vector_repo.delete_by_document_id(context.document_id, config.qdrant_name)
                data["vector_stored"] = False
            self._save(checkpoint_path, context)
            logger.exception(
                "event=ingest_step step=compensation status=%s document_id=%s "
                "parse_job_ids=%s",
                compensation_status,
                context.document_id,
                ",".join(data.get("parse_job_ids") or []),
            )
            raise

    # 2026.10.19 추가 - 최신본 변경 실패: 이 버전의 포인트·리소스만 지우고 failed로 처리.
    @staticmethod
    def _compensate_new_version(service, context: IngestContext) -> None:
        data, request = context.data, context.request
        document_id, version_no = context.document_id, _version_of(request)
        if data.get("activated"):
            return  # 전환 이후 단계의 실패는 되돌리지 않는다(새 버전이 이미 최신본)
        resource_service = _resource_service(service)
        if resource_service:
            for parse_job_id in data.get("parse_job_ids") or []:
                resource_service.rollback_parse_job(parse_job_id)
            for resource_id in data.get("new_resource_ids") or []:
                shutil.rmtree(
                    resource_service.resolve_relative_path(f"documents/{document_id}/resources/{resource_id}"),
                    ignore_errors=True,
                )
            data["new_resource_ids"] = []
        purged = True
        if data.get("vector_stored"):
            config = data.get("collection_config")
            purged = service.vector_repo.delete_document_version_points(
                document_id, config.qdrant_name, version_no=version_no
            )
            data["vector_stored"] = not purged
        try:
            repo = _record_repo(service)
            repo.set_version_status(document_id, version_no, "failed", vectors_purged=purged)
            if data.get("stored_path"):
                repo.set_version_source(document_id, version_no, data["stored_path"], data.get("stored_filename"))
        except Exception:
            logger.exception("event=version_replace status=mark_failed_error document_id=%s", document_id)
        logger.error(
            "event=version_replace status=failed document_id=%s version_no=%s vectors_purged=%s",
            document_id, version_no, purged,
        )

    @staticmethod
    def _save(path: Optional[str], context: IngestContext) -> None:
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as handle:
                pickle.dump(context, handle)

    @staticmethod
    def _load(path: Optional[str]) -> IngestContext:
        if not path or not os.path.exists(path):
            raise ValueError("재시도 체크포인트를 찾을 수 없습니다.")
        with open(path, "rb") as handle:
            return pickle.load(handle)

    @staticmethod
    def _remove_checkpoint(path: Optional[str]) -> None:
        if path:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
