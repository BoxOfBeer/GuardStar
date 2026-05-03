"""Публичные и игровые страницы (без админки)."""

from __future__ import annotations

import uuid

from flask import abort, current_app, redirect, render_template, request, session, url_for
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.engine import db_session
from app.db.models.event import Event
from app.db.models.feedback_message import FeedbackMessage
from app.db.models.player import Player
from app.db.models.reserved_display_name import ReservedDisplayName
from app.db.models.world_state import WorldState
from app.routes.web.blueprint import web_bp
from app.routes.web.common import (
    _DISCORD_INVITE_URL,
    _FEEDBACK_CATEGORIES,
    _require_login,
)
from app.services.auth_service import (
    AuthService,
    DisplayNameInvalid,
    normalized_operator_name,
    prepare_operator_display_name,
)
from app.services.world_service import WorldService

_REGISTER_NAME_MESSAGES: dict[str, str] = {
    "empty": "Введите имя оператора.",
    "too_short": "Имя не короче 3 символов (пробелы по краям не считаются).",
    "too_long": "Имя не длиннее 64 символов.",
    "taken": "Это имя уже занято. Ранее использованные позывные не освобождаются.",
}


def _past_operator_profile_names(session: Session, *, player: Player) -> list[str]:
    """Исторические позывные (снимки), исключая текущий активный."""

    cur_nn = normalized_operator_name(prepare_operator_display_name(player.display_name))
    rows = session.execute(
        select(ReservedDisplayName.display_snapshot, ReservedDisplayName.name_norm)
        .where(ReservedDisplayName.player_id == player.id)
        .order_by(ReservedDisplayName.created_at.desc())
    ).all()
    seen_nn: set[str] = set()
    out: list[str] = []
    for snapshot, nn in rows:
        if nn == cur_nn:
            continue
        if nn in seen_nn:
            continue
        seen_nn.add(nn)
        out.append(str(snapshot))
    return out


@web_bp.get("/favicon.ico")
def favicon():
    # MVP: иконка не обязательна, но убираем 404 в консоли браузера.
    return ("", 204)


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
        return render_template(
            "register.html",
            races=races,
            selected_race_id=None,
            display_name_value="",
            accept_pilot_rules_checked=False,
        )

    form_race = (request.form.get("race_id") or "").strip() or None
    display_name = (request.form.get("display_name") or "").strip()
    accept_rules = request.form.get("accept_pilot_rules") == "1"
    if not accept_rules:
        return render_template(
            "register.html",
            error="Нужно отметить согласие с правилами оператора.",
            races=races,
            selected_race_id=form_race,
            display_name_value=display_name,
            accept_pilot_rules_checked=False,
        )
    if not display_name:
        return render_template(
            "register.html",
            error="Введите имя.",
            races=races,
            selected_race_id=form_race,
            display_name_value=display_name,
            accept_pilot_rules_checked=True,
        )

    race_id = form_race or "human"
    if race_id and balance:
        try:
            r = balance.get_race(race_id)
        except Exception:
            r = None
        if not isinstance(r, dict) or r.get("enabled") is False:
            return render_template(
                "register.html",
                error="Выберите расу из списка.",
                races=races,
                selected_race_id=form_race,
                display_name_value=display_name,
                accept_pilot_rules_checked=True,
            )

    auth = AuthService(server_salt=current_app.config["SERVER_SALT"])
    world = WorldService(balance=balance)

    try:
        with db_session() as s:
            player, access_code = auth.register_player(
                s, display_name=display_name, race_id=race_id
            )
            world.ensure_player_has_start(s, player_id=player.id)
            s.commit()
    except DisplayNameInvalid as exc:
        return render_template(
            "register.html",
            error=_REGISTER_NAME_MESSAGES.get(
                exc.code, "Не удалось зарезервировать имя."
            ),
            races=races,
            selected_race_id=form_race,
            display_name_value=display_name,
            accept_pilot_rules_checked=True,
        )

    session["player_id"] = str(player.id)
    return render_template(
        "show_code.html", access_code=access_code, display_name=player.display_name
    )


