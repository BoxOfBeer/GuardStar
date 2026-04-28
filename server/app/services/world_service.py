from __future__ import annotations

import hashlib
import json
import random
import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.game_rules import calc_fuel_cost, calc_planet_production, calc_travel_plan, calc_upkeep
from app.db.models.event import Event
from app.db.models.explored_sector import ExploredSector
from app.db.models.building import Building
from app.db.models.fleet import Fleet
from app.db.models.fleet_order import FleetOrder
from app.db.models.game_clock import GameClock
from app.db.models.world_state import WorldState
from app.db.models.planet import Planet
from app.db.models.resource import Resource
from app.db.models.resource_tick import ResourceTick
from app.db.models.unit import Unit
from app.db.models.unit_order import UnitOrder
from app.db.models.player import Player


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
        }

    def __init__(self, *, world_seed: str = "guardstar") -> None:
        self._world_seed = world_seed or "guardstar"

    def _balance_pack(self):
        # Берём загруженный pack из app.extensions (см. create_app()).
        try:
            from flask import current_app

            return current_app.extensions.get("balance")
        except Exception:
            return None

    def _get_player_race_id(self, s: Session, *, player_id: uuid.UUID) -> str | None:
        # race_id появится как поле Player позже. Пока — None.
        _p = s.execute(select(Player).where(Player.id == player_id)).scalar_one_or_none()
        if not _p:
            return None
        rid = getattr(_p, "race_id", None)
        return str(rid) if rid else None

    def _race_modifiers(self, s: Session, *, player_id: uuid.UUID) -> dict:
        pack = self._balance_pack()
        rid = self._get_player_race_id(s, player_id=player_id)
        if not pack or not rid:
            return {
                "build_time_multiplier": 1.0,
                "upkeep_energy_multiplier": 1.0,
                "travel_fuel_multiplier": 1.0,
                "production_multiplier": {"metal": 1.0, "crystal": 1.0, "energy": 1.0, "fuel": 1.0},
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
            },
        }

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
        planet = Planet(owner_player_id=player_id, name="Terra Prime", pos_x=x, pos_y=y)
        s.add(planet)
        s.flush()

        s.add(Resource(planet_id=planet.id, metal=500, crystal=250, energy=100, fuel=100))
        # Стартовые корабли должны быть видимы на карте и "стоять вокруг" планеты:
        # - выше планеты: 1 fighter
        # - слева: 1 scout
        # - справа: 1 scout
        #
        # Сток на планете оставляем нулевым, чтобы движение не "печатало" новые корабли.
        s.add(Unit(owner_player_id=player_id, planet_id=planet.id, unit_type="scout", qty=0))
        s.add(Unit(owner_player_id=player_id, planet_id=planet.id, unit_type="fighter", qty=0))

        s.add(Fleet(owner_player_id=player_id, unit_type="fighter", qty=1, pos_x=x, pos_y=y - 1, pos_z=0))
        s.add(Fleet(owner_player_id=player_id, unit_type="scout", qty=1, pos_x=x - 1, pos_y=y, pos_z=0))
        s.add(Fleet(owner_player_id=player_id, unit_type="scout", qty=1, pos_x=x + 1, pos_y=y, pos_z=0))
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
        # MVP: небольшой расход энергии на поддержание флота (из ресурсов домашней планеты).
        home = s.execute(select(Planet).where(Planet.owner_player_id == player_id)).scalar_one_or_none()
        if not home:
            return
        res = s.execute(select(Resource).where(Resource.planet_id == home.id)).scalar_one_or_none()
        if not res:
            return

        total_qty = s.execute(select(Fleet.qty).where(Fleet.owner_player_id == player_id)).scalars().all()
        fleet_units = int(sum(total_qty)) if total_qty else 0
        if fleet_units <= 0:
            return

        upkeep = calc_upkeep(fleet_units=fleet_units)
        if res.energy >= upkeep.energy_per_tick:
            res.energy -= upkeep.energy_per_tick
        else:
            # Уходим в ноль и пишем событие, чтобы игрок видел проблему.
            res.energy = 0
            self._emit_event(
                s,
                tick=tick,
                type="upkeep_warning",
                message=f"Не хватает энергии на содержание флота (нужно {upkeep.energy_per_tick})",
                payload={"energy_cost": upkeep.energy_per_tick, "fleet_units": fleet_units},
                player_id=player_id,
            )
        s.flush()

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
                    },
                    "units": [{"unit_type": u.unit_type, "qty": u.qty} for u in units],
                }
            ],
        }

    def apply_planet_production_tick(self, s: Session, *, planet_id: uuid.UUID) -> dict:
        planet = s.execute(select(Planet).where(Planet.id == planet_id)).scalar_one_or_none()
        if not planet:
            return {"metal": 0, "crystal": 0, "energy": 0, "fuel": 0}
        res = s.execute(select(Resource).where(Resource.planet_id == planet_id)).scalar_one_or_none()
        if not res:
            return {"metal": 0, "crystal": 0, "energy": 0, "fuel": 0}

        # База: пока через game_rules, далее можно тоже вынести в balance pack.
        prod = calc_planet_production()
        base = {
            "metal": int(prod.metal_per_tick),
            "crystal": int(prod.crystal_per_tick),
            "energy": int(prod.energy_per_tick),
            "fuel": int(prod.fuel_per_tick),
        }

        # Бонус от построек: если есть баланс pack — берём эффекты от buildings.json, иначе fallback на старую формулу.
        pack = self._balance_pack()
        bonus = {"metal": 0, "crystal": 0, "energy": 0, "fuel": 0}
        if pack and hasattr(pack, "buildings_by_id"):
            b_rows = (
                s.execute(select(Building).where(Building.owner_player_id == planet.owner_player_id))
                .scalars()
                .all()
            )
            for b in b_rows:
                b_id = (
                    "mine_t1"
                    if b.building_type == "mine"
                    else ("reactor_t1" if b.building_type == "reactor" else "crystal_farm_t1")
                )
                bd = pack.buildings_by_id.get(b_id)
                eff = bd.get("effects") if isinstance(bd, dict) else None
                prod_add = (eff.get("production_per_tick_add") if isinstance(eff, dict) else None) or {}
                for k in ("metal", "crystal", "energy", "fuel"):
                    if isinstance(prod_add.get(k), (int, float)):
                        bonus[k] += int(prod_add.get(k))
        else:
            bonus = self._get_building_bonus_for_player(s, player_id=planet.owner_player_id)

        mods = self._race_modifiers(s, player_id=planet.owner_player_id)
        mul = mods.get("production_multiplier") if isinstance(mods.get("production_multiplier"), dict) else {}

        def _calc(k: str) -> int:
            m = float(mul.get(k, 1.0))
            return int(round((base[k] + bonus[k]) * m))

        dm, dc, de, df = _calc("metal"), _calc("crystal"), _calc("energy"), _calc("fuel")
        res.metal += dm
        res.crystal += dc
        res.energy += de
        res.fuel += df
        s.flush()
        return {"metal": dm, "crystal": dc, "energy": de, "fuel": df}

    def get_sector_stub(self, s: Session, *, x: int | None, y: int | None, z: int = 0, player_id: str | None) -> dict:
        sector = {"x": x, "y": y, "z": z, "objects": [], "cell": None}
        if not player_id:
            return sector

        if x is None or y is None:
            return sector

        sector["cell"] = self.get_cell_terrain(x=x, y=y, z=z)

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
        for f in fleets_in_cell:
            owner_ids.add(f.owner_player_id)
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
                # Заглушки под будущую систему построек/очередей.
                prod = calc_planet_production()
                bonus = self._get_building_bonus_for_player(s, player_id=pobj.owner_player_id)
                production = {
                    "metal_per_tick": prod.metal_per_tick + bonus["metal"],
                    "crystal_per_tick": prod.crystal_per_tick + bonus["crystal"],
                    "energy_per_tick": prod.energy_per_tick + bonus["energy"],
                    "fuel_per_tick": prod.fuel_per_tick + bonus["fuel"],
                }
                build = {"active": None, "queue": []}
                obj["details"] = {
                    "resources": {
                        "metal": int(res.metal) if res else 0,
                        "crystal": int(res.crystal) if res else 0,
                        "energy": int(res.energy) if res else 0,
                        "fuel": int(getattr(res, "fuel", 0)) if res else 0,
                    },
                    "production": production,
                    "units": [{"unit_type": u.unit_type, "qty": int(u.qty)} for u in units],
                    "build": build,
                }
            sector["objects"].append(obj)

        # В секторе показываем флоты всех игроков (для "кто здесь").
        for f in fleets_in_cell:
            sector["objects"].append(
                {
                    "type": "fleet",
                    "id": str(f.id),
                    "unit_type": f.unit_type,
                    "qty": f.qty,
                    "owner": str(f.owner_player_id),
                    "owner_name": owners.get(str(f.owner_player_id)),
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
                    "unit_type": f.unit_type,
                    "qty": f.qty,
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

        # --- Fog of war (MVP): 2 слоя ---
        # 1) unknown: игрок ни разу не видел клетку
        # 2) memory: игрок видел, но сейчас не видит (память хранится 10 тиков), далее -> stale (почти ничего не видно)
        vis_sources: list[tuple[int, int, int]] = []
        # планеты игрока дают радиус 5
        my_planets = s.execute(select(Planet).where(Planet.owner_player_id == pid)).scalars().all()
        for p in my_planets:
            vis_sources.append((p.pos_x, p.pos_y, 5))
        # флоты игрока дают радиус: scout=2, fighter=1, иначе 1
        my_fleets = s.execute(select(Fleet).where(Fleet.owner_player_id == pid, Fleet.pos_z == z)).scalars().all()
        for f in my_fleets:
            r = 2 if f.unit_type == "scout" else 1
            vis_sources.append((f.pos_x, f.pos_y, r))

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
                else:
                    # В тумане не показываем руины/астероиды и т.п.
                    # В stale оставляем только намёк на аномалию (серым вопросом).
                    objects = []
                    if fog_state == "stale":
                        terrain = {"terrain": "fog", "glyph": "?"}
                    else:
                        terrain = {"terrain": "fog", "glyph": ""}
                row.append(
                    {
                        "x": x,
                        "y": y,
                        "z": z,
                        "objects": objects,
                        "terrain": terrain["terrain"],
                        "glyph": terrain["glyph"],
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

    def _can_build_at(self, s: Session, *, owner_id: uuid.UUID, x: int, y: int, z: int) -> dict:
        if z != 0:
            return {"ok": False, "error": "z_not_supported_yet"}
        # Строим в радиусе 3 от своей планеты, но не в радиусе 3 от чужой.
        my_planets = s.execute(select(Planet).where(Planet.owner_player_id == owner_id)).scalars().all()
        if not my_planets:
            return {"ok": False, "error": "no_home_planet"}

        in_self = any((abs(p.pos_x - x) + abs(p.pos_y - y)) <= 3 for p in my_planets)
        if not in_self:
            return {"ok": False, "error": "outside_build_zone"}

        enemy_planets = s.execute(select(Planet).where(Planet.owner_player_id != owner_id)).scalars().all()
        in_enemy = any((abs(p.pos_x - x) + abs(p.pos_y - y)) <= 3 for p in enemy_planets)
        if in_enemy:
            return {"ok": False, "error": "inside_enemy_build_zone"}

        return {"ok": True}

    def place_building(
        self,
        s: Session,
        *,
        player_id: str,
        x: int,
        y: int,
        z: int,
        building_type: str,
    ) -> dict:
        pid = uuid.UUID(player_id)
        btype = (building_type or "").strip().lower()
        if btype not in ("mine", "reactor", "crystal_farm"):
            return {"ok": False, "error": "invalid_building_type"}

        gate = self._can_build_at(s, owner_id=pid, x=x, y=y, z=z)
        if not gate.get("ok"):
            return gate

        # 1 постройка на клетку (MVP).
        exists = (
            s.execute(select(Building).where(Building.x == x, Building.y == y, Building.z == z))
            .scalars()
            .first()
        )
        if exists:
            return {"ok": False, "error": "cell_already_built"}

        # Стоимость (MVP): списываем с домашней планеты.
        home = s.execute(select(Planet).where(Planet.owner_player_id == pid)).scalar_one_or_none()
        if not home:
            return {"ok": False, "error": "no_home_planet"}
        res = s.execute(select(Resource).where(Resource.planet_id == home.id)).scalar_one_or_none()
        if not res:
            return {"ok": False, "error": "no_resources"}

        cost = {"metal": 120, "crystal": 60}
        if btype == "reactor":
            cost = {"metal": 160, "crystal": 40}
        elif btype == "crystal_farm":
            cost = {"metal": 100, "crystal": 90}

        if int(res.metal) < cost["metal"] or int(res.crystal) < cost["crystal"]:
            self._emit_event(
                s,
                tick=self.get_or_create_world_state(s).current_tick,
                type="not_enough_resources",
                message=f"Не хватает ресурсов для постройки {btype} (нужно M{cost['metal']}/C{cost['crystal']})",
                payload={"need": cost, "have": {"metal": int(res.metal), "crystal": int(res.crystal)}},
                player_id=pid,
            )
            return {"ok": False, "error": "not_enough_resources", "need": cost, "have": {"metal": int(res.metal), "crystal": int(res.crystal)}}

        res.metal -= cost["metal"]
        res.crystal -= cost["crystal"]

        b = Building(owner_player_id=pid, x=int(x), y=int(y), z=int(z), building_type=btype, level=1)
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

        return {"ok": True, "building": {"id": str(b.id), "building_type": btype, "level": int(b.level), "pos": {"x": x, "y": y, "z": z}}, "cost": cost}

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
                .where(FleetOrder.fleet_id == fleet_id, FleetOrder.status.in_(["queued", "in_progress"]))
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

        if self._active_order_for_fleet(s, fleet_id=fleet.id):
            return {"ok": False, "error": "active_order_exists"}

        travel = calc_travel_plan(from_x=fleet.pos_x, from_y=fleet.pos_y, to_x=target_x, to_y=target_y, unit_type=fleet.unit_type)
        if travel.distance == 0:
            return {"ok": False, "error": "target_same_cell"}

        # Fuel (MVP): списываем с ресурсов домашней планеты владельца.
        home = s.execute(select(Planet).where(Planet.owner_player_id == pid)).scalar_one_or_none()
        if not home:
            return {"ok": False, "error": "no_home_planet"}
        res = s.execute(select(Resource).where(Resource.planet_id == home.id)).scalar_one_or_none()
        if not res:
            return {"ok": False, "error": "no_resources"}

        pack = self._balance_pack()
        mods = self._race_modifiers(s, player_id=pid)
        if pack and hasattr(pack, "units_by_id"):
            unit_id = "scout_t1" if fleet.unit_type == "scout" else "fighter_t1"
            u = pack.units_by_id.get(unit_id)
            per_cell = int(u.get("travel_fuel_per_cell", 1)) if isinstance(u, dict) else 1
            mult = float(mods.get("travel_fuel_multiplier", 1.0))
            fuel_cost = int(round(max(0, travel.distance) * max(1, fleet.qty) * max(1, per_cell) * mult))
            fuel_plan = type("FuelPlan", (), {"fuel_cost": fuel_cost})
        else:
            fuel_plan = calc_fuel_cost(distance=travel.distance, qty=fleet.qty, unit_type=fleet.unit_type)
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
        )
        s.add(order)
        s.flush()

        self._emit_event(
            s,
            tick=ws.current_tick,
            type="fleet_order_created",
            message=f"Приказ флота: {fleet.unit_type}×{fleet.qty} → ({target_x},{target_y},{target_z})",
            payload={
                "order_id": str(order.id),
                "fleet_id": str(fleet.id),
                "from": {"x": order.from_x, "y": order.from_y, "z": order.from_z},
                "target": {"x": order.target_x, "y": order.target_y, "z": order.target_z},
                "qty": order.qty,
                "travel_ticks": travel.travel_ticks,
                "fuel_cost": fuel_plan.fuel_cost,
            },
            player_id=pid,
        )
        self._emit_event(
            s,
            tick=ws.current_tick,
            type="fuel_spent",
            message=f"Топливо потрачено: -{fuel_plan.fuel_cost} (перелёт {fleet.unit_type}×{fleet.qty})",
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
            "start_tick": order.start_tick,
            "finish_tick": order.finish_tick,
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
        source_fleet = (
            s.execute(
                select(Fleet)
                .where(Fleet.owner_player_id == pid, Fleet.unit_type == "scout")
                .order_by(Fleet.created_at.asc())
            )
            .scalars()
            .first()
        )
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

        # 1) Fleet orders
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

            # MVP: перемещаем весь стек
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

        # MVP: производство ресурсов по тикам на планетах
        planets = s.execute(select(Planet)).scalars().all()
        for p in planets:
            self.apply_planet_production_tick(s, planet_id=p.id)

        # MVP: upkeep после обработки ордеров, для всех игроков у кого есть флоты.
        owner_ids = s.execute(select(Fleet.owner_player_id).distinct()).scalars().all()
        for oid in owner_ids:
            self.apply_fleet_upkeep_tick(s, player_id=oid, tick=next_tick)

        s.flush()
        return {"current_tick": ws.current_tick, "events": events}

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
        return {"current_tick": ws.current_tick, "units": payload}

    def get_world_state(self, s: Session, *, player_id: str, auto_tick_enabled: bool, auto_tick_interval_seconds: float) -> dict:
        pid = uuid.UUID(player_id)
        ws = self.get_or_create_world_state(s)

        home = s.execute(select(Planet).where(Planet.owner_player_id == pid)).scalar_one_or_none()
        if not home:
            return {
                "current_tick": ws.current_tick,
                "auto_tick_enabled": auto_tick_enabled,
                "auto_tick_interval_seconds": auto_tick_interval_seconds,
                "unit": None,
            }

        # Основная “движимая” сущность: Fleet (стек), а не Unit.qty.
        scout_fleet = (
            s.execute(
                select(Fleet)
                .where(Fleet.owner_player_id == pid, Fleet.unit_type == "scout")
                .order_by(Fleet.qty.desc())
            )
            .scalars()
            .first()
        )

        pos = {"x": home.pos_x, "y": home.pos_y, "z": 0}
        fleet_payload = None
        if scout_fleet and scout_fleet.qty > 0:
            pos = {"x": scout_fleet.pos_x, "y": scout_fleet.pos_y, "z": scout_fleet.pos_z}
            active_fleet_order = self._active_order_for_fleet(s, fleet_id=scout_fleet.id)
            status = "moving" if active_fleet_order else "idle"
            active_payload = None
            if active_fleet_order:
                remaining = max(0, int(active_fleet_order.finish_tick - clock.current_tick))
                travel = calc_travel_plan(
                    from_x=active_fleet_order.from_x,
                    from_y=active_fleet_order.from_y,
                    to_x=active_fleet_order.target_x,
                    to_y=active_fleet_order.target_y,
                    unit_type=scout_fleet.unit_type,
                )
                active_payload = {
                    "from_x": active_fleet_order.from_x,
                    "from_y": active_fleet_order.from_y,
                    "from_z": active_fleet_order.from_z,
                    "target_x": active_fleet_order.target_x,
                    "target_y": active_fleet_order.target_y,
                    "target_z": active_fleet_order.target_z,
                    "finish_tick": active_fleet_order.finish_tick,
                    "remaining_ticks": remaining,
                    "distance": travel.distance,
                    "travel_ticks": travel.travel_ticks,
                }

            fleet_payload = {
                "id": str(scout_fleet.id),
                "unit_type": scout_fleet.unit_type,
                "qty": int(scout_fleet.qty),
                "status": status,
                **pos,
                "active_order": active_payload,
            }

        # Полный список флотов игрока (для одновременной отрисовки движения нескольких флотов).
        fleets_payload: list[dict] = []
        all_fleets = (
            s.execute(select(Fleet).where(Fleet.owner_player_id == pid).order_by(Fleet.unit_type, Fleet.qty.desc()))
            .scalars()
            .all()
        )
        for f in all_fleets:
            if int(f.qty) <= 0:
                continue
            active = self._active_order_for_fleet(s, fleet_id=f.id)
            status = "moving" if active else "idle"
            active_payload = None
            if active:
                remaining = max(0, int(active.finish_tick - clock.current_tick))
                travel = calc_travel_plan(
                    from_x=active.from_x,
                    from_y=active.from_y,
                    to_x=active.target_x,
                    to_y=active.target_y,
                    unit_type=f.unit_type,
                )
                active_payload = {
                    "from_x": active.from_x,
                    "from_y": active.from_y,
                    "from_z": active.from_z,
                    "target_x": active.target_x,
                    "target_y": active.target_y,
                    "target_z": active.target_z,
                    "finish_tick": active.finish_tick,
                    "remaining_ticks": remaining,
                    "distance": travel.distance,
                    "travel_ticks": travel.travel_ticks,
                }
            fleets_payload.append(
                {
                    "id": str(f.id),
                    "unit_type": f.unit_type,
                    "qty": int(f.qty),
                    "status": status,
                    "x": f.pos_x,
                    "y": f.pos_y,
                    "z": f.pos_z,
                    "active_order": active_payload,
                }
            )

        # Economy summary for UI
        res = s.execute(select(Resource).where(Resource.planet_id == home.id)).scalar_one_or_none()
        total_qty = s.execute(select(Fleet.qty).where(Fleet.owner_player_id == pid)).scalars().all()
        fleet_units = int(sum(total_qty)) if total_qty else 0
        upkeep = calc_upkeep(fleet_units=fleet_units)
        metal = int(res.metal) if res else 0
        crystal = int(res.crystal) if res else 0
        energy = int(res.energy) if res else 0
        fuel = int(getattr(res, "fuel", 0)) if res else 0
        prod = calc_planet_production()
        bonus = self._get_building_bonus_for_player(s, player_id=pid)
        energy_ticks_left = None
        if upkeep.energy_per_tick > 0:
            energy_ticks_left = energy // upkeep.energy_per_tick

        recent_events = (
            s.execute(select(Event).where(Event.player_id == pid).order_by(Event.id.desc()).limit(25)).scalars().all()
        )
        events_payload = [
            {"id": e.id, "tick": e.tick, "type": e.type, "message": e.message, "created_at": e.created_at.isoformat()}
            for e in reversed(recent_events)
        ]

        return {
            "current_tick": ws.current_tick,
            "auto_tick_enabled": auto_tick_enabled,
            "auto_tick_interval_seconds": auto_tick_interval_seconds,
            "fleet": fleet_payload,
            "fleets": fleets_payload,
            "events": events_payload,
            "economy": {
                "metal": metal,
                "crystal": crystal,
                "energy": energy,
                "fuel": fuel,
                "production_per_tick": {
                    "metal": prod.metal_per_tick + bonus["metal"],
                    "crystal": prod.crystal_per_tick + bonus["crystal"],
                    "energy": prod.energy_per_tick + bonus["energy"],
                    "fuel": prod.fuel_per_tick + bonus["fuel"],
                },
                "avg_10_ticks": {
                    "metal": prod.metal_per_tick + bonus["metal"],
                    "crystal": prod.crystal_per_tick + bonus["crystal"],
                    "energy": max(0, (prod.energy_per_tick + bonus["energy"]) - upkeep.energy_per_tick),
                    "fuel": prod.fuel_per_tick + bonus["fuel"],
                },
                "upkeep_energy_per_tick": upkeep.energy_per_tick,
                "fleet_units": upkeep.fleet_units,
                "energy_ticks_left": energy_ticks_left,
            },
        }
