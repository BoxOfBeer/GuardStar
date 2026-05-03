"""HTTP API: чат и модерация."""

from __future__ import annotations

from flask import jsonify, request

from app.db.engine import db_session
from app.routes.api.blueprint import api_bp
from app.routes.api.common import _current_player_id
from app.services import chat_service as chat_svc



@api_bp.get("/chat/global")
def api_chat_global_get():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    since = request.args.get("since_id", type=int)
    with db_session() as s:
        data = chat_svc.list_global_messages(s, viewer_id=player_id, since_id=since)
    return jsonify(data)


@api_bp.post("/chat/global")
def api_chat_global_post():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    payload = request.get_json(silent=True) or {}
    body = payload.get("body") or ""
    with db_session() as s:
        result = chat_svc.post_global_message(s, sender_id=player_id, body=str(body))
        if not result.get("ok"):
            err = result.get("error")
            if err == "rate_limited":
                code = 429
            elif err == "message_too_long":
                code = 413
            else:
                code = 400
            return jsonify(result), code
        s.commit()
    return jsonify(result)


@api_bp.get("/chat/private")
def api_chat_private_get():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    peer = (request.args.get("peer_id") or "").strip()
    if not peer:
        return jsonify({"ok": False, "error": "peer_id_required"}), 400
    since = request.args.get("since_id", type=int)
    with db_session() as s:
        data = chat_svc.list_private_messages(
            s, viewer_id=player_id, peer_id=peer, since_id=since
        )
        if data.get("ok"):
            s.commit()
    if not data.get("ok") and data.get("error") == "blocked_peer":
        return jsonify(data), 403
    return jsonify(data)


@api_bp.post("/chat/private")
def api_chat_private_post():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    payload = request.get_json(silent=True) or {}
    peer = (payload.get("peer_id") or "").strip()
    body = payload.get("body") or ""
    with db_session() as s:
        result = chat_svc.post_private_message(
            s, sender_id=player_id, recipient_id=peer, body=str(body)
        )
        if not result.get("ok"):
            err = result.get("error")
            if err == "rate_limited":
                code = 429
            elif err == "message_too_long":
                code = 413
            else:
                code = 400
            return jsonify(result), code
        s.commit()
    return jsonify(result)


@api_bp.get("/chat/private/threads")
def api_chat_private_threads():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    with db_session() as s:
        data = chat_svc.list_private_threads(s, viewer_id=player_id)
    return jsonify(data)


@api_bp.get("/chat/private/badge")
def api_chat_private_badge():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    with db_session() as s:
        data = chat_svc.private_inbox_badge_counts(s, viewer_id=player_id)
    return jsonify(data)


@api_bp.get("/chat/private/thread/meta")
def api_chat_private_thread_meta():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    peer = (request.args.get("peer_id") or "").strip()
    if not peer:
        return jsonify({"ok": False, "error": "peer_id_required"}), 400
    with db_session() as s:
        data = chat_svc.get_private_thread_meta(s, viewer_id=player_id, peer_id=peer)
    if data.get("ok"):
        return jsonify(data)
    code = 404 if data.get("error") == "recipient_not_found" else 400
    return jsonify(data), code


@api_bp.post("/chat/private/thread/open")
def api_chat_private_thread_open():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    payload = request.get_json(silent=True) or {}
    peer = (payload.get("peer_id") or "").strip()
    send_rr = bool(payload.get("send_read_receipts"))
    if not peer:
        return jsonify({"ok": False, "error": "peer_id_required"}), 400
    with db_session() as s:
        result = chat_svc.open_private_thread_intro(
            s, viewer_id=player_id, peer_id=peer, send_read_receipts=send_rr
        )
        if not result.get("ok"):
            err = result.get("error")
            code = 404 if err == "recipient_not_found" else 400
            return jsonify(result), code
        s.commit()
    return jsonify(result)


@api_bp.patch("/chat/private/thread/prefs")
def api_chat_private_thread_prefs():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    payload = request.get_json(silent=True) or {}
    peer = (payload.get("peer_id") or "").strip()
    send_rr = bool(payload.get("send_read_receipts"))
    if not peer:
        return jsonify({"ok": False, "error": "peer_id_required"}), 400
    with db_session() as s:
        result = chat_svc.set_private_send_read_receipts(
            s, viewer_id=player_id, peer_id=peer, send_read_receipts=send_rr
        )
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
    return jsonify(result)


