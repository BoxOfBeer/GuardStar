from flask import Flask
from dotenv import load_dotenv

from app.config import Config
from app.db.engine import get_engine, init_engine, init_session_factory
from app.routes.api import api_bp
from app.routes.web import web_bp


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

    Base.metadata.create_all(get_engine())

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    return app

