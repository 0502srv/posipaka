"""Batch API processor для non-urgent tasks."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class BatchRequest:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    messages: list[dict] = field(default_factory=list)
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 1024
    metadata: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class BatchResult:
    id: str
    response: str = ""
    tokens_used: int = 0
    cost_usd: float = 0.0
    error: str | None = None


class BatchProcessor:
    """Batch processing для non-urgent tasks.

    Для heartbeat analysis, daily briefs, scheduled reports.
    ~50% cheaper than real-time API calls.
    """

    MAX_BATCH_SIZE = 20
    MAX_BATCH_AGE = 300  # секунд

    def __init__(self, llm_call=None) -> None:
        self._queue: list[BatchRequest] = []
        self._results: dict[str, BatchResult] = {}
        self._llm_call = llm_call
        self._lock = asyncio.Lock()

    async def add_request(
        self,
        messages: list[dict],
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 1024,
        **metadata,
    ) -> str:
        """Додати запит у чергу. Повертає request_id."""
        req = BatchRequest(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            metadata=metadata,
        )
        async with self._lock:
            self._queue.append(req)
            logger.debug(f"Batch request queued: {req.id} (queue: {len(self._queue)})")

            # Auto-flush якщо черга повна
            if len(self._queue) >= self.MAX_BATCH_SIZE:
                await self._flush_locked()

        return req.id

    async def flush(self) -> list[BatchResult]:
        """Обробити всі запити з черги."""
        async with self._lock:
            return await self._flush_locked()

    async def _flush_locked(self) -> list[BatchResult]:
        """Обробити чергу (під lock)."""
        if not self._queue:
            return []

        requests = list(self._queue)
        self._queue.clear()

        results = []
        logger.info(f"Processing batch of {len(requests)} requests")

        # Fallback: sequential processing (batch API не завжди доступний)
        for req in requests:
            try:
                if self._llm_call:
                    response = await self._llm_call(
                        messages=req.messages,
                        model=req.model,
                        max_tokens=req.max_tokens,
                    )
                    result = BatchResult(
                        id=req.id,
                        response=response.get("content", ""),
                        tokens_used=response.get("usage", {}).get("total_tokens", 0),
                        cost_usd=response.get("cost", 0.0),
                    )
                else:
                    result = BatchResult(
                        id=req.id,
                        error="No LLM callback configured",
                    )
            except Exception as e:
                result = BatchResult(id=req.id, error=str(e))

            results.append(result)
            self._results[req.id] = result

        return results

    async def get_result(self, request_id: str) -> BatchResult | None:
        """Отримати результат за ID."""
        return self._results.get(request_id)

    async def check_and_flush(self) -> list[BatchResult]:
        """Перевірити вік черги і flush якщо старіше MAX_BATCH_AGE."""
        async with self._lock:
            if not self._queue:
                return []
            oldest = min(r.created_at for r in self._queue)
            if time.time() - oldest >= self.MAX_BATCH_AGE:
                return await self._flush_locked()
        return []

    @property
    def queue_size(self) -> int:
        return len(self._queue)
