"""Фрагмент WorldService: главный тик, API состояния."""

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


class WorldServiceMixin06:
    def process_next_tick(self, s: Session) -> dict:
        ws = self.get_or_create_world_state(s)
        next_tick = ws.current_tick + 1
        events: list[dict] = []

        cleanup_expired_player_effects(s, before_tick=next_tick)

        # 0) Tech completion
        ready_techs = (
            s.execute(
                select(PlayerTech)
                .where(
                    PlayerTech.status == "in_progress",
                    PlayerTech.finish_tick <= next_tick,
                )
                .order_by(PlayerTech.created_at)
            )
            .scalars()
            .all()
        )
        for t in ready_techs:
            t.status = "done"
            events.append(
                {
                    "type": "tech_done",
                    "tech_id": t.tech_id,
                    "player_id": str(t.player_id),
                }
            )
            tech_nm = t.tech_id
            if self._balance and self._balance.pack:
                td = self._balance.pack.tech_by_id.get(t.tech_id)
                if (
                    isinstance(td, dict)
                    and isinstance(td.get("name"), str)
                    and td["name"].strip()
                ):
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
                .where(
                    FleetOrder.status.in_(["queued", "in_progress"]),
                    FleetOrder.finish_tick <= next_tick,
                )
                .order_by(FleetOrder.created_at)
            )
            .scalars()
            .all()
        )
        for order in ready_fleet_orders:
            order.status = "in_progress"
            fleet = (
                s.execute(
                    select(Fleet).where(
                        Fleet.id == order.fleet_id,
                        Fleet.owner_player_id == order.owner_player_id,
                    )
                )
                .scalars()
                .first()
            )
            if not fleet or fleet.qty < 1:
                order.status = "failed"
                events.append(
                    {
                        "type": "fleet_order_failed",
                        "order_id": str(order.id),
                        "reason": "fleet_unavailable",
                    }
                )
                continue

            if str(getattr(order, "order_type", "") or "") == "npc_transit":
                tx, ty, tz = (
                    int(order.target_x),
                    int(order.target_y),
                    int(order.target_z),
                )
                occ = (
                    s.execute(
                        select(Fleet).where(
                            Fleet.pos_x == tx,
                            Fleet.pos_y == ty,
                            Fleet.pos_z == tz,
                            Fleet.id != fleet.id,
                        )
                    )
                    .scalars()
                    .first()
                )
                if occ is not None:
                    pair = self._nearest_cell_without_other_fleet(
                        s,
                        center_x=tx,
                        center_y=ty,
                        center_z=tz,
                        exclude_fleet_id=fleet.id,
                    )
                    if pair:
                        tx, ty = int(pair[0]), int(pair[1])
                    else:
                        order.status = "done"
                        self._purge_fleet_row(s, fleet)
                        events.append(
                            {
                                "type": "fleet_order_failed",
                                "order_id": str(order.id),
                                "reason": "npc_transit_no_cell",
                            }
                        )
                        continue
                fleet.pos_x, fleet.pos_y, fleet.pos_z = tx, ty, tz
                order.status = "done"
                events.append(
                    {
                        "type": "fleet_order_done",
                        "order_id": str(order.id),
                        "fleet_id": str(fleet.id),
                    }
                )
                self._emit_event(
                    s,
                    tick=next_tick,
                    type="npc_transit_completed",
                    message=f"Гражданский конвой прибыл в ({tx},{ty},{tz}) и покинул сектор.",
                    payload={
                        "fleet_id": str(fleet.id),
                        "pos": {"x": tx, "y": ty, "z": tz},
                    },
                    player_id=fleet.owner_player_id,
                )
                self._purge_fleet_row(s, fleet)
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
                    if (
                        str(getattr(order, "order_type", "") or "")
                        == "emergency_return"
                    ):
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
                            payload={
                                "order_id": str(order.id),
                                "reason": "cell_occupied_by_own_fleet",
                            },
                            player_id=order.owner_player_id,
                        )
                        continue
                    order.status = "failed"
                    # Топливо уже списали при создании приказа; к прилёту цель занялась своим флотом — возвращаем стоимость этого перелёта.
                    pid_own = fleet.owner_player_id
                    fc_rf = 0
                    home_rf = s.execute(
                        select(Planet).where(Planet.owner_player_id == pid_own)
                    ).scalar_one_or_none()
                    res_rf = (
                        s.execute(
                            select(Resource).where(Resource.planet_id == home_rf.id)
                        ).scalar_one_or_none()
                        if home_rf
                        else None
                    )
                    if res_rf and hasattr(res_rf, "fuel"):
                        d_rf = abs(int(order.target_x) - int(order.from_x)) + abs(
                            int(order.target_y) - int(order.from_y)
                        )
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
                        fail_msg = (
                            f"{fail_msg} Топливо за перелёт возвращено: +{fc_rf}."
                        )
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
                    events.append(
                        {
                            "type": "fleet_order_done",
                            "order_id": str(order.id),
                            "fleet_id": str(fleet.id),
                        }
                    )
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
                        events.append(
                            {
                                "type": "fleet_order_done",
                                "order_id": str(order.id),
                                "fleet_id": str(fleet.id),
                            }
                        )
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
                                "hub": {
                                    "x": order.target_x,
                                    "y": order.target_y,
                                    "z": order.target_z,
                                },
                                "staging": {
                                    "x": pair[0],
                                    "y": pair[1],
                                    "z": fleet.pos_z,
                                },
                                "defender_fleet_id": str(occupant.id),
                            },
                            player_id=order.owner_player_id,
                        )
                        continue
                    order.status = "failed"
                    events.append(
                        {
                            "type": "fleet_order_failed",
                            "order_id": str(order.id),
                            "reason": "emergency_no_staging_cell",
                        }
                    )
                    self._emit_event(
                        s,
                        tick=next_tick,
                        type="fleet_order_failed",
                        message="Аварийный возврат: нет свободной клетки у хаба, занятого врагом.",
                        payload={
                            "order_id": str(order.id),
                            "reason": "emergency_no_staging_cell",
                        },
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
                        "target": {
                            "x": order.target_x,
                            "y": order.target_y,
                            "z": order.target_z,
                        },
                        "staging": {
                            "x": fleet.pos_x,
                            "y": fleet.pos_y,
                            "z": fleet.pos_z,
                        },
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
                events.append(
                    {"type": "combat_prompt_arrival", "order_id": str(order.id)}
                )
                continue

            fleet.pos_x = order.target_x
            fleet.pos_y = order.target_y
            fleet.pos_z = order.target_z
            order.status = "done"
            events.append(
                {
                    "type": "fleet_order_done",
                    "order_id": str(order.id),
                    "fleet_id": str(fleet.id),
                }
            )
            self._emit_event(
                s,
                tick=next_tick,
                type="fleet_arrived",
                message=f"Флот прибыл: {fleet.unit_type}×{fleet.qty} в ({fleet.pos_x},{fleet.pos_y},{fleet.pos_z})",
                payload={
                    "fleet_id": str(fleet.id),
                    "qty": fleet.qty,
                    "pos": {"x": fleet.pos_x, "y": fleet.pos_y, "z": fleet.pos_z},
                },
                player_id=order.owner_player_id,
            )

        ready_orders = (
            s.execute(
                select(UnitOrder)
                .where(
                    UnitOrder.status.in_(["queued", "in_progress"]),
                    UnitOrder.finish_tick <= next_tick,
                )
                .order_by(UnitOrder.created_at)
            )
            .scalars()
            .all()
        )

        for order in ready_orders:
            order.status = "in_progress"
            unit = s.execute(
                select(Unit).where(Unit.id == order.unit_id)
            ).scalar_one_or_none()
            if not unit or unit.qty < 1:
                # Если сток юнитов пуст, попробуем списать 1 из fleet в клетке from_* (MVP).
                source_fleet = (
                    s.execute(
                        select(Fleet).where(
                            Fleet.owner_player_id
                            == (unit.owner_player_id if unit else None),
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
                    events.append(
                        {
                            "type": "order_failed",
                            "order_id": str(order.id),
                            "reason": "unit_unavailable",
                        }
                    )
                    continue
                source_fleet.qty -= 1
            else:
                unit.qty -= 1

            fleet = s.execute(
                select(Fleet).where(
                    Fleet.owner_player_id == unit.owner_player_id,
                    Fleet.pos_x == order.target_x,
                    Fleet.pos_y == order.target_y,
                    Fleet.pos_z == order.target_z,
                    Fleet.unit_type == unit.unit_type,
                )
            ).scalar_one_or_none()
            if not fleet:
                fleet = Fleet(
                    owner_player_id=unit.owner_player_id,
                    unit_type=unit.unit_type,
                    qty=1,
                    pos_x=order.target_x,
                    pos_y=order.target_y,
                    pos_z=order.target_z,
                    name=self._next_fleet_default_name(
                        s, owner_id=unit.owner_player_id
                    ),
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
                    "target": {
                        "x": order.target_x,
                        "y": order.target_y,
                        "z": order.target_z,
                    },
                }
            )
            self._emit_event(
                s,
                tick=next_tick,
                type="order_done",
                message=f"Scout прибыл в сектор ({order.target_x},{order.target_y},{order.target_z})",
                payload={
                    "order_id": str(order.id),
                    "unit_id": str(unit.id),
                    "target": {
                        "x": order.target_x,
                        "y": order.target_y,
                        "z": order.target_z,
                    },
                },
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

        # Экономический блок тика (вынесено в сервис).
        from app.services.economy_service import EconomyService

        EconomyService(world=self).apply_economy_tick(
            s, tick=next_tick, influence_sources=inf_src
        )

        # MVP: upkeep после обработки ордеров, для всех игроков у кого есть флоты.
        owner_ids = s.execute(select(Fleet.owner_player_id).distinct()).scalars().all()
        for oid in owner_ids:
            self.apply_fleet_upkeep_tick(s, player_id=oid, tick=next_tick)

        self._apply_research_economy_tick(s, tick=next_tick)
        self._try_spawn_npc_transit_convoy(s, current_tick=int(next_tick))

        s.flush()
        return {
            "current_tick": ws.current_tick,
            "current_sol": int(ws.current_tick),
            "events": events,
        }

    def get_units_status(self, s: Session, *, player_id: str) -> dict:
        pid = uuid.UUID(player_id)
        home = s.execute(
            select(Planet).where(Planet.owner_player_id == pid)
        ).scalar_one_or_none()
        if not home:
            return {"units": []}

        units = (
            s.execute(
                select(Unit).where(Unit.owner_player_id == pid).order_by(Unit.unit_type)
            )
            .scalars()
            .all()
        )
        payload = []
        for unit in units:
            active_order = self._active_order_for_unit(s, unit_id=unit.id)
            status = "moving" if active_order else "idle"
            position = {"x": home.pos_x, "y": home.pos_y, "z": 0}
            if status == "moving" and active_order:
                position = {
                    "x": active_order.from_x,
                    "y": active_order.from_y,
                    "z": active_order.from_z,
                }

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
                            "from": {
                                "x": active_order.from_x,
                                "y": active_order.from_y,
                                "z": active_order.from_z,
                            },
                            "target": {
                                "x": active_order.target_x,
                                "y": active_order.target_y,
                                "z": active_order.target_z,
                            },
                            "start_tick": active_order.start_tick,
                            "finish_tick": active_order.finish_tick,
                        }
                        if active_order
                        else None
                    ),
                }
            )

        ws = self.get_or_create_world_state(s)
        return {
            "current_tick": ws.current_tick,
            "current_sol": int(ws.current_tick),
            "units": payload,
        }

    def get_world_state(
        self,
        s: Session,
        *,
        player_id: str,
        auto_tick_enabled: bool,
        auto_tick_interval_seconds: float,
    ) -> dict:
        pid = uuid.UUID(player_id)
        ws = self.get_or_create_world_state(s)
        self._resolve_expired_fleet_combat_prompts(s, tick=ws.current_tick, events=[])

        home = s.execute(
            select(Planet).where(Planet.owner_player_id == pid)
        ).scalar_one_or_none()
        if not home:
            pl0 = s.get(Player, pid)
            return {
                "current_tick": ws.current_tick,
                "current_sol": int(ws.current_tick),
                "player_id": str(pid),
                "auto_tick_enabled": auto_tick_enabled,
                "auto_tick_interval_seconds": auto_tick_interval_seconds,
                "unit": None,
                "pending_combat_prompts": [],
                "is_game_admin": bool(getattr(pl0, "is_game_admin", False)) if pl0 else False,
                "is_game_moderator": bool(getattr(pl0, "is_game_moderator", False)) if pl0 else False,
            }

        # Приоритет «главного» флота — больше скаутов в составе (для HUD/камеры).
        scout_fleet = None
        best_scouts = -1
        for f in s.execute(
            select(Fleet)
            .where(Fleet.owner_player_id == pid)
            .order_by(Fleet.created_at.asc())
        ).scalars():
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
            pos = {
                "x": scout_fleet.pos_x,
                "y": scout_fleet.pos_y,
                "z": scout_fleet.pos_z,
            }
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
            s.execute(
                select(Fleet)
                .where(Fleet.owner_player_id == pid)
                .order_by(Fleet.created_at.asc())
            )
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
        res = s.execute(
            select(Resource).where(Resource.planet_id == home.id)
        ).scalar_one_or_none()
        metal = int(res.metal) if res else 0
        crystal = int(res.crystal) if res else 0
        energy = int(res.energy) if res else 0
        fuel = int(getattr(res, "fuel", 0)) if res else 0
        food = int(getattr(res, "food", 0)) if res else 0
        water = int(getattr(res, "water", 0)) if res else 0

        inf_src_h = self._collect_influence_sources(s)
        dlt_home = self._planet_production_deltas(
            s, planet=home, influence_sources=inf_src_h
        )
        prod_per_tick = {k: int(dlt_home[k]) for k in PLANET_STORE_KEYS}

        fleets = (
            s.execute(select(Fleet).where(Fleet.owner_player_id == pid)).scalars().all()
        )
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
        pop_food_need, pop_water_need = self._population_vitals_upkeep_needs(
            population=home_pop
        )

        inf_sources_hud = self._collect_influence_sources(s)
        h_scores = self._influence_scores_at(
            inf_sources_hud, int(home.pos_x), int(home.pos_y), 0
        )
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
                for p in s.execute(select(Player).where(Player.id.in_(list(h_inf_ids))))
                .scalars()
                .all()
            }
        home_influence = self._influence_cell_payload(
            h_scores, pid, h_inf_owners, h_control_scores
        )

        energy_ticks_left = None
        if upkeep_energy > 0:
            energy_ticks_left = energy // upkeep_energy

        recent_events = (
            s.execute(
                select(Event)
                .where(Event.player_id == pid)
                .order_by(Event.id.desc())
                .limit(25)
            )
            .scalars()
            .all()
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

        from app.services.economy_service import EconomyService

        pl_row = s.get(Player, pid)
        rp_bal = float(getattr(pl_row, "research_points", 0) or 0) if pl_row else 0.0
        rp_per_sol = float(
            EconomyService(world=self)._player_rp_info(s, player_id=pid).per_sol
        )

        return {
            "current_tick": ws.current_tick,
            "current_sol": int(ws.current_tick),
            "player_id": str(pid),
            "is_game_admin": bool(getattr(pl_row, "is_game_admin", False)) if pl_row else False,
            "is_game_moderator": bool(getattr(pl_row, "is_game_moderator", False)) if pl_row else False,
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
                "research_points": round(rp_bal, 4),
                "research_points_per_sol": round(rp_per_sol, 4),
                "production_per_tick": {
                    "metal": prod_per_tick["metal"],
                    "crystal": prod_per_tick["crystal"],
                    "energy": prod_per_tick["energy"],
                    "fuel": prod_per_tick["fuel"],
                    "food": prod_per_tick["food"],
                    "water": prod_per_tick["water"],
                },
                "production_per_sol": {
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
                "population_vitals_per_sol": {
                    "food": pop_food_need,
                    "water": pop_water_need,
                },
                "upkeep_energy_per_tick": upkeep_energy,
                "upkeep_energy_per_sol": upkeep_energy,
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
            "pending_combat_prompts": self._pending_combat_prompts_payload(
                s, player_id=pid
            ),
        }

    def get_economy_summary(
        self, s: Session, *, player_id: str, include_external_buildings: bool = True
    ) -> dict:
        from app.services.economy_service import EconomyService

        return EconomyService(world=self).get_economy_summary(
            s,
            player_id=player_id,
            include_external_buildings=include_external_buildings,
        )
