"""API чата: общий канал, ЛС, блокировки (нужен TEST_DATABASE_URL)."""

from __future__ import annotations

import pytest

import tests.integration_helpers as ih


@pytest.fixture(autouse=True)
def _integration_world_cleanup(_test_engine):
    ih.reset_world_tick(_test_engine)
    yield
    ih.delete_players_display_prefix(_test_engine)


def test_global_chat_roundtrip(client, _test_engine):
    with ih.registered_player(client, _test_engine, "ch1") as a:
        r = client.post("/api/chat/global", json={"body": "  hello world  "})
        assert r.status_code == 200
        assert r.get_json().get("ok") is True
        g = client.get("/api/chat/global").get_json()
        assert g.get("ok") is True
        msgs = g.get("messages") or []
        assert any((m.get("body") or "").strip() == "hello world" for m in msgs)


def test_global_chat_message_too_long(client, _test_engine):
    with ih.registered_player(client, _test_engine, "ch1long") as a:
        long_body = "x" * 1001
        r = client.post("/api/chat/global", json={"body": long_body})
        assert r.status_code == 413
        assert r.get_json().get("error") == "message_too_long"


def test_private_chat_and_block(client, _test_engine):
    na = ih.display_name_pytest("ch2a")
    nb = ih.display_name_pytest("ch2b")
    ra = client.post("/api/register", json={"display_name": na})
    assert ra.status_code == 200
    a = ra.get_json()
    client.post("/api/logout")
    rb = client.post("/api/register", json={"display_name": nb})
    assert rb.status_code == 200
    b = rb.get_json()
    try:
        client.post("/api/logout")
        assert client.post("/api/login", json={"access_code": a["access_code"]}).status_code == 200
        peer = b["player_id"]
        r = client.post("/api/chat/private", json={"peer_id": peer, "body": "hi there"})
        assert r.status_code == 200
        assert r.get_json().get("ok") is True

        client.post("/api/logout")
        assert client.post("/api/login", json={"access_code": b["access_code"]}).status_code == 200
        inbox = client.get(f"/api/chat/private?peer_id={a['player_id']}").get_json()
        assert inbox.get("ok") is True
        assert any("hi there" in (m.get("body") or "") for m in (inbox.get("messages") or []))

        blk = client.post("/api/chat/blocks", json={"blocked_id": a["player_id"]})
        assert blk.status_code == 200
        inbox2 = client.get(f"/api/chat/private?peer_id={a['player_id']}").get_json()
        assert inbox2.get("ok") is False
        assert inbox2.get("error") == "blocked_peer"
    finally:
        ih.delete_player_cascade(_test_engine, a["player_id"])
        ih.delete_player_cascade(_test_engine, b["player_id"])


def test_private_read_receipt_intro_and_hide(client, _test_engine):
    na = ih.display_name_pytest("rch_a")
    nb = ih.display_name_pytest("rch_b")
    ra = client.post("/api/register", json={"display_name": na})
    rb = client.post("/api/register", json={"display_name": nb})
    assert ra.status_code == 200 and rb.status_code == 200
    a = ra.get_json()
    b = rb.get_json()
    try:
        client.post("/api/logout")
        assert client.post("/api/login", json={"access_code": a["access_code"]}).status_code == 200
        assert (
            client.post("/api/chat/private", json={"peer_id": b["player_id"], "body": "ping"}).status_code
            == 200
        )
        client.post("/api/logout")
        assert client.post("/api/login", json={"access_code": b["access_code"]}).status_code == 200

        thr = client.get("/api/chat/private/threads").get_json()
        assert thr.get("ok") is True
        assert int(thr.get("badge_unread") or 0) >= 1

        assert (
            client.post(
                "/api/chat/private/thread/open",
                json={"peer_id": a["player_id"], "send_read_receipts": True},
            ).status_code
            == 200
        )

        inbox_b = client.get(f"/api/chat/private?peer_id={a['player_id']}").get_json()
        assert inbox_b.get("ok") is True
        msgs_b = inbox_b.get("messages") or []
        assert any((m.get("body") or "") == "ping" for m in msgs_b)

        client.post("/api/logout")
        assert client.post("/api/login", json={"access_code": a["access_code"]}).status_code == 200
        inbox_a = client.get(f"/api/chat/private?peer_id={b['player_id']}").get_json()
        assert inbox_a.get("ok") is True
        sent = [m for m in (inbox_a.get("messages") or []) if m.get("sender_id") == a["player_id"]]
        assert sent
        assert sent[-1].get("read_receipt_at")

        hid = client.post(
            "/api/chat/private/thread/hide", json={"peer_id": b["player_id"]}
        ).get_json()
        assert hid.get("ok") is True
        thr2 = client.get("/api/chat/private/threads").get_json()
        assert thr2.get("ok") is True
        peers = [t.get("peer_id") for t in (thr2.get("threads") or [])]
        assert b["player_id"] not in peers
    finally:
        ih.delete_player_cascade(_test_engine, a["player_id"])
        ih.delete_player_cascade(_test_engine, b["player_id"])
