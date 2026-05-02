from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app.db.models.chat_message import ChatMessage
from app.db.models.player import Player
from app.db.models.player_block import PlayerBlock

MAX_CHAT_BODY_LEN = 1000
MAX_MESSAGES_PER_POLL = 100
RATE_WINDOW_SEC = 60
RATE_MAX_MESSAGES = 40
CHAT_HIDDEN_PLACEHOLDER = "Сообщение скрыто модератором."
CHAT_BAN_HOURS_MAX_MOD = 168
CHAT_BAN_HOURS_MAX_ADMIN = 8760  # 365d


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_uuid(s: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(s).strip())
    except (ValueError, TypeError, AttributeError):
        return None


def _validate_chat_body(body: str) -> tuple[str | None, str | None]:
    """Возвращает (текст, None) или (None, код_ошибки). Без молчаливого усечения — клиент знает лимит."""
    t = (body or "").strip()
    if not t:
        return None, "empty_body"
    if len(t) > MAX_CHAT_BODY_LEN:
        return None, "message_too_long"
    return t, None


def _rate_limited(s: Session, *, sender_id: uuid.UUID) -> bool:
    since = _utcnow() - timedelta(seconds=RATE_WINDOW_SEC)
    n = int(
        s.execute(
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.sender_id == sender_id, ChatMessage.created_at >= since)
        ).scalar_one()
    )
    return n >= RATE_MAX_MESSAGES


def _blocked_ids_for_viewer(s: Session, *, viewer_id: uuid.UUID) -> set[uuid.UUID]:
    rows = s.execute(
        select(PlayerBlock.blocked_id).where(PlayerBlock.blocker_id == viewer_id)
    ).scalars().all()
    return set(rows)


def _player_row(s: Session, *, player_id: uuid.UUID) -> Player | None:
    return s.execute(select(Player).where(Player.id == player_id)).scalar_one_or_none()


def viewer_moderation_flags(s: Session, *, viewer_id: str) -> tuple[bool, bool]:
    vid = _parse_uuid(viewer_id)
    if not vid:
        return False, False
    p = _player_row(s, player_id=vid)
    if not p:
        return False, False
    return bool(getattr(p, "is_game_admin", False)), bool(getattr(p, "is_game_moderator", False))


def viewer_can_moderate_global(s: Session, *, viewer_id: str) -> bool:
    a, m = viewer_moderation_flags(s, viewer_id=viewer_id)
    return a or m


def _sender_chat_banned(s: Session, *, sender_id: uuid.UUID) -> bool:
    p = _player_row(s, player_id=sender_id)
    if not p:
        return False
    until = getattr(p, "chat_banned_until", None)
    if until is None:
        return False
    return until > _utcnow()


def _staff_exempt_map(s: Session, *, player_ids: list[uuid.UUID]) -> dict[uuid.UUID, bool]:
    if not player_ids:
        return {}
    rows = s.execute(select(Player.id, Player.staff_chat_exempt).where(Player.id.in_(player_ids))).all()
    return {r[0]: bool(r[1]) for r in rows}


def _should_hide_sender(
    *,
    sender_id: uuid.UUID,
    viewer_id: uuid.UUID,
    blocked: set[uuid.UUID],
    staff: dict[uuid.UUID, bool],
) -> bool:
    if sender_id == viewer_id:
        return False
    if sender_id not in blocked:
        return False
    return not bool(staff.get(sender_id, False))


def post_global_message(s: Session, *, sender_id: str, body: str) -> dict[str, Any]:
    sid = _parse_uuid(sender_id)
    if not sid:
        return {"ok": False, "error": "invalid_sender"}
    sp = _player_row(s, player_id=sid)
    if sp and bool(getattr(sp, "account_disabled", False)):
        return {"ok": False, "error": "account_disabled"}
    if _sender_chat_banned(s, sender_id=sid):
        return {"ok": False, "error": "chat_banned"}
    text_body, err = _validate_chat_body(body)
    if err:
        return {"ok": False, "error": err, **({"max": MAX_CHAT_BODY_LEN} if err == "message_too_long" else {})}
    if _rate_limited(s, sender_id=sid):
        return {"ok": False, "error": "rate_limited"}
    row = ChatMessage(
        channel_kind="global",
        alliance_id=None,
        sender_id=sid,
        recipient_id=None,
        body=text_body,
        moderation_hidden=False,
    )
    s.add(row)
    s.flush()
    return {"ok": True, "id": int(row.id)}


