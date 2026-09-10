"""Smoke test: count_tokens no revienta con tiktoken presente o ausente
(fallback heuristico ~4 chars/token), y es monotono con la longitud del texto."""

from leo_code.core.tokens import count_tokens


def test_empty_text_is_zero_tokens():
    assert count_tokens("") == 0


def test_nonempty_text_has_positive_tokens():
    assert count_tokens("hola mundo") > 0


def test_longer_text_has_more_tokens():
    assert count_tokens("palabra " * 200) > count_tokens("palabra " * 5)
