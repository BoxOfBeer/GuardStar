from flask import Blueprint, current_app, jsonify, request, session
from sqlalchemy import func, select, text

from app.build_info import BUILD_ID, GAME_VERSION
from app.db.engine import db_session, get_engine
from app.services.auth_service import AuthService
from app.services.player_research_effects import (
    adjusted_research_duration_ticks,
    consume_field_data,
    consume_blueprint_cache,
    count_field_data,
    get_research_time_multiplier,
    list_active_player_effects,
)
from app.services.world_service import WorldService
from app.services.feedback_playtest_audit import register_playtest_audit_hooks
from app.services.auto_tick import start_auto_tick, stop_auto_tick
from app.db.models.world_state import WorldState
from app.db.models.player_tech import PlayerTech
from app.db.models.player import Player

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
    balance = current_app.extensions.get("balance_service")
    return jsonify(
        {
            "app": "guardstar",
            "game_version": GAME_VERSION,
            "balance_schema_version": balance.balance_schema_version()
            if balance
            else None,
            "balance_pack_id": balance.balance_pack_id() if balance else None,
            "balance_pack_name": balance.balance_pack_name() if balance else None,
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
    race_id = (payload.get("race_id") or "").strip() or "human"

    auth = AuthService(server_salt=current_app.config["SERVER_SALT"])
    balance = current_app.extensions.get("balance_service")
    world = WorldService(balance=balance)
    if balance:
        try:
            r = balance.get_race(race_id)
        except Exception:
            r = None
        if not isinstance(r, dict) or r.get("enabled") is False:
            return jsonify({"error": "invalid_race_id"}), 400

    with db_session() as s:
        player, access_code = auth.register_player(
            s, display_name=display_name, race_id=race_id
        )
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
        balance = current_app.extensions.get("balance_service")
        world = WorldService(balance=balance)
        data = world.get_player_overview(s, player_id=player_id)

    return jsonify(data)


@api_bp.get("/supply/state")
def api_supply_state():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    x = request.args.get("x", type=int)
    y = request.args.get("y", type=int)
    z = request.args.get("z", default=0, type=int)
    z = max(-10, min(z, 10))
    if not isinstance(x, int) or not isinstance(y, int):
        return jsonify({"error": "invalid_params"}), 400
    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        return jsonify(world.get_supply_state(s, player_id=player_id, x=x, y=y, z=z))


@api_bp.post("/supply/hire_supplier")
def api_hire_supplier():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    payload = request.get_json(silent=True) or {}
    planet_id = payload.get("planet_id")
    if planet_id is not None and not isinstance(planet_id, str):
        return jsonify({"error": "invalid_payload"}), 400
    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        result = world.hire_supplier(s, player_id=player_id, planet_id=planet_id)
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)


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

    radius = request.args.get("radius", default=4, type=int)
    radius = max(1, min(radius, 10))
    z = request.args.get("z", default=0, type=int)
    z = max(-10, min(z, 10))
    center_x = request.args.get("center_x", default=None, type=int)
    center_y = request.args.get("center_y", default=None, type=int)

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        return jsonify(
            world.get_player_map_window(
                s,
                player_id=player_id,
                radius=radius,
                z=z,
                center_x=center_x,
                center_y=center_y,
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
        window = world.get_player_map_window(
            s,
            player_id=player_id,
            radius=radius,
            z=z,
            center_x=center_x,
            center_y=center_y,
        )
        # buildings уже включены в объекты карты; отдаём только их, чтобы не тащить всю карту.
        buildings = []
        for row in window.get("cells", []):
            for cell in row.get("row", []):
                for o in cell.get("objects") or []:
                    if o.get("type") == "building":
                        buildings.append(
                            {"x": cell["x"], "y": cell["y"], "z": cell["z"], **o}
                        )
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
    fleet_id = payload.get("fleet_id")
    if (
        not isinstance(x, int)
        or not isinstance(y, int)
        or not isinstance(z, int)
        or not isinstance(building_type, str)
        or (fleet_id is not None and not isinstance(fleet_id, str))
    ):
        return jsonify({"error": "invalid_payload"}), 400

    z = max(-10, min(z, 10))
    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        result = world.place_building(
            s,
            player_id=player_id,
            x=x,
            y=y,
            z=z,
            building_type=building_type,
            fleet_id=fleet_id,
        )
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)


@api_bp.post("/buildings/placement_checks")
def api_buildings_placement_checks():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    payload = request.get_json(silent=True) or {}
    x = payload.get("x")
    y = payload.get("y")
    z = payload.get("z", 0)
    fleet_id = payload.get("fleet_id")
    building_types = payload.get("building_types") or []

    if (
        not isinstance(x, int)
        or not isinstance(y, int)
        or not isinstance(z, int)
        or (fleet_id is not None and not isinstance(fleet_id, str))
        or not isinstance(building_types, list)
        or not all(isinstance(t, str) for t in building_types)
    ):
        return jsonify({"error": "invalid_payload"}), 400

    building_types = [
        t.strip().lower() for t in building_types if isinstance(t, str) and t.strip()
    ]
    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        results: dict[str, dict] = {}
        for bt in building_types:
            results[bt] = world.check_building_placement(
                s,
                player_id=player_id,
                x=x,
                y=y,
                z=z,
                building_type=bt,
                fleet_id=fleet_id,
            )
        return jsonify({"ok": True, "results": results})


@api_bp.post("/buildings/dismantle")
def api_buildings_dismantle():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    payload = request.get_json(silent=True) or {}
    building_id = payload.get("building_id")
    if not isinstance(building_id, str):
        return jsonify({"error": "invalid_payload"}), 400

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        result = world.dismantle_building(
            s, player_id=player_id, building_id=building_id
        )
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)


@api_bp.post("/buildings/upgrade")
def api_buildings_upgrade():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    payload = request.get_json(silent=True) or {}
    building_id = payload.get("building_id")
    if not isinstance(building_id, str):
        return jsonify({"error": "invalid_payload"}), 400

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        result = world.upgrade_building(s, player_id=player_id, building_id=building_id)
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)


