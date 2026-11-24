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
    # 2026.11.19(sooyeon.choi) 추가 - 단일 출처 생성(유형 구분 없음)
    "law": "법령",
    "general": "일반",
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


# ── 2026.11.19(sooyeon.choi) 추가 - 시험 데이터셋 Excel 다운로드 ─────────────────
# API: GET /api/eval/datasets/{dataset_id}/test-set.xlsx  (설계 eval-law-testset-design-v1.0 4장)
# - 질의 시트: 일괄 질의 업로드 파일 호환(질의ID·질의문)
# - 정답 근거 시트: 일괄 질의 정답 파일 호환(청크ID가 있으면 자동 매칭 없이 확정)
# - 청크ID = Qdrant 포인트 ID(검색 결과와 같은 ID)

TESTSET_QUERY_HEADERS = ["질의ID", "질의문", "정답 답변"]
TESTSET_GOLD_HEADERS = ["질의ID", "근거순번", "근거 문서명", "근거 조항", "페이지", "청크ID", "근거 내용"]
# 2026.11.19(sooyeon.choi) 추가 - 승인 QA Excel에만 있던 검수 정보(다운로드 통합)
TESTSET_REVIEW_HEADERS = [
    "질의ID", "QA ID", "유형", "검수 상태", "검수자", "검수일시", "자체 검증 순위",
    "기대 동작", "태그", "난이도", "문서 ID", "생성일시",
]
GENERATION_MODE_LABELS = {
    "typed": "유형별(사실·절차·비교·멀티홉)",
    "law_article": "법령 조항 단일 출처",
    "single_section": "일반 문서 단일 출처",
    # 2026.11.20(sooyeon.choi) 수정 - 합본 데이터셋
    "merged": "합본(확정 데이터셋 합치기)",
}
_QUERY_ID_PREFIX = re.compile(r"[^0-9A-Za-z가-힣_-]+")


def _testset_sort_key(item: dict) -> tuple:
    meta = _parse_json(item.get("source_meta_json"), {})
    meta = meta if isinstance(meta, dict) else {}
    unit_order = meta.get("unit_order")
    # 2026.11.20(sooyeon.choi) 수정 - 합본 문항은 합친 순서(merge_order)가 우선. 단독 데이터셋은 항상 0이라 순서 그대로
    merge_order = meta.get("merge_order")
    return (
        merge_order if isinstance(merge_order, int) else 0,
        0 if isinstance(unit_order, int) else 1,
        unit_order if isinstance(unit_order, int) else 0,
        meta.get("chunk_index") if isinstance(meta.get("chunk_index"), int) else 0,
        meta.get("variant") if isinstance(meta.get("variant"), int) else 0,
        item.get("qa_id") or 0,
    )


# 2026.11.23(sooyeon.choi) 추가 - 접두어 정리 규칙을 접두어 변경 API와 함께 쓰도록 분리
def normalize_query_id_prefix(raw: Any) -> str:
    """허용 문자(영문·숫자·한글·_·-)만 남기고 앞뒤 _·- 제거, 최대 20자. 빈 값이면 ''."""
    return _QUERY_ID_PREFIX.sub("", str(raw or "")).strip("-_")[:20]


def testset_query_id_prefix(dataset: dict) -> str:
    config = _parse_json(dataset.get("gen_config_json"), {})
    raw = (config or {}).get("query_id_prefix") if isinstance(config, dict) else None
    return normalize_query_id_prefix(raw) or "Q"


def _article_label(meta: dict) -> str:
    if meta.get("article"):
        return str(meta["article"])
    path = meta.get("header_path")
    if isinstance(path, list) and path:
        return str(path[-1])
    return str(meta.get("section_title") or "")


