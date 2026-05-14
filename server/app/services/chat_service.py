from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.db.models.chat_message import ChatMessage
from app.db.models.player import Player
from app.db.models.player_block import PlayerBlock
from app.db.models.private_chat_peer_pref import PrivateChatPeerPref

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


def _pref_row(
    s: Session, *, viewer: uuid.UUID, peer: uuid.UUID
) -> PrivateChatPeerPref | None:
    return s.execute(
        select(PrivateChatPeerPref).where(
            PrivateChatPeerPref.viewer_player_id == viewer,
            PrivateChatPeerPref.peer_player_id == peer,
        )
    ).scalar_one_or_none()


def _clear_peer_hidden_after_inbound(
    s: Session, *, recipient_id: uuid.UUID, sender_id: uuid.UUID
) -> None:
    row = _pref_row(s, viewer=recipient_id, peer=sender_id)
    if row and row.hidden_at is not None:
        row.hidden_at = None


def _unread_private_incoming(
    s: Session, *, viewer_id: uuid.UUID, peer_id: uuid.UUID, pref: PrivateChatPeerPref | None
) -> int:
    cond = and_(
        ChatMessage.channel_kind == "private",
        ChatMessage.sender_id == peer_id,
        ChatMessage.recipient_id == viewer_id,
    )
    if pref is not None and pref.welcomed_at is not None:
        return int(
            s.execute(
                select(func.count())
                .select_from(ChatMessage)
                .where(cond, ChatMessage.id > int(pref.last_read_incoming_id or 0))
            ).scalar_one()
        )
    return int(s.execute(select(func.count()).select_from(ChatMessage).where(cond)).scalar_one())


def _needs_intro(pref: PrivateChatPeerPref | None) -> bool:
    return pref is None or pref.welcomed_at is None


def advance_private_incoming_read(
    s: Session, *, viewer_id: uuid.UUID, peer_id: uuid.UUID
) -> None:
    """После загрузки ленты: отметить входящие прочитанными (если диалог уже «принят»)."""
    pref = _pref_row(s, viewer=viewer_id, peer=peer_id)
    if pref is None or pref.welcomed_at is None:
        return
    mx = s.execute(
        select(func.max(ChatMessage.id)).where(
            ChatMessage.channel_kind == "private",
            ChatMessage.sender_id == peer_id,
            ChatMessage.recipient_id == viewer_id,
        )
    ).scalar_one_or_none()
    mx = int(mx or 0)
    old = int(pref.last_read_incoming_id or 0)
    if mx <= old:
        return
    now = _utcnow()
    if pref.send_read_receipts:
        s.execute(
            update(ChatMessage)
            .where(
                ChatMessage.channel_kind == "private",
                ChatMessage.sender_id == peer_id,
                ChatMessage.recipient_id == viewer_id,
                ChatMessage.id > old,
                ChatMessage.id <= mx,
                ChatMessage.read_receipt_at.is_(None),
            )
            .values(read_receipt_at=now)
        )
    pref.last_read_incoming_id = mx


def private_inbox_badge_counts(s: Session, *, viewer_id: str) -> dict[str, Any]:
    vid = _parse_uuid(viewer_id)
    if not vid:
        return {"ok": False, "error": "invalid_viewer"}
    tl = list_private_threads(s, viewer_id=viewer_id)
    if not tl.get("ok"):
        return tl
    threads = tl.get("threads") or []
    new_c = sum(
        1
        for t in threads
        if t.get("needs_intro") and int(t.get("unread_incoming") or 0) > 0
    )
    unrd = sum(int(t.get("unread_incoming") or 0) for t in threads)
    return {"ok": True, "new_contacts": new_c, "unread_messages": unrd}


def get_private_thread_meta(s: Session, *, viewer_id: str, peer_id: str) -> dict[str, Any]:
    vid = _parse_uuid(viewer_id)
    pid = _parse_uuid(peer_id)
    if not vid or not pid:
        return {"ok": False, "error": "invalid_player_id"}
    if pid == vid:
        return {"ok": False, "error": "cannot_message_self"}
    peer = s.execute(select(Player).where(Player.id == pid)).scalar_one_or_none()
    if not peer:
        return {"ok": False, "error": "recipient_not_found"}
    pref = _pref_row(s, viewer=vid, peer=pid)
    needs_intro = pref is None or pref.welcomed_at is None
    return {
        "ok": True,
        "needs_intro": needs_intro,
        "send_read_receipts": bool(pref.send_read_receipts) if pref else False,
        "peer_display_name": str(peer.display_name or "—"),
    }


