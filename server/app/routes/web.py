from flask import (
    Blueprint,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
    abort,
)

from app.db.engine import db_session
from app.services.auth_service import AuthService
from app.services.feedback_playtest_audit import invalidate_feedback_audited_cache
from app.services.world_service import WorldService
from app.db.models.player import Player
from app.db.models.event import Event
from app.db.models.planet import Planet
from app.db.models.fleet import Fleet
from app.db.models.admin_config import AdminConfig
from sqlalchemy import delete, func, select
import uuid

from app.build_info import BUILD_ID, GAME_VERSION

web_bp = Blueprint("web", __name__)


@web_bp.get("/favicon.ico")
def favicon():
    # MVP: иконка не обязательна, но убираем 404 в консоли браузера.
    return ("", 204)


def _require_login() -> str | None:
    player_id = session.get("player_id")
    if not player_id:
        return None
    return str(player_id)


@web_bp.get("/")
def index():
    return render_template("index.html")


@web_bp.route("/register", methods=["GET", "POST"])
def register():
    balance = current_app.extensions.get("balance_service")
    races = []
    if (
        balance
        and getattr(balance, "pack", None)
        and isinstance(getattr(balance.pack, "races_by_id", None), dict)
    ):
        races = sorted(
            [
                r
                for r in balance.pack.races_by_id.values()
                if isinstance(r, dict) and r.get("enabled") is not False
            ],
            key=lambda r: str(r.get("name") or r.get("id") or ""),
        )
    if request.method == "GET":
        return render_template("register.html", races=races)

    display_name = (request.form.get("display_name") or "").strip()
    if not display_name:
        return render_template("register.html", error="Введите имя.", races=races)

    race_id = (request.form.get("race_id") or "").strip() or "human"
    if race_id and balance:
        try:
            r = balance.get_race(race_id)
        except Exception:
            r = None
        if not isinstance(r, dict) or r.get("enabled") is False:
            return render_template(
                "register.html", error="Выберите расу из списка.", races=races
            )

    auth = AuthService(server_salt=current_app.config["SERVER_SALT"])
    world = WorldService(balance=balance)

    with db_session() as s:
        player, access_code = auth.register_player(
            s, display_name=display_name, race_id=race_id
        )
        world.ensure_player_has_start(s, player_id=player.id)
        s.commit()

    session["player_id"] = str(player.id)
    return render_template(
        "show_code.html", access_code=access_code, display_name=display_name
    )


@web_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    access_code = (request.form.get("access_code") or "").strip()
    if not access_code:
        return render_template("login.html", error="Введите код доступа.")

    auth = AuthService(server_salt=current_app.config["SERVER_SALT"])
    with db_session() as s:
        player = auth.authenticate_by_code(s, access_code=access_code)

    if not player:
        return render_template("login.html", error="Неверный код доступа.")

    session["player_id"] = str(player.id)
    return redirect(url_for("web.me"))


@web_bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("web.index"))


@web_bp.get("/me")
def me():
    player_id = _require_login()
    if not player_id:
        return redirect(url_for("web.login"))

    sel_x = request.args.get("x", type=int)
    sel_y = request.args.get("y", type=int)
    z = request.args.get("z", default=0, type=int)
    if z is None:
        z = 0
    z = max(-10, min(z, 10))

    with db_session() as s:
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        data = world.get_player_overview(s, player_id=player_id)
        window = world.get_player_map_window(s, player_id=player_id, radius=4, z=z)
        sector = None
        if sel_x is not None and sel_y is not None:
            sector = world.get_sector_stub(
                s, x=sel_x, y=sel_y, z=z, player_id=player_id
            )

    return render_template(
        "me.html",
        data=data,
        window=window,
        sector=sector,
        sel_x=sel_x,
        sel_y=sel_y,
        z=z,
    )


@web_bp.get("/account")
def account():
    player_id = _require_login()
    if not player_id:
        return redirect(url_for("web.login"))

    with db_session() as s:
        pid = uuid.UUID(player_id)
        player = s.execute(select(Player).where(Player.id == pid)).scalar_one_or_none()
        if not player:
            session.clear()
            return redirect(url_for("web.index"))
        return render_template("account.html", player=player, access_code=None)


@web_bp.post("/account/rename")
def account_rename():
    player_id = _require_login()
    if not player_id:
        return redirect(url_for("web.login"))

    new_name = (request.form.get("display_name") or "").strip()
    if not new_name:
        return redirect(url_for("web.account"))

    with db_session() as s:
        pid = uuid.UUID(player_id)
        player = s.execute(select(Player).where(Player.id == pid)).scalar_one_or_none()
        if not player:
            session.clear()
            return redirect(url_for("web.index"))
        player.display_name = new_name[:64]
        s.commit()
        return redirect(url_for("web.account"))


@web_bp.post("/account/regenerate")
def account_regenerate():
    player_id = _require_login()
    if not player_id:
        return redirect(url_for("web.login"))

    auth = AuthService(server_salt=current_app.config["SERVER_SALT"])
    access_code = auth.generate_access_code()
    access_code_hash = auth.hash_access_code(access_code)

    with db_session() as s:
        pid = uuid.UUID(player_id)
        player = s.execute(select(Player).where(Player.id == pid)).scalar_one_or_none()
        if not player:
            session.clear()
            return redirect(url_for("web.index"))
        player.access_code_hash = access_code_hash
        s.commit()
        return render_template("account.html", player=player, access_code=access_code)


@web_bp.post("/account/delete")
def account_delete():
    player_id = _require_login()
    if not player_id:
        return redirect(url_for("web.login"))

    with db_session() as s:
        pid = uuid.UUID(player_id)
        # Events не имеют FK на players, чистим вручную.
        s.execute(delete(Event).where(Event.player_id == pid))
        player = s.execute(select(Player).where(Player.id == pid)).scalar_one_or_none()
        if player:
            s.delete(player)
        s.commit()

    session.clear()
    return redirect(url_for("web.index"))


def _require_admin_token() -> str:
    token = (request.args.get("token") or "").strip()
    # Админский токен живёт в БД (хэш), чтобы не зависеть от env.
    with db_session() as s:
        cfg = s.execute(
            select(AdminConfig).where(AdminConfig.id == 1)
        ).scalar_one_or_none()
        expected_hash = (cfg.admin_token_hash if cfg else "").strip()
    if not expected_hash:
        abort(403)
    auth = AuthService(server_salt=current_app.config["SERVER_SALT"])
    if auth.hash_access_code(token) != expected_hash:
        abort(403)
    return token


@web_bp.get("/admin/accounts")
def admin_accounts():
    token = _require_admin_token()
    with db_session() as s:
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
                }
            )

    return render_template("admin_accounts.html", players=payload, token=token)


@web_bp.get("/admin/world")
def admin_world():
    token = _require_admin_token()
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
    return render_template("admin_world.html", token=token, data=data)


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

    return redirect(url_for("web.admin_world", token=token))


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

    return redirect(url_for("web.admin_world", token=token))


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
    return redirect(url_for("web.admin_accounts", token=token))


@web_bp.post("/admin/accounts/<player_id>/delete")
def admin_delete_player(player_id: str):
    _require_admin_token()
    with db_session() as s:
        pid = uuid.UUID(player_id)
        s.execute(delete(Event).where(Event.player_id == pid))
        player = s.execute(select(Player).where(Player.id == pid)).scalar_one_or_none()
        if player:
            s.delete(player)
        s.commit()
    return redirect(url_for("web.admin_accounts", token=request.args.get("token")))


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