@api_bp.post("/outposts/build")
def api_outposts_build():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    payload = request.get_json(silent=True) or {}
    x = payload.get("x")
    y = payload.get("y")
    z = payload.get("z", 0)
    outpost_type = payload.get("outpost_type")
    fleet_id = payload.get("fleet_id")
    if (
        not isinstance(x, int)
        or not isinstance(y, int)
        or not isinstance(z, int)
        or not isinstance(outpost_type, str)
        or (fleet_id is not None and not isinstance(fleet_id, str))
    ):
        return jsonify({"error": "invalid_payload"}), 400
    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        result = world.build_outpost(
            s,
            player_id=player_id,
            x=x,
            y=y,
            z=z,
            outpost_type=outpost_type,
            fleet_id=fleet_id,
        )
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)


@api_bp.post("/outposts/upgrade")
def api_outposts_upgrade():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    payload = request.get_json(silent=True) or {}
    outpost_id = payload.get("outpost_id")
    if not isinstance(outpost_id, str):
        return jsonify({"error": "invalid_payload"}), 400
    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        result = world.upgrade_outpost(s, player_id=player_id, outpost_id=outpost_id)
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)


@api_bp.post("/outposts/modules/install")
def api_outpost_modules_install():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    payload = request.get_json(silent=True) or {}
    outpost_id = payload.get("outpost_id")
    module_type = payload.get("module_type")
    if not isinstance(outpost_id, str) or not isinstance(module_type, str):
        return jsonify({"error": "invalid_payload"}), 400
    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        result = world.install_outpost_module(
            s, player_id=player_id, outpost_id=outpost_id, module_type=module_type
        )
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)


@api_bp.post("/outposts/modules/upgrade")
def api_outpost_modules_upgrade():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    payload = request.get_json(silent=True) or {}
    module_id = payload.get("module_id")
    if not isinstance(module_id, str):
        return jsonify({"error": "invalid_payload"}), 400
    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        result = world.upgrade_outpost_module(
            s, player_id=player_id, module_id=module_id
        )
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)


@api_bp.post("/fleets/create")
def api_fleets_create():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    payload = request.get_json(silent=True) or {}
    planet_id = payload.get("planet_id")
    name = payload.get("name")
    composition = payload.get("composition")
    if not isinstance(planet_id, str) or not isinstance(composition, dict):
        return jsonify({"error": "invalid_payload"}), 400

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        result = world.create_fleet(
            s,
            player_id=player_id,
            planet_id=planet_id,
            name=name if isinstance(name, str) else None,
            composition=composition,
        )
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)


