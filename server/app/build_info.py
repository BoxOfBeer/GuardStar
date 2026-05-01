from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

# Перезапуск сервера меняет BUILD_ID — удобно, чтобы понять, в какой процесс попали запросы.
BUILD_ID = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _repo_root() -> Path:
    # server/app/build_info.py -> repo root
    return Path(__file__).resolve().parents[2]


def read_game_version() -> str:
    """Релизная версия игры MM.mmm из docs/GAME_VERSION (см. правила проекта)."""
    p = _repo_root() / "docs" / "GAME_VERSION"
    try:
        raw = p.read_text(encoding="utf-8").strip()
    except OSError:
        return "00.000"
    return raw if raw else "00.000"


GAME_VERSION = read_game_version()
