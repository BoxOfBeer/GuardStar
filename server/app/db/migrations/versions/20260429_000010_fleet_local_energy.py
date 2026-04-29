"""fleet local energy

Revision ID: 20260429_000010
Revises: 20260429_000009
Create Date: 2026-04-29

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260429_000010"
down_revision = "20260429_000009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("fleets") as batch:
        batch.add_column(sa.Column("energy", sa.Integer(), nullable=False, server_default="100"))
        batch.add_column(sa.Column("max_energy", sa.Integer(), nullable=False, server_default="100"))


def downgrade() -> None:
    with op.batch_alter_table("fleets") as batch:
        batch.drop_column("max_energy")
        batch.drop_column("energy")

