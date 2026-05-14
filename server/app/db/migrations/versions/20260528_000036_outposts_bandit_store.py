"""outposts: склад корсарского форпоста (bandit_store_*).

Revision ID: 20260528_000036
Revises: 20260527_000035
Create Date: 2026-05-28

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260528_000036"
down_revision = "20260527_000035"
branch_labels = None
depends_on = None

_BANDIT_STORE_COLS = (
    "bandit_store_metal",
    "bandit_store_crystal",
    "bandit_store_food",
    "bandit_store_water",
    "bandit_store_energy",
    "bandit_store_fuel",
)


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if "outposts" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("outposts")}
    for col in _BANDIT_STORE_COLS:
        if col in existing:
            continue
        op.add_column(
            "outposts",
            sa.Column(col, sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if "outposts" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("outposts")}
    for col in reversed(_BANDIT_STORE_COLS):
        if col not in existing:
            continue
        op.drop_column("outposts", col)
