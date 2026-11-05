import pytest

from app.parsers.document_types import (
    DocumentTypeSource,
    normalize_requested_doc_type,
    validate_document_type_compatibility,
)


def test_document_type_normalization_defaults_and_rejects_unknown_values():
    assert normalize_requested_doc_type(None) == "auto"
    assert normalize_requested_doc_type(" Spreadsheet ") == "spreadsheet"
    with pytest.raises(ValueError):
        normalize_requested_doc_type("unknown")


def test_spreadsheet_selection_requires_ooxml_extension():
    validate_document_type_compatibility("report.xlsx", "spreadsheet")
    validate_document_type_compatibility("report.xlsm", "auto")
    with pytest.raises(ValueError):
        validate_document_type_compatibility("report.pdf", "spreadsheet")


def test_non_spreadsheet_selection_is_rejected_for_ooxml_files():
    with pytest.raises(ValueError):
        validate_document_type_compatibility("report.xlsx", "manual")
    assert DocumentTypeSource.FILE_EXTENSION.value == "file_extension"


def test_manual_selection_bypasses_detectors(monkeypatch):
    from app.parsers import processor

    called = []
    monkeypatch.setattr(processor, "count_law_signals", lambda text: called.append("law"))
    monkeypatch.setattr(processor, "count_manual_signals", lambda text: called.append("manual"))
    instance = processor.DocumentChunkingProcessor.__new__(processor.DocumentChunkingProcessor)
    instance.config = type(
        "Config",
        (),
        {"law_score_threshold": 1, "law_article_threshold": 1, "manual_score_threshold": 1},
    )()

    decision = instance._resolve_document_type(
        requested_doc_type="manual",
        extension="pdf",
        sample_text="text",
        first_page_text="text",
        is_spreadsheet=False,
        sample_document_count=1,
    )
    assert decision.effective_doc_type == "manual"
    assert decision.source == "user_selected"
    assert decision.detector_details is None
    assert called == []
