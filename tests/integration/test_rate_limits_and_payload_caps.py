"""Integration tests for route rate limits and task payload caps."""

import base64
import secrets

import pytest
from httpx import ASGITransport, AsyncClient

from executec2.agents.python_agent import PythonAgentPlugin
from executec2.config.schema import ExecuteC2Config, ServerConfig
from executec2.server.app import create_app, init_app_state, teardown_app_state
from executec2.server.auth import RateLimiter
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
            max_task_payload_bytes=1024,
        ),
        operators={"admin": "adminpass"},
    )


@pytest.fixture
async def auth_client(tmp_path):
    config = make_config(tmp_path)
    app = create_app(config)
    await init_app_state(app, config)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            login = await c.post(
                "/api/auth/login",
                json={"username": "admin", "password": "adminpass"},
            )
            token = login.json()["access_token"]
            c.headers["Authorization"] = f"Bearer {token}"
            yield c, app.state
    finally:
        await teardown_app_state(app)


async def _insert_agent(state) -> str:
    agent_id = secrets.token_hex(4)
    data = AgentData(
        id=agent_id,
        name="python",
        session_key=secrets.token_bytes(32),
        listener="http",
        sleep=60,
        os=OSType.LINUX,
    )
    await state.db.agent_insert(data)
    return agent_id


async def test_raw_task_payload_cap_enforced(auth_client):
    client, state = auth_client
    agent_id = await _insert_agent(state)
    body = {"data": base64.b64encode(b"A" * 2048).decode()}

    resp = await client.post(f"/api/agents/{agent_id}/commands/raw", json=body)
    assert resp.status_code == 413


async def test_normal_task_payload_cap_enforced(auth_client, monkeypatch):
    client, state = auth_client
    agent_id = await _insert_agent(state)
    monkeypatch.setattr("executec2.agents.get_agent_class", lambda _name: PythonAgentPlugin)
    body = {"command": "shell", "args": {"command": "A" * 4096}}

    resp = await client.post(f"/api/agents/{agent_id}/commands", json=body)
    assert resp.status_code == 413


async def test_raw_command_rate_limit_returns_429_with_error_code(auth_client):
    client, state = auth_client
    agent_id = await _insert_agent(state)
    state.route_limiters["raw_command"] = RateLimiter(max_requests=1)

    first = await client.post(f"/api/agents/{agent_id}/commands/raw", json={"data": "not-base64"})
    assert first.status_code == 422

    second = await client.post(f"/api/agents/{agent_id}/commands/raw", json={"data": "not-base64"})
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED"


async def test_listener_create_rate_limit_returns_429(auth_client):
    client, state = auth_client
    state.route_limiters["listener_mutation"] = RateLimiter(max_requests=1)

    first = await client.post("/api/listeners", json={})
    assert first.status_code == 400

    second = await client.post("/api/listeners", json={})
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED"
