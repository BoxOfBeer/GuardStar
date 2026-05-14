"""Шпионаж v0: скан чужого флота (соседняя клетка, RP, антишпионаж по техе)."""

from __future__ import annotations

import uuid

from app.hex_coords import hex_distance
from app.services.world_service._deps import *  # noqa: F403


class WorldServiceMixin09:
    def _intel_scan_config(self, s: Session | None) -> dict:
        eco = self._merged_pack_economy(s)
        b = eco.get("intel_scan") if isinstance(eco.get("intel_scan"), dict) else {}
        return {
            "rp_cost": max(0.0, float(b.get("rp_cost", 3.0) or 3.0)),
            "max_range_hex": max(0, int(b.get("max_range_hex", 1) or 1)),
            "defender_blocking_tech": str(
                b.get("defender_blocking_tech") or "tech_fleet_doctrine_1"
            ).strip(),
        }

    def intel_scan_fleet(
        self,
        s: Session,
        *,
        player_id: str,
        scanner_fleet_id: str,
        target_fleet_id: str,
    ) -> dict:
        """Скан соседнего чужого флота: состав из баланса по FleetShip. Стоимость — RP игрока."""
        try:
            pid = uuid.UUID(str(player_id))
            sid = uuid.UUID(str(scanner_fleet_id).strip())
            tid = uuid.UUID(str(target_fleet_id).strip())
        except Exception:
            return {"ok": False, "error": "invalid_payload"}

        cfg = self._intel_scan_config(s)
        ws = self.get_or_create_world_state(s)
        tick = int(ws.current_tick)

        scan_fleet = (
            s.execute(
                select(Fleet).where(Fleet.id == sid, Fleet.owner_player_id == pid)
            )
            .scalars()
            .first()
        )
        if not scan_fleet:
            return {"ok": False, "error": "fleet_not_found", "which": "scanner"}

        if self._active_order_for_fleet(s, fleet_id=sid):
            return {"ok": False, "error": "active_order_exists"}

        target = s.execute(select(Fleet).where(Fleet.id == tid)).scalars().first()
        if not target:
            return {"ok": False, "error": "fleet_not_found", "which": "target"}

        if target.owner_player_id == pid:
            return {"ok": False, "error": "cannot_scan_own_fleet"}

        if int(scan_fleet.pos_z) != int(target.pos_z):
            return {"ok": False, "error": "target_not_adjacent"}

        d = hex_distance(
            int(scan_fleet.pos_x),
            int(scan_fleet.pos_y),
            int(target.pos_x),
            int(target.pos_y),
        )
        if d > int(cfg["max_range_hex"]) or d < 0:
            return {"ok": False, "error": "target_not_adjacent"}

        pl = s.get(Player, pid)
        if not pl:
            return {"ok": False, "error": "player_not_found"}

        tgt_owner = target.owner_player_id
        done_def = set(self._get_player_done_techs(s, player_id=tgt_owner))
        block_tech = cfg["defender_blocking_tech"]
        if block_tech and block_tech in done_def:
            self._emit_event(
                s,
                tick=tick,
                type="intel_blocked",
                message="Скан заблокирован: у цели действует контрразведка (техи).",
                payload={
                    "scanner_fleet_id": str(sid),
                    "target_fleet_id": str(tid),
                    "target_player_id": str(tgt_owner),
                    "blocking_tech": block_tech,
                    "source": "intel_scan",
                },
                player_id=pid,
                ui_channel="toast",
            )
            return {"ok": False, "error": "intel_blocked", "blocking_tech": block_tech}

        cur_rp = self._player_research_points_float(pl)
        need = float(cfg["rp_cost"])
        if cur_rp + 1e-9 < need:
            return {
                "ok": False,
                "error": "not_enough_research_points",
                "need_rp": need,
                "have_rp": cur_rp,
            }

        comp = dict(self._fleet_units_map(s, target))
        pl.research_points = cur_rp - need

        scan_name = (pl.display_name or "").strip() or str(pid)[:8]
        tgt_pl = s.get(Player, tgt_owner) if tgt_owner else None
        tgt_name = (
            (tgt_pl.display_name or "").strip() if tgt_pl else str(tgt_owner)[:8]
        )

        self._emit_event(
            s,
            tick=tick,
            type="intel_scan_success",
            message=f"Скан: состав вражеского флота у ({target.pos_x},{target.pos_y}).",
            payload={
                "scanner_fleet_id": str(sid),
                "target_fleet_id": str(tid),
                "target_player_id": str(tgt_owner),
                "target_display_name": tgt_name,
                "composition": comp,
                "rp_spent": need,
                "source": "intel_scan",
            },
            player_id=pid,
            ui_channel="toast",
        )

        self._emit_event(
            s,
            tick=tick,
            type="intel_scanned",
            message=f"Вас просканировали: {scan_name} (флот у {scan_fleet.pos_x},{scan_fleet.pos_y}).",
            payload={
                "scanner_player_id": str(pid),
                "scanner_display_name": scan_name,
                "scanner_fleet_id": str(sid),
                "target_fleet_id": str(tid),
                "source": "intel_scan",
            },
            player_id=tgt_owner,
            ui_channel="toast",
        )

        return {
            "ok": True,
            "composition": comp,
            "rp_spent": need,
            "research_points_after": float(self._player_research_points_float(pl)),
            "target_fleet_id": str(tid),
            "target_display_name": tgt_name,
        }
