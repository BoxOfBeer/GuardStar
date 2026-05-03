"""Админ-хаб и POST-эндпоинты админки."""

from __future__ import annotations

import json
import uuid

from flask import abort, current_app, redirect, render_template, request, session, url_for
from sqlalchemy import delete, func, select

from app.build_info import BUILD_ID, GAME_VERSION
from app.db.engine import db_session
from app.services.world_research_runtime import (
    parse_research_overrides_json,
    serialize_research_overrides_from_maps,
)
from app.services.world_service.constants import DEFAULT_MAX_FLEET_UNITS
from app.db.models.admin_config import AdminConfig
from app.db.models.event import Event
from app.db.models.feedback_message import FeedbackMessage
from app.db.models.fleet import Fleet
from app.db.models.planet import Planet
from app.db.models.player import Player
from app.db.models.world_state import WorldState
from app.routes.web.blueprint import web_bp
from app.routes.web.common import (
    _DISCORD_INVITE_URL,
    _FEEDBACK_CATEGORIES,
    _require_login,
)
from app.services.auth_service import AuthService
from app.services.feedback_playtest_audit import invalidate_feedback_audited_cache
from app.services.world_service import WorldService


def _db_connection_label(database_url: str) -> str:
    """Хост и имя БД без пароля — чтобы сверить, та ли это база, где лежат игроки."""
    try:
        from sqlalchemy.engine.url import make_url

        u = make_url(database_url)
        host = u.host or "?"
        if u.port:
            host = f"{host}:{u.port}"
        dbn = u.database or "?"
        return f"{host} · «{dbn}»"
    except Exception:
        return "не удалось разобрать DATABASE_URL"


def _admin_token_raw() -> str:
    return (request.args.get("token") or request.form.get("token") or "").strip()


def _admin_expected_token_hash() -> str:
    with db_session() as s:
        cfg = s.execute(
            select(AdminConfig).where(AdminConfig.id == 1)
        ).scalar_one_or_none()
        return (cfg.admin_token_hash if cfg else "").strip()


def _admin_token_valid(token: str) -> bool:
    t = (token or "").strip()
    expected_hash = _admin_expected_token_hash()
    if not expected_hash or not t:
        return False
    auth = AuthService(server_salt=current_app.config["SERVER_SALT"])
    return auth.hash_access_code(t) == expected_hash


def _require_admin_token() -> str:
    tok = _admin_token_raw()
    if not _admin_token_valid(tok):
        abort(403)
    return tok


@web_bp.get("/admin/world")
def admin_world_legacy_redirect():
    return redirect(
        url_for(
            "web.admin_hub",
            token=(request.args.get("token") or "").strip(),
            tab="world",
        )
    )


@web_bp.get("/admin/accounts")
def admin_accounts_legacy_redirect():
    return redirect(
        url_for(
            "web.admin_hub",
            token=(request.args.get("token") or "").strip(),
            tab="accounts",
        )
    )


