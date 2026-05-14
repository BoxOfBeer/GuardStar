"""reserved_display_names.id: BigInteger -> Integer (SQLite autoincrement).

Revision ID: 20260520_000033
Revises: 20260520_000032
Create Date: 2026-05-20

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260520_000033"
down_revision = "20260520_000032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    insp = inspect(conn)
    cols = {c["name"]: c for c in insp.get_columns("reserved_display_names")}
    col = cols.get("id")
    if not col:
        return
    t = col.get("type")
    if not isinstance(t, sa.BigInteger):
        return
    op.alter_column(
        "reserved_display_names",
        "id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
        autoincrement=True,
    )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    insp = inspect(conn)
    cols = {c["name"]: c for c in insp.get_columns("reserved_display_names")}
    col = cols.get("id")
    t = col.get("type") if col else None
    if isinstance(t, sa.BigInteger):
        return
    op.alter_column(
        "reserved_display_names",
        "id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
        autoincrement=True,
    )
