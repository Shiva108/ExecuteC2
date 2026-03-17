"""Unit tests for MessageBroker."""

import asyncio

import msgpack
import pytest

from executec2.server.broker import SYNC_BATCH_SIZE, MessageBroker, encode_packet
from executec2.server.models import BrokerMessage, BrokerMsgType, ClientHandler, SyncPacketType


class MockWebSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def send_bytes(self, data: bytes):
        self.sent.append(data)

    async def close(self):
        self.closed = True


def make_client(username="alice"):
    ws = MockWebSocket()
    return ClientHandler(ws=ws, username=username)


def make_message(category="agents", state_key="", msg_type=BrokerMsgType.EVENT):
    return BrokerMessage(
        msg_type=msg_type,
        state_key=state_key,
        packet_type=SyncPacketType.AGENT_NEW,
        data=msgpack.packb({"id": "abc12345"}),
        category=category,
    )


@pytest.fixture
async def broker():
    b = MessageBroker()
    await b.start()
    yield b
    await b.stop()


# ---------------------------------------------------------------------------
# encode_packet
# ---------------------------------------------------------------------------


def test_encode_packet_structure():
    frame = encode_packet(SyncPacketType.AGENT_NEW, b"\x01\x02")
    assert frame[0] == int(SyncPacketType.AGENT_NEW)
    assert frame[1:] == b"\x01\x02"


# ---------------------------------------------------------------------------
# Client registration
# ---------------------------------------------------------------------------


async def test_register_and_unregister(broker):
    client = make_client()
    broker.register(client)
    assert client in broker._clients
    broker.unregister(client)
    assert client not in broker._clients


async def test_unregister_unknown_client_safe(broker):
    client = make_client()
    broker.unregister(client)  # Should not raise


# ---------------------------------------------------------------------------
# Broadcast delivery
# ---------------------------------------------------------------------------


async def test_broadcast_delivers_to_client(broker):
    client = make_client()
    broker.register(client)

    msg = make_message()
    await broker.broadcast(msg)
    await asyncio.sleep(0.05)  # Let the loop process

    assert not client.send_queue.empty()
    frame = await client.send_queue.get()
    assert frame[0] == int(SyncPacketType.AGENT_NEW)


async def test_broadcast_respects_category_subscription(broker):
    client = make_client()
    client.subscriptions = {"agents"}  # Only agents
    broker.register(client)

    await broker.broadcast(make_message(category="listeners"))
    await asyncio.sleep(0.05)

    assert client.send_queue.empty()


async def test_broadcast_empty_subscriptions_receives_all(broker):
    """Empty subscriptions set means client receives all messages."""
    client = make_client()
    client.subscriptions = set()  # Empty = all
    broker.register(client)

    await broker.broadcast(make_message(category="listeners"))
    await asyncio.sleep(0.05)

    assert not client.send_queue.empty()


async def test_broadcast_multiple_clients(broker):
    clients = [make_client(f"user{i}") for i in range(3)]
    for c in clients:
        broker.register(c)

    await broker.broadcast(make_message())
    await asyncio.sleep(0.05)

    for c in clients:
        assert not c.send_queue.empty()


# ---------------------------------------------------------------------------
# State message deduplication
# ---------------------------------------------------------------------------


async def test_state_message_stored_in_client(broker):
    client = make_client()
    broker.register(client)

    msg = BrokerMessage(
        msg_type=BrokerMsgType.STATE,
        state_key="tick:abc12345",
        packet_type=SyncPacketType.AGENT_TICK,
        data=msgpack.packb({"id": "abc12345"}),
        category="agents",
    )
    await broker.broadcast(msg)
    await asyncio.sleep(0.05)

    assert "tick:abc12345" in client.state_store
    assert client.state_store["tick:abc12345"] is msg


async def test_state_message_last_write_wins(broker):
    client = make_client()
    broker.register(client)

    for i in range(3):
        msg = BrokerMessage(
            msg_type=BrokerMsgType.STATE,
            state_key="tick:abc12345",
            packet_type=SyncPacketType.AGENT_TICK,
            data=msgpack.packb({"id": "abc12345", "seq": i}),
            category="agents",
        )
        await broker.broadcast(msg)
    await asyncio.sleep(0.1)

    # Should have the last message in state store
    assert client.state_store["tick:abc12345"].data == msgpack.packb({"id": "abc12345", "seq": 2})


# ---------------------------------------------------------------------------
# Presync frames
# ---------------------------------------------------------------------------


def test_get_presync_frames_empty(broker):
    frames = broker.get_presync_frames("agents", {"agents": []})
    assert frames == []


def test_get_presync_frames_small_batch(broker):
    items = [{"id": f"agent{i}"} for i in range(5)]
    frames = broker.get_presync_frames("agents", {"agents": items})
    assert len(frames) == 1
    frame = frames[0]
    assert frame[0] == int(SyncPacketType.SYNC_CATEGORY_BATCH)
    payload = msgpack.unpackb(frame[1:])
    assert payload["category"] == "agents"
    assert len(payload["items"]) == 5


def test_get_presync_frames_large_batch(broker):
    items = [{"id": f"a{i}"} for i in range(SYNC_BATCH_SIZE + 10)]
    frames = broker.get_presync_frames("agents", {"agents": items})
    assert len(frames) == 2
