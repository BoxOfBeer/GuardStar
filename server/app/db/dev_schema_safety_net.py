"""MVP: догонка схемы БД без Alembic (только при GUARDSTAR_DB_SAFETY_NET).

Соответствие миграциям на проде: ``docs/safety-net-parity.md`` (миграция ``20260517_000028``).
"""

from __future__ import annotations

from app.db.engine import get_engine


def apply_dev_schema_safety_net() -> None:
    try:
        from sqlalchemy import text
        from sqlalchemy import inspect

        engine = get_engine()
        insp = inspect(engine)

        # Planets: добавляем колонки для населения/класса/слотов, если БД устарела.
        if "planets" in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns("planets")}
            with engine.begin() as conn:
                if "population" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE planets ADD COLUMN IF NOT EXISTS population INTEGER NOT NULL DEFAULT 800"
                        )
                    )
                if "max_population" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE planets ADD COLUMN IF NOT EXISTS max_population INTEGER NOT NULL DEFAULT 5000"
                        )
                    )
                if "planet_class" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE planets ADD COLUMN IF NOT EXISTS planet_class VARCHAR(32) NOT NULL DEFAULT 'earthlike'"
                        )
                    )
                if "build_slots_total" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE planets ADD COLUMN IF NOT EXISTS build_slots_total INTEGER NOT NULL DEFAULT 55"
                        )
                    )
                if "supplier_count" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE planets ADD COLUMN IF NOT EXISTS supplier_count INTEGER NOT NULL DEFAULT 0"
                        )
                    )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_planets_planet_class ON planets (planet_class)"
                    )
                )

        if "fleets" in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns("fleets")}
            with engine.begin() as conn:
                if "energy" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE fleets ADD COLUMN IF NOT EXISTS energy INTEGER NOT NULL DEFAULT 100"
                        )
                    )
                if "max_energy" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE fleets ADD COLUMN IF NOT EXISTS max_energy INTEGER NOT NULL DEFAULT 100"
                        )
                    )
                if "hunt_target_fleet_id" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE fleets ADD COLUMN IF NOT EXISTS hunt_target_fleet_id UUID NULL REFERENCES fleets(id) ON DELETE SET NULL"
                        )
                    )
                if "patrol_outpost_id" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE fleets ADD COLUMN IF NOT EXISTS patrol_outpost_id UUID NULL"
                        )
                    )
                if "strike_origin_outpost_id" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE fleets ADD COLUMN IF NOT EXISTS strike_origin_outpost_id UUID NULL"
                        )
                    )
                if "bandit_hunt_announced" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE fleets ADD COLUMN IF NOT EXISTS bandit_hunt_announced BOOLEAN NOT NULL DEFAULT false"
                        )
                    )

        if "unit_orders" in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns("unit_orders")}
            with engine.begin() as conn:
                if "from_x" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE unit_orders ADD COLUMN IF NOT EXISTS from_x INTEGER NOT NULL DEFAULT 0"
                        )
                    )
                if "from_y" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE unit_orders ADD COLUMN IF NOT EXISTS from_y INTEGER NOT NULL DEFAULT 0"
                        )
                    )
                if "from_z" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE unit_orders ADD COLUMN IF NOT EXISTS from_z INTEGER NOT NULL DEFAULT 0"
                        )
                    )

        if "events" not in insp.get_table_names():
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS events (
                          id SERIAL PRIMARY KEY,
                          tick INTEGER NOT NULL,
                          type VARCHAR(64) NOT NULL,
                          message VARCHAR(255) NOT NULL,
                          payload_json TEXT NULL,
                          player_id UUID NULL,
                          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                        );
                        """
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_events_tick ON events (tick)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_events_type ON events (type)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_events_player_id ON events (player_id)"
                    )
                )

        if "fleet_orders" not in insp.get_table_names():
            with engine.begin() as conn:
                conn.execute(
                    text(
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
                        );
                        """
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_fleet_orders_fleet_id ON fleet_orders (fleet_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_fleet_orders_owner_player_id ON fleet_orders (owner_player_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_fleet_orders_status ON fleet_orders (status)"
                    )
                )

        # Alembic 20260429_000006: если таблица уже была без новых колонок — догоняем схему без ручного upgrade.
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE fleet_orders ADD COLUMN IF NOT EXISTS force_attack BOOLEAN NOT NULL DEFAULT false"
                    )
                )
                conn.execute(
                    text(
                        "ALTER TABLE fleet_orders ADD COLUMN IF NOT EXISTS combat_prompt_expires_at TIMESTAMPTZ NULL"
                    )
                )
        except Exception:
            pass

        if "explored_sectors" not in insp.get_table_names():
            with engine.begin() as conn:
                conn.execute(
                    text(
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
            insp = inspect(engine)
        if "outposts" not in insp.get_table_names():
            with engine.begin() as conn:
                conn.execute(
                    text(
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
                        );
                        """
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_outposts_owner_player_id ON outposts (owner_player_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_outposts_planet_id ON outposts (planet_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_outposts_builder_fleet_id ON outposts (builder_fleet_id)"
                    )
                )
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_outposts_x ON outposts (x)")
                )
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_outposts_y ON outposts (y)")
                )
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_outposts_z ON outposts (z)")
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_outposts_outpost_type ON outposts (outpost_type)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_outposts_status ON outposts (status)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_outposts_finish_tick ON outposts (finish_tick)"
                    )
                )
        else:
            cols = {c["name"] for c in insp.get_columns("outposts")}
            with engine.begin() as conn:
                if "started_at_tick" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE outposts ADD COLUMN IF NOT EXISTS started_at_tick INTEGER NOT NULL DEFAULT 0"
                        )
                    )
                if "finish_tick" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE outposts ADD COLUMN IF NOT EXISTS finish_tick INTEGER NOT NULL DEFAULT 0"
                        )
                    )
                if "hp_current" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE outposts ADD COLUMN IF NOT EXISTS hp_current INTEGER NULL"
                        )
                    )
                if "strike_next_tick" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE outposts ADD COLUMN IF NOT EXISTS strike_next_tick INTEGER NOT NULL DEFAULT 0"
                        )
                    )
                if "patrol_fleet_id" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE outposts ADD COLUMN IF NOT EXISTS patrol_fleet_id UUID NULL"
                        )
                    )
                if "patrol_respawn_at_tick" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE outposts ADD COLUMN IF NOT EXISTS patrol_respawn_at_tick INTEGER NOT NULL DEFAULT 0"
                        )
                    )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_outposts_finish_tick ON outposts (finish_tick)"
                    )
                )

        if "outpost_modules" not in insp.get_table_names():
            with engine.begin() as conn:
                conn.execute(
                    text(
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
                        );
                        """
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_outpost_modules_outpost_id ON outpost_modules (outpost_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_outpost_modules_module_type ON outpost_modules (module_type)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_outpost_modules_kind ON outpost_modules (kind)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_outpost_modules_status ON outpost_modules (status)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_outpost_modules_finish_tick ON outpost_modules (finish_tick)"
                    )
                )
        else:
            cols = {c["name"] for c in insp.get_columns("outpost_modules")}
            with engine.begin() as conn:
                if "started_at_tick" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE outpost_modules ADD COLUMN IF NOT EXISTS started_at_tick INTEGER NOT NULL DEFAULT 0"
                        )
                    )
                if "finish_tick" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE outpost_modules ADD COLUMN IF NOT EXISTS finish_tick INTEGER NOT NULL DEFAULT 0"
                        )
                    )
                if "pending_module_type" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE outpost_modules ADD COLUMN IF NOT EXISTS pending_module_type VARCHAR(64)"
                        )
                    )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_outpost_modules_finish_tick ON outpost_modules (finish_tick)"
                    )
                )

        # Персистентные настройки автотика в game_clock (MVP).
        if "game_clock" in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns("game_clock")}
            with engine.begin() as conn:
                if "auto_tick_enabled" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE game_clock ADD COLUMN IF NOT EXISTS auto_tick_enabled BOOLEAN NOT NULL DEFAULT false"
                        )
                    )
                if "auto_tick_interval_seconds" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE game_clock ADD COLUMN IF NOT EXISTS auto_tick_interval_seconds DOUBLE PRECISION NOT NULL DEFAULT 5.0"
                        )
                    )

        if "resources" in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns("resources")}
            with engine.begin() as conn:
                if "fuel" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE resources ADD COLUMN IF NOT EXISTS fuel INTEGER NOT NULL DEFAULT 0"
                        )
                    )
                if "food" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE resources ADD COLUMN IF NOT EXISTS food INTEGER NOT NULL DEFAULT 0"
                        )
                    )
                if "water" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE resources ADD COLUMN IF NOT EXISTS water INTEGER NOT NULL DEFAULT 0"
                        )
                    )

        if "world_state" not in insp.get_table_names():
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS world_state (
                          id INTEGER PRIMARY KEY,
                          current_tick INTEGER NOT NULL DEFAULT 0,
                          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                          auto_tick_enabled BOOLEAN NOT NULL DEFAULT false,
                          auto_tick_interval_seconds DOUBLE PRECISION NOT NULL DEFAULT 10.0,
                          player_spawn_min_manhattan INTEGER NOT NULL DEFAULT 25
                        );
                        """
                    )
                )
                # singleton row
                conn.execute(
                    text(
                        """
                        INSERT INTO world_state (
                          id, current_tick, updated_at,
                          auto_tick_enabled, auto_tick_interval_seconds, player_spawn_min_manhattan
                        ) VALUES (
                          1, 0, now(),
                          false, 10.0, 25
                        ) ON CONFLICT (id) DO NOTHING
                        """
                    )
                )

        if "world_state" in insp.get_table_names():
            ws_cols = {c["name"] for c in insp.get_columns("world_state")}
            with engine.begin() as conn:
                if "player_spawn_min_manhattan" not in ws_cols:
                    conn.execute(
                        text(
                            "ALTER TABLE world_state ADD COLUMN IF NOT EXISTS player_spawn_min_manhattan INTEGER NOT NULL DEFAULT 25"
                        )
                    )
                if "test_block_new_fleets" not in ws_cols:
                    conn.execute(
                        text(
                            "ALTER TABLE world_state ADD COLUMN IF NOT EXISTS test_block_new_fleets BOOLEAN NOT NULL DEFAULT false"
                        )
                    )
                for sql in (
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
                    "ALTER TABLE world_state ADD COLUMN IF NOT EXISTS admin_presence_window_minutes INTEGER NOT NULL DEFAULT 10",
                ):
                    conn.execute(text(sql))

        if "admin_config" not in insp.get_table_names():
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS admin_config (
                          id INTEGER PRIMARY KEY,
                          admin_token_hash VARCHAR(64) NOT NULL DEFAULT '',
                          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                        );
                        """
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO admin_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING"
                    )
                )

        if "buildings" not in insp.get_table_names():
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS buildings (
                          id UUID PRIMARY KEY,
                          owner_player_id UUID NOT NULL REFERENCES players(id) ON DELETE CASCADE,
                          x INTEGER NOT NULL,
                          y INTEGER NOT NULL,
                          z INTEGER NOT NULL DEFAULT 0,
                          building_type VARCHAR(32) NOT NULL,
                          level INTEGER NOT NULL DEFAULT 1,
                          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                        );
                        """
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_buildings_owner_player_id ON buildings (owner_player_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_buildings_xyz ON buildings (x, y, z)"
                    )
                )

        if "players" in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns("players")}
            with engine.begin() as conn:
                if "race_id" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE players ADD COLUMN IF NOT EXISTS race_id VARCHAR(32) NULL"
                        )
                    )
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_players_race_id ON players (race_id)"
                        )
                    )
                if "feedback_audited" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE players ADD COLUMN IF NOT EXISTS feedback_audited BOOLEAN NOT NULL DEFAULT false"
                        )
                    )
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_players_feedback_audited ON players (feedback_audited)"
                        )
                    )
                if "research_points" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE players ADD COLUMN IF NOT EXISTS research_points NUMERIC(16,6) NOT NULL DEFAULT 0"
                        )
                    )
                if "last_game_activity_at" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE players ADD COLUMN IF NOT EXISTS last_game_activity_at TIMESTAMPTZ NULL"
                        )
                    )
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_players_last_game_activity_at ON players (last_game_activity_at)"
                        )
                    )

        if "planets" in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns("planets")}
            with engine.begin() as conn:
                if "population" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE planets ADD COLUMN IF NOT EXISTS population INTEGER NOT NULL DEFAULT 800"
                        )
                    )
                if "max_population" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE planets ADD COLUMN IF NOT EXISTS max_population INTEGER NOT NULL DEFAULT 5000"
                        )
                    )

        if "buildings" in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns("buildings")}
            with engine.begin() as conn:
                if "planet_id" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE buildings ADD COLUMN IF NOT EXISTS planet_id UUID NULL REFERENCES planets(id) ON DELETE SET NULL"
                        )
                    )
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_buildings_planet_id ON buildings (planet_id)"
                        )
                    )
                if "capture_progress" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE buildings ADD COLUMN IF NOT EXISTS capture_progress DOUBLE PRECISION NOT NULL DEFAULT 0"
                        )
                    )
                if "capture_attacker_id" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE buildings ADD COLUMN IF NOT EXISTS capture_attacker_id UUID NULL REFERENCES players(id) ON DELETE SET NULL"
                        )
                    )
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_buildings_capture_attacker_id ON buildings (capture_attacker_id)"
                        )
                    )

        if "fleet_ships" not in insp.get_table_names():
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS fleet_ships (
                          fleet_id UUID NOT NULL REFERENCES fleets(id) ON DELETE CASCADE,
                          unit_type VARCHAR(32) NOT NULL,
                          qty INTEGER NOT NULL DEFAULT 0,
                          PRIMARY KEY (fleet_id, unit_type)
                        );
                        """
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_fleet_ships_fleet_id ON fleet_ships (fleet_id)"
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO fleet_ships (fleet_id, unit_type, qty)
                        SELECT id, unit_type, qty FROM fleets WHERE qty > 0
                        ON CONFLICT (fleet_id, unit_type) DO NOTHING;
                        """
                    )
                )

        if "fleets" in insp.get_table_names():
            fleet_cols_before = {c["name"] for c in insp.get_columns("fleets")}
            fleet_name_added = "name" not in fleet_cols_before
            from app.fleet_defaults import (
                fleet_display_name_for_index as _fleet_name_slot,
            )

            with engine.begin() as conn:
                if fleet_name_added:
                    conn.execute(
                        text(
                            "ALTER TABLE fleets ADD COLUMN IF NOT EXISTS name VARCHAR(64) NOT NULL DEFAULT ''"
                        )
                    )

            if fleet_name_added:
                with engine.begin() as conn:
                    pids = conn.execute(
                        text("SELECT DISTINCT owner_player_id FROM fleets")
                    ).fetchall()
                    for (pid,) in pids:
                        frows = conn.execute(
                            text(
                                "SELECT id FROM fleets WHERE owner_player_id = :pid ORDER BY created_at ASC"
                            ),
                            {"pid": pid},
                        ).fetchall()
                        for idx, (fid,) in enumerate(frows):
                            conn.execute(
                                text(
                                    "UPDATE fleets SET name = :nm WHERE id = :fid"
                                ),
                                {"nm": _fleet_name_slot(idx), "fid": fid},
                            )

        if "player_techs" not in insp.get_table_names():
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS player_techs (
                          id SERIAL PRIMARY KEY,
                          player_id UUID NOT NULL REFERENCES players(id) ON DELETE CASCADE,
                          tech_id VARCHAR(64) NOT NULL,
                          status VARCHAR(16) NOT NULL DEFAULT 'in_progress',
                          started_tick INTEGER NOT NULL DEFAULT 0,
                          finish_tick INTEGER NOT NULL DEFAULT 0,
                          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                          CONSTRAINT ux_player_techs_player_tech UNIQUE (player_id, tech_id)
                        );
                        """
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_player_techs_player_id ON player_techs (player_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_player_techs_tech_id ON player_techs (tech_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_player_techs_status ON player_techs (status)"
                    )
                )

        if "explored_sectors" in insp.get_table_names():
            es_cols = {c["name"] for c in insp.get_columns("explored_sectors")}
            with engine.begin() as conn:
                if "discovery_done" not in es_cols:
                    conn.execute(
                        text(
                            "ALTER TABLE explored_sectors ADD COLUMN IF NOT EXISTS discovery_done BOOLEAN NOT NULL DEFAULT false"
                        )
                    )
                if "discovery_seen_tick" not in es_cols:
                    conn.execute(
                        text(
                            "ALTER TABLE explored_sectors ADD COLUMN IF NOT EXISTS discovery_seen_tick INTEGER NULL"
                        )
                    )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_explored_sectors_player_id ON explored_sectors (player_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_explored_sectors_xyz ON explored_sectors (x, y, z)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ux_explored_sectors_player_xyz ON explored_sectors (player_id, x, y, z)"
                    )
                )

        if "player_effects" not in insp.get_table_names():
            with engine.begin() as conn:
                conn.execute(
                    text(
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
                        );
                        """
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_player_effects_player_id ON player_effects (player_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_player_effects_effect_type ON player_effects (effect_type)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_player_effects_created_tick ON player_effects (created_tick)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_player_effects_expires_tick ON player_effects (expires_tick)"
                    )
                )

        if "feedback_playtest_api_logs" not in insp.get_table_names():
            with engine.begin() as conn:
                conn.execute(
                    text(
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
                        );
                        """
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_feedback_playtest_api_logs_player_id ON feedback_playtest_api_logs (player_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_feedback_playtest_api_logs_created_at ON feedback_playtest_api_logs (created_at)"
                    )
                )

        # Личные сообщения: read_receipt_at + таблица настроек пары (20260510_000021).
        if "chat_messages" in insp.get_table_names():
            cm_cols = {c["name"] for c in insp.get_columns("chat_messages")}
            with engine.begin() as conn:
                if "read_receipt_at" not in cm_cols:
                    conn.execute(
                        text(
                            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS read_receipt_at TIMESTAMPTZ NULL"
                        )
                    )
        if "private_chat_peer_prefs" not in insp.get_table_names():
            with engine.begin() as conn:
                conn.execute(
                    text(
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
                        );
                        """
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_private_chat_peer_prefs_viewer ON private_chat_peer_prefs (viewer_player_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_private_chat_peer_prefs_peer ON private_chat_peer_prefs (peer_player_id)"
                    )
                )
    except Exception:
        pass
