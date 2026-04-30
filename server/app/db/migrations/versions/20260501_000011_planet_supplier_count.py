"""planet supplier_count

Revision ID: 20260501_000011
Revises: 20260429_000010
Create Date: 2026-05-01

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260501_000011"
down_revision = "20260429_000010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("planets") as batch:
        batch.add_column(sa.Column("supplier_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("planets") as batch:
        batch.drop_column("supplier_count")
