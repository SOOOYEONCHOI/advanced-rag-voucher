"""
문서 수집(Ingest) 파이프라인 서비스.

문서 업로드 → 파싱/청킹 → 임베딩 → Qdrant 저장 → SQLite 이력 저장
업로드 요청 청크 설정을 ChunkingConfig로 변환하여 DocumentChunkingProcessor에 전달
"""

import asyncio
import shutil
import time
# 2026.04.21(sooyeon.choi) 추가 - run_in_executor용 partial 임포트
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

from qdrant_client.models import PointStruct

from app.clients.embedding_client import EmbeddingClient
from app.clients.kiwi_bm25_encoder import KiwiBm25Encoder
# 2026.04.20(sooyeon.choi) 옵션 추가 - sparse encoder 임포트
from app.clients.sparse_encoder import SparseEncoder
from app.core.config import get_settings
from app.parsers.config import ChunkingConfig
from app.parsers.metadata_extractor import build_unified_payload
from app.parsers.document_types import DocumentTypeMismatchError
from app.parsers.processor import DocumentChunkingProcessor
from app.parsers.semantic_enricher import SemanticEnricher
# 2026.04.01(sooyeon.choi) 수정 - 멀티컬렉션 관리 기능 추가
from app.repositories.collection_repository import CollectionRepository
# 2026.04.02(sooyeon.choi) - 문서 삭제 기능 추가
from app.repositories.vector_repository import VectorRepository
# 2026.04.10(sooyeon.choi) 추가 - SQLite 연결 일원화: 직접 sqlite3.connect 대신 DatabaseManager 사용
from app.repositories.database import get_database_manager
# 2026.06.16(sooyeon.choi) 수정 - tb_ingest_documents → DocumentRepository
from app.repositories.document_repository import DocumentRepository
from app.models.data_models import DocumentMetadata, DocumentEvent, DocumentEventType, DocumentStatus
from app.repositories.spreadsheet_resource_repository import SpreadsheetResourceRepository
from app.services.spreadsheet_resource_service import SpreadsheetResourceService

from app.utils.log.log import LoggingLogger
from app.utils.datetime import now_kst, now_kst_iso

# 로거 초기화
# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용 (B16)
logger = LoggingLogger().getLogger(__name__)

# 2026.06.16(sooyeon.choi) 수정 - _INGEST_TABLE 상수 제거 (tb_ingest_documents → tb_documents 전환)
_BATCH_SIZE = 100
# 2026.05.04(sooyeon.choi) 수정 - 청크 결과 저장 경로를 instance/chunk 로 변경,
#   컬렉션별/문서별 하위 폴더 구조로 저장
_CHUNK_OUTPUT_DIR_NAME = "chunk"
_FILE_STORAGE_DIR_NAME = "data"


