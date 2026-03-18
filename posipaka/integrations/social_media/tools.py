"""Social Media integration — Twitter/X, LinkedIn (MASTER.md sec 46.1).

Uses httpx for API calls. Requires API tokens per platform.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

# ─── Twitter/X ──────────────────────────────────────────────────────

async def twitter_post(text: str) -> str:
    """Опублікувати твіт (X/Twitter API v2)."""
    bearer = os.environ.get("TWITTER_BEARER_TOKEN", "")
    if not bearer:
        return "Twitter API не налаштовано. Встановіть TWITTER_BEARER_TOKEN."
    if len(text) > 280:
        return f"Твіт занадто довгий: {len(text)} символів (максимум 280)."

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.twitter.com/2/tweets",
                headers={"Authorization": f"Bearer {bearer}"},
                json={"text": text},
            )
            resp.raise_for_status()
            data = resp.json()
            tweet_id = data.get("data", {}).get("id", "unknown")
        return f"Твіт опубліковано: https://twitter.com/i/status/{tweet_id}"
    except httpx.HTTPError as e:
        return f"Помилка Twitter API: {e}"


async def twitter_search(query: str, max_results: int = 10) -> str:
    """Пошук твітів."""
    bearer = os.environ.get("TWITTER_BEARER_TOKEN", "")
    if not bearer:
        return "Twitter API не налаштовано."
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.twitter.com/2/tweets/search/recent",
                headers={"Authorization": f"Bearer {bearer}"},
                params={"query": query, "max_results": min(max_results, 100)},
            )
            resp.raise_for_status()
            data = resp.json()
        tweets = data.get("data", [])
        if not tweets:
            return f"Нічого не знайдено за запитом '{query}'."
        lines = [f"Результати пошуку '{query}':"]
        for t in tweets[:max_results]:
            lines.append(f"  • {t.get('text', '')[:120]}")
        return "\n".join(lines)
    except httpx.HTTPError as e:
        return f"Помилка Twitter API: {e}"


# ─── LinkedIn ───────────────────────────────────────────────────────

async def linkedin_post(text: str) -> str:
    """Опублікувати пост у LinkedIn."""
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
    if not token:
        return "LinkedIn API не налаштовано. Встановіть LINKEDIN_ACCESS_TOKEN."

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Get user URN
            me_resp = await client.get(
                "https://api.linkedin.com/v2/userinfo",
                headers={"Authorization": f"Bearer {token}"},
            )
            me_resp.raise_for_status()
            user_sub = me_resp.json().get("sub", "")

            resp = await client.post(
                "https://api.linkedin.com/v2/ugcPosts",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Restli-Protocol-Version": "2.0.0",
                },
                json={
                    "author": f"urn:li:person:{user_sub}",
                    "lifecycleState": "PUBLISHED",
                    "specificContent": {
                        "com.linkedin.ugc.ShareContent": {
                            "shareCommentary": {"text": text},
                            "shareMediaCategory": "NONE",
                        }
                    },
                    "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
                },
            )
            resp.raise_for_status()
        return "Пост опубліковано в LinkedIn."
    except httpx.HTTPError as e:
        return f"Помилка LinkedIn API: {e}"


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="twitter_post",
            description="Post a tweet to Twitter/X. Max 280 characters.",
            category="social_media",
            handler=twitter_post,
            requires_approval=True,
            input_schema={
                "type": "object",
                "required": ["text"],
                "properties": {
                    "text": {"type": "string", "description": "Tweet text (max 280 chars)"},
                },
            },
            tags=["social", "twitter"],
        )
    )

    registry.register(
        ToolDefinition(
            name="twitter_search",
            description="Search recent tweets on Twitter/X.",
            category="social_media",
            handler=twitter_search,
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "description": "Max results (default 10)"},
                },
            },
            tags=["social", "twitter", "search"],
        )
    )

    registry.register(
        ToolDefinition(
            name="linkedin_post",
            description="Publish a post to LinkedIn.",
            category="social_media",
            handler=linkedin_post,
            requires_approval=True,
            input_schema={
                "type": "object",
                "required": ["text"],
                "properties": {
                    "text": {"type": "string", "description": "Post text"},
                },
            },
            tags=["social", "linkedin"],
        )
    )
