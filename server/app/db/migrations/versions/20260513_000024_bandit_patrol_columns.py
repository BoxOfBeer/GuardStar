"""bandit outpost patrol fleet + hunter hunt announce ping"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "20260513_000024"
down_revision = "20260512_000023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)

    if "outposts" in insp.get_table_names():
        ocols = {c["name"] for c in insp.get_columns("outposts")}
        with op.batch_alter_table("outposts") as batch:
            if "patrol_fleet_id" not in ocols:
                batch.add_column(
                    sa.Column(
                        "patrol_fleet_id",
                        postgresql.UUID(as_uuid=True),
                        nullable=True,
                    )
                )
            if "patrol_respawn_at_tick" not in ocols:
                batch.add_column(
                    sa.Column(
                        "patrol_respawn_at_tick",
                        sa.Integer(),
                        nullable=False,
                        server_default=sa.text("0"),
                    )
                )
        if "patrol_fleet_id" not in ocols:
            try:
                op.create_foreign_key(
                    "fk_outposts_patrol_fleet",
                    "outposts",
                    "fleets",
                    ["patrol_fleet_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
            except Exception:
                pass
            try:
                op.create_index(
                    "ix_outposts_patrol_fleet_id",
                    "outposts",
                    ["patrol_fleet_id"],
                    unique=False,
                )
            except Exception:
                pass

    if "fleets" in insp.get_table_names():
        fcols = {c["name"] for c in insp.get_columns("fleets")}
        with op.batch_alter_table("fleets") as batch:
            if "patrol_outpost_id" not in fcols:
                batch.add_column(
                    sa.Column(
                        "patrol_outpost_id",
                        postgresql.UUID(as_uuid=True),
                        nullable=True,
                    )
                )
            if "bandit_hunt_announced" not in fcols:
                batch.add_column(
                    sa.Column(
                        "bandit_hunt_announced",
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.text("false"),
                    )
                )
            if "strike_origin_outpost_id" not in fcols:
                batch.add_column(
                    sa.Column(
                        "strike_origin_outpost_id",
                        postgresql.UUID(as_uuid=True),
                        nullable=True,
                    )
                )
        if "strike_origin_outpost_id" not in fcols:
            try:
                op.create_foreign_key(
                    "fk_fleets_strike_origin_outpost",
                    "fleets",
                    "outposts",
                    ["strike_origin_outpost_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
            except Exception:
                pass
        if "patrol_outpost_id" not in fcols:
            try:
                op.create_foreign_key(
                    "fk_fleets_patrol_outpost",
                    "fleets",
                    "outposts",
                    ["patrol_outpost_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
            except Exception:
                pass


def downgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if "fleets" in insp.get_table_names():
        fcols = {c["name"] for c in insp.get_columns("fleets")}
        if "strike_origin_outpost_id" in fcols:
            try:
                op.drop_constraint(
                    "fk_fleets_strike_origin_outpost",
                    "fleets",
                    type_="foreignkey",
                )
            except Exception:
                pass
        if "patrol_outpost_id" in fcols:
            try:
                op.drop_constraint(
                    "fk_fleets_patrol_outpost", "fleets", type_="foreignkey"
                )
            except Exception:
                pass
        with op.batch_alter_table("fleets") as batch:
            if "strike_origin_outpost_id" in fcols:
                batch.drop_column("strike_origin_outpost_id")
            if "bandit_hunt_announced" in fcols:
                batch.drop_column("bandit_hunt_announced")
            if "patrol_outpost_id" in fcols:
                batch.drop_column("patrol_outpost_id")

    if "outposts" in insp.get_table_names():
        ocols = {c["name"] for c in insp.get_columns("outposts")}
        if "patrol_fleet_id" in ocols:
            try:
                op.drop_index(
                    "ix_outposts_patrol_fleet_id", table_name="outposts"
                )
            except Exception:
                pass
            try:
                op.drop_constraint(
                    "fk_outposts_patrol_fleet", "outposts", type_="foreignkey"
                )
            except Exception:
                pass
        with op.batch_alter_table("outposts") as batch:
            if "patrol_respawn_at_tick" in ocols:
                batch.drop_column("patrol_respawn_at_tick")
            if "patrol_fleet_id" in ocols:
                batch.drop_column("patrol_fleet_id")
