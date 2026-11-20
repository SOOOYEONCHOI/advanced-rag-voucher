# 2026.11.10(sooyeon.choi) 추가 - 검색 개선 1~3: SOP 질의 법령 표기 오변환, v2 토큰 정책(코드·규격·호기), 리랭커 입력 문서명
import sys
import types
from types import SimpleNamespace

import pytest

config_stub = types.ModuleType("app.core.config")
config_stub.LOG_PATH = "./instance/log"
sys.modules.setdefault("app.core.config", config_stub)

from app.graphs.preprocessing.query_preprocessor import QueryPreprocessor  # noqa: E402
from app.utils import kiwi_tokenizer  # noqa: E402
from app.utils.kiwi_tokenizer import (  # noqa: E402
    standardize_code_token,
    token_policy_for_version,
    tokenize_corpus,
    tokenize_query_for_bm25,
)

sys.modules.pop("app.core.config", None)


# ── ① 법령 표기 정규화 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("3호기 브라켓 조립 순서", "3호기 브라켓 조립 순서"),
        ("2조립 라인 커넥터 체결", "2조립 라인 커넥터 체결"),
        ("제12조 확인", "제12조 확인"),  # 기존 버그: "제1제2조"
        ("2조에서 작업", "제2조에서 작업"),
        ("1조원 예산", "1조원 예산"),
    ],
)
def test_law_notation_only_before_particle_or_end(query, expected):
    assert QueryPreprocessor().preprocess(query).normalized_query == expected


def test_sop_query_is_not_classified_as_law_reference():
    result = QueryPreprocessor().preprocess("2조립 라인 커넥터 체결")
    assert result.matched_patterns["law_references"] == []


def test_law_notation_can_be_disabled():
    result = QueryPreprocessor(law_notation_normalize=False).preprocess("2조에서 작업 제3조")
    assert result.normalized_query == "2조에서 작업 제3조"
    assert result.matched_patterns["law_references"] == []


# ── ② v2 토큰 정책 ─────────────────────────────────────────────────────────────

def test_encoder_version_selects_policy():
    assert token_policy_for_version("kiwi-bm25-v1") == "v1"
    assert token_policy_for_version("kiwi-bm25-v2") == "v2"
    assert token_policy_for_version(None) == "v1"


@pytest.mark.parametrize(
    ("form", "expected"),
    [
        ("XG-500A", ["xg500a", "xg", "500a"]),
        ("M6", ["m6"]),
        ("12N·m", ["12nm"]),
        ("12 N·m", ["12nm"]),
        ("1.5mm", ["1_5mm"]),
        ("ABC-12-3B", ["abc123b", "abc", "12", "3b"]),
        ("커넥터", ["커넥터"]),
        ("LOTO", ["LOTO"]),
    ],
)
def test_standardize_code_token(form, expected):
    assert standardize_code_token(form) == expected


@pytest.fixture()
def real_kiwi():
    pytest.importorskip("kiwipiepy")
    if kiwi_tokenizer.get_kiwi("v2") is None:
        pytest.skip("Kiwi 초기화 실패")


@pytest.mark.parametrize(
    ("text", "must_have"),
    [
        ("XG-500A 모델 M6 볼트 체결", ["xg500a", "500a", "m6", "볼트"]),
        ("3호기 브라켓", ["3호기", "브라켓"]),
        ("2조립 라인", ["조립", "라인"]),
        ("12N·m 토크로 조이는 공정", ["12nm", "토크"]),
        ("1.5mm 간격", ["1_5mm", "간격"]),
        ("220V 전원", ["220v", "전원"]),
    ],
)
def test_v2_query_and_corpus_share_code_tokens(real_kiwi, text, must_have):
    query_tokens = tokenize_query_for_bm25(text, "v2")
    corpus_tokens = tokenize_corpus(text, "v2")
    for token in must_have:
        assert token in query_tokens, (token, query_tokens)
        assert token in corpus_tokens, (token, corpus_tokens)


def test_v2_tokens_survive_qdrant_bm25_tokenizer(real_kiwi):
    """Qdrant BM25(FastEmbed SimpleTokenizer)는 소문자화 후 비단어 문자에서 자른다. 표준형은 한 단어로 남아야 한다."""
    import re

    for token in tokenize_corpus("XG-500A 12N·m 1.5mm 3호기", "v2"):
        assert re.sub(r"[^\w]", " ", token.lower()).split() == [token.lower()]


def test_v1_policy_keeps_existing_tokens(real_kiwi):
    assert "3호" in tokenize_corpus("3호기 브라켓", "v1")
    assert "XG" in tokenize_corpus("XG-500A 모델", "v1")


def test_explicit_policy_does_not_replace_default_instance(real_kiwi):
    default = kiwi_tokenizer.get_kiwi()
    other = "v2" if kiwi_tokenizer.current_token_policy() == "v1" else "v1"
    kiwi_tokenizer.get_kiwi(other)
    assert kiwi_tokenizer.get_kiwi() is default


def test_bm25_encoder_uses_policy_from_version(monkeypatch):
    from app.clients import kiwi_bm25_encoder as module

    calls = []
    monkeypatch.setattr(module, "tokenize_corpus", lambda text, policy=None: calls.append(policy) or ["a1"])
    settings = SimpleNamespace(bm25_k1=1.2, bm25_b=0.5, bm25_avg_len=128.0, kiwi_bm25_encoder_version="kiwi-bm25-v2")
    encoder = module.KiwiBm25Encoder(settings)
    assert encoder.token_policy == "v2"
    encoder.normalize_document("x")
    assert calls == ["v2"]


# ── ③ 리랭커 입력 ──────────────────────────────────────────────────────────────

def test_rerank_text_uses_original_filename_and_sheet():
    from app.graphs.nodes.rerank import _build_rerank_text

    text = _build_rerank_text({
        "text": "본문",
        "metadata": {"original_filename": "SOP_A.xlsx", "document_type": "spreadsheet", "sheet_name": "조립"},
    })
    assert text == "[문서명] SOP_A.xlsx\n[시트] 조립\n[본문] 본문"


def test_rerank_text_falls_back_to_filename_and_header_path():
    from app.graphs.nodes.rerank import _build_rerank_text

    text = _build_rerank_text({
        "text": "본문",
        "metadata": {"filename": "a.pdf", "header_path": ["1장", "1.1"], "sheet_name": "무시"},
    })
    assert text == "[문서명] a.pdf\n[섹션] 1장 > 1.1\n[본문] 본문"


# ── 재계산 스크립트: 프로필 갱신 대상 ───────────────────────────────────────────

def test_rebuild_profile_targets_only_differ_by_encoder_version():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "rebuild_kiwi_bm25.py"
    spec = importlib.util.spec_from_file_location("rebuild_kiwi_bm25", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    profile_targets = module.profile_targets

    current = {"embedding_model_name": "m", "kiwi_bm25_encoder_version": "kiwi-bm25-v2"}
    same_except_version = {"embedding_model_name": "m", "kiwi_bm25_encoder_version": "kiwi-bm25-v1"}
    other_model = {"embedding_model_name": "old", "kiwi_bm25_encoder_version": "kiwi-bm25-v1"}

    class FakeDb:
        def execute_query(self, sql, params):
            return [("d1", 1, same_except_version), ("d1", 2, other_model)]

    assert profile_targets(FakeDb(), ["c"], 9, current) == [("d1", 1)]
