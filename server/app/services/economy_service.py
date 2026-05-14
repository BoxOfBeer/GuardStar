from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.building import Building
from app.db.models.fleet import Fleet
from app.db.models.outpost import Outpost
from app.db.models.planet import Planet
from app.db.models.player import Player
from app.db.models.resource import Resource


@dataclass(frozen=True)
class ResearchPointsInfo:
    balance: float
    per_sol: float


def _runway_approx_sols(stock: int, net_per_sol: int) -> tuple[str, int | None]:
    """Грубая оценка «хватит на N солов» по запасам империи и чистому потоку за сол."""
    st = max(0, int(stock))
    n = int(net_per_sol)
    if n >= 0:
        return "surplus", None
    loss = -n
    if loss <= 0:
        return "surplus", None
    return "drain", int(math.floor(st / loss))


class EconomyService:
    """Экономика империи (MVP): агрегации для UI и RP-инфо.

    Примечание: производство/списания в тике остаются в `WorldService.process_next_tick`,
    этот сервис — тонкий слой для расчётов и вынесения логики из монолита.
    """

    def __init__(self, *, world: object) -> None:
        self._world = world

    def _player_rp_info(
        self, s: Session, *, player_id: uuid.UUID
    ) -> ResearchPointsInfo:
        pl = s.get(Player, player_id)
        bal = 0.0
        if pl is not None:
            try:
                bal = float(getattr(pl, "research_points", 0) or 0)
            except Exception:
                bal = float(getattr(pl, "research_points", 0) or 0)

        per = 0.0
        bal_svc = getattr(self._world, "_balance", None)
        if bal_svc and isinstance(getattr(bal_svc, "pack", None), object):
            eco = bal_svc.pack.economy if isinstance(bal_svc.pack.economy, dict) else {}
            rp_cfg = (
                eco.get("research_points")
                if isinstance(eco.get("research_points"), dict)
                else {}
            )
            base_h = float(rp_cfg.get("home_capital_per_sol", 0.1))
            lab_h = float(rp_cfg.get("research_lab_t1_per_sol", 0.1))
            labs = int(
                getattr(self._world, "_count_player_research_labs")(s, player_id)
            )
            per = base_h + float(labs) * lab_h

        return ResearchPointsInfo(balance=bal, per_sol=per)

    def get_economy_summary(
        self,
        s: Session,
        *,
        player_id: str,
        include_external_buildings: bool = True,
        influence_sources: list[dict] | None = None,
        for_hud_poll: bool = False,
    ) -> dict:
        """Сводка доходов/расходов по империи за один сол для UI.

        ``for_hud_poll=True`` — только потоки ``net_per_sol`` / ``net_home_per_sol`` (без
        справочных затрат на «восстановление» построек/флота и без лишних агрегатов казны):
        для частого ``GET /api/world/state``.
        """
        pid = uuid.UUID(player_id)
        ws = getattr(self._world, "get_or_create_world_state")(s)
        tick = int(getattr(ws, "current_tick", 0) or 0)

        home = s.execute(
            select(Planet)
            .where(Planet.owner_player_id == pid)
            .order_by(Planet.created_at.asc())
        ).scalar_one_or_none()
        if not for_hud_poll:
            res = (
                s.execute(
                    select(Resource).where(Resource.planet_id == home.id)
                ).scalar_one_or_none()
                if home
                else None
            )
            treasury_home = {
                "metal": int(getattr(res, "metal", 0) or 0),
                "crystal": int(getattr(res, "crystal", 0) or 0),
                "energy": int(getattr(res, "energy", 0) or 0),
                "fuel": int(getattr(res, "fuel", 0) or 0),
                "food": int(getattr(res, "food", 0) or 0),
                "water": int(getattr(res, "water", 0) or 0),
            }
        else:
            treasury_home = {
                "metal": 0,
                "crystal": 0,
                "energy": 0,
                "fuel": 0,
                "food": 0,
                "water": 0,
            }

        planets = (
            s.execute(select(Planet).where(Planet.owner_player_id == pid))
            .scalars()
            .all()
        )
        treasury_empire = {
            "metal": 0,
            "crystal": 0,
            "energy": 0,
            "fuel": 0,
            "food": 0,
            "water": 0,
        }
        if not for_hud_poll:
            for p in planets:
                rr = s.execute(
                    select(Resource).where(Resource.planet_id == p.id)
                ).scalar_one_or_none()
                if not rr:
                    continue
                treasury_empire["metal"] += int(getattr(rr, "metal", 0) or 0)
                treasury_empire["crystal"] += int(getattr(rr, "crystal", 0) or 0)
                treasury_empire["energy"] += int(getattr(rr, "energy", 0) or 0)
                treasury_empire["fuel"] += int(getattr(rr, "fuel", 0) or 0)
                treasury_empire["food"] += int(getattr(rr, "food", 0) or 0)
                treasury_empire["water"] += int(getattr(rr, "water", 0) or 0)

        outposts = (
            s.execute(select(Outpost).where(Outpost.owner_player_id == pid))
            .scalars()
            .all()
        )
        fleets = (
            s.execute(select(Fleet).where(Fleet.owner_player_id == pid)).scalars().all()
        )

        inf_src = (
            influence_sources
            if influence_sources is not None
            else getattr(self._world, "_collect_influence_sources")(s)
        )

        PLANET_STORE_KEYS = getattr(
            self._world,
            "PLANET_STORE_KEYS",
            ("metal", "crystal", "energy", "fuel", "food", "water"),
        )
        prod_sum = {k: 0 for k in PLANET_STORE_KEYS}
        pop_need = {"food": 0, "water": 0}
        planet_rows: list[dict] = []
        for p in planets:
            dlt = getattr(self._world, "_planet_production_deltas")(
                s, planet=p, influence_sources=inf_src
            )
            for k in PLANET_STORE_KEYS:
                prod_sum[k] += int(dlt.get(k, 0) or 0)
            pop = int(getattr(p, "population", 0) or 0)
            pf, pw = getattr(self._world, "_population_vitals_upkeep_needs")(
                population=pop
            )
            pop_need["food"] += int(pf)
            pop_need["water"] += int(pw)
            if not for_hud_poll:
                planet_rows.append(
                    {
                        "planet_id": str(p.id),
                        "name": p.name,
                        "pos": {"x": int(p.pos_x), "y": int(p.pos_y)},
                        "population": pop,
                        "production_per_sol": {
                            k: int(dlt.get(k, 0) or 0) for k in PLANET_STORE_KEYS
                        },
                        "population_upkeep_per_sol": {"food": int(pf), "water": int(pw)},
                    }
                )

        logistics = {"food": 0, "water": 0, "outposts_count": 0}
        for op in outposts:
            if int(getattr(op, "z", 0) or 0) != 0:
                continue
            if getattr(op, "status", "") != "active":
                continue
            if getattr(self._world, "_cell_is_owned_planet_tile")(
                s, owner_id=pid, x=int(op.x), y=int(op.y), z=0
            ):
                continue
            if not getattr(self._world, "_is_cell_supplied")(
                s, owner_id=pid, x=int(op.x), y=int(op.y), z=int(op.z)
            ):
                continue
            hub = getattr(self._world, "_supply_hub_planet_for_cell")(
                s, owner_id=pid, x=int(op.x), y=int(op.y), z=int(op.z)
            )
            if not hub:
                continue
            lvl = max(1, int(getattr(op, "level", 1) or 1))
            cap = min(lvl, 3)
            tier_mult = float(2 ** (cap - 1))
            need_f, need_w = getattr(self._world, "_supply_route_logistics_costs")(
                hub=hub,
                ox=int(op.x),
                oy=int(op.y),
                outpost_supply_tier_multiplier=tier_mult,
            )
            logistics["food"] += int(need_f)
            logistics["water"] += int(need_w)
            logistics["outposts_count"] += 1

        outpost_upkeep = {
            "metal": 0,
            "crystal": 0,
            "energy": 0,
            "fuel": 0,
            "outposts_count": 0,
        }
        for op in outposts:
            if getattr(op, "status", "") not in ("active", "offline"):
                continue
            try:
                od = getattr(self._world, "_outpost_definition")(
                    str(getattr(op, "outpost_type", "") or "")
                )
            except Exception:
                od = {}
            upkeep = (
                od.get("upkeep_per_tick")
                if isinstance(od.get("upkeep_per_tick"), dict)
                else {}
            )
            for k in ("metal", "crystal", "energy", "fuel"):
                outpost_upkeep[k] += int(upkeep.get(k, 0) or 0)
            outpost_upkeep["outposts_count"] += 1

        fleet_count = 0
        ships_total = 0
        upkeep_energy = 0
        empire_fleet_upkeep = {"metal": 0, "crystal": 0, "food": 0, "water": 0}
        for f in fleets:
            if getattr(self._world, "_fleet_total_units")(s, f) <= 0:
                continue
            fleet_count += 1
            um = getattr(self._world, "_fleet_units_map")(s, f)
            ships_total += sum(int(v) for v in um.values())
            upkeep_energy += (
                getattr(self._world, "_fleet_upkeep_energy_total")(
                    s, player_id=pid, units=um
                )
                if um
                else 0
            )
            part = getattr(self._world, "_fleet_empire_supply_need_for_fleet")(
                s, fleet=f
            )
            for k in empire_fleet_upkeep:
                empire_fleet_upkeep[k] += int(part.get(k, 0) or 0)

        if for_hud_poll:
            buildings: list[Building] = []
            ext_buildings = 0
            planet_buildings = 0
        else:
            buildings = (
                s.execute(select(Building).where(Building.owner_player_id == pid))
                .scalars()
                .all()
            )
            ext_buildings = 0
            planet_buildings = 0
            cell_planet_fn = getattr(self._world, "_cell_has_planet", None)
            for b in buildings:
                on_planet_tile = (
                    cell_planet_fn(s, x=int(b.x), y=int(b.y), z=int(b.z))
                    if callable(cell_planet_fn)
                    else False
                )
                if on_planet_tile:
                    planet_buildings += 1
                else:
                    ext_buildings += 1

        net = {k: int(prod_sum.get(k, 0) or 0) for k in PLANET_STORE_KEYS}
        net["food"] -= int(pop_need["food"])
        net["water"] -= int(pop_need["water"])
        net["food"] -= int(logistics["food"])
        net["water"] -= int(logistics["water"])
        for k in ("metal", "crystal", "food", "water"):
            net[k] -= int(empire_fleet_upkeep.get(k, 0) or 0)
        net["energy"] -= int(upkeep_energy)
        for k in ("metal", "crystal", "energy", "fuel"):
            net[k] -= int(outpost_upkeep.get(k, 0) or 0)

        expenses_aggregate_per_sol = (
            {
                k: int(prod_sum.get(k, 0) or 0) - int(net.get(k, 0) or 0)
                for k in PLANET_STORE_KEYS
            }
            if not for_hud_poll
            else {}
        )

        net_home = {
            "metal": 0,
            "crystal": 0,
            "energy": 0,
            "fuel": 0,
            "food": 0,
            "water": 0,
        }
        if home:
            dlt_h = getattr(self._world, "_planet_production_deltas")(
                s, planet=home, influence_sources=inf_src
            )
            for k in PLANET_STORE_KEYS:
                net_home[k] = int(dlt_h.get(k, 0) or 0)
            pop_h = int(getattr(home, "population", 0) or 0)
            pf_h, pw_h = getattr(self._world, "_population_vitals_upkeep_needs")(
                population=pop_h
            )
            net_home["food"] -= int(pf_h)
            net_home["water"] -= int(pw_h)

        if for_hud_poll:
            return {
                "ok": True,
                "current_tick": tick,
                "current_sol": int(tick),
                "net_per_sol": net,
                "net_home_per_sol": net_home,
            }

        rp = self._player_rp_info(s, player_id=pid)

        buildings_info = {
            "planet_buildings": planet_buildings,
            "external_buildings": ext_buildings if include_external_buildings else 0,
            "external_buildings_hidden": ext_buildings
            if not include_external_buildings
            else 0,
        }

        bal = getattr(self._world, "_balance", None)
        stock_buildings = {"metal": 0, "crystal": 0, "energy": 0, "fuel": 0}
        stock_fleet_ships = {"metal": 0, "crystal": 0, "energy": 0, "fuel": 0}
        if bal:
            for b in buildings:
                bt = str(getattr(b, "building_type", "") or "").strip().lower()
                if not bt:
                    continue
                try:
                    bd = bal.get_building(bt)
                except Exception:
                    continue
                bbuild = bd.get("build") if isinstance(bd.get("build"), dict) else {}
                bc = bbuild.get("cost") if isinstance(bbuild.get("cost"), dict) else {}
                lvl = max(1, int(getattr(b, "level", 1) or 1))
                for k in stock_buildings:
                    v = int(bc.get(k, 0) or 0) if isinstance(bc.get(k), (int, float)) else 0
                    if v:
                        stock_buildings[k] += v * lvl
            for f in fleets:
                if int(getattr(f, "qty", 0) or 0) <= 0:
                    continue
                um = getattr(self._world, "_fleet_units_map")(s, f)
                for ut, n in (um or {}).items():
                    qty = int(n) or 0
                    if qty <= 0:
                        continue
                    try:
                        parts = getattr(self._world, "_unit_build_cost_parts")(str(ut))
                    except Exception:
                        parts = {}
                    if not isinstance(parts, dict):
                        parts = {}
                    for k in stock_fleet_ships:
                        stock_fleet_ships[k] += int(parts.get(k, 0) or 0) * qty

        fleets_payload = []
        for f in fleets:
            if int(getattr(f, "qty", 0) or 0) <= 0:
                continue
            um = getattr(self._world, "_fleet_units_map")(s, f)
            fleets_payload.append(
                {
                    "id": str(f.id),
                    "name": getattr(self._world, "_fleet_public_name")(f),
                    "pos": {"x": int(f.pos_x), "y": int(f.pos_y), "z": int(f.pos_z)},
                    "ships": sum(int(v) for v in (um or {}).values()),
                }
            )

        runway_sols: dict[str, dict[str, object]] = {}
        for k in PLANET_STORE_KEYS:
            trend, approx = _runway_approx_sols(
                int(treasury_empire.get(k, 0) or 0), int(net.get(k, 0) or 0)
            )
            runway_sols[k] = {"trend": trend, "approx_sols": approx}

        return {
            "ok": True,
            "current_tick": tick,
            "current_sol": int(tick),
            "research_points": round(float(rp.balance), 4),
            "research_points_per_sol": round(float(rp.per_sol), 4),
            "treasury_home": treasury_home,
            "treasury_empire": treasury_empire,
            "net_per_sol": net,
            "net_home_per_sol": net_home,
            "production_per_sol": prod_sum,
            "costs_per_sol": {
                "population_vitals": pop_need,
                "outpost_supply_logistics": {
                    "food": logistics["food"],
                    "water": logistics["water"],
                    "outposts": logistics["outposts_count"],
                },
                "outpost_upkeep": outpost_upkeep,
                "fleet_empire_upkeep": {
                    "metal": empire_fleet_upkeep.get("metal", 0),
                    "crystal": empire_fleet_upkeep.get("crystal", 0),
                    "food": empire_fleet_upkeep.get("food", 0),
                    "water": empire_fleet_upkeep.get("water", 0),
                    "fleets": fleet_count,
                    "ships": ships_total,
                },
                "fleet_energy_upkeep": {
                    "energy": int(upkeep_energy),
                    "fleets": fleet_count,
                },
            },
            "expenses_aggregate_per_sol": expenses_aggregate_per_sol,
            "construction_reference": {
                "note": "Справочно: сумма цен из баланса для текущих построек (×уровень) и кораблей во флотах; не ежесолевая статья расходов.",
                "buildings_replacement_cost": stock_buildings,
                "fleet_ships_replacement_cost": stock_fleet_ships,
            },
            "planets": planet_rows,
            "buildings": buildings_info,
            "fleets": fleets_payload,
            "runway_sols": runway_sols,
        }

    def apply_economy_tick(
        self, s: Session, *, tick: int, influence_sources: dict
    ) -> None:
        """Экономический блок тика: производство планет + логистика снабжения + имперский upkeep флотов."""
        planets = s.execute(select(Planet)).scalars().all()
        for p in planets:
            getattr(self._world, "apply_planet_production_tick")(
                s, planet_id=p.id, influence_sources=influence_sources
            )

        getattr(self._world, "_apply_supply_route_logistics_tick")(s, tick=tick)
        getattr(self._world, "_apply_fleet_empire_upkeep_tick")(s, tick=tick)
        getattr(self._world, "_apply_bandit_fleet_empire_upkeep_tick")(s, tick=tick)
