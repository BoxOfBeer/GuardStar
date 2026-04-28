from __future__ import annotations

import hashlib
import random
import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.db.models.fleet import Fleet
from app.db.models.planet import Planet
from app.db.models.resource import Resource
from app.db.models.resource_tick import ResourceTick
from app.db.models.unit import Unit


class WorldService:
    def __init__(self, *, world_seed: str = "guardstar") -> None:
        # Seed только для процедурной генерации клеток.
        self._world_seed = world_seed or "guardstar"

    def ensure_player_has_start(self, s: Session, *, player_id: uuid.UUID) -> None:
        planet = s.execute(select(Planet).where(Planet.owner_player_id == player_id)).scalar_one_or_none()
        if planet:
            return

        x = random.randint(-5, 5)
        y = random.randint(-5, 5)
        planet = Planet(owner_player_id=player_id, name="Terra Prime", pos_x=x, pos_y=y)
        s.add(planet)
        s.flush()

        s.add(Resource(planet_id=planet.id, metal=500, crystal=250, energy=100))
        s.add(Unit(owner_player_id=player_id, planet_id=planet.id, unit_type="scout", qty=5))
        s.add(Unit(owner_player_id=player_id, planet_id=planet.id, unit_type="fighter", qty=1))
        s.add(ResourceTick(planet_id=planet.id, last_collected_at=datetime.now(UTC)))

    def apply_resource_tick(self, s: Session, *, planet_id: uuid.UUID) -> None:
        res = s.execute(select(Resource).where(Resource.planet_id == planet_id)).scalar_one_or_none()
        if not res:
            return

        tick = s.execute(select(ResourceTick).where(ResourceTick.planet_id == planet_id)).scalar_one_or_none()
        now = datetime.now(UTC)
        if not tick:
            s.add(ResourceTick(planet_id=planet_id, last_collected_at=now))
            s.flush()
            return

        delta = now - tick.last_collected_at
        minutes = int(delta.total_seconds() // 60)
        if minutes <= 0:
            return

        # MVP-ставки (позже привяжем к зданиям/клеткам).
        # Делаем заметный прирост, чтобы это ощущалось при ручном тесте.
        res.metal += minutes * 60
        res.crystal += minutes * 30
        res.energy += minutes * 20
        tick.last_collected_at = now
        s.flush()

    def _hash_u32(self, x: int, y: int, z: int) -> int:
        raw = f"{self._world_seed}:{x}:{y}:{z}".encode("utf-8")
        d = hashlib.sha256(raw).digest()
        return int.from_bytes(d[:4], "big", signed=False)

    def get_cell_terrain(self, *, x: int, y: int, z: int) -> dict:
        """
        Процедурная (детерминированная) генерация содержимого.
        Сейчас это простые 'биомы/объекты', позже можно расширить до параметров.
        """
        r = self._hash_u32(x, y, z) % 1000

        # Базовое распределение.
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

        # Z-слой влияет на "состав" пространства.
        if z != 0:
            # В верх/низ слоях меньше "обычных" объектов и больше странностей.
            if terrain == "asteroids" and (r % 4 == 0):
                terrain, glyph = "empty", "."
            if terrain == "empty" and (r % 7 == 0):
                terrain, glyph = "anomaly", "?"

        return {"terrain": terrain, "glyph": glyph}

    def get_player_overview(self, s: Session, *, player_id: str) -> dict:
        pid = uuid.UUID(player_id)

        planet = s.execute(select(Planet).where(Planet.owner_player_id == pid)).scalar_one_or_none()
        if not planet:
            return {"player_id": player_id, "planets": []}

        self.apply_resource_tick(s, planet_id=planet.id)

        res = s.execute(select(Resource).where(Resource.planet_id == planet.id)).scalar_one_or_none()
        units = s.execute(select(Unit).where(Unit.planet_id == planet.id).order_by(Unit.unit_type)).scalars().all()

        return {
            "player_id": player_id,
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

    def get_sector_stub(self, s: Session, *, x: int | None, y: int | None, z: int = 0, player_id: str | None) -> dict:
        sector = {"x": x, "y": y, "z": z, "objects": [], "cell": None}
        if not player_id:
            return sector

        if x is None or y is None:
            return sector

        sector["cell"] = self.get_cell_terrain(x=x, y=y, z=z)

        pid = uuid.UUID(player_id)
        q = select(Planet).where(Planet.owner_player_id == pid)
        # Планеты пока живут только на z=0
        if z == 0:
            q = q.where(Planet.pos_x == x).where(Planet.pos_y == y)
        else:
            q = q.where(and_(False))

        planets = s.execute(q).scalars().all()
        for p in planets:
            sector["objects"].append({"type": "planet", "id": str(p.id), "name": p.name, "owner": str(p.owner_player_id)})

        # Флоты игрока в секторе
        fleets = (
            s.execute(
                select(Fleet).where(
                    Fleet.owner_player_id == pid,
                    Fleet.pos_x == x,
                    Fleet.pos_y == y,
                    Fleet.pos_z == z,
                )
            )
            .scalars()
            .all()
        )
        for f in fleets:
            sector["objects"].append({"type": "fleet", "id": str(f.id), "unit_type": f.unit_type, "qty": f.qty, "owner": str(f.owner_player_id)})
        return sector

    def get_player_map_window(self, s: Session, *, player_id: str, radius: int = 4, z: int = 0) -> dict:
        pid = uuid.UUID(player_id)

        planet = s.execute(select(Planet).where(Planet.owner_player_id == pid)).scalar_one_or_none()
        if not planet:
            return {"center": None, "radius": radius, "z": z, "cells": []}

        cx, cy = planet.pos_x, planet.pos_y
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
        by_pos: dict[tuple[int, int], list[dict]] = {}
        for p in planets:
            by_pos.setdefault((p.pos_x, p.pos_y), []).append(
                {"type": "planet", "id": str(p.id), "name": p.name, "owner": str(p.owner_player_id)}
            )

        fleets = (
            s.execute(
                select(Fleet).where(
                    Fleet.owner_player_id == pid,
                    Fleet.pos_z == z,
                    and_(Fleet.pos_x >= x0, Fleet.pos_x <= x1, Fleet.pos_y >= y0, Fleet.pos_y <= y1),
                )
            )
            .scalars()
            .all()
        )
        for f in fleets:
            by_pos.setdefault((f.pos_x, f.pos_y), []).append(
                {"type": "fleet", "id": str(f.id), "unit_type": f.unit_type, "qty": f.qty, "owner": str(f.owner_player_id)}
            )

        cells: list[dict] = []
        for y in range(y0, y1 + 1):
            row: list[dict] = []
            for x in range(x0, x1 + 1):
                objects = by_pos.get((x, y), [])
                terrain = self.get_cell_terrain(x=x, y=y, z=z)
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
                        },
                    }
                )
            cells.append({"y": y, "row": row})

        return {"center": {"x": cx, "y": cy}, "radius": radius, "z": z, "cells": cells}

    def move_one_scout_from_home(self, s: Session, *, player_id: str, target_x: int, target_y: int, target_z: int) -> dict:
        """
        MVP-действие: отправить 1 scout с домашней планеты в соседнюю клетку.
        Пока без времени полёта — создаём/обновляем fleet в целевой клетке.
        """
        pid = uuid.UUID(player_id)

        home = s.execute(select(Planet).where(Planet.owner_player_id == pid)).scalar_one_or_none()
        if not home:
            return {"ok": False, "error": "no_home_planet"}

        if target_z != 0:
            return {"ok": False, "error": "z_not_supported_yet"}

        dx = abs(target_x - home.pos_x)
        dy = abs(target_y - home.pos_y)
        if dx + dy != 1:
            return {"ok": False, "error": "target_not_adjacent"}

        scout = (
            s.execute(
                select(Unit).where(
                    Unit.owner_player_id == pid,
                    Unit.planet_id == home.id,
                    Unit.unit_type == "scout",
                )
            )
            .scalar_one_or_none()
        )
        if not scout or scout.qty < 1:
            return {"ok": False, "error": "not_enough_scouts"}

        scout.qty -= 1

        fleet = (
            s.execute(
                select(Fleet).where(
                    Fleet.owner_player_id == pid,
                    Fleet.pos_x == target_x,
                    Fleet.pos_y == target_y,
                    Fleet.pos_z == target_z,
                    Fleet.unit_type == "scout",
                )
            )
            .scalar_one_or_none()
        )
        if not fleet:
            fleet = Fleet(owner_player_id=pid, unit_type="scout", qty=1, pos_x=target_x, pos_y=target_y, pos_z=target_z)
            s.add(fleet)
        else:
            fleet.qty += 1

        s.flush()
        return {"ok": True}

