"""Эффекты, влияющие на исследования (player_effects)."""

from __future__ import annotations

import json
import math
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models.player_effect import PlayerEffect

EFFECT_RESEARCH_SPEED = "research_speed_boost"
EFFECT_BLUEPRINT_CACHE = "blueprint_cache"
EFFECT_BANDIT_AMBUSH_COOLDOWN = "bandit_ambush_cooldown"
EFFECT_RUIN_ARCHIVES = "ruin_archives"
EFFECT_ANOMALY_DATA = "anomaly_data"
EFFECT_RESEARCH_FRAGMENTS = "research_fragments"


def list_active_player_effects(s: Session, *, player_id: uuid.UUID, tick: int) -> list[dict]:
    """Список активных (не used, не истёк) эффектов игрока для UI."""
    now = int(tick)
    rows = (
        s.execute(
            select(PlayerEffect)
            .where(
                PlayerEffect.player_id == player_id,
                PlayerEffect.used_at_tick.is_(None),
            )
            .order_by(PlayerEffect.id.asc())
        )
        .scalars()
        .all()
    )
    out: list[dict] = []
    for r in rows:
        if r.expires_tick is not None and int(r.expires_tick) <= now:
            continue
        try:
            payload = json.loads(r.payload_json or "{}")
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        rem = None
        if r.expires_tick is not None:
            rem = max(0, int(r.expires_tick) - now)
        out.append(
            {
                "id": int(r.id),
                "effect_type": str(r.effect_type),
                "source_type": str(r.source_type or ""),
                "source_ref": str(r.source_ref or ""),
                "created_tick": int(r.created_tick or 0),
                "expires_tick": int(r.expires_tick) if r.expires_tick is not None else None,
                "remaining_ticks": rem,
                "payload": payload,
            }
        )
    return out


def add_field_data(
    s: Session,
    *,
    player_id: uuid.UUID,
    tick: int,
    kind: str,
    source_type: str,
    source_ref: str,
    payload: dict | None = None,
) -> None:
    k = str(kind or "").strip()
    if k not in (EFFECT_RUIN_ARCHIVES, EFFECT_ANOMALY_DATA, EFFECT_RESEARCH_FRAGMENTS):
        return
    s.add(
        PlayerEffect(
            player_id=player_id,
            effect_type=k,
            source_type=str(source_type or "unknown"),
            source_ref=str(source_ref or ""),
            payload_json=json.dumps(payload or {}, ensure_ascii=False),
            created_tick=int(tick),
            expires_tick=None,
            used_at_tick=None,
        )
    )
    s.flush()


def count_field_data(s: Session, *, player_id: uuid.UUID, tick: int, kind: str) -> int:
    k = str(kind or "").strip()
    if k not in (EFFECT_RUIN_ARCHIVES, EFFECT_ANOMALY_DATA, EFFECT_RESEARCH_FRAGMENTS):
        return 0
    now = int(tick)
    rows = (
        s.execute(
            select(PlayerEffect.id, PlayerEffect.expires_tick)
            .where(
                PlayerEffect.player_id == player_id,
                PlayerEffect.effect_type == k,
                PlayerEffect.used_at_tick.is_(None),
            )
        )
        .all()
    )
    c = 0
    for _id, exp in rows:
        if exp is not None and int(exp) <= now:
            continue
        c += 1
    return c


def consume_field_data(s: Session, *, player_id: uuid.UUID, tick: int, kind: str, qty: int = 1) -> bool:
    k = str(kind or "").strip()
    need = max(0, int(qty))
    if need <= 0:
        return True
    if k not in (EFFECT_RUIN_ARCHIVES, EFFECT_ANOMALY_DATA, EFFECT_RESEARCH_FRAGMENTS):
        return False
    now = int(tick)
    rows = (
        s.execute(
            select(PlayerEffect)
            .where(
                PlayerEffect.player_id == player_id,
                PlayerEffect.effect_type == k,
                PlayerEffect.used_at_tick.is_(None),
            )
            .order_by(PlayerEffect.id.asc())
        )
        .scalars()
        .all()
    )
    usable = []
    for r in rows:
        if r.expires_tick is not None and int(r.expires_tick) <= now:
            continue
        usable.append(r)
    if len(usable) < need:
        return False
    for r in usable[:need]:
        r.used_at_tick = now
    s.flush()
    return True


