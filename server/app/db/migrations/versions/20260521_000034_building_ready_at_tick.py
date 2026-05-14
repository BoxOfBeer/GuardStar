"""buildings.ready_at_tick — задержка готовности постройки в тиках.

Revision ID: 20260521_000034
Revises: 20260520_000033
Create Date: 2026-05-21

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260521_000034"
down_revision = "20260520_000033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if "buildings" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("buildings")}
    if "ready_at_tick" not in cols:
        op.add_column(
            "buildings",
            sa.Column(
                "ready_at_tick",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    insp2 = inspect(conn)
    cols2 = {c["name"] for c in insp2.get_columns("buildings")}
    if "ready_at_tick" in cols2:
        op.alter_column("buildings", "ready_at_tick", server_default=None)


def downgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if "buildings" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("buildings")}
    if "ready_at_tick" in cols:
        op.drop_column("buildings", "ready_at_tick")