@api_bp.post("/fleets/rename")
def api_fleets_rename():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    payload = request.get_json(silent=True) or {}
    fleet_id = payload.get("fleet_id")
    name = payload.get("name")
    if not isinstance(fleet_id, str) or not isinstance(name, str):
        return jsonify({"error": "invalid_payload"}), 400

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        result = world.rename_fleet(
            s, player_id=player_id, fleet_id=fleet_id, name=name
        )
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)


@api_bp.post("/fleets/adjust")
def api_fleets_adjust():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    payload = request.get_json(silent=True) or {}
    fleet_id = payload.get("fleet_id")
    deltas = payload.get("deltas")
    if not isinstance(fleet_id, str) or not isinstance(deltas, dict):
        return jsonify({"error": "invalid_payload"}), 400

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        result = world.adjust_fleet_composition(
            s, player_id=player_id, fleet_id=fleet_id, deltas=deltas
        )
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)


@api_bp.post("/fleets/save")
def api_fleets_save():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    payload = request.get_json(silent=True) or {}
    fleet_id = payload.get("fleet_id")
    if not isinstance(fleet_id, str):
        return jsonify({"error": "invalid_payload"}), 400
    if "name" not in payload and "composition" not in payload:
        return jsonify(
            {"error": "invalid_payload", "detail": "need_name_or_composition"}
        ), 400

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        kwargs: dict = {"player_id": player_id, "fleet_id": fleet_id}
        if "name" in payload:
            kwargs["name"] = payload.get("name")
        if "composition" in payload:
            kwargs["composition"] = payload.get("composition")
        result = world.save_fleet(s, **kwargs)
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)


@api_bp.post("/fleets/disband")
def api_fleets_disband():
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
        result = world.disband_fleet(s, player_id=player_id, fleet_id=fleet_id)
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)


@api_bp.post("/fleets/merge")
def api_fleets_merge():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    payload = request.get_json(silent=True) or {}
    target_fleet_id = payload.get("target_fleet_id")
    source_fleet_id = payload.get("source_fleet_id")
    if not isinstance(target_fleet_id, str) or not isinstance(source_fleet_id, str):
        return jsonify({"error": "invalid_payload"}), 400

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        result = world.merge_fleets(
            s,
            player_id=player_id,
            target_fleet_id=target_fleet_id,
            source_fleet_id=source_fleet_id,
        )
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)


@api_bp.post("/fleets/split")
def api_fleets_split():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    payload = request.get_json(silent=True) or {}
    fleet_id = payload.get("fleet_id")
    take = payload.get("take")
    if not isinstance(fleet_id, str) or not isinstance(take, dict):
        return jsonify({"error": "invalid_payload"}), 400

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        result = world.split_fleet(s, player_id=player_id, fleet_id=fleet_id, take=take)
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)


@api_bp.post("/fleets/combat_preview")
def api_fleets_combat_preview():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    payload = request.get_json(silent=True) or {}
    fleet_id = payload.get("fleet_id")
    tx = payload.get("target_x")
    ty = payload.get("target_y")
    tz = payload.get("target_z", 0)
    if (
        not isinstance(fleet_id, str)
        or not isinstance(tx, int)
        or not isinstance(ty, int)
        or not isinstance(tz, int)
    ):
        return jsonify({"error": "invalid_payload"}), 400

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        result = world.combat_preview_for_move(
            s,
            player_id=player_id,
            fleet_id=fleet_id,
            target_x=tx,
            target_y=ty,
            target_z=tz,
        )
        if not result.get("ok"):
            return jsonify(result), 400
        return jsonify(result)


@api_bp.post("/fleets/combat_prompt_resolve")
def api_fleets_combat_prompt_resolve():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    payload = request.get_json(silent=True) or {}
    order_id = payload.get("order_id")
    attack = payload.get("attack")
    if not isinstance(order_id, str) or not isinstance(attack, bool):
        return jsonify({"error": "invalid_payload"}), 400

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        result = world.resolve_fleet_combat_prompt(
            s, player_id=player_id, order_id=order_id, attack=attack
        )
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
    balance = current_app.extensions.get("balance_service")
    pack = balance.pack if balance else None
    if not pack:
        return jsonify(
            {
                "ok": False,
                "error": "balance_not_loaded",
                "detail": current_app.extensions.get("balance_error"),
            }
        ), 500
    return jsonify(
        {
            "ok": True,
            "meta": pack.meta,
            "resources": pack.resources,
            "economy": pack.economy,
            "aliases": pack.aliases,
            "races": list(pack.races_by_id.values()),
            "units": list(pack.units_by_id.values()),
            "buildings": list(pack.buildings_by_id.values()),
            "tech": list(pack.tech_by_id.values()),
        }
    )


