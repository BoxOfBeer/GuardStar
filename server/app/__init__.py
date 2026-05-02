from flask import Flask
from dotenv import load_dotenv

from app.config import Config
from app.db.engine import get_engine, init_engine, init_session_factory
from app.routes.api import api_bp
from app.routes.web import web_bp
from app.services.auto_tick import start_auto_tick

_auto_tick_started = False


def create_app() -> Flask:
    load_dotenv()
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(Config())

    init_engine(app.config["DATABASE_URL"])
    init_session_factory()
    # Для MVP/локальной разработки: если таблиц ещё нет, создаём их автоматически.
    # Миграции Alembic остаются основным способом обновлений схемы.
    from app.db.models import Base
    from app.db.models.fleet import Fleet  # noqa: F401
    from app.db.models.planet import Planet  # noqa: F401
    from app.db.models.player import Player  # noqa: F401
    from app.db.models.resource import Resource  # noqa: F401
    from app.db.models.resource_tick import ResourceTick  # noqa: F401
    from app.db.models.unit import Unit  # noqa: F401
    from app.db.models.unit_order import UnitOrder  # noqa: F401
    from app.db.models.game_clock import GameClock  # noqa: F401
    from app.db.models.world_state import WorldState  # noqa: F401
    from app.db.models.admin_config import AdminConfig  # noqa: F401
    from app.db.models.event import Event  # noqa: F401
    from app.db.models.fleet_order import FleetOrder  # noqa: F401
    from app.db.models.explored_sector import ExploredSector  # noqa: F401
    from app.db.models.influence_cell import InfluenceCell  # noqa: F401
    from app.db.models.building import Building  # noqa: F401
    from app.db.models.outpost import Outpost  # noqa: F401
    from app.db.models.outpost_module import OutpostModule  # noqa: F401
    from app.db.models.player_tech import PlayerTech  # noqa: F401
    from app.db.models.player_effect import PlayerEffect  # noqa: F401
    from app.db.models.fleet_ship import FleetShip  # noqa: F401
    from app.db.models.feedback_playtest_api_log import FeedbackPlaytestApiLog  # noqa: F401
    from app.db.models.feedback_message import FeedbackMessage  # noqa: F401

    if bool(app.config.get("GUARDSTAR_DB_SAFETY_NET", True)):
        Base.metadata.create_all(get_engine())
        # MVP safety net: create_all() не делает ALTER TABLE.
        # Если вы обновили код, но не прогнали alembic, добавим минимально нужные колонки/таблицы.
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
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_outpost_modules_finish_tick ON outpost_modules (finish_tick)"
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
                              auto_tick_interval_seconds DOUBLE PRECISION NOT NULL DEFAULT 5.0,
                              player_spawn_min_manhattan INTEGER NOT NULL DEFAULT 25
                            );
                            """
                        )
                    )
                    # singleton row
                    conn.execute(
                        text(
                            "INSERT INTO world_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING"
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
        except Exception:
            pass

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    # ADMIN_TOKEN из конфига (env или дефолт в Config) — источник правды для хэша в БД при каждом старте.
    # Иначе после смены токена в коде/.env старый хэш в admin_config остаётся и вход ломается.
    # Явный ADMIN_TOKEN="" в окружении оставляет env_tok пустым — хэш не трогаем (ручная настройка в БД).
    try:
        from sqlalchemy import select

        from app.db.engine import db_session
        from app.db.models.admin_config import AdminConfig
        from app.services.auth_service import AuthService

        env_tok = (str(app.config.get("ADMIN_TOKEN") or "")).strip()
        if env_tok:
            auth_svc = AuthService(server_salt=app.config["SERVER_SALT"])
            h = auth_svc.hash_access_code(env_tok)
            with db_session() as s:
                cfg = s.execute(
                    select(AdminConfig).where(AdminConfig.id == 1)
                ).scalar_one_or_none()
                if cfg is None:
                    s.add(AdminConfig(id=1, admin_token_hash=h))
                else:
                    cfg.admin_token_hash = h
                s.commit()
    except Exception as e:
        app.logger.warning("admin token bootstrap failed: %s", e)

    # Загружаем баланс (JSON) один раз на старте (in-memory).
    try:
        from app.services.balance_service import BalanceService, default_balance_dir

        app.extensions["balance_service"] = BalanceService.load_from_path(
            default_balance_dir()
        )
    except Exception as e:
        # Если баланс не загрузился — лучше сразу видеть это в /api/world/state.
        app.extensions["balance_error"] = repr(e)

    # Подтянем настройки автотика из БД (переживают рестарт).
    try:
        from app.db.engine import db_session
        from sqlalchemy import select
        from app.db.models.world_state import WorldState

        with db_session() as s:
            ws = s.execute(
                select(WorldState).where(WorldState.id == 1)
            ).scalar_one_or_none()
            if not ws:
                ws = WorldState(id=1, current_tick=0)
                s.add(ws)
                s.commit()
            app.config["AUTO_TICK_ENABLED"] = bool(ws.auto_tick_enabled)
            app.config["AUTO_TICK_INTERVAL_SECONDS"] = float(
                ws.auto_tick_interval_seconds
            )
    except Exception as e:
        # Не валим приложение из-за настроек (в MVP важнее подняться).
        app.extensions["auto_tick_error"] = repr(e)

    # Автотики (MVP): один процесс, без gunicorn workers.
    # Защитимся от двойного старта в одном процессе, если create_app() вызовут повторно.
    global _auto_tick_started
    if (not _auto_tick_started) and app.config.get("AUTO_TICK_ENABLED"):
        try:
            start_auto_tick(app)
            _auto_tick_started = True
        except Exception as e:
            # В MVP лучше не падать целиком из-за планировщика, но важно видеть причину.
            app.extensions["auto_tick_error"] = repr(e)

    return app
