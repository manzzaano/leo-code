"""Parser genérico multi-lenguaje vía regex patterns.

Soporta: JavaScript, TypeScript, Go, Rust, Java, Ruby, C, C++, C#, HTML, CSS.
Para lenguajes sin patterns específicos, usa heurística de indentación.
"""

import re
from pathlib import Path

from leo_code.core.parser import Capsule, _make_id

_LANG_PATTERNS: dict[str, dict[str, str]] = {
    "javascript": {
        "function": r"(?:async\s+)?function\s+(\w+)\s*\((.*?)\)",
        "arrow": r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\((.*?)\)\s*=>",
        "class": r"class\s+(\w+)(?:\s+extends\s+(\w+))?",
        "import": r"import\s+(?:\{[^}]*\}|\*\s+as\s+\w+|\w+)\s+from\s+['\"](.+?)['\"]",
        "require": r"(?:const|let|var)\s+\w+\s*=\s*require\(['\"](.+?)['\"]\)",
    },
    "typescript": {
        "function": r"(?:async\s+)?function\s+(\w+)\s*\((.*?)\)(?:\s*:\s*\w+)?",
        "arrow": r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\((.*?)\)\s*=>",
        "class": r"class\s+(\w+)(?:\s+extends\s+(\w+))?(?:\s+implements\s+[^{]+)?",
        "interface": r"(?:export\s+)?interface\s+(\w+)",
        "type": r"(?:export\s+)?type\s+(\w+)\s*=",
        "import": r"import\s+(?:\{[^}]*\}|\*\s+as\s+\w+|\w+)\s+from\s+['\"](.+?)['\"]",
    },
    "go": {
        "function": r"func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\((.*?)\)",
        "method": r"func\s+\((\w+)\s+\*?(\w+)\)\s+(\w+)\s*\((.*?)\)",
        "struct": r"type\s+(\w+)\s+struct\s*\{",
        "interface": r"type\s+(\w+)\s+interface\s*\{",
        "import_block": r'import\s+(?:\w+\s+)?["]([^"]+)["]',
    },
    "rust": {
        "function": r"(?:pub(?:\s*\(\s*crate\s*\))?\s+)?fn\s+(\w+)\s*[<(](.*?)[)>]",
        "struct": r"(?:pub\s+)?struct\s+(\w+)(?:<[^>]+>)?",
        "enum": r"(?:pub\s+)?enum\s+(\w+)",
        "impl": r"impl\s+(?:<[^>]+>\s*)?(\w+)",
        "trait": r"(?:pub\s+)?trait\s+(\w+)",
        "use": r"use\s+(.+?);",
    },
    "java": {
        "method": r"(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?(?:\w+(?:<[^>]+>)?\s+)?(\w+)\s*\((.*?)\)",
        "class": r"(?:public\s+)?(?:abstract\s+)?class\s+(\w+)",
        "interface": r"(?:public\s+)?interface\s+(\w+)",
        "import": r"import\s+(.+?);",
    },
    "ruby": {
        "def": r"def\s+(self\.)?(\w+)(?:\((.*?)\))?",
        "class": r"class\s+(\w+)(?:\s*<\s*(\w+))?",
        "module": r"module\s+(\w+)",
        "require": r"require\s+['\"](.+?)['\"]",
    },
    "c": {
        "function": r"(?:static\s+)?(?:inline\s+)?\w+(?:\s*\*)?\s+(\w+)\s*\((.*?)\)",
    },
    "cpp": {
        "function": r"(?:virtual\s+)?(?:static\s+)?\w+(?:::\w+)?(?:\s*[*&])?\s+(\w+)\s*\((.*?)\)",
        "class": r"class\s+(\w+)(?:\s*:\s*public\s+\w+)?",
        "include": r'#include\s+[<"](.+?)[>"]',
    },
    "csharp": {
        "method": r"(?:public|private|protected|internal)\s+(?:static\s+)?(?:async\s+)?\w+(?:<[^>]+>)?\s+(\w+)\s*\((.*?)\)",
        "class": r"(?:public\s+)?class\s+(\w+)",
        "using": r"using\s+([^;]+);",
    },
}

_LANG_COMMENT: dict[str, str] = {
    "javascript": "//", "typescript": "//", "go": "//", "rust": "//",
    "java": "//", "c": "//", "cpp": "//", "csharp": "//", "ruby": "#",
}

_FUNC_DECORATION = r"^\s*(?:pub|export|static|async|virtual|inline|const|fn|func|def|function|class)\b"


