"""Альянсы: создание, вступление по коду, выход; карта «союзник»; превью влияния; чат канала alliance."""

from __future__ import annotations

import re
import secrets
import string
import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models.alliance import Alliance, AllianceMember
from app.db.models.influence_cell import InfluenceCell
from app.db.models.player import Player

_TAG_RE = re.compile(r"^[A-Z0-9]{2,8}$")


def _new_join_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(12))


def normalize_tag(raw: str) -> str | None:
    t = (raw or "").strip().upper().replace(" ", "")
    if not _TAG_RE.match(t):
        return None
    return t


def alliance_ids_for_players(
    s: Session, player_ids: set[uuid.UUID]
) -> dict[str, uuid.UUID | None]:
    if not player_ids:
        return {}
    rows = (
        s.execute(
            select(AllianceMember.player_id, AllianceMember.alliance_id).where(
                AllianceMember.player_id.in_(player_ids)
            )
        )
        .all()
    )
    return {str(r[0]): r[1] for r in rows}


def get_alliance_economy(balance: Any) -> dict[str, Any]:
    if not balance or not getattr(balance, "pack", None):
        return {"max_members": 24, "influence_cell_cap": 5.0}
    eco = balance.pack.economy if isinstance(balance.pack.economy, dict) else {}
    a = eco.get("alliance") if isinstance(eco.get("alliance"), dict) else {}
    return {
        "max_members": max(2, int(a.get("max_members", 24) or 24)),
        "influence_cell_cap": max(0.1, float(a.get("influence_cell_cap", 5.0) or 5.0)),
    }


def membership_for_player(s: Session, *, player_id: uuid.UUID) -> AllianceMember | None:
    return (
        s.execute(
            select(AllianceMember).where(AllianceMember.player_id == player_id)
        )
        .scalar_one_or_none()
    )


def create_alliance(
    s: Session,
    balance: Any,
    *,
    player_id: str,
    display_name: str,
    tag: str,
) -> dict:
    try:
        pid = uuid.UUID(str(player_id).strip())
    except Exception:
        return {"ok": False, "error": "invalid_player_id"}

    if membership_for_player(s, player_id=pid):
        return {"ok": False, "error": "already_in_alliance"}

    nm = (display_name or "").strip()
    if len(nm) < 2 or len(nm) > 64:
        return {"ok": False, "error": "invalid_display_name"}

    tnorm = normalize_tag(tag)
    if not tnorm:
        return {"ok": False, "error": "invalid_tag"}

    exists = s.execute(select(Alliance.id).where(Alliance.tag == tnorm)).first()
    if exists:
        return {"ok": False, "error": "tag_taken"}

    eco = get_alliance_economy(balance)
    join_code = _new_join_code()
    for _ in range(8):
        clash = s.execute(select(Alliance.id).where(Alliance.join_code == join_code)).first()
        if not clash:
            break
        join_code = _new_join_code()
    else:
        return {"ok": False, "error": "join_code_collision"}

    a = Alliance(display_name=nm[:64], tag=tnorm, join_code=join_code)
    s.add(a)
    s.flush()
    s.add(
        AllianceMember(
            alliance_id=a.id,
            player_id=pid,
            role="leader",
        )
    )
    s.flush()
    return {
        "ok": True,
        "alliance": {
            "id": str(a.id),
            "display_name": a.display_name,
            "tag": a.tag,
            "join_code": a.join_code,
        },
    }


