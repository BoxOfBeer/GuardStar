"""fleets and resource ticks

Revision ID: 20260407_000002
Revises: 20260407_000001
Create Date: 2026-04-07

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260407_000002"
down_revision = "20260407_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resource_ticks",
        sa.Column(
            "planet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("planets.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("last_collected_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "fleets",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            "owner_player_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("unit_type", sa.String(length=32), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pos_x", sa.Integer(), nullable=False),
        sa.Column("pos_y", sa.Integer(), nullable=False),
        sa.Column("pos_z", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_fleets_owner_player_id", "fleets", ["owner_player_id"], unique=False
    )
    op.create_index("ix_fleets_unit_type", "fleets", ["unit_type"], unique=False)
    op.create_index("ix_fleets_pos_x", "fleets", ["pos_x"], unique=False)
    op.create_index("ix_fleets_pos_y", "fleets", ["pos_y"], unique=False)
    op.create_index("ix_fleets_pos_z", "fleets", ["pos_z"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_fleets_pos_z", table_name="fleets")
    op.drop_index("ix_fleets_pos_y", table_name="fleets")
    op.drop_index("ix_fleets_pos_x", table_name="fleets")
    op.drop_index("ix_fleets_unit_type", table_name="fleets")
    op.drop_index("ix_fleets_owner_player_id", table_name="fleets")
    op.drop_table("fleets")
    op.drop_table("resource_ticks")
