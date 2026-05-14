"""Нейтральные миры, колонизация, осада планет."""

from __future__ import annotations

import random
import string
import uuid

from datetime import datetime, timezone

from sqlalchemy import delete, func, or_, select

from app.hex_coords import hex_axial_neighbors, hex_distance
from app.services.world_service._deps import *  # noqa: F403
from app.services.world_service.constants import (
    CIVILIAN_NPC_PLAYER_ID,
    NPC_FLEET_PLAYER_IDS,
    WORLD_NEUTRAL_PLAYER_ID,
)


class WorldServiceMixin08:
    def _neutral_planet_economy_cfg(self, s: Session | None) -> dict:
        eco = self._merged_pack_economy(s) if s is not None else {}
        if not isinstance(eco, dict):
            eco = {}
        blk = eco.get("neutral_planets")
        return blk if isinstance(blk, dict) else {}

    def _planet_siege_cfg(self, s: Session | None) -> dict:
        eco = self._merged_pack_economy(s) if s is not None else {}
        if not isinstance(eco, dict):
            eco = {}
        blk = eco.get("planet_siege")
        return blk if isinstance(blk, dict) else {}

    def _player_done_tech_ids(self, s: Session, *, player_id: uuid.UUID) -> set[str]:
        rows = (
            s.execute(
                select(PlayerTech.tech_id).where(
                    PlayerTech.player_id == player_id,
                    PlayerTech.status == "done",
                )
            )
            .scalars()
            .all()
        )
        return {str(x) for x in rows if x}

    def _player_satisfies_tech_ids(
        self, s: Session, *, player_id: uuid.UUID, tech_ids: list[str]
    ) -> bool:
        if not tech_ids:
            return True
        done = self._player_done_tech_ids(s, player_id=player_id)
        return all(str(tid) in done for tid in tech_ids if tid)

    def _player_max_completed_tech_tier(
        self, s: Session, *, player_id: uuid.UUID
    ) -> int:
        if not self._balance:
            return 0
        mx = 0
        for tid in self._player_done_tech_ids(s, player_id=player_id):
            t = self._balance.pack.tech_by_id.get(tid)
            if isinstance(t, dict) and isinstance(t.get("tier"), (int, float)):
                mx = max(mx, int(t["tier"]))
        return mx

    def _try_spawn_neutral_planets(self, s: Session, *, tick: int) -> None:
        self._ensure_world_neutral_player(s)
        cfg = self._neutral_planet_economy_cfg(s)
        target = max(0, int(cfg.get("target_count", 18) or 18))
        per_tick = max(1, int(cfg.get("spawn_per_tick_max", 4) or 4))
        dmin = max(1, int(cfg.get("spawn_min_hex_to_nearest", 20) or 20))
        dmax = max(dmin, int(cfg.get("spawn_max_hex_to_nearest", 40) or 40))
        bounds = max(50, int(cfg.get("bounds_half", 220) or 220))

        cur = int(
            s.execute(
                select(func.count(Planet.id)).where(
                    Planet.owner_player_id == WORLD_NEUTRAL_PLAYER_ID
                )
            ).scalar()
            or 0
        )
        if cur >= target:
            return
        if not s.execute(select(Planet.id).limit(1)).first():
            return

        existing = s.execute(select(Planet.pos_x, Planet.pos_y)).all()
        occupied = {(int(x), int(y)) for x, y in existing}

        def nearest_dist(qx: int, qy: int) -> int:
            return min(hex_distance(qx, qy, int(px), int(py)) for px, py in existing)

        classes = ["earthlike", "desert", "oceanic", "volcanic"]
        spawned = 0
        attempts_budget = 400
        while spawned < per_tick and cur + spawned < target and attempts_budget > 0:
            attempts_budget -= 1
            qx = random.randint(-bounds, bounds)
            qy = random.randint(-bounds, bounds)
            if (qx, qy) in occupied:
                continue
            d = nearest_dist(qx, qy)
            if not (dmin <= d <= dmax):
                continue
            pcl = random.choice(classes)
            slots = 50
            mxpop = 5000
            if self._balance:
                try:
                    pt = self._balance.get_planet_type(pcl)
                    sm = float(pt.get("build_slots_multiplier", 1.0) or 1.0)
                    mm = float(pt.get("max_population_multiplier", 1.0) or 1.0)
                    slots = max(20, min(80, int(round(55 * sm))))
                    mxpop = max(2000, min(12000, int(round(5000 * mm))))
                except Exception:
                    pass
            nm = (
                "".join(random.choice(string.ascii_uppercase) for _ in range(3))
                + "-"
                + "".join(random.choice(string.digits) for _ in range(3))
            )
            p = Planet(
                owner_player_id=WORLD_NEUTRAL_PLAYER_ID,
                name=nm,
                pos_x=qx,
                pos_y=qy,
                population=0,
                max_population=mxpop,
                planet_class=pcl,
                build_slots_total=slots,
                is_capital=False,
                is_colonized=False,
                conquest_penalty_until_tick=0,
            )
            s.add(p)
            s.flush()
            existing.append((qx, qy))
            occupied.add((qx, qy))
            spawned += 1

    def colonize_planet(
        self,
        s: Session,
        *,
        player_id: str,
        planet_id: str,
        fleet_id: str,
    ) -> dict:
        if not self._balance:
            return {"ok": False, "error": "balance_unavailable"}
        pid = uuid.UUID(player_id)
        try:
            plid = uuid.UUID(planet_id)
            flid = uuid.UUID(fleet_id)
        except Exception:
            return {"ok": False, "error": "invalid_uuid"}

        planet = s.get(Planet, plid)
        if not planet:
            return {"ok": False, "error": "planet_not_found"}
        if planet.owner_player_id != WORLD_NEUTRAL_PLAYER_ID:
            return {"ok": False, "error": "not_neutral_planet"}
        if bool(getattr(planet, "is_colonized", True)):
            return {"ok": False, "error": "already_colonized"}

        fleet = s.get(Fleet, flid)
        if not fleet or fleet.owner_player_id != pid:
            return {"ok": False, "error": "fleet_not_found"}
        if int(fleet.pos_z) != 0:
            return {"ok": False, "error": "z_not_supported_yet"}
        fx, fy = int(fleet.pos_x), int(fleet.pos_y)
        px, py = int(planet.pos_x), int(planet.pos_y)
        # Колонизация с клетки планеты или с любой из 6 соседних (гекс), чтобы флот не обязан стоять «под» пиктограммой мира.
        if hex_distance(fx, fy, px, py) > 1:
            return {"ok": False, "error": "fleet_not_adjacent_to_planet"}

        um = self._fleet_units_map(s, fleet)
        colon = 0
        for ut, q in um.items():
            try:
                udef = self._balance.get_unit(str(ut))
            except Exception:
                continue
            flags = udef.get("flags") if isinstance(udef.get("flags"), list) else []
            if "colonize_planet" in flags:
                colon += int(q)
        if colon <= 0:
            return {"ok": False, "error": "no_colonizer_in_fleet"}

        ptype = self._balance.get_planet_type(str(planet.planet_class or "earthlike"))
        need_tier = int(ptype.get("colonize_min_tech_tier", 1) or 1)
        if self._player_max_completed_tech_tier(s, player_id=pid) < need_tier:
            return {
                "ok": False,
                "error": "tech_tier_too_low",
                "need_tier": need_tier,
            }
        req = ptype.get("colonize_required_tech_ids")
        req_list = [str(x) for x in req] if isinstance(req, list) else []
        if not self._player_satisfies_tech_ids(
            s, player_id=pid, tech_ids=req_list
        ):
            return {"ok": False, "error": "tech_required", "required_techs": req_list}

        cap = self._capital_planet_for_player(s, player_id=pid)
        if not cap:
            return {"ok": False, "error": "no_capital_planet"}
        res = s.execute(
            select(Resource).where(Resource.planet_id == cap.id)
        ).scalar_one_or_none()
        if not res:
            return {"ok": False, "error": "no_resources"}

        cost_m, cost_c = 300, 200
        if int(res.metal) < cost_m or int(res.crystal) < cost_c:
            return {
                "ok": False,
                "error": "not_enough_resources",
                "need": {"metal": cost_m, "crystal": cost_c},
            }

        res.metal -= cost_m
        res.crystal -= cost_c

        new_um = dict(um)
        used = False
        for ut in list(new_um.keys()):
            try:
                udef = self._balance.get_unit(str(ut))
            except Exception:
                continue
            flags = udef.get("flags") if isinstance(udef.get("flags"), list) else []
            if "colonize_planet" in flags and int(new_um.get(ut, 0) or 0) > 0:
                new_um[ut] = int(new_um[ut]) - 1
                used = True
                break
        if not used:
            return {"ok": False, "error": "no_colonizer_in_fleet"}
        self._write_fleet_units(s, fleet, new_um)

        starter = int(ptype.get("starter_population", 500) or 500)
        col_rm = self._race_modifiers(s, player_id=pid)
        if col_rm.get("no_passive_population_growth"):
            colony_pop = 0
        else:
            colony_pop = max(50, starter)
        planet.owner_player_id = pid
        planet.is_colonized = True
        planet.is_capital = False
        planet.population = colony_pop
        planet.conquest_penalty_until_tick = 0
        s.add(
            Resource(
                planet_id=planet.id,
                metal=200,
                crystal=120,
                energy=80,
                fuel=60,
                food=80,
                water=80,
            )
        )
        s.add(
            ResourceTick(
                planet_id=planet.id, last_collected_at=datetime.now(timezone.utc)
            )
        )
        s.flush()
        return {"ok": True, "planet_id": str(planet.id)}

    def _apply_planet_siege_tick(self, s: Session, *, tick: int) -> None:
        cfg = self._planet_siege_cfg(s)
        frac = float(cfg.get("population_surrender_fraction", 0.1) or 0.1)
        pen_sols = max(1, int(cfg.get("conquest_penalty_sols", 100) or 100))

        planets = (
            s.execute(
                select(Planet).where(
                    Planet.is_colonized == True,  # noqa: E712
                    Planet.is_capital == False,  # noqa: E712
                    Planet.owner_player_id != WORLD_NEUTRAL_PLAYER_ID,
                )
            )
            .scalars()
            .all()
        )
        if not planets:
            return

        fleets = s.execute(select(Fleet).where(Fleet.qty > 0)).scalars().all()
        by_cell: dict[tuple[int, int, int], list[Fleet]] = {}
        for f in fleets:
            k = (int(f.pos_x), int(f.pos_y), int(f.pos_z))
            by_cell.setdefault(k, []).append(f)

        for pl in planets:
            defender = pl.owner_player_id
            px, py = int(pl.pos_x), int(pl.pos_y)
            neigh = hex_axial_neighbors(px, py)
            attackers: list[Fleet] = []
            for nx, ny in neigh:
                for f in by_cell.get((nx, ny, 0), []):
                    if f.owner_player_id == defender:
                        continue
                    if f.owner_player_id in NPC_FLEET_PLAYER_IDS:
                        continue
                    if f.owner_player_id == CIVILIAN_NPC_PLAYER_ID:
                        continue
                    attackers.append(f)
            if not attackers:
                continue

            att_fleet = max(
                attackers,
                key=lambda f: float(
                    self._fleet_combat_score(
                        s, fleet=f, player_id=f.owner_player_id
                    )
                    or 0.0
                ),
            )
            att_pid = att_fleet.owner_player_id

            def_b = None
            def_hp = 0
            intercept = 0.0
            for b in (
                s.execute(
                    select(Building).where(
                        Building.owner_player_id == defender,
                        Building.x == px,
                        Building.y == py,
                        Building.z == 0,
                        or_(Building.ready_at_tick == 0, Building.ready_at_tick <= int(tick)),
                    )
                )
                .scalars()
                .all()
            ):
                try:
                    bd = self._balance.get_building(b.building_type) if self._balance else {}
                except Exception:
                    bd = {}
                eff = bd.get("effects") if isinstance(bd, dict) else {}
                pd = eff.get("planetary_defense") if isinstance(eff, dict) else None
                if isinstance(pd, dict):
                    def_b = b
                    mx = int(pd.get("max_hp", 5000) or 5000)
                    cur = int(getattr(b, "structure_hp", 0) or 0)
                    if cur <= 0:
                        cur = mx
                        b.structure_hp = cur
                    def_hp = cur
                    intercept = float(pd.get("intercept_pop_damage_fraction", 0.9) or 0.0)
                    intercept = max(0.0, min(0.99, intercept))
                    break

            strike_frac = 0.06
            for b in (
                s.execute(
                    select(Building).where(
                        Building.owner_player_id == defender,
                        Building.x == px,
                        Building.y == py,
                        Building.z == 0,
                        or_(Building.ready_at_tick == 0, Building.ready_at_tick <= int(tick)),
                    )
                )
                .scalars()
                .all()
            ):
                try:
                    bd = self._balance.get_building(b.building_type) if self._balance else {}
                except Exception:
                    bd = {}
                eff = bd.get("effects") if isinstance(bd, dict) else {}
                os_ = eff.get("orbital_strike") if isinstance(eff, dict) else None
                if isinstance(os_, dict):
                    strike_frac = float(os_.get("fleet_damage_fraction_per_sol", 0.06) or 0.06)
                    break

            if strike_frac > 0:
                self._apply_fleet_post_combat_losses(
                    s,
                    att_fleet,
                    fraction=min(0.35, strike_frac),
                    allow_eliminate_fleet=True,
                )
                att_fleet = s.get(Fleet, att_fleet.id)
                if not att_fleet or int(att_fleet.qty or 0) <= 0:
                    continue

            score = float(
                self._fleet_combat_score(
                    s, fleet=att_fleet, player_id=att_fleet.owner_player_id
                )
                or 0.0
            )
            raw_damage = max(0, int(score // 2))
            pop_damage = raw_damage
            if def_b is not None and def_hp > 0 and intercept > 0:
                to_def = int(round(raw_damage * intercept))
                new_hp = def_hp - to_def
                pop_damage = max(0, raw_damage - to_def)
                if new_hp <= 0:
                    s.delete(def_b)
                else:
                    def_b.structure_hp = new_hp

            pop = int(getattr(pl, "population", 0) or 0)
            mxp = max(1, int(getattr(pl, "max_population", 5000) or 5000))
            pl.population = max(0, pop - pop_damage)
            if pl.population < int(frac * mxp):
                ptype = (
                    self._balance.get_planet_type(str(pl.planet_class or "earthlike"))
                    if self._balance
                    else {}
                )
                cap_req = ptype.get("capture_required_tech_ids")
                cap_list = [str(x) for x in cap_req] if isinstance(cap_req, list) else []
                if self._player_satisfies_tech_ids(
                    s, player_id=att_pid, tech_ids=cap_list
                ):
                    pl.owner_player_id = att_pid
                    pl.conquest_penalty_until_tick = int(tick) + pen_sols
                    for surf_b in (
                        s.execute(
                            select(Building).where(
                                Building.x == px,
                                Building.y == py,
                                Building.z == 0,
                                Building.owner_player_id == defender,
                                or_(
                                    Building.ready_at_tick == 0,
                                    Building.ready_at_tick <= int(tick),
                                ),
                            )
                        )
                        .scalars()
                        .all()
                    ):
                        surf_b.owner_player_id = att_pid
                else:
                    pl.population = max(1, int(frac * mxp))
