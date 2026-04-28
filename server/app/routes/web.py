from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

from app.db.engine import db_session
from app.services.auth_service import AuthService
from app.services.world_service import WorldService

web_bp = Blueprint("web", __name__)


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
    if request.method == "GET":
        return render_template("register.html")

    display_name = (request.form.get("display_name") or "").strip()
    if not display_name:
        return render_template("register.html", error="Введите имя.")

    auth = AuthService(server_salt=current_app.config["SERVER_SALT"])
    world = WorldService()

    with db_session() as s:
        player, access_code = auth.register_player(s, display_name=display_name)
        world.ensure_player_has_start(s, player_id=player.id)
        s.commit()

    session["player_id"] = str(player.id)
    return render_template("show_code.html", access_code=access_code, display_name=display_name)


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
        world = WorldService(world_seed=current_app.config["SERVER_SALT"])
        data = world.get_player_overview(s, player_id=player_id)
        window = world.get_player_map_window(s, player_id=player_id, radius=4, z=z)
        sector = None
        if sel_x is not None and sel_y is not None:
            sector = world.get_sector_stub(s, x=sel_x, y=sel_y, z=z, player_id=player_id)

    return render_template("me.html", data=data, window=window, sector=sector, sel_x=sel_x, sel_y=sel_y, z=z)


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
        result = world.move_one_scout_from_home(s, player_id=player_id, target_x=x, target_y=y, target_z=z)
        if result.get("ok"):
            s.commit()

    return redirect(url_for("web.me", x=x, y=y, z=z))

