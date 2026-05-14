"""HTTP API: альянсы (фаза 1)."""

from __future__ import annotations

from flask import current_app, jsonify, request

from app.db.engine import db_session
from app.routes.api.blueprint import api_bp
from app.routes.api.common import _current_player_id
from app.services import alliance_service as alliance_svc


@api_bp.post("/alliance/create")
def api_alliance_create():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    payload = request.get_json(silent=True) or {}
    name = payload.get("display_name") or payload.get("name")
    tag = payload.get("tag")
    if not isinstance(name, str) or not isinstance(tag, str):
        return jsonify({"ok": False, "error": "invalid_payload"}), 400
    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        result = alliance_svc.create_alliance(
            s, balance, player_id=player_id, display_name=name, tag=tag
        )
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)


@api_bp.post("/alliance/join")
def api_alliance_join():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    payload = request.get_json(silent=True) or {}
    code = payload.get("join_code") or payload.get("code")
    if not isinstance(code, str):
        return jsonify({"ok": False, "error": "invalid_payload"}), 400
    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        result = alliance_svc.join_alliance_by_code(
            s, balance, player_id=player_id, join_code=code
        )
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)


@api_bp.post("/alliance/leave")
def api_alliance_leave():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    with db_session() as s:
        result = alliance_svc.leave_alliance(s, player_id=player_id)
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)


@api_bp.get("/alliance/me")
def api_alliance_me():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    with db_session() as s:
        return jsonify(alliance_svc.get_my_alliance(s, player_id=player_id))


@api_bp.get("/alliance/influence_at")
def api_alliance_influence_at():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    x = request.args.get("x", type=int)
    y = request.args.get("y", type=int)
    z = request.args.get("z", default=0, type=int)
    if not isinstance(x, int) or not isinstance(y, int) or not isinstance(z, int):
        return jsonify({"ok": False, "error": "invalid_params"}), 400
    z = max(-10, min(z, 10))
    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        result = alliance_svc.alliance_influence_at_cell(
            s, balance, player_id=player_id, x=x, y=y, z=z
        )
        if not result.get("ok"):
            code = 400
            if result.get("error") == "not_in_alliance":
                code = 403
            return jsonify(result), code
        return jsonify(result)
