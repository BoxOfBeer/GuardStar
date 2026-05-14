from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from flask import Flask

log = logging.getLogger(__name__)


def start_auto_tick(app: Flask) -> None:
    from apscheduler.schedulers.background import BackgroundScheduler

    from app.db.engine import db_session
    from app.services.world_service import WorldService

    if app.extensions.get("auto_tick_scheduler"):
        return

    tick_lock = threading.Lock()

    def _do_tick():
        if not tick_lock.acquire(blocking=False):
            log.debug("auto_tick: пропуск — предыдущий прогон ещё выполняется")
            return
        try:
            with app.app_context():
                try:
                    with db_session() as s:
                        balance = app.extensions.get("balance_service")
                        world = WorldService(
                            world_seed=app.config["SERVER_SALT"], balance=balance
                        )
                        result = world.process_next_tick(s)
                        s.commit()
                    app.extensions["auto_tick_last_tick"] = int(
                        result.get("current_tick", 0)
                    )
                    app.extensions["auto_tick_last_run_at"] = datetime.now(
                        timezone.utc
                    ).isoformat()
                    app.extensions.pop("auto_tick_error", None)
                    log.info(
                        "auto_tick: сол %s",
                        app.extensions.get("auto_tick_last_tick"),
                    )
                except Exception as e:
                    log.exception("auto_tick: ошибка")
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

    # IntervalTrigger в APScheduler 3.x ставит первый запуск через полный интервал после
    # старта планировщика — без немедленного тика админка долго показывает «—», кажется что
    # автосол «не включился».
    _do_tick()


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
