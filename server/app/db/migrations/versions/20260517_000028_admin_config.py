"""Прод-схема без safety-net: admin_config, race_id, fleets, resources, fleet_ships, buildings, player_techs, game_clock autotick.

Остаток идемпотентного DDL — паритет с ``dev_schema_safety_net`` (см. ``docs/safety-net-parity.md``).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql

from app.fleet_defaults import fleet_display_name_for_index

revision = "20260517_000028"
down_revision = "20260516_000027"
branch_labels = None
depends_on = None


def _apply_safety_net_parity_sql(conn) -> None:
    """Идемпотентные догонки схемы (остаток к ``apply_dev_schema_safety_net``)."""
    stmts = (
        # planets
        "ALTER TABLE planets ADD COLUMN IF NOT EXISTS population INTEGER NOT NULL DEFAULT 800",
        "ALTER TABLE planets ADD COLUMN IF NOT EXISTS max_population INTEGER NOT NULL DEFAULT 5000",
        "ALTER TABLE planets ADD COLUMN IF NOT EXISTS planet_class VARCHAR(32) NOT NULL DEFAULT 'earthlike'",
        "ALTER TABLE planets ADD COLUMN IF NOT EXISTS build_slots_total INTEGER NOT NULL DEFAULT 55",
        "ALTER TABLE planets ADD COLUMN IF NOT EXISTS supplier_count INTEGER NOT NULL DEFAULT 0",
        "CREATE INDEX IF NOT EXISTS ix_planets_planet_class ON planets (planet_class)",
        # fleets (кроме name — выше в upgrade)
        "ALTER TABLE fleets ADD COLUMN IF NOT EXISTS energy INTEGER NOT NULL DEFAULT 100",
        "ALTER TABLE fleets ADD COLUMN IF NOT EXISTS max_energy INTEGER NOT NULL DEFAULT 100",
        "ALTER TABLE fleets ADD COLUMN IF NOT EXISTS hunt_target_fleet_id UUID NULL REFERENCES fleets(id) ON DELETE SET NULL",
        "ALTER TABLE fleets ADD COLUMN IF NOT EXISTS patrol_outpost_id UUID NULL",
        "ALTER TABLE fleets ADD COLUMN IF NOT EXISTS strike_origin_outpost_id UUID NULL",
        "ALTER TABLE fleets ADD COLUMN IF NOT EXISTS bandit_hunt_announced BOOLEAN NOT NULL DEFAULT false",
        # unit_orders
        "ALTER TABLE unit_orders ADD COLUMN IF NOT EXISTS from_x INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE unit_orders ADD COLUMN IF NOT EXISTS from_y INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE unit_orders ADD COLUMN IF NOT EXISTS from_z INTEGER NOT NULL DEFAULT 0",
        # events
        """
        CREATE TABLE IF NOT EXISTS events (
          id SERIAL PRIMARY KEY,
          tick INTEGER NOT NULL,
          type VARCHAR(64) NOT NULL,
          message VARCHAR(255) NOT NULL,
          payload_json TEXT NULL,
          player_id UUID NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_events_tick ON events (tick)",
        "CREATE INDEX IF NOT EXISTS ix_events_type ON events (type)",
        "CREATE INDEX IF NOT EXISTS ix_events_player_id ON events (player_id)",
        # fleet_orders
        """
        CREATE TABLE IF NOT EXISTS fleet_orders (
          id UUID PRIMARY KEY,
          fleet_id UUID NOT NULL REFERENCES fleets(id) ON DELETE CASCADE,
          owner_player_id UUID NOT NULL REFERENCES players(id) ON DELETE CASCADE,
          order_type VARCHAR(32) NOT NULL DEFAULT 'move',
          from_x INTEGER NOT NULL,
          from_y INTEGER NOT NULL,
          from_z INTEGER NOT NULL DEFAULT 0,
          target_x INTEGER NOT NULL,
          target_y INTEGER NOT NULL,
          target_z INTEGER NOT NULL DEFAULT 0,
          qty INTEGER NOT NULL DEFAULT 0,
          status VARCHAR(32) NOT NULL DEFAULT 'queued',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          start_tick INTEGER NOT NULL,
          finish_tick INTEGER NOT NULL,
          force_attack BOOLEAN NOT NULL DEFAULT false,
          combat_prompt_expires_at TIMESTAMPTZ NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_fleet_orders_fleet_id ON fleet_orders (fleet_id)",
        "CREATE INDEX IF NOT EXISTS ix_fleet_orders_owner_player_id ON fleet_orders (owner_player_id)",
        "CREATE INDEX IF NOT EXISTS ix_fleet_orders_status ON fleet_orders (status)",
        "ALTER TABLE fleet_orders ADD COLUMN IF NOT EXISTS force_attack BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE fleet_orders ADD COLUMN IF NOT EXISTS combat_prompt_expires_at TIMESTAMPTZ NULL",
        # explored_sectors
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
        )
        """,
        "ALTER TABLE explored_sectors ADD COLUMN IF NOT EXISTS discovery_done BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE explored_sectors ADD COLUMN IF NOT EXISTS discovery_seen_tick INTEGER NULL",
        "CREATE INDEX IF NOT EXISTS ix_explored_sectors_player_id ON explored_sectors (player_id)",
        "CREATE INDEX IF NOT EXISTS ix_explored_sectors_xyz ON explored_sectors (x, y, z)",
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_explored_sectors_player_xyz
        ON explored_sectors (player_id, x, y, z)
        """,
        # outposts
        """
        CREATE TABLE IF NOT EXISTS outposts (
          id UUID PRIMARY KEY,
          owner_player_id UUID NOT NULL REFERENCES players(id) ON DELETE CASCADE,
          planet_id UUID NULL REFERENCES planets(id) ON DELETE SET NULL,
          builder_fleet_id UUID NULL REFERENCES fleets(id) ON DELETE SET NULL,
          x INTEGER NOT NULL,
          y INTEGER NOT NULL,
          z INTEGER NOT NULL DEFAULT 0,
          outpost_type VARCHAR(64) NOT NULL,
          family VARCHAR(64) NOT NULL DEFAULT 'outpost',
          level INTEGER NOT NULL DEFAULT 1,
          module_slots_total INTEGER NOT NULL DEFAULT 1,
          status VARCHAR(32) NOT NULL DEFAULT 'active',
          started_at_tick INTEGER NOT NULL DEFAULT 0,
          finish_tick INTEGER NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT uq_outposts_xyz UNIQUE (x, y, z)
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_outposts_owner_player_id ON outposts (owner_player_id)",
        "CREATE INDEX IF NOT EXISTS ix_outposts_planet_id ON outposts (planet_id)",
        "CREATE INDEX IF NOT EXISTS ix_outposts_builder_fleet_id ON outposts (builder_fleet_id)",
        "CREATE INDEX IF NOT EXISTS ix_outposts_x ON outposts (x)",
        "CREATE INDEX IF NOT EXISTS ix_outposts_y ON outposts (y)",
        "CREATE INDEX IF NOT EXISTS ix_outposts_z ON outposts (z)",
        "CREATE INDEX IF NOT EXISTS ix_outposts_outpost_type ON outposts (outpost_type)",
        "CREATE INDEX IF NOT EXISTS ix_outposts_status ON outposts (status)",
        "CREATE INDEX IF NOT EXISTS ix_outposts_finish_tick ON outposts (finish_tick)",
        "ALTER TABLE outposts ADD COLUMN IF NOT EXISTS started_at_tick INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE outposts ADD COLUMN IF NOT EXISTS finish_tick INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE outposts ADD COLUMN IF NOT EXISTS hp_current INTEGER NULL",
        "ALTER TABLE outposts ADD COLUMN IF NOT EXISTS strike_next_tick INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE outposts ADD COLUMN IF NOT EXISTS patrol_fleet_id UUID NULL",
        "ALTER TABLE outposts ADD COLUMN IF NOT EXISTS patrol_respawn_at_tick INTEGER NOT NULL DEFAULT 0",
        # outpost_modules
        """
        CREATE TABLE IF NOT EXISTS outpost_modules (
          id UUID PRIMARY KEY,
          outpost_id UUID NOT NULL REFERENCES outposts(id) ON DELETE CASCADE,
          module_type VARCHAR(64) NOT NULL,
          kind VARCHAR(32) NOT NULL,
          level INTEGER NOT NULL DEFAULT 1,
          slot_idx INTEGER NOT NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'active',
          started_at_tick INTEGER NOT NULL DEFAULT 0,
          finish_tick INTEGER NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT uq_outpost_modules_slot UNIQUE (outpost_id, slot_idx)
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_outpost_modules_outpost_id ON outpost_modules (outpost_id)",
        "CREATE INDEX IF NOT EXISTS ix_outpost_modules_module_type ON outpost_modules (module_type)",
        "CREATE INDEX IF NOT EXISTS ix_outpost_modules_kind ON outpost_modules (kind)",
        "CREATE INDEX IF NOT EXISTS ix_outpost_modules_status ON outpost_modules (status)",
        "CREATE INDEX IF NOT EXISTS ix_outpost_modules_finish_tick ON outpost_modules (finish_tick)",
        "ALTER TABLE outpost_modules ADD COLUMN IF NOT EXISTS started_at_tick INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE outpost_modules ADD COLUMN IF NOT EXISTS finish_tick INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE outpost_modules ADD COLUMN IF NOT EXISTS pending_module_type VARCHAR(64)",
        # world_state
        """
        CREATE TABLE IF NOT EXISTS world_state (
          id INTEGER PRIMARY KEY,
          current_tick INTEGER NOT NULL DEFAULT 0,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          auto_tick_enabled BOOLEAN NOT NULL DEFAULT false,
          auto_tick_interval_seconds DOUBLE PRECISION NOT NULL DEFAULT 10.0,
          player_spawn_min_manhattan INTEGER NOT NULL DEFAULT 25
        )
        """,
        "ALTER TABLE world_state ADD COLUMN IF NOT EXISTS player_spawn_min_manhattan INTEGER NOT NULL DEFAULT 25",
        "ALTER TABLE world_state ADD COLUMN IF NOT EXISTS test_block_new_fleets BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE world_state ADD COLUMN IF NOT EXISTS admin_block_player_fleet_create BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE world_state ADD COLUMN IF NOT EXISTS admin_block_npc_transit BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE world_state ADD COLUMN IF NOT EXISTS admin_block_bandit_mines BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE world_state ADD COLUMN IF NOT EXISTS admin_block_bandit_outposts BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE world_state ADD COLUMN IF NOT EXISTS admin_block_bandit_fleets BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE world_state ADD COLUMN IF NOT EXISTS admin_max_fleet_units INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE world_state ADD COLUMN IF NOT EXISTS admin_research_overrides_json TEXT",
        "ALTER TABLE world_state ADD COLUMN IF NOT EXISTS admin_economy_overrides_json TEXT",
        "ALTER TABLE world_state ADD COLUMN IF NOT EXISTS economy_base_food_per_sol INTEGER NOT NULL DEFAULT 10",
        "ALTER TABLE world_state ADD COLUMN IF NOT EXISTS economy_base_water_per_sol INTEGER NOT NULL DEFAULT 10",
        """
        INSERT INTO world_state (
          id, current_tick, updated_at,
          auto_tick_enabled, auto_tick_interval_seconds, player_spawn_min_manhattan,
          test_block_new_fleets, admin_block_player_fleet_create, admin_block_npc_transit,
          admin_block_bandit_mines, admin_block_bandit_outposts, admin_block_bandit_fleets,
          admin_max_fleet_units, economy_base_food_per_sol, economy_base_water_per_sol
        ) VALUES (
          1, 0, now(),
          false, 10.0, 25,
          false, false, false, false, false, false,
          0, 10, 10
        ) ON CONFLICT (id) DO NOTHING
        """,
        "UPDATE world_state SET player_spawn_min_manhattan = 25 WHERE id = 1 AND player_spawn_min_manhattan IS NULL",
        # buildings (если таблица старая, без колонок из новых миграций)
        "ALTER TABLE buildings ADD COLUMN IF NOT EXISTS planet_id UUID NULL REFERENCES planets(id) ON DELETE SET NULL",
        "CREATE INDEX IF NOT EXISTS ix_buildings_planet_id ON buildings (planet_id)",
        "ALTER TABLE buildings ADD COLUMN IF NOT EXISTS capture_progress DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE buildings ADD COLUMN IF NOT EXISTS capture_attacker_id UUID NULL REFERENCES players(id) ON DELETE SET NULL",
        "CREATE INDEX IF NOT EXISTS ix_buildings_capture_attacker_id ON buildings (capture_attacker_id)",
        # players
        "ALTER TABLE players ADD COLUMN IF NOT EXISTS feedback_audited BOOLEAN NOT NULL DEFAULT false",
        "CREATE INDEX IF NOT EXISTS ix_players_feedback_audited ON players (feedback_audited)",
        "ALTER TABLE players ADD COLUMN IF NOT EXISTS research_points NUMERIC(16,6) NOT NULL DEFAULT 0",
        # player_techs
        "CREATE INDEX IF NOT EXISTS ix_player_techs_status ON player_techs (status)",
        # player_effects
        """
        CREATE TABLE IF NOT EXISTS player_effects (
          id SERIAL PRIMARY KEY,
          player_id UUID NOT NULL REFERENCES players(id) ON DELETE CASCADE,
          effect_type VARCHAR(64) NOT NULL,
          source_type VARCHAR(32) NOT NULL DEFAULT 'unknown',
          source_ref VARCHAR(128) NOT NULL DEFAULT '',
          payload_json TEXT NULL,
          created_tick INTEGER NOT NULL DEFAULT 0,
          expires_tick INTEGER NULL,
          used_at_tick INTEGER NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_player_effects_player_id ON player_effects (player_id)",
        "CREATE INDEX IF NOT EXISTS ix_player_effects_effect_type ON player_effects (effect_type)",
        "CREATE INDEX IF NOT EXISTS ix_player_effects_created_tick ON player_effects (created_tick)",
        "CREATE INDEX IF NOT EXISTS ix_player_effects_expires_tick ON player_effects (expires_tick)",
        # feedback_playtest_api_logs
        """
        CREATE TABLE IF NOT EXISTS feedback_playtest_api_logs (
          id SERIAL PRIMARY KEY,
          player_id UUID NOT NULL REFERENCES players(id) ON DELETE CASCADE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          method VARCHAR(8) NOT NULL,
          path VARCHAR(512) NOT NULL,
          query_string VARCHAR(512) NOT NULL DEFAULT '',
          body_preview TEXT NULL,
          status_code SMALLINT NOT NULL,
          duration_ms INTEGER NOT NULL DEFAULT 0
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_feedback_playtest_api_logs_player_id ON feedback_playtest_api_logs (player_id)",
        "CREATE INDEX IF NOT EXISTS ix_feedback_playtest_api_logs_created_at ON feedback_playtest_api_logs (created_at)",
        # chat / private prefs
        "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS read_receipt_at TIMESTAMPTZ NULL",
        """
        CREATE TABLE IF NOT EXISTS private_chat_peer_prefs (
          id BIGSERIAL PRIMARY KEY,
          viewer_player_id UUID NOT NULL REFERENCES players(id) ON DELETE CASCADE,
          peer_player_id UUID NOT NULL REFERENCES players(id) ON DELETE CASCADE,
          welcomed_at TIMESTAMPTZ NULL,
          send_read_receipts BOOLEAN NOT NULL DEFAULT false,
          last_read_incoming_id BIGINT NOT NULL DEFAULT 0,
          hidden_at TIMESTAMPTZ NULL,
          CONSTRAINT uq_private_chat_peer_prefs_pair UNIQUE (viewer_player_id, peer_player_id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_private_chat_peer_prefs_viewer ON private_chat_peer_prefs (viewer_player_id)",
        "CREATE INDEX IF NOT EXISTS ix_private_chat_peer_prefs_peer ON private_chat_peer_prefs (peer_player_id)",
    )
    for raw in stmts:
        conn.execute(text(raw.strip()))


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if "admin_config" not in insp.get_table_names():
        op.create_table(
            "admin_config",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("admin_token_hash", sa.String(64), nullable=False, server_default=""),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        conn.execute(text("INSERT INTO admin_config (id) VALUES (1)"))

    if "players" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("players")}
        if "race_id" not in cols:
            op.add_column(
                "players",
                sa.Column("race_id", sa.String(32), nullable=True),
            )
            op.create_index("ix_players_race_id", "players", ["race_id"])

    if "fleets" in insp.get_table_names():
        fcols = {c["name"] for c in insp.get_columns("fleets")}
        fleet_name_was_missing = "name" not in fcols
        if "name" not in fcols:
            op.add_column(
                "fleets",
                sa.Column(
                    "name",
                    sa.String(64),
                    nullable=False,
                    server_default="",
                ),
            )
            op.alter_column("fleets", "name", server_default=None)
        if fleet_name_was_missing:
            for (pid,) in conn.execute(
                text("SELECT DISTINCT owner_player_id FROM fleets")
            ).fetchall():
                frows = conn.execute(
                    text(
                        "SELECT id FROM fleets WHERE owner_player_id = :pid "
                        "ORDER BY created_at ASC"
                    ),
                    {"pid": pid},
                ).fetchall()
                for idx, (fid,) in enumerate(frows):
                    conn.execute(
                        text("UPDATE fleets SET name = :nm WHERE id = :fid"),
                        {"nm": fleet_display_name_for_index(idx), "fid": fid},
                    )

    if "resources" in insp.get_table_names():
        rcols = {c["name"] for c in insp.get_columns("resources")}
        with op.batch_alter_table("resources") as batch:
            if "fuel" not in rcols:
                batch.add_column(
                    sa.Column(
                        "fuel",
                        sa.Integer(),
                        nullable=False,
                        server_default=sa.text("0"),
                    )
                )
            if "food" not in rcols:
                batch.add_column(
                    sa.Column(
                        "food",
                        sa.Integer(),
                        nullable=False,
                        server_default=sa.text("0"),
                    )
                )
            if "water" not in rcols:
                batch.add_column(
                    sa.Column(
                        "water",
                        sa.Integer(),
                        nullable=False,
                        server_default=sa.text("0"),
                    )
                )
        for col in ("fuel", "food", "water"):
            if col not in rcols:
                op.alter_column("resources", col, server_default=None)

    if "fleet_ships" not in insp.get_table_names():
        op.create_table(
            "fleet_ships",
            sa.Column(
                "fleet_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column("unit_type", sa.String(32), nullable=False),
            sa.Column(
                "qty",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.PrimaryKeyConstraint("fleet_id", "unit_type"),
            sa.ForeignKeyConstraint(
                ["fleet_id"],
                ["fleets.id"],
                ondelete="CASCADE",
            ),
        )
        op.create_index("ix_fleet_ships_fleet_id", "fleet_ships", ["fleet_id"])
        conn.execute(
            text(
                """
                INSERT INTO fleet_ships (fleet_id, unit_type, qty)
                SELECT id, unit_type, qty FROM fleets WHERE qty > 0
                ON CONFLICT (fleet_id, unit_type) DO NOTHING
                """
            )
        )

    if "buildings" not in insp.get_table_names():
        op.create_table(
            "buildings",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("owner_player_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("x", sa.Integer(), nullable=False),
            sa.Column("y", sa.Integer(), nullable=False),
            sa.Column("z", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("building_type", sa.String(32), nullable=False),
            sa.Column("level", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("planet_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "capture_progress",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("capture_attacker_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["owner_player_id"], ["players.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["planet_id"], ["planets.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["capture_attacker_id"], ["players.id"], ondelete="SET NULL"
            ),
        )
        op.create_index(
            "ix_buildings_owner_player_id", "buildings", ["owner_player_id"]
        )
        op.create_index("ix_buildings_xyz", "buildings", ["x", "y", "z"])
        op.create_index("ix_buildings_planet_id", "buildings", ["planet_id"])
        op.create_index(
            "ix_buildings_capture_attacker_id",
            "buildings",
            ["capture_attacker_id"],
        )

    if "player_techs" not in insp.get_table_names():
        op.create_table(
            "player_techs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("player_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tech_id", sa.String(64), nullable=False),
            sa.Column(
                "status",
                sa.String(16),
                nullable=False,
                server_default=sa.text("'in_progress'"),
            ),
            sa.Column(
                "started_tick", sa.Integer(), nullable=False, server_default=sa.text("0")
            ),
            sa.Column(
                "finish_tick", sa.Integer(), nullable=False, server_default=sa.text("0")
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(
                ["player_id"], ["players.id"], ondelete="CASCADE"
            ),
            sa.UniqueConstraint(
                "player_id", "tech_id", name="ux_player_techs_player_tech"
            ),
        )
        op.create_index("ix_player_techs_player_id", "player_techs", ["player_id"])
        op.create_index("ix_player_techs_tech_id", "player_techs", ["tech_id"])

    _apply_safety_net_parity_sql(conn)

    if "game_clock" in insp.get_table_names():
        gcols = {c["name"] for c in insp.get_columns("game_clock")}
        with op.batch_alter_table("game_clock") as batch:
            if "auto_tick_enabled" not in gcols:
                batch.add_column(
                    sa.Column(
                        "auto_tick_enabled",
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.text("false"),
                    )
                )
            if "auto_tick_interval_seconds" not in gcols:
                batch.add_column(
                    sa.Column(
                        "auto_tick_interval_seconds",
                        sa.Float(),
                        nullable=False,
                        server_default=sa.text("5.0"),
                    )
                )
        if "auto_tick_enabled" not in gcols:
            op.alter_column("game_clock", "auto_tick_enabled", server_default=None)
        if "auto_tick_interval_seconds" not in gcols:
            op.alter_column(
                "game_clock", "auto_tick_interval_seconds", server_default=None
            )


def downgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    if "game_clock" in insp.get_table_names():
        gcols = {c["name"] for c in insp.get_columns("game_clock")}
        with op.batch_alter_table("game_clock") as batch:
            if "auto_tick_interval_seconds" in gcols:
                batch.drop_column("auto_tick_interval_seconds")
            if "auto_tick_enabled" in gcols:
                batch.drop_column("auto_tick_enabled")
    if "player_techs" in insp.get_table_names():
        op.drop_index("ix_player_techs_tech_id", table_name="player_techs")
        op.drop_index("ix_player_techs_player_id", table_name="player_techs")
        op.drop_table("player_techs")
    if "buildings" in insp.get_table_names():
        op.drop_index("ix_buildings_capture_attacker_id", table_name="buildings")
        op.drop_index("ix_buildings_planet_id", table_name="buildings")
        op.drop_index("ix_buildings_xyz", table_name="buildings")
        op.drop_index("ix_buildings_owner_player_id", table_name="buildings")
        op.drop_table("buildings")
    if "fleet_ships" in insp.get_table_names():
        op.drop_index("ix_fleet_ships_fleet_id", table_name="fleet_ships")
        op.drop_table("fleet_ships")
    if "resources" in insp.get_table_names():
        rcols = {c["name"] for c in insp.get_columns("resources")}
        with op.batch_alter_table("resources") as batch:
            if "water" in rcols:
                batch.drop_column("water")
            if "food" in rcols:
                batch.drop_column("food")
            if "fuel" in rcols:
                batch.drop_column("fuel")
    if "fleets" in insp.get_table_names():
        fcols = {c["name"] for c in insp.get_columns("fleets")}
        if "name" in fcols:
            op.drop_column("fleets", "name")
    if "players" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("players")}
        if "race_id" in cols:
            op.drop_index("ix_players_race_id", table_name="players")
            op.drop_column("players", "race_id")
    if "admin_config" in insp.get_table_names():
        op.drop_table("admin_config")