def open_private_thread_intro(
    s: Session, *, viewer_id: str, peer_id: str, send_read_receipts: bool
) -> dict[str, Any]:
    vid = _parse_uuid(viewer_id)
    pid = _parse_uuid(peer_id)
    if not vid or not pid:
        return {"ok": False, "error": "invalid_player_id"}
    if pid == vid:
        return {"ok": False, "error": "cannot_message_self"}
    peer = s.execute(select(Player).where(Player.id == pid)).scalar_one_or_none()
    if not peer:
        return {"ok": False, "error": "recipient_not_found"}
    now = _utcnow()
    pref = _pref_row(s, viewer=vid, peer=pid)
    if not pref:
        pref = PrivateChatPeerPref(
            viewer_player_id=vid,
            peer_player_id=pid,
            welcomed_at=now,
            send_read_receipts=bool(send_read_receipts),
            last_read_incoming_id=0,
        )
        s.add(pref)
    else:
        pref.welcomed_at = now
        pref.send_read_receipts = bool(send_read_receipts)
    s.flush()
    return {"ok": True}


def set_private_send_read_receipts(
    s: Session, *, viewer_id: str, peer_id: str, send_read_receipts: bool
) -> dict[str, Any]:
    vid = _parse_uuid(viewer_id)
    pid = _parse_uuid(peer_id)
    if not vid or not pid:
        return {"ok": False, "error": "invalid_player_id"}
    pref = _pref_row(s, viewer=vid, peer=pid)
    if not pref:
        pref = PrivateChatPeerPref(
            viewer_player_id=vid,
            peer_player_id=pid,
            welcomed_at=_utcnow(),
            send_read_receipts=bool(send_read_receipts),
            last_read_incoming_id=0,
        )
        s.add(pref)
    else:
        pref.send_read_receipts = bool(send_read_receipts)
    return {"ok": True}


