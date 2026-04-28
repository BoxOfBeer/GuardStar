from flask import Blueprint, jsonify, request, session, current_app

from app.db.engine import db_session
from app.services.auth_service import AuthService
from app.services.world_service import WorldService

api_bp = Blueprint("api", __name__)


def _current_player_id() -> str | None:
    pid = session.get("player_id")
    return str(pid) if pid else None


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
    # Заглушка под будущую «шахматку». Пока возвращаем только то, что принадлежит игроку
    # или пустой сектор.
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

    with db_session() as s:
        world = WorldService(world_seed=current_app.config["SERVER_SALT"])
        return jsonify(world.get_player_map_window(s, player_id=player_id, radius=radius, z=z))


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
        result = world.move_one_scout_from_home(s, player_id=player_id, target_x=x, target_y=y, target_z=z)
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify({"ok": True})

