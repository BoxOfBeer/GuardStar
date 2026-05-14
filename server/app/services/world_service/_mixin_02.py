"""Фрагмент WorldService: часы мира, тики ресурсов/флота, обзор, производство."""

from __future__ import annotations

import copy
import math

from app.services.world_economy_runtime import deep_merge_eco
from app.services.world_service._deps import *  # noqa: F403
from app.hex_coords import hex_axial_neighbors, hex_distance
from app.services.world_service.constants import (
    BANDIT_PLAYER_ID,
    CIVILIAN_NPC_PLAYER_ID,
    DEFAULT_MAX_FLEET_UNITS,
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


class WorldServiceMixin02:
    def _world_blocks_new_fleets(self, s: Session) -> bool:
        """«Ядерный» стоп: `world_state.test_block_new_fleets` — всё, что завязано на мастер-флаг."""
        ws = s.get(WorldState, 1)
        return bool(ws and getattr(ws, "test_block_new_fleets", False))

    def _admin_master_spawn_block(self, s: Session) -> bool:
        return self._world_blocks_new_fleets(s)

    def _admin_block_player_fleet_create(self, s: Session) -> bool:
        if self._admin_master_spawn_block(s):
            return True
        ws = s.get(WorldState, 1)
        return bool(ws and getattr(ws, "admin_block_player_fleet_create", False))

    def _admin_block_npc_transit(self, s: Session) -> bool:
        if self._admin_master_spawn_block(s):
            return True
        ws = s.get(WorldState, 1)
        return bool(ws and getattr(ws, "admin_block_npc_transit", False))

    def _admin_block_bandit_mines(self, s: Session) -> bool:
        if self._admin_master_spawn_block(s):
            return True
        ws = s.get(WorldState, 1)
        return bool(ws and getattr(ws, "admin_block_bandit_mines", False))

    def _admin_block_bandit_outposts(self, s: Session) -> bool:
        if self._admin_master_spawn_block(s):
            return True
        ws = s.get(WorldState, 1)
        return bool(ws and getattr(ws, "admin_block_bandit_outposts", False))

    def _admin_block_bandit_extra_fleets(self, s: Session) -> bool:
        """Патруль-респавн, ударные звена, MVP-патруль у колонии (не стартовый патруль нового форпоста)."""
        if self._admin_master_spawn_block(s):
            return True
        ws = s.get(WorldState, 1)
        return bool(ws and getattr(ws, "admin_block_bandit_fleets", False))

    def _world_max_fleet_units(self, s: Session) -> int:
        ws = self.get_or_create_world_state(s)
        v = int(getattr(ws, "admin_max_fleet_units", 0) or 0)
        if v <= 0:
            return int(DEFAULT_MAX_FLEET_UNITS)
        return max(1, min(v, 500))

    def _merged_pack_economy(self, s: Session | None) -> dict:
        """Копия `economy` из баланса + `world_state.admin_economy_overrides_json` (рекурсивно).

        Затем фиксированные поля админки: базовая еда/вода с планеты за сол (перекрывают
        `base_planet_production` из файла и из JSON overrides).
        """
        eco: dict = {}
        if self._balance and isinstance(
            getattr(self._balance, "pack", None), object
        ):
            raw0 = self._balance.pack.economy
            if isinstance(raw0, dict):
                eco = copy.deepcopy(raw0)
        if s is None:
            return eco
        ws = s.get(WorldState, 1)
        raw = getattr(ws, "admin_economy_overrides_json", None) if ws else None
        if raw and str(raw).strip():
            try:
                patch = json.loads(raw)
            except Exception:
                patch = None
            else:
                if isinstance(patch, dict):
                    eco = deep_merge_eco(eco, patch)
        if ws is not None:
            bp = eco.get("base_planet_production")
            if isinstance(bp, dict):
                try:
                    f = int(getattr(ws, "economy_base_food_per_sol", 10) or 10)
                    w = int(getattr(ws, "economy_base_water_per_sol", 10) or 10)
                except (TypeError, ValueError):
                    f, w = 10, 10
                bp["food"] = max(0, min(f, 999))
                bp["water"] = max(0, min(w, 999))
        return eco

    def get_or_create_world_state(self, s: Session) -> WorldState:
        ws = s.execute(
            select(WorldState).where(WorldState.id == 1)
        ).scalar_one_or_none()
        if not ws:
            ws = WorldState(id=1, current_tick=0, updated_at=datetime.now(timezone.utc))
            s.add(ws)
            s.flush()
        return ws

    def get_or_create_clock(self, s: Session) -> GameClock:
        clock = s.execute(
            select(GameClock).where(GameClock.id == 1)
        ).scalar_one_or_none()
        if not clock:
            clock = GameClock(
                id=1, current_tick=0, updated_at=datetime.now(timezone.utc)
            )
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
        ui_channel: str | None = None,
        ui_dedupe_key: str | None = None,
    ) -> None:
        # Защита от аномально длинных строк (индексы/логи); полный контекст — в payload_json.
        _max_msg = 8192
        msg = str(message or "")
        if len(msg) > _max_msg:
            msg = msg[: _max_msg - 1] + "…"
        # Нормализуем payload: source для UI/аудита; ui_channel — «toast» vs полный лог.
        pl: dict = dict(payload) if isinstance(payload, dict) else {}
        if "source" not in pl:
            pl["source"] = "server_tick"
        if ui_channel:
            pl["ui_channel"] = ui_channel
        if ui_dedupe_key is not None:
            pl["ui_dedupe_key"] = ui_dedupe_key
        s.add(
            Event(
                tick=tick,
                type=type,
                message=msg,
                payload_json=json.dumps(pl, ensure_ascii=False) if pl else None,
                player_id=player_id,
            )
        )

    def apply_resource_tick(self, s: Session, *, planet_id: uuid.UUID) -> None:
        res = s.execute(
            select(Resource).where(Resource.planet_id == planet_id)
        ).scalar_one_or_none()
        if not res:
            return

        tick = s.execute(
            select(ResourceTick).where(ResourceTick.planet_id == planet_id)
        ).scalar_one_or_none()
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

    def apply_fleet_upkeep_tick(
        self, s: Session, *, player_id: uuid.UUID, tick: int
    ) -> None:
        # MVP: поддержание флота тратит ЛОКАЛЬНУЮ энергию флота (не энергию империи).
        if player_id in NPC_FLEET_PLAYER_IDS:
            return
        fleets = (
            s.execute(select(Fleet).where(Fleet.owner_player_id == player_id))
            .scalars()
            .all()
        )
        if not fleets:
            return
        for f in fleets:
            self._sync_fleet_energy_scale(s, f)
            units_map = self._fleet_units_map(s, f)
            if not units_map:
                continue
            if self._fleet_skip_local_energy_upkeep(s, f):
                continue
            cost = int(
                self._fleet_upkeep_energy_total(s, player_id=player_id, units=units_map)
            )
            if cost <= 0:
                continue
            cur = int(getattr(f, "energy", 0) or 0)
            cur = max(0, cur - cost)
            f.energy = cur
        s.flush()

    def _ru_fleet_maintenance_fail_message(
        self,
        *,
        fleet_name: str,
        need: dict[str, int],
        have: dict[str, int],
        penalty: int,
    ) -> str:
        """Короткий текст для игрока: дефицит снабжения со склада столицы; детали — в payload."""
        parts: list[str] = []
        for key, ru in (
            ("metal", "металл"),
            ("crystal", "кристаллы"),
            ("food", "еда"),
            ("water", "вода"),
        ):
            n = int(need.get(key, 0) or 0)
            if n <= 0:
                continue
            h = int(have.get(key, 0) or 0)
            parts.append(f"{ru}: есть {h}, нужно {n} за сол")
        if parts:
            detail = "; ".join(parts)
        else:
            detail = "на складе столицы не хватает ресурсов на снабжение за этот сол."
        pen = (
            f" Штраф на борт: −{int(penalty)} ⚡ за сол."
            if int(penalty or 0) > 0
            else ""
        )
        nm = (fleet_name or "").strip() or "флот"
        return f"Флот «{nm}»: не оплачено снабжение со склада столицы ({detail}){pen}"

    def _max_owner_planet_supply_radius(self, s: Session, *, owner_id: uuid.UUID) -> int:
        mx = int(getattr(self._supply, "SUPPLY_BASE_RADIUS", 5) or 5)
        for p in (
            s.execute(select(Planet).where(Planet.owner_player_id == owner_id))
            .scalars()
            .all()
        ):
            r, _, _ = self._supply.planet_supply_radius(s, planet=p)
            mx = max(mx, int(r))
        return min(max(mx, 3), 80)

    def _cell_blocked_for_emergency_staging(
        self,
        s: Session,
        *,
        owner_id: uuid.UUID,
        q: int,
        r: int,
        z: int,
        exclude_fleet_id: uuid.UUID | None,
    ) -> bool:
        """Нельзя ставить аварийный привал: планета, не снабжение, постройка, форпост, чужой/свой флот."""
        if (
            s.execute(
                select(Planet.id).where(Planet.pos_x == int(q), Planet.pos_y == int(r))
            ).first()
            is not None
        ):
            return True
        if not self._is_cell_supplied(
            s, owner_id=owner_id, x=int(q), y=int(r), z=int(z)
        ):
            return True
        if (
            s.execute(
                select(Building.id).where(
                    Building.x == int(q), Building.y == int(r), Building.z == int(z)
                )
            ).first()
            is not None
        ):
            return True
        if (
            s.execute(
                select(Outpost.id).where(
                    Outpost.x == int(q),
                    Outpost.y == int(r),
                    Outpost.z == int(z),
                    Outpost.status == "active",
                )
            ).first()
            is not None
        ):
            return True
        fq = select(Fleet.id).where(
            Fleet.pos_x == int(q),
            Fleet.pos_y == int(r),
            Fleet.pos_z == int(z),
            Fleet.qty > 0,
        )
        if exclude_fleet_id is not None:
            fq = fq.where(Fleet.id != exclude_fleet_id)
        return s.execute(fq).first() is not None

    def _nearest_supplied_emergency_staging_bfs(
        self,
        s: Session,
        *,
        owner_id: uuid.UUID,
        from_x: int,
        from_y: int,
        exclude_fleet_id: uuid.UUID,
        max_radius: int = 400,
    ) -> tuple[int, int, int] | None:
        """Ближайшая к флоту свободная клетка в снабжении: без планеты, флота, полевых построек, форпоста.

        Расширяющийся по гекс-расстоянию обход от позиции флота (не только диск вокруг одного хаба).
        """
        sx, sy = int(from_x), int(from_y)
        cap = max(16, min(int(max_radius), 600))
        frontier: list[tuple[int, int]] = [(sx, sy)]
        seen: set[tuple[int, int]] = {(sx, sy)}
        for dist in range(0, cap + 1):
            next_frontier: list[tuple[int, int]] = []
            for x, y in frontier:
                if not self._cell_blocked_for_emergency_staging(
                    s,
                    owner_id=owner_id,
                    q=int(x),
                    r=int(y),
                    z=0,
                    exclude_fleet_id=exclude_fleet_id,
                ):
                    return (int(x), int(y), 0)
                if dist >= cap:
                    continue
                for nx, ny in hex_axial_neighbors(int(x), int(y)):
                    t = (nx, ny)
                    if t in seen:
                        continue
                    seen.add(t)
                    next_frontier.append(t)
            frontier = next_frontier
            if not frontier:
                break
        return None

    def _capital_planet_for_player(
        self, s: Session, *, player_id: uuid.UUID
    ) -> Planet | None:
        cap = (
            s.execute(
                select(Planet)
                .where(
                    Planet.owner_player_id == player_id,
                    Planet.is_colonized == True,  # noqa: E712
                    Planet.is_capital == True,  # noqa: E712
                )
                .order_by(Planet.created_at.asc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if cap:
            return cap
        return (
            s.execute(
                select(Planet)
                .where(
                    Planet.owner_player_id == player_id,
                    Planet.is_colonized == True,  # noqa: E712
                )
                .order_by(Planet.created_at.asc())
                .limit(1)
            )
            .scalars()
            .first()
        )

    def _fleet_empire_overhead_per_sol(self) -> dict[str, int]:
        keys = ("metal", "crystal", "food", "water")
        z = {k: 0 for k in keys}
        if not self._balance:
            return z
        eco = getattr(self._balance.pack, "economy", None)
        eco = eco if isinstance(eco, dict) else {}
        blk = eco.get("fleet_empire_upkeep")
        blk = blk if isinstance(blk, dict) else {}
        z["metal"] = max(0, int(blk.get("metal_per_sol_per_fleet", 0) or 0))
        z["crystal"] = max(0, int(blk.get("crystal_per_sol_per_fleet", 0) or 0))
        z["food"] = max(0, int(blk.get("food_per_sol_per_fleet", 0) or 0))
        z["water"] = max(0, int(blk.get("water_per_sol_per_fleet", 0) or 0))
        return z

    def _fleet_empire_uniform_per_ship_addon(self, *, ships: int) -> dict[str, int]:
        """Равномерная надбавка за любой корпус (economy.*_per_sol_per_ship); суммируется с units.upkeep.empire_per_sol."""
        keys = ("metal", "crystal", "food", "water")
        z = {k: 0 for k in keys}
        sc = max(0, int(ships))
        if sc <= 0 or not self._balance:
            return z
        eco = getattr(self._balance.pack, "economy", None)
        eco = eco if isinstance(eco, dict) else {}
        blk = eco.get("fleet_empire_upkeep")
        blk = blk if isinstance(blk, dict) else {}
        z["metal"] = max(0, int(blk.get("metal_per_sol_per_ship", 0) or 0)) * sc
        z["crystal"] = max(0, int(blk.get("crystal_per_sol_per_ship", 0) or 0)) * sc
        z["food"] = max(0, int(blk.get("food_per_sol_per_ship", 0) or 0)) * sc
        z["water"] = max(0, int(blk.get("water_per_sol_per_ship", 0) or 0)) * sc
        return z

    def _fleet_empire_supply_need_for_fleet(self, s: Session, *, fleet: Fleet) -> dict[str, int]:
        keys = ("metal", "crystal", "food", "water")
        zero = {k: 0 for k in keys}
        if self._fleet_total_units(s, fleet) <= 0:
            return zero
        units_map = self._fleet_units_map(s, fleet)
        if not units_map:
            return zero
        oh = self._fleet_empire_overhead_per_sol()
        ships = sum(max(0, int(q)) for q in units_map.values())
        uni = self._fleet_empire_uniform_per_ship_addon(ships=ships)
        if not self._balance:
            return {k: int(oh.get(k, 0)) + int(uni.get(k, 0)) for k in keys}
        rid = self._get_player_race_id(s, player_id=fleet.owner_player_id)
        techs = self._get_player_done_techs(s, player_id=fleet.owner_player_id)
        ucost = self._balance.calc_units_empire_supply_upkeep(
            units=units_map, race_id=rid, techs=techs
        )
        return {
            k: int(oh.get(k, 0)) + int(uni.get(k, 0)) + int(ucost.get(k, 0) or 0)
            for k in keys
        }

    def _fleet_empire_upkeep_unpaid_penalty_energy(self) -> int:
        eco = (
            self._balance.pack.economy
            if self._balance
            and isinstance(getattr(self._balance, "pack", None), object)
            else {}
        )
        blk = eco.get("fleet_empire_upkeep") if isinstance(eco, dict) else None
        if not isinstance(blk, dict):
            return 25
        return max(0, int(blk.get("energy_penalty_on_unpaid", 25) or 25))

    def _apply_fleet_empire_upkeep_tick(self, s: Session, *, tick: int) -> None:
        """Имперское снабжение флота: металл/кристалл/еда/вода с капитала (не локальная энергия).

        Учитывается состав каждого флота (units.upkeep.empire_per_sol × qty) и опционально
        ровная надбавка economy.*_per_sol_per_ship/fleet.

        Если не хватает любого ресурса — штраф энергии флоту и событие.
        """
        if not self._balance:
            return
        penalty = self._fleet_empire_upkeep_unpaid_penalty_energy()

        owner_ids: set[uuid.UUID] = set()
        for f in s.execute(select(Fleet)).scalars().all():
            if f.owner_player_id in NPC_FLEET_PLAYER_IDS:
                continue
            if self._fleet_total_units(s, f) <= 0:
                continue
            owner_ids.add(f.owner_player_id)

        for oid in owner_ids:
            cap = self._capital_planet_for_player(s, player_id=oid)
            if not cap:
                continue
            res = s.execute(
                select(Resource).where(Resource.planet_id == cap.id)
            ).scalar_one_or_none()
            if not res:
                continue

            fleets = (
                s.execute(
                    select(Fleet)
                    .where(Fleet.owner_player_id == oid)
                    .order_by(Fleet.created_at.asc(), Fleet.id.asc())
                )
                .scalars()
                .all()
            )
            for f in fleets:
                if self._fleet_total_units(s, f) <= 0:
                    continue
                need = self._fleet_empire_supply_need_for_fleet(s, fleet=f)
                if all(int(need.get(k, 0) or 0) <= 0 for k in need):
                    continue

                have_m = int(getattr(res, "metal", 0) or 0)
                have_c = int(getattr(res, "crystal", 0) or 0)
                have_f = int(getattr(res, "food", 0) or 0)
                have_w = int(getattr(res, "water", 0) or 0)
                nm, nc = int(need["metal"]), int(need["crystal"])
                nf, nw = int(need["food"]), int(need["water"])
                if (
                    have_m >= nm
                    and have_c >= nc
                    and have_f >= nf
                    and have_w >= nw
                ):
                    res.metal = have_m - nm
                    res.crystal = have_c - nc
                    res.food = have_f - nf
                    res.water = have_w - nw
                    continue

                if penalty > 0:
                    cur = int(getattr(f, "energy", 0) or 0)
                    f.energy = max(0, cur - penalty)
                self._emit_event(
                    s,
                    tick=tick,
                    type="fleet_maintenance_failed",
                    message=self._ru_fleet_maintenance_fail_message(
                        fleet_name=str(f.name or f.unit_type or "флот"),
                        need=need,
                        have={
                            "metal": have_m,
                            "crystal": have_c,
                            "food": have_f,
                            "water": have_w,
                        },
                        penalty=penalty,
                    ),
                    payload={
                        "fleet_id": str(f.id),
                        "capital_planet_id": str(cap.id),
                        "need": need,
                        "have": {
                            "metal": have_m,
                            "crystal": have_c,
                            "food": have_f,
                            "water": have_w,
                        },
                        "penalty_energy": penalty,
                    },
                    player_id=oid,
                    ui_channel="toast",
                    ui_dedupe_key=f"fleet_maintenance:{f.id}",
                )
        s.flush()

    def _apply_bandit_fleet_empire_upkeep_tick(self, s: Session, *, tick: int) -> None:
        """Имперское снабжение флотов корсаров: склад форпоста в зоне логистики, иначе штраф ⚡."""
        if not self._balance:
            return
        penalty = self._fleet_empire_upkeep_unpaid_penalty_energy()
        wc = self._warfare_economy(s)
        sr = max(5, int(float(wc.get("bandit_supply_radius_hex", 25) or 25)))

        for f in s.execute(select(Fleet)).scalars().all():
            if f.owner_player_id != BANDIT_PLAYER_ID:
                continue
            if self._fleet_total_units(s, f) <= 0:
                continue
            op = self._bandit_fleet_home_outpost(s, f)
            need = self._fleet_empire_supply_need_for_fleet(s, fleet=f)
            if all(int(need.get(k, 0) or 0) <= 0 for k in need):
                continue
            if op is None:
                if penalty > 0:
                    cur = int(getattr(f, "energy", 0) or 0)
                    f.energy = max(0, cur - penalty)
                continue
            ox, oy = int(op.x), int(op.y)
            in_zone = hex_distance(int(f.pos_x), int(f.pos_y), ox, oy) <= sr
            if not in_zone:
                if penalty > 0:
                    cur = int(getattr(f, "energy", 0) or 0)
                    f.energy = max(0, cur - penalty)
                continue
            have_m = int(getattr(op, "bandit_store_metal", 0) or 0)
            have_c = int(getattr(op, "bandit_store_crystal", 0) or 0)
            have_f = int(getattr(op, "bandit_store_food", 0) or 0)
            have_w = int(getattr(op, "bandit_store_water", 0) or 0)
            nm, nc = int(need["metal"]), int(need["crystal"])
            nf, nw = int(need["food"]), int(need["water"])
            if (
                have_m >= nm
                and have_c >= nc
                and have_f >= nf
                and have_w >= nw
            ):
                op.bandit_store_metal = have_m - nm
                op.bandit_store_crystal = have_c - nc
                op.bandit_store_food = have_f - nf
                op.bandit_store_water = have_w - nw
                continue
            if penalty > 0:
                cur = int(getattr(f, "energy", 0) or 0)
                f.energy = max(0, cur - penalty)
        s.flush()

    def _apply_fleet_energy_tick(self, s: Session, *, tick: int) -> None:
        """Реген/пополнение энергии флота.

        Принцип: энергия появляется только если есть снабжение или "хаб" (планета/форпост).
        """
        fleets = s.execute(select(Fleet)).scalars().all()
        if not fleets:
            return
        for f in fleets:
            if self._fleet_total_units(s, f) <= 0:
                continue
            self._sync_fleet_energy_scale(s, f)
            if f.owner_player_id in NPC_FLEET_PLAYER_IDS:
                if f.owner_player_id == BANDIT_PLAYER_ID and self._balance:
                    wc = self._warfare_economy(s)
                    if self._bandit_fleet_in_logistics_supply(s, f, wc):
                        mx = int(
                            getattr(f, "max_energy", FLEET_ENERGY_MAX_FLOOR)
                            or FLEET_ENERGY_MAX_FLOOR
                        )
                        cur = int(getattr(f, "energy", 0) or 0)
                        reg = max(2, int((mx + 24) // 25))
                        f.energy = min(mx, cur + reg)
                    else:
                        mx = int(
                            getattr(f, "max_energy", FLEET_ENERGY_MAX_FLOOR)
                            or FLEET_ENERGY_MAX_FLOOR
                        )
                        cur = int(getattr(f, "energy", 0) or 0)
                        mul = float(
                            self._race_modifiers(s, player_id=f.owner_player_id).get(
                                "fleet_unsupplied_energy_decay_multiplier", 1.0
                            )
                        )
                        mul = 1.0 if mul <= 0 else mul
                        decay = max(1, int(round(1 * mul)))
                        f.energy = max(0, cur - decay)
                else:
                    mx = int(
                        getattr(f, "max_energy", FLEET_ENERGY_MAX_FLOOR)
                        or FLEET_ENERGY_MAX_FLOOR
                    )
                    f.energy = mx
                continue
            mx = int(getattr(f, "max_energy", FLEET_ENERGY_MAX_FLOOR) or FLEET_ENERGY_MAX_FLOOR)
            cur = int(getattr(f, "energy", 0) or 0)
            # Хаб пополнения: на своей планете или у активного (и снабжённого) форпоста.
            on_planet = (
                int(getattr(f, "pos_z", 0) or 0) == 0
                and s.execute(
                    select(Planet.id).where(
                        Planet.owner_player_id == f.owner_player_id,
                        Planet.pos_x == int(f.pos_x),
                        Planet.pos_y == int(f.pos_y),
                    )
                ).first()
            )
            on_outpost = (
                s.execute(
                    select(Outpost.id).where(
                        Outpost.owner_player_id == f.owner_player_id,
                        Outpost.x == int(f.pos_x),
                        Outpost.y == int(f.pos_y),
                        Outpost.z == int(getattr(f, "pos_z", 0) or 0),
                        Outpost.status == "active",
                    )
                ).first()
                is not None
            )
            if on_planet or on_outpost:
                f.energy = mx
                continue

            # Реген только в снабжении. Вне снабжения — лёгкая деградация энергии (стиль игры).
            if self._is_cell_supplied(
                s,
                owner_id=f.owner_player_id,
                x=int(f.pos_x),
                y=int(f.pos_y),
                z=int(getattr(f, "pos_z", 0) or 0),
            ):
                # Масштаб с ёмкостью: крупный флот быстрее набирает заряд в сети снабжения.
                reg = max(2, int((mx + 24) // 25))
                f.energy = min(mx, cur + reg)
            else:
                # Базовый расход 1/тик, раса может усиливать/ослаблять.
                mul = float(
                    self._race_modifiers(s, player_id=f.owner_player_id).get(
                        "fleet_unsupplied_energy_decay_multiplier", 1.0
                    )
                )
                mul = 1.0 if mul <= 0 else mul
                decay = max(1, int(round(1 * mul)))
                f.energy = max(0, cur - decay)
        s.flush()

    def _nearest_return_hub(
        self, s: Session, *, owner_id: uuid.UUID, x: int, y: int, z: int
    ) -> tuple[int, int, int] | None:
        """Ближайшая точка пополнения: своя планета или активный форпост.

        Предпочитаем хаб без флота в клетке (чтобы аварийный возврат не упирался в занятую клетку).
        Если все хабы заняты — ближайший по Манхэттену (дальше обработка ордера).
        """
        if int(z) != 0:
            return None
        hubs: list[tuple[int, int, int]] = []
        for p in (
            s.execute(select(Planet).where(Planet.owner_player_id == owner_id))
            .scalars()
            .all()
        ):
            hubs.append((int(p.pos_x), int(p.pos_y), 0))
        for op in (
            s.execute(
                select(Outpost).where(
                    Outpost.owner_player_id == owner_id,
                    Outpost.z == 0,
                    Outpost.status == "active",
                )
            )
            .scalars()
            .all()
        ):
            hubs.append((int(op.x), int(op.y), int(op.z)))
        if not hubs:
            return None
        scored: list[tuple[int, tuple[int, int, int]]] = []
        for hx, hy, hz in hubs:
            d = hex_distance(int(hx), int(hy), int(x), int(y))
            scored.append((d, (int(hx), int(hy), int(hz))))
        scored.sort(key=lambda t: t[0])
        for _d, (hx, hy, hz) in scored:
            blocked = (
                s.execute(
                    select(Fleet.id).where(
                        Fleet.pos_x == int(hx),
                        Fleet.pos_y == int(hy),
                        Fleet.pos_z == int(hz),
                    )
                ).first()
                is not None
            )
            if not blocked:
                return (hx, hy, hz)
        return scored[0][1]

    def _fleet_adjacent_to_enemy_occupied_hub(
        self, s: Session, *, fleet: Fleet
    ) -> bool:
        """Флот на соседней с хабом клетке, а клетка хаба занята чужим флотом.

        Иначе каждый тик создаётся новый emergency_return до хаба (осцилляция).
        """
        owner_id = fleet.owner_player_id
        if int(getattr(fleet, "pos_z", 0) or 0) != 0:
            return False
        fx, fy = int(fleet.pos_x), int(fleet.pos_y)
        hubs: list[tuple[int, int, int]] = []
        for p in (
            s.execute(select(Planet).where(Planet.owner_player_id == owner_id))
            .scalars()
            .all()
        ):
            hubs.append((int(p.pos_x), int(p.pos_y), 0))
        for op in (
            s.execute(
                select(Outpost).where(
                    Outpost.owner_player_id == owner_id,
                    Outpost.z == 0,
                    Outpost.status == "active",
                )
            )
            .scalars()
            .all()
        ):
            hubs.append((int(op.x), int(op.y), int(op.z)))
        for hx, hy, hz in hubs:
            foe = (
                s.execute(
                    select(Fleet).where(
                        Fleet.pos_x == int(hx),
                        Fleet.pos_y == int(hy),
                        Fleet.pos_z == int(hz),
                        Fleet.owner_player_id != owner_id,
                    )
                )
                .scalars()
                .first()
            )
            if not foe:
                continue
            if hex_distance(fx, fy, int(hx), int(hy)) == 1:
                return True
        return False

    def _apply_emergency_return_orders(self, s: Session, *, tick: int) -> None:
        """Если флот без энергии и не в снабжении — аварийный приказ к пустой клетке в зоне снабжения у хаба.

        Это "буксировка/аварийный режим": не требует топлива и энергии на постановку.
        """
        fleets = s.execute(select(Fleet)).scalars().all()
        if not fleets:
            return
        ws = self.get_or_create_world_state(s)
        for f in fleets:
            if self._fleet_total_units(s, f) <= 0:
                continue
            if f.owner_player_id in NPC_FLEET_PLAYER_IDS:
                continue
            if int(getattr(f, "pos_z", 0) or 0) != 0:
                continue
            if int(getattr(f, "energy", 0) or 0) > 0:
                continue
            # если в снабжении — энергия скоро появится, не дёргаем
            if self._is_cell_supplied(
                s, owner_id=f.owner_player_id, x=int(f.pos_x), y=int(f.pos_y), z=0
            ):
                continue
            if self._active_order_for_fleet(s, fleet_id=f.id):
                continue
            if self._fleet_adjacent_to_enemy_occupied_hub(s, fleet=f):
                continue
            hub = self._nearest_return_hub(
                s, owner_id=f.owner_player_id, x=int(f.pos_x), y=int(f.pos_y), z=0
            )
            if not hub:
                continue
            hx, hy, hz = hub
            staging = self._nearest_supplied_emergency_staging_bfs(
                s,
                owner_id=f.owner_player_id,
                from_x=int(f.pos_x),
                from_y=int(f.pos_y),
                exclude_fleet_id=f.id,
            )
            if not staging:
                continue
            tx, ty, tz = int(staging[0]), int(staging[1]), int(staging[2])
            if int(tx) == int(f.pos_x) and int(ty) == int(f.pos_y) and int(tz) == 0:
                continue
            dist = hex_distance(int(tx), int(ty), int(f.pos_x), int(f.pos_y))
            travel_ticks = max(1, dist)  # аварийно медленно: 1 клетка/тик
            order = FleetOrder(
                fleet_id=f.id,
                owner_player_id=f.owner_player_id,
                order_type="emergency_return",
                from_x=int(f.pos_x),
                from_y=int(f.pos_y),
                from_z=int(getattr(f, "pos_z", 0) or 0),
                target_x=int(tx),
                target_y=int(ty),
                target_z=0,
                qty=int(f.qty),
                status="queued",
                start_tick=int(ws.current_tick) + 1,
                finish_tick=int(ws.current_tick) + int(travel_ticks),
                force_attack=False,
                combat_prompt_expires_at=None,
            )
            s.add(order)
            s.flush()
            hub_note = (
                f" (хаб {hx},{hy})"
                if int(tx) != int(hx) or int(ty) != int(hy)
                else ""
            )
            self._emit_event(
                s,
                tick=int(ws.current_tick),
                type="fleet_emergency_return",
                message=(
                    f"Аварийный возврат в снабжение: флот → ({tx},{ty}){hub_note} "
                    f"(нет энергии вне сети; ближайшая свободная клетка снабжения)"
                ),
                payload={
                    "order_id": str(order.id),
                    "fleet_id": str(f.id),
                    "target": {"x": tx, "y": ty, "z": tz},
                },
                player_id=f.owner_player_id,
            )

    def _hash_u32(self, x: int, y: int, z: int) -> int:
        raw = f"{self._world_seed}:{x}:{y}:{z}".encode("utf-8")
        d = hashlib.sha256(raw).digest()
        return int.from_bytes(d[:4], "big", signed=False)

    def get_cell_terrain(
        self, *, x: int, y: int, z: int, s: Session | None = None
    ) -> dict:
        if s is not None and int(z) == 0:
            hit = s.execute(
                select(Planet.id).where(
                    Planet.pos_x == int(x),
                    Planet.pos_y == int(y),
                )
            ).first()
            if hit:
                return {"terrain": "planet", "glyph": "P"}
        r = self._hash_u32(x, y, z) % 1000

        if r < 650:
            terrain = "empty"
            glyph = "."
        elif r < 820:
            terrain = "asteroids"
            glyph = "A"
        elif r < 910:
            terrain = "nebula"
            glyph = "≋"
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
        planets = (
            s.execute(
                select(Planet)
                .where(Planet.owner_player_id == pid)
                .order_by(Planet.is_capital.desc(), Planet.created_at.asc())
            )
            .scalars()
            .all()
        )
        if not planets:
            return {
                "player_id": player_id,
                "display_name": player.display_name if player else player_id,
                "planets": [],
                "is_game_admin": bool(getattr(player, "is_game_admin", False)) if player else False,
                "is_game_moderator": bool(getattr(player, "is_game_moderator", False))
                if player
                else False,
            }

        out_planets: list[dict] = []
        for planet in planets:
            pcl = str(getattr(planet, "planet_class", "") or "earthlike")
            is_cap = bool(getattr(planet, "is_capital", False))
            is_col = bool(getattr(planet, "is_colonized", True))
            if not is_col:
                out_planets.append(
                    {
                        "id": str(planet.id),
                        "name": planet.name,
                        "planet_class": pcl,
                        "is_capital": is_cap,
                        "is_colonized": False,
                        "pos": {"x": planet.pos_x, "y": planet.pos_y},
                        "status_ru": "не колонизирована",
                        "resources": None,
                        "units": [],
                    }
                )
                continue
            res = s.execute(
                select(Resource).where(Resource.planet_id == planet.id)
            ).scalar_one_or_none()
            units = (
                s.execute(
                    select(Unit)
                    .where(Unit.planet_id == planet.id)
                    .order_by(Unit.unit_type)
                )
                .scalars()
                .all()
            )
            out_planets.append(
                {
                    "id": str(planet.id),
                    "name": planet.name,
                    "planet_class": pcl,
                    "is_capital": is_cap,
                    "is_colonized": True,
                    "pos": {"x": planet.pos_x, "y": planet.pos_y},
                    "resources": {
                        "metal": res.metal if res else 0,
                        "crystal": res.crystal if res else 0,
                        "energy": res.energy if res else 0,
                        "fuel": int(getattr(res, "fuel", 0)) if res else 0,
                        "food": int(getattr(res, "food", 0)) if res else 0,
                        "water": int(getattr(res, "water", 0)) if res else 0,
                    },
                    "units": [{"unit_type": u.unit_type, "qty": u.qty} for u in units],
                }
            )

        return {
            "player_id": player_id,
            "display_name": player.display_name if player else player_id,
            "planets": out_planets,
            "is_game_admin": bool(getattr(player, "is_game_admin", False)) if player else False,
            "is_game_moderator": bool(getattr(player, "is_game_moderator", False)) if player else False,
        }

    def _planet_production_deltas(
        self, s: Session, *, planet: Planet, influence_sources: list[dict] | None = None
    ) -> dict[str, int]:
        from app.services.world_service.constants import WORLD_NEUTRAL_PLAYER_ID

        if not bool(getattr(planet, "is_colonized", True)):
            return {k: 0 for k in PLANET_STORE_KEYS}
        if planet.owner_player_id == WORLD_NEUTRAL_PLAYER_ID:
            return {k: 0 for k in PLANET_STORE_KEYS}
        if self._balance:
            eco_m = self._merged_pack_economy(s)
            bp = eco_m.get("base_planet_production")
            if isinstance(bp, dict):
                keys = ("metal", "crystal", "energy", "fuel", "food", "water")
                base = {k: int(bp.get(k, 0)) for k in keys}
            else:
                base = self._balance.get_base_production()
        else:
            prod = calc_planet_production()
            base = {
                "metal": int(prod.metal_per_tick),
                "crystal": int(prod.crystal_per_tick),
                "energy": int(prod.energy_per_tick),
                "fuel": int(prod.fuel_per_tick),
                "food": int(prod.food_per_tick),
                "water": int(prod.water_per_tick),
            }

        rm0 = self._race_modifiers(s, player_id=planet.owner_player_id)
        if rm0.get("no_passive_planet_food_water"):
            base["food"] = 0
            base["water"] = 0

        bonus = {k: 0 for k in PLANET_STORE_KEYS}
        ws = self.get_or_create_world_state(s)
        tick = int(getattr(ws, "current_tick", 0) or 0)
        if self._balance:
            b_rows = (
                s.execute(
                    select(Building).where(
                        Building.owner_player_id == planet.owner_player_id
                    )
                )
                .scalars()
                .all()
            )
            for b in b_rows:
                if int(getattr(b, "ready_at_tick", 0) or 0) > tick:
                    continue
                if not self._is_cell_supplied(
                    s,
                    owner_id=planet.owner_player_id,
                    x=int(b.x),
                    y=int(b.y),
                    z=int(getattr(b, "z", 0) or 0),
                ):
                    continue
                try:
                    bd = self._balance.get_building(b.building_type)
                except Exception:
                    bd = {}
                eff = bd.get("effects") if isinstance(bd, dict) else None
                prod_add = (
                    eff.get("production_per_tick_add")
                    if isinstance(eff, dict)
                    else None
                ) or {}
                for k in PLANET_STORE_KEYS:
                    if isinstance(prod_add.get(k), (int, float)):
                        bonus[k] += int(prod_add.get(k))
        else:
            bonus = self._get_building_bonus_for_player(
                s, player_id=planet.owner_player_id
            )

        mods = self._race_modifiers(s, player_id=planet.owner_player_id)
        mul = (
            mods.get("production_multiplier")
            if isinstance(mods.get("production_multiplier"), dict)
            else {}
        )
        tech_mul = self._tech_production_multipliers(
            s, player_id=planet.owner_player_id
        )

        sources = (
            influence_sources
            if influence_sources is not None
            else self._collect_influence_sources(s)
        )
        inf_scores = self._influence_scores_at(
            sources, int(planet.pos_x), int(planet.pos_y), 0
        )
        inf_mul = self._planet_influence_production_multiplier(
            inf_scores, planet.owner_player_id
        )

        ptype_mul: dict[str, float] = {k: 1.0 for k in PLANET_STORE_KEYS}
        if self._balance:
            ptd = self._balance.get_planet_type(str(getattr(planet, "planet_class", "") or "earthlike"))
            pm = ptd.get("base_production_multiplier") if isinstance(ptd, dict) else None
            if isinstance(pm, dict):
                for k in PLANET_STORE_KEYS:
                    if isinstance(pm.get(k), (int, float)):
                        ptype_mul[k] = float(pm[k])

        cap_pen = int(getattr(planet, "conquest_penalty_until_tick", 0) or 0)
        pen_mult = 10.0 if cap_pen > tick else 1.0

        def _calc(k: str) -> int:
            m = (
                float(mul.get(k, 1.0))
                * float(tech_mul.get(k, 1.0))
                * float(ptype_mul.get(k, 1.0))
                * float(pen_mult)
            )
            return int(round((base[k] + bonus[k]) * m * inf_mul))

        return {k: _calc(k) for k in PLANET_STORE_KEYS}

    def _population_vitals_upkeep_needs(self, *, population: int) -> tuple[int, int]:
        """Еда/вода на содержание населения за один сол (из economy.json)."""
        pop = max(0, int(population))
        if pop <= 0:
            return 0, 0
        ff, ww = 3, 3
        if self._balance and isinstance(self._balance.pack.economy, dict):
            pm = self._balance.pack.economy.get("population_maintenance")
            if isinstance(pm, dict):
                v = pm.get("food_per_1000_pop_per_tick")
                if isinstance(v, (int, float)):
                    ff = int(v)
                v2 = pm.get("water_per_1000_pop_per_tick")
                if isinstance(v2, (int, float)):
                    ww = int(v2)
        ff = max(0, ff)
        ww = max(0, ww)
        return (max(0, (pop * ff + 999) // 1000), max(0, (pop * ww + 999) // 1000))

    def apply_planet_production_tick(
        self,
        s: Session,
        *,
        planet_id: uuid.UUID,
        influence_sources: list[dict] | None = None,
    ) -> dict:
        planet = s.execute(
            select(Planet).where(Planet.id == planet_id)
        ).scalar_one_or_none()
        if not planet:
            return {k: 0 for k in PLANET_STORE_KEYS}
        res = s.execute(
            select(Resource).where(Resource.planet_id == planet_id)
        ).scalar_one_or_none()
        if not res:
            return {k: 0 for k in PLANET_STORE_KEYS}
        if not bool(getattr(planet, "is_colonized", True)):
            return {k: 0 for k in PLANET_STORE_KEYS}

        deltas = self._planet_production_deltas(
            s, planet=planet, influence_sources=influence_sources
        )
        res.metal += deltas["metal"]
        res.crystal += deltas["crystal"]
        res.energy += deltas["energy"]
        res.fuel += deltas["fuel"]
        res.food += deltas["food"]
        res.water += deltas["water"]
        s.flush()

        if hasattr(planet, "population"):
            rm = self._race_modifiers(s, player_id=planet.owner_player_id)
            pop_floor = 0 if rm.get("no_passive_population_growth") else 80
            mx = self._effective_max_population(s, planet)
            pop = int(getattr(planet, "population", 0) or 0)
            pop = min(pop, mx)
            f_need, w_need = self._population_vitals_upkeep_needs(population=pop)
            cur_f, cur_w = int(res.food), int(res.water)
            take_f = min(cur_f, f_need)
            take_w = min(cur_w, w_need)
            res.food = cur_f - take_f
            res.water = cur_w - take_w
            fed_full = (f_need == 0 or take_f >= f_need) and (
                w_need == 0 or take_w >= w_need
            )
            severe_short = (f_need > 0 and take_f * 2 < f_need) or (
                w_need > 0 and take_w * 2 < w_need
            )
            # MVP: не даём планете "вымереть в ноль" от дефицита — оставляем минимальный порог населения.
            if take_f == 0 and take_w == 0 and f_need + w_need > 0 and pop > pop_floor:
                planet.population = max(pop_floor, pop - max(1, pop // 100))
            elif severe_short and pop > max(pop_floor, 150):
                planet.population = max(pop_floor, pop - max(1, pop // 250))
            pop = int(getattr(planet, "population", 0) or 0)
            pop = min(pop, mx)
            gap = mx - pop
            if (not rm.get("no_passive_population_growth")) and fed_full and gap > 0:
                step = max(1, gap // 200)
                planet.population = min(mx, pop + step)
            elif pop > mx:
                planet.population = mx

        return deltas

    def _cell_visible_to_player(
        self, s: Session, *, player_id: uuid.UUID, x: int, y: int, z: int
    ) -> bool:
        for sx, sy, r in self._collect_visibility_sources_for_player(
            s, player_id=player_id, z=int(z)
        ):
            if hex_distance(int(x), int(y), int(sx), int(sy)) <= int(r):
                return True
        return False

    def recruit_planet_population(
        self,
        s: Session,
        *,
        player_id: str,
        planet_id: str,
        amount: int,
    ) -> dict:
        """Явный набор населения для рас с `no_passive_population_growth` (напр. silicon)."""
        try:
            pid = uuid.UUID(str(player_id).strip())
            plid = uuid.UUID(str(planet_id).strip())
        except Exception:
            return {"ok": False, "error": "invalid_uuid"}
        try:
            raw_am = int(amount)
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid_amount"}
        if raw_am <= 0:
            return {"ok": False, "error": "invalid_amount"}

        rm = self._race_modifiers(s, player_id=pid)
        if not rm.get("no_passive_population_growth"):
            return {"ok": False, "error": "recruit_not_available_for_race"}

        eco = self._merged_pack_economy(s)
        rc = (
            eco.get("citizen_recruit")
            if isinstance(eco.get("citizen_recruit"), dict)
            else {}
        )

        def _f(key: str, default: float) -> float:
            v = rc.get(key)
            if isinstance(v, (int, float)):
                return float(v)
            try:
                return float(str(v).strip())
            except Exception:
                return default

        max_req = max(1, int(_f("max_population_per_request", 500)))
        metal_pp = max(0.0, _f("metal_per_pop", 2.0))
        crystal_pp = max(0.0, _f("crystal_per_pop", 1.0))
        food_pp = max(0.0, _f("food_per_pop", 4.0))
        water_pp = max(0.0, _f("water_per_pop", 3.0))

        am = min(raw_am, max_req)

        planet = s.get(Planet, plid)
        if (
            not planet
            or planet.owner_player_id != pid
            or not bool(getattr(planet, "is_colonized", True))
        ):
            return {"ok": False, "error": "planet_not_owned"}

        res = (
            s.execute(select(Resource).where(Resource.planet_id == plid))
            .scalar_one_or_none()
        )
        if not res:
            return {"ok": False, "error": "no_resources"}

        mx = self._effective_max_population(s, planet)
        pop = int(getattr(planet, "population", 0) or 0)
        gap = mx - pop
        if gap <= 0:
            return {"ok": False, "error": "population_cap"}

        take = min(am, gap)

        cost_m = int(math.ceil(metal_pp * take))
        cost_c = int(math.ceil(crystal_pp * take))
        cost_f = int(math.ceil(food_pp * take))
        cost_w = int(math.ceil(water_pp * take))

        cur_m, cur_c = int(res.metal), int(res.crystal)
        cur_f = int(getattr(res, "food", 0) or 0)
        cur_w = int(getattr(res, "water", 0) or 0)
        if cur_m < cost_m or cur_c < cost_c or cur_f < cost_f or cur_w < cost_w:
            return {
                "ok": False,
                "error": "not_enough_resources",
                "need": {
                    "metal": cost_m,
                    "crystal": cost_c,
                    "food": cost_f,
                    "water": cost_w,
                },
                "have": {
                    "metal": cur_m,
                    "crystal": cur_c,
                    "food": cur_f,
                    "water": cur_w,
                },
            }

        res.metal = cur_m - cost_m
        res.crystal = cur_c - cost_c
        res.food = cur_f - cost_f
        res.water = cur_w - cost_w
        planet.population = pop + take
        s.flush()
        return {
            "ok": True,
            "added": take,
            "population": int(planet.population),
            "cost": {
                "metal": cost_m,
                "crystal": cost_c,
                "food": cost_f,
                "water": cost_w,
            },
        }

    def resolve_discovery_at_cell(
        self, s: Session, *, player_id: str, x: int, y: int, z: int
    ) -> dict:
        pid = uuid.UUID(player_id)
        z = max(-10, min(int(z), 10))
        if not self._cell_visible_to_player(s, player_id=pid, x=int(x), y=int(y), z=z):
            return {"ok": False, "error": "sector_not_visible"}
        cell_info = self.get_cell_terrain(x=int(x), y=int(y), z=z, s=s)
        tk = str(
            cell_info.get("terrain", "")
            if isinstance(cell_info, dict)
            else cell_info or ""
        )
        if (
            z == 0
            and s.execute(
                select(Planet.id).where(Planet.pos_x == x, Planet.pos_y == y)
            ).first()
        ):
            return {"ok": False, "error": "discovery_not_applicable"}
        if tk not in ("ruins", "anomaly"):
            return {"ok": False, "error": "nothing_to_discover"}
        explor = s.execute(
            select(ExploredSector).where(
                ExploredSector.player_id == pid,
                ExploredSector.x == int(x),
                ExploredSector.y == int(y),
                ExploredSector.z == z,
            )
        ).scalar_one_or_none()
        ws = self.get_or_create_world_state(s)
        now_tick = int(ws.current_tick)
        if not explor:
            explor = ExploredSector(
                player_id=pid,
                x=int(x),
                y=int(y),
                z=z,
                first_seen_tick=now_tick,
                last_seen_tick=now_tick,
            )
            s.add(explor)
            s.flush()
        if bool(explor.discovery_done):
            return {"ok": True, "already_done": True}
        if not self._player_has_fleet_at_cell(
            s, player_id=pid, x=int(x), y=int(y), z=z
        ):
            return {"ok": False, "error": "fleet_required"}
        info = try_resolve_ruins_anomaly_for_sector(
            s,
            self,
            player_id=pid,
            x=int(x),
            y=int(y),
            z=z,
            terrain=tk,
            now_tick=now_tick,
            explored=explor,
        )
        s.flush()
        if not info.get("ok", True):
            return {"ok": False, "error": str(info.get("reason") or "discovery_failed")}
        out = {"ok": True}
        for k in ("outcome", "subtype", "terrain", "headline"):
            if k in info:
                out[k] = info[k]
        return out

