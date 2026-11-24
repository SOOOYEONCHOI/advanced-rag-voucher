# 2026.11.18(sooyeon.choi) 추가 - 일괄 질의 결과 CSV(UTF-8 BOM)·xlsx (설계 9장, F-12)
"""질의별 결과·단계 상태와 xlsx 요약 시트. Excel 수식 주입 방지, 비밀값 미포함."""

import csv
import io
from typing import Any, Dict, List, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from app.evaluation.batch.runner import stage_timings
from app.evaluation.excel_exporter import safe_excel_text

RESULT_HEADERS = [
    "순번", "질의ID", "질의문", "상태", "결과유형", "생성답변(원문)", "생성답변(본문)",
    "인용 출처", "인용 근거 내용", "검색 상위10", "재랭킹 상위10", "Recall@10 적중", "정답 적중 순위", "NDCG@5",
    "응답시간(ms)", "첫 토큰(ms)", "검색(ms)", "재랭킹(ms)", "답변생성(ms)", "오류내용", "실행시각",
    "검색 상태", "재랭킹 상태", "답변 생성 상태",
]
# 2026.11.18(sooyeon.choi) 수정 - NDCG@5(재랭킹 후, 정답 확정 후)·첫 토큰(ms) 열 추가(19 → 21열)
OUTCOME_LABELS = {
    "success": "답변",
    "no_context": "근거 없음",
    "guardrail_blocked": "차단",
}
STATUS_LABELS = {"ok": "정상", "error": "오류", "pending": "미실행", "skipped": "제외"}
STAGE_STATUS_LABELS = {"ok": "정상", "error": "오류", "not_run": "미실행", "skipped": "비활성화", "empty": "후보 없음"}
XLSX_CELL_LIMIT = 32000
_TRUNCATED = " …(잘림, CSV에 전문)"


def outcome_label(item: Dict[str, Any]) -> str:
    if item.get("status") == "error":
        return "오류"
    if item.get("status") == "pending":
        return ""
    return OUTCOME_LABELS.get(item.get("outcome_code") or "", item.get("outcome_code") or "")


def _location(row: Dict[str, Any]) -> str:
    parts = [row.get("filename") or row.get("document_id") or ""]
    if row.get("sheet_name"):
        parts.append(str(row["sheet_name"]))
    if row.get("step_no") is not None:
        parts.append(f"단계 {row['step_no']}")
    elif row.get("source_range"):
        parts.append(str(row["source_range"]))
    elif row.get("page_number") is not None:
        parts.append(f"p.{row['page_number']}")
    return " › ".join(p for p in parts if p)


def _citation_sources(citations: Optional[List[Dict[str, Any]]]) -> str:
    return "\n".join(f"[{c.get('citation_id')}] {_location(c)}" for c in citations or [])


def _citation_texts(citations: Optional[List[Dict[str, Any]]]) -> str:
    return "\n\n".join(
        f"[{c.get('citation_id')}] {(c.get('chunk_text') or '').strip()}" for c in citations or []
    )


def _ranked(rows: Optional[List[Dict[str, Any]]], with_score: bool) -> str:
    lines = []
    for row in rows or []:
        line = f"{row.get('rank')}. {_location(row)} [{row.get('chunk_id')}]"
        if with_score and isinstance(row.get("score"), (int, float)):
            line += f" ({row['score']:.4f})"
        lines.append(line)
    return "\n".join(lines)


