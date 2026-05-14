"""planet is_capital is_colonized conquest_penalty; building structure_hp

Revision ID: 20260513_000031
Revises: 20260519_000030
Create Date: 2026-05-13

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260513_000031"
down_revision = "20260519_000030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("planets") as batch:
        batch.add_column(
            sa.Column(
                "is_capital",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
        batch.add_column(
            sa.Column(
                "is_colonized",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            )
        )
        batch.add_column(
            sa.Column(
                "conquest_penalty_until_tick",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
    op.execute(
        """
        UPDATE planets p
        SET is_capital = true
        FROM (
            SELECT DISTINCT ON (owner_player_id) id
            FROM planets
            ORDER BY owner_player_id, created_at ASC
        ) firstp
        WHERE p.id = firstp.id
        """
    )
    op.execute("UPDATE planets SET is_colonized = true WHERE is_colonized IS NULL")

    with op.batch_alter_table("buildings") as batch:
        batch.add_column(
            sa.Column("structure_hp", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table("buildings") as batch:
        batch.drop_column("structure_hp")

    with op.batch_alter_table("planets") as batch:
        batch.drop_column("conquest_penalty_until_tick")
        batch.drop_column("is_colonized")
        batch.drop_column("is_capital")
