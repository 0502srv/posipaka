"""Posipaka — Browser Integration. Web search, fetch, screenshot."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

import httpx
from loguru import logger

from posipaka.security.injection import sanitize_external_content


async def web_search(query: str, num_results: int = 5) -> str:
    """Пошук в інтернеті через DuckDuckGo HTML."""
    try:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                url, headers={"User-Agent": "Mozilla/5.0 (compatible; Posipaka/0.1)"}
            )
            response.raise_for_status()

        # Parse results
        from html.parser import HTMLParser

        class DDGParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.results = []
                self._in_result = False
                self._current = {}
                self._capture_text = False

            def handle_starttag(self, tag, attrs):
                attrs_dict = dict(attrs)
                if tag == "a" and "result__a" in attrs_dict.get("class", ""):
                    self._in_result = True
                    self._current = {"url": attrs_dict.get("href", ""), "title": ""}
                    self._capture_text = True
                elif tag == "a" and "result__snippet" in attrs_dict.get("class", ""):
                    self._capture_text = True

            def handle_data(self, data):
                if self._capture_text and self._in_result:
                    if "title" in self._current and not self._current.get("snippet"):
                        self._current["title"] += data
                    else:
                        self._current.setdefault("snippet", "")
                        self._current["snippet"] += data

            def handle_endtag(self, tag):
                if tag == "a" and self._in_result and self._current.get("title"):
                    self._capture_text = False
                    if len(self.results) < num_results:
                        self.results.append(dict(self._current))
                    self._in_result = False
                    self._current = {}

        parser = DDGParser()
        parser.feed(response.text)

        if not parser.results:
            return f"Нічого не знайдено за запитом: {query}"

        lines = [f"Результати пошуку: '{query}'\n"]
        for i, r in enumerate(parser.results[:num_results], 1):
            lines.append(f"{i}. {r.get('title', 'Без назви')}")
            if r.get("url"):
                lines.append(f"   URL: {r['url']}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet'][:200]}")
            lines.append("")

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Web search error: {e}")
        return f"Помилка пошуку: {e}"


async def web_fetch(url: str, extract_text: bool = True) -> str:
    """Завантажити веб-сторінку."""
    try:
        # SSRF protection
        from posipaka.security.ssrf import validate_url

        safe, reason = validate_url(url)
        if not safe:
            return f"URL заблоковано (SSRF protection): {reason}"

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(
                url, headers={"User-Agent": "Mozilla/5.0 (compatible; Posipaka/0.1)"}
            )
            response.raise_for_status()

        content = response.text

        if extract_text:
            try:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(content, "html.parser")
                # Remove scripts and styles
                for tag in soup(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                text = soup.get_text(separator="\n", strip=True)
                # Trim
                if len(text) > 5000:
                    text = text[:5000] + "\n... (обрізано)"
                content = text
            except ImportError:
                # Without beautifulsoup — return raw
                if len(content) > 5000:
                    content = content[:5000] + "\n... (обрізано)"

        return sanitize_external_content(content, source=url)
    except Exception as e:
        return f"Помилка завантаження {url}: {e}"


async def web_screenshot(url: str) -> str:
    """Зробити скріншот веб-сторінки (потрібен playwright)."""
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            screenshot = await page.screenshot(full_page=False)
            await browser.close()

        import base64

        base64.b64encode(screenshot).decode()
        return f"Screenshot saved (base64, {len(screenshot)} bytes)"
    except ImportError:
        return (
            "Playwright не встановлено. Виконайте: "
            "pip install playwright && playwright install chromium"
        )
    except Exception as e:
        return f"Помилка скріншоту: {e}"


def register(registry: Any) -> None:
    """Реєстрація browser tools."""
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="web_search",
            description=(
                "Search the internet using DuckDuckGo. Use for finding information, news, answers."
            ),
            category="integration",
            handler=web_search,
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "num_results": {
                        "type": "integer",
                        "description": "Number of results (default 5)",
                    },
                },
            },
            tags=["browser", "search"],
        )
    )

    registry.register(
        ToolDefinition(
            name="web_fetch",
            description=(
                "Fetch and read a web page. Use to read articles, documentation, web content."
            ),
            category="integration",
            handler=web_fetch,
            input_schema={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                    "extract_text": {
                        "type": "boolean",
                        "description": "Extract text only (default true)",
                    },
                },
            },
            tags=["browser", "web"],
        )
    )

    registry.register(
        ToolDefinition(
            name="web_screenshot",
            description="Take a screenshot of a web page. Requires playwright.",
            category="integration",
            handler=web_screenshot,
            input_schema={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string", "description": "URL to screenshot"},
                },
            },
            tags=["browser", "web"],
        )
    )
