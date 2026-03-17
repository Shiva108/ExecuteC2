"""Integration tests for listener API routes."""

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
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def test_list_listeners_empty(client):
    app, c = client
    token = await get_token(c)
    resp = await c.get("/api/listeners", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_listener_missing_type(client):
    app, c = client
    token = await get_token(c)
    resp = await c.post("/api/listeners",
                        json={"listener_name": "test"},
                        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 400


async def test_create_listener_unknown_type(client):
    app, c = client
    token = await get_token(c)
    resp = await c.post("/api/listeners",
                        json={"listener_type": "nonexistent", "listener_name": "test", "config": {}},
                        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 400


async def test_stop_nonexistent_listener(client):
    app, c = client
    token = await get_token(c)
    resp = await c.post("/api/listeners/nonexistent/stop",
                        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


async def test_pause_nonexistent_listener(client):
    app, c = client
    token = await get_token(c)
    resp = await c.post("/api/listeners/nonexistent/pause",
                        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


async def test_resume_nonexistent_listener(client):
    app, c = client
    token = await get_token(c)
    resp = await c.post("/api/listeners/nonexistent/resume",
                        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


async def test_update_nonexistent_listener(client):
    app, c = client
    token = await get_token(c)
    resp = await c.put("/api/listeners/nonexistent",
                       json={"config": {}},
                       headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


async def test_listeners_require_auth(client):
    _, c = client
    resp = await c.get("/api/listeners")
    assert resp.status_code == 401