@api_bp.get("/tech/state")
def api_tech_state():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    pid = __import__("uuid").UUID(player_id)

    with db_session() as s:
        rows = (
            s.execute(
                select(PlayerTech)
                .where(PlayerTech.player_id == pid)
                .order_by(PlayerTech.created_at.desc())
            )
            .scalars()
            .all()
        )
        ws = s.get(WorldState, 1)
        current_tick = int(ws.current_tick) if ws else 0
        pl = s.get(Player, pid)
        rp_bal = float(getattr(pl, "research_points", 0) or 0) if pl else 0.0
        payload = []
        for r in rows:
            remaining = None
            if r.status == "in_progress":
                remaining = max(0, int(r.finish_tick - current_tick))
            payload.append(
                {
                    "tech_id": r.tech_id,
                    "status": r.status,
                    "started_tick": int(r.started_tick),
                    "started_sol": int(r.started_tick),
                    "finish_tick": int(r.finish_tick),
                    "finish_sol": int(r.finish_tick),
                    "remaining_ticks": remaining,
                    "remaining_sols": remaining,
                }
            )
        return jsonify(
            {
                "ok": True,
                "current_tick": current_tick,
                "current_sol": current_tick,
                "research_points": round(rp_bal, 4),
                "techs": payload,
            }
        )


@api_bp.get("/effects/active")
def api_effects_active():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    pid = __import__("uuid").UUID(player_id)

    with db_session() as s:
        ws = s.get(WorldState, 1)
        current_tick = int(ws.current_tick) if ws else 0
        effects = list_active_player_effects(s, player_id=pid, tick=current_tick)
        return jsonify({"ok": True, "current_tick": current_tick, "effects": effects})


@api_bp.get("/economy/summary")
def api_economy_summary():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    include_external = request.args.get(
        "include_external_buildings", default=1, type=int
    )
    include_external = 1 if int(include_external or 0) != 0 else 0

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        result = world.get_economy_summary(
            s, player_id=player_id, include_external_buildings=bool(include_external)
        )
        return jsonify(result)


