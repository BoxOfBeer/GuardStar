"""Активность игрока по API (для админки: «онлайн», координаты с задержкой)."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from time import monotonic

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db.models.player import Player

_LOCK = threading.Lock()
_LAST_MONO: dict[uuid.UUID, float] = {}
# Не чаще одного UPDATE на игрока за интервал — снижает нагрузку при частом poll `/api/world/state`.
THROTTLE_SECONDS = 90.0


def touch_player_game_activity_if_due(s: Session, player_id: uuid.UUID) -> None:
    """Обновить `players.last_game_activity_at`, если с прошлого раза прошло достаточно времени."""
    now_m = monotonic()
    with _LOCK:
        prev = _LAST_MONO.get(player_id, 0.0)
        if now_m - prev < THROTTLE_SECONDS:
            return
        _LAST_MONO[player_id] = now_m
    now_dt = datetime.now(timezone.utc)
    s.execute(
        update(Player)
        .where(Player.id == player_id)
        .values(last_game_activity_at=now_dt)
    )
    s.commit()
