"""Unit tests for agent lifecycle, TeamserverCore, and PythonAgentPlugin."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from executec2.agents.python_agent import PythonAgentPlugin
from executec2.server.models import AgentMark, TaskData

# ---------------------------------------------------------------------------
# PythonAgentPlugin
# ---------------------------------------------------------------------------


def test_plugin_info():
    plugin = PythonAgentPlugin()
    info = plugin.get_info()
    assert info["name"] == "python"
    assert info["watermark"] == "py01c2e0"
    assert "http" in info["compatible_listeners"]


def test_get_commands_returns_19():
    plugin = PythonAgentPlugin()
    cmds = plugin.get_commands()
    assert len(cmds) == 19
    names = {c["name"] for c in cmds}
    assert "shell" in names
    assert "exit" in names
    assert "upload" in names
    assert "download" in names


def test_parse_beat():
    plugin = PythonAgentPlugin()
    beat = {
        "hostname": "WIN-BOX",
        "username": "alice",
        "domain": "CORP",
        "internal_ip": "10.0.0.5",
        "os": 1,
        "os_desc": "Windows 10",
        "arch": "x64",
        "pid": 1234,
        "process": "python.exe",
        "elevated": True,
        "sleep": 30,
        "jitter": 10,
    }
    result = plugin.parse_beat(beat)
    assert result["computer"] == "WIN-BOX"
    assert result["username"] == "alice"
    assert result["elevated"] is True
    assert result["sleep"] == 30


def test_build_task_known_command():
    plugin = PythonAgentPlugin()
    task = plugin.build_task("shell", {"command": "whoami"})
    assert task["cmd"] == 50
    assert task["args"] == {"command": "whoami"}
    assert task["type"] == 0  # TaskType.TASK


def test_build_task_unknown_command():
    plugin = PythonAgentPlugin()
    with pytest.raises(ValueError, match="Unknown command"):
        plugin.build_task("nonexistent", {})


def test_process_response_success():
    plugin = PythonAgentPlugin()
    result = plugin.process_response("task1", {"status": 1, "output": b"root\n", "error": ""})
    assert result["completed"] is True
    assert result["message"] == "root\n"
    assert result["message_type"] == 1  # SUCCESS


def test_process_response_error():
    plugin = PythonAgentPlugin()
    result = plugin.process_response("task1", {"status": 2, "output": b"", "error": "not found"})
    assert result["completed"] is True
    assert result["message"] == "not found"
    assert result["message_type"] == 2  # ERROR


def test_process_response_in_progress():
    plugin = PythonAgentPlugin()
    result = plugin.process_response("task1", {"status": 0, "output": b"running...", "error": ""})
    assert result["completed"] is False
    assert result["message_type"] == 0  # INFO


# ---------------------------------------------------------------------------
# Agent plugin loader
# ---------------------------------------------------------------------------


def test_agent_plugin_loader():
    from executec2.agents import get_agent_class, load_agents
    load_agents(["executec2.agents.python_agent"])
    cls = get_agent_class("python")
    assert cls is PythonAgentPlugin
    cls2 = get_agent_class("py01c2e0")
    assert cls2 is PythonAgentPlugin


# ---------------------------------------------------------------------------
# TeamserverCore
# ---------------------------------------------------------------------------


@pytest.fixture
async def teamserver_fixture():
    """Build a TeamserverCore with mock dependencies."""
    # Use an in-memory database

    from executec2.server.broker import MessageBroker
    from executec2.server.database import Database
    from executec2.server.events import EventManager
    from executec2.server.teamserver import TeamserverCore
    db = await Database.create(":memory:")
    broker = MessageBroker()
    await broker.start()
    event_manager = EventManager()
    await event_manager.start()
    agents = {}

    core = TeamserverCore(db=db, broker=broker, event_manager=event_manager, agents=agents)
    core.register_agent_plugin("python", PythonAgentPlugin())
    core.register_listener_master_key("test-listener", b"\x11" * 32)
    await core.start()

    yield core, agents

    await core.stop()
    await broker.stop()
    await event_manager.stop()
    await db.close()


async def test_agent_checkin_new(teamserver_fixture):
    core, agents = teamserver_fixture
    beat = {
        "hostname": "BOX", "username": "user", "domain": "", "internal_ip": "10.0.0.1",
        "os": 2, "os_desc": "Linux", "arch": "x64", "pid": 100,
        "process": "python3", "elevated": False, "sleep": 5, "jitter": 0, "ctr": 1,
    }
    await core.agent_checkin("aabbccdd", "python", beat, "192.168.1.1", "test-listener")

    assert "aabbccdd" in agents
    assert agents["aabbccdd"].data.computer == "BOX"
    assert agents["aabbccdd"].data.username == "user"


async def test_agent_checkin_updates_tick(teamserver_fixture):
    core, agents = teamserver_fixture
    beat = {
        "hostname": "BOX", "username": "user", "domain": "", "internal_ip": "10.0.0.1",
        "os": 2, "os_desc": "Linux", "arch": "x64", "pid": 100,
        "process": "python3", "elevated": False, "sleep": 5, "jitter": 0, "ctr": 1,
    }
    beat["ctr"] = 2
    await core.agent_checkin("aabbccdd", "python", beat, "", "test-listener")
    first_tick = agents["aabbccdd"].data.last_tick

    await asyncio.sleep(0.01)
    await core.agent_checkin("aabbccdd", "python", beat, "", "test-listener")
    second_tick = agents["aabbccdd"].data.last_tick

    assert second_tick >= first_tick


async def test_agent_checkin_refreshes_sleep_and_jitter(teamserver_fixture):
    core, agents = teamserver_fixture
    register = {
        "hostname": "BOX",
        "username": "user",
        "domain": "",
        "internal_ip": "10.0.0.1",
        "os": 2,
        "os_desc": "Linux",
        "arch": "x64",
        "pid": 100,
        "process": "python3",
        "elevated": False,
        "sleep": 5,
        "jitter": 0,
        "ctr": 1,
    }
    await core.agent_checkin("aabbccdd", "python", register, "", "test-listener")

    heartbeat = {"ctr": 2, "sleep": 30, "jitter": 15}
    await core.agent_checkin("aabbccdd", "python", heartbeat, "", "test-listener")

    assert agents["aabbccdd"].data.sleep == 30
    assert agents["aabbccdd"].data.jitter == 15


async def test_agent_checkin_unknown_type(teamserver_fixture):
    core, agents = teamserver_fixture
    # Should not raise, just log a warning
    await core.agent_checkin("deadbeef", "unknown_type", {}, "", "test-listener")
    assert "deadbeef" not in agents


async def test_get_pending_tasks_empty(teamserver_fixture):
    core, agents = teamserver_fixture
    beat = {
        "hostname": "BOX", "username": "user", "domain": "", "internal_ip": "10.0.0.1",
        "os": 2, "os_desc": "Linux", "arch": "x64", "pid": 100,
        "process": "python3", "elevated": False, "sleep": 5, "jitter": 0, "ctr": 1,
    }
    await core.agent_checkin("aabbccdd", "python", beat, "", "test-listener")
    tasks = await core.agent_get_pending_tasks("aabbccdd")
    assert tasks == []


async def test_get_pending_tasks_unknown_agent(teamserver_fixture):
    core, _ = teamserver_fixture
    tasks = await core.agent_get_pending_tasks("unknown")
    assert tasks == []


async def test_submit_results_updates_task(teamserver_fixture):
    core, _ = teamserver_fixture
    beat = {
        "hostname": "BOX",
        "username": "user",
        "domain": "",
        "internal_ip": "10.0.0.1",
        "os": 2,
        "os_desc": "Linux",
        "arch": "x64",
        "pid": 100,
        "process": "python3",
        "elevated": False,
        "sleep": 5,
        "jitter": 0,
        "ctr": 1,
    }
    await core.agent_checkin("aabbccdd", "python", beat, "", "test-listener")
    task = TaskData(task_id="task1234", agent_id="aabbccdd")
    await core._db.task_insert(task)

    await core.submit_results(
        "aabbccdd",
        [{"task_id": "task1234", "payload": {"status": 1, "output": b"ok", "error": ""}}],
    )

    updated = await core._db.task_get("task1234")
    assert updated is not None
    assert updated.completed is True
    assert updated.message == "ok"


async def test_get_session_key(teamserver_fixture):
    core, agents = teamserver_fixture
    beat = {
        "hostname": "BOX", "username": "user", "domain": "", "internal_ip": "10.0.0.1",
        "os": 2, "os_desc": "Linux", "arch": "x64", "pid": 100,
        "process": "python3", "elevated": False, "sleep": 5, "jitter": 0, "ctr": 1,
    }
    await core.agent_checkin("aabbccdd", "python", beat, "", "test-listener")
    key = await core.get_session_key("aabbccdd")
    assert len(key) == 32


async def test_get_session_key_unknown_agent(teamserver_fixture):
    core, _ = teamserver_fixture
    key = await core.get_session_key("unknown")
    assert key == b"\x00" * 32


async def test_agent_marked_inactive_after_threshold(teamserver_fixture):
    """Agent should be marked inactive when last_tick exceeds 3× sleep."""
    core, agents = teamserver_fixture
    beat = {
        "hostname": "BOX", "username": "user", "domain": "", "internal_ip": "10.0.0.1",
        "os": 2, "os_desc": "Linux", "arch": "x64", "pid": 100,
        "process": "python3", "elevated": False, "sleep": 1, "jitter": 0, "ctr": 1,
    }
    await core.agent_checkin("aabbccdd", "python", beat, "", "test-listener")

    # Simulate old last_tick
    agents["aabbccdd"].data.last_tick = datetime.now(UTC) - timedelta(seconds=10)

    # Wait for tick updater to run (interval is 0.8s)
    await asyncio.sleep(1.2)

    assert agents["aabbccdd"].data.mark == AgentMark.INACTIVE


async def test_agent_reactivated_on_checkin(teamserver_fixture):
    """Agent marked inactive should be reactivated on next check-in."""
    core, agents = teamserver_fixture
    beat = {
        "hostname": "BOX", "username": "user", "domain": "", "internal_ip": "10.0.0.1",
        "os": 2, "os_desc": "Linux", "arch": "x64", "pid": 100,
        "process": "python3", "elevated": False, "sleep": 1, "jitter": 0, "ctr": 1,
    }
    beat["ctr"] = 2
    await core.agent_checkin("aabbccdd", "python", beat, "", "test-listener")

    # Force inactive
    agents["aabbccdd"].data.mark = AgentMark.INACTIVE
    agents["aabbccdd"].active = False

    # Check-in again — should reactivate
    beat["ctr"] = 3
    await core.agent_checkin("aabbccdd", "python", beat, "", "test-listener")
    assert agents["aabbccdd"].data.mark == AgentMark.ACTIVE
    assert agents["aabbccdd"].active is True


async def test_agent_replay_counter_rejected(teamserver_fixture):
    core, agents = teamserver_fixture
    beat = {
        "hostname": "BOX", "username": "user", "domain": "", "internal_ip": "10.0.0.1",
        "os": 2, "os_desc": "Linux", "arch": "x64", "pid": 100,
        "process": "python3", "elevated": False, "sleep": 1, "jitter": 0, "ctr": 1,
    }
    accepted = await core.agent_checkin("aabbccdd", "python", beat, "", "test-listener")
    assert accepted is True

    # Replay same counter must be rejected and last_counter unchanged.
    accepted = await core.agent_checkin("aabbccdd", "python", beat, "", "test-listener")
    assert accepted is False
    assert agents["aabbccdd"].data.last_counter == 1
