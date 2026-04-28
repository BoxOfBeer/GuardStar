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

    # Для z!=0 планет нет, но terrain/glyph должен быть.
    any_cell = w1["cells"][0]["row"][0]
    assert "terrain" in any_cell
    assert "glyph" in any_cell

