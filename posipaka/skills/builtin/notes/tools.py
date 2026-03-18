"""Quick notes — create, search, list personal notes."""

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
        _DB_PATH = Path.home() / ".posipaka" / "notes.db"
    return _DB_PATH


async def _ensure_schema(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '[]'
        )
    """)
    await db.commit()


async def create_note(content: str, title: str = "", tags: str = "") -> str:
    """Create a new note with optional title and tags."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    async with aiosqlite.connect(_get_db_path()) as db:
        await _ensure_schema(db)
        cursor = await db.execute(
            "INSERT INTO notes (ts, title, content, tags) VALUES (?, ?, ?, ?)",
            (time.time(), title, content, json.dumps(tag_list)),
        )
        await db.commit()
        note_id = cursor.lastrowid
    label = f" \"{title}\"" if title else ""
    return f"Note{label} created (id={note_id})."


async def list_notes(limit: int = 10) -> str:
    """List latest notes."""
    async with aiosqlite.connect(_get_db_path()) as db:
        await _ensure_schema(db)
        rows = await db.execute_fetchall(
            "SELECT id, ts, title, content, tags FROM notes ORDER BY ts DESC LIMIT ?",
            (limit,),
        )
    if not rows:
        return "No notes yet."
    lines: list[str] = [f"Notes (latest {len(rows)}):"]
    for row in rows:
        nid, ts, title, content, tags = row
        date_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
        preview = content[:80] + "..." if len(content) > 80 else content
        tag_list = json.loads(tags) if tags else []
        tag_str = f" [{', '.join(tag_list)}]" if tag_list else ""
        label = f" {title} —" if title else ""
        lines.append(f"  #{nid} [{date_str}]{label} {preview}{tag_str}")
    return "\n".join(lines)


async def search_notes(query: str) -> str:
    """Search notes by content or title."""
    pattern = f"%{query}%"
    async with aiosqlite.connect(_get_db_path()) as db:
        await _ensure_schema(db)
        rows = await db.execute_fetchall(
            "SELECT id, ts, title, content, tags FROM notes "
            "WHERE content LIKE ? OR title LIKE ? ORDER BY ts DESC LIMIT 10",
            (pattern, pattern),
        )
    if not rows:
        return f"No notes matching \"{query}\"."
    lines: list[str] = [f"Found {len(rows)} note(s) for \"{query}\":"]
    for row in rows:
        nid, ts, title, content, tags = row
        date_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
        preview = content[:80] + "..." if len(content) > 80 else content
        label = f" {title} —" if title else ""
        lines.append(f"  #{nid} [{date_str}]{label} {preview}")
    return "\n".join(lines)


async def delete_note(note_id: int) -> str:
    """Delete a note by id. Requires approval."""
    async with aiosqlite.connect(_get_db_path()) as db:
        await _ensure_schema(db)
        cursor = await db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        await db.commit()
        if cursor.rowcount == 0:
            return f"Note #{note_id} not found."
    return f"Note #{note_id} deleted."


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(ToolDefinition(
        name="create_note",
        description="Create a new personal note with optional title and tags",
        category="productivity",
        handler=create_note,
        input_schema={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Note content"},
                "title": {"type": "string", "description": "Optional title", "default": ""},
                "tags": {"type": "string", "description": "Comma-separated tags", "default": ""},
            },
            "required": ["content"],
        },
        tags=["notes", "productivity"],
    ))
    registry.register(ToolDefinition(
        name="list_notes",
        description="List latest personal notes",
        category="productivity",
        handler=list_notes,
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max notes to return", "default": 10},
            },
        },
        tags=["notes", "productivity"],
    ))
    registry.register(ToolDefinition(
        name="search_notes",
        description="Search notes by content or title",
        category="productivity",
        handler=search_notes,
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
        tags=["notes", "productivity"],
    ))
    registry.register(ToolDefinition(
        name="delete_note",
        description="Delete a note by id",
        category="productivity",
        handler=delete_note,
        requires_approval=True,
        input_schema={
            "type": "object",
            "properties": {
                "note_id": {"type": "integer", "description": "Note id to delete"},
            },
            "required": ["note_id"],
        },
        tags=["notes", "productivity"],
    ))
