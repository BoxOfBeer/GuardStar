"""world_state.test_block_new_fleets — тестовый запрет новых флотов"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260514_000025"
down_revision = "20260513_000024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if "world_state" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("world_state")}
    if "test_block_new_fleets" in cols:
        return
    with op.batch_alter_table("world_state") as batch:
        batch.add_column(
            sa.Column(
                "test_block_new_fleets",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if "world_state" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("world_state")}
    if "test_block_new_fleets" not in cols:
        return
    with op.batch_alter_table("world_state") as batch:
        batch.drop_column("test_block_new_fleets")
