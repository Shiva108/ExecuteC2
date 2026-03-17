"""Unit tests for the database layer."""

import secrets
import uuid
from datetime import UTC, datetime

import pytest

from executec2.server.database import Database
from executec2.server.models import (
    AgentData,
    AgentMark,
    ChatMessage,
    CredentialData,
    CredentialType,
    DownloadData,
    DownloadState,
    ListenerData,
    ListenerStatus,
    MessageType,
    OSType,
    TargetData,
    TaskData,
    TaskType,
)


@pytest.fixture
async def db(tmp_path):
    database = await Database.create(tmp_path / "test.db")
    yield database
    await database.close()


def make_agent() -> AgentData:
    return AgentData(
        id=secrets.token_hex(4),
        name="python",
        session_key=secrets.token_bytes(32),
        listener="test-listener",
        sleep=60,
        os=OSType.LINUX,
    )


def make_task(agent_id: str) -> TaskData:
    return TaskData(
        task_id=secrets.token_urlsafe(6)[:8],
        agent_id=agent_id,
        command_line="whoami",
        task_type=TaskType.TASK,
    )


# ---------------------------------------------------------------------------
# Schema & WAL
# ---------------------------------------------------------------------------


async def test_wal_mode(db):
    mode = await db.get_journal_mode()
    assert mode == "wal"


async def test_all_tables_created(db):
    tables = await db.table_names()
    expected = {"agents", "tasks", "listeners", "credentials", "targets", "downloads", "chat", "consoles"}
    assert expected.issubset(set(tables))


# ---------------------------------------------------------------------------
# Listener CRUD
# ---------------------------------------------------------------------------


async def test_listener_insert_and_get(db):
    data = ListenerData(
        listener_name="http-01",
        listener_type="http",
        config={"host_bind": "0.0.0.0", "port_bind": 8080},
    )
    await db.listener_insert(data)
    result = await db.listener_get("http-01")
    assert result is not None
    assert result.listener_name == "http-01"
    assert result.listener_type == "http"
    assert result.config["port_bind"] == 8080
    assert result.status == ListenerStatus.STOPPED


async def test_listener_list(db):
    for i in range(3):
        await db.listener_insert(
            ListenerData(listener_name=f"http-{i}", listener_type="http", config={})
        )
    items = await db.listener_list()
    assert len(items) == 3


async def test_listener_update(db):
    await db.listener_insert(
        ListenerData(listener_name="http-01", listener_type="http", config={})
    )
    await db.listener_update("http-01", status=ListenerStatus.RUNNING)
    result = await db.listener_get("http-01")
    assert result.status == ListenerStatus.RUNNING


async def test_listener_delete(db):
    await db.listener_insert(
        ListenerData(listener_name="http-01", listener_type="http", config={})
    )
    await db.listener_delete("http-01")
    assert await db.listener_get("http-01") is None


# ---------------------------------------------------------------------------
# Agent CRUD
# ---------------------------------------------------------------------------


async def test_agent_insert_and_get(db):
    agent = make_agent()
    await db.agent_insert(agent)
    result = await db.agent_get(agent.id)
    assert result is not None
    assert result.id == agent.id
    assert result.session_key == agent.session_key
    assert result.os == OSType.LINUX
    assert result.mark == AgentMark.ACTIVE


async def test_agent_list(db):
    for _ in range(3):
        await db.agent_insert(make_agent())
    agents = await db.agent_list()
    assert len(agents) == 3


async def test_agent_update_mark(db):
    agent = make_agent()
    await db.agent_insert(agent)
    await db.agent_update(agent.id, mark=AgentMark.INACTIVE)
    result = await db.agent_get(agent.id)
    assert result.mark == AgentMark.INACTIVE


async def test_agent_update_last_tick(db):
    agent = make_agent()
    await db.agent_insert(agent)
    new_tick = datetime.now(UTC)
    await db.agent_update(agent.id, last_tick=new_tick)
    result = await db.agent_get(agent.id)
    assert abs((result.last_tick - new_tick).total_seconds()) < 2


async def test_agent_delete(db):
    agent = make_agent()
    await db.agent_insert(agent)
    await db.agent_delete(agent.id)
    assert await db.agent_get(agent.id) is None


# ---------------------------------------------------------------------------
# Task CRUD + cascade
# ---------------------------------------------------------------------------


async def test_task_insert_and_get(db):
    agent = make_agent()
    await db.agent_insert(agent)
    task = make_task(agent.id)
    await db.task_insert(task)
    result = await db.task_get(task.task_id)
    assert result is not None
    assert result.task_id == task.task_id
    assert result.command_line == "whoami"
    assert result.completed is False


async def test_task_list(db):
    agent = make_agent()
    await db.agent_insert(agent)
    for _ in range(4):
        await db.task_insert(make_task(agent.id))
    tasks = await db.task_list(agent.id)
    assert len(tasks) == 4


