"""Осада полевых построек, урон форпосту флотом, территория корсаров."""

from __future__ import annotations

import random as _random
import uuid

from app.hex_coords import hex_axial_neighbors, hex_distance
from app.services.balance_service import BalanceError
from app.services.world_service._deps import *  # noqa: F403
from app.services.world_service.constants import (
    BANDIT_PLAYER_ID,
    CIVILIAN_NPC_PLAYER_ID,
    NPC_FLEET_PLAYER_IDS,
)

_BANDIT_STORE_RES = ("metal", "crystal", "food", "water", "energy", "fuel")


class WorldServiceMixin07:
    @staticmethod
    def _eco_int(d: dict, *keys: str, default: int = 0) -> int:
        for k in keys:
            if k in d and d[k] is not None:
                try:
                    return int(d[k])
                except (TypeError, ValueError):
                    continue
        return int(default)

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
        ormin = self._eco_int(
            bp, "orbit_radius_hex_min", "orbit_radius_manhattan_min", default=4
        )
        ormax = self._eco_int(
            bp, "orbit_radius_hex_max", "orbit_radius_manhattan_max", default=5
        )
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
        spawn_half = max(
            0,
            self._eco_int(
                bf, "spawn_window_hex_half", "spawn_window_manhattan_half", default=40
            ),
        )
        mine_ch = float(bf.get("mine_spawn_chance", 0.5) or 0.5)
        mine_ch = max(0.0, min(1.0, mine_ch))
        outpost_ch = float(bf.get("outpost_spawn_chance", 0.28) or 0.28)
        outpost_ch = max(0.0, min(1.0, outpost_ch))
        early_sol_max = max(0, int(bf.get("early_phase_sol_max", 0) or 0))
        early_max_ops = max(0, int(bf.get("early_max_bandit_outposts_world", 0) or 0))
        early_ospawn_mul = float(bf.get("early_outpost_spawn_chance_mult", 1.0) or 1.0)
        early_ospawn_mul = max(0.0, min(1.0, early_ospawn_mul))
        early_strike_cd_mul = float(bf.get("early_strike_cooldown_mult", 1.0) or 1.0)
        early_strike_cd_mul = max(1.0, early_strike_cd_mul)
        sep = max(
            0,
            self._eco_int(
                bf,
                "min_separation_from_bandit_outpost_hex",
                "min_separation_from_bandit_outpost_manhattan",
                default=6,
            ),
        )
        announce_extra = max(
            0,
            self._eco_int(
                bp,
                "announce_warn_extra_hex",
                "announce_warn_extra_manhattan",
                default=6,
            ),
        )
        st_fi_min = max(1, int(bm.get("strike_fighter_min", 3) or 3))
        st_fi_max = max(st_fi_min, int(bm.get("strike_fighter_max", 5) or 5))
        st_co_min = max(1, int(bm.get("strike_corvette_min", 3) or 3))
        st_co_max = max(st_co_min, int(bm.get("strike_corvette_max", 5) or 5))
        rtry_lo = max(1, int(bm.get("spawn_retry_sol_min", 8) or 8))
        rtry_hi = max(rtry_lo, int(bm.get("spawn_retry_sol_max", 20) or 20))
        st_scout = max(0, int(bm.get("strike_scout_count", 1) or 1))
        strike_over = float(bm.get("strike_target_overmatch", 1.35) or 1.35)
        strike_over = max(1.02, strike_over)
        strike_co_cap_none = max(0, int(bm.get("strike_corvette_cap_if_target_has_none", 1) or 1))
        strike_min_f = max(1, int(bm.get("strike_min_fighter_after_clamp", 1) or 1))
        patrol_over = float(bp.get("patrol_target_overmatch", 1.45) or 1.45)
        patrol_over = max(1.02, patrol_over)
        patrol_min_f = max(1, int(bp.get("patrol_min_fighter_after_clamp", 2) or 2))
        patrol_e = max(1, int(bp.get("spawn_energy", 200) or 200))
        patrol_me = max(patrol_e, int(bp.get("spawn_max_energy", 240) or 240))
        strike_e = max(1, int(bm.get("spawn_energy", 220) or 220))
        strike_me = max(strike_e, int(bm.get("spawn_max_energy", 260) or 260))
        strike_jit_lo = float(bm.get("strike_threat_jitter_min", 0.78) or 0.78)
        strike_jit_hi = float(bm.get("strike_threat_jitter_max", 1.06) or 1.06)
        if strike_jit_hi < strike_jit_lo:
            strike_jit_lo, strike_jit_hi = strike_jit_hi, strike_jit_lo
        pat_jit_lo = float(bp.get("patrol_ref_jitter_min", 0.84) or 0.84)
        pat_jit_hi = float(bp.get("patrol_ref_jitter_max", 1.14) or 1.14)
        if pat_jit_hi < pat_jit_lo:
            pat_jit_lo, pat_jit_hi = pat_jit_hi, pat_jit_lo
        cand: list[tuple[int, int]] = []
        offs_raw = bf.get("outpost_candidate_offsets")
        if isinstance(offs_raw, list):
            for it in offs_raw:
                if isinstance(it, (list, tuple)) and len(it) >= 2:
                    cand.append((int(it[0]), int(it[1])))
        if not cand:
            cand = [(2, 0), (-2, 0), (0, 2), (0, -2)]

        bl = eco.get("bandit_outpost_logistics")
        bl = bl if isinstance(bl, dict) else {}
        b_supply_r = max(5, min(80, self._eco_int(bl, "supply_radius_hex", default=25)))
        _bcap_def = {
            "metal": 6000,
            "crystal": 4000,
            "food": 8000,
            "water": 8000,
            "energy": 4000,
            "fuel": 2000,
        }
        _bper_def = {
            "metal": 2,
            "crystal": 1,
            "food": 4,
            "water": 4,
            "energy": 2,
            "fuel": 0,
        }
        _bin_def = {
            "metal": 200,
            "crystal": 120,
            "food": 300,
            "water": 300,
            "energy": 80,
            "fuel": 40,
        }
        bandit_logistics: dict[str, int | float] = {
            "bandit_supply_radius_hex": float(b_supply_r),
        }
        for _rk in _BANDIT_STORE_RES:
            bandit_logistics[f"bandit_store_{_rk}_per_sol"] = max(
                0,
                int(bl.get(f"store_{_rk}_per_sol", _bper_def[_rk]) or 0),
            )
            bandit_logistics[f"bandit_store_cap_{_rk}"] = max(
                0,
                int(bl.get(f"store_cap_{_rk}", _bcap_def[_rk]) or 0),
            )
            bandit_logistics[f"bandit_store_initial_{_rk}"] = max(
                0,
                int(bl.get(f"initial_{_rk}", _bin_def[_rk]) or 0),
            )

        return {
            "field_progress_per_sol": float(fb.get("progress_per_sol", 0.25) or 0.25),
            "field_resistance": float(fb.get("resistance_default", 5.0) or 5.0),
            "field_event_every_n_ticks": int(fb.get("event_every_n_ticks", 5) or 5),
            "bombard_range": self._eco_int(
                bs, "fleet_range_hex", "fleet_range_manhattan", default=3
            ),
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
            "patrol_aggro_radius": max(
                ormax,
                self._eco_int(
                    bp, "aggro_radius_hex", "aggro_radius_manhattan", default=5
                ),
            ),
            "patrol_respawn_sol_min": rsp_min,
            "patrol_respawn_sol_max": rsp_max,
            "wilderness_spawn_loop_attempts": spawn_loop,
            "wilderness_spawn_window_hex_half": spawn_half,
            "wilderness_mine_spawn_chance": mine_ch,
            "wilderness_outpost_spawn_chance": outpost_ch,
            "early_phase_sol_max": early_sol_max,
            "early_max_bandit_outposts_world": early_max_ops,
            "early_outpost_spawn_chance_mult": early_ospawn_mul,
            "early_strike_cooldown_mult": early_strike_cd_mul,
            "min_separation_from_bandit_outpost_hex": sep,
            "patrol_announce_warn_extra_hex": announce_extra,
            "strike_fighter_min": st_fi_min,
            "strike_fighter_max": st_fi_max,
            "strike_corvette_min": st_co_min,
            "strike_corvette_max": st_co_max,
            "strike_spawn_retry_sol_min": rtry_lo,
            "strike_spawn_retry_sol_max": rtry_hi,
            "strike_scout_count": st_scout,
            "strike_target_overmatch": strike_over,
            "strike_corvette_cap_if_target_has_none": strike_co_cap_none,
            "strike_min_fighter_after_clamp": strike_min_f,
            "strike_threat_jitter_min": strike_jit_lo,
            "strike_threat_jitter_max": strike_jit_hi,
            "patrol_target_overmatch": patrol_over,
            "patrol_min_fighter_after_clamp": patrol_min_f,
            "patrol_ref_jitter_min": pat_jit_lo,
            "patrol_ref_jitter_max": pat_jit_hi,
            "patrol_spawn_energy": patrol_e,
            "patrol_spawn_max_energy": patrol_me,
            "strike_spawn_energy": strike_e,
            "strike_spawn_max_energy": strike_me,
            "outpost_candidate_offsets": cand,
            **bandit_logistics,
        }

    def _bandit_units_spawn_cost_total(self, units_map: dict[str, int] | None) -> dict[str, int]:
        acc = {k: 0 for k in _BANDIT_STORE_RES}
        if not units_map:
            return acc
        for u, q in units_map.items():
            qi = max(0, int(q))
            if qi <= 0:
                continue
            parts = self._unit_build_cost_parts(str(u))
            for k in _BANDIT_STORE_RES:
                acc[k] += int(parts.get(k, 0) or 0) * qi
        return acc

    def _bandit_outpost_try_spend_store(self, op: Outpost, cost: dict[str, int]) -> bool:
        for k in _BANDIT_STORE_RES:
            need = max(0, int(cost.get(k, 0) or 0))
            if need <= 0:
                continue
            cur = int(getattr(op, f"bandit_store_{k}", 0) or 0)
            if cur < need:
                return False
        for k in _BANDIT_STORE_RES:
            need = max(0, int(cost.get(k, 0) or 0))
            if need <= 0:
                continue
            cur = int(getattr(op, f"bandit_store_{k}", 0) or 0)
            setattr(op, f"bandit_store_{k}", cur - need)
        return True

    def _bandit_seed_outpost_initial_store(
        self, s: Session, op: Outpost, wc: dict
    ) -> None:
        for k in _BANDIT_STORE_RES:
            v = max(0, int(wc.get(f"bandit_store_initial_{k}", 0) or 0))
            setattr(op, f"bandit_store_{k}", v)
        s.flush()

    def _apply_bandit_outpost_store_tick(self, s: Session, *, tick: int) -> None:
        del tick  # сол = тик; сигнатура единообразна с другими тиками
        wc = self._warfare_economy(s)
        ops = (
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
        for op in ops:
            for k in _BANDIT_STORE_RES:
                prod = max(0, int(wc.get(f"bandit_store_{k}_per_sol", 0) or 0))
                if prod <= 0:
                    continue
                capv = max(0, int(wc.get(f"bandit_store_cap_{k}", 0) or 0))
                cur = int(getattr(op, f"bandit_store_{k}", 0) or 0)
                nxt = cur + prod
                if capv > 0:
                    nxt = min(capv, nxt)
                setattr(op, f"bandit_store_{k}", nxt)
        s.flush()

    def _bandit_fleet_home_outpost(self, s: Session, fl: Fleet) -> Outpost | None:
        pid = getattr(fl, "patrol_outpost_id", None)
        if pid is not None:
            op = s.get(Outpost, pid)
            if (
                op is not None
                and op.status == "active"
                and str(op.owner_player_id) == str(BANDIT_PLAYER_ID)
            ):
                return op
        sid = getattr(fl, "strike_origin_outpost_id", None)
        if sid is not None:
            op2 = s.get(Outpost, sid)
            if (
                op2 is not None
                and op2.status == "active"
                and str(op2.owner_player_id) == str(BANDIT_PLAYER_ID)
            ):
                return op2
        return None

    def _bandit_fleet_in_logistics_supply(self, s: Session, fl: Fleet, wc: dict) -> bool:
        op = self._bandit_fleet_home_outpost(s, fl)
        if op is None:
            return False
        sr = max(5, int(float(wc.get("bandit_supply_radius_hex", 25) or 25)))
        return (
            hex_distance(
                int(fl.pos_x), int(fl.pos_y), int(op.x), int(op.y)
            )
            <= sr
        )

    def _unit_bandit_threat_weight(self, unit_key: str) -> float:
        """Грубая «мощность» юнита для сравнения составов корсаров и игрока (без модификаторов расы/техов)."""
        k = str(unit_key or "").strip().lower()
        if not k:
            return 0.0
        try:
            u = self._balance.get_unit(k)
        except BalanceError:
            return 0.0
        role = str(u.get("role") or "")
        hp = float(u.get("hp") or 0)
        dmg = float(u.get("damage") or 0)
        raw = hp + 2.0 * dmg
        if role == "combat":
            return max(1.0, raw)
        if role == "scout":
            return max(0.0, 0.45 * raw)
        if role == "engineering":
            return max(0.0, 0.35 * hp)
        return 0.0

    def _bandit_threat_from_unit_counts(self, counts: dict[str, int] | None) -> float:
        if not counts:
            return 0.0
        t = 0.0
        for uk, q in counts.items():
            qi = max(0, int(q))
            if qi <= 0:
                continue
            t += qi * self._unit_bandit_threat_weight(str(uk))
        return float(t)

    def _fleet_bandit_threat_estimate(self, s: Session, fl: Fleet | None) -> float:
        if fl is None:
            return 0.0
        return self._bandit_threat_from_unit_counts(self._fleet_units_map(s, fl))

    def _clamp_bandit_strike_vs_target(
        self,
        s: Session,
        wc: dict,
        target: Fleet,
        nf: int,
        nc: int,
        n_scout: int,
    ) -> tuple[int, int, int]:
        """Сужает ударное звено под целевой флот (ближайший к форпосту)."""
        um_tgt = self._fleet_units_map(s, target)
        t_thr = max(0.0, self._bandit_threat_from_unit_counts(um_tgt))
        mult = max(1.02, float(wc.get("strike_target_overmatch", 1.35) or 1.35))
        w_fi = self._unit_bandit_threat_weight("fighter")
        min_f = max(1, int(wc.get("strike_min_fighter_after_clamp", 1) or 1))
        max_th = max(t_thr * mult, min_f * w_fi * 1.05)
        j_lo = float(wc.get("strike_threat_jitter_min", 1.0) or 1.0)
        j_hi = float(wc.get("strike_threat_jitter_max", 1.0) or 1.0)
        if j_hi < j_lo:
            j_lo, j_hi = j_hi, j_lo
        max_th *= _random.uniform(j_lo, j_hi)
        if int(um_tgt.get("corvette", 0) or 0) <= 0:
            nc = min(int(nc), int(wc.get("strike_corvette_cap_if_target_has_none", 1) or 1))
        nf, nc = max(0, int(nf)), max(0, int(nc))
        n_scout = max(0, int(n_scout))
        units_map: dict[str, int] = {}
        if n_scout > 0:
            units_map["scout"] = n_scout
        units_map["fighter"] = int(nf)
        units_map["corvette"] = int(nc)

        def _thr() -> float:
            return self._bandit_threat_from_unit_counts(units_map)

        while _thr() > max_th:
            if units_map.get("corvette", 0) > 0:
                units_map["corvette"] -= 1
            elif units_map.get("fighter", 0) > min_f:
                units_map["fighter"] -= 1
            elif units_map.get("scout", 0) > 0:
                units_map["scout"] -= 1
            else:
                break
        if _thr() < 1.0:
            units_map = {"fighter": min_f}
            if n_scout > 0:
                units_map["scout"] = 1
            while _thr() > max_th and units_map.get("scout", 0) > 0:
                units_map["scout"] -= 1
        return (
            max(min_f, int(units_map.get("fighter", min_f))),
            max(0, int(units_map.get("corvette", 0))),
            max(0, int(units_map.get("scout", 0))),
        )

    def _bandit_in_early_phase(self, wc: dict, tick: int) -> bool:
        lim = int(wc.get("early_phase_sol_max", 0) or 0)
        return lim > 0 and int(tick) < lim

    def _bandit_scheduled_tick_after(
        self, wc: dict, now_tick: int, lo_key: str, hi_key: str
    ) -> int:
        span = _random.randint(int(wc[lo_key]), int(wc[hi_key]))
        if self._bandit_in_early_phase(wc, int(now_tick)):
            span = int(
                span * max(1.0, float(wc.get("early_strike_cooldown_mult", 1.0) or 1.0))
            )
        return int(now_tick) + max(1, span)

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
        return hex_distance(int(ax), int(ay), int(bx), int(by))

    def _bandit_pick_adjacent_spawn(
        self, s: Session, *, cx: int, cy: int, cz: int
    ) -> tuple[int, int] | None:
        neigh = list(hex_axial_neighbors(int(cx), int(cy)))
        _random.shuffle(neigh)
        for tx_, ty_ in neigh:
            if not self._cell_blocked_for_fleet(s, tx_, ty_, int(cz)):
                return int(tx_), int(ty_)
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
        ox, oy = int(outpost.x), int(outpost.y)
        oz = int(outpost.z)
        agro = int(wc["patrol_aggro_radius"])
        sr_cap = max(5, int(float(wc.get("bandit_supply_radius_hex", 25) or 25)))
        agro_eff = min(agro, sr_cap)
        warn_r = agro + int(wc["patrol_announce_warn_extra_hex"])
        npc_sql = tuple(NPC_FLEET_PLAYER_IDS)
        fl_batch = (
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
        )
        T_near = 0.0
        for fln in fl_batch:
            if int(self._fleet_total_units(s, fln)) <= 0:
                continue
            if self._manhattan(ox, oy, int(fln.pos_x), int(fln.pos_y)) <= warn_r:
                T_near = max(T_near, self._fleet_bandit_threat_estimate(s, fln))
        nf = _random.randint(
            int(wc["patrol_fighter_min"]), int(wc["patrol_fighter_max"])
        )
        w_fi = self._unit_bandit_threat_weight("fighter")
        if T_near > 0.0 and w_fi > 1e-6:
            mult = max(1.02, float(wc.get("patrol_target_overmatch", 1.45) or 1.45))
            pmin = max(1, int(wc.get("patrol_min_fighter_after_clamp", 2) or 2))
            ref = max(T_near * mult, pmin * w_fi * 1.05)
            pj_lo = float(wc.get("patrol_ref_jitter_min", 1.0) or 1.0)
            pj_hi = float(wc.get("patrol_ref_jitter_max", 1.0) or 1.0)
            if pj_hi < pj_lo:
                pj_lo, pj_hi = pj_hi, pj_lo
            ref *= _random.uniform(pj_lo, pj_hi)
            while nf * w_fi > ref and nf > pmin:
                nf -= 1
        spawn_cost = self._bandit_units_spawn_cost_total({"fighter": int(nf)})
        if not self._bandit_outpost_try_spend_store(outpost, spawn_cost):
            outpost.patrol_respawn_at_tick = int(tick) + _random.randint(4, 14)
            s.flush()
            return
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
        near: set[uuid.UUID] = set()
        for fln in fl_batch:
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
                    f"зона агро ~{agro_eff} кл. от базы."
                ),
                payload={
                    "kind": "patrol",
                    "outpost_id": str(outpost.id),
                    "fleet_id": str(fg.id),
                    "outpost_pos": {"x": ox, "y": oy, "z": int(outpost.z)},
                    "aggro_radius": agro_eff,
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
            sr_cap = max(5, int(float(wc.get("bandit_supply_radius_hex", 25) or 25)))
            agro_eff = min(agro, sr_cap)

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
                if d_hub > agro_eff:
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
                step_opts: list[tuple[int, int, int]] = []
                for tcx, tcy in hex_axial_neighbors(fx, fy):
                    if self._cell_blocked_for_fleet(
                        s, tcx, tcy, fz, enter_to_attack_fleet_id=prey.id
                    ):
                        continue
                    if self._manhattan(tcx, tcy, ox, oy) > r_cap:
                        continue
                    step_opts.append(
                        (self._manhattan(tcx, tcy, tx, ty), int(tcx), int(tcy))
                    )
                step_opts.sort(key=lambda t: t[0])
                nx, ny = fx, fy
                if step_opts:
                    nx, ny = step_opts[0][1], step_opts[0][2]
                if (nx, ny) != (fx, fy):
                    fl.pos_x, fl.pos_y = nx, ny
                    fx, fy = nx, ny
                if prey and fx == int(prey.pos_x) and fy == int(prey.pos_y):
                    _patrol_engages_player(hunter=fl, victim=prey)
                s.flush()
                continue

            neigh = list(hex_axial_neighbors(fx, fy))
            _random.shuffle(neigh)
            nx, ny = fx, fy
            for tcx, tcy in neigh:
                if self._cell_blocked_for_fleet(s, tcx, tcy, fz):
                    continue
                if self._manhattan(tcx, tcy, ox, oy) <= r_cap:
                    nx, ny = int(tcx), int(tcy)
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
                if self._manhattan(int(occ.pos_x), int(occ.pos_y), ox, oy) > agro_eff:
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
                dman = hex_distance(int(f.pos_x), int(f.pos_y), ox, oy)
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
            if hex_distance(int(rx), int(ry), ox, oy) < need:
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
            if strike_origin is not None:
                sop = s.get(Outpost, strike_origin)
                if sop is not None and sop.status == "active":
                    continue
                self._purge_fleet_row(s, fl)
                continue
            if nm == "Ударное звено":
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
        half = int(wc["wilderness_spawn_window_hex_half"])
        n_loops = int(wc["wilderness_spawn_loop_attempts"])
        mine_ch = float(wc["wilderness_mine_spawn_chance"])
        outpost_ch = float(wc["wilderness_outpost_spawn_chance"])
        if self._bandit_in_early_phase(wc, int(tick)):
            outpost_ch *= float(wc.get("early_outpost_spawn_chance_mult", 1.0) or 1.0)
            outpost_ch = max(0.0, min(1.0, outpost_ch))
        min_sep = int(wc["min_separation_from_bandit_outpost_hex"])
        cand_off: list[tuple[int, int]] = list(wc["outpost_candidate_offsets"])
        max_world_ops = int(wc["max_bandit_outposts_world"])
        e_cap = int(wc.get("early_max_bandit_outposts_world", 0) or 0)
        if self._bandit_in_early_phase(wc, int(tick)) and e_cap > 0:
            max_world_ops = min(max_world_ops, e_cap)

        for _ in range(n_loops):
            gx = bx_ + _random.randint(-half, half)
            gy = by_ + _random.randint(-half, half)
            ck = self._chunk_key_xy(gx, gy, sz)
            mines_n, ops_n = self._bandit_mine_ops_in_chunk(s, ck[0], ck[1], sz)

            terrain = self.get_cell_terrain(x=gx, y=gy, z=0, s=s).get("terrain")

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
                and total_ops_world < max_world_ops
                and ops_n2 < wc["max_bandit_outposts_per_chunk"]
                and _random.random() < outpost_ch
            ):
                for dx, dy in cand_off:
                    ox, oy = gx + int(dx), gy + int(dy)
                    terr2 = self.get_cell_terrain(x=ox, y=oy, z=0, s=s).get("terrain")
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
                        strike_next_tick=self._bandit_scheduled_tick_after(
                            wc, int(tick), "strike_min", "strike_max"
                        ),
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
                    self._bandit_seed_outpost_initial_store(s, op_new, wc)
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
                dm = hex_distance(int(fl.pos_x), int(fl.pos_y), int(op.x), int(op.y))
                if dm < best_d:
                    best_d = dm
                    best = fl
            if best is None:
                op.strike_next_tick = self._bandit_scheduled_tick_after(
                    wc, int(tick), "strike_min", "strike_max"
                )
                continue
            nm = self._fleet_public_name(best)
            oxs, oys = int(op.x), int(op.y)
            spx, spy = oxs, oys
            spawn_xy = self._bandit_pick_adjacent_spawn(
                s, cx=spx, cy=spy, cz=int(op.z)
            )
            if spawn_xy is None:
                op.strike_next_tick = self._bandit_scheduled_tick_after(
                    wc,
                    int(tick),
                    "strike_spawn_retry_sol_min",
                    "strike_spawn_retry_sol_max",
                )
                continue
            sx_, sy_ = spawn_xy
            nf = _random.randint(
                int(wc["strike_fighter_min"]), int(wc["strike_fighter_max"])
            )
            nc = _random.randint(
                int(wc["strike_corvette_min"]), int(wc["strike_corvette_max"])
            )
            n_scout = int(wc["strike_scout_count"])
            nf, nc, n_scout = self._clamp_bandit_strike_vs_target(s, wc, best, nf, nc, n_scout)
            units_map_pre: dict[str, int] = {}
            if n_scout > 0:
                units_map_pre["scout"] = n_scout
            units_map_pre["fighter"] = nf
            units_map_pre["corvette"] = nc
            strike_cost = self._bandit_units_spawn_cost_total(units_map_pre)
            if not self._bandit_outpost_try_spend_store(op, strike_cost):
                op.strike_next_tick = self._bandit_scheduled_tick_after(
                    wc,
                    int(tick),
                    "strike_spawn_retry_sol_min",
                    "strike_spawn_retry_sol_max",
                )
                s.flush()
                continue
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
            s.add(fg)
            s.flush()
            self._write_fleet_units(s, fg, units_map_pre)
            self._sync_fleet_energy_scale(s, fg)
            op.strike_next_tick = self._bandit_scheduled_tick_after(
                wc, int(tick), "strike_min", "strike_max"
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
        neigh = list(hex_axial_neighbors(bx, by))
        _random.shuffle(neigh)
        for ax, ay in neigh:
            if not self._cell_blocked_for_fleet(s, ax, ay, bz):
                return int(ax), int(ay)
        return bx, by

    def _apply_bandit_raider_move_tick(self, s: Session, *, tick: int) -> None:
        wc = self._warfare_economy(s)
        sr = max(5, int(float(wc.get("bandit_supply_radius_hex", 25) or 25)))
        rows = (
            s.execute(
                select(Fleet).where(
                    Fleet.owner_player_id == BANDIT_PLAYER_ID,
                    Fleet.patrol_outpost_id.is_(None),
                    or_(
                        Fleet.hunt_target_fleet_id.is_not(None),
                        Fleet.strike_origin_outpost_id.is_not(None),
                    ),
                )
            )
            .scalars()
            .all()
        )
        for fl in rows:
            um = self._fleet_units_map(s, fl)
            if not um or int(self._fleet_total_units(s, fl)) <= 0:
                continue
            fx, fy, fz = int(fl.pos_x), int(fl.pos_y), int(fl.pos_z)
            so = getattr(fl, "strike_origin_outpost_id", None)
            sop = s.get(Outpost, so) if so is not None else None
            if sop is not None and (
                sop.status != "active"
                or str(sop.owner_player_id) != str(BANDIT_PLAYER_ID)
            ):
                sop = None

            tid = fl.hunt_target_fleet_id
            tgt = s.get(Fleet, tid) if tid else None

            if tgt is not None and (
                tgt.owner_player_id in NPC_FLEET_PLAYER_IDS
                or int(self._fleet_total_units(s, tgt)) <= 0
            ):
                fl.hunt_target_fleet_id = None
                tid = None
                tgt = None

            if tgt is not None:
                if int(tgt.pos_z) != fz:
                    fl.hunt_target_fleet_id = None
                    tid = None
                    tgt = None
                elif sop is not None:
                    d_home = hex_distance(fx, fy, int(sop.x), int(sop.y))
                    if d_home > sr:
                        fl.hunt_target_fleet_id = None
                        tid = None
                        tgt = None

            if (tgt is None or tid is None) and sop is not None:
                ox, oy = int(sop.x), int(sop.y)
                if hex_distance(fx, fy, ox, oy) <= 1:
                    self._purge_fleet_row(s, fl)
                    s.flush()
                    continue
                step_opts: list[tuple[int, int, int]] = []
                for tcx, tcy in hex_axial_neighbors(fx, fy):
                    if self._cell_blocked_for_fleet(s, tcx, tcy, fz):
                        continue
                    step_opts.append(
                        (hex_distance(int(tcx), int(tcy), ox, oy), int(tcx), int(tcy))
                    )
                step_opts.sort(key=lambda t: t[0])
                if step_opts:
                    fl.pos_x, fl.pos_y = step_opts[0][1], step_opts[0][2]
                s.flush()
                continue

            if tgt is None or tid is None:
                continue

            tx, ty, tz = int(tgt.pos_x), int(tgt.pos_y), int(tgt.pos_z)

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

            step_opts: list[tuple[int, int, int]] = []
            for tcx, tcy in hex_axial_neighbors(fx, fy):
                if self._cell_blocked_for_fleet(
                    s, tcx, tcy, fz, enter_to_attack_fleet_id=tid
                ):
                    continue
                step_opts.append((hex_distance(int(tcx), int(tcy), tx, ty), int(tcx), int(tcy)))
            step_opts.sort(key=lambda t: t[0])
            if not step_opts:
                continue
            nx, ny = step_opts[0][1], step_opts[0][2]
            fl.pos_x, fl.pos_y = nx, ny
            fx, fy = int(fl.pos_x), int(fl.pos_y)
            tgt_live = s.get(Fleet, tid)
            if (
                tgt_live is not None
                and int(self._fleet_total_units(s, tgt_live)) > 0
                and not bool(getattr(fl, "bandit_hunt_announced", False))
            ):
                so2 = getattr(fl, "strike_origin_outpost_id", None)
                sop2 = s.get(Outpost, so2) if so2 is not None else None
                op_x = int(sop2.x) if sop2 is not None else int(tx)
                op_y = int(sop2.y) if sop2 is not None else int(ty)
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
                            "z": int(sop2.z) if sop2 is not None else int(fl.pos_z),
                        },
                        "origin_outpost_id": str(so2) if so2 else None,
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
