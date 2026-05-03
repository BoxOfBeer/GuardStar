"""Снимок империи по UUID или подстроке display_name (.env DATABASE_URL).

Пример:
  PYTHONPATH=. python scripts/inspect_player_snap.py --list
  PYTHONPATH=. python scripts/inspect_player_snap.py <uuid>
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip()
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        os.environ.setdefault(k, v)


def main() -> int:
    needle = " ".join(sys.argv[1:]).strip() or "молот"
    list_mode = needle == "--list"
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        print("NO_DB")
        return 1
    url = re.sub(r"^postgresql\+psycopg\b", "postgresql+psycopg2", url)
    try:
        eng = create_engine(url, future=True)
    except Exception as e:
        print("ENGINE_FAIL", type(e).__name__, e)
        return 2

    from app.db.models.fleet import Fleet
    from app.db.models.fleet_ship import FleetShip
    from app.db.models.outpost import Outpost
    from app.db.models.planet import Planet
    from app.db.models.player import Player
    from app.db.models.player_tech import PlayerTech
    from app.db.models.resource import Resource
    from app.db.models.world_state import WorldState

    with Session(eng) as s:
        if list_mode:
            allp = s.execute(select(Player).order_by(Player.display_name)).scalars().all()
            print("PLAYERS", len(allp))
            for p in allp[:200]:
                print(" ", p.id, p.display_name)
            return 0
        pl = None
        if len(needle) == 36 and needle.count("-") == 4:
            import uuid

            try:
                uid = uuid.UUID(needle)
                pl = s.get(Player, uid)
            except ValueError:
                pl = None
        if pl is None:
            rows = (
                s.execute(select(Player).where(Player.display_name.ilike(f"%{needle}%")))
                .scalars()
                .all()
            )
            pl = rows[0] if rows else None
        if pl is None:
            print("PLAYER_NOT_FOUND", repr(needle))
            return 0
        pid = pl.id
        ws = s.execute(select(WorldState).limit(1)).scalar_one_or_none()
        tick = int(ws.current_tick) if ws else None
        planets = s.execute(select(Planet).where(Planet.owner_player_id == pid)).scalars().all()
        outposts = s.execute(select(Outpost).where(Outpost.owner_player_id == pid)).scalars().all()
        fleets = s.execute(select(Fleet).where(Fleet.owner_player_id == pid)).scalars().all()
        techs = s.execute(select(PlayerTech).where(PlayerTech.player_id == pid)).scalars().all()

        tot = {"metal": 0, "crystal": 0, "energy": 0, "fuel": 0, "food": 0, "water": 0}
        for p in planets:
            r = s.execute(select(Resource).where(Resource.planet_id == p.id)).scalar_one_or_none()
            if not r:
                continue
            for k in tot:
                tot[k] += int(getattr(r, k, 0) or 0)

        fleet_info: list[dict] = []
        ship_tot: dict[str, int] = {}
        for f in fleets:
            ships = s.execute(select(FleetShip).where(FleetShip.fleet_id == f.id)).scalars().all()
            um: dict[str, int] = {}
            for sh in ships:
                um[sh.unit_type] = um.get(sh.unit_type, 0) + int(sh.qty or 0)
            for k, v in um.items():
                ship_tot[k] = ship_tot.get(k, 0) + v
            fleet_info.append(
                {
                    "id": str(f.id)[:8],
                    "name": f.name,
                    "pos": (f.pos_x, f.pos_y, f.pos_z),
                    "ships": um,
                    "qty_legacy": f.qty,
                }
            )

        print("PLAYER", pl.display_name, str(pl.id))
        print("TICK", tick)
        print("RP", float(pl.research_points or 0))
        print("PLANETS", len(planets), [(p.name, int(p.population or 0), p.pos_x, p.pos_y) for p in planets])
        print("EMPIRE_STOCK", tot)
        print("OUTPOSTS", len(outposts))
        for o in outposts:
            print(" ", o.outpost_type, "status", getattr(o, "status", None), "cell", o.x, o.y, o.z)
        print("FLEETS", len(fleets), "ship_agg", ship_tot)
        for fi in fleet_info:
            print(" ", fi)
        done = [t.tech_id for t in techs if getattr(t, "status", None) == "done"]
        prog = [(t.tech_id, t.status, t.finish_tick) for t in techs if getattr(t, "status", None) != "done"]
        print("TECH_DONE_COUNT", len(done))
        print("TECH_ACTIVE", prog[:12])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