def build_testset_workbook(
    dataset: dict,
    items: list[dict],
    current_versions: dict[str, Any] | None = None,
) -> BytesIO:
    """승인·수정 문항 → `질의`·`정답 근거`·`검수 정보`·`요약` 시트의 데이터셋 Excel."""
    current_versions = current_versions or {}
    config = _parse_json(dataset.get("gen_config_json"), {})
    config = config if isinstance(config, dict) else {}
    prefix = testset_query_id_prefix(dataset)
    ordered = sorted(items, key=_testset_sort_key)
    width = max(3, len(str(len(ordered))))
    # 2026.11.20(sooyeon.choi) 수정 - 합본은 문항에 저장한 원본 질의ID를 쓰고, 질의 시트에 법령 열을 둔다
    is_merged = config.get("dataset_kind") == "merged"

    workbook = Workbook()
    query_sheet = workbook.active
    query_sheet.title = "질의"
    query_sheet.append([*TESTSET_QUERY_HEADERS, "법령"] if is_merged else TESTSET_QUERY_HEADERS)
    gold_sheet = workbook.create_sheet("정답 근거")
    gold_sheet.append(TESTSET_GOLD_HEADERS)
    review_sheet = workbook.create_sheet("검수 정보")
    review_sheet.append(TESTSET_REVIEW_HEADERS)

    per_document: dict[str, int] = {}
    per_chapter: dict[tuple, int] = {}
    stale: list[str] = []
    versions_used: dict[str, Any] = {}
    for index, item in enumerate(ordered, start=1):
        qa_id = item.get("qa_id")
        meta = _parse_json(item.get("source_meta_json"), {})
        meta = meta if isinstance(meta, dict) else {}
        query_id = str(meta.get("query_id") or f"{prefix}-{index:0{width}d}")
        query_row = [query_id, item.get("question") or "", item.get("gold_answer") or ""]
        query_sheet.append(_safe_row([*query_row, meta.get("law_label") or ""] if is_merged else query_row, qa_id))

        chunk_ids = _parse_dataset_json(item.get("gold_chunk_ids"), "gold_chunk_ids", qa_id)
        texts = _parse_dataset_json(item.get("gold_chunk_texts"), "gold_chunk_texts", qa_id)
        chunk_ids = chunk_ids if isinstance(chunk_ids, list) else [chunk_ids]
        texts = texts if isinstance(texts, list) else [texts]
        document_name = str(meta.get("original_filename") or "")
        for seq, chunk_id in enumerate(chunk_ids, start=1):
            # 출처 메타(조항·페이지)는 첫 근거 기준으로 저장되어 있다(단일 출처 생성은 근거 1개)
            gold_sheet.append(_safe_row([
                query_id, seq, document_name,
                _article_label(meta) if seq == 1 else "",
                meta.get("page_number") if seq == 1 else None,
                str(chunk_id),
                texts[seq - 1] if seq - 1 < len(texts) else "",
            ], qa_id))

        review_sheet.append(_safe_row([
            query_id, qa_id,
            QUESTION_TYPE_LABELS.get(item.get("question_type"), item.get("question_type") or ""),
            item.get("review_status") or "", item.get("reviewed_by") or "", item.get("reviewed_at") or "",
            item.get("self_valid_rank"), item.get("expected_behavior") or "",
            _join_dataset_json(item.get("tags"), ", ", "tags", qa_id), item.get("difficulty") or "",
            _join_dataset_json(item.get("gold_document_ids"), "\n", "gold_document_ids", qa_id),
            item.get("created_at") or "",
        ], qa_id))

        law_name = str(meta.get("law_name") or document_name or "-")
        per_document[law_name] = per_document.get(law_name, 0) + 1
        path = meta.get("header_path") if isinstance(meta.get("header_path"), list) else []
        chapter = str(path[0]) if len(path) > 1 else ("별표" if meta.get("is_annex") else "-")
        per_chapter[(law_name, chapter)] = per_chapter.get((law_name, chapter), 0) + 1
        doc_id = meta.get("document_id")
        if doc_id:
            versions_used[str(doc_id)] = meta.get("version_no")
            current = current_versions.get(str(doc_id), meta.get("version_no"))
            if current != meta.get("version_no") and query_id not in stale:
                stale.append(query_id)

    header_fill = PatternFill("solid", fgColor="D9EAF7")
    for sheet, widths in (
        (query_sheet, [12, 70, 80, 18] if is_merged else [12, 70, 80]),
        (gold_sheet, [12, 10, 40, 16, 8, 40, 80]),
        (review_sheet, [12, 10, 10, 12, 14, 22, 14, 14, 24, 10, 40, 22]),
    ):
        for cell in sheet[1]:
            cell.font = Font(bold=True)
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for index, column_width in enumerate(widths, start=1):
            sheet.column_dimensions[sheet.cell(1, index).column_letter].width = column_width
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")

    summary = workbook.create_sheet("요약")
    rows: list[tuple] = [
        ("데이터셋 ID", dataset.get("dataset_id")),
        ("데이터셋명", dataset.get("name") or ""),
        ("컬렉션명", " + ".join(
            str(source.get("collection_name") or "") for source in config.get("merged_from") or []
        ) if is_merged else dataset.get("collection_name") or ""),
        ("생성 방식", GENERATION_MODE_LABELS.get(
            config.get("generation_mode") or ("merged" if is_merged else "typed"), config.get("generation_mode"))),
        ("생성 모델", config.get("llm_model") or config.get("openai_model") or ""),
        ("sampling seed", config.get("sampling_seed")),
        ("목표 문항 수", config.get("target_count")),
        ("문항 수(승인·수정)", len(ordered)),
        ("질의ID 접두어", "원본 질의ID 유지(합본)" if is_merged else prefix),
        ("데이터셋 생성일시", dataset.get("created_at") or ""),
        ("다운로드 생성일시", datetime.now(KST).replace(microsecond=0).isoformat()),
        ("문서 버전(생성 당시)", ", ".join(f"{doc}:v{ver}" for doc, ver in versions_used.items())),
        ("버전 확인",
         f"경고: 생성 이후 문서 버전이 바뀐 질의 {len(stale)}건({', '.join(stale[:5])}…) - 청크ID가 무효일 수 있습니다"
         if stale else "생성 당시 문서 버전과 같음"),
        ("", ""),
        ("문서별 문항 수", ""),
    ]
    rows.extend((f"  {name}", count) for name, count in per_document.items())
    rows.append(("", ""))
    rows.append(("장(章)별 문항 수", ""))
    rows.extend((f"  {name} · {chapter}", count) for (name, chapter), count in per_chapter.items())
    for label, value in rows:
        summary.append([label, _limited_text(value) if isinstance(value, str) else value])
    for cell in summary["A"]:
        if cell.value and not str(cell.value).startswith("  "):
            cell.font = Font(bold=True)
    summary.column_dimensions["A"].width = 34
    summary.column_dimensions["B"].width = 70

    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


