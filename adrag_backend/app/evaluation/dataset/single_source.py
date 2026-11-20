# 2026.11.19(sooyeon.choi) 추가 - 단일 출처 평가 데이터셋 배분·검사 (eval-law-testset-design-v1.0 3장)
"""질의 1건 = 출처(청크) 1곳. 질문 유형(사실·절차·비교·멀티홉)을 나누지 않는다.

생성 방식(gen_config.generation_mode)
- law_article   : 법령 조항 단위로 고르게 배분. 부칙·목차·머리글만 있는 청크 제외, 별표는 선택(기본 보충용)
- single_section: 일반 문서. 문서·섹션 단위로 고르게 배분

배분 규칙(공통)
1. 단위(조항/섹션)를 문서 순서대로 놓는다(법률 → 시행령 → 시행규칙 → 그 밖의 문서, 같은 종류는 파일명 순).
2. 1바퀴: 단위마다 청크 1개(본문이 긴 것 우선). 목표 수가 단위 수보다 적으면 같은 간격으로 단위를 고른다.
3. 모자라면 2바퀴(단위의 두 번째 청크) → … → 보충 단위(별표) → 같은 청크의 다른 질문(variant 1, 최대 max_questions_per_chunk)
4. 목표 수를 넘는 뒤쪽 후보는 생성 실패 시 대체 후보로 쓴다.
"""

import ast
import json
import re
from collections import Counter, OrderedDict
from typing import Any, Dict, List, Optional, Sequence, Tuple

GENERATION_MODE_TYPED = "typed"
GENERATION_MODE_LAW = "law_article"
GENERATION_MODE_SECTION = "single_section"
SINGLE_SOURCE_MODES = (GENERATION_MODE_LAW, GENERATION_MODE_SECTION)
QUESTION_TYPE_BY_MODE = {GENERATION_MODE_LAW: "law", GENERATION_MODE_SECTION: "general"}

DEFAULT_LAW_MIN_BODY_CHARS = 80
DEFAULT_ARTICLE_REF_RATIO = 0.3
DEFAULT_MAX_QUESTIONS_PER_CHUNK = 2

