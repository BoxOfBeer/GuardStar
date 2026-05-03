"""world_state: базовая выработка еды/воды с планеты за сол (админка)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260518_000029"
down_revision = "20260517_000028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if "world_state" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("world_state")}
    with op.batch_alter_table("world_state") as batch:
        if "economy_base_food_per_sol" not in cols:
            batch.add_column(
                sa.Column(
                    "economy_base_food_per_sol",
                    sa.Integer(),
                    nullable=False,
                    server_default=sa.text("10"),
                )
            )
        if "economy_base_water_per_sol" not in cols:
            batch.add_column(
                sa.Column(
                    "economy_base_water_per_sol",
                    sa.Integer(),
                    nullable=False,
                    server_default=sa.text("10"),
                )
            )
    insp2 = inspect(conn)
    cols2 = {c["name"] for c in insp2.get_columns("world_state")}
    for cname in ("economy_base_food_per_sol", "economy_base_water_per_sol"):
        if cname in cols2:
            op.alter_column("world_state", cname, server_default=None)


def downgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if "world_state" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("world_state")}
    with op.batch_alter_table("world_state") as batch:
        if "economy_base_water_per_sol" in cols:
            batch.drop_column("economy_base_water_per_sol")
        if "economy_base_food_per_sol" in cols:
            batch.drop_column("economy_base_food_per_sol")
