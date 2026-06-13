"""TeamserverInterface Protocol and TeamserverCore implementation."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Protocol

import msgpack

from executec2.server.broker import MessageBroker
from executec2.server.database import Database
from executec2.server.events import EventManager
from executec2.server.models import (
    Agent,
    AgentData,
    AgentMark,
    BrokerMessage,
    BrokerMsgType,
    SyncPacketType,
    TaskData,
    TaskType,
)
from executec2.transport import derive_session_key, sign_envelope

logger = logging.getLogger(__name__)

_TICK_INTERVAL = 0.8  # seconds
_INACTIVE_MULTIPLIER = 3  # mark inactive after 3× sleep


class TeamserverInterface(Protocol):
    """Interface that listener plugins use to interact with the teamserver."""

    async def agent_checkin(
        self,
        agent_id: str,
        agent_type: str,
        beat_data: dict,
        external_ip: str,
        listener_name: str,
    ) -> bool: ...

    async def agent_get_pending_tasks(self, agent_id: str) -> list[bytes]: ...

    async def get_session_key(self, agent_id: str) -> bytes: ...

    async def submit_results(self, agent_id: str, responses: list[dict]) -> None: ...


class TeamserverCore:
    """Core teamserver logic: agent lifecycle, tick updater, task dispatch."""

    def __init__(
        self,
        db: Database,
        broker: MessageBroker,
        event_manager: EventManager,
        agents: dict[str, Agent],
    ) -> None:
        self._db = db
        self._broker = broker
        self._events = event_manager
        self._agents = agents
        self._tick_task: asyncio.Task | None = None
        self._agent_plugins: dict[str, object] = {}  # type_name → AgentPlugin instance
        self._listener_master_keys: dict[str, bytes] = {}

    def register_agent_plugin(self, agent_type: str, plugin: object) -> None:
        self._agent_plugins[agent_type] = plugin

    def register_listener_master_key(self, listener_name: str, master_key: bytes) -> None:
        self._listener_master_keys[listener_name] = master_key

    async def start(self) -> None:
        self._tick_task = asyncio.create_task(self._agent_tick_updater())

    async def stop(self) -> None:
        if self._tick_task:
            self._tick_task.cancel()
            self._tick_task = None

    # ------------------------------------------------------------------
    # TeamserverInterface implementation
    # ------------------------------------------------------------------

    async def agent_checkin(
        self,
        agent_id: str,
        agent_type: str,
        beat_data: dict,
        external_ip: str,
        listener_name: str,
    ) -> bool:
        """Handle an agent check-in (new registration or recurring tick)."""
        plugin = self._agent_plugins.get(agent_type)
        if plugin is None:
            logger.warning("Unknown agent type: %s", agent_type)
            return False

        counter = int(beat_data.get("ctr", 0))
        if counter <= 0:
            logger.warning("Rejected beat with invalid counter from %s", agent_id)
            return False

        if agent_id in self._agents:
            # Known agent — update last_tick
            agent = self._agents[agent_id]
            agent.listener_master_key = self._listener_master_keys.get(listener_name)
            if counter <= agent.data.last_counter:
                logger.warning(
                    "Rejected replayed beat from %s (ctr=%d <= %d)",
                    agent_id,
                    counter,
                    agent.data.last_counter,
                )
                return False

            agent.data.last_counter = counter
            agent.data.last_tick = datetime.now(UTC)
            if "sleep" in beat_data:
                agent.data.sleep = int(beat_data["sleep"])
            if "jitter" in beat_data:
                agent.data.jitter = int(beat_data["jitter"])
            if not agent.active:
                agent.active = True
                agent.data.mark = AgentMark.ACTIVE
            await self._db.agent_update(
                agent_id,
                last_tick=agent.data.last_tick,
                mark=str(agent.data.mark),
                last_counter=counter,
                sleep=agent.data.sleep,
                jitter=agent.data.jitter,
            )
            return True
        else:
            # New agent — parse beat and register
            fields = plugin.parse_beat(beat_data)

            master_key = self._listener_master_keys.get(listener_name)
            if master_key is None:
                logger.warning("No master key registered for listener %s", listener_name)
                return False
            session_key = derive_session_key(master_key, agent_id)

            _explicit = {"id", "name", "session_key", "listener", "external_ip"}
            agent_data = AgentData(
                id=agent_id,
                name=agent_type,
                session_key=session_key,
                listener=listener_name,
                external_ip=external_ip,
                **{k: v for k, v in fields.items() if k in AgentData.model_fields and k not in _explicit},
                last_counter=counter,
            )
            agent = Agent(data=agent_data)
            agent.listener_master_key = master_key
            self._agents[agent_id] = agent

            await self._db.agent_insert(agent_data)

            msg = BrokerMessage(
                msg_type=BrokerMsgType.EVENT,
                packet_type=SyncPacketType.AGENT_NEW,
                data=msgpack.packb(agent_data.model_dump(mode="json", exclude={"session_key", "custom_data"})),
                category="agents",
            )
            await self._broker.broadcast(msg)
            await self._events.emit_async("agent.new", {"agent_id": agent_id})
            logger.info("New agent registered: %s (%s)", agent_id, agent_type)
            return True

    async def agent_get_pending_tasks(self, agent_id: str) -> list[bytes]:
        """Drain the pending task queue for an agent and return task bytes."""
        agent = self._agents.get(agent_id)
        if agent is None:
            return []
        tasks = []
        while not agent.pending_tasks.empty():
            try:
                task_bytes = agent.pending_tasks.get_nowait()
                tasks.append(task_bytes)
            except asyncio.QueueEmpty:
                break
        return tasks

    async def get_session_key(self, agent_id: str) -> bytes:
        agent = self._agents.get(agent_id)
        if agent is None:
            return b"\x00" * 32
        return agent.data.session_key

    async def submit_results(self, agent_id: str, responses: list[dict]) -> None:
        agent = self._agents.get(agent_id)
        if agent is None:
            return
        plugin = self._agent_plugins.get(agent.data.name)
        if plugin is None:
            return

        for response in responses:
            task_id = str(response.get("task_id", ""))
            payload = response.get("payload", {})
            if not task_id:
                continue
            task = await self._db.task_get(task_id)
            if task is None:
                logger.warning("Received result for unknown task %s", task_id)
                continue
            if task.agent_id != agent_id:
                logger.warning(
                    "Received task result for mismatched agent %s on task %s",
                    agent_id,
                    task_id,
                )
                continue

            processed = plugin.process_response(task_id, payload)
            update_fields = {
                "message_type": processed["message_type"],
                "message": processed["message"],
                "clear_text": processed["clear_text"],
                "completed": bool(processed["completed"]),
            }
            if processed.get("completed"):
                update_fields["finish_date"] = datetime.now(UTC)
            await self._db.task_update(task_id, **update_fields)

            msg = BrokerMessage(
                msg_type=BrokerMsgType.EVENT,
                packet_type=SyncPacketType.AGENT_TASK_UPDATE,
                data=msgpack.packb(
                    {
                        "task_id": task_id,
                        "agent_id": agent_id,
                        "message_type": int(processed["message_type"]),
                        "message": processed["message"],
                        "clear_text": processed["clear_text"],
                        "completed": bool(processed["completed"]),
                        "finish_date": (
                            update_fields["finish_date"].isoformat()
                            if "finish_date" in update_fields
                            else None
                        ),
                    }
                ),
                category="agents",
            )
            await self._broker.broadcast(msg)
            await self._events.emit_async("task.update", {"task_id": task_id})

    # ------------------------------------------------------------------
    # Task dispatch
    # ------------------------------------------------------------------

    async def dispatch_task(self, task: TaskData, task_payload: bytes) -> None:
        """Enqueue a task for delivery to the agent on next check-in."""
        agent = self._agents.get(task.agent_id)
        if agent is None:
            raise ValueError(f"Agent {task.agent_id} not connected")

        await self._db.task_insert(task)
        try:
            wire_payload = msgpack.unpackb(task_payload, raw=False) if task_payload else {}
        except Exception:
            wire_payload = task_payload

        envelope = sign_envelope(
            key=agent.data.session_key,
            kind="task",
            seq=agent.outbound_seq,
            task_id=task.task_id,
            payload=wire_payload,
        )
        agent.outbound_seq += 1
        packed_envelope = msgpack.packb(envelope, use_bin_type=True)

        if task.task_type == TaskType.TUNNEL:
            try:
                agent.pending_tunnel_tasks.put_nowait(packed_envelope)
            except asyncio.QueueFull:
                logger.warning("Agent %s tunnel task queue full", task.agent_id)
        else:
            try:
                agent.pending_tasks.put_nowait(packed_envelope)
            except asyncio.QueueFull:
                logger.warning("Agent %s task queue full", task.agent_id)
                return

        msg = BrokerMessage(
            msg_type=BrokerMsgType.EVENT,
            packet_type=SyncPacketType.AGENT_TASK_SEND,
            data=msgpack.packb(task.model_dump(mode="json")),
            category="agents",
        )
        await self._broker.broadcast(msg)
        await self._events.emit_async("task.send", {"task_id": task.task_id})

    # ------------------------------------------------------------------
    # Tick updater
    # ------------------------------------------------------------------

    async def _agent_tick_updater(self) -> None:
        """Periodically broadcast AGENT_TICK for each agent and mark inactives."""
        while True:
            try:
                await asyncio.sleep(_TICK_INTERVAL)
                now = datetime.now(UTC)
                for agent_id, agent in list(self._agents.items()):
                    elapsed = (now - agent.data.last_tick).total_seconds()
                    threshold = agent.data.sleep * _INACTIVE_MULTIPLIER
                    if elapsed > threshold and agent.data.mark == AgentMark.ACTIVE:
                        agent.data.mark = AgentMark.INACTIVE
                        agent.active = False
                        await self._db.agent_update(agent_id, mark=str(AgentMark.INACTIVE))
                        logger.info("Agent %s marked inactive", agent_id)

                    msg = BrokerMessage(
                        msg_type=BrokerMsgType.STATE,
                        state_key=f"tick:{agent_id}",
                        packet_type=SyncPacketType.AGENT_TICK,
                        data=msgpack.packb({"id": agent_id, "last_tick": agent.data.last_tick.isoformat(), "mark": str(agent.data.mark)}),
                        category="agents",
                    )
                    await self._broker.broadcast(msg)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Tick updater error")
