"""파싱·청킹 회귀 기준선 생성 공통 모듈.

2026.09.09(sooyeon.choi) 추가 - 목차 기반 논리 구조화(SFR-044~051) 착수 전
  현행 파이프라인 동작을 고정하기 위한 기준선. AC-051-1 대응.

Docling 파싱은 결정적이다(동일 문서 반복 파싱 시 헤딩 수 완전 일치, AC-051-2).
따라서 저장된 중간 산출물을 픽스처로 고정값 비교가 가능하다.

픽스처 종류는 두 가지이며, 커버리지가 서로 다르다.

  json : 파서 원본 응답(docling-parser/app/results/*_result.json)
         DoclingApiLoader._map_result → DocumentChunkingProcessor.process
         헤딩 제거까지 포함하므로 SFR-046(유형별 헤딩 보존 분기)의 영향이 드러난다.

  md   : 백엔드가 저장한 파싱 결과(instance/parsed_md/*.md)
         헤딩 제거 이후 상태라 청킹 경로만 덮지만,
         instance/data의 원본 PDF와 짝지어 북마크 정답을 얻을 수 있어
         SFR-048(법령 조문 경계 보정)의 수용 기준 검증에 쓰인다.

두 종류 모두 실제 업무 문서라 VCS에 포함하지 않는다. 기준선 JSON만 커밋한다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# 기준선 스키마 버전. 항목 구조가 바뀌면 올린다.
BASELINE_SCHEMA = "parse-baseline/1.1"

BASELINE_PATH = Path(__file__).with_name("baseline_parse_snapshot.json")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = Path(__file__).resolve().parents[2]

_DEFAULT_JSON_DIR = _REPO_ROOT / "docling-parser" / "app" / "results"
_DEFAULT_MD_DIR = _BACKEND_ROOT / "instance" / "parsed_md"
_DEFAULT_PDF_DIR = _BACKEND_ROOT / "instance" / "data"

# 6페이지 미만은 구조가 없어 회귀 판별력이 낮다.
MIN_PAGES = 6

_ARTICLE_IN_PATH = re.compile(r"제\s*(\d+)\s*조")
_ARTICLE_IN_BOOKMARK = re.compile(r"^\s*제\s*(\d+)\s*조")
_MD_PAGE_RE = re.compile(r"<!--\s*page\s+(\d+|\?)\s*-->\n?")
_MD_PAGE_SEP_RE = re.compile(r"\n\n---\n\n\Z")


def _dir_from_env(var: str, default: Path) -> Path:
    override = os.environ.get(var)
    return Path(override) if override else default


def json_fixture_dir() -> Path:
    return _dir_from_env("PARSE_FIXTURE_JSON_DIR", _DEFAULT_JSON_DIR)


def md_fixture_dir() -> Path:
    return _dir_from_env("PARSE_FIXTURE_MD_DIR", _DEFAULT_MD_DIR)


def pdf_fixture_dir() -> Path:
    return _dir_from_env("PARSE_FIXTURE_PDF_DIR", _DEFAULT_PDF_DIR)


@dataclass(frozen=True)
class Fixture:
    """중복 제거된 픽스처 1건."""

    doc_key: str          # 내용 해시. 파일명이 job UUID라 내용으로 식별한다.
    kind: str             # "json" | "md"
    label: str
    page_count: int
    md_meta: list[dict[str, Any]]
    source_files: list[str] = field(default_factory=list)
    # md 픽스처에만 존재하는 북마크 정답 (SFR-048 검증용)
    bookmark_articles: list[int] | None = None
    bookmark_total: int | None = None


def _label_of(texts: Iterable[str]) -> str:
    for text in texts:
        cleaned = " ".join((text or "").split())
        cleaned = re.sub(r"<!--\s*image\s*-->", "", cleaned).strip()
        cleaned = re.sub(r"^#+\s*", "", cleaned)
        if len(cleaned) >= 8:
            return cleaned[:48]
    return "(제목 없음)"


def _content_key(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


# ── json 픽스처 ─────────────────────────────────────────────────────────────

def _discover_json_fixtures() -> list[Fixture]:
    root = json_fixture_dir()
    if not root.is_dir():
        return []

    # 지연 import: 픽스처가 없으면 백엔드 모듈을 건드리지 않는다.
    from app.parsers.loaders.docling_loader import DoclingApiLoader

    loader = DoclingApiLoader(host="http://baseline.invalid")

    grouped: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("*_result.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        pages = payload.get("pages")
        if not pages or len(pages) < MIN_PAGES:
            continue
        key = _content_key(pages)
        entry = grouped.setdefault(key, {"payload": payload, "pages": pages, "files": []})
        entry["files"].append(path.name)

    fixtures: list[Fixture] = []
    for key, entry in grouped.items():
        md_meta = loader._map_result(entry["payload"], f"{key}.pdf", "pdf")
        fixtures.append(
            Fixture(
                doc_key=f"json:{key}",
                kind="json",
                label=_label_of(p.get("markdown", "") for p in entry["pages"][:3]),
                page_count=len(entry["pages"]),
                md_meta=md_meta,
                source_files=sorted(entry["files"]),
            )
        )
    return fixtures


# ── md 픽스처 + 북마크 정답 ─────────────────────────────────────────────────

def _parse_saved_markdown(text: str) -> list[tuple[str, str]] | None:
    """_save_markdown이 기록한 형식을 무손실로 되돌린다."""
    parts = _MD_PAGE_RE.split(text)
    if len(parts) < 3:
        return None
    entries = [
        (parts[i], _MD_PAGE_SEP_RE.sub("", parts[i + 1]))
        for i in range(1, len(parts) - 1, 2)
    ]
    rejoined = "\n\n---\n\n".join(f"<!-- page {p} -->\n{b}" for p, b in entries)
    # 복원이 정확하지 않으면 기준선에 넣지 않는다.
    return entries if rejoined == text else None


def _is_spreadsheet_markdown(entries: list[tuple[str, str]]) -> bool:
    """저장된 마크다운이 Excel(시트 단위) 결과인지 판정한다."""
    sheet_pages = sum(1 for _, body in entries if body.lstrip().startswith("시트:"))
    return sheet_pages * 2 >= len(entries)


def _bookmark_index() -> dict[int, dict[str, Any]]:
    """원본 PDF를 페이지 수로 색인한 북마크 정답. 모호하면 제외한다."""
    root = pdf_fixture_dir()
    if not root.is_dir():
        return {}
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return {}

    by_pages: dict[int, list[dict[str, Any]]] = {}
    for path in sorted(root.rglob("*.pdf")):
        try:
            doc = fitz.open(path)
        except Exception:
            continue
        try:
            toc = doc.get_toc()
            page_count = len(doc)
        finally:
            doc.close()
        if page_count < MIN_PAGES or not toc:
            continue
        articles = sorted(
            {
                int(m.group(1))
                for _, title, _ in toc
                if (m := _ARTICLE_IN_BOOKMARK.match(title.strip()))
            }
        )
        by_pages.setdefault(page_count, []).append(
            {"articles": articles, "total": len(toc)}
        )

    index: dict[int, dict[str, Any]] = {}
    for page_count, candidates in by_pages.items():
        distinct = {(tuple(c["articles"]), c["total"]) for c in candidates}
        # 같은 페이지 수에 서로 다른 북마크가 있으면 짝을 확정할 수 없다.
        if len(distinct) == 1:
            index[page_count] = candidates[0]
    return index


def _discover_md_fixtures() -> list[Fixture]:
    root = md_fixture_dir()
    if not root.is_dir():
        return []

    bookmarks = _bookmark_index()

    grouped: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        entries = _parse_saved_markdown(text)
        if not entries or len(entries) < MIN_PAGES:
            continue
        if _is_spreadsheet_markdown(entries):
            # OOXML Excel은 StructuredSpreadsheet 경로를 쓰므로 본 기준선의 범위 밖이다.
            # PDF 경로로 재처리하면 의미 없는 결과가 나오므로 제외한다.
            continue
        key = _content_key([list(e) for e in entries])
        grouped.setdefault(key, {"entries": entries, "files": []})["files"].append(path.name)

    fixtures: list[Fixture] = []
    for key, entry in grouped.items():
        entries = entry["entries"]
        page_count = len(entries)
        md_meta = [
            {
                "text": body,
                "metadata": {
                    "page": int(page) if page.isdigit() else None,
                    "page_count": page_count,
                    "file_path": f"{key}.pdf",
                    "file_type": "pdf",
                },
            }
            for page, body in entries
        ]
        truth = bookmarks.get(page_count)
        fixtures.append(
            Fixture(
                doc_key=f"md:{key}",
                kind="md",
                label=_label_of(body for _, body in entries[:3]),
                page_count=page_count,
                md_meta=md_meta,
                source_files=sorted(entry["files"]),
                bookmark_articles=truth["articles"] if truth else None,
                bookmark_total=truth["total"] if truth else None,
            )
        )
    return fixtures


def discover_fixtures() -> list[Fixture]:
    fixtures = _discover_json_fixtures() + _discover_md_fixtures()
    # 페이지 수 내림차순 → doc_key 순. 실행 순서를 고정한다.
    fixtures.sort(key=lambda f: (-f.page_count, f.doc_key))
    return fixtures


# ── 스냅샷 ──────────────────────────────────────────────────────────────────

def _digest(values: Iterable[str]) -> str:
    h = hashlib.sha256()
    for value in values:
        h.update(value.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def snapshot_fixture(fixture: Fixture) -> dict[str, Any]:
    """픽스처 1건을 현행 파이프라인에 통과시켜 기준선 항목을 만든다."""
    from app.parsers.config import ChunkingConfig
    from app.parsers.processor import DocumentChunkingProcessor

    source_name = f"{fixture.doc_key.split(':', 1)[1]}.pdf"
    result = DocumentChunkingProcessor(ChunkingConfig()).process(
        source_name, md_meta=fixture.md_meta
    )
    chunks = result["chunks"]

    header_paths: list[str] = []
    articles: set[int] = set()
    pages_seen: list[int] = []
    for chunk in chunks:
        meta = chunk.metadata or {}
        path = meta.get("header_path")
        if path:
            header_paths.append(str(path))
            if m := _ARTICLE_IN_PATH.search(str(path)):
                articles.add(int(m.group(1)))
        page = meta.get("page_start") or meta.get("page")
        if isinstance(page, int):
            pages_seen.append(page)

    entry: dict[str, Any] = {
        "kind": fixture.kind,
        "label": fixture.label,
        "source_files": fixture.source_files,
        "page_count": fixture.page_count,
        "doc_type": result["doc_type"],
        # 리팩터링 중 추가된 필드는 있을 때만 기록한다.
        "doc_type_source": result.get("doc_type_source"),
        "chunk_count": result["chunk_count"],
        "header_path_unique_count": len(set(header_paths)),
        "header_paths": sorted(set(header_paths)),
        "article_numbers": sorted(articles),
        "page_min": min(pages_seen) if pages_seen else None,
        "page_max": max(pages_seen) if pages_seen else None,
        # 본문이 바뀌면 text_digest, 페이지·경로 귀속이 바뀌면 attribution_digest가 깨진다.
        "text_digest": _digest(c.page_content for c in chunks),
        "attribution_digest": _digest(
            "|".join(
                str((chunk.metadata or {}).get(key))
                for key in ("page_start", "page_end", "header_path", "section_title")
            )
            for chunk in chunks
        ),
    }

    if fixture.bookmark_articles is not None:
        truth = set(fixture.bookmark_articles)
        entry["bookmark_total"] = fixture.bookmark_total
        entry["bookmark_article_count"] = len(truth)
        entry["article_detection_rate"] = (
            round(len(articles & truth) / len(truth), 4) if truth else None
        )
        entry["articles_missing_vs_bookmark"] = sorted(truth - articles)
        entry["articles_not_in_bookmark"] = sorted(articles - truth)

    return entry


def build_snapshot() -> dict[str, Any]:
    fixtures = discover_fixtures()
    return {
        "schema": BASELINE_SCHEMA,
        "fixture_count": len(fixtures),
        "documents": {f.doc_key: snapshot_fixture(f) for f in fixtures},
    }


def load_baseline() -> dict[str, Any] | None:
    if not BASELINE_PATH.is_file():
        return None
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def save_baseline(snapshot: dict[str, Any]) -> None:
    BASELINE_PATH.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
