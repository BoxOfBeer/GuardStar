"""Слияние economy base + admin patch."""

from app.services.world_economy_runtime import deep_merge_eco


def test_deep_merge_eco_nested_and_scalar():
    base = {
        "a": 1,
        "bandit_wilderness": {"every_n_ticks": 15, "chunk_side": 10},
        "npc_transit": {"spawn_attempts": 48},
    }
    patch = {
        "a": 2,
        "bandit_wilderness": {"every_n_ticks": 3},
        "extra": {"x": 1},
    }
    out = deep_merge_eco(base, patch)
    assert out["a"] == 2
    assert out["bandit_wilderness"]["every_n_ticks"] == 3
    assert out["bandit_wilderness"]["chunk_side"] == 10
    assert out["npc_transit"]["spawn_attempts"] == 48
    assert out["extra"]["x"] == 1
    assert base["a"] == 1
