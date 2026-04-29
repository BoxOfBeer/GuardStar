"""fleet order combat prompt fields

Revision ID: 20260429_000006
Revises: 20260428_000005
Create Date: 2026-04-29

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260429_000006"
down_revision = "20260428_000005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fleet_orders",
        sa.Column("force_attack", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("fleet_orders", sa.Column("combat_prompt_expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("fleet_orders", "combat_prompt_expires_at")
    op.drop_column("fleet_orders", "force_attack")