def list_global_messages(
    s: Session, *, viewer_id: str, since_id: int | None = None
) -> dict[str, Any]:
    vid = _parse_uuid(viewer_id)
    if not vid:
        return {"ok": False, "error": "invalid_viewer", "messages": []}
    blocked = _blocked_ids_for_viewer(s, viewer_id=vid)
    since = int(since_id or 0)
    if since > 0:
        q = (
            select(ChatMessage)
            .where(ChatMessage.channel_kind == "global", ChatMessage.id > since)
            .order_by(ChatMessage.id.asc())
            .limit(MAX_MESSAGES_PER_POLL)
        )
        rows = list(s.execute(q).scalars().all())
    else:
        q = (
            select(ChatMessage)
            .where(ChatMessage.channel_kind == "global")
            .order_by(ChatMessage.id.desc())
            .limit(MAX_MESSAGES_PER_POLL)
        )
        rows = list(s.execute(q).scalars().all())
        rows.reverse()
    senders = list({m.sender_id for m in rows})
    staff = _staff_exempt_map(s, player_ids=senders)
    names = dict(
        s.execute(select(Player.id, Player.display_name).where(Player.id.in_(senders))).all()
    )
    can_mod = viewer_can_moderate_global(s, viewer_id=viewer_id)
    out: list[dict[str, Any]] = []
    for m in rows:
        if _should_hide_sender(
            sender_id=m.sender_id, viewer_id=vid, blocked=blocked, staff=staff
        ):
            continue
        hidden = bool(getattr(m, "moderation_hidden", False))
        body_out = m.body
        if hidden and not can_mod:
            body_out = CHAT_HIDDEN_PLACEHOLDER
        out.append(
            {
                "id": int(m.id),
                "sender_id": str(m.sender_id),
                "display_name": str(names.get(m.sender_id, "—")),
                "body": body_out,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "hidden": hidden,
                "can_mod": can_mod,
            }
        )
    return {"ok": True, "messages": out, "viewer_can_moderate": can_mod}


def post_private_message(
    s: Session, *, sender_id: str, recipient_id: str, body: str
) -> dict[str, Any]:
    sid = _parse_uuid(sender_id)
    rid = _parse_uuid(recipient_id)
    if not sid or not rid:
        return {"ok": False, "error": "invalid_player_id"}
    sp = _player_row(s, player_id=sid)
    if sp and bool(getattr(sp, "account_disabled", False)):
        return {"ok": False, "error": "account_disabled"}
    if _sender_chat_banned(s, sender_id=sid):
        return {"ok": False, "error": "chat_banned"}
    if sid == rid:
        return {"ok": False, "error": "cannot_message_self"}
    peer = s.execute(select(Player).where(Player.id == rid)).scalar_one_or_none()
    if not peer:
        return {"ok": False, "error": "recipient_not_found"}
    text_body, err = _validate_chat_body(body)
    if err:
        return {"ok": False, "error": err, **({"max": MAX_CHAT_BODY_LEN} if err == "message_too_long" else {})}
    if _rate_limited(s, sender_id=sid):
        return {"ok": False, "error": "rate_limited"}
    row = ChatMessage(
        channel_kind="private",
        alliance_id=None,
        sender_id=sid,
        recipient_id=rid,
        body=text_body,
        moderation_hidden=False,
    )
    s.add(row)
    s.flush()
    return {"ok": True, "id": int(row.id)}