async def test_task_update_completed(db):
    agent = make_agent()
    await db.agent_insert(agent)
    task = make_task(agent.id)
    await db.task_insert(task)
    await db.task_update(task.task_id, completed=True, message="output here",
                          message_type=MessageType.SUCCESS)
    result = await db.task_get(task.task_id)
    assert result.completed is True
    assert result.message == "output here"


async def test_task_delete(db):
    agent = make_agent()
    await db.agent_insert(agent)
    task = make_task(agent.id)
    await db.task_insert(task)
    await db.task_delete(task.task_id)
    assert await db.task_get(task.task_id) is None


async def test_cascade_delete_agent_deletes_tasks(db):
    agent = make_agent()
    await db.agent_insert(agent)
    task = make_task(agent.id)
    await db.task_insert(task)
    await db.agent_delete(agent.id)
    assert await db.task_get(task.task_id) is None


# ---------------------------------------------------------------------------
# Credential CRUD
# ---------------------------------------------------------------------------


async def test_credential_insert_and_get(db):
    cred = CredentialData(
        cred_id=uuid.uuid4().hex,
        username="administrator",
        secret="plaintext-secret",
        realm="CORP",
        cred_type=CredentialType.PASSWORD,
    )
    secret_blob = b"encrypted-blob"
    await db.credential_insert(cred, secret_blob)
    result, blob = await db.credential_get(cred.cred_id)
    assert result.username == "administrator"
    assert blob == secret_blob


async def test_credential_list(db):
    for i in range(3):
        cred = CredentialData(cred_id=uuid.uuid4().hex, username=f"user{i}")
        await db.credential_insert(cred, b"blob")
    items = await db.credential_list()
    assert len(items) == 3


async def test_credential_delete(db):
    cred = CredentialData(cred_id=uuid.uuid4().hex, username="test")
    await db.credential_insert(cred, b"blob")
    await db.credential_delete(cred.cred_id)
    assert await db.credential_get(cred.cred_id) is None


# ---------------------------------------------------------------------------
# Target CRUD
# ---------------------------------------------------------------------------


async def test_target_insert_and_get(db):
    target = TargetData(
        target_id=uuid.uuid4().hex,
        computer="WORKSTATION01",
        domain="CORP",
        address="192.168.1.50",
    )
    await db.target_insert(target)
    result = await db.target_get(target.target_id)
    assert result.computer == "WORKSTATION01"
    assert result.alive is True


async def test_target_update_agents(db):
    target = TargetData(target_id=uuid.uuid4().hex, computer="DC01")
    await db.target_insert(target)
    await db.target_update(target.target_id, agents=["abc12345"])
    result = await db.target_get(target.target_id)
    assert "abc12345" in result.agents


async def test_target_delete(db):
    target = TargetData(target_id=uuid.uuid4().hex)
    await db.target_insert(target)
    await db.target_delete(target.target_id)
    assert await db.target_get(target.target_id) is None


# ---------------------------------------------------------------------------
# Download CRUD + cascade
# ---------------------------------------------------------------------------


async def test_download_insert_and_get(db):
    agent = make_agent()
    await db.agent_insert(agent)
    dl = DownloadData(
        file_id=uuid.uuid4().hex,
        agent_id=agent.id,
        remote_path="/tmp/secret.txt",
    )
    await db.download_insert(dl)
    result = await db.download_get(dl.file_id)
    assert result.remote_path == "/tmp/secret.txt"
    assert result.state == DownloadState.IN_PROGRESS


async def test_download_cascade_delete(db):
    agent = make_agent()
    await db.agent_insert(agent)
    dl = DownloadData(file_id=uuid.uuid4().hex, agent_id=agent.id, remote_path="/tmp/x")
    await db.download_insert(dl)
    await db.agent_delete(agent.id)
    assert await db.download_get(dl.file_id) is None


# ---------------------------------------------------------------------------
# Chat CRUD
# ---------------------------------------------------------------------------


async def test_chat_insert_and_list(db):
    await db.chat_insert(ChatMessage(username="admin", message="hello team"))
    await db.chat_insert(ChatMessage(username="operator1", message="acknowledged"))
    msgs = await db.chat_list()
    assert len(msgs) == 2
    assert msgs[0].message == "hello team"
    assert msgs[1].username == "operator1"


# ---------------------------------------------------------------------------
# Console CRUD + cascade
# ---------------------------------------------------------------------------


async def test_console_insert_list_clear(db):
    agent = make_agent()
    await db.agent_insert(agent)
    await db.console_insert(agent.id, b"\x01\x02\x03")
    await db.console_insert(agent.id, b"\x04\x05\x06")
    packets = await db.console_list(agent.id)
    assert len(packets) == 2
    assert packets[0] == b"\x01\x02\x03"
    await db.console_clear(agent.id)
    assert await db.console_list(agent.id) == []


async def test_console_cascade_delete(db):
    agent = make_agent()
    await db.agent_insert(agent)
    await db.console_insert(agent.id, b"data")
    await db.agent_delete(agent.id)
    assert await db.console_list(agent.id) == []
