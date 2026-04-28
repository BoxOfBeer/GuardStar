from flask import Blueprint, current_app, jsonify, request, session
from sqlalchemy import text

from app.build_info import BUILD_ID
from app.db.engine import db_session, get_engine
from app.services.auth_service import AuthService
from app.services.world_service import WorldService
from app.services.auto_tick import start_auto_tick, stop_auto_tick
from app.db.models.world_state import WorldState

api_bp = Blueprint("api", __name__)


def _current_player_id() -> str | None:
    pid = session.get("player_id")
    return str(pid) if pid else None


@api_bp.get("/health")
def api_health():
    return jsonify({"status": "ok", "app": "GuardStar", "build_id": BUILD_ID})


@api_bp.get("/ready")
def api_ready():
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return jsonify({"status": "ready"})
    except Exception:
        return jsonify({"status": "not_ready", "error": "db_unavailable"}), 503


@api_bp.get("/version")
def api_version():
    return jsonify(
        {
            "app": "guardstar",
            "features": {
                "z_layers": True,
                "procgen": True,
                "move_scout": True,
                "resource_tick": True,
                "manual_world_tick": True,
            },
        }
    )


@api_bp.post("/register")
def api_register():
    payload = request.get_json(silent=True) or {}
    display_name = (payload.get("display_name") or "").strip()
    if not display_name:
        return jsonify({"error": "display_name_required"}), 400

    auth = AuthService(server_salt=current_app.config["SERVER_SALT"])
    world = WorldService()

    with db_session() as s:
        player, access_code = auth.register_player(s, display_name=display_name)
        world.ensure_player_has_start(s, player_id=player.id)
        s.commit()

    session["player_id"] = str(player.id)
    return jsonify({"player_id": str(player.id), "access_code": access_code})


@api_bp.post("/login")
def api_login():
    payload = request.get_json(silent=True) or {}
    access_code = (payload.get("access_code") or "").strip()
    if not access_code:
        return jsonify({"error": "access_code_required"}), 400

    auth = AuthService(server_salt=current_app.config["SERVER_SALT"])
    with db_session() as s:
        player = auth.authenticate_by_code(s, access_code=access_code)

    if not player:
        return jsonify({"error": "invalid_access_code"}), 401

    session["player_id"] = str(player.id)
    return jsonify({"ok": True, "player_id": str(player.id)})


@api_bp.post("/logout")
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@api_bp.get("/me")
def api_me():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    with db_session() as s:
        world = WorldService()
        data = world.get_player_overview(s, player_id=player_id)

    return jsonify(data)


@api_bp.get("/world/sector")
def api_world_sector():
    x = request.args.get("x", type=int)
    y = request.args.get("y", type=int)
    z = request.args.get("z", default=0, type=int)
    z = max(-10, min(z, 10))
    player_id = _current_player_id()

    with db_session() as s:
        world = WorldService(world_seed=current_app.config["SERVER_SALT"])
        return jsonify(world.get_sector_stub(s, x=x, y=y, z=z, player_id=player_id))


@api_bp.get("/world/window")
def api_world_window():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    radius = request.args.get("radius", default=4, type=int)
    radius = max(1, min(radius, 10))
    z = request.args.get("z", default=0, type=int)
    z = max(-10, min(z, 10))
    center_x = request.args.get("center_x", default=None, type=int)
    center_y = request.args.get("center_y", default=None, type=int)

    with db_session() as s:
        world = WorldService(world_seed=current_app.config["SERVER_SALT"])
        return jsonify(world.get_player_map_window(s, player_id=player_id, radius=radius, z=z, center_x=center_x, center_y=center_y))




@api_bp.post("/world/tick")
def api_world_tick():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    with db_session() as s:
        world = WorldService(world_seed=current_app.config["SERVER_SALT"])
        result = world.process_next_tick(s)
        s.commit()
        return jsonify({"ok": True, **result})


@api_bp.get("/units/status")
def api_units_status():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    with db_session() as s:
        world = WorldService(world_seed=current_app.config["SERVER_SALT"])
        return jsonify(world.get_units_status(s, player_id=player_id))


