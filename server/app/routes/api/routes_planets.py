"""HTTP API: планеты (колонизация и т.п.)."""

from __future__ import annotations

from flask import current_app, jsonify, request

from app.db.engine import db_session
from app.routes.api.blueprint import api_bp
from app.routes.api.common import _current_player_id
from app.services.world_service import WorldService


@api_bp.post("/planets/colonize")
def api_planets_colonize():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    payload = request.get_json(silent=True) or {}
    planet_id = payload.get("planet_id")
    fleet_id = payload.get("fleet_id")
    if not isinstance(planet_id, str) or not isinstance(fleet_id, str):
        return jsonify({"ok": False, "error": "invalid_payload"}), 400

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(world_seed=current_app.config["SERVER_SALT"], balance=balance)
        result = world.colonize_planet(
            s, player_id=player_id, planet_id=planet_id, fleet_id=fleet_id
        )
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
        return jsonify(result)

