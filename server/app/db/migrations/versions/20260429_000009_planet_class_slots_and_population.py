"""planet class/slots/population columns

Revision ID: 20260429_000009
Revises: 20260429_000008
Create Date: 2026-04-29

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260429_000009"
down_revision = "20260429_000008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Старые БД могли быть созданы через create_all() без этих колонок.
    with op.batch_alter_table("planets") as batch:
        batch.add_column(
            sa.Column("population", sa.Integer(), nullable=False, server_default="800")
        )
        batch.add_column(
            sa.Column(
                "max_population", sa.Integer(), nullable=False, server_default="5000"
            )
        )
        batch.add_column(
            sa.Column(
                "planet_class",
                sa.String(length=32),
                nullable=False,
                server_default="earthlike",
            )
        )
        batch.add_column(
            sa.Column(
                "build_slots_total", sa.Integer(), nullable=False, server_default="55"
            )
        )
        batch.create_index("ix_planets_planet_class", ["planet_class"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("planets") as batch:
        batch.drop_index("ix_planets_planet_class")
        batch.drop_column("build_slots_total")
        batch.drop_column("planet_class")
        batch.drop_column("max_population")
        batch.drop_column("population")