def join_alliance_by_code(
    s: Session, balance: Any, *, player_id: str, join_code: str
) -> dict:
    try:
        pid = uuid.UUID(str(player_id).strip())
    except Exception:
        return {"ok": False, "error": "invalid_player_id"}

    if membership_for_player(s, player_id=pid):
        return {"ok": False, "error": "already_in_alliance"}

    code = (join_code or "").strip().upper()
    if len(code) < 10:
        return {"ok": False, "error": "invalid_join_code"}

    a = (
        s.execute(select(Alliance).where(Alliance.join_code == code))
        .scalar_one_or_none()
    )
    if not a:
        return {"ok": False, "error": "alliance_not_found"}

    n = int(
        s.execute(
            select(func.count(AllianceMember.id)).where(
                AllianceMember.alliance_id == a.id
            )
        ).scalar()
        or 0
    )
    eco = get_alliance_economy(balance)
    if n >= int(eco["max_members"]):
        return {"ok": False, "error": "alliance_full"}

    s.add(AllianceMember(alliance_id=a.id, player_id=pid, role="member"))
    s.flush()
    return {
        "ok": True,
        "alliance": {
            "id": str(a.id),
            "display_name": a.display_name,
            "tag": a.tag,
        },
    }


def leave_alliance(s: Session, *, player_id: str) -> dict:
    try:
        pid = uuid.UUID(str(player_id).strip())
    except Exception:
        return {"ok": False, "error": "invalid_player_id"}

    m = membership_for_player(s, player_id=pid)
    if not m:
        return {"ok": False, "error": "not_in_alliance"}

    aid = m.alliance_id
    if m.role == "leader":
        s.execute(delete(Alliance).where(Alliance.id == aid))
    else:
        s.delete(m)
    s.flush()
    return {"ok": True, "disbanded": m.role == "leader"}


def get_my_alliance(s: Session, *, player_id: str) -> dict:
    try:
        pid = uuid.UUID(str(player_id).strip())
    except Exception:
        return {"ok": False, "error": "invalid_player_id"}

    m = membership_for_player(s, player_id=pid)
    if not m:
        return {"ok": True, "alliance": None}

    a = s.get(Alliance, m.alliance_id)
    if not a:
        return {"ok": True, "alliance": None}

    rows = (
        s.execute(
            select(AllianceMember, Player.display_name)
            .join(Player, Player.id == AllianceMember.player_id)
            .where(AllianceMember.alliance_id == a.id)
            .order_by(AllianceMember.joined_at.asc())
        )
        .all()
    )
    members = [
        {
            "player_id": str(r[0].player_id),
            "display_name": str(r[1]),
            "role": str(r[0].role),
        }
        for r in rows
    ]
    return {
        "ok": True,
        "alliance": {
            "id": str(a.id),
            "display_name": a.display_name,
            "tag": a.tag,
            "join_code": a.join_code if m.role == "leader" else None,
            "my_role": m.role,
            "members": members,
        },
    }


def assert_alliance_member(
    s: Session, *, player_id: uuid.UUID, alliance_id: uuid.UUID
) -> bool:
    m = (
        s.execute(
            select(AllianceMember).where(
                AllianceMember.player_id == player_id,
                AllianceMember.alliance_id == alliance_id,
            )
        )
        .scalar_one_or_none()
    )
    return m is not None


def alliance_influence_at_cell(
    s: Session, balance: Any, *, player_id: str, x: int, y: int, z: int
) -> dict:
    try:
        pid = uuid.UUID(str(player_id).strip())
    except Exception:
        return {"ok": False, "error": "invalid_player_id"}

    m = membership_for_player(s, player_id=pid)
    if not m:
        return {"ok": False, "error": "not_in_alliance"}

    member_ids = (
        s.execute(
            select(AllianceMember.player_id).where(
                AllianceMember.alliance_id == m.alliance_id
            )
        )
        .scalars()
        .all()
    )
    if not member_ids:
        return {"ok": True, "sum": 0.0, "capped": 0.0}

    raw = s.execute(
        select(func.coalesce(func.sum(InfluenceCell.control_value), 0.0)).where(
            InfluenceCell.x == int(x),
            InfluenceCell.y == int(y),
            InfluenceCell.z == int(z),
            InfluenceCell.player_id.in_(member_ids),
        )
    ).scalar_one()
    total = float(raw or 0.0)
    eco = get_alliance_economy(balance)
    cap = float(eco["influence_cell_cap"])
    capped = min(cap, total)
    return {
        "ok": True,
        "sum": total,
        "capped": capped,
        "cap": cap,
        "alliance_id": str(m.alliance_id),
    }
