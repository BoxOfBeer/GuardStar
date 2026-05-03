"""players.last_game_activity_at; world_state.admin_presence_window_minutes (админ-онлайн)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260519_000030"
down_revision = "20260518_000029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if "players" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("players")}
        if "last_game_activity_at" not in cols:
            with op.batch_alter_table("players") as batch:
                batch.add_column(
                    sa.Column(
                        "last_game_activity_at",
                        sa.DateTime(timezone=True),
                        nullable=True,
                    )
                )
            op.create_index(
                "ix_players_last_game_activity_at",
                "players",
                ["last_game_activity_at"],
            )
    if "world_state" in insp.get_table_names():
        wcols = {c["name"] for c in insp.get_columns("world_state")}
        if "admin_presence_window_minutes" not in wcols:
            with op.batch_alter_table("world_state") as batch:
                batch.add_column(
                    sa.Column(
                        "admin_presence_window_minutes",
                        sa.Integer(),
                        nullable=False,
                        server_default=sa.text("10"),
                    )
                )
            op.alter_column(
                "world_state",
                "admin_presence_window_minutes",
                server_default=None,
            )


def downgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if "players" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("players")}
        if "last_game_activity_at" in cols:
            op.drop_index(
                "ix_players_last_game_activity_at", table_name="players"
            )
            with op.batch_alter_table("players") as batch:
                batch.drop_column("last_game_activity_at")
    if "world_state" in insp.get_table_names():
        wcols = {c["name"] for c in insp.get_columns("world_state")}
        if "admin_presence_window_minutes" in wcols:
            with op.batch_alter_table("world_state") as batch:
                batch.drop_column("admin_presence_window_minutes")
