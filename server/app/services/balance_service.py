from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


class BalanceError(RuntimeError):
    pass


class BalanceService:
    def __init__(self, *, pack: BalancePack):
        self.pack = pack

    @classmethod
    def load_from_path(cls, base_dir: Path) -> "BalanceService":
        return cls(pack=load_balance_pack(base_dir=base_dir))

    def balance_schema_version(self) -> int:
        v = self.pack.meta.get("schema_version")
        return int(v) if isinstance(v, int) else 0

    def balance_pack_id(self) -> str | None:
        # meta.json может содержать pack_id (если нет — None)
        v = self.pack.meta.get("pack_id")
        return str(v) if isinstance(v, str) and v.strip() else None

    def balance_pack_name(self) -> str | None:
        v = self.pack.meta.get("name")
        return str(v) if isinstance(v, str) and v.strip() else None

    def _resolve_unit_id(self, unit_type: str) -> str:
        aliases = self.pack.aliases.get("unit_aliases") if isinstance(self.pack.aliases, dict) else {}
        if isinstance(aliases, dict) and unit_type in aliases:
            return str(aliases[unit_type])
        return unit_type

    def _resolve_building_id(self, building_type: str) -> str:
        aliases = self.pack.aliases.get("building_aliases") if isinstance(self.pack.aliases, dict) else {}
        if isinstance(aliases, dict) and building_type in aliases:
            return str(aliases[building_type])
        return building_type

    def get_unit(self, unit_type: str) -> dict:
        uid = self._resolve_unit_id(unit_type)
        unit = self.pack.units_by_id.get(uid)
        if not unit:
            raise BalanceError(f"unknown_unit: unit_type={unit_type} resolved_id={uid}")
        return unit

    def get_building(self, building_type: str) -> dict:
        bid = self._resolve_building_id(building_type)
        b = self.pack.buildings_by_id.get(bid)
        if not b:
            raise BalanceError(f"unknown_building: building_type={building_type} resolved_id={bid}")
        return b

    def get_outpost(self, outpost_type: str) -> dict:
        outpost = self.pack.outposts_by_id.get(outpost_type)
        if not outpost:
            raise BalanceError(f"unknown_outpost: outpost_type={outpost_type}")
        return outpost

    def get_outpost_module(self, module_id: str) -> dict:
        mod = self.pack.outpost_modules_by_id.get(module_id)
        if not mod:
            raise BalanceError(f"unknown_outpost_module: module_id={module_id}")
        return mod

    def get_race(self, race_id: str) -> dict:
        r = self.pack.races_by_id.get(race_id)
        if not r:
            raise BalanceError(f"unknown_race: race_id={race_id}")
        return r

    def get_base_production(self) -> dict:
        base = self.pack.economy.get("base_planet_production") if isinstance(self.pack.economy, dict) else None
        if not isinstance(base, dict):
            raise BalanceError("economy_missing_base_planet_production")
        keys = ("metal", "crystal", "energy", "fuel", "food", "water")
        return {k: int(base.get(k, 0)) for k in keys}

    def calc_unit_upkeep(self, *, unit_type: str, qty: int, race_id: str | None, techs: list[str] | None) -> dict:
        u = self.get_unit(unit_type)
        upkeep = u.get("upkeep") if isinstance(u.get("upkeep"), dict) else {}
        base_energy = int(upkeep.get("energy", 0)) * max(0, int(qty))

        mult = 1.0
        if race_id:
            mods = (self.get_race(race_id).get("modifiers") if isinstance(self.get_race(race_id), dict) else {}) or {}
            if isinstance(mods, dict):
                mult *= float(mods.get("upkeep_energy_multiplier", 1.0))

        # tech modifiers
        if techs:
            for tid in techs:
                t = self.pack.tech_by_id.get(tid)
                eff = t.get("effects") if isinstance(t, dict) else None
                if isinstance(eff, dict) and "upkeep_energy_multiplier" in eff:
                    mult *= float(eff.get("upkeep_energy_multiplier", 1.0))

        val = float(base_energy) * float(mult)
        # Для расходов лучше округлять вверх, чтобы модификаторы ощущались и не давали «бесплатных» дробей.
        return {"energy": int(math.ceil(val)) if val > 0 else 0}

    def calc_travel_cost(
        self,
        *,
        unit_type: str,
        qty: int,
        distance: int,
        race_id: str | None,
        techs: list[str] | None,
    ) -> dict:
        u = self.get_unit(unit_type)
        per_cell = int(u.get("travel_fuel_per_cell", 1)) if isinstance(u, dict) else 1
        base = max(0, int(distance)) * max(0, int(qty)) * max(1, per_cell)

        mult = 1.0
        if race_id:
            mods = (self.get_race(race_id).get("modifiers") if isinstance(self.get_race(race_id), dict) else {}) or {}
            if isinstance(mods, dict):
                mult *= float(mods.get("travel_fuel_multiplier", 1.0))

        # tech modifiers
        if techs:
            for tid in techs:
                t = self.pack.tech_by_id.get(tid)
                eff = t.get("effects") if isinstance(t, dict) else None
                if isinstance(eff, dict) and "travel_fuel_multiplier" in eff:
                    mult *= float(eff.get("travel_fuel_multiplier", 1.0))

        val = float(base) * float(mult)
        return {"fuel": int(math.ceil(val)) if val > 0 else 0}

    def calc_travel_plan(self, *, unit_type: str, distance: int) -> dict:
        u = self.get_unit(unit_type)
        speed = int(u.get("speed_cells_per_tick", 1))
        speed = max(1, speed)
        d = max(0, int(distance))
        travel_ticks = max(1, int(math.ceil(d / speed))) if d > 0 else 0
        return {"distance": d, "travel_ticks": travel_ticks}