@api_bp.post("/tech/start")
def api_tech_start():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    payload = request.get_json(silent=True) or {}
    tech_id = payload.get("tech_id")
    if not isinstance(tech_id, str) or not tech_id.strip():
        return jsonify({"error": "invalid_payload"}), 400
    tech_id = tech_id.strip()

    balance = current_app.extensions.get("balance_service")
    if not balance:
        return jsonify(
            {
                "ok": False,
                "error": "balance_not_loaded",
                "detail": current_app.extensions.get("balance_error"),
            }
        ), 500

    # validate tech exists and enabled + prereq
    try:
        tech = balance.pack.tech_by_id.get(tech_id)
    except Exception:
        tech = None
    if not isinstance(tech, dict):
        return jsonify({"ok": False, "error": "unknown_tech"}), 400
    if tech.get("enabled") is False:
        return jsonify({"ok": False, "error": "tech_disabled"}), 400

    pid = __import__("uuid").UUID(player_id)
    with db_session() as s:
        ws = s.get(WorldState, 1) or WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        ).get_or_create_world_state(s)
        now = int(ws.current_tick)

        # Research slots: MVP = 1 активное исследование одновременно.
        # В будущем можно расширять слотами от техов/построек/расы.
        active_slots_total = 1
        active_now = int(
            s.execute(
                select(func.count(PlayerTech.id)).where(
                    PlayerTech.player_id == pid, PlayerTech.status == "in_progress"
                )
            ).scalar()
            or 0
        )
        if active_now >= active_slots_total:
            return jsonify(
                {
                    "ok": False,
                    "error": "tech_queue_full",
                    "active": active_now,
                    "slots": active_slots_total,
                }
            ), 400

        existing = (
            s.execute(
                select(PlayerTech).where(
                    PlayerTech.player_id == pid, PlayerTech.tech_id == tech_id
                )
            )
            .scalars()
            .first()
        )
        if existing and existing.status in ("in_progress", "done"):
            return jsonify({"ok": False, "error": "tech_already_started"}), 400

        # prereq: must be done
        prereq = tech.get("prereq") or []
        if not isinstance(prereq, list):
            return jsonify({"ok": False, "error": "tech_bad_prereq"}), 400
        if prereq:
            done = set(
                s.execute(
                    select(PlayerTech.tech_id).where(
                        PlayerTech.player_id == pid, PlayerTech.status == "done"
                    )
                )
                .scalars()
                .all()
            )
            missing = [p for p in prereq if p not in done]
            if missing:
                return jsonify(
                    {"ok": False, "error": "tech_prereq_missing", "missing": missing}
                ), 400

        req_fd = tech.get("field_data_requirements")
        if req_fd is None:
            req_fd = []
        if not isinstance(req_fd, list):
            return jsonify(
                {"ok": False, "error": "tech_bad_field_data_requirements"}
            ), 400
        req_fd = [str(x) for x in req_fd if isinstance(x, str) and x.strip()]
        if req_fd:
            missing_fd = []
            for k in req_fd:
                if count_field_data(s, player_id=pid, tick=now, kind=k) < 1:
                    missing_fd.append(k)
            if missing_fd:
                return jsonify(
                    {
                        "ok": False,
                        "error": "tech_field_data_missing",
                        "missing": missing_fd,
                    }
                ), 400

        time_ticks = int(tech.get("time_ticks", 0))
        time_ticks = max(1, time_ticks)
        residual = int(tech.get("residual_time_ticks", 0) or 0)
        if residual <= 0:
            residual = max(3, min(time_ticks, int(round(time_ticks * 0.45)) or 3))
        residual = max(1, residual)

        rp_need = float(tech.get("research_points_cost", 0) or 0)
        if rp_need < 0:
            rp_need = 0.0
        player_row = s.get(Player, pid)
        if not player_row:
            return jsonify({"ok": False, "error": "player_not_found"}), 400
        cur_rp = float(getattr(player_row, "research_points", 0) or 0)
        if rp_need > 1e-9:
            if cur_rp + 1e-9 < rp_need:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": "not_enough_research_points",
                            "need": rp_need,
                            "have": cur_rp,
                        }
                    ),
                    400,
                )
            player_row.research_points = cur_rp - rp_need

        world_svc = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        time_mult = get_research_time_multiplier(s, player_id=pid, tick=now)
        adj_ticks = adjusted_research_duration_ticks(
            base_ticks=residual, time_multiplier=time_mult
        )
        blueprint_discount = consume_blueprint_cache(s, player_id=pid, tick=now)
        consumed_fd: list[str] = []
        for k in req_fd:
            if consume_field_data(s, player_id=pid, tick=now, kind=k, qty=1):
                consumed_fd.append(k)

        if time_mult < 0.9999:
            world_svc._emit_event(
                s,
                tick=now,
                type="tech_start_research_boost",
                message=f"Ускорение исследования (×{time_mult:g}) применено к «{tech_id}».",
                payload={
                    "tech_id": tech_id,
                    "time_multiplier": time_mult,
                    "legacy_time_ticks_ref": time_ticks,
                    "residual_ticks_base": residual,
                    "adjusted_ticks": adj_ticks,
                },
                player_id=pid,
            )
        if blueprint_discount:
            world_svc._emit_event(
                s,
                tick=now,
                type="tech_start_blueprint_cache",
                message="Кэш чертежей применён к стоимости исследования (скидка по металлу/кристаллам).",
                payload={"tech_id": tech_id, "discount": blueprint_discount},
                player_id=pid,
            )

        row = PlayerTech(
            player_id=pid,
            tech_id=tech_id,
            status="in_progress",
            started_tick=now + 1,
            finish_tick=now + adj_ticks,
        )
        s.add(row)
        s.commit()
        return jsonify(
            {
                "ok": True,
                "tech_id": tech_id,
                "status": row.status,
                "started_tick": row.started_tick,
                "started_sol": int(row.started_tick),
                "finish_tick": row.finish_tick,
                "finish_sol": int(row.finish_tick),
                "research_time_multiplier": time_mult,
                "research_ticks_base": time_ticks,
                "residual_time_ticks": residual,
                "research_ticks_adjusted": adj_ticks,
                "research_points_spent": rp_need,
                "research_points_after": float(
                    getattr(player_row, "research_points", 0) or 0
                ),
                "blueprint_cache_consumed": bool(blueprint_discount),
                "blueprint_discount": blueprint_discount,
                "field_data_required": req_fd,
                "field_data_consumed": consumed_fd,
            }
        )


register_playtest_audit_hooks(api_bp)
