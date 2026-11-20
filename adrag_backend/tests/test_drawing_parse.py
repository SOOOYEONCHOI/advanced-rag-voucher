"""도면 처리기 단위 테스트 — 판별·변환·보정·추출·이미지 (2026.11.12(sooyeon.choi) 도면 파싱 기능 추가).

합성 도면(tests/drawing_fakes.py)만 쓴다. 변환기는 가짜 스크립트로 대신한다(LibreDWG 없이 실행).
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from types import SimpleNamespace

import ezdxf
import pytest
from PIL import Image

from app.ingest.drawing.common import DrawingError
from app.ingest.drawing.convert import LibreDwgConverter
from app.ingest.drawing.detect import detect_drawing
from app.ingest.drawing.ir import METADATA_KEYS, export_md, summarize
from app.ingest.drawing.reader import estimate_paper, load_dxf, pick_layout
from app.ingest.drawing.runner import convert_step, doc_key_of, extract_step, render_step
from app.ingest.drawing.sanitize import sanitize_dxf
from app.ingest.drawing.textcodes import normalize_text
from drawing_fakes import fake_converter_script, fake_dwg, make_drawing


def _settings(**extra):
    base = dict(drawing_template_dir="", drawing_render_max_px=1200, drawing_render_timeout_sec=90,
                libredwg_bin="dwg2dxf", dwg_convert_timeout_sec=30, dwg_convert_max_mem_mb=2048)
    return SimpleNamespace(**{**base, **extra})


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    base = tmp_path_factory.mktemp("drawing")
    path = make_drawing(base / "synthetic.dxf")
    source = convert_step(str(path), path.name, base / "derived", _settings())
    source.update(filename=path.name, sha256="0" * 64)
    ir = extract_step(source["dxf_path"], source, base / "derived" / "drawing_ir.json", _settings())
    return SimpleNamespace(base=base, path=path, source=source, ir=ir)


# ── 판별 ──────────────────────────────────────────────────────────────

def test_detect_dwg_versions(tmp_path):
    fmt = detect_drawing(str(fake_dwg(tmp_path / "a.dwg", b"AC1015")))
    assert (fmt.kind, fmt.acadver, fmt.release) == ("dwg", "AC1015", "R2000")
    assert detect_drawing(str(fake_dwg(tmp_path / "b.DWG", b"AC1032"))).release == "R2018"


@pytest.mark.parametrize("name,content", [
    ("old.dwg", b"AC1009" + b"\x00" * 50),       # R12 이하
    ("future.dwg", b"AC1040" + b"\x00" * 50),
    ("fake.dwg", b"hello this is text"),         # 확장자만 .dwg
    ("empty.dwg", b""),
    ("bad.dxf", b"not a dxf file at all"),
])
def test_detect_rejects(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content)
    with pytest.raises(DrawingError) as exc:
        detect_drawing(str(path))
    assert exc.value.error_code == "E_UNSUPPORTED_FORMAT"


def test_detect_dxf(tmp_path, synthetic):
    assert detect_drawing(str(synthetic.path)).kind == "dxf_ascii"


# ── 보정 ──────────────────────────────────────────────────────────────

def test_sanitize_removes_handle_zero_entries(tmp_path):
    doc = ezdxf.new("R2000")
    doc.modelspace().add_line((0, 0), (1, 1))
    good = tmp_path / "good.dxf"
    doc.saveas(good)
    text = good.read_text(encoding="cp1252")
    at = text.index("\n", text.index("AcDbDictionary", text.index("OBJECTS"))) + 1
    bad = tmp_path / "bad.dxf"
    bad.write_text(text[:at] + "  3\n\n350\n0\n  3\n\n360\n0\n" + text[at:], encoding="cp1252")
    with pytest.raises(ValueError, match="handle 0"):
        ezdxf.readfile(bad)
    fixed = tmp_path / "fixed.dxf"
    assert sanitize_dxf(str(bad), str(fixed)) == 2
    ezdxf.readfile(fixed)
    assert bad.read_text(encoding="cp1252").count("\n350\n0\n") == 1  # 원본은 그대로


def test_unreadable_or_empty_dxf_fails(tmp_path):
    """읽지 못하면 E_DXF_LOAD, recover가 빈 문서로 살리면 E_EMPTY_DRAWING — 어느 쪽이든 작업 실패."""
    path = tmp_path / "broken.dxf"
    path.write_bytes(b"0\nSECTION\n2\nENTITIES\n0\nLINE\n\xff\xfe garbage")
    with pytest.raises(DrawingError) as exc:
        doc, _ = load_dxf(str(path))
        pick_layout(doc)
    assert exc.value.error_code in ("E_DXF_LOAD", "E_EMPTY_DRAWING")


# ── 변환(가짜 변환기) ───────────────────────────────────────────────────

def test_convert_ok_with_fake_converter(tmp_path, synthetic):
    script = fake_converter_script(tmp_path / "dwg2dxf", mode="ok", dxf_source=synthetic.path)
    dwg = fake_dwg(tmp_path / "input file 한글.dwg")
    source = convert_step(str(dwg), dwg.name, tmp_path / "derived", _settings(libredwg_bin=str(script)))
    assert source["format"] == "dwg" and source["acadver"] == "AC1015"
    assert Path(source["dxf_path"]).name == "sanitized.dxf" and Path(source["dxf_path"]).exists()
    assert (tmp_path / "derived" / "converted.dxf").exists()  # 보정 전 파일도 보관
    assert source["converter"]["name"] == "libredwg"
    assert "W_CONVERTER_WARN" in [w["code"] for w in source["warnings"]]


def test_convert_with_relative_paths(tmp_path, synthetic, monkeypatch):
    """운영처럼 저장 폴더가 상대 경로(instance/data/...)여도 변환기가 파일을 찾는다(작업 폴더 cwd 겹침 방지)."""
    monkeypatch.chdir(tmp_path)
    script = fake_converter_script(tmp_path / "dwg2dxf", mode="ok", dxf_source=synthetic.path)
    fake_dwg(tmp_path / "rel.dwg")
    source = convert_step("rel.dwg", "rel.dwg", Path("instance/data/drawing/doc/v1/derived"),
                          _settings(libredwg_bin=str(script)))
    assert Path(source["dxf_path"]).exists() and source["format"] == "dwg"
    result = render_step(source["dxf_path"], synthetic.ir, _settings(drawing_render_timeout_sec=120))
    assert any(i.role == "drawing" for i in result.images), result.warnings


def test_convert_failure_and_timeout(tmp_path, synthetic):
    dwg = fake_dwg(tmp_path / "a.dwg")
    fail = fake_converter_script(tmp_path / "fail", mode="fail", dxf_source=synthetic.path)
    with pytest.raises(DrawingError) as exc:
        LibreDwgConverter(str(fail), timeout_sec=30).convert(str(dwg), str(tmp_path / "out1"))
    assert exc.value.error_code == "E_CONVERT_FAILED"
    hang = fake_converter_script(tmp_path / "hang", mode="hang", dxf_source=synthetic.path)
    with pytest.raises(DrawingError) as exc:
        LibreDwgConverter(str(hang), timeout_sec=2).convert(str(dwg), str(tmp_path / "out2"))
    assert exc.value.error_code == "E_CONVERT_TIMEOUT"
    with pytest.raises(DrawingError) as exc:
        LibreDwgConverter(str(tmp_path / "no_such_binary"), timeout_sec=2).convert(str(dwg), str(tmp_path / "out3"))
    assert exc.value.error_code == "E_CONVERT_FAILED"


# ── 추출 ──────────────────────────────────────────────────────────────

def test_sheet_paper_and_scale(synthetic):
    sheet = synthetic.ir["sheet"]
    assert sheet["size"] == "A3" and sheet["scale_factor"] == 5.0
    assert estimate_paper(210, 148.5)[0] == "A3"      # 2:1 확대 도면도 A3
    assert estimate_paper(5040, 3564)[0] == "A3"


def test_title_block_values_below_labels(synthetic):
    title = synthetic.ir["title_block"]
    fields = title["fields"]
    assert title["method"] == "template:yest_a3_v1"
    assert (fields["part_no"], fields["part_name"], fields["revision"]) == ("DW-100200", "ASSY_SAMPLE MODULE", "B.2")
    assert (fields["rev_major"], fields["rev_iter"]) == ("B", "2")
    assert fields["scale"] == "1:5" and fields["material"] == "SS400" and fields["drawn"] == "설계자A"
    assert fields["checked"] == "검토자B" and fields["approved"] == "승인자C"


def test_bom_table_multiline_header_in_block(synthetic):
    bom = next(t for t in synthetic.ir["tables"] if t["kind"] == "bom")
    assert bom["header_pos"] == "top" and bom["block"] == "SW_TABLEANNOTATION_0"
    assert bom["columns"] == ["item_no", "part_no", "part_name", "qty", "material"]
    assert [r["part_no"] for r in bom["rows"]] == ["DW-100201", "DW-100231", "BRG-6205ZZ"]
    assert bom["rows"][1] == {"item_no": "2", "part_no": "DW-100231", "part_name": "SHAFT_DRIVE", "qty": "2",
                              "material": "S45C"}


def test_revision_table_header_bottom(synthetic):
    rev = next(t for t in synthetic.ir["tables"] if t["kind"] == "revision")
    assert rev["header_pos"] == "bottom"
    assert [r["rev"] for r in rev["rows"]] == ["B", "A"]
    assert rev["rows"][0]["description"] == "커버 볼트 수량 변경"


def test_notes_tolerance_and_spec_memo(synthetic):
    notes = synthetic.ir["notes"]
    assert notes["items"] == ["일반 공차는 KS B ISO 2768-m/K 을 따른다.", "날카로운 모서리는 C0.5 모따기.", "도장 색상은 회색."]
    assert notes["general_tolerance"] == "KS B ISO 2768-m/K"
    assert notes["spec_memos"][0] == "<샘플 규격 : SP-10, 폭 20mm>"


def test_dimensions_prefix_and_reference(synthetic):
    texts = {d["text"]: d for d in synthetic.ir["dimensions"]}
    assert "2-Ø5.5 THRU" in texts and texts["(12.5)"]["reference"] is True
    assert any(d["measured"] == 800.0 for d in synthetic.ir["dimensions"])
    assert synthetic.ir["tolerance_summary"]["general_tolerance_only"] is True


def test_misc_excludes_fixed_phrases(synthetic):
    misc = synthetic.ir["misc_texts"]
    assert "조립 후 회전 확인" in misc
    assert not any(t in misc for t in ("Confidential", "보통급", "PART NUMBER", "DW-100201"))
    assert synthetic.ir["confidential"] is True


def test_metadata_key_contract(synthetic):
    meta = synthetic.ir["metadata"]
    assert tuple(meta) == METADATA_KEYS
    assert meta["doc_type"] == "drawing" and meta["drawing_no"] == meta["part_no"] == "DW-100200"
    assert meta["drawing_kind"] == "assembly" and meta["bom_part_nos"] == ["DW-100201", "DW-100231", "BRG-6205ZZ"]
    assert doc_key_of(synthetic.ir, "x.dwg") == "DW-100200"
    assert synthetic.ir["warnings"] == []
    summary = summarize(synthetic.ir)
    assert summary["needs_review"] is False and summary["bom_rows"] == 3 and summary["search_status"] == "not_indexed"


def test_missing_title_fields_warns(tmp_path):
    path = make_drawing(tmp_path / "norev.dxf", title_overrides={"REVISION": None}, with_bom=False)
    source = convert_step(str(path), path.name, tmp_path / "d", _settings())
    ir = extract_step(source["dxf_path"], {**source, "filename": path.name}, tmp_path / "d" / "ir.json", _settings())
    warning = next(w for w in ir["warnings"] if w["code"] == "W_TITLE_MISSING")
    assert warning["level"] == "warn" and warning["missing"] == ["revision"]
    assert summarize(ir)["needs_review"] is True and ir["metadata"]["drawing_kind"] == "part"


def test_no_title_block_falls_back_to_filename(tmp_path):
    path = make_drawing(tmp_path / "plain_name.dxf", with_title=False, with_bom=False)
    source = convert_step(str(path), path.name, tmp_path / "d", _settings())
    ir = extract_step(source["dxf_path"], {**source, "filename": path.name}, tmp_path / "d" / "ir.json", _settings())
    codes = [w["code"] for w in ir["warnings"]]
    assert "W_TITLE_MISSING" in codes and "W_TEMPLATE_MISMATCH" in codes
    assert doc_key_of(ir, path.name) == "plain_name"


def test_unicode_and_mbcs_codes():
    assert normalize_text("\\U+D55C\\U+AE00 %%c10 %%d %%p0.1") == "한글 Ø10 ° ±0.1"
    assert normalize_text("\\M+3C7D1") == "한"
    assert normalize_text("a\\Pb") == "a\nb"


def test_export_md_keeps_last_runs(tmp_path, synthetic):
    for i in range(4):
        out = export_md(synthetic.ir, str(tmp_path), "DW-100200", f"job{i}", keep_last=2)
        os.utime(out, (i, i))
    runs = sorted(p.name for p in (tmp_path / "drawing" / "DW-100200").iterdir())
    assert len(runs) == 2
    text = (tmp_path / "drawing" / "DW-100200" / runs[-1] / "summary.md").read_text(encoding="utf-8")
    assert "| DW-100201 |" in text and "KS B ISO 2768-m/K" in text


# ── 이미지 ────────────────────────────────────────────────────────────

def test_render_fixed_extents_crops_and_skips_damaged_hatch(synthetic):
    result = render_step(synthetic.source["dxf_path"], synthetic.ir, _settings(), in_process=True)
    roles = [(i.role, i.region) for i in result.images]
    assert ("drawing", "full") in roles and ("drawing_preview", "full") in roles
    assert {r for role, r in roles if role == "drawing_crop"} == {"title_block", "bom", "revision"}
    full = next(i for i in result.images if i.role == "drawing")
    assert max(full.width, full.height) == 1200
    assert abs(full.width / full.height - 420 / 297) < 0.01  # 손상 해칭이 범위를 넓히지 않음
    with Image.open(io.BytesIO(full.png)) as img:
        assert img.getextrema() != ((255, 255), (255, 255), (255, 255))  # 빈 그림이 아님
    skipped = next(w for w in result.warnings if w["code"] == "W_RENDER_SKIPPED")
    assert skipped["count"] == 1 and skipped["level"] == "warn"


def test_render_failure_is_warning_only(tmp_path, synthetic):
    result = render_step(str(tmp_path / "missing.dxf"), synthetic.ir, _settings(drawing_render_timeout_sec=60))
    assert result.images == [] and result.warnings[0]["code"] == "W_RENDER_FAILED"