@api_bp.post("/chat/private/thread/hide")
def api_chat_private_thread_hide():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    payload = request.get_json(silent=True) or {}
    peer = (payload.get("peer_id") or "").strip()
    if not peer:
        return jsonify({"ok": False, "error": "peer_id_required"}), 400
    with db_session() as s:
        result = chat_svc.hide_private_thread(s, viewer_id=player_id, peer_id=peer)
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
    return jsonify(result)


@api_bp.get("/chat/blocks")
def api_chat_blocks_get():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    with db_session() as s:
        data = chat_svc.list_blocks(s, viewer_id=player_id)
    return jsonify(data)


@api_bp.post("/chat/blocks")
def api_chat_blocks_post():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    payload = request.get_json(silent=True) or {}
    blocked = (payload.get("blocked_id") or "").strip()
    with db_session() as s:
        result = chat_svc.add_block(s, blocker_id=player_id, blocked_id=blocked)
        if not result.get("ok"):
            return jsonify(result), 400
        s.commit()
    return jsonify(result)


@api_bp.delete("/chat/blocks/<blocked_id>")
def api_chat_blocks_delete(blocked_id: str):
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    with db_session() as s:
        result = chat_svc.remove_block(s, blocker_id=player_id, blocked_id=blocked_id)
        s.commit()
    return jsonify(result)


@api_bp.post("/chat/global/<int:message_id>/hide")
def api_chat_global_hide(message_id: int):
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    with db_session() as s:
        result = chat_svc.hide_global_message(s, actor_id=player_id, message_id=message_id)
        if not result.get("ok"):
            code = 403 if result.get("error") == "forbidden" else 404
            return jsonify(result), code
        s.commit()
    return jsonify(result)


@api_bp.delete("/chat/global/<int:message_id>")
def api_chat_global_delete_message(message_id: int):
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    with db_session() as s:
        result = chat_svc.delete_global_message(s, actor_id=player_id, message_id=message_id)
        if not result.get("ok"):
            code = 403 if result.get("error") == "forbidden" else 404
            return jsonify(result), code
        s.commit()
    return jsonify(result)


@api_bp.post("/chat/moderation/chat-ban")
def api_chat_moderation_chat_ban():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    payload = request.get_json(silent=True) or {}
    target = (payload.get("player_id") or "").strip()
    hours = int(payload.get("hours") or 24)
    with db_session() as s:
        result = chat_svc.ban_player_chat(
            s, actor_id=player_id, target_id=target, hours=hours
        )
        if not result.get("ok"):
            err = result.get("error")
            code = 403 if err in ("forbidden", "admin_only") else 400
            return jsonify(result), code
        s.commit()
    return jsonify(result)


@api_bp.post("/chat/moderation/account-ban")
def api_chat_moderation_account_ban():
    player_id = _current_player_id()
    if not player_id:
        return jsonify({"error": "not_authenticated"}), 401
    payload = request.get_json(silent=True) or {}
    target = (payload.get("player_id") or "").strip()
    disabled = bool(payload.get("disable", True))
    with db_session() as s:
        result = chat_svc.set_player_account_disabled(
            s, actor_id=player_id, target_id=target, disabled=disabled
        )
        if not result.get("ok"):
            err = result.get("error")
            code = 403 if err in ("admin_only", "forbidden") else 400
            return jsonify(result), code
        s.commit()
    return jsonify(result)


@api_bp.get("/chat/alliance")
def api_chat_alliance_stub():
    """Заглушка до модели альянсов и канала alliance:{id}."""
    return (
        jsonify(
            {
                "ok": False,
                "error": "alliance_chat_not_implemented",
                "detail": "Альянс-чат будет доступен после введения сущности альянса.",
            }
        ),
        501,
    )


@api_bp.post("/chat/alliance")
def api_chat_alliance_post_stub():
    return (
        jsonify({"ok": False, "error": "alliance_chat_not_implemented"}),
        501,
    )