def list_private_messages(
    s: Session, *, viewer_id: str, peer_id: str, since_id: int | None = None
) -> dict[str, Any]:
    vid = _parse_uuid(viewer_id)
    pid = _parse_uuid(peer_id)
    if not vid or not pid:
        return {"ok": False, "error": "invalid_player_id", "messages": []}
    blocked = _blocked_ids_for_viewer(s, viewer_id=vid)
    if pid in blocked:
        staff_peer = _staff_exempt_map(s, player_ids=[pid]).get(pid, False)
        if not staff_peer:
            return {"ok": False, "error": "blocked_peer", "messages": []}
    since = int(since_id or 0)
    pair = or_(
        and_(ChatMessage.sender_id == vid, ChatMessage.recipient_id == pid),
        and_(ChatMessage.sender_id == pid, ChatMessage.recipient_id == vid),
    )
    if since > 0:
        q = (
            select(ChatMessage)
            .where(ChatMessage.channel_kind == "private", pair, ChatMessage.id > since)
            .order_by(ChatMessage.id.asc())
            .limit(MAX_MESSAGES_PER_POLL)
        )
        rows = list(s.execute(q).scalars().all())
    else:
        q = (
            select(ChatMessage)
            .where(ChatMessage.channel_kind == "private", pair)
            .order_by(ChatMessage.id.desc())
            .limit(MAX_MESSAGES_PER_POLL)
        )
        rows = list(s.execute(q).scalars().all())
        rows.reverse()
    senders = list({m.sender_id for m in rows})
    staff = _staff_exempt_map(s, player_ids=senders)
    names = dict(
        s.execute(select(Player.id, Player.display_name).where(Player.id.in_(senders))).all()
    )
    out: list[dict[str, Any]] = []
    for m in rows:
        if _should_hide_sender(
            sender_id=m.sender_id, viewer_id=vid, blocked=blocked, staff=staff
        ):
            continue
        out.append(
            {
                "id": int(m.id),
                "sender_id": str(m.sender_id),
                "display_name": str(names.get(m.sender_id, "—")),
                "body": m.body,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
        )
    return {"ok": True, "messages": out}


def list_private_threads(s: Session, *, viewer_id: str) -> dict[str, Any]:
    vid = _parse_uuid(viewer_id)
    if not vid:
        return {"ok": False, "error": "invalid_viewer", "threads": []}
    blocked = _blocked_ids_for_viewer(s, viewer_id=vid)
    staff_blocked = _staff_exempt_map(s, player_ids=list(blocked)) if blocked else {}
    q = (
        select(ChatMessage)
        .where(
            ChatMessage.channel_kind == "private",
            or_(ChatMessage.sender_id == vid, ChatMessage.recipient_id == vid),
        )
        .order_by(ChatMessage.id.desc())
        .limit(2000)
    )
    rows = list(s.execute(q).scalars().all())
    last_by_peer: dict[uuid.UUID, ChatMessage] = {}
    for m in rows:
        peer = m.recipient_id if m.sender_id == vid else m.sender_id
        if peer is None:
            continue
        if peer in blocked and not staff_blocked.get(peer, False):
            continue
        if peer not in last_by_peer:
            last_by_peer[peer] = m
    if not last_by_peer:
        return {"ok": True, "threads": []}
    peers = list(last_by_peer.keys())
    names = dict(s.execute(select(Player.id, Player.display_name).where(Player.id.in_(peers))).all())
    threads = []
    for peer in sorted(peers, key=lambda p: last_by_peer[p].id, reverse=True):
        lm = last_by_peer[peer]
        threads.append(
            {
                "peer_id": str(peer),
                "display_name": str(names.get(peer, "—")),
                "last_preview": (lm.body or "")[:120],
                "last_id": int(lm.id),
            }
        )
    return {"ok": True, "threads": threads}


def list_blocks(s: Session, *, viewer_id: str) -> dict[str, Any]:
    vid = _parse_uuid(viewer_id)
    if not vid:
        return {"ok": False, "error": "invalid_viewer", "blocked_ids": []}
    rows = s.execute(select(PlayerBlock.blocked_id).where(PlayerBlock.blocker_id == vid)).scalars().all()
    return {"ok": True, "blocked_ids": [str(x) for x in rows]}


def add_block(s: Session, *, blocker_id: str, blocked_id: str) -> dict[str, Any]:
    bid = _parse_uuid(blocker_id)
    oid = _parse_uuid(blocked_id)
    if not bid or not oid:
        return {"ok": False, "error": "invalid_player_id"}
    if bid == oid:
        return {"ok": False, "error": "cannot_block_self"}
    other = s.execute(select(Player).where(Player.id == oid)).scalar_one_or_none()
    if not other:
        return {"ok": False, "error": "player_not_found"}
    exists = s.execute(
        select(PlayerBlock).where(
            PlayerBlock.blocker_id == bid, PlayerBlock.blocked_id == oid
        )
    ).scalar_one_or_none()
    if not exists:
        s.add(PlayerBlock(blocker_id=bid, blocked_id=oid))
    return {"ok": True}


def remove_block(s: Session, *, blocker_id: str, blocked_id: str) -> dict[str, Any]:
    bid = _parse_uuid(blocker_id)
    oid = _parse_uuid(blocked_id)
    if not bid or not oid:
        return {"ok": False, "error": "invalid_player_id"}
    s.execute(delete(PlayerBlock).where(PlayerBlock.blocker_id == bid, PlayerBlock.blocked_id == oid))
    return {"ok": True}


def hide_global_message(s: Session, *, actor_id: str, message_id: int) -> dict[str, Any]:
    if not viewer_can_moderate_global(s, viewer_id=actor_id):
        return {"ok": False, "error": "forbidden"}
    mid = int(message_id)
    m = s.execute(
        select(ChatMessage).where(
            ChatMessage.id == mid, ChatMessage.channel_kind == "global"
        )
    ).scalar_one_or_none()
    if not m:
        return {"ok": False, "error": "not_found"}
    m.moderation_hidden = True
    return {"ok": True}


def delete_global_message(s: Session, *, actor_id: str, message_id: int) -> dict[str, Any]:
    if not viewer_can_moderate_global(s, viewer_id=actor_id):
        return {"ok": False, "error": "forbidden"}
    mid = int(message_id)
    m = s.execute(
        select(ChatMessage).where(
            ChatMessage.id == mid, ChatMessage.channel_kind == "global"
        )
    ).scalar_one_or_none()
    if not m:
        return {"ok": False, "error": "not_found"}
    s.delete(m)
    return {"ok": True}


def ban_player_chat(
    s: Session, *, actor_id: str, target_id: str, hours: int
) -> dict[str, Any]:
    if not viewer_can_moderate_global(s, viewer_id=actor_id):
        return {"ok": False, "error": "forbidden"}
    aid = _parse_uuid(actor_id)
    tid = _parse_uuid(target_id)
    if not aid or not tid:
        return {"ok": False, "error": "invalid_player_id"}
    is_adm, is_mod = viewer_moderation_flags(s, viewer_id=actor_id)
    h = int(hours)
    target = _player_row(s, player_id=tid)
    if not target:
        return {"ok": False, "error": "player_not_found"}
    if tid == aid:
        return {"ok": False, "error": "cannot_ban_self"}
    if bool(getattr(target, "is_game_admin", False)) and not is_adm:
        return {"ok": False, "error": "forbidden"}
    if h <= 0:
        if not is_adm:
            return {"ok": False, "error": "invalid_hours"}
        target.chat_banned_until = None
        return {"ok": True, "cleared": True}
    cap = CHAT_BAN_HOURS_MAX_ADMIN if is_adm else CHAT_BAN_HOURS_MAX_MOD
    h = max(1, min(h, cap))
    target.chat_banned_until = _utcnow() + timedelta(hours=h)
    return {"ok": True, "until": target.chat_banned_until.isoformat()}


def set_player_account_disabled(
    s: Session, *, actor_id: str, target_id: str, disabled: bool
) -> dict[str, Any]:
    if not viewer_moderation_flags(s, viewer_id=actor_id)[0]:
        return {"ok": False, "error": "admin_only"}
    aid = _parse_uuid(actor_id)
    tid = _parse_uuid(target_id)
    if not aid or not tid:
        return {"ok": False, "error": "invalid_player_id"}
    if tid == aid:
        return {"ok": False, "error": "cannot_ban_self"}
    target = _player_row(s, player_id=tid)
    if not target:
        return {"ok": False, "error": "player_not_found"}
    target.account_disabled = bool(disabled)
    return {"ok": True}


