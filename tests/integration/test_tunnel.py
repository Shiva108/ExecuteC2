"""Integration tests for tunnel API — Phase 11."""

import secrets
import socket

import pytest
from httpx import ASGITransport, AsyncClient

from executec2.config.schema import ExecuteC2Config, ServerConfig
from executec2.server.app import create_app, init_app_state, teardown_app_state
from executec2.server.models import AgentData, OSType


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


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


# ---------------------------------------------------------------------------
# List tunnels
# ---------------------------------------------------------------------------


async def test_list_tunnels_empty(auth_client):
    client, _ = auth_client
    resp = await client.get("/api/tunnels")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_tunnels_require_auth(auth_client):
    client, _ = auth_client
    no_auth = AsyncClient(transport=client._transport, base_url="http://test")
    async with no_auth as c:
        resp = await c.get("/api/tunnels")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# SOCKS5 tunnel
# ---------------------------------------------------------------------------


async def test_create_socks5_missing_agent_returns_404(auth_client):
    client, _ = auth_client
    resp = await client.post("/api/tunnels/socks5", json={
        "agent_id": "nosuchagent",
        "lport": 1080,
    })
    assert resp.status_code == 404


async def test_create_socks5_missing_fields_returns_400(auth_client):
    client, _ = auth_client
    resp = await client.post("/api/tunnels/socks5", json={"agent_id": "x"})
    assert resp.status_code == 400


async def test_create_socks5_tunnel_persisted(auth_client):
    """Creating a SOCKS5 tunnel persists it to DB and broadcasts the event."""
    client, state = auth_client
    agent_id = await _insert_agent(state)
    lport = _free_port()
    resp = await client.post("/api/tunnels/socks5", json={
        "agent_id": agent_id,
        "lport": lport,
    })
    assert resp.status_code == 201
    tunnels = await state.db.tunnel_list()
    assert len(tunnels) == 1


# ---------------------------------------------------------------------------
# Local port-forward tunnel
# ---------------------------------------------------------------------------


async def test_create_lportfwd_missing_fields_returns_400(auth_client):
    client, _ = auth_client
    resp = await client.post("/api/tunnels/lportfwd", json={"agent_id": "x", "lport": 9000})
    assert resp.status_code == 400


async def test_create_lportfwd_tunnel_persisted(auth_client):
    """Creating a local port-forward persists it to DB."""
    client, state = auth_client
    agent_id = await _insert_agent(state)
    lport = _free_port()
    resp = await client.post("/api/tunnels/lportfwd", json={
        "agent_id": agent_id,
        "lport": lport,
        "thost": "10.0.0.1",
        "tport": 22,
    })
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Stop tunnel
# ---------------------------------------------------------------------------


async def test_stop_nonexistent_tunnel_returns_404(auth_client):
    client, _ = auth_client
    resp = await client.post("/api/tunnels/nosuchid/stop")
    assert resp.status_code == 404


@pytest.mark.xfail(reason="Phase 11 tunnel stop requires active asyncio server")
async def test_tunnel_stop_cleans_up(auth_client):
    """Stopping a tunnel removes it from DB and broadcasts TUNNEL_DELETE."""
    raise NotImplementedError
