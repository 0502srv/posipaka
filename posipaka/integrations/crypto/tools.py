"""Posipaka — Crypto Integration (CoinGecko, no API key)."""

from __future__ import annotations

from typing import Any

import httpx

COINGECKO_API = "https://api.coingecko.com/api/v3"


async def get_crypto_price(symbol: str = "bitcoin") -> str:
    """Отримати поточну ціну криптовалюти."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{COINGECKO_API}/simple/price",
                params={
                    "ids": symbol.lower(),
                    "vs_currencies": "usd,eur,uah",
                    "include_24hr_change": "true",
                },
            )
            resp.raise_for_status()

        data = resp.json()
        coin_data = data.get(symbol.lower())
        if not coin_data:
            return f"Криптовалюта '{symbol}' не знайдена"

        usd = coin_data.get("usd", "?")
        eur = coin_data.get("eur", "?")
        uah = coin_data.get("uah", "?")
        change = coin_data.get("usd_24h_change", 0)
        arrow = "📈" if change > 0 else "📉"

        return (
            f"{symbol.upper()}:\n"
            f"💵 ${usd:,.2f} USD\n"
            f"💶 €{eur:,.2f} EUR\n"
            f"🇺🇦 ₴{uah:,.2f} UAH\n"
            f"{arrow} 24h: {change:+.2f}%"
        )
    except Exception as e:
        return f"Помилка крипто: {e}"


async def get_crypto_chart(symbol: str = "bitcoin", days: int = 7) -> str:
    """Отримати дані для графіку ціни."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{COINGECKO_API}/coins/{symbol.lower()}/market_chart",
                params={"vs_currency": "usd", "days": days},
            )
            resp.raise_for_status()

        data = resp.json()
        prices = data.get("prices", [])
        if not prices:
            return f"Немає даних для {symbol}"

        from datetime import datetime

        lines = [f"{symbol.upper()} — ціна за {days} днів:\n"]

        # Sample ~10 points
        step = max(1, len(prices) // 10)
        for i in range(0, len(prices), step):
            ts, price = prices[i]
            dt = datetime.fromtimestamp(ts / 1000).strftime("%m-%d %H:%M")
            lines.append(f"  {dt}: ${price:,.2f}")

        return "\n".join(lines)
    except Exception as e:
        return f"Помилка: {e}"


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="get_crypto_price",
            description="Get current cryptocurrency price (CoinGecko, no API key needed).",
            category="integration",
            handler=get_crypto_price,
            input_schema={
                "type": "object",
                "required": ["symbol"],
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Coin ID (e.g. bitcoin, ethereum, solana)",
                    },
                },
            },
            tags=["crypto", "finance"],
        )
    )

    registry.register(
        ToolDefinition(
            name="get_crypto_chart",
            description="Get crypto price history for charting.",
            category="integration",
            handler=get_crypto_chart,
            input_schema={
                "type": "object",
                "required": ["symbol"],
                "properties": {
                    "symbol": {"type": "string"},
                    "days": {"type": "integer", "description": "Days of history (default 7)"},
                },
            },
            tags=["crypto", "finance"],
        )
    )
