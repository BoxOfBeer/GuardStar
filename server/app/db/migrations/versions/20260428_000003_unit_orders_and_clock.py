"""unit orders and game clock

Revision ID: 20260428_000003
Revises: 20260407_000002
Create Date: 2026-04-28

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260428_000003"
down_revision = "20260407_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "game_clock",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("current_tick", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "unit_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "unit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("units.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order_type", sa.String(length=32), nullable=False, server_default="move"),
        sa.Column("target_x", sa.Integer(), nullable=False),
        sa.Column("target_y", sa.Integer(), nullable=False),
        sa.Column("target_z", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_tick", sa.Integer(), nullable=False),
        sa.Column("finish_tick", sa.Integer(), nullable=False),
    )
    op.create_index("ix_unit_orders_unit_id", "unit_orders", ["unit_id"], unique=False)
    op.create_index("ix_unit_orders_status", "unit_orders", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_unit_orders_status", table_name="unit_orders")
    op.drop_index("ix_unit_orders_unit_id", table_name="unit_orders")
    op.drop_table("unit_orders")
    op.drop_table("game_clock")
