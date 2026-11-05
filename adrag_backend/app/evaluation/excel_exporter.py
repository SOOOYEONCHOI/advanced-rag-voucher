"""평가 데이터셋과 평가 실행 결과를 Excel 통합 문서로 변환한다.

구성:
- 공통 영역: 두 종류의 Excel 다운로드가 함께 사용하는 보안·길이·파일명 처리
- 승인 평가 데이터셋 영역: 데이터셋 목록의 승인 QA Excel 다운로드에서 사용
- 평가 실행 결과 영역: 평가 실행 이력의 지표·항목별 결과 Excel 다운로드에서 사용
"""

import json
import re
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any, Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)

KST = timezone(timedelta(hours=9))
MAX_CELL_TEXT = 32_000
TRUNCATION_MARKER = "[내용 잘림]"
QUESTION_TYPE_LABELS = {
    "factual": "사실형",
    "procedural": "절차형",
    "comparative": "비교형",
    "multihop": "멀티홉",
}
QA_HEADERS = [
    "유형", "질문", "답변", "검색 근거", "근거 원문", "난이도", "기대 동작", "태그",
    "검수 상태", "검수자", "검수일시", "QA ID", "문서 ID", "청크 ID", "자체 검증 순위", "생성일시",
]
METRIC_HEADERS = ["지표", "성능", "표준편차", "평가 건수", "제외 건수", "오류 건수", "전체 건수"]


# ── 공통: 승인 데이터셋·평가 실행 Excel에서 함께 사용 ──────────────────────

def safe_excel_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


def _limited_text(value: Any, item_id: Any = None) -> str:
    text = safe_excel_text(value)
    if len(text) <= MAX_CELL_TEXT:
        return text
    logger.warning("평가 Excel 셀 내용 잘림: item_id=%s", item_id)
    return text[: MAX_CELL_TEXT - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER


def _safe_filename_name(value: Any, fallback: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or fallback)).strip(" .")[:80]
    return name or fallback


def _parse_json(value: Any, fallback: Any) -> Any:
    if not value:
        return fallback
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


# ── 승인 생성된 평가 데이터셋 Excel 다운로드 전용 ──────────────────────────────────
# API: GET /api/eval/datasets/{dataset_id}/approved-items.xlsx

def _parse_dataset_json(value: Any, field: str, qa_id: Any) -> Any:
    if value in (None, ""):
        return []
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        logger.warning("평가 Excel JSON 파싱 실패: qa_id=%s field=%s", qa_id, field)
        return value


def _join_dataset_json(value: Any, separator: str, field: str, qa_id: Any) -> str:
    parsed = _parse_dataset_json(value, field, qa_id)
    if isinstance(parsed, list):
        return separator.join(str(item) for item in parsed)
    return "" if parsed is None else str(parsed)


def _format_source(source_meta: Any, qa_id: Any) -> str:
    parsed = _parse_dataset_json(source_meta, "source_meta_json", qa_id)
    sources = parsed if isinstance(parsed, list) else [parsed]
    lines = []
    for source in sources:
        if not isinstance(source, dict):
            if source not in (None, "", []):
                lines.append(str(source))
            continue
        parts = []
        if source.get("original_filename"):
            parts.append(str(source["original_filename"]))
        if source.get("section_title"):
            parts.append(str(source["section_title"]))
        if source.get("page_number") not in (None, ""):
            parts.append(f"p.{source['page_number']}")
        if parts:
            lines.append(" · ".join(parts))
    return "\n".join(lines)


def _safe_row(values: Iterable[Any], item_id: Any) -> list[Any]:
    return [_limited_text(value, item_id) if isinstance(value, str) else value for value in values]


