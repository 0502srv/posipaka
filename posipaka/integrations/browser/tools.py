"""Posipaka — Browser Integration. Web search, fetch, screenshot."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote_plus, urljoin

import httpx
from loguru import logger

from posipaka.security.injection import sanitize_external_content
from posipaka.security.ssrf import validate_url as _validate_url

# ---------------------------------------------------------------------------
# FetchResult + JS-only detection
# ---------------------------------------------------------------------------

_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

JS_ONLY_PATTERNS: list[str] = [
    "enable javascript",
    "you need javascript",
    "javascript is required",
    "please enable javascript",
    "this app requires javascript",
    '<div id="root"></div>',
    '<div id="app"></div>',
    "<noscript>",
]


@dataclass
class FetchResult:
    """Result of a web_fetch operation."""

    title: str = ""
    content: str = ""
    links: list[str] = field(default_factory=list)
    method: str = ""  # "httpx" or "playwright"
    error: str = ""

    def is_valid(self) -> bool:
        """Content is sufficient and not a JS-only placeholder."""
        if self.error:
            return False
        stripped = self.content.strip()
        if len(stripped) < 200:
            return False
        lower = stripped.lower()
        return not any(p in lower for p in JS_ONLY_PATTERNS)


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


# ---------------------------------------------------------------------------
# Шар 1 — легкий httpx fetch (без браузера)
# ---------------------------------------------------------------------------


def _extract_content(html: str, base_url: str) -> FetchResult:
    """Витягнути текст, title, links з HTML через BeautifulSoup."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        # Без BeautifulSoup — повернути raw (обрізаний)
        text = html
        if len(text) > 5000:
            text = text[:5000] + "\n... (обрізано)"
        return FetchResult(content=text)

    soup = BeautifulSoup(html, "html.parser")

    # Title
    title = ""
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        title = title_tag.string.strip()

    # Links (абсолютні URL)
    links: list[str] = []
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if href.startswith(("http://", "https://")):
            links.append(href)
        elif href.startswith("/"):
            links.append(urljoin(base_url, href))

    # Текст (без скриптів, стилів, навігації)
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    if len(text) > 5000:
        text = text[:5000] + "\n... (обрізано)"

    return FetchResult(title=title, content=text, links=links[:50])


async def _fetch_with_httpx(url: str) -> FetchResult:
    """Легкий fetch через httpx — без браузера, ~0 RAM overhead."""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": _BROWSER_UA})
            response.raise_for_status()

        result = _extract_content(response.text, url)
        result.method = "httpx"
        return result
    except Exception as e:
        return FetchResult(method="httpx", error=str(e))


# ---------------------------------------------------------------------------
# Шар 2 — Playwright fallback (тільки якщо httpx не вистачило)
# ---------------------------------------------------------------------------


async def _fetch_with_playwright(url: str) -> FetchResult:
    """Playwright fetch — для JS-heavy сторінок."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return FetchResult(
            method="playwright",
            error=(
                "Playwright не встановлено. "
                "pip install playwright && playwright install chromium"
            ),
        )

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=_BROWSER_UA)
            await page.goto(url, wait_until="networkidle", timeout=30000)
            html = await page.content()
            await browser.close()

        result = _extract_content(html, url)
        result.method = "playwright"
        return result
    except Exception as e:
        return FetchResult(method="playwright", error=str(e))


# ---------------------------------------------------------------------------
# web_fetch — двошарова стратегія: httpx → Playwright fallback
# ---------------------------------------------------------------------------


async def web_fetch(url: str, extract_text: bool = True) -> str:
    """Двошаровий fetch: httpx → Playwright fallback.

    Шар 1 (httpx): швидко, без RAM overhead. Достатньо для 80% сайтів.
    Шар 2 (Playwright): тільки якщо httpx повернув порожній/JS-only контент.
    """
    start = time.monotonic()

    # SSRF protection — завжди першим
    safe, reason = _validate_url(url)
    if not safe:
        return f"URL заблоковано (SSRF protection): {reason}"

    # Шар 1: легкий httpx
    result = await _fetch_with_httpx(url)
    if result.is_valid():
        elapsed = (time.monotonic() - start) * 1000
        logger.info(
            f"web_fetch url={url} method=httpx chars={len(result.content)} "
            f"elapsed={elapsed:.0f}ms"
        )
        return sanitize_external_content(result.content, source=url)

    # Шар 2: Playwright fallback
    logger.debug(
        f"web_fetch httpx недостатньо для {url} "
        f"(chars={len(result.content)}, error={result.error!r}), "
        f"переключаюсь на Playwright"
    )
    result = await _fetch_with_playwright(url)

    elapsed = (time.monotonic() - start) * 1000
    if result.error:
        logger.error(
            f"web_fetch url={url} method=playwright error={result.error} "
            f"elapsed={elapsed:.0f}ms"
        )
        return f"Помилка завантаження {url}: {result.error}"

    logger.info(
        f"web_fetch url={url} method=playwright chars={len(result.content)} "
        f"elapsed={elapsed:.0f}ms"
    )

    return sanitize_external_content(result.content, source=url)


async def web_screenshot(url: str) -> str:
    """Зробити скріншот веб-сторінки (потрібен playwright)."""
    start = time.monotonic()

    # SSRF protection — обов'язково
    safe, reason = _validate_url(url)
    if not safe:
        return f"URL заблоковано (SSRF protection): {reason}"

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=_BROWSER_UA)
            await page.goto(url, wait_until="networkidle", timeout=30000)
            screenshot = await page.screenshot(full_page=False)
            await browser.close()

        elapsed = (time.monotonic() - start) * 1000
        logger.info(
            f"web_screenshot url={url} "
            f"bytes={len(screenshot)} elapsed={elapsed:.0f}ms"
        )
        return f"Screenshot saved ({len(screenshot)} bytes)"
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
