from __future__ import annotations

"""Сервис форпостов.

Здесь будет логика: upkeep форпостов, логистика снабжения к ним, модули и авто-бой.
На первом шаге вынесены: содержание форпостов и логистика снабжения (еда/вода с хаба).
"""

import uuid
from datetime import datetime
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.outpost import Outpost
from app.db.models.planet import Planet
from app.db.models.player import Player
from app.db.models.resource import Resource
from app.services.supply_service import SupplyService


class OutpostService:
    def __init__(
        self,
        *,
        balance: object | None = None,
        supply: SupplyService,
        emit_event: Callable[..., None],
        outpost_definition: Callable[[str], dict],
        cell_is_owned_planet_tile: Callable[..., bool],
    ) -> None:
        self._balance = balance
        self._supply = supply
        self._emit_event = emit_event
        self._outpost_definition = outpost_definition
        self._cell_is_owned_planet_tile = cell_is_owned_planet_tile

    def supply_route_logistics_costs(self, *, hub: Planet, ox: int, oy: int) -> tuple[int, int]:
        """Еда/вода с хаба за содержание линии к форпосту за один сол (balance supply_route_upkeep)."""
        food, water = 2, 2
        extra_f, extra_w = 0, 0
        if self._balance and isinstance(getattr(getattr(self._balance, "pack", None), "economy", None), dict):
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

    def apply_supply_route_logistics_tick(self, s: Session, *, tick: int) -> None:
        """После выработки на планетах: логистика линий к форпостам (еда/вода с хаба)."""
        outposts = s.execute(select(Outpost).where(Outpost.status == "active")).scalars().all()
        if not outposts:
            return
        for op in outposts:
            if int(getattr(op, "z", 0) or 0) != 0:
                continue
            if self._cell_is_owned_planet_tile(s, owner_id=op.owner_player_id, x=int(op.x), y=int(op.y), z=0):
                continue
            if not self._supply.is_cell_supplied(
                s, owner_id=op.owner_player_id, x=int(op.x), y=int(op.y), z=int(op.z)
            ):
                continue
            hub = self._supply.supply_hub_planet_for_cell(
                s, owner_id=op.owner_player_id, x=int(op.x), y=int(op.y), z=int(op.z)
            )
            if not hub:
                continue
            need_f, need_w = self.supply_route_logistics_costs(hub=hub, ox=int(op.x), oy=int(op.y))
            # Расовые модификаторы (MVP): умножаем стоимость логистики снабжения.
            mul = 1.0
            if self._balance and getattr(getattr(self._balance, "pack", None), "races_by_id", None):
                pr = s.execute(select(Player.race_id).where(Player.id == op.owner_player_id)).scalar_one_or_none()
                if pr:
                    rd = self._balance.pack.races_by_id.get(str(pr))
                    mods = (rd.get("modifiers") if isinstance(rd, dict) else None) or {}
                    if isinstance(mods.get("supply_route_upkeep_multiplier"), (int, float)):
                        mul = float(mods["supply_route_upkeep_multiplier"])
            if mul <= 0:
                mul = 1.0
            need_f = int(round(need_f * mul))
            need_w = int(round(need_w * mul))
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

    def apply_outpost_upkeep_tick(self, s: Session, *, tick: int) -> None:
        """Содержание форпостов. При нехватке ресурсов — форпост уходит в offline и перестаёт давать эффект."""
        outposts = s.execute(select(Outpost).where(Outpost.status.in_(["active", "offline"]))).scalars().all()
        if not outposts:
            return

        # Ресурсы берём с домашней планеты владельца (пока "имперский склад").
        res_by_owner: dict[uuid.UUID, Resource] = {}
        for pid in {op.owner_player_id for op in outposts}:
            home = (
                s.execute(select(Planet).where(Planet.owner_player_id == pid).order_by(Planet.created_at.asc()))
                .scalar_one_or_none()
            )
            if not home:
                continue
            res = s.execute(select(Resource).where(Resource.planet_id == home.id)).scalar_one_or_none()
            if not res:
                continue
            res_by_owner[pid] = res

        for op in outposts:
            res = res_by_owner.get(op.owner_player_id)
            if not res:
                continue
            # Вне снабжения форпост выключается (не даёт эффект, пока не снабжён).
            if not self._supply.is_cell_supplied(
                s, owner_id=op.owner_player_id, x=int(op.x), y=int(op.y), z=int(op.z)
            ):
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
                        message="Форпост отключён (не хватает ресурсов на содержание)",
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
                    message="Форпост снова активен (содержание оплачено)",
                    payload={"outpost_id": str(op.id), "paid": need},
                    player_id=op.owner_player_id,
                )

