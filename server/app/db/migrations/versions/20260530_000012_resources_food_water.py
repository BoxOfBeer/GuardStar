"""resources food and water

Revision ID: 20260530_000012
Revises: 20260501_000011
Create Date: 2026-05-30

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260530_000012"
down_revision = "20260501_000011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("resources") as batch:
        batch.add_column(
            sa.Column("food", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("water", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("resources") as batch:
        batch.drop_column("water")
        batch.drop_column("food")
