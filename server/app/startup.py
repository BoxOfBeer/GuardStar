"""Точки входа после создания Flask-приложения и схемы БД."""

from __future__ import annotations

from flask import Flask

from app.services.auto_tick import start_auto_tick

_auto_tick_started = False


def bootstrap_admin_token_from_env(app: Flask) -> None:
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


def bootstrap_balance_service(app: Flask) -> None:
    try:
        from app.services.balance_service import BalanceService, default_balance_dir

        app.extensions["balance_service"] = BalanceService.load_from_path(
            default_balance_dir()
        )
    except Exception as e:
        # Если баланс не загрузился — лучше сразу видеть это в /api/world/state.
        app.extensions["balance_error"] = repr(e)


def bootstrap_auto_tick_config(app: Flask) -> None:
    try:
        from sqlalchemy import select

        from app.db.engine import db_session
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


def start_auto_tick_if_enabled(app: Flask) -> None:
    global _auto_tick_started
    if (not _auto_tick_started) and app.config.get("AUTO_TICK_ENABLED"):
        try:
            start_auto_tick(app)
            _auto_tick_started = True
        except Exception as e:
            # В MVP лучше не падать целиком из-за планировщика, но важно видеть причину.
            app.extensions["auto_tick_error"] = repr(e)
