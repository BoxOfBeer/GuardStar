from __future__ import annotations

import hashlib
import json
import random
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app.fleet_defaults import fleet_display_name_for_index
from app.game_rules import calc_fuel_cost, calc_planet_production, calc_travel_plan, calc_upkeep
from app.db.models.event import Event
from app.db.models.explored_sector import ExploredSector
from app.db.models.influence_cell import InfluenceCell
from app.db.models.building import Building
from app.db.models.fleet import Fleet
from app.db.models.fleet_ship import FleetShip
from app.db.models.outpost import Outpost
from app.db.models.outpost_module import OutpostModule
from app.db.models.fleet_order import FleetOrder
from app.db.models.game_clock import GameClock
from app.db.models.world_state import WorldState
from app.db.models.planet import Planet
from app.db.models.resource import Resource
from app.db.models.resource_tick import ResourceTick
from app.db.models.unit import Unit
from app.db.models.unit_order import UnitOrder
from app.db.models.player import Player
from app.db.models.player_tech import PlayerTech

# Фиксированный «NPC» для вражеских засад в MVP (не логинится).
BANDIT_PLAYER_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")

# Территориальное влияние:
# - в гарант-радиусе сила источника постоянная;
# - далее каждую клетку делим влияние пополам.
INFLUENCE_WEIGHT_COLONY = 1.0
INFLUENCE_WEIGHT_BUILDING = 0.4
INFLUENCE_RADIUS_COLONY = 40
INFLUENCE_RADIUS_BUILDING = 14
INFLUENCE_BASE_RADIUS = 3
INFLUENCE_MIN_DOMINANT_SCORE = 0.1
INFLUENCE_CONTEST_RATIO = 0.68
INFLUENCE_CAPTURE_THRESHOLD = 1.0
INFLUENCE_NATURAL_DECAY_PER_TICK = 0.1
INFLUENCE_BUILDING_TYPES = {"outpost", "fortified_outpost", "command_post"}

# Склад планеты и производство за игровой сол (металл…вода).
PLANET_STORE_KEYS = ("metal", "crystal", "energy", "fuel", "food", "water")


