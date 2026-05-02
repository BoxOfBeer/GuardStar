"""Админ-хаб и POST-эндпоинты админки."""

from __future__ import annotations

import uuid

from flask import abort, current_app, redirect, render_template, request, session, url_for
from sqlalchemy import delete, func, select

from app.build_info import BUILD_ID, GAME_VERSION
from app.db.engine import db_session
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
    if tab not in ("world", "accounts", "feedback"):
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
