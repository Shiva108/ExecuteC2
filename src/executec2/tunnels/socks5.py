"""SOCKS5 server for ExecuteC2 tunneling."""

import asyncio
import logging
import struct
import uuid

logger = logging.getLogger(__name__)

# SOCKS5 constants
_SOCKS_VER = 0x05
_NO_AUTH = 0x00
_USER_PASS_AUTH = 0x02
_NO_ACCEPTABLE = 0xFF
_CMD_CONNECT = 0x01
_ATYP_IPV4 = 0x01
_ATYP_DOMAIN = 0x03
_ATYP_IPV6 = 0x04
_REP_SUCCESS = 0x00
_REP_GENERAL_FAIL = 0x01
_REP_CONN_REFUSED = 0x05
_REP_CMD_NOT_SUPPORTED = 0x07


class SOCKS5Server:
    """Asyncio SOCKS5 server that relays through an agent."""

    def __init__(
        self,
        tunnel_id: str,
        host: str,
        port: int,
        agent_id: str,
        use_auth: bool = False,
        username: str = "",
        password: str = "",
        data_relay=None,  # callable(channel_id, data) → None
    ):
        self.tunnel_id = tunnel_id
        self.host = host
        self.port = port
        self.agent_id = agent_id
        self.use_auth = use_auth
        self.username = username
        self.password = password
        self._data_relay = data_relay
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        logger.info("SOCKS5 server %s listening on %s:%d", self.tunnel_id, self.host, self.port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        channel_id = uuid.uuid4().hex[:8]
        try:
            await self._socks5_handshake(reader, writer, channel_id)
        except Exception:
            logger.debug("SOCKS5 client error", exc_info=True)
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def _socks5_handshake(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, channel_id: str
    ) -> None:
        # --- Auth negotiation ---
        header = await asyncio.wait_for(reader.readexactly(2), timeout=10)
        ver, nmethods = header
        if ver != _SOCKS_VER:
            writer.close()
            return
        methods = await asyncio.wait_for(reader.readexactly(nmethods), timeout=10)

        if self.use_auth:
            if _USER_PASS_AUTH not in methods:
                writer.write(bytes([_SOCKS_VER, _NO_ACCEPTABLE]))
                await writer.drain()
                return
            writer.write(bytes([_SOCKS_VER, _USER_PASS_AUTH]))
            await writer.drain()

            # Username/password sub-negotiation
            sub_ver = (await reader.readexactly(1))[0]
            ulen = (await reader.readexactly(1))[0]
            uname = (await reader.readexactly(ulen)).decode(errors="replace")
            plen = (await reader.readexactly(1))[0]
            passwd = (await reader.readexactly(plen)).decode(errors="replace")

            if uname != self.username or passwd != self.password:
                writer.write(bytes([sub_ver, 0x01]))  # failure
                await writer.drain()
                return
            writer.write(bytes([sub_ver, 0x00]))  # success
            await writer.drain()
        else:
            writer.write(bytes([_SOCKS_VER, _NO_AUTH]))
            await writer.drain()

        # --- Request ---
        req_header = await asyncio.wait_for(reader.readexactly(4), timeout=10)
        ver2, cmd, _, atyp = req_header

        if ver2 != _SOCKS_VER or cmd != _CMD_CONNECT:
            self._send_reply(writer, _REP_CMD_NOT_SUPPORTED)
            return

        if atyp == _ATYP_IPV4:
            dst_addr_bytes = await reader.readexactly(4)
            dst_host = ".".join(str(b) for b in dst_addr_bytes)
        elif atyp == _ATYP_DOMAIN:
            domain_len = (await reader.readexactly(1))[0]
            dst_host = (await reader.readexactly(domain_len)).decode()
        elif atyp == _ATYP_IPV6:
            dst_addr_bytes = await reader.readexactly(16)
            import ipaddress
            dst_host = str(ipaddress.IPv6Address(dst_addr_bytes))
        else:
            self._send_reply(writer, _REP_GENERAL_FAIL)
            return

        dst_port_bytes = await reader.readexactly(2)
        dst_port = struct.unpack("!H", dst_port_bytes)[0]

        # Send success reply
        self._send_reply(writer, _REP_SUCCESS, dst_host, dst_port)
        await writer.drain()

        logger.debug("SOCKS5 CONNECT %s:%d (channel %s)", dst_host, dst_port, channel_id)

        # Relay data through agent if relay is configured
        if self._data_relay:
            await self._data_relay(channel_id, self.agent_id, dst_host, dst_port, reader, writer)

    def _send_reply(
        self,
        writer: asyncio.StreamWriter,
        rep: int,
        bind_host: str = "0.0.0.0",
        bind_port: int = 0,
    ) -> None:
        try:
            import ipaddress
            addr = ipaddress.ip_address(bind_host)
            if addr.version == 4:
                atyp = _ATYP_IPV4
                addr_bytes = addr.packed
            else:
                atyp = _ATYP_IPV6
                addr_bytes = addr.packed
        except ValueError:
            # Domain — use 0.0.0.0
            atyp = _ATYP_IPV4
            addr_bytes = b"\x00\x00\x00\x00"

        port_bytes = struct.pack("!H", bind_port)
        writer.write(bytes([_SOCKS_VER, rep, 0x00, atyp]) + addr_bytes + port_bytes)
