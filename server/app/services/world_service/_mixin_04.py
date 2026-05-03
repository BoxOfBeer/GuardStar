"""Фрагмент WorldService: здания, флоты, состав, NPC-игроки."""

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


class WorldServiceMixin04:
    def _can_build_at(
        self,
        s: Session,
        *,
        owner_id: uuid.UUID,
        x: int,
        y: int,
        z: int,
        fleet_id: str | None = None,
    ) -> dict:
        if z != 0:
            return {"ok": False, "error": "z_not_supported_yet"}
        my_planets = (
            s.execute(select(Planet).where(Planet.owner_player_id == owner_id))
            .scalars()
            .all()
        )
        if not my_planets:
            return {"ok": False, "error": "no_home_planet"}

        eng_fleet = self._owned_engineer_fleet_at(
            s, owner_id=owner_id, x=x, y=y, z=z, fleet_id=fleet_id
        )
        in_self = any((abs(p.pos_x - x) + abs(p.pos_y - y)) <= 3 for p in my_planets)
        if not in_self and not eng_fleet:
            return {"ok": False, "error": "engineer_required"}

        if self._cell_enemy_control_owner(s, owner_id=owner_id, x=x, y=y, z=z):
            return {"ok": False, "error": "inside_enemy_control_zone"}

        return {
            "ok": True,
            "builder_fleet_id": str(eng_fleet.id) if eng_fleet else None,
        }

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
            aliases = (
                self._balance.pack.aliases.get("building_aliases", {})
                if self._balance.pack
                else {}
            )
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
                return {
                    "ok": False,
                    "error": "tech_required",
                    "required_techs": req_techs,
                    "missing_techs": missing,
                }

        # Основание для постройки: валидируем по типу ландшафта клетки.
        # Примеры из ТЗ: шахты только на астероидах; жилые/лаборатории нельзя строить в «пустом космосе».
        if build_def is not None:
            allowed_terrains = (
                build_def.get("build_on_terrain")
                if isinstance(build_def, dict)
                else None
            )
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
                if (
                    isinstance(allowed_terrains, list)
                    and allowed_terrains
                    and terrain not in allowed_terrains
                ):
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

        planet = self._resolve_owning_planet_for_build_site(
            s, owner_id=pid, x=x, y=y, z=z
        )
        if not planet:
            planet = s.execute(
                select(Planet)
                .where(Planet.owner_player_id == pid)
                .order_by(Planet.created_at.asc())
            ).scalar_one_or_none()
        if not planet:
            return {"ok": False, "error": "no_controlling_planet"}

        on_planet_tile = self._cell_has_planet(s, x=int(x), y=int(y), z=int(z))
        # Слоты build_slots_total — только для тайла колонии; полевая экспансия лимитом не считается.
        if on_planet_tile:
            slots_total = int(getattr(planet, "build_slots_total", 55) or 55)
            built_surface = int(
                self._surface_slot_buildings_count_for_planet(s, planet=planet)
            )
            if built_surface >= slots_total:
                return {
                    "ok": False,
                    "error": "planet_slots_full",
                    "built": built_surface,
                    "built_surface": built_surface,
                    "total": slots_total,
                }

        # На тайле колонии несколько построек, но суммой не больше build_slots_total.
        # На остальных клетках — только «одна постройка на клетку», без лимита экспансии по счётчику.
        if not on_planet_tile:
            exists = (
                s.execute(
                    select(Building).where(
                        Building.x == x, Building.y == y, Building.z == z
                    )
                )
                .scalars()
                .first()
            )
            if exists:
                return {"ok": False, "error": "cell_already_built"}

        home = s.execute(
            select(Planet).where(Planet.owner_player_id == pid)
        ).scalar_one_or_none()
        if not home:
            return {"ok": False, "error": "no_home_planet"}
        res = s.execute(
            select(Resource).where(Resource.planet_id == home.id)
        ).scalar_one_or_none()
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
                payload={
                    "need": cost,
                    "have": {"metal": int(res.metal), "crystal": int(res.crystal)},
                },
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
                fleet = s.execute(
                    select(Fleet).where(Fleet.id == bf, Fleet.owner_player_id == pid)
                ).scalar_one_or_none()
                if fleet:
                    um = self._fleet_units_map(s, fleet)
                    if int(um.get("engineer", 0)) <= 0:
                        return {
                            "ok": False,
                            "error": "not_enough_engineers",
                            "need_engineers": 1,
                        }
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
            payload={
                "building_id": str(b.id),
                "building_type": btype,
                "pos": {"x": x, "y": y, "z": z},
                "cost": cost,
            },
            player_id=pid,
        )

        return {
            "ok": True,
            "building": {
                "id": str(b.id),
                "building_type": btype,
                "level": int(b.level),
                "pos": {"x": x, "y": y, "z": z},
            },
            "cost": cost,
            "builder_fleet_id": gate.get("builder_fleet_id"),
        }

    def _building_effects_summary_ru(self, build_def: dict | None) -> str:
        if not isinstance(build_def, dict):
            return "—"
        eff = (
            build_def.get("effects")
            if isinstance(build_def.get("effects"), dict)
            else {}
        )
        prod = (
            eff.get("production_per_tick_add")
            if isinstance(eff.get("production_per_tick_add"), dict)
            else {}
        )
        parts: list[str] = []
        for k, ru in (
            ("metal", "металл"),
            ("crystal", "кристаллы"),
            ("energy", "энергия"),
            ("fuel", "топливо"),
            ("food", "еда"),
            ("water", "вода"),
        ):
            if isinstance(prod.get(k), (int, float)) and float(prod[k]) != 0:
                v = int(prod[k])
                sign = "+" if v > 0 else ""
                parts.append(f"{sign}{v} {ru}/сол")
        if (
            isinstance(eff.get("max_population_add"), (int, float))
            and float(eff["max_population_add"]) != 0
        ):
            v = int(eff["max_population_add"])
            sign = "+" if v > 0 else ""
            parts.append(f"{sign}{v} насел.")
        return ", ".join(parts) if parts else "—"

    def _building_ui_meta(self, logical_type: str, build_def: dict | None) -> dict:
        name = None
        if (
            isinstance(build_def, dict)
            and isinstance(build_def.get("name"), str)
            and build_def.get("name").strip()
        ):
            name = str(build_def["name"]).strip()
        desc = None
        if (
            isinstance(build_def, dict)
            and isinstance(build_def.get("description"), str)
            and build_def.get("description").strip()
        ):
            desc = str(build_def["description"]).strip()
        allowed = None
        if isinstance(build_def, dict) and isinstance(
            build_def.get("build_on_terrain"), list
        ):
            allowed = [
                str(x) for x in build_def.get("build_on_terrain") if isinstance(x, str)
            ]
        return {
            "type": str(logical_type),
            "name": name,
            "description": desc,
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
            aliases = (
                self._balance.pack.aliases.get("building_aliases", {})
                if self._balance.pack
                else {}
            )
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
                return {
                    "ok": False,
                    "error": "tech_required",
                    "required_techs": req_techs,
                    "missing_techs": missing,
                    "meta": meta,
                }

        # Основание (ландшафт клетки)
        if build_def is not None:
            allowed_terrains = (
                build_def.get("build_on_terrain")
                if isinstance(build_def, dict)
                else None
            )
            if isinstance(allowed_terrains, list) and allowed_terrains:
                if "planet" in allowed_terrains:
                    if not self._cell_has_planet(s, x=int(x), y=int(y), z=int(z)):
                        return {"ok": False, "error": "planet_required", "meta": meta}
                    allowed_terrains = [t for t in allowed_terrains if t != "planet"]
                    if not allowed_terrains:
                        allowed_terrains = None
                cell = self.get_cell_terrain(x=x, y=y, z=z)
                terrain = cell.get("terrain")
                if (
                    isinstance(allowed_terrains, list)
                    and allowed_terrains
                    and terrain not in allowed_terrains
                ):
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

        return {
            "ok": True,
            "builder_fleet_id": gate.get("builder_fleet_id"),
            "meta": meta,
        }

    def dismantle_building(
        self, s: Session, *, player_id: str, building_id: str
    ) -> dict:
        pid = uuid.UUID(player_id)
        try:
            bid = uuid.UUID(building_id)
        except Exception:
            return {"ok": False, "error": "invalid_building_id"}
        row = (
            s.execute(
                select(Building).where(
                    Building.id == bid, Building.owner_player_id == pid
                )
            )
            .scalars()
            .first()
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

        home = s.execute(
            select(Planet).where(Planet.owner_player_id == pid)
        ).scalar_one_or_none()
        res = (
            s.execute(
                select(Resource).where(Resource.planet_id == home.id)
            ).scalar_one_or_none()
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

    def upgrade_building(self, s: Session, *, player_id: str, building_id: str) -> dict:
        pid = uuid.UUID(player_id)
        try:
            bid = uuid.UUID(building_id)
        except Exception:
            return {"ok": False, "error": "invalid_building_id"}
        row = (
            s.execute(
                select(Building).where(
                    Building.id == bid, Building.owner_player_id == pid
                )
            )
            .scalars()
            .first()
        )
        if not row:
            return {"ok": False, "error": "building_not_found"}
        if not self._balance:
            return {"ok": False, "error": "balance_unavailable"}

        try:
            bd = self._balance.get_building(row.building_type)
        except Exception:
            return {"ok": False, "error": "unknown_building"}
        up = bd.get("upgrade") if isinstance(bd, dict) else None
        if not isinstance(up, dict) or not str(up.get("to") or "").strip():
            return {"ok": False, "error": "building_upgrade_unavailable"}
        target_key = str(up["to"]).strip().lower()
        try:
            tdef = self._balance.get_building(target_key)
        except Exception:
            return {"ok": False, "error": "upgrade_target_unknown"}

        req_techs = [str(x) for x in up.get("prereq_tech", []) if isinstance(x, str)]
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

        if self._cell_enemy_control_owner(
            s, owner_id=pid, x=int(row.x), y=int(row.y), z=int(row.z)
        ):
            return {"ok": False, "error": "inside_enemy_control_zone"}

        # Улучшение на тайле колонии не требует повторных инженеров. Полевые — как новая постройка.
        if row.planet_id is None:
            gate = self._can_build_at(
                s, owner_id=pid, x=int(row.x), y=int(row.y), z=int(row.z), fleet_id=None
            )
            if not gate.get("ok"):
                return gate

        # Лимиты по типам (max_per_planet) для планеты не используем при улучшении:
        # на тайле колонии слотов хватает при постановке; апгрейд — замена типа на той же клетке,
        # иначе «базовая ферма» (max 6) не могла бы стать гидропоникой (max 4) после dev-логики «только слоты».

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

        cost = up.get("cost") if isinstance(up.get("cost"), dict) else {}
        need = {k: int(cost.get(k, 0)) for k in ("metal", "crystal", "energy", "fuel")}
        if int(res.metal) < need["metal"] or int(res.crystal) < need["crystal"]:
            return {"ok": False, "error": "not_enough_resources", "need": need}
        if (
            int(res.energy) < need["energy"]
            or int(getattr(res, "fuel", 0)) < need["fuel"]
        ):
            return {"ok": False, "error": "not_enough_resources", "need": need}

        res.metal -= need["metal"]
        res.crystal -= need["crystal"]
        res.energy -= need["energy"]
        if hasattr(res, "fuel"):
            res.fuel = int(getattr(res, "fuel", 0)) - need["fuel"]

        prev = row.building_type
        tier = (
            int(tdef.get("tier", row.level))
            if isinstance(tdef, dict)
            else int(row.level)
        )
        row.building_type = target_key
        row.level = max(1, tier)
        s.flush()

        planet = s.get(Planet, row.planet_id) if row.planet_id else None

        ws = self.get_or_create_world_state(s)
        self._emit_event(
            s,
            tick=ws.current_tick,
            type="building_upgraded",
            message=f"Постройка улучшена: {prev} → {target_key}",
            payload={
                "building_id": str(bid),
                "from_type": prev,
                "to_type": target_key,
                "cost": need,
                "pos": {"x": int(row.x), "y": int(row.y), "z": int(row.z)},
            },
            player_id=pid,
        )
        if planet:
            curpop = getattr(planet, "population", 800)
            mx = self._effective_max_population(s, planet)
            if hasattr(planet, "population") and int(curpop) > int(mx):
                planet.population = int(mx)

        return {
            "ok": True,
            "building": {
                "id": str(row.id),
                "building_type": target_key,
                "level": int(row.level),
            },
            "cost": need,
        }

    def _fleet_active_order_payload(
        self, s: Session, ws: WorldState, fleet: Fleet
    ) -> dict | None:
        ao = self._active_order_for_fleet(s, fleet_id=fleet.id)
        if not ao:
            return None
        remaining = max(0, int(ao.finish_tick - ws.current_tick))
        units_map = self._fleet_units_map(s, fleet)
        d = abs(ao.target_x - ao.from_x) + abs(ao.target_y - ao.from_y)
        travel_ticks = self._fleet_travel_ticks_for_distance(
            distance=d, units=units_map
        )
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
        if ao.status == "pending_combat" and getattr(
            ao, "combat_prompt_expires_at", None
        ):
            exp = ao.combat_prompt_expires_at
            out["pending_combat"] = True
            out["combat_prompt_expires_at"] = (
                exp.isoformat() if hasattr(exp, "isoformat") else str(exp)
            )
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
        fleet = (
            s.execute(
                select(Fleet).where(Fleet.id == fid, Fleet.owner_player_id == pid)
            )
            .scalars()
            .first()
        )
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

        done_tech = set(self._get_player_done_techs(s, player_id=pid))
        for k, v in newd.items():
            prev = int(cur.get(k, 0))
            if int(v) <= prev:
                continue
            miss = [tid for tid in self._unit_required_techs(k) if tid not in done_tech]
            if miss:
                return {
                    "ok": False,
                    "error": "tech_required",
                    "unit_type": k,
                    "missing_techs": miss,
                }

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

        pay_res = self._try_apply_home_resource_net_for_fleet_change(
            s, pid=pid, cur=cur, newd=newd
        )
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

    def rename_fleet(
        self, s: Session, *, player_id: str, fleet_id: str, name: str | None
    ) -> dict:
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
        fleet = (
            s.execute(
                select(Fleet).where(Fleet.id == fid, Fleet.owner_player_id == pid)
            )
            .scalars()
            .first()
        )
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
        home = s.execute(
            select(Planet).where(Planet.owner_player_id == pid)
        ).scalar_one_or_none()
        if not home:
            return {"ok": False, "error": "no_home_planet"}
        res = s.execute(
            select(Resource).where(Resource.planet_id == home.id)
        ).scalar_one_or_none()
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
        fleet = (
            s.execute(
                select(Fleet).where(Fleet.id == fid, Fleet.owner_player_id == pid)
            )
            .scalars()
            .first()
        )
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
            cap = self._world_max_fleet_units(s)
            if total_new > cap:
                return {"ok": False, "error": "fleet_too_large", "max_units": cap}

            cur = self._fleet_units_map(s, fleet)
            pay_res = self._try_apply_home_resource_net_for_fleet_change(
                s, pid=pid, cur=cur, newd=newd
            )
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
                payload={
                    "fleet_id": str(fleet.id),
                    "composition": out.get("composition", {}),
                },
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

    def get_fleet_upkeep_preview(
        self, s: Session, *, player_id: str, fleet_id: str
    ) -> dict:
        """Узкий превью расходов флота за сол (энергия на кораблях + имперское снабжение)."""
        try:
            pid = uuid.UUID(str(player_id).strip())
            fid = uuid.UUID(str(fleet_id).strip())
        except Exception:
            return {"ok": False, "error": "invalid_id"}
        fleet = (
            s.execute(
                select(Fleet).where(Fleet.id == fid, Fleet.owner_player_id == pid)
            )
            .scalars()
            .first()
        )
        if not fleet:
            return {"ok": False, "error": "not_found"}
        if self._fleet_total_units(s, fleet) <= 0:
            return {
                "ok": True,
                "fleet_id": str(fid),
                "energy_upkeep_per_sol": 0,
                "empire_supply_per_sol": {
                    "metal": 0,
                    "crystal": 0,
                    "food": 0,
                    "water": 0,
                },
                "fleet_energy_current": int(getattr(fleet, "energy", 0) or 0),
                "energy_penalty_on_unpaid_maintenance": int(
                    self._fleet_empire_upkeep_unpaid_penalty_energy()
                ),
            }
        um = self._fleet_units_map(s, fleet)
        en = int(self._fleet_upkeep_energy_total(s, player_id=pid, units=um))
        sup = self._fleet_empire_supply_need_for_fleet(s, fleet=fleet)
        return {
            "ok": True,
            "fleet_id": str(fid),
            "energy_upkeep_per_sol": en,
            "empire_supply_per_sol": {
                "metal": int(sup.get("metal", 0) or 0),
                "crystal": int(sup.get("crystal", 0) or 0),
                "food": int(sup.get("food", 0) or 0),
                "water": int(sup.get("water", 0) or 0),
            },
            "fleet_energy_current": int(getattr(fleet, "energy", 0) or 0),
            "energy_penalty_on_unpaid_maintenance": int(
                self._fleet_empire_upkeep_unpaid_penalty_energy()
            ),
        }

    def disband_fleet(self, s: Session, *, player_id: str, fleet_id: str) -> dict:
        pid = uuid.UUID(player_id)
        try:
            fid = uuid.UUID(fleet_id)
        except Exception:
            return {"ok": False, "error": "invalid_fleet_id"}
        fleet = (
            s.execute(
                select(Fleet).where(Fleet.id == fid, Fleet.owner_player_id == pid)
            )
            .scalars()
            .first()
        )
        if not fleet:
            return {"ok": False, "error": "fleet_not_found"}
        if self._active_order_for_fleet(s, fleet_id=fleet.id):
            return {"ok": False, "error": "active_order_exists"}

        cur = self._fleet_units_map(s, fleet)
        home = s.execute(
            select(Planet).where(Planet.owner_player_id == pid)
        ).scalar_one_or_none()
        if not home:
            return {"ok": False, "error": "no_home_planet"}
        res = s.execute(
            select(Resource).where(Resource.planet_id == home.id)
        ).scalar_one_or_none()
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

    def merge_fleets(
        self, s: Session, *, player_id: str, target_fleet_id: str, source_fleet_id: str
    ) -> dict:
        pid = uuid.UUID(player_id)
        try:
            tid = uuid.UUID(target_fleet_id)
            sid = uuid.UUID(source_fleet_id)
        except Exception:
            return {"ok": False, "error": "invalid_fleet_id"}
        if tid == sid:
            return {"ok": False, "error": "same_fleet"}
        target = (
            s.execute(
                select(Fleet).where(Fleet.id == tid, Fleet.owner_player_id == pid)
            )
            .scalars()
            .first()
        )
        source = (
            s.execute(
                select(Fleet).where(Fleet.id == sid, Fleet.owner_player_id == pid)
            )
            .scalars()
            .first()
        )
        if not target or not source:
            return {"ok": False, "error": "fleet_not_found"}
        if self._active_order_for_fleet(
            s, fleet_id=target.id
        ) or self._active_order_for_fleet(s, fleet_id=source.id):
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
        cap = self._world_max_fleet_units(s)
        if sum(newd.values()) > cap:
            return {"ok": False, "error": "fleet_too_large", "max_units": cap}

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
            payload={
                "target_fleet_id": str(tid),
                "source_fleet_id": str(sid),
                "composition": dict(newd),
            },
            player_id=pid,
        )
        return {
            "ok": True,
            "fleet_id": str(tid),
            "composition": dict(newd),
            "merged_from": str(sid),
        }

    def split_fleet(
        self, s: Session, *, player_id: str, fleet_id: str, take: dict | None
    ) -> dict:
        pid = uuid.UUID(player_id)
        try:
            fid = uuid.UUID(fleet_id)
        except Exception:
            return {"ok": False, "error": "invalid_fleet_id"}
        if not isinstance(take, dict) or not take:
            return {"ok": False, "error": "invalid_take"}
        fleet = (
            s.execute(
                select(Fleet).where(Fleet.id == fid, Fleet.owner_player_id == pid)
            )
            .scalars()
            .first()
        )
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

        cap = self._world_max_fleet_units(s)
        if sum(take_map.values()) > cap or sum(remainder.values()) > cap:
            return {"ok": False, "error": "fleet_too_large", "max_units": cap}

        spawn = self._pick_fleet_spawn_xy(
            s,
            owner_id=pid,
            px=int(fleet.pos_x),
            py=int(fleet.pos_y),
            pz=int(fleet.pos_z),
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

