"""Session lifecycle and channel relays for agent-backed interactive features."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import msgpack
from fastapi import WebSocket, WebSocketDisconnect

from executec2.server.models import (
    BrokerMessage,
    BrokerMsgType,
    SessionData,
    SessionStatus,
    SessionType,
    SyncPacketType,
)
from executec2.transport import sign_envelope

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SessionRuntime:
    data: SessionData
    queue: asyncio.Queue[bytes | None] = field(default_factory=lambda: asyncio.Queue(maxsize=4096))
    closed: bool = False


class SessionManager:
    def __init__(self, db, broker, event_manager, agents: dict):
        self._db = db
        self._broker = broker
        self._events = event_manager
        self._agents = agents
        self._sessions: dict[str, SessionRuntime] = {}

    async def open_session(
        self,
        *,
        agent_id: str,
        session_type: SessionType,
        created_by: str,
        metadata: dict | None = None,
    ) -> SessionData:
        agent = self._agents.get(agent_id)
        if agent is None or agent.ws is None:
            raise ValueError("Agent does not have an active WebSocket transport")

        session = SessionData(
            session_id=uuid4().hex[:12],
            agent_id=agent_id,
            session_type=session_type,
            status=SessionStatus.OPENING,
            created_by=created_by,
            metadata=metadata or {},
        )
        runtime = SessionRuntime(data=session)
        self._sessions[session.session_id] = runtime
        await self._db.session_insert(session)
        await self._broadcast(SyncPacketType.SESSION_CREATE, session.model_dump(mode="json"))
        await self._events.emit_async("session.create", {"session_id": session.session_id})
        await self._send_agent_envelope(
            agent_id,
            sign_envelope(
                key=agent.data.session_key,
                kind="session_open",
                seq=agent.outbound_seq,
                session_id=session.session_id,
                channel=session.session_type.value,
                payload=session.metadata,
            ),
        )
        agent.outbound_seq += 1
        return session

    async def list_sessions(self) -> list[SessionData]:
        return await self._db.session_list()

    async def get_session(self, session_id: str) -> SessionData | None:
        runtime = self._sessions.get(session_id)
        if runtime is not None:
            return runtime.data
        return await self._db.session_get(session_id)

    async def mark_active(self, session_id: str) -> None:
        runtime = self._sessions.get(session_id)
        if runtime is None:
            return
        runtime.data.status = SessionStatus.ACTIVE
        runtime.data.last_activity_at = datetime.now(UTC)
        await self._db.session_update(
            session_id,
            status=SessionStatus.ACTIVE,
            last_activity_at=runtime.data.last_activity_at,
        )
        await self._broadcast(SyncPacketType.SESSION_UPDATE, runtime.data.model_dump(mode="json"))

    async def handle_agent_envelope(self, agent_id: str, envelope: dict) -> None:
        kind = envelope.get("kind")
        session_id = str(envelope.get("session_id", ""))
        runtime = self._sessions.get(session_id)
        if runtime is None:
            return

        runtime.data.last_activity_at = datetime.now(UTC)
        await self._db.session_update(session_id, last_activity_at=runtime.data.last_activity_at)

        if kind == "session_opened":
            await self.mark_active(session_id)
            return
        if kind == "session_data":
            payload = envelope.get("payload", b"")
            if isinstance(payload, str):
                payload = payload.encode()
            if isinstance(payload, (bytes, bytearray)):
                await runtime.queue.put(bytes(payload))
            return
        if kind == "session_error":
            await self.stop_session(session_id, status=SessionStatus.ERROR, notify_agent=False)
            return
        if kind == "session_closed":
            await self.stop_session(session_id, status=SessionStatus.CLOSED, notify_agent=False)
            return

        logger.debug("Unhandled session envelope kind=%s agent=%s", kind, agent_id)

    async def attach_operator(self, websocket: WebSocket, session_id: str) -> None:
        runtime = self._sessions.get(session_id)
        if runtime is None:
            session = await self._db.session_get(session_id)
            if session is None:
                raise ValueError("Session not found")
            runtime = SessionRuntime(data=session)
            self._sessions[session_id] = runtime

        await websocket.accept()
        sender = asyncio.create_task(self._session_to_websocket(runtime, websocket))
        try:
            while True:
                data = await websocket.receive_bytes()
                await self._forward_session_data(runtime.data.session_id, data)
        except WebSocketDisconnect:
            pass
        finally:
            sender.cancel()
            await self.stop_session(session_id, status=SessionStatus.CLOSED)

    async def bridge_stream(
        self,
        session_id: str,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        runtime = self._sessions.get(session_id)
        if runtime is None:
            writer.close()
            return

        sender = asyncio.create_task(self._session_to_stream(runtime, writer))
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                await self._forward_session_data(session_id, chunk)
        finally:
            sender.cancel()
            try:
                writer.close()
            except Exception:
                pass
            await self.stop_session(session_id, status=SessionStatus.CLOSED)

    async def stop_session(
        self,
        session_id: str,
        *,
        status: SessionStatus = SessionStatus.TERMINATED,
        notify_agent: bool = True,
    ) -> None:
        runtime = self._sessions.get(session_id)
        if runtime is None or runtime.closed:
            return
        runtime.closed = True
        runtime.data.status = status
        runtime.data.closed_at = datetime.now(UTC)
        runtime.data.last_activity_at = runtime.data.closed_at
        await self._db.session_update(
            session_id,
            status=status,
            closed_at=runtime.data.closed_at,
            last_activity_at=runtime.data.last_activity_at,
        )
        await self._broadcast(SyncPacketType.SESSION_DELETE, runtime.data.model_dump(mode="json"))
        await self._events.emit_async("session.close", {"session_id": session_id})
        if notify_agent:
            agent = self._agents.get(runtime.data.agent_id)
            if agent is not None and agent.ws is not None:
                await self._send_agent_envelope(
                    runtime.data.agent_id,
                    sign_envelope(
                        key=agent.data.session_key,
                        kind="session_close",
                        seq=agent.outbound_seq,
                        session_id=session_id,
                        channel=runtime.data.session_type.value,
                        payload={},
                    ),
                )
                agent.outbound_seq += 1
        await runtime.queue.put(None)

    async def close_agent_sessions(self, agent_id: str) -> None:
        for session_id, runtime in list(self._sessions.items()):
            if runtime.data.agent_id == agent_id and not runtime.closed:
                await self.stop_session(session_id, status=SessionStatus.TERMINATED, notify_agent=False)

    async def _forward_session_data(self, session_id: str, chunk: bytes) -> None:
        runtime = self._sessions.get(session_id)
        if runtime is None:
            return
        agent = self._agents.get(runtime.data.agent_id)
        if agent is None or agent.ws is None:
            raise ValueError("Agent disconnected")
        runtime.data.last_activity_at = datetime.now(UTC)
        await self._db.session_update(session_id, last_activity_at=runtime.data.last_activity_at)
        await self._send_agent_envelope(
            runtime.data.agent_id,
            sign_envelope(
                key=agent.data.session_key,
                kind="session_data",
                seq=agent.outbound_seq,
                session_id=session_id,
                channel=runtime.data.session_type.value,
                payload=chunk,
            ),
        )
        agent.outbound_seq += 1

    async def _send_agent_envelope(self, agent_id: str, envelope: dict) -> None:
        agent = self._agents.get(agent_id)
        if agent is None or agent.ws is None:
            raise ValueError("Agent does not have an active WebSocket transport")
        await agent.ws.send_bytes(msgpack.packb(envelope, use_bin_type=True))

    async def _session_to_websocket(self, runtime: SessionRuntime, websocket: WebSocket) -> None:
        while True:
            chunk = await runtime.queue.get()
            if chunk is None:
                return
            await websocket.send_bytes(chunk)

    async def _session_to_stream(self, runtime: SessionRuntime, writer: asyncio.StreamWriter) -> None:
        while True:
            chunk = await runtime.queue.get()
            if chunk is None:
                return
            writer.write(chunk)
            await writer.drain()

    async def _broadcast(self, packet_type: SyncPacketType, payload: dict) -> None:
        await self._broker.broadcast(
            BrokerMessage(
                msg_type=BrokerMsgType.EVENT,
                packet_type=packet_type,
                data=msgpack.packb(payload),
                category="sessions",
            )
        )