_ARTICLE = re.compile(r"^제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
_ANNEX = re.compile(r"^(별표|별지)")
_ARTICLE_REF = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_SPACES = re.compile(r"[\s,]+")
_EXT = re.compile(r"\.[A-Za-z0-9]{2,5}$")
# 부칙 시작 판단: 본문 조항이 이 번호 이상까지 나온 뒤 제1·2조로 되돌아가면 부칙으로 본다
_SUPPLEMENT_MIN_BODY_ARTICLE = 5
_SUPPLEMENT_RESET_MAX_ARTICLE = 2


# ── 메타데이터 해석 ─────────────────────────────────────────────────────────

def header_path_list(payload: Dict[str, Any]) -> List[str]:
    """payload.header_path → 문자열 목록(list·JSON·repr·'a > b' 모두 허용)."""
    value = payload.get("header_path")
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.startswith("["):
            for loader in (json.loads, ast.literal_eval):
                try:
                    parsed = loader(text)
                    if isinstance(parsed, (list, tuple)):
                        return [str(v).strip() for v in parsed if str(v).strip()]
                except (ValueError, SyntaxError, TypeError):
                    continue
            return []
        return [part.strip() for part in text.split(">") if part.strip()]
    return []


def law_name_from_filename(filename: Any) -> str:
    """'산업안전보건법 시행령(대통령령)(제34603호)(20260626).pdf' → '산업안전보건법 시행령'."""
    name = _EXT.sub("", str(filename or "").strip())
    for mark in ("(", "（", "["):
        if mark in name:
            name = name.split(mark, 1)[0]
    return name.strip() or str(filename or "").strip()


def _law_rank(filename: str) -> int:
    if "시행규칙" in filename:
        return 2
    if "시행령" in filename:
        return 1
    return 0


def _document_order(chunks: Sequence[Dict[str, Any]], law: bool) -> List[str]:
    names: Dict[str, str] = {}
    for chunk in chunks:
        names.setdefault(str(chunk.get("document_id") or ""), str(chunk.get("original_filename") or ""))
    return sorted(names, key=lambda doc: ((_law_rank(names[doc]) if law else 0), names[doc], doc))


def _chunk_index(chunk: Dict[str, Any]) -> int:
    try:
        return int(chunk.get("chunk_index") or 0)
    except (TypeError, ValueError):
        return 0


def body_text(chunk: Dict[str, Any]) -> str:
    """청크 본문에서 머리글 경로 줄(예: '제2장 > 제4조')과 마크다운 제목 줄을 뺀 내용."""
    header = " > ".join(header_path_list(chunk))
    lines = []
    for line in str(chunk.get("text") or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped == header or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return "\n".join(lines)


def _body_len(chunk: Dict[str, Any]) -> int:
    return len(body_text(chunk))


def _make_unit(document_id: str, label: str, header_path: List[str], chunk: Dict[str, Any], kind: str) -> Dict[str, Any]:
    return {
        "document_id": document_id,
        "original_filename": chunk.get("original_filename"),
        "law_name": law_name_from_filename(chunk.get("original_filename")),
        "label": label,
        "header_path": header_path,
        "kind": kind,
        "chunks": [],
    }


def _finish_units(units: "OrderedDict[Tuple, Dict[str, Any]]") -> List[Dict[str, Any]]:
    output = []
    for unit in units.values():
        if not unit["chunks"]:
            continue
        unit["chunks"].sort(key=lambda c: (-_body_len(c), _chunk_index(c)))
        output.append(unit)
    return output


def build_law_units(
    chunks: Sequence[Dict[str, Any]],
    *,
    min_body_chars: int = DEFAULT_LAW_MIN_BODY_CHARS,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    """법령 청크 → (조항 단위, 별표 단위, 제외 사유별 건수). 부칙·머리글 경로 없는 청크·짧은 본문 제외."""
    articles: "OrderedDict[Tuple, Dict[str, Any]]" = OrderedDict()
    annexes: "OrderedDict[Tuple, Dict[str, Any]]" = OrderedDict()
    skipped: Counter = Counter()
    by_doc: Dict[str, List[Dict[str, Any]]] = {}
    for chunk in chunks:
        by_doc.setdefault(str(chunk.get("document_id") or ""), []).append(chunk)

    for doc_id in _document_order(chunks, law=True):
        max_article = 0
        in_supplement = False
        for chunk in sorted(by_doc[doc_id], key=_chunk_index):
            path = header_path_list(chunk)
            label = path[-1] if path else str(chunk.get("section_title") or "").strip()
            if not label:
                skipped["no_article"] += 1
                continue
            if _ANNEX.match(label):
                if _body_len(chunk) < min_body_chars:
                    skipped["short"] += 1
                    continue
                unit = annexes.setdefault((doc_id, label), _make_unit(doc_id, label, path, chunk, "annex"))
                unit["chunks"].append(chunk)
                continue
            match = _ARTICLE.match(label)
            if path and path[0].startswith("부칙"):
                in_supplement = True
            elif match:
                number = int(match.group(1))
                if max_article >= _SUPPLEMENT_MIN_BODY_ARTICLE and number <= _SUPPLEMENT_RESET_MAX_ARTICLE < max_article:
                    in_supplement = True
                if not in_supplement:
                    max_article = max(max_article, number)
            if in_supplement:
                skipped["supplement"] += 1
                continue
            if not match:
                skipped["no_article"] += 1
                continue
            if _body_len(chunk) < min_body_chars:
                skipped["short"] += 1
                continue
            unit = articles.setdefault((doc_id, tuple(path) or (label,)), _make_unit(doc_id, label, path, chunk, "article"))
            unit["chunks"].append(chunk)
    return _finish_units(articles), _finish_units(annexes), dict(skipped)


def build_section_units(
    chunks: Sequence[Dict[str, Any]],
    *,
    min_chars: int = 200,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """일반 문서 청크 → 섹션 단위(header_path → section_title → 페이지 순으로 묶음)."""
    units: "OrderedDict[Tuple, Dict[str, Any]]" = OrderedDict()
    skipped: Counter = Counter()
    by_doc: Dict[str, List[Dict[str, Any]]] = {}
    for chunk in chunks:
        by_doc.setdefault(str(chunk.get("document_id") or ""), []).append(chunk)
    for doc_id in _document_order(chunks, law=False):
        for chunk in sorted(by_doc[doc_id], key=_chunk_index):
            if len(str(chunk.get("text") or "").strip()) < min_chars:
                skipped["short"] += 1
                continue
            path = header_path_list(chunk)
            section = str(chunk.get("section_title") or "").strip()
            if path:
                key, label = tuple(path), path[-1]
            elif section:
                key, label = (section,), section
            else:
                page = chunk.get("page_number")
                key = (f"p.{page}",) if page not in (None, "") else (f"#{_chunk_index(chunk)}",)
                label = key[0]
            unit = units.setdefault((doc_id, key), _make_unit(doc_id, label, path, chunk, "section"))
            unit["chunks"].append(chunk)
    return _finish_units(units), dict(skipped)


# ── 배분 ────────────────────────────────────────────────────────────────────

def _spread(candidates: List[Any], need: int) -> List[Any]:
    """need개를 같은 간격으로 앞에 두고 나머지는 원래 순서로 뒤에 둔다."""
    count = len(candidates)
    if need <= 0 or need >= count:
        return list(candidates)
    picked = sorted({int((i + 0.5) * count / need) for i in range(need)})
    chosen = set(picked)
    return [candidates[i] for i in picked] + [c for i, c in enumerate(candidates) if i not in chosen]


def plan_single_source_jobs(
    units: Sequence[Dict[str, Any]],
    target_count: int,
    *,
    supplement_units: Sequence[Dict[str, Any]] = (),
    max_questions_per_chunk: int = DEFAULT_MAX_QUESTIONS_PER_CHUNK,
) -> List[Dict[str, Any]]:
    """우선순위 순 작업 목록. 앞의 target_count개가 생성 대상, 나머지는 대체 후보.

    작업 = {chunk, unit, unit_order, variant}. 같은 (청크, variant)는 한 번만 나온다.
    """
    order = {id(unit): index for index, unit in enumerate(list(units) + list(supplement_units))}
    jobs: List[Dict[str, Any]] = []
    for pool in (units, supplement_units):
        round_no = 0
        while True:
            candidates = [unit for unit in pool if len(unit["chunks"]) > round_no]
            if not candidates:
                break
            for unit in _spread(candidates, target_count - len(jobs)):
                jobs.append({
                    "chunk": unit["chunks"][round_no], "unit": unit,
                    "unit_order": order[id(unit)], "variant": 0,
                })
            round_no += 1
    base = list(jobs)
    for variant in range(1, max(1, int(max_questions_per_chunk))):
        for job in _spread(base, target_count - len(jobs)):
            jobs.append({**job, "variant": variant})
    return jobs


def mention_article_flags(count: int, ratio: float) -> List[bool]:
    """count건 중 ratio 비율만큼 고르게 True(질문에 조항을 직접 언급)."""
    ratio = min(max(float(ratio), 0.0), 1.0)
    return [int((i + 1) * ratio) > int(i * ratio) for i in range(count)]


# ── 단일 출처 검사 ──────────────────────────────────────────────────────────

def _compact(text: str) -> str:
    return _SPACES.sub("", str(text or ""))


def check_single_source(question: str, answer: str, chunk_text: str) -> Optional[str]:
    """근거 청크 밖의 내용이 섞였는지 검사. 문제 없으면 None, 있으면 사유.

    - 답변의 숫자(수치·기간·금액·항목 번호)가 모두 근거 본문에 있어야 한다
    - 질문·답변의 조항 번호(제N조, 제N조의M)가 모두 근거 본문(머리글 경로 포함)에 있어야 한다
    """
    source = _compact(chunk_text)
    for number in _NUMBER.findall(str(answer or "").replace(",", "")):
        if number not in source:
            return f"답변의 숫자 '{number}'가 근거 본문에 없음"
    for match in _ARTICLE_REF.finditer(f"{question}\n{answer}"):
        ref = f"제{match.group(1)}조" + (f"의{match.group(2)}" if match.group(2) else "")
        if ref not in source:
            return f"근거 본문에 없는 조항 '{ref}' 언급"
    return None


def source_meta_for(job: Dict[str, Any], mode: str, *, article_mentioned: bool = False) -> Dict[str, Any]:
    chunk, unit = job["chunk"], job["unit"]
    meta = {
        "generation_mode": mode,
        "original_filename": chunk.get("original_filename"),
        "section_title": chunk.get("section_title"),
        "header_path": header_path_list(chunk),
        "page_number": chunk.get("page_number"),
        "document_id": chunk.get("document_id"),
        "version_no": chunk.get("version_no"),
        "chunk_index": _chunk_index(chunk),
        "unit_label": unit["label"],
        "unit_order": job["unit_order"],
        "variant": job["variant"],
    }
    if mode == GENERATION_MODE_LAW:
        meta.update({
            "law_name": unit["law_name"],
            "article": unit["label"],
            "is_annex": unit["kind"] == "annex",
            "article_mentioned": article_mentioned,
        })
    return meta