# 2026.04.10(sooyeon.choi) 추가 - 청크 결과 파일 저장 책임 분리
class ChunkResultWriter:
    """청크 결과를 Markdown 파일로 기록하는 헬퍼.

    저장 구조:
      {output_dir}/{collection_name}/{document_id}/{safe_filename}_chunks.md
    """

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def write(
        self,
        filename: str,
        document_id: str,
        doc_type: str,
        collection_name: str,
        total_pages: int,
        points: List[PointStruct],
    ) -> None:
        """청크 결과를 Markdown 파일로 저장한다. 실패 시 WARNING 로그만 출력."""
        try:
            # 2026.05.04(sooyeon.choi) 수정 - 컬렉션/문서 하위 폴더 구조로 저장
            safe_name = Path(filename).stem.replace(" ", "_")
            chunk_dir = self.output_dir / collection_name / document_id
            chunk_dir.mkdir(parents=True, exist_ok=True)
            chunk_file = chunk_dir / f"{safe_name}_chunks.md"
            with open(chunk_file, "w", encoding="utf-8") as f:
                f.write(f"# 청크 결과: {filename}\n\n")
                f.write(f"- Document ID: `{document_id}`\n")
                f.write(f"- 문서 유형: {doc_type}\n")
                f.write(f"- 컬렉션: {collection_name}\n")
                f.write(f"- 총 페이지: {total_pages}\n")
                f.write(f"- 총 청크 수: {len(points)}\n")
                f.write(f"- 생성 시각: {now_kst_iso()}\n\n---\n\n")
                for idx, point in enumerate(points):
                    p = point.payload
                    f.write(f"## Chunk {idx} (ID: {p.get('chunk_id', '')[:8]}...)\n\n")

                    # ── Document 메타데이터 ──
                    f.write("### Document 메타데이터\n\n| 필드 | 값 |\n|---|---|\n")
                    for field in (
                        "document_id", "original_filename", "source_collection",
                        "document_type", "title", "security_level", "file_format",
                        "created_at", "updated_at", "version", "source_path",
                    ):
                        val = p.get(field)
                        if val is not None:
                            f.write(f"| {field} | {val} |\n")
                    f.write("\n")

                    # ── Chunk 메타데이터 ──
                    f.write("### Chunk 메타데이터\n\n| 필드 | 값 |\n|---|---|\n")
                    for field in (
                        "chunk_id", "chunk_index", "page_number", "content_type",
                        "section_title", "char_start_offset", "char_end_offset",
                    ):
                        val = p.get(field)
                        if val is not None:
                            f.write(f"| {field} | {val} |\n")
                    header_path = p.get("header_path")
                    if header_path:
                        f.write(f"| header_path | {' > '.join(header_path)} |\n")
                    f.write("\n")

                    # ── Semantic 메타데이터 ──
                    f.write("### Semantic 메타데이터\n\n| 필드 | 값 |\n|---|---|\n")
                    for field in ("intent", "summary"):
                        val = p.get(field)
                        if val is not None:
                            f.write(f"| {field} | {val} |\n")
                    keywords = p.get("keywords")
                    if keywords:
                        f.write(f"| keywords | {', '.join(keywords)} |\n")
                    topics = p.get("topics")
                    if topics:
                        f.write(f"| topics | {', '.join(topics)} |\n")
                    f.write("\n")

                    # ── 텍스트 본문 ──
                    f.write("### Text 본문\n\n")
                    f.write(f"```\n{p.get('text', '')}\n```\n\n---\n\n")
            logger.info(f"[Ingest] 청크 결과 저장: {chunk_file}")
        except Exception as e:
            logger.warning(f"[Ingest] 청크 결과 파일 저장 실패 (무시): {e}")

    # 2026.05.04(sooyeon.choi) 수정 - collection_name 파라미터 추가 (폴더 구조 변경 대응)
    def delete(self, filename: str, document_id: str, collection_name: str = "") -> None:
        """청크 결과 디렉토리를 삭제한다. 실패 시 WARNING 로그만 출력."""
        try:
            import shutil
            chunk_dir = self.output_dir / collection_name / document_id
            if chunk_dir.exists():
                shutil.rmtree(chunk_dir)
                logger.info(f"[Ingest] 청크 결과 디렉토리 삭제: {chunk_dir}")
        except Exception as e:
            logger.warning(f"[Ingest] 청크 결과 디렉토리 삭제 실패 (무시): {e}")


