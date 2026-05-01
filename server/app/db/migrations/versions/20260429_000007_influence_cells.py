"""add influence_cells table

Revision ID: 20260429_000007
Revises: 20260429_000006
Create Date: 2026-04-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260429_000007"
down_revision = "20260429_000006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "influence_cells",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("player_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("x", sa.Integer(), nullable=False),
        sa.Column("y", sa.Integer(), nullable=False),
        sa.Column("z", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "control_value", sa.Float(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "updated_tick", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "player_id", "x", "y", "z", name="uq_influence_cells_player_xyz"
        ),
    )
    op.create_index("ix_influence_cells_player_id", "influence_cells", ["player_id"])
    op.create_index("ix_influence_cells_x", "influence_cells", ["x"])
    op.create_index("ix_influence_cells_y", "influence_cells", ["y"])
    op.create_index("ix_influence_cells_z", "influence_cells", ["z"])
    op.create_index(
        "ix_influence_cells_updated_tick", "influence_cells", ["updated_tick"]
    )


def downgrade() -> None:
    op.drop_index("ix_influence_cells_updated_tick", table_name="influence_cells")
    op.drop_index("ix_influence_cells_z", table_name="influence_cells")
    op.drop_index("ix_influence_cells_y", table_name="influence_cells")
    op.drop_index("ix_influence_cells_x", table_name="influence_cells")
    op.drop_index("ix_influence_cells_player_id", table_name="influence_cells")
    op.drop_table("influence_cells")
