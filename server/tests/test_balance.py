import uuid
from pathlib import Path

import pytest

from app.services.balance_service import BalanceError, BalanceService, load_balance_pack
from app.services.player_research_effects import adjusted_research_duration_ticks
from app.services.world_service import WorldService
from app.db.models.planet import Planet


def test_balance_pack_loads_from_repo_default_path():
    base = Path(__file__).resolve().parents[1] / "data" / "balance"
    svc = BalanceService.load_from_path(base)
    assert svc.balance_schema_version() == 1
    bp = svc.get_base_production()
    assert bp["metal"] > 0
    assert "food" in bp and "water" in bp
    eco = svc.pack.economy
    assert isinstance(eco.get("population_maintenance"), dict)
    assert isinstance(eco.get("supply_route_upkeep"), dict)
    assert isinstance(eco.get("fleet_empire_upkeep"), dict)
    assert isinstance(eco.get("research_points"), dict)
    assert isinstance(eco.get("npc_transit"), dict)
    assert svc.pack.tech_by_id.get("tech_supply_networks_1") is not None
    assert svc.pack.tech_by_id.get("tech_deep_scan_1") is not None
    assert svc.pack.buildings_by_id.get("logistics_center_t1") is not None

    ws = WorldService(balance=svc)
    assert ws._fleet_empire_upkeep_unpaid_penalty_energy() >= 0


def test_supply_route_logistics_costs_use_manhattan_extras():
    base = Path(__file__).resolve().parents[1] / "data" / "balance"
    svc = BalanceService.load_from_path(base)
    ws = WorldService(balance=svc)

    # Подменим экстра-стоимость, чтобы тест был стабильным.
    svc.pack.economy["supply_route_upkeep"]["food_per_sol_per_outpost"] = 2
    svc.pack.economy["supply_route_upkeep"]["water_per_sol_per_outpost"] = 2
    svc.pack.economy["supply_route_upkeep"]["food_per_manhattan_from_hub"] = 1
    svc.pack.economy["supply_route_upkeep"]["water_per_manhattan_from_hub"] = 2

    hub = Planet(pos_x=10, pos_y=10, owner_player_id=uuid.uuid4(), name="Hub", population=800, max_population=5000)
    food, water = ws._supply_route_logistics_costs(hub=hub, ox=13, oy=12)  # d=5
    assert food == 2 + 1 * 5
    assert water == 2 + 2 * 5


def test_fleet_empire_upkeep_costs_default_is_per_fleet():
    base = Path(__file__).resolve().parents[1] / "data" / "balance"
    svc = BalanceService.load_from_path(base)
    ws = WorldService(balance=svc)

    # Значения по умолчанию: 1 металл + 1 кристалл за флот, per_ship=0.
    c = ws._fleet_empire_upkeep_costs(fleets=3, ships=99)
    assert c["metal"] == 3
    assert c["crystal"] == 3


def test_supplier_unit_definition_exists():
    base = Path(__file__).resolve().parents[1] / "data" / "balance"
    svc = BalanceService.load_from_path(base)
    u = svc.get_unit("supplier_t1")
    assert u.get("id") == "supplier_t1"


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


def test_adjusted_research_duration_ticks():
    assert adjusted_research_duration_ticks(base_ticks=10, time_multiplier=0.5) == 5
    assert adjusted_research_duration_ticks(base_ticks=10, time_multiplier=0.85) == 9


def test_expansionist_race_in_balance_pack():
    base = Path(__file__).resolve().parents[1] / "data" / "balance"
    svc = BalanceService.load_from_path(base)
    ex = svc.pack.races_by_id.get("expansionist")
    assert isinstance(ex, dict)
    mods = ex.get("modifiers") or {}
    assert float(mods.get("influence_multiplier", 0)) > 1.0
    assert float(mods.get("supply_route_upkeep_multiplier", 0)) > 1.0
    assert float(mods.get("fleet_unsupplied_energy_decay_multiplier", 0)) > 1.0


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
    assert "tech_hydroponics_1" in svc.pack.tech_by_id
    assert "tech_atmospheric_water_1" in svc.pack.tech_by_id


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
    hf = svc.get_building("hydro_farm")
    assert hf.get("effects", {}).get("production_per_tick_add", {}).get("food") == 3

