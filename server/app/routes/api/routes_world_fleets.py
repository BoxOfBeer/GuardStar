"""HTTP API: сектор, окно мира, тик, юниты, скаут, флот до cancel_order."""

from __future__ import annotations

import uuid

from flask import current_app, jsonify, request
from sqlalchemy import select

from app.build_info import BUILD_ID
from app.db.engine import db_session
from app.db.models.player import Player
from app.db.models.world_state import WorldState
from app.routes.api.blueprint import api_bp
from app.routes.api.common import (
    MAP_WINDOW_RADIUS_MAX,
    MAP_WINDOW_RADIUS_MIN,
    _clamp_map_window_radius,
    _current_player_id,
)
from app.services.auto_tick import start_auto_tick, stop_auto_tick
from app.services.world_service import WorldService


@api_bp.get("/world/sector")
def api_world_sector():
    x = request.args.get("x", type=int)
    y = request.args.get("y", type=int)
    z = request.args.get("z", default=0, type=int)
    z = max(-10, min(z, 10))
    player_id = _current_player_id()

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        return jsonify(world.get_sector_stub(s, x=x, y=y, z=z, player_id=player_id))


@api_bp.post("/discovery/resolve")
def api_discovery_resolve():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    payload = request.get_json(silent=True) or {}
    x = payload.get("x")
    y = payload.get("y")
    z = payload.get("z", 0)
    if not isinstance(x, int) or not isinstance(y, int) or not isinstance(z, int):
        return jsonify({"ok": False, "error": "invalid_payload"}), 400
    z = max(-10, min(z, 10))

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        result = world.resolve_discovery_at_cell(s, player_id=player_id, x=x, y=y, z=z)
        if not result.get("ok"):
            code = 400
            if result.get("error") == "sector_not_visible":
                code = 403
            return jsonify(result), code
        s.commit()
        return jsonify(result)


@api_bp.get("/world/window")
def api_world_window():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    radius = request.args.get("radius", default=MAP_WINDOW_RADIUS_MIN, type=int)
    radius = _clamp_map_window_radius(radius)
    z = request.args.get("z", default=0, type=int)
    z = max(-10, min(z, 10))
    center_x = request.args.get("center_x", default=None, type=int)
    center_y = request.args.get("center_y", default=None, type=int)

    reveal_raw = request.args.get("reveal_fog", default=0, type=int)
    reveal = bool(reveal_raw)
    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        if reveal:
            pl = s.execute(
                select(Player).where(Player.id == uuid.UUID(player_id))
            ).scalar_one_or_none()
            if not pl or not bool(getattr(pl, "is_game_admin", False)):
                reveal = False
        return jsonify(
            world.get_player_map_window(
                s,
                player_id=player_id,
                radius=radius,
                z=z,
                center_x=center_x,
                center_y=center_y,
                reveal_fog=reveal,
            )
        )


@api_bp.post("/world/tick")
def api_world_tick():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        result = world.process_next_tick(s)
        s.commit()
        return jsonify({"ok": True, **result})


@api_bp.get("/units/status")
def api_units_status():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        return jsonify(world.get_units_status(s, player_id=player_id))


@api_bp.get("/world/state")
def api_world_state():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        ws = s.get(WorldState, 1) or world.get_or_create_world_state(s)
        state = world.get_world_state(
            s,
            player_id=player_id,
            auto_tick_enabled=bool(ws.auto_tick_enabled),
            auto_tick_interval_seconds=float(ws.auto_tick_interval_seconds),
        )
        if current_app.extensions.get("balance_error"):
            state["balance_error"] = current_app.extensions.get("balance_error")
        if current_app.extensions.get("auto_tick_error"):
            state["auto_tick_error"] = current_app.extensions.get("auto_tick_error")
        state["auto_tick_running"] = bool(
            current_app.extensions.get("auto_tick_scheduler")
        )
        state["auto_tick_last_run_at"] = current_app.extensions.get(
            "auto_tick_last_run_at"
        )
        state["auto_tick_last_tick"] = current_app.extensions.get("auto_tick_last_tick")
        state["build_id"] = BUILD_ID
        s.commit()
        return jsonify(state)


