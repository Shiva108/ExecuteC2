"""Unit tests for SOCKS5 server and TunnelManager."""

import asyncio
import struct

from executec2.tunnels import TunnelManager
from executec2.tunnels.socks5 import _NO_AUTH, _REP_SUCCESS, _SOCKS_VER, SOCKS5Server

# ---------------------------------------------------------------------------
# SOCKS5 Server helpers
# ---------------------------------------------------------------------------


async def socks5_connect_no_auth(reader, writer, dst_host: str, dst_port: int):
    """Perform SOCKS5 no-auth handshake + CONNECT request."""
    # Auth negotiation
    writer.write(bytes([_SOCKS_VER, 1, _NO_AUTH]))
    await writer.drain()
    resp = await reader.readexactly(2)
    assert resp == bytes([_SOCKS_VER, _NO_AUTH])

    # CONNECT request (domain)
    host_bytes = dst_host.encode()
    writer.write(
        bytes([_SOCKS_VER, 0x01, 0x00, 0x03, len(host_bytes)])
        + host_bytes
        + struct.pack("!H", dst_port)
    )
    await writer.drain()

    # Read reply (at least 10 bytes for IPv4)
    reply = await reader.read(256)
    return reply


async def test_socks5_no_auth_handshake():
    """SOCKS5 server accepts no-auth connection."""
    server = SOCKS5Server(
        tunnel_id="test01",
        host="127.0.0.1",
        port=0,  # OS-assigned
        agent_id="aabbccdd",
    )
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), timeout=5
        )
        reply = await asyncio.wait_for(
            socks5_connect_no_auth(reader, writer, "example.com", 80), timeout=5
        )
        # First byte should be SOCKS version, second byte the reply code
        assert reply[0] == _SOCKS_VER
        assert reply[1] == _REP_SUCCESS
        writer.close()
    finally:
        await server.stop()


async def test_socks5_wrong_version_rejected():
    """SOCKS5 server closes connection on wrong SOCKS version."""
    server = SOCKS5Server(
        tunnel_id="test02",
        host="127.0.0.1",
        port=0,
        agent_id="aabbccdd",
    )
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), timeout=5
        )
        # Send SOCKS4 version
        writer.write(bytes([0x04, 1, 0x00]))
        await writer.drain()
        # Server should close connection
        data = await asyncio.wait_for(reader.read(100), timeout=2)
        assert data == b""  # connection closed
        writer.close()
    finally:
        await server.stop()


async def test_socks5_auth_success():
    """SOCKS5 username/password auth succeeds with correct credentials."""
    server = SOCKS5Server(
        tunnel_id="test03",
        host="127.0.0.1",
        port=0,
        agent_id="aabbccdd",
        use_auth=True,
        username="user",
        password="pass",
    )
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), timeout=5
        )
        # Auth method negotiation
        writer.write(bytes([_SOCKS_VER, 1, 0x02]))  # offer user/pass
        await writer.drain()
        resp = await asyncio.wait_for(reader.readexactly(2), timeout=5)
        assert resp[1] == 0x02  # server selected user/pass

        # Send credentials
        uname = b"user"
        passwd = b"pass"
        writer.write(bytes([0x01, len(uname)]) + uname + bytes([len(passwd)]) + passwd)
        await writer.drain()

        sub_resp = await asyncio.wait_for(reader.readexactly(2), timeout=5)
        assert sub_resp[1] == 0x00  # success

        # CONNECT request
        host_bytes = b"example.com"
        writer.write(
            bytes([_SOCKS_VER, 0x01, 0x00, 0x03, len(host_bytes)])
            + host_bytes
            + struct.pack("!H", 80)
        )
        await writer.drain()
        reply = await asyncio.wait_for(reader.read(256), timeout=5)
        assert reply[1] == _REP_SUCCESS
        writer.close()
    finally:
        await server.stop()


async def test_socks5_auth_wrong_credentials():
    """SOCKS5 auth rejects wrong username/password."""
    server = SOCKS5Server(
        tunnel_id="test04",
        host="127.0.0.1",
        port=0,
        agent_id="aabbccdd",
        use_auth=True,
        username="user",
        password="correct",
    )
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), timeout=5
        )
        writer.write(bytes([_SOCKS_VER, 1, 0x02]))
        await writer.drain()
        await asyncio.wait_for(reader.readexactly(2), timeout=5)

        uname = b"user"
        passwd = b"wrong"
        writer.write(bytes([0x01, len(uname)]) + uname + bytes([len(passwd)]) + passwd)
        await writer.drain()

        sub_resp = await asyncio.wait_for(reader.readexactly(2), timeout=5)
        assert sub_resp[1] != 0x00  # failure
        writer.close()
    finally:
        await server.stop()


# ---------------------------------------------------------------------------
# TunnelManager
# ---------------------------------------------------------------------------


async def test_tunnel_manager_create_socks5():
    mgr = TunnelManager()
    tunnel_id = await mgr.create_socks5("aabbccdd", "127.0.0.1", 0)
    assert tunnel_id in mgr.list_tunnel_ids()
    await mgr.stop_all()


async def test_tunnel_manager_stop_tunnel():
    mgr = TunnelManager()
    tunnel_id = await mgr.create_socks5("aabbccdd", "127.0.0.1", 0)
    result = await mgr.stop_tunnel(tunnel_id)
    assert result is True
    assert tunnel_id not in mgr.list_tunnel_ids()


async def test_tunnel_manager_stop_nonexistent():
    mgr = TunnelManager()
    result = await mgr.stop_tunnel("nonexistent")
    assert result is False


async def test_tunnel_manager_create_lportfwd():
    """Local port forward server binds successfully."""
    mgr = TunnelManager()
    # Use a server that will exist (localhost HTTP — just bind the port)
    tunnel_id = await mgr.create_lportfwd("aabbccdd", "127.0.0.1", 0, "127.0.0.1", 80)
    assert tunnel_id in mgr.list_tunnel_ids()
    await mgr.stop_all()
