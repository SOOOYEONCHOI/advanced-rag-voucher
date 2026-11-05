"""Phase 2 완료 기준 검증 — 샘플 엑셀 실제 적재 + 테스트 질의 7개 Top-5 + 이미지 수치 (2026.10.01).

실제 임베딩 서버·Qdrant를 쓰고, DB는 테스트 DB(``{POSTGRES_DB}_test``, alembic head)를 쓴다.
Qdrant에는 임시 컬렉션(``phase2_eval_<시각>``)을 만들고 끝나면 지운다(``--keep``이면 남김).
파일 저장소(RESOURCE_STORAGE_ROOT·MD_SAVE_DIR·INSTANCE_DIR)는 임시 폴더를 쓴다 — 실제 instance/를 건드리지 않는다.

사용법 (adrag_backend 폴더에서)
    python scripts/eval_excel_retrieval.py --report ../docs/design/reports/phase-2-retrieval.md
    python scripts/eval_excel_retrieval.py --model "NEOCON C2" --top-k 5 --keep
샘플 경로: --sample, 없으면 환경변수 NEOCON_SAMPLE_XLSX, 없으면 저장소 루트 NEOCON_SAMPLE_XLSX.xlsx.
LLM 보강(ENABLE_SEMANTIC_ENRICHMENT)은 기존 설정을 따른다(--enrichment on|off로 덮어쓰기 가능).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

# 설계 문서 6장 검증 테스트셋 — 기대 청크는 excel_ingest 원본 청크 ID(source_chunk_id) 패턴
QUERIES = [
    ("FAN 모듈 REACT FAN 조립 체크포인트 알려줘", "FAN Step 6 청크", [r":09:step:6$"]),
    ("도면 스캔본으로 성적서 제출해도 돼?", "수입검사성적서(가공품) 안내 ①", [r":04:guide_note:12$"]),
    ("시료가 5개 넘으면 어떻게 작성해?", "안내 ④/⑤", [r":04:guide_note:11$", r":04:guide_note:13$"]),
    ("중간 검수 NG면 어떻게 돼?", "흐름도 중간 검수 단계/흐름 청크", [r":02:flow_stage:6$", r":02:flow_overview:0$"]),
    ("출하 검사 항목 뭐 있어?", "흐름도 출하 검수 단계/흐름 청크", [r":02:flow_stage:7$", r":02:flow_overview:0$"]),
    ("재생 FAN 품번?", "핵심 부품 List 행·부품 사진 청크", [r":07:"]),
    ("제습 Rotor 모듈 조립 전체 순서", "제습 Rotor SOP 요약 청크", [r":10:summary:0$"]),
]


def _parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample")
    parser.add_argument("--model", default="NEOCON C2", help="업로드 폼 model 값(빈 문자열이면 미지정)")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--enrichment", choices=["on", "off"], help="기본: ENABLE_SEMANTIC_ENRICHMENT 설정")
    parser.add_argument("--keep", action="store_true", help="Qdrant 컬렉션·DB 행·임시 폴더를 남긴다")
    parser.add_argument("--report", help="결과 마크다운 저장 경로")
    parser.add_argument("--work-dir", help="임시 저장소를 만들 상위 폴더(기본: 시스템 임시 폴더)")
    return parser.parse_args()


def _prepare_environment(work: Path) -> str:
    """앱 설정 로드 전에 테스트 DB·임시 저장소를 환경변수로 지정한다."""
    from dotenv import dotenv_values
    from sqlalchemy.engine import URL

    env = {**dotenv_values(BACKEND_ROOT.parent / ".env"), **os.environ}
    url = os.environ.get("TEST_DATABASE_URL") or URL.create(
        "postgresql+psycopg",
        username=env.get("POSTGRES_USER") or "neocon",
        password=env.get("POSTGRES_PASSWORD") or None,
        host=env.get("POSTGRES_HOST") or "localhost",
        port=int(env.get("POSTGRES_PORT") or 5432),
        database=env.get("POSTGRES_TEST_DB") or f"{env.get('POSTGRES_DB') or 'neocon_rag'}_test",
    ).render_as_string(hide_password=False)
    os.environ.update(
        DATABASE_URL=str(url),
        EXCEL_PARSE_MODE="backend",
        RESOURCE_STORAGE_ROOT=str(work / "xl_res"),
        MD_SAVE_DIR=str(work / "parsed_md"),
        INSTANCE_DIR=str(work / "instance"),
    )
    return str(url)


def _upgrade_schema(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")


def _matches(source_chunk_id: str, patterns: list[str]) -> bool:
    return any(re.search(p, source_chunk_id or "") for p in patterns)


def _rank(results, patterns) -> int | None:
    for rank, (_, _, payload) in enumerate(results, start=1):
        if _matches(payload.get("source_chunk_id"), patterns):
            return rank
    return None


def _short(payload) -> str:
    key = (payload.get("chunk_key") or "").split(":", 1)[-1]
    return key


async def _evaluate(service, collection: str, document_id: str, top_k: int):
    from app.graphs.retrieval_engine import _merge_rrf
    from app.utils.kiwi_tokenizer import normalize_query

    rows = []
    flt = {"document_id": document_id}
    for query, expected_label, patterns in QUERIES:
        vector = await service.embedding_client.embed_query(query)
        dense = await asyncio.to_thread(
            service.vector_repo.search_similar, query_vector=vector, top_k=max(top_k, 20),
            collection_name=collection, filters=flt,
        )
        kiwi = await asyncio.to_thread(
            service.vector_repo.search_bm25, query_text=normalize_query(query), top_k=max(top_k, 20),
            collection_name=collection, filters=flt,
        )
        hybrid = _merge_rrf({"dense": dense, "kiwi_bm25": kiwi}, weights={"dense": 1.0, "kiwi_bm25": 1.0})
        rows.append({
            "query": query,
            "expected": expected_label,
            "dense_rank": _rank(dense[:top_k], patterns),
            "hybrid_rank": _rank(hybrid[:top_k], patterns),
            "dense_top": [_short(p) for _, _, p in dense[:top_k]],
            "hybrid_top": [_short(p) for _, _, p in hybrid[:top_k]],
        })
    return rows


def _count(db, sql, *params) -> int:
    return int(db.execute_query(sql, params)[0][0])


async def main() -> int:
    args = _parse_args()
    sample = Path(args.sample or os.environ.get("NEOCON_SAMPLE_XLSX") or BACKEND_ROOT.parent / "NEOCON_SAMPLE_XLSX.xlsx")
    if not sample.is_file():
        print(f"샘플 파일이 없습니다: {sample}", file=sys.stderr)
        return 2
    if args.work_dir:
        Path(args.work_dir).mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="phase2_eval_", dir=args.work_dir))
    url = _prepare_environment(work)
    _upgrade_schema(url)

    from app.core.config import get_settings
    from app.repositories.database import get_database_manager
    from app.services.ingest_service import IngestService

    settings = get_settings()
    enrichment = settings.enable_semantic_enrichment if args.enrichment is None else args.enrichment == "on"
    db = get_database_manager()
    collection = f"phase2_eval_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    collection_id = db.execute_query(
        "INSERT INTO tb_collections (display_name, qdrant_name) VALUES (?, ?) RETURNING collection_id",
        (collection, collection),
    )[0][0]
    service = IngestService()
    assets_before = _count(db, "SELECT count(*) FROM tb_image_assets")
    lines: list[str] = []
    documents: list[str] = []
    try:
        timings = []
        results = []
        for run in (1, 2):
            job_id = f"eval-{run}"
            shutil.copy2(sample, work / f"{job_id}.xlsx")
            started = time.perf_counter()
            result = await service.ingest(
                str(work / f"{job_id}.xlsx"), sample.name, collection, enable_enrichment=enrichment,
                job_id=job_id, model=args.model or None, uploaded_by="",
            )
            timings.append(time.perf_counter() - started)
            documents.append(result["document_id"])
            results.append(result)
            if run == 1:
                evaluation = await _evaluate(service, collection, result["document_id"], args.top_k)

        first, second = results
        doc1, doc2 = documents
        stats = {
            "sheets": first["excel_ingest"]["sheet_count"],
            "chunks_source": first["excel_ingest"]["chunk_count"],
            "chunks_indexed": first["chunk_count"],
            "points": service.vector_repo.count_by_document_id(doc1, collection),
            "tb_chunks": _count(db, "SELECT count(*) FROM tb_chunks WHERE document_id=?", doc1),
            "max_chars": _count(db, "SELECT max(length(text)) FROM tb_chunks WHERE document_id=?", doc1),
            "placements_1": _count(db, "SELECT count(*) FROM tb_image_placements WHERE document_id=?", doc1),
            "placements_2": _count(db, "SELECT count(*) FROM tb_image_placements WHERE document_id=?", doc2),
            "assets_new_1": first["excel_ingest"]["new_asset_count"],
            "assets_new_2": second["excel_ingest"]["new_asset_count"],
            "assets_total_delta": _count(db, "SELECT count(*) FROM tb_image_assets") - assets_before,
            "needs_review": _count(
                db, "SELECT count(*) FROM tb_image_placements WHERE document_id=? AND review_status='needs_review'", doc1
            ),
            "vlm_pending": _count(
                db, """SELECT count(DISTINCT a.image_id) FROM tb_image_assets a JOIN tb_image_placements p
                       ON p.image_id=a.image_id WHERE p.document_id=? AND a.vlm_status='pending'""", doc1
            ),
            "converted": _count(
                db, """SELECT count(DISTINCT a.image_id) FROM tb_image_assets a JOIN tb_image_placements p
                       ON p.image_id=a.image_id WHERE p.document_id=? AND a.conversion_status='converted'""", doc1
            ),
            "convert_failed": _count(
                db, """SELECT count(DISTINCT a.image_id) FROM tb_image_assets a JOIN tb_image_placements p
                       ON p.image_id=a.image_id WHERE p.document_id=? AND a.conversion_status='failed'""", doc1
            ),
            "flow_graphs": _count(db, "SELECT count(*) FROM tb_flow_graphs WHERE document_id=?", doc1),
        }

        hits_dense = sum(1 for r in evaluation if r["dense_rank"])
        hits_hybrid = sum(1 for r in evaluation if r["hybrid_rank"])
        lines += [
            f"# Phase 2 검색·적재 검증 결과 ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
            "",
            f"- 샘플: `{sample.name}` / model 입력: `{args.model or '(없음)'}` / LLM 보강: {'on' if enrichment else 'off'}",
            f"- 임베딩: 설정의 EMBEDDING_* 서버, Qdrant 임시 컬렉션, Top-{args.top_k}, 검색 범위 = 첫 적재 문서",
            f"- 적재 시간: 1회차 {timings[0]:.1f}초, 2회차(재적재) {timings[1]:.1f}초",
            "",
            f"## 테스트 질의 Top-{args.top_k} (dense {hits_dense}/7, dense+Kiwi BM25 RRF {hits_hybrid}/7)",
            "",
            "| # | 질의 | 기대 청크 | dense 순위 | 하이브리드 순위 | dense Top-5 (시트:종류:블록) |",
            "|---|---|---|---:|---:|---|",
        ]
        for i, r in enumerate(evaluation, start=1):
            lines.append(
                f"| {i} | {r['query']} | {r['expected']} | {r['dense_rank'] or '✗'} | "
                f"{r['hybrid_rank'] or '✗'} | {'<br>'.join(r['dense_top'])} |"
            )
        lines += [
            "",
            "## 적재 수치",
            "",
            "| 항목 | 값 |",
            "|---|---:|",
            f"| 시트 | {stats['sheets']} |",
            f"| excel_ingest 청크 → 적재 청크(800자 분할 후) | {stats['chunks_source']} → {stats['chunks_indexed']} |",
            f"| Qdrant point / tb_chunks | {stats['points']} / {stats['tb_chunks']} |",
            f"| 적재 청크 최대 길이(자) | {stats['max_chars']} |",
            f"| image_placement (1회차 / 재적재 문서) | {stats['placements_1']} / {stats['placements_2']} |",
            f"| image_asset 신규 (1회차 / 재적재) | {stats['assets_new_1']} / {stats['assets_new_2']} |",
            f"| image_asset 전체 증가 | {stats['assets_total_delta']} |",
            f"| 검수 필요 placement(needs_review) | {stats['needs_review']} |",
            f"| VLM 대상(pending) 이미지 | {stats['vlm_pending']} |",
            f"| emf/wmf PNG 변환 성공 / 실패 | {stats['converted']} / {stats['convert_failed']} |",
            f"| flow_graph | {stats['flow_graphs']} |",
            "",
        ]
        report = "\n".join(lines)
        print(report)
        if args.report:
            Path(args.report).write_text(report, encoding="utf-8")
        ok = (
            hits_dense == len(QUERIES) and stats["placements_1"] == 190 and stats["assets_new_2"] == 0
            and stats["assets_total_delta"] <= 152
        )
        return 0 if ok else 1
    finally:
        if not args.keep:
            for document_id in documents:
                try:
                    service.delete_document(document_id)
                except Exception as exc:  # 정리 실패는 보고만
                    print(f"[cleanup] 문서 삭제 실패 {document_id}: {exc}", file=sys.stderr)
            service.vector_repo.delete_collection(collection)
            with db.get_connection() as conn:
                conn.execute("DELETE FROM tb_document_events WHERE collection_id=?", (collection_id,))
                conn.execute("DELETE FROM tb_documents WHERE collection_id=?", (collection_id,))
                conn.execute("DELETE FROM tb_collections WHERE collection_id=?", (collection_id,))
                conn.execute(
                    """DELETE FROM tb_image_assets a WHERE NOT EXISTS
                       (SELECT 1 FROM tb_image_placements p WHERE p.image_id = a.image_id)"""
                )
            shutil.rmtree(work, ignore_errors=True)
        else:
            print(f"[keep] collection={collection} work={work}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
