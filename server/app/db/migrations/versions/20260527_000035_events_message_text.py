"""events.message: VARCHAR(255) → TEXT (длинные тексты событий ломали тик).

Revision ID: 20260527_000035
Revises: 20260521_000034
Create Date: 2026-05-27

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision = "20260527_000035"
down_revision = "20260521_000034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if "events" not in insp.get_table_names():
        return
    op.alter_column(
        "events",
        "message",
        existing_type=sa.String(255),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if "events" not in insp.get_table_names():
        return
    op.execute(text("UPDATE events SET message = LEFT(message, 255)"))
    op.alter_column(
        "events",
        "message",
        existing_type=sa.Text(),
        type_=sa.String(255),
        existing_nullable=False,
    )