def build_approved_dataset_workbook(dataset: dict, items: list[dict]) -> BytesIO:
    """승인·수정 QA를 `QA`, `정보` 두 시트의 데이터셋 Excel로 생성한다."""
    workbook = Workbook()
    qa_sheet = workbook.active
    qa_sheet.title = "QA"
    qa_sheet.append(QA_HEADERS)

    for item in items:
        qa_id = item.get("qa_id")
        qa_sheet.append(_safe_row([
            QUESTION_TYPE_LABELS.get(item.get("question_type"), item.get("question_type") or ""),
            item.get("question") or "",
            item.get("gold_answer") or "",
            _format_source(item.get("source_meta_json"), qa_id),
            _join_dataset_json(item.get("gold_chunk_texts"), "\n\n", "gold_chunk_texts", qa_id),
            item.get("difficulty") or "",
            item.get("expected_behavior") or "",
            _join_dataset_json(item.get("tags"), ", ", "tags", qa_id),
            item.get("review_status") or "",
            item.get("reviewed_by") or "",
            item.get("reviewed_at") or "",
            qa_id,
            _join_dataset_json(item.get("gold_document_ids"), "\n", "gold_document_ids", qa_id),
            _join_dataset_json(item.get("gold_chunk_ids"), "\n", "gold_chunk_ids", qa_id),
            item.get("self_valid_rank"),
            item.get("created_at") or "",
        ], qa_id))

    header_fill = PatternFill("solid", fgColor="D9EAF7")
    for cell in qa_sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
    qa_sheet.freeze_panes = "A2"
    qa_sheet.auto_filter.ref = qa_sheet.dimensions
    widths = [14, 45, 55, 45, 65, 12, 16, 24, 12, 14, 20, 10, 20, 20, 14, 20]
    for index, width in enumerate(widths, start=1):
        qa_sheet.column_dimensions[qa_sheet.cell(1, index).column_letter].width = width
    for row in qa_sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    info_sheet = workbook.create_sheet("정보")
    info_rows = [
        ("데이터셋 ID", dataset.get("dataset_id")),
        ("데이터셋명", dataset.get("name") or ""),
        ("컬렉션명", dataset.get("collection_name") or ""),
        ("데이터셋 상태", dataset.get("status") or ""),
        ("승인 항목 수", len(items)),
        ("생성일시", dataset.get("created_at") or ""),
        ("최종 수정일시", dataset.get("updated_at") or ""),
        ("다운로드 생성일시", datetime.now(KST).replace(microsecond=0).isoformat()),
        ("포함 상태", "approved, edited"),
    ]
    for label, value in info_rows:
        info_sheet.append([label, _limited_text(value) if isinstance(value, str) else value])
    for cell in info_sheet["A"]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
    info_sheet.column_dimensions["A"].width = 22
    info_sheet.column_dimensions["B"].width = 55

    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


def build_excel_filename(dataset: dict, now: datetime | None = None) -> str:
    """승인 평가 데이터셋 다운로드 파일명을 생성한다."""
    fallback = f"dataset_{dataset.get('dataset_id', '')}"
    name = _safe_filename_name(dataset.get("name"), fallback)
    timestamp = (now or datetime.now(KST)).strftime("%Y%m%d_%H%M%S")
    return f"평가데이터셋_{name}_{timestamp}.xlsx"


# ── 평가 실행 결과 Excel 다운로드 전용 ──────────────────────────────────────
# API: GET /api/eval/runs/{run_id}/results.xlsx

def _metric_summary_value(metric: dict) -> float | str:
    value = metric.get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if metric.get("error_count", 0) > 0 and metric.get("evaluated_count", 0) == 0:
        return "오류"
    if metric.get("excluded_count", 0) > 0 and metric.get("evaluated_count", 0) == 0:
        return "제외"
    return "-"


def _metric_state_value(metric: Any, item_status: str | None = None) -> float | str:
    if isinstance(metric, dict):
        value = metric.get("value")
        if metric.get("status") == "evaluated" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if metric.get("status") == "excluded":
            return "제외"
        if metric.get("status") == "error":
            return "오류"
    if item_status and item_status != "ok":
        return "오류"
    return "-"


def _legacy_metric(container: Any, channel: str, key: str) -> dict | None:
    parsed = _parse_json(container, {})
    value = parsed.get(channel, {}).get(key) if isinstance(parsed, dict) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"value": value, "status": "evaluated"}
    return None


def _item_metric_values(item: dict, run_type: str, n: int, k: int) -> list[float | str]:
    metrics = _parse_json(item.get("metric_status_json"), {})
    if not isinstance(metrics, dict):
        metrics = {}
    recall = metrics.get(f"retrieval.rrf.recall@{n}") or _legacy_metric(
        item.get("retrieval_json"), "rrf", f"recall@{n}"
    )
    ndcg = metrics.get(f"retrieval.rerank.ndcg@{k}") or _legacy_metric(
        item.get("retrieval_json"), "rerank", f"ndcg@{k}"
    )
    values = [
        _metric_state_value(recall, item.get("status")),
        _metric_state_value(ndcg, item.get("status")),
    ]
    if run_type != "full":
        return [*values, "해당 없음", "해당 없음"]

    correctness = metrics.get("answer.correctness") or metrics.get("answer.correctness_v2_shadow")
    citation = metrics.get("citation.completeness")
    if citation is None:
        citation_json = _parse_json(item.get("citation_json"), {})
        citation_value = citation_json.get("completeness") if isinstance(citation_json, dict) else None
        if isinstance(citation_value, (int, float)) and not isinstance(citation_value, bool):
            citation = {"value": citation_value, "status": "evaluated"}
    return [
        *values,
        _metric_state_value(correctness, item.get("status")),
        _metric_state_value(citation, item.get("status")),
    ]


