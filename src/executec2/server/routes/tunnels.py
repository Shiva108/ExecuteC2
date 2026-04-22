"""Tunnel routes — Phase 11 implementation."""


import msgpack
from fastapi import APIRouter, Depends, HTTPException, Request, status

from executec2.server.auth import (
    ROLE_ADMIN,
    ROLE_OPERATOR,
    ROLE_VIEWER,
    enforce_limit,
    limit_key_user_ip,
    require_roles,
)
from executec2.server.broker import MessageBroker
from executec2.server.models import (
    BrokerMessage,
    BrokerMsgType,
    SyncPacketType,
    TunnelData,
    TunnelType,
    TokenClaims,
)
from executec2.tunnels import TunnelManager

router = APIRouter(prefix="/api/tunnels", tags=["tunnels"])

def _get_tunnel_manager(request: Request) -> TunnelManager:
    if not hasattr(request.app.state, "tunnel_manager"):
        request.app.state.tunnel_manager = TunnelManager()
    return request.app.state.tunnel_manager


@router.get("")
async def list_tunnels(
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_VIEWER, ROLE_OPERATOR, ROLE_ADMIN)),
):
    db = request.app.state.db
    tunnels = await db.tunnel_list()
    return [t.model_dump(mode="json") for t in tunnels]


@router.post("/socks5", status_code=status.HTTP_201_CREATED)
async def create_socks5(
    body: dict,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_ADMIN)),
):
    enforce_limit(request, "tunnel_mutation", limit_key_user_ip(request, claims.username))
    agent_id = body.get("agent_id")
    lhost = body.get("lhost", "127.0.0.1")
    lport = body.get("lport")
    use_auth = body.get("use_auth", False)
    socks_user = body.get("username", "")
    socks_pass = body.get("password", "")

    if not agent_id or not lport:
        raise HTTPException(status_code=400, detail="agent_id and lport required")

    db = request.app.state.db
    if await db.agent_get(agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    mgr = _get_tunnel_manager(request)
    try:
        tunnel_id = await mgr.create_socks5(
            agent_id=agent_id,
            lhost=lhost,
            lport=int(lport),
            use_auth=use_auth,
            username=socks_user,
            password=socks_pass,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start SOCKS5: {e}")

    tunnel = TunnelData(
        tunnel_id=tunnel_id,
        agent_id=agent_id,
        tunnel_type=TunnelType.SOCKS5,
        info=body.get("info", ""),
        lhost=lhost,
        lport=int(lport),
        use_auth=use_auth,
        username=socks_user,
        password="",
    )
    await db.tunnel_insert(tunnel)

    broker: MessageBroker = request.app.state.broker
    await broker.broadcast(BrokerMessage(
        msg_type=BrokerMsgType.EVENT,
        packet_type=SyncPacketType.TUNNEL_CREATE,
        data=msgpack.packb(tunnel.model_dump(mode="json")),
        category="tunnels",
    ))

    return tunnel.model_dump(mode="json")


@router.post("/lportfwd", status_code=status.HTTP_201_CREATED)
async def create_lportfwd(
    body: dict,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_ADMIN)),
):
    enforce_limit(request, "tunnel_mutation", limit_key_user_ip(request, claims.username))
    agent_id = body.get("agent_id")
    lhost = body.get("lhost", "127.0.0.1")
    lport = body.get("lport")
    thost = body.get("thost")
    tport = body.get("tport")

    if not agent_id or not lport or not thost or not tport:
        raise HTTPException(status_code=400, detail="agent_id, lport, thost, tport required")

    db = request.app.state.db
    if await db.agent_get(agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    mgr = _get_tunnel_manager(request)
    try:
        tunnel_id = await mgr.create_lportfwd(
            agent_id=agent_id,
            lhost=lhost,
            lport=int(lport),
            thost=thost,
            tport=int(tport),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start portfwd: {e}")

    tunnel = TunnelData(
        tunnel_id=tunnel_id,
        agent_id=agent_id,
        tunnel_type=TunnelType.LOCAL_PORTFWD,
        info=body.get("info", ""),
        lhost=lhost,
        lport=int(lport),
        thost=thost,
        tport=int(tport),
    )
    await db.tunnel_insert(tunnel)

    broker: MessageBroker = request.app.state.broker
    await broker.broadcast(BrokerMessage(
        msg_type=BrokerMsgType.EVENT,
        packet_type=SyncPacketType.TUNNEL_CREATE,
        data=msgpack.packb(tunnel.model_dump(mode="json")),
        category="tunnels",
    ))

    return tunnel.model_dump(mode="json")


@router.post("/{tunnel_id}/stop", status_code=status.HTTP_204_NO_CONTENT)
async def stop_tunnel(
    tunnel_id: str,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_ADMIN)),
):
    enforce_limit(request, "tunnel_mutation", limit_key_user_ip(request, claims.username))
    db = request.app.state.db
    if await db.tunnel_get(tunnel_id) is None:
        raise HTTPException(status_code=404, detail="Tunnel not found")

    mgr = _get_tunnel_manager(request)
    await mgr.stop_tunnel(tunnel_id)
    await db.tunnel_delete(tunnel_id)

    broker: MessageBroker = request.app.state.broker
    await broker.broadcast(BrokerMessage(
        msg_type=BrokerMsgType.EVENT,
        packet_type=SyncPacketType.TUNNEL_DELETE,
        data=msgpack.packb({"tunnel_id": tunnel_id}),
        category="tunnels",
    ))


@router.put("/{tunnel_id}/info", status_code=status.HTTP_204_NO_CONTENT)
async def update_tunnel_info(
    tunnel_id: str,
    body: dict,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_ADMIN)),
):
    enforce_limit(request, "tunnel_mutation", limit_key_user_ip(request, claims.username))
    db = request.app.state.db
    if await db.tunnel_get(tunnel_id) is None:
        raise HTTPException(status_code=404, detail="Tunnel not found")

    info = body.get("info", "")
    await db.tunnel_update(tunnel_id, info=info)

    broker: MessageBroker = request.app.state.broker
    await broker.broadcast(BrokerMessage(
        msg_type=BrokerMsgType.EVENT,
        packet_type=SyncPacketType.TUNNEL_UPDATE,
        data=msgpack.packb({"tunnel_id": tunnel_id, "info": info}),
        category="tunnels",
    ))
