"""Утилиты интеграционных тестов: только тестовые игроки и явная очистка."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.db.models.event import Event
from app.db.models.player import Player


def display_name_pytest(tag: str) -> str:
    """Префикс для имён — автоподчистка по шаблону после теста."""
    return f"gs_py_{tag}_{uuid.uuid4().hex[:10]}"[:64]


def reset_world_tick(engine: Engine) -> None:
    """Глобальный сол в БД один на всех — сбрасываем между тестами."""
    with engine.begin() as conn:
        conn.execute(text("UPDATE world_state SET current_tick = 0 WHERE id = 1"))


def delete_player_cascade(engine: Engine, player_id: str) -> None:
    """Как при удалении аккаунта: events, затем игрок (остальное — CASCADE в БД)."""
    pid = uuid.UUID(str(player_id))
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        s.execute(delete(Event).where(Event.player_id == pid))
        row = s.get(Player, pid)
        if row:
            s.delete(row)
        s.commit()


def delete_players_display_prefix(engine: Engine, prefix: str = "gs_py_") -> None:
    """Удалить всех тестовых операторов по префиксу имени (хвосты после падения теста)."""
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        ids = list(
            s.execute(select(Player.id).where(Player.display_name.like(f"{prefix}%")))
            .scalars()
            .all()
        )
    for pid in ids:
        delete_player_cascade(engine, str(pid))


@contextmanager
def registered_player(
    client: Any, engine: Engine, tag: str
) -> Iterator[dict[str, Any]]:
    name = display_name_pytest(tag)
    reg = client.post("/api/register", json={"display_name": name})
    assert reg.status_code == 200, reg.get_data(as_text=True)
    info = reg.get_json()
    pid = info["player_id"]
    try:
        yield info
    finally:
        delete_player_cascade(engine, pid)
