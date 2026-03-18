"""Token bucket rate limiter."""

from __future__ import annotations

import time


class RateLimiter:
    """Token bucket rate limiter."""

    def __init__(self, rate: float, per: float = 60.0) -> None:
        """
        Args:
            rate: Кількість дозволених запитів.
            per: За який період (секунди). Default: 60s = per minute.
        """
        self.rate = rate
        self.per = per
        self._allowance = rate
        self._last_check = time.monotonic()

    def allow(self) -> bool:
        """Перевірити чи запит дозволений."""
        now = time.monotonic()
        elapsed = now - self._last_check
        self._last_check = now
        self._allowance += elapsed * (self.rate / self.per)
        if self._allowance > self.rate:
            self._allowance = self.rate
        if self._allowance < 1.0:
            return False
        self._allowance -= 1.0
        return True

    def retry_after(self) -> float:
        """Скільки секунд чекати до наступного дозволеного запиту."""
        if self._allowance >= 1.0:
            return 0.0
        return (1.0 - self._allowance) * (self.per / self.rate)
