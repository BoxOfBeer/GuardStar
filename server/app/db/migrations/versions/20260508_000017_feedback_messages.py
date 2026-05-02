"""feedback_messages table for player feedback

Revision ID: 20260508_000017
Revises: 20260501_000016
Create Date: 2026-05-08

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260508_000017"
down_revision = "20260501_000016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("player_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pilot_name", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=24), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("current_tick", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_feedback_messages_player_id", "feedback_messages", ["player_id"]
    )
    op.create_index(
        "ix_feedback_messages_created_at", "feedback_messages", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_feedback_messages_created_at", table_name="feedback_messages")
    op.drop_index("ix_feedback_messages_player_id", table_name="feedback_messages")
    op.drop_table("feedback_messages")
