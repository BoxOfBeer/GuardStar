from flask import Flask
from dotenv import load_dotenv

from app.config import Config
from app.db.dev_schema_safety_net import apply_dev_schema_safety_net
from app.db.engine import get_engine, init_engine, init_session_factory
from app.db.models import Base
from app.db.models_registry import import_all_models
from app.routes.api import api_bp
from app.routes.web import web_bp
from app.startup import (
    bootstrap_admin_token_from_env,
    bootstrap_auto_tick_config,
    bootstrap_balance_service,
    start_auto_tick_if_enabled,
)


def create_app() -> Flask:
    load_dotenv()
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(Config())

    init_engine(app.config["DATABASE_URL"])
    init_session_factory()
    # Для MVP/локальной разработки: если таблиц ещё нет, создаём их автоматически.
    # Миграции Alembic остаются основным способом обновлений схемы.
    import_all_models()

    if bool(app.config.get("GUARDSTAR_DB_SAFETY_NET", True)):
        Base.metadata.create_all(get_engine())
        # MVP safety net: create_all() не делает ALTER TABLE.
        # Если вы обновили код, но не прогнали alembic, добавим минимально нужные колонки/таблицы.
        apply_dev_schema_safety_net()

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    bootstrap_admin_token_from_env(app)

    # Загружаем баланс (JSON) один раз на старте (in-memory).
    bootstrap_balance_service(app)

    # Подтянем настройки автотика из БД (переживают рестарт).
    bootstrap_auto_tick_config(app)

    # Автотики (MVP): один процесс, без gunicorn workers.
    start_auto_tick_if_enabled(app)

    return app