@api_bp.post("/world/autotick")
def api_world_autotick():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    payload = request.get_json(silent=True) or {}
    enabled = payload.get("enabled")
    interval = payload.get("interval_seconds")
    if not isinstance(enabled, bool):
        return jsonify({"error": "invalid_payload"}), 400
    if interval is not None and not isinstance(interval, (int, float)):
        return jsonify({"error": "invalid_payload"}), 400
    if interval is not None:
        interval = float(interval)
        if interval < 1 or interval > 60:
            return jsonify({"error": "interval_out_of_range", "min": 1, "max": 60}), 400

    # Персистентно сохраняем настройки в WorldState (id=1).
    with db_session() as s:
        world = WorldService(world_seed=current_app.config["SERVER_SALT"])
        ws = s.get(WorldState, 1) or world.get_or_create_world_state(s)
        ws.auto_tick_enabled = bool(enabled)
        if interval is not None:
            ws.auto_tick_interval_seconds = float(interval)
        s.commit()

        # Дублируем в config для совместимости с текущим кодом автотика.
        current_app.config["AUTO_TICK_ENABLED"] = bool(ws.auto_tick_enabled)
        current_app.config["AUTO_TICK_INTERVAL_SECONDS"] = float(
            ws.auto_tick_interval_seconds
        )

    # reset last error on user action
    current_app.extensions.pop("auto_tick_error", None)

    try:
        app_obj = current_app._get_current_object()
        # Чтобы новый интервал применился без рестарта — перезапускаем scheduler.
        stop_auto_tick(app_obj)
        if bool(current_app.config.get("AUTO_TICK_ENABLED")):
            start_auto_tick(app_obj)
    except Exception as e:
        current_app.extensions["auto_tick_error"] = repr(e)
        return jsonify(
            {"ok": False, "error": "autotick_toggle_failed", "detail": repr(e)}
        ), 500

    return jsonify(
        {
            "ok": True,
            "auto_tick_enabled": bool(current_app.config.get("AUTO_TICK_ENABLED")),
            "auto_tick_interval_seconds": float(
                current_app.config.get("AUTO_TICK_INTERVAL_SECONDS", 5)
            ),
        }
    )


@api_bp.post("/units/move_scout")
def api_move_scout():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    payload = request.get_json(silent=True) or {}
    x = payload.get("x")
    y = payload.get("y")
    z = payload.get("z", 0)
    if not isinstance(x, int) or not isinstance(y, int) or not isinstance(z, int):
        return jsonify({"error": "invalid_coords"}), 400

    z = max(-10, min(z, 10))

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        result = world.create_scout_move_order(
            s, player_id=player_id, target_x=x, target_y=y, target_z=z
        )
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify({"ok": True, "status": "queued", **result})


@api_bp.post("/fleets/move")
def api_fleet_move():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    payload = request.get_json(silent=True) or {}
    fleet_id = payload.get("fleet_id")
    x = payload.get("x")
    y = payload.get("y")
    z = payload.get("z", 0)
    if (
        not isinstance(fleet_id, str)
        or not isinstance(x, int)
        or not isinstance(y, int)
        or not isinstance(z, int)
    ):
        return jsonify({"error": "invalid_payload"}), 400

    z = max(-10, min(z, 10))
    force_attack = bool(payload.get("force_attack"))

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        result = world.create_fleet_move_order(
            s,
            player_id=player_id,
            fleet_id=fleet_id,
            target_x=x,
            target_y=y,
            target_z=z,
            force_attack=force_attack,
        )
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify({"ok": True, "status": "queued", **result})


@api_bp.post("/fleets/cancel_order")
def api_fleet_cancel_order():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    payload = request.get_json(silent=True) or {}
    fleet_id = payload.get("fleet_id")
    if not isinstance(fleet_id, str):
        return jsonify({"error": "invalid_payload"}), 400

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        result = world.cancel_fleet_order(s, player_id=player_id, fleet_id=fleet_id)
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)


def _require_game_admin(s, *, player_id: str) -> bool:
    pl = s.get(Player, uuid.UUID(player_id))
    return bool(pl and getattr(pl, "is_game_admin", False))


@api_bp.post("/world/admin/dev/purge_bandits")
def api_world_admin_dev_purge_bandits():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    with db_session() as s:
        if not _require_game_admin(s, player_id=player_id):
            return jsonify({"error": "forbidden"}), 403
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        body = world.admin_dev_purge_bandit_world(s)
        s.commit()
    return jsonify(body)


@api_bp.post("/world/admin/dev/fleet_spawn_lock")
def api_world_admin_dev_fleet_spawn_lock():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    payload = request.get_json(silent=True) or {}
    if "enabled" not in payload or not isinstance(payload.get("enabled"), bool):
        return jsonify({"error": "invalid_payload", "need": {"enabled": True}}), 400
    enabled = bool(payload["enabled"])
    with db_session() as s:
        if not _require_game_admin(s, player_id=player_id):
            return jsonify({"error": "forbidden"}), 403
        ws = s.get(WorldState, 1)
        if not ws:
            return jsonify({"error": "no_world_state"}), 500
        ws.test_block_new_fleets = enabled
        s.commit()
    return jsonify({"ok": True, "test_block_new_fleets": enabled})