def upsert_single_blueprint_cache(
    s: Session, *, player_id: uuid.UUID, tick: int, source_type: str, source_ref: str, payload: dict
) -> PlayerEffect:
    """Гарантирует максимум один активный blueprint_cache: обновляет существующий или создаёт новый."""
    row = (
        s.execute(
            select(PlayerEffect)
            .where(
                PlayerEffect.player_id == player_id,
                PlayerEffect.effect_type == EFFECT_BLUEPRINT_CACHE,
                PlayerEffect.used_at_tick.is_(None),
            )
            .order_by(PlayerEffect.id.asc())
        )
        .scalars()
        .first()
    )
    if not row:
        row = PlayerEffect(
            player_id=player_id,
            effect_type=EFFECT_BLUEPRINT_CACHE,
            source_type=str(source_type or "unknown"),
            source_ref=str(source_ref or ""),
            payload_json=json.dumps(payload or {}, ensure_ascii=False),
            created_tick=int(tick),
            expires_tick=None,
        )
        s.add(row)
        s.flush()
        return row

    row.source_type = str(source_type or row.source_type or "unknown")
    row.source_ref = str(source_ref or row.source_ref or "")
    row.payload_json = json.dumps(payload or {}, ensure_ascii=False)
    row.created_tick = int(tick)
    s.flush()
    return row


def upsert_research_speed_boost(
    s: Session, *, player_id: uuid.UUID, tick: int, source_type: str, source_ref: str, time_multiplier: float, duration_ticks: int
) -> PlayerEffect:
    """
    research_speed_boost не стакуется:
    - если новый лучше (меньше time_multiplier) — заменить;
    - иначе продлить expires_tick (добавить duration_ticks).
    """
    now = int(tick)
    dur = max(1, int(duration_ticks))
    new_m = float(time_multiplier) if float(time_multiplier) > 0 else 1.0
    row = (
        s.execute(
            select(PlayerEffect)
            .where(
                PlayerEffect.player_id == player_id,
                PlayerEffect.effect_type == EFFECT_RESEARCH_SPEED,
                PlayerEffect.used_at_tick.is_(None),
            )
            .order_by(PlayerEffect.id.asc())
        )
        .scalars()
        .first()
    )
    if not row or (row.expires_tick is not None and int(row.expires_tick) <= now):
        exp = now + dur
        payload = {"time_multiplier": new_m, "duration_ticks": dur}
        row2 = PlayerEffect(
            player_id=player_id,
            effect_type=EFFECT_RESEARCH_SPEED,
            source_type=str(source_type or "unknown"),
            source_ref=str(source_ref or ""),
            payload_json=json.dumps(payload, ensure_ascii=False),
            created_tick=now,
            expires_tick=exp,
        )
        s.add(row2)
        s.flush()
        return row2

    try:
        cur_payload = json.loads(row.payload_json or "{}")
    except Exception:
        cur_payload = {}
    if not isinstance(cur_payload, dict):
        cur_payload = {}
    cur_m = cur_payload.get("time_multiplier")
    cur_m = float(cur_m) if isinstance(cur_m, (int, float)) and float(cur_m) > 0 else 1.0

    if new_m < cur_m:
        exp = now + dur
        row.source_type = str(source_type or row.source_type or "unknown")
        row.source_ref = str(source_ref or row.source_ref or "")
        row.payload_json = json.dumps({"time_multiplier": new_m, "duration_ticks": dur}, ensure_ascii=False)
        row.created_tick = now
        row.expires_tick = exp
        s.flush()
        return row

    # не лучше — продлеваем
    base_exp = int(row.expires_tick) if row.expires_tick is not None else now
    row.expires_tick = max(base_exp, now) + dur
    s.flush()
    return row


