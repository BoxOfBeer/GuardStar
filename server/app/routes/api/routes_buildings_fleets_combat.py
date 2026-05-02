"""HTTP API: здания, аутпосты, флоты, бой."""

from __future__ import annotations

from flask import current_app, jsonify, request

from app.db.engine import db_session
from app.routes.api.blueprint import api_bp
from app.routes.api.common import (
    MAP_WINDOW_RADIUS_MAX,
    MAP_WINDOW_RADIUS_MIN,
    _clamp_map_window_radius,
    _current_player_id,
)
from app.services.world_service import WorldService

@api_bp.get("/buildings/list")
def api_buildings_list():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401

    radius = request.args.get("radius", default=MAP_WINDOW_RADIUS_MIN, type=int)
    radius = _clamp_map_window_radius(radius)
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

