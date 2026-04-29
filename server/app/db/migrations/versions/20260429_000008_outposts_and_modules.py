"""add outposts and outpost_modules

Revision ID: 20260429_000008
Revises: 20260429_000007
Create Date: 2026-04-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260429_000008"
down_revision = "20260429_000007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outposts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_player_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("planet_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("builder_fleet_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("x", sa.Integer(), nullable=False),
        sa.Column("y", sa.Integer(), nullable=False),
        sa.Column("z", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("outpost_type", sa.String(length=64), nullable=False),
        sa.Column("family", sa.String(length=64), nullable=False, server_default=sa.text("'outpost'")),
        sa.Column("level", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("module_slots_total", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'active'")),
        sa.Column("started_at_tick", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("finish_tick", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["builder_fleet_id"], ["fleets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_player_id"], ["players.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["planet_id"], ["planets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("x", "y", "z", name="uq_outposts_xyz"),
    )
    op.create_index("ix_outposts_owner_player_id", "outposts", ["owner_player_id"])
    op.create_index("ix_outposts_planet_id", "outposts", ["planet_id"])
    op.create_index("ix_outposts_builder_fleet_id", "outposts", ["builder_fleet_id"])
    op.create_index("ix_outposts_x", "outposts", ["x"])
    op.create_index("ix_outposts_y", "outposts", ["y"])
    op.create_index("ix_outposts_z", "outposts", ["z"])
    op.create_index("ix_outposts_outpost_type", "outposts", ["outpost_type"])
    op.create_index("ix_outposts_status", "outposts", ["status"])
    op.create_index("ix_outposts_finish_tick", "outposts", ["finish_tick"])

    op.create_table(
        "outpost_modules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outpost_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module_type", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("slot_idx", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'active'")),
        sa.Column("started_at_tick", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("finish_tick", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["outpost_id"], ["outposts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("outpost_id", "slot_idx", name="uq_outpost_modules_slot"),
    )
    op.create_index("ix_outpost_modules_outpost_id", "outpost_modules", ["outpost_id"])
    op.create_index("ix_outpost_modules_module_type", "outpost_modules", ["module_type"])
    op.create_index("ix_outpost_modules_kind", "outpost_modules", ["kind"])
    op.create_index("ix_outpost_modules_status", "outpost_modules", ["status"])
    op.create_index("ix_outpost_modules_finish_tick", "outpost_modules", ["finish_tick"])


def downgrade() -> None:
    op.drop_index("ix_outpost_modules_status", table_name="outpost_modules")
    op.drop_index("ix_outpost_modules_kind", table_name="outpost_modules")
    op.drop_index("ix_outpost_modules_module_type", table_name="outpost_modules")
    op.drop_index("ix_outpost_modules_outpost_id", table_name="outpost_modules")
    op.drop_index("ix_outpost_modules_finish_tick", table_name="outpost_modules")
    op.drop_table("outpost_modules")

    op.drop_index("ix_outposts_status", table_name="outposts")
    op.drop_index("ix_outposts_outpost_type", table_name="outposts")
    op.drop_index("ix_outposts_z", table_name="outposts")
    op.drop_index("ix_outposts_y", table_name="outposts")
    op.drop_index("ix_outposts_x", table_name="outposts")
    op.drop_index("ix_outposts_builder_fleet_id", table_name="outposts")
    op.drop_index("ix_outposts_planet_id", table_name="outposts")
    op.drop_index("ix_outposts_owner_player_id", table_name="outposts")
    op.drop_index("ix_outposts_finish_tick", table_name="outposts")
    op.drop_table("outposts")

