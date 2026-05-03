"""world_state: гранулярные флаги спавна, лимит флота, множители исследований."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260515_000026"
down_revision = "20260514_000025"
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
    if not cols:
        return
    add_cols: list[sa.Column] = []
    if "admin_block_player_fleet_create" not in cols:
        add_cols.append(
            sa.Column(
                "admin_block_player_fleet_create",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
    if "admin_block_npc_transit" not in cols:
        add_cols.append(
            sa.Column(
                "admin_block_npc_transit",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
    if "admin_block_bandit_mines" not in cols:
        add_cols.append(
            sa.Column(
                "admin_block_bandit_mines",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
    if "admin_block_bandit_outposts" not in cols:
        add_cols.append(
            sa.Column(
                "admin_block_bandit_outposts",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
    if "admin_block_bandit_fleets" not in cols:
        add_cols.append(
            sa.Column(
                "admin_block_bandit_fleets",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
    if "admin_max_fleet_units" not in cols:
        add_cols.append(
            sa.Column(
                "admin_max_fleet_units",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
    if "admin_research_overrides_json" not in cols:
        add_cols.append(
            sa.Column("admin_research_overrides_json", sa.Text(), nullable=True)
        )
    if not add_cols:
        return
    with op.batch_alter_table("world_state") as batch:
        for c in add_cols:
            batch.add_column(c)


def downgrade() -> None:
    conn = op.get_bind()
    cols = _cols(conn, "world_state")
    if not cols:
        return
    drop_names = [
        "admin_block_player_fleet_create",
        "admin_block_npc_transit",
        "admin_block_bandit_mines",
        "admin_block_bandit_outposts",
        "admin_block_bandit_fleets",
        "admin_max_fleet_units",
        "admin_research_overrides_json",
    ]
    to_drop = [n for n in drop_names if n in cols]
    if not to_drop:
        return
    with op.batch_alter_table("world_state") as batch:
        for name in to_drop:
            batch.drop_column(name)
