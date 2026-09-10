"""Smoke test del parser generico multi-lenguaje (regex-based, sin tree-sitter)."""

from leo_code.core.parser_generic import extract_generic, extract_html_css


def test_extract_generic_javascript_function():
    caps = extract_generic(
        "function greet(name) {\n  return name;\n}\n", "greet.js", "javascript"
    )
    assert "greet" in {c.name for c in caps}


def test_extract_generic_unknown_language_uses_heuristic_fallback():
    caps = extract_generic("def greet():\n    return 1\n", "greet.mystery", "cobol")
    assert isinstance(caps, list)  # lenguaje sin patterns: no debe reventar


def test_extract_html_css_html_collects_tags_and_classes():
    caps = extract_html_css(
        '<html><body class="main"><h1>Hola</h1></body></html>', "index.html", "html"
    )
    assert caps[0].type == "document"
    assert "h1" in caps[0].properties["tags"]
    assert "main" in caps[0].properties["css_classes"]


def test_extract_html_css_css_collects_selectors():
    caps = extract_html_css(".btn { color: red; }", "style.css", "css")
    assert ".btn" in caps[0].properties["selectors"]