def result_rows(items: List[Dict[str, Any]], recall_by_key: Optional[Dict[str, Dict[str, Any]]] = None) -> List[List[Any]]:
    """질의별 결과 행(값은 가공 전 원본 타입). recall_by_key: {query_key: {hit, rank}} (정답 확정 후)."""
    recall_by_key = recall_by_key or {}
    rows = []
    for item in items:
        stages = stage_timings(item.get("timing_json") or {})
        recall = recall_by_key.get(item.get("query_key")) or {}
        rows.append([
            item.get("seq"),
            item.get("query_key"),
            item.get("query_text"),
            STATUS_LABELS.get(item.get("status"), item.get("status")),
            outcome_label(item),
            item.get("answer_text") or "",
            item.get("answer_plain") or "",
            _citation_sources(item.get("citations_json")),
            _citation_texts(item.get("citations_json")),
            _ranked(item.get("retrieved_top_json"), with_score=False),
            _ranked(item.get("reranked_top_json"), with_score=True),
            recall.get("hit"),
            recall.get("rank"),
            recall.get("ndcg"),
            item.get("response_ms"),
            (item.get("timing_json") or {}).get("first_token_ms"),
            stages["search_ms"],
            stages["rerank_ms"],
            stages["generate_ms"],
            item.get("error_message") or "",
            item.get("finished_at") or "",
            *[STAGE_STATUS_LABELS.get((item.get("timing_json") or {}).get("stage_statuses", {}).get(stage), "미기록")
              for stage in ("retrieval", "rerank", "answer")],
        ])
    return rows


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, str):
        return safe_excel_text(value)
    return value


