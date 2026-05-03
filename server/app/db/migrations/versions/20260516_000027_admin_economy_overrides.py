"""world_state.admin_economy_overrides_json — частичный JSON поверх economy.json."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260516_000027"
down_revision = "20260515_000026"
branch_labels = None
depends_on = None


def _cols(conn, table: str) -> set[str]:
    insp = inspect(conn)
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    cols = _cols(conn, "world_state")
    if not cols or "admin_economy_overrides_json" in cols:
        return
    with op.batch_alter_table("world_state") as batch:
        batch.add_column(sa.Column("admin_economy_overrides_json", sa.Text(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    cols = _cols(conn, "world_state")
    if not cols or "admin_economy_overrides_json" not in cols:
        return
    with op.batch_alter_table("world_state") as batch:
        batch.drop_column("admin_economy_overrides_json")
