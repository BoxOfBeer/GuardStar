"""Фрагмент WorldService: исследования, влияние, бой, ордера."""

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


class WorldServiceMixin05:
    def _ensure_bandit_player(self, s: Session) -> Player:
        p = s.get(Player, BANDIT_PLAYER_ID)
        if p:
            if str(p.display_name).strip() in ("ADM", "adm"):
                p.display_name = "Корсары (ИИ)"
            if getattr(p, "race_id", None) not in ("zenith",):
                p.race_id = "zenith"
                s.flush()
            return p
        h = hashlib.sha256(f"npc_bandit::{self._world_seed}".encode()).hexdigest()
        p = Player(
            id=BANDIT_PLAYER_ID,
            display_name="Корсары (ИИ)",
            access_code_hash=h,
            race_id="zenith",
        )
        s.add(p)
        s.flush()
        return p

    def _ensure_civilian_npc_player(self, s: Session) -> Player:
        p = s.get(Player, CIVILIAN_NPC_PLAYER_ID)
        if p:
            if getattr(p, "race_id", None) not in ("human",):
                p.race_id = "human"
                s.flush()
            return p
        h = hashlib.sha256(
            f"npc_civilian_convoy::{self._world_seed}".encode()
        ).hexdigest()
        p = Player(
            id=CIVILIAN_NPC_PLAYER_ID,
            display_name="Гражданский транзит (ИИ)",
            access_code_hash=h,
            race_id="human",
        )
        s.add(p)
        s.flush()
        return p

    def _human_player_ids(self, s: Session) -> list[uuid.UUID]:
        out: list[uuid.UUID] = []
        for row in s.execute(select(Player.id)).scalars():
            if row in NPC_FLEET_PLAYER_IDS:
                continue
            out.append(row)
        return out

    def _cell_visible_to_any_human_player(
        self, s: Session, *, x: int, y: int, z: int
    ) -> bool:
        for pid in self._human_player_ids(s):
            if self._cell_visible_to_player(
                s, player_id=pid, x=int(x), y=int(y), z=int(z)
            ):
                return True
        return False

    def _player_research_points_float(self, player: Player) -> float:
        v = getattr(player, "research_points", 0)
        try:
            return float(v or 0)
        except Exception:
            return float(v)

    def grant_player_research_points(
        self,
        s: Session,
        *,
        player_id: uuid.UUID,
        amount: float,
        tick: int,
        reason: str,
        message: str | None = None,
        payload_extra: dict | None = None,
    ) -> None:
        amt = float(amount)
        if amt <= 1e-12 or player_id in NPC_FLEET_PLAYER_IDS:
            return
        pl = s.get(Player, player_id)
        if not pl:
            return
        cur = self._player_research_points_float(pl)
        pl.research_points = cur + amt
        pay = payload_extra.copy() if isinstance(payload_extra, dict) else {}
        pay.update({"amount": amt, "reason": reason})
        msg = message or (f"+{amt:g} очков исследования ({reason}).")
        self._emit_event(
            s,
            tick=int(tick),
            type="research_points_granted",
            message=str(msg),
            payload=pay,
            player_id=player_id,
        )

    def _active_npc_transit_convoys_count(self, s: Session) -> int:
        civ = self._ensure_civilian_npc_player(s)
        return int(
            s.execute(
                select(func.count(Fleet.id)).where(
                    Fleet.owner_player_id == civ.id, Fleet.qty > 0
                )
            ).scalar()
            or 0
        )

    def _purge_fleet_row(self, s: Session, fleet: Fleet) -> None:
        s.execute(delete(FleetShip).where(FleetShip.fleet_id == fleet.id))
        s.execute(delete(FleetOrder).where(FleetOrder.fleet_id == fleet.id))
        s.delete(fleet)

    def _enqueue_npc_transit_move(
        self,
        s: Session,
        *,
        fleet: Fleet,
        target_x: int,
        target_y: int,
        target_z: int,
        start_after_tick: int,
    ) -> None:
        units_map = self._fleet_units_map(s, fleet)
        dist = abs(int(target_x) - int(fleet.pos_x)) + abs(
            int(target_y) - int(fleet.pos_y)
        )
        travel_ticks = max(
            1, self._fleet_travel_ticks_for_distance(distance=dist, units=units_map)
        )
        order = FleetOrder(
            fleet_id=fleet.id,
            owner_player_id=fleet.owner_player_id,
            order_type="npc_transit",
            from_x=int(fleet.pos_x),
            from_y=int(fleet.pos_y),
            from_z=int(fleet.pos_z),
            target_x=int(target_x),
            target_y=int(target_y),
            target_z=int(target_z),
            qty=max(1, int(fleet.qty)),
            status="queued",
            start_tick=int(start_after_tick) + 1,
            finish_tick=int(start_after_tick) + int(travel_ticks),
            force_attack=False,
            combat_prompt_expires_at=None,
        )
        s.add(order)
        s.flush()

    def _try_spawn_npc_transit_convoy(self, s: Session, *, current_tick: int) -> None:
        if not self._balance or not isinstance(
            getattr(self._balance, "pack", None), object
        ):
            return
        eco = (
            self._balance.pack.economy
            if isinstance(self._balance.pack.economy, dict)
            else {}
        )
        blk = eco.get("npc_transit") if isinstance(eco.get("npc_transit"), dict) else {}
        if not blk.get("enabled", True):
            return
        if not self._human_player_ids(s):
            return
        every = int(blk.get("spawn_every_n_ticks", 5) or 5)
        if every <= 0 or int(current_tick) % every != 0:
            return
        max_active = int(blk.get("max_active_convoys", 5) or 5)
        if self._active_npc_transit_convoys_count(s) >= max_active:
            return
        dmin = int(blk.get("min_route_manhattan", 10) or 10)
        dmax = int(blk.get("max_route_manhattan", 36) or 36)
        if dmax < dmin:
            dmin, dmax = dmax, dmin
        attempts = int(blk.get("spawn_attempts", 48) or 48)
        civ = self._ensure_civilian_npc_player(s)
        seed_i = int(
            hashlib.sha256(
                f"{self._world_seed}|npc_transit|{current_tick}".encode()
            ).hexdigest()[:8],
            16,
        )
        rng = random.Random(seed_i)

        # Раньше концы маршрута требовали «вне обзора всех людей» — конвои никогда
        # не попадали на карту игрока. Достаточно свободных клеток и маршрута.
        ax = ay = bx = by = None
        for _ in range(max(12, attempts)):
            sx = rng.randint(-120, 120)
            sy = rng.randint(-120, 120)
            if self._cell_blocked_for_fleet(s, sx, sy, 0):
                continue
            dist = rng.randint(dmin, dmax)
            dx_sign = rng.choice([-1, 1])
            dy_sign = rng.choice([-1, 1])
            split = rng.randint(0, dist)
            tx = sx + dx_sign * split
            ty = sy + dy_sign * (dist - split)
            if self._cell_blocked_for_fleet(s, tx, ty, 0):
                continue
            ax, ay, bx, by = sx, sy, tx, ty
            break

        if ax is None:
            return
        fleet = Fleet(
            owner_player_id=civ.id,
            unit_type="supplier",
            qty=0,
            pos_x=int(ax),
            pos_y=int(ay),
            pos_z=0,
            name="Транзит",
            energy=100,
        )
        s.add(fleet)
        s.flush()
        self._write_fleet_units(s, fleet, {"supplier": 2, "scout": 1})
        s.flush()
        self._enqueue_npc_transit_move(
            s,
            fleet=fleet,
            target_x=int(bx),
            target_y=int(by),
            target_z=0,
            start_after_tick=int(current_tick),
        )

    def _building_is_research_lab_t1(self, logical_type: str) -> bool:
        if not self._balance:
            return False
        try:
            bd = self._balance.get_building(str(logical_type))
            return str(bd.get("id") or "") == "research_lab_t1"
        except Exception:
            return False

    def _count_player_research_labs(self, s: Session, player_id: uuid.UUID) -> int:
        n = 0
        rows = (
            s.execute(
                select(Building.building_type)
                .join(Planet, Building.planet_id == Planet.id)
                .where(Planet.owner_player_id == player_id)
            )
            .scalars()
            .all()
        )
        for bt in rows:
            if self._building_is_research_lab_t1(str(bt or "")):
                n += 1
        return n

    def _apply_research_economy_tick(self, s: Session, *, tick: int) -> None:
        if not self._balance or not isinstance(
            getattr(self._balance, "pack", None), object
        ):
            return
        eco = (
            self._balance.pack.economy
            if isinstance(self._balance.pack.economy, dict)
            else {}
        )
        rp_cfg = (
            eco.get("research_points")
            if isinstance(eco.get("research_points"), dict)
            else {}
        )
        lab_eco = (
            eco.get("research_lab") if isinstance(eco.get("research_lab"), dict) else {}
        )
        base_home = float(rp_cfg.get("home_capital_per_sol", 0.1))
        lab_rp = float(rp_cfg.get("research_lab_t1_per_sol", 0.1))
        upcry = int(lab_eco.get("upkeep_crystal_per_sol", 0) or 0)
        pch = float(lab_eco.get("strain_event_chance_per_lab_per_sol", 0) or 0)
        pst = int(lab_eco.get("strain_event_crystal_cost", 0) or 0)
        seed_mix = int(hashlib.sha256(self._world_seed.encode()).hexdigest()[:8], 16)
        rng = random.Random((int(tick) ^ seed_mix) & 0xFFFFFFFF)

        for pid in self._human_player_ids(s):
            home = self._capital_planet_for_player(s, player_id=pid)
            pl = s.get(Player, pid)
            if not pl or not home:
                continue
            labs_n = self._count_player_research_labs(s, pid)
            gain = base_home + float(labs_n) * lab_rp
            if gain > 1e-9:
                cur = self._player_research_points_float(pl)
                pl.research_points = cur + gain

            res = s.execute(
                select(Resource).where(Resource.planet_id == home.id)
            ).scalar_one_or_none()
            if labs_n > 0 and upcry > 0 and res:
                need_c = upcry * labs_n
                have_c = int(getattr(res, "crystal", 0) or 0)
                if have_c >= need_c:
                    res.crystal = have_c - need_c
                else:
                    self._emit_event(
                        s,
                        tick=tick,
                        type="research_lab_underfunded",
                        message="Нехватка кристаллов на содержание лабораторий.",
                        payload={"need_crystal": need_c, "have_crystal": have_c},
                        player_id=pid,
                    )

            if labs_n > 0 and pch > 0 and pst > 0 and res:
                for _ in range(labs_n):
                    if rng.random() >= pch:
                        continue
                    have_c = int(getattr(res, "crystal", 0) or 0)
                    if have_c < pst:
                        break
                    res.crystal = have_c - pst
                    self._emit_event(
                        s,
                        tick=tick,
                        type="research_lab_strain_event",
                        message="Лаборатория: калибровка датчиков стоила дополнительных кристаллов.",
                        payload={"crystal": pst},
                        player_id=pid,
                    )
        s.flush()

    def _cell_blocked_for_fleet(self, s: Session, x: int, y: int, z: int) -> bool:
        if (
            s.execute(
                select(Building.id).where(
                    Building.x == x, Building.y == y, Building.z == z
                )
            )
            .scalars()
            .first()
        ):
            return True
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
            return True
        if (
            s.execute(
                select(Fleet.id).where(
                    Fleet.pos_x == x, Fleet.pos_y == y, Fleet.pos_z == z
                )
            )
            .scalars()
            .first()
        ):
            return True
        return False

    def _cell_in_player_build_zone(
        self, s: Session, *, player_id: uuid.UUID, x: int, y: int
    ) -> bool:
        """Радиус 3 от любой планеты владельца (как зона стройки)."""
        for p in (
            s.execute(select(Planet).where(Planet.owner_player_id == player_id))
            .scalars()
            .all()
        ):
            if abs(int(p.pos_x) - int(x)) + abs(int(p.pos_y) - int(y)) <= 3:
                return True
        return False

    def _collect_influence_sources(self, s: Session) -> list[dict]:
        out: list[dict] = []
        # Имперский бонус: суммарное население слегка усиливает все давления по империи.
        # 100k населения -> +0.05 ко всем давлениям (множитель 1.05).
        pops = s.execute(
            select(
                Planet.owner_player_id, func.sum(getattr(Planet, "population", 0))
            ).group_by(Planet.owner_player_id)
        ).all()
        pop_by_owner: dict[uuid.UUID, int] = {pid: int(sp or 0) for pid, sp in pops}
        mult_by_owner: dict[uuid.UUID, float] = {}
        for pid, pop in pop_by_owner.items():
            mult_by_owner[pid] = 1.0 + (max(0, int(pop)) / 100000.0) * 0.05
        race_inf: dict[uuid.UUID, float] = {}

        def _race_inf_mul(owner: uuid.UUID) -> float:
            if owner not in race_inf:
                race_inf[owner] = float(
                    self._race_modifiers(s, player_id=owner).get(
                        "influence_multiplier", 1.0
                    )
                )
            return race_inf[owner]

        for p in s.execute(select(Planet)).scalars().all():
            mul = float(mult_by_owner.get(p.owner_player_id, 1.0)) * _race_inf_mul(
                p.owner_player_id
            )
            out.append(
                {
                    "owner": p.owner_player_id,
                    "x": int(p.pos_x),
                    "y": int(p.pos_y),
                    "z": 0,
                    "w": float(INFLUENCE_WEIGHT_COLONY) * mul,
                    "r": INFLUENCE_RADIUS_COLONY,
                }
            )
        for op in (
            s.execute(select(Outpost).where(Outpost.z == 0, Outpost.status == "active"))
            .scalars()
            .all()
        ):
            st = self._outpost_stats(s, op)
            mul = float(mult_by_owner.get(op.owner_player_id, 1.0)) * _race_inf_mul(
                op.owner_player_id
            )
            out.append(
                {
                    "owner": op.owner_player_id,
                    "x": int(op.x),
                    "y": int(op.y),
                    "z": int(op.z),
                    "w": float(st["territory"]["influence_strength"]) * mul,
                    "r": int(st["territory"]["influence_radius"]),
                }
            )
        return out

    def _collect_visibility_sources_for_player(
        self, s: Session, *, player_id: uuid.UUID, z: int
    ) -> list[tuple[int, int, int]]:
        vis_sources: list[tuple[int, int, int]] = []
        my_planets = (
            s.execute(select(Planet).where(Planet.owner_player_id == player_id))
            .scalars()
            .all()
        )
        for p in my_planets:
            vis_sources.append((int(p.pos_x), int(p.pos_y), 5))
        my_fleets = (
            s.execute(
                select(Fleet).where(
                    Fleet.owner_player_id == player_id, Fleet.pos_z == z
                )
            )
            .scalars()
            .all()
        )
        for f in my_fleets:
            um = self._fleet_units_map(s, f)
            r = 2 if int(um.get("scout", 0)) > 0 or f.unit_type == "scout" else 1
            vis_sources.append((int(f.pos_x), int(f.pos_y), r))
        my_outposts = (
            s.execute(
                select(Outpost).where(
                    Outpost.owner_player_id == player_id,
                    Outpost.z == z,
                    Outpost.status == "active",
                )
            )
            .scalars()
            .all()
        )
        for op in my_outposts:
            st = self._outpost_stats(s, op)
            vis_sources.append((int(op.x), int(op.y), int(st["vision"]["radius"])))
        return vis_sources

    @staticmethod
    def _influence_decay_contrib(weight: float, manhattan_d: int, radius: int) -> float:
        if radius <= 0 or manhattan_d > radius:
            return 0.0
        guaranteed = min(INFLUENCE_BASE_RADIUS, radius)
        if manhattan_d <= guaranteed:
            return float(weight)
        return float(weight) * (0.5 ** int(manhattan_d - guaranteed))

    def _influence_scores_at(
        self, sources: list[dict], x: int, y: int, z: int
    ) -> dict[uuid.UUID, float]:
        acc: dict[uuid.UUID, float] = defaultdict(float)
        for src in sources:
            if int(src["z"]) != int(z):
                continue
            d = abs(int(src["x"]) - x) + abs(int(src["y"]) - y)
            c = self._influence_decay_contrib(float(src["w"]), d, int(src["r"]))
            if c > 0:
                acc[src["owner"]] += c
        return dict(acc)

    def _owned_engineer_fleet_at(
        self,
        s: Session,
        *,
        owner_id: uuid.UUID,
        x: int,
        y: int,
        z: int,
        fleet_id: str | None = None,
    ) -> Fleet | None:
        q = (
            select(Fleet)
            .where(
                Fleet.owner_player_id == owner_id,
                Fleet.pos_x == x,
                Fleet.pos_y == y,
                Fleet.pos_z == z,
            )
            .order_by(Fleet.created_at.asc())
        )
        if fleet_id:
            try:
                q = q.where(Fleet.id == uuid.UUID(fleet_id))
            except Exception:
                return None
        for fleet in s.execute(q).scalars().all():
            if int(self._fleet_units_map(s, fleet).get("engineer", 0)) > 0:
                return fleet
        return None

    def _cell_enemy_control_owner(
        self, s: Session, *, owner_id: uuid.UUID, x: int, y: int, z: int
    ) -> uuid.UUID | None:
        rows = (
            s.execute(
                select(InfluenceCell)
                .where(
                    InfluenceCell.x == x,
                    InfluenceCell.y == y,
                    InfluenceCell.z == z,
                    InfluenceCell.control_value > 0,
                )
                .order_by(InfluenceCell.control_value.desc())
            )
            .scalars()
            .all()
        )
        if not rows:
            return None
        top = rows[0]
        second = float(rows[1].control_value) if len(rows) > 1 else 0.0
        if float(top.control_value) <= INFLUENCE_CAPTURE_THRESHOLD:
            return None
        if float(top.control_value) - second <= 0.01:
            return None
        return None if top.player_id == owner_id else top.player_id

    @staticmethod
    def _influence_next_control_value(
        current_value: float, own_strength: float, others_strength: float
    ) -> float:
        net = (
            float(own_strength)
            - float(others_strength)
            - INFLUENCE_NATURAL_DECAY_PER_TICK
        )
        return max(0.0, min(INFLUENCE_CONTROL_VALUE_CAP, float(current_value) + net))

    def _apply_influence_control_tick(
        self, s: Session, *, tick: int, sources: list[dict]
    ) -> None:
        claims = (
            s.execute(select(InfluenceCell).where(InfluenceCell.control_value > 0))
            .scalars()
            .all()
        )
        by_cell_player: dict[tuple[int, int, int, uuid.UUID], InfluenceCell] = {
            (int(c.x), int(c.y), int(c.z), c.player_id): c for c in claims
        }
        players_by_cell: dict[tuple[int, int, int], set[uuid.UUID]] = defaultdict(set)
        for c in claims:
            players_by_cell[(int(c.x), int(c.y), int(c.z))].add(c.player_id)

        covered_cells: set[tuple[int, int, int]] = set(players_by_cell.keys())
        for src in sources:
            sx, sy, sz, rr = int(src["x"]), int(src["y"]), int(src["z"]), int(src["r"])
            for dy in range(-rr, rr + 1):
                max_dx = rr - abs(dy)
                for dx in range(-max_dx, max_dx + 1):
                    covered_cells.add((sx + dx, sy + dy, sz))

        for x, y, z in covered_cells:
            scores = self._influence_scores_at(sources, x, y, z)
            score_players = set(scores.keys())
            existed_players = players_by_cell.get((x, y, z), set())
            all_players = score_players | existed_players
            if not all_players:
                continue
            total = float(sum(scores.values()))
            for pid in all_players:
                own = float(scores.get(pid, 0.0))
                others = max(0.0, total - own)
                key = (x, y, z, pid)
                cur = by_cell_player.get(key)
                old = float(cur.control_value) if cur else 0.0
                newv = self._influence_next_control_value(old, own, others)
                if newv <= 1e-9:
                    if cur:
                        s.delete(cur)
                        by_cell_player.pop(key, None)
                    continue
                if cur:
                    cur.control_value = float(newv)
                    cur.updated_tick = int(tick)
                else:
                    cur = InfluenceCell(
                        player_id=pid,
                        x=int(x),
                        y=int(y),
                        z=int(z),
                        control_value=float(newv),
                        updated_tick=int(tick),
                    )
                    s.add(cur)
                    by_cell_player[key] = cur

    def _influence_cell_payload(
        self,
        scores: dict[uuid.UUID, float],
        viewer_id: uuid.UUID,
        owners_by_id: dict[str, str],
        control_scores: dict[uuid.UUID, float] | None = None,
    ) -> dict:
        entries = [(uid, float(v)) for uid, v in scores.items() if float(v) > 1e-12]
        entries.sort(key=lambda kv: kv[1], reverse=True)
        total = float(sum(sc for _, sc in entries))

        control_entries: list[tuple[uuid.UUID, float]] = []
        if control_scores:
            control_entries = [
                (uid, float(v)) for uid, v in control_scores.items() if float(v) > 1e-12
            ]
            control_entries.sort(key=lambda kv: kv[1], reverse=True)

        control_owner: str | None = None
        control_owner_name: str | None = None
        if control_entries and control_entries[0][1] > INFLUENCE_CAPTURE_THRESHOLD:
            if (
                len(control_entries) == 1
                or control_entries[0][1] - control_entries[1][1] > 0.01
            ):
                control_owner = str(control_entries[0][0])
                control_owner_name = owners_by_id.get(control_owner)

        dominant: str | None = None
        dominant_name: str | None = None
        if control_owner:
            dominant = control_owner
            dominant_name = control_owner_name
        elif entries and entries[0][1] >= INFLUENCE_MIN_DOMINANT_SCORE:
            dominant = str(entries[0][0])
            dominant_name = owners_by_id.get(dominant)

        contested = False
        if len(entries) >= 2 and entries[0][1] > 1e-9:
            contested = entries[1][1] / entries[0][1] >= INFLUENCE_CONTEST_RATIO

        top: list[dict] = []
        for uid, sc in entries[:4]:
            sid = str(uid)
            top.append(
                {
                    "player_id": sid,
                    "score": round(sc, 2),
                    "share": round(sc / total, 4) if total > 1e-9 else 0.0,
                    "name": owners_by_id.get(sid),
                }
            )

        your = float(scores.get(viewer_id, 0.0))
        your_share = round(your / total, 4) if total > 1e-9 else None

        dominant_rel = None
        if dominant:
            dominant_rel = (
                "self" if viewer_id and dominant == str(viewer_id) else "other"
            )

        return {
            "dominant": dominant,
            "dominant_name": dominant_name,
            "dominant_rel": dominant_rel,
            "contested": contested,
            "your_share": your_share,
            "top": top,
            "total_score": round(total, 2),
            "control": {
                "owner": control_owner,
                "owner_name": control_owner_name,
                "your_value": round(float(control_scores.get(viewer_id, 0.0)), 3)
                if control_scores
                else 0.0,
                "top_value": round(control_entries[0][1], 3)
                if control_entries
                else 0.0,
                "capture_threshold": INFLUENCE_CAPTURE_THRESHOLD,
            },
        }

    @staticmethod
    def _planet_influence_production_multiplier(
        scores: dict[uuid.UUID, float], owner_id: uuid.UUID
    ) -> float:
        total = float(sum(scores.values()))
        if total <= 1e-12:
            return 1.0
        share = float(scores.get(owner_id, 0.0)) / total
        return max(0.88, min(1.12, 1.0 + (share - 0.5) * 0.24))

    def _spawn_mvp_bandit_patrol_near(
        self, s: Session, *, home_x: int, home_y: int
    ) -> None:
        """Один вражеский патруль рядом с колонией — цель для боя в MVP."""
        npc = self._ensure_bandit_player(s)
        z = 0
        cand = [
            (6, 0),
            (7, 0),
            (5, 1),
            (6, 1),
            (8, 0),
            (4, 1),
            (6, -1),
            (7, -1),
            (5, -1),
            (8, 1),
            (4, -1),
            (9, 0),
        ]
        for dx, dy in cand:
            tx, ty = home_x + dx, home_y + dy
            if self._cell_blocked_for_fleet(s, tx, ty, z):
                continue
            fleet = Fleet(
                owner_player_id=npc.id,
                unit_type="fighter",
                qty=0,
                pos_x=int(tx),
                pos_y=int(ty),
                pos_z=z,
                name="Засада",
            )
            s.add(fleet)
            s.flush()
            self._write_fleet_units(s, fleet, {"fighter": 2, "scout": 1})
            s.flush()
            return

    def _combat_tech_breakdown(
        self, s: Session, *, player_id: uuid.UUID
    ) -> tuple[float, float, list[dict]]:
        """Множители урона/HP от завершённых исследований + список для отображения игроку."""
        dmg = 1.0
        hp = 1.0
        lines: list[dict] = []
        if not self._balance or not getattr(self._balance, "pack", None):
            return dmg, hp, lines
        for tid in self._get_player_done_techs(s, player_id=player_id):
            t = self._balance.pack.tech_by_id.get(tid)
            if not isinstance(t, dict):
                continue
            nm = str(t.get("name") or tid).strip() or tid
            eff = t.get("effects") if isinstance(t.get("effects"), dict) else {}
            has_cf = False
            if isinstance(eff.get("combat_damage_multiplier"), (int, float)):
                dmg *= float(eff["combat_damage_multiplier"])
                has_cf = True
            if isinstance(eff.get("combat_hp_multiplier"), (int, float)):
                hp *= float(eff["combat_hp_multiplier"])
                has_cf = True
            if has_cf:
                parts: list[str] = []
                if isinstance(eff.get("combat_damage_multiplier"), (int, float)):
                    parts.append(f"урон ×{float(eff['combat_damage_multiplier']):g}")
                if isinstance(eff.get("combat_hp_multiplier"), (int, float)):
                    parts.append(f"HP ×{float(eff['combat_hp_multiplier']):g}")
                lines.append({"tech_id": tid, "name": nm, "summary": "; ".join(parts)})
        return dmg, hp, lines

    def _combat_race_multipliers(self, *, race_id: str | None) -> tuple[float, float]:
        dmg = 1.0
        hp = 1.0
        if not race_id or not self._balance or not getattr(self._balance, "pack", None):
            return dmg, hp
        race = self._balance.pack.races_by_id.get(str(race_id))
        if not isinstance(race, dict):
            return dmg, hp
        mods = race.get("modifiers") if isinstance(race.get("modifiers"), dict) else {}
        if isinstance(mods.get("combat_damage_multiplier"), (int, float)):
            dmg *= float(mods["combat_damage_multiplier"])
        if isinstance(mods.get("combat_hp_multiplier"), (int, float)):
            hp *= float(mods["combat_hp_multiplier"])
        return dmg, hp

    def _combat_stat_multipliers_for_player(
        self, s: Session, *, player_id: uuid.UUID
    ) -> tuple[float, float]:
        d_tech, h_tech, _ = self._combat_tech_breakdown(s, player_id=player_id)
        rid = self._get_player_race_id(s, player_id=player_id)
        dr, hr = self._combat_race_multipliers(race_id=rid)
        return d_tech * dr, h_tech * hr

    def _fleet_combat_score(
        self, s: Session, *, fleet: Fleet, player_id: uuid.UUID
    ) -> int:
        um = self._fleet_units_map(s, fleet)
        dmg_m, hp_m = self._combat_stat_multipliers_for_player(s, player_id=player_id)
        score = 0
        for ut, q in um.items():
            u: dict = {}
            if self._balance:
                try:
                    u = self._balance.get_unit(ut)
                except Exception:
                    u = {}
            hp = float(u.get("hp", 10)) * hp_m
            dmg = float(u.get("damage", 1)) * dmg_m
            score += int((hp + dmg * 3.0) * max(0, int(q)))
        return max(1, int(score))

    def _fleet_composition_snapshot(self, s: Session, fleet: Fleet) -> dict[str, int]:
        return {
            str(k): int(v)
            for k, v in self._fleet_units_map(s, fleet).items()
            if int(v) > 0
        }

    def _composition_casualties(
        self, before: dict[str, int], after: dict[str, int]
    ) -> dict:
        lost: dict[str, int] = {}
        for k in set(before) | set(after):
            b = int(before.get(k, 0))
            a = int(after.get(k, 0))
            if b > a:
                lost[k] = b - a
        return {
            "before": dict(before),
            "after": dict(after),
            "lost_by_type": lost,
            "lost_total": sum(lost.values()),
        }

    def _apply_fleet_post_combat_losses(
        self,
        s: Session,
        fleet: Fleet,
        *,
        fraction: float = 0.08,
        allow_eliminate_fleet: bool = False,
    ) -> None:
        """Списать долю кораблей (MVP). По умолчанию остаётся минимум 1 корабль — для боя флот-флот.

        Для обстрела форпоста/стационаров: ``allow_eliminate_fleet=True``, иначе последний юнит
        никогда не снимается из-за раннего ``return`` при ``tot <= 1``.
        """
        um = dict(self._fleet_units_map(s, fleet))
        tot = sum(int(v) for v in um.values())
        if tot <= 0:
            return
        min_remain = 0 if allow_eliminate_fleet else 1
        if tot <= min_remain:
            return
        remove = min(tot - min_remain, max(1, int(tot * fraction)))
        while remove > 0 and sum(um.values()) > min_remain:
            ut = max(um.items(), key=lambda kv: (kv[1], kv[0]))[0]
            if int(um.get(ut, 0)) <= 0:
                break
            um[ut] = int(um[ut]) - 1
            remove -= 1
        self._write_fleet_units(s, fleet, um)

    def _combat_effective_scores(
        self,
        s: Session,
        *,
        attacker: Fleet,
        defender: Fleet,
        attacker_from_x: int,
        attacker_from_y: int,
        battle_cell_x: int,
        battle_cell_y: int,
    ) -> tuple[float, float, dict]:
        """Базовые очки боя с учётом территории (снабжение атакующего / оборона у защитника)."""
        ap, dp = attacker.owner_player_id, defender.owner_player_id
        atk_raw = float(self._fleet_combat_score(s, fleet=attacker, player_id=ap))
        def_raw = float(self._fleet_combat_score(s, fleet=defender, player_id=dp))
        atk_sup = self._cell_in_player_build_zone(
            s, player_id=ap, x=attacker_from_x, y=attacker_from_y
        )
        def_home = self._cell_in_player_build_zone(
            s, player_id=dp, x=battle_cell_x, y=battle_cell_y
        )
        atk_mul = 1.05 if atk_sup else 1.0
        def_mul = 1.08 if def_home else 1.0
        eff_atk = atk_raw * atk_mul
        eff_def = def_raw * def_mul
        _, _, atk_rd = self._combat_tech_breakdown(s, player_id=ap)
        _, _, def_rd = self._combat_tech_breakdown(s, player_id=dp)
        meta = {
            "attacker_base": int(atk_raw),
            "defender_base": int(def_raw),
            "attacker_supply_zone": atk_sup,
            "defender_home_zone": def_home,
            "attacker_effective_before_roll": round(eff_atk, 2),
            "defender_effective_before_roll": round(eff_def, 2),
            "attacker_effective": round(eff_atk, 1),
            "defender_effective": round(eff_def, 1),
            "supply_zone_bonus": {
                "attacker": 1.05 if atk_sup else 1.0,
                "defender": 1.08 if def_home else 1.0,
            },
            "attacker_research": atk_rd,
            "defender_research": def_rd,
            "note": "На итоговые очки каждого тика применяется случайный множитель Uniform(0.94…1.08). Победа — если очки после броска ≥ у соперника.",
        }
        return eff_atk, eff_def, meta

    def estimate_fleet_combat_preview(
        self,
        s: Session,
        *,
        attacker: Fleet,
        defender: Fleet,
        attacker_from_x: int,
        attacker_from_y: int,
    ) -> dict:
        bx, by = int(defender.pos_x), int(defender.pos_y)
        eff_atk, eff_def, meta = self._combat_effective_scores(
            s,
            attacker=attacker,
            defender=defender,
            attacker_from_x=attacker_from_x,
            attacker_from_y=attacker_from_y,
            battle_cell_x=bx,
            battle_cell_y=by,
        )
        trials = 400
        wins = 0
        for _ in range(trials):
            ar = int(eff_atk * random.uniform(0.94, 1.08))
            dr = int(eff_def * random.uniform(0.94, 1.08))
            if ar >= dr:
                wins += 1
        p_win = round(wins / trials, 3)
        return {
            "combat": True,
            "attacker_composition": dict(self._fleet_units_map(s, attacker)),
            "defender_composition": dict(self._fleet_units_map(s, defender)),
            "p_win_attacker": p_win,
            "factors": meta,
            "disclaimer": "Оценка по многократной симуляции случайного боя; исход одного боя не гарантирован.",
        }

    def _resolve_fleet_vs_fleet_combat(
        self,
        s: Session,
        *,
        attacker: Fleet,
        defender: Fleet,
        attacker_from_x: int,
        attacker_from_y: int,
        battle_tick: int,
        event_player_id: uuid.UUID,
    ) -> dict:
        """Итог боя: проигравший флот удалён; победитель с потерями; атакующий при победе занимает клетку защитника."""
        tx, ty, tz = int(defender.pos_x), int(defender.pos_y), int(defender.pos_z)
        eff_atk, eff_def, meta = self._combat_effective_scores(
            s,
            attacker=attacker,
            defender=defender,
            attacker_from_x=attacker_from_x,
            attacker_from_y=attacker_from_y,
            battle_cell_x=tx,
            battle_cell_y=ty,
        )
        u_atk = random.uniform(0.94, 1.08)
        u_def = random.uniform(0.94, 1.08)
        atk_roll = int(eff_atk * u_atk)
        def_roll = int(eff_def * u_def)
        ap = attacker.owner_player_id
        dp = defender.owner_player_id
        dname = self._fleet_public_name(defender)
        aname = self._fleet_public_name(attacker)
        atk_comp_0 = self._fleet_composition_snapshot(s, attacker)
        def_comp_0 = self._fleet_composition_snapshot(s, defender)

        roll_block = {
            "effective_attacker": round(eff_atk, 4),
            "effective_defender": round(eff_def, 4),
            "random_factor_attacker": round(u_atk, 6),
            "random_factor_defender": round(u_def, 6),
            "rolled_score_attacker": atk_roll,
            "rolled_score_defender": def_roll,
            "rule": "Победитель — у кого больше очков после броска (при равенстве побеждает атакующий).",
        }
        calc_block = {
            "how_score_works": "По каждому типу корабля: (HP + 3×урон) × количество; HP/урон из баланса × множители исследований; сумма = база. К базе: ×1.05 если атакующий стартовал из своей зоны снабжения; ×1.08 защитнику на своей домашней зоне.",
            "factors": meta,
            "rolls": roll_block,
            "composition_start": {"attacker": atk_comp_0, "defender": def_comp_0},
        }

        if atk_roll >= def_roll:
            loser_id = str(defender.id)
            s.delete(defender)
            s.flush()
            loss_frac = min(0.2, 0.06 + min(0.08, def_roll / max(400, atk_roll)))
            self._apply_fleet_post_combat_losses(s, attacker, fraction=loss_frac)
            atk_comp_1 = self._fleet_composition_snapshot(s, attacker)
            attacker.pos_x = tx
            attacker.pos_y = ty
            attacker.pos_z = tz
            s.flush()
            victor_side = {
                "destroyed_defender_fleet_id": loser_id,
                "winner": "attacker",
            }
            atk_casualties = self._composition_casualties(atk_comp_0, atk_comp_1)
            payload_att = {
                "result": "victory",
                "battle_calculation": calc_block,
                "outcome_summary": victor_side,
                "consequences": {
                    "enemy_fleet_removed": loser_id,
                    "your_ship_loss_fraction_applied": round(loss_frac, 4),
                    "your_fleet_survivors": atk_casualties,
                    "winner_takes_square": {"x": tx, "y": ty, "z": tz},
                },
            }
            self._emit_event(
                s,
                tick=battle_tick,
                type="fleet_combat",
                message=f"Бой: победа «{aname}» над «{dname}» ({atk_roll}:{def_roll}).",
                payload=payload_att,
                player_id=event_player_id,
            )
            if dp != ap:
                self._emit_event(
                    s,
                    tick=battle_tick,
                    type="fleet_combat",
                    message=f"Бой: «{dname}» уничтожен ({def_roll}:{atk_roll}).",
                    payload={
                        "result": "defeat_side",
                        "battle_calculation": calc_block,
                        "consequences": {
                            "your_fleet_lost_id": loser_id,
                            "winner_enemy_fleet": str(attacker.id),
                        },
                    },
                    player_id=dp,
                )
            return {
                "winner": "attacker",
                "destroyed_fleet_id": loser_id,
                "rolls": {"attacker": atk_roll, "defender": def_roll},
            }

        loser_id = str(attacker.id)
        s.delete(attacker)
        s.flush()
        loss_frac_d = min(0.2, 0.05 + min(0.08, atk_roll / max(400, def_roll)))
        self._apply_fleet_post_combat_losses(s, defender, fraction=loss_frac_d)
        def_comp_1 = self._fleet_composition_snapshot(s, defender)
        s.flush()

        defender_win = {"destroyed_attacker_fleet_id": loser_id, "winner": "defender"}
        def_casualties = self._composition_casualties(def_comp_0, def_comp_1)
        payload_lose_att = {
            "result": "defeat",
            "battle_calculation": calc_block,
            "outcome_summary": defender_win,
            "consequences": {
                "your_fleet_lost_id": loser_id,
                "enemy_survivors_after": def_casualties,
                "defender_ship_loss_fraction_applied": round(loss_frac_d, 4),
            },
        }
        self._emit_event(
            s,
            tick=battle_tick,
            type="fleet_combat",
            message=f"Бой: «{aname}» уничтожен «{dname}» ({atk_roll}:{def_roll}).",
            payload=payload_lose_att,
            player_id=event_player_id,
        )
        if dp != ap:
            self._emit_event(
                s,
                tick=battle_tick,
                type="fleet_combat",
                message=f"Бой: «{dname}» отбил «{aname}» ({def_roll}:{atk_roll}).",
                payload={
                    "result": "defense_win",
                    "battle_calculation": calc_block,
                    "consequences": {
                        "destroyed_enemy_fleet_id": loser_id,
                        "your_fleet_after_battle": def_casualties,
                        "ship_loss_fraction_applied": round(loss_frac_d, 4),
                    },
                },
                player_id=dp,
            )
        return {
            "winner": "defender",
            "lost_attacker_id": loser_id,
            "rolls": {"attacker": atk_roll, "defender": def_roll},
        }

    def combat_preview_for_move(
        self,
        s: Session,
        *,
        player_id: str,
        fleet_id: str,
        target_x: int,
        target_y: int,
        target_z: int,
    ) -> dict:
        """Превью боя при прилёте на клетку (если там чужой флот)."""
        pid = uuid.UUID(player_id)
        try:
            fid = uuid.UUID(fleet_id)
        except Exception:
            return {"ok": False, "error": "invalid_fleet_id"}
        if target_z != 0:
            return {"ok": False, "error": "z_not_supported_yet"}
        atk = (
            s.execute(
                select(Fleet).where(Fleet.id == fid, Fleet.owner_player_id == pid)
            )
            .scalars()
            .first()
        )
        if not atk:
            return {"ok": False, "error": "fleet_not_found"}
        dfd = (
            s.execute(
                select(Fleet).where(
                    Fleet.pos_x == int(target_x),
                    Fleet.pos_y == int(target_y),
                    Fleet.pos_z == int(target_z),
                    Fleet.owner_player_id != pid,
                )
            )
            .scalars()
            .first()
        )
        if not dfd:
            return {"ok": True, "combat": False}
        prev = self.estimate_fleet_combat_preview(
            s,
            attacker=atk,
            defender=dfd,
            attacker_from_x=int(atk.pos_x),
            attacker_from_y=int(atk.pos_y),
        )
        return {"ok": True, **prev}

    def _enemy_fleet_at(
        self, s: Session, *, x: int, y: int, z: int, owner_player_id: uuid.UUID
    ) -> Fleet | None:
        return (
            s.execute(
                select(Fleet).where(
                    Fleet.pos_x == int(x),
                    Fleet.pos_y == int(y),
                    Fleet.pos_z == int(z),
                    Fleet.owner_player_id != owner_player_id,
                )
            )
            .scalars()
            .first()
        )

    def _nearest_cell_without_other_fleet(
        self,
        s: Session,
        *,
        center_x: int,
        center_y: int,
        center_z: int,
        exclude_fleet_id: uuid.UUID,
        max_ring: int = 60,
    ) -> tuple[int, int] | None:
        """Ближайшая клетка (BFS по сетке), где нет чужого флота; exclude_fleet_id не считается занятием."""
        start = (int(center_x), int(center_y))
        seen: set[tuple[int, int]] = {start}
        q: deque[tuple[int, int]] = deque([start])
        cz = int(center_z)
        while q:
            x, y = q.popleft()
            if abs(x - int(center_x)) + abs(y - int(center_y)) > max_ring:
                continue
            other = s.execute(
                select(Fleet.id).where(
                    Fleet.pos_x == x,
                    Fleet.pos_y == y,
                    Fleet.pos_z == cz,
                    Fleet.id != exclude_fleet_id,
                )
            ).first()
            if other is None:
                return (x, y)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if (nx, ny) in seen:
                    continue
                seen.add((nx, ny))
                q.append((nx, ny))
        return None

    def _resolve_expired_fleet_combat_prompts(
        self, s: Session, *, tick: int, events: list
    ) -> None:
        now = datetime.now(timezone.utc)
        expired = (
            s.execute(
                select(FleetOrder).where(
                    FleetOrder.status == "pending_combat",
                    FleetOrder.combat_prompt_expires_at.is_not(None),
                    FleetOrder.combat_prompt_expires_at <= now,
                )
            )
            .scalars()
            .all()
        )
        for order in expired:
            fleet = s.get(Fleet, order.fleet_id)
            if fleet and int(fleet.qty) >= 1:
                self._emit_event(
                    s,
                    tick=tick,
                    type="combat_prompt_expired",
                    message=(
                        f"Время подтверждения боя истекло — флот «{self._fleet_public_name(fleet)}» "
                        f"остаётся у ({fleet.pos_x},{fleet.pos_y})."
                    ),
                    payload={
                        "order_id": str(order.id),
                        "fleet_id": str(fleet.id),
                        "target": {
                            "x": order.target_x,
                            "y": order.target_y,
                            "z": order.target_z,
                        },
                    },
                    player_id=order.owner_player_id,
                )
            order.status = "done"
            order.combat_prompt_expires_at = None
            events.append({"type": "combat_prompt_expired", "order_id": str(order.id)})

    def resolve_fleet_combat_prompt(
        self, s: Session, *, player_id: str, order_id: str, attack: bool
    ) -> dict:
        """Второе подтверждение: attack=True — бой/заход; False — отказ (как истечение таймера)."""
        pid = uuid.UUID(player_id)
        try:
            oid = uuid.UUID(order_id)
        except Exception:
            return {"ok": False, "error": "invalid_order_id"}
        order = (
            s.execute(
                select(FleetOrder).where(
                    FleetOrder.id == oid, FleetOrder.owner_player_id == pid
                )
            )
            .scalars()
            .first()
        )
        if not order or order.status != "pending_combat":
            return {"ok": False, "error": "no_pending_combat"}
        now = datetime.now(timezone.utc)
        if order.combat_prompt_expires_at and order.combat_prompt_expires_at <= now:
            fleet_e = s.get(Fleet, order.fleet_id)
            bt = self.get_or_create_world_state(s).current_tick
            if fleet_e and int(fleet_e.qty) >= 1:
                self._emit_event(
                    s,
                    tick=bt,
                    type="combat_prompt_expired",
                    message=(
                        f"Время подтверждения боя истекло — флот «{self._fleet_public_name(fleet_e)}» "
                        f"остаётся у ({fleet_e.pos_x},{fleet_e.pos_y})."
                    ),
                    payload={
                        "order_id": str(order.id),
                        "fleet_id": str(fleet_e.id),
                        "target": {
                            "x": order.target_x,
                            "y": order.target_y,
                            "z": order.target_z,
                        },
                    },
                    player_id=pid,
                )
            order.status = "done"
            order.combat_prompt_expires_at = None
            return {"ok": False, "error": "combat_prompt_expired"}

        fleet = s.get(Fleet, order.fleet_id)
        if not fleet or int(fleet.qty) < 1:
            order.status = "failed"
            order.combat_prompt_expires_at = None
            return {"ok": False, "error": "fleet_not_found"}

        ws = self.get_or_create_world_state(s)
        battle_tick = int(ws.current_tick)

        if not attack:
            order.status = "done"
            order.combat_prompt_expires_at = None
            self._emit_event(
                s,
                tick=battle_tick,
                type="combat_prompt_declined",
                message=f"Атака отменена — флот «{self._fleet_public_name(fleet)}» остаётся у ({fleet.pos_x},{fleet.pos_y}).",
                payload={"order_id": str(order.id), "fleet_id": str(fleet.id)},
                player_id=pid,
            )
            return {"ok": True, "result": "declined"}

        defender = self._enemy_fleet_at(
            s, x=order.target_x, y=order.target_y, z=order.target_z, owner_player_id=pid
        )
        if not defender:
            fleet.pos_x = int(order.target_x)
            fleet.pos_y = int(order.target_y)
            fleet.pos_z = int(order.target_z)
            order.status = "done"
            order.combat_prompt_expires_at = None
            self._emit_event(
                s,
                tick=battle_tick,
                type="fleet_arrived",
                message=f"Флот прибыл: {fleet.unit_type}×{fleet.qty} в ({fleet.pos_x},{fleet.pos_y},{fleet.pos_z}) (враг ушёл с клетки)",
                payload={
                    "fleet_id": str(fleet.id),
                    "qty": fleet.qty,
                    "pos": {"x": fleet.pos_x, "y": fleet.pos_y, "z": fleet.pos_z},
                },
                player_id=pid,
            )
            return {"ok": True, "result": "walked_in"}

        own_block = (
            s.execute(
                select(Fleet).where(
                    Fleet.pos_x == int(order.target_x),
                    Fleet.pos_y == int(order.target_y),
                    Fleet.pos_z == int(order.target_z),
                    Fleet.owner_player_id == pid,
                    Fleet.id != fleet.id,
                )
            )
            .scalars()
            .first()
        )
        if own_block:
            order.status = "done"
            order.combat_prompt_expires_at = None
            self._emit_event(
                s,
                tick=battle_tick,
                type="fleet_order_failed",
                message="Атака отменена: в цели уже ваш другой флот.",
                payload={
                    "order_id": str(order.id),
                    "reason": "cell_occupied_by_own_fleet",
                },
                player_id=pid,
            )
            return {"ok": False, "error": "cell_occupied_by_own_fleet"}

        # Удаляем ордер до боя: иначе при проигрыше атакующего CASCADE по fleet_id удалит строку,
        # а ORM всё ещё попытается UPDATE — StaleDataError.
        s.delete(order)
        s.flush()

        self._resolve_fleet_vs_fleet_combat(
            s,
            attacker=fleet,
            defender=defender,
            attacker_from_x=int(fleet.pos_x),
            attacker_from_y=int(fleet.pos_y),
            battle_tick=battle_tick,
            event_player_id=pid,
        )
        return {"ok": True, "result": "combat"}

    def _pending_combat_prompts_payload(
        self, s: Session, *, player_id: uuid.UUID
    ) -> list[dict]:
        out: list[dict] = []
        orders = (
            s.execute(
                select(FleetOrder).where(
                    FleetOrder.owner_player_id == player_id,
                    FleetOrder.status == "pending_combat",
                )
            )
            .scalars()
            .all()
        )
        for order in orders:
            fleet = s.get(Fleet, order.fleet_id)
            if not fleet or int(fleet.qty) < 1:
                continue
            dfd = self._enemy_fleet_at(
                s,
                x=order.target_x,
                y=order.target_y,
                z=order.target_z,
                owner_player_id=player_id,
            )
            if not dfd:
                preview: dict = {"combat": False}
            else:
                preview = self.estimate_fleet_combat_preview(
                    s,
                    attacker=fleet,
                    defender=dfd,
                    attacker_from_x=int(fleet.pos_x),
                    attacker_from_y=int(fleet.pos_y),
                )
            exp = getattr(order, "combat_prompt_expires_at", None)
            out.append(
                {
                    "order_id": str(order.id),
                    "fleet_id": str(fleet.id),
                    "target": {
                        "x": order.target_x,
                        "y": order.target_y,
                        "z": order.target_z,
                    },
                    "staging": {"x": fleet.pos_x, "y": fleet.pos_y, "z": fleet.pos_z},
                    "expires_at": exp.isoformat() if exp else None,
                    "defender_fleet_id": str(dfd.id) if dfd else None,
                    "preview": preview,
                }
            )
        return out

    def _primary_colony_planet(
        self, s: Session, *, owner_id: uuid.UUID
    ) -> Planet | None:
        return (
            s.execute(
                select(Planet)
                .where(Planet.owner_player_id == owner_id)
                .order_by(Planet.created_at.asc())
            )
            .scalars()
            .first()
        )

    def _drydock_count_on_planet(
        self, s: Session, *, planet_id: uuid.UUID, owner_id: uuid.UUID
    ) -> int:
        return int(
            s.execute(
                select(func.count(Building.id)).where(
                    Building.planet_id == planet_id,
                    Building.owner_player_id == owner_id,
                    or_(
                        Building.building_type == "drydock_mini",
                        Building.building_type == "drydock_mini_t1",
                    ),
                )
            ).scalar()
            or 0
        )

    def _can_create_fleet_at_planet(
        self, s: Session, *, owner_id: uuid.UUID, planet: Planet
    ) -> bool:
        home = self._primary_colony_planet(s, owner_id=owner_id)
        if home and home.id == planet.id:
            return True
        return (
            self._drydock_count_on_planet(s, planet_id=planet.id, owner_id=owner_id) > 0
        )

    def _pick_fleet_spawn_xy(
        self, s: Session, *, owner_id: uuid.UUID, px: int, py: int, pz: int
    ) -> tuple[int, int] | None:
        offsets = [
            (0, -1),
            (-1, 0),
            (1, 0),
            (0, 1),
            (0, -2),
            (-2, 0),
            (2, 0),
            (0, 2),
            (-1, -1),
            (1, -1),
            (-1, 1),
            (1, 1),
        ]
        for dx, dy in offsets:
            tx, ty = px + dx, py + dy
            blocked = (
                s.execute(
                    select(Building.id).where(
                        Building.x == tx, Building.y == ty, Building.z == pz
                    )
                )
                .scalars()
                .first()
            )
            if blocked:
                continue
            occupied = (
                s.execute(
                    select(Fleet.id).where(
                        Fleet.pos_x == tx, Fleet.pos_y == ty, Fleet.pos_z == pz
                    )
                )
                .scalars()
                .first()
            )
            if occupied:
                continue
            return tx, ty
        return None

    def create_fleet(
        self,
        s: Session,
        *,
        player_id: str,
        planet_id: str,
        name: str | None,
        composition: dict | None,
    ) -> dict:
        pid = uuid.UUID(player_id)
        try:
            plid = uuid.UUID(planet_id)
        except Exception:
            return {"ok": False, "error": "invalid_planet_id"}
        planet = (
            s.execute(
                select(Planet).where(Planet.id == plid, Planet.owner_player_id == pid)
            )
            .scalars()
            .first()
        )
        if not planet:
            return {"ok": False, "error": "planet_not_found"}
        if not self._can_create_fleet_at_planet(s, owner_id=pid, planet=planet):
            return {"ok": False, "error": "no_shipyard_access"}

        spawn = self._pick_fleet_spawn_xy(
            s, owner_id=pid, px=planet.pos_x, py=planet.pos_y, pz=0
        )
        if not spawn:
            return {"ok": False, "error": "no_free_spawn_cell"}
        tx, ty = spawn

        if not isinstance(composition, dict) or not composition:
            return {"ok": False, "error": "invalid_composition"}
        allowed = self._logical_unit_keys()
        units: dict[str, int] = {}
        for raw_k, raw_v in composition.items():
            k = str(raw_k or "").strip().lower()
            if k not in allowed:
                return {"ok": False, "error": "invalid_unit_type", "unit_type": k}
            try:
                q = int(raw_v)
            except Exception:
                return {"ok": False, "error": "invalid_qty"}
            if q < 0:
                return {"ok": False, "error": "negative_qty"}
            if q > 0:
                units[k] = int(q)
        total = sum(units.values())
        if total < 1:
            return {"ok": False, "error": "fleet_empty"}
        if total > 50:
            return {"ok": False, "error": "fleet_too_large"}

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

        pay = {"metal": 0, "crystal": 0, "energy": 0, "fuel": 0}
        for ut, q in units.items():
            cst = self._unit_build_cost_parts(ut)
            for rk in pay:
                pay[rk] += int(cst.get(rk, 0)) * int(q)

        if (
            int(res.metal) < pay["metal"]
            or int(res.crystal) < pay["crystal"]
            or int(res.energy) < pay["energy"]
            or int(getattr(res, "fuel", 0)) < pay["fuel"]
        ):
            return {
                "ok": False,
                "error": "not_enough_resources",
                "need": pay,
                "have": {
                    "metal": int(res.metal),
                    "crystal": int(res.crystal),
                    "energy": int(res.energy),
                    "fuel": int(getattr(res, "fuel", 0)),
                },
            }

        res.metal = int(res.metal) - pay["metal"]
        res.crystal = int(res.crystal) - pay["crystal"]
        res.energy = int(res.energy) - pay["energy"]
        res.fuel = int(res.fuel) - pay["fuel"]

        nm = (
            name if isinstance(name, str) else ""
        ).strip() or self._next_fleet_default_name(s, owner_id=pid)
        if len(nm) > 64:
            return {"ok": False, "error": "name_too_long"}
        dominant = max(units.items(), key=lambda kv: (kv[1], kv[0]))[0]
        fleet = Fleet(
            owner_player_id=pid,
            unit_type=str(dominant),
            qty=0,
            pos_x=int(tx),
            pos_y=int(ty),
            pos_z=0,
            name=nm[:64],
        )
        s.add(fleet)
        s.flush()
        self._write_fleet_units(s, fleet, units)
        s.flush()

        ws = self.get_or_create_world_state(s)
        self._emit_event(
            s,
            tick=ws.current_tick,
            type="fleet_created",
            message=f"Создан флот «{fleet.name}» у планеты {planet.name}",
            payload={
                "fleet_id": str(fleet.id),
                "name": fleet.name,
                "pos": {"x": tx, "y": ty, "z": 0},
                "composition": dict(units),
            },
            player_id=pid,
        )
        return {
            "ok": True,
            "fleet_id": str(fleet.id),
            "name": fleet.name,
            "pos": {"x": tx, "y": ty, "z": 0},
            "composition": dict(units),
            "cost": pay,
        }

    def _active_order_for_unit(
        self, s: Session, *, unit_id: uuid.UUID
    ) -> UnitOrder | None:
        return (
            s.execute(
                select(UnitOrder)
                .where(
                    UnitOrder.unit_id == unit_id,
                    UnitOrder.status.in_(["queued", "in_progress"]),
                )
                .order_by(UnitOrder.created_at.desc())
            )
            .scalars()
            .first()
        )

    def _active_order_for_fleet(
        self, s: Session, *, fleet_id: uuid.UUID
    ) -> FleetOrder | None:
        return (
            s.execute(
                select(FleetOrder)
                .where(
                    FleetOrder.fleet_id == fleet_id,
                    FleetOrder.status.in_(["queued", "in_progress", "pending_combat"]),
                )
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
        force_attack: bool = False,
    ) -> dict:
        pid = uuid.UUID(player_id)
        fid = uuid.UUID(fleet_id)

        fleet = (
            s.execute(
                select(Fleet).where(Fleet.id == fid, Fleet.owner_player_id == pid)
            )
            .scalars()
            .first()
        )
        if not fleet:
            return {"ok": False, "error": "fleet_not_found"}
        if fleet.qty < 1:
            return {"ok": False, "error": "fleet_empty"}
        if target_z != 0:
            return {"ok": False, "error": "z_not_supported_yet"}

        units_map = self._fleet_units_map(s, fleet)
        if not units_map:
            return {"ok": False, "error": "fleet_empty"}

        if self._active_order_for_fleet(s, fleet_id=fleet.id):
            return {"ok": False, "error": "active_order_exists"}

        ally_at = (
            s.execute(
                select(Fleet).where(
                    Fleet.pos_x == int(target_x),
                    Fleet.pos_y == int(target_y),
                    Fleet.pos_z == int(target_z),
                    Fleet.owner_player_id == pid,
                    Fleet.id != fleet.id,
                )
            )
            .scalars()
            .first()
        )
        if ally_at:
            return {"ok": False, "error": "cell_occupied_by_own_fleet"}

        distance = abs(target_x - fleet.pos_x) + abs(target_y - fleet.pos_y)
        if distance == 0:
            return {"ok": False, "error": "target_same_cell"}
        travel_ticks = self._fleet_travel_ticks_for_distance(
            distance=distance, units=units_map
        )
        travel = type(
            "TravelPlan",
            (),
            {"distance": int(distance), "travel_ticks": int(travel_ticks)},
        )

        self._sync_fleet_energy_scale(s, fleet)

        # Energy (fleet-local): движение тратит энергию флота, не энергию империи.
        move_energy_cost = int(
            max(1, self._fleet_upkeep_energy_total(s, player_id=pid, units=units_map))
            * int(travel.distance)
        )
        mx = int(getattr(fleet, "max_energy", FLEET_ENERGY_MAX_FLOOR) or FLEET_ENERGY_MAX_FLOOR)
        fx, fy, fz = int(fleet.pos_x), int(fleet.pos_y), int(getattr(fleet, "pos_z", 0) or 0)
        # В зоне снабжения линия даёт энергию постепенно (+2/тик), но без «полного колодца»
        # на астероиде флот мог остаться с E=0 и не пройти короткий перелёт — перед приказом
        # считаем, что снабжение даёт рабочий заряд для манёвра в пределах сети.
        if self._is_cell_supplied(s, owner_id=pid, x=fx, y=fy, z=fz):
            fleet.energy = mx
            cur_e = mx
        else:
            cur_e = int(getattr(fleet, "energy", 0) or 0)
        if cur_e < move_energy_cost:
            return {
                "ok": False,
                "error": "not_enough_fleet_energy",
                "need": move_energy_cost,
                "have": cur_e,
            }
        fleet.energy = int(cur_e) - int(move_energy_cost)

        # Fuel (MVP): списываем с ресурсов домашней планеты владельца.
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

        fuel_plan = type(
            "FuelPlan",
            (),
            {
                "fuel_cost": int(
                    self._fleet_fuel_cost_total(
                        s,
                        player_id=str(player_id),
                        fleet=fleet,
                        distance=int(travel.distance),
                        units=units_map,
                    )
                )
            },
        )
        if int(getattr(res, "fuel", 0)) < fuel_plan.fuel_cost:
            self._emit_event(
                s,
                tick=self.get_or_create_world_state(s).current_tick,
                type="not_enough_fuel",
                message=f"Не хватает топлива для перелёта (нужно {fuel_plan.fuel_cost}, есть {int(getattr(res, 'fuel', 0))})",
                payload={
                    "need": fuel_plan.fuel_cost,
                    "have": int(getattr(res, "fuel", 0)),
                    "distance": travel.distance,
                    "qty": fleet.qty,
                },
                player_id=pid,
            )
            return {
                "ok": False,
                "error": "not_enough_fuel",
                "need": fuel_plan.fuel_cost,
                "have": int(getattr(res, "fuel", 0)),
            }

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
            force_attack=bool(force_attack),
            combat_prompt_expires_at=None,
        )
        s.add(order)
        s.flush()

        self._emit_event(
            s,
            tick=ws.current_tick,
            type="fleet_order_created",
            message=f"Приказ флота: {fleet.qty} кораблей → ({target_x},{target_y},{target_z})",
            payload={
                "order_id": str(order.id),
                "fleet_id": str(fleet.id),
                "from": {"x": order.from_x, "y": order.from_y, "z": order.from_z},
                "target": {
                    "x": order.target_x,
                    "y": order.target_y,
                    "z": order.target_z,
                },
                "qty": order.qty,
                "composition": dict(units_map),
                "travel_ticks": travel.travel_ticks,
                "fuel_cost": fuel_plan.fuel_cost,
            },
            player_id=pid,
        )
        self._emit_event(
            s,
            tick=ws.current_tick,
            type="fuel_spent",
            message=f"Топливо потрачено: -{fuel_plan.fuel_cost} (перелёт, {fleet.qty} кораблей)",
            payload={
                "fuel_cost": fuel_plan.fuel_cost,
                "distance": travel.distance,
                "qty": fleet.qty,
                "fleet_id": str(fleet.id),
            },
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
            "travel_sols": int(travel.travel_ticks),
            "start_tick": order.start_tick,
            "start_sol": int(order.start_tick),
            "finish_tick": order.finish_tick,
            "finish_sol": int(order.finish_tick),
            "fuel_cost": fuel_plan.fuel_cost,
        }

    def cancel_fleet_order(self, s: Session, *, player_id: str, fleet_id: str) -> dict:
        pid = uuid.UUID(player_id)
        fid = uuid.UUID(fleet_id)

        fleet = s.execute(
            select(Fleet).where(Fleet.id == fid, Fleet.owner_player_id == pid)
        ).scalar_one_or_none()
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

    def create_scout_move_order(
        self, s: Session, *, player_id: str, target_x: int, target_y: int, target_z: int
    ) -> dict:
        pid = uuid.UUID(player_id)

        home = s.execute(
            select(Planet).where(Planet.owner_player_id == pid)
        ).scalar_one_or_none()
        if not home:
            return {"ok": False, "error": "no_home_planet"}

        if target_z != 0:
            return {"ok": False, "error": "z_not_supported_yet"}

        scout_unit = s.execute(
            select(Unit).where(
                Unit.owner_player_id == pid,
                Unit.planet_id == home.id,
                Unit.unit_type == "scout",
            )
        ).scalar_one_or_none()

        # Для "клик по клетке -> лететь" используем существующий scout fleet игрока.
        # Никаких автосозданий: иначе можно "напечатать" бесконечно много скаутов.
        source_fleet = None
        for cand in s.execute(
            select(Fleet)
            .where(Fleet.owner_player_id == pid)
            .order_by(Fleet.created_at.asc())
        ).scalars():
            um = self._fleet_units_map(s, cand)
            if int(um.get("scout", 0)) > 0:
                source_fleet = cand
                break
        if not source_fleet or source_fleet.qty < 1:
            return {"ok": False, "error": "not_enough_scouts"}

        from_x, from_y, from_z = (
            source_fleet.pos_x,
            source_fleet.pos_y,
            source_fleet.pos_z,
        )

        # Ордеры движения должны быть через FleetOrder. UnitOrder здесь — устаревшая ветка.
        return self.create_fleet_move_order(
            s,
            player_id=player_id,
            fleet_id=str(source_fleet.id),
            target_x=target_x,
            target_y=target_y,
            target_z=target_z,
        )