class FileStorageManager:
    """업로드된 원본 파일을 영구 저장/삭제하는 헬퍼."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir.resolve()
        self._adrag_root = self.base_dir.parent.parent

    async def save(
        self, src_path: str, original_filename: str, document_id: str, version_no: int = 1
    ) -> Tuple[str, str, int]:
        """원본 파일을 영구 경로에 복사하고 (stored_filename, source_path, file_size)를 반환한다."""
        ext = Path(original_filename).suffix.lower()
        now = now_kst()
        # 2026.10.19 수정 - 최신본 변경(v2 이상)은 같은 날 이전 버전 원본을 덮어쓰지 않도록 버전을 붙인다
        version_suffix = f"_v{version_no}" if version_no and version_no > 1 else ""
        stored_filename = f"{now.strftime('%Y%m%d')}_{document_id}{version_suffix}{ext}"

        dest_dir = self.base_dir / str(now.year) / f"{now.month:02d}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / stored_filename

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, shutil.copy2, src_path, str(dest_path))

        file_size = dest_path.stat().st_size
        # 2026.10.30(sooyeon.choi) 수정 - Windows 로컬 등록에서도 '/' 구분자로 기록(운영 Linux 컨테이너에서 풀 수 있게)
        relative_path = dest_path.relative_to(self._adrag_root).as_posix()
        return stored_filename, relative_path, file_size

    # 2026.10.30(sooyeon.choi) 추가 - DB의 source_path를 실제 파일 경로로 바꾼다(저장·삭제·원본 열기 공통).
    #   운영은 소스(/app)와 데이터(/data)가 따로 마운트되므로 백엔드 소스 폴더가 아니라 저장 폴더 기준으로 푼다.
    def resolve(self, source_path: str) -> Path:
        """source_path를 절대 경로로 바꾼다. 저장 폴더 밖이면 ValueError."""
        path = (self._adrag_root / source_path).resolve()
        path.relative_to(self.base_dir)
        return path

    def delete(self, source_path: str) -> None:
        """저장된 파일을 삭제한다. 실패 시 WARNING 로그만 출력."""
        try:
            # 2026.10.30(sooyeon.choi) 수정 - resolve()로 경로 계산 통일(저장 폴더 밖이면 삭제하지 않음)
            path = self.resolve(source_path)
            if path.exists():
                path.unlink()
                logger.info(f"[Ingest] 저장 파일 삭제: {path}")
                for parent in (path.parent, path.parent.parent):
                    if parent.exists() and not any(parent.iterdir()):
                        parent.rmdir()
        except Exception as e:
            logger.warning(f"[Ingest] 저장 파일 삭제 실패 (무시): {e}")


# 2026.10.30(sooyeon.choi) 추가 - 원본 파일 저장소를 한 곳에서 만든다(등록·원본 열기 API가 같은 기준을 쓰도록)
def get_original_file_storage(settings) -> FileStorageManager:
    instance_dir = Path(settings.sqlite_db_path).parent.parent
    return FileStorageManager(instance_dir / _FILE_STORAGE_DIR_NAME)


class IngestService:
    """
    문서 수집 파이프라인 오케스트레이터.

    파서(parsers) + 임베딩 클라이언트(clients) + 벡터 저장소(repositories)를
    서비스 레이어에서 조립합니다.
    """

    # 2026.04.10(sooyeon.choi) 추가 - 생성자 기반 의존성 주입
    def __init__(
        self,
        collection_repo: Optional[CollectionRepository] = None,
        vector_repo: Optional[VectorRepository] = None,
    ) -> None:
        self.settings = get_settings()
        self.embedding_client = EmbeddingClient(self.settings)
        # 2026.07.07(sooyeon.choi) 수정 - 적재 시 Kiwi BM25 sparse vector를 사전 생성
        self.kiwi_bm25_encoder = KiwiBm25Encoder(self.settings)
        # 2026.04.20(sooyeon.choi) 옵션 추가 - sparse encoder 초기화 (none이면 비활성)
        self.sparse_encoder = SparseEncoder(self.settings)
        self.db = get_database_manager(self.settings.sqlite_db_path)
        # 2026.06.16(sooyeon.choi) 추가 - DocumentRepository 초기화
        self.doc_repo = DocumentRepository(self.settings.sqlite_db_path)
        self.collection_repo = collection_repo or CollectionRepository()
        self.vector_repo = vector_repo or VectorRepository(
            host=self.settings.qdrant_host,
            port=self.settings.qdrant_port,
            sparse_encoder_type=self.settings.sparse_encoder_type,
            kiwi_bm25_vector_name=self.settings.kiwi_bm25_vector_name,
        )
        _instance_dir = Path(self.settings.sqlite_db_path).parent.parent
        self._chunk_writer = ChunkResultWriter(_instance_dir / _CHUNK_OUTPUT_DIR_NAME)
        # 2026.10.30(sooyeon.choi) 수정 - 저장소 생성을 get_original_file_storage()로 통일
        self._file_manager = get_original_file_storage(self.settings)
        # 2026.08.27(sooyeon.choi) 추가 - parser resource staging/commit/delete 연결
        resource_root = Path(self.settings.resource_storage_root)
        if not resource_root.is_absolute():
            resource_root = Path(__file__).resolve().parents[2] / resource_root
        self.resource_service = SpreadsheetResourceService(
            root=resource_root,
            repository=SpreadsheetResourceRepository(db=self.db),
            max_upload_bytes=self.settings.resource_max_upload_bytes,
        )

    # ── 유효성 검증 ────────────────────────────────────────────────────────

    # 2026.06.16(sooyeon.choi) 수정 - CollectionConfig 반환으로 변경 (collection_id 포함)
    def _validate_collection(self, collection_name: str):
        """등록된 컬렉션인지 검증 후 CollectionConfig를 반환한다.

        qdrant_name 또는 display_name 모두 허용한다.
        미등록 시 ValueError를 발생시킨다.
        """
        col = self.collection_repo.get_by_qdrant_name(collection_name)
        if col:
            return col
        # 2026.06.16(sooyeon.choi) 수정 - get_by_name → get_by_display_name
        col = self.collection_repo.get_by_display_name(collection_name)
        if col:
            return col
        raise ValueError("등록되지 않은 컬렉션입니다")

    # ── 파싱 + 청킹 ───────────────────────────────────────────────────────

    def _parse_and_chunk(
        self,
        file_path: str,
        filename: str,
        parser_type: str,
        chunk_size: Optional[int],
        document_id: Optional[str] = None,
        requested_doc_type: str = "auto",
    ) -> Dict[str, Any]:
        """문서를 파싱하고 청킹한다. 결과가 없으면 ValueError를 발생시킨다."""
        config_kwargs: Dict[str, Any] = {
            "parser_type": parser_type,
            "requested_doc_type": requested_doc_type,
        }
        if chunk_size:
            config_kwargs["general_chunk_size"] = chunk_size
            config_kwargs["law_chunk_size"] = chunk_size
            config_kwargs["manual_chunk_size"] = chunk_size

        processor = DocumentChunkingProcessor(ChunkingConfig(**config_kwargs))
        parse_start = time.perf_counter()
        logger.info("[PARSE][step=process] 시작 filename=%s parser=%s", filename, parser_type)
        # logger.info(f"[ingest] 파싱 시작: {filename} (parser={parser_type})")
        parse_result = processor.process(file_path, document_id=document_id)

        if not parse_result["chunks"]:
            if requested_doc_type != "auto":
                raise DocumentTypeMismatchError(
                    f"선택한 문서 유형 '{requested_doc_type}'로 청크를 생성하지 못했습니다. "
                    "문서 유형을 확인하거나 '자동'을 선택해 주세요."
                )
            raise ValueError("청킹 결과가 없습니다. 문서 내용을 확인해주세요.")

        logger.info(
            "[PARSE][step=process] 완료 filename=%s pages=%s chunks=%s doc_type=%s elapsed=%.2fs",
            filename,
            parse_result.get("total_pages"),
            len(parse_result["chunks"]),
            parse_result.get("doc_type"),
            time.perf_counter() - parse_start,
        )
        # logger.info(f"[ingest] 청킹 완료: {len(parse_result['chunks'])}개")
        return parse_result

    # ── 임베딩 ────────────────────────────────────────────────────────────

    async def _embed(self, chunks: list) -> List[List[float]]:
        """청크 텍스트를 임베딩한다. 결과 정합성 검증 포함."""
        texts = [c.page_content for c in chunks]
        embed_start = time.perf_counter()
        logger.info(
            "[INGEST][step=embedding] 시작 chunks=%s total_chars=%s max_chars=%s",
            len(texts),
            sum(len(text) for text in texts),
            max((len(text) for text in texts), default=0),
        )
        # logger.info(f"[ingest] 임베딩 요청: {len(texts)}개 청크")
        embeddings = await self.embedding_client.embed_texts(texts)

        if not embeddings:
            raise RuntimeError("임베딩 결과가 비어 있습니다.")
        if len(embeddings) != len(chunks):
            raise RuntimeError(
                f"임베딩 수({len(embeddings)})와 청크 수({len(chunks)})가 일치하지 않습니다."
            )

        logger.info(
            "[INGEST][step=embedding] 완료 chunks=%s dim=%s elapsed=%.2fs",
            len(embeddings),
            len(embeddings[0]),
            time.perf_counter() - embed_start,
        )
        # logger.info(f"[ingest] 임베딩 완료 (dim={len(embeddings[0])})")
        return embeddings

    # ── Sparse 인코딩 ─────────────────────────────────────────────────────

    # 2026.04.20(sooyeon.choi) 옵션 추가 - sparse vector 생성 (none이면 None 반환)
    async def _encode_sparse(self, chunks: list) -> Optional[list]:
        """sparse_encoder_type 설정에 따라 sparse vector를 생성한다."""
        if not self.sparse_encoder.is_enabled:
            return None
        texts = [c.page_content for c in chunks]
        try:
            sparse_start = time.perf_counter()
            logger.info(
                "[INGEST][step=sparse_encoding] 시작 chunks=%s encoder=%s",
                len(texts),
                self.settings.sparse_encoder_type,
            )
            # logger.info(f"[ingest] sparse 인코딩 시작: {len(texts)}개 청크 ({self.settings.sparse_encoder_type})")
            result = await self.sparse_encoder.encode_batch(texts)
            logger.info(
                "[INGEST][step=sparse_encoding] 완료 chunks=%s elapsed=%.2fs",
                len(texts),
                time.perf_counter() - sparse_start,
            )
            # logger.info("[ingest] sparse 인코딩 완료")
            return result
        except Exception as e:
            logger.warning(f"[Ingest] sparse 인코딩 실패, 건너뜀: {e}")
            return None

    def _encode_kiwi_bm25(self, chunks: list) -> list:
        """각 청크를 Qdrant BM25 document 입력으로 변환한다."""
        # 2026.07.07(sooyeon.choi) 수정 - 검색 시 문서 재토큰화 방지
        return [
            self.kiwi_bm25_encoder.encode_document(chunk.page_content)
            for chunk in chunks
        ]

    # ── 시맨틱 보강 ───────────────────────────────────────────────────────

    async def _enrich(self, texts: List[str]) -> Optional[list]:
        """LLM 기반 시맨틱 보강을 수행한다. 실패 시 None 반환."""
        try:
            enricher = SemanticEnricher(
                vllm_api_url=self.settings.vllm_api_url,
                model_name=self.settings.vllm_model_name,
                api_key=self.settings.vllm_api_key,
            )
            logger.info("[INGEST][step=semantic_enrichment] 시작 chunks=%s", len(texts))
            # logger.info(f"[ingest] 시맨틱 보강 시작: {len(texts)}개 청크")
            _t0 = time.perf_counter()
            results = await enricher.extract_batch(texts)
            _elapsed = time.perf_counter() - _t0
            logger.info(
                "[INGEST][step=semantic_enrichment] 완료 chunks=%s elapsed=%.2fs avg=%.2fs",
                len(texts),
                _elapsed,
                _elapsed / len(texts),
            )
            return results
        except Exception as e:
            logger.warning(f"[Ingest] 시맨틱 보강 실패 (건너뜀): {e}")
            return None

    # ── 벡터 적재 ─────────────────────────────────────────────────────────

    def _build_points(
        self,
        chunks: list,
        embeddings: List[List[float]],
        semantic_results: Optional[list],
        document_id: str,
        source_path: str,
        filename: str,
        collection_name: str,
        parse_result: Dict[str, Any],
        doc_title: str,
        file_fmt: str,
        kiwi_bm25_documents: list,
        security_level: str,
        sparse_vectors: Optional[list] = None,
    ) -> List[PointStruct]:
        """청크·임베딩·시맨틱 결과로 Qdrant PointStruct 목록을 생성한다."""
        from qdrant_client.models import SparseVector as QdrantSparseVector
        points: List[PointStruct] = []
        if len(kiwi_bm25_documents) != len(chunks):
            raise RuntimeError(
                f"Kiwi BM25 벡터 수({len(kiwi_bm25_documents)})와 "
                f"청크 수({len(chunks)})가 일치하지 않습니다."
            )
        if sparse_vectors is not None and len(sparse_vectors) != len(chunks):
            raise RuntimeError(
                f"Sparse 벡터 수({len(sparse_vectors)})와 청크 수({len(chunks)})가 일치하지 않습니다."
            )

        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            meta = chunk.metadata or {}
            # 2026.10.16 수정 - Phase 2(P2-7): 파이프라인이 정한 결정적 포인트 ID(uuid5) 사용, 없으면 기존처럼 uuid4
            chunk_id = str(meta.get("point_id") or uuid4())
            payload = build_unified_payload(
                document_id=document_id,
                chunk_id=chunk_id,
                chunk_index=i,
                chunk_text=chunk.page_content,
                chunk_meta=meta,
                source_path=source_path,
                original_filename=filename,
                source_collection=collection_name,
                document_type=parse_result["doc_type"],
                title=doc_title,
                file_format=file_fmt,
                # 2026.07.07(sooyeon.choi) 수정 - Qdrant payload 보안등급 누락 보정
                security_level=security_level,
                requested_document_type=parse_result.get("requested_doc_type", "auto"),
                document_type_source=parse_result.get("doc_type_source"),
            )
            # 2026.10.16 추가 - Phase 2(P2-2): 버전·포인트 종류·버전 무관 키(검색 필터·개정 전환·재매핑용)
            payload["version_no"] = meta.get("version_no", 1)
            # 2026.11.06(sooyeon.choi) 수정 - 버전 제외 필터용 고정 키 "document_id:version_no"(설계 v1.1 7.3 C안).
            #   버전마다 값이 고정이라 최신본 전환·복원 때 Qdrant를 다시 쓰지 않는다
            payload["doc_version"] = f"{document_id}:{int(payload['version_no'])}"
            payload["point_type"] = "text"
            if meta.get("source_key"):
                payload["source_key"] = meta["source_key"]
            payload["kiwi_text"] = self.kiwi_bm25_encoder.normalize_document(chunk.page_content)
            payload["bm25_encoder_version"] = self.kiwi_bm25_encoder.version
            if semantic_results and i < len(semantic_results):
                semantic_results[i].merge_into_payload(payload)

            # 2026.07.07(sooyeon.choi) 수정 - Dense와 Kiwi BM25를 항상 함께 적재
            vector = {
                "dense": embedding,
                self.settings.kiwi_bm25_vector_name: kiwi_bm25_documents[i],
            }
            if sparse_vectors:
                sv = sparse_vectors[i]
                vector["sparse"] = QdrantSparseVector(
                    indices=sv.indices,
                    values=sv.values,
                )

            points.append(PointStruct(id=chunk_id, vector=vector, payload=payload))
        return points

    def _store_vector(
        self,
        collection_name: str,
        vector_size: int,
        points: List[PointStruct],
    ) -> None:
        """컬렉션 보장 후 포인트를 VectorRepository를 통해 Qdrant에 upsert한다."""
        store_start = time.perf_counter()
        logger.info(
            "[INGEST][step=vector_store] 시작 collection=%s points=%s vector_size=%s",
            collection_name,
            len(points),
            vector_size,
        )
        self.vector_repo.ensure_collection(collection_name, vector_size)
        self.vector_repo.upsert_points(collection_name, points, batch_size=_BATCH_SIZE)
        logger.info(
            "[INGEST][step=vector_store] 완료 collection=%s points=%s elapsed=%.2fs",
            collection_name,
            len(points),
            time.perf_counter() - store_start,
        )
        # logger.info(f"[ingest] Qdrant 적재 완료: {len(points)}개 → '{collection_name}'")

    # ── 이력 저장 ─────────────────────────────────────────────────────────

    # 2026.06.16(sooyeon.choi) 수정 - tb_ingest_documents INSERT → DocumentRepository.store()
    def _save_history(
        self,
        document_id: str,
        source_path: str,
        filename: str,
        stored_filename: str,
        file_size: int,
        uploaded_by: str,
        collection_id: int,
        parse_result: Dict[str, Any],
        doc_title: str,
        file_fmt: str,
        parser_type: str,
        security_level: str = "public",
    ) -> None:
        """수집 이력을 tb_documents에 저장한다."""
        self.doc_repo.store(
            DocumentMetadata(
                document_id=document_id,
                collection_id=collection_id,
                source_path=source_path,
                uploaded_by=uploaded_by or None,
                original_filename=filename,
                stored_filename=stored_filename,
                file_size=file_size,
                doc_type=parse_result.get("doc_type"),
                requested_doc_type=parse_result.get("requested_doc_type", "auto"),
                doc_type_source=parse_result.get("doc_type_source"),
                title=doc_title,
                file_format=file_fmt,
                security_level=security_level,
                parser_type=parser_type,
                total_pages=parse_result.get("total_pages"),
                chunk_count=parse_result.get("chunk_count"),
                status=DocumentStatus.READY,
            )
        )

    # ── 응답 생성 ─────────────────────────────────────────────────────────

    def _build_response(
        self,
        document_id: str,
        filename: str,
        parse_result: Dict[str, Any],
        collection_name: str,
    ) -> Dict[str, Any]:
        """수집 완료 응답 딕셔너리를 생성한다."""
        return {
            "document_id":     document_id,
            "filename":        filename,
            "doc_type":        parse_result["doc_type"],
            "requested_doc_type": parse_result.get("requested_doc_type", "auto"),
            "doc_type_source": parse_result.get("doc_type_source"),
            "detection_details": parse_result.get("detection_details"),
            "is_law":          parse_result["is_law"],
            "is_manual":       parse_result["is_manual"],
            "total_pages":     parse_result["total_pages"],
            "chunk_count":     parse_result["chunk_count"],
            "collection_name": collection_name,
            "status":          "success",
        }

    # ── 메인 파이프라인 ────────────────────────────────────────────────────

    async def ingest(
        self,
        file_path: str,
        filename: str,
        collection_name: str,
        parser_type: str = "docling",
        chunk_size: Optional[int] = None,
        document_type: str = "auto",
        enable_enrichment: Optional[bool] = None,
        uploaded_by: str = "",
        security_level: str = "public",
        progress_callback: Optional[Callable[[str], Awaitable[None]]] = None,
        checkpoint_path: Optional[str] = None,
        resume_from: Optional[str] = None,
        # 2026.10.16 추가 - Phase 1: 확인용 md 폴더 이름({md_save_dir}/excel/{doc_key}/{job_id})
        job_id: Optional[str] = None,
        # 2026.10.16 추가 - Phase 2(P2-11): 제품 모델(선택)
        product_model: Optional[str] = None,
        # 2026.10.19 추가 - 최신본 변경: 기존 문서의 다음 버전으로 적재
        target_document_id: Optional[str] = None,
        version_no: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        문서 수집 전체 파이프라인 실행.

        Steps:
            1.  컬렉션 검증 (CollectionConfig 반환)
            1.5 원본 파일 영구 저장  (FileStorageManager, 롤백 대상)
            2.  파싱 + 청킹          (DocumentChunkingProcessor)
            3.  임베딩               (EmbeddingClient)
            4.  시맨틱 보강          (SemanticEnricher, LLM 기반)
            5.  Qdrant 적재          (VectorRepository)
            6.  청크 결과 파일 저장
            7.  이력 저장            (tb_documents via DocumentRepository)
        """
        from app.services.ingest_pipeline import IngestPipeline

        return await IngestPipeline().run(
            self,
            {
                "file_path": file_path,
                "filename": filename,
                "collection_name": collection_name,
                "parser_type": parser_type,
                "document_type": document_type,
                "chunk_size": chunk_size,
                "enable_enrichment": enable_enrichment,
                "uploaded_by": uploaded_by,
                "security_level": security_level,
                "job_id": job_id,
                "product_model": product_model,
                "target_document_id": target_document_id,
                "version_no": version_no,
            },
            checkpoint_path=checkpoint_path,
            resume_from=resume_from,
            progress_callback=progress_callback,
        )

    def delete_document(
        self,
        document_id: str,
        actor_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        문서 삭제: Qdrant 포인트 삭제 → tb_documents Soft Delete → 이벤트 기록.

        Qdrant 삭제를 먼저 수행하여 검색 노출을 방지한다.
        """
        # 1. tb_documents에서 문서 정보 조회
        doc = self.doc_repo.get_by_id(document_id)
        already_deleted = False
        if not doc:
            doc = self.doc_repo.get_by_id(document_id, include_deleted=True)
            if not doc:
                raise ValueError("해당 문서를 찾을 수 없습니다")
            already_deleted = True

        # 2. collection_id → qdrant_name 변환
        col = self.collection_repo.get_by_id(doc.collection_id)
        if col is None or not col.qdrant_name:
            raise RuntimeError(
                f"문서의 Qdrant 컬렉션을 찾을 수 없습니다: document_id={document_id}"
            )
        source_collection = col.qdrant_name

        # 3. 삭제 전 정확한 Qdrant 포인트 수 조회
        before_count = self.vector_repo.count_by_document_id(
            document_id=document_id,
            collection_name=source_collection,
        )

        # 4. 포인트가 있을 때만 Qdrant 삭제 후 잔여 수를 검증한다.
        if before_count > 0:
            success = self.vector_repo.delete_by_document_id(
                document_id=document_id,
                collection_name=source_collection,
            )
            if not success:
                raise RuntimeError(
                    f"Qdrant 포인트 삭제 실패: document_id={document_id}"
                )
            remaining_count = self.vector_repo.count_by_document_id(
                document_id=document_id,
                collection_name=source_collection,
            )
        else:
            remaining_count = 0

        if remaining_count != 0:
            raise RuntimeError(
                "Qdrant 문서 벡터 삭제 검증 실패: "
                f"document_id={document_id}, 잔여 포인트={remaining_count}"
            )

        deleted_vector_count = before_count - remaining_count
        reconciled = (
            (not already_deleted and before_count == 0)
            or (already_deleted and before_count > 0)
        )

        # 이미 삭제된 문서는 Qdrant 정합성만 확인하고 멱등 성공한다.
        if already_deleted:
            logger.info(
                "[Ingest] 이미 삭제된 문서 확인 완료: %s (컬렉션: %s)",
                document_id,
                source_collection,
            )
            return {
                "status": "already_deleted",
                "document_id": document_id,
                "source_collection": source_collection,
                "title": doc.title or "",
                "deleted_vector_count": deleted_vector_count,
                "remaining_vector_count": remaining_count,
                "reconciled": reconciled,
            }

        # 5. Qdrant 삭제 검증이 끝난 뒤 tb_documents를 Soft Delete한다.
        if not self.doc_repo.soft_delete(document_id):
            raise RuntimeError(
                f"SQLite 문서 삭제 상태 저장 실패: document_id={document_id}"
            )
        # 2026.10.16 추가 - Phase 2: 청크·청크↔사진·흐름도 행 삭제, 버전 행은 retired로 보존(감사)
        from app.repositories.ingest_record_repository import IngestRecordRepository

        record_repo = getattr(self, "record_repo", None) or IngestRecordRepository(
            getattr(self, "db", None) or get_database_manager()
        )
        record_repo.delete_document_chunks(document_id)
        # 2026.10.19 추가 - 최신본 변경으로 남은 이전 버전 원본 파일도 함께 지운다(아래 8단계는 현재 버전만)
        version_paths = [
            row[0] for row in self.db.execute_query(
                "SELECT DISTINCT source_path FROM tb_document_versions WHERE document_id = ? AND source_path <> ''",
                (document_id,),
            )
        ] if getattr(self, "db", None) is not None else []
        record_repo.retire_document_versions(document_id)

        # 6. 삭제 이벤트 기록
        self.doc_repo.record_event(
            DocumentEvent(
                document_id=document_id,
                event_type=DocumentEventType.DELETE,
                collection_id=doc.collection_id,
                actor_id=actor_id,
                event_message=f"delete: {doc.original_filename or ''}",
            )
        )

        # 7. 청크 결과 디렉토리 삭제
        filename = doc.original_filename or doc.title or ""
        self._chunk_writer.delete(filename, document_id, collection_name=source_collection)

        # 8. 영구 저장된 원본 파일 삭제
        if doc.source_path:
            self._file_manager.delete(doc.source_path)
        for path in version_paths:
            if path != doc.source_path:
                self._file_manager.delete(path)

        # 2026.08.27(sooyeon.choi) 추가 - 원본 문서와 연결된 resource/analysis 디렉터리 삭제
        # 2026.08.27(sooyeon.choi) 수정 - 삭제 실패는 문서 삭제를 막지 않고 재시도 대상으로 남긴다.
        resource_deletion = "skipped"
        if hasattr(self, "resource_service"):
            try:
                resource_deletion = self.resource_service.delete_document_resources(document_id)
            except Exception as e:
                resource_deletion = "pending"
                logger.error(
                    "[RESOURCE][delete] 재시도 대기 document_id=%s error=%s", document_id, e
                )

        logger.info(f"[Ingest] 문서 삭제 완료: {document_id} (컬렉션: {source_collection})")
        return {
            "status": "deleted",
            "document_id": document_id,
            "resource_deletion": resource_deletion,
            "source_collection": source_collection,
            "title": doc.title or "",
            "deleted_vector_count": deleted_vector_count,
            "remaining_vector_count": remaining_count,
            "reconciled": reconciled,
        }

    # ── 조회 ──────────────────────────────────────────────────────────────

    # 2026.06.16(sooyeon.choi) 수정 - tb_ingest_documents → tb_documents (v4 스키마)
    #   _cleanup_stale_documents(): Soft Delete 방식이므로 불필요하여 제거
    def list_documents(
        self,
        collection_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """업로드 이력 목록 조회 (tb_documents)."""
        try:
            if collection_name:
                # qdrant_name 또는 display_name → collection_id 변환
                col = self.collection_repo.get_by_qdrant_name(collection_name)
                if col is None:
                    col = self.collection_repo.get_by_display_name(collection_name)
                if col is None:
                    return []
                rows_raw = self.doc_repo.list_by_collection(col.collection_id)
                for d in rows_raw:
                    d["collection_name"] = col.display_name
                    d["source_collection"] = col.qdrant_name
                    d["upload_timestamp"] = d.get("created_at")
                return rows_raw
            else:
                # 전체 컬렉션 문서 (tb_documents JOIN tb_collections)
                # 2026.10.19 수정 - 모델명·현재 버전·최근 변경일 포함
                rows = self.db.execute_query(
                    """
                    SELECT d.document_id, d.collection_id, d.uploaded_by,
                           d.original_filename, d.doc_type, d.security_level,
                           d.status, d.total_pages, d.chunk_count,
                           d.parser_type, d.created_at,
                           d.product_model, d.version_no, d.updated_at,
                           c.qdrant_name as source_collection,
                           c.display_name as collection_display_name
                    FROM tb_documents d
                    LEFT JOIN tb_collections c ON c.collection_id = d.collection_id
                    WHERE d.deleted_at IS NULL
                    ORDER BY d.created_at DESC
                    """
                )
                results = []
                for r in rows:
                    d = dict(r)
                    d["collection_name"] = d.get("source_collection", "")
                    d["upload_timestamp"] = d.get("created_at")
                    d["filename"] = d.get("original_filename") or ""
                    results.append(d)
                return results
        except Exception as e:
            logger.error(f"[Ingest] 문서 목록 조회 실패: {e}")
            return []

    def list_collections(self) -> List[str]:
        """Qdrant 컬렉션 목록 조회."""
        try:
            return self.vector_repo.list_collections()
        except Exception as e:
            logger.error(f"[Ingest] 컬렉션 목록 조회 실패: {e}")
            return []
