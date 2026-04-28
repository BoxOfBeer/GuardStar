from __future__ import annotations

import threading

from flask import Flask


def start_auto_tick(app: Flask) -> None:
    from apscheduler.schedulers.background import BackgroundScheduler

    from app.db.engine import db_session
    from app.services.world_service import WorldService

    if app.extensions.get("auto_tick_scheduler"):
        return

    tick_lock = threading.Lock()

    def _do_tick():
        if not tick_lock.acquire(blocking=False):
            return
        try:
            try:
                with app.app_context():
                    with db_session() as s:
                        world = WorldService(world_seed=app.config["SERVER_SALT"])
                        result = world.process_next_tick(s)
                        s.commit()
                app.extensions["auto_tick_last_tick"] = int(result.get("current_tick", 0))
                app.extensions["auto_tick_last_run_at"] = __import__("datetime").datetime.utcnow().isoformat() + "Z"
                app.extensions.pop("auto_tick_error", None)
            except Exception as e:
                # Не даём job «молча умереть» — сохраняем ошибку в state.
                app.extensions["auto_tick_error"] = repr(e)
        finally:
            tick_lock.release()

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        _do_tick,
        "interval",
        seconds=float(app.config.get("AUTO_TICK_INTERVAL_SECONDS", 5)),
        id="auto_world_tick",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    app.extensions["auto_tick_scheduler"] = scheduler
    app.extensions["auto_tick_last_run_at"] = None
    app.extensions["auto_tick_last_tick"] = None


def stop_auto_tick(app: Flask) -> None:
    scheduler = app.extensions.get("auto_tick_scheduler")
    if not scheduler:
        return
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    app.extensions.pop("auto_tick_scheduler", None)
    app.extensions.pop("auto_tick_last_run_at", None)
    app.extensions.pop("auto_tick_last_tick", None)

