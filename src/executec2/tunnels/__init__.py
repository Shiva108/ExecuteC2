"""TunnelManager for ExecuteC2."""

from __future__ import annotations

import asyncio
import logging
import uuid

from executec2.server.models import SessionType
from executec2.tunnels.socks5 import SOCKS5Server

logger = logging.getLogger(__name__)


class TunnelManager:
    """Manages local tunnel frontends backed by agent WebSocket sessions."""

    def __init__(self, session_manager=None):
        self._session_manager = session_manager
        self._tunnels: dict[str, object] = {}

    async def create_socks5(
        self,
        agent_id: str,
        lhost: str,
        lport: int,
        use_auth: bool = False,
        username: str = "",
        password: str = "",
    ) -> str:
        tunnel_id = uuid.uuid4().hex[:8]
        server = SOCKS5Server(
            tunnel_id=tunnel_id,
            host=lhost,
            port=lport,
            agent_id=agent_id,
            use_auth=use_auth,
            username=username,
            password=password,
            data_relay=self._relay_socks if self._session_manager else None,
        )
        await server.start()
        self._tunnels[tunnel_id] = server
        return tunnel_id

    async def create_lportfwd(
        self,
        agent_id: str,
        lhost: str,
        lport: int,
        thost: str,
        tport: int,
    ) -> str:
        tunnel_id = uuid.uuid4().hex[:8]

        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            if self._session_manager is None:
                try:
                    rem_reader, rem_writer = await asyncio.open_connection(thost, tport)
                    await asyncio.gather(
                        _relay(reader, rem_writer),
                        _relay(rem_reader, writer),
                    )
                finally:
                    writer.close()
                return

            session = await self._session_manager.open_session(
                agent_id=agent_id,
                session_type=SessionType.PORTFWD,
                created_by="system",
                metadata={"target_host": thost, "target_port": int(tport)},
            )
            await self._session_manager.bridge_stream(session.session_id, reader, writer)

        server = await asyncio.start_server(handler, lhost, lport)
        self._tunnels[tunnel_id] = server
        return tunnel_id

    async def _relay_socks(
        self,
        _channel_id: str,
        agent_id: str,
        dst_host: str,
        dst_port: int,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        session = await self._session_manager.open_session(
            agent_id=agent_id,
            session_type=SessionType.SOCKS,
            created_by="system",
            metadata={"target_host": dst_host, "target_port": int(dst_port)},
        )
        await self._session_manager.bridge_stream(session.session_id, reader, writer)

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
        finally:
            logger.info("Stopped tunnel %s", tunnel_id)
        return True

    async def stop_all(self) -> None:
        for tunnel_id in list(self._tunnels):
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
