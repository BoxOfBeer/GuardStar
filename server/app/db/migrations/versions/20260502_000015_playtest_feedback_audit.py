"""playtest feedback audit log + player.feedback_audited

Revision ID: 20260502_000015
Revises: 20260502_000014
Create Date: 2026-05-02

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260502_000015"
down_revision = "20260502_000014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "players",
        sa.Column(
            "feedback_audited",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index("ix_players_feedback_audited", "players", ["feedback_audited"])
    op.alter_column("players", "feedback_audited", server_default=None)

    op.create_table(
        "feedback_playtest_api_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("player_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column(
            "query_string", sa.String(length=512), nullable=False, server_default=""
        ),
        sa.Column("body_preview", sa.Text(), nullable=True),
        sa.Column("status_code", sa.SmallInteger(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_feedback_playtest_api_logs_player_id",
        "feedback_playtest_api_logs",
        ["player_id"],
    )
    op.create_index(
        "ix_feedback_playtest_api_logs_created_at",
        "feedback_playtest_api_logs",
        ["created_at"],
    )
    op.alter_column("feedback_playtest_api_logs", "query_string", server_default=None)
    op.alter_column("feedback_playtest_api_logs", "duration_ms", server_default=None)


def downgrade() -> None:
    op.drop_table("feedback_playtest_api_logs")
    op.drop_index("ix_players_feedback_audited", table_name="players")
    op.drop_column("players", "feedback_audited")
