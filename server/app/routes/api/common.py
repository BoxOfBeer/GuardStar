"""Общие хелперы и константы API."""

from __future__ import annotations

from flask import session

# Радиус окна карты в клетках от центра; сторона квадрата = 2 * radius + 1 → 13…25 при 6…12.
MAP_WINDOW_RADIUS_MIN = 6
MAP_WINDOW_RADIUS_MAX = 12


def _clamp_map_window_radius(r: int) -> int:
    return max(MAP_WINDOW_RADIUS_MIN, min(MAP_WINDOW_RADIUS_MAX, int(r)))


def _current_player_id() -> str | None:
    pid = session.get("player_id")
    return str(pid) if pid else None

