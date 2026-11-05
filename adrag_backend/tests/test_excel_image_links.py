"""엑셀 사진 전부 자동 연결 단위 테스트 (2026.10.22, EXCEL_IMAGE_LINK_ALL).

관련 ID: R3-2(사진↔작업 단계 연결), F-3-04 · 결정: 검수 화면(UI-15) 1차 제외, 모든 사진을 셀 위치 기준으로 청크에 연결.
규칙: Step → 행 겹침 → 가장 가까운 청크(같으면 위쪽) → 글자 청크 없는 시트는 이미지 청크. 장식·양식 머리글은 연결 안 함.
"""
from types import SimpleNamespace

from app.ingest.excel_chunks import excel_chunks_to_documents
from app.ingest.excel_images import link_excel_images, plan_excel_images


def _placement(image_id, cell_range, role="figure", step_no=None):
    return {"image_id": image_id, "sha256": image_id * 4, "cell_range": cell_range, "role": role, "step_no": step_no}


def _sheet(name, index, *, steps=(), header_rows=(), placements=()):
    return {
        "name": name, "index": index, "section_type": "sop" if steps else "other",
        "steps": [{"no": no, "rows": list(rows)} for no, rows in steps],
        "header_kv": [{"row": r, "cells": []} for r in header_rows],
        "placements": list(placements),
    }


def _chunk(sheet, kind, block, meta=None, text="내용"):
    return {"chunk_id": f"doc:{sheet['index']:02d}:{kind}:{block}", "sheet": sheet["name"],
            "content_type": kind, "text": text, "meta": meta or {}}


def _result(sheets, chunks):
    assets = {p["sha256"]: {"data": b"x", "ext": "png"} for s in sheets for p in s["placements"]}
    return SimpleNamespace(ir={"sections": sheets}, chunks=chunks, assets=assets)


def _link(sheets, chunks):
    result = _result(sheets, chunks)
    plan = plan_excel_images(result, "D", 1, "job")
    rid = {(sheet, p["image_id"], p["cell_range"]): r for sheet, p, r in plan.items}
    return result, plan, link_excel_images(result, plan), rid


def test_step_photos_follow_placement_step_even_with_duplicate_step_numbers():
    # Step 0이 두 번(12행·13행) 나오는 시트, Step 1로 보정된 확대도(O12), 같은 그림이 Step 6·7에 있는 경우
    photos = [
        _placement("a0", "C12", "step_photo", 0), _placement("b0", "C13", "step_photo", 0),
        _placement("c1", "C14", "step_photo", 1), _placement("c1", "O12", "detail_view", 1),
        _placement("dd", "T19", "detail_view", 6), _placement("dd", "Q20", "detail_view", 7),
    ]
    s = _sheet("S", 11, steps=[(0, (12, 12)), (0, (13, 13)), (1, (14, 14)), (6, (19, 19)), (7, (20, 20))],
               placements=photos)
    chunks = [_chunk(s, "step", n, {"step_no": no}) for n, no in (("0", 0), ("0", 0), ("1", 1), ("6", 6), ("7", 7))]
    _, _, links, rid = _link([s], chunks)

    assert links.by_chunk[0] == [rid[("S", "a0", "C12")]]                                   # 첫 Step 0
    assert links.by_chunk[1] == [rid[("S", "b0", "C13")]]                                   # 두 번째 Step 0
    assert links.by_chunk[2] == [rid[("S", "c1", "C14")], rid[("S", "c1", "O12")]]          # 보정된 확대도는 Step 1
    assert links.by_chunk[3] == [rid[("S", "dd", "T19")]] and links.by_chunk[4] == [rid[("S", "dd", "Q20")]]
    assert links.summary["by_method"]["step"] == 6 and links.summary["unlinked"] == 0