def _append_metric_table(sheet, title: str, metrics: list[dict], start_row: int) -> int:
    sheet.cell(start_row, 1, title)
    sheet.cell(start_row, 1).font = Font(bold=True, color="FFFFFF")
    sheet.cell(start_row, 1).fill = PatternFill("solid", fgColor="4472C4")
    sheet.merge_cells(start_row=start_row, start_column=1, end_row=start_row, end_column=len(METRIC_HEADERS))
    sheet.append(METRIC_HEADERS)
    header_row = start_row + 1
    for cell in sheet[header_row]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9EAF7")
        cell.alignment = Alignment(horizontal="center")
    for metric in metrics:
        sheet.append([
            metric.get("label") or metric.get("key") or "",
            _metric_summary_value(metric),
            metric.get("std"),
            metric.get("evaluated_count", 0),
            metric.get("excluded_count", 0),
            metric.get("error_count", 0),
            metric.get("total_count", 0),
        ])
        row = sheet.max_row
        for column in (2, 3):
            if isinstance(sheet.cell(row, column).value, (int, float)):
                sheet.cell(row, column).number_format = "0.0%"
    return sheet.max_row + 2


def build_run_result_workbook(
    run: dict,
    primary_metrics: list[dict],
    secondary_metrics: list[dict],
    items: list[dict],
) -> BytesIO:
    """실행 결과를 `지표 요약`, `항목별 결과` 두 시트의 Excel로 생성한다."""
    config = _parse_json(run.get("config") or run.get("config_json"), {})
    n = int(config.get("retrieval_top_n", config.get("top_k", 10)))
    k = int(config.get("rerank_top_k", 5))
    run_type = run.get("scope") or run.get("run_type") or "retrieval"

    workbook = Workbook()
    summary = workbook.active
    summary.title = "지표 요약"
    info_rows = [
        ("실행 ID", run.get("run_id")),
        ("데이터셋", run.get("dataset_name") or ""),
        ("골드셋 버전", run.get("goldset_version")),
        ("컬렉션", run.get("collection_name") or ""),
        ("평가 유형", "전체 RAG" if run_type == "full" else "검색·재정렬"),
        ("실행 상태", run.get("status") or ""),
        ("검색 후보 수 N", n),
        ("최종 문서 수 K", k),
        ("평가 기준 버전", config.get("metric_version", "legacy")),
        ("시작일시", run.get("started_at") or ""),
        ("완료일시", run.get("finished_at") or ""),
        ("다운로드 생성일시", datetime.now(KST).replace(microsecond=0).isoformat()),
    ]
    info_fill = PatternFill("solid", fgColor="E2F0D9")
    for label, value in info_rows:
        summary.append([label, _limited_text(value) if isinstance(value, str) else value])
        summary.cell(summary.max_row, 1).font = Font(bold=True)
        summary.cell(summary.max_row, 1).fill = info_fill
    next_row = _append_metric_table(summary, "주요 지표", primary_metrics, summary.max_row + 2)
    _append_metric_table(summary, "보조 지표", secondary_metrics, next_row)
    summary.column_dimensions["A"].width = 29
    summary.column_dimensions["B"].width = 24
    for column in "CDEFG":
        summary.column_dimensions[column].width = 14

    results = workbook.create_sheet("항목별 결과")
    results.append([
        "번호", "유형", "질문", f"Retriever Recall@{n}", f"Reranked NDCG@{k}",
        "Answer Correctness", "Citation Completeness",
    ])
    for cell in results[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9EAD3")
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for index, item in enumerate(items, start=1):
        result_id = item.get("result_id")
        results.append([
            item.get("dataset_sequence") or index,
            QUESTION_TYPE_LABELS.get(item.get("question_type"), item.get("question_type") or ""),
            _limited_text(item.get("question") or "", result_id),
            *_item_metric_values(item, run_type, n, k),
        ])
        row = results.max_row
        results.cell(row, 3).alignment = Alignment(wrap_text=True, vertical="top")
        for column in range(4, 8):
            cell = results.cell(row, column)
            cell.alignment = Alignment(horizontal="center", vertical="top")
            if isinstance(cell.value, (int, float)):
                cell.number_format = "0.0%"
    results.freeze_panes = "A2"
    results.auto_filter.ref = results.dimensions
    widths = [10, 13, 65, 22, 22, 22, 24]
    for index, width in enumerate(widths, start=1):
        results.column_dimensions[results.cell(1, index).column_letter].width = width

    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


def build_run_excel_filename(run: dict, now: datetime | None = None) -> str:
    """평가 실행 결과 다운로드 파일명을 생성한다."""
    fallback = f"dataset_{run.get('dataset_id', '')}"
    name = _safe_filename_name(run.get("dataset_name"), fallback)
    timestamp = (now or datetime.now(KST)).strftime("%Y%m%d_%H%M%S")
    return f"평가실행_{name}_run_{run.get('run_id')}_{timestamp}.xlsx"
