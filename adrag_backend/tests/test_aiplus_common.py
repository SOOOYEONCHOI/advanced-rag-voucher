# 2026.11.23(sooyeon.choi) 추가 - AI+ 시험 스크립트 공통 모듈(시험 데이터 읽기·컬렉션 선택) 테스트 (시험합의서 시험 1·2·4)
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from aiplus_common import assign_collections, load_testset, parse_collection_map, split_chunk_ids  # noqa: E402


def _testset(path: Path, queries, golds) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "질의"
    sheet.append(["질의ID", "질의문", "정답 답변", "법령"])
    for row in queries:
        sheet.append(row)
    gold = workbook.create_sheet("정답 근거")
    gold.append(["질의ID", "근거순번", "근거 문서명", "근거 조항", "페이지", "청크ID", "근거 내용"])
    for row in golds:
        gold.append(row)
    workbook.save(path)
    return path


def test_load_testset_merges_gold_chunk_ids_per_query(tmp_path):
    path = _testset(
        tmp_path / "t.xlsx",
        [["산안-001", "질문1", "답1", "산업안전보건법"], ["중처-001", "질문2", "답2", "중대재해처벌법"]],
        [["산안-001", 1, "법", "제1조", 1, "a-1", "본문"], ["산안-001", 2, "법", "", None, "a-2, a-3", "본문"],
         ["중처-001", 1, "법", "제2조", 2, "b-1", "본문"]],
    )
    queries = load_testset(str(path))
    assert [q.query_id for q in queries] == ["산안-001", "중처-001"]
    assert queries[0].gold_chunk_ids == {"a-1", "a-2", "a-3"}
    assert queries[1].law == "중대재해처벌법"


def test_load_testset_without_gold_skips_gold_sheet(tmp_path):
    path = _testset(tmp_path / "t.xlsx", [["Q1", "질문", "", ""]], [["없는ID", 1, "", "", None, "x", ""]])
    assert load_testset(str(path), with_gold=False)[0].gold_chunk_ids == set()
    with pytest.raises(SystemExit):
        load_testset(str(path))  # 정답 근거의 질의ID가 질의 시트에 없음


def test_duplicate_query_id_is_rejected(tmp_path):
    path = _testset(tmp_path / "t.xlsx", [["Q1", "질문", "", ""], ["Q1", "질문2", "", ""]], [])
    with pytest.raises(SystemExit):
        load_testset(str(path))


def test_split_chunk_ids_accepts_comma_newline_space():
    assert split_chunk_ids("a, b\nc;d  e") == ["a", "b", "c", "d", "e"]
    assert split_chunk_ids("") == []


def test_assign_collections_priority(tmp_path):
    path = _testset(
        tmp_path / "t.xlsx",
        [["Q1", "질문", "", "산업안전보건법"], ["Q2", "질문", "", "기타"]],
        [],
    )
    queries = load_testset(str(path), with_gold=False)
    mapping = parse_collection_map("산업안전보건법=AIE_산안, 중대재해처벌법=AIE_중처")
    assign_collections(queries, "AIE_기본", mapping)
    assert [q.collection for q in queries] == ["AIE_산안", "AIE_기본"]
    queries[1].collection = ""
    with pytest.raises(SystemExit):
        assign_collections(queries[1:], None, mapping)