def extract_generic(content: str, file_path: str, language: str) -> list[Capsule]:
    patterns = _LANG_PATTERNS.get(language)
    if patterns is None:
        return _extract_heuristic(content, file_path, language)

    module_name = Path(file_path).stem
    capsules = []
    seen_lines: set[int] = set()
    lines = content.split("\n")

    for ptype, pattern in patterns.items():
        for match in re.finditer(pattern, content, re.MULTILINE):
            before = content[:match.start()]
            lineno = before.count("\n") + 1

            if lineno in seen_lines and ptype not in ("import", "require", "include", "using"):
                continue

            if _is_comment(lines, lineno, language):
                continue

            seen_lines.add(lineno)
            cap = _build_capsule(match, ptype, language, file_path, module_name, content, lineno, lines)
            if cap:
                capsules.append(cap)

    return capsules


def _build_capsule(match: re.Match, ptype: str, language: str,
                   file_path: str, module_name: str, content: str,
                   lineno: int, lines: list[str]) -> Capsule | None:
    groups = match.groups()
    name = groups[0] if groups else ""
    if not name:
        return None
    if name in ("if", "for", "while", "switch", "return", "new", "throw", "else", "case", "default"):
        return None

    params = groups[1] if len(groups) > 1 else ""

    type_map = {
        "function": "function", "arrow": "function", "method": "function", "def": "function",
        "class": "class", "struct": "class", "interface": "class",
        "enum": "class", "impl": "class", "trait": "class", "module": "class", "type": "class",
        "import": "module", "require": "module", "use": "module",
        "import_block": "module", "include": "module", "using": "module",
    }
    ctype = type_map.get(ptype, "function")

    sig = _build_signature(language, ptype, name, params)

    end_lineno = _find_block_end(lines, lineno, language)
    block_content = "\n".join(lines[lineno - 1:end_lineno])
    if len(block_content) > 3000:
        block_content = block_content[:3000] + "\n# ... [truncado]"

    calls = _find_calls_in_block(block_content, language)

    return Capsule(
        id=_make_id(file_path, lineno, sig),
        type=ctype, name=name, file_path=file_path,
        start_line=lineno, end_line=end_lineno,
        language=language, signature=sig,
        content=block_content,
        calls=calls,
        properties={
            "lineas": end_lineno - lineno + 1,
            "module": module_name,
        },
    )


def _is_comment(lines: list[str], lineno: int, language: str) -> bool:
    comment_prefix = _LANG_COMMENT.get(language, "//")
    if lineno < 1 or lineno > len(lines):
        return False
    line = lines[lineno - 1].strip()
    return line.startswith(comment_prefix)


def _build_signature(language: str, ptype: str, name: str, params: str) -> str:
    keyword_map = {
        "javascript": "function", "typescript": "function", "go": "func",
        "rust": "fn", "java": "def", "ruby": "def", "c": "func", "cpp": "func", "csharp": "def",
    }
    kw = keyword_map.get(language, "def")

    if ptype == "class":
        return f"class {name}"
    if ptype in ("struct", "enum"):
        return f"{ptype} {name}"
    if ptype in ("import", "require", "use", "import_block", "include", "using"):
        return f"import {name}"

    params_fmt = params[:120] if len(params) <= 120 else params[:117] + "..."
    return f"{kw} {name}({params_fmt})"


def _find_block_end(lines: list[str], start_lineno: int, language: str) -> int:
    if start_lineno < 1 or start_lineno > len(lines):
        return min(start_lineno + 10, len(lines))

    brace_langs = {"javascript", "typescript", "go", "rust", "java", "c", "cpp", "csharp"}
    if language in brace_langs:
        depth = 0
        started = False
        for i in range(start_lineno - 1, len(lines)):
            line = lines[i]
            depth += line.count("{") - line.count("}")
            if "{" in line:
                started = True
            if started and depth == 0:
                return i + 1
        return min(start_lineno + 20, len(lines))

    if language == "ruby":
        match = re.match(r"^\s*", lines[start_lineno - 1])
        base_indent = len(match.group()) if match else 0
        for i in range(start_lineno, len(lines)):
            if lines[i].strip() == "end":
                return i + 1
            if lines[i].strip() and not lines[i].startswith(" " * (base_indent + 1)):
                if i > start_lineno + 1:
                    return i
        return min(start_lineno + 30, len(lines))

    return min(start_lineno + 10, len(lines))


def _find_calls_in_block(content: str, language: str) -> list[str]:
    call_patterns = {
        "javascript": r"(\w+)\s*\(",
        "typescript": r"(\w+)\s*\(",
        "go": r"(\w+)\s*\(",
        "rust": r"(\w+)!\s*\(",
        "java": r"(\w+)\s*\(",
        "ruby": r"\.(\w+)(?:\s+|\()",
        "c": r"(\w+)\s*\(",
        "cpp": r"(\w+)\s*\(",
        "csharp": r"(\w+)\s*\(",
    }
    pattern = call_patterns.get(language, r"(\w+)\s*\(")
    stopwords = {"if", "for", "while", "switch", "return", "new", "throw", "catch",
                 "else", "case", "default", "import", "require", "print", "fmt", "log",
                 "super", "this", "self", "sizeof", "typeof", "void", "println"}
    calls = set()
    for m in re.finditer(pattern, content):
        name = m.group(1)
        if name not in stopwords and len(name) >= 2:
            calls.add(name)
    return sorted(calls)[:10]


