"""private chat read receipts, peer prefs, thread hide

Revision ID: 20260510_000021
Revises: 20260504_000020
Create Date: 2026-05-10

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "20260510_000021"
down_revision = "20260504_000020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    chat_cols = {c["name"] for c in insp.get_columns("chat_messages")}
    if "read_receipt_at" not in chat_cols:
        op.add_column(
            "chat_messages",
            sa.Column("read_receipt_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "private_chat_peer_prefs" not in insp.get_table_names():
        op.create_table(
            "private_chat_peer_prefs",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("viewer_player_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("peer_player_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("welcomed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "send_read_receipts",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "last_read_incoming_id",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["viewer_player_id"],
                ["players.id"],
                name="private_chat_prefs_viewer_player_id_fkey",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["peer_player_id"],
                ["players.id"],
                name="private_chat_prefs_peer_player_id_fkey",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "viewer_player_id",
                "peer_player_id",
                name="uq_private_chat_peer_prefs_pair",
            ),
        )
        op.create_index(
            "ix_private_chat_peer_prefs_viewer",
            "private_chat_peer_prefs",
            ["viewer_player_id"],
            unique=False,
        )
        op.create_index(
            "ix_private_chat_peer_prefs_peer",
            "private_chat_peer_prefs",
            ["peer_player_id"],
            unique=False,
        )
        op.alter_column("private_chat_peer_prefs", "send_read_receipts", server_default=None)
        op.alter_column(
            "private_chat_peer_prefs", "last_read_incoming_id", server_default=None
        )


def downgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if "private_chat_peer_prefs" in insp.get_table_names():
        op.drop_index("ix_private_chat_peer_prefs_peer", table_name="private_chat_peer_prefs")
        op.drop_index("ix_private_chat_peer_prefs_viewer", table_name="private_chat_peer_prefs")
        op.drop_table("private_chat_peer_prefs")
    chat_cols = {c["name"] for c in insp.get_columns("chat_messages")}
    if "read_receipt_at" in chat_cols:
        op.drop_column("chat_messages", "read_receipt_at")
