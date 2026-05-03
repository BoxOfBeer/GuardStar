"""Слияние `economy.json` с админскими переопределениями (`world_state.admin_economy_overrides_json`)."""

from __future__ import annotations

import copy
from typing import Any


def deep_merge_eco(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Рекурсивное объединение: значения из ``patch`` перекрывают ``base``."""
    out: dict[str, Any] = copy.deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge_eco(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out
