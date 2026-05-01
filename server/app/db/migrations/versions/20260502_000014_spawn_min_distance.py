"""world_state: player spawn min manhattan distance

Revision ID: 20260502_000014
Revises: 20260430_000013
Create Date: 2026-05-02

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260502_000014"
down_revision = "20260430_000013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Исторически `world_state` мог появляться через create_all()/safety-net. Для чистого разворачивания создаём.
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS world_state (
              id INTEGER PRIMARY KEY,
              current_tick INTEGER NOT NULL DEFAULT 0,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              auto_tick_enabled BOOLEAN NOT NULL DEFAULT false,
              auto_tick_interval_seconds DOUBLE PRECISION NOT NULL DEFAULT 5.0
            );
            """
        )
    )
    # Добавляем колонку безопасно (если таблица уже существовала).
    op.execute(
        sa.text(
            "ALTER TABLE world_state ADD COLUMN IF NOT EXISTS player_spawn_min_manhattan INTEGER NOT NULL DEFAULT 25"
        )
    )
    op.alter_column("world_state", "player_spawn_min_manhattan", server_default=None)


def downgrade() -> None:
    op.drop_column("world_state", "player_spawn_min_manhattan")