def build_testset_filename(dataset: dict, now: datetime | None = None) -> str:
    fallback = f"dataset_{dataset.get('dataset_id', '')}"
    name = _safe_filename_name(dataset.get("name"), fallback)
    timestamp = (now or datetime.now(KST)).strftime("%Y%m%d_%H%M%S")
    return f"시험데이터셋_{name}_{timestamp}.xlsx"


# ── 평가 실행 결과 Excel 다운로드 전용 ──────────────────────────────────────
# API: GET /api/eval/runs/{run_id}/results.xlsx

def _metric_summary_value(metric: dict) -> float | str:
    # 2026.11.19(sooyeon.choi) 추가 - 합의서 필수 지표 중 아직 계산하지 않는 것(3종 LLM 심사)
    if metric.get("status") == "not_measured":
        return "미측정"
    if metric.get("status") == "incomplete":
        return "측정 미완료"
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
    # 2026.11.17(sooyeon.choi) 수정 - 검색 열을 Recall@N → Hit@N(검색 완전성)으로 변경
    hit = metrics.get(f"retrieval.rrf.hit@{n}") or _legacy_metric(
        item.get("retrieval_json"), "rrf", f"hit@{n}"
    )
    ndcg = metrics.get(f"retrieval.rerank.ndcg@{k}") or _legacy_metric(
        item.get("retrieval_json"), "rerank", f"ndcg@{k}"
    )
    values = [
        _metric_state_value(hit, item.get("status")),
        _metric_state_value(ndcg, item.get("status")),
    ]
    if run_type != "full":
        return [*values, "해당 없음", "해당 없음"]

    # 2026.11.17(sooyeon.choi) 수정 - answer.correctness(F2)만 사용, v2 shadow 대체 삭제
    correctness = metrics.get("answer.correctness")
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
        # 2026.11.19(sooyeon.choi) 수정 - ms 단위 지표(반환 시간)는 초로 표시, 비율 지표는 %
        is_ms = metric.get("unit") == "ms"
        label = metric.get("label") or metric.get("key") or ""
        summary_value = _metric_summary_value(metric)
        sheet.append([
            f"{label} (초)" if is_ms else label,
            _seconds(summary_value) if is_ms else summary_value,
            _seconds(metric.get("std")) if is_ms else metric.get("std"),
            metric.get("evaluated_count", 0),
            metric.get("excluded_count", 0),
            metric.get("error_count", 0),
            metric.get("total_count", 0),
        ])
        row = sheet.max_row
        for column in (2, 3):
            if isinstance(sheet.cell(row, column).value, (int, float)):
                sheet.cell(row, column).number_format = "0.00" if is_ms else "0.0%"
    return sheet.max_row + 2


