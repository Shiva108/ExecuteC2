"""Integration tests for role-based authorization."""

import os

import pytest
from httpx import ASGITransport, AsyncClient

from executec2.config.schema import ExecuteC2Config, ServerConfig
from executec2.server.app import create_app, init_app_state, teardown_app_state
from executec2.server.models import AgentData, OSType


def make_config(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("fake")
    key.write_text("fake")
    return ExecuteC2Config(
        server=ServerConfig(
            admin_bind_host="127.0.0.1",
            port=4321,
            data_dir=tmp_path / "data",
            tls_cert=cert,
            tls_key=key,
        ),
        operators={
            "view": {"password": "viewpass", "roles": ["viewer"]},
            "op": {"password": "oppass", "roles": ["operator"]},
            "admin": {"password": "adminpass", "roles": ["admin"]},
        },
    )


@pytest.fixture
async def client(tmp_path):
    config = make_config(tmp_path)
    app = create_app(config)
    await init_app_state(app, config)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c, app.state
    finally:
        await teardown_app_state(app)


async def _token(c: AsyncClient, username: str, password: str) -> str:
    resp = await c.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def _insert_agent(state, agent_id: str = "aabbccdd") -> None:
    data = AgentData(
        id=agent_id,
        name="python",
        session_key=os.urandom(32),
        listener="test",
        external_ip="1.2.3.4",
        internal_ip="10.0.0.1",
        sleep=30,
        os=OSType.LINUX,
    )
    await state.db.agent_insert(data)


async def test_viewer_read_only(client):
    c, _state = client
    token = await _token(c, "view", "viewpass")
    headers = {"Authorization": f"Bearer {token}"}

    resp = await c.get("/api/agents", headers=headers)
    assert resp.status_code == 200

    resp = await c.post(
        "/api/listeners",
        headers=headers,
        json={"listener_type": "http", "listener_name": "l1", "config": {}},
    )
    assert resp.status_code == 403


async def test_operator_cannot_use_admin_endpoints(client):
    c, state = client
    token = await _token(c, "op", "oppass")
    headers = {"Authorization": f"Bearer {token}"}
    await _insert_agent(state)

    resp = await c.delete("/api/agents/aabbccdd", headers=headers)
    assert resp.status_code == 403

    resp = await c.post("/api/agents/aabbccdd/commands/raw", headers=headers, json={"data": "AQID"})
    assert resp.status_code == 403

    resp = await c.post(
        "/api/agents/aabbccdd/commands",
        headers=headers,
        json={"command": "upload", "args": {"path": "/tmp/a", "data": "x"}},
    )
    assert resp.status_code == 403


async def test_admin_can_delete_agent(client):
    c, state = client
    token = await _token(c, "admin", "adminpass")
    headers = {"Authorization": f"Bearer {token}"}
    await _insert_agent(state)

    resp = await c.delete("/api/agents/aabbccdd", headers=headers)
    assert resp.status_code == 204