@api_bp.get("/world/state")
def api_world_state():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    with db_session() as s:
        world = WorldService(world_seed=current_app.config["SERVER_SALT"])
        ws = s.get(WorldState, 1) or world.get_or_create_world_state(s)
        state = world.get_world_state(
            s,
            player_id=player_id,
            auto_tick_enabled=bool(ws.auto_tick_enabled),
            auto_tick_interval_seconds=float(ws.auto_tick_interval_seconds),
        )
        if current_app.extensions.get("auto_tick_error"):
            state["auto_tick_error"] = current_app.extensions.get("auto_tick_error")
        state["auto_tick_running"] = bool(current_app.extensions.get("auto_tick_scheduler"))
        state["auto_tick_last_run_at"] = current_app.extensions.get("auto_tick_last_run_at")
        state["auto_tick_last_tick"] = current_app.extensions.get("auto_tick_last_tick")
        state["build_id"] = BUILD_ID
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
        current_app.config["AUTO_TICK_INTERVAL_SECONDS"] = float(ws.auto_tick_interval_seconds)

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
        return jsonify({"ok": False, "error": "autotick_toggle_failed", "detail": repr(e)}), 500

    return jsonify(
        {
            "ok": True,
            "auto_tick_enabled": bool(current_app.config.get("AUTO_TICK_ENABLED")),
            "auto_tick_interval_seconds": float(current_app.config.get("AUTO_TICK_INTERVAL_SECONDS", 5)),
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
        world = WorldService(world_seed=current_app.config["SERVER_SALT"])
        result = world.create_scout_move_order(s, player_id=player_id, target_x=x, target_y=y, target_z=z)
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
    if not isinstance(fleet_id, str) or not isinstance(x, int) or not isinstance(y, int) or not isinstance(z, int):
        return jsonify({"error": "invalid_payload"}), 400

    z = max(-10, min(z, 10))

    with db_session() as s:
        world = WorldService(world_seed=current_app.config["SERVER_SALT"])
        result = world.create_fleet_move_order(
            s, player_id=player_id, fleet_id=fleet_id, target_x=x, target_y=y, target_z=z
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
        world = WorldService(world_seed=current_app.config["SERVER_SALT"])
        result = world.cancel_fleet_order(s, player_id=player_id, fleet_id=fleet_id)
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)


@api_bp.get("/buildings/list")
def api_buildings_list():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    radius = request.args.get("radius", default=4, type=int)
    radius = max(1, min(radius, 10))
    z = request.args.get("z", default=0, type=int)
    z = max(-10, min(z, 10))
    center_x = request.args.get("center_x", default=None, type=int)
    center_y = request.args.get("center_y", default=None, type=int)

    with db_session() as s:
        world = WorldService(world_seed=current_app.config["SERVER_SALT"])
        window = world.get_player_map_window(s, player_id=player_id, radius=radius, z=z, center_x=center_x, center_y=center_y)
        # buildings уже включены в объекты карты; отдаём только их, чтобы не тащить всю карту.
        buildings = []
        for row in window.get("cells", []):
            for cell in row.get("row", []):
                for o in (cell.get("objects") or []):
                    if o.get("type") == "building":
                        buildings.append({"x": cell["x"], "y": cell["y"], "z": cell["z"], **o})
        return jsonify({"ok": True, "buildings": buildings})


@api_bp.post("/buildings/place")
def api_buildings_place():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    payload = request.get_json(silent=True) or {}
    x = payload.get("x")
    y = payload.get("y")
    z = payload.get("z", 0)
    building_type = payload.get("building_type")
    if not isinstance(x, int) or not isinstance(y, int) or not isinstance(z, int) or not isinstance(building_type, str):
        return jsonify({"error": "invalid_payload"}), 400

    z = max(-10, min(z, 10))
    with db_session() as s:
        world = WorldService(world_seed=current_app.config["SERVER_SALT"])
        result = world.place_building(s, player_id=player_id, x=x, y=y, z=z, building_type=building_type)
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)


@api_bp.get("/balance")
def api_balance():
    # Публичное (для залогиненных): показать доступные расы/юниты/постройки/tech (без чувствительных данных).
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    pack = current_app.extensions.get("balance")
    if not pack:
        return jsonify({"ok": False, "error": "balance_not_loaded", "detail": current_app.extensions.get("balance_error")}), 500
    return jsonify(
        {
            "ok": True,
            "meta": pack.meta,
            "resources": pack.resources,
            "races": list(pack.races_by_id.values()),
            "units": list(pack.units_by_id.values()),
            "buildings": list(pack.buildings_by_id.values()),
            "tech": list(pack.tech_by_id.values()),
        }
    )
