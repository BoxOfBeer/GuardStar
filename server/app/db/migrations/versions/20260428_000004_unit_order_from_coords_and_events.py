"""unit order from coords and events

Revision ID: 20260428_000004
Revises: 20260428_000003
Create Date: 2026-04-28

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260428_000004"
down_revision = "20260428_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # unit_orders: store start position for route/ETA
    op.add_column(
        "unit_orders",
        sa.Column("from_x", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "unit_orders",
        sa.Column("from_y", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "unit_orders",
        sa.Column("from_z", sa.Integer(), nullable=False, server_default="0"),
    )

    # Best-effort backfill for existing rows (unknown real start -> assume target)
    op.execute(
        "UPDATE unit_orders SET from_x = target_x, from_y = target_y, from_z = target_z WHERE from_x = 0 AND from_y = 0 AND from_z = 0"
    )

    op.alter_column("unit_orders", "from_x", server_default=None)
    op.alter_column("unit_orders", "from_y", server_default=None)
    op.alter_column("unit_orders", "from_z", server_default=None)

    # events: MVP world log
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tick", sa.Integer(), nullable=False, index=True),
        sa.Column("type", sa.String(length=64), nullable=False, index=True),
        sa.Column("message", sa.String(length=255), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("player_id", sa.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("events")
    op.drop_column("unit_orders", "from_z")
    op.drop_column("unit_orders", "from_y")
    op.drop_column("unit_orders", "from_x")