# 전체 RAG 응답시간은 오류 포함 전체 항목, 첫 토큰 시간은 정상 답변 생성 건 기준.
# 2026.11.18(sooyeon.choi) 수정 - 표시 단위 ms → 초(s), 소수 둘째 자리. DB 저장은 ms 그대로
TIMING_HEADERS = ["구분", "평균(s)", "p50(s)", "p90(s)", "p95(s)", "최대(s)", "건수"]


def _seconds(value_ms: Any) -> Any:
    """ms → 초(소수 둘째 자리). 숫자가 아니면 그대로."""
    if isinstance(value_ms, (int, float)) and not isinstance(value_ms, bool):
        return round(value_ms / 1000, 2)
    return value_ms


def _item_first_token_ms(item: dict) -> Any:
    timing = _parse_json(item.get("timing_json"), {})
    value = timing.get("first_token_ms") if isinstance(timing, dict) else None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _item_latency_ms(item: dict) -> Any:
    value = item.get("latency_ms")
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def run_timing_stats(items: list[dict]) -> dict:
    """시험 4: 오류 포함 전체 질의로 계산하며 시간 누락 시 평균을 확정하지 않는다."""
    from app.evaluation.batch.runner import compute_summary

    return compute_summary([
        {"status": item.get("status"), "response_ms": _item_latency_ms(item),
         "timing_json": {"first_token_ms": _item_first_token_ms(item)}}
        for item in items
    ])


