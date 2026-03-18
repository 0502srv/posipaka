"""Posipaka — Notion Integration."""

from __future__ import annotations

import os
from typing import Any

from posipaka.security.injection import sanitize_external_content


def _get_notion():
    try:
        from notion_client import Client

        token = os.environ.get("NOTION_TOKEN", "")
        if not token:
            return None
        return Client(auth=token)
    except ImportError:
        return None


async def notion_list_pages(database_id: str) -> str:
    client = _get_notion()
    if not client:
        return "Notion не налаштовано (NOTION_TOKEN)."
    try:
        result = client.databases.query(database_id=database_id, page_size=20)
        pages = result.get("results", [])
        if not pages:
            return "Сторінок не знайдено."
        lines = ["Notion сторінки:\n"]
        for p in pages:
            title_prop = p.get("properties", {}).get("Name", {}) or p.get("properties", {}).get(
                "title", {}
            )
            title = ""
            if "title" in title_prop:
                title = "".join(t.get("plain_text", "") for t in title_prop["title"])
            lines.append(f"• {title or p['id'][:8]}")
        return "\n".join(lines)
    except Exception as e:
        return f"Notion помилка: {e}"


async def notion_create_page(parent_id: str, title: str, content: str = "") -> str:
    client = _get_notion()
    if not client:
        return "Notion не налаштовано."
    try:
        page = client.pages.create(
            parent={"database_id": parent_id},
            properties={"Name": {"title": [{"text": {"content": title}}]}},
            children=[
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"text": {"content": content}}]},
                }
            ]
            if content
            else [],
        )
        return f"Сторінку створено: {page.get('url', title)}"
    except Exception as e:
        return f"Помилка: {e}"


async def notion_update_page(page_id: str, content: str) -> str:
    client = _get_notion()
    if not client:
        return "Notion не налаштовано."
    try:
        client.blocks.children.append(
            block_id=page_id,
            children=[
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"text": {"content": content}}]},
                }
            ],
        )
        return f"Сторінку {page_id} оновлено."
    except Exception as e:
        return f"Помилка: {e}"


async def notion_search(query: str) -> str:
    client = _get_notion()
    if not client:
        return "Notion не налаштовано."
    try:
        result = client.search(query=query, page_size=10)
        pages = result.get("results", [])
        if not pages:
            return f"Нічого не знайдено: {query}"
        lines = [f"Notion пошук: '{query}'\n"]
        for p in pages:
            title = p.get("properties", {}).get("Name", {})
            t = ""
            if title and "title" in title:
                t = "".join(x.get("plain_text", "") for x in title["title"])
            url = p.get("url", "")
            lines.append(f"• {t or p['id'][:8]}  {url}")
        return sanitize_external_content("\n".join(lines), source="notion")
    except Exception as e:
        return f"Помилка: {e}"


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="notion_list_pages",
            description="List pages in a Notion database.",
            category="integration",
            handler=notion_list_pages,
            input_schema={
                "type": "object",
                "required": ["database_id"],
                "properties": {"database_id": {"type": "string"}},
            },
            tags=["notion"],
        )
    )
    registry.register(
        ToolDefinition(
            name="notion_create_page",
            description="Create a new page in Notion.",
            category="integration",
            handler=notion_create_page,
            input_schema={
                "type": "object",
                "required": ["parent_id", "title"],
                "properties": {
                    "parent_id": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                },
            },
            requires_approval=True,
            tags=["notion"],
        )
    )
    registry.register(
        ToolDefinition(
            name="notion_update_page",
            description="Update a Notion page. Requires approval.",
            category="integration",
            handler=notion_update_page,
            input_schema={
                "type": "object",
                "required": ["page_id", "content"],
                "properties": {"page_id": {"type": "string"}, "content": {"type": "string"}},
            },
            requires_approval=True,
            tags=["notion"],
        )
    )
    registry.register(
        ToolDefinition(
            name="notion_search",
            description="Search Notion workspace.",
            category="integration",
            handler=notion_search,
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}},
            },
            tags=["notion"],
        )
    )
