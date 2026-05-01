from __future__ import annotations

import threading
import time
import uuid
from time import perf_counter

from flask import Blueprint, g, request, session
from sqlalchemy import select

from app.db.engine import db_session
from app.db.models.feedback_playtest_api_log import FeedbackPlaytestApiLog
from app.db.models.player import Player

_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_BODY_MAX = 4000
_CACHE_TTL_SEC = 45.0
_lock = threading.Lock()
_flag_cache: dict[str, tuple[bool, float]] = {}


def invalidate_feedback_audited_cache(player_id: str | uuid.UUID | None = None) -> None:
    with _lock:
        if player_id is None:
            _flag_cache.clear()
        else:
            _flag_cache.pop(str(player_id), None)


def _cached_feedback_audited(player_id: uuid.UUID) -> bool:
    key = str(player_id)
    now = time.monotonic()
    with _lock:
        hit = _flag_cache.get(key)
        if hit is not None and (now - hit[1]) < _CACHE_TTL_SEC:
            return hit[0]
    with db_session() as s:
        row = (
            s.execute(select(Player.feedback_audited).where(Player.id == player_id)).scalar_one_or_none()
        )
    flag = bool(row)
    with _lock:
        _flag_cache[key] = (flag, now)
    return flag


def _record_row(
    *,
    player_id: uuid.UUID,
    method: str,
    path: str,
    query_string: str,
    body_preview: str | None,
    status_code: int,
    duration_ms: int,
) -> None:
    row = FeedbackPlaytestApiLog(
        player_id=player_id,
        method=method[:8],
        path=path[:512],
        query_string=(query_string or "")[:512],
        body_preview=body_preview,
        status_code=min(32767, max(-32768, int(status_code))),
        duration_ms=max(0, int(duration_ms)),
    )
    with db_session() as s:
        s.add(row)
        s.commit()


def register_playtest_audit_hooks(bp: Blueprint) -> None:
    """Запись мутаций (POST и т.д.) для игроков с Player.feedback_audited=True."""

    @bp.before_request
    def _playtest_audit_capture() -> None:
        g._playtest_audit_t0 = perf_counter()
        g._playtest_audit_meta = None

        raw_pid = session.get("player_id")
        if not raw_pid:
            return
        try:
            pid = uuid.UUID(str(raw_pid))
        except ValueError:
            return

        if request.method not in _MUTATING:
            return
        if not _cached_feedback_audited(pid):
            return

        qs = ""
        if request.query_string:
            qs = request.query_string.decode("utf-8", errors="replace")

        route_path = request.path or ""
        base = route_path.rstrip("/")
        if base.endswith("/login") or base.endswith("/register"):
            preview = "<redacted:auth>"
        else:
            try:
                raw = request.get_data(cache=True, as_text=False)
                if raw is None:
                    preview = None
                else:
                    txt = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
                    preview = txt if len(txt) <= _BODY_MAX else txt[:_BODY_MAX] + "…"
            except Exception:
                preview = "<unreadable>"

        g._playtest_audit_meta = {
            "player_id": pid,
            "body_preview": preview,
            "query_string": qs,
        }

    @bp.after_request
    def _playtest_audit_flush(response):  # type: ignore[no-untyped-def]
        meta = getattr(g, "_playtest_audit_meta", None)
        if not meta:
            return response

        t0 = getattr(g, "_playtest_audit_t0", None)
        try:
            ms = int(max(0, (perf_counter() - float(t0)) * 1000)) if t0 is not None else 0
            _record_row(
                player_id=meta["player_id"],
                method=request.method,
                path=request.path or "",
                query_string=str(meta.get("query_string") or ""),
                body_preview=meta.get("body_preview"),
                status_code=int(response.status_code),
                duration_ms=ms,
            )
        except Exception:
            pass
        return response
