import uuid
from pathlib import Path

import pytest

from app.services.balance_service import BalanceError, BalanceService, load_balance_pack
from app.services.world_service import WorldService


def test_balance_pack_loads_from_repo_default_path():
    base = Path(__file__).resolve().parents[1] / "data" / "balance"
    svc = BalanceService.load_from_path(base)
    assert svc.balance_schema_version() == 1
    assert svc.get_base_production()["metal"] > 0


def test_unknown_unit_building_errors_are_readable():
    base = Path(__file__).resolve().parents[1] / "data" / "balance"
    svc = BalanceService.load_from_path(base)
    with pytest.raises(BalanceError) as e:
        svc.get_unit("no_such_unit_type")
    assert "unknown_unit" in str(e.value)

    with pytest.raises(BalanceError) as e2:
        svc.get_building("no_such_building_type")
    assert "unknown_building" in str(e2.value)


def test_scout_and_fighter_have_different_upkeep_and_fuel():
    base = Path(__file__).resolve().parents[1] / "data" / "balance"
    svc = BalanceService.load_from_path(base)

    up_scout = svc.calc_unit_upkeep(unit_type="scout", qty=2, race_id=None, techs=None)["energy"]
    up_fighter = svc.calc_unit_upkeep(unit_type="fighter", qty=2, race_id=None, techs=None)["energy"]
    assert up_fighter != up_scout

    fuel_scout = svc.calc_travel_cost(unit_type="scout", qty=2, distance=5, race_id=None, techs=None)["fuel"]
    fuel_fighter = svc.calc_travel_cost(unit_type="fighter", qty=2, distance=5, race_id=None, techs=None)["fuel"]
    assert fuel_fighter != fuel_scout


def test_race_modifiers_affect_costs_and_production():
    base = Path(__file__).resolve().parents[1] / "data" / "balance"
    pack = load_balance_pack(base_dir=base)
    svc = BalanceService(pack=pack)

    # zenith: travel_fuel_multiplier=1.15, upkeep_energy_multiplier=1.25 (from races.json in repo)
    fuel_h = svc.calc_travel_cost(unit_type="scout", qty=1, distance=10, race_id="human", techs=None)["fuel"]
    fuel_z = svc.calc_travel_cost(unit_type="scout", qty=1, distance=10, race_id="zenith", techs=None)["fuel"]
    assert fuel_z > fuel_h

    up_h = svc.calc_unit_upkeep(unit_type="fighter", qty=1, race_id="human", techs=None)["energy"]
    up_z = svc.calc_unit_upkeep(unit_type="fighter", qty=1, race_id="zenith", techs=None)["energy"]
    assert up_z > up_h

    base_prod = svc.get_base_production()
    assert base_prod["metal"] == 6


def test_influence_helpers_decay_and_multiplier():
    ws = WorldService(balance=None)
    pid = uuid.uuid4()
    src = [{"owner": pid, "x": 0, "y": 0, "z": 0, "w": 1.0, "r": 40}]
    at = ws._influence_scores_at(src, 0, 0, 0)
    assert at[pid] == 1.0
    # В радиусе 3 — гарантированная сила 1.0.
    at_base = ws._influence_scores_at(src, 0, 3, 0)
    assert at_base[pid] == 1.0
    # Дальше /2 за клетку: 4 -> 0.5, 5 -> 0.25.
    at_4 = ws._influence_scores_at(src, 0, 4, 0)
    assert at_4[pid] == 0.5
    at_5 = ws._influence_scores_at(src, 0, 5, 0)
    assert at_5[pid] == 0.25
    at_edge = ws._influence_scores_at(src, 0, 40, 0)
    assert at_edge.get(pid, 0) > 0.0
    oid = uuid.uuid4()
    oid2 = uuid.uuid4()
    mul = WorldService._planet_influence_production_multiplier({oid: 50.0, oid2: 50.0}, oid)
    assert 0.88 <= mul <= 1.12


def test_influence_control_accumulates_with_decay_and_opposition():
    # Без соперника: 0.21 - 0.1 = +0.11 за тик -> >1 примерно за 10 тиков.
    v = 0.0
    for _ in range(10):
        v = WorldService._influence_next_control_value(v, 0.21, 0.0)
    assert v > 1.0

    # При 0.2 против 0.1: 0.2 - 0.1 - 0.1 = 0 => владение не растёт.
    v2 = 0.0
    for _ in range(8):
        v2 = WorldService._influence_next_control_value(v2, 0.2, 0.1)
    assert v2 == 0.0


def test_influence_decay_has_building_whitelist_guard():
    ws_path = Path(__file__).resolve().parents[1] / "app" / "services" / "world_service.py"
    txt = ws_path.read_text(encoding="utf-8")
    assert "INFLUENCE_BUILDING_TYPES" in txt


def test_balance_contains_outposts_and_territory_techs():
    base = Path(__file__).resolve().parents[1] / "data" / "balance"
    svc = BalanceService.load_from_path(base)
    assert svc.get_outpost("outpost_t1")["id"] == "outpost_t1"
    assert svc.get_outpost("outpost_t2")["id"] == "outpost_t2"
    assert svc.get_outpost("outpost_t3")["id"] == "outpost_t3"
    assert svc.get_outpost_module("module_radar_t1")["id"] == "module_radar_t1"
    assert "tech_territory_2" in svc.pack.tech_by_id
    assert "tech_territory_3" in svc.pack.tech_by_id


def test_get_sector_stub_regression_guard_no_pobj_typo():
    # Regression guard: раньше в get_sector_stub было pobj.owner_player_id (NameError).
    ws_path = Path(__file__).resolve().parents[1] / "app" / "services" / "world_service.py"
    txt = ws_path.read_text(encoding="utf-8")
    assert "pobj.owner_player_id" not in txt


def test_building_foundation_terrain_rules_present():
    base = Path(__file__).resolve().parents[1] / "data" / "balance"
    svc = BalanceService.load_from_path(base)
    mine = svc.get_building("mine")
    assert "build_on_terrain" in mine
    assert "asteroids" in mine["build_on_terrain"]
    crystal_farm = svc.get_building("crystal_farm")
    assert "build_on_terrain" in crystal_farm
    assert "asteroids" in crystal_farm["build_on_terrain"]
    reactor = svc.get_building("reactor")
    assert "empty" in reactor["build_on_terrain"]
    drydock = svc.get_building("drydock_mini")
    assert "empty" in drydock["build_on_terrain"]
    sensor = svc.get_building("sensor_mast")
    assert "anomaly" in sensor["build_on_terrain"]
    habitat = svc.get_building("habitat")
    assert "build_on_terrain" in habitat
    assert "empty" not in habitat["build_on_terrain"]

