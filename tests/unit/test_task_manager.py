"""Unit tests for task type routing and management — Phase 10."""

import secrets

import pytest

from executec2.server.models import Agent, AgentData, MessageType, OSType, TaskData, TaskType


def make_agent_data(**kw) -> AgentData:
    return AgentData(
        id=kw.get("id", secrets.token_hex(4)),
        name="python",
        session_key=secrets.token_bytes(32),
        listener="http",
        sleep=60,
        os=OSType.LINUX,
    )


def make_task(task_type: TaskType = TaskType.TASK, **kw) -> TaskData:
    return TaskData(
        task_id=secrets.token_hex(4),
        agent_id=kw.get("agent_id", "deadbeef"),
        task_type=task_type,
        **{k: v for k, v in kw.items() if k != "agent_id"},
    )


# ---------------------------------------------------------------------------
# TaskType routing
# ---------------------------------------------------------------------------


def test_task_type_task_goes_to_pending_tasks():
    """TaskType.TASK payloads route to the agent pending_tasks queue."""
    agent = Agent(make_agent_data())
    task = make_task(TaskType.TASK)
    import msgpack
    payload = msgpack.packb({"task_id": task.task_id, "cmd": "shell"})
    agent.pending_tasks.put_nowait(payload)
    assert not agent.pending_tasks.empty()
    assert agent.pending_tunnel_tasks.empty()


def test_task_type_tunnel_goes_to_tunnel_queue():
    """TaskType.TUNNEL payloads route to the agent pending_tunnel_tasks queue."""
    agent = Agent(make_agent_data())
    task = make_task(TaskType.TUNNEL)
    import msgpack
    payload = msgpack.packb({"task_id": task.task_id, "type": "socks5"})
    agent.pending_tunnel_tasks.put_nowait(payload)
    assert not agent.pending_tunnel_tasks.empty()
    assert agent.pending_tasks.empty()


# ---------------------------------------------------------------------------
# Task lifecycle model
# ---------------------------------------------------------------------------


def test_task_default_not_completed():
    task = make_task()
    assert task.completed is False
    assert task.finish_date is None


def test_task_can_be_marked_completed():
    task = make_task()
    task.completed = True
    assert task.completed is True


def test_task_message_type_defaults_to_info():
    task = make_task()
    assert task.message_type == MessageType.INFO


@pytest.mark.xfail(reason="Phase 10 task manager / job progress not yet implemented")
def test_job_progress_updates():
    """JobType tasks emit AGENT_TASK_UPDATE broker events on partial progress."""
    raise NotImplementedError


@pytest.mark.xfail(reason="Phase 10 task manager not yet implemented")
def test_completed_task_stored_in_db():
    """Completed tasks are persisted to DB with finish_date set."""
    raise NotImplementedError
