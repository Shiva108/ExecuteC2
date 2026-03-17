"""Unit tests for Pydantic models — Phase 1 skeleton validation."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from executec2.server.models import (
    AgentData,
    AgentMark,
    ChatMessage,
    CredentialData,
    CredentialType,
    ListenerData,
    ListenerStatus,
    OSType,
    OTPEntry,
    OTPType,
    TaskData,
    TaskType,
    TargetData,
    TunnelData,
    TunnelType,
)


# ---------------------------------------------------------------------------
# AgentData
# ---------------------------------------------------------------------------


def test_agent_data_defaults():
    agent = AgentData(
        id="deadbeef",
        name="python",
        session_key=b"\x00" * 32,
        listener="http",
        sleep=60,
        os=OSType.LINUX,
    )
    assert agent.mark == AgentMark.ACTIVE
    assert agent.elevated is False
    assert agent.jitter == 0
    assert agent.create_time.tzinfo is not None
    assert agent.last_tick.tzinfo is not None


def test_agent_data_datetime_always_utc_aware():
    """Datetime fields must always be timezone-aware (UTC)."""
    agent = AgentData(
        id="deadbeef",
        name="python",
        session_key=b"\x00" * 32,
        listener="http",
        sleep=60,
        os=OSType.LINUX,
    )
    assert agent.create_time.tzinfo is not None
    assert agent.last_tick.tzinfo is not None


def test_agent_data_naive_datetime_normalized():
    """Naive datetimes passed in are coerced to UTC-aware."""
    naive = datetime(2025, 1, 1, 12, 0, 0)
    agent = AgentData(
        id="deadbeef",
        name="python",
        session_key=b"\x00" * 32,
        listener="http",
        sleep=60,
        os=OSType.LINUX,
        last_tick=naive,
        create_time=naive,
    )
    assert agent.last_tick.tzinfo is not None
    assert agent.create_time.tzinfo is not None


# ---------------------------------------------------------------------------
# OTPEntry
# ---------------------------------------------------------------------------


def test_otp_entry_created_always_utc_aware():
    entry = OTPEntry(otp="abc123", otp_type=OTPType.CONNECT, username="alice")
    assert entry.created.tzinfo is not None


def test_otp_entry_naive_created_normalized():
    naive = datetime(2025, 1, 1, 12, 0, 0)
    entry = OTPEntry(otp="abc123", otp_type=OTPType.CONNECT, username="alice", created=naive)
    assert entry.created.tzinfo is not None


# ---------------------------------------------------------------------------
# TaskData
# ---------------------------------------------------------------------------


def test_task_data_defaults():
    task = TaskData(task_id="abc12345", agent_id="deadbeef")
    assert task.task_type == TaskType.TASK
    assert task.completed is False
    assert task.data == b""


# ---------------------------------------------------------------------------
# ListenerData
# ---------------------------------------------------------------------------


def test_listener_data_defaults():
    listener = ListenerData(listener_name="l1", listener_type="http", config={})
    assert listener.status == ListenerStatus.STOPPED
    assert listener.watermark == ""


# ---------------------------------------------------------------------------
# CredentialData
# ---------------------------------------------------------------------------


def test_credential_data_defaults():
    cred = CredentialData(cred_id="abc123")
    assert cred.cred_type == CredentialType.PASSWORD
    assert cred.secret == ""


# ---------------------------------------------------------------------------
# TargetData
# ---------------------------------------------------------------------------


def test_target_data_defaults():
    target = TargetData(target_id="xyz")
    assert target.alive is True
    assert target.agents == []


# ---------------------------------------------------------------------------
# TunnelData
# ---------------------------------------------------------------------------


def test_tunnel_data_fields():
    tunnel = TunnelData(
        tunnel_id="t1",
        agent_id="deadbeef",
        tunnel_type=TunnelType.SOCKS5,
        lport=1080,
    )
    assert tunnel.lhost == "127.0.0.1"
    assert tunnel.use_auth is False


# ---------------------------------------------------------------------------
# ChatMessage
# ---------------------------------------------------------------------------


def test_chat_message_defaults():
    msg = ChatMessage(username="alice", message="hello")
    assert msg.id == 0
    assert msg.date.tzinfo is not None
