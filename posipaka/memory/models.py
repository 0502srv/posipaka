"""SQLAlchemy models for Alembic migrations.

These models mirror the tables created in sqlite_backend.py.
Alembic uses this metadata for autogenerate and migration tracking.
"""

from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()

# Layer 2: Session messages
messages = sa.Table(
    "messages",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("session_id", sa.Text, nullable=False, index=True),
    sa.Column("role", sa.Text, nullable=False),
    sa.Column("content", sa.Text, nullable=False),
    sa.Column("metadata", sa.Text, server_default="{}"),
    sa.Column("created_at", sa.Float, nullable=False),
)

# Layer 3: Extracted facts
facts = sa.Table(
    "facts",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("session_id", sa.Text, index=True),
    sa.Column("fact", sa.Text, nullable=False),
    sa.Column("source", sa.Text, server_default="auto"),
    sa.Column("created_at", sa.Float, nullable=False),
)

# Session tracking
sessions = sa.Table(
    "sessions",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("user_id", sa.Text, nullable=False),
    sa.Column("channel", sa.Text, nullable=False),
    sa.Column("created_at", sa.Float, nullable=False),
    sa.Column("last_active", sa.Float, nullable=False),
    sa.Column("metadata", sa.Text, server_default="{}"),
)

# Indexes (matching sqlite_backend.py)
sa.Index("idx_messages_session", messages.c.session_id, messages.c.created_at.desc())
sa.Index("idx_facts_session", facts.c.session_id)