def _append_timing_table(sheet, stats: dict, start_row: int) -> int:
    sheet.cell(start_row, 1, "응답 시간")
    sheet.cell(start_row, 1).font = Font(bold=True, color="FFFFFF")
    sheet.cell(start_row, 1).fill = PatternFill("solid", fgColor="4472C4")
    sheet.merge_cells(start_row=start_row, start_column=1, end_row=start_row, end_column=len(TIMING_HEADERS))
    sheet.append(TIMING_HEADERS)
    for cell in sheet[start_row + 1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9EAF7")
        cell.alignment = Alignment(horizontal="center")
    for label, key in (("답변 생성 응답시간(전체)", "response_ms"), ("첫 토큰 반환 시간", "first_token_ms")):
        values = stats.get(key) or {}
        sheet.append([
            label, *(_seconds(values.get(key)) for key in ("mean", "p50", "p90", "p95", "max")),
            values.get("count", 0),
        ])
        for column in range(2, 7):
            if isinstance(sheet.cell(sheet.max_row, column).value, (int, float)):
                sheet.cell(sheet.max_row, column).number_format = "0.00"
    sheet.append([
        "기준",
        "응답시간: 전체 질의·오류 포함, 측정 누락 시 미완료 / 첫 토큰: 정상 답변 생성 건만",
    ])
    if stats.get("response_time_status") == "incomplete":
        sheet.append(["시간 측정 상태", f"미완료 · 누락 {stats.get('response_time_missing')}건"])
    return sheet.max_row + 2


def build_run_result_workbook(
    run: dict,
    primary_metrics: list[dict],
    secondary_metrics: list[dict],
    items: list[dict],
    law_metrics: list[dict] | None = None,
) -> BytesIO:
    """실행 결과를 `지표 요약`, `항목별 결과` 두 시트의 Excel로 생성한다.

    2026.11.20(sooyeon.choi) 수정 - law_metrics(합본 실행의 법령별 주요 지표)가 있으면 요약 시트에 법령별 표,
    항목별 결과 시트에 법령 열을 넣는다. 항목별 결과에 질의ID·정답 답변·생성 답변·인용 출처 열 추가.
    """
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
    if law_metrics:
        next_row = _append_law_table(summary, primary_metrics, law_metrics, next_row)
    next_row = _append_metric_table(summary, "보조 지표 (내부 참고 · 인증 합격 판정 제외)", secondary_metrics, next_row)
    # 2026.11.18(sooyeon.choi) 추가 - 전체 RAG 평가만 응답시간 표(검색·재정렬 평가는 답변을 생성하지 않음)
    if run_type == "full":
        _append_timing_table(summary, run_timing_stats(items), next_row)
    summary.column_dimensions["A"].width = 29
    summary.column_dimensions["B"].width = 24
    for column in "CDEFG":
        summary.column_dimensions[column].width = 14

    results = workbook.create_sheet("항목별 결과")
    # 2026.11.18(sooyeon.choi) 수정 - 응답시간(ms)·첫 토큰(ms) 열 추가(전체 RAG 평가만 값, 검색 평가는 '해당 없음')
    # 2026.11.20(sooyeon.choi) 수정 - 질의ID·(합본)법령·정답 답변·생성 답변·인용 출처 열 추가
    with_law = bool(law_metrics)
    text_headers = ["번호", "질의ID", *(["법령"] if with_law else []), "유형", "질문", "정답 답변", "생성 답변", "인용 출처"]
    first_metric = len(text_headers) + 1
    results.append([
        *text_headers, f"검색 완전성 Hit@{n}", f"Reranked NDCG@{k}",
        "Answer Correctness (F2)", "Citation Completeness", "전체 응답시간(s)", "첫 토큰(s)",
    ])
    for cell in results[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9EAD3")
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for index, item in enumerate(items, start=1):
        result_id = item.get("result_id")
        results.append([
            item.get("dataset_sequence") or index,
            item.get("query_id") or "",
            *([item.get("law_label") or ""] if with_law else []),
            QUESTION_TYPE_LABELS.get(item.get("question_type"), item.get("question_type") or ""),
            _limited_text(item.get("question") or "", result_id),
            _limited_text(item.get("gold_answer") or "", result_id),
            _limited_text(item.get("answer_text") or "", result_id) if run_type == "full" else "해당 없음",
            _limited_text(_cited_sources(item), result_id) if run_type == "full" else "해당 없음",
            *_item_metric_values(item, run_type, n, k),
            *(
                [_seconds(_item_latency_ms(item)), _seconds(_item_first_token_ms(item))]
                if run_type == "full" else ["해당 없음", "해당 없음"]
            ),
        ])
        row = results.max_row
        for column in range(2, first_metric):
            results.cell(row, column).alignment = Alignment(wrap_text=True, vertical="top")
        for column in range(first_metric, first_metric + 4):
            cell = results.cell(row, column)
            cell.alignment = Alignment(horizontal="center", vertical="top")
            if isinstance(cell.value, (int, float)):
                cell.number_format = "0.0%"
        for column in (first_metric + 4, first_metric + 5):
            cell = results.cell(row, column)
            cell.alignment = Alignment(horizontal="center", vertical="top")
            if isinstance(cell.value, (int, float)):
                cell.number_format = "0.00"
    results.freeze_panes = "A2"
    results.auto_filter.ref = results.dimensions
    widths = [8, 12, *([16] if with_law else []), 10, 50, 50, 60, 36, 22, 22, 22, 24, 14, 14]
    for index, width in enumerate(widths, start=1):
        results.column_dimensions[results.cell(1, index).column_letter].width = width

    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


def _cited_sources(item: dict) -> str:
    """2026.11.20(sooyeon.choi) 수정 - 생성 답변의 인용 출처([번호] 문서명 · 조항 · 쪽), 한 줄에 하나."""
    detail = _parse_json(item.get("citation_detail_json"), {})
    cited = detail.get("cited") if isinstance(detail, dict) else None
    lines = []
    for citation in cited if isinstance(cited, list) else []:
        if not isinstance(citation, dict):
            continue
        path = citation.get("header_path") if isinstance(citation.get("header_path"), list) else []
        parts = [str(citation.get("original_filename") or ""), str(path[-1]) if path else ""]
        if citation.get("page_number") is not None:
            parts.append(f"p.{citation['page_number']}")
        number = citation.get("citation_id")
        lines.append(f"[{number}] " * (number is not None) + " · ".join(part for part in parts if part))
    return "\n".join(lines)


def _append_law_table(sheet, primary_metrics: list[dict], law_metrics: list[dict], start_row: int) -> int:
    """2026.11.20(sooyeon.choi) 수정 - 합본 실행의 법령별 주요 지표(같은 실행 항목을 법령으로 나눈 참고 값)."""
    headers = ["구분", *[metric.get("label") or metric.get("key") for metric in primary_metrics], "문항 수"]
    sheet.cell(start_row, 1, "법령별 주요 지표 (참고 · 합격 판정은 전체 값)")
    sheet.cell(start_row, 1).font = Font(bold=True, color="FFFFFF")
    sheet.cell(start_row, 1).fill = PatternFill("solid", fgColor="4472C4")
    sheet.merge_cells(start_row=start_row, start_column=1, end_row=start_row, end_column=len(headers))
    sheet.append(headers)
    for cell in sheet[start_row + 1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9EAF7")
        cell.alignment = Alignment(horizontal="center", wrap_text=True)

    def value_of(metric: dict, row: dict | None) -> Any:
        if metric.get("status") == "not_measured" or row is None:
            return "미측정" if metric.get("status") == "not_measured" else "-"
        value = row.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return "-"
        return _seconds(value) if metric.get("unit") == "ms" else float(value)

    total = max((metric.get("total_count") or 0 for metric in primary_metrics), default=0)
    rows = [("전체 (판정 기준)", {metric["key"]: metric for metric in primary_metrics}, total)]
    for law in law_metrics:
        counts = [m.get("total_count") or 0 for m in (law.get("metrics") or {}).values()]
        rows.append((law.get("law") or "", law.get("metrics") or {}, max(counts, default=0)))
    for label, by_key, count in rows:
        sheet.append([label, *[value_of(metric, by_key.get(metric["key"])) for metric in primary_metrics], count])
        for column, metric in enumerate(primary_metrics, start=2):
            cell = sheet.cell(sheet.max_row, column)
            if isinstance(cell.value, (int, float)):
                cell.number_format = "0.00" if metric.get("unit") == "ms" else "0.0%"
    sheet.cell(start_row + 2, 1).font = Font(bold=True)
    return sheet.max_row + 2


def build_run_excel_filename(run: dict, now: datetime | None = None) -> str:
    """평가 실행 결과 다운로드 파일명을 생성한다."""
    fallback = f"dataset_{run.get('dataset_id', '')}"
    name = _safe_filename_name(run.get("dataset_name"), fallback)
    timestamp = (now or datetime.now(KST)).strftime("%Y%m%d_%H%M%S")
    return f"평가실행_{name}_run_{run.get('run_id')}_{timestamp}.xlsx"
