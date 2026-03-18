"""Tenacity retry helpers для API calls."""

from __future__ import annotations

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


def llm_retry(func):
    """Retry decorator для LLM API calls: 3 спроби, exponential backoff."""
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        reraise=True,
    )(func)
