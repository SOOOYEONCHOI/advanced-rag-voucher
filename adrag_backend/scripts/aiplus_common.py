# 2026.11.23(sooyeon.choi) 추가 - AI+ 인증 시험 스크립트 공통 모듈 (시험합의서 시험 1·2·4, R8-7)
"""시험 데이터 불러오기·컬렉션 선택·결과 저장 공통 함수.

이 모듈은 백엔드 앱(app.*)을 import하지 않는다. 시험 4 스크립트는 시험 PC에서
httpx·openpyxl만 있으면 돌아가야 하기 때문이다.

시험 데이터 파일 = 평가 > 데이터셋 > [시험 데이터셋] 다운로드 xlsx
  - '질의' 시트      : 질의ID, 질의문, 정답 답변, (합본이면) 법령, (선택) 컬렉션
  - '정답 근거' 시트 : 질의ID, 근거순번, 근거 문서명, 근거 조항, 페이지, 청크ID, 근거 내용
    청크ID = Qdrant 포인트 ID(검색 결과 chunk_id와 같은 값). 한 칸에 여러 개면 쉼표·줄바꿈으로 구분.
"""

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set

from openpyxl import load_workbook

QUERY_SHEET = "질의"
GOLD_SHEET = "정답 근거"


@dataclass
class TestQuery:
    """시험 질의 1건 (질의 시트 1행 + 정답 근거 시트의 같은 질의ID 행들)."""

    query_id: str
    question: str
    law: str = ""
    collection: str = ""
    gold_chunk_ids: Set[str] = field(default_factory=set)


def _rows(path: Path, sheet_name: str) -> List[Dict[str, str]]:
    """시트의 첫 행을 머리글로 보고 나머지 행을 {머리글: 값} 목록으로 읽는다."""
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if sheet_name not in workbook.sheetnames:
            raise SystemExit(f"'{path.name}'에 '{sheet_name}' 시트가 없습니다. 시험 데이터셋 xlsx를 지정하세요.")
        rows = workbook[sheet_name].iter_rows(values_only=True)
        headers = [str(value or "").strip() for value in next(rows, [])]
        output = []
        for values in rows:
            if not any(value not in (None, "") for value in values):
                continue
            output.append({
                header: "" if value is None else str(value).strip()
                for header, value in zip(headers, values) if header
            })
        return output
    finally:
        workbook.close()


def split_chunk_ids(value: str) -> List[str]:
    """청크ID 칸 값 → ID 목록 (쉼표·세미콜론·줄바꿈·공백 구분)."""
    return [part for part in re.split(r"[,;，\s]+", value or "") if part]


def load_testset(path: str, *, with_gold: bool = True) -> List[TestQuery]:
    """[확인 항목] 시험 데이터 및 정답 데이터를 불러오는 코드.

    질의 시트 순서대로 TestQuery 목록을 만들고, 정답 근거 시트의 청크ID를 질의ID별로 합친다.
    """
    file_path = Path(path)
    queries: List[TestQuery] = []
    by_id: Dict[str, TestQuery] = {}
    for row in _rows(file_path, QUERY_SHEET):
        query_id, question = row.get("질의ID", ""), row.get("질의문", "")
        if not query_id or not question:
            raise SystemExit(f"'{QUERY_SHEET}' 시트에 질의ID 또는 질의문이 빈 행이 있습니다: {row}")
        if query_id in by_id:
            raise SystemExit(f"질의ID가 중복됩니다: {query_id}")
        item = TestQuery(query_id, question, row.get("법령", ""), row.get("컬렉션", ""))
        queries.append(item)
        by_id[query_id] = item

    if with_gold:
        for row in _rows(file_path, GOLD_SHEET):
            item = by_id.get(row.get("질의ID", ""))
            if item is None:
                raise SystemExit(f"'{GOLD_SHEET}' 시트의 질의ID가 '{QUERY_SHEET}' 시트에 없습니다: {row.get('질의ID')}")
            item.gold_chunk_ids.update(split_chunk_ids(row.get("청크ID", "")))
    return queries


def parse_collection_map(value: Optional[str]) -> Dict[str, str]:
    """--collection-map "산업안전보건법=AIE_산업안전보건법,중대재해처벌법=AIE_중대재해처벌법" → dict."""
    mapping: Dict[str, str] = {}
    for pair in (value or "").split(","):
        if pair.strip():
            law, _, collection = pair.partition("=")
            if not collection.strip():
                raise SystemExit(f"--collection-map 형식 오류: {pair} (법령=컬렉션)")
            mapping[law.strip()] = collection.strip()
    return mapping


def assign_collections(
    queries: Iterable[TestQuery], default: Optional[str], mapping: Dict[str, str]
) -> None:
    """질의별 검색 컬렉션을 정한다. 우선순위: 질의 시트 '컬렉션' 열 > 법령 매핑 > --collection."""
    for item in queries:
        if not item.collection:
            item.collection = mapping.get(item.law) or default or ""
        if not item.collection:
            raise SystemExit(
                f"{item.query_id}: 검색 컬렉션을 정할 수 없습니다(법령='{item.law}'). "
                "--collection 또는 --collection-map을 지정하세요."
            )


def write_csv(path: Path, headers: Sequence[str], rows: Iterable[Sequence]) -> None:
    """[확인 항목] 질의별 결과 저장 — Excel에서 바로 열리도록 UTF-8(BOM) CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(headers)
        writer.writerows(rows)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def print_banner(lines: Sequence[str]) -> None:
    print("=" * 64)
    for line in lines:
        print(line)
    print("=" * 64)
