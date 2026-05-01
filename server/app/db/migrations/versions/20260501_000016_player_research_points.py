"""players.research_points for RP economy

Revision ID: 20260501_000016
Revises: 20260502_000015
Create Date: 2026-05-01

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260501_000016"
down_revision = "20260502_000015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "players",
        sa.Column("research_points", sa.Numeric(precision=16, scale=6), nullable=False, server_default=sa.text("0")),
    )
    op.alter_column("players", "research_points", server_default=None)


def downgrade() -> None:
    op.drop_column("players", "research_points")
