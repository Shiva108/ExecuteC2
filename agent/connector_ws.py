"""WebSocket connector for the Python agent."""

import random
import ssl

import aiohttp


class WebSocketConnector:
    def __init__(self, config: dict):
        self.callback_addresses: list[str] = config["callback_addresses"]
        self.path: str = config.get("path", "/ws")
        self.ssl: bool = config.get("ssl", False)
        self.verify_ssl: bool = bool(config.get("verify_ssl", False))
        self._addr_index = 0

    def _next_url(self) -> str:
        scheme = "wss" if self.ssl else "ws"
        addr = self.callback_addresses[self._addr_index % len(self.callback_addresses)]
        self._addr_index += 1
        return f"{scheme}://{addr}{self.path}"

    async def connect(self, handshake: bytes):
        connector_ssl = ssl.create_default_context() if self.ssl and self.verify_ssl else False
        session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=connector_ssl))
        try:
            ws = await session.ws_connect(self._next_url(), heartbeat=20)
            await ws.send_bytes(handshake)
            return session, ws
        except Exception:
            await session.close()
            return None, None

    def backoff(self, fail_count: int) -> float:
        delay = min(2.0 ** fail_count, 300.0)
        return delay * (0.8 + 0.4 * random.random())
