"""fleet orders

Revision ID: 20260428_000005
Revises: 20260428_000004
Create Date: 2026-04-28

"""

from alembic import op
import sqlalchemy as sa


revision = "20260428_000005"
down_revision = "20260428_000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fleet_orders",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("fleet_id", sa.UUID(as_uuid=True), sa.ForeignKey("fleets.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("owner_player_id", sa.UUID(as_uuid=True), sa.ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("order_type", sa.String(length=32), nullable=False, server_default="move"),
        sa.Column("from_x", sa.Integer(), nullable=False),
        sa.Column("from_y", sa.Integer(), nullable=False),
        sa.Column("from_z", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("target_x", sa.Integer(), nullable=False),
        sa.Column("target_y", sa.Integer(), nullable=False),
        sa.Column("target_z", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("start_tick", sa.Integer(), nullable=False),
        sa.Column("finish_tick", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("fleet_orders")

