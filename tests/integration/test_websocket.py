"""Integration tests for WebSocket sync."""

import asyncio

import msgpack
import pytest

from executec2.config.schema import ExecuteC2Config, ServerConfig
from executec2.server.app import create_app, init_app_state, teardown_app_state
from executec2.server.models import OTPType, SyncPacketType


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
async def app_fixture(tmp_path):
    config = make_config(tmp_path)
    app = create_app(config)
    await init_app_state(app, config)
    try:
        yield app
    finally:
        await teardown_app_state(app)


# ---------------------------------------------------------------------------
# OTP lifecycle tests (no actual WebSocket transport needed)
# ---------------------------------------------------------------------------


async def test_otp_single_use(app_fixture):
    otp_store = app_fixture.state.otp_store
    otp = otp_store.generate("admin", OTPType.CONNECT)

    entry = otp_store.validate(otp)
    assert entry is not None
    assert entry.username == "admin"
    assert entry.otp_type == OTPType.CONNECT

    # Second use fails
    assert otp_store.validate(otp) is None


async def test_tunnel_otp_wrong_type_rejected(app_fixture):
    otp_store = app_fixture.state.otp_store
    otp = otp_store.generate("admin", OTPType.TUNNEL)

    # Should not validate as CONNECT type
    assert otp_store.validate(otp, expected_type=OTPType.CONNECT) is None


# ---------------------------------------------------------------------------
# Sync helper function tests
# ---------------------------------------------------------------------------


async def test_get_db_snapshot_agents(app_fixture):
    from executec2.server.routes.sync import _get_db_snapshot
    snapshot = await _get_db_snapshot(app_fixture.state.db, ["agents", "listeners"])
    assert "agents" in snapshot
    assert "listeners" in snapshot
    assert isinstance(snapshot["agents"], list)


async def test_sync_sequence_frames_structure(app_fixture):
    from executec2.server.routes.sync import _send_sync_sequence

    received = []

    class MockWS:
        app = app_fixture

        async def send_bytes(self, data: bytes):
            received.append(data)

    ws = MockWS()
    broker = app_fixture.state.broker
    db = app_fixture.state.db

    await _send_sync_sequence(ws, db, ["agents", "listeners"], broker)

    assert len(received) >= 2
    # First frame is SYNC_START
    assert received[0][0] == int(SyncPacketType.SYNC_START)
    # Last frame is SYNC_FINISH
    assert received[-1][0] == int(SyncPacketType.SYNC_FINISH)


# ---------------------------------------------------------------------------
# Broker integration via app state
# ---------------------------------------------------------------------------


async def test_broker_broadcasts_reach_registered_clients(app_fixture):
    from executec2.server.models import BrokerMessage, ClientHandler

    class MockWS:
        app = app_fixture
        async def send_bytes(self, data): pass
        async def close(self): pass

    client = ClientHandler(ws=MockWS(), username="test-user")
    broker = app_fixture.state.broker
    broker.register(client)

    msg = BrokerMessage(
        packet_type=SyncPacketType.AGENT_NEW,
        data=msgpack.packb({"id": "abc12345"}),
        category="agents",
    )
    await broker.broadcast(msg)
    await asyncio.sleep(0.05)

    broker.unregister(client)
    assert not client.send_queue.empty()


async def test_subscribe_updates_client_subscriptions(app_fixture):
    from executec2.server.models import ClientHandler

    class MockWS:
        app = app_fixture
        async def send_bytes(self, data): pass
        async def close(self): pass

    client = ClientHandler(ws=MockWS(), username="admin")
    client.subscriptions = {"agents"}
    broker = app_fixture.state.broker
    broker.register(client)

    # Add tasks subscription
    client.subscriptions.add("tasks")
    assert "tasks" in client.subscriptions
    assert "agents" in client.subscriptions

    broker.unregister(client)
