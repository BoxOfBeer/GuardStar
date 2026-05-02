"""HTTP API: баланс, tech, economy, эффекты."""

from __future__ import annotations

from flask import current_app, jsonify, request
from sqlalchemy import func, select

from app.db.engine import db_session
from app.db.models.player import Player
from app.db.models.player_tech import PlayerTech
from app.db.models.world_state import WorldState
from app.routes.api.blueprint import api_bp
from app.routes.api.common import _current_player_id
from app.services.player_research_effects import (
    adjusted_research_duration_ticks,
    consume_blueprint_cache,
    consume_field_data,
    count_field_data,
    get_research_time_multiplier,
    list_active_player_effects,
)
from app.services.world_service import WorldService


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
            "outposts": list(pack.outposts_by_id.values()),
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
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        from app.services.economy_service import EconomyService

        rp_per_sol = float(
            EconomyService(world=world)._player_rp_info(s, player_id=pid).per_sol
        )
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
                "research_points_per_sol": round(rp_per_sol, 4),
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


