"""Одноразовые discovery-события при первой видимости руин/аномалий."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.explored_sector import ExploredSector
from app.services.player_research_effects import (
    EFFECT_BLUEPRINT_CACHE,
    EFFECT_RESEARCH_SPEED,
    add_field_data,
    EFFECT_ANOMALY_DATA,
    EFFECT_RESEARCH_FRAGMENTS,
    EFFECT_RUIN_ARCHIVES,
    has_active_ambush_cooldown,
    start_ambush_cooldown,
    upsert_research_speed_boost,
    upsert_single_blueprint_cache,
)

TERRAIN_DISCOVERY = frozenset({"ruins", "anomaly"})


def _roll_u32(
    world_seed: str, player_id: uuid.UUID, x: int, y: int, z: int, salt: str
) -> int:
    raw = f"{world_seed}|{player_id}|{x}|{y}|{z}|{salt}".encode()
    h = hashlib.sha256(raw).digest()
    return int.from_bytes(h[:4], "big")


def _source_subtype(
    world_seed: str, player_id: uuid.UUID, x: int, y: int, z: int, terrain: str
) -> str:
    v = _roll_u32(world_seed, player_id, x, y, z, f"disc_subtype_v1::{terrain}") % 3
    if terrain == "ruins":
        return ["archive", "storage", "damaged_beacon"][v]
    return ["unstable_field", "signal", "trap"][v]


def _weighted_outcome(
    world_seed: str,
    player_id: uuid.UUID,
    x: int,
    y: int,
    z: int,
    terrain: str,
    subtype: str,
) -> str:
    """
    Возвращает одно из: 'boost' | 'cache' | 'ambush'
    Тип источника меняет веса исходов (без новой механики).
    """
    # base weights (sum=100)
    weights: dict[str, tuple[int, int, int]] = {
        # ruins
        "archive": (60, 30, 10),
        "storage": (25, 65, 10),
        "damaged_beacon": (30, 30, 40),
        # anomaly
        "unstable_field": (55, 25, 20),
        "signal": (25, 50, 25),
        "trap": (15, 25, 60),
    }
    w = weights.get(subtype, (45, 40, 15))
    r = (
        _roll_u32(
            world_seed, player_id, x, y, z, f"disc_outcome_v1::{terrain}::{subtype}"
        )
        % 100
    )
    if r < w[0]:
        return "boost"
    if r < w[0] + w[1]:
        return "cache"
    return "ambush"


def try_resolve_ruins_anomaly_for_sector(
    s: Session,
    world: Any,
    *,
    player_id: uuid.UUID,
    x: int,
    y: int,
    z: int,
    terrain: str,
    now_tick: int,
    explored: ExploredSector,
) -> dict[str, Any]:
    if terrain not in TERRAIN_DISCOVERY:
        return {"ok": False, "reason": "not_applicable"}
    if bool(getattr(explored, "discovery_done", False)):
        return {"ok": False, "reason": "already_done"}

    headline: str | None = None
    seed = str(getattr(world, "_world_seed", "") or "")
    subtype = _source_subtype(seed, player_id, int(x), int(y), int(z), terrain)
    outcome = _weighted_outcome(
        seed, player_id, int(x), int(y), int(z), terrain, subtype
    )
    src = str(terrain).lower()
    ref = f"{int(x)}:{int(y)}:{int(z)}"
    tick = int(now_tick)

    explored.discovery_done = True
    explored.discovery_seen_tick = tick

    if outcome == "boost":
        duration = 15
        mult = 0.85
        row = upsert_research_speed_boost(
            s,
            player_id=player_id,
            tick=tick,
            source_type=src,
            source_ref=ref,
            time_multiplier=mult,
            duration_ticks=duration,
        )
        exp = (
            int(row.expires_tick) if row.expires_tick is not None else (tick + duration)
        )
        place = "аномалии" if terrain == "anomaly" else "руинах"
        pct = max(0, int(round((1.0 - float(mult)) * 100)))
        subtype_ru = {
            "archive": "архив старых расчётов",
            "storage": "пакет производственных схем",
            "damaged_beacon": "повреждённый маяк с телеметрией",
            "unstable_field": "нестабильное поле, ускоряющее анализ",
            "signal": "сигнал с научной телеметрией",
            "trap": "аномальная структура с полезными следами",
        }.get(subtype, "архив данных")
        msg = f"В {place} найден {subtype_ru}. Исследования быстрее на {pct}%, осталось {max(0, exp - tick)} тиков."
        headline = msg
        world.grant_player_research_points(
            s,
            player_id=player_id,
            amount=1.8,
            tick=tick,
            reason="ruins_anomaly_discovery",
            message=f"+1.8 очков исследования за находку в {place}.",
            payload_extra={"terrain": terrain, "x": x, "y": y, "z": z},
        )
        world._emit_event(
            s,
            tick=tick,
            type="discovery_research_boost",
            message=msg,
            payload={
                "x": x,
                "y": y,
                "z": z,
                "time_multiplier": mult,
                "expires_tick": exp,
                "duration_ticks": duration,
                "source_subtype": subtype,
                "label": subtype_ru,
            },
            player_id=player_id,
        )
        # Полевые данные: архивы руин / данные аномалий.
        if terrain == "ruins":
            add_field_data(
                s,
                player_id=player_id,
                tick=tick,
                kind=EFFECT_RUIN_ARCHIVES,
                source_type=src,
                source_ref=ref,
            )
        else:
            add_field_data(
                s,
                player_id=player_id,
                tick=tick,
                kind=EFFECT_ANOMALY_DATA,
                source_type=src,
                source_ref=ref,
            )
    elif outcome == "cache":
        payload = {"metal_discount_pct": 0.12, "crystal_discount_pct": 0.12}
        upsert_single_blueprint_cache(
            s,
            player_id=player_id,
            tick=tick,
            source_type=src,
            source_ref=ref,
            payload=payload,
        )
        place = "аномалии" if terrain == "anomaly" else "руинах"
        if terrain == "ruins":
            subtype_ru = {
                "archive": "архив",
                "storage": "склад",
                "damaged_beacon": "маяк",
            }.get(subtype, "руины")
            msg = f"В {place} найден {subtype_ru} проектной документации. Следующее исследование дешевле по металлу и кристаллам."
        else:
            subtype_ru = {
                "unstable_field": "поле",
                "signal": "сигнал",
                "trap": "ловушка",
            }.get(subtype, "аномалия")
            msg = f"В {place} обнаружены фрагменты данных ({subtype_ru}). Следующее исследование дешевле по металлу и кристаллам."
        headline = msg
        world._emit_event(
            s,
            tick=tick,
            type="discovery_blueprint_cache",
            message=msg,
            payload={
                "x": x,
                "y": y,
                "z": z,
                **payload,
                "source_subtype": subtype,
                "label": "Кэш чертежей",
            },
            player_id=player_id,
        )
        world.grant_player_research_points(
            s,
            player_id=player_id,
            amount=2.6,
            tick=tick,
            reason="ruins_anomaly_discovery_cache",
            message="+2.6 очков исследования за удачную выгрузку данных.",
            payload_extra={"terrain": terrain, "x": x, "y": y, "z": z},
        )
        # Фрагменты исследований (универсальные).
        add_field_data(
            s,
            player_id=player_id,
            tick=tick,
            kind=EFFECT_RESEARCH_FRAGMENTS,
            source_type=src,
            source_ref=ref,
        )
    else:
        # Не чаще N тиков.
        ambush_cd = 12
        if has_active_ambush_cooldown(s, player_id=player_id, tick=tick):
            # Фолбэк: если засада в кулдауне — выдаём исследовательский бонус.
            duration = 10
            mult = 0.9
            row = upsert_research_speed_boost(
                s,
                player_id=player_id,
                tick=tick,
                source_type=src,
                source_ref=ref,
                time_multiplier=mult,
                duration_ticks=duration,
            )
            exp = (
                int(row.expires_tick)
                if row.expires_tick is not None
                else (tick + duration)
            )
            place = "аномалии" if terrain == "anomaly" else "руинах"
            pct = max(0, int(round((1.0 - float(mult)) * 100)))
            headline = (
                f"В {place} найден повреждённый маяк с телеметрией. Исследования быстрее на {pct}%, "
                f"осталось {max(0, exp - tick)} тиков."
            )
            world._emit_event(
                s,
                tick=tick,
                type="discovery_research_boost",
                message=headline,
                payload={
                    "x": x,
                    "y": y,
                    "z": z,
                    "time_multiplier": mult,
                    "expires_tick": exp,
                    "duration_ticks": duration,
                    "source_subtype": "damaged_beacon",
                    "label": "маяк",
                },
                player_id=player_id,
            )
        else:
            world._spawn_mvp_bandit_patrol_near(s, home_x=int(x), home_y=int(y))
            start_ambush_cooldown(
                s, player_id=player_id, tick=tick, cooldown_ticks=ambush_cd
            )
            place = "аномалии" if terrain == "anomaly" else "руин"
            danger_src = (
                "ловушка"
                if subtype == "trap"
                else "сигнал"
                if subtype == "signal"
                else "маяк"
            )
            headline = (
                f"{danger_src.capitalize()} из {place} привлёк корсаров. "
                "Засада рядом с сектором — будьте готовы к бою."
            )
            world._emit_event(
                s,
                tick=tick,
                type="discovery_bandit_ambush",
                message=headline,
                payload={
                    "x": x,
                    "y": y,
                    "z": z,
                    "cooldown_ticks": ambush_cd,
                    "source_subtype": subtype,
                    "label": "Засада",
                },
                player_id=player_id,
            )
            # Даже в случае засады можно “поднять” пару фрагментов из места.
            add_field_data(
                s,
                player_id=player_id,
                tick=tick,
                kind=EFFECT_RESEARCH_FRAGMENTS,
                source_type=src,
                source_ref=ref,
            )

    s.flush()
    return {
        "ok": True,
        "outcome": outcome,
        "subtype": subtype,
        "terrain": terrain,
        "headline": headline or "Исследование завершено.",
    }