def has_active_ambush_cooldown(s: Session, *, player_id: uuid.UUID, tick: int) -> bool:
    now = int(tick)
    row = (
        s.execute(
            select(PlayerEffect.id, PlayerEffect.expires_tick)
            .where(
                PlayerEffect.player_id == player_id,
                PlayerEffect.effect_type == EFFECT_BANDIT_AMBUSH_COOLDOWN,
                PlayerEffect.used_at_tick.is_(None),
            )
            .order_by(PlayerEffect.id.desc())
        )
        .first()
    )
    if not row:
        return False
    exp = row[1]
    return exp is None or int(exp) > now


def start_ambush_cooldown(s: Session, *, player_id: uuid.UUID, tick: int, cooldown_ticks: int) -> None:
    now = int(tick)
    cd = max(1, int(cooldown_ticks))
    s.add(
        PlayerEffect(
            player_id=player_id,
            effect_type=EFFECT_BANDIT_AMBUSH_COOLDOWN,
            source_type="system",
            source_ref="bandit_ambush",
            payload_json=json.dumps({"cooldown_ticks": cd}, ensure_ascii=False),
            created_tick=now,
            expires_tick=now + cd,
        )
    )
    s.flush()


def cleanup_expired_player_effects(s: Session, *, before_tick: int) -> None:
    """Удаляет истёкшие по expires_tick эффекты (строго < before_tick)."""
    s.execute(delete(PlayerEffect).where(PlayerEffect.expires_tick.isnot(None), PlayerEffect.expires_tick < int(before_tick)))


def get_research_time_multiplier(s: Session, *, player_id: uuid.UUID, tick: int) -> float:
    """
    Множитель длительности исследования (чем меньше — тем быстрее).
    Берём лучший активный research_speed_boost.
    """
    rows = (
        s.execute(
            select(PlayerEffect)
            .where(
                PlayerEffect.player_id == player_id,
                PlayerEffect.effect_type == EFFECT_RESEARCH_SPEED,
                PlayerEffect.used_at_tick.is_(None),
            )
            .order_by(PlayerEffect.id.asc())
        )
        .scalars()
        .all()
    )
    best: float | None = None
    now = int(tick)
    for r in rows:
        if r.expires_tick is not None and int(r.expires_tick) <= now:
            continue
        try:
            payload = json.loads(r.payload_json or "{}")
        except Exception:
            payload = {}
        m = payload.get("time_multiplier")
        if not isinstance(m, (int, float)) or float(m) <= 0:
            continue
        fm = float(m)
        best = fm if best is None else min(best, fm)
    return float(best) if best is not None else 1.0


def consume_blueprint_cache(s: Session, *, player_id: uuid.UUID, tick: int) -> dict | None:
    """
    Списывает один активный blueprint_cache (самый ранний по id).
    Возвращает payload-скидки или None.
    """
    row = (
        s.execute(
            select(PlayerEffect)
            .where(
                PlayerEffect.player_id == player_id,
                PlayerEffect.effect_type == EFFECT_BLUEPRINT_CACHE,
                PlayerEffect.used_at_tick.is_(None),
            )
            .order_by(PlayerEffect.id.asc())
        )
        .scalars()
        .first()
    )
    if not row:
        return None
    row.used_at_tick = int(tick)
    try:
        payload = json.loads(row.payload_json or "{}")
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    s.flush()
    return payload


def adjusted_research_duration_ticks(*, base_ticks: int, time_multiplier: float) -> int:
    base = max(1, int(base_ticks))
    mult = float(time_multiplier)
    if mult <= 0:
        mult = 1.0
    return max(1, int(math.ceil(base * mult)))
