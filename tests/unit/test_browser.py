"""Тести для browser tools — двошарова стратегія web_fetch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from posipaka.integrations.browser.tools import (
    JS_ONLY_PATTERNS,
    FetchResult,
    _extract_content,
    web_fetch,
)

# ---------------------------------------------------------------------------
# FetchResult.is_valid()
# ---------------------------------------------------------------------------


class TestFetchResultIsValid:
    def test_valid_content(self):
        r = FetchResult(content="x" * 300)
        assert r.is_valid() is True

    def test_too_short(self):
        r = FetchResult(content="short")
        assert r.is_valid() is False

    def test_exactly_200_chars(self):
        r = FetchResult(content="x" * 200)
        assert r.is_valid() is True

    def test_empty(self):
        r = FetchResult(content="")
        assert r.is_valid() is False

    def test_js_only_noscript(self):
        r = FetchResult(content="a" * 100 + "<noscript>" + "b" * 200)
        assert r.is_valid() is False

    def test_js_only_root_div(self):
        r = FetchResult(content='<div id="root"></div>' + "x" * 300)
        assert r.is_valid() is False

    def test_js_only_enable_javascript(self):
        r = FetchResult(content="Please enable JavaScript to continue " + "x" * 300)
        assert r.is_valid() is False

    def test_error_makes_invalid(self):
        r = FetchResult(content="x" * 500, error="connection refused")
        assert r.is_valid() is False

    def test_all_js_patterns_detected(self):
        for pattern in JS_ONLY_PATTERNS:
            r = FetchResult(content=pattern + "x" * 300)
            assert r.is_valid() is False, f"Патерн не виявлено: {pattern}"


# ---------------------------------------------------------------------------
# _extract_content()
# ---------------------------------------------------------------------------


class TestExtractContent:
    def test_extracts_title(self):
        html = (
            "<html><head><title>Test Page</title></head>"
            "<body><p>Hello world content here enough text"
            "</p></body></html>"
        )
        result = _extract_content(html, "https://example.com")
        assert result.title == "Test Page"

    def test_extracts_links_absolute(self):
        html = '<body><a href="https://other.com/page">Link</a><p>' + "x" * 300 + "</p></body>"
        result = _extract_content(html, "https://example.com")
        assert "https://other.com/page" in result.links

    def test_extracts_links_relative(self):
        html = '<body><a href="/about">About</a><p>' + "x" * 300 + "</p></body>"
        result = _extract_content(html, "https://example.com")
        assert "https://example.com/about" in result.links

    def test_removes_scripts_and_styles(self):
        html = "<body><script>alert(1)</script><style>.x{}</style><p>Real content here</p></body>"
        result = _extract_content(html, "https://example.com")
        assert "alert" not in result.content
        assert "Real content" in result.content

    def test_truncates_long_content(self):
        html = "<body><p>" + "x" * 6000 + "</p></body>"
        result = _extract_content(html, "https://example.com")
        assert len(result.content) < 5200
        assert "обрізано" in result.content


# ---------------------------------------------------------------------------
# web_fetch — двошарова стратегія
# ---------------------------------------------------------------------------


class TestWebFetchTwoLayer:
    """Перевірка що httpx використовується для простих сторінок,
    а Playwright тільки для JS-only."""

    @pytest.mark.asyncio
    async def test_httpx_sufficient_no_playwright(self):
        """Якщо httpx повернув достатньо контенту — Playwright НЕ викликається."""
        good_html = (
            "<html><head><title>Docs</title></head>"
            "<body><p>" + "A" * 500 + "</p></body></html>"
        )

        mock_response = MagicMock()
        mock_response.text = good_html
        mock_response.raise_for_status = MagicMock()

        with (
            patch("posipaka.integrations.browser.tools._validate_url", return_value=(True, "ok")),
            patch("httpx.AsyncClient") as mock_client_cls,
            patch(
                "posipaka.integrations.browser.tools._fetch_with_playwright",
            ) as mock_pw,
            patch(
                "posipaka.integrations.browser.tools.sanitize_external_content",
                side_effect=lambda c, **kw: c,
            ),
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await web_fetch("https://docs.python.org/3/", extract_text=True)

            # Playwright не повинен викликатись
            mock_pw.assert_not_called()
            assert "A" * 50 in result

    @pytest.mark.asyncio
    async def test_js_only_triggers_playwright(self):
        """Якщо httpx повернув JS-only — Playwright має викликатись."""
        js_only_html = (
            '<html><body><div id="root"></div>'
            '<script src="app.js"></script></body></html>'
        )

        mock_response = MagicMock()
        mock_response.text = js_only_html
        mock_response.raise_for_status = MagicMock()

        pw_result = FetchResult(
            title="SPA App",
            content="B" * 500,
            method="playwright",
        )

        with (
            patch("posipaka.integrations.browser.tools._validate_url", return_value=(True, "ok")),
            patch("httpx.AsyncClient") as mock_client_cls,
            patch(
                "posipaka.integrations.browser.tools._fetch_with_playwright",
                return_value=pw_result,
            ) as mock_pw,
            patch(
                "posipaka.integrations.browser.tools.sanitize_external_content",
                side_effect=lambda c, **kw: c,
            ),
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await web_fetch("https://spa-app.com/", extract_text=True)

            # Playwright повинен викликатись
            mock_pw.assert_called_once_with("https://spa-app.com/")
            assert "B" * 50 in result

    @pytest.mark.asyncio
    async def test_ssrf_blocked(self):
        """SSRF перевірка блокує внутрішні URL."""
        with patch(
            "posipaka.integrations.browser.tools._validate_url",
            return_value=(False, "Внутрішня IP адреса: 127.0.0.1"),
        ):
            result = await web_fetch("http://127.0.0.1/admin")
            assert "SSRF" in result
            assert "заблоковано" in result

    @pytest.mark.asyncio
    async def test_httpx_error_triggers_playwright(self):
        """Якщо httpx кинув помилку — Playwright має спрацювати."""
        pw_result = FetchResult(
            title="Fallback",
            content="C" * 500,
            method="playwright",
        )

        with (
            patch("posipaka.integrations.browser.tools._validate_url", return_value=(True, "ok")),
            patch(
                "posipaka.integrations.browser.tools._fetch_with_httpx",
            ) as mock_httpx,
            patch(
                "posipaka.integrations.browser.tools._fetch_with_playwright",
                return_value=pw_result,
            ),
            patch(
                "posipaka.integrations.browser.tools.sanitize_external_content",
                side_effect=lambda c, **kw: c,
            ),
        ):
            mock_httpx.return_value = FetchResult(method="httpx", error="timeout")

            result = await web_fetch("https://heavy-js.com/")
            assert "C" * 50 in result
