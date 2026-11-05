import ast
import inspect
import sys
import types

import pytest

config_stub = types.ModuleType("app.core.config")
config_stub.LOG_PATH = "./instance/log"
sys.modules.setdefault("app.core.config", config_stub)

from app.utils import kiwi_tokenizer

sys.modules.pop("app.core.config", None)


def _registered_re_word_patterns() -> list[str]:
    tree = ast.parse(inspect.getsource(kiwi_tokenizer))
    patterns: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "add_re_word":
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            value = node.args[0].value
            if isinstance(value, str):
                patterns.append(value)
    return patterns


def test_add_re_word_patterns_do_not_use_pipe_inside_character_class():
    for pattern in _registered_re_word_patterns():
        assert not any("|" in part.split("]", 1)[0] for part in pattern.split("[")[1:])


@pytest.fixture()
def kiwi():
    pytest.importorskip("kiwipiepy")
    kiwi_tokenizer._kiwi = None
    instance = kiwi_tokenizer.get_kiwi()
    assert instance is not None
    return instance


def _normalized_forms(kiwi, text: str) -> list[str]:
    return [token.form.replace(" ", "") for token in kiwi.tokenize(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("제17조의3", "제17조의3"),
        ("제1항제2호", "제1항제2호"),
        ("별표3", "별표3"),
        ("별표 3", "별표3"),
        ("부칙 제3조", "부칙제3조"),
        ("100명", "100명"),
        ("3년", "3년"),
    ],
)
def test_legal_reference_and_quantity_patterns_are_preserved(kiwi, text, expected):
    assert expected in _normalized_forms(kiwi, text)
