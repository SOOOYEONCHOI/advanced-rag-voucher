# 2026.11.18(sooyeon.choi) 추가 - 정답 근거 자동 매칭 (설계 7장, F-10·F-11, REQ-B-09)
"""시험기관 정답(근거 문서명·위치·내용) → 우리 청크 ID 후보.

절차
1. 문서 찾기: 문서명을 정규화(확장자·공백·괄호·버전 표기 제거, 소문자)해 original_filename/title과 비교.
   일치 → 포함 관계 → 없으면 컬렉션 전체를 후보로(doc_match='none' 경고)
2. 후보 청크: 그 문서의 활성 버전 청크. 위치에 시트명·단계 번호가 있으면 먼저 좁히고, 0건이면 문서 전체로 되돌림
3. 점수: 정규화(NFKC·소문자·공백·기호 제거)한 문자 3-gram 포함률 = |근거 ∩ 청크| / |근거|
   (근거가 6자 미만이면 부분 문자열 포함 여부 1/0)
4. 판정: 포함률 ≥ threshold 인 청크 전부(점수순). 없으면 unmatched + 최고점 상위 3개를 참고로 표시
"""

import re
import unicodedata
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.evaluation.batch.file_reader import QueryFileError, read_table

GOLD_KEY_ALIASES = ("질의id", "질의번호", "query_id", "queryid", "id", "qid")
GOLD_SEQ_ALIASES = ("근거순번", "순번", "evidence_seq", "seq")
GOLD_DOC_ALIASES = ("근거문서명", "근거문서", "문서명", "source_doc", "document", "doc")
GOLD_LOC_ALIASES = ("근거위치", "위치", "출처", "source_loc", "location")
GOLD_TEXT_ALIASES = ("근거내용", "근거", "내용", "evidence", "evidence_text", "text")
# 2026.11.19(sooyeon.choi) 추가 - 시험 데이터셋(정답 근거 시트) 호환: 청크ID가 있으면 자동 매칭 없이 바로 확정
GOLD_IDS_ALIASES = ("청크id", "정답청크id", "근거청크id", "확정청크id", "chunk_id", "chunk_ids", "chunkid")
GOLD_ARTICLE_ALIASES = ("근거조항", "조항", "article")
GOLD_PAGE_ALIASES = ("페이지", "page", "쪽")

MAX_CANDIDATES = 10
REFERENCE_CANDIDATES = 3
_SHORT_EVIDENCE_CHARS = 6

_EXT = re.compile(r"\.(xlsx|xlsm|xls|csv|pdf|docx?|pptx?|hwp|dxf|txt)$", re.IGNORECASE)
_VERSION_MARK = re.compile(r"(?:_|\s|\()?(?:rev|ver|v)\s*\.?\s*\d+(?:\.\d+)*\)?", re.IGNORECASE)
_BRACKETS = re.compile(r"[\(\[\{（【].*?[\)\]\}）】]")
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)
_STEP = re.compile(r"(?:단계|step|no\.?)\s*(\d+)|(\d+)\s*단계", re.IGNORECASE)


def normalize_text(value: Any) -> str:
    """NFKC(전각→반각) + 소문자 + 공백·기호 제거."""
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return _NON_WORD.sub("", text)


def normalize_doc_name(value: Any) -> str:
    name = unicodedata.normalize("NFKC", str(value or "")).strip()
    name = _EXT.sub("", name)
    name = _BRACKETS.sub("", name)
    name = _VERSION_MARK.sub("", name)
    return normalize_text(name)


def trigrams(text: str) -> Set[str]:
    if len(text) < 3:
        return {text} if text else set()
    return {text[i:i + 3] for i in range(len(text) - 2)}


def containment(evidence: str, chunk_text: str) -> float:
    """근거 내용이 청크에 들어 있는 비율(0~1). 입력은 normalize_text 결과."""
    if not evidence or not chunk_text:
        return 0.0
    if len(evidence) < _SHORT_EVIDENCE_CHARS:
        return 1.0 if evidence in chunk_text else 0.0
    grams = trigrams(evidence)
    return len(grams & trigrams(chunk_text)) / len(grams)


def parse_step_no(location: Any) -> Optional[int]:
    match = _STEP.search(str(location or ""))
    if not match:
        return None
    return int(match.group(1) or match.group(2))


def find_documents(source_doc: Any, documents: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], str]:
    """문서명 → (후보 문서, 'exact'|'partial'|'none')."""
    target = normalize_doc_name(source_doc)
    if not target:
        return documents, "none"

    def names(doc):
        return [n for n in (normalize_doc_name(doc.get("original_filename")), normalize_doc_name(doc.get("title"))) if n]

    exact = [d for d in documents if target in names(d)]
    if exact:
        return exact, "exact"
    partial = [d for d in documents if any(target in n or n in target for n in names(d))]
    if partial:
        return partial, "partial"
    return documents, "none"


