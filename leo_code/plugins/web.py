"""Web Plugin — fetch URLs y búsqueda web (DuckDuckGo, sin API key)."""

from leo_code.plugins import Plugin, register_builtin


class WebPlugin(Plugin):
    name = "web"
    version = "0.1.0"

    def on_init(self, config: dict, repo_path: str):
        self.config = config
        self.timeout = config.get("timeout", 15)

    def on_tool_register(self, registry):
        registry.register("web_fetch", self.web_fetch,
            {"name": "web_fetch", "description": "Descargar el contenido de una URL (HTML o markdown)",
             "parameters": {"type": "object", "properties": {"url": {"type": "string", "description": "URL a descargar"}}, "required": ["url"]}})
        registry.register("web_search", self.web_search,
            {"name": "web_search", "description": "Buscar en la web usando DuckDuckGo (gratis, sin API key). Retorna títulos y snippets.",
             "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Términos de búsqueda"}}, "required": ["query"]}})

    def web_fetch(self, args: dict, repo_path: str) -> str:
        url = args.get("url", "")
        if not url.startswith("http"):
            return "[URL inválida]"
        try:
            import httpx
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                r = client.get(url, headers={"User-Agent": "leo-code/0.2.0"})
                r.raise_for_status()
                ct = r.headers.get("content-type", "")
                if "text/html" in ct:
                    text = self._html_to_text(r.text)
                    return text[:3000] if len(text) > 3000 else text
                return r.text[:3000]
        except Exception as e:
            return f"[web_fetch error: {e}]"

    def web_search(self, args: dict, repo_path: str) -> str:
        query = args.get("query", "")
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=5))
            if not results:
                return "[Sin resultados]"
            return "\n".join(f"{r['title']}\n  {r['href']}\n  {r['body'][:200]}" for r in results)
        except ImportError:
            return "[web_search requiere: pip install duckduckgo-search]"
        except Exception as e:
            return f"[web_search error: {e}]"

    @staticmethod
    def _html_to_text(html: str) -> str:
        try:
            from html.parser import HTMLParser
            class TextExtractor(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.text = []
                    self.skip = False
                def handle_starttag(self, tag, attrs):
                    if tag in ("script", "style", "noscript"):
                        self.skip = True
                def handle_endtag(self, tag):
                    if tag in ("script", "style", "noscript"):
                        self.skip = False
                def handle_data(self, data):
                    if not self.skip:
                        stripped = data.strip()
                        if stripped:
                            self.text.append(stripped)
            extractor = TextExtractor()
            extractor.feed(html)
            return "\n".join(extractor.text)
        except Exception:
            import re
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text)
            return text.strip()


register_builtin("web", WebPlugin)
