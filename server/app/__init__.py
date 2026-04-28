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
    from app.db.models.building import Building  # noqa: F401

    Base.metadata.create_all(get_engine())
    # MVP safety net: create_all() не делает ALTER TABLE.
    # Если вы обновили код, но не прогнали alembic, добавим минимально нужные колонки/таблицы.
    try:
        from sqlalchemy import text
        from sqlalchemy import inspect

        engine = get_engine()
        insp = inspect(engine)

        if "unit_orders" in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns("unit_orders")}
            with engine.begin() as conn:
                if "from_x" not in cols:
                    conn.execute(text("ALTER TABLE unit_orders ADD COLUMN IF NOT EXISTS from_x INTEGER NOT NULL DEFAULT 0"))
                if "from_y" not in cols:
                    conn.execute(text("ALTER TABLE unit_orders ADD COLUMN IF NOT EXISTS from_y INTEGER NOT NULL DEFAULT 0"))
                if "from_z" not in cols:
                    conn.execute(text("ALTER TABLE unit_orders ADD COLUMN IF NOT EXISTS from_z INTEGER NOT NULL DEFAULT 0"))

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
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_events_tick ON events (tick)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_events_type ON events (type)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_events_player_id ON events (player_id)"))

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
                          finish_tick INTEGER NOT NULL
                        );
                        """
                    )
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_fleet_orders_fleet_id ON fleet_orders (fleet_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_fleet_orders_owner_player_id ON fleet_orders (owner_player_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_fleet_orders_status ON fleet_orders (status)"))

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
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_explored_sectors_player_id ON explored_sectors (player_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_explored_sectors_xyz ON explored_sectors (x, y, z)"))
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_explored_sectors_player_xyz ON explored_sectors (player_id, x, y, z)"))

        # Персистентные настройки автотика в game_clock (MVP).
        if "game_clock" in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns("game_clock")}
            with engine.begin() as conn:
                if "auto_tick_enabled" not in cols:
                    conn.execute(text("ALTER TABLE game_clock ADD COLUMN IF NOT EXISTS auto_tick_enabled BOOLEAN NOT NULL DEFAULT false"))
                if "auto_tick_interval_seconds" not in cols:
                    conn.execute(text("ALTER TABLE game_clock ADD COLUMN IF NOT EXISTS auto_tick_interval_seconds DOUBLE PRECISION NOT NULL DEFAULT 5.0"))

        if "resources" in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns("resources")}
            with engine.begin() as conn:
                if "fuel" not in cols:
                    conn.execute(text("ALTER TABLE resources ADD COLUMN IF NOT EXISTS fuel INTEGER NOT NULL DEFAULT 0"))

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
                          auto_tick_interval_seconds DOUBLE PRECISION NOT NULL DEFAULT 5.0
                        );
                        """
                    )
                )
                # singleton row
                conn.execute(text("INSERT INTO world_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING"))

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
                conn.execute(text("INSERT INTO admin_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING"))

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
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_buildings_owner_player_id ON buildings (owner_player_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_buildings_xyz ON buildings (x, y, z)"))

        if "players" in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns("players")}
            with engine.begin() as conn:
                if "race_id" not in cols:
                    conn.execute(text("ALTER TABLE players ADD COLUMN IF NOT EXISTS race_id VARCHAR(32) NULL"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_players_race_id ON players (race_id)"))
    except Exception:
        pass

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    # Загружаем баланс (JSON) на старте, чтобы править без кода.
    try:
        from app.services.balance_service import default_balance_dir, load_balance_pack

        app.extensions["balance"] = load_balance_pack(base_dir=default_balance_dir())
    except Exception as e:
        # Если баланс не загрузился — лучше сразу видеть это в /api/world/state.
        app.extensions["balance_error"] = repr(e)

    # Подтянем настройки автотика из БД (переживают рестарт).
    try:
        from app.db.engine import db_session
        from sqlalchemy import select
        from app.db.models.world_state import WorldState

        with db_session() as s:
            ws = s.execute(select(WorldState).where(WorldState.id == 1)).scalar_one_or_none()
            if not ws:
                ws = WorldState(id=1, current_tick=0)
                s.add(ws)
                s.commit()
            app.config["AUTO_TICK_ENABLED"] = bool(ws.auto_tick_enabled)
            app.config["AUTO_TICK_INTERVAL_SECONDS"] = float(ws.auto_tick_interval_seconds)
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

