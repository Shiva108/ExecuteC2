"""Persistent WebSocket listener for agent transport."""

from __future__ import annotations

import asyncio
import base64
import logging
import ssl
from typing import TYPE_CHECKING

import msgpack
from aiohttp import WSMsgType, web

from executec2.listeners.base import ListenerPlugin
from executec2.transport import aes_decrypt, derive_beat_key, verify_envelope

if TYPE_CHECKING:
    from executec2.server.teamserver import TeamserverInterface

logger = logging.getLogger(__name__)


class WebSocketListener(ListenerPlugin):
    def __init__(self):
        self.teamserver: TeamserverInterface | None = None
        self.config: dict | None = None
        self._master_key: bytes | None = None
        self._beat_key: bytes | None = None
        self._paused = False
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    def get_info(self) -> dict:
        return {"name": "WebSocketListener", "type": "websocket", "protocol": "WS/S"}

    def validate_config(self, config: dict) -> dict:
        required = ["port_bind", "callback_addresses", "encrypt_key", "path"]
        for field in required:
            if field not in config:
                raise ValueError(f"Missing required field: {field}")
        if len(str(config["encrypt_key"])) != 64:
            raise ValueError("encrypt_key must be 64 hex chars (32 bytes)")
        config.setdefault("host_bind", "0.0.0.0")
        config.setdefault("ssl", False)
        config.setdefault("ssl_cert", "")
        config.setdefault("ssl_key", "")
        config.setdefault("max_frame_size", 1024 * 1024)
        config.setdefault("channel_limit", 64)
        return config

    async def start(self, config: dict, teamserver: "TeamserverInterface") -> None:
        self.config = self.validate_config(dict(config))
        self.teamserver = teamserver
        self._master_key = bytes.fromhex(self.config["encrypt_key"])
        self._beat_key = derive_beat_key(self._master_key)
        if hasattr(teamserver, "register_listener_master_key"):
            teamserver.register_listener_master_key(self.config["listener_name"], self._master_key)

        app = web.Application(client_max_size=int(self.config["max_frame_size"]))
        app.router.add_get(self.config["path"], self._ws_handler)
        self._runner = web.AppRunner(app)
        await self._runner.setup()

        ssl_ctx = None
        if self.config["ssl"]:
            ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_ctx.load_cert_chain(self.config["ssl_cert"], self.config["ssl_key"])

        self._site = web.TCPSite(
            self._runner,
            host=self.config["host_bind"],
            port=int(self.config["port_bind"]),
            ssl_context=ssl_ctx,
        )
        await self._site.start()

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None

    async def pause(self) -> None:
        self._paused = True

    async def resume(self) -> None:
        self._paused = False

    async def _ws_handler(self, request: web.Request) -> web.StreamResponse:
        ws = web.WebSocketResponse(max_msg_size=int(self.config["max_frame_size"]))
        await ws.prepare(request)

        agent_id = ""
        send_task: asyncio.Task | None = None
        try:
            hello = await ws.receive(timeout=10.0)
            if hello.type != WSMsgType.BINARY:
                await ws.close()
                return ws
            frame = msgpack.unpackb(hello.data, raw=False)
            beat_header = frame.get("beat", "")
            if not beat_header:
                await ws.close()
                return ws

            beat_raw = aes_decrypt(self._beat_key, base64.b64decode(beat_header))
            type_len = int.from_bytes(beat_raw[:4], "big")
            agent_type = beat_raw[4 : 4 + type_len].decode("utf-8", errors="strict")
            agent_id = beat_raw[4 + type_len : 4 + type_len + 8].decode("utf-8", errors="strict")
            beat_data = msgpack.unpackb(beat_raw[4 + type_len + 8 :], raw=False)

            if not self._paused:
                accepted = await self.teamserver.agent_checkin(
                    agent_id=agent_id,
                    agent_type=agent_type,
                    beat_data=beat_data,
                    external_ip=request.remote or "",
                    listener_name=self.config["listener_name"],
                )
                if not accepted:
                    await ws.close()
                    return ws

            if hasattr(self.teamserver, "_agents"):
                agent = self.teamserver._agents.get(agent_id)
                if agent is not None:
                    agent.transport = "websocket"
                    agent.ws = ws
                    agent.listener_master_key = self._master_key
            send_task = asyncio.create_task(self._send_loop(ws, agent_id))

            async for message in ws:
                if message.type != WSMsgType.BINARY:
                    continue
                envelope = msgpack.unpackb(message.data, raw=False)
                session_key = await self.teamserver.get_session_key(agent_id)
                if not verify_envelope(session_key, envelope):
                    continue

                if hasattr(self.teamserver, "_agents"):
                    agent = self.teamserver._agents.get(agent_id)
                    if agent is not None:
                        seq = int(envelope.get("seq", 0))
                        if seq <= agent.inbound_seq:
                            continue
                        agent.inbound_seq = seq

                kind = envelope.get("kind")
                if kind == "result":
                    await self.teamserver.submit_results(
                        agent_id,
                        [{"task_id": envelope.get("task_id", ""), "payload": envelope.get("payload", {})}],
                    )
                elif kind == "heartbeat":
                    await self.teamserver.agent_checkin(
                        agent_id=agent_id,
                        agent_type=agent_type,
                        beat_data=envelope.get("payload", {}),
                        external_ip=request.remote or "",
                        listener_name=self.config["listener_name"],
                    )
                elif kind.startswith("session_") and getattr(self.teamserver, "session_manager", None):
                    await self.teamserver.session_manager.handle_agent_envelope(agent_id, envelope)
        finally:
            if send_task:
                send_task.cancel()
            if agent_id and hasattr(self.teamserver, "_agents"):
                agent = self.teamserver._agents.get(agent_id)
                if agent is not None:
                    agent.ws = None
                if getattr(self.teamserver, "session_manager", None):
                    await self.teamserver.session_manager.close_agent_sessions(agent_id)

        return ws

    async def _send_loop(self, ws: web.WebSocketResponse, agent_id: str) -> None:
        while True:
            tasks = await self.teamserver.agent_get_pending_tasks(agent_id)
            for task in tasks:
                await ws.send_bytes(task)
            await asyncio.sleep(0.1)