def _narrow_by_location(chunks: List[Dict[str, Any]], location: Any) -> Tuple[List[Dict[str, Any]], bool]:
    if not location:
        return chunks, False
    narrowed = chunks
    loc_norm = normalize_text(location)
    sheet_hits = [c for c in narrowed if c.get("sheet_name") and normalize_text(c["sheet_name"]) in loc_norm]
    if sheet_hits:
        narrowed = sheet_hits
    step_no = parse_step_no(location)
    if step_no is not None:
        step_hits = [c for c in narrowed if c.get("step_no") == step_no]
        if step_hits:
            narrowed = step_hits
    if narrowed is chunks or not narrowed:
        return chunks, False
    return narrowed, True


def _candidate(chunk: Dict[str, Any], score: float, doc_names: Dict[str, str]) -> Dict[str, Any]:
    return {
        "chunk_id": chunk["chunk_id"],
        "score": round(score, 4),
        "document_id": chunk.get("document_id"),
        "filename": doc_names.get(chunk.get("document_id"), ""),
        "sheet_name": chunk.get("sheet_name"),
        "step_no": chunk.get("step_no"),
        "text": (chunk.get("chunk_text") or "")[:500],
    }


def match_evidence(
    evidence: Dict[str, Any],
    documents: List[Dict[str, Any]],
    chunks_by_doc: Dict[str, List[Dict[str, Any]]],
    threshold: float,
) -> Dict[str, Any]:
    """근거 1건 → {match_status, matched_json}. matched_json.auto_ids는 임계값 이상 후보 ID."""
    doc_candidates, doc_match = find_documents(evidence.get("source_doc"), documents)
    chunks = [c for d in doc_candidates for c in chunks_by_doc.get(d["document_id"], [])]
    narrowed, used_location = _narrow_by_location(chunks, evidence.get("source_loc"))
    doc_names = {d["document_id"]: d.get("original_filename") or d.get("title") or "" for d in documents}

    target = normalize_text(evidence.get("evidence_text"))

    def score_all(pool):
        return sorted(
            ((containment(target, normalize_text(c.get("chunk_text"))), c) for c in pool),
            key=lambda pair: (-pair[0], pair[1]["chunk_id"]),
        )

    scored = score_all(narrowed)
    passed = [(s, c) for s, c in scored if s >= threshold]
    if not passed and used_location:
        # 위치로 좁힌 범위에 없으면 문서 전체로 되돌려 다시 본다(위치 표기가 우리 청크 단위와 다를 수 있음)
        scored = score_all(chunks)
        passed = [(s, c) for s, c in scored if s >= threshold]
        used_location = False

    if passed:
        candidates = [_candidate(c, s, doc_names) for s, c in passed[:MAX_CANDIDATES]]
        status = "auto"
    else:
        candidates = [_candidate(c, s, doc_names) for s, c in scored[:REFERENCE_CANDIDATES]]
        status = "unmatched"
    return {
        "match_status": status,
        "matched_json": {
            "doc_match": doc_match,
            "location_used": used_location,
            "threshold": threshold,
            "candidates": candidates,
            "auto_ids": [c["chunk_id"] for c in candidates] if status == "auto" else [],
        },
    }


# ── 정답 파일 읽기 ───────────────────────────────────────────────────────────

