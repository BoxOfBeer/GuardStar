"""Осада полевых построек, урон форпосту флотом, территория корсаров."""

from __future__ import annotations

import random as _random
import uuid

from app.services.world_service._deps import *  # noqa: F403
from app.services.world_service.constants import (
    BANDIT_PLAYER_ID,
    CIVILIAN_NPC_PLAYER_ID,
    NPC_FLEET_PLAYER_IDS,
)


class WorldServiceMixin07:
    def _warfare_economy(self, s: Session | None = None) -> dict:
        eco = self._merged_pack_economy(s)
        fb = eco.get("field_building_capture")
        fb = fb if isinstance(fb, dict) else {}
        bs = eco.get("outpost_bombard")
        bs = bs if isinstance(bs, dict) else {}
        bf = eco.get("bandit_wilderness")
        bf = bf if isinstance(bf, dict) else {}
        bm = eco.get("bandit_strike_wing")
        bm = bm if isinstance(bm, dict) else {}
        bp = eco.get("bandit_patrol_wing")
        bp = bp if isinstance(bp, dict) else {}
        smin = int(bm.get("cooldown_sol_min", 150) or 150)
        smax = int(bm.get("cooldown_sol_max", 200) or 200)
        if smax < smin:
            smin, smax = smax, smin
        ormin = int(bp.get("orbit_radius_manhattan_min", 4) or 4)
        ormax = int(bp.get("orbit_radius_manhattan_max", 5) or 5)
        if ormax < ormin:
            ormin, ormax = ormax, ormin
        fmin = int(bp.get("fighter_min", 4) or 4)
        fmax = int(bp.get("fighter_max", 5) or 5)
        if fmax < fmin:
            fmin, fmax = fmax, fmin
        rsp_min = int(bp.get("respawn_sol_min", 15) or 15)
        rsp_max = int(bp.get("respawn_sol_max", 25) or 25)
        if rsp_max < rsp_min:
            rsp_min, rsp_max = rsp_max, rsp_min
        spawn_loop = max(1, int(bf.get("spawn_loop_attempts", 10) or 10))
        spawn_half = max(0, int(bf.get("spawn_window_manhattan_half", 40) or 40))
        mine_ch = float(bf.get("mine_spawn_chance", 0.5) or 0.5)
        mine_ch = max(0.0, min(1.0, mine_ch))
        outpost_ch = float(bf.get("outpost_spawn_chance", 0.28) or 0.28)
        outpost_ch = max(0.0, min(1.0, outpost_ch))
        sep = max(0, int(bf.get("min_separation_from_bandit_outpost_manhattan", 6) or 6))
        announce_extra = max(0, int(bp.get("announce_warn_extra_manhattan", 6) or 6))
        st_fi_min = max(1, int(bm.get("strike_fighter_min", 3) or 3))
        st_fi_max = max(st_fi_min, int(bm.get("strike_fighter_max", 5) or 5))
        st_co_min = max(1, int(bm.get("strike_corvette_min", 3) or 3))
        st_co_max = max(st_co_min, int(bm.get("strike_corvette_max", 5) or 5))
        rtry_lo = max(1, int(bm.get("spawn_retry_sol_min", 8) or 8))
        rtry_hi = max(rtry_lo, int(bm.get("spawn_retry_sol_max", 20) or 20))
        st_scout = max(0, int(bm.get("strike_scout_count", 1) or 1))
        patrol_e = max(1, int(bp.get("spawn_energy", 200) or 200))
        patrol_me = max(patrol_e, int(bp.get("spawn_max_energy", 240) or 240))
        strike_e = max(1, int(bm.get("spawn_energy", 220) or 220))
        strike_me = max(strike_e, int(bm.get("spawn_max_energy", 260) or 260))
        cand: list[tuple[int, int]] = []
        offs_raw = bf.get("outpost_candidate_offsets")
        if isinstance(offs_raw, list):
            for it in offs_raw:
                if isinstance(it, (list, tuple)) and len(it) >= 2:
                    cand.append((int(it[0]), int(it[1])))
        if not cand:
            cand = [(2, 0), (-2, 0), (0, 2), (0, -2)]
        return {
            "field_progress_per_sol": float(fb.get("progress_per_sol", 0.25) or 0.25),
            "field_resistance": float(fb.get("resistance_default", 5.0) or 5.0),
            "field_event_every_n_ticks": int(fb.get("event_every_n_ticks", 5) or 5),
            "bombard_range": int(bs.get("fleet_range_manhattan", 3) or 3),
            "chunk_size": max(6, int(bf.get("chunk_side", 10) or 10)),
            "max_bandit_mines_per_chunk": int(bf.get("max_mines_per_chunk", 5) or 5),
            "max_bandit_outposts_per_chunk": int(bf.get("max_outposts_per_chunk", 2) or 2),
            "max_bandit_outposts_world": max(
                1, int(bf.get("max_outposts_world", 8) or 8)
            ),
            "bandit_spawn_every_n_ticks": max(5, int(bf.get("every_n_ticks", 15) or 15)),
            "bandit_ai_every_n_ticks": max(
                1, int(bf.get("ai_every_n_ticks", 5) or 5)
            ),
            "strike_min": smin,
            "strike_max": smax,
            "strike_spawn_max_global_per_pass": max(
                1, int(bm.get("max_spawn_per_tick_global", 1) or 1)
            ),
            "patrol_orbit_radius_min": ormin,
            "patrol_orbit_radius_max": ormax,
            "patrol_fighter_min": fmin,
            "patrol_fighter_max": fmax,
            "patrol_aggro_radius": max(ormax, int(bp.get("aggro_radius_manhattan", 5) or 5)),
            "patrol_respawn_sol_min": rsp_min,
            "patrol_respawn_sol_max": rsp_max,
            "wilderness_spawn_loop_attempts": spawn_loop,
            "wilderness_spawn_window_manhattan_half": spawn_half,
            "wilderness_mine_spawn_chance": mine_ch,
            "wilderness_outpost_spawn_chance": outpost_ch,
            "min_separation_from_bandit_outpost_manhattan": sep,
            "patrol_announce_warn_extra_manhattan": announce_extra,
            "strike_fighter_min": st_fi_min,
            "strike_fighter_max": st_fi_max,
            "strike_corvette_min": st_co_min,
            "strike_corvette_max": st_co_max,
            "strike_spawn_retry_sol_min": rtry_lo,
            "strike_spawn_retry_sol_max": rtry_hi,
            "strike_scout_count": st_scout,
            "patrol_spawn_energy": patrol_e,
            "patrol_spawn_max_energy": patrol_me,
            "strike_spawn_energy": strike_e,
            "strike_spawn_max_energy": strike_me,
            "outpost_candidate_offsets": cand,
        }

    def _ensure_outpost_hp_current(self, s: Session, *, outpost: Outpost) -> int:
        st = self._outpost_stats(s, outpost, viewer_player_id=None)
        cmb = st.get("combat") if isinstance(st.get("combat"), dict) else {}
        hp_max = int(cmb.get("hp_max") or cmb.get("hp", 0) or 420)
        hc = getattr(outpost, "hp_current", None)
        if hc is None:
            outpost.hp_current = hp_max
            return hp_max
        cur = int(hc)
        if cur > hp_max:
            outpost.hp_current = hp_max
            return hp_max
        return cur

    def _manhattan(self, ax: int, ay: int, bx: int, by: int) -> int:
        return abs(int(ax) - int(bx)) + abs(int(ay) - int(by))

    def _bandit_pick_adjacent_spawn(
        self, s: Session, *, cx: int, cy: int, cz: int
    ) -> tuple[int, int] | None:
        offs = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        _random.shuffle(offs)
        for dx, dy in offs:
            tx_, ty_ = int(cx) + dx, int(cy) + dy
            if not self._cell_blocked_for_fleet(s, tx_, ty_, int(cz)):
                return tx_, ty_
        return None

    def _spawn_bandit_patrol_for_outpost(
        self,
        s: Session,
        *,
        npc: Player,
        outpost: Outpost,
        tick: int,
        wc: dict,
        for_new_outpost: bool = False,
    ) -> None:
        if self._admin_master_spawn_block(s):
            return
        if not for_new_outpost and self._admin_block_bandit_extra_fleets(s):
            return
        if getattr(outpost, "patrol_fleet_id", None):
            return
        sp = self._bandit_pick_adjacent_spawn(
            s, cx=int(outpost.x), cy=int(outpost.y), cz=int(outpost.z)
        )
        if sp is None:
            return
        sx_, sy_ = sp
        nf = _random.randint(
            int(wc["patrol_fighter_min"]), int(wc["patrol_fighter_max"])
        )
        fg = Fleet(
            owner_player_id=npc.id,
            unit_type="fighter",
            qty=0,
            pos_x=int(sx_),
            pos_y=int(sy_),
            pos_z=int(outpost.z),
            hunt_target_fleet_id=None,
            patrol_outpost_id=outpost.id,
            bandit_hunt_announced=False,
            energy=int(wc["patrol_spawn_energy"]),
            max_energy=int(wc["patrol_spawn_max_energy"]),
            name="Патруль корсаров",
        )
        s.add(fg)
        s.flush()
        self._write_fleet_units(s, fg, {"fighter": int(nf)})
        self._sync_fleet_energy_scale(s, fg)
        outpost.patrol_fleet_id = fg.id
        ox, oy = int(outpost.x), int(outpost.y)
        oz = int(outpost.z)
        agro = int(wc["patrol_aggro_radius"])
        near: set[uuid.UUID] = set()
        warn_r = agro + int(wc["patrol_announce_warn_extra_manhattan"])
        npc_sql = tuple(NPC_FLEET_PLAYER_IDS)
        for fln in (
            s.execute(
                select(Fleet).where(
                    Fleet.owner_player_id.not_in(npc_sql),
                    Fleet.pos_z == oz,
                    Fleet.pos_x >= ox - warn_r,
                    Fleet.pos_x <= ox + warn_r,
                    Fleet.pos_y >= oy - warn_r,
                    Fleet.pos_y <= oy + warn_r,
                )
            )
            .scalars()
            .all()
        ):
            if int(self._fleet_total_units(s, fln)) <= 0:
                continue
            if self._manhattan(ox, oy, int(fln.pos_x), int(fln.pos_y)) <= warn_r:
                near.add(fln.owner_player_id)
        for pid in sorted(near, key=lambda x: str(x)):
            self._emit_event(
                s,
                tick=tick,
                type="bandit_patrol_spawned",
                message=(
                    f"! Корсарский форпост ({ox},{oy}) поднял патруль орбиты; "
                    f"зона агро ~{agro} кл. от базы."
                ),
                payload={
                    "kind": "patrol",
                    "outpost_id": str(outpost.id),
                    "fleet_id": str(fg.id),
                    "outpost_pos": {"x": ox, "y": oy, "z": int(outpost.z)},
                    "aggro_radius": agro,
                },
                player_id=pid,
            )
        s.flush()

    def _sync_bandit_patrol_health_and_respawn(self, s: Session, *, tick: int) -> None:
        wc = self._warfare_economy(s)
        npc = self._ensure_bandit_player(s)
        ops = (
            s.execute(
                select(Outpost).where(
                    Outpost.owner_player_id == BANDIT_PLAYER_ID,
                    Outpost.status == "active",
                )
            )
            .scalars()
            .all()
        )
        for op in ops:
            pfid = getattr(op, "patrol_fleet_id", None)
            if pfid is not None:
                row = s.get(Fleet, pfid)
                if row is None or int(self._fleet_total_units(s, row)) <= 0:
                    op.patrol_fleet_id = None
                    rr = _random.randint(
                        int(wc["patrol_respawn_sol_min"]),
                        int(wc["patrol_respawn_sol_max"]),
                    )
                    op.patrol_respawn_at_tick = int(tick) + int(rr)
                    s.flush()
            else:
                rs = int(getattr(op, "patrol_respawn_at_tick", 0) or 0)
                if int(tick) >= rs:
                    self._spawn_bandit_patrol_for_outpost(
                        s,
                        npc=npc,
                        outpost=op,
                        tick=tick,
                        wc=wc,
                        for_new_outpost=False,
                    )

    def _apply_bandit_patrol_move_tick(self, s: Session, *, tick: int) -> None:
        wc = self._warfare_economy(s)
        patrols = (
            s.execute(
                select(Fleet).where(
                    Fleet.owner_player_id == BANDIT_PLAYER_ID,
                    Fleet.patrol_outpost_id.is_not(None),
                )
            )
            .scalars()
            .all()
        )
        if not patrols:
            return
        npc_sql = tuple(NPC_FLEET_PLAYER_IDS)
        prey_pool = (
            s.execute(
                select(Fleet).where(Fleet.owner_player_id.not_in(npc_sql))
            )
            .scalars()
            .all()
        )
        for fl in patrols:
            opid = fl.patrol_outpost_id
            if opid is None:
                continue
            op = s.get(Outpost, opid)
            um = self._fleet_units_map(s, fl)
            if (
                op is None
                or op.status != "active"
                or str(op.owner_player_id) != str(BANDIT_PLAYER_ID)
                or not um
            ):
                self._purge_fleet_row(s, fl)
                s.flush()
                continue
            if int(self._fleet_total_units(s, fl)) <= 0:
                continue
            ox, oy, oz = int(op.x), int(op.y), int(op.z)
            r_cap = int(wc["patrol_orbit_radius_max"])
            agro = int(wc["patrol_aggro_radius"])

            prey: Fleet | None = None
            best_dm = 10**9
            for prey_cand in prey_pool:
                if int(self._fleet_total_units(s, prey_cand)) <= 0:
                    continue
                if int(prey_cand.pos_z) != oz:
                    continue
                d_hub = self._manhattan(
                    ox, oy, int(prey_cand.pos_x), int(prey_cand.pos_y)
                )
                if d_hub > agro:
                    continue
                dm = self._manhattan(
                    int(fl.pos_x), int(fl.pos_y), int(prey_cand.pos_x), int(prey_cand.pos_y)
                )
                if dm < best_dm:
                    best_dm = dm
                    prey = prey_cand

            fx, fy = int(fl.pos_x), int(fl.pos_y)
            fz = int(fl.pos_z)

            def _patrol_engages_player(*, hunter: Fleet, victim: Fleet) -> None:
                afx, afy = self._attacker_neighbor_for_fleet_vs_fleet(
                    s, cell_x=int(hunter.pos_x), cell_y=int(hunter.pos_y), cell_z=fz
                )
                self._resolve_fleet_vs_fleet_combat(
                    s,
                    attacker=hunter,
                    defender=victim,
                    attacker_from_x=afx,
                    attacker_from_y=afy,
                    battle_tick=tick,
                    event_player_id=hunter.owner_player_id,
                )
                s.flush()

            if prey is not None:
                tx, ty = int(prey.pos_x), int(prey.pos_y)
                if fx == tx and fy == ty:
                    _patrol_engages_player(hunter=fl, victim=prey)
                    continue
                if abs(tx - fx) >= abs(ty - fy):
                    dx = 1 if tx > fx else (-1 if tx < fx else 0)
                    dy = 0
                else:
                    dx = 0
                    dy = 1 if ty > fy else (-1 if ty < fy else 0)
                cand_steps: list[tuple[int, int]] = [(fx + dx, fy + dy)]
                cand_steps.extend(
                    (fx + sx, fy + sy)
                    for sx, sy in _random.sample(
                        [(1, 0), (-1, 0), (0, 1), (0, -1)], k=4
                    )
                )
                nx, ny = fx, fy
                for tcx, tcy in cand_steps:
                    if tcx == fx and tcy == fy:
                        continue
                    if abs(tcx - fx) + abs(tcy - fy) != 1:
                        continue
                    if self._cell_blocked_for_fleet(
                        s, tcx, tcy, fz, enter_to_attack_fleet_id=prey.id
                    ):
                        continue
                    if self._manhattan(tcx, tcy, ox, oy) <= r_cap:
                        nx, ny = tcx, tcy
                        break
                if (nx, ny) != (fx, fy):
                    fl.pos_x, fl.pos_y = nx, ny
                    fx, fy = nx, ny
                if prey and fx == int(prey.pos_x) and fy == int(prey.pos_y):
                    _patrol_engages_player(hunter=fl, victim=prey)
                s.flush()
                continue

            neigh = [(1, 0), (-1, 0), (0, 1), (0, -1)]
            _random.shuffle(neigh)
            nx, ny = fx, fy
            for sx, sy in neigh:
                tcx, tcy = fx + sx, fy + sy
                if self._cell_blocked_for_fleet(s, tcx, tcy, fz):
                    continue
                if self._manhattan(tcx, tcy, ox, oy) <= r_cap:
                    nx, ny = tcx, tcy
                    break
            if (nx, ny) != (fx, fy):
                fl.pos_x, fl.pos_y = nx, ny
            at_cell = (
                s.execute(
                    select(Fleet).where(
                        Fleet.pos_x == int(fl.pos_x),
                        Fleet.pos_y == int(fl.pos_y),
                        Fleet.pos_z == fz,
                        Fleet.id != fl.id,
                    )
                )
                .scalars()
                .all()
            )
            for occ in at_cell:
                if occ.owner_player_id in NPC_FLEET_PLAYER_IDS:
                    continue
                if int(self._fleet_total_units(s, occ)) <= 0:
                    continue
                if self._manhattan(int(occ.pos_x), int(occ.pos_y), ox, oy) > agro:
                    continue
                _patrol_engages_player(hunter=fl, victim=occ)
                break
            s.flush()

    def _destroy_outpost_row(self, s: Session, *, outpost: Outpost, tick: int) -> None:
        oid = outpost.id
        opid = outpost.owner_player_id
        px, py, pz = int(outpost.x), int(outpost.y), int(outpost.z)
        patrol_id = getattr(outpost, "patrol_fleet_id", None)
        if patrol_id:
            prow = s.get(Fleet, patrol_id)
            if prow is not None:
                self._purge_fleet_row(s, prow)
        s.execute(delete(OutpostModule).where(OutpostModule.outpost_id == oid))
        s.delete(outpost)
        s.flush()
        self._emit_event(
            s,
            tick=tick,
            type="outpost_destroyed",
            message=f"Форпост уничтожен на ({px},{py},{pz})",
            payload={"outpost_id": str(oid), "pos": {"x": px, "y": py, "z": pz}},
            player_id=opid,
        )

    def _apply_field_building_capture_tick(self, s: Session, *, tick: int) -> None:
        wc = self._warfare_economy(s)
        step = float(wc["field_progress_per_sol"])
        resist = float(wc["field_resistance"])
        every_n = max(1, int(wc["field_event_every_n_ticks"]))

        buildings = s.execute(select(Building)).scalars().all()
        fleets_all = (
            s.execute(select(Fleet).where(Fleet.qty > 0)).scalars().all()
        )
        fleets_by_xyz: dict[tuple[int, int, int], list[Fleet]] = {}
        for f in fleets_all:
            k = (int(f.pos_x), int(f.pos_y), int(f.pos_z))
            fleets_by_xyz.setdefault(k, []).append(f)

        for b in buildings:
            if b.owner_player_id == CIVILIAN_NPC_PLAYER_ID:
                continue

            bx, by, bz = int(b.x), int(b.y), int(b.z)
            if self._cell_has_planet(s, x=bx, y=by, z=bz):
                if float(getattr(b, "capture_progress", 0) or 0) > 0 or getattr(
                    b, "capture_attacker_id", None
                ):
                    b.capture_progress = 0.0
                    b.capture_attacker_id = None
                    s.flush()
                continue

            at_cell = fleets_by_xyz.get((bx, by, bz), [])
            contenders: list[tuple[float, Fleet]] = []
            for f in at_cell:
                if f.owner_player_id == b.owner_player_id:
                    continue
                if f.owner_player_id in NPC_FLEET_PLAYER_IDS:
                    continue
                um = self._fleet_units_map(s, f)
                if not um or sum(int(v) for v in um.values()) <= 0:
                    continue
                sc = float(
                    self._fleet_combat_score(s, fleet=f, player_id=f.owner_player_id)
                    or 0.0
                )
                contenders.append((sc, f))
            contenders.sort(key=lambda t: (-t[0], str(t[1].id)))

            prev_att = getattr(b, "capture_attacker_id", None)
            prog = float(getattr(b, "capture_progress", 0) or 0)

            if not contenders:
                if prog > 0 or prev_att is not None:
                    b.capture_progress = 0.0
                    b.capture_attacker_id = None
                    s.flush()
                continue

            best = contenders[0][1]
            att_id = best.owner_player_id

            if prev_att is not None and prev_att != att_id:
                b.capture_progress = 0.0
            b.capture_attacker_id = att_id

            old_nf = int(prog // 1.0)
            new_prog = float(prog + step)
            b.capture_progress = new_prog
            nf = int(new_prog // 1.0)

            defender_id = b.owner_player_id

            emit_mid = tick % every_n == 0 or nf > old_nf
            if emit_mid and new_prog < resist:
                msg_a = (
                    f"⚠ Захват внешней постройки (+{step:g}/сол): "
                    f"{new_prog:.1f}/{resist:g} ({bx},{by})"
                )
                pay = {
                    "building_id": str(b.id),
                    "building_type": b.building_type,
                    "progress": round(new_prog, 3),
                    "resistance": resist,
                    "pos": {"x": bx, "y": by, "z": bz},
                    "role": "attacker",
                }
                self._emit_event(
                    s,
                    tick=tick,
                    type="field_building_capture_tick",
                    message=msg_a,
                    payload=pay,
                    player_id=att_id,
                )
                msg_d = (
                    f"⚠ Противник захватывает вашу постройку "
                    f"({new_prog:.1f}/{resist:g}) на ({bx},{by},{bz})"
                )
                pay_d = dict(pay)
                pay_d["role"] = "defender"
                self._emit_event(
                    s,
                    tick=tick,
                    type="field_building_capture_tick",
                    message=msg_d,
                    payload=pay_d,
                    player_id=defender_id,
                )

            if new_prog >= resist:
                home = (
                    s.execute(
                        select(Planet)
                        .where(Planet.owner_player_id == att_id)
                        .order_by(Planet.created_at.asc())
                    )
                    .scalars()
                    .first()
                )
                bt = str(b.building_type)
                b.owner_player_id = att_id
                if home:
                    b.planet_id = home.id
                b.capture_progress = 0.0
                b.capture_attacker_id = None
                s.flush()
                self._emit_event(
                    s,
                    tick=tick,
                    type="building_captured",
                    message=(
                        f"⚠ Захват: постройка «{bt}» на ({bx},{by},{bz}) — теперь ваша колония"
                    ),
                    payload={
                        "building_id": str(b.id),
                        "building_type": bt,
                        "pos": {"x": bx, "y": by, "z": bz},
                    },
                    player_id=att_id,
                )
                self._emit_event(
                    s,
                    tick=tick,
                    type="building_lost_capture",
                    message=(
                        f"⚠ Потеря: «{bt}» на ({bx},{by},{bz}) захватил противник "
                        f"(внешнее поле)."
                    ),
                    payload={
                        "building_id": str(b.id),
                        "building_type": bt,
                        "pos": {"x": bx, "y": by, "z": bz},
                        "lost_to": str(att_id),
                    },
                    player_id=defender_id,
                )

    def _apply_fleet_bombard_outposts_tick(self, s: Session, *, tick: int) -> None:
        wc = self._warfare_economy(s)
        rng_dist = max(1, int(wc["bombard_range"]))

        outposts = (
            s.execute(select(Outpost).where(Outpost.status == "active"))
            .scalars()
            .all()
        )
        if not outposts:
            return

        fleets = (
            s.execute(select(Fleet).where(Fleet.qty > 0)).scalars().all()
        )
        attacker_fleets = [
            f
            for f in fleets
            if f.owner_player_id not in NPC_FLEET_PLAYER_IDS
            and int(self._fleet_total_units(s, f)) > 0
            and getattr(f, "hunt_target_fleet_id", None) is None
            and getattr(f, "patrol_outpost_id", None) is None
        ]

        for op in outposts:
            hc_start = self._ensure_outpost_hp_current(s, outpost=op)
            if hc_start <= 0:
                continue
            st = self._outpost_stats(s, op, viewer_player_id=str(op.owner_player_id))
            cmb = st.get("combat") if isinstance(st.get("combat"), dict) else {}
            hp_max = max(1, int(cmb.get("hp_max") or cmb.get("hp", hc_start) or 1))
            defn = float(max(1.0, float(cmb.get("defense", 8) or 8)))
            ox, oy, oz = int(op.x), int(op.y), int(op.z)

            total_dmg = 0
            per_fleet: list[tuple[uuid.UUID, int, int]] = []
            for f in attacker_fleets:
                if f.owner_player_id == op.owner_player_id:
                    continue
                if int(f.pos_z) != oz:
                    continue
                dman = abs(int(f.pos_x) - ox) + abs(int(f.pos_y) - oy)
                if dman > rng_dist:
                    continue
                um = self._fleet_units_map(s, f)
                score = float(
                    self._fleet_combat_score(
                        s, fleet=f, player_id=f.owner_player_id
                    )
                    or 35.0
                )
                raw = score / max(42.0, defn + 18.0)
                frac = min(0.11, max(0.035, raw / 14.5))
                dmg_cell = max(18, min(130, int(hp_max * frac + score * 0.065)))
                total_dmg += dmg_cell
                per_fleet.append((f.owner_player_id, dmg_cell, int(dman)))

            if total_dmg <= 0:
                continue

            nim = max(0, int(op.hp_current or 0) - int(total_dmg))
            op.hp_current = nim
            s.flush()

            self._emit_event(
                s,
                tick=tick,
                type="outpost_under_bombardment",
                message=(
                    f"⚠ Ваш форпост ({ox},{oy}) −{total_dmg} HP от флотов игроков."
                ),
                payload={
                    "outpost_id": str(op.id),
                    "damage": int(total_dmg),
                    "hp_left": nim,
                    "hp_max": hp_max,
                },
                player_id=op.owner_player_id,
            )
            for oid, dmg_cell, dm in per_fleet:
                self._emit_event(
                    s,
                    tick=tick,
                    type="fleet_bombards_outpost",
                    message=(
                        f"⚠ Обстрел форпоста: −{dmg_cell} HP (дистанция {dm}), "
                        f"остаток узла защиты {nim}"
                    ),
                    payload={
                        "outpost_id": str(op.id),
                        "damage": int(dmg_cell),
                        "distance": dm,
                        "hp_left_target": nim,
                        "pos": {"x": ox, "y": oy, "z": oz},
                    },
                    player_id=oid,
                )

            if nim <= 0:
                self._destroy_outpost_row(s, outpost=op, tick=tick)

    def _chunk_key_xy(self, x: int, y: int, size: int) -> tuple[int, int]:
        return (int(x) // int(size), int(y) // int(size))

    def _bandit_mine_ops_in_chunk(
        self, s: Session, cx: int, cy: int, size: int
    ) -> tuple[int, int]:
        x0, x1 = cx * size, (cx + 1) * size - 1
        y0, y1 = cy * size, (cy + 1) * size - 1
        mines = int(
            s.execute(
                select(func.count(Building.id)).where(
                    Building.owner_player_id == BANDIT_PLAYER_ID,
                    Building.building_type == "mine_t1",
                    Building.x >= x0,
                    Building.x <= x1,
                    Building.y >= y0,
                    Building.y <= y1,
                    Building.z == 0,
                )
            ).scalar()
            or 0
        )
        ops = int(
            s.execute(
                select(func.count(Outpost.id)).where(
                    Outpost.owner_player_id == BANDIT_PLAYER_ID,
                    Outpost.z == 0,
                    Outpost.status == "active",
                    Outpost.x >= x0,
                    Outpost.x <= x1,
                    Outpost.y >= y0,
                    Outpost.y <= y1,
                )
            ).scalar()
            or 0
        )
        return mines, ops

    def _bandit_far_enough_from_outposts(
        self, s: Session, ox: int, oy: int, *, min_sep: int
    ) -> bool:
        rows = (
            s.execute(
                select(Outpost.x, Outpost.y).where(
                    Outpost.owner_player_id == BANDIT_PLAYER_ID,
                    Outpost.status == "active",
                    Outpost.z == 0,
                )
            )
            .all()
        )
        need = max(0, int(min_sep))
        for rx, ry in rows:
            if abs(int(rx) - ox) + abs(int(ry) - oy) < need:
                return False
        return True

    def _purge_dangling_bandit_fleets(self, s: Session) -> None:
        """Флоты корсаров без форпоста и без охоты: пустые строки и осиротевшие ударные.

        «Засада» из руин может стоять без `hunt_target`, пока игрок не подойдёт — её не трогаем.
        """
        rows = (
            s.execute(
                select(Fleet).where(
                    Fleet.owner_player_id == BANDIT_PLAYER_ID,
                    Fleet.patrol_outpost_id.is_(None),
                    Fleet.hunt_target_fleet_id.is_(None),
                )
            )
            .scalars()
            .all()
        )
        for fl in rows:
            nm = (getattr(fl, "name", None) or "").strip()
            strike_origin = getattr(fl, "strike_origin_outpost_id", None)
            units = int(self._fleet_total_units(s, fl))
            if units <= 0:
                self._purge_fleet_row(s, fl)
                continue
            if strike_origin is not None or nm == "Ударное звено":
                self._purge_fleet_row(s, fl)

    def _try_bandit_wilderness_tick(self, s: Session, *, tick: int) -> None:
        wc = self._warfare_economy(s)
        if tick % int(wc["bandit_spawn_every_n_ticks"]) != 0:
            return
        sz = int(wc["chunk_size"])
        npc = self._ensure_bandit_player(s)
        hum_home = s.execute(
            select(Planet.pos_x, Planet.pos_y)
            .where(
                Planet.owner_player_id.not_in(
                    (BANDIT_PLAYER_ID, CIVILIAN_NPC_PLAYER_ID)
                )
            )
            .order_by(Planet.created_at.asc())
            .limit(1)
        ).first()
        if not hum_home:
            return
        bx_, by_ = int(hum_home[0]), int(hum_home[1])
        half = int(wc["wilderness_spawn_window_manhattan_half"])
        n_loops = int(wc["wilderness_spawn_loop_attempts"])
        mine_ch = float(wc["wilderness_mine_spawn_chance"])
        outpost_ch = float(wc["wilderness_outpost_spawn_chance"])
        min_sep = int(wc["min_separation_from_bandit_outpost_manhattan"])
        cand_off: list[tuple[int, int]] = list(wc["outpost_candidate_offsets"])

        for _ in range(n_loops):
            gx = bx_ + _random.randint(-half, half)
            gy = by_ + _random.randint(-half, half)
            ck = self._chunk_key_xy(gx, gy, sz)
            mines_n, ops_n = self._bandit_mine_ops_in_chunk(s, ck[0], ck[1], sz)

            terrain = self.get_cell_terrain(x=gx, y=gy, z=0).get("terrain")

            blocked_cell = (
                self._cell_blocked_for_fleet(s, gx, gy, 0)
                or self._cell_has_planet(s, x=gx, y=gy, z=0)
            )

            if (
                not self._admin_block_bandit_mines(s)
                and mines_n < wc["max_bandit_mines_per_chunk"]
                and terrain == "asteroids"
                and not blocked_cell
                and _random.random() < mine_ch
            ):
                nm = Building(
                    owner_player_id=npc.id,
                    planet_id=None,
                    x=gx,
                    y=gy,
                    z=0,
                    building_type="mine_t1",
                    level=1,
                )
                nm.capture_progress = 0.0
                nm.capture_attacker_id = None
                s.add(nm)
                s.flush()
                self._emit_event(
                    s,
                    tick=tick,
                    type="bandit_mine_placed",
                    message=f"Корсары выставили шахту на ({gx},{gy}).",
                    payload={"pos": {"x": gx, "y": gy, "z": 0}},
                    player_id=BANDIT_PLAYER_ID,
                )

            mines_n2, ops_n2 = self._bandit_mine_ops_in_chunk(s, ck[0], ck[1], sz)
            placed = False
            total_ops_world = int(
                s.execute(
                    select(func.count(Outpost.id)).where(
                        Outpost.owner_player_id == BANDIT_PLAYER_ID,
                        Outpost.z == 0,
                        Outpost.status == "active",
                    )
                ).scalar()
                or 0
            )
            if (
                not self._admin_block_bandit_outposts(s)
                and total_ops_world < int(wc["max_bandit_outposts_world"])
                and ops_n2 < wc["max_bandit_outposts_per_chunk"]
                and _random.random() < outpost_ch
            ):
                for dx, dy in cand_off:
                    ox, oy = gx + int(dx), gy + int(dy)
                    terr2 = self.get_cell_terrain(x=ox, y=oy, z=0).get("terrain")
                    if terr2 != "empty":
                        continue
                    if self._cell_blocked_for_fleet(s, ox, oy, 0):
                        continue
                    if self._cell_has_planet(s, x=ox, y=oy, z=0):
                        continue
                    if not self._bandit_far_enough_from_outposts(
                        s, ox, oy, min_sep=min_sep
                    ):
                        continue
                    op_new = Outpost(
                        owner_player_id=npc.id,
                        planet_id=None,
                        builder_fleet_id=None,
                        x=int(ox),
                        y=int(oy),
                        z=0,
                        outpost_type="outpost_t1",
                        family="outpost",
                        level=1,
                        module_slots_total=1,
                        status="active",
                        started_at_tick=int(tick),
                        finish_tick=int(tick),
                        strike_next_tick=int(tick)
                        + _random.randint(wc["strike_min"], wc["strike_max"]),
                        patrol_respawn_at_tick=0,
                        updated_at=datetime.now(timezone.utc),
                    )
                    stub_stats = self._outpost_definition("outpost_t1")
                    cob = stub_stats.get("combat") if isinstance(stub_stats.get("combat"), dict) else {}
                    op_new.hp_current = int(cob.get("hp", 420) or 420)
                    s.add(op_new)
                    s.flush()
                    hc = self._ensure_outpost_hp_current(s, outpost=op_new)
                    op_new.hp_current = hc
                    s.flush()
                    self._spawn_bandit_patrol_for_outpost(
                        s,
                        npc=npc,
                        outpost=op_new,
                        tick=tick,
                        wc=wc,
                        for_new_outpost=True,
                    )
                    self._emit_event(
                        s,
                        tick=tick,
                        type="bandit_outpost_placed",
                        message=f"Корсары возвели форпост у ({ox},{oy}).",
                        payload={"pos": {"x": ox, "y": oy, "z": 0}},
                        player_id=BANDIT_PLAYER_ID,
                    )
                    placed = True
                    break
            if placed:
                break

        if self._admin_block_bandit_extra_fleets(s):
            return
        ops_bandit = (
            s.execute(
                select(Outpost).where(
                    Outpost.owner_player_id == BANDIT_PLAYER_ID,
                    Outpost.status == "active",
                    Outpost.z == 0,
                )
            )
            .scalars()
            .all()
        )
        strike_ready = [
            op
            for op in ops_bandit
            if int(getattr(op, "strike_next_tick", 0) or 0) <= int(tick)
        ]
        _random.shuffle(strike_ready)
        quota = min(
            len(strike_ready),
            max(1, int(wc["strike_spawn_max_global_per_pass"])),
        )
        chosen = strike_ready[:quota]
        npc_sql = tuple(NPC_FLEET_PLAYER_IDS)
        strike_human_fleets = (
            s.execute(
                select(Fleet).where(
                    Fleet.qty > 0,
                    Fleet.owner_player_id.not_in(npc_sql),
                )
            )
            .scalars()
            .all()
        )
        for op in chosen:
            best: Fleet | None = None
            best_d = 10**9
            oz = int(op.z)
            for fl in strike_human_fleets:
                if int(fl.pos_z) != oz:
                    continue
                dm = abs(int(fl.pos_x) - op.x) + abs(int(fl.pos_y) - op.y)
                if dm < best_d:
                    best_d = dm
                    best = fl
            if best is None:
                op.strike_next_tick = int(tick) + _random.randint(
                    wc["strike_min"], wc["strike_max"]
                )
                continue
            nm = self._fleet_public_name(best)
            oxs, oys = int(op.x), int(op.y)
            spx, spy = oxs, oys
            spawn_xy = self._bandit_pick_adjacent_spawn(
                s, cx=spx, cy=spy, cz=int(op.z)
            )
            if spawn_xy is None:
                op.strike_next_tick = int(tick) + _random.randint(
                    int(wc["strike_spawn_retry_sol_min"]),
                    int(wc["strike_spawn_retry_sol_max"]),
                )
                continue
            sx_, sy_ = spawn_xy
            fg = Fleet(
                owner_player_id=npc.id,
                unit_type="fighter",
                qty=0,
                pos_x=sx_,
                pos_y=sy_,
                pos_z=int(op.z),
                hunt_target_fleet_id=best.id,
                patrol_outpost_id=None,
                strike_origin_outpost_id=op.id,
                bandit_hunt_announced=False,
                energy=int(wc["strike_spawn_energy"]),
                max_energy=int(wc["strike_spawn_max_energy"]),
                name="Ударное звено",
            )
            nf = _random.randint(
                int(wc["strike_fighter_min"]), int(wc["strike_fighter_max"])
            )
            nc = _random.randint(
                int(wc["strike_corvette_min"]), int(wc["strike_corvette_max"])
            )
            s.add(fg)
            s.flush()
            n_scout = int(wc["strike_scout_count"])
            units_map: dict[str, int] = {}
            if n_scout > 0:
                units_map["scout"] = n_scout
            units_map["fighter"] = nf
            units_map["corvette"] = nc
            self._write_fleet_units(s, fg, units_map)
            self._sync_fleet_energy_scale(s, fg)
            op.strike_next_tick = int(tick) + _random.randint(
                wc["strike_min"], wc["strike_max"]
            )
            self._emit_event(
                s,
                tick=tick,
                type="bandit_strike_spawned",
                message=(
                    f"! Корсарский форпост выпустил ударное звено (база {oxs},{oys}). "
                    f"Цель: ближайший ваш флот «{nm}»."
                ),
                payload={
                    "kind": "strike_wing",
                    "outpost_id": str(op.id),
                    "outpost_pos": {"x": oxs, "y": oys, "z": int(op.z)},
                    "target_fleet_id": str(best.id),
                    "target_fleet_display_name": nm,
                    "fleet_id": str(fg.id),
                },
                player_id=best.owner_player_id,
            )
            s.flush()

    def _attacker_neighbor_for_fleet_vs_fleet(
        self, s: Session, *, cell_x: int, cell_y: int, cell_z: int
    ) -> tuple[int, int]:
        """Соседняя проходимая клетка — для броска бафа атакующего «из снаряжения» (не в той же клетке что цель)."""
        bx, by, bz = int(cell_x), int(cell_y), int(cell_z)
        for ox, oy in (
            (-1, 0),
            (1, 0),
            (0, -1),
            (0, 1),
            (-1, -1),
            (-1, 1),
            (1, -1),
            (1, 1),
        ):
            ax, ay = bx + ox, by + oy
            if ax == bx and ay == by:
                continue
            if not self._cell_blocked_for_fleet(s, ax, ay, bz):
                return ax, ay
        return bx, by

    def _apply_bandit_raider_move_tick(self, s: Session, *, tick: int) -> None:
        rows = (
            s.execute(
                select(Fleet).where(
                    Fleet.owner_player_id == BANDIT_PLAYER_ID,
                    Fleet.hunt_target_fleet_id.is_not(None),
                    Fleet.patrol_outpost_id.is_(None),
                )
            )
            .scalars()
            .all()
        )
        for fl in rows:
            tid = fl.hunt_target_fleet_id
            if tid is None:
                continue
            tgt = s.get(Fleet, tid)
            um = self._fleet_units_map(s, fl)
            if (
                tgt is None
                or tgt.owner_player_id in NPC_FLEET_PLAYER_IDS
                or int(self._fleet_total_units(s, tgt)) <= 0
                or not um
            ):
                fl.hunt_target_fleet_id = None
                continue
            fx, fy, fz = int(fl.pos_x), int(fl.pos_y), int(fl.pos_z)
            tx, ty, tz = int(tgt.pos_x), int(tgt.pos_y), int(tgt.pos_z)
            if fz != tz:
                fl.hunt_target_fleet_id = None
                continue

            def _engage() -> None:
                afx, afy = self._attacker_neighbor_for_fleet_vs_fleet(
                    s, cell_x=fx, cell_y=fy, cell_z=fz
                )
                fl.hunt_target_fleet_id = None
                cur_h = s.get(Fleet, fl.id)
                cur_t = s.get(Fleet, tid)
                if cur_h is None or cur_t is None:
                    return
                if cur_h.owner_player_id != BANDIT_PLAYER_ID:
                    return
                if int(self._fleet_total_units(s, cur_h)) <= 0:
                    return
                if int(self._fleet_total_units(s, cur_t)) <= 0:
                    return
                self._resolve_fleet_vs_fleet_combat(
                    s,
                    attacker=cur_h,
                    defender=cur_t,
                    attacker_from_x=afx,
                    attacker_from_y=afy,
                    battle_tick=tick,
                    event_player_id=cur_h.owner_player_id,
                )
                s.flush()

            if fx == tx and fy == ty:
                _engage()
                continue

            cand: list[tuple[int, int]] = []
            if abs(tx - fx) >= abs(ty - fy):
                cand.append((fx + (1 if tx > fx else (-1 if tx < fx else 0)), fy))
            else:
                cand.append((fx, fy + (1 if ty > fy else (-1 if ty < fy else 0))))
            if cand[0][0] == fx and cand[0][1] == fy:
                continue
            order = cand
            nx, ny = order[0]
            if nx == fx and ny == fy:
                continue
            if self._cell_blocked_for_fleet(
                s, nx, ny, fz, enter_to_attack_fleet_id=tid
            ):
                for alt in ((fx + 1, fy), (fx - 1, fy), (fx, fy + 1), (fx, fy - 1)):
                    if alt == (nx, ny):
                        continue
                    if not self._cell_blocked_for_fleet(
                        s, alt[0], alt[1], fz, enter_to_attack_fleet_id=tid
                    ):
                        nx, ny = alt
                        break
            if self._cell_blocked_for_fleet(
                s, nx, ny, fz, enter_to_attack_fleet_id=tid
            ):
                continue
            fl.pos_x, fl.pos_y = nx, ny
            fx, fy = int(fl.pos_x), int(fl.pos_y)
            tgt_live = s.get(Fleet, tid)
            if (
                tgt_live is not None
                and int(self._fleet_total_units(s, tgt_live)) > 0
                and not bool(getattr(fl, "bandit_hunt_announced", False))
            ):
                so = getattr(fl, "strike_origin_outpost_id", None)
                sop = s.get(Outpost, so) if so is not None else None
                op_x = int(sop.x) if sop is not None else int(tx)
                op_y = int(sop.y) if sop is not None else int(ty)
                t_nm = self._fleet_public_name(tgt_live)
                fl.bandit_hunt_announced = True
                self._emit_event(
                    s,
                    tick=tick,
                    type="bandit_strike_chasing",
                    message=(
                        f"! Ударное звено корсаров преследует ваш флот «{t_nm}». "
                        f"Источник: форпост ({op_x},{op_y})."
                    ),
                    payload={
                        "kind": "strike_wing",
                        "hunter_fleet_id": str(fl.id),
                        "target_fleet_id": str(tgt_live.id),
                        "origin_outpost_pos": {
                            "x": op_x,
                            "y": op_y,
                            "z": int(sop.z) if sop is not None else int(fl.pos_z),
                        },
                        "origin_outpost_id": str(so) if so else None,
                    },
                    player_id=tgt_live.owner_player_id,
                )
            if fx == tx and fy == ty:
                _engage()
                continue

            s.flush()

    def admin_dev_purge_bandit_world(self, s: Session) -> dict:
        """Тест/админ: удалить все корсарские форпосты (с патрулями), полевые шахты и флоты корсаров."""
        ws = self.get_or_create_world_state(s)
        tick = int(ws.current_tick)
        removed_o = 0
        removed_b = 0
        removed_f = 0
        ops = (
            s.execute(
                select(Outpost).where(Outpost.owner_player_id == BANDIT_PLAYER_ID)
            )
            .scalars()
            .all()
        )
        for op in list(ops):
            self._destroy_outpost_row(s, outpost=op, tick=tick)
            removed_o += 1
        for b in (
            s.execute(
                select(Building).where(Building.owner_player_id == BANDIT_PLAYER_ID)
            )
            .scalars()
            .all()
        ):
            s.delete(b)
            removed_b += 1
        for fl in (
            s.execute(
                select(Fleet).where(Fleet.owner_player_id == BANDIT_PLAYER_ID)
            )
            .scalars()
            .all()
        ):
            self._purge_fleet_row(s, fl)
            removed_f += 1
        s.flush()
        return {
            "ok": True,
            "removed": {
                "bandit_outposts": removed_o,
                "bandit_buildings": removed_b,
                "bandit_fleets": removed_f,
            },
        }
