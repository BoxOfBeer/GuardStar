"""chat_messages, player_blocks, players.staff_chat_exempt

Revision ID: 20260502_000018
Revises: 20260508_000017
Create Date: 2026-05-02

Идемпотентный upgrade: таблицы чата могли появиться через create_all до применения Alembic.

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "20260502_000018"
down_revision = "20260508_000017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    insp = inspect(conn)
    player_cols = {c["name"] for c in insp.get_columns("players")}
    if "staff_chat_exempt" not in player_cols:
        op.add_column(
            "players",
            sa.Column(
                "staff_chat_exempt",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
        op.create_index(
            "ix_players_staff_chat_exempt", "players", ["staff_chat_exempt"]
        )
        op.alter_column("players", "staff_chat_exempt", server_default=None)

    insp = inspect(conn)
    if "chat_messages" not in insp.get_table_names():
        op.create_table(
            "chat_messages",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column(
                "channel_kind",
                sa.String(length=16),
                nullable=False,
            ),
            sa.Column(
                "alliance_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
            sa.Column(
                "sender_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column(
                "recipient_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["sender_id"], ["players.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["recipient_id"], ["players.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    insp = inspect(conn)
    if "chat_messages" in insp.get_table_names():
        idx_chat = {i["name"] for i in insp.get_indexes("chat_messages")}
        if "ix_chat_messages_channel_kind_id" not in idx_chat:
            op.create_index(
                "ix_chat_messages_channel_kind_id",
                "chat_messages",
                ["channel_kind", "id"],
            )
        if "ix_chat_messages_private_pair" not in idx_chat:
            op.create_index(
                "ix_chat_messages_private_pair",
                "chat_messages",
                ["channel_kind", "sender_id", "recipient_id", "id"],
            )

    insp = inspect(conn)
    if "player_blocks" not in insp.get_table_names():
        op.create_table(
            "player_blocks",
            sa.Column(
                "blocker_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column(
                "blocked_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["blocker_id"], ["players.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["blocked_id"], ["players.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("blocker_id", "blocked_id"),
        )


def downgrade() -> None:
    op.drop_table("player_blocks")
    op.drop_index("ix_chat_messages_private_pair", table_name="chat_messages")
    op.drop_index("ix_chat_messages_channel_kind_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_players_staff_chat_exempt", table_name="players")
    op.drop_column("players", "staff_chat_exempt")
