"""JSON API GuardStar (маршруты разнесены по routes_*.py)."""

from __future__ import annotations

import uuid

from flask import jsonify, request, session
from sqlalchemy import select

from app.db.engine import db_session
from app.db.models.player import Player
from app.routes.api.blueprint import api_bp
from app.services.player_presence import touch_player_game_activity_if_due

_SKIP_ACCOUNT_DISABLED = frozenset(
    {
        "api.api_health",
        "api.api_ready",
        "api.api_version",
        "api.api_register",
        "api.api_login",
        "api.api_logout",
    }
)


@api_bp.before_request
def _api_reject_disabled_accounts() -> None:
    ep = request.endpoint or ""
    if ep in _SKIP_ACCOUNT_DISABLED:
        return None
    pid_raw = session.get("player_id")
    if not pid_raw:
        return None
    try:
        uid = uuid.UUID(str(pid_raw))
    except Exception:
        return None
    with db_session() as s:
        row = s.execute(
            select(Player.account_disabled).where(Player.id == uid)
        ).scalar_one_or_none()
        if row is True:
            session.clear()
            return jsonify({"error": "account_disabled"}), 403
        touch_player_game_activity_if_due(s, uid)
    return None


from app.routes.api import routes_core  # noqa: F401,E402
from app.routes.api import routes_buildings_fleets_combat  # noqa: F401,E402
from app.routes.api import routes_chat  # noqa: F401,E402
from app.routes.api import routes_progress  # noqa: F401,E402
from app.routes.api import routes_world_fleets  # noqa: F401,E402

from app.services.feedback_playtest_audit import register_playtest_audit_hooks

register_playtest_audit_hooks(api_bp)

__all__ = ["api_bp"]
