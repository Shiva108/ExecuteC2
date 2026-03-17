"""Integration tests for agent check-in flow — Phase 9.

The HTTP check-in endpoint (POST /agent/<listener_name>) is served by the
listener plugin, not the teamserver REST API.  These tests verify the full
registration + task-dispatch loop through an in-process ASGI client.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from executec2.config.schema import ExecuteC2Config, ServerConfig
from executec2.server.app import create_app, init_app_state, teardown_app_state


def make_config(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("fake")
    key.write_text("fake")
    return ExecuteC2Config(
        server=ServerConfig(
            host="127.0.0.1",
            port=4321,
            data_dir=tmp_path / "data",
            tls_cert=cert,
            tls_key=key,
        ),
        operators={"admin": "password123"},
    )


@pytest.fixture
async def auth_client(tmp_path):
    config = make_config(tmp_path)
    app = create_app(config)
    await init_app_state(app, config)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            login = await c.post("/api/auth/login", json={"username": "admin", "password": "password123"})
            token = login.json()["access_token"]
            c.headers["Authorization"] = f"Bearer {token}"
            yield c, app.state
    finally:
        await teardown_app_state(app)


@pytest.mark.xfail(reason="Phase 9 agent HTTP check-in endpoint not yet implemented")
async def test_agent_registration_flow(auth_client):
    """Agent registers via POST /agent/<listener>; appears in agent list."""
    client, state = auth_client
    # Start an HTTP listener first
    resp = await client.post("/api/listeners", json={
        "name": "http1",
        "type": "http",
        "config": {"host": "0.0.0.0", "port": 8080, "master_key": "a" * 64},
    })
    assert resp.status_code == 201

    # Simulated encrypted agent check-in (implementation-specific payload)
    resp = await client.post("/agent/http1", content=b"\x00" * 32,
                             headers={"Content-Type": "application/octet-stream"})
    # Should produce a 200 or 204 (not 404)
    assert resp.status_code not in (404, 500)

    # Agent should appear in the list
    agents = await client.get("/api/agents")
    assert len(agents.json()) >= 1


@pytest.mark.xfail(reason="Phase 9 agent HTTP check-in endpoint not yet implemented")
async def test_agent_receives_and_executes_task(auth_client):
    """After registration, a dispatched command is returned on next check-in."""
    raise NotImplementedError("Phase 9 not yet implemented")


@pytest.mark.xfail(reason="Phase 9 agent HTTP check-in endpoint not yet implemented")
async def test_agent_exponential_backoff(auth_client):
    """Agent connector doubles sleep on HTTP errors up to the configured cap."""
    raise NotImplementedError("Phase 9 not yet implemented")


@pytest.mark.xfail(reason="Phase 9 agent HTTP check-in endpoint not yet implemented")
async def test_kill_date_terminates_agent(auth_client):
    """An agent with an elapsed kill_date self-terminates on check-in."""
    raise NotImplementedError("Phase 9 not yet implemented")
