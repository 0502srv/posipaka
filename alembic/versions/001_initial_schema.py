"""Initial schema — messages, facts, sessions.

Revision ID: 001_initial
Revises: None
Create Date: 2026-03-17

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("metadata", sa.Text, server_default="{}"),
        sa.Column("created_at", sa.Float, nullable=False),
    )
    op.create_index("idx_messages_session", "messages", ["session_id", "created_at"])

    op.create_table(
        "facts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text),
        sa.Column("fact", sa.Text, nullable=False),
        sa.Column("source", sa.Text, server_default="auto"),
        sa.Column("created_at", sa.Float, nullable=False),
    )
    op.create_index("idx_facts_session", "facts", ["session_id"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("channel", sa.Text, nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("last_active", sa.Float, nullable=False),
        sa.Column("metadata", sa.Text, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_table("sessions")
    op.drop_table("facts")
    op.drop_table("messages")
