"""TunnelManager for ExecuteC2 — tracks tunnels and manages asyncio servers."""

import asyncio
import logging
import uuid

from executec2.tunnels.socks5 import SOCKS5Server

logger = logging.getLogger(__name__)


class TunnelManager:
    """Manages active tunnels (SOCKS5 + local port forwarding)."""

    def __init__(self):
        self._tunnels: dict[str, object] = {}  # tunnel_id → server

    async def create_socks5(
        self,
        agent_id: str,
        lhost: str,
        lport: int,
        use_auth: bool = False,
        username: str = "",
        password: str = "",
    ) -> str:
        """Start a SOCKS5 server. Returns tunnel_id."""
        tunnel_id = uuid.uuid4().hex[:8]
        server = SOCKS5Server(
            tunnel_id=tunnel_id,
            host=lhost,
            port=lport,
            agent_id=agent_id,
            use_auth=use_auth,
            username=username,
            password=password,
        )
        await server.start()
        self._tunnels[tunnel_id] = server
        logger.info("Created SOCKS5 tunnel %s for agent %s on %s:%d", tunnel_id, agent_id, lhost, lport)
        return tunnel_id

    async def create_lportfwd(
        self,
        agent_id: str,
        lhost: str,
        lport: int,
        thost: str,
        tport: int,
    ) -> str:
        """Start a local port-forward TCP server. Returns tunnel_id."""
        tunnel_id = uuid.uuid4().hex[:8]

        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            try:
                rem_reader, rem_writer = await asyncio.open_connection(thost, tport)
                await asyncio.gather(
                    _relay(reader, rem_writer),
                    _relay(rem_reader, writer),
                )
            except Exception:
                pass
            finally:
                try:
                    writer.close()
                except Exception:
                    pass

        server = await asyncio.start_server(handler, lhost, lport)
        self._tunnels[tunnel_id] = server
        logger.info("Created lportfwd tunnel %s: %s:%d → %s:%d", tunnel_id, lhost, lport, thost, tport)
        return tunnel_id

    async def stop_tunnel(self, tunnel_id: str) -> bool:
        server = self._tunnels.pop(tunnel_id, None)
        if server is None:
            return False
        try:
            if isinstance(server, SOCKS5Server):
                await server.stop()
            elif isinstance(server, asyncio.Server):
                server.close()
                await server.wait_closed()
        except Exception:
            pass
        logger.info("Stopped tunnel %s", tunnel_id)
        return True

    async def stop_all(self) -> None:
        for tunnel_id in list(self._tunnels.keys()):
            await self.stop_tunnel(tunnel_id)

    def list_tunnel_ids(self) -> list[str]:
        return list(self._tunnels.keys())


async def _relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(4096)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass
