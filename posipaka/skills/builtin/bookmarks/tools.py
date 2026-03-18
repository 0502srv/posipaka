"""Save and search web bookmarks with tags."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import aiosqlite

_DB_PATH: Path | None = None


def _get_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = Path.home() / ".posipaka" / "bookmarks.db"
    return _DB_PATH


async def _ensure_schema(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            url TEXT NOT NULL,
            title TEXT DEFAULT '',
            description TEXT DEFAULT '',
            tags TEXT DEFAULT '[]'
        )
    """)
    await db.commit()


async def add_bookmark(url: str, title: str = "", description: str = "", tags: str = "") -> str:
    """Save a web bookmark. URL is validated against SSRF first."""
    from posipaka.security.ssrf import validate_url

    try:
        validate_url(url)
    except Exception as e:
        return f"URL blocked by SSRF policy: {e}"

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    async with aiosqlite.connect(_get_db_path()) as db:
        await _ensure_schema(db)
        cursor = await db.execute(
            "INSERT INTO bookmarks (ts, url, title, description, tags) VALUES (?, ?, ?, ?, ?)",
            (time.time(), url, title, description, json.dumps(tag_list)),
        )
        await db.commit()
        bid = cursor.lastrowid
    label = f' "{title}"' if title else ""
    return f"Bookmark{label} saved (id={bid}): {url}"


async def list_bookmarks(limit: int = 10) -> str:
    """List latest bookmarks."""
    async with aiosqlite.connect(_get_db_path()) as db:
        await _ensure_schema(db)
        rows = await db.execute_fetchall(
            "SELECT id, ts, url, title, description, tags FROM bookmarks ORDER BY ts DESC LIMIT ?",
            (limit,),
        )
    if not rows:
        return "No bookmarks yet."
    lines: list[str] = [f"Bookmarks (latest {len(rows)}):"]
    for row in rows:
        bid, ts, url, title, desc, tags = row
        date_str = time.strftime("%Y-%m-%d", time.localtime(ts))
        tag_list = json.loads(tags) if tags else []
        tag_str = f" [{', '.join(tag_list)}]" if tag_list else ""
        label = f" {title} —" if title else ""
        lines.append(f"  #{bid} [{date_str}]{label} {url}{tag_str}")
    return "\n".join(lines)


async def search_bookmarks(query: str) -> str:
    """Search bookmarks by URL, title, description or tags."""
    pattern = f"%{query}%"
    async with aiosqlite.connect(_get_db_path()) as db:
        await _ensure_schema(db)
        rows = await db.execute_fetchall(
            "SELECT id, ts, url, title, description, tags FROM bookmarks "
            "WHERE url LIKE ? OR title LIKE ? OR description LIKE ? OR tags LIKE ? "
            "ORDER BY ts DESC LIMIT 10",
            (pattern, pattern, pattern, pattern),
        )
    if not rows:
        return f'No bookmarks matching "{query}".'
    lines: list[str] = [f'Found {len(rows)} bookmark(s) for "{query}":']
    for row in rows:
        bid, ts, url, title, desc, tags = row
        date_str = time.strftime("%Y-%m-%d", time.localtime(ts))
        label = f" {title} —" if title else ""
        lines.append(f"  #{bid} [{date_str}]{label} {url}")
    return "\n".join(lines)


async def delete_bookmark(bookmark_id: int) -> str:
    """Delete a bookmark by id. Requires approval."""
    async with aiosqlite.connect(_get_db_path()) as db:
        await _ensure_schema(db)
        cursor = await db.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
        await db.commit()
        if cursor.rowcount == 0:
            return f"Bookmark #{bookmark_id} not found."
    return f"Bookmark #{bookmark_id} deleted."


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="add_bookmark",
            description="Save a web bookmark with optional title, description and tags",
            category="productivity",
            handler=add_bookmark,
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to bookmark"},
                    "title": {"type": "string", "description": "Bookmark title", "default": ""},
                    "description": {"type": "string", "description": "Description", "default": ""},
                    "tags": {
                        "type": "string",
                        "description": "Comma-separated tags",
                        "default": "",
                    },
                },
                "required": ["url"],
            },
            tags=["bookmarks", "web", "productivity"],
        )
    )
    registry.register(
        ToolDefinition(
            name="list_bookmarks",
            description="List latest saved bookmarks",
            category="productivity",
            handler=list_bookmarks,
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max bookmarks to return",
                        "default": 10,
                    },
                },
            },
            tags=["bookmarks", "web", "productivity"],
        )
    )
    registry.register(
        ToolDefinition(
            name="search_bookmarks",
            description="Search bookmarks by URL, title, description or tags",
            category="productivity",
            handler=search_bookmarks,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
            tags=["bookmarks", "web", "productivity"],
        )
    )
    registry.register(
        ToolDefinition(
            name="delete_bookmark",
            description="Delete a bookmark by id",
            category="productivity",
            handler=delete_bookmark,
            requires_approval=True,
            input_schema={
                "type": "object",
                "properties": {
                    "bookmark_id": {"type": "integer", "description": "Bookmark id to delete"},
                },
                "required": ["bookmark_id"],
            },
            tags=["bookmarks", "web", "productivity"],
        )
    )
