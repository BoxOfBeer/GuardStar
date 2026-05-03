"""field building capture + outpost HP + hunter fleets"""

from alembic import op
from sqlalchemy import inspect

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260512_000023"
down_revision = "20260511_000022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)

    if "buildings" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("buildings")}
        with op.batch_alter_table("buildings") as batch:
            if "capture_progress" not in cols:
                batch.add_column(
                    sa.Column(
                        "capture_progress",
                        sa.Float(),
                        nullable=False,
                        server_default=sa.text("0"),
                    )
                )
            if "capture_attacker_id" not in cols:
                batch.add_column(
                    sa.Column(
                        "capture_attacker_id",
                        postgresql.UUID(as_uuid=True),
                        nullable=True,
                    )
                )
        if "capture_attacker_id" not in cols:
            try:
                op.create_foreign_key(
                    "fk_buildings_capture_attacker",
                    "buildings",
                    "players",
                    ["capture_attacker_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
            except Exception:
                pass
            try:
                op.create_index(
                    "ix_buildings_capture_attacker_id",
                    "buildings",
                    ["capture_attacker_id"],
                )
            except Exception:
                pass

    if "outposts" in insp.get_table_names():
        ocols = {c["name"] for c in insp.get_columns("outposts")}
        with op.batch_alter_table("outposts") as batch:
            if "hp_current" not in ocols:
                batch.add_column(sa.Column("hp_current", sa.Integer(), nullable=True))
            if "strike_next_tick" not in ocols:
                batch.add_column(
                    sa.Column(
                        "strike_next_tick",
                        sa.Integer(),
                        nullable=False,
                        server_default=sa.text("0"),
                    )
                )

    if "fleets" in insp.get_table_names():
        fcols = {c["name"] for c in insp.get_columns("fleets")}
        with op.batch_alter_table("fleets") as batch:
            if "hunt_target_fleet_id" not in fcols:
                batch.add_column(
                    sa.Column(
                        "hunt_target_fleet_id",
                        postgresql.UUID(as_uuid=True),
                        nullable=True,
                    )
                )
        if "hunt_target_fleet_id" not in fcols:
            try:
                op.create_foreign_key(
                    "fk_fleets_hunt_target",
                    "fleets",
                    "fleets",
                    ["hunt_target_fleet_id"],
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
        if "hunt_target_fleet_id" in fcols:
            try:
                op.drop_constraint("fk_fleets_hunt_target", "fleets", type_="foreignkey")
            except Exception:
                pass
            with op.batch_alter_table("fleets") as batch:
                batch.drop_column("hunt_target_fleet_id")

    if "outposts" in insp.get_table_names():
        ocols = {c["name"] for c in insp.get_columns("outposts")}
        with op.batch_alter_table("outposts") as batch:
            if "strike_next_tick" in ocols:
                batch.drop_column("strike_next_tick")
            if "hp_current" in ocols:
                batch.drop_column("hp_current")

    if "buildings" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("buildings")}
        if "capture_attacker_id" in cols:
            try:
                op.drop_index("ix_buildings_capture_attacker_id", "buildings")
            except Exception:
                pass
            try:
                op.drop_constraint(
                    "fk_buildings_capture_attacker", "buildings", type_="foreignkey"
                )
            except Exception:
                pass
        with op.batch_alter_table("buildings") as batch:
            if "capture_attacker_id" in cols:
                batch.drop_column("capture_attacker_id")
            if "capture_progress" in cols:
                batch.drop_column("capture_progress")