@web_bp.get("/operator/<uuid:pid>")
def operator_public_profile(pid: uuid.UUID):
    with db_session() as s:
        pl = s.get(Player, pid)
        if pl is None or bool(getattr(pl, "account_disabled", False)):
            abort(404)
        past = _past_operator_profile_names(s, player=pl)
        profile_id = str(pl.id)
        profile_name = pl.display_name

    cid = session.get("player_id")
    return render_template(
        "operator_public.html",
        profile={
            "id": profile_id,
            "display_name": profile_name,
            "past_names": past,
        },
        current_player_id_str=str(cid) if cid else None,
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
        pid = uuid.UUID(player_id)
        pl_check = s.execute(select(Player).where(Player.id == pid)).scalar_one_or_none()
        if not pl_check or bool(getattr(pl_check, "account_disabled", False)):
            session.clear()
            return redirect(url_for("web.login"))
        balance = current_app.extensions.get("balance_service")
        world = WorldService(
            world_seed=current_app.config["SERVER_SALT"], balance=balance
        )
        data = world.get_player_overview(s, player_id=player_id)
        window = world.get_player_map_window(s, player_id=player_id, radius=6, z=z)
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
        rename_err = (request.args.get("rename_err") or "").strip() or None
        return render_template(
            "account.html",
            player=player,
            access_code=None,
            rename_err=rename_err,
        )


@web_bp.post("/account/rename")
def account_rename():
    player_id = _require_login()
    if not player_id:
        return redirect(url_for("web.login"))

    new_name = (request.form.get("display_name") or "").strip()
    if not new_name:
        return redirect(url_for("web.account"))

    auth = AuthService(server_salt=current_app.config["SERVER_SALT"])
    try:
        with db_session() as s:
            pid = uuid.UUID(player_id)
            player = s.execute(select(Player).where(Player.id == pid)).scalar_one_or_none()
            if not player:
                session.clear()
                return redirect(url_for("web.index"))
            auth.rename_player(s, player=player, new_display_name_raw=new_name)
            s.commit()
            return redirect(url_for("web.account"))
    except DisplayNameInvalid as exc:
        return redirect(url_for("web.account", rename_err=exc.code))


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
        return render_template(
            "account.html",
            player=player,
            access_code=access_code,
            rename_err=None,
        )


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


@web_bp.route("/feedback", methods=["GET", "POST"])
def feedback():
    player_id = _require_login()
    if not player_id:
        return redirect(url_for("web.login"))

    if request.method == "GET":
        sent = request.args.get("sent")
        category = (request.args.get("category") or "bug").strip()
        if category not in _FEEDBACK_CATEGORIES:
            category = "bug"
        return render_template(
            "feedback.html",
            discord_url=_DISCORD_INVITE_URL,
            sent_ok=bool(sent),
            error=None,
            category=category,
            body_prefill="",
        )

    category = (request.form.get("category") or "bug").strip()
    if category not in _FEEDBACK_CATEGORIES:
        category = "bug"
    body = (request.form.get("body") or "").strip()
    if len(body) < 3:
        return render_template(
            "feedback.html",
            discord_url=_DISCORD_INVITE_URL,
            sent_ok=False,
            error="Напишите хотя бы пару слов (от 3 символов).",
            category=category,
            body_prefill=body,
        )
    if len(body) > 6000:
        body = body[:6000]

    with db_session() as s:
        pid = uuid.UUID(player_id)
        player = s.execute(select(Player).where(Player.id == pid)).scalar_one_or_none()
        if not player:
            session.clear()
            return redirect(url_for("web.index"))
        ws = s.execute(select(WorldState).where(WorldState.id == 1)).scalar_one_or_none()
        tick = int(ws.current_tick) if ws else None
        msg = FeedbackMessage(
            pilot_name=(player.display_name or "")[:64],
            category=category,
            body=body,
            player_id=pid,
            current_tick=tick,
        )
        s.add(msg)
        s.commit()

    return redirect(url_for("web.feedback", sent=1))

