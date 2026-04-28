from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TravelPlan:
    distance: int
    travel_ticks: int


@dataclass(frozen=True)
class UpkeepPlan:
    energy_per_tick: int
    fleet_units: int


@dataclass(frozen=True)
class ProductionPlan:
    metal_per_tick: int
    crystal_per_tick: int
    energy_per_tick: int
    fuel_per_tick: int


@dataclass(frozen=True)
class FuelPlan:
    fuel_cost: int


def manhattan_distance(*, from_x: int, from_y: int, to_x: int, to_y: int) -> int:
    return abs(to_x - from_x) + abs(to_y - from_y)


def calc_travel_plan(*, from_x: int, from_y: int, to_x: int, to_y: int, unit_type: str = "scout") -> TravelPlan:
    # MVP: базовая формула. Дальше можно подключить скорость юнита/terrain/форпосты.
    dist = manhattan_distance(from_x=from_x, from_y=from_y, to_x=to_x, to_y=to_y)
    travel_ticks = max(1, dist)
    return TravelPlan(distance=dist, travel_ticks=travel_ticks)


def calc_upkeep(*, fleet_units: int) -> UpkeepPlan:
    # MVP: 1 energy за 1 корабль за тик.
    energy_per_tick = max(0, int(fleet_units))
    return UpkeepPlan(energy_per_tick=energy_per_tick, fleet_units=int(fleet_units))


def calc_planet_production(*, planet_level: int = 1) -> ProductionPlan:
    # MVP: фиксированная выработка на тик для стартовой планеты.
    # Дальше сюда добавятся здания/форпосты/модификаторы.
    lvl = max(1, int(planet_level))
    return ProductionPlan(metal_per_tick=6 * lvl, crystal_per_tick=3 * lvl, energy_per_tick=2 * lvl, fuel_per_tick=2 * lvl)


def calc_fuel_cost(*, distance: int, qty: int, unit_type: str = "scout") -> FuelPlan:
    # MVP: 1 fuel за 1 клетку за 1 корабль.
    # Позже: модификаторы по типу флота/terrain/технологиям.
    d = max(0, int(distance))
    q = max(1, int(qty))
    return FuelPlan(fuel_cost=d * q)

