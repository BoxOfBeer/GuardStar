"""Константы и мелкие хелперы веб-слоя."""

from __future__ import annotations

from flask import session

_DISCORD_INVITE_URL = "https://discord.gg/7Wf4hRJSZu"
_FEEDBACK_CATEGORIES = frozenset({"bug", "idea", "other"})

def _require_login() -> str | None:
    player_id = session.get("player_id")
    if not player_id:
        return None
    return str(player_id)