@dataclass(frozen=True)
class BalancePack:
    meta: dict
    resources: list[str]
    economy: dict
    aliases: dict
    units_by_id: dict[str, dict]
    buildings_by_id: dict[str, dict]
    outposts_by_id: dict[str, dict]
    outpost_modules_by_id: dict[str, dict]
    races_by_id: dict[str, dict]
    tech_by_id: dict[str, dict]


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise BalanceError(f"Не удалось прочитать {path}: {e!r}")


def _require_id_map(items: list[dict], *, kind: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for it in items:
        if not isinstance(it, dict):
            raise BalanceError(f"{kind}: элемент должен быть object")
        _id = it.get("id")
        if not isinstance(_id, str) or not _id.strip():
            raise BalanceError(f"{kind}: у элемента нет корректного id")
        if _id in out:
            raise BalanceError(f"{kind}: дублирующийся id={_id}")
        out[_id] = it
    return out


def _validate_meta(meta: dict) -> None:
    if not isinstance(meta, dict):
        raise BalanceError("meta.json должен быть object")
    v = meta.get("schema_version")
    if v != 1:
        raise BalanceError(f"Неподдерживаемая schema_version={v}, ожидаю 1")


def _validate_resources(res: dict) -> list[str]:
    resources = res.get("resources")
    if not isinstance(resources, list) or not all(isinstance(x, str) for x in resources):
        raise BalanceError("resources.json: ожидаю resources: [string]")
    if len(set(resources)) != len(resources):
        raise BalanceError("resources.json: ресурсы не должны повторяться")
    return resources


def _validate_tech_dag(tech_by_id: dict[str, dict]) -> None:
    # DAG check by DFS colors
    color: dict[str, int] = {k: 0 for k in tech_by_id.keys()}  # 0=unseen,1=visiting,2=done

    def dfs(tid: str) -> None:
        c = color.get(tid, 0)
        if c == 1:
            raise BalanceError(f"tech: найден цикл, узел {tid}")
        if c == 2:
            return
        color[tid] = 1
        prereq = tech_by_id[tid].get("prereq", [])
        if prereq is None:
            prereq = []
        if not isinstance(prereq, list) or not all(isinstance(x, str) for x in prereq):
            raise BalanceError(f"tech: prereq у {tid} должен быть [string]")
        for p in prereq:
            if p not in tech_by_id:
                raise BalanceError(f"tech: prereq {p} у {tid} не существует")
            dfs(p)
        color[tid] = 2

    for tid in tech_by_id.keys():
        if color[tid] == 0:
            dfs(tid)


def load_balance_pack(*, base_dir: Path) -> BalancePack:
    meta = _read_json(base_dir / "meta.json")
    _validate_meta(meta)

    resources_doc = _read_json(base_dir / "resources.json")
    resources = _validate_resources(resources_doc)

    economy_doc = _read_json(base_dir / "economy.json")
    if not isinstance(economy_doc, dict) or not isinstance(economy_doc.get("base_planet_production"), dict):
        raise BalanceError("economy.json: ожидаю base_planet_production (metal,crystal,energy,fuel,food,water)")
    base_prod = economy_doc.get("base_planet_production", {})
    for k in ("metal", "crystal", "energy", "fuel", "food", "water"):
        if k not in base_prod or not isinstance(base_prod.get(k), (int, float)):
            raise BalanceError(f"economy.json: base_planet_production.{k} должен быть числом")

    aliases_doc = _read_json(base_dir / "aliases.json") if (base_dir / "aliases.json").exists() else {}
    if aliases_doc and not isinstance(aliases_doc, dict):
        raise BalanceError("aliases.json: ожидаю object")
    unit_aliases = aliases_doc.get("unit_aliases", {}) if isinstance(aliases_doc, dict) else {}
    building_aliases = aliases_doc.get("building_aliases", {}) if isinstance(aliases_doc, dict) else {}
    if not isinstance(unit_aliases, dict) or not isinstance(building_aliases, dict):
        raise BalanceError("aliases.json: unit_aliases/building_aliases должны быть object")

    units_doc = _read_json(base_dir / "units.json")
    units = units_doc.get("units", [])
    if not isinstance(units, list):
        raise BalanceError("units.json: ожидаю units: []")
    units_by_id = _require_id_map(units, kind="units")

    buildings_doc = _read_json(base_dir / "buildings.json")
    buildings = buildings_doc.get("buildings", [])
    if not isinstance(buildings, list):
        raise BalanceError("buildings.json: ожидаю buildings: []")
    buildings_by_id = _require_id_map(buildings, kind="buildings")

    outposts_doc = _read_json(base_dir / "outposts.json") if (base_dir / "outposts.json").exists() else {"outposts": []}
    outposts = outposts_doc.get("outposts", [])
    if not isinstance(outposts, list):
        raise BalanceError("outposts.json: ожидаю outposts: []")
    outposts_by_id = _require_id_map(outposts, kind="outposts")

    modules_doc = (
        _read_json(base_dir / "outpost_modules.json") if (base_dir / "outpost_modules.json").exists() else {"outpost_modules": []}
    )
    outpost_modules = modules_doc.get("outpost_modules", [])
    if not isinstance(outpost_modules, list):
        raise BalanceError("outpost_modules.json: ожидаю outpost_modules: []")
    outpost_modules_by_id = _require_id_map(outpost_modules, kind="outpost_modules")

    # validate aliases -> ids exist
    for k, v in unit_aliases.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise BalanceError("aliases.json: unit_aliases должен быть {string:string}")
        if v not in units_by_id:
            raise BalanceError(f"aliases.json: unit_aliases[{k}]={v} не найден в units")
    for k, v in building_aliases.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise BalanceError("aliases.json: building_aliases должен быть {string:string}")
        if v not in buildings_by_id:
            raise BalanceError(f"aliases.json: building_aliases[{k}]={v} не найден в buildings")

    races_doc = _read_json(base_dir / "races.json")
    races = races_doc.get("races", [])
    if not isinstance(races, list):
        raise BalanceError("races.json: ожидаю races: []")
    races_by_id = _require_id_map(races, kind="races")

    tech_doc = _read_json(base_dir / "tech.json")
    tech = tech_doc.get("tech", [])
    if not isinstance(tech, list):
        raise BalanceError("tech.json: ожидаю tech: []")
    tech_by_id = _require_id_map(tech, kind="tech")
    _validate_tech_dag(tech_by_id)

    return BalancePack(
        meta=meta,
        resources=resources,
        economy=economy_doc,
        aliases={"unit_aliases": unit_aliases, "building_aliases": building_aliases},
        units_by_id=units_by_id,
        buildings_by_id=buildings_by_id,
        outposts_by_id=outposts_by_id,
        outpost_modules_by_id=outpost_modules_by_id,
        races_by_id=races_by_id,
        tech_by_id=tech_by_id,
    )


def default_balance_dir() -> Path:
    # server/app/services/balance_service.py -> server/data/balance
    return Path(__file__).resolve().parents[2] / "data" / "balance"

