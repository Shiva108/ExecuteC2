"""Unit tests for target routes (CRUD)."""

import pytest
from httpx import ASGITransport, AsyncClient

from executec2.config.schema import ExecuteC2Config, ServerConfig
from executec2.server.app import create_app, init_app_state, teardown_app_state


def make_config(tmp_path) -> ExecuteC2Config:
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("fake")
    key.write_text("fake")
    return ExecuteC2Config(
        server=ServerConfig(
            host="127.0.0.1",
            port=8000,
            data_dir=tmp_path / "data",
            tls_cert=cert,
            tls_key=key,
        ),
        operators={"alice": "secret"},
    )


@pytest.fixture
async def client(tmp_path):
    config = make_config(tmp_path)
    app = create_app(config)
    await init_app_state(app, config)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield app, c
    await teardown_app_state(app)


async def get_token(c) -> str:
    resp = await c.post("/api/auth/login", json={"username": "alice", "password": "secret"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def test_list_targets_empty(client):
    app, c = client
    token = await get_token(c)
    resp = await c.get("/api/targets", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_target(client):
    app, c = client
    token = await get_token(c)
    resp = await c.post("/api/targets",
                        json={
                            "computer": "WIN-DC01",
                            "domain": "CORP",
                            "address": "10.0.0.1",
                            "os": "Windows",
                        },
                        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["computer"] == "WIN-DC01"
    assert "target_id" in data


async def test_create_and_list_target(client):
    app, c = client
    token = await get_token(c)
    await c.post("/api/targets",
                 json={"computer": "SERVER01", "address": "192.168.1.1"},
                 headers={"Authorization": f"Bearer {token}"})

    resp = await c.get("/api/targets", headers={"Authorization": f"Bearer {token}"})
    items = resp.json()
    assert len(items) == 1
    assert items[0]["computer"] == "SERVER01"


async def test_update_target(client):
    app, c = client
    token = await get_token(c)
    resp = await c.post("/api/targets",
                        json={"computer": "BOX", "address": "10.0.0.2"},
                        headers={"Authorization": f"Bearer {token}"})
    target_id = resp.json()["target_id"]

    upd = await c.put(f"/api/targets/{target_id}",
                      json={"info": "Domain controller"},
                      headers={"Authorization": f"Bearer {token}"})
    assert upd.status_code == 200


async def test_update_nonexistent_target(client):
    app, c = client
    token = await get_token(c)
    resp = await c.put("/api/targets/nonexistent",
                       json={"info": "test"},
                       headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


async def test_delete_target(client):
    app, c = client
    token = await get_token(c)
    resp = await c.post("/api/targets",
                        json={"computer": "VICTIM"},
                        headers={"Authorization": f"Bearer {token}"})
    target_id = resp.json()["target_id"]

    del_resp = await c.delete(f"/api/targets/{target_id}",
                               headers={"Authorization": f"Bearer {token}"})
    assert del_resp.status_code == 204

    list_resp = await c.get("/api/targets", headers={"Authorization": f"Bearer {token}"})
    assert list_resp.json() == []


async def test_delete_nonexistent_target(client):
    app, c = client
    token = await get_token(c)
    resp = await c.delete("/api/targets/nonexistent",
                           headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


async def test_tag_target(client):
    app, c = client
    token = await get_token(c)
    resp = await c.post("/api/targets",
                        json={"computer": "TAGGED"},
                        headers={"Authorization": f"Bearer {token}"})
    target_id = resp.json()["target_id"]

    tag_resp = await c.put(f"/api/targets/{target_id}/tag",
                            json={"tag": "high-value"},
                            headers={"Authorization": f"Bearer {token}"})
    assert tag_resp.status_code == 204


async def test_targets_require_auth(client):
    _, c = client
    resp = await c.get("/api/targets")
    assert resp.status_code == 401
