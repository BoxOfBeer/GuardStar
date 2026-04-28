from __future__ import annotations

import hashlib
import random
import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.db.models.fleet import Fleet
from app.db.models.game_clock import GameClock
from app.db.models.planet import Planet
from app.db.models.resource import Resource
from app.db.models.resource_tick import ResourceTick
from app.db.models.unit import Unit
from app.db.models.unit_order import UnitOrder


class WorldService:
    def __init__(self, *, world_seed: str = "guardstar") -> None:
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
        s.add(ResourceTick(planet_id=planet.id, last_collected_at=datetime.now(timezone.utc)))
        self.get_or_create_clock(s)

    def get_or_create_clock(self, s: Session) -> GameClock:
        clock = s.execute(select(GameClock).where(GameClock.id == 1)).scalar_one_or_none()
        if not clock:
            clock = GameClock(id=1, current_tick=0, updated_at=datetime.now(timezone.utc))
            s.add(clock)
            s.flush()
        return clock

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
        if z == 0:
            q = q.where(Planet.pos_x == x).where(Planet.pos_y == y)
        else:
            q = q.where(and_(False))

        planets = s.execute(q).scalars().all()
        for p in planets:
            sector["objects"].append({"type": "planet", "id": str(p.id), "name": p.name, "owner": str(p.owner_player_id)})

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

    def move_one_scout_from_home(self, s: Session, *, player_id: str, target_x: int, target_y: int, target_z: int) -> dict:
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

        if self._active_order_for_unit(s, unit_id=scout.id):
            return {"ok": False, "error": "active_order_exists"}

        clock = self.get_or_create_clock(s)
        order = UnitOrder(
            unit_id=scout.id,
            order_type="move",
            target_x=target_x,
            target_y=target_y,
            target_z=target_z,
            status="queued",
            start_tick=clock.current_tick + 1,
            finish_tick=clock.current_tick + 1,
        )
        s.add(order)
        s.flush()
        return {"ok": True, "order_id": str(order.id), "start_tick": order.start_tick, "finish_tick": order.finish_tick}

    def process_next_tick(self, s: Session) -> dict:
        clock = self.get_or_create_clock(s)
        next_tick = clock.current_tick + 1
        events: list[dict] = []

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
                order.status = "failed"
                events.append({"type": "order_failed", "order_id": str(order.id), "reason": "unit_unavailable"})
                continue

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

        clock.current_tick = next_tick
        clock.updated_at = datetime.now(timezone.utc)
        s.flush()
        return {"current_tick": clock.current_tick, "events": events}

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
            if status == "moving":
                position = {"x": active_order.target_x, "y": active_order.target_y, "z": active_order.target_z}

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
                            "target": {"x": active_order.target_x, "y": active_order.target_y, "z": active_order.target_z},
                            "start_tick": active_order.start_tick,
                            "finish_tick": active_order.finish_tick,
                        }
                        if active_order
                        else None
                    ),
                }
            )

        clock = self.get_or_create_clock(s)
        return {"current_tick": clock.current_tick, "units": payload}
