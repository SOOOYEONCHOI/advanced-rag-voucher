import json

import pytest

from app.services.manual_display_service import ManualDisplayService


def _service_with_map(tmp_path, mapping):
    base_dir = tmp_path / "manual_display"
    base_dir.mkdir()
    (base_dir / "pdf").mkdir()
    (base_dir / "manual_citation_map.json").write_text(
        json.dumps(mapping, ensure_ascii=False),
        encoding="utf-8",
    )
    return ManualDisplayService(base_dir=base_dir)


def test_resolve_manual_display_mapping(tmp_path):
    # 2026.07.10(sooyeon.choi) 추가 - 매뉴얼 표시용 PDF 파일/페이지 매핑 검증
    service = _service_with_map(
        tmp_path,
        {
            "uploaded.pdf": {
                "display_source": "display.pdf",
                "page_map": {
                    "1": "6",
                    "2": "6",
                },
            },
        },
    )

    resolved = service.resolve("uploaded.pdf", 1)

    assert resolved == {
        "mapped": True,
        "display_filename": "display.pdf",
        "display_page": 6,
    }


def test_resolve_falls_back_when_filename_is_not_mapped(tmp_path):
    service = _service_with_map(tmp_path, {})

    resolved = service.resolve("other.pdf", 3)

    assert resolved == {
        "mapped": False,
        "display_filename": "other.pdf",
        "display_page": 3,
    }


def test_resolve_falls_back_when_page_is_not_mapped(tmp_path):
    service = _service_with_map(
        tmp_path,
        {
            "uploaded.pdf": {
                "display_source": "display.pdf",
                "page_map": {
                    "1": "6",
                },
            },
        },
    )

    resolved = service.resolve("uploaded.pdf", 2)

    assert resolved == {
        "mapped": False,
        "display_filename": "uploaded.pdf",
        "display_page": 2,
    }


def test_resolve_pdf_path_rejects_path_traversal(tmp_path):
    service = _service_with_map(tmp_path, {})

    with pytest.raises(ValueError):
        service.resolve_pdf_path("../secret.pdf")
