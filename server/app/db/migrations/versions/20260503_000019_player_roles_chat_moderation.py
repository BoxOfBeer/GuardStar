"""player roles, chat moderation, account_disabled

Revision ID: 20260503_000019
Revises: 20260502_000018
Create Date: 2026-05-03

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260503_000019"
down_revision = "20260502_000018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    player_cols = {c["name"] for c in insp.get_columns("players")}
    if "is_game_admin" not in player_cols:
        op.add_column(
            "players",
            sa.Column(
                "is_game_admin",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
        op.alter_column("players", "is_game_admin", server_default=None)
    if "is_game_moderator" not in player_cols:
        op.add_column(
            "players",
            sa.Column(
                "is_game_moderator",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
        op.alter_column("players", "is_game_moderator", server_default=None)
    if "chat_banned_until" not in player_cols:
        op.add_column(
            "players",
            sa.Column("chat_banned_until", sa.DateTime(timezone=True), nullable=True),
        )
    if "account_disabled" not in player_cols:
        op.add_column(
            "players",
            sa.Column(
                "account_disabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
        op.alter_column("players", "account_disabled", server_default=None)

    insp = inspect(conn)
    if "chat_messages" in insp.get_table_names():
        cm_cols = {c["name"] for c in insp.get_columns("chat_messages")}
        if "moderation_hidden" not in cm_cols:
            op.add_column(
                "chat_messages",
                sa.Column(
                    "moderation_hidden",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("false"),
                ),
            )
            op.alter_column("chat_messages", "moderation_hidden", server_default=None)


def downgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if "chat_messages" in insp.get_table_names():
        cm_cols = {c["name"] for c in insp.get_columns("chat_messages")}
        if "moderation_hidden" in cm_cols:
            op.drop_column("chat_messages", "moderation_hidden")
    player_cols = {c["name"] for c in insp.get_columns("players")}
    for col in ("account_disabled", "chat_banned_until", "is_game_moderator", "is_game_admin"):
        if col in player_cols:
            op.drop_column("players", col)
