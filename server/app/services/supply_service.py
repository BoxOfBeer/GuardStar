from __future__ import annotations

"""Выделенный слой логистики снабжения.

Цель: постепенно разгружать WorldService, не ломая MVP. На первом шаге этот модуль
содержит фактическую логику снабжения (радиус, хаб, L-маршрут, обрыв чужим флотом),
которую WorldService использует как зависимость.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.building import Building
from app.db.models.fleet import Fleet
from app.db.models.planet import Planet
from app.db.models.player_tech import PlayerTech
from app.hex_coords import hex_distance, hex_line_cells_exclusive_start


class SupplyService:
    """Supply-related rules and helpers."""

    # Фаза A снабжения: счётчик на планете (supplier_count).
    SUPPLY_BASE_RADIUS = 5
    SUPPLY_PER_SUPPLIER = 3

    def __init__(self, *, balance: object | None = None) -> None:
        self._balance = balance

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

    def _supply_radius_modifiers_for_player(
        self, s: Session, *, player_id: uuid.UUID
    ) -> tuple[int, int]:
        """(base_add, per_supplier_add) из завершённых технологий."""
        if not self._balance:
            return (0, 0)
        base_add = 0
        per_add = 0
        for tid in self._get_player_done_techs(s, player_id=player_id):
            t = getattr(getattr(self._balance, "pack", None), "tech_by_id", {}).get(tid)
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

    def _supply_radius_modifiers_for_planet_buildings(
        self, s: Session, *, planet_id: uuid.UUID
    ) -> tuple[int, int]:
        """(base_add, per_supplier_add) из построек на планете."""
        if not self._balance:
            return (0, 0)
        base_add = 0
        per_add = 0
        rows = s.execute(
            select(Building.building_type, func.count(Building.id))
            .where(Building.planet_id == planet_id)
            .group_by(Building.building_type)
        ).all()
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

    def planet_supply_radius(
        self,
        s: Session,
        *,
        planet: Planet,
        player_supply_mods: tuple[int, int] | None = None,
    ) -> tuple[int, int, int]:
        """(effective_radius, effective_base, effective_per_supplier)

        Если передан ``player_supply_mods`` (base_add, per_add из техов игрока),
        повторный запрос ``PlayerTech`` на каждую планету не выполняется.
        """
        n = int(getattr(planet, "supplier_count", 0) or 0)
        if player_supply_mods is None:
            base_add_t, per_add_t = self._supply_radius_modifiers_for_player(
                s, player_id=planet.owner_player_id
            )
        else:
            base_add_t, per_add_t = player_supply_mods
        base_add_b, per_add_b = self._supply_radius_modifiers_for_planet_buildings(
            s, planet_id=planet.id
        )
        eff_base = int(self.SUPPLY_BASE_RADIUS) + int(base_add_t) + int(base_add_b)
        eff_per = int(self.SUPPLY_PER_SUPPLIER) + int(per_add_t) + int(per_add_b)
        eff_radius = max(0, int(eff_base + eff_per * n))
        return eff_radius, eff_base, eff_per

    def planet_supply_rows_for_owner(
        self, s: Session, *, owner_id: uuid.UUID
    ) -> list[tuple[Planet, int, int, int]]:
        """Один проход: планеты игрока и эффективный радиус снабжения по каждой.

        Кортеж: ``(planet, eff_radius, eff_base, eff_per)`` — для окна карты без
        N×M запросов к БД на каждую клетку.
        """
        planets = (
            s.execute(select(Planet).where(Planet.owner_player_id == owner_id))
            .scalars()
            .all()
        )
        if not planets:
            return []
        mods = self._supply_radius_modifiers_for_player(s, player_id=owner_id)
        out: list[tuple[Planet, int, int, int]] = []
        for p in planets:
            r, eb, ep = self.planet_supply_radius(
                s, planet=p, player_supply_mods=mods
            )
            out.append((p, int(r), int(eb), int(ep)))
        return out

    def enemy_fleet_positions_xy_in_bbox(
        self,
        s: Session,
        *,
        owner_id: uuid.UUID,
        x0: int,
        x1: int,
        y0: int,
        y1: int,
        z: int = 0,
    ) -> set[tuple[int, int]]:
        """Клетки (x,y), где стоит чужой живой флот, в ограничивающем прямоугольнике."""
        rows = s.execute(
            select(Fleet.pos_x, Fleet.pos_y).where(
                Fleet.pos_z == int(z),
                Fleet.qty > 0,
                Fleet.owner_player_id != owner_id,
                Fleet.pos_x >= int(x0),
                Fleet.pos_x <= int(x1),
                Fleet.pos_y >= int(y0),
                Fleet.pos_y <= int(y1),
            )
        ).all()
        return {(int(rx), int(ry)) for rx, ry in rows}

    def map_window_supply_precalc(
        self,
        s: Session,
        *,
        owner_id: uuid.UUID,
        x0: int,
        x1: int,
        y0: int,
        y1: int,
        z: int,
    ) -> tuple[list[tuple[Planet, int, int, int]], set[tuple[int, int]]]:
        """Для ``get_player_map_window``: хабы + множество чужих флотов в bbox путей снабжения."""
        if int(z) != 0:
            return [], set()
        rows = self.planet_supply_rows_for_owner(s, owner_id=owner_id)
        ex0, ex1, ey0, ey1 = int(x0), int(x1), int(y0), int(y1)
        for p, _r, _eb, _ep in rows:
            px, py = int(p.pos_x), int(p.pos_y)
            ex0 = min(ex0, px, int(x0))
            ex1 = max(ex1, px, int(x1))
            ey0 = min(ey0, py, int(y0))
            ey1 = max(ey1, py, int(y1))
        enemy = self.enemy_fleet_positions_xy_in_bbox(
            s,
            owner_id=owner_id,
            x0=ex0,
            x1=ex1,
            y0=ey0,
            y1=ey1,
            z=0,
        )
        return rows, enemy

    @staticmethod
    def is_cell_supplied_from_precalc(
        rows: list[tuple[Planet, int, int, int]],
        enemy_xy: set[tuple[int, int]],
        *,
        x: int,
        y: int,
        z: int,
    ) -> bool:
        """Та же семантика, что ``is_cell_supplied``, без запросов к БД."""
        if int(z) != 0:
            return False
        for p, r, _eff_base, _eff_per in rows:
            if r <= 0:
                continue
            d = hex_distance(int(p.pos_x), int(p.pos_y), int(x), int(y))
            if d > r:
                continue
            path = hex_line_cells_exclusive_start(
                int(p.pos_x), int(p.pos_y), int(x), int(y)
            )
            if any((int(cx), int(cy)) in enemy_xy for cx, cy in path):
                continue
            return True
        return False

    def supply_route_block_cell(
        self, s: Session, *, owner_id: uuid.UUID, path_cells: list[tuple[int, int]]
    ) -> tuple[int, int] | None:
        """Первая клетка пути с чужим флотом — обрыв линии снабжения."""
        for cx, cy in path_cells:
            hit = s.execute(
                select(Fleet.id).where(
                    Fleet.pos_x == int(cx),
                    Fleet.pos_y == int(cy),
                    Fleet.pos_z == 0,
                    Fleet.owner_player_id != owner_id,
                    Fleet.qty > 0,
                )
            ).first()
            if hit:
                return (int(cx), int(cy))
        return None

    def planet_supply_candidates(
        self, s: Session, *, owner_id: uuid.UUID, x: int, y: int
    ) -> list[tuple[Planet, int, int, int, int]]:
        """(planet, radius, distance, eff_base, eff_per_supplier)"""
        planets = (
            s.execute(select(Planet).where(Planet.owner_player_id == owner_id))
            .scalars()
            .all()
        )
        mods = (
            self._supply_radius_modifiers_for_player(s, player_id=owner_id)
            if planets
            else (0, 0)
        )
        rows: list[tuple[Planet, int, int, int, int]] = []
        for p in planets:
            r, eff_base, eff_per = self.planet_supply_radius(
                s, planet=p, player_supply_mods=mods
            )
            d = hex_distance(int(p.pos_x), int(p.pos_y), int(x), int(y))
            rows.append((p, int(r), int(d), int(eff_base), int(eff_per)))
        return rows

    def supply_hub_planet_for_cell(
        self, s: Session, *, owner_id: uuid.UUID, x: int, y: int, z: int
    ) -> Planet | None:
        """Планета-хаб, через которую клетка в снабжении (радиус + чистый L-путь)."""
        if int(z) != 0:
            return None
        rows = self.planet_supply_candidates(s, owner_id=owner_id, x=int(x), y=int(y))
        in_range = [(p, r, d, _b, _ps) for p, r, d, _b, _ps in rows if r > 0 and d <= r]
        for p, _r, _d, _b, _ps in sorted(in_range, key=lambda t: t[2]):
            path = hex_line_cells_exclusive_start(
                int(p.pos_x), int(p.pos_y), int(x), int(y)
            )
            if (
                self.supply_route_block_cell(s, owner_id=owner_id, path_cells=path)
                is None
            ):
                return p
        return None

    def is_cell_supplied(
        self, s: Session, *, owner_id: uuid.UUID, x: int, y: int, z: int
    ) -> bool:
        if int(z) != 0:
            return False
        rows = self.planet_supply_candidates(s, owner_id=owner_id, x=int(x), y=int(y))
        for p, r, d, _b, _ps in rows:
            if r <= 0 or d > r:
                continue
            path = hex_line_cells_exclusive_start(
                int(p.pos_x), int(p.pos_y), int(x), int(y)
            )
            if (
                self.supply_route_block_cell(s, owner_id=owner_id, path_cells=path)
                is None
            ):
                return True
        return False

    def get_supply_state(
        self, s: Session, *, player_id: str, x: int, y: int, z: int = 0
    ) -> dict:
        """Публичный контракт для GET /api/supply/state."""
        pid = uuid.UUID(player_id)
        if int(z) != 0:
            return {
                "ok": True,
                "in_supply": False,
                "nearest_hub": None,
                "supply_radius": 0,
                "distance": None,
                "route_clear": False,
                "route_blocked_at": None,
                "supply_path": "hex_line",
                "supply_base": int(self.SUPPLY_BASE_RADIUS),
                "supply_per_supplier": int(self.SUPPLY_PER_SUPPLIER),
            }

        rows = self.planet_supply_candidates(s, owner_id=pid, x=int(x), y=int(y))
        if not rows:
            return {
                "ok": True,
                "in_supply": False,
                "nearest_hub": None,
                "supply_radius": 0,
                "distance": None,
                "route_clear": False,
                "route_blocked_at": None,
                "supply_path": "hex_line",
                "supply_base": int(self.SUPPLY_BASE_RADIUS),
                "supply_per_supplier": int(self.SUPPLY_PER_SUPPLIER),
            }

        in_range = [(p, r, d, b, ps) for p, r, d, b, ps in rows if r > 0 and d <= r]
        best_blocked: tuple[int, int] | None = None
        best_tuple: tuple[Planet, int, int, int, int] | None = None

        if in_range:
            for p, r, d, b, ps in sorted(in_range, key=lambda t: t[2]):
                path = hex_line_cells_exclusive_start(
                    int(p.pos_x), int(p.pos_y), int(x), int(y)
                )
                blk = self.supply_route_block_cell(s, owner_id=pid, path_cells=path)
                if blk is None:
                    return {
                        "ok": True,
                        "in_supply": True,
                        "nearest_hub": {
                            "type": "planet",
                            "id": str(p.id),
                            "x": int(p.pos_x),
                            "y": int(p.pos_y),
                            "z": 0,
                        },
                        "supply_radius": int(r),
                        "distance": int(d),
                        "route_clear": True,
                        "route_blocked_at": None,
                        "supplier_count": int(getattr(p, "supplier_count", 0) or 0),
                        "supply_path": "hex_line",
                        "supply_base": int(b),
                        "supply_per_supplier": int(ps),
                    }
                if best_tuple is None:
                    best_tuple = (p, r, d, b, ps)
                    best_blocked = blk

            p, r, d, b, ps = (
                best_tuple if best_tuple else min(in_range, key=lambda t: t[2])
            )
            return {
                "ok": True,
                "in_supply": False,
                "nearest_hub": {
                    "type": "planet",
                    "id": str(p.id),
                    "x": int(p.pos_x),
                    "y": int(p.pos_y),
                    "z": 0,
                },
                "supply_radius": int(r),
                "distance": int(d),
                "route_clear": False,
                "route_blocked_at": (
                    {"x": best_blocked[0], "y": best_blocked[1]}
                    if best_blocked
                    else None
                ),
                "supplier_count": int(getattr(p, "supplier_count", 0) or 0),
                "supply_path": "hex_line",
                "supply_base": int(b),
                "supply_per_supplier": int(ps),
            }

        p, r, d, b, ps = min(rows, key=lambda t: t[2])
        return {
            "ok": True,
            "in_supply": False,
            "nearest_hub": {
                "type": "planet",
                "id": str(p.id),
                "x": int(p.pos_x),
                "y": int(p.pos_y),
                "z": 0,
            },
            "supply_radius": int(r),
            "distance": int(d),
            "route_clear": False,
            "route_blocked_at": None,
            "supplier_count": int(getattr(p, "supplier_count", 0) or 0),
            "supply_path": "hex_line",
            "supply_base": int(b),
            "supply_per_supplier": int(ps),
        }
