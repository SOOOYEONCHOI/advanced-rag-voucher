import sys
import types
from types import SimpleNamespace

config_stub = types.ModuleType("app.core.config")
config_stub.LOG_PATH = "./instance/log"
sys.modules.setdefault("app.core.config", config_stub)

from app.graphs.preprocessing.query_preprocessor import QueryPreprocessor
from app.utils import kiwi_tokenizer
from app.utils.dictionary_loader import load_korean_search_dictionary

sys.modules.pop("app.core.config", None)


def test_korean_search_dictionary_loads_shared_entries():
    dictionary = load_korean_search_dictionary()

    assert dictionary.abbreviations["산안법"] == "산업안전보건법"
    assert "위험성평가" in dictionary.compound_terms
    assert dictionary.aliases["PSM"] == "공정안전관리"
    assert "알려줘" in dictionary.stopwords_query_functional


def test_query_preprocessor_uses_yaml_abbreviations():
    result = QueryPreprocessor().preprocess("산안법 기준 알려줘")

    assert "산업안전보건법" in result.normalized_query
    assert "산업안전보건법" in result.expanded_terms


def test_query_preprocessor_normalizes_law_reference_notation():
    preprocessor = QueryPreprocessor()

    result = preprocessor.preprocess("산안법 1조")
    assert result.normalized_query == "산업안전보건법 제1조"
    assert result.matched_patterns["law_references"] == ["제1조"]

    assert preprocessor.preprocess("1조의 2").normalized_query == "제1조의2"
    assert preprocessor.preprocess("제 1 항").normalized_query == "제1항"
    assert preprocessor.preprocess("1조원 예산").normalized_query == "1조원 예산"


def test_query_preprocessor_preserves_alias_and_adds_full_name():
    result = QueryPreprocessor().preprocess("PSM 대상 알려줘")

    assert "PSM" in result.normalized_query
    assert "공정안전관리" in result.expanded_terms


# 2026.06.29(sooyeon.choi) 수정 - YAML만 변경해 신규 사전 항목이 반영되는 수용 기준 검증
def test_dictionary_loader_reflects_entries_from_custom_yaml(tmp_path):
    dictionary_path = tmp_path / "korean_search_dictionary.yaml"
    dictionary_path.write_text(
        """
abbreviations:
  새약어: 새로운정식명
compound_terms:
  - 새로운복합어
aliases:
  NEW: 새로운복합어
stopwords:
  query_functional:
    - 제거어
  domain_weak:
    - 약한어
protected_patterns: []
""".strip(),
        encoding="utf-8",
    )

    load_korean_search_dictionary.cache_clear()
    try:
        dictionary = load_korean_search_dictionary(str(dictionary_path))
        assert dictionary.abbreviations["새약어"] == "새로운정식명"
        assert "새로운복합어" in dictionary.compound_terms
        assert dictionary.aliases["NEW"] == "새로운복합어"
    finally:
        load_korean_search_dictionary.cache_clear()


# 2026.06.29(sooyeon.choi) 수정 - Kiwi 초기화 시 YAML 전체 항목 등록과 alias 보존 검증
def test_kiwi_registers_dictionary_entries_and_preserves_alias(monkeypatch):
    class FakeKiwi:
        def __init__(self):
            self.user_words = []
            self.pre_analyzed_words = []

        def add_re_word(self, pattern, tag):
            pass

        def add_user_word(self, word, tag):
            self.user_words.append((word, tag))

        def add_pre_analyzed_word(self, word, analyzed):
            self.pre_analyzed_words.append((word, analyzed))

        def tokenize(self, text):
            if text == "PSM 대상":
                return [
                    SimpleNamespace(form="PSM", tag="SL"),
                    SimpleNamespace(form="대상", tag="NNG"),
                ]
            return []

    fake_module = types.ModuleType("kiwipiepy")
    fake_module.Kiwi = FakeKiwi
    monkeypatch.setitem(sys.modules, "kiwipiepy", fake_module)
    load_korean_search_dictionary.cache_clear()
    kiwi_tokenizer._kiwi = None

    try:
        dictionary = load_korean_search_dictionary()
        kiwi = kiwi_tokenizer.get_kiwi()

        assert kiwi is not None
        assert all((term, "NNP") in kiwi.user_words for term in dictionary.compound_terms)
        assert all((alias, "SL") in kiwi.user_words for alias in dictionary.aliases)
        assert kiwi_tokenizer.tokenize_query("PSM 대상") == ["PSM", "대상"]
    finally:
        kiwi_tokenizer._kiwi = None
        load_korean_search_dictionary.cache_clear()
