# 2026.06.29(sooyeon.choi) 수정 - Task 3 검색 토큰 정책의 독립 수용 테스트 추가
import sys
import types
from types import SimpleNamespace

import pytest

config_stub = types.ModuleType("app.core.config")
config_stub.LOG_PATH = "./instance/log"
sys.modules.setdefault("app.core.config", config_stub)

from app.graphs.preprocessing.query_preprocessor import QueryPreprocessor
from app.utils import kiwi_tokenizer

sys.modules.pop("app.core.config", None)


class FakeKiwi:
    _tokens = {
        "안전관리자의 자격 요건": [
            ("안전관리자", "NNP"),
            ("의", "JKG"),
            ("자격", "NNG"),
            ("요건", "NNG"),
        ],
        "위험한 작업을 반드시": [
            ("위험", "VA"),
            ("하", "XSA"),
            ("작업", "NNG"),
            ("을", "JKO"),
            ("반드시", "MAG"),
        ],
        # 2026.06.29(sooyeon.choi) 수정 - Task 5 MatchText 입력의 조사 제거 결과 검증용 토큰
        "안전관리자의 자격 요건은": [
            ("안전관리자", "NNP"),
            ("의", "JKG"),
            ("자격", "NNG"),
            ("요건", "NNG"),
            ("은", "JX"),
        ],
    }

    def tokenize(self, text):
        return [
            SimpleNamespace(form=form, tag=tag)
            for form, tag in self._tokens.get(text, [])
        ]


@pytest.fixture()
def fake_kiwi():
    previous = kiwi_tokenizer._kiwi
    kiwi_tokenizer._kiwi = FakeKiwi()
    try:
        yield
    finally:
        kiwi_tokenizer._kiwi = previous


def test_corpus_and_query_share_noun_tokens(fake_kiwi):
    text = "안전관리자의 자격 요건"

    assert kiwi_tokenizer.tokenize_corpus(text) == ["안전관리자", "자격", "요건"]
    assert kiwi_tokenizer.tokenize_query(text) == ["안전관리자", "자격", "요건"]


def test_query_excludes_adjective_and_adverb_tokens(fake_kiwi):
    assert kiwi_tokenizer.tokenize_query("위험한 작업을 반드시") == ["작업"]

    # 2026.06.29(sooyeon.choi) 수정 - 검색 품사가 없을 때 전체 품사로 되돌아가지 않도록 검증
    kiwi_tokenizer._kiwi._tokens["위험한 반드시"] = [
        ("위험", "VA"),
        ("반드시", "MAG"),
    ]
    assert kiwi_tokenizer.tokenize_query("위험한 반드시") == []


def test_normalize_query_joins_compound_spacing_without_removing_dense_words():
    normalized = kiwi_tokenizer.normalize_query("제 17 조의 3 위험성 평가를 알려줘")

    assert "제17조의3" in normalized
    assert "위험성평가를" in normalized
    assert "알려줘" in normalized


def test_extract_search_terms_removes_functional_stopwords(fake_kiwi):
    terms = kiwi_tokenizer.extract_search_terms("공정안전관리 대상 사업장 알려줘")

    assert terms == ["공정안전관리", "대상", "사업장"]


def test_tokenize_query_for_bm25_normalizes_and_filters(fake_kiwi):
    assert kiwi_tokenizer.tokenize_query_for_bm25("위험성 평가 알려줘") == ["위험성평가"]


def test_tokenize_query_for_bm25_removes_korean_particles(fake_kiwi):
    assert kiwi_tokenizer.tokenize_query_for_bm25(
        "안전관리자의 자격 요건은"
    ) == ["안전관리자", "자격", "요건"]


def test_domain_weak_terms_are_flagged_instead_of_removed():
    assert kiwi_tokenizer.is_domain_weak_term("기준") is True
    assert "기준" in kiwi_tokenizer.extract_search_terms("안전 기준")


def test_query_preprocessor_keeps_dense_query_and_filters_keywords(fake_kiwi):
    result = QueryPreprocessor().preprocess("산안법 기준 알려줘")

    assert "산업안전보건법" in result.normalized_query
    assert "알려줘" in result.normalized_query
    assert "알려줘" not in result.extracted_keywords
