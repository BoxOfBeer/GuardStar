"""Фрагмент WorldService: сектор, карта, аутпосты и модули."""

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


class WorldServiceMixin03:
    def get_sector_stub(
        self,
        s: Session,
        *,
        x: int | None,
        y: int | None,
        z: int = 0,
        player_id: str | None,
    ) -> dict:
        sector = {"x": x, "y": y, "z": z, "objects": [], "cell": None}
        if not player_id:
            return sector

        if x is None or y is None:
            return sector

        sector["cell"] = self.get_cell_terrain(x=x, y=y, z=z)
        if (
            z == 0
            and s.execute(
                select(Planet.id).where(Planet.pos_x == x, Planet.pos_y == y)
            ).first()
        ):
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
            s.execute(
                select(Outpost).where(
                    Outpost.x == x,
                    Outpost.y == y,
                    Outpost.z == z,
                    Outpost.status == "active",
                )
            )
            .scalars()
            .all()
        )
        buildings_in_cell = (
            s.execute(
                select(Building).where(
                    Building.x == x, Building.y == y, Building.z == z
                )
            )
            .scalars()
            .all()
        )
        for f in fleets_in_cell:
            if not self._fleet_units_map(s, f):
                continue
            owner_ids.add(f.owner_player_id)
        for op in outposts_in_cell:
            owner_ids.add(op.owner_player_id)
        for b in buildings_in_cell:
            owner_ids.add(b.owner_player_id)
        owners = {}
        if owner_ids:
            owners = {
                str(p.id): p.display_name
                for p in s.execute(select(Player).where(Player.id.in_(list(owner_ids))))
                .scalars()
                .all()
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
                res = s.execute(
                    select(Resource).where(Resource.planet_id == p.id)
                ).scalar_one_or_none()
                units = (
                    s.execute(
                        select(Unit)
                        .where(Unit.planet_id == p.id)
                        .order_by(Unit.unit_type)
                    )
                    .scalars()
                    .all()
                )
                inf_src = self._collect_influence_sources(s)
                dlt = self._planet_production_deltas(
                    s, planet=p, influence_sources=inf_src
                )
                production = {
                    "metal_per_tick": dlt["metal"],
                    "crystal_per_tick": dlt["crystal"],
                    "energy_per_tick": dlt["energy"],
                    "fuel_per_tick": dlt["fuel"],
                    "food_per_tick": dlt["food"],
                    "water_per_tick": dlt["water"],
                    "metal_per_sol": dlt["metal"],
                    "crystal_per_sol": dlt["crystal"],
                    "energy_per_sol": dlt["energy"],
                    "fuel_per_sol": dlt["fuel"],
                    "food_per_sol": dlt["food"],
                    "water_per_sol": dlt["water"],
                }
                built_total = int(
                    s.execute(
                        select(func.count(Building.id)).where(
                            Building.planet_id == p.id
                        )
                    ).scalar()
                    or 0
                )
                built_surface = int(
                    self._surface_slot_buildings_count_for_planet(s, planet=p)
                )
                field_buildings = max(0, built_total - built_surface)
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
                    "planet_class": str(
                        getattr(p, "planet_class", "earthlike") or "earthlike"
                    ),
                    "build_slots": {
                        "used": built_surface,
                        "total": slots_total,
                        "field_buildings": field_buildings,
                        "planet_buildings_anywhere": built_total,
                    },
                    "supplier_count": int(getattr(p, "supplier_count", 0) or 0),
                    "supply_radius": int(sr),
                    "supply_base": self.SUPPLY_BASE_RADIUS,
                    "supply_per_supplier": self.SUPPLY_PER_SUPPLIER,
                    "units": [
                        {"unit_type": u.unit_type, "qty": int(u.qty)} for u in units
                    ],
                    "build": build,
                }
            sector["objects"].append(obj)

        for f in fleets_in_cell:
            comp = self._fleet_units_map(s, f)
            if not comp:
                continue
            sector["objects"].append(
                {
                    "type": "fleet",
                    "id": str(f.id),
                    "name": self._fleet_public_name(f),
                    "unit_type": f.unit_type,
                    "qty": int(sum(int(v) for v in comp.values())),
                    "composition": comp,
                    "energy": int(getattr(f, "energy", 0) or 0),
                    "max_energy": int(getattr(f, "max_energy", 100) or 100),
                    "owner": str(f.owner_player_id),
                    "owner_name": owners.get(str(f.owner_player_id)),
                }
            )
        for op in outposts_in_cell:
            st = self._outpost_stats(
                s,
                op,
                viewer_player_id=(
                    str(pid) if str(op.owner_player_id) == str(pid) else None
                ),
            )
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
        for b in buildings_in_cell:
            sector["objects"].append(
                {
                    "type": "building",
                    "id": str(b.id),
                    "owner": str(b.owner_player_id),
                    "owner_name": owners.get(str(b.owner_player_id)),
                    "building_type": str(getattr(b, "building_type", "") or ""),
                    "level": int(getattr(b, "level", 1) or 1),
                }
            )

        tk = sector.get("cell")
        tstr = tk.get("terrain", "") if isinstance(tk, dict) else str(tk or "")
        if (
            z == 0
            and s.execute(
                select(Planet.id).where(Planet.pos_x == x, Planet.pos_y == y)
            ).first()
        ):
            tstr = "planet"
        es_row = s.execute(
            select(ExploredSector).where(
                ExploredSector.player_id == pid,
                ExploredSector.x == int(x),
                ExploredSector.y == int(y),
                ExploredSector.z == int(z),
            )
        ).scalar_one_or_none()
        vis_here = self._cell_visible_to_player(
            s, player_id=pid, x=int(x), y=int(y), z=int(z)
        )
        elig = tstr in ("ruins", "anomaly")
        done_e = bool(es_row.discovery_done) if es_row else False
        fleet_here = self._player_has_fleet_at_cell(
            s, player_id=pid, x=int(x), y=int(y), z=int(z)
        )
        sector["discovery"] = {
            "terrain": tstr,
            "eligible": elig,
            "done": done_e,
            "visible_now": vis_here,
            "fleet_on_cell": fleet_here,
            "can_resolve": bool(elig and vis_here and not done_e and fleet_here),
        }
        return sector

    def get_player_map_window(
        self,
        s: Session,
        *,
        player_id: str,
        radius: int = 6,
        z: int = 0,
        center_x: int | None = None,
        center_y: int | None = None,
        reveal_fog: bool = False,
    ) -> dict:
        pid = uuid.UUID(player_id)

        planet = s.execute(
            select(Planet).where(Planet.owner_player_id == pid)
        ).scalar_one_or_none()
        if not planet:
            return {"center": None, "radius": radius, "z": z, "cells": []}

        cx, cy = (
            (center_x if center_x is not None else planet.pos_x),
            (center_y if center_y is not None else planet.pos_y),
        )
        x0, x1 = cx - radius, cx + radius
        y0, y1 = cy - radius, cy + radius

        planets = []
        if z == 0:
            planets = (
                s.execute(
                    select(Planet).where(
                        and_(
                            Planet.pos_x >= x0,
                            Planet.pos_x <= x1,
                            Planet.pos_y >= y0,
                            Planet.pos_y <= y1,
                        )
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
                {
                    "type": "planet",
                    "id": str(p.id),
                    "name": p.name,
                    "owner": str(p.owner_player_id),
                }
            )

        # Флоты в окне (для объектов, которые могут оказаться видимыми).
        fleets = (
            s.execute(
                select(Fleet).where(
                    Fleet.pos_z == z,
                    and_(
                        Fleet.pos_x >= x0,
                        Fleet.pos_x <= x1,
                        Fleet.pos_y >= y0,
                        Fleet.pos_y <= y1,
                    ),
                )
            )
            .scalars()
            .all()
        )
        for f in fleets:
            if self._fleet_units_map(s, f):
                owner_ids.add(f.owner_player_id)

        owners = {}
        if owner_ids:
            owners = {
                str(p.id): p.display_name
                for p in s.execute(select(Player).where(Player.id.in_(list(owner_ids))))
                .scalars()
                .all()
            }
        for f in fleets:
            comp = self._fleet_units_map(s, f)
            if not comp:
                continue
            by_pos.setdefault((f.pos_x, f.pos_y), []).append(
                {
                    "type": "fleet",
                    "id": str(f.id),
                    "name": self._fleet_public_name(f),
                    "unit_type": f.unit_type,
                    "qty": int(sum(int(v) for v in comp.values())),
                    "composition": comp,
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
                    and_(
                        Building.x >= x0,
                        Building.x <= x1,
                        Building.y >= y0,
                        Building.y <= y1,
                    ),
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
                for p in s.execute(select(Player).where(Player.id.in_(list(owner_ids))))
                .scalars()
                .all()
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
                    and_(
                        Outpost.x >= x0,
                        Outpost.x <= x1,
                        Outpost.y >= y0,
                        Outpost.y <= y1,
                    ),
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
                for p in s.execute(select(Player).where(Player.id.in_(list(owner_ids))))
                .scalars()
                .all()
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
                for p in s.execute(select(Player).where(Player.id.in_(list(owner_ids))))
                .scalars()
                .all()
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
                    and_(
                        InfluenceCell.x >= x0,
                        InfluenceCell.x <= x1,
                        InfluenceCell.y >= y0,
                        InfluenceCell.y <= y1,
                    ),
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
                    and_(
                        ExploredSector.x >= x0,
                        ExploredSector.x <= x1,
                        ExploredSector.y >= y0,
                        ExploredSector.y <= y1,
                    ),
                )
            )
            .scalars()
            .all()
        )
        explored_by_xy = {(e.x, e.y): e for e in explored_rows}

        def _touch_explored(x: int, y: int) -> None:
            e = explored_by_xy.get((x, y))
            if not e:
                e = ExploredSector(
                    player_id=pid,
                    x=x,
                    y=y,
                    z=z,
                    first_seen_tick=now_tick,
                    last_seen_tick=now_tick,
                )
                s.add(e)
                explored_by_xy[(x, y)] = e
                return
            e.last_seen_tick = now_tick

        # Снабжение для оценки опасности: раньше на каждую видимую клетку —
        # сотни запросов (планеты + каждая клетка L-пути). Один precalc на окно.
        supply_rows, enemy_supply_xy = self._supply.map_window_supply_precalc(
            s,
            owner_id=pid,
            x0=x0,
            x1=x1,
            y0=y0,
            y1=y1,
            z=z,
        )

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
                visible = True if reveal_fog else _is_visible(x, y)
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
                    tk_neb = str(
                        terrain.get("terrain", "")
                        if isinstance(terrain, dict)
                        else terrain or ""
                    )
                    if tk_neb == "nebula":
                        own_struct = any(
                            o
                            and str(o.get("owner")) == str(pid)
                            and o.get("type") in ("building", "outpost", "planet")
                            for o in objects
                        )
                        # На «своей» территории (радиус колоний) без своей постройки на клетке —
                        # чужой флот в туманности не виден вашим «радарам»; у чужого игрока свой флот он видит.
                        if not own_struct and (x, y) in build_self:
                            objects = [
                                o
                                for o in objects
                                if not (
                                    o
                                    and o.get("type") == "fleet"
                                    and str(o.get("owner")) != str(pid)
                                )
                            ]
                else:
                    # В тумане не показываем руины/астероиды и т.п.
                    # В stale оставляем только намёк на аномалию (серым вопросом).
                    objects = []
                    if fog_state == "stale":
                        terrain = {"terrain": "fog", "glyph": "?"}
                    else:
                        terrain = {"terrain": "fog", "glyph": ""}

                influence_payload = None
                danger_level = None
                danger_reasons: list[str] = []
                cell_tint: str | None = None
                ruins_surveyed_flag = False
                if visible:
                    inc_scores = self._influence_scores_at(inf_sources, x, y, z)
                    ctl_scores = control_by_xy.get((x, y), {})
                    influence_payload = self._influence_cell_payload(
                        inc_scores, pid, owners, ctl_scores
                    )
                    tk = str(
                        terrain.get("terrain", "")
                        if isinstance(terrain, dict)
                        else terrain or ""
                    )

                    # Командирская оценка опасности (эвристика).
                    enemy_fleet_here = any(
                        (
                            o
                            and o.get("type") == "fleet"
                            and str(o.get("owner")) != str(pid)
                            and int(o.get("qty") or 0) > 0
                        )
                        for o in (objects or [])
                    )
                    if enemy_fleet_here:
                        danger_reasons.append("enemy_fleet")
                    if tk == "anomaly":
                        danger_reasons.append("anomaly")
                    elif tk == "ruins":
                        danger_reasons.append("ruins")
                    if int(z) == 0:
                        supplied = self._supply.is_cell_supplied_from_precalc(
                            supply_rows,
                            enemy_supply_xy,
                            x=int(x),
                            y=int(y),
                            z=int(z),
                        )
                    else:
                        supplied = False
                    if not supplied:
                        danger_reasons.append("unsupplied")

                    # базовый уровень
                    if enemy_fleet_here:
                        danger_level = "high"
                    elif tk == "anomaly":
                        danger_level = "medium"
                    elif tk == "ruins":
                        danger_level = "low"
                    else:
                        danger_level = "low"

                    # вне снабжения повышаем на 1 ступень
                    if not supplied:
                        if danger_level == "low":
                            danger_level = "medium"
                        elif danger_level == "medium":
                            danger_level = "high"

                    ruins_surveyed = bool(
                        tk == "ruins"
                        and explored
                        and bool(getattr(explored, "discovery_done", False))
                    )
                    own_here = any(
                        o
                        and str(o.get("owner")) == str(pid)
                        and o.get("type") in ("building", "outpost", "planet", "fleet")
                        for o in objects
                    )
                    hostile_here = any(
                        o
                        and o.get("owner")
                        and str(o.get("owner")) != str(pid)
                        and o.get("type") in ("building", "outpost", "planet", "fleet")
                        for o in objects
                    )
                    if own_here:
                        cell_tint = "ally"
                    elif ruins_surveyed:
                        cell_tint = "ruins_surveyed"
                    elif hostile_here:
                        cell_tint = "hostile"
                    else:
                        cell_tint = "neutral"
                    ruins_surveyed_flag = ruins_surveyed

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
                            "danger_level": danger_level,
                            "danger_reasons": danger_reasons,
                            # зоны
                            "zone_vision_self": bool(visible),
                            "zone_build_self": bool((x, y) in build_self),
                            "zone_build_enemy": bool((x, y) in build_enemy),
                            "cell_tint": cell_tint,
                            "ruins_surveyed": ruins_surveyed_flag,
                        },
                    }
                )
            cells.append({"y": y, "row": row})

        s.flush()
        return {"center": {"x": cx, "y": cy}, "radius": radius, "z": z, "cells": cells}

    def check_outpost_placement(
        self,
        s: Session,
        *,
        player_id: str,
        x: int,
        y: int,
        z: int,
        outpost_type: str,
        fleet_id: str | None = None,
    ) -> dict:
        """Проверка постройки форпоста без изменения БД (для UI до `/api/outposts/build`)."""
        pid = uuid.UUID(player_id)
        otype = str(outpost_type or "").strip()
        try:
            od = self._outpost_definition(otype)
        except Exception:
            return {"ok": False, "error": "invalid_outpost_type"}

        vis = od.get("vision") if isinstance(od.get("vision"), dict) else {}
        min_dist = int(vis.get("base_radius", 6) or 6)
        if min_dist > 0:
            nearby = (
                s.execute(
                    select(Outpost).where(
                        Outpost.owner_player_id == pid,
                        Outpost.z == int(z),
                        Outpost.status.in_(["active", "offline"]),
                    )
                )
                .scalars()
                .all()
            )
            nearest = None
            nearest_op: Outpost | None = None
            for op in nearby:
                d = abs(int(op.x) - int(x)) + abs(int(op.y) - int(y))
                if nearest is None or d < nearest:
                    nearest = d
                    nearest_op = op
            if nearest is not None and int(nearest) < int(min_dist):
                return {
                    "ok": False,
                    "error": "outpost_too_close",
                    "need_distance": int(min_dist),
                    "nearest": int(nearest),
                    "nearest_outpost": (
                        {
                            "id": str(nearest_op.id),
                            "x": int(nearest_op.x),
                            "y": int(nearest_op.y),
                            "z": int(nearest_op.z),
                            "status": str(getattr(nearest_op, "status", "") or ""),
                            "outpost_type": str(
                                getattr(nearest_op, "outpost_type", "") or ""
                            ),
                        }
                        if nearest_op
                        else None
                    ),
                }

        gate = self._can_build_at(s, owner_id=pid, x=x, y=y, z=z, fleet_id=fleet_id)
        if not gate.get("ok"):
            return gate

        eng_fleet = self._owned_engineer_fleet_at(
            s, owner_id=pid, x=x, y=y, z=z, fleet_id=fleet_id
        )
        if not eng_fleet:
            return {"ok": False, "error": "engineer_required"}
        if int(self._fleet_units_map(s, eng_fleet).get("engineer", 0)) <= 0:
            return {"ok": False, "error": "not_enough_engineers", "need_engineers": 1}
        if (
            s.execute(
                select(Outpost.id).where(
                    Outpost.x == x,
                    Outpost.y == y,
                    Outpost.z == z,
                    Outpost.status == "active",
                )
            )
            .scalars()
            .first()
        ):
            return {"ok": False, "error": "cell_already_has_outpost"}
        if (
            s.execute(
                select(Building.id).where(
                    Building.x == x, Building.y == y, Building.z == z
                )
            )
            .scalars()
            .first()
        ):
            return {"ok": False, "error": "cell_already_built"}

        req_techs = self._outpost_required_techs(otype)
        if req_techs:
            done = set(self._get_player_done_techs(s, player_id=pid))
            missing = [tid for tid in req_techs if tid not in done]
            if missing:
                return {
                    "ok": False,
                    "error": "tech_required",
                    "required_techs": req_techs,
                    "missing_techs": missing,
                }

        home = s.execute(
            select(Planet)
            .where(Planet.owner_player_id == pid)
            .order_by(Planet.created_at.asc())
        ).scalar_one_or_none()
        if not home:
            return {"ok": False, "error": "no_home_planet"}
        res = s.execute(
            select(Resource).where(Resource.planet_id == home.id)
        ).scalar_one_or_none()
        if not res:
            return {"ok": False, "error": "no_resources"}
        cost = (od.get("build") if isinstance(od.get("build"), dict) else {}).get(
            "cost", {}
        )
        need = {k: int(cost.get(k, 0)) for k in ("metal", "crystal", "energy", "fuel")}
        have_res = {
            "metal": int(res.metal),
            "crystal": int(res.crystal),
            "energy": int(res.energy),
            "fuel": int(getattr(res, "fuel", 0)),
        }
        if (
            int(res.metal) < need["metal"]
            or int(res.crystal) < need["crystal"]
            or int(res.energy) < need["energy"]
            or int(getattr(res, "fuel", 0)) < need["fuel"]
        ):
            return {
                "ok": False,
                "error": "not_enough_resources",
                "need": need,
                "have": have_res,
            }

        return {"ok": True}

    def build_outpost(
        self,
        s: Session,
        *,
        player_id: str,
        x: int,
        y: int,
        z: int,
        outpost_type: str,
        fleet_id: str | None = None,
    ) -> dict:
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
                    select(Outpost).where(
                        Outpost.owner_player_id == pid,
                        Outpost.z == int(z),
                        Outpost.status.in_(["active", "offline"]),
                    )
                )
                .scalars()
                .all()
            )
            nearest = None
            nearest_op: Outpost | None = None
            for op in nearby:
                d = abs(int(op.x) - int(x)) + abs(int(op.y) - int(y))
                if nearest is None or d < nearest:
                    nearest = d
                    nearest_op = op
            if nearest is not None and int(nearest) < int(min_dist):
                return {
                    "ok": False,
                    "error": "outpost_too_close",
                    "need_distance": int(min_dist),
                    "nearest": int(nearest),
                    "nearest_outpost": (
                        {
                            "id": str(nearest_op.id),
                            "x": int(nearest_op.x),
                            "y": int(nearest_op.y),
                            "z": int(nearest_op.z),
                            "status": str(getattr(nearest_op, "status", "") or ""),
                            "outpost_type": str(
                                getattr(nearest_op, "outpost_type", "") or ""
                            ),
                        }
                        if nearest_op
                        else None
                    ),
                }

        gate = self._can_build_at(s, owner_id=pid, x=x, y=y, z=z, fleet_id=fleet_id)
        if not gate.get("ok"):
            return gate
        # Форпост всегда требует инженера (MVP-правило).
        eng_fleet = self._owned_engineer_fleet_at(
            s, owner_id=pid, x=x, y=y, z=z, fleet_id=fleet_id
        )
        if not eng_fleet:
            return {"ok": False, "error": "engineer_required"}
        if int(self._fleet_units_map(s, eng_fleet).get("engineer", 0)) <= 0:
            return {"ok": False, "error": "not_enough_engineers", "need_engineers": 1}
        if (
            s.execute(
                select(Outpost.id).where(
                    Outpost.x == x,
                    Outpost.y == y,
                    Outpost.z == z,
                    Outpost.status == "active",
                )
            )
            .scalars()
            .first()
        ):
            return {"ok": False, "error": "cell_already_has_outpost"}
        if (
            s.execute(
                select(Building.id).where(
                    Building.x == x, Building.y == y, Building.z == z
                )
            )
            .scalars()
            .first()
        ):
            return {"ok": False, "error": "cell_already_built"}

        req_techs = self._outpost_required_techs(otype)
        if req_techs:
            done = set(self._get_player_done_techs(s, player_id=pid))
            missing = [tid for tid in req_techs if tid not in done]
            if missing:
                return {
                    "ok": False,
                    "error": "tech_required",
                    "required_techs": req_techs,
                    "missing_techs": missing,
                }

        home = s.execute(
            select(Planet)
            .where(Planet.owner_player_id == pid)
            .order_by(Planet.created_at.asc())
        ).scalar_one_or_none()
        if not home:
            return {"ok": False, "error": "no_home_planet"}
        res = s.execute(
            select(Resource).where(Resource.planet_id == home.id)
        ).scalar_one_or_none()
        if not res:
            return {"ok": False, "error": "no_resources"}
        cost = (od.get("build") if isinstance(od.get("build"), dict) else {}).get(
            "cost", {}
        )
        need = {k: int(cost.get(k, 0)) for k in ("metal", "crystal", "energy", "fuel")}
        have_res = {
            "metal": int(res.metal),
            "crystal": int(res.crystal),
            "energy": int(res.energy),
            "fuel": int(getattr(res, "fuel", 0)),
        }
        if (
            int(res.metal) < need["metal"]
            or int(res.crystal) < need["crystal"]
            or int(res.energy) < need["energy"]
            or int(getattr(res, "fuel", 0)) < need["fuel"]
        ):
            return {
                "ok": False,
                "error": "not_enough_resources",
                "need": need,
                "have": have_res,
            }

        eng_map = self._fleet_units_map(s, eng_fleet)
        eng_map["engineer"] = max(0, int(eng_map.get("engineer", 0)) - 1)
        self._write_fleet_units(s, eng_fleet, eng_map)

        res.metal -= need["metal"]
        res.crystal -= need["crystal"]
        res.energy -= need["energy"]
        if hasattr(res, "fuel"):
            res.fuel = int(getattr(res, "fuel", 0)) - need["fuel"]

        anchor_planet = (
            self._resolve_owning_planet_for_build_site(s, owner_id=pid, x=x, y=y, z=z)
            or home
        )
        slots = (
            (od.get("slots") if isinstance(od.get("slots"), dict) else {}) or {}
        ).get("module_slots", 1)
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
        st_hp = self._outpost_stats(s, outpost, viewer_player_id=player_id)
        cmb = st_hp.get("combat") if isinstance(st_hp.get("combat"), dict) else {}
        outpost.hp_current = int(cmb.get("hp", 0) or 0) or None
        if str(pid) == str(BANDIT_PLAYER_ID):
            wc = self._warfare_economy(s)
            outpost.strike_next_tick = int(start_tick) + random.randint(
                int(wc["strike_min"]), int(wc["strike_max"])
            )
            outpost.patrol_respawn_at_tick = 0
            s.flush()
            bnpc = self._ensure_bandit_player(s)
            self._spawn_bandit_patrol_for_outpost(
                s,
                npc=bnpc,
                outpost=outpost,
                tick=start_tick,
                wc=wc,
                for_new_outpost=True,
            )
            s.flush()
        return {
            "ok": True,
            "outpost": {
                "id": str(outpost.id),
                **self._outpost_stats(s, outpost, viewer_player_id=player_id),
                "x": x,
                "y": y,
                "z": z,
            },
        }

    def upgrade_outpost(self, s: Session, *, player_id: str, outpost_id: str) -> dict:
        pid = uuid.UUID(player_id)
        try:
            oid = uuid.UUID(outpost_id)
        except Exception:
            return {"ok": False, "error": "invalid_outpost_id"}
        outpost = s.execute(
            select(Outpost).where(Outpost.id == oid, Outpost.owner_player_id == pid)
        ).scalar_one_or_none()
        if not outpost:
            return {"ok": False, "error": "outpost_not_found"}
        od = self._outpost_definition(outpost.outpost_type)
        upgrade = od.get("upgrade") if isinstance(od.get("upgrade"), dict) else None
        if not upgrade or not upgrade.get("to"):
            return {"ok": False, "error": "outpost_upgrade_unavailable"}
        req_techs = [
            str(x) for x in upgrade.get("prereq_tech", []) if isinstance(x, str)
        ]
        if req_techs:
            done = set(self._get_player_done_techs(s, player_id=pid))
            missing = [tid for tid in req_techs if tid not in done]
            if missing:
                return {
                    "ok": False,
                    "error": "tech_required",
                    "required_techs": req_techs,
                    "missing_techs": missing,
                }
        home = s.execute(
            select(Planet)
            .where(Planet.owner_player_id == pid)
            .order_by(Planet.created_at.asc())
        ).scalar_one_or_none()
        res = (
            s.execute(
                select(Resource).where(Resource.planet_id == home.id)
            ).scalar_one_or_none()
            if home
            else None
        )
        if not home or not res:
            return {"ok": False, "error": "no_resources"}
        cost = upgrade.get("cost") if isinstance(upgrade.get("cost"), dict) else {}
        need = {k: int(cost.get(k, 0)) for k in ("metal", "crystal", "energy", "fuel")}
        if (
            int(res.metal) < need["metal"]
            or int(res.crystal) < need["crystal"]
            or int(res.energy) < need["energy"]
            or int(getattr(res, "fuel", 0)) < need["fuel"]
        ):
            return {"ok": False, "error": "not_enough_resources", "need": need}
        st_old = self._outpost_stats(s, outpost, viewer_player_id=player_id)
        c_old = st_old.get("combat") if isinstance(st_old.get("combat"), dict) else {}
        old_max = int(c_old.get("hp", 0) or 0)
        old_hp_raw = getattr(outpost, "hp_current", None)
        old_hp_i = (
            int(old_hp_raw)
            if old_hp_raw is not None
            else (old_max if old_max > 0 else 0)
        )
        res.metal -= need["metal"]
        res.crystal -= need["crystal"]
        res.energy -= need["energy"]
        if hasattr(res, "fuel"):
            res.fuel = int(getattr(res, "fuel", 0)) - need["fuel"]
        outpost.outpost_type = str(upgrade["to"])
        newd = self._outpost_definition(outpost.outpost_type)
        outpost.level = int(newd.get("level", outpost.level))
        outpost.module_slots_total = int(
            (
                (newd.get("slots") if isinstance(newd.get("slots"), dict) else {}) or {}
            ).get("module_slots", outpost.module_slots_total)
        )
        outpost.updated_at = datetime.utcnow()
        s.flush()
        st_new = self._outpost_stats(s, outpost, viewer_player_id=player_id)
        c_new = st_new.get("combat") if isinstance(st_new.get("combat"), dict) else {}
        new_max = int(c_new.get("hp", 0) or old_max or 0)
        if new_max > 0:
            bonus = max(0, new_max - (old_max if old_max > 0 else new_max))
            outpost.hp_current = max(0, min(new_max, old_hp_i + bonus))
        s.flush()
        return {
            "ok": True,
            "outpost": {
                "id": str(outpost.id),
                **self._outpost_stats(s, outpost, viewer_player_id=player_id),
                "x": outpost.x,
                "y": outpost.y,
                "z": outpost.z,
            },
        }

    def install_outpost_module(
        self, s: Session, *, player_id: str, outpost_id: str, module_type: str
    ) -> dict:
        pid = uuid.UUID(player_id)
        try:
            oid = uuid.UUID(outpost_id)
        except Exception:
            return {"ok": False, "error": "invalid_outpost_id"}
        outpost = s.execute(
            select(Outpost).where(Outpost.id == oid, Outpost.owner_player_id == pid)
        ).scalar_one_or_none()
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
                return {
                    "ok": False,
                    "error": "tech_required",
                    "required_techs": req_techs,
                    "missing_techs": missing,
                }
        busy_other = (
            s.execute(
                select(OutpostModule.id)
                .join(Outpost, Outpost.id == OutpostModule.outpost_id)
                .where(
                    Outpost.owner_player_id == pid,
                    OutpostModule.status == "in_progress",
                )
                .limit(1)
            )
            .scalars()
            .first()
        )
        if busy_other:
            return {"ok": False, "error": "module_work_queue_full"}
        modules = self._outpost_module_rows(s, outpost_id=outpost.id)
        if len(modules) >= int(outpost.module_slots_total):
            return {"ok": False, "error": "outpost_slots_full"}
        used = {int(m.slot_idx) for m in modules}
        slot_idx = next(
            (i for i in range(int(outpost.module_slots_total)) if i not in used),
            len(used),
        )
        if int(slot_idx) >= int(outpost.module_slots_total):
            return {"ok": False, "error": "outpost_slots_full"}
        spend = max(1, int(slot_idx) + 1)
        eng_fleet = self._owned_engineer_fleet_at(
            s, owner_id=pid, x=int(outpost.x), y=int(outpost.y), z=int(outpost.z)
        )
        if not eng_fleet:
            return {"ok": False, "error": "engineer_required"}
        eng_map = self._fleet_units_map(s, eng_fleet)
        if int(eng_map.get("engineer", 0)) < spend:
            return {
                "ok": False,
                "error": "not_enough_engineers",
                "need_engineers": spend,
            }
        bld = md.get("build") if isinstance(md.get("build"), dict) else {}
        eng_map["engineer"] = max(0, int(eng_map.get("engineer", 0)) - spend)
        self._write_fleet_units(s, eng_fleet, eng_map)
        ws = self.get_or_create_world_state(s)
        start_tick = int(ws.current_tick)
        duration = int(bld.get("time_ticks", 3) or 3)
        duration = max(1, duration)
        finish_tick = start_tick + duration
        row = OutpostModule(
            outpost_id=outpost.id,
            module_type=module_type,
            pending_module_type=None,
            kind=str(md.get("kind") or "utility"),
            level=int(md.get("level", 1) or 1),
            slot_idx=int(slot_idx),
            status="in_progress",
            started_at_tick=start_tick,
            finish_tick=finish_tick,
            updated_at=datetime.utcnow(),
        )
        s.add(row)
        s.flush()
        return {
            "ok": True,
            "outpost": {
                "id": str(outpost.id),
                **self._outpost_stats(s, outpost, viewer_player_id=player_id),
                "x": outpost.x,
                "y": outpost.y,
                "z": outpost.z,
            },
        }

    def upgrade_outpost_module(
        self, s: Session, *, player_id: str, module_id: str
    ) -> dict:
        pid = uuid.UUID(player_id)
        try:
            mid = uuid.UUID(module_id)
        except Exception:
            return {"ok": False, "error": "invalid_module_id"}
        row = (
            s.execute(
                select(OutpostModule)
                .join(Outpost, Outpost.id == OutpostModule.outpost_id)
                .where(OutpostModule.id == mid, Outpost.owner_player_id == pid)
            )
            .scalars()
            .first()
        )
        if not row:
            return {"ok": False, "error": "module_not_found"}
        if str(row.status or "") != "active":
            return {"ok": False, "error": "module_busy"}
        md = self._outpost_module_definition(row.module_type)
        upgrade = md.get("upgrade") if isinstance(md.get("upgrade"), dict) else None
        if not upgrade or not upgrade.get("to"):
            return {"ok": False, "error": "module_upgrade_unavailable"}
        req_techs = [
            str(x) for x in upgrade.get("prereq_tech", []) if isinstance(x, str)
        ]
        if req_techs:
            done = set(self._get_player_done_techs(s, player_id=pid))
            missing = [tid for tid in req_techs if tid not in done]
            if missing:
                return {
                    "ok": False,
                    "error": "tech_required",
                    "required_techs": req_techs,
                    "missing_techs": missing,
                }
        busy_other = (
            s.execute(
                select(OutpostModule.id)
                .join(Outpost, Outpost.id == OutpostModule.outpost_id)
                .where(
                    Outpost.owner_player_id == pid,
                    OutpostModule.status == "in_progress",
                    OutpostModule.id != row.id,
                )
                .limit(1)
            )
            .scalars()
            .first()
        )
        if busy_other:
            return {"ok": False, "error": "module_work_queue_full"}
        outpost = s.get(Outpost, row.outpost_id)
        eng_fleet = (
            self._owned_engineer_fleet_at(
                s, owner_id=pid, x=int(outpost.x), y=int(outpost.y), z=int(outpost.z)
            )
            if outpost
            else None
        )
        if not eng_fleet:
            return {"ok": False, "error": "engineer_required"}
        eng_map = self._fleet_units_map(s, eng_fleet)
        spend = max(1, int(row.slot_idx) + 1)
        if int(eng_map.get("engineer", 0)) < spend:
            return {
                "ok": False,
                "error": "not_enough_engineers",
                "need_engineers": spend,
            }
        eng_map["engineer"] = max(0, int(eng_map.get("engineer", 0)) - spend)
        self._write_fleet_units(s, eng_fleet, eng_map)
        ws = self.get_or_create_world_state(s)
        start_tick = int(ws.current_tick)
        duration = int(upgrade.get("time_ticks", 4) or 4)
        duration = max(1, duration)
        row.pending_module_type = str(upgrade["to"])
        row.status = "in_progress"
        row.started_at_tick = start_tick
        row.finish_tick = start_tick + duration
        row.updated_at = datetime.utcnow()
        s.flush()
        return {
            "ok": True,
            "outpost": {
                "id": str(outpost.id),
                **self._outpost_stats(s, outpost, viewer_player_id=player_id),
                "x": outpost.x,
                "y": outpost.y,
                "z": outpost.z,
            },
        }

    def dismantle_outpost_module(
        self, s: Session, *, player_id: str, module_id: str
    ) -> dict:
        pid = uuid.UUID(player_id)
        try:
            mid = uuid.UUID(module_id)
        except Exception:
            return {"ok": False, "error": "invalid_module_id"}
        row = (
            s.execute(
                select(OutpostModule)
                .join(Outpost, Outpost.id == OutpostModule.outpost_id)
                .where(OutpostModule.id == mid, Outpost.owner_player_id == pid)
            )
            .scalars()
            .first()
        )
        if not row:
            return {"ok": False, "error": "module_not_found"}
        outpost = s.get(Outpost, row.outpost_id)
        if not outpost:
            return {"ok": False, "error": "outpost_not_found"}
        if str(row.status or "") != "active":
            return {"ok": False, "error": "module_busy"}
        refund = max(1, int(row.slot_idx) + 1)
        eng_fleet = self._owned_engineer_fleet_at(
            s, owner_id=pid, x=int(outpost.x), y=int(outpost.y), z=int(outpost.z)
        )
        if not eng_fleet:
            return {"ok": False, "error": "engineer_required"}
        eng_map = self._fleet_units_map(s, eng_fleet)
        eng_map["engineer"] = int(eng_map.get("engineer", 0)) + refund
        self._write_fleet_units(s, eng_fleet, eng_map)
        s.delete(row)
        s.flush()
        return {
            "ok": True,
            "outpost": {
                "id": str(outpost.id),
                **self._outpost_stats(s, outpost, viewer_player_id=player_id),
                "x": outpost.x,
                "y": outpost.y,
                "z": outpost.z,
            },
        }

    def _resolve_completed_outpost_modules(self, s: Session, *, next_tick: int) -> None:
        rows = (
            s.execute(
                select(OutpostModule).where(
                    OutpostModule.status == "in_progress",
                    OutpostModule.finish_tick <= int(next_tick),
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            pend = getattr(row, "pending_module_type", None)
            if isinstance(pend, str) and pend.strip():
                tgt = pend.strip()
                row.module_type = tgt
                try:
                    new_md = self._outpost_module_definition(tgt)
                except Exception:
                    new_md = {}
                row.level = int(new_md.get("level", row.level) or row.level)
                row.kind = str(new_md.get("kind") or row.kind or "utility")
                row.pending_module_type = None
            row.status = "active"
            row.updated_at = datetime.utcnow()
        if rows:
            s.flush()