def _find(headers: Sequence[str], aliases: Sequence[str]) -> Optional[int]:
    normalized = ["".join(str(h or "").split()).lower() for h in headers]
    for alias in aliases:
        if alias in normalized:
            return normalized.index(alias)
    return None


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def read_gold_file(filename: str, content: bytes, known_keys: Sequence[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """정답 파일(설계 7.1) → (근거 행, 오류 행). 질의ID는 작업에 있는 것만 허용."""
    from app.evaluation.batch.recall import parse_chunk_ids

    rows = read_table(filename, content, sheet_name="정답 근거")  # 2026.11.19(sooyeon.choi) 수정 - 시험 데이터셋 시트 우선
    if not rows:
        raise QueryFileError("빈 파일입니다")
    headers = [_cell(h) for h in rows[0]]
    cols = {
        "key": _find(headers, GOLD_KEY_ALIASES),
        "seq": _find(headers, GOLD_SEQ_ALIASES),
        "doc": _find(headers, GOLD_DOC_ALIASES),
        "loc": _find(headers, GOLD_LOC_ALIASES),
        "text": _find(headers, GOLD_TEXT_ALIASES),
        # 2026.11.19(sooyeon.choi) 추가
        "ids": _find(headers, GOLD_IDS_ALIASES),
        "article": _find(headers, GOLD_ARTICLE_ALIASES),
        "page": _find(headers, GOLD_PAGE_ALIASES),
    }
    if cols["key"] is None or cols["doc"] is None or (cols["text"] is None and cols["ids"] is None):
        raise QueryFileError("머리글에 '질의ID', '근거 문서명', '근거 내용'(또는 '청크ID') 열이 필요합니다")

    known = set(known_keys)
    width = max(i for i in cols.values() if i is not None) + 1
    evidences: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    next_seq: Dict[str, int] = {}
    seen: Dict[Tuple[str, int], int] = {}
    for row_no, row in enumerate(rows[1:], start=2):
        cells = list(row) + [None] * (width - len(row))

        def get(name):
            index = cols[name]
            return _cell(cells[index]) if index is not None else ""

        key, text = get("key"), get("text")
        chunk_ids = parse_chunk_ids(get("ids")) if cols["ids"] is not None else []
        if not key and not text and not chunk_ids:
            continue
        if not key:
            errors.append({"row": row_no, "column": "질의ID", "reason": "빈 값"})
            continue
        if key not in known:
            errors.append({"row": row_no, "column": "질의ID", "reason": "작업에 없는 질의ID"})
            continue
        if not text and not chunk_ids:
            errors.append({"row": row_no, "column": "근거 내용", "reason": "빈 값"})
            continue
        seq_text = get("seq")
        if seq_text:
            if not seq_text.isdigit():
                errors.append({"row": row_no, "column": "근거순번", "reason": "숫자가 아님"})
                continue
            seq = int(seq_text)
        else:
            seq = next_seq.get(key, 0) + 1
        next_seq[key] = max(next_seq.get(key, 0), seq)
        if (key, seq) in seen:
            errors.append({"row": row_no, "column": "근거순번", "reason": f"중복({seen[(key, seq)]}행과 같음)"})
            continue
        seen[(key, seq)] = row_no
        # 2026.11.19(sooyeon.choi) 추가 - 위치 열이 없으면 '근거 조항 · p.페이지'로 만든다
        location = get("loc") or " · ".join(
            part for part in (get("article"), f"p.{get('page')}" if get("page") else "") if part
        )
        evidences.append({
            "query_key": key,
            "evidence_seq": seq,
            "source_doc": get("doc") or None,
            "source_loc": location or None,
            "evidence_text": text,
            "chunk_ids": chunk_ids,
        })
    if not evidences and not errors:
        errors.append({"row": None, "column": None, "reason": "근거 행이 없습니다"})
    return evidences, errors


def match_all(
    evidences: List[Dict[str, Any]],
    documents: List[Dict[str, Any]],
    chunks: List[Dict[str, Any]],
    threshold: float,
) -> List[Dict[str, Any]]:
    chunks_by_doc: Dict[str, List[Dict[str, Any]]] = {}
    for chunk in chunks:
        chunks_by_doc.setdefault(chunk["document_id"], []).append(chunk)
    output = []
    for ev in evidences:
        # 2026.11.19(sooyeon.choi) 추가 - 청크ID가 주어진 근거는 매칭 없이 확정(시험 정답 데이터)
        if ev.get("chunk_ids"):
            output.append({
                **ev,
                "match_status": "confirmed",
                "confirmed_ids": list(ev["chunk_ids"]),
                "matched_json": {
                    "doc_match": "direct", "location_used": None, "threshold": threshold,
                    "candidates": [], "auto_ids": list(ev["chunk_ids"]),
                },
            })
            continue
        output.append({**ev, **match_evidence(ev, documents, chunks_by_doc, threshold)})
    return output


# ── 검토 Excel 읽기 (설계 6.7 gold-review 업로드) ────────────────────────────
# 2026.11.18(sooyeon.choi) 추가

_EXCLUDE_MARKS = {"y", "yes", "o", "1", "true", "예", "제외", "v"}


def read_gold_review(content: bytes) -> List[Dict[str, Any]]:
    """검토 Excel → [{query_key, evidence_seq, confirmed_ids, excluded, row}]."""
    import io

    from openpyxl import load_workbook

    from app.evaluation.batch.recall import parse_chunk_ids

    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise QueryFileError("검토 Excel(xlsx)을 열 수 없습니다") from exc
    try:
        sheet = workbook["검토"] if "검토" in workbook.sheetnames else workbook.worksheets[0]
        rows = [list(r) for r in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()
    if not rows:
        raise QueryFileError("빈 파일입니다")
    headers = ["".join(str(h or "").split()) for h in rows[0]]

    def col(name):
        key = "".join(name.split())
        return headers.index(key) if key in headers else None

    key_col, seq_col, ids_col, ex_col = col("질의ID"), col("근거순번"), col("확정 청크ID"), col("제외(Y)")
    if None in (key_col, seq_col, ids_col):
        raise QueryFileError("검토 시트에 '질의ID', '근거순번', '확정 청크ID' 열이 필요합니다")
    output = []
    for row_no, row in enumerate(rows[1:], start=2):
        cells = list(row) + [None] * (len(headers) - len(row))
        key = _cell(cells[key_col])
        if not key:
            continue
        seq_text = _cell(cells[seq_col])
        output.append({
            "row": row_no,
            "query_key": key,
            "evidence_seq": int(seq_text) if seq_text.isdigit() else None,
            "confirmed_ids": parse_chunk_ids(cells[ids_col]),
            "excluded": ex_col is not None and _cell(cells[ex_col]).lower() in _EXCLUDE_MARKS,
        })
    return output