def _extract_heuristic(content: str, file_path: str, language: str) -> list[Capsule]:
    """Fallback: detecta funciones por indentación de keywords universales."""
    module_name = Path(file_path).stem
    capsules = []
    lines = content.split("\n")

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//", "/*", "*", ";")):
            continue

        m = re.match(_FUNC_DECORATION, stripped)
        if not m:
            continue

        kw = m.group()
        sig = stripped[:200]
        end = _find_block_end(lines, i, language)

        block = "\n".join(lines[i - 1:end])
        if len(block) > 3000:
            block = block[:3000] + "\n# ... [truncado]"

        capsules.append(Capsule(
            id=_make_id(file_path, i, sig),
            type="class" if kw in ("class", "struct", "interface") else "function",
            name=f"__{module_name}_L{i}",
            file_path=file_path,
            start_line=i, end_line=end,
            language=language, signature=sig,
            content=block,
            properties={"lineas": end - i + 1, "module": module_name},
        ))

    return capsules


def extract_html_css(content: str, file_path: str, language: str) -> list[Capsule]:
    """Extrae estructura de HTML/CSS: tags, clases, meta tags, selectores."""
    module_name = Path(file_path).stem
    capsules = []

    if language == "html":
        caps = _parse_html(content, file_path, module_name)
    else:
        caps = _parse_css(content, file_path, module_name)

    capsules.extend(caps)
    return capsules


def _parse_html(content: str, file_path: str, module_name: str) -> list[Capsule]:
    capsules = []
    tags = re.findall(r"<\s*(\w+)", content)
    tag_counts: dict[str, int] = {}
    for t in tags:
        tag_counts[t] = tag_counts.get(t, 0) + 1

    classes = set()
    for m in re.finditer(r'class=["\x27]([^"\x27]+)["\x27]', content):
        classes.update(c.strip() for c in m.group(1).split())

    meta_tags: dict[str, str] = {}
    for m in re.finditer(r'<meta\s+([^>]+)>', content):
        attrs = m.group(1)
        name = re.search(r'name=["\x27]([^"\x27]+)["\x27]', attrs)
        prop = re.search(r'property=["\x27]([^"\x27]+)["\x27]', attrs)
        content_attr = re.search(r'content=["\x27]([^"\x27]+)["\x27]', attrs)
        key = (name or prop)
        if key and content_attr:
            meta_tags[key.group(1)] = content_attr.group(1)

    json_lds = re.findall(r'<script\s[^>]*type=["\x27]application/ld\+json["\x27][^>]*>(.*?)</script>', content, re.DOTALL)

    headings = re.findall(r"<(h[1-6])\b[^>]*>(.*?)</h[1-6]>", content)
    heading_texts = [f"{h.upper()}: {t.strip()[:100]}" for h, t in headings[:10]]

    html_capsule = Capsule(
        id=_make_id(file_path, 1, "html_structure"),
        type="document",
        name=f"{module_name}.html",
        file_path=file_path,
        start_line=1, end_line=content.count("\n") + 1,
        language="html",
        signature=f"[html] {module_name}",
        content=content[:3000],
        properties={
            "tags": ", ".join(f"{t}({c})" for t, c in sorted(tag_counts.items())),
            "css_classes": ", ".join(sorted(classes)[:30]),
            "meta_tags": ", ".join(f"{k}={v}" for k, v in meta_tags.items()),
            "headings": ", ".join(heading_texts),
            "json_ld": json_lds[0][:500] if json_lds else "",
            "chars": len(content),
        },
    )
    capsules.append(html_capsule)
    return capsules


def _parse_css(content: str, file_path: str, module_name: str) -> list[Capsule]:
    selectors = re.findall(r"([.#@]?[a-zA-Z][\w-]*)\s*\{", content)
    colors = re.findall(r"(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\)|hsla?\([^)]+\))", content)
    fonts = re.findall(r"font-family\s*:\s*([^;]+);", content)
    media_queries = re.findall(r"@media\s+([^{]+)\{", content)

    css_capsule = Capsule(
        id=_make_id(file_path, 1, "css_structure"),
        type="document",
        name=f"{module_name}.css",
        file_path=file_path,
        start_line=1, end_line=content.count("\n") + 1,
        language="css",
        signature=f"[css] {module_name}",
        content=content[:3000],
        properties={
            "selectors": ", ".join(set(selectors)[:30]),
            "colors": ", ".join(set(colors)[:20]),
            "fonts": ", ".join(f.strip() for f in fonts[:10]),
            "media_queries": ", ".join(mq.strip() for mq in media_queries[:5]),
            "chars": len(content),
        },
    )
    return [css_capsule]
