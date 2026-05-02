"""HTTP API: health, version, auth, supply."""

from __future__ import annotations

from flask import current_app, jsonify, request, session
from sqlalchemy import text

from app.build_info import BUILD_ID, GAME_VERSION
from app.db.engine import db_session, get_engine
from app.routes.api.blueprint import api_bp
from app.routes.api.common import (
    MAP_WINDOW_RADIUS_MAX,
    MAP_WINDOW_RADIUS_MIN,
    _clamp_map_window_radius,
    _current_player_id,
)
from app.services.auth_service import AuthService
from app.services.world_service import WorldService

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
    if bool(getattr(player, "account_disabled", False)):
        return jsonify({"error": "account_disabled"}), 403

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

