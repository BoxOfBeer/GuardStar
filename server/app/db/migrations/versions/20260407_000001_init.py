"""init

Revision ID: 20260407_000001
Revises:
Create Date: 2026-04-07

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260407_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "players",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("access_code_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_players_access_code_hash", "players", ["access_code_hash"], unique=True
    )

    op.create_table(
        "planets",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            "owner_player_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("pos_x", sa.Integer(), nullable=False),
        sa.Column("pos_y", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_planets_owner_player_id", "planets", ["owner_player_id"], unique=False
    )
    op.create_index("ix_planets_pos_x", "planets", ["pos_x"], unique=False)
    op.create_index("ix_planets_pos_y", "planets", ["pos_y"], unique=False)

    op.create_table(
        "resources",
        sa.Column(
            "planet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("planets.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("metal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("crystal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("energy", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "units",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            "owner_player_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "planet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("planets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("unit_type", sa.String(length=32), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_units_owner_player_id", "units", ["owner_player_id"], unique=False
    )
    op.create_index("ix_units_planet_id", "units", ["planet_id"], unique=False)
    op.create_index("ix_units_unit_type", "units", ["unit_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_units_unit_type", table_name="units")
    op.drop_index("ix_units_planet_id", table_name="units")
    op.drop_index("ix_units_owner_player_id", table_name="units")
    op.drop_table("units")

    op.drop_table("resources")

    op.drop_index("ix_planets_pos_y", table_name="planets")
    op.drop_index("ix_planets_pos_x", table_name="planets")
    op.drop_index("ix_planets_owner_player_id", table_name="planets")
    op.drop_table("planets")

    op.drop_index("ix_players_access_code_hash", table_name="players")
    op.drop_table("players")
