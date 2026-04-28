def test_register_creates_player_and_start(client):
    r = client.post("/api/register", json={"display_name": "Test"})
    assert r.status_code == 200
    body = r.get_json()
    assert "player_id" in body
    assert "access_code" in body
    assert isinstance(body["access_code"], str)
    assert len(body["access_code"]) == 32

    me = client.get("/api/me")
    assert me.status_code == 200
    data = me.get_json()
    assert data["player_id"] == body["player_id"]
    assert len(data["planets"]) == 1
    p = data["planets"][0]
    assert p["resources"]["metal"] >= 0
    assert any(u["unit_type"] == "scout" for u in p["units"])


def test_login_with_invalid_code_fails(client):
    r = client.post("/api/login", json={"access_code": "0" * 32})
    assert r.status_code == 401


def test_login_with_valid_code_works(client):
    reg = client.post("/api/register", json={"display_name": "Test2"})
    code = reg.get_json()["access_code"]

    client.post("/api/logout")
    me_before = client.get("/api/me")
    assert me_before.status_code == 401

    login = client.post("/api/login", json={"access_code": code})
    assert login.status_code == 200

    me_after = client.get("/api/me")
    assert me_after.status_code == 200


def test_world_window_returns_9x9(client):
    client.post("/api/register", json={"display_name": "MapTest"})
    r = client.get("/api/world/window?radius=4")
    assert r.status_code == 200
    body = r.get_json()
    assert body["radius"] == 4
    assert body["z"] == 0
    assert body["center"]["x"] is not None
    assert body["center"]["y"] is not None
    assert len(body["cells"]) == 9
    assert all(len(row["row"]) == 9 for row in body["cells"])


def test_world_window_z_changes_and_is_deterministic(client):
    client.post("/api/register", json={"display_name": "ZTest"})

    w0a = client.get("/api/world/window?radius=2&z=0").get_json()
    w0b = client.get("/api/world/window?radius=2&z=0").get_json()
    assert w0a == w0b

    w1 = client.get("/api/world/window?radius=2&z=1").get_json()
    assert w1["z"] == 1
    assert w1["center"] == w0a["center"]

    any_cell = w1["cells"][0]["row"][0]
    assert "terrain" in any_cell
    assert "glyph" in any_cell


def test_health_and_ready_endpoints(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.get_json() == {"status": "ok", "app": "GuardStar"}

    ready = client.get("/api/ready")
    assert ready.status_code == 200
    assert ready.get_json() == {"status": "ready"}


def test_move_scout_creates_order(client):
    client.post("/api/register", json={"display_name": "Mover"})
    window = client.get("/api/world/window?radius=4&z=0").get_json()
    cx, cy = window["center"]["x"], window["center"]["y"]

    move = client.post("/api/units/move_scout", json={"x": cx + 1, "y": cy, "z": 0})
    assert move.status_code == 200
    body = move.get_json()
    assert body["ok"] is True
    assert body["status"] == "queued"
    assert body["target"] == {"x": cx + 1, "y": cy, "z": 0}
    assert body["start_tick"] == 1
    assert body["finish_tick"] == 1


def test_move_scout_rejects_second_active_order(client):
    client.post("/api/register", json={"display_name": "QueueLock"})
    window = client.get("/api/world/window?radius=4&z=0").get_json()
    cx, cy = window["center"]["x"], window["center"]["y"]

    first = client.post("/api/units/move_scout", json={"x": cx + 1, "y": cy, "z": 0})
    assert first.status_code == 200

    second = client.post("/api/units/move_scout", json={"x": cx, "y": cy + 1, "z": 0})
    assert second.status_code == 400
    assert second.get_json()["error"] == "active_order_exists"


def test_tick_executes_move_order(client):
    client.post("/api/register", json={"display_name": "TickRunner"})
    window = client.get("/api/world/window?radius=4&z=0").get_json()
    cx, cy = window["center"]["x"], window["center"]["y"]

    client.post("/api/units/move_scout", json={"x": cx + 1, "y": cy, "z": 0})

    before_tick = client.get("/api/world/window?radius=4&z=0").get_json()
    target_before = None
    for row in before_tick["cells"]:
        for cell in row["row"]:
            if cell["x"] == cx + 1 and cell["y"] == cy:
                target_before = cell
    assert target_before is not None
    assert not any(o["type"] == "fleet" and o["unit_type"] == "scout" for o in target_before["objects"])

    tick = client.post("/api/world/tick")
    assert tick.status_code == 200
    tick_body = tick.get_json()
    assert tick_body["ok"] is True
    assert tick_body["current_tick"] == 1
    assert any(e["type"] == "order_done" for e in tick_body["events"])

    after_tick = client.get("/api/world/window?radius=4&z=0").get_json()
    target_after = None
    for row in after_tick["cells"]:
        for cell in row["row"]:
            if cell["x"] == cx + 1 and cell["y"] == cy:
                target_after = cell
    assert target_after is not None
    assert any(o["type"] == "fleet" and o["unit_type"] == "scout" for o in target_after["objects"])


def test_units_status_switches_idle_moving(client):
    client.post("/api/register", json={"display_name": "UnitStatus"})
    window = client.get("/api/world/window?radius=4&z=0").get_json()
    cx, cy = window["center"]["x"], window["center"]["y"]

    initial = client.get("/api/units/status").get_json()
    scout_initial = next(u for u in initial["units"] if u["unit_type"] == "scout")
    assert scout_initial["status"] == "idle"
    assert scout_initial["active_order"] is None

    client.post("/api/units/move_scout", json={"x": cx + 1, "y": cy, "z": 0})
    moving = client.get("/api/units/status").get_json()
    scout_moving = next(u for u in moving["units"] if u["unit_type"] == "scout")
    assert scout_moving["status"] == "moving"
    assert scout_moving["active_order"] is not None

    client.post("/api/world/tick")
    done = client.get("/api/units/status").get_json()
    scout_done = next(u for u in done["units"] if u["unit_type"] == "scout")
    assert scout_done["status"] == "idle"
    assert scout_done["active_order"] is None


def test_move_scout_invalid_target_fails(client):
    client.post("/api/register", json={"display_name": "BadMove"})
    window = client.get("/api/world/window?radius=4&z=0").get_json()
    cx, cy = window["center"]["x"], window["center"]["y"]

    move = client.post("/api/units/move_scout", json={"x": cx + 2, "y": cy + 2, "z": 0})
    assert move.status_code == 400
    assert move.get_json()["error"] == "target_not_adjacent"


def test_move_scout_unauthorized(client):
    r = client.post("/api/units/move_scout", json={"x": 0, "y": 0, "z": 0})
    assert r.status_code == 401
    assert r.get_json()["error"] == "not_authenticated"