@web_bp.get("/admin")
def admin_hub():
    token_in = _admin_token_raw()
    tab = (request.args.get("tab") or "world").strip()
    if tab not in ("world", "npc", "balance", "accounts", "feedback"):
        tab = "world"

    authorized = _admin_token_valid(token_in)
    if not authorized:
        return render_template(
            "admin_hub.html",
            title="GuardStar — админка",
            authorized=False,
            token_field_value=token_in,
            tab=tab,
            bad_token=bool(token_in),
            game_version=GAME_VERSION,
            build_id=BUILD_ID,
        )

    token = token_in

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        ws = world.get_or_create_world_state(s)

        runtime = {
            "auto_tick_running": bool(
                current_app.extensions.get("auto_tick_scheduler")
            ),
            "auto_tick_last_run_at": current_app.extensions.get(
                "auto_tick_last_run_at"
            ),
            "auto_tick_last_tick": current_app.extensions.get("auto_tick_last_tick"),
            "auto_tick_error": current_app.extensions.get("auto_tick_error"),
        }
        spawn_min = max(0, int(getattr(ws, "player_spawn_min_manhattan", 25) or 25))

        planets_n = int(
            s.execute(select(func.count()).select_from(Planet)).scalar_one()
        )

        t_ov, r_ov = parse_research_overrides_json(
            getattr(ws, "admin_research_overrides_json", None)
        )
        research_tiers = []
        for ti in range(1, 7):
            research_tiers.append(
                {
                    "tier": ti,
                    "time": float(t_ov.get(ti, 1.0)),
                    "rp": float(r_ov.get(ti, 1.0)),
                }
            )
        data = {
            "auto_tick_enabled": bool(ws.auto_tick_enabled),
            "auto_tick_interval_seconds": float(ws.auto_tick_interval_seconds),
            "current_tick": int(ws.current_tick),
            "player_spawn_min_manhattan": spawn_min,
            "planets_registered": planets_n,
            "runtime": runtime,
            "api_app": "guardstar",
            "game_version": GAME_VERSION,
            "build_id": BUILD_ID,
            "balance_schema_version": balance.balance_schema_version()
            if balance
            else None,
            "spawn_flags": {
                "test_block_new_fleets": bool(
                    getattr(ws, "test_block_new_fleets", False)
                ),
                "admin_block_player_fleet_create": bool(
                    getattr(ws, "admin_block_player_fleet_create", False)
                ),
                "admin_block_npc_transit": bool(
                    getattr(ws, "admin_block_npc_transit", False)
                ),
                "admin_block_bandit_mines": bool(
                    getattr(ws, "admin_block_bandit_mines", False)
                ),
                "admin_block_bandit_outposts": bool(
                    getattr(ws, "admin_block_bandit_outposts", False)
                ),
                "admin_block_bandit_fleets": bool(
                    getattr(ws, "admin_block_bandit_fleets", False)
                ),
            },
            "admin_max_fleet_units": int(getattr(ws, "admin_max_fleet_units", 0) or 0),
            "default_max_fleet_units": int(DEFAULT_MAX_FLEET_UNITS),
            "research_tiers": research_tiers,
            "admin_economy_overrides_json": getattr(
                ws, "admin_economy_overrides_json", None
            )
            or "",
            "economy_base_food_per_sol": max(
                0,
                min(
                    999,
                    int(getattr(ws, "economy_base_food_per_sol", 10) or 10),
                ),
            ),
            "economy_base_water_per_sol": max(
                0,
                min(
                    999,
                    int(getattr(ws, "economy_base_water_per_sol", 10) or 10),
                ),
            ),
        }

        players = (
            s.execute(select(Player).order_by(Player.created_at.desc())).scalars().all()
        )

        ids = [p.id for p in players]
        planets_by_owner = {}
        fleets_by_owner = {}
        if ids:
            planets_by_owner = dict(
                s.execute(
                    select(Planet.owner_player_id, func.count(Planet.id))
                    .where(Planet.owner_player_id.in_(ids))
                    .group_by(Planet.owner_player_id)
                ).all()
            )
            fleets_by_owner = dict(
                s.execute(
                    select(Fleet.owner_player_id, func.count(Fleet.id))
                    .where(Fleet.owner_player_id.in_(ids))
                    .group_by(Fleet.owner_player_id)
                ).all()
            )

        payload = []
        for p in players:
            payload.append(
                {
                    "id": str(p.id),
                    "display_name": p.display_name,
                    "access_code_hash": p.access_code_hash,
                    "created_at": p.created_at,
                    "last_login_at": p.last_login_at,
                    "planets_count": int(planets_by_owner.get(p.id, 0)),
                    "fleets_count": int(fleets_by_owner.get(p.id, 0)),
                    "feedback_audited": bool(getattr(p, "feedback_audited", False)),
                    "staff_chat_exempt": bool(getattr(p, "staff_chat_exempt", False)),
                    "is_game_admin": bool(getattr(p, "is_game_admin", False)),
                    "is_game_moderator": bool(getattr(p, "is_game_moderator", False)),
                    "account_disabled": bool(getattr(p, "account_disabled", False)),
                }
            )

        feedback_messages = (
            s.execute(
                select(FeedbackMessage)
                .order_by(FeedbackMessage.created_at.desc())
                .limit(400)
            )
            .scalars()
            .all()
        )

    return render_template(
        "admin_hub.html",
        title="GuardStar — админка",
        authorized=True,
        token=token,
        tab=tab,
        players=payload,
        data=data,
        feedback_messages=feedback_messages,
        discord_url=_DISCORD_INVITE_URL,
        economy_json_error=(request.args.get("economy_json_error") or "").strip() == "1",
        db_connection_label=_db_connection_label(
            str(current_app.config.get("DATABASE_URL") or "")
        ),
    )


