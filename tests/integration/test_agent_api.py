"""Integration tests for agent API routes."""

import pytest
from httpx import ASGITransport, AsyncClient

from executec2.config.schema import ExecuteC2Config, ServerConfig
from executec2.server.app import create_app, init_app_state, teardown_app_state
from executec2.server.models import AgentData, OSType


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


async def get_token(app, c) -> str:
    resp = await c.post("/api/auth/login", json={"username": "alice", "password": "secret"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def insert_agent(app, agent_id: str = "aabbccdd") -> AgentData:
    import os
    data = AgentData(
        id=agent_id,
        name="python",
        session_key=os.urandom(32),
        listener="test",
        external_ip="1.2.3.4",
        internal_ip="10.0.0.1",
        sleep=30,
        os=OSType.LINUX,
        os_desc="Linux",
        arch="x64",
        computer="box",
        username="user",
    )
    await app.state.db.agent_insert(data)
    return data


async def test_list_agents_empty(client):
    app, c = client
    token = await get_token(app, c)
    resp = await c.get("/api/agents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_agents_with_data(client):
    app, c = client
    token = await get_token(app, c)
    await insert_agent(app)
    resp = await c.get("/api/agents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["id"] == "aabbccdd"


async def test_delete_agent(client):
    app, c = client
    token = await get_token(app, c)
    await insert_agent(app)
    resp = await c.delete("/api/agents/aabbccdd", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 204

    # Verify gone
    resp2 = await c.get("/api/agents", headers={"Authorization": f"Bearer {token}"})
    assert resp2.json() == []


async def test_delete_nonexistent_agent(client):
    app, c = client
    token = await get_token(app, c)
    resp = await c.delete("/api/agents/notexist", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


async def test_set_tag(client):
    app, c = client
    token = await get_token(app, c)
    await insert_agent(app)
    resp = await c.put("/api/agents/aabbccdd/tag",
                       json={"tag": "important"},
                       headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 204

    # Verify tag updated in DB
    agent = await app.state.db.agent_get("aabbccdd")
    assert agent.tags == "important"


async def test_set_mark(client):
    app, c = client
    token = await get_token(app, c)
    await insert_agent(app)
    resp = await c.put("/api/agents/aabbccdd/mark",
                       json={"mark": "inactive"},
                       headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 204


async def test_set_color(client):
    app, c = client
    token = await get_token(app, c)
    await insert_agent(app)
    resp = await c.put("/api/agents/aabbccdd/color",
                       json={"color": "#ff0000"},
                       headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 204


async def test_list_tasks_empty(client):
    app, c = client
    token = await get_token(app, c)
    await insert_agent(app)
    resp = await c.get("/api/agents/aabbccdd/tasks",
                       headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_agents_require_auth(client):
    _, c = client
    resp = await c.get("/api/agents")
    assert resp.status_code == 401
