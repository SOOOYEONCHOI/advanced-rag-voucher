"""Phase 4 완료 기준 검증 — 샘플 엑셀 적재 후 실제 RAG 파이프라인으로 이미지 답변 확인 (2026.10.12, 설계 C-4).

완료 기준(작업지시서 Phase 4)
1. "FAN 모듈 REACT FAN 조립 체크포인트" 질의 응답에 FAN 시트 Step 6 사진이 포함된다.
2. 후보에 없는 IMG ID는 응답에서 제거된다(실제 후보 목록에 가짜 ID를 섞어 검증 단계 확인).

실제 임베딩·리랭커·LLM·Qdrant를 쓰고, DB는 테스트 DB(``{POSTGRES_DB}_test``)를 쓴다(scripts/eval_excel_retrieval.py와 같은 준비).
Qdrant 임시 컬렉션(``phase4_eval_<시각>``)과 평가용 관리자 계정은 끝나면 지운다(``--keep``이면 남김).

사용법 (adrag_backend 폴더에서)
    python scripts/eval_image_answer.py --report ../docs/design/reports/phase-4-image-answer.md
    python scripts/eval_image_answer.py --enrichment off --repeat 3
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "scripts"))

from eval_excel_retrieval import _prepare_environment, _upgrade_schema  # noqa: E402

CRITERION_QUERY = "FAN 모듈 REACT FAN 조립 체크포인트 알려줘"
EXTRA_QUERIES = [
    "재생 FAN 품번?",
    "제습 Rotor 모듈 조립 전체 순서",
    "도면 스캔본으로 성적서 제출해도 돼?",
]
EVAL_USER = "phase4_eval"


def _parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample")
    parser.add_argument("--model", default="NEOCON C2")
    parser.add_argument("--enrichment", choices=["on", "off"], help="기본: ENABLE_SEMANTIC_ENRICHMENT 설정")
    parser.add_argument("--repeat", type=int, default=1, help="기준 질의 반복 횟수(LLM 응답 변동 확인)")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--report")
    parser.add_argument("--work-dir")
    return parser.parse_args()


def _is_fan_step6_photo(image: dict) -> bool:
    return (
        "FAN" in (image.get("sheet_name") or "").upper()
        and image.get("step_no") == 6
        and image.get("role") in ("step_photo", "same_image_as_step_photo")
    )


async def _ask(graph, collection: str, query: str) -> dict:
    from app.graphs.state import make_initial_state

    state = make_initial_state(
        user_id=EVAL_USER, session_id=None, original_query=query, collection_filters=None,
        collection_name=collection, top_k=None, citation_limit=5, llm_provider="local", llm_model=None,
        llm_api_key=None, enable_metadata_filtering=None, relevance_threshold=None,
    )
    started = time.perf_counter()
    result = await graph.ainvoke(state)
    result["elapsed"] = time.perf_counter() - started
    return result


def _image_line(image: dict) -> str:
    cell = image.get("from_cell") or ""
    if image.get("to_cell"):
        cell += f":{image['to_cell']}"
    mark = "인용" if image.get("cited") else "자동 첨부"
    return f"{image.get('title')} ({image.get('sheet_name')}!{cell}, {image.get('role')}, {mark})"


async def main() -> int:
    args = _parse_args()
    sample = Path(args.sample or os.environ.get("NEOCON_SAMPLE_XLSX") or BACKEND_ROOT.parent / "NEOCON_SAMPLE_XLSX.xlsx")
    if not sample.is_file():
        print(f"샘플 파일이 없습니다: {sample}", file=sys.stderr)
        return 2
    if args.work_dir:
        Path(args.work_dir).mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="phase4_eval_", dir=args.work_dir))
    url = _prepare_environment(work)
    _upgrade_schema(url)

    from app.core.config import get_settings
    from app.graphs.images import validate_answer_images
    from app.graphs.rag_graph import build_rag_graph
    from app.repositories.database import get_database_manager
    from app.services.ingest_service import IngestService

    settings = get_settings()
    enrichment = settings.enable_semantic_enrichment if args.enrichment is None else args.enrichment == "on"
    db = get_database_manager()
    collection = f"phase4_eval_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    collection_id = db.execute_query(
        "INSERT INTO tb_collections (display_name, qdrant_name) VALUES (?, ?) RETURNING collection_id",
        (collection, collection),
    )[0][0]
    db.execute_update(
        """INSERT INTO tb_users (user_id, user_pwd, user_name, role, is_active)
           VALUES (?, '!', 'Phase4 평가', 'admin', true) ON CONFLICT (user_id) DO NOTHING""",
        (EVAL_USER,),
    )
    service = IngestService()
    document_id = None
    try:
        shutil.copy2(sample, work / "eval.xlsx")
        started = time.perf_counter()
        ingested = await service.ingest(
            str(work / "eval.xlsx"), sample.name, collection, enable_enrichment=enrichment,
            job_id="phase4-eval", model=args.model or None, uploaded_by="",
        )
        ingest_seconds = time.perf_counter() - started
        document_id = ingested["document_id"]
        graph = build_rag_graph()

        runs = [await _ask(graph, collection, CRITERION_QUERY) for _ in range(max(1, args.repeat))]
        extras = [(q, await _ask(graph, collection, q)) for q in EXTRA_QUERIES]

        # 완료 기준 2: 실제 후보 + 가짜 ID 인용 → 검증 단계에서 제거
        candidates = runs[0].get("image_candidates") or []
        fake_answer = f"테스트 문장입니다[IMG:{candidates[0]['ref'] if candidates else 'none00'}] [IMG:fake99]."
        cleaned, kept = validate_answer_images(fake_answer, candidates)
        fake_removed = "[IMG:fake99]" not in cleaned and all(i["ref"] != "fake99" for i in kept)

        hits = [any(_is_fan_step6_photo(i) for i in run.get("images") or []) for run in runs]
        lines = [
            f"# Phase 4 이미지 답변 검증 결과 ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
            "",
            f"- 샘플: `{sample.name}` / LLM 보강: {'on' if enrichment else 'off'} / 적재 {ingest_seconds:.0f}초",
            "- 실제 임베딩·리랭커·LLM 서버, Qdrant 임시 컬렉션, 테스트 DB",
            "",
            "## 완료 기준",
            "",
            "| # | 기준 | 결과 |",
            "|---|---|---|",
            f"| 1 | \"{CRITERION_QUERY}\" 응답에 FAN Step 6 사진 포함 | {'✅' if all(hits) else '❌'} {sum(hits)}/{len(hits)}회 |",
            f"| 2 | 후보에 없는 IMG ID 제거 | {'✅' if fake_removed else '❌'} (`[IMG:fake99]` → 제거, 실제 후보 유지 {len(kept)}건) |",
            "",
        ]
        for index, run in enumerate(runs, start=1):
            lines += [
                f"## 기준 질의 {index}회차 ({run['elapsed']:.1f}초, 후보 {len(run.get('image_candidates') or [])}건)",
                "",
                "**이미지**: " + ("; ".join(_image_line(i) for i in run.get("images") or []) or "없음"),
                "",
                "**컨텍스트 청크**: " + ", ".join(
                    f"[{n}] {c['metadata'].get('sheet_name')} {c['metadata'].get('content_type')}"
                    f"{' Step ' + str(c['metadata'].get('step_no')) if c['metadata'].get('step_no') is not None else ''}"
                    for n, c in enumerate(run.get("context_chunks") or [], start=1)
                ),
                "",
                "```text",
                (run.get("generated_answer") or run.get("error") or "").strip(),
                "```",
                "",
            ]
        lines += ["## 추가 질의", "", "| 질의 | 이미지 | 후보 수 |", "|---|---|---:|"]
        for query, run in extras:
            images = "<br>".join(_image_line(i) for i in run.get("images") or []) or "없음"
            lines.append(f"| {query} | {images} | {len(run.get('image_candidates') or [])} |")
        report = "\n".join(lines) + "\n"
        print(report)
        if args.report:
            Path(args.report).write_text(report, encoding="utf-8")
        return 0 if all(hits) and fake_removed else 1
    finally:
        if not args.keep:
            if document_id:
                try:
                    service.delete_document(document_id)
                except Exception as exc:
                    print(f"[cleanup] 문서 삭제 실패 {document_id}: {exc}", file=sys.stderr)
            service.vector_repo.delete_collection(collection)
            with db.get_connection() as conn:
                conn.execute("DELETE FROM tb_document_events WHERE collection_id=?", (collection_id,))
                conn.execute("DELETE FROM tb_documents WHERE collection_id=?", (collection_id,))
                conn.execute("DELETE FROM tb_collections WHERE collection_id=?", (collection_id,))
                conn.execute("DELETE FROM tb_users WHERE user_id=?", (EVAL_USER,))
                conn.execute(
                    """DELETE FROM tb_image_assets a WHERE NOT EXISTS
                       (SELECT 1 FROM tb_image_placements p WHERE p.image_id = a.image_id)"""
                )
            shutil.rmtree(work, ignore_errors=True)
        else:
            print(f"[keep] collection={collection} work={work}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
