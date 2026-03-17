"""MessageBroker and WebSocket fan-out for ExecuteC2."""

import asyncio
import logging
import struct

import msgpack

from executec2.server.models import BrokerMessage, BrokerMsgType, ClientHandler, SyncPacketType

logger = logging.getLogger(__name__)

# Backpressure thresholds (fraction of queue capacity)
_WARN_THRESH = 0.75
_DROP_THRESH = 0.95
_DISCONNECT_THRESH = 1.0

SYNC_BATCH_SIZE = 500


def encode_packet(packet_type: SyncPacketType, data: bytes) -> bytes:
    """Build a binary WebSocket frame: [1 byte packet_type][payload]."""
    return struct.pack("B", int(packet_type)) + data


class MessageBroker:
    """Fan-out broadcast to all connected operator WebSocket clients."""

    def __init__(self, queue_size: int = 8192):
        self._clients: list[ClientHandler] = []
        self._broadcast_queue: asyncio.Queue[BrokerMessage] = asyncio.Queue(maxsize=queue_size)
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    def register(self, client: ClientHandler) -> None:
        self._clients.append(client)

    def unregister(self, client: ClientHandler) -> None:
        try:
            self._clients.remove(client)
        except ValueError:
            pass

    async def broadcast(self, message: BrokerMessage) -> None:
        """Enqueue message for fan-out. Non-blocking."""
        try:
            self._broadcast_queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning("Broker broadcast queue full, dropping message type=%s", message.packet_type)

    async def _loop(self) -> None:
        while True:
            try:
                message = await self._broadcast_queue.get()
                await self._deliver(message)
                self._broadcast_queue.task_done()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Broker loop error")

    async def _deliver(self, message: BrokerMessage) -> None:
        """Deliver message to all subscribed clients with backpressure handling."""
        frame = encode_packet(message.packet_type, message.data)
        to_disconnect = []

        for client in list(self._clients):
            # Check category subscription (empty subscriptions = receives all)
            if client.subscriptions and message.category not in client.subscriptions:
                continue

            # State messages: last-write-wins per state_key
            if message.msg_type == BrokerMsgType.STATE and message.state_key:
                client.state_store[message.state_key] = message

            queue = client.send_queue
            capacity = queue.maxsize
            size = queue.qsize()
            fill_ratio = size / capacity if capacity > 0 else 0.0

            if fill_ratio >= _DISCONNECT_THRESH:
                logger.error("Client %s queue full (100%%), disconnecting", client.username)
                to_disconnect.append(client)
                continue
            elif fill_ratio >= _DROP_THRESH:
                logger.warning("Client %s queue at 95%%, dropping message", client.username)
                continue
            elif fill_ratio >= _WARN_THRESH:
                logger.warning("Client %s queue at 75%% fill", client.username)

            try:
                client.send_queue.put_nowait(frame)
            except asyncio.QueueFull:
                logger.warning("Client %s send_queue full, dropping frame", client.username)

        for client in to_disconnect:
            self.unregister(client)
            try:
                await client.ws.close()
            except Exception:
                pass

    def get_presync_frames(self, category: str, db_snapshots: dict) -> list[bytes]:
        """Build presync batch frames for a category from current state."""
        items = db_snapshots.get(category, [])
        frames = []
        batch = []

        for item_data in items:
            batch.append(item_data)
            if len(batch) >= SYNC_BATCH_SIZE:
                frames.append(encode_packet(
                    SyncPacketType.SYNC_CATEGORY_BATCH,
                    msgpack.packb({"category": category, "items": batch}),
                ))
                batch = []

        if batch:
            frames.append(encode_packet(
                SyncPacketType.SYNC_CATEGORY_BATCH,
                msgpack.packb({"category": category, "items": batch}),
            ))

        return frames