@web_bp.post("/admin/world/autotick")
def admin_world_autotick():
    token = _require_admin_token()
    enabled = (request.form.get("enabled") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    interval_raw = (request.form.get("interval_seconds") or "").strip()
    interval = None
    if interval_raw:
        try:
            interval = float(interval_raw)
        except Exception:
            interval = None

    # Переиспользуем API-логику: дёрнем внутренний endpoint через прямой вызов сервиса.
    from app.services.auto_tick import start_auto_tick, stop_auto_tick

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        ws = world.get_or_create_world_state(s)
        ws.auto_tick_enabled = bool(enabled)
        if interval is not None:
            ws.auto_tick_interval_seconds = float(max(1.0, min(interval, 60.0)))
        s.commit()

        current_app.config["AUTO_TICK_ENABLED"] = bool(ws.auto_tick_enabled)
        current_app.config["AUTO_TICK_INTERVAL_SECONDS"] = float(
            ws.auto_tick_interval_seconds
        )

    current_app.extensions.pop("auto_tick_error", None)
    try:
        app_obj = current_app._get_current_object()
        stop_auto_tick(app_obj)
        if bool(current_app.config.get("AUTO_TICK_ENABLED")):
            start_auto_tick(app_obj)
    except Exception as e:
        current_app.extensions["auto_tick_error"] = repr(e)

    return redirect(url_for("web.admin_hub", token=token, tab="world"))


@web_bp.post("/admin/world/spawn")
def admin_world_spawn_settings():
    token = _require_admin_token()
    raw = (request.form.get("player_spawn_min_manhattan") or "").strip()
    try:
        v = int(raw)
    except ValueError:
        v = 25
    # 0 = без требования к дистанции (локальные тесты); верхний предохранитель против опечаток.
    v = max(0, min(v, 500))

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        ws = world.get_or_create_world_state(s)
        ws.player_spawn_min_manhattan = int(v)
        s.commit()

    return redirect(url_for("web.admin_hub", token=token, tab="world"))


def _admin_checkbox_on(name: str) -> bool:
    v = (request.form.get(name) or "").strip().lower()
    return v in ("1", "true", "yes", "on")


@web_bp.post("/admin/world/spawn-flags")
def admin_world_spawn_flags():
    token = _require_admin_token()
    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        ws = world.get_or_create_world_state(s)
        ws.test_block_new_fleets = _admin_checkbox_on("test_block_new_fleets")
        ws.admin_block_player_fleet_create = _admin_checkbox_on(
            "admin_block_player_fleet_create"
        )
        ws.admin_block_npc_transit = _admin_checkbox_on("admin_block_npc_transit")
        ws.admin_block_bandit_mines = _admin_checkbox_on("admin_block_bandit_mines")
        ws.admin_block_bandit_outposts = _admin_checkbox_on(
            "admin_block_bandit_outposts"
        )
        ws.admin_block_bandit_fleets = _admin_checkbox_on("admin_block_bandit_fleets")
        s.commit()
    return redirect(url_for("web.admin_hub", token=token, tab="npc"))


@web_bp.post("/admin/world/balance-tuning")
def admin_world_balance_tuning():
    token = _require_admin_token()
    raw_max = (request.form.get("admin_max_fleet_units") or "").strip()
    try:
        max_v = int(raw_max)
    except ValueError:
        max_v = 0
    max_v = max(0, min(max_v, 500))
    time_map: dict[int, float] = {}
    rp_map: dict[int, float] = {}
    for ti in range(1, 7):
        tt = (request.form.get(f"time_t{ti}") or "1").strip().replace(",", ".")
        rt = (request.form.get(f"rp_t{ti}") or "1").strip().replace(",", ".")
        try:
            time_map[ti] = max(0.01, min(float(tt), 100.0))
        except ValueError:
            time_map[ti] = 1.0
        try:
            rp_map[ti] = max(0.01, min(float(rt), 100.0))
        except ValueError:
            rp_map[ti] = 1.0
    j = serialize_research_overrides_from_maps(time_map, rp_map)
    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        ws = world.get_or_create_world_state(s)
        ws.admin_max_fleet_units = int(max_v)
        ws.admin_research_overrides_json = j
        s.commit()
    return redirect(url_for("web.admin_hub", token=token, tab="balance"))


@web_bp.post("/admin/world/economy-base-food-water")
def admin_world_economy_base_food_water():
    token = _require_admin_token()
    raw_f = (request.form.get("economy_base_food_per_sol") or "").strip()
    raw_w = (request.form.get("economy_base_water_per_sol") or "").strip()
    try:
        f = int(raw_f) if raw_f else 10
    except ValueError:
        f = 10
    try:
        w = int(raw_w) if raw_w else 10
    except ValueError:
        w = 10
    f = max(0, min(f, 999))
    w = max(0, min(w, 999))
    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        ws = world.get_or_create_world_state(s)
        ws.economy_base_food_per_sol = int(f)
        ws.economy_base_water_per_sol = int(w)
        s.commit()
    return redirect(url_for("web.admin_hub", token=token, tab="balance"))


@web_bp.post("/admin/world/economy-overrides")
def admin_world_economy_overrides():
    token = _require_admin_token()
    raw = (request.form.get("admin_economy_overrides_json") or "").strip()
    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        ws = world.get_or_create_world_state(s)
        if not raw:
            ws.admin_economy_overrides_json = None
        else:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return redirect(
                    url_for(
                        "web.admin_hub",
                        token=token,
                        tab="balance",
                        economy_json_error=1,
                    )
                )
            if not isinstance(parsed, dict):
                return redirect(
                    url_for(
                        "web.admin_hub",
                        token=token,
                        tab="balance",
                        economy_json_error=1,
                    )
                )
            ws.admin_economy_overrides_json = raw
        s.commit()
    return redirect(url_for("web.admin_hub", token=token, tab="balance"))


@web_bp.post("/admin/world/purge-bandits")
def admin_world_purge_bandits():
    token = _require_admin_token()
    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        world.admin_dev_purge_bandit_world(s)
        s.commit()
    return redirect(url_for("web.admin_hub", token=token, tab="npc"))


@web_bp.post("/admin/world/tick_once")
def admin_world_tick_once():
    token = _require_admin_token()
    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        world.process_next_tick(s)
        s.commit()
    return redirect(url_for("web.admin_hub", token=token, tab="world"))


@web_bp.post("/admin/accounts/<player_id>/staff-chat-exempt")
def admin_toggle_staff_chat_exempt(player_id: str):
    token = _require_admin_token()
    on = request.form.get("enabled", "").strip().lower() in ("1", "true", "yes", "on")
    pid_s = player_id.strip()
    with db_session() as s:
        try:
            pid = uuid.UUID(pid_s)
        except ValueError:
            abort(404)
        player = s.execute(select(Player).where(Player.id == pid)).scalar_one_or_none()
        if not player:
            abort(404)
        player.staff_chat_exempt = bool(on)
        s.commit()
    return redirect(url_for("web.admin_hub", token=token, tab="accounts"))


@web_bp.post("/admin/accounts/<player_id>/game-admin")
def admin_toggle_game_admin(player_id: str):
    token = _require_admin_token()
    on = request.form.get("enabled", "").strip().lower() in ("1", "true", "yes", "on")
    pid_s = player_id.strip()
    with db_session() as s:
        try:
            pid = uuid.UUID(pid_s)
        except ValueError:
            abort(404)
        player = s.execute(select(Player).where(Player.id == pid)).scalar_one_or_none()
        if not player:
            abort(404)
        player.is_game_admin = bool(on)
        s.commit()
    return redirect(url_for("web.admin_hub", token=token, tab="accounts"))


@web_bp.post("/admin/accounts/<player_id>/game-moderator")
def admin_toggle_game_moderator(player_id: str):
    token = _require_admin_token()
    on = request.form.get("enabled", "").strip().lower() in ("1", "true", "yes", "on")
    pid_s = player_id.strip()
    with db_session() as s:
        try:
            pid = uuid.UUID(pid_s)
        except ValueError:
            abort(404)
        player = s.execute(select(Player).where(Player.id == pid)).scalar_one_or_none()
        if not player:
            abort(404)
        player.is_game_moderator = bool(on)
        s.commit()
    return redirect(url_for("web.admin_hub", token=token, tab="accounts"))


@web_bp.post("/admin/accounts/<player_id>/account-disabled")
def admin_toggle_account_disabled(player_id: str):
    token = _require_admin_token()
    on = request.form.get("enabled", "").strip().lower() in ("1", "true", "yes", "on")
    pid_s = player_id.strip()
    with db_session() as s:
        try:
            pid = uuid.UUID(pid_s)
        except ValueError:
            abort(404)
        player = s.execute(select(Player).where(Player.id == pid)).scalar_one_or_none()
        if not player:
            abort(404)
        player.account_disabled = bool(on)
        s.commit()
    return redirect(url_for("web.admin_hub", token=token, tab="accounts"))


@web_bp.post("/admin/accounts/<player_id>/playtest-audit")
def admin_toggle_playtest_audit(player_id: str):
    token = _require_admin_token()
    on = request.form.get("enabled", "").strip().lower() in ("1", "true", "yes", "on")
    pid_s = player_id.strip()
    with db_session() as s:
        try:
            pid = uuid.UUID(pid_s)
        except ValueError:
            abort(404)
        player = s.execute(select(Player).where(Player.id == pid)).scalar_one_or_none()
        if not player:
            abort(404)
        player.feedback_audited = bool(on)
        s.commit()

    invalidate_feedback_audited_cache(pid_s)
    return redirect(url_for("web.admin_hub", token=token, tab="accounts"))


@web_bp.post("/admin/accounts/<player_id>/delete")
def admin_delete_player(player_id: str):
    token = _require_admin_token()
    with db_session() as s:
        pid = uuid.UUID(player_id)
        s.execute(delete(Event).where(Event.player_id == pid))
        player = s.execute(select(Player).where(Player.id == pid)).scalar_one_or_none()
        if player:
            s.delete(player)
        s.commit()
    return redirect(url_for("web.admin_hub", token=token, tab="accounts"))


@web_bp.post("/admin/feedback/<int:message_id>/delete")
def admin_feedback_delete(message_id: int):
    token = _require_admin_token()
    with db_session() as s:
        msg = s.get(FeedbackMessage, message_id)
        if msg:
            s.delete(msg)
            s.commit()
    return redirect(url_for("web.admin_hub", token=token, tab="feedback"))


@web_bp.post("/admin/accounts/<player_id>/regenerate")
def admin_regenerate_player_access_code(player_id: str):
    token = _require_admin_token()
    auth = AuthService(server_salt=current_app.config["SERVER_SALT"])
    access_code = auth.generate_access_code()
    access_code_hash = auth.hash_access_code(access_code)

    with db_session() as s:
        pid = uuid.UUID(player_id)
        player = s.execute(select(Player).where(Player.id == pid)).scalar_one_or_none()
        if not player:
            abort(404)
        player.access_code_hash = access_code_hash
        s.commit()
        # Показываем код один раз (как на регистрации).
        return render_template(
            "show_code.html",
            access_code=access_code,
            display_name=player.display_name,
            admin_token=token,
        )


@web_bp.route("/actions/move_scout", methods=["GET", "POST"])
def move_scout():
    # Если открыть URL руками в браузере, просто вернём назад на /me.
    if request.method == "GET":
        return redirect(url_for("web.me"))

    player_id = _require_login()
    if not player_id:
        return redirect(url_for("web.login"))

    x = request.form.get("x", type=int)
    y = request.form.get("y", type=int)
    z = request.form.get("z", type=int, default=0)
    if z is None:
        z = 0
    if x is None or y is None:
        return redirect(url_for("web.me"))

    z = max(-10, min(z, 10))

    with db_session() as s:
        world = WorldService(world_seed=current_app.config["SERVER_SALT"])
        result = world.create_scout_move_order(
            s, player_id=player_id, target_x=x, target_y=y, target_z=z
        )
        if result.get("ok"):
            s.commit()

    return redirect(url_for("web.me", x=x, y=y, z=z))