def test_figures_link_to_overlapping_chunks_then_nearest_with_upper_preference():
    s = _sheet("S", 2, header_rows=(2, 3), placements=[
        _placement("ov", "B6:D8"),      # 표 5~10행과 겹침
        _placement("wd", "B9:H15"),     # 표 5~10행·12~20행 둘 다 겹침
        _placement("nr", "B22"),        # 표 12~20행 아래 2행 → 가장 가까운 위쪽
        _placement("tie", "B11"),       # 위(10행)·아래(12행) 거리 1로 같음 → 위쪽
        _placement("top", "A1"),        # 개요(2~3행)가 가장 가까움
    ])
    chunks = [
        _chunk(s, "summary", "0"),
        _chunk(s, "table_section", "0.0", {"rows": [5, 10]}),
        _chunk(s, "table_section", "1.0", {"rows": [12, 20]}),
        _chunk(s, "form_control", "0"),                      # 위치 없음 → 후보 아님
    ]
    _, _, links, rid = _link([s], chunks)

    assert links.by_chunk[0] == [rid[("S", "top", "A1")]]
    assert links.by_chunk[1] == [rid[("S", "ov", "B6:D8")], rid[("S", "wd", "B9:H15")], rid[("S", "tie", "B11")]]
    assert links.by_chunk[2] == [rid[("S", "wd", "B9:H15")], rid[("S", "nr", "B22")]]
    assert 3 not in links.by_chunk
    assert links.summary["by_method"] == {"step": 0, "row_overlap": 2, "nearest": 3, "image_chunk": 0}


def test_guide_note_position_and_link_order_overlap_before_nearest():
    s = _sheet("S", 3, placements=[_placement("far", "C30"), _placement("in", "C6")])
    chunks = [_chunk(s, "guide_note", "sp1", {"shape_range": "B5:F9"})]
    _, _, links, rid = _link([s], chunks)
    # 배치 순서는 far가 먼저지만 겹침(in)이 가까운 청크(far)보다 앞
    assert links.by_chunk[0] == [rid[("S", "in", "C6")], rid[("S", "far", "C30")]]


def test_decoration_and_form_header_are_not_linked():
    s = _sheet("S", 4, placements=[_placement("lg", "A1", "form_header"), _placement("dc", "B5", "decoration"),
                                   _placement("pp", "D6", "part_photo")])
    chunks = [_chunk(s, "table_section", "0.0", {"rows": [5, 8]})]
    _, _, links, rid = _link([s], chunks)
    assert links.by_chunk == {0: [rid[("S", "pp", "D6")]]}
    assert (links.summary["excluded"], links.summary["linked"], links.summary["unlinked"]) == (2, 1, 0)


def test_image_only_sheet_keeps_image_chunk_and_links_it():
    text_sheet = _sheet("T", 1, placements=[])
    image_sheet = _sheet("P", 2, placements=[_placement("im", "B3:F9")])
    chunks = [
        _chunk(text_sheet, "table_section", "0.0", {"rows": [1, 3]}),
        _chunk(image_sheet, "form_control", "0"),
        _chunk(image_sheet, "image", "im@B3:F9", {"image_id": "im"}, text="[P > B3:F9] 이미지(figure)"),
    ]
    _, _, links, rid = _link([text_sheet, image_sheet], chunks)
    assert links.keep_image_chunks == {2} and links.by_chunk[2] == [rid[("P", "im", "B3:F9")]]
    assert links.summary["by_method"]["image_chunk"] == 1 and links.summary["unlinked"] == 0

    documents = excel_chunks_to_documents(chunks, resource_ids_by_index=links.by_chunk,
                                          keep_indexes=links.keep_image_chunks)
    image_docs = [d for d in documents if d.metadata["content_type"] == "image"]
    assert len(image_docs) == 1 and image_docs[0].metadata["resource_ids"] == [rid[("P", "im", "B3:F9")]]
    # 연결 결과가 없으면 이미지 청크는 기존처럼 적재하지 않는다
    assert not [d for d in excel_chunks_to_documents(chunks) if d.metadata["content_type"] == "image"]


def test_split_chunk_pieces_share_links():
    s = _sheet("S", 5, placements=[_placement("im", "C6")])
    body = "\n".join(f"행 {i} " + "가" * 40 for i in range(30))
    chunks = [_chunk(s, "table_section", "0.0", {"rows": [5, 34]}, text=f"[S > 표]\n{body}")]
    _, _, links, rid = _link([s], chunks)
    documents = excel_chunks_to_documents(chunks, max_chunk_size=300, resource_ids_by_index=links.by_chunk)
    assert len(documents) > 1
    assert all(d.metadata["resource_ids"] == [rid[("S", "im", "C6")]] for d in documents)
