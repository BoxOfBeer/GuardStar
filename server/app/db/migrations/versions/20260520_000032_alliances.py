"""alliances + alliance_members (фаза 1 альянса)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "20260520_000032"
down_revision = "20260513_000031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if "alliances" not in insp.get_table_names():
        op.create_table(
            "alliances",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column("display_name", sa.String(length=64), nullable=False),
            sa.Column("tag", sa.String(length=8), nullable=False),
            sa.Column("join_code", sa.String(length=16), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tag", name="uq_alliances_tag"),
            sa.UniqueConstraint("join_code", name="uq_alliances_join_code"),
        )

    insp = inspect(conn)
    if "alliance_members" not in insp.get_table_names():
        op.create_table(
            "alliance_members",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column(
                "alliance_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column(
                "player_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column("role", sa.String(length=16), nullable=False, server_default="member"),
            sa.Column(
                "joined_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["alliance_id"], ["alliances.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("player_id", name="uq_alliance_members_player_id"),
        )
        op.create_index(
            "ix_alliance_members_alliance_id", "alliance_members", ["alliance_id"]
        )


def downgrade() -> None:
    op.drop_index("ix_alliance_members_alliance_id", table_name="alliance_members")
    op.drop_table("alliance_members")
    op.drop_table("alliances")
