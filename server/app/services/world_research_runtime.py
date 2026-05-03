"""Множители исследований из world_state (админка), поверх баланса tech.json."""

from __future__ import annotations

import json
import math
from typing import Any


def _tier_key(tier: int) -> tuple[int, str]:
    t = max(1, min(int(tier), 99))
    return t, str(t)


def parse_research_overrides_json(raw: str | None) -> tuple[dict[int, float], dict[int, float]]:
    """Возвращает (time_mult_by_tier, rp_mult_by_tier). Пустые/битые данные → пустые dict."""
    if not raw or not str(raw).strip():
        return {}, {}
    try:
        obj = json.loads(raw)
    except Exception:
        return {}, {}
    if not isinstance(obj, dict):
        return {}, {}
    out_t: dict[int, float] = {}
    out_r: dict[int, float] = {}
    for branch, target in (("time", out_t), ("rp", out_r), ("research_points", out_r)):
        blk = obj.get(branch)
        if not isinstance(blk, dict):
            continue
        for k, v in blk.items():
            try:
                ti = int(k)
            except Exception:
                continue
            if isinstance(v, (int, float)) and float(v) > 0:
                ti = max(1, min(ti, 99))
                target[ti] = float(v)
    return out_t, out_r


def tier_time_multiplier(overrides_json: str | None, *, tier: int) -> float:
    tm, _ = parse_research_overrides_json(overrides_json)
    t, _sk = _tier_key(tier)
    if t in tm:
        return max(0.01, min(float(tm[t]), 100.0))
    return 1.0


def tier_rp_multiplier(overrides_json: str | None, *, tier: int) -> float:
    _, rm = parse_research_overrides_json(overrides_json)
    t, _sk = _tier_key(tier)
    if t in rm:
        return max(0.01, min(float(rm[t]), 100.0))
    return 1.0


def apply_tier_to_residual_ticks(*, residual: int, tier_time_mult: float) -> int:
    base = max(1, int(residual))
    m = float(tier_time_mult)
    if m <= 0:
        m = 1.0
    return max(1, int(math.ceil(base * m)))


def apply_tier_to_rp_cost(*, rp_need: float, tier_rp_mult: float) -> float:
    m = float(tier_rp_mult)
    if m <= 0:
        m = 1.0
    return max(0.0, float(rp_need) * m)


def serialize_research_overrides_from_maps(
    time_by_tier: dict[int, float], rp_by_tier: dict[int, float]
) -> str | None:
    """Если всё по сути 1.0 — возвращает None (очистить колонку)."""
    tj: dict[str, float] = {}
    rj: dict[str, float] = {}
    for t, v in sorted(time_by_tier.items()):
        if abs(float(v) - 1.0) > 1e-9:
            tj[str(int(t))] = float(v)
    for t, v in sorted(rp_by_tier.items()):
        if abs(float(v) - 1.0) > 1e-9:
            rj[str(int(t))] = float(v)
    if not tj and not rj:
        return None
    out: dict[str, Any] = {}
    if tj:
        out["time"] = tj
    if rj:
        out["rp"] = rj
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))