def build_results_csv(items: List[Dict[str, Any]], recall_by_key=None) -> bytes:
    """UTF-8 BOM CSV — 엑셀에서 바로 열어도 한글이 깨지지 않는다."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(RESULT_HEADERS)
    for row in result_rows(items, recall_by_key):
        writer.writerow([_csv_value(v) for v in row])
    return buffer.getvalue().encode("utf-8-sig")


def _xlsx_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        text = safe_excel_text(value)
        if len(text) > XLSX_CELL_LIMIT:
            text = text[: XLSX_CELL_LIMIT - len(_TRUNCATED)] + _TRUNCATED
        return text
    return value


def _fmt_ms(stats: Optional[Dict[str, Any]], key: str) -> Any:
    return stats.get(key) if stats else None


def summary_rows(job: Dict[str, Any]) -> List[List[Any]]:
    config = job.get("config_json") or {}
    summary = job.get("summary_json") or {}
    stats = summary.get("response_ms")
    rows: List[List[Any]] = [
        ["작업명", job.get("name")],
        ["작업 ID", job.get("job_id")],
        ["컬렉션", job.get("collection_name")],
        ["상태", job.get("status")],
        ["LLM 모델", config.get("llm_model")],
        ["검색 후보 수(candidate_top_k)", config.get("candidate_top_k")],
        ["재랭킹 수(reranker_top_k)", config.get("reranker_top_k")],
        ["컨텍스트 수(context_top_k)", config.get("context_top_k")],
        ["관련도 임계값", config.get("relevance_threshold")],
        ["실행 시작", job.get("started_at")],
        ["실행 종료", job.get("finished_at")],
        ["워밍업 건수(결과 제외)", job.get("warmup_count")],
        ["전체 건수", summary.get("total", job.get("total_count"))],
        ["정상 건수", summary.get("ok")],
        ["오류 건수", summary.get("error")],
        ["미실행 건수", summary.get("not_run")],
        ["시간 측정 상태", "완료" if summary.get("response_time_status") == "complete" else "미완료"],
        ["시간 측정 건수", summary.get("response_time_measured")],
        ["시간 측정 누락 건수", summary.get("response_time_missing")],
        ["응답시간 평균(ms)", _fmt_ms(stats, "mean")],
        ["응답시간 p50(ms)", _fmt_ms(stats, "p50")],
        ["응답시간 p90(ms)", _fmt_ms(stats, "p90")],
        ["응답시간 p95(ms)", _fmt_ms(stats, "p95")],
        ["응답시간 최대(ms)", _fmt_ms(stats, "max")],
        ["응답시간 기준", "전체 질의(오류·타임아웃 포함) · 서비스 요청 시작 → 반환/실패 · 누락 시 미완료"],
    ]
    # 2026.11.18(sooyeon.choi) 추가 - 첫 토큰 시간(요청 시작 → LLM 첫 답변 토큰)
    first_token = summary.get("first_token_ms")
    rows.extend([
        ["첫 토큰 평균(ms)", _fmt_ms(first_token, "mean")],
        ["첫 토큰 p50(ms)", _fmt_ms(first_token, "p50")],
        ["첫 토큰 p90(ms)", _fmt_ms(first_token, "p90")],
        ["첫 토큰 p95(ms)", _fmt_ms(first_token, "p95")],
        ["첫 토큰 최대(ms)", _fmt_ms(first_token, "max")],
        ["첫 토큰 기준", "요청 시작 → 검색 → 재랭킹 → LLM 첫 답변 토큰 수신(재시도 시 마지막 생성 기준, 답변 생성 건만)"],
    ])
    for outcome, outcome_stats in (summary.get("response_ms_by_outcome") or {}).items():
        label = OUTCOME_LABELS.get(outcome, outcome)
        rows.append([f"응답시간 평균(ms) · {label}", _fmt_ms(outcome_stats, "mean")])
        rows.append([f"건수 · {label}", _fmt_ms(outcome_stats, "count")])
    recall = summary.get("recall_at_10")
    # 2026.11.18(sooyeon.choi) 수정 - Recall@10·NDCG@5 값과 분모를 풀어서 표시
    if recall:
        rows.extend([
            ["Recall@10(검색 완전성)", recall.get("value")],
            ["Recall@10 기준", f"{'재랭킹 전' if recall.get('basis') == 'retrieved' else '재랭킹 후'} 상위 {recall.get('k')}개"],
            ["NDCG@5(재랭킹)", recall.get("ndcg")],
            ["전체 질의 수(분모)", recall.get("total")],
            ["정답 확정 질의 수", recall.get("evaluated")],
            ["적중 질의 수", recall.get("hit")],
            ["제외 질의 수", recall.get("excluded")],
            ["실행 오류 질의 수(검색 단계별 평가)", recall.get("item_errors")],
            ["문서 버전 불일치 질의 수", recall.get("version_mismatch")],
        ])
    else:
        rows.append(["Recall@10 · NDCG@5", "정답 근거 확정 전"])
    if job.get("doc_version_changed"):
        rows.append(["경고", "작업 등록 이후 컬렉션 문서 버전이 바뀌었습니다"])
    return rows


def build_results_xlsx(job: Dict[str, Any], items: List[Dict[str, Any]], recall_by_key=None) -> bytes:
    workbook = Workbook()
    summary_sheet = workbook.active
    summary_sheet.title = "요약"
    for row in summary_rows(job):
        summary_sheet.append([_xlsx_value(v) for v in row])
    summary_sheet.column_dimensions["A"].width = 34
    summary_sheet.column_dimensions["B"].width = 60

    sheet = workbook.create_sheet("질의별 결과")
    sheet.append(RESULT_HEADERS)
    header_fill = PatternFill("solid", fgColor="4472C4")
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
    for row in result_rows(items, recall_by_key):
        sheet.append([_xlsx_value(v) for v in row])
    widths = [6, 12, 40, 8, 10, 60, 60, 40, 60, 50, 50, 10, 10, 8, 12, 12, 10, 10, 12, 30, 22, 12, 12, 12]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[sheet.cell(1, index).column_letter].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    sheet.freeze_panes = "C2"

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# ── 정답 근거 검토 Excel (설계 6.7) ──────────────────────────────────────────
# 2026.11.18(sooyeon.choi) 추가 - 자동 매칭 후보를 사람이 확인·수정하는 파일

REVIEW_SHEET = "검토"
REVIEW_HEADERS = [
    "질의ID", "근거순번", "근거 문서명", "근거 위치", "근거 내용", "매칭 상태", "문서 일치",
    "후보 수", "최고 점수", "확정 청크ID", "제외(Y)", "메모",
]
REVIEW_EDITABLE = ("확정 청크ID", "제외(Y)", "메모")
CANDIDATE_HEADERS = ["질의ID", "근거순번", "후보순위", "청크ID", "점수", "문서명", "시트", "단계", "청크 내용"]
MATCH_STATUS_LABELS = {"auto": "자동 매칭", "unmatched": "매칭 없음", "confirmed": "확정", "excluded": "제외"}
DOC_MATCH_LABELS = {"exact": "일치", "partial": "부분 일치", "none": "못 찾음(컬렉션 전체 검색)"}
REVIEW_GUIDE = [
    "1. '검토' 시트의 '확정 청크ID' 칸이 정답 청크입니다. 자동 매칭 후보가 미리 채워져 있습니다.",
    "2. 틀린 후보는 지우고, 빠진 청크는 '후보 상세' 시트나 결과 파일의 청크ID를 보고 추가하세요(쉼표·줄바꿈 구분).",
    "3. 판정에서 뺄 근거는 '제외(Y)' 칸에 Y를 넣으세요. 근거가 모두 제외된 질의도 전체 분모에 포함되며 0점입니다.",
    "4. '질의ID'·'근거순번' 열은 바꾸지 마세요. 저장 후 gold-review API로 다시 올리면 확정됩니다.",
]


def build_gold_review_xlsx(job: Dict[str, Any], gold_rows: List[Dict[str, Any]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = REVIEW_SHEET
    sheet.append(REVIEW_HEADERS)
    edit_fill = PatternFill("solid", fgColor="FFF2CC")
    header_fill = PatternFill("solid", fgColor="4472C4")
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
    detail = workbook.create_sheet("후보 상세")
    detail.append(CANDIDATE_HEADERS)
    for cell in detail[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill

    for row in gold_rows:
        matched = row.get("matched_json") or {}
        candidates = matched.get("candidates") or []
        confirmed = row.get("confirmed_ids")
        ids = confirmed if confirmed is not None else matched.get("auto_ids") or []
        sheet.append([_xlsx_value(v) for v in [
            row["query_key"], row["evidence_seq"], row.get("source_doc"), row.get("source_loc"),
            row.get("evidence_text"), MATCH_STATUS_LABELS.get(row.get("match_status"), row.get("match_status")),
            DOC_MATCH_LABELS.get(matched.get("doc_match"), matched.get("doc_match")),
            len(candidates), candidates[0]["score"] if candidates else None,
            "\n".join(ids), "Y" if row.get("match_status") == "excluded" else None, None,
        ]])
        for rank, candidate in enumerate(candidates, start=1):
            detail.append([_xlsx_value(v) for v in [
                row["query_key"], row["evidence_seq"], rank, candidate.get("chunk_id"), candidate.get("score"),
                candidate.get("filename"), candidate.get("sheet_name"), candidate.get("step_no"),
                candidate.get("text"),
            ]])

    for index, width in enumerate([10, 8, 30, 20, 60, 10, 14, 8, 8, 50, 8, 20], start=1):
        sheet.column_dimensions[sheet.cell(1, index).column_letter].width = width
    for index, width in enumerate([10, 8, 8, 50, 8, 30, 12, 6, 80], start=1):
        detail.column_dimensions[detail.cell(1, index).column_letter].width = width
    editable_cols = [REVIEW_HEADERS.index(h) + 1 for h in REVIEW_EDITABLE]
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if cell.column in editable_cols:
                cell.fill = edit_fill
    for row in detail.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    sheet.freeze_panes = "C2"

    guide = workbook.create_sheet("안내")
    guide.append([f"작업 {job.get('job_id')} · {job.get('name')} · 컬렉션 {job.get('collection_name')}"])
    for line in REVIEW_GUIDE:
        guide.append([line])
    guide.column_dimensions["A"].width = 120

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