class WorldService:
    def _get_building_bonus_for_player(self, s: Session, *, player_id: uuid.UUID) -> dict:
        rows = (
            s.execute(
                select(Building.building_type, func.count(Building.id))
                .where(Building.owner_player_id == player_id)
                .group_by(Building.building_type)
            )
            .all()
        )
        counts = {t: int(c) for t, c in rows}
        mines = counts.get("mine", 0)
        reactors = counts.get("reactor", 0)
        farms = counts.get("crystal_farm", 0)
        return {
            "metal": 2 * mines,
            "crystal": 2 * farms,
            "energy": 1 * reactors,
            "fuel": 1 * reactors,
            "food": 0,
            "water": 0,
        }

    def __init__(self, *, world_seed: str = "guardstar", balance: object | None = None) -> None:
        self._world_seed = world_seed or "guardstar"
        # BalanceService (DI). Не зависит от Flask context.
        self._balance = balance

    def _get_player_race_id(self, s: Session, *, player_id: uuid.UUID) -> str | None:
        # race_id появится как поле Player позже. Пока — None.
        _p = s.execute(select(Player).where(Player.id == player_id)).scalar_one_or_none()
        if not _p:
            return None
        rid = getattr(_p, "race_id", None)
        return str(rid) if rid else None

    def _race_modifiers(self, s: Session, *, player_id: uuid.UUID) -> dict:
        pack = self._balance.pack if self._balance else None
        rid = self._get_player_race_id(s, player_id=player_id)
        if not pack or not rid:
            return {
                "build_time_multiplier": 1.0,
                "upkeep_energy_multiplier": 1.0,
                "travel_fuel_multiplier": 1.0,
                "production_multiplier": {
                    "metal": 1.0,
                    "crystal": 1.0,
                    "energy": 1.0,
                    "fuel": 1.0,
                    "food": 1.0,
                    "water": 1.0,
                },
            }
        race = pack.races_by_id.get(rid) if hasattr(pack, "races_by_id") else None
        mods = (race.get("modifiers") if isinstance(race, dict) else None) or {}
        prod_mul = mods.get("production_multiplier") if isinstance(mods.get("production_multiplier"), dict) else {}
        return {
            "build_time_multiplier": float(mods.get("build_time_multiplier", 1.0)),
            "upkeep_energy_multiplier": float(mods.get("upkeep_energy_multiplier", 1.0)),
            "travel_fuel_multiplier": float(mods.get("travel_fuel_multiplier", 1.0)),
            "production_multiplier": {
                "metal": float(prod_mul.get("metal", 1.0)),
                "crystal": float(prod_mul.get("crystal", 1.0)),
                "energy": float(prod_mul.get("energy", 1.0)),
                "fuel": float(prod_mul.get("fuel", 1.0)),
                "food": float(prod_mul.get("food", 1.0)),
                "water": float(prod_mul.get("water", 1.0)),
            },
        }

    def _get_player_done_techs(self, s: Session, *, player_id: uuid.UUID) -> list[str]:
        return (
            s.execute(
                select(PlayerTech.tech_id)
                .where(PlayerTech.player_id == player_id, PlayerTech.status == "done")
                .order_by(PlayerTech.tech_id)
            )
            .scalars()
            .all()
        )

    def _tech_production_multipliers(self, s: Session, *, player_id: uuid.UUID) -> dict[str, float]:
        out = {k: 1.0 for k in PLANET_STORE_KEYS}
        if not self._balance:
            return out
        for tid in self._get_player_done_techs(s, player_id=player_id):
            t = self._balance.pack.tech_by_id.get(tid)
            if not isinstance(t, dict):
                continue
            eff = t.get("effects") if isinstance(t.get("effects"), dict) else {}
            pm = eff.get("production_multiplier") if isinstance(eff.get("production_multiplier"), dict) else {}
            for k in PLANET_STORE_KEYS:
                if isinstance(pm.get(k), (int, float)):
                    out[k] *= float(pm[k])
        return out

    def _building_influence_profile(self, building_type: str) -> tuple[float, int] | None:
        btype = str(building_type or "").strip().lower()
        if btype not in INFLUENCE_BUILDING_TYPES:
            return None
        if self._balance:
            try:
                bd = self._balance.get_building(btype)
            except Exception:
                bd = {}
            eff = bd.get("effects") if isinstance(bd, dict) else {}
            if isinstance(eff, dict):
                strength = eff.get("influence_strength")
                radius = eff.get("influence_radius")
                if isinstance(strength, (int, float)) and isinstance(radius, int):
                    return float(strength), int(radius)
        return INFLUENCE_WEIGHT_BUILDING, INFLUENCE_RADIUS_BUILDING

    def _fleet_units_map(self, s: Session, fleet: Fleet) -> dict[str, int]:
        rows = s.execute(select(FleetShip).where(FleetShip.fleet_id == fleet.id)).scalars().all()
        if rows:
            pos = {r.unit_type: int(r.qty) for r in rows if int(r.qty) > 0}
            if pos:
                return pos
        if int(fleet.qty) > 0 and fleet.unit_type:
            return {str(fleet.unit_type): int(fleet.qty)}
        return {}

    def _cell_has_planet(self, s: Session, *, x: int, y: int, z: int) -> bool:
        if int(z) != 0:
            return False
        row = s.execute(select(Planet.id).where(Planet.pos_x == int(x), Planet.pos_y == int(y))).first()
        return bool(row)

    def _write_fleet_units(self, s: Session, fleet: Fleet, units: dict[str, int]) -> None:
        s.execute(delete(FleetShip).where(FleetShip.fleet_id == fleet.id))
        pos = {str(k): int(v) for k, v in units.items() if int(v) > 0}
        tot = sum(pos.values())
        if tot <= 0:
            fleet.qty = 0
            return
        for ut, q in pos.items():
            s.add(FleetShip(fleet_id=fleet.id, unit_type=ut, qty=int(q)))
        fleet.qty = tot
        fleet.unit_type = max(pos.items(), key=lambda kv: (kv[1], kv[0]))[0]

    def _sync_fleet_ships_from_legacy(self, s: Session, fleet: Fleet) -> None:
        if fleet.qty <= 0:
            return
        rows = s.execute(select(FleetShip).where(FleetShip.fleet_id == fleet.id)).scalars().all()
        if rows:
            tot = sum(int(r.qty) for r in rows)
            if tot <= 0 and int(fleet.qty) > 0 and fleet.unit_type:
                s.execute(delete(FleetShip).where(FleetShip.fleet_id == fleet.id))
                s.flush()
                s.add(FleetShip(fleet_id=fleet.id, unit_type=str(fleet.unit_type), qty=int(fleet.qty)))
                return
            fleet.qty = tot
            dominant = max(((r.unit_type, int(r.qty)) for r in rows), key=lambda x: (x[1], x[0]))[0]
            fleet.unit_type = str(dominant)
            return
        s.add(FleetShip(fleet_id=fleet.id, unit_type=str(fleet.unit_type), qty=int(fleet.qty)))

    def _fleet_travel_ticks_for_distance(self, *, distance: int, units: dict[str, int]) -> int:
        d = max(0, int(distance))
        if d == 0:
            return 0
        if not self._balance or not units:
            return max(1, d)
        ticks = 1
        for ut, q in units.items():
            if int(q) <= 0:
                continue
            tp = self._balance.calc_travel_plan(unit_type=str(ut), distance=d)
            ticks = max(ticks, int(tp.get("travel_ticks", 1)))
        return max(1, ticks)

    def _fleet_fuel_cost_total(
        self,
        s: Session,
        *,
        player_id: str,
        fleet: Fleet,
        distance: int,
        units: dict[str, int],
    ) -> int:
        if not self._balance:
            fu = 0
            for ut, q in units.items():
                fp = calc_fuel_cost(distance=distance, qty=int(q), unit_type=str(ut))
                fu += int(fp.fuel_cost)
            return fu
        pid = self._get_player_race_id(s, player_id=uuid.UUID(player_id))
        techs = self._get_player_done_techs(s, player_id=uuid.UUID(player_id))
        tot = 0
        for ut, q in units.items():
            if int(q) <= 0:
                continue
            r = self._balance.calc_travel_cost(
                unit_type=str(ut),
                qty=int(q),
                distance=int(distance),
                race_id=pid,
                techs=techs,
            )
            tot += int(r.get("fuel", 0))
        return tot

    def _fleet_upkeep_energy_total(self, s: Session, *, player_id: uuid.UUID, units: dict[str, int]) -> int:
        if not units:
            return 0
        if not self._balance:
            return sum(max(0, int(q)) for q in units.values())
        rid = self._get_player_race_id(s, player_id=player_id)
        techs = self._get_player_done_techs(s, player_id=player_id)
        tot = 0
        for ut, q in units.items():
            if int(q) <= 0:
                continue
            part = self._balance.calc_unit_upkeep(
                unit_type=str(ut), qty=int(q), race_id=rid, techs=techs
            )
            tot += int(part.get("energy", 0))
        return tot

    def _resolve_owning_planet_for_build_site(
        self, s: Session, *, owner_id: uuid.UUID, x: int, y: int, z: int
    ) -> Planet | None:
        if z != 0:
            return None
        mine = s.execute(select(Planet).where(Planet.owner_player_id == owner_id)).scalars().all()
        best: tuple[int, Planet] | None = None
        for p in mine:
            md = abs(p.pos_x - x) + abs(p.pos_y - y)
            if md > 3:
                continue
            if best is None or md < best[0]:
                best = (md, p)
        return best[1] if best else None

    def _max_per_planet_for_building(self, logical_type: str) -> int | None:
        if not self._balance:
            return None
        bd = self._balance.get_building(logical_type)
        mp = bd.get("max_per_planet") if isinstance(bd, dict) else None
        return int(mp) if isinstance(mp, int) and mp >= 0 else None

    def _building_required_techs(self, logical_type: str) -> list[str]:
        if not self._balance:
            return []
        try:
            bd = self._balance.get_building(logical_type)
        except Exception:
            return []
        req = bd.get("prereq_tech") if isinstance(bd, dict) else None
        if not isinstance(req, list):
            return []
        return [str(x) for x in req if isinstance(x, str) and x.strip()]

    def _outpost_required_techs(self, outpost_type: str) -> list[str]:
        if not self._balance:
            return []
        try:
            out = self._balance.get_outpost(outpost_type)
        except Exception:
            return []
        build = out.get("build") if isinstance(out, dict) else None
        req = build.get("prereq_tech") if isinstance(build, dict) else None
        if not isinstance(req, list):
            return []
        return [str(x) for x in req if isinstance(x, str) and x.strip()]

    def _outpost_module_required_techs(self, module_type: str) -> list[str]:
        if not self._balance:
            return []
        try:
            mod = self._balance.get_outpost_module(module_type)
        except Exception:
            return []
        req = mod.get("prereq_tech") if isinstance(mod, dict) else None
        if not isinstance(req, list):
            return []
        return [str(x) for x in req if isinstance(x, str) and x.strip()]

    def _outpost_definition(self, outpost_type: str) -> dict:
        if self._balance:
            return self._balance.get_outpost(outpost_type)
        fallback = {
            "outpost_t1": {
                "id": "outpost_t1",
                "family": "outpost",
                "level": 1,
                "build": {"cost": {"metal": 220, "crystal": 120, "fuel": 10}, "time_ticks": 5, "prereq_tech": []},
                "territory": {"influence_strength": 0.4, "influence_radius": 14},
                "vision": {"base_radius": 6},
                "combat": {"hp": 420, "attack": 8, "defense": 10, "range": 5},
                "slots": {"module_slots": 1},
                "upgrade": {"to": "outpost_t2", "cost": {"metal": 180, "crystal": 120, "fuel": 10}, "time_ticks": 6},
            },
            "outpost_t2": {
                "id": "outpost_t2",
                "family": "outpost",
                "level": 2,
                "build": {"cost": {"metal": 360, "crystal": 220, "fuel": 20}, "time_ticks": 7, "prereq_tech": ["tech_territory_2"]},
                "territory": {"influence_strength": 0.7, "influence_radius": 17},
                "vision": {"base_radius": 7},
                "combat": {"hp": 650, "attack": 9, "defense": 12, "range": 5},
                "slots": {"module_slots": 2},
                "upgrade": {"to": "outpost_t3", "cost": {"metal": 260, "crystal": 180, "fuel": 15}, "time_ticks": 8},
            },
            "outpost_t3": {
                "id": "outpost_t3",
                "family": "outpost",
                "level": 3,
                "build": {"cost": {"metal": 520, "crystal": 360, "fuel": 35}, "time_ticks": 9, "prereq_tech": ["tech_territory_3"]},
                "territory": {"influence_strength": 1.0, "influence_radius": 20},
                "vision": {"base_radius": 8},
                "combat": {"hp": 950, "attack": 10, "defense": 14, "range": 5},
                "slots": {"module_slots": 3},
                "upgrade": None,
            },
        }
        return fallback[outpost_type]

    def _outpost_module_definition(self, module_type: str) -> dict:
        if self._balance:
            return self._balance.get_outpost_module(module_type)
        raise KeyError(module_type)

    def _outpost_module_rows(self, s: Session, *, outpost_id: uuid.UUID) -> list[OutpostModule]:
        return (
            s.execute(select(OutpostModule).where(OutpostModule.outpost_id == outpost_id).order_by(OutpostModule.slot_idx.asc()))
            .scalars()
            .all()
        )

    def _outpost_stats(self, s: Session, outpost: Outpost) -> dict:
        od = self._outpost_definition(outpost.outpost_type)
        territory = od.get("territory") if isinstance(od.get("territory"), dict) else {}
        vision = od.get("vision") if isinstance(od.get("vision"), dict) else {}
        combat = od.get("combat") if isinstance(od.get("combat"), dict) else {}
        modules = self._outpost_module_rows(s, outpost_id=outpost.id)

        vision_radius = int(vision.get("base_radius", 0) or 0)
        hp = int(combat.get("hp", 0) or 0)
        attack = int(combat.get("attack", 0) or 0)
        defense = int(combat.get("defense", 0) or 0)
        attack_range = int(combat.get("range", 5) or 5)
        territory_strength = float(territory.get("influence_strength", 0.0) or 0.0)
        territory_radius = int(territory.get("influence_radius", 0) or 0)

        payload_modules: list[dict] = []
        for mod in modules:
            md = self._outpost_module_definition(mod.module_type)
            eff = md.get("effects") if isinstance(md.get("effects"), dict) else {}
            vis = eff.get("vision") if isinstance(eff.get("vision"), dict) else {}
            cmb = eff.get("combat") if isinstance(eff.get("combat"), dict) else {}
            if isinstance(vis.get("radius_add"), (int, float)):
                vision_radius += int(vis.get("radius_add", 0))
            if isinstance(cmb.get("attack_add"), (int, float)):
                attack += int(cmb.get("attack_add", 0))
            if isinstance(cmb.get("defense_add"), (int, float)):
                defense += int(cmb.get("defense_add", 0))
            if isinstance(cmb.get("hp_add"), (int, float)):
                hp += int(cmb.get("hp_add", 0))
            payload_modules.append(
                {
                    "id": str(mod.id),
                    "module_type": mod.module_type,
                    "kind": mod.kind,
                    "level": int(mod.level),
                    "slot_idx": int(mod.slot_idx),
                    "status": mod.status,
                    "started_at_tick": int(getattr(mod, "started_at_tick", 0) or 0),
                    "finish_tick": int(getattr(mod, "finish_tick", 0) or 0),
                    "name": md.get("name"),
                }
            )

        supply_line: dict | None = None
        if int(getattr(outpost, "z", 0) or 0) == 0 and not self._cell_is_owned_planet_tile(
            s, owner_id=outpost.owner_player_id, x=int(outpost.x), y=int(outpost.y), z=0
        ):
            if self._is_cell_supplied(s, owner_id=outpost.owner_player_id, x=int(outpost.x), y=int(outpost.y), z=int(outpost.z)):
                hub_p = self._supply_hub_planet_for_cell(
                    s, owner_id=outpost.owner_player_id, x=int(outpost.x), y=int(outpost.y), z=int(outpost.z)
                )
                if hub_p is not None:
                    cf, cw = self._supply_route_logistics_costs(hub=hub_p, ox=int(outpost.x), oy=int(outpost.y))
                    supply_line = {
                        "hub_planet_id": str(hub_p.id),
                        "food_per_sol": int(cf),
                        "water_per_sol": int(cw),
                    }

        return {
            "outpost_type": outpost.outpost_type,
            "family": outpost.family,
            "level": int(outpost.level),
            "status": outpost.status,
            "started_at_tick": int(getattr(outpost, "started_at_tick", 0) or 0),
            "finish_tick": int(getattr(outpost, "finish_tick", 0) or 0),
            "territory": {"influence_strength": territory_strength, "influence_radius": territory_radius},
            "vision": {"radius": int(vision_radius)},
            "combat": {"hp": int(hp), "attack": int(attack), "defense": int(defense), "range": int(attack_range)},
            "slots": {"total": int(outpost.module_slots_total), "used": len(modules)},
            "modules": payload_modules,
            "upgrade": od.get("upgrade"),
            "name": od.get("name"),
            "supply_line": supply_line,
        }

    def _apply_outpost_combat_tick(self, s: Session, *, tick: int) -> None:
        outposts = s.execute(select(Outpost).where(Outpost.status == "active")).scalars().all()
        if not outposts:
            return
        fleets = s.execute(select(Fleet).where(Fleet.qty > 0)).scalars().all()
        if not fleets:
            return

        for op in outposts:
            stats = self._outpost_stats(s, op)
            cmb = stats.get("combat") if isinstance(stats.get("combat"), dict) else {}
            atk = int(cmb.get("attack", 0) or 0)
            rng = int(cmb.get("range", 5) or 5)
            if atk <= 0 or rng <= 0:
                continue

            in_range: list[Fleet] = []
            for f in fleets:
                if f.owner_player_id == op.owner_player_id:
                    continue
                if int(f.pos_z) != int(op.z):
                    continue
                d = abs(int(f.pos_x) - int(op.x)) + abs(int(f.pos_y) - int(op.y))
                if d <= rng:
                    in_range.append(f)
            if not in_range:
                continue

            target = max(in_range, key=lambda f: (int(f.qty), str(f.id)))
            before = dict(self._fleet_units_map(s, target))

            score = float(self._fleet_combat_score(s, fleet=target, player_id=target.owner_player_id) or 0)
            denom = max(35.0, score)
            frac = min(0.22, max(0.02, float(atk) / denom))
            self._apply_fleet_post_combat_losses(s, target, fraction=frac)

            after = dict(self._fleet_units_map(s, target))
            cas = self._composition_casualties(before, after)
            if int(cas.get("lost_total", 0) or 0) <= 0:
                continue

            self._emit_event(
                s,
                tick=tick,
                type="outpost_fire",
                message=f"Форпост обстрелял ваш флот в ({int(target.pos_x)},{int(target.pos_y)},{int(target.pos_z)})",
                payload={
                    "outpost_id": str(op.id),
                    "outpost_type": str(op.outpost_type),
                    "pos": {"x": int(op.x), "y": int(op.y), "z": int(op.z)},
                    "target_fleet_id": str(target.id),
                    "range": rng,
                    "attack": atk,
                    "losses": cas,
                },
                player_id=target.owner_player_id,
            )

    def _apply_outpost_upkeep_tick(self, s: Session, *, tick: int) -> None:
        """Содержание форпостов. При нехватке ресурсов — форпост уходит в offline и перестаёт давать эффект."""
        outposts = s.execute(select(Outpost).where(Outpost.status.in_(["active", "offline"]))).scalars().all()
        if not outposts:
            return

        # Ресурсы берём с домашней планеты владельца (пока "имперский склад").
        home_by_owner: dict[uuid.UUID, Planet] = {}
        res_by_owner: dict[uuid.UUID, Resource] = {}
        for pid in {op.owner_player_id for op in outposts}:
            home = s.execute(select(Planet).where(Planet.owner_player_id == pid).order_by(Planet.created_at.asc())).scalar_one_or_none()
            if not home:
                continue
            res = s.execute(select(Resource).where(Resource.planet_id == home.id)).scalar_one_or_none()
            if not res:
                continue
            home_by_owner[pid] = home
            res_by_owner[pid] = res

        for op in outposts:
            res = res_by_owner.get(op.owner_player_id)
            if not res:
                continue
            # Вне снабжения форпост выключается (не даёт эффект, пока не снабжён).
            if not self._is_cell_supplied(s, owner_id=op.owner_player_id, x=int(op.x), y=int(op.y), z=int(op.z)):
                if op.status != "offline":
                    op.status = "offline"
                    op.updated_at = datetime.utcnow()
                    self._emit_event(
                        s,
                        tick=tick,
                        type="outpost_offline",
                        message="Форпост отключён (нет снабжения)",
                        payload={"outpost_id": str(op.id), "reason": "no_supply"},
                        player_id=op.owner_player_id,
                    )
                continue
            od = self._outpost_definition(op.outpost_type)
            upkeep = od.get("upkeep_per_tick") if isinstance(od.get("upkeep_per_tick"), dict) else {}
            need = {k: int(upkeep.get(k, 0) or 0) for k in ("metal", "crystal", "energy", "fuel")}
            if all(v <= 0 for v in need.values()):
                continue

            can = (
                int(getattr(res, "metal", 0)) >= need["metal"]
                and int(getattr(res, "crystal", 0)) >= need["crystal"]
                and int(getattr(res, "energy", 0)) >= need["energy"]
                and int(getattr(res, "fuel", 0)) >= need["fuel"]
            )
            if not can:
                if op.status != "offline":
                    op.status = "offline"
                    op.updated_at = datetime.utcnow()
                    self._emit_event(
                        s,
                        tick=tick,
                        type="outpost_offline",
                        message=f"Форпост отключён (не хватает ресурсов на содержание)",
                        payload={"outpost_id": str(op.id), "need": need},
                        player_id=op.owner_player_id,
                    )
                continue

            # списываем и (если был offline) включаем
            res.metal = int(getattr(res, "metal", 0)) - need["metal"]
            res.crystal = int(getattr(res, "crystal", 0)) - need["crystal"]
            res.energy = int(getattr(res, "energy", 0)) - need["energy"]
            if hasattr(res, "fuel"):
                res.fuel = int(getattr(res, "fuel", 0)) - need["fuel"]
            if op.status == "offline":
                op.status = "active"
                op.updated_at = datetime.utcnow()
                self._emit_event(
                    s,
                    tick=tick,
                    type="outpost_online",
                    message=f"Форпост снова активен (содержание оплачено)",
                    payload={"outpost_id": str(op.id), "paid": need},
                    player_id=op.owner_player_id,
                )

    def _effective_max_population(self, s: Session, planet: Planet) -> int:
        base = int(getattr(planet, "max_population", 5000) or 5000)
        add = 0
        rows = s.execute(select(Building).where(Building.planet_id == planet.id)).scalars().all()
        if self._balance:
            for b in rows:
                bd = self._balance.get_building(b.building_type)
                eff = bd.get("effects") if isinstance(bd, dict) else {}
                if isinstance(eff, dict) and isinstance(eff.get("max_population_add"), (int, float)):
                    add += int(eff["max_population_add"])
        return max(0, base + add)

    def _next_fleet_default_name(self, s: Session, *, owner_id: uuid.UUID) -> str:
        n = s.execute(select(func.count(Fleet.id)).where(Fleet.owner_player_id == owner_id)).scalar()
        return fleet_display_name_for_index(int(n or 0))

    def _fleet_public_name(self, fleet: Fleet) -> str:
        raw = str(getattr(fleet, "name", "") or "").strip()
        return raw if raw else "Флот"

    def _planet_slot_usage(self, s: Session, planet: Planet) -> dict:
        rows = (
            s.execute(
                select(Building.building_type, func.count(Building.id))
                .where(Building.planet_id == planet.id)
                .group_by(Building.building_type)
            )
            .all()
        )
        out: dict[str, dict] = {}
        for bt, cnt in rows:
            mx = self._max_per_planet_for_building(str(bt))
            out[str(bt)] = {"built": int(cnt), "max": mx}
        return out

    def _logical_unit_keys(self) -> set[str]:
        if self._balance and self._balance.pack:
            ua = (
                self._balance.pack.aliases.get("unit_aliases")
                if isinstance(self._balance.pack.aliases, dict)
                else None
            )
            return set(ua.keys()) if isinstance(ua, dict) else set()
        return {"scout", "fighter", "engineer"}

    # Фаза A снабжения: только счётчик на планете (не юнит на карте).
    SUPPLY_BASE_RADIUS = 5
    SUPPLY_PER_SUPPLIER = 3

    def _supply_radius_modifiers_for_player(self, s: Session, *, player_id: uuid.UUID) -> tuple[int, int]:
        """(base_add, per_supplier_add) из завершённых технологий."""
        if not self._balance:
            return (0, 0)
        base_add = 0
        per_add = 0
        for tid in self._get_player_done_techs(s, player_id=player_id):
            t = self._balance.pack.tech_by_id.get(tid)
            if not isinstance(t, dict):
                continue
            eff = t.get("effects") if isinstance(t.get("effects"), dict) else {}
            v = eff.get("supply_base_add")
            if isinstance(v, (int, float)):
                base_add += int(v)
            v2 = eff.get("supply_per_supplier_add")
            if isinstance(v2, (int, float)):
                per_add += int(v2)
        return (base_add, per_add)

    def _supply_radius_modifiers_for_planet_buildings(self, s: Session, *, planet_id: uuid.UUID) -> tuple[int, int]:
        """(base_add, per_supplier_add) из построек на планете."""
        if not self._balance:
            return (0, 0)
        base_add = 0
        per_add = 0
        rows = (
            s.execute(
                select(Building.building_type, func.count(Building.id))
                .where(Building.planet_id == planet_id)
                .group_by(Building.building_type)
            )
            .all()
        )
        for bt, cnt in rows:
            try:
                bd = self._balance.get_building(str(bt))
            except Exception:
                bd = {}
            eff = bd.get("effects") if isinstance(bd, dict) else {}
            if not isinstance(eff, dict):
                continue
            n = max(0, int(cnt))
            v = eff.get("supply_base_add")
            if isinstance(v, (int, float)):
                base_add += int(v) * n
            v2 = eff.get("supply_per_supplier_add")
            if isinstance(v2, (int, float)):
                per_add += int(v2) * n
        return (base_add, per_add)

    def _planet_supply_radius(self, s: Session, *, planet: Planet) -> int:
        n = int(getattr(planet, "supplier_count", 0) or 0)
        base_add_t, per_add_t = self._supply_radius_modifiers_for_player(s, player_id=planet.owner_player_id)
        base_add_b, per_add_b = self._supply_radius_modifiers_for_planet_buildings(s, planet_id=planet.id)
        base = int(self.SUPPLY_BASE_RADIUS) + int(base_add_t) + int(base_add_b)
        per = int(self.SUPPLY_PER_SUPPLIER) + int(per_add_t) + int(per_add_b)
        return max(0, int(base + per * n))

    @staticmethod
    def _manhattan_l_path_cells(px: int, py: int, tx: int, ty: int) -> list[tuple[int, int]]:
        """Клетки пути от (px,py) до (tx,ty) без стартовой клетки: сначала X, затем Y (логистика «как»)."""
        cells: list[tuple[int, int]] = []
        cx, cy = int(px), int(py)
        tx, ty = int(tx), int(ty)
        while cx != tx:
            cx += 1 if tx > cx else -1
            cells.append((cx, cy))
        while cy != ty:
            cy += 1 if ty > cy else -1
            cells.append((cx, cy))
        return cells

    def _supply_route_block_cell(
        self, s: Session, *, owner_id: uuid.UUID, path_cells: list[tuple[int, int]]
    ) -> tuple[int, int] | None:
        """Первая клетка пути с чужим флотом — обрыв линии снабжения."""
        for cx, cy in path_cells:
            hit = (
                s.execute(
                    select(Fleet.id).where(
                        Fleet.pos_x == int(cx),
                        Fleet.pos_y == int(cy),
                        Fleet.pos_z == 0,
                        Fleet.owner_player_id != owner_id,
                        Fleet.qty > 0,
                    )
                )
                .first()
            )
            if hit:
                return (int(cx), int(cy))
        return None

    def _planet_supply_candidates(self, s: Session, *, owner_id: uuid.UUID, x: int, y: int) -> list[tuple[Planet, int, int]]:
        planets = s.execute(select(Planet).where(Planet.owner_player_id == owner_id)).scalars().all()
        rows: list[tuple[Planet, int, int]] = []
        for p in planets:
            r = self._planet_supply_radius(s, planet=p)
            d = abs(int(p.pos_x) - int(x)) + abs(int(p.pos_y) - int(y))
            rows.append((p, r, d))
        return rows

    def _supply_hub_planet_for_cell(self, s: Session, *, owner_id: uuid.UUID, x: int, y: int, z: int) -> Planet | None:
        """Планета-хаб, через которую клетка в снабжении (радиус + чистый L-путь)."""
        if int(z) != 0:
            return None
        rows = self._planet_supply_candidates(s, owner_id=owner_id, x=int(x), y=int(y))
        in_range = [(p, r, d) for p, r, d in rows if r > 0 and d <= r]
        for p, _r, _d in sorted(in_range, key=lambda t: t[2]):
            path = self._manhattan_l_path_cells(int(p.pos_x), int(p.pos_y), int(x), int(y))
            if self._supply_route_block_cell(s, owner_id=owner_id, path_cells=path) is None:
                return p
        return None

    def _cell_is_owned_planet_tile(self, s: Session, *, owner_id: uuid.UUID, x: int, y: int, z: int) -> bool:
        if int(z) != 0:
            return False
        return (
            s.execute(
                select(Planet.id).where(
                    Planet.owner_player_id == owner_id,
                    Planet.pos_x == int(x),
                    Planet.pos_y == int(y),
                )
            ).first()
            is not None
        )

    def _supply_route_logistics_costs(self, *, hub: Planet, ox: int, oy: int) -> tuple[int, int]:
        """Еда/вода с хаба за содержание линии к форпосту за один сол (balance supply_route_upkeep)."""
        food, water = 2, 2
        extra_f, extra_w = 0, 0
        if self._balance and isinstance(self._balance.pack.economy, dict):
            sr = self._balance.pack.economy.get("supply_route_upkeep")
            if isinstance(sr, dict):
                v = sr.get("food_per_sol_per_outpost")
                if isinstance(v, (int, float)):
                    food = int(v)
                v2 = sr.get("water_per_sol_per_outpost")
                if isinstance(v2, (int, float)):
                    water = int(v2)
                d = abs(int(hub.pos_x) - int(ox)) + abs(int(hub.pos_y) - int(oy))
                cf = sr.get("food_per_manhattan_from_hub")
                if isinstance(cf, (int, float)):
                    extra_f = int(cf) * max(0, d)
                cw = sr.get("water_per_manhattan_from_hub")
                if isinstance(cw, (int, float)):
                    extra_w = int(cw) * max(0, d)
        return max(0, food + extra_f), max(0, water + extra_w)

    def _apply_supply_route_logistics_tick(self, s: Session, *, tick: int) -> None:
        """После выработки на планетах: логистика линий к форпостам (еда/вода с хаба)."""
        outposts = s.execute(select(Outpost).where(Outpost.status == "active")).scalars().all()
        if not outposts:
            return
        for op in outposts:
            if int(getattr(op, "z", 0) or 0) != 0:
                continue
            if self._cell_is_owned_planet_tile(s, owner_id=op.owner_player_id, x=int(op.x), y=int(op.y), z=0):
                continue
            if not self._is_cell_supplied(s, owner_id=op.owner_player_id, x=int(op.x), y=int(op.y), z=int(op.z)):
                continue
            hub = self._supply_hub_planet_for_cell(s, owner_id=op.owner_player_id, x=int(op.x), y=int(op.y), z=int(op.z))
            if not hub:
                continue
            need_f, need_w = self._supply_route_logistics_costs(hub=hub, ox=int(op.x), oy=int(op.y))
            if need_f <= 0 and need_w <= 0:
                continue
            res = s.execute(select(Resource).where(Resource.planet_id == hub.id)).scalar_one_or_none()
            if not res:
                continue
            if int(getattr(res, "food", 0) or 0) >= need_f and int(getattr(res, "water", 0) or 0) >= need_w:
                res.food = int(getattr(res, "food", 0) or 0) - need_f
                res.water = int(getattr(res, "water", 0) or 0) - need_w
                continue
            op.status = "offline"
            op.updated_at = datetime.utcnow()
            self._emit_event(
                s,
                tick=tick,
                type="outpost_offline",
                message="Форпост отключён: не хватило еды/воды на логистику снабжения",
                payload={
                    "outpost_id": str(op.id),
                    "reason": "supply_logistics_unpaid",
                    "hub_planet_id": str(hub.id),
                    "need": {"food": need_f, "water": need_w},
                    "have": {"food": int(getattr(res, "food", 0) or 0), "water": int(getattr(res, "water", 0) or 0)},
                },
                player_id=op.owner_player_id,
            )

    def get_supply_state(self, s: Session, *, player_id: str, x: int, y: int, z: int = 0) -> dict:
        """Снабжение: радиус хаба + непрерывный L-маршрут без чужих флотов на пути (фаза «как»)."""
        pid = uuid.UUID(player_id)
        base_tail = {"supply_base": self.SUPPLY_BASE_RADIUS, "supply_per_supplier": self.SUPPLY_PER_SUPPLIER}
        if int(z) != 0:
            return {
                "ok": True,
                "in_supply": False,
                "nearest_hub": None,
                "supply_radius": 0,
                "distance": None,
                "route_clear": False,
                "route_blocked_at": None,
                "supply_path": "manhattan_L",
                **base_tail,
            }
        rows = self._planet_supply_candidates(s, owner_id=pid, x=int(x), y=int(y))
        if not rows:
            return {
                "ok": True,
                "in_supply": False,
                "nearest_hub": None,
                "supply_radius": 0,
                "distance": None,
                "route_clear": False,
                "route_blocked_at": None,
                "supply_path": "manhattan_L",
                **base_tail,
            }
        in_range = [(p, r, d) for p, r, d in rows if r > 0 and d <= r]
        best_blocked: tuple[int, int] | None = None
        best_tuple: tuple[Planet, int, int] | None = None
        if in_range:
            for p, r, d in sorted(in_range, key=lambda t: t[2]):
                path = self._manhattan_l_path_cells(int(p.pos_x), int(p.pos_y), int(x), int(y))
                blk = self._supply_route_block_cell(s, owner_id=pid, path_cells=path)
                base_add_t, per_add_t = self._supply_radius_modifiers_for_player(s, player_id=p.owner_player_id)
                base_add_b, per_add_b = self._supply_radius_modifiers_for_planet_buildings(s, planet_id=p.id)
                eff_base = int(self.SUPPLY_BASE_RADIUS) + int(base_add_t) + int(base_add_b)
                eff_per = int(self.SUPPLY_PER_SUPPLIER) + int(per_add_t) + int(per_add_b)
                if blk is None:
                    return {
                        "ok": True,
                        "in_supply": True,
                        "nearest_hub": {"type": "planet", "id": str(p.id), "x": int(p.pos_x), "y": int(p.pos_y), "z": 0},
                        "supply_radius": int(r),
                        "distance": int(d),
                        "route_clear": True,
                        "route_blocked_at": None,
                        "supplier_count": int(getattr(p, "supplier_count", 0) or 0),
                        "supply_path": "manhattan_L",
                        "supply_base": eff_base,
                        "supply_per_supplier": eff_per,
                    }
                if best_tuple is None:
                    best_tuple = (p, r, d)
                    best_blocked = blk
            p, r, d = best_tuple if best_tuple else min(in_range, key=lambda t: t[2])
            base_add_t, per_add_t = self._supply_radius_modifiers_for_player(s, player_id=p.owner_player_id)
            base_add_b, per_add_b = self._supply_radius_modifiers_for_planet_buildings(s, planet_id=p.id)
            eff_base = int(self.SUPPLY_BASE_RADIUS) + int(base_add_t) + int(base_add_b)
            eff_per = int(self.SUPPLY_PER_SUPPLIER) + int(per_add_t) + int(per_add_b)
            return {
                "ok": True,
                "in_supply": False,
                "nearest_hub": {"type": "planet", "id": str(p.id), "x": int(p.pos_x), "y": int(p.pos_y), "z": 0},
                "supply_radius": int(r),
                "distance": int(d),
                "route_clear": False,
                "route_blocked_at": ({"x": best_blocked[0], "y": best_blocked[1]} if best_blocked else None),
                "supplier_count": int(getattr(p, "supplier_count", 0) or 0),
                "supply_path": "manhattan_L",
                "supply_base": eff_base,
                "supply_per_supplier": eff_per,
            }
        p, r, d = min(rows, key=lambda t: t[2])
        base_add_t, per_add_t = self._supply_radius_modifiers_for_player(s, player_id=p.owner_player_id)
        base_add_b, per_add_b = self._supply_radius_modifiers_for_planet_buildings(s, planet_id=p.id)
        eff_base = int(self.SUPPLY_BASE_RADIUS) + int(base_add_t) + int(base_add_b)
        eff_per = int(self.SUPPLY_PER_SUPPLIER) + int(per_add_t) + int(per_add_b)
        return {
            "ok": True,
            "in_supply": False,
            "nearest_hub": {"type": "planet", "id": str(p.id), "x": int(p.pos_x), "y": int(p.pos_y), "z": 0},
            "supply_radius": int(r),
            "distance": int(d),
            "route_clear": False,
            "route_blocked_at": None,
            "supplier_count": int(getattr(p, "supplier_count", 0) or 0),
            "supply_path": "manhattan_L",
            "supply_base": eff_base,
            "supply_per_supplier": eff_per,
        }

    def hire_supplier(self, s: Session, *, player_id: str, planet_id: str | None = None) -> dict:
        pid = uuid.UUID(player_id)
        planet: Planet | None = None
        if planet_id:
            try:
                plid = uuid.UUID(str(planet_id).strip())
            except Exception:
                return {"ok": False, "error": "invalid_planet_id"}
            planet = s.execute(select(Planet).where(Planet.id == plid, Planet.owner_player_id == pid)).scalar_one_or_none()
        else:
            planet = s.execute(select(Planet).where(Planet.owner_player_id == pid).order_by(Planet.created_at.asc())).scalar_one_or_none()
        if not planet:
            return {"ok": False, "error": "no_planet"}
        need = {"metal": 120, "crystal": 40, "energy": 0, "fuel": 0}
        if self._balance:
            try:
                u = self._balance.get_unit("supplier_t1")
                bc = (u.get("build") if isinstance(u, dict) else None) or {}
                cst = bc.get("cost") if isinstance(bc.get("cost"), dict) else {}
                for k in need:
                    if isinstance(cst.get(k), (int, float)):
                        need[k] = int(cst[k])
            except Exception:
                pass
        res = s.execute(select(Resource).where(Resource.planet_id == planet.id)).scalar_one_or_none()
        if not res:
            return {"ok": False, "error": "no_resources"}
        if (
            int(res.metal) < need["metal"]
            or int(res.crystal) < need["crystal"]
            or int(res.energy) < need["energy"]
            or int(getattr(res, "fuel", 0)) < need["fuel"]
        ):
            return {"ok": False, "error": "not_enough_resources", "need": need}
        res.metal -= need["metal"]
        res.crystal -= need["crystal"]
        res.energy -= need["energy"]
        if hasattr(res, "fuel"):
            res.fuel = int(getattr(res, "fuel", 0)) - need["fuel"]
        before_r = self._planet_supply_radius(s, planet=planet)
        planet.supplier_count = int(getattr(planet, "supplier_count", 0) or 0) + 1
        after_r = self._planet_supply_radius(s, planet=planet)
        tick = int(self.get_or_create_world_state(s).current_tick)
        self._emit_event(
            s,
            tick=tick,
            type="supplier_hired",
            message="Нанят снабженец",
            payload={"planet_id": str(planet.id), "supplier_count": int(planet.supplier_count)},
            player_id=pid,
        )
        self._emit_event(
            s,
            tick=tick,
            type="supply_radius_changed",
            message=f"Радиус снабжения увеличен до {after_r}",
            payload={"planet_id": str(planet.id), "radius_before": before_r, "radius_after": after_r},
            player_id=pid,
        )
        s.flush()
        return {
            "ok": True,
            "planet_id": str(planet.id),
            "supplier_count": int(planet.supplier_count),
            "supply_radius": after_r,
            "cost": need,
        }

    def _is_cell_supplied(self, s: Session, *, owner_id: uuid.UUID, x: int, y: int, z: int) -> bool:
        if int(z) != 0:
            return False
        rows = self._planet_supply_candidates(s, owner_id=owner_id, x=int(x), y=int(y))
        for p, r, d in rows:
            if r <= 0 or d > r:
                continue
            path = self._manhattan_l_path_cells(int(p.pos_x), int(p.pos_y), int(x), int(y))
            if self._supply_route_block_cell(s, owner_id=owner_id, path_cells=path) is None:
                return True
        return False

    def _unit_build_cost_parts(self, logical_type: str) -> dict[str, int]:
        if not self._balance:
            return {"metal": 50, "crystal": 20, "energy": 0, "fuel": 0}
        u = self._balance.get_unit(logical_type)
        bc = (u.get("build") if isinstance(u, dict) else None) or {}
        cst = bc.get("cost") if isinstance(bc.get("cost"), dict) else {}
        out = {"metal": 0, "crystal": 0, "energy": 0, "fuel": 0}
        for k in list(out.keys()):
            if isinstance(cst.get(k), (int, float)):
                out[k] = int(cst[k])
        return out

    def _pick_start_pos(self, s: Session) -> tuple[int, int]:
        # Спавним игроков на достаточном расстоянии (тихий старт / защита новичка).
        # MVP: пытаемся найти точку, которая минимум в 25 клетках по манхэттену от любой другой планеты.
        # Диапазон потом можно расширить до 100+.
        min_dist = 25
        attempts = 200
        bounds = 250

        existing = s.execute(select(Planet.pos_x, Planet.pos_y)).all()
        occupied = set((x, y) for x, y in existing)

        if not existing:
            return 0, 0

        for _ in range(attempts):
            x = random.randint(-bounds, bounds)
            y = random.randint(-bounds, bounds)
            if (x, y) in occupied:
                continue
            if all((abs(x - ex) + abs(y - ey)) >= min_dist for ex, ey in existing):
                return x, y

        # fallback: найдём "самую далёкую" из нескольких кандидатов
        best = None
        best_score = -1
        for _ in range(100):
            x = random.randint(-bounds, bounds)
            y = random.randint(-bounds, bounds)
            if (x, y) in occupied:
                continue
            score = min(abs(x - ex) + abs(y - ey) for ex, ey in existing)
            if score > best_score:
                best_score = score
                best = (x, y)
        return best if best else (random.randint(-bounds, bounds), random.randint(-bounds, bounds))

    def ensure_player_has_start(self, s: Session, *, player_id: uuid.UUID) -> None:
        planet = s.execute(select(Planet).where(Planet.owner_player_id == player_id)).scalar_one_or_none()
        if planet:
            return

        x, y = self._pick_start_pos(s)
        rid = self._get_player_race_id(s, player_id=player_id) or "human"
        # MVP: для "людей" (техническая/простая раса) — землеподобная планета.
        # Разброс небольшой, чтобы не ломать баланс старта.
        if rid == "human":
            planet_class = "earthlike"
            slots_total = random.randint(50, 60)
            max_pop = random.randint(5000, 7000)
        else:
            # Фолбэк для прочих рас до появления полноценного генератора.
            planet_class = "earthlike"
            slots_total = random.randint(48, 62)
            max_pop = random.randint(4800, 7200)
        planet = Planet(
            owner_player_id=player_id,
            name="Терра Прайм",
            pos_x=x,
            pos_y=y,
            population=800,
            max_population=max_pop,
            planet_class=planet_class,
            build_slots_total=slots_total,
        )
        s.add(planet)
        s.flush()

        s.add(Resource(planet_id=planet.id, metal=500, crystal=250, energy=100, fuel=100, food=120, water=120))
        # Стартовые корабли должны быть видимы на карте и "стоять вокруг" планеты:
        # - выше планеты: 1 fighter
        # - слева: 1 scout
        # - справа: 1 scout
        #
        # Сток на планете оставляем нулевым, чтобы движение не "печатало" новые корабли.
        s.add(Unit(owner_player_id=player_id, planet_id=planet.id, unit_type="scout", qty=0))
        s.add(Unit(owner_player_id=player_id, planet_id=planet.id, unit_type="fighter", qty=0))

        s.add(
            Fleet(
                owner_player_id=player_id,
                unit_type="fighter",
                qty=1,
                pos_x=x,
                pos_y=y - 1,
                pos_z=0,
                name=fleet_display_name_for_index(0),
                energy=100,
                max_energy=100,
            )
        )
        s.add(
            Fleet(
                owner_player_id=player_id,
                unit_type="scout",
                qty=1,
                pos_x=x - 1,
                pos_y=y,
                pos_z=0,
                name=fleet_display_name_for_index(1),
                energy=100,
                max_energy=100,
            )
        )
        s.add(
            Fleet(
                owner_player_id=player_id,
                unit_type="scout",
                qty=1,
                pos_x=x + 1,
                pos_y=y,
                pos_z=0,
                name=fleet_display_name_for_index(2),
                energy=100,
                max_energy=100,
            )
        )
        s.flush()
        for fleet in s.execute(select(Fleet).where(Fleet.owner_player_id == player_id)).scalars().all():
            self._sync_fleet_ships_from_legacy(s, fleet)
        self._spawn_mvp_bandit_patrol_near(s, home_x=x, home_y=y)
        s.add(ResourceTick(planet_id=planet.id, last_collected_at=datetime.now(timezone.utc)))
        # tick — мировая сущность, но старый GameClock оставляем как совместимость до миграции.
        self.get_or_create_world_state(s)
        self.get_or_create_clock(s)

    def get_or_create_world_state(self, s: Session) -> WorldState:
        ws = s.execute(select(WorldState).where(WorldState.id == 1)).scalar_one_or_none()
        if not ws:
            ws = WorldState(id=1, current_tick=0, updated_at=datetime.now(timezone.utc))
            s.add(ws)
            s.flush()
        return ws

    def get_or_create_clock(self, s: Session) -> GameClock:
        clock = s.execute(select(GameClock).where(GameClock.id == 1)).scalar_one_or_none()
        if not clock:
            clock = GameClock(id=1, current_tick=0, updated_at=datetime.now(timezone.utc))
            s.add(clock)
            s.flush()
        return clock

    def _emit_event(
        self,
        s: Session,
        *,
        tick: int,
        type: str,
        message: str,
        payload: dict | None = None,
        player_id: uuid.UUID | None = None,
    ) -> None:
        s.add(
            Event(
                tick=tick,
                type=type,
                message=message,
                payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
                player_id=player_id,
            )
        )

    def apply_resource_tick(self, s: Session, *, planet_id: uuid.UUID) -> None:
        res = s.execute(select(Resource).where(Resource.planet_id == planet_id)).scalar_one_or_none()
        if not res:
            return

        tick = s.execute(select(ResourceTick).where(ResourceTick.planet_id == planet_id)).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if not tick:
            s.add(ResourceTick(planet_id=planet_id, last_collected_at=now))
            s.flush()
            return

        delta = now - tick.last_collected_at
        minutes = int(delta.total_seconds() // 60)
        if minutes <= 0:
            return

        res.metal += minutes * 60
        res.crystal += minutes * 30
        res.energy += minutes * 20
        tick.last_collected_at = now
        s.flush()

    def apply_fleet_upkeep_tick(self, s: Session, *, player_id: uuid.UUID, tick: int) -> None:
        # MVP: поддержание флота тратит ЛОКАЛЬНУЮ энергию флота (не энергию империи).
        fleets = s.execute(select(Fleet).where(Fleet.owner_player_id == player_id)).scalars().all()
        if not fleets:
            return
        for f in fleets:
            units_map = self._fleet_units_map(s, f)
            if not units_map:
                continue
            cost = int(self._fleet_upkeep_energy_total(s, player_id=player_id, units=units_map))
            if cost <= 0:
                continue
            cur = int(getattr(f, "energy", 0) or 0)
            cur = max(0, cur - cost)
            f.energy = cur
        s.flush()

    def _capital_planet_for_player(self, s: Session, *, player_id: uuid.UUID) -> Planet | None:
        return (
            s.execute(
                select(Planet).where(Planet.owner_player_id == player_id).order_by(Planet.created_at.asc()).limit(1)
            )
            .scalars()
            .first()
        )

    def _fleet_empire_upkeep_costs(self, *, fleets: int, ships: int) -> dict[str, int]:
        eco = self._balance.pack.economy if self._balance and isinstance(getattr(self._balance, "pack", None), object) else {}
        blk = eco.get("fleet_empire_upkeep") if isinstance(eco, dict) else None
        if not isinstance(blk, dict):
            return {"metal": 0, "crystal": 0}
        mf = int(blk.get("metal_per_sol_per_fleet", 0) or 0)
        cf = int(blk.get("crystal_per_sol_per_fleet", 0) or 0)
        ms = int(blk.get("metal_per_sol_per_ship", 0) or 0)
        cs = int(blk.get("crystal_per_sol_per_ship", 0) or 0)
        return {
            "metal": max(0, mf) * max(0, int(fleets)) + max(0, ms) * max(0, int(ships)),
            "crystal": max(0, cf) * max(0, int(fleets)) + max(0, cs) * max(0, int(ships)),
        }

    def _fleet_empire_upkeep_unpaid_penalty_energy(self) -> int:
        eco = self._balance.pack.economy if self._balance and isinstance(getattr(self._balance, "pack", None), object) else {}
        blk = eco.get("fleet_empire_upkeep") if isinstance(eco, dict) else None
        if not isinstance(blk, dict):
            return 25
        return max(0, int(blk.get("energy_penalty_on_unpaid", 25) or 25))

    def _apply_fleet_empire_upkeep_tick(self, s: Session, *, tick: int) -> None:
        """Имперское содержание флотов (кроме локальной энергии флота).

        Платим с "капитальной" (самой ранней) планеты игрока из её складских ресурсов.
        Если не хватает — штрафуем конкретный флот снижением локальной энергии и пишем событие.
        """
        if not self._balance:
            return
        eco = self._balance.pack.economy if isinstance(getattr(self._balance, "pack", None), object) else {}
        blk = eco.get("fleet_empire_upkeep") if isinstance(eco, dict) else None
        if not isinstance(blk, dict):
            return

        mf = int(blk.get("metal_per_sol_per_fleet", 0) or 0)
        cf = int(blk.get("crystal_per_sol_per_fleet", 0) or 0)
        ms = int(blk.get("metal_per_sol_per_ship", 0) or 0)
        cs = int(blk.get("crystal_per_sol_per_ship", 0) or 0)
        if max(mf, cf, ms, cs) <= 0:
            return

        penalty = self._fleet_empire_upkeep_unpaid_penalty_energy()

        owner_ids = s.execute(select(Fleet.owner_player_id).where(Fleet.qty > 0).distinct()).scalars().all()
        for oid in owner_ids:
            cap = self._capital_planet_for_player(s, player_id=oid)
            if not cap:
                continue
            res = s.execute(select(Resource).where(Resource.planet_id == cap.id)).scalar_one_or_none()
            if not res:
                continue

            fleets = (
                s.execute(
                    select(Fleet)
                    .where(Fleet.owner_player_id == oid, Fleet.qty > 0)
                    .order_by(Fleet.created_at.asc(), Fleet.id.asc())
                )
                .scalars()
                .all()
            )
            for f in fleets:
                units_map = self._fleet_units_map(s, f)
                ships = sum(max(0, int(q)) for q in (units_map or {}).values())
                need = self._fleet_empire_upkeep_costs(fleets=1, ships=ships)
                if need["metal"] <= 0 and need["crystal"] <= 0:
                    continue

                have_m = int(getattr(res, "metal", 0) or 0)
                have_c = int(getattr(res, "crystal", 0) or 0)
                if have_m >= need["metal"] and have_c >= need["crystal"]:
                    res.metal = have_m - need["metal"]
                    res.crystal = have_c - need["crystal"]
                    continue

                if penalty > 0:
                    cur = int(getattr(f, "energy", 0) or 0)
                    f.energy = max(0, cur - penalty)
                self._emit_event(
                    s,
                    tick=tick,
                    type="fleet_maintenance_failed",
                    message=f"Империя не может оплатить содержание флота «{f.name or f.unit_type}»",
                    payload={
                        "fleet_id": str(f.id),
                        "capital_planet_id": str(cap.id),
                        "need": need,
                        "have": {"metal": have_m, "crystal": have_c},
                        "penalty_energy": penalty,
                    },
                    player_id=oid,
                )
        s.flush()

    def _apply_fleet_energy_tick(self, s: Session, *, tick: int) -> None:
        """Реген/пополнение энергии флота.

        Принцип: энергия появляется только если есть снабжение или "хаб" (планета/форпост).
        """
        fleets = s.execute(select(Fleet).where(Fleet.qty > 0)).scalars().all()
        if not fleets:
            return
        for f in fleets:
            mx = int(getattr(f, "max_energy", 100) or 100)
            cur = int(getattr(f, "energy", 0) or 0)
            # Хаб пополнения: на своей планете или у активного (и снабжённого) форпоста.
            on_planet = (
                int(getattr(f, "pos_z", 0) or 0) == 0
                and s.execute(
                    select(Planet.id).where(
                        Planet.owner_player_id == f.owner_player_id,
                        Planet.pos_x == int(f.pos_x),
                        Planet.pos_y == int(f.pos_y),
                    )
                ).first()
            )
            on_outpost = (
                s.execute(
                    select(Outpost.id).where(
                        Outpost.owner_player_id == f.owner_player_id,
                        Outpost.x == int(f.pos_x),
                        Outpost.y == int(f.pos_y),
                        Outpost.z == int(getattr(f, "pos_z", 0) or 0),
                        Outpost.status == "active",
                    )
                ).first()
                is not None
            )
            if on_planet or on_outpost:
                f.energy = mx
                continue

            # Реген только в снабжении.
            if self._is_cell_supplied(
                s, owner_id=f.owner_player_id, x=int(f.pos_x), y=int(f.pos_y), z=int(getattr(f, "pos_z", 0) or 0)
            ):
                f.energy = min(mx, cur + 2)
        s.flush()

    def _nearest_return_hub(self, s: Session, *, owner_id: uuid.UUID, x: int, y: int, z: int) -> tuple[int, int, int] | None:
        """Ближайшая точка пополнения: своя планета или активный форпост.

        Предпочитаем хаб без флота в клетке (чтобы аварийный возврат не упирался в занятую клетку).
        Если все хабы заняты — ближайший по Манхэттену (дальше обработка ордера).
        """
        if int(z) != 0:
            return None
        hubs: list[tuple[int, int, int]] = []
        for p in s.execute(select(Planet).where(Planet.owner_player_id == owner_id)).scalars().all():
            hubs.append((int(p.pos_x), int(p.pos_y), 0))
        for op in s.execute(select(Outpost).where(Outpost.owner_player_id == owner_id, Outpost.z == 0, Outpost.status == "active")).scalars().all():
            hubs.append((int(op.x), int(op.y), int(op.z)))
        if not hubs:
            return None
        scored: list[tuple[int, tuple[int, int, int]]] = []
        for hx, hy, hz in hubs:
            d = abs(int(hx) - int(x)) + abs(int(hy) - int(y))
            scored.append((d, (int(hx), int(hy), int(hz))))
        scored.sort(key=lambda t: t[0])
        for _d, (hx, hy, hz) in scored:
            blocked = (
                s.execute(
                    select(Fleet.id).where(
                        Fleet.pos_x == int(hx),
                        Fleet.pos_y == int(hy),
                        Fleet.pos_z == int(hz),
                    )
                ).first()
                is not None
            )
            if not blocked:
                return (hx, hy, hz)
        return scored[0][1]

    def _fleet_adjacent_to_enemy_occupied_hub(self, s: Session, *, fleet: Fleet) -> bool:
        """Флот на соседней с хабом клетке, а клетка хаба занята чужим флотом.

        Иначе каждый тик создаётся новый emergency_return до хаба (осцилляция).
        """
        owner_id = fleet.owner_player_id
        if int(getattr(fleet, "pos_z", 0) or 0) != 0:
            return False
        fx, fy = int(fleet.pos_x), int(fleet.pos_y)
        hubs: list[tuple[int, int, int]] = []
        for p in s.execute(select(Planet).where(Planet.owner_player_id == owner_id)).scalars().all():
            hubs.append((int(p.pos_x), int(p.pos_y), 0))
        for op in s.execute(select(Outpost).where(Outpost.owner_player_id == owner_id, Outpost.z == 0, Outpost.status == "active")).scalars().all():
            hubs.append((int(op.x), int(op.y), int(op.z)))
        for hx, hy, hz in hubs:
            foe = (
                s.execute(
                    select(Fleet).where(
                        Fleet.pos_x == int(hx),
                        Fleet.pos_y == int(hy),
                        Fleet.pos_z == int(hz),
                        Fleet.owner_player_id != owner_id,
                    )
                )
                .scalars()
                .first()
            )
            if not foe:
                continue
            if abs(fx - int(hx)) + abs(fy - int(hy)) == 1:
                return True
        return False

    def _apply_emergency_return_orders(self, s: Session, *, tick: int) -> None:
        """Если флот без энергии и не в снабжении — ставим аварийный возврат к хабу.

        Это "буксировка/аварийный режим": не требует топлива и энергии на постановку.
        """
        fleets = s.execute(select(Fleet).where(Fleet.qty > 0)).scalars().all()
        if not fleets:
            return
        ws = self.get_or_create_world_state(s)
        for f in fleets:
            if int(getattr(f, "pos_z", 0) or 0) != 0:
                continue
            if int(getattr(f, "energy", 0) or 0) > 0:
                continue
            # если в снабжении — энергия скоро появится, не дёргаем
            if self._is_cell_supplied(s, owner_id=f.owner_player_id, x=int(f.pos_x), y=int(f.pos_y), z=0):
                continue
            if self._active_order_for_fleet(s, fleet_id=f.id):
                continue
            if self._fleet_adjacent_to_enemy_occupied_hub(s, fleet=f):
                continue
            hub = self._nearest_return_hub(s, owner_id=f.owner_player_id, x=int(f.pos_x), y=int(f.pos_y), z=0)
            if not hub:
                continue
            tx, ty, tz = hub
            if int(tx) == int(f.pos_x) and int(ty) == int(f.pos_y) and int(tz) == 0:
                continue
            dist = abs(int(tx) - int(f.pos_x)) + abs(int(ty) - int(f.pos_y))
            travel_ticks = max(1, dist)  # аварийно медленно: 1 клетка/тик
            order = FleetOrder(
                fleet_id=f.id,
                owner_player_id=f.owner_player_id,
                order_type="emergency_return",
                from_x=int(f.pos_x),
                from_y=int(f.pos_y),
                from_z=int(getattr(f, "pos_z", 0) or 0),
                target_x=int(tx),
                target_y=int(ty),
                target_z=0,
                qty=int(f.qty),
                status="queued",
                start_tick=int(ws.current_tick) + 1,
                finish_tick=int(ws.current_tick) + int(travel_ticks),
                force_attack=False,
                combat_prompt_expires_at=None,
            )
            s.add(order)
            s.flush()
            self._emit_event(
                s,
                tick=int(ws.current_tick),
                type="fleet_emergency_return",
                message=f"Аварийный возврат: флот → ({tx},{ty},{tz}) (нет энергии/снабжения)",
                payload={"order_id": str(order.id), "fleet_id": str(f.id), "target": {"x": tx, "y": ty, "z": tz}},
                player_id=f.owner_player_id,
            )

    def _hash_u32(self, x: int, y: int, z: int) -> int:
        raw = f"{self._world_seed}:{x}:{y}:{z}".encode("utf-8")
        d = hashlib.sha256(raw).digest()
        return int.from_bytes(d[:4], "big", signed=False)

    def get_cell_terrain(self, *, x: int, y: int, z: int) -> dict:
        r = self._hash_u32(x, y, z) % 1000

        if r < 650:
            terrain = "empty"
            glyph = "."
        elif r < 820:
            terrain = "asteroids"
            glyph = "A"
        elif r < 910:
            terrain = "nebula"
            glyph = "N"
        elif r < 970:
            terrain = "ruins"
            glyph = "R"
        else:
            terrain = "anomaly"
            glyph = "?"

        if z != 0:
            if terrain == "asteroids" and (r % 4 == 0):
                terrain, glyph = "empty", "."
            if terrain == "empty" and (r % 7 == 0):
                terrain, glyph = "anomaly", "?"

        return {"terrain": terrain, "glyph": glyph}

    def get_player_overview(self, s: Session, *, player_id: str) -> dict:
        pid = uuid.UUID(player_id)

        player = s.execute(select(Player).where(Player.id == pid)).scalar_one_or_none()
        planet = s.execute(select(Planet).where(Planet.owner_player_id == pid)).scalar_one_or_none()
        if not planet:
            return {"player_id": player_id, "display_name": player.display_name if player else player_id, "planets": []}

        res = s.execute(select(Resource).where(Resource.planet_id == planet.id)).scalar_one_or_none()
        units = s.execute(select(Unit).where(Unit.planet_id == planet.id).order_by(Unit.unit_type)).scalars().all()

        return {
            "player_id": player_id,
            "display_name": player.display_name if player else player_id,
            "planets": [
                {
                    "id": str(planet.id),
                    "name": planet.name,
                    "pos": {"x": planet.pos_x, "y": planet.pos_y},
                    "resources": {
                        "metal": res.metal if res else 0,
                        "crystal": res.crystal if res else 0,
                        "energy": res.energy if res else 0,
                        "fuel": int(getattr(res, "fuel", 0)) if res else 0,
                        "food": int(getattr(res, "food", 0)) if res else 0,
                        "water": int(getattr(res, "water", 0)) if res else 0,
                    },
                    "units": [{"unit_type": u.unit_type, "qty": u.qty} for u in units],
                }
            ],
        }

    def _planet_production_deltas(
        self, s: Session, *, planet: Planet, influence_sources: list[dict] | None = None
    ) -> dict[str, int]:
        if self._balance:
            base = self._balance.get_base_production()
        else:
            prod = calc_planet_production()
            base = {
                "metal": int(prod.metal_per_tick),
                "crystal": int(prod.crystal_per_tick),
                "energy": int(prod.energy_per_tick),
                "fuel": int(prod.fuel_per_tick),
                "food": int(prod.food_per_tick),
                "water": int(prod.water_per_tick),
            }

        bonus = {k: 0 for k in PLANET_STORE_KEYS}
        if self._balance:
            b_rows = (
                s.execute(select(Building).where(Building.owner_player_id == planet.owner_player_id))
                .scalars()
                .all()
            )
            for b in b_rows:
                if not self._is_cell_supplied(
                    s, owner_id=planet.owner_player_id, x=int(b.x), y=int(b.y), z=int(getattr(b, "z", 0) or 0)
                ):
                    continue
                try:
                    bd = self._balance.get_building(b.building_type)
                except Exception:
                    bd = {}
                eff = bd.get("effects") if isinstance(bd, dict) else None
                prod_add = (eff.get("production_per_tick_add") if isinstance(eff, dict) else None) or {}
                for k in PLANET_STORE_KEYS:
                    if isinstance(prod_add.get(k), (int, float)):
                        bonus[k] += int(prod_add.get(k))
        else:
            bonus = self._get_building_bonus_for_player(s, player_id=planet.owner_player_id)

        mods = self._race_modifiers(s, player_id=planet.owner_player_id)
        mul = mods.get("production_multiplier") if isinstance(mods.get("production_multiplier"), dict) else {}
        tech_mul = self._tech_production_multipliers(s, player_id=planet.owner_player_id)

        sources = influence_sources if influence_sources is not None else self._collect_influence_sources(s)
        inf_scores = self._influence_scores_at(sources, int(planet.pos_x), int(planet.pos_y), 0)
        inf_mul = WorldService._planet_influence_production_multiplier(inf_scores, planet.owner_player_id)

        def _calc(k: str) -> int:
            m = float(mul.get(k, 1.0)) * float(tech_mul.get(k, 1.0))
            return int(round((base[k] + bonus[k]) * m * inf_mul))

        return {k: _calc(k) for k in PLANET_STORE_KEYS}

    def _population_vitals_upkeep_needs(self, *, population: int) -> tuple[int, int]:
        """Еда/вода на содержание населения за один сол (из economy.json)."""
        pop = max(0, int(population))
        if pop <= 0:
            return 0, 0
        ff, ww = 3, 3
        if self._balance and isinstance(self._balance.pack.economy, dict):
            pm = self._balance.pack.economy.get("population_maintenance")
            if isinstance(pm, dict):
                v = pm.get("food_per_1000_pop_per_tick")
                if isinstance(v, (int, float)):
                    ff = int(v)
                v2 = pm.get("water_per_1000_pop_per_tick")
                if isinstance(v2, (int, float)):
                    ww = int(v2)
        ff = max(0, ff)
        ww = max(0, ww)
        return (max(0, (pop * ff + 999) // 1000), max(0, (pop * ww + 999) // 1000))

    def apply_planet_production_tick(
        self, s: Session, *, planet_id: uuid.UUID, influence_sources: list[dict] | None = None
    ) -> dict:
        planet = s.execute(select(Planet).where(Planet.id == planet_id)).scalar_one_or_none()
        if not planet:
            return {k: 0 for k in PLANET_STORE_KEYS}
        res = s.execute(select(Resource).where(Resource.planet_id == planet_id)).scalar_one_or_none()
        if not res:
            return {k: 0 for k in PLANET_STORE_KEYS}

        deltas = self._planet_production_deltas(s, planet=planet, influence_sources=influence_sources)
        res.metal += deltas["metal"]
        res.crystal += deltas["crystal"]
        res.energy += deltas["energy"]
        res.fuel += deltas["fuel"]
        res.food += deltas["food"]
        res.water += deltas["water"]
        s.flush()

        if hasattr(planet, "population"):
            mx = self._effective_max_population(s, planet)
            pop = int(getattr(planet, "population", 0) or 0)
            pop = min(pop, mx)
            f_need, w_need = self._population_vitals_upkeep_needs(population=pop)
            cur_f, cur_w = int(res.food), int(res.water)
            take_f = min(cur_f, f_need)
            take_w = min(cur_w, w_need)
            res.food = cur_f - take_f
            res.water = cur_w - take_w
            fed_full = (f_need == 0 or take_f >= f_need) and (w_need == 0 or take_w >= w_need)
            severe_short = (f_need > 0 and take_f * 2 < f_need) or (w_need > 0 and take_w * 2 < w_need)
            if take_f == 0 and take_w == 0 and f_need + w_need > 0 and pop > 80:
                planet.population = max(0, pop - max(1, pop // 100))
            elif severe_short and pop > 150:
                planet.population = max(0, pop - max(1, pop // 250))
            pop = int(getattr(planet, "population", 0) or 0)
            pop = min(pop, mx)
            gap = mx - pop
            if fed_full and gap > 0:
                step = max(1, gap // 200)
                planet.population = min(mx, pop + step)
            elif pop > mx:
                planet.population = mx

        return deltas

    def get_sector_stub(self, s: Session, *, x: int | None, y: int | None, z: int = 0, player_id: str | None) -> dict:
        sector = {"x": x, "y": y, "z": z, "objects": [], "cell": None}
        if not player_id:
            return sector

        if x is None or y is None:
            return sector

        sector["cell"] = self.get_cell_terrain(x=x, y=y, z=z)
        if z == 0 and s.execute(select(Planet.id).where(Planet.pos_x == x, Planet.pos_y == y)).first():
            sector["cell"] = {"terrain": "planet", "glyph": "P"}

        pid = uuid.UUID(player_id)
        q = select(Planet).where(Planet.owner_player_id == pid)
        if z == 0:
            q = q.where(Planet.pos_x == x).where(Planet.pos_y == y)
        else:
            q = q.where(and_(False))

        planets = s.execute(q).scalars().all()
        owner_ids: set[uuid.UUID] = set(p.owner_player_id for p in planets)
        fleets_in_cell = (
            s.execute(
                select(Fleet).where(
                    Fleet.pos_x == x,
                    Fleet.pos_y == y,
                    Fleet.pos_z == z,
                )
            )
            .scalars()
            .all()
        )
        outposts_in_cell = (
            s.execute(select(Outpost).where(Outpost.x == x, Outpost.y == y, Outpost.z == z, Outpost.status == "active"))
            .scalars()
            .all()
        )
        for f in fleets_in_cell:
            owner_ids.add(f.owner_player_id)
        for op in outposts_in_cell:
            owner_ids.add(op.owner_player_id)
        owners = {}
        if owner_ids:
            owners = {
                str(p.id): p.display_name
                for p in s.execute(select(Player).where(Player.id.in_(list(owner_ids)))).scalars().all()
            }
        for p in planets:
            obj = {
                "type": "planet",
                "id": str(p.id),
                "name": p.name,
                "owner": str(p.owner_player_id),
                "owner_name": owners.get(str(p.owner_player_id)),
            }
            # Если планета игрока — добавим подробности для правой панели (MVP).
            if str(p.owner_player_id) == str(pid):
                res = s.execute(select(Resource).where(Resource.planet_id == p.id)).scalar_one_or_none()
                units = (
                    s.execute(select(Unit).where(Unit.planet_id == p.id).order_by(Unit.unit_type))
                    .scalars()
                    .all()
                )
                inf_src = self._collect_influence_sources(s)
                dlt = self._planet_production_deltas(s, planet=p, influence_sources=inf_src)
                production = {
                    "metal_per_tick": dlt["metal"],
                    "crystal_per_tick": dlt["crystal"],
                    "energy_per_tick": dlt["energy"],
                    "fuel_per_tick": dlt["fuel"],
                    "food_per_tick": dlt["food"],
                    "water_per_tick": dlt["water"],
                }
                built_total = int(
                    s.execute(select(func.count(Building.id)).where(Building.planet_id == p.id)).scalar() or 0
                )
                slots_total = int(getattr(p, "build_slots_total", 55) or 55)
                build = {"active": None, "queue": []}
                mxpop = self._effective_max_population(s, p)
                sr = self._planet_supply_radius(s, planet=p)
                ppop = int(getattr(p, "population", 0) or 0)
                f_up, w_up = self._population_vitals_upkeep_needs(population=ppop)
                obj["details"] = {
                    "resources": {
                        "metal": int(res.metal) if res else 0,
                        "crystal": int(res.crystal) if res else 0,
                        "energy": int(res.energy) if res else 0,
                        "fuel": int(getattr(res, "fuel", 0)) if res else 0,
                        "food": int(getattr(res, "food", 0)) if res else 0,
                        "water": int(getattr(res, "water", 0)) if res else 0,
                    },
                    "production": production,
                    "population": ppop,
                    "population_vitals": {"food_per_sol": f_up, "water_per_sol": w_up},
                    "max_population": mxpop,
                    "planet_class": str(getattr(p, "planet_class", "earthlike") or "earthlike"),
                    "build_slots": {"used": built_total, "total": slots_total},
                    "supplier_count": int(getattr(p, "supplier_count", 0) or 0),
                    "supply_radius": int(sr),
                    "supply_base": self.SUPPLY_BASE_RADIUS,
                    "supply_per_supplier": self.SUPPLY_PER_SUPPLIER,
                    "units": [{"unit_type": u.unit_type, "qty": int(u.qty)} for u in units],
                    "build": build,
                }
            sector["objects"].append(obj)

        for f in fleets_in_cell:
            comp = self._fleet_units_map(s, f)
            sector["objects"].append(
                {
                    "type": "fleet",
                    "id": str(f.id),
                    "name": self._fleet_public_name(f),
                    "unit_type": f.unit_type,
                    "qty": f.qty,
                    "composition": comp,
                    "energy": int(getattr(f, "energy", 0) or 0),
                    "max_energy": int(getattr(f, "max_energy", 100) or 100),
                    "owner": str(f.owner_player_id),
                    "owner_name": owners.get(str(f.owner_player_id)),
                }
            )
        for op in outposts_in_cell:
            st = self._outpost_stats(s, op)
            sector["objects"].append(
                {
                    "type": "outpost",
                    "id": str(op.id),
                    "owner": str(op.owner_player_id),
                    "owner_name": owners.get(str(op.owner_player_id)),
                    "x": int(op.x),
                    "y": int(op.y),
                    "z": int(op.z),
                    "details": st,
                    "name": st.get("name"),
                }
            )
        return sector

    def get_player_map_window(
        self,
        s: Session,
        *,
        player_id: str,
        radius: int = 4,
        z: int = 0,
        center_x: int | None = None,
        center_y: int | None = None,
    ) -> dict:
        pid = uuid.UUID(player_id)

        planet = s.execute(select(Planet).where(Planet.owner_player_id == pid)).scalar_one_or_none()
        if not planet:
            return {"center": None, "radius": radius, "z": z, "cells": []}

        cx, cy = (center_x if center_x is not None else planet.pos_x), (center_y if center_y is not None else planet.pos_y)
        x0, x1 = cx - radius, cx + radius
        y0, y1 = cy - radius, cy + radius

        planets = []
        if z == 0:
            planets = (
                s.execute(
                    select(Planet).where(
                        and_(Planet.pos_x >= x0, Planet.pos_x <= x1, Planet.pos_y >= y0, Planet.pos_y <= y1)
                    )
                )
                .scalars()
                .all()
            )

        # Подтягиваем display_name владельцев (планеты + флоты) одним запросом.
        owner_ids: set[uuid.UUID] = set(p.owner_player_id for p in planets)
        by_pos: dict[tuple[int, int], list[dict]] = {}
        for p in planets:
            owner_ids.add(p.owner_player_id)
            by_pos.setdefault((p.pos_x, p.pos_y), []).append(
                {"type": "planet", "id": str(p.id), "name": p.name, "owner": str(p.owner_player_id)}
            )

        # Флоты в окне (для объектов, которые могут оказаться видимыми).
        fleets = (
            s.execute(
                select(Fleet).where(
                    Fleet.pos_z == z,
                    and_(Fleet.pos_x >= x0, Fleet.pos_x <= x1, Fleet.pos_y >= y0, Fleet.pos_y <= y1),
                )
            )
            .scalars()
            .all()
        )
        for f in fleets:
            owner_ids.add(f.owner_player_id)

        owners = {}
        if owner_ids:
            owners = {
                str(p.id): p.display_name
                for p in s.execute(select(Player).where(Player.id.in_(list(owner_ids)))).scalars().all()
            }
        for f in fleets:
            by_pos.setdefault((f.pos_x, f.pos_y), []).append(
                {
                    "type": "fleet",
                    "id": str(f.id),
                    "name": self._fleet_public_name(f),
                    "unit_type": f.unit_type,
                    "qty": f.qty,
                    "composition": self._fleet_units_map(s, f),
                    "energy": int(getattr(f, "energy", 0) or 0),
                    "max_energy": int(getattr(f, "max_energy", 100) or 100),
                    "owner": str(f.owner_player_id),
                    "owner_name": owners.get(str(f.owner_player_id)),
                }
            )
        # дополним owner_name для планет, уже добавленных выше
        for pos, objs in by_pos.items():
            for o in objs:
                if o.get("type") == "planet":
                    o["owner_name"] = owners.get(o.get("owner"))

        # Постройки в окне (видны как объект на клетке).
        buildings = (
            s.execute(
                select(Building).where(
                    Building.z == z,
                    and_(Building.x >= x0, Building.x <= x1, Building.y >= y0, Building.y <= y1),
                )
            )
            .scalars()
            .all()
        )
        for b in buildings:
            owner_ids.add(b.owner_player_id)
        if buildings and owner_ids:
            owners = {
                str(p.id): p.display_name
                for p in s.execute(select(Player).where(Player.id.in_(list(owner_ids)))).scalars().all()
            }
        for b in buildings:
            by_pos.setdefault((b.x, b.y), []).append(
                {
                    "type": "building",
                    "id": str(b.id),
                    "building_type": b.building_type,
                    "level": int(b.level),
                    "owner": str(b.owner_player_id),
                    "owner_name": owners.get(str(b.owner_player_id)),
                }
            )

        outposts = (
            s.execute(
                select(Outpost).where(
                    Outpost.z == z,
                    Outpost.status == "active",
                    and_(Outpost.x >= x0, Outpost.x <= x1, Outpost.y >= y0, Outpost.y <= y1),
                )
            )
            .scalars()
            .all()
        )
        for op in outposts:
            owner_ids.add(op.owner_player_id)
        if outposts and owner_ids:
            owners = {
                str(p.id): p.display_name
                for p in s.execute(select(Player).where(Player.id.in_(list(owner_ids)))).scalars().all()
            }
        for op in outposts:
            st = self._outpost_stats(s, op)
            by_pos.setdefault((op.x, op.y), []).append(
                {
                    "type": "outpost",
                    "id": str(op.id),
                    "owner": str(op.owner_player_id),
                    "owner_name": owners.get(str(op.owner_player_id)),
                    "level": int(op.level),
                    "status": op.status,
                    "details": st,
                    "name": st.get("name"),
                }
            )

        inf_sources = self._collect_influence_sources(s)
        for src in inf_sources:
            owner_ids.add(src["owner"])
        if owner_ids:
            owners = {
                str(p.id): p.display_name
                for p in s.execute(select(Player).where(Player.id.in_(list(owner_ids)))).scalars().all()
            }
            for pos, objs in by_pos.items():
                for o in objs:
                    if o.get("type") == "planet":
                        o["owner_name"] = owners.get(o.get("owner"))

        control_rows = (
            s.execute(
                select(InfluenceCell).where(
                    InfluenceCell.z == z,
                    InfluenceCell.control_value > 0,
                    and_(InfluenceCell.x >= x0, InfluenceCell.x <= x1, InfluenceCell.y >= y0, InfluenceCell.y <= y1),
                )
            )
            .scalars()
            .all()
        )
        control_by_xy: dict[tuple[int, int], dict[uuid.UUID, float]] = defaultdict(dict)
        for r in control_rows:
            control_by_xy[(int(r.x), int(r.y))][r.player_id] = float(r.control_value)

        # --- Fog of war (MVP): 2 слоя ---
        # 1) unknown: игрок ни разу не видел клетку
        # 2) memory: игрок видел, но сейчас не видит (память хранится 10 тиков), далее -> stale (почти ничего не видно)
        vis_sources = self._collect_visibility_sources_for_player(s, player_id=pid, z=z)

        def _is_visible(x: int, y: int) -> bool:
            for sx, sy, r in vis_sources:
                if abs(x - sx) + abs(y - sy) <= r:
                    return True
            return False

        ws = self.get_or_create_world_state(s)
        now_tick = int(ws.current_tick)
        memory_ticks = 10

        explored_rows = (
            s.execute(
                select(ExploredSector).where(
                    ExploredSector.player_id == pid,
                    ExploredSector.z == z,
                    and_(ExploredSector.x >= x0, ExploredSector.x <= x1, ExploredSector.y >= y0, ExploredSector.y <= y1),
                )
            )
            .scalars()
            .all()
        )
        explored_by_xy = {(e.x, e.y): e for e in explored_rows}

        def _touch_explored(x: int, y: int) -> None:
            e = explored_by_xy.get((x, y))
            if not e:
                e = ExploredSector(player_id=pid, x=x, y=y, z=z, first_seen_tick=now_tick, last_seen_tick=now_tick)
                s.add(e)
                explored_by_xy[(x, y)] = e
                return
            e.last_seen_tick = now_tick

        # --- Зоны влияния/стройки (радиус 3 от планет). ---
        # В базовом варианте: зона врага видна, но строить там нельзя (геймплейно проверим позже).
        build_self: set[tuple[int, int]] = set()
        build_enemy: set[tuple[int, int]] = set()
        for p in planets:
            r = 3
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if abs(dx) + abs(dy) > r:
                        continue
                    tx, ty = p.pos_x + dx, p.pos_y + dy
                    if p.owner_player_id == pid:
                        build_self.add((tx, ty))
                    else:
                        build_enemy.add((tx, ty))

        cells: list[dict] = []
        for y in range(y0, y1 + 1):
            row: list[dict] = []
            for x in range(x0, x1 + 1):
                visible = _is_visible(x, y)
                if visible:
                    _touch_explored(x, y)
                explored = explored_by_xy.get((x, y))
                age = None
                if explored:
                    age = max(0, now_tick - int(explored.last_seen_tick))

                # unknown / memory / stale
                fog_state = "unknown"
                if explored and age is not None:
                    fog_state = "memory" if age <= memory_ticks else "stale"

                if visible:
                    objects = by_pos.get((x, y), [])
                    terrain = self.get_cell_terrain(x=x, y=y, z=z)
                    if any((o and o.get("type") == "planet") for o in objects):
                        terrain = {"terrain": "planet", "glyph": "P"}
                else:
                    # В тумане не показываем руины/астероиды и т.п.
                    # В stale оставляем только намёк на аномалию (серым вопросом).
                    objects = []
                    if fog_state == "stale":
                        terrain = {"terrain": "fog", "glyph": "?"}
                    else:
                        terrain = {"terrain": "fog", "glyph": ""}

                influence_payload = None
                if visible:
                    inc_scores = self._influence_scores_at(inf_sources, x, y, z)
                    ctl_scores = control_by_xy.get((x, y), {})
                    influence_payload = self._influence_cell_payload(inc_scores, pid, owners, ctl_scores)

                row.append(
                    {
                        "x": x,
                        "y": y,
                        "z": z,
                        "objects": objects,
                        "terrain": terrain["terrain"],
                        "glyph": terrain["glyph"],
                        "influence": influence_payload,
                        "flags": {
                            "is_center": (x == cx and y == cy and z == 0),
                            "has_objects": len(objects) > 0,
                            "is_visible": visible,
                            "fog_state": fog_state,
                            "seen_age": age,
                            # зоны
                            "zone_vision_self": bool(visible),
                            "zone_build_self": bool((x, y) in build_self),
                            "zone_build_enemy": bool((x, y) in build_enemy),
                        },
                    }
                )
            cells.append({"y": y, "row": row})

        s.flush()
        return {"center": {"x": cx, "y": cy}, "radius": radius, "z": z, "cells": cells}

    def build_outpost(self, s: Session, *, player_id: str, x: int, y: int, z: int, outpost_type: str, fleet_id: str | None = None) -> dict:
        pid = uuid.UUID(player_id)
        otype = str(outpost_type or "").strip()
        try:
            od = self._outpost_definition(otype)
        except Exception:
            return {"ok": False, "error": "invalid_outpost_type"}

        # Анти-спам: расстояние между своими форпостами должно быть не меньше базового радиуса обзора форпоста.
        vis = od.get("vision") if isinstance(od.get("vision"), dict) else {}
        min_dist = int(vis.get("base_radius", 6) or 6)
        if min_dist > 0:
            nearby = (
                s.execute(
                    select(Outpost)
                    .where(Outpost.owner_player_id == pid, Outpost.z == int(z), Outpost.status.in_(["active", "offline"]))
                )
                .scalars()
                .all()
            )
            nearest = None
            for op in nearby:
                d = abs(int(op.x) - int(x)) + abs(int(op.y) - int(y))
                if nearest is None or d < nearest:
                    nearest = d
            if nearest is not None and int(nearest) < int(min_dist):
                return {"ok": False, "error": "outpost_too_close", "need_distance": int(min_dist), "nearest": int(nearest)}

        gate = self._can_build_at(s, owner_id=pid, x=x, y=y, z=z, fleet_id=fleet_id)
        if not gate.get("ok"):
            return gate
        eng_fleet = self._owned_engineer_fleet_at(s, owner_id=pid, x=x, y=y, z=z, fleet_id=fleet_id)
        if not eng_fleet or int(self._fleet_units_map(s, eng_fleet).get("engineer", 0)) <= 0:
            return {"ok": False, "error": "engineer_required"}
        if s.execute(select(Outpost.id).where(Outpost.x == x, Outpost.y == y, Outpost.z == z, Outpost.status == "active")).scalars().first():
            return {"ok": False, "error": "cell_already_has_outpost"}
        if s.execute(select(Building.id).where(Building.x == x, Building.y == y, Building.z == z)).scalars().first():
            return {"ok": False, "error": "cell_already_built"}

        req_techs = self._outpost_required_techs(otype)
        if req_techs:
            done = set(self._get_player_done_techs(s, player_id=pid))
            missing = [tid for tid in req_techs if tid not in done]
            if missing:
                return {"ok": False, "error": "tech_required", "required_techs": req_techs, "missing_techs": missing}

        home = s.execute(select(Planet).where(Planet.owner_player_id == pid).order_by(Planet.created_at.asc())).scalar_one_or_none()
        if not home:
            return {"ok": False, "error": "no_home_planet"}
        res = s.execute(select(Resource).where(Resource.planet_id == home.id)).scalar_one_or_none()
        if not res:
            return {"ok": False, "error": "no_resources"}
        cost = (od.get("build") if isinstance(od.get("build"), dict) else {}).get("cost", {})
        need = {k: int(cost.get(k, 0)) for k in ("metal", "crystal", "energy", "fuel")}
        if int(res.metal) < need["metal"] or int(res.crystal) < need["crystal"] or int(res.energy) < need["energy"] or int(getattr(res, "fuel", 0)) < need["fuel"]:
            return {"ok": False, "error": "not_enough_resources", "need": need}

        eng_map = self._fleet_units_map(s, eng_fleet)
        eng_map["engineer"] = max(0, int(eng_map.get("engineer", 0)) - 1)
        self._write_fleet_units(s, eng_fleet, eng_map)

        res.metal -= need["metal"]
        res.crystal -= need["crystal"]
        res.energy -= need["energy"]
        if hasattr(res, "fuel"):
            res.fuel = int(getattr(res, "fuel", 0)) - need["fuel"]

        anchor_planet = self._resolve_owning_planet_for_build_site(s, owner_id=pid, x=x, y=y, z=z) or home
        slots = ((od.get("slots") if isinstance(od.get("slots"), dict) else {}) or {}).get("module_slots", 1)
        ws = self.get_or_create_world_state(s)
        start_tick = int(ws.current_tick)
        finish_tick = int(ws.current_tick)
        outpost = Outpost(
            owner_player_id=pid,
            planet_id=anchor_planet.id if anchor_planet else None,
            builder_fleet_id=eng_fleet.id,
            x=int(x),
            y=int(y),
            z=int(z),
            outpost_type=otype,
            family=str(od.get("family") or "outpost"),
            level=int(od.get("level", 1) or 1),
            module_slots_total=int(slots or 1),
            status="active",
            started_at_tick=start_tick,
            finish_tick=finish_tick,
            updated_at=datetime.utcnow(),
        )
        s.add(outpost)
        s.flush()
        return {"ok": True, "outpost": {"id": str(outpost.id), **self._outpost_stats(s, outpost), "x": x, "y": y, "z": z}}

    def upgrade_outpost(self, s: Session, *, player_id: str, outpost_id: str) -> dict:
        pid = uuid.UUID(player_id)
        try:
            oid = uuid.UUID(outpost_id)
        except Exception:
            return {"ok": False, "error": "invalid_outpost_id"}
        outpost = s.execute(select(Outpost).where(Outpost.id == oid, Outpost.owner_player_id == pid)).scalar_one_or_none()
        if not outpost:
            return {"ok": False, "error": "outpost_not_found"}
        od = self._outpost_definition(outpost.outpost_type)
        upgrade = od.get("upgrade") if isinstance(od.get("upgrade"), dict) else None
        if not upgrade or not upgrade.get("to"):
            return {"ok": False, "error": "outpost_upgrade_unavailable"}
        req_techs = [str(x) for x in upgrade.get("prereq_tech", []) if isinstance(x, str)]
        if req_techs:
            done = set(self._get_player_done_techs(s, player_id=pid))
            missing = [tid for tid in req_techs if tid not in done]
            if missing:
                return {"ok": False, "error": "tech_required", "required_techs": req_techs, "missing_techs": missing}
        home = s.execute(select(Planet).where(Planet.owner_player_id == pid).order_by(Planet.created_at.asc())).scalar_one_or_none()
        res = s.execute(select(Resource).where(Resource.planet_id == home.id)).scalar_one_or_none() if home else None
        if not home or not res:
            return {"ok": False, "error": "no_resources"}
        cost = upgrade.get("cost") if isinstance(upgrade.get("cost"), dict) else {}
        need = {k: int(cost.get(k, 0)) for k in ("metal", "crystal", "energy", "fuel")}
        if int(res.metal) < need["metal"] or int(res.crystal) < need["crystal"] or int(res.energy) < need["energy"] or int(getattr(res, "fuel", 0)) < need["fuel"]:
            return {"ok": False, "error": "not_enough_resources", "need": need}
        res.metal -= need["metal"]
        res.crystal -= need["crystal"]
        res.energy -= need["energy"]
        if hasattr(res, "fuel"):
            res.fuel = int(getattr(res, "fuel", 0)) - need["fuel"]
        outpost.outpost_type = str(upgrade["to"])
        newd = self._outpost_definition(outpost.outpost_type)
        outpost.level = int(newd.get("level", outpost.level))
        outpost.module_slots_total = int(((newd.get("slots") if isinstance(newd.get("slots"), dict) else {}) or {}).get("module_slots", outpost.module_slots_total))
        outpost.updated_at = datetime.utcnow()
        s.flush()
        return {"ok": True, "outpost": {"id": str(outpost.id), **self._outpost_stats(s, outpost), "x": outpost.x, "y": outpost.y, "z": outpost.z}}

    def install_outpost_module(self, s: Session, *, player_id: str, outpost_id: str, module_type: str) -> dict:
        pid = uuid.UUID(player_id)
        try:
            oid = uuid.UUID(outpost_id)
        except Exception:
            return {"ok": False, "error": "invalid_outpost_id"}
        outpost = s.execute(select(Outpost).where(Outpost.id == oid, Outpost.owner_player_id == pid)).scalar_one_or_none()
        if not outpost:
            return {"ok": False, "error": "outpost_not_found"}
        try:
            md = self._outpost_module_definition(module_type)
        except Exception:
            return {"ok": False, "error": "invalid_module_type"}
        req_techs = self._outpost_module_required_techs(module_type)
        if req_techs:
            done = set(self._get_player_done_techs(s, player_id=pid))
            missing = [tid for tid in req_techs if tid not in done]
            if missing:
                return {"ok": False, "error": "tech_required", "required_techs": req_techs, "missing_techs": missing}
        modules = self._outpost_module_rows(s, outpost_id=outpost.id)
        if len(modules) >= int(outpost.module_slots_total):
            return {"ok": False, "error": "outpost_slots_full"}
        eng_fleet = self._owned_engineer_fleet_at(s, owner_id=pid, x=int(outpost.x), y=int(outpost.y), z=int(outpost.z))
        if not eng_fleet:
            return {"ok": False, "error": "engineer_required"}
        eng_map = self._fleet_units_map(s, eng_fleet)
        spend = int(md.get("slot_cost_engineers", 1) or 1)
        if int(eng_map.get("engineer", 0)) < spend:
            return {"ok": False, "error": "not_enough_engineers", "need_engineers": spend}
        home = s.execute(select(Planet).where(Planet.owner_player_id == pid).order_by(Planet.created_at.asc())).scalar_one_or_none()
        res = s.execute(select(Resource).where(Resource.planet_id == home.id)).scalar_one_or_none() if home else None
        if not home or not res:
            return {"ok": False, "error": "no_resources"}
        cost = (md.get("build") if isinstance(md.get("build"), dict) else {}).get("cost", {})
        need = {k: int(cost.get(k, 0)) for k in ("metal", "crystal", "energy", "fuel")}
        if int(res.metal) < need["metal"] or int(res.crystal) < need["crystal"] or int(res.energy) < need["energy"] or int(getattr(res, "fuel", 0)) < need["fuel"]:
            return {"ok": False, "error": "not_enough_resources", "need": need}
        eng_map["engineer"] = max(0, int(eng_map.get("engineer", 0)) - spend)
        self._write_fleet_units(s, eng_fleet, eng_map)
        res.metal -= need["metal"]
        res.crystal -= need["crystal"]
        res.energy -= need["energy"]
        if hasattr(res, "fuel"):
            res.fuel = int(getattr(res, "fuel", 0)) - need["fuel"]
        used = {int(m.slot_idx) for m in modules}
        slot_idx = next((i for i in range(int(outpost.module_slots_total)) if i not in used), len(used))
        row = OutpostModule(
            outpost_id=outpost.id,
            module_type=module_type,
            kind=str(md.get("kind") or "utility"),
            level=int(md.get("level", 1) or 1),
            slot_idx=int(slot_idx),
            status="active",
            started_at_tick=int(self.get_or_create_world_state(s).current_tick),
            finish_tick=int(self.get_or_create_world_state(s).current_tick),
            updated_at=datetime.utcnow(),
        )
        s.add(row)
        s.flush()
        return {"ok": True, "outpost": {"id": str(outpost.id), **self._outpost_stats(s, outpost), "x": outpost.x, "y": outpost.y, "z": outpost.z}}

    def upgrade_outpost_module(self, s: Session, *, player_id: str, module_id: str) -> dict:
        pid = uuid.UUID(player_id)
        try:
            mid = uuid.UUID(module_id)
        except Exception:
            return {"ok": False, "error": "invalid_module_id"}
        row = (
            s.execute(select(OutpostModule).join(Outpost, Outpost.id == OutpostModule.outpost_id).where(OutpostModule.id == mid, Outpost.owner_player_id == pid))
            .scalars()
            .first()
        )
        if not row:
            return {"ok": False, "error": "module_not_found"}
        md = self._outpost_module_definition(row.module_type)
        upgrade = md.get("upgrade") if isinstance(md.get("upgrade"), dict) else None
        if not upgrade or not upgrade.get("to"):
            return {"ok": False, "error": "module_upgrade_unavailable"}
        req_techs = [str(x) for x in upgrade.get("prereq_tech", []) if isinstance(x, str)]
        if req_techs:
            done = set(self._get_player_done_techs(s, player_id=pid))
            missing = [tid for tid in req_techs if tid not in done]
            if missing:
                return {"ok": False, "error": "tech_required", "required_techs": req_techs, "missing_techs": missing}
        outpost = s.get(Outpost, row.outpost_id)
        eng_fleet = self._owned_engineer_fleet_at(s, owner_id=pid, x=int(outpost.x), y=int(outpost.y), z=int(outpost.z)) if outpost else None
        if not eng_fleet:
            return {"ok": False, "error": "engineer_required"}
        eng_map = self._fleet_units_map(s, eng_fleet)
        spend = int(md.get("slot_cost_engineers", 1) or 1)
        if int(eng_map.get("engineer", 0)) < spend:
            return {"ok": False, "error": "not_enough_engineers", "need_engineers": spend}
        home = s.execute(select(Planet).where(Planet.owner_player_id == pid).order_by(Planet.created_at.asc())).scalar_one_or_none()
        res = s.execute(select(Resource).where(Resource.planet_id == home.id)).scalar_one_or_none() if home else None
        if not home or not res:
            return {"ok": False, "error": "no_resources"}
        cost = upgrade.get("cost") if isinstance(upgrade.get("cost"), dict) else {}
        need = {k: int(cost.get(k, 0)) for k in ("metal", "crystal", "energy", "fuel")}
        if int(res.metal) < need["metal"] or int(res.crystal) < need["crystal"] or int(res.energy) < need["energy"] or int(getattr(res, "fuel", 0)) < need["fuel"]:
            return {"ok": False, "error": "not_enough_resources", "need": need}
        eng_map["engineer"] = max(0, int(eng_map.get("engineer", 0)) - spend)
        self._write_fleet_units(s, eng_fleet, eng_map)
        res.metal -= need["metal"]
        res.crystal -= need["crystal"]
        res.energy -= need["energy"]
        if hasattr(res, "fuel"):
            res.fuel = int(getattr(res, "fuel", 0)) - need["fuel"]
        row.module_type = str(upgrade["to"])
        new_md = self._outpost_module_definition(row.module_type)
        row.level = int(new_md.get("level", row.level) or row.level)
        row.kind = str(new_md.get("kind") or row.kind)
        row.updated_at = datetime.utcnow()
        s.flush()
        return {"ok": True, "outpost": {"id": str(outpost.id), **self._outpost_stats(s, outpost), "x": outpost.x, "y": outpost.y, "z": outpost.z}}

    def _can_build_at(
        self, s: Session, *, owner_id: uuid.UUID, x: int, y: int, z: int, fleet_id: str | None = None
    ) -> dict:
        if z != 0:
            return {"ok": False, "error": "z_not_supported_yet"}
        my_planets = s.execute(select(Planet).where(Planet.owner_player_id == owner_id)).scalars().all()
        if not my_planets:
            return {"ok": False, "error": "no_home_planet"}

        eng_fleet = self._owned_engineer_fleet_at(s, owner_id=owner_id, x=x, y=y, z=z, fleet_id=fleet_id)
        in_self = any((abs(p.pos_x - x) + abs(p.pos_y - y)) <= 3 for p in my_planets)
        if not in_self and not eng_fleet:
            return {"ok": False, "error": "engineer_required"}

        if self._cell_enemy_control_owner(s, owner_id=owner_id, x=x, y=y, z=z):
            return {"ok": False, "error": "inside_enemy_control_zone"}

        return {"ok": True, "builder_fleet_id": str(eng_fleet.id) if eng_fleet else None}

    def place_building(
        self,
        s: Session,
        *,
        player_id: str,
        x: int,
        y: int,
        z: int,
        building_type: str,
        fleet_id: str | None = None,
    ) -> dict:
        pid = uuid.UUID(player_id)
        btype = (building_type or "").strip().lower()
        if not btype:
            return {"ok": False, "error": "invalid_building_type"}

        build_def: dict | None = None
        if self._balance:
            aliases = self._balance.pack.aliases.get("building_aliases", {}) if self._balance.pack else {}
            allowed = set(aliases.keys()) if isinstance(aliases, dict) else set()
            if btype not in allowed:
                return {"ok": False, "error": "invalid_building_type"}
            try:
                build_def = self._balance.get_building(btype)
            except Exception:
                return {"ok": False, "error": "unknown_building"}
        elif btype not in (
            "mine",
            "reactor",
            "crystal_farm",
            "fuel_depot",
            "habitat",
            "research_lab",
            "drydock_mini",
            "solar_array",
            "cargo_yard",
            "sensor_mast",
        ):
            return {"ok": False, "error": "invalid_building_type"}

        req_techs = self._building_required_techs(btype)
        if req_techs:
            done = set(self._get_player_done_techs(s, player_id=pid))
            missing = [tid for tid in req_techs if tid not in done]
            if missing:
                return {"ok": False, "error": "tech_required", "required_techs": req_techs, "missing_techs": missing}

        # Основание для постройки: валидируем по типу ландшафта клетки.
        # Примеры из ТЗ: шахты только на астероидах; жилые/лаборатории нельзя строить в «пустом космосе».
        if build_def is not None:
            allowed_terrains = build_def.get("build_on_terrain") if isinstance(build_def, dict) else None
            if isinstance(allowed_terrains, list) and allowed_terrains:
                # Спец-правило: "planet" означает, что строить можно только в клетке планеты.
                if "planet" in allowed_terrains:
                    if not self._cell_has_planet(s, x=int(x), y=int(y), z=int(z)):
                        return {"ok": False, "error": "planet_required"}
                    allowed_terrains = [t for t in allowed_terrains if t != "planet"]
                    if not allowed_terrains:
                        allowed_terrains = None
                cell = self.get_cell_terrain(x=x, y=y, z=z)
                terrain = cell.get("terrain")
                if isinstance(allowed_terrains, list) and allowed_terrains and terrain not in allowed_terrains:
                    return {
                        "ok": False,
                        "error": "wrong_foundation_terrain",
                        "terrain": terrain,
                        "expected": allowed_terrains,
                    }
        else:
            if btype == "mine":
                cell = self.get_cell_terrain(x=x, y=y, z=z)
                if cell.get("terrain") != "asteroids":
                    return {
                        "ok": False,
                        "error": "wrong_foundation_terrain",
                        "terrain": cell.get("terrain"),
                        "expected": ["asteroids"],
                    }
            if btype in ("habitat", "research_lab"):
                cell = self.get_cell_terrain(x=x, y=y, z=z)
                if cell.get("terrain") == "empty":
                    return {
                        "ok": False,
                        "error": "wrong_foundation_terrain",
                        "terrain": cell.get("terrain"),
                        "expected": ["ruins", "nebula", "anomaly"],
                    }

        gate = self._can_build_at(s, owner_id=pid, x=x, y=y, z=z, fleet_id=fleet_id)
        if not gate.get("ok"):
            return gate

        planet = self._resolve_owning_planet_for_build_site(s, owner_id=pid, x=x, y=y, z=z)
        if not planet:
            planet = s.execute(select(Planet).where(Planet.owner_player_id == pid).order_by(Planet.created_at.asc())).scalar_one_or_none()
        if not planet:
            return {"ok": False, "error": "no_controlling_planet"}

        # Общие слоты планеты: ограничение только по "размеру" планеты, а не по типам.
        slots_total = int(getattr(planet, "build_slots_total", 55) or 55)
        built_total = int(
            s.execute(select(func.count(Building.id)).where(Building.planet_id == planet.id)).scalar() or 0
        )
        if built_total >= slots_total:
            return {
                "ok": False,
                "error": "planet_slots_full",
                "built": built_total,
                "total": slots_total,
            }

        exists = (
            s.execute(select(Building).where(Building.x == x, Building.y == y, Building.z == z))
            .scalars()
            .first()
        )
        if exists:
            return {"ok": False, "error": "cell_already_built"}

        home = s.execute(select(Planet).where(Planet.owner_player_id == pid)).scalar_one_or_none()
        if not home:
            return {"ok": False, "error": "no_home_planet"}
        res = s.execute(select(Resource).where(Resource.planet_id == home.id)).scalar_one_or_none()
        if not res:
            return {"ok": False, "error": "no_resources"}

        cost = {"metal": 0, "crystal": 0, "energy": 0, "fuel": 0}
        if self._balance:
            bobj = build_def or self._balance.get_building(btype)
            bc = bobj.get("build") if isinstance(bobj, dict) else {}
            cst = bc.get("cost") if isinstance(bc.get("cost"), dict) else {}
            for k in ("metal", "crystal", "energy", "fuel"):
                if isinstance(cst.get(k), (int, float)):
                    cost[k] = int(cst[k])
        else:
            cost = {"metal": 120, "crystal": 60, "energy": 0, "fuel": 0}
            if btype == "reactor":
                cost = {"metal": 160, "crystal": 40, "energy": 0, "fuel": 0}
            elif btype == "crystal_farm":
                cost = {"metal": 100, "crystal": 90, "energy": 0, "fuel": 0}

        if (
            int(res.metal) < cost["metal"]
            or int(res.crystal) < cost["crystal"]
            or int(res.energy) < cost["energy"]
            or int(getattr(res, "fuel", 0)) < cost["fuel"]
        ):
            self._emit_event(
                s,
                tick=self.get_or_create_world_state(s).current_tick,
                type="not_enough_resources",
                message=f"Не хватает ресурсов для постройки {btype}",
                payload={"need": cost, "have": {"metal": int(res.metal), "crystal": int(res.crystal)}},
                player_id=pid,
            )
            return {
                "ok": False,
                "error": "not_enough_resources",
                "need": cost,
                "have": {
                    "metal": int(res.metal),
                    "crystal": int(res.crystal),
                    "energy": int(res.energy),
                    "fuel": int(getattr(res, "fuel", 0)),
                },
            }

        res.metal -= cost["metal"]
        res.crystal -= cost["crystal"]
        res.energy -= cost["energy"]
        if hasattr(res, "fuel"):
            res.fuel = int(getattr(res, "fuel", 0)) - cost["fuel"]

        # Если строим «полевой стройкой» (разрешено инженером на клетке) — инженер расходуется.
        builder_fleet_id = gate.get("builder_fleet_id")
        if builder_fleet_id:
            try:
                bf = uuid.UUID(str(builder_fleet_id))
            except Exception:
                bf = None
            if bf:
                fleet = s.execute(select(Fleet).where(Fleet.id == bf, Fleet.owner_player_id == pid)).scalar_one_or_none()
                if fleet:
                    um = self._fleet_units_map(s, fleet)
                    if int(um.get("engineer", 0)) <= 0:
                        return {"ok": False, "error": "not_enough_engineers", "need_engineers": 1}
                    um["engineer"] = max(0, int(um.get("engineer", 0)) - 1)
                    self._write_fleet_units(s, fleet, um)

        b = Building(
            owner_player_id=pid,
            planet_id=planet.id,
            x=int(x),
            y=int(y),
            z=int(z),
            building_type=btype,
            level=1,
        )
        curpop = getattr(planet, "population", 800)
        mx = self._effective_max_population(s, planet)
        if hasattr(planet, "population") and int(curpop) > int(mx):
            planet.population = int(mx)

        s.add(b)
        s.flush()

        self._emit_event(
            s,
            tick=self.get_or_create_world_state(s).current_tick,
            type="building_placed",
            message=f"Постройка: {btype} в ({x},{y},{z})",
            payload={"building_id": str(b.id), "building_type": btype, "pos": {"x": x, "y": y, "z": z}, "cost": cost},
            player_id=pid,
        )

        return {
            "ok": True,
            "building": {"id": str(b.id), "building_type": btype, "level": int(b.level), "pos": {"x": x, "y": y, "z": z}},
            "cost": cost,
            "builder_fleet_id": gate.get("builder_fleet_id"),
        }

    def _building_effects_summary_ru(self, build_def: dict | None) -> str:
        if not isinstance(build_def, dict):
            return "—"
        eff = build_def.get("effects") if isinstance(build_def.get("effects"), dict) else {}
        prod = eff.get("production_per_tick_add") if isinstance(eff.get("production_per_tick_add"), dict) else {}
        parts: list[str] = []
        for k, ru in (("metal", "металл"), ("crystal", "кристаллы"), ("energy", "энергия"), ("fuel", "топливо")):
            if isinstance(prod.get(k), (int, float)) and float(prod[k]) != 0:
                v = int(prod[k])
                sign = "+" if v > 0 else ""
                parts.append(f"{sign}{v} {ru}/тик")
        if isinstance(eff.get("max_population_add"), (int, float)) and float(eff["max_population_add"]) != 0:
            v = int(eff["max_population_add"])
            sign = "+" if v > 0 else ""
            parts.append(f"{sign}{v} насел.")
        return ", ".join(parts) if parts else "—"

    def _building_ui_meta(self, logical_type: str, build_def: dict | None) -> dict:
        name = None
        if isinstance(build_def, dict) and isinstance(build_def.get("name"), str) and build_def.get("name").strip():
            name = str(build_def["name"]).strip()
        allowed = None
        if isinstance(build_def, dict) and isinstance(build_def.get("build_on_terrain"), list):
            allowed = [str(x) for x in build_def.get("build_on_terrain") if isinstance(x, str)]
        return {
            "type": str(logical_type),
            "name": name,
            "allowed_terrains": allowed,
            "effects_ru": self._building_effects_summary_ru(build_def),
        }

    def check_building_placement(
        self,
        s: Session,
        *,
        player_id: str,
        x: int,
        y: int,
        z: int,
        building_type: str,
        fleet_id: str | None = None,
    ) -> dict:
        """Проверка возможности постройки без изменения БД/списания ресурсов."""
        pid = uuid.UUID(player_id)
        btype = (building_type or "").strip().lower()
        if not btype:
            return {"ok": False, "error": "invalid_building_type"}

        build_def: dict | None = None
        if self._balance:
            aliases = self._balance.pack.aliases.get("building_aliases", {}) if self._balance.pack else {}
            allowed = set(aliases.keys()) if isinstance(aliases, dict) else set()
            if btype not in allowed:
                return {"ok": False, "error": "invalid_building_type"}
            try:
                build_def = self._balance.get_building(btype)
            except Exception:
                return {"ok": False, "error": "unknown_building"}
        elif btype not in (
            "mine",
            "reactor",
            "crystal_farm",
            "fuel_depot",
            "habitat",
            "research_lab",
            "drydock_mini",
            "solar_array",
            "cargo_yard",
            "sensor_mast",
        ):
            return {"ok": False, "error": "invalid_building_type"}

        meta = self._building_ui_meta(btype, build_def)

        req_techs = self._building_required_techs(btype)
        if req_techs:
            done = set(self._get_player_done_techs(s, player_id=pid))
            missing = [tid for tid in req_techs if tid not in done]
            if missing:
                return {"ok": False, "error": "tech_required", "required_techs": req_techs, "missing_techs": missing, "meta": meta}

        # Основание (ландшафт клетки)
        if build_def is not None:
            allowed_terrains = build_def.get("build_on_terrain") if isinstance(build_def, dict) else None
            if isinstance(allowed_terrains, list) and allowed_terrains:
                if "planet" in allowed_terrains:
                    if not self._cell_has_planet(s, x=int(x), y=int(y), z=int(z)):
                        return {"ok": False, "error": "planet_required", "meta": meta}
                    allowed_terrains = [t for t in allowed_terrains if t != "planet"]
                    if not allowed_terrains:
                        allowed_terrains = None
                cell = self.get_cell_terrain(x=x, y=y, z=z)
                terrain = cell.get("terrain")
                if isinstance(allowed_terrains, list) and allowed_terrains and terrain not in allowed_terrains:
                    return {
                        "ok": False,
                        "error": "wrong_foundation_terrain",
                        "terrain": terrain,
                        "expected": allowed_terrains,
                        "meta": meta,
                    }
        else:
            # fallback (для режима без balance)
            if btype == "mine":
                cell = self.get_cell_terrain(x=x, y=y, z=z)
                if cell.get("terrain") != "asteroids":
                    return {
                        "ok": False,
                        "error": "wrong_foundation_terrain",
                        "terrain": cell.get("terrain"),
                        "expected": ["asteroids"],
                        "meta": meta,
                    }
            if btype in ("habitat", "research_lab"):
                cell = self.get_cell_terrain(x=x, y=y, z=z)
                if btype == "habitat":
                    expected = ["ruins", "nebula"]
                    if cell.get("terrain") == "empty":
                        return {
                            "ok": False,
                            "error": "wrong_foundation_terrain",
                            "terrain": cell.get("terrain"),
                            "expected": expected,
                            "meta": meta,
                        }
                if btype == "research_lab":
                    expected = ["ruins", "nebula", "anomaly"]
                    if cell.get("terrain") == "empty":
                        return {
                            "ok": False,
                            "error": "wrong_foundation_terrain",
                            "terrain": cell.get("terrain"),
                            "expected": expected,
                            "meta": meta,
                        }

        # Геометрия/зоны/контроль/инженеры
        gate = self._can_build_at(s, owner_id=pid, x=x, y=y, z=z, fleet_id=fleet_id)
        if not gate.get("ok"):
            return {**gate, "meta": meta}

        return {"ok": True, "builder_fleet_id": gate.get("builder_fleet_id"), "meta": meta}

    def dismantle_building(
        self, s: Session, *, player_id: str, building_id: str
    ) -> dict:
        pid = uuid.UUID(player_id)
        try:
            bid = uuid.UUID(building_id)
        except Exception:
            return {"ok": False, "error": "invalid_building_id"}
        row = (
            s.execute(select(Building).where(Building.id == bid, Building.owner_player_id == pid)).scalars().first()
        )
        if not row:
            return {"ok": False, "error": "building_not_found"}
        ws = self.get_or_create_world_state(s)

        refund = {"metal": 0, "crystal": 0, "energy": 0, "fuel": 0}
        if self._balance:
            try:
                bd = self._balance.get_building(row.building_type)
                bc = bd.get("build") if isinstance(bd, dict) else {}
                cst = bc.get("cost") if isinstance(bc.get("cost"), dict) else {}
                for k in ("metal", "crystal", "energy", "fuel"):
                    if isinstance(cst.get(k), (int, float)):
                        refund[k] = int(int(cst[k]) * 0.5)
            except Exception:
                pass

        home = s.execute(select(Planet).where(Planet.owner_player_id == pid)).scalar_one_or_none()
        res = (
            s.execute(select(Resource).where(Resource.planet_id == home.id)).scalar_one_or_none()
            if home
            else None
        )
        if res:
            res.metal += refund["metal"]
            res.crystal += refund["crystal"]
            res.energy += refund["energy"]
            if hasattr(res, "fuel"):
                res.fuel = int(getattr(res, "fuel", 0)) + refund["fuel"]

        bt = row.building_type
        pl_ref = row.planet_id
        s.delete(row)
        s.flush()
        if pl_ref:
            planet = s.get(Planet, pl_ref)
            if planet:
                mx = self._effective_max_population(s, planet)
                if hasattr(planet, "population") and planet.population > mx:
                    planet.population = mx

        self._emit_event(
            s,
            tick=ws.current_tick,
            type="building_dismantled",
            message=f"Снесено: {bt}",
            payload={"building_id": str(bid), "refund": refund},
            player_id=pid,
        )
        return {"ok": True, "refund": refund}

    def _fleet_active_order_payload(self, s: Session, ws: WorldState, fleet: Fleet) -> dict | None:
        ao = self._active_order_for_fleet(s, fleet_id=fleet.id)
        if not ao:
            return None
        remaining = max(0, int(ao.finish_tick - ws.current_tick))
        units_map = self._fleet_units_map(s, fleet)
        d = abs(ao.target_x - ao.from_x) + abs(ao.target_y - ao.from_y)
        travel_ticks = self._fleet_travel_ticks_for_distance(distance=d, units=units_map)
        out: dict = {
            "id": str(ao.id),
            "status": ao.status,
            "from_x": ao.from_x,
            "from_y": ao.from_y,
            "from_z": ao.from_z,
            "target_x": ao.target_x,
            "target_y": ao.target_y,
            "target_z": ao.target_z,
            "finish_tick": ao.finish_tick,
            "finish_sol": int(ao.finish_tick),
            "remaining_ticks": remaining,
            "remaining_sols": int(remaining),
            "distance": d,
            "travel_ticks": travel_ticks,
            "travel_sols": int(travel_ticks),
            "force_attack": bool(getattr(ao, "force_attack", False)),
        }
        if ao.status == "pending_combat" and getattr(ao, "combat_prompt_expires_at", None):
            exp = ao.combat_prompt_expires_at
            out["pending_combat"] = True
            out["combat_prompt_expires_at"] = exp.isoformat() if hasattr(exp, "isoformat") else str(exp)
            out["remaining_ticks"] = 0
        return out

    def adjust_fleet_composition(
        self, s: Session, *, player_id: str, fleet_id: str, deltas: dict | None
    ) -> dict:
        if not isinstance(deltas, dict) or not deltas:
            return {"ok": False, "error": "invalid_deltas"}
        pid = uuid.UUID(player_id)
        try:
            fid = uuid.UUID(fleet_id)
        except Exception:
            return {"ok": False, "error": "invalid_fleet_id"}
        allowed = self._logical_unit_keys()
        fleet = s.execute(select(Fleet).where(Fleet.id == fid, Fleet.owner_player_id == pid)).scalars().first()
        if not fleet:
            return {"ok": False, "error": "fleet_not_found"}
        if self._active_order_for_fleet(s, fleet_id=fleet.id):
            return {"ok": False, "error": "active_order_exists"}

        cur = self._fleet_units_map(s, fleet)
        newd: dict[str, int] = {str(k): int(v) for k, v in cur.items() if int(v) > 0}
        for raw_k, raw_v in deltas.items():
            k = str(raw_k or "").strip().lower()
            if not k:
                continue
            if k not in allowed:
                return {"ok": False, "error": "invalid_unit_type", "unit_type": k}
            try:
                dv = int(raw_v)
            except Exception:
                return {"ok": False, "error": "invalid_delta"}
            newd[k] = newd.get(k, 0) + dv

        for k, v in list(newd.items()):
            if v < 0:
                return {"ok": False, "error": "negative_qty", "unit_type": k}
            if v == 0:
                del newd[k]

        total_new = sum(newd.values())
        if total_new <= 0:
            s.delete(fleet)
            s.flush()
            ws = self.get_or_create_world_state(s)
            self._emit_event(
                s,
                tick=ws.current_tick,
                type="fleet_disbanded",
                message="Флот расформирован (0 кораблей)",
                payload={"fleet_id": str(fid)},
                player_id=pid,
            )
            return {"ok": True, "composition": {}, "deleted": True}

        pay_res = self._try_apply_home_resource_net_for_fleet_change(s, pid=pid, cur=cur, newd=newd)
        if not pay_res.get("ok"):
            return pay_res
        net = pay_res.get("net", {})

        self._write_fleet_units(s, fleet, newd)
        s.flush()
        ws = self.get_or_create_world_state(s)
        self._emit_event(
            s,
            tick=ws.current_tick,
            type="fleet_composition_changed",
            message="Изменён состав флота",
            payload={"fleet_id": str(fleet.id), "composition": dict(newd)},
            player_id=pid,
        )
        return {"ok": True, "composition": dict(newd), "cost_net": net}

    def rename_fleet(self, s: Session, *, player_id: str, fleet_id: str, name: str | None) -> dict:
        pid = uuid.UUID(player_id)
        try:
            fid = uuid.UUID(fleet_id)
        except Exception:
            return {"ok": False, "error": "invalid_fleet_id"}
        nm_raw = name if isinstance(name, str) else ""
        nm = nm_raw.strip()
        if not nm:
            return {"ok": False, "error": "invalid_name"}
        if len(nm) > 64:
            return {"ok": False, "error": "name_too_long"}
        fleet = s.execute(select(Fleet).where(Fleet.id == fid, Fleet.owner_player_id == pid)).scalars().first()
        if not fleet:
            return {"ok": False, "error": "fleet_not_found"}
        fleet.name = nm[:64]
        s.flush()
        ws = self.get_or_create_world_state(s)
        self._emit_event(
            s,
            tick=ws.current_tick,
            type="fleet_renamed",
            message=f"Переименован флот: {fleet.name}",
            payload={"fleet_id": str(fid), "name": fleet.name},
            player_id=pid,
        )
        return {"ok": True, "name": fleet.name}

    _SAVE_FLEET_UNSET = object()

    def _fleet_composition_pay_refund_net(
        self, *, cur: dict[str, int], newd: dict[str, int]
    ) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
        pay = {"metal": 0, "crystal": 0, "energy": 0, "fuel": 0}
        refund = {"metal": 0, "crystal": 0, "energy": 0, "fuel": 0}
        for k in set(cur.keys()) | set(newd.keys()):
            old_n = int(cur.get(k, 0))
            new_n = int(newd.get(k, 0))
            diff = new_n - old_n
            if diff == 0:
                continue
            cst = self._unit_build_cost_parts(k)
            if diff > 0:
                for rk in pay:
                    pay[rk] += int(cst.get(rk, 0)) * diff
            else:
                for rk in refund:
                    refund[rk] += int(int(cst.get(rk, 0)) * abs(diff) * 0.5)
        net = {rk: pay[rk] - refund[rk] for rk in pay}
        return pay, refund, net

    def _try_apply_home_resource_net_for_fleet_change(
        self, s: Session, *, pid: uuid.UUID, cur: dict[str, int], newd: dict[str, int]
    ) -> dict:
        """Списание/возврат на склад домашней планеты при смене состава. Возвращает {ok, net?} или {ok: False, error, ...}."""
        home = s.execute(select(Planet).where(Planet.owner_player_id == pid)).scalar_one_or_none()
        if not home:
            return {"ok": False, "error": "no_home_planet"}
        res = s.execute(select(Resource).where(Resource.planet_id == home.id)).scalar_one_or_none()
        if not res:
            return {"ok": False, "error": "no_resources"}
        _pay, _refund, net = self._fleet_composition_pay_refund_net(cur=cur, newd=newd)
        if (
            int(res.metal) < net["metal"]
            or int(res.crystal) < net["crystal"]
            or int(res.energy) < net["energy"]
            or int(getattr(res, "fuel", 0)) < net["fuel"]
        ):
            return {
                "ok": False,
                "error": "not_enough_resources",
                "need": net,
                "have": {
                    "metal": int(res.metal),
                    "crystal": int(res.crystal),
                    "energy": int(res.energy),
                    "fuel": int(getattr(res, "fuel", 0)),
                },
            }
        res.metal = int(res.metal) - net["metal"]
        res.crystal = int(res.crystal) - net["crystal"]
        res.energy = int(res.energy) - net["energy"]
        res.fuel = int(res.fuel) - net["fuel"]
        return {"ok": True, "net": net}

    def save_fleet(
        self,
        s: Session,
        *,
        player_id: str,
        fleet_id: str,
        name=_SAVE_FLEET_UNSET,
        composition=_SAVE_FLEET_UNSET,
    ) -> dict:
        """Атомарно: опционально имя + абсолютный состав (один запрос, одно списание ресурсов)."""
        if name is self._SAVE_FLEET_UNSET and composition is self._SAVE_FLEET_UNSET:
            return {"ok": False, "error": "nothing_to_save"}
        pid = uuid.UUID(player_id)
        try:
            fid = uuid.UUID(fleet_id)
        except Exception:
            return {"ok": False, "error": "invalid_fleet_id"}
        fleet = s.execute(select(Fleet).where(Fleet.id == fid, Fleet.owner_player_id == pid)).scalars().first()
        if not fleet:
            return {"ok": False, "error": "fleet_not_found"}
        if self._active_order_for_fleet(s, fleet_id=fleet.id):
            return {"ok": False, "error": "active_order_exists"}

        out: dict = {"ok": True, "fleet_id": str(fid)}

        if name is not self._SAVE_FLEET_UNSET:
            if not isinstance(name, str):
                return {"ok": False, "error": "invalid_name"}
            nm = name.strip()
            if not nm:
                return {"ok": False, "error": "invalid_name"}
            if len(nm) > 64:
                return {"ok": False, "error": "name_too_long"}
            fleet.name = nm[:64]
            out["name"] = fleet.name

        if composition is not self._SAVE_FLEET_UNSET:
            if not isinstance(composition, dict):
                return {"ok": False, "error": "invalid_composition"}
            allowed = self._logical_unit_keys()
            newd: dict[str, int] = {}
            for raw_k, raw_v in composition.items():
                k = str(raw_k or "").strip().lower()
                if not k:
                    continue
                if k not in allowed:
                    return {"ok": False, "error": "invalid_unit_type", "unit_type": k}
                try:
                    q = int(raw_v)
                except Exception:
                    return {"ok": False, "error": "invalid_qty"}
                if q < 0:
                    return {"ok": False, "error": "negative_qty"}
                if q > 0:
                    newd[k] = int(q)
            total_new = sum(newd.values())
            if total_new < 1:
                return {"ok": False, "error": "fleet_empty_use_disband"}
            if total_new > 50:
                return {"ok": False, "error": "fleet_too_large"}

            cur = self._fleet_units_map(s, fleet)
            pay_res = self._try_apply_home_resource_net_for_fleet_change(s, pid=pid, cur=cur, newd=newd)
            if not pay_res.get("ok"):
                return pay_res
            self._write_fleet_units(s, fleet, newd)
            out["composition"] = dict(newd)
            out["cost_net"] = pay_res.get("net", {})

        s.flush()
        ws = self.get_or_create_world_state(s)
        if composition is not self._SAVE_FLEET_UNSET:
            self._emit_event(
                s,
                tick=ws.current_tick,
                type="fleet_composition_changed",
                message="Изменён состав флота",
                payload={"fleet_id": str(fleet.id), "composition": out.get("composition", {})},
                player_id=pid,
            )
        if name is not self._SAVE_FLEET_UNSET:
            self._emit_event(
                s,
                tick=ws.current_tick,
                type="fleet_renamed",
                message=f"Переименован флот: {fleet.name}",
                payload={"fleet_id": str(fid), "name": fleet.name},
                player_id=pid,
            )
        return out

    def disband_fleet(self, s: Session, *, player_id: str, fleet_id: str) -> dict:
        pid = uuid.UUID(player_id)
        try:
            fid = uuid.UUID(fleet_id)
        except Exception:
            return {"ok": False, "error": "invalid_fleet_id"}
        fleet = s.execute(select(Fleet).where(Fleet.id == fid, Fleet.owner_player_id == pid)).scalars().first()
        if not fleet:
            return {"ok": False, "error": "fleet_not_found"}
        if self._active_order_for_fleet(s, fleet_id=fleet.id):
            return {"ok": False, "error": "active_order_exists"}

        cur = self._fleet_units_map(s, fleet)
        home = s.execute(select(Planet).where(Planet.owner_player_id == pid)).scalar_one_or_none()
        if not home:
            return {"ok": False, "error": "no_home_planet"}
        res = s.execute(select(Resource).where(Resource.planet_id == home.id)).scalar_one_or_none()
        if not res:
            return {"ok": False, "error": "no_resources"}

        refund = {"metal": 0, "crystal": 0, "energy": 0, "fuel": 0}
        for ut, q in cur.items():
            if int(q) <= 0:
                continue
            cst = self._unit_build_cost_parts(ut)
            for rk in refund:
                refund[rk] += int(int(cst.get(rk, 0)) * int(q) * 0.5)
        for rk in refund:
            setattr(res, rk, int(getattr(res, rk)) + int(refund[rk]))

        s.delete(fleet)
        s.flush()
        ws = self.get_or_create_world_state(s)
        self._emit_event(
            s,
            tick=ws.current_tick,
            type="fleet_disbanded",
            message="Флот расформирован",
            payload={"fleet_id": str(fid), "refund": refund},
            player_id=pid,
        )
        return {"ok": True, "deleted": True, "refund": refund}

    def merge_fleets(self, s: Session, *, player_id: str, target_fleet_id: str, source_fleet_id: str) -> dict:
        pid = uuid.UUID(player_id)
        try:
            tid = uuid.UUID(target_fleet_id)
            sid = uuid.UUID(source_fleet_id)
        except Exception:
            return {"ok": False, "error": "invalid_fleet_id"}
        if tid == sid:
            return {"ok": False, "error": "same_fleet"}
        target = s.execute(select(Fleet).where(Fleet.id == tid, Fleet.owner_player_id == pid)).scalars().first()
        source = s.execute(select(Fleet).where(Fleet.id == sid, Fleet.owner_player_id == pid)).scalars().first()
        if not target or not source:
            return {"ok": False, "error": "fleet_not_found"}
        if self._active_order_for_fleet(s, fleet_id=target.id) or self._active_order_for_fleet(
            s, fleet_id=source.id
        ):
            return {"ok": False, "error": "active_order_exists"}

        cur_t = self._fleet_units_map(s, target)
        cur_s = self._fleet_units_map(s, source)
        newd: dict[str, int] = {}
        for k in set(cur_t.keys()) | set(cur_s.keys()):
            n = int(cur_t.get(k, 0)) + int(cur_s.get(k, 0))
            if n > 0:
                newd[k] = n
        if sum(newd.values()) < 1:
            return {"ok": False, "error": "fleet_empty"}
        if sum(newd.values()) > 50:
            return {"ok": False, "error": "fleet_too_large"}

        s.delete(source)
        s.flush()
        self._write_fleet_units(s, target, newd)
        s.flush()
        ws = self.get_or_create_world_state(s)
        self._emit_event(
            s,
            tick=ws.current_tick,
            type="fleet_merged",
            message="Флоты объединены",
            payload={"target_fleet_id": str(tid), "source_fleet_id": str(sid), "composition": dict(newd)},
            player_id=pid,
        )
        return {"ok": True, "fleet_id": str(tid), "composition": dict(newd), "merged_from": str(sid)}

    def split_fleet(self, s: Session, *, player_id: str, fleet_id: str, take: dict | None) -> dict:
        pid = uuid.UUID(player_id)
        try:
            fid = uuid.UUID(fleet_id)
        except Exception:
            return {"ok": False, "error": "invalid_fleet_id"}
        if not isinstance(take, dict) or not take:
            return {"ok": False, "error": "invalid_take"}
        fleet = s.execute(select(Fleet).where(Fleet.id == fid, Fleet.owner_player_id == pid)).scalars().first()
        if not fleet:
            return {"ok": False, "error": "fleet_not_found"}
        if self._active_order_for_fleet(s, fleet_id=fleet.id):
            return {"ok": False, "error": "active_order_exists"}

        allowed = self._logical_unit_keys()
        take_map: dict[str, int] = {}
        for raw_k, raw_v in take.items():
            k = str(raw_k or "").strip().lower()
            if not k or k not in allowed:
                return {"ok": False, "error": "invalid_unit_type", "unit_type": k}
            try:
                q = int(raw_v)
            except Exception:
                return {"ok": False, "error": "invalid_qty"}
            if q < 0:
                return {"ok": False, "error": "negative_qty"}
            if q > 0:
                take_map[k] = int(q)

        if sum(take_map.values()) < 1:
            return {"ok": False, "error": "take_empty"}

        cur = self._fleet_units_map(s, fleet)
        for k, q in take_map.items():
            if int(cur.get(k, 0)) < int(q):
                return {"ok": False, "error": "not_enough_ships", "unit_type": k}

        remainder: dict[str, int] = {}
        for k in set(cur.keys()) | set(take_map.keys()):
            left = int(cur.get(k, 0)) - int(take_map.get(k, 0))
            if left > 0:
                remainder[k] = left
        if sum(remainder.values()) < 1:
            return {"ok": False, "error": "cannot_split_entire_fleet"}

        spawn = self._pick_fleet_spawn_xy(
            s, owner_id=pid, px=int(fleet.pos_x), py=int(fleet.pos_y), pz=int(fleet.pos_z)
        )
        if not spawn:
            return {"ok": False, "error": "no_free_spawn_cell"}
        tx, ty = spawn
        nm = self._next_fleet_default_name(s, owner_id=pid)
        dominant = max(take_map.items(), key=lambda kv: (kv[1], kv[0]))[0]
        new_fleet = Fleet(
            owner_player_id=pid,
            unit_type=str(dominant),
            qty=0,
            pos_x=int(tx),
            pos_y=int(ty),
            pos_z=int(fleet.pos_z),
            name=nm[:64],
        )
        s.add(new_fleet)
        s.flush()
        self._write_fleet_units(s, new_fleet, take_map)
        self._write_fleet_units(s, fleet, remainder)
        s.flush()
        ws = self.get_or_create_world_state(s)
        self._emit_event(
            s,
            tick=ws.current_tick,
            type="fleet_split",
            message="Флот разделён",
            payload={
                "original_fleet_id": str(fid),
                "new_fleet_id": str(new_fleet.id),
                "take": dict(take_map),
                "remainder": dict(remainder),
            },
            player_id=pid,
        )
        return {
            "ok": True,
            "original_fleet_id": str(fid),
            "new_fleet_id": str(new_fleet.id),
            "take": dict(take_map),
            "remainder": dict(remainder),
        }

    def _ensure_bandit_player(self, s: Session) -> Player:
        p = s.get(Player, BANDIT_PLAYER_ID)
        if p:
            if str(p.display_name).strip() in ("ADM", "adm"):
                p.display_name = "Корсары (ИИ)"
                s.flush()
            return p
        h = hashlib.sha256(f"npc_bandit::{self._world_seed}".encode()).hexdigest()
        p = Player(id=BANDIT_PLAYER_ID, display_name="Корсары (ИИ)", access_code_hash=h)
        s.add(p)
        s.flush()
        return p

    def _cell_blocked_for_fleet(self, s: Session, x: int, y: int, z: int) -> bool:
        if (
            s.execute(select(Building.id).where(Building.x == x, Building.y == y, Building.z == z))
            .scalars()
            .first()
        ):
            return True
        if (
            s.execute(select(Outpost.id).where(Outpost.x == x, Outpost.y == y, Outpost.z == z, Outpost.status == "active"))
            .scalars()
            .first()
        ):
            return True
        if (
            s.execute(select(Fleet.id).where(Fleet.pos_x == x, Fleet.pos_y == y, Fleet.pos_z == z))
            .scalars()
            .first()
        ):
            return True
        return False

    def _cell_in_player_build_zone(self, s: Session, *, player_id: uuid.UUID, x: int, y: int) -> bool:
        """Радиус 3 от любой планеты владельца (как зона стройки)."""
        for p in s.execute(select(Planet).where(Planet.owner_player_id == player_id)).scalars().all():
            if abs(int(p.pos_x) - int(x)) + abs(int(p.pos_y) - int(y)) <= 3:
                return True
        return False

    def _collect_influence_sources(self, s: Session) -> list[dict]:
        out: list[dict] = []
        # Имперский бонус: суммарное население слегка усиливает все давления по империи.
        # 100k населения -> +0.05 ко всем давлениям (множитель 1.05).
        pops = (
            s.execute(select(Planet.owner_player_id, func.sum(getattr(Planet, "population", 0))).group_by(Planet.owner_player_id))
            .all()
        )
        pop_by_owner: dict[uuid.UUID, int] = {pid: int(sp or 0) for pid, sp in pops}
        mult_by_owner: dict[uuid.UUID, float] = {}
        for pid, pop in pop_by_owner.items():
            mult_by_owner[pid] = 1.0 + (max(0, int(pop)) / 100000.0) * 0.05
        for p in s.execute(select(Planet)).scalars().all():
            mul = float(mult_by_owner.get(p.owner_player_id, 1.0))
            out.append(
                {
                    "owner": p.owner_player_id,
                    "x": int(p.pos_x),
                    "y": int(p.pos_y),
                    "z": 0,
                    "w": float(INFLUENCE_WEIGHT_COLONY) * mul,
                    "r": INFLUENCE_RADIUS_COLONY,
                }
            )
        for op in s.execute(select(Outpost).where(Outpost.z == 0, Outpost.status == "active")).scalars().all():
            st = self._outpost_stats(s, op)
            mul = float(mult_by_owner.get(op.owner_player_id, 1.0))
            out.append(
                {
                    "owner": op.owner_player_id,
                    "x": int(op.x),
                    "y": int(op.y),
                    "z": int(op.z),
                    "w": float(st["territory"]["influence_strength"]) * mul,
                    "r": int(st["territory"]["influence_radius"]),
                }
            )
        return out

    def _collect_visibility_sources_for_player(self, s: Session, *, player_id: uuid.UUID, z: int) -> list[tuple[int, int, int]]:
        vis_sources: list[tuple[int, int, int]] = []
        my_planets = s.execute(select(Planet).where(Planet.owner_player_id == player_id)).scalars().all()
        for p in my_planets:
            vis_sources.append((int(p.pos_x), int(p.pos_y), 5))
        my_fleets = s.execute(select(Fleet).where(Fleet.owner_player_id == player_id, Fleet.pos_z == z)).scalars().all()
        for f in my_fleets:
            um = self._fleet_units_map(s, f)
            r = 2 if int(um.get("scout", 0)) > 0 or f.unit_type == "scout" else 1
            vis_sources.append((int(f.pos_x), int(f.pos_y), r))
        my_outposts = s.execute(select(Outpost).where(Outpost.owner_player_id == player_id, Outpost.z == z, Outpost.status == "active")).scalars().all()
        for op in my_outposts:
            st = self._outpost_stats(s, op)
            vis_sources.append((int(op.x), int(op.y), int(st["vision"]["radius"])))
        return vis_sources

    @staticmethod
    def _influence_decay_contrib(weight: float, manhattan_d: int, radius: int) -> float:
        if radius <= 0 or manhattan_d > radius:
            return 0.0
        guaranteed = min(INFLUENCE_BASE_RADIUS, radius)
        if manhattan_d <= guaranteed:
            return float(weight)
        return float(weight) * (0.5 ** int(manhattan_d - guaranteed))

    def _influence_scores_at(self, sources: list[dict], x: int, y: int, z: int) -> dict[uuid.UUID, float]:
        acc: dict[uuid.UUID, float] = defaultdict(float)
        for src in sources:
            if int(src["z"]) != int(z):
                continue
            d = abs(int(src["x"]) - x) + abs(int(src["y"]) - y)
            c = self._influence_decay_contrib(float(src["w"]), d, int(src["r"]))
            if c > 0:
                acc[src["owner"]] += c
        return dict(acc)

    def _owned_engineer_fleet_at(
        self, s: Session, *, owner_id: uuid.UUID, x: int, y: int, z: int, fleet_id: str | None = None
    ) -> Fleet | None:
        q = select(Fleet).where(Fleet.owner_player_id == owner_id, Fleet.pos_x == x, Fleet.pos_y == y, Fleet.pos_z == z)
        if fleet_id:
            try:
                q = q.where(Fleet.id == uuid.UUID(fleet_id))
            except Exception:
                return None
        for fleet in s.execute(q).scalars().all():
            if int(self._fleet_units_map(s, fleet).get("engineer", 0)) > 0:
                return fleet
        return None

    def _cell_enemy_control_owner(self, s: Session, *, owner_id: uuid.UUID, x: int, y: int, z: int) -> uuid.UUID | None:
        rows = (
            s.execute(
                select(InfluenceCell)
                .where(InfluenceCell.x == x, InfluenceCell.y == y, InfluenceCell.z == z, InfluenceCell.control_value > 0)
                .order_by(InfluenceCell.control_value.desc())
            )
            .scalars()
            .all()
        )
        if not rows:
            return None
        top = rows[0]
        second = float(rows[1].control_value) if len(rows) > 1 else 0.0
        if float(top.control_value) <= INFLUENCE_CAPTURE_THRESHOLD:
            return None
        if float(top.control_value) - second <= 0.01:
            return None
        return None if top.player_id == owner_id else top.player_id

    @staticmethod
    def _influence_next_control_value(current_value: float, own_strength: float, others_strength: float) -> float:
        net = float(own_strength) - float(others_strength) - INFLUENCE_NATURAL_DECAY_PER_TICK
        return max(0.0, float(current_value) + net)

    def _apply_influence_control_tick(self, s: Session, *, tick: int, sources: list[dict]) -> None:
        claims = s.execute(select(InfluenceCell).where(InfluenceCell.control_value > 0)).scalars().all()
        by_cell_player: dict[tuple[int, int, int, uuid.UUID], InfluenceCell] = {
            (int(c.x), int(c.y), int(c.z), c.player_id): c for c in claims
        }
        players_by_cell: dict[tuple[int, int, int], set[uuid.UUID]] = defaultdict(set)
        for c in claims:
            players_by_cell[(int(c.x), int(c.y), int(c.z))].add(c.player_id)

        covered_cells: set[tuple[int, int, int]] = set(players_by_cell.keys())
        for src in sources:
            sx, sy, sz, rr = int(src["x"]), int(src["y"]), int(src["z"]), int(src["r"])
            for dy in range(-rr, rr + 1):
                max_dx = rr - abs(dy)
                for dx in range(-max_dx, max_dx + 1):
                    covered_cells.add((sx + dx, sy + dy, sz))

        for x, y, z in covered_cells:
            scores = self._influence_scores_at(sources, x, y, z)
            score_players = set(scores.keys())
            existed_players = players_by_cell.get((x, y, z), set())
            all_players = score_players | existed_players
            if not all_players:
                continue
            total = float(sum(scores.values()))
            for pid in all_players:
                own = float(scores.get(pid, 0.0))
                others = max(0.0, total - own)
                key = (x, y, z, pid)
                cur = by_cell_player.get(key)
                old = float(cur.control_value) if cur else 0.0
                newv = self._influence_next_control_value(old, own, others)
                if newv <= 1e-9:
                    if cur:
                        s.delete(cur)
                        by_cell_player.pop(key, None)
                    continue
                if cur:
                    cur.control_value = float(newv)
                    cur.updated_tick = int(tick)
                else:
                    cur = InfluenceCell(
                        player_id=pid,
                        x=int(x),
                        y=int(y),
                        z=int(z),
                        control_value=float(newv),
                        updated_tick=int(tick),
                    )
                    s.add(cur)
                    by_cell_player[key] = cur

    def _influence_cell_payload(
        self,
        scores: dict[uuid.UUID, float],
        viewer_id: uuid.UUID,
        owners_by_id: dict[str, str],
        control_scores: dict[uuid.UUID, float] | None = None,
    ) -> dict:
        entries = [(uid, float(v)) for uid, v in scores.items() if float(v) > 1e-12]
        entries.sort(key=lambda kv: kv[1], reverse=True)
        total = float(sum(sc for _, sc in entries))

        control_entries: list[tuple[uuid.UUID, float]] = []
        if control_scores:
            control_entries = [(uid, float(v)) for uid, v in control_scores.items() if float(v) > 1e-12]
            control_entries.sort(key=lambda kv: kv[1], reverse=True)

        control_owner: str | None = None
        control_owner_name: str | None = None
        if control_entries and control_entries[0][1] > INFLUENCE_CAPTURE_THRESHOLD:
            if len(control_entries) == 1 or control_entries[0][1] - control_entries[1][1] > 0.01:
                control_owner = str(control_entries[0][0])
                control_owner_name = owners_by_id.get(control_owner)

        dominant: str | None = None
        dominant_name: str | None = None
        if control_owner:
            dominant = control_owner
            dominant_name = control_owner_name
        elif entries and entries[0][1] >= INFLUENCE_MIN_DOMINANT_SCORE:
            dominant = str(entries[0][0])
            dominant_name = owners_by_id.get(dominant)

        contested = False
        if len(entries) >= 2 and entries[0][1] > 1e-9:
            contested = entries[1][1] / entries[0][1] >= INFLUENCE_CONTEST_RATIO

        top: list[dict] = []
        for uid, sc in entries[:4]:
            sid = str(uid)
            top.append(
                {
                    "player_id": sid,
                    "score": round(sc, 2),
                    "share": round(sc / total, 4) if total > 1e-9 else 0.0,
                    "name": owners_by_id.get(sid),
                }
            )

        your = float(scores.get(viewer_id, 0.0))
        your_share = round(your / total, 4) if total > 1e-9 else None

        dominant_rel = None
        if dominant:
            dominant_rel = "self" if viewer_id and dominant == str(viewer_id) else "other"

        return {
            "dominant": dominant,
            "dominant_name": dominant_name,
            "dominant_rel": dominant_rel,
            "contested": contested,
            "your_share": your_share,
            "top": top,
            "total_score": round(total, 2),
            "control": {
                "owner": control_owner,
                "owner_name": control_owner_name,
                "your_value": round(float(control_scores.get(viewer_id, 0.0)), 3) if control_scores else 0.0,
                "top_value": round(control_entries[0][1], 3) if control_entries else 0.0,
                "capture_threshold": INFLUENCE_CAPTURE_THRESHOLD,
            },
        }

    @staticmethod
    def _planet_influence_production_multiplier(scores: dict[uuid.UUID, float], owner_id: uuid.UUID) -> float:
        total = float(sum(scores.values()))
        if total <= 1e-12:
            return 1.0
        share = float(scores.get(owner_id, 0.0)) / total
        return max(0.88, min(1.12, 1.0 + (share - 0.5) * 0.24))

    def _spawn_mvp_bandit_patrol_near(self, s: Session, *, home_x: int, home_y: int) -> None:
        """Один вражеский патруль рядом с колонией — цель для боя в MVP."""
        npc = self._ensure_bandit_player(s)
        z = 0
        cand = [(6, 0), (7, 0), (5, 1), (6, 1), (8, 0), (4, 1), (6, -1), (7, -1), (5, -1), (8, 1), (4, -1), (9, 0)]
        for dx, dy in cand:
            tx, ty = home_x + dx, home_y + dy
            if self._cell_blocked_for_fleet(s, tx, ty, z):
                continue
            fleet = Fleet(
                owner_player_id=npc.id,
                unit_type="fighter",
                qty=0,
                pos_x=int(tx),
                pos_y=int(ty),
                pos_z=z,
                name="Засада",
            )
            s.add(fleet)
            s.flush()
            self._write_fleet_units(s, fleet, {"fighter": 2, "scout": 1})
            s.flush()
            return

    def _combat_tech_breakdown(self, s: Session, *, player_id: uuid.UUID) -> tuple[float, float, list[dict]]:
        """Множители урона/HP от завершённых исследований + список для отображения игроку."""
        dmg = 1.0
        hp = 1.0
        lines: list[dict] = []
        if not self._balance or not getattr(self._balance, "pack", None):
            return dmg, hp, lines
        for tid in self._get_player_done_techs(s, player_id=player_id):
            t = self._balance.pack.tech_by_id.get(tid)
            if not isinstance(t, dict):
                continue
            nm = str(t.get("name") or tid).strip() or tid
            eff = t.get("effects") if isinstance(t.get("effects"), dict) else {}
            has_cf = False
            if isinstance(eff.get("combat_damage_multiplier"), (int, float)):
                dmg *= float(eff["combat_damage_multiplier"])
                has_cf = True
            if isinstance(eff.get("combat_hp_multiplier"), (int, float)):
                hp *= float(eff["combat_hp_multiplier"])
                has_cf = True
            if has_cf:
                parts: list[str] = []
                if isinstance(eff.get("combat_damage_multiplier"), (int, float)):
                    parts.append(f"урон ×{float(eff['combat_damage_multiplier']):g}")
                if isinstance(eff.get("combat_hp_multiplier"), (int, float)):
                    parts.append(f"HP ×{float(eff['combat_hp_multiplier']):g}")
                lines.append({"tech_id": tid, "name": nm, "summary": "; ".join(parts)})
        return dmg, hp, lines

    def _combat_stat_multipliers_for_player(self, s: Session, *, player_id: uuid.UUID) -> tuple[float, float]:
        d, h, _ = self._combat_tech_breakdown(s, player_id=player_id)
        return d, h

    def _fleet_combat_score(self, s: Session, *, fleet: Fleet, player_id: uuid.UUID) -> int:
        um = self._fleet_units_map(s, fleet)
        dmg_m, hp_m = self._combat_stat_multipliers_for_player(s, player_id=player_id)
        score = 0
        for ut, q in um.items():
            u: dict = {}
            if self._balance:
                try:
                    u = self._balance.get_unit(ut)
                except Exception:
                    u = {}
            hp = float(u.get("hp", 10)) * hp_m
            dmg = float(u.get("damage", 1)) * dmg_m
            score += int((hp + dmg * 3.0) * max(0, int(q)))
        return max(1, int(score))

    def _fleet_composition_snapshot(self, s: Session, fleet: Fleet) -> dict[str, int]:
        return {str(k): int(v) for k, v in self._fleet_units_map(s, fleet).items() if int(v) > 0}

    def _composition_casualties(self, before: dict[str, int], after: dict[str, int]) -> dict:
        lost: dict[str, int] = {}
        for k in set(before) | set(after):
            b = int(before.get(k, 0))
            a = int(after.get(k, 0))
            if b > a:
                lost[k] = b - a
        return {
            "before": dict(before),
            "after": dict(after),
            "lost_by_type": lost,
            "lost_total": sum(lost.values()),
        }

    def _apply_fleet_post_combat_losses(self, s: Session, fleet: Fleet, *, fraction: float = 0.08) -> None:
        um = dict(self._fleet_units_map(s, fleet))
        tot = sum(int(v) for v in um.values())
        if tot <= 1:
            return
        remove = min(tot - 1, max(1, int(tot * fraction)))
        while remove > 0 and sum(um.values()) > 0:
            ut = max(um.items(), key=lambda kv: (kv[1], kv[0]))[0]
            if int(um.get(ut, 0)) <= 0:
                break
            um[ut] = int(um[ut]) - 1
            remove -= 1
        self._write_fleet_units(s, fleet, um)

    def _combat_effective_scores(
        self,
        s: Session,
        *,
        attacker: Fleet,
        defender: Fleet,
        attacker_from_x: int,
        attacker_from_y: int,
        battle_cell_x: int,
        battle_cell_y: int,
    ) -> tuple[float, float, dict]:
        """Базовые очки боя с учётом территории (снабжение атакующего / оборона у защитника)."""
        ap, dp = attacker.owner_player_id, defender.owner_player_id
        atk_raw = float(self._fleet_combat_score(s, fleet=attacker, player_id=ap))
        def_raw = float(self._fleet_combat_score(s, fleet=defender, player_id=dp))
        atk_sup = self._cell_in_player_build_zone(s, player_id=ap, x=attacker_from_x, y=attacker_from_y)
        def_home = self._cell_in_player_build_zone(s, player_id=dp, x=battle_cell_x, y=battle_cell_y)
        atk_mul = 1.05 if atk_sup else 1.0
        def_mul = 1.08 if def_home else 1.0
        eff_atk = atk_raw * atk_mul
        eff_def = def_raw * def_mul
        _, _, atk_rd = self._combat_tech_breakdown(s, player_id=ap)
        _, _, def_rd = self._combat_tech_breakdown(s, player_id=dp)
        meta = {
            "attacker_base": int(atk_raw),
            "defender_base": int(def_raw),
            "attacker_supply_zone": atk_sup,
            "defender_home_zone": def_home,
            "attacker_effective_before_roll": round(eff_atk, 2),
            "defender_effective_before_roll": round(eff_def, 2),
            "attacker_effective": round(eff_atk, 1),
            "defender_effective": round(eff_def, 1),
            "supply_zone_bonus": {"attacker": 1.05 if atk_sup else 1.0, "defender": 1.08 if def_home else 1.0},
            "attacker_research": atk_rd,
            "defender_research": def_rd,
            "note": "На итоговые очки каждого тика применяется случайный множитель Uniform(0.94…1.08). Победа — если очки после броска ≥ у соперника.",
        }
        return eff_atk, eff_def, meta

    def estimate_fleet_combat_preview(
        self,
        s: Session,
        *,
        attacker: Fleet,
        defender: Fleet,
        attacker_from_x: int,
        attacker_from_y: int,
    ) -> dict:
        bx, by = int(defender.pos_x), int(defender.pos_y)
        eff_atk, eff_def, meta = self._combat_effective_scores(
            s,
            attacker=attacker,
            defender=defender,
            attacker_from_x=attacker_from_x,
            attacker_from_y=attacker_from_y,
            battle_cell_x=bx,
            battle_cell_y=by,
        )
        trials = 400
        wins = 0
        for _ in range(trials):
            ar = int(eff_atk * random.uniform(0.94, 1.08))
            dr = int(eff_def * random.uniform(0.94, 1.08))
            if ar >= dr:
                wins += 1
        p_win = round(wins / trials, 3)
        return {
            "combat": True,
            "attacker_composition": dict(self._fleet_units_map(s, attacker)),
            "defender_composition": dict(self._fleet_units_map(s, defender)),
            "p_win_attacker": p_win,
            "factors": meta,
            "disclaimer": "Оценка по многократной симуляции случайного боя; исход одного боя не гарантирован.",
        }

    def _resolve_fleet_vs_fleet_combat(
        self,
        s: Session,
        *,
        attacker: Fleet,
        defender: Fleet,
        attacker_from_x: int,
        attacker_from_y: int,
        battle_tick: int,
        event_player_id: uuid.UUID,
    ) -> dict:
        """Итог боя: проигравший флот удалён; победитель с потерями; атакующий при победе занимает клетку защитника."""
        tx, ty, tz = int(defender.pos_x), int(defender.pos_y), int(defender.pos_z)
        eff_atk, eff_def, meta = self._combat_effective_scores(
            s,
            attacker=attacker,
            defender=defender,
            attacker_from_x=attacker_from_x,
            attacker_from_y=attacker_from_y,
            battle_cell_x=tx,
            battle_cell_y=ty,
        )
        u_atk = random.uniform(0.94, 1.08)
        u_def = random.uniform(0.94, 1.08)
        atk_roll = int(eff_atk * u_atk)
        def_roll = int(eff_def * u_def)
        ap = attacker.owner_player_id
        dp = defender.owner_player_id
        dname = self._fleet_public_name(defender)
        aname = self._fleet_public_name(attacker)
        atk_comp_0 = self._fleet_composition_snapshot(s, attacker)
        def_comp_0 = self._fleet_composition_snapshot(s, defender)

        roll_block = {
            "effective_attacker": round(eff_atk, 4),
            "effective_defender": round(eff_def, 4),
            "random_factor_attacker": round(u_atk, 6),
            "random_factor_defender": round(u_def, 6),
            "rolled_score_attacker": atk_roll,
            "rolled_score_defender": def_roll,
            "rule": "Победитель — у кого больше очков после броска (при равенстве побеждает атакующий).",
        }
        calc_block = {
            "how_score_works": "По каждому типу корабля: (HP + 3×урон) × количество; HP/урон из баланса × множители исследований; сумма = база. К базе: ×1.05 если атакующий стартовал из своей зоны снабжения; ×1.08 защитнику на своей домашней зоне.",
            "factors": meta,
            "rolls": roll_block,
            "composition_start": {"attacker": atk_comp_0, "defender": def_comp_0},
        }

        if atk_roll >= def_roll:
            loser_id = str(defender.id)
            s.delete(defender)
            s.flush()
            loss_frac = min(0.2, 0.06 + min(0.08, def_roll / max(400, atk_roll)))
            self._apply_fleet_post_combat_losses(s, attacker, fraction=loss_frac)
            atk_comp_1 = self._fleet_composition_snapshot(s, attacker)
            attacker.pos_x = tx
            attacker.pos_y = ty
            attacker.pos_z = tz
            s.flush()
            victor_side = {"destroyed_defender_fleet_id": loser_id, "winner": "attacker"}
            atk_casualties = self._composition_casualties(atk_comp_0, atk_comp_1)
            payload_att = {
                "result": "victory",
                "battle_calculation": calc_block,
                "outcome_summary": victor_side,
                "consequences": {
                    "enemy_fleet_removed": loser_id,
                    "your_ship_loss_fraction_applied": round(loss_frac, 4),
                    "your_fleet_survivors": atk_casualties,
                    "winner_takes_square": {"x": tx, "y": ty, "z": tz},
                },
            }
            self._emit_event(
                s,
                tick=battle_tick,
                type="fleet_combat",
                message=f"Бой: победа «{aname}» над «{dname}» ({atk_roll}:{def_roll}).",
                payload=payload_att,
                player_id=event_player_id,
            )
            if dp != ap:
                self._emit_event(
                    s,
                    tick=battle_tick,
                    type="fleet_combat",
                    message=f"Бой: «{dname}» уничтожен ({def_roll}:{atk_roll}).",
                    payload={
                        "result": "defeat_side",
                        "battle_calculation": calc_block,
                        "consequences": {
                            "your_fleet_lost_id": loser_id,
                            "winner_enemy_fleet": str(attacker.id),
                        },
                    },
                    player_id=dp,
                )
            return {
                "winner": "attacker",
                "destroyed_fleet_id": loser_id,
                "rolls": {"attacker": atk_roll, "defender": def_roll},
            }

        loser_id = str(attacker.id)
        s.delete(attacker)
        s.flush()
        loss_frac_d = min(0.2, 0.05 + min(0.08, atk_roll / max(400, def_roll)))
        self._apply_fleet_post_combat_losses(s, defender, fraction=loss_frac_d)
        def_comp_1 = self._fleet_composition_snapshot(s, defender)
        s.flush()

        defender_win = {"destroyed_attacker_fleet_id": loser_id, "winner": "defender"}
        def_casualties = self._composition_casualties(def_comp_0, def_comp_1)
        payload_lose_att = {
            "result": "defeat",
            "battle_calculation": calc_block,
            "outcome_summary": defender_win,
            "consequences": {
                "your_fleet_lost_id": loser_id,
                "enemy_survivors_after": def_casualties,
                "defender_ship_loss_fraction_applied": round(loss_frac_d, 4),
            },
        }
        self._emit_event(
            s,
            tick=battle_tick,
            type="fleet_combat",
            message=f"Бой: «{aname}» уничтожен «{dname}» ({atk_roll}:{def_roll}).",
            payload=payload_lose_att,
            player_id=event_player_id,
        )
        if dp != ap:
            self._emit_event(
                s,
                tick=battle_tick,
                type="fleet_combat",
                message=f"Бой: «{dname}» отбил «{aname}» ({def_roll}:{atk_roll}).",
                payload={
                    "result": "defense_win",
                    "battle_calculation": calc_block,
                    "consequences": {
                        "destroyed_enemy_fleet_id": loser_id,
                        "your_fleet_after_battle": def_casualties,
                        "ship_loss_fraction_applied": round(loss_frac_d, 4),
                    },
                },
                player_id=dp,
            )
        return {
            "winner": "defender",
            "lost_attacker_id": loser_id,
            "rolls": {"attacker": atk_roll, "defender": def_roll},
        }

    def combat_preview_for_move(
        self,
        s: Session,
        *,
        player_id: str,
        fleet_id: str,
        target_x: int,
        target_y: int,
        target_z: int,
    ) -> dict:
        """Превью боя при прилёте на клетку (если там чужой флот)."""
        pid = uuid.UUID(player_id)
        try:
            fid = uuid.UUID(fleet_id)
        except Exception:
            return {"ok": False, "error": "invalid_fleet_id"}
        if target_z != 0:
            return {"ok": False, "error": "z_not_supported_yet"}
        atk = s.execute(select(Fleet).where(Fleet.id == fid, Fleet.owner_player_id == pid)).scalars().first()
        if not atk:
            return {"ok": False, "error": "fleet_not_found"}
        dfd = (
            s.execute(
                select(Fleet).where(
                    Fleet.pos_x == int(target_x),
                    Fleet.pos_y == int(target_y),
                    Fleet.pos_z == int(target_z),
                    Fleet.owner_player_id != pid,
                )
            )
            .scalars()
            .first()
        )
        if not dfd:
            return {"ok": True, "combat": False}
        prev = self.estimate_fleet_combat_preview(
            s,
            attacker=atk,
            defender=dfd,
            attacker_from_x=int(atk.pos_x),
            attacker_from_y=int(atk.pos_y),
        )
        return {"ok": True, **prev}

    def _enemy_fleet_at(
        self, s: Session, *, x: int, y: int, z: int, owner_player_id: uuid.UUID
    ) -> Fleet | None:
        return (
            s.execute(
                select(Fleet).where(
                    Fleet.pos_x == int(x),
                    Fleet.pos_y == int(y),
                    Fleet.pos_z == int(z),
                    Fleet.owner_player_id != owner_player_id,
                )
            )
            .scalars()
            .first()
        )

    def _nearest_cell_without_other_fleet(
        self,
        s: Session,
        *,
        center_x: int,
        center_y: int,
        center_z: int,
        exclude_fleet_id: uuid.UUID,
        max_ring: int = 60,
    ) -> tuple[int, int] | None:
        """Ближайшая клетка (BFS по сетке), где нет чужого флота; exclude_fleet_id не считается занятием."""
        start = (int(center_x), int(center_y))
        seen: set[tuple[int, int]] = {start}
        q: deque[tuple[int, int]] = deque([start])
        cz = int(center_z)
        while q:
            x, y = q.popleft()
            if abs(x - int(center_x)) + abs(y - int(center_y)) > max_ring:
                continue
            other = (
                s.execute(
                    select(Fleet.id).where(
                        Fleet.pos_x == x,
                        Fleet.pos_y == y,
                        Fleet.pos_z == cz,
                        Fleet.id != exclude_fleet_id,
                    )
                )
                .first()
            )
            if other is None:
                return (x, y)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if (nx, ny) in seen:
                    continue
                seen.add((nx, ny))
                q.append((nx, ny))
        return None

    def _resolve_expired_fleet_combat_prompts(self, s: Session, *, tick: int, events: list) -> None:
        now = datetime.now(timezone.utc)
        expired = (
            s.execute(
                select(FleetOrder).where(
                    FleetOrder.status == "pending_combat",
                    FleetOrder.combat_prompt_expires_at.is_not(None),
                    FleetOrder.combat_prompt_expires_at <= now,
                )
            )
            .scalars()
            .all()
        )
        for order in expired:
            fleet = s.get(Fleet, order.fleet_id)
            if fleet and int(fleet.qty) >= 1:
                self._emit_event(
                    s,
                    tick=tick,
                    type="combat_prompt_expired",
                    message=(
                        f"Время подтверждения боя истекло — флот «{self._fleet_public_name(fleet)}» "
                        f"остаётся у ({fleet.pos_x},{fleet.pos_y})."
                    ),
                    payload={
                        "order_id": str(order.id),
                        "fleet_id": str(fleet.id),
                        "target": {"x": order.target_x, "y": order.target_y, "z": order.target_z},
                    },
                    player_id=order.owner_player_id,
                )
            order.status = "done"
            order.combat_prompt_expires_at = None
            events.append({"type": "combat_prompt_expired", "order_id": str(order.id)})

    def resolve_fleet_combat_prompt(self, s: Session, *, player_id: str, order_id: str, attack: bool) -> dict:
        """Второе подтверждение: attack=True — бой/заход; False — отказ (как истечение таймера)."""
        pid = uuid.UUID(player_id)
        try:
            oid = uuid.UUID(order_id)
        except Exception:
            return {"ok": False, "error": "invalid_order_id"}
        order = (
            s.execute(select(FleetOrder).where(FleetOrder.id == oid, FleetOrder.owner_player_id == pid))
            .scalars()
            .first()
        )
        if not order or order.status != "pending_combat":
            return {"ok": False, "error": "no_pending_combat"}
        now = datetime.now(timezone.utc)
        if order.combat_prompt_expires_at and order.combat_prompt_expires_at <= now:
            fleet_e = s.get(Fleet, order.fleet_id)
            bt = self.get_or_create_world_state(s).current_tick
            if fleet_e and int(fleet_e.qty) >= 1:
                self._emit_event(
                    s,
                    tick=bt,
                    type="combat_prompt_expired",
                    message=(
                        f"Время подтверждения боя истекло — флот «{self._fleet_public_name(fleet_e)}» "
                        f"остаётся у ({fleet_e.pos_x},{fleet_e.pos_y})."
                    ),
                    payload={
                        "order_id": str(order.id),
                        "fleet_id": str(fleet_e.id),
                        "target": {"x": order.target_x, "y": order.target_y, "z": order.target_z},
                    },
                    player_id=pid,
                )
            order.status = "done"
            order.combat_prompt_expires_at = None
            return {"ok": False, "error": "combat_prompt_expired"}

        fleet = s.get(Fleet, order.fleet_id)
        if not fleet or int(fleet.qty) < 1:
            order.status = "failed"
            order.combat_prompt_expires_at = None
            return {"ok": False, "error": "fleet_not_found"}

        ws = self.get_or_create_world_state(s)
        battle_tick = int(ws.current_tick)

        if not attack:
            order.status = "done"
            order.combat_prompt_expires_at = None
            self._emit_event(
                s,
                tick=battle_tick,
                type="combat_prompt_declined",
                message=f"Атака отменена — флот «{self._fleet_public_name(fleet)}» остаётся у ({fleet.pos_x},{fleet.pos_y}).",
                payload={"order_id": str(order.id), "fleet_id": str(fleet.id)},
                player_id=pid,
            )
            return {"ok": True, "result": "declined"}

        defender = self._enemy_fleet_at(
            s, x=order.target_x, y=order.target_y, z=order.target_z, owner_player_id=pid
        )
        if not defender:
            fleet.pos_x = int(order.target_x)
            fleet.pos_y = int(order.target_y)
            fleet.pos_z = int(order.target_z)
            order.status = "done"
            order.combat_prompt_expires_at = None
            self._emit_event(
                s,
                tick=battle_tick,
                type="fleet_arrived",
                message=f"Флот прибыл: {fleet.unit_type}×{fleet.qty} в ({fleet.pos_x},{fleet.pos_y},{fleet.pos_z}) (враг ушёл с клетки)",
                payload={"fleet_id": str(fleet.id), "qty": fleet.qty, "pos": {"x": fleet.pos_x, "y": fleet.pos_y, "z": fleet.pos_z}},
                player_id=pid,
            )
            return {"ok": True, "result": "walked_in"}

        own_block = (
            s.execute(
                select(Fleet).where(
                    Fleet.pos_x == int(order.target_x),
                    Fleet.pos_y == int(order.target_y),
                    Fleet.pos_z == int(order.target_z),
                    Fleet.owner_player_id == pid,
                    Fleet.id != fleet.id,
                )
            )
            .scalars()
            .first()
        )
        if own_block:
            order.status = "done"
            order.combat_prompt_expires_at = None
            self._emit_event(
                s,
                tick=battle_tick,
                type="fleet_order_failed",
                message="Атака отменена: в цели уже ваш другой флот.",
                payload={"order_id": str(order.id), "reason": "cell_occupied_by_own_fleet"},
                player_id=pid,
            )
            return {"ok": False, "error": "cell_occupied_by_own_fleet"}

        # Удаляем ордер до боя: иначе при проигрыше атакующего CASCADE по fleet_id удалит строку,
        # а ORM всё ещё попытается UPDATE — StaleDataError.
        s.delete(order)
        s.flush()

        self._resolve_fleet_vs_fleet_combat(
            s,
            attacker=fleet,
            defender=defender,
            attacker_from_x=int(fleet.pos_x),
            attacker_from_y=int(fleet.pos_y),
            battle_tick=battle_tick,
            event_player_id=pid,
        )
        return {"ok": True, "result": "combat"}

    def _pending_combat_prompts_payload(self, s: Session, *, player_id: uuid.UUID) -> list[dict]:
        out: list[dict] = []
        orders = (
            s.execute(select(FleetOrder).where(FleetOrder.owner_player_id == player_id, FleetOrder.status == "pending_combat"))
            .scalars()
            .all()
        )
        for order in orders:
            fleet = s.get(Fleet, order.fleet_id)
            if not fleet or int(fleet.qty) < 1:
                continue
            dfd = self._enemy_fleet_at(
                s, x=order.target_x, y=order.target_y, z=order.target_z, owner_player_id=player_id
            )
            if not dfd:
                preview: dict = {"combat": False}
            else:
                preview = self.estimate_fleet_combat_preview(
                    s,
                    attacker=fleet,
                    defender=dfd,
                    attacker_from_x=int(fleet.pos_x),
                    attacker_from_y=int(fleet.pos_y),
                )
            exp = getattr(order, "combat_prompt_expires_at", None)
            out.append(
                {
                    "order_id": str(order.id),
                    "fleet_id": str(fleet.id),
                    "target": {"x": order.target_x, "y": order.target_y, "z": order.target_z},
                    "staging": {"x": fleet.pos_x, "y": fleet.pos_y, "z": fleet.pos_z},
                    "expires_at": exp.isoformat() if exp else None,
                    "defender_fleet_id": str(dfd.id) if dfd else None,
                    "preview": preview,
                }
            )
        return out

    def _primary_colony_planet(self, s: Session, *, owner_id: uuid.UUID) -> Planet | None:
        return (
            s.execute(select(Planet).where(Planet.owner_player_id == owner_id).order_by(Planet.created_at.asc()))
            .scalars()
            .first()
        )

    def _drydock_count_on_planet(self, s: Session, *, planet_id: uuid.UUID, owner_id: uuid.UUID) -> int:
        return int(
            s.execute(
                select(func.count(Building.id)).where(
                    Building.planet_id == planet_id,
                    Building.owner_player_id == owner_id,
                    or_(
                        Building.building_type == "drydock_mini",
                        Building.building_type == "drydock_mini_t1",
                    ),
                )
            ).scalar()
            or 0
        )

    def _can_create_fleet_at_planet(self, s: Session, *, owner_id: uuid.UUID, planet: Planet) -> bool:
        home = self._primary_colony_planet(s, owner_id=owner_id)
        if home and home.id == planet.id:
            return True
        return self._drydock_count_on_planet(s, planet_id=planet.id, owner_id=owner_id) > 0

    def _pick_fleet_spawn_xy(
        self, s: Session, *, owner_id: uuid.UUID, px: int, py: int, pz: int
    ) -> tuple[int, int] | None:
        offsets = [
            (0, -1),
            (-1, 0),
            (1, 0),
            (0, 1),
            (0, -2),
            (-2, 0),
            (2, 0),
            (0, 2),
            (-1, -1),
            (1, -1),
            (-1, 1),
            (1, 1),
        ]
        for dx, dy in offsets:
            tx, ty = px + dx, py + dy
            blocked = (
                s.execute(select(Building.id).where(Building.x == tx, Building.y == ty, Building.z == pz))
                .scalars()
                .first()
            )
            if blocked:
                continue
            occupied = (
                s.execute(select(Fleet.id).where(Fleet.pos_x == tx, Fleet.pos_y == ty, Fleet.pos_z == pz))
                .scalars()
                .first()
            )
            if occupied:
                continue
            return tx, ty
        return None

    def create_fleet(
        self,
        s: Session,
        *,
        player_id: str,
        planet_id: str,
        name: str | None,
        composition: dict | None,
    ) -> dict:
        pid = uuid.UUID(player_id)
        try:
            plid = uuid.UUID(planet_id)
        except Exception:
            return {"ok": False, "error": "invalid_planet_id"}
        planet = s.execute(select(Planet).where(Planet.id == plid, Planet.owner_player_id == pid)).scalars().first()
        if not planet:
            return {"ok": False, "error": "planet_not_found"}
        if not self._can_create_fleet_at_planet(s, owner_id=pid, planet=planet):
            return {"ok": False, "error": "no_shipyard_access"}

        spawn = self._pick_fleet_spawn_xy(s, owner_id=pid, px=planet.pos_x, py=planet.pos_y, pz=0)
        if not spawn:
            return {"ok": False, "error": "no_free_spawn_cell"}
        tx, ty = spawn

        if not isinstance(composition, dict) or not composition:
            return {"ok": False, "error": "invalid_composition"}
        allowed = self._logical_unit_keys()
        units: dict[str, int] = {}
        for raw_k, raw_v in composition.items():
            k = str(raw_k or "").strip().lower()
            if k not in allowed:
                return {"ok": False, "error": "invalid_unit_type", "unit_type": k}
            try:
                q = int(raw_v)
            except Exception:
                return {"ok": False, "error": "invalid_qty"}
            if q < 0:
                return {"ok": False, "error": "negative_qty"}
            if q > 0:
                units[k] = int(q)
        total = sum(units.values())
        if total < 1:
            return {"ok": False, "error": "fleet_empty"}
        if total > 50:
            return {"ok": False, "error": "fleet_too_large"}

        home = s.execute(select(Planet).where(Planet.owner_player_id == pid)).scalar_one_or_none()
        if not home:
            return {"ok": False, "error": "no_home_planet"}
        res = s.execute(select(Resource).where(Resource.planet_id == home.id)).scalar_one_or_none()
        if not res:
            return {"ok": False, "error": "no_resources"}

        pay = {"metal": 0, "crystal": 0, "energy": 0, "fuel": 0}
        for ut, q in units.items():
            cst = self._unit_build_cost_parts(ut)
            for rk in pay:
                pay[rk] += int(cst.get(rk, 0)) * int(q)

        if (
            int(res.metal) < pay["metal"]
            or int(res.crystal) < pay["crystal"]
            or int(res.energy) < pay["energy"]
            or int(getattr(res, "fuel", 0)) < pay["fuel"]
        ):
            return {
                "ok": False,
                "error": "not_enough_resources",
                "need": pay,
                "have": {
                    "metal": int(res.metal),
                    "crystal": int(res.crystal),
                    "energy": int(res.energy),
                    "fuel": int(getattr(res, "fuel", 0)),
                },
            }

        res.metal = int(res.metal) - pay["metal"]
        res.crystal = int(res.crystal) - pay["crystal"]
        res.energy = int(res.energy) - pay["energy"]
        res.fuel = int(res.fuel) - pay["fuel"]

        nm = (name if isinstance(name, str) else "").strip() or self._next_fleet_default_name(s, owner_id=pid)
        if len(nm) > 64:
            return {"ok": False, "error": "name_too_long"}
        dominant = max(units.items(), key=lambda kv: (kv[1], kv[0]))[0]
        fleet = Fleet(
            owner_player_id=pid,
            unit_type=str(dominant),
            qty=0,
            pos_x=int(tx),
            pos_y=int(ty),
            pos_z=0,
            name=nm[:64],
        )
        s.add(fleet)
        s.flush()
        self._write_fleet_units(s, fleet, units)
        s.flush()

        ws = self.get_or_create_world_state(s)
        self._emit_event(
            s,
            tick=ws.current_tick,
            type="fleet_created",
            message=f"Создан флот «{fleet.name}» у планеты {planet.name}",
            payload={
                "fleet_id": str(fleet.id),
                "name": fleet.name,
                "pos": {"x": tx, "y": ty, "z": 0},
                "composition": dict(units),
            },
            player_id=pid,
        )
        return {
            "ok": True,
            "fleet_id": str(fleet.id),
            "name": fleet.name,
            "pos": {"x": tx, "y": ty, "z": 0},
            "composition": dict(units),
            "cost": pay,
        }

    def _active_order_for_unit(self, s: Session, *, unit_id: uuid.UUID) -> UnitOrder | None:
        return (
            s.execute(
                select(UnitOrder)
                .where(UnitOrder.unit_id == unit_id, UnitOrder.status.in_(["queued", "in_progress"]))
                .order_by(UnitOrder.created_at.desc())
            )
            .scalars()
            .first()
        )

    def _active_order_for_fleet(self, s: Session, *, fleet_id: uuid.UUID) -> FleetOrder | None:
        return (
            s.execute(
                select(FleetOrder)
                .where(
                    FleetOrder.fleet_id == fleet_id,
                    FleetOrder.status.in_(["queued", "in_progress", "pending_combat"]),
                )
                .order_by(FleetOrder.created_at.desc())
            )
            .scalars()
            .first()
        )

    def create_fleet_move_order(
        self,
        s: Session,
        *,
        player_id: str,
        fleet_id: str,
        target_x: int,
        target_y: int,
        target_z: int,
        force_attack: bool = False,
    ) -> dict:
        pid = uuid.UUID(player_id)
        fid = uuid.UUID(fleet_id)

        fleet = (
            s.execute(select(Fleet).where(Fleet.id == fid, Fleet.owner_player_id == pid))
            .scalars()
            .first()
        )
        if not fleet:
            return {"ok": False, "error": "fleet_not_found"}
        if fleet.qty < 1:
            return {"ok": False, "error": "fleet_empty"}
        if target_z != 0:
            return {"ok": False, "error": "z_not_supported_yet"}

        units_map = self._fleet_units_map(s, fleet)
        if not units_map:
            return {"ok": False, "error": "fleet_empty"}

        if self._active_order_for_fleet(s, fleet_id=fleet.id):
            return {"ok": False, "error": "active_order_exists"}

        ally_at = (
            s.execute(
                select(Fleet).where(
                    Fleet.pos_x == int(target_x),
                    Fleet.pos_y == int(target_y),
                    Fleet.pos_z == int(target_z),
                    Fleet.owner_player_id == pid,
                    Fleet.id != fleet.id,
                )
            )
            .scalars()
            .first()
        )
        if ally_at:
            return {"ok": False, "error": "cell_occupied_by_own_fleet"}

        distance = abs(target_x - fleet.pos_x) + abs(target_y - fleet.pos_y)
        if distance == 0:
            return {"ok": False, "error": "target_same_cell"}
        travel_ticks = self._fleet_travel_ticks_for_distance(distance=distance, units=units_map)
        travel = type("TravelPlan", (), {"distance": int(distance), "travel_ticks": int(travel_ticks)})

        # Energy (fleet-local): движение тратит энергию флота, не энергию империи.
        move_energy_cost = int(max(1, self._fleet_upkeep_energy_total(s, player_id=pid, units=units_map)) * int(travel.distance))
        cur_e = int(getattr(fleet, "energy", 0) or 0)
        if cur_e < move_energy_cost:
            return {"ok": False, "error": "not_enough_fleet_energy", "need": move_energy_cost, "have": cur_e}
        fleet.energy = int(cur_e) - int(move_energy_cost)

        # Fuel (MVP): списываем с ресурсов домашней планеты владельца.
        home = s.execute(select(Planet).where(Planet.owner_player_id == pid)).scalar_one_or_none()
        if not home:
            return {"ok": False, "error": "no_home_planet"}
        res = s.execute(select(Resource).where(Resource.planet_id == home.id)).scalar_one_or_none()
        if not res:
            return {"ok": False, "error": "no_resources"}

        fuel_plan = type(
            "FuelPlan",
            (),
            {
                "fuel_cost": int(
                    self._fleet_fuel_cost_total(
                        s,
                        player_id=str(player_id),
                        fleet=fleet,
                        distance=int(travel.distance),
                        units=units_map,
                    )
                )
            },
        )
        if int(getattr(res, "fuel", 0)) < fuel_plan.fuel_cost:
            self._emit_event(
                s,
                tick=self.get_or_create_world_state(s).current_tick,
                type="not_enough_fuel",
                message=f"Не хватает топлива для перелёта (нужно {fuel_plan.fuel_cost}, есть {int(getattr(res, 'fuel', 0))})",
                payload={"need": fuel_plan.fuel_cost, "have": int(getattr(res, "fuel", 0)), "distance": travel.distance, "qty": fleet.qty},
                player_id=pid,
            )
            return {"ok": False, "error": "not_enough_fuel", "need": fuel_plan.fuel_cost, "have": int(getattr(res, "fuel", 0))}

        # Списание топлива при постановке приказа.
        res.fuel = int(getattr(res, "fuel", 0)) - fuel_plan.fuel_cost

        ws = self.get_or_create_world_state(s)
        order = FleetOrder(
            fleet_id=fleet.id,
            owner_player_id=pid,
            order_type="move",
            from_x=fleet.pos_x,
            from_y=fleet.pos_y,
            from_z=fleet.pos_z,
            target_x=target_x,
            target_y=target_y,
            target_z=target_z,
            qty=fleet.qty,
            status="queued",
            start_tick=ws.current_tick + 1,
            finish_tick=ws.current_tick + travel.travel_ticks,
            force_attack=bool(force_attack),
            combat_prompt_expires_at=None,
        )
        s.add(order)
        s.flush()

        self._emit_event(
            s,
            tick=ws.current_tick,
            type="fleet_order_created",
            message=f"Приказ флота: {fleet.qty} кораблей → ({target_x},{target_y},{target_z})",
            payload={
                "order_id": str(order.id),
                "fleet_id": str(fleet.id),
                "from": {"x": order.from_x, "y": order.from_y, "z": order.from_z},
                "target": {"x": order.target_x, "y": order.target_y, "z": order.target_z},
                "qty": order.qty,
                "composition": dict(units_map),
                "travel_ticks": travel.travel_ticks,
                "fuel_cost": fuel_plan.fuel_cost,
            },
            player_id=pid,
        )
        self._emit_event(
            s,
            tick=ws.current_tick,
            type="fuel_spent",
            message=f"Топливо потрачено: -{fuel_plan.fuel_cost} (перелёт, {fleet.qty} кораблей)",
            payload={"fuel_cost": fuel_plan.fuel_cost, "distance": travel.distance, "qty": fleet.qty, "fleet_id": str(fleet.id)},
            player_id=pid,
        )

        return {
            "ok": True,
            "order_id": str(order.id),
            "fleet_id": str(fleet.id),
            "from": {"x": order.from_x, "y": order.from_y, "z": order.from_z},
            "target": {"x": order.target_x, "y": order.target_y, "z": order.target_z},
            "qty": order.qty,
            "distance": travel.distance,
            "travel_ticks": travel.travel_ticks,
            "travel_sols": int(travel.travel_ticks),
            "start_tick": order.start_tick,
            "start_sol": int(order.start_tick),
            "finish_tick": order.finish_tick,
            "finish_sol": int(order.finish_tick),
            "fuel_cost": fuel_plan.fuel_cost,
        }

    def cancel_fleet_order(self, s: Session, *, player_id: str, fleet_id: str) -> dict:
        pid = uuid.UUID(player_id)
        fid = uuid.UUID(fleet_id)

        fleet = s.execute(select(Fleet).where(Fleet.id == fid, Fleet.owner_player_id == pid)).scalar_one_or_none()
        if not fleet:
            return {"ok": False, "error": "fleet_not_found"}

        active = self._active_order_for_fleet(s, fleet_id=fid)
        if not active:
            return {"ok": False, "error": "no_active_order"}

        active.status = "cancelled"
        self._emit_event(
            s,
            tick=self.get_or_create_clock(s).current_tick,
            type="fleet_order_cancelled",
            message=f"Приказ отменён: {fleet.unit_type}×{fleet.qty}",
            payload={"fleet_id": str(fleet.id), "order_id": str(active.id)},
            player_id=pid,
        )
        s.flush()
        return {"ok": True, "fleet_id": str(fleet.id), "order_id": str(active.id)}

    def create_scout_move_order(self, s: Session, *, player_id: str, target_x: int, target_y: int, target_z: int) -> dict:
        pid = uuid.UUID(player_id)

        home = s.execute(select(Planet).where(Planet.owner_player_id == pid)).scalar_one_or_none()
        if not home:
            return {"ok": False, "error": "no_home_planet"}

        if target_z != 0:
            return {"ok": False, "error": "z_not_supported_yet"}

        scout_unit = (
            s.execute(
                select(Unit).where(
                    Unit.owner_player_id == pid,
                    Unit.planet_id == home.id,
                    Unit.unit_type == "scout",
                )
            )
            .scalar_one_or_none()
        )

        # Для "клик по клетке -> лететь" используем существующий scout fleet игрока.
        # Никаких автосозданий: иначе можно "напечатать" бесконечно много скаутов.
        source_fleet = None
        for cand in s.execute(select(Fleet).where(Fleet.owner_player_id == pid).order_by(Fleet.created_at.asc())).scalars():
            um = self._fleet_units_map(s, cand)
            if int(um.get("scout", 0)) > 0:
                source_fleet = cand
                break
        if not source_fleet or source_fleet.qty < 1:
            return {"ok": False, "error": "not_enough_scouts"}

        from_x, from_y, from_z = source_fleet.pos_x, source_fleet.pos_y, source_fleet.pos_z

        # Ордеры движения должны быть через FleetOrder. UnitOrder здесь — устаревшая ветка.
        return self.create_fleet_move_order(
            s,
            player_id=player_id,
            fleet_id=str(source_fleet.id),
            target_x=target_x,
            target_y=target_y,
            target_z=target_z,
        )

    def process_next_tick(self, s: Session) -> dict:
        ws = self.get_or_create_world_state(s)
        next_tick = ws.current_tick + 1
        events: list[dict] = []

        # 0) Tech completion
        ready_techs = (
            s.execute(
                select(PlayerTech)
                .where(PlayerTech.status == "in_progress", PlayerTech.finish_tick <= next_tick)
                .order_by(PlayerTech.created_at)
            )
            .scalars()
            .all()
        )
        for t in ready_techs:
            t.status = "done"
            events.append({"type": "tech_done", "tech_id": t.tech_id, "player_id": str(t.player_id)})
            tech_nm = t.tech_id
            if self._balance and self._balance.pack:
                td = self._balance.pack.tech_by_id.get(t.tech_id)
                if isinstance(td, dict) and isinstance(td.get("name"), str) and td["name"].strip():
                    tech_nm = td["name"].strip()
            self._emit_event(
                s,
                tick=next_tick,
                type="tech_done",
                message=f"Исследование завершено: {tech_nm}",
                payload={"tech_id": t.tech_id},
                player_id=t.player_id,
            )

        # 1) Fleet orders
        self._resolve_expired_fleet_combat_prompts(s, tick=next_tick, events=events)
        ready_fleet_orders = (
            s.execute(
                select(FleetOrder)
                .where(FleetOrder.status.in_(["queued", "in_progress"]), FleetOrder.finish_tick <= next_tick)
                .order_by(FleetOrder.created_at)
            )
            .scalars()
            .all()
        )
        for order in ready_fleet_orders:
            order.status = "in_progress"
            fleet = (
                s.execute(select(Fleet).where(Fleet.id == order.fleet_id, Fleet.owner_player_id == order.owner_player_id))
                .scalars()
                .first()
            )
            if not fleet or fleet.qty < 1:
                order.status = "failed"
                events.append({"type": "fleet_order_failed", "order_id": str(order.id), "reason": "fleet_unavailable"})
                continue

            occupant = (
                s.execute(
                    select(Fleet).where(
                        Fleet.pos_x == order.target_x,
                        Fleet.pos_y == order.target_y,
                        Fleet.pos_z == order.target_z,
                        Fleet.id != fleet.id,
                    )
                )
                .scalars()
                .first()
            )
            if occupant:
                if occupant.owner_player_id == fleet.owner_player_id:
                    if str(getattr(order, "order_type", "") or "") == "emergency_return":
                        order.status = "failed"
                        events.append(
                            {
                                "type": "fleet_order_failed",
                                "order_id": str(order.id),
                                "reason": "cell_occupied_by_own_fleet",
                            }
                        )
                        self._emit_event(
                            s,
                            tick=next_tick,
                            type="fleet_order_failed",
                            message="Аварийный возврат отменён: в клетке хаба уже стоит ваш другой флот.",
                            payload={"order_id": str(order.id), "reason": "cell_occupied_by_own_fleet"},
                            player_id=order.owner_player_id,
                        )
                        continue
                    order.status = "failed"
                    # Топливо уже списали при создании приказа; к прилёту цель занялась своим флотом — возвращаем стоимость этого перелёта.
                    pid_own = fleet.owner_player_id
                    fc_rf = 0
                    home_rf = s.execute(select(Planet).where(Planet.owner_player_id == pid_own)).scalar_one_or_none()
                    res_rf = (
                        s.execute(select(Resource).where(Resource.planet_id == home_rf.id)).scalar_one_or_none()
                        if home_rf
                        else None
                    )
                    if res_rf and hasattr(res_rf, "fuel"):
                        d_rf = abs(int(order.target_x) - int(order.from_x)) + abs(int(order.target_y) - int(order.from_y))
                        um_rf = self._fleet_units_map(s, fleet)
                        fc_rf = int(
                            self._fleet_fuel_cost_total(
                                s,
                                player_id=str(pid_own),
                                fleet=fleet,
                                distance=d_rf,
                                units=um_rf,
                            )
                        )
                        if fc_rf > 0:
                            res_rf.fuel = int(getattr(res_rf, "fuel", 0)) + fc_rf
                    fail_msg = "Перелёт отменён: в цели уже стоит ваш другой флот (в одной клетке — только один флот)."
                    if fc_rf > 0:
                        fail_msg = f"{fail_msg} Топливо за перелёт возвращено: +{fc_rf}."
                    events.append(
                        {
                            "type": "fleet_order_failed",
                            "order_id": str(order.id),
                            "reason": "cell_occupied_by_own_fleet",
                        }
                    )
                    self._emit_event(
                        s,
                        tick=next_tick,
                        type="fleet_order_failed",
                        message=fail_msg,
                        payload={
                            "order_id": str(order.id),
                            "reason": "cell_occupied_by_own_fleet",
                            "fuel_refunded": fc_rf,
                        },
                        player_id=order.owner_player_id,
                    )
                    continue
                if bool(getattr(order, "force_attack", False)):
                    self._resolve_fleet_vs_fleet_combat(
                        s,
                        attacker=fleet,
                        defender=occupant,
                        attacker_from_x=int(order.from_x),
                        attacker_from_y=int(order.from_y),
                        battle_tick=next_tick,
                        event_player_id=order.owner_player_id,
                    )
                    order.status = "done"
                    events.append({"type": "fleet_order_done", "order_id": str(order.id), "fleet_id": str(fleet.id)})
                    continue

                if str(getattr(order, "order_type", "") or "") == "emergency_return":
                    pair = self._nearest_cell_without_other_fleet(
                        s,
                        center_x=int(order.target_x),
                        center_y=int(order.target_y),
                        center_z=int(order.target_z),
                        exclude_fleet_id=fleet.id,
                    )
                    if pair:
                        fleet.pos_x, fleet.pos_y = int(pair[0]), int(pair[1])
                        fleet.pos_z = int(order.target_z)
                        order.status = "done"
                        events.append({"type": "fleet_order_done", "order_id": str(order.id), "fleet_id": str(fleet.id)})
                        self._emit_event(
                            s,
                            tick=next_tick,
                            type="emergency_orbit_staging",
                            message=(
                                f"Аварийный возврат: у хаба ({order.target_x},{order.target_y}) враг "
                                f"«{self._fleet_public_name(occupant)}» — флот на ({pair[0]},{pair[1]}), нужен ваш приказ."
                            ),
                            payload={
                                "order_id": str(order.id),
                                "fleet_id": str(fleet.id),
                                "hub": {"x": order.target_x, "y": order.target_y, "z": order.target_z},
                                "staging": {"x": pair[0], "y": pair[1], "z": fleet.pos_z},
                                "defender_fleet_id": str(occupant.id),
                            },
                            player_id=order.owner_player_id,
                        )
                        continue
                    order.status = "failed"
                    events.append(
                        {"type": "fleet_order_failed", "order_id": str(order.id), "reason": "emergency_no_staging_cell"}
                    )
                    self._emit_event(
                        s,
                        tick=next_tick,
                        type="fleet_order_failed",
                        message="Аварийный возврат: нет свободной клетки у хаба, занятого врагом.",
                        payload={"order_id": str(order.id), "reason": "emergency_no_staging_cell"},
                        player_id=order.owner_player_id,
                    )
                    continue

                # Второе подтверждение: флот у кромки цели, бой только после согласия игрока (или таймаут).
                pair = self._nearest_cell_without_other_fleet(
                    s,
                    center_x=int(order.target_x),
                    center_y=int(order.target_y),
                    center_z=int(order.target_z),
                    exclude_fleet_id=fleet.id,
                )
                if pair:
                    fleet.pos_x, fleet.pos_y = int(pair[0]), int(pair[1])
                    fleet.pos_z = int(order.target_z)
                exp = datetime.now(timezone.utc) + timedelta(seconds=30)
                order.status = "pending_combat"
                order.combat_prompt_expires_at = exp
                pv = self.estimate_fleet_combat_preview(
                    s,
                    attacker=fleet,
                    defender=occupant,
                    attacker_from_x=int(fleet.pos_x),
                    attacker_from_y=int(fleet.pos_y),
                )
                self._emit_event(
                    s,
                    tick=next_tick,
                    type="combat_prompt_arrival",
                    message=(
                        f"Флот у цели ({order.target_x},{order.target_y}): враг «{self._fleet_public_name(occupant)}». "
                        f"Подтвердите бой в течение 30 с."
                    ),
                    payload={
                        "order_id": str(order.id),
                        "fleet_id": str(fleet.id),
                        "target": {"x": order.target_x, "y": order.target_y, "z": order.target_z},
                        "staging": {"x": fleet.pos_x, "y": fleet.pos_y, "z": fleet.pos_z},
                        "expires_at": exp.isoformat(),
                        "defender_fleet_id": str(occupant.id),
                        "preview": {
                            "p_win_attacker": pv.get("p_win_attacker"),
                            "attacker_composition": pv.get("attacker_composition"),
                            "defender_composition": pv.get("defender_composition"),
                            "factors": pv.get("factors"),
                            "disclaimer": pv.get("disclaimer"),
                        },
                    },
                    player_id=order.owner_player_id,
                )
                events.append({"type": "combat_prompt_arrival", "order_id": str(order.id)})
                continue

            fleet.pos_x = order.target_x
            fleet.pos_y = order.target_y
            fleet.pos_z = order.target_z
            order.status = "done"
            events.append({"type": "fleet_order_done", "order_id": str(order.id), "fleet_id": str(fleet.id)})
            self._emit_event(
                s,
                tick=next_tick,
                type="fleet_arrived",
                message=f"Флот прибыл: {fleet.unit_type}×{fleet.qty} в ({fleet.pos_x},{fleet.pos_y},{fleet.pos_z})",
                payload={"fleet_id": str(fleet.id), "qty": fleet.qty, "pos": {"x": fleet.pos_x, "y": fleet.pos_y, "z": fleet.pos_z}},
                player_id=order.owner_player_id,
            )

        ready_orders = (
            s.execute(
                select(UnitOrder)
                .where(UnitOrder.status.in_(["queued", "in_progress"]), UnitOrder.finish_tick <= next_tick)
                .order_by(UnitOrder.created_at)
            )
            .scalars()
            .all()
        )

        for order in ready_orders:
            order.status = "in_progress"
            unit = s.execute(select(Unit).where(Unit.id == order.unit_id)).scalar_one_or_none()
            if not unit or unit.qty < 1:
                # Если сток юнитов пуст, попробуем списать 1 из fleet в клетке from_* (MVP).
                source_fleet = (
                    s.execute(
                        select(Fleet).where(
                            Fleet.owner_player_id == (unit.owner_player_id if unit else None),
                            Fleet.unit_type == (unit.unit_type if unit else "scout"),
                            Fleet.pos_x == order.from_x,
                            Fleet.pos_y == order.from_y,
                            Fleet.pos_z == order.from_z,
                        )
                    )
                    .scalars()
                    .first()
                )
                if not source_fleet or source_fleet.qty < 1:
                    order.status = "failed"
                    events.append({"type": "order_failed", "order_id": str(order.id), "reason": "unit_unavailable"})
                    continue
                source_fleet.qty -= 1
            else:
                unit.qty -= 1

            fleet = (
                s.execute(
                    select(Fleet).where(
                        Fleet.owner_player_id == unit.owner_player_id,
                        Fleet.pos_x == order.target_x,
                        Fleet.pos_y == order.target_y,
                        Fleet.pos_z == order.target_z,
                        Fleet.unit_type == unit.unit_type,
                    )
                )
                .scalar_one_or_none()
            )
            if not fleet:
                fleet = Fleet(
                    owner_player_id=unit.owner_player_id,
                    unit_type=unit.unit_type,
                    qty=1,
                    pos_x=order.target_x,
                    pos_y=order.target_y,
                    pos_z=order.target_z,
                    name=self._next_fleet_default_name(s, owner_id=unit.owner_player_id),
                )
                s.add(fleet)
            else:
                fleet.qty += 1

            order.status = "done"
            events.append(
                {
                    "type": "order_done",
                    "order_id": str(order.id),
                    "unit_id": str(unit.id),
                    "target": {"x": order.target_x, "y": order.target_y, "z": order.target_z},
                }
            )
            self._emit_event(
                s,
                tick=next_tick,
                type="order_done",
                message=f"Scout прибыл в сектор ({order.target_x},{order.target_y},{order.target_z})",
                payload={"order_id": str(order.id), "unit_id": str(unit.id), "target": {"x": order.target_x, "y": order.target_y, "z": order.target_z}},
                player_id=unit.owner_player_id,
            )

        ws.current_tick = next_tick
        ws.updated_at = datetime.now(timezone.utc)

        # 2) Форпосты: содержание (может выключить форпост)
        self._apply_outpost_upkeep_tick(s, tick=next_tick)
        # 3) Энергия флотов: пополнение/реген только при снабжении/хабе
        self._apply_fleet_energy_tick(s, tick=next_tick)
        # 4) Автопилот: аварийный возврат к хабу если нет энергии/снабжения
        self._apply_emergency_return_orders(s, tick=next_tick)
        # 5) Форпосты: автоматический обстрел вражеских флотов (каждый тик)
        self._apply_outpost_combat_tick(s, tick=next_tick)

        inf_src = self._collect_influence_sources(s)
        self._apply_influence_control_tick(s, tick=next_tick, sources=inf_src)

        # MVP: производство ресурсов по тикам на планетах
        planets = s.execute(select(Planet)).scalars().all()
        for p in planets:
            self.apply_planet_production_tick(s, planet_id=p.id, influence_sources=inf_src)

        # Логистика линий снабжения к форпостам (еда/вода с планеты-хаба).
        self._apply_supply_route_logistics_tick(s, tick=next_tick)

        # Имперское содержание флотов: списание с капитальной планеты.
        self._apply_fleet_empire_upkeep_tick(s, tick=next_tick)

        # MVP: upkeep после обработки ордеров, для всех игроков у кого есть флоты.
        owner_ids = s.execute(select(Fleet.owner_player_id).distinct()).scalars().all()
        for oid in owner_ids:
            self.apply_fleet_upkeep_tick(s, player_id=oid, tick=next_tick)

        s.flush()
        return {"current_tick": ws.current_tick, "current_sol": int(ws.current_tick), "events": events}

    def get_units_status(self, s: Session, *, player_id: str) -> dict:
        pid = uuid.UUID(player_id)
        home = s.execute(select(Planet).where(Planet.owner_player_id == pid)).scalar_one_or_none()
        if not home:
            return {"units": []}

        units = s.execute(select(Unit).where(Unit.owner_player_id == pid).order_by(Unit.unit_type)).scalars().all()
        payload = []
        for unit in units:
            active_order = self._active_order_for_unit(s, unit_id=unit.id)
            status = "moving" if active_order else "idle"
            position = {"x": home.pos_x, "y": home.pos_y, "z": 0}
            if status == "moving" and active_order:
                position = {"x": active_order.from_x, "y": active_order.from_y, "z": active_order.from_z}

            payload.append(
                {
                    "unit_id": str(unit.id),
                    "unit_type": unit.unit_type,
                    "qty": unit.qty,
                    "position": position,
                    "status": status,
                    "active_order": (
                        {
                            "id": str(active_order.id),
                            "order_type": active_order.order_type,
                            "status": active_order.status,
                            "from": {"x": active_order.from_x, "y": active_order.from_y, "z": active_order.from_z},
                            "target": {"x": active_order.target_x, "y": active_order.target_y, "z": active_order.target_z},
                            "start_tick": active_order.start_tick,
                            "finish_tick": active_order.finish_tick,
                        }
                        if active_order
                        else None
                    ),
                }
            )

        ws = self.get_or_create_world_state(s)
        return {"current_tick": ws.current_tick, "current_sol": int(ws.current_tick), "units": payload}

    def get_world_state(self, s: Session, *, player_id: str, auto_tick_enabled: bool, auto_tick_interval_seconds: float) -> dict:
        pid = uuid.UUID(player_id)
        ws = self.get_or_create_world_state(s)
        self._resolve_expired_fleet_combat_prompts(s, tick=ws.current_tick, events=[])

        home = s.execute(select(Planet).where(Planet.owner_player_id == pid)).scalar_one_or_none()
        if not home:
            return {
                "current_tick": ws.current_tick,
                "current_sol": int(ws.current_tick),
                "player_id": str(pid),
                "auto_tick_enabled": auto_tick_enabled,
                "auto_tick_interval_seconds": auto_tick_interval_seconds,
                "unit": None,
                "pending_combat_prompts": [],
            }

        # Приоритет «главного» флота — больше скаутов в составе (для HUD/камеры).
        scout_fleet = None
        best_scouts = -1
        for f in s.execute(select(Fleet).where(Fleet.owner_player_id == pid).order_by(Fleet.created_at.asc())).scalars():
            um = self._fleet_units_map(s, f)
            sc = int(um.get("scout", 0))
            if sc > best_scouts:
                best_scouts = sc
                scout_fleet = f
        if scout_fleet is not None and best_scouts <= 0:
            scout_fleet = None

        pos = {"x": home.pos_x, "y": home.pos_y, "z": 0}
        fleet_payload = None
        if scout_fleet and scout_fleet.qty > 0:
            pos = {"x": scout_fleet.pos_x, "y": scout_fleet.pos_y, "z": scout_fleet.pos_z}
            active_payload = self._fleet_active_order_payload(s, ws, scout_fleet)
            status = "moving" if active_payload else "idle"
            comp = self._fleet_units_map(s, scout_fleet)
            fleet_payload = {
                "id": str(scout_fleet.id),
                "name": self._fleet_public_name(scout_fleet),
                "unit_type": scout_fleet.unit_type,
                "qty": int(scout_fleet.qty),
                "composition": comp,
                "status": status,
                **pos,
                "active_order": active_payload,
            }

        fleets_payload: list[dict] = []
        all_fleets = (
            s.execute(select(Fleet).where(Fleet.owner_player_id == pid).order_by(Fleet.created_at.asc()))
            .scalars()
            .all()
        )
        for f in all_fleets:
            if int(f.qty) <= 0:
                continue
            active_payload = self._fleet_active_order_payload(s, ws, f)
            status = "moving" if active_payload else "idle"
            comp = self._fleet_units_map(s, f)
            fleets_payload.append(
                {
                    "id": str(f.id),
                    "name": self._fleet_public_name(f),
                    "unit_type": f.unit_type,
                    "qty": int(f.qty),
                    "composition": comp,
                    "status": status,
                    "x": f.pos_x,
                    "y": f.pos_y,
                    "z": f.pos_z,
                    "active_order": active_payload,
                }
            )

        # Economy summary for UI
        res = s.execute(select(Resource).where(Resource.planet_id == home.id)).scalar_one_or_none()
        metal = int(res.metal) if res else 0
        crystal = int(res.crystal) if res else 0
        energy = int(res.energy) if res else 0
        fuel = int(getattr(res, "fuel", 0)) if res else 0
        food = int(getattr(res, "food", 0)) if res else 0
        water = int(getattr(res, "water", 0)) if res else 0

        inf_src_h = self._collect_influence_sources(s)
        dlt_home = self._planet_production_deltas(s, planet=home, influence_sources=inf_src_h)
        prod_per_tick = {k: int(dlt_home[k]) for k in PLANET_STORE_KEYS}

        fleets = s.execute(select(Fleet).where(Fleet.owner_player_id == pid)).scalars().all()
        upkeep_energy = 0
        fleet_units = 0
        for f in fleets:
            um = self._fleet_units_map(s, f)
            if not um:
                continue
            fleet_units += sum(int(v) for v in um.values())
            upkeep_energy += self._fleet_upkeep_energy_total(s, player_id=pid, units=um)

        home_mx = self._effective_max_population(s, home)
        home_pop = int(getattr(home, "population", 0) or 0)
        pop_food_need, pop_water_need = self._population_vitals_upkeep_needs(population=home_pop)

        inf_sources_hud = self._collect_influence_sources(s)
        h_scores = self._influence_scores_at(inf_sources_hud, int(home.pos_x), int(home.pos_y), 0)
        h_control_rows = (
            s.execute(
                select(InfluenceCell).where(
                    InfluenceCell.x == int(home.pos_x),
                    InfluenceCell.y == int(home.pos_y),
                    InfluenceCell.z == 0,
                    InfluenceCell.control_value > 0,
                )
            )
            .scalars()
            .all()
        )
        h_control_scores = {r.player_id: float(r.control_value) for r in h_control_rows}
        h_inf_ids = set(h_scores.keys()) | set(h_control_scores.keys())
        h_inf_owners: dict[str, str] = {}
        if h_inf_ids:
            h_inf_owners = {
                str(p.id): p.display_name
                for p in s.execute(select(Player).where(Player.id.in_(list(h_inf_ids)))).scalars().all()
            }
        home_influence = self._influence_cell_payload(h_scores, pid, h_inf_owners, h_control_scores)

        energy_ticks_left = None
        if upkeep_energy > 0:
            energy_ticks_left = energy // upkeep_energy

        recent_events = (
            s.execute(select(Event).where(Event.player_id == pid).order_by(Event.id.desc()).limit(25)).scalars().all()
        )
        events_payload = []
        for e in reversed(recent_events):
            pl: dict | None = None
            if e.payload_json:
                try:
                    pl = json.loads(e.payload_json)
                except Exception:
                    pl = None
            events_payload.append(
                {
                    "id": e.id,
                    "tick": e.tick,
                    "type": e.type,
                    "message": e.message,
                    "created_at": e.created_at.isoformat(),
                    "payload": pl,
                }
            )

        return {
            "current_tick": ws.current_tick,
            "current_sol": int(ws.current_tick),
            "player_id": str(pid),
            "auto_tick_enabled": auto_tick_enabled,
            "auto_tick_interval_seconds": auto_tick_interval_seconds,
            "fleet": fleet_payload,
            "fleets": fleets_payload,
            "events": events_payload,
            "home_planet": {
                "population": home_pop,
                "max_population": home_mx,
                "pos": {"x": home.pos_x, "y": home.pos_y},
            },
            "economy": {
                "metal": metal,
                "crystal": crystal,
                "energy": energy,
                "fuel": fuel,
                "food": food,
                "water": water,
                "production_per_tick": {
                    "metal": prod_per_tick["metal"],
                    "crystal": prod_per_tick["crystal"],
                    "energy": prod_per_tick["energy"],
                    "fuel": prod_per_tick["fuel"],
                    "food": prod_per_tick["food"],
                    "water": prod_per_tick["water"],
                },
                "avg_10_ticks": {
                    "metal": prod_per_tick["metal"],
                    "crystal": prod_per_tick["crystal"],
                    "energy": max(0, prod_per_tick["energy"] - upkeep_energy),
                    "fuel": prod_per_tick["fuel"],
                    "food": max(0, prod_per_tick["food"] - pop_food_need),
                    "water": max(0, prod_per_tick["water"] - pop_water_need),
                },
                "population_vitals_per_sol": {"food": pop_food_need, "water": pop_water_need},
                "upkeep_energy_per_tick": upkeep_energy,
                "fleet_units": fleet_units,
                "energy_ticks_left": energy_ticks_left,
                "influence": {
                    "home_share": home_influence["your_share"],
                    "home_contested": home_influence["contested"],
                    "home_dominant_id": home_influence["dominant"],
                    "home_dominant_name": home_influence["dominant_name"],
                    "home_total_score": home_influence["total_score"],
                    "home_control_owner": home_influence["control"]["owner"],
                    "home_control_owner_name": home_influence["control"]["owner_name"],
                    "home_control_your_value": home_influence["control"]["your_value"],
                    "home_control_top_value": home_influence["control"]["top_value"],
                },
            },
            "pending_combat_prompts": self._pending_combat_prompts_payload(s, player_id=pid),
        }
