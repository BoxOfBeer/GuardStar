"""Фрагмент WorldService: инициализация, аутпосты, снабжение, старт игрока."""

from __future__ import annotations

from app.services.world_service._deps import *  # noqa: F403
from app.services.world_service.constants import (
    BANDIT_PLAYER_ID,
    CIVILIAN_NPC_PLAYER_ID,
    FLEET_ENERGY_MAX_ABS_CAP,
    FLEET_ENERGY_MAX_FLOOR,
    FLEET_ENERGY_MAX_UPKEEP_MULT,
    INFLUENCE_BASE_RADIUS,
    INFLUENCE_BUILDING_TYPES,
    INFLUENCE_CAPTURE_THRESHOLD,
    INFLUENCE_CONTEST_RATIO,
    INFLUENCE_CONTROL_VALUE_CAP,
    INFLUENCE_MIN_DOMINANT_SCORE,
    INFLUENCE_NATURAL_DECAY_PER_TICK,
    INFLUENCE_RADIUS_BUILDING,
    INFLUENCE_RADIUS_COLONY,
    INFLUENCE_WEIGHT_BUILDING,
    INFLUENCE_WEIGHT_COLONY,
    NPC_FLEET_PLAYER_IDS,
    PLANET_STORE_KEYS,
)


class WorldServiceMixin01:
    def _get_building_bonus_for_player(
        self, s: Session, *, player_id: uuid.UUID
    ) -> dict:
        rows = s.execute(
            select(Building.building_type, func.count(Building.id))
            .where(Building.owner_player_id == player_id)
            .group_by(Building.building_type)
        ).all()
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

    def __init__(
        self, *, world_seed: str = "guardstar", balance: object | None = None
    ) -> None:
        self._world_seed = world_seed or "guardstar"
        # BalanceService (DI). Не зависит от Flask context.
        self._balance = balance
        self._supply = SupplyService(balance=balance)
        self._outposts = OutpostService(
            balance=balance,
            supply=self._supply,
            emit_event=self._emit_event,
            outpost_definition=self._outpost_definition,
            cell_is_owned_planet_tile=self._cell_is_owned_planet_tile,
        )

    def _get_player_race_id(self, s: Session, *, player_id: uuid.UUID) -> str | None:
        _p = s.execute(
            select(Player).where(Player.id == player_id)
        ).scalar_one_or_none()
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
                "influence_multiplier": 1.0,
                "supply_route_upkeep_multiplier": 1.0,
                "fleet_unsupplied_energy_decay_multiplier": 1.0,
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
        prod_mul = (
            mods.get("production_multiplier")
            if isinstance(mods.get("production_multiplier"), dict)
            else {}
        )
        return {
            "build_time_multiplier": float(mods.get("build_time_multiplier", 1.0)),
            "upkeep_energy_multiplier": float(
                mods.get("upkeep_energy_multiplier", 1.0)
            ),
            "travel_fuel_multiplier": float(mods.get("travel_fuel_multiplier", 1.0)),
            "influence_multiplier": float(
                mods.get(
                    "influence_multiplier",
                    mods.get("influence_strength_multiplier", 1.0),
                )
            ),
            "supply_route_upkeep_multiplier": float(
                mods.get("supply_route_upkeep_multiplier", 1.0)
            ),
            "fleet_unsupplied_energy_decay_multiplier": float(
                mods.get("fleet_unsupplied_energy_decay_multiplier", 1.0)
            ),
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

    def _tech_production_multipliers(
        self, s: Session, *, player_id: uuid.UUID
    ) -> dict[str, float]:
        out = {k: 1.0 for k in PLANET_STORE_KEYS}
        if not self._balance:
            return out
        for tid in self._get_player_done_techs(s, player_id=player_id):
            t = self._balance.pack.tech_by_id.get(tid)
            if not isinstance(t, dict):
                continue
            eff = t.get("effects") if isinstance(t.get("effects"), dict) else {}
            pm = (
                eff.get("production_multiplier")
                if isinstance(eff.get("production_multiplier"), dict)
                else {}
            )
            for k in PLANET_STORE_KEYS:
                if isinstance(pm.get(k), (int, float)):
                    out[k] *= float(pm[k])
        return out

    def _building_influence_profile(
        self, building_type: str
    ) -> tuple[float, int] | None:
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
        rows = (
            s.execute(select(FleetShip).where(FleetShip.fleet_id == fleet.id))
            .scalars()
            .all()
        )
        pos = {r.unit_type: int(r.qty) for r in rows if int(r.qty) > 0}
        tot_rows = sum(pos.values())
        fq = int(fleet.qty) if fleet.qty else 0
        # Если строки fleet_ships неполные, а legacy qty больше — добиваем «невидимых»
        # кораблей в доминантный тип (частая причина пропажи скаута после полевой стройки).
        if pos and fleet.unit_type and fq > tot_rows:
            ut = str(fleet.unit_type)
            pos[ut] = int(pos.get(ut, 0)) + (fq - tot_rows)
        if pos:
            return pos
        if fq > 0 and fleet.unit_type:
            return {str(fleet.unit_type): fq}
        return {}

    def _cell_has_planet(self, s: Session, *, x: int, y: int, z: int) -> bool:
        if int(z) != 0:
            return False
        row = s.execute(
            select(Planet.id).where(Planet.pos_x == int(x), Planet.pos_y == int(y))
        ).first()
        return bool(row)

    def _write_fleet_units(
        self, s: Session, fleet: Fleet, units: dict[str, int]
    ) -> None:
        s.execute(delete(FleetShip).where(FleetShip.fleet_id == fleet.id))
        pos = {str(k): int(v) for k, v in units.items() if int(v) > 0}
        tot = sum(pos.values())
        if tot <= 0:
            fid = fleet.id
            pid_ev = fleet.owner_player_id
            s.delete(fleet)
            s.flush()
            ws = self.get_or_create_world_state(s)
            self._emit_event(
                s,
                tick=ws.current_tick,
                type="fleet_disbanded",
                message="Флот расформирован (0 кораблей)",
                payload={"fleet_id": str(fid), "reason": "empty_composition"},
                player_id=str(pid_ev),
            )
            return
        for ut, q in pos.items():
            s.add(FleetShip(fleet_id=fleet.id, unit_type=ut, qty=int(q)))
        fleet.qty = tot
        fleet.unit_type = max(pos.items(), key=lambda kv: (kv[1], kv[0]))[0]
        self._sync_fleet_energy_scale(s, fleet)

    def _sync_fleet_ships_from_legacy(self, s: Session, fleet: Fleet) -> None:
        if fleet.qty <= 0:
            return
        rows = (
            s.execute(select(FleetShip).where(FleetShip.fleet_id == fleet.id))
            .scalars()
            .all()
        )
        if rows:
            tot = sum(int(r.qty) for r in rows)
            if tot <= 0 and int(fleet.qty) > 0 and fleet.unit_type:
                s.execute(delete(FleetShip).where(FleetShip.fleet_id == fleet.id))
                s.flush()
                s.add(
                    FleetShip(
                        fleet_id=fleet.id,
                        unit_type=str(fleet.unit_type),
                        qty=int(fleet.qty),
                    )
                )
                return
            fleet.qty = tot
            dominant = max(
                ((r.unit_type, int(r.qty)) for r in rows), key=lambda x: (x[1], x[0])
            )[0]
            fleet.unit_type = str(dominant)
            return
        s.add(
            FleetShip(
                fleet_id=fleet.id, unit_type=str(fleet.unit_type), qty=int(fleet.qty)
            )
        )

    def _fleet_travel_ticks_for_distance(
        self, *, distance: int, units: dict[str, int]
    ) -> int:
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

    def _fleet_upkeep_energy_total(
        self, s: Session, *, player_id: uuid.UUID, units: dict[str, int]
    ) -> int:
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

    def _fleet_energy_max_for_units(
        self, s: Session, *, player_id: uuid.UUID, units: dict[str, int]
    ) -> int:
        """Потолок локальной энергии: несколько «клеток маршрута» по цене upkeep за клетку."""
        up = int(self._fleet_upkeep_energy_total(s, player_id=player_id, units=units or {}))
        up = max(1, up)
        m = up * FLEET_ENERGY_MAX_UPKEEP_MULT
        return min(FLEET_ENERGY_MAX_ABS_CAP, max(FLEET_ENERGY_MAX_FLOOR, m))

    def _sync_fleet_energy_scale(self, s: Session, fleet: Fleet) -> None:
        """Пересчитать max_energy и сохранить долю заряда при смене состава."""
        um = self._fleet_units_map(s, fleet)
        if not um:
            return
        new_mx = self._fleet_energy_max_for_units(
            s, player_id=fleet.owner_player_id, units=um
        )
        old_mx = int(getattr(fleet, "max_energy", FLEET_ENERGY_MAX_FLOOR) or FLEET_ENERGY_MAX_FLOOR)
        cur = int(getattr(fleet, "energy", 0) or 0)
        if new_mx != old_mx and old_mx > 0:
            cur = min(new_mx, int(round(cur * (new_mx / float(old_mx)))))
        else:
            cur = min(new_mx, cur)
        fleet.max_energy = new_mx
        fleet.energy = max(0, min(new_mx, cur))

    def _resolve_owning_planet_for_build_site(
        self, s: Session, *, owner_id: uuid.UUID, x: int, y: int, z: int
    ) -> Planet | None:
        if z != 0:
            return None
        mine = (
            s.execute(select(Planet).where(Planet.owner_player_id == owner_id))
            .scalars()
            .all()
        )
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
                "build": {
                    "cost": {"metal": 220, "crystal": 120, "fuel": 10},
                    "time_ticks": 5,
                    "prereq_tech": [],
                },
                "territory": {"influence_strength": 0.4, "influence_radius": 14},
                "vision": {"base_radius": 6},
                "combat": {"hp": 420, "attack": 8, "defense": 10, "range": 5},
                "slots": {"module_slots": 1},
                "upgrade": {
                    "to": "outpost_t2",
                    "cost": {"metal": 180, "crystal": 120, "fuel": 10},
                    "time_ticks": 6,
                },
            },
            "outpost_t2": {
                "id": "outpost_t2",
                "family": "outpost",
                "level": 2,
                "build": {
                    "cost": {"metal": 360, "crystal": 220, "fuel": 20},
                    "time_ticks": 7,
                    "prereq_tech": ["tech_territory_2"],
                },
                "territory": {"influence_strength": 0.7, "influence_radius": 17},
                "vision": {"base_radius": 7},
                "combat": {"hp": 650, "attack": 9, "defense": 12, "range": 5},
                "slots": {"module_slots": 2},
                "upgrade": {
                    "to": "outpost_t3",
                    "cost": {"metal": 260, "crystal": 180, "fuel": 15},
                    "time_ticks": 8,
                },
            },
            "outpost_t3": {
                "id": "outpost_t3",
                "family": "outpost",
                "level": 3,
                "build": {
                    "cost": {"metal": 520, "crystal": 360, "fuel": 35},
                    "time_ticks": 9,
                    "prereq_tech": ["tech_territory_3"],
                },
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

    def _outpost_module_rows(
        self, s: Session, *, outpost_id: uuid.UUID
    ) -> list[OutpostModule]:
        return (
            s.execute(
                select(OutpostModule)
                .where(OutpostModule.outpost_id == outpost_id)
                .order_by(OutpostModule.slot_idx.asc())
            )
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
        if int(
            getattr(outpost, "z", 0) or 0
        ) == 0 and not self._cell_is_owned_planet_tile(
            s, owner_id=outpost.owner_player_id, x=int(outpost.x), y=int(outpost.y), z=0
        ):
            if self._is_cell_supplied(
                s,
                owner_id=outpost.owner_player_id,
                x=int(outpost.x),
                y=int(outpost.y),
                z=int(outpost.z),
            ):
                hub_p = self._supply_hub_planet_for_cell(
                    s,
                    owner_id=outpost.owner_player_id,
                    x=int(outpost.x),
                    y=int(outpost.y),
                    z=int(outpost.z),
                )
                if hub_p is not None:
                    cf, cw = self._supply_route_logistics_costs(
                        hub=hub_p, ox=int(outpost.x), oy=int(outpost.y)
                    )
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
            "territory": {
                "influence_strength": territory_strength,
                "influence_radius": territory_radius,
            },
            "vision": {"radius": int(vision_radius)},
            "combat": {
                "hp": int(hp),
                "attack": int(attack),
                "defense": int(defense),
                "range": int(attack_range),
            },
            "slots": {"total": int(outpost.module_slots_total), "used": len(modules)},
            "modules": payload_modules,
            "upgrade": od.get("upgrade"),
            "name": od.get("name"),
            "supply_line": supply_line,
        }

    def _apply_outpost_combat_tick(self, s: Session, *, tick: int) -> None:
        outposts = (
            s.execute(select(Outpost).where(Outpost.status == "active")).scalars().all()
        )
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
                # Гражданский транзит не обстреливаем; корсары и прочие враждебные ИИ — в зоне досягаемости.
                if f.owner_player_id == CIVILIAN_NPC_PLAYER_ID:
                    continue
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
            tgt_id = target.id
            tgt_pid = target.owner_player_id
            tx, ty, tz = int(target.pos_x), int(target.pos_y), int(target.pos_z)

            score = float(
                self._fleet_combat_score(
                    s, fleet=target, player_id=target.owner_player_id
                )
                or 0
            )
            denom = max(35.0, score)
            frac = min(0.22, max(0.02, float(atk) / denom))
            self._apply_fleet_post_combat_losses(
                s, target, fraction=frac, allow_eliminate_fleet=True
            )

            survivor = s.get(Fleet, tgt_id)
            after = dict(self._fleet_units_map(s, survivor)) if survivor else {}
            cas = self._composition_casualties(before, after)
            lost = int(cas.get("lost_total", 0) or 0)
            wiped = survivor is None or sum(int(v) for v in after.values()) <= 0
            if lost <= 0 and not wiped:
                continue

            op_display = str(stats.get("name") or "").strip() or "Форпост"
            payload = {
                "outpost_id": str(op.id),
                "outpost_type": str(op.outpost_type),
                "pos": {"x": int(op.x), "y": int(op.y), "z": int(op.z)},
                "target_fleet_id": str(tgt_id),
                "range": rng,
                "attack": atk,
                "losses": cas,
                "fleet_destroyed": bool(wiped),
            }
            if tgt_pid in NPC_FLEET_PLAYER_IDS:
                msg = (
                    f"«{op_display}» ({int(op.x)},{int(op.y)}) уничтожил вражеский флот "
                    f"у ({tx},{ty},{tz})"
                    if wiped
                    else (
                        f"«{op_display}» ({int(op.x)},{int(op.y)}) обстрелял вражеский флот "
                        f"в ({tx},{ty},{tz})"
                    )
                )
                self._emit_event(
                    s,
                    tick=tick,
                    type="outpost_fire",
                    message=msg,
                    payload=payload,
                    player_id=op.owner_player_id,
                )
            else:
                self._emit_event(
                    s,
                    tick=tick,
                    type="outpost_fire",
                    message=(
                        f"Форпост уничтожил ваш флот у ({tx},{ty},{tz})"
                        if wiped
                        else f"Форпост обстрелял ваш флот в ({tx},{ty},{tz})"
                    ),
                    payload=payload,
                    player_id=tgt_pid,
                )

    def _effective_max_population(self, s: Session, planet: Planet) -> int:
        base = int(getattr(planet, "max_population", 5000) or 5000)
        add = 0
        rows = (
            s.execute(select(Building).where(Building.planet_id == planet.id))
            .scalars()
            .all()
        )
        if self._balance:
            for b in rows:
                bd = self._balance.get_building(b.building_type)
                eff = bd.get("effects") if isinstance(bd, dict) else {}
                if isinstance(eff, dict) and isinstance(
                    eff.get("max_population_add"), (int, float)
                ):
                    add += int(eff["max_population_add"])
        return max(0, base + add)

    def _next_fleet_default_name(self, s: Session, *, owner_id: uuid.UUID) -> str:
        n = s.execute(
            select(func.count(Fleet.id)).where(Fleet.owner_player_id == owner_id)
        ).scalar()
        return fleet_display_name_for_index(int(n or 0))

    def _fleet_public_name(self, fleet: Fleet) -> str:
        raw = str(getattr(fleet, "name", "") or "").strip()
        return raw if raw else "Флот"

    def _planet_slot_usage(self, s: Session, planet: Planet) -> dict:
        rows = s.execute(
            select(Building.building_type, func.count(Building.id))
            .where(Building.planet_id == planet.id)
            .group_by(Building.building_type)
        ).all()
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

    def _unit_required_techs(self, logical_alias: str) -> list[str]:
        if not self._balance:
            return []
        try:
            u = self._balance.get_unit(str(logical_alias).strip().lower())
        except Exception:
            return []
        req = u.get("prereq_tech") if isinstance(u, dict) else None
        if not isinstance(req, list):
            return []
        return [str(x) for x in req if isinstance(x, str) and x.strip()]

    # Фаза A снабжения: только счётчик на планете (не юнит на карте).
    SUPPLY_BASE_RADIUS = 5
    SUPPLY_PER_SUPPLIER = 3

    def _planet_supply_radius(self, s: Session, *, planet: Planet) -> int:
        r, _b, _ps = self._supply.planet_supply_radius(s, planet=planet)
        return int(r)

    @staticmethod
    def _manhattan_l_path_cells(
        px: int, py: int, tx: int, ty: int
    ) -> list[tuple[int, int]]:
        return SupplyService.manhattan_l_path_cells(px, py, tx, ty)

    def _supply_route_block_cell(
        self, s: Session, *, owner_id: uuid.UUID, path_cells: list[tuple[int, int]]
    ) -> tuple[int, int] | None:
        return self._supply.supply_route_block_cell(
            s, owner_id=owner_id, path_cells=path_cells
        )

    def _planet_supply_candidates(
        self, s: Session, *, owner_id: uuid.UUID, x: int, y: int
    ) -> list[tuple[Planet, int, int]]:
        # Back-compat wrapper: SupplyService возвращает расширенную структуру.
        rows = self._supply.planet_supply_candidates(
            s, owner_id=owner_id, x=int(x), y=int(y)
        )
        return [(p, int(r), int(d)) for (p, r, d, _b, _ps) in rows]

    def _supply_hub_planet_for_cell(
        self, s: Session, *, owner_id: uuid.UUID, x: int, y: int, z: int
    ) -> Planet | None:
        return self._supply.supply_hub_planet_for_cell(
            s, owner_id=owner_id, x=int(x), y=int(y), z=int(z)
        )

    def _cell_is_owned_planet_tile(
        self, s: Session, *, owner_id: uuid.UUID, x: int, y: int, z: int
    ) -> bool:
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

    def _supply_route_logistics_costs(
        self, *, hub: Planet, ox: int, oy: int
    ) -> tuple[int, int]:
        return self._outposts.supply_route_logistics_costs(
            hub=hub, ox=int(ox), oy=int(oy)
        )

    def _apply_supply_route_logistics_tick(self, s: Session, *, tick: int) -> None:
        return self._outposts.apply_supply_route_logistics_tick(s, tick=tick)

    def _apply_outpost_upkeep_tick(self, s: Session, *, tick: int) -> None:
        return self._outposts.apply_outpost_upkeep_tick(s, tick=tick)

    def get_supply_state(
        self, s: Session, *, player_id: str, x: int, y: int, z: int = 0
    ) -> dict:
        return self._supply.get_supply_state(
            s, player_id=player_id, x=int(x), y=int(y), z=int(z)
        )

    def hire_supplier(
        self, s: Session, *, player_id: str, planet_id: str | None = None
    ) -> dict:
        pid = uuid.UUID(player_id)
        planet: Planet | None = None
        if planet_id:
            try:
                plid = uuid.UUID(str(planet_id).strip())
            except Exception:
                return {"ok": False, "error": "invalid_planet_id"}
            planet = s.execute(
                select(Planet).where(Planet.id == plid, Planet.owner_player_id == pid)
            ).scalar_one_or_none()
        else:
            planet = s.execute(
                select(Planet)
                .where(Planet.owner_player_id == pid)
                .order_by(Planet.created_at.asc())
            ).scalar_one_or_none()
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
        res = s.execute(
            select(Resource).where(Resource.planet_id == planet.id)
        ).scalar_one_or_none()
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
            payload={
                "planet_id": str(planet.id),
                "supplier_count": int(planet.supplier_count),
            },
            player_id=pid,
        )
        self._emit_event(
            s,
            tick=tick,
            type="supply_radius_changed",
            message=f"Радиус снабжения увеличен до {after_r}",
            payload={
                "planet_id": str(planet.id),
                "radius_before": before_r,
                "radius_after": after_r,
            },
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

    def _is_cell_supplied(
        self, s: Session, *, owner_id: uuid.UUID, x: int, y: int, z: int
    ) -> bool:
        return self._supply.is_cell_supplied(
            s, owner_id=owner_id, x=int(x), y=int(y), z=int(z)
        )

    def _player_has_fleet_at_cell(
        self, s: Session, *, player_id: uuid.UUID, x: int, y: int, z: int
    ) -> bool:
        return (
            s.execute(
                select(Fleet.id).where(
                    Fleet.owner_player_id == player_id,
                    Fleet.pos_x == int(x),
                    Fleet.pos_y == int(y),
                    Fleet.pos_z == int(z),
                    Fleet.qty > 0,
                )
            ).first()
            is not None
        )

    def _fleet_skip_local_energy_upkeep(self, s: Session, fleet: Fleet) -> bool:
        """В хабе или в зоне снабжения не списываем «содержание» с локальной батареи за сол.

        Иначе upkeep (сумма по кораблям) каждый тик съедает больше, чем даёт реген в сети,
        и E залипает на нуле без приказа на движение.
        """
        oid = fleet.owner_player_id
        z = int(getattr(fleet, "pos_z", 0) or 0)
        x, y = int(fleet.pos_x), int(fleet.pos_y)
        if self._is_cell_supplied(s, owner_id=oid, x=x, y=y, z=z):
            return True
        if z == 0 and (
            s.execute(
                select(Planet.id).where(
                    Planet.owner_player_id == oid,
                    Planet.pos_x == x,
                    Planet.pos_y == y,
                )
            ).first()
        ):
            return True
        return (
            s.execute(
                select(Outpost.id).where(
                    Outpost.owner_player_id == oid,
                    Outpost.x == x,
                    Outpost.y == y,
                    Outpost.z == z,
                    Outpost.status == "active",
                )
            ).first()
            is not None
        )

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
        # MVP: пытаемся найти точку, которая минимум в N клетках по манхэттену от любой другой планеты.
        ws = self.get_or_create_world_state(s)
        min_dist = max(0, int(getattr(ws, "player_spawn_min_manhattan", 25) or 25))
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
        return (
            best
            if best
            else (random.randint(-bounds, bounds), random.randint(-bounds, bounds))
        )

    def ensure_player_has_start(self, s: Session, *, player_id: uuid.UUID) -> None:
        planet = s.execute(
            select(Planet).where(Planet.owner_player_id == player_id)
        ).scalar_one_or_none()
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
            population=600,
            max_population=max_pop,
            planet_class=planet_class,
            build_slots_total=slots_total,
        )
        s.add(planet)
        s.flush()

        s.add(
            Resource(
                planet_id=planet.id,
                metal=500,
                crystal=250,
                energy=100,
                fuel=100,
                food=120,
                water=120,
            )
        )
        # Стартовые корабли должны быть видимы на карте и "стоять вокруг" планеты:
        # - выше планеты: 1 fighter
        # - слева: 1 scout
        # - справа: 1 scout
        #
        # Сток на планете оставляем нулевым, чтобы движение не "печатало" новые корабли.
        s.add(
            Unit(
                owner_player_id=player_id, planet_id=planet.id, unit_type="scout", qty=0
            )
        )
        s.add(
            Unit(
                owner_player_id=player_id,
                planet_id=planet.id,
                unit_type="fighter",
                qty=0,
            )
        )

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
        for fleet in (
            s.execute(select(Fleet).where(Fleet.owner_player_id == player_id))
            .scalars()
            .all()
        ):
            self._sync_fleet_ships_from_legacy(s, fleet)
            self._sync_fleet_energy_scale(s, fleet)
        self._spawn_mvp_bandit_patrol_near(s, home_x=x, home_y=y)
        s.add(
            ResourceTick(
                planet_id=planet.id, last_collected_at=datetime.now(timezone.utc)
            )
        )
        # tick — мировая сущность, но старый GameClock оставляем как совместимость до миграции.
        self.get_or_create_world_state(s)
        self.get_or_create_clock(s)

