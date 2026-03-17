"""Integration tests for task lifecycle via REST API — Phase 10."""

import secrets

import pytest
from httpx import ASGITransport, AsyncClient

from executec2.config.schema import ExecuteC2Config, ServerConfig
from executec2.server.app import create_app, init_app_state, teardown_app_state
from executec2.server.models import AgentData, OSType, TaskData, TaskType


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
    """Helper: insert a test agent directly into the DB."""
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


async def _insert_task(state, agent_id: str) -> str:
    """Helper: insert a test task directly into the DB."""
    task_id = secrets.token_hex(4)
    task = TaskData(task_id=task_id, agent_id=agent_id, task_type=TaskType.TASK)
    await state.db.task_insert(task)
    return task_id


# ---------------------------------------------------------------------------
# Task cancellation via REST
# ---------------------------------------------------------------------------


async def test_cancel_task_marks_completed(auth_client):
    client, state = auth_client
    agent_id = await _insert_agent(state)
    task_id = await _insert_task(state, agent_id)

    resp = await client.post(f"/api/agents/{agent_id}/tasks/{task_id}/cancel")
    assert resp.status_code == 204

    task = await state.db.task_get(task_id)
    assert task.completed is True


async def test_cancel_nonexistent_task_returns_404(auth_client):
    client, state = auth_client
    agent_id = await _insert_agent(state)
    resp = await client.post(f"/api/agents/{agent_id}/tasks/nosuchid/cancel")
    assert resp.status_code == 404


async def test_cancel_already_completed_task_returns_409(auth_client):
    client, state = auth_client
    agent_id = await _insert_agent(state)
    task_id = await _insert_task(state, agent_id)
    await state.db.task_update(task_id, completed=True)

    resp = await client.post(f"/api/agents/{agent_id}/tasks/{task_id}/cancel")
    assert resp.status_code == 409


async def test_delete_task(auth_client):
    client, state = auth_client
    agent_id = await _insert_agent(state)
    task_id = await _insert_task(state, agent_id)

    resp = await client.delete(f"/api/agents/{agent_id}/tasks/{task_id}")
    assert resp.status_code == 204

    assert await state.db.task_get(task_id) is None


@pytest.mark.xfail(reason="Phase 10 task type routing not yet exposed via REST")
async def test_task_type_routing_via_api(auth_client):
    """TASK/JOB/TUNNEL tasks are dispatched to the correct internal queues."""
    raise NotImplementedError


@pytest.mark.xfail(reason="Phase 10 job progress events not yet implemented")
async def test_job_progress_updates_via_websocket(auth_client):
    """JOB tasks emit AGENT_TASK_UPDATE packets as progress arrives."""
    raise NotImplementedError
