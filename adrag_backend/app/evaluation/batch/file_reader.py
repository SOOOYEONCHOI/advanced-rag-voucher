# 2026.11.18(sooyeon.choi) 추가 - 일괄 질의 파일(CSV/xlsx) 읽기·검증 (설계 6.1, REQ-B-01)
"""질의 파일을 읽어 [{query_key, query_text}] 목록과 행 단위 오류를 반환한다.

- CSV 인코딩: utf-8-sig(BOM) → utf-8 → cp949 순으로 판별
- xlsx: 첫 시트, 첫 행이 머리글
- 열 이름: 질의ID/query_id/id, 질의문/질의/query/question (공백·대소문자 무시)
- 검증: 행 수 1~max_rows, 질의ID 중복 금지, 빈 값 금지, 질의문 max_chars 이하
"""

import csv
import io
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

KEY_ALIASES = ("질의id", "질의번호", "query_id", "queryid", "id", "qid")
TEXT_ALIASES = ("질의문", "질의", "질문", "query", "question", "query_text")
_CSV_ENCODINGS = ("utf-8-sig", "utf-8", "cp949")


@dataclass
class QueryFileResult:
    items: List[Dict[str, str]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)


class QueryFileError(ValueError):
    """파일 자체를 읽을 수 없을 때(형식·인코딩·머리글)."""


def _norm_header(value: Any) -> str:
    return "".join(str(value or "").split()).lower()


def _find_column(headers: Sequence[str], aliases: Sequence[str]) -> Optional[int]:
    normalized = [_norm_header(h) for h in headers]
    for alias in aliases:
        if alias in normalized:
            return normalized.index(alias)
    return None


def _decode_csv(content: bytes) -> str:
    for encoding in _CSV_ENCODINGS:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise QueryFileError("CSV 인코딩을 판별할 수 없습니다(UTF-8 또는 CP949로 저장해 주세요)")


def read_table(filename: str, content: bytes, sheet_name: Optional[str] = None) -> List[List[Any]]:
    """CSV/xlsx를 행 목록(첫 행 머리글 포함)으로 읽는다."""
    lower = (filename or "").lower()
    if lower.endswith(".csv"):
        text = _decode_csv(content)
        return [row for row in csv.reader(io.StringIO(text))]
    if lower.endswith(".xlsx"):
        from openpyxl import load_workbook

        try:
            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception as exc:
            raise QueryFileError("xlsx 파일을 열 수 없습니다") from exc
        try:
            # 2026.11.19(sooyeon.choi) 수정 - sheet_name 시트가 있으면 그 시트, 없으면 첫 시트
            sheet = workbook[sheet_name] if sheet_name and sheet_name in workbook.sheetnames else workbook.worksheets[0]
            return [list(row) for row in sheet.iter_rows(values_only=True)]
        finally:
            workbook.close()
    raise QueryFileError("CSV 또는 xlsx 파일만 업로드할 수 있습니다")


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # 엑셀 숫자 ID(1.0 → "1")
    return str(value).strip()


def parse_query_rows(rows: List[List[Any]], *, max_rows: int, max_chars: int) -> QueryFileResult:
    if not rows:
        raise QueryFileError("빈 파일입니다")
    headers = [_cell_text(h) for h in rows[0]]
    key_col = _find_column(headers, KEY_ALIASES)
    text_col = _find_column(headers, TEXT_ALIASES)
    if key_col is None or text_col is None:
        raise QueryFileError("머리글에 '질의ID'와 '질의문' 열이 필요합니다")

    result = QueryFileResult()
    seen: Dict[str, int] = {}
    for row_no, row in enumerate(rows[1:], start=2):
        cells = list(row) + [None] * (max(key_col, text_col) + 1 - len(row))
        key = _cell_text(cells[key_col])
        text = _cell_text(cells[text_col])
        if not key and not text:
            continue  # 빈 행은 건너뜀
        if not key:
            result.errors.append({"row": row_no, "column": "질의ID", "reason": "빈 값"})
            continue
        if not text:
            result.errors.append({"row": row_no, "column": "질의문", "reason": "빈 값"})
            continue
        if len(text) > max_chars:
            result.errors.append({"row": row_no, "column": "질의문", "reason": f"{max_chars}자 초과"})
            continue
        if key in seen:
            result.errors.append({
                "row": row_no, "column": "질의ID", "reason": f"중복({seen[key]}행과 같음)",
            })
            continue
        seen[key] = row_no
        result.items.append({"query_key": key, "query_text": text})

    if not result.items and not result.errors:
        result.errors.append({"row": None, "column": None, "reason": "질의 행이 없습니다"})
    if len(result.items) > max_rows:
        result.errors.append({
            "row": None, "column": None, "reason": f"질의는 최대 {max_rows}건까지 등록할 수 있습니다",
        })
    return result


def read_query_file(filename: str, content: bytes, *, max_rows: int, max_chars: int) -> QueryFileResult:
    return parse_query_rows(read_table(filename, content), max_rows=max_rows, max_chars=max_chars)
