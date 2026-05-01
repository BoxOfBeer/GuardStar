"""explored sector discovery + player_effects

Revision ID: 20260430_000013
Revises: 20260530_000012
Create Date: 2026-04-30

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260430_000013"
down_revision = "20260530_000012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Исторически `explored_sectors` мог появляться через create_all()/safety-net, а не миграцией.
    # При "чистом" разворачивании схемы (DROP SCHEMA) таблицы ещё нет, поэтому создаём её, если нужно.
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS explored_sectors (
              id SERIAL PRIMARY KEY,
              player_id UUID NOT NULL REFERENCES players(id) ON DELETE CASCADE,
              x INTEGER NOT NULL,
              y INTEGER NOT NULL,
              z INTEGER NOT NULL DEFAULT 0,
              first_seen_tick INTEGER NOT NULL DEFAULT 0,
              last_seen_tick INTEGER NOT NULL DEFAULT 0,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_explored_sectors_player_id ON explored_sectors (player_id)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_explored_sectors_x ON explored_sectors (x)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_explored_sectors_y ON explored_sectors (y)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_explored_sectors_z ON explored_sectors (z)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_explored_sectors_last_seen_tick ON explored_sectors (last_seen_tick)"
        )
    )

    with op.batch_alter_table("explored_sectors") as batch:
        batch.add_column(
            sa.Column(
                "discovery_done",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
        batch.add_column(sa.Column("discovery_seen_tick", sa.Integer(), nullable=True))
    op.alter_column("explored_sectors", "discovery_done", server_default=None)

    op.create_table(
        "player_effects",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "player_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("effect_type", sa.String(length=64), nullable=False),
        sa.Column(
            "source_type",
            sa.String(length=32),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "source_ref", sa.String(length=128), nullable=False, server_default=""
        ),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("created_tick", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_tick", sa.Integer(), nullable=True),
        sa.Column("used_at_tick", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_player_effects_player_id", "player_effects", ["player_id"])
    op.create_index("ix_player_effects_effect_type", "player_effects", ["effect_type"])
    op.create_index(
        "ix_player_effects_created_tick", "player_effects", ["created_tick"]
    )
    op.create_index(
        "ix_player_effects_expires_tick", "player_effects", ["expires_tick"]
    )


def downgrade() -> None:
    op.drop_index("ix_player_effects_expires_tick", table_name="player_effects")
    op.drop_index("ix_player_effects_created_tick", table_name="player_effects")
    op.drop_index("ix_player_effects_effect_type", table_name="player_effects")
    op.drop_index("ix_player_effects_player_id", table_name="player_effects")
    op.drop_table("player_effects")
    with op.batch_alter_table("explored_sectors") as batch:
        batch.drop_column("discovery_seen_tick")
        batch.drop_column("discovery_done")