def hide_private_thread(s: Session, *, viewer_id: str, peer_id: str) -> dict[str, Any]:
    vid = _parse_uuid(viewer_id)
    pid = _parse_uuid(peer_id)
    if not vid or not pid:
        return {"ok": False, "error": "invalid_player_id"}
    now = _utcnow()
    pref = _pref_row(s, viewer=vid, peer=pid)
    if not pref:
        pref = PrivateChatPeerPref(
            viewer_player_id=vid,
            peer_player_id=pid,
            welcomed_at=now,
            send_read_receipts=False,
            last_read_incoming_id=0,
            hidden_at=now,
        )
        s.add(pref)
    else:
        pref.hidden_at = now
    return {"ok": True}


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
    _clear_peer_hidden_after_inbound(s, recipient_id=rid, sender_id=sid)
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
        # Исходящие: отметка «прочитано» только если собеседник включает уведомления об этом ко мне
        rr_at = getattr(m, "read_receipt_at", None)
        item: dict[str, Any] = {
            "id": int(m.id),
            "sender_id": str(m.sender_id),
            "display_name": str(names.get(m.sender_id, "—")),
            "body": m.body,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        if m.sender_id == vid:
            rp = _pref_row(s, viewer=m.recipient_id, peer=vid) if m.recipient_id else None
            if rp is not None and rp.send_read_receipts:
                item["read_receipt_at"] = rr_at.isoformat() if rr_at else None
            else:
                item["read_receipt_at"] = None
        out.append(item)

    advance_private_incoming_read(s, viewer_id=vid, peer_id=pid)
    return {"ok": True, "messages": out}


def list_private_threads(s: Session, *, viewer_id: str) -> dict[str, Any]:
    vid = _parse_uuid(viewer_id)
    if not vid:
        return {
            "ok": False,
            "error": "invalid_viewer",
            "threads": [],
            "badge_new_contacts": 0,
            "badge_unread": 0,
        }
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
        return {"ok": True, "threads": [], "badge_new_contacts": 0, "badge_unread": 0}
    peers = list(last_by_peer.keys())
    prefs = {
        r.peer_player_id: r
        for r in s.execute(
            select(PrivateChatPeerPref).where(
                PrivateChatPeerPref.viewer_player_id == vid,
                PrivateChatPeerPref.peer_player_id.in_(peers),
            )
        ).scalars().all()
    }
    names = dict(s.execute(select(Player.id, Player.display_name).where(Player.id.in_(peers))).all())
    threads = []
    badge_new = 0
    badge_unread = 0
    for peer in sorted(peers, key=lambda p: last_by_peer[p].id, reverse=True):
        pref = prefs.get(peer)
        if pref is not None and pref.hidden_at is not None:
            continue
        lm = last_by_peer[peer]
        unread = _unread_private_incoming(s, viewer_id=vid, peer_id=peer, pref=pref)
        intro = _needs_intro(pref)
        if intro and unread > 0:
            badge_new += 1
        badge_unread += unread
        threads.append(
            {
                "peer_id": str(peer),
                "display_name": str(names.get(peer, "—")),
                "last_preview": (lm.body or "")[:120],
                "last_id": int(lm.id),
                "last_message_at": lm.created_at.isoformat() if lm.created_at else None,
                "unread_incoming": unread,
                "needs_intro": intro,
                "send_read_receipts": bool(pref.send_read_receipts) if pref else False,
            }
        )
    return {
        "ok": True,
        "threads": threads,
        "badge_new_contacts": badge_new,
        "badge_unread": badge_unread,
    }


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


def post_alliance_message(
    s: Session, *, sender_id: str, alliance_id: str, body: str
) -> dict[str, Any]:
    from app.services import alliance_service as als

    sid = _parse_uuid(sender_id)
    aid = _parse_uuid(alliance_id)
    if not sid or not aid:
        return {"ok": False, "error": "invalid_payload"}
    sp = _player_row(s, player_id=sid)
    if sp and bool(getattr(sp, "account_disabled", False)):
        return {"ok": False, "error": "account_disabled"}
    if _sender_chat_banned(s, sender_id=sid):
        return {"ok": False, "error": "chat_banned"}
    if not als.assert_alliance_member(s, player_id=sid, alliance_id=aid):
        return {"ok": False, "error": "forbidden"}
    text_body, err = _validate_chat_body(body)
    if err:
        return {
            "ok": False,
            "error": err,
            **({"max": MAX_CHAT_BODY_LEN} if err == "message_too_long" else {}),
        }
    if _rate_limited(s, sender_id=sid):
        return {"ok": False, "error": "rate_limited"}
    row = ChatMessage(
        channel_kind="alliance",
        alliance_id=aid,
        sender_id=sid,
        recipient_id=None,
        body=text_body,
        moderation_hidden=False,
    )
    s.add(row)
    s.flush()
    return {"ok": True, "id": int(row.id)}


def list_alliance_messages(
    s: Session, *, viewer_id: str, alliance_id: str, since_id: int | None = None
) -> dict[str, Any]:
    from app.services import alliance_service as als

    vid = _parse_uuid(viewer_id)
    aid = _parse_uuid(alliance_id)
    if not vid or not aid:
        return {"ok": False, "error": "invalid_payload", "messages": []}
    if not als.assert_alliance_member(s, player_id=vid, alliance_id=aid):
        return {"ok": False, "error": "forbidden", "messages": []}
    blocked = _blocked_ids_for_viewer(s, viewer_id=vid)
    since = int(since_id or 0)
    base = and_(
        ChatMessage.channel_kind == "alliance",
        ChatMessage.alliance_id == aid,
    )
    if since > 0:
        q = (
            select(ChatMessage)
            .where(base, ChatMessage.id > since)
            .order_by(ChatMessage.id.asc())
            .limit(MAX_MESSAGES_PER_POLL)
        )
        rows = list(s.execute(q).scalars().all())
    else:
        q = (
            select(ChatMessage)
            .where(base)
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
    return {"ok": True, "messages": out}


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


