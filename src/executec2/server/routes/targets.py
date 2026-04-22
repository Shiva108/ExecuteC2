"""Target routes — Phase 12 implementation."""

import uuid

import msgpack
from fastapi import APIRouter, Depends, HTTPException, Request, status

from executec2.server.auth import ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER, require_roles
from executec2.server.broker import MessageBroker
from executec2.server.models import (
    BrokerMessage,
    BrokerMsgType,
    SyncPacketType,
    TargetData,
    TokenClaims,
)

router = APIRouter(prefix="/api/targets", tags=["targets"])

@router.get("")
async def list_targets(
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_VIEWER, ROLE_OPERATOR, ROLE_ADMIN)),
):
    db = request.app.state.db
    items = await db.target_list()
    return [t.model_dump(mode="json") for t in items]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_target(
    body: dict,
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_OPERATOR, ROLE_ADMIN)),
):
    db = request.app.state.db

    target = TargetData(
        target_id=uuid.uuid4().hex,
        computer=body.get("computer", ""),
        domain=body.get("domain", ""),
        address=body.get("address", ""),
        os=body.get("os", ""),
        os_desc=body.get("os_desc", ""),
        tag=body.get("tag", ""),
        info=body.get("info", ""),
        alive=body.get("alive", True),
        agents=body.get("agents", []),
    )
    await db.target_insert(target)

    broker: MessageBroker = request.app.state.broker
    await broker.broadcast(BrokerMessage(
        msg_type=BrokerMsgType.EVENT,
        packet_type=SyncPacketType.TARGETS_CREATE,
        data=msgpack.packb(target.model_dump(mode="json")),
        category="targets",
    ))

    event_manager = request.app.state.event_manager
    await event_manager.emit_async("target.add", {"target_id": target.target_id})

    return target.model_dump(mode="json")


@router.put("/{target_id}")
async def update_target(
    target_id: str,
    body: dict,
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_OPERATOR, ROLE_ADMIN)),
):
    db = request.app.state.db
    if await db.target_get(target_id) is None:
        raise HTTPException(status_code=404, detail="Target not found")

    updates = {k: v for k, v in body.items() if k in {
        "computer", "domain", "address", "os", "os_desc", "tag", "info", "alive"
    }}
    if updates:
        await db.target_update(target_id, **updates)

    broker: MessageBroker = request.app.state.broker
    await broker.broadcast(BrokerMessage(
        msg_type=BrokerMsgType.EVENT,
        packet_type=SyncPacketType.TARGETS_UPDATE,
        data=msgpack.packb({"target_id": target_id, **updates}),
        category="targets",
    ))

    event_manager = request.app.state.event_manager
    await event_manager.emit_async("target.edit", {"target_id": target_id})

    return {"target_id": target_id}


@router.delete("/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target(
    target_id: str,
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_OPERATOR, ROLE_ADMIN)),
):
    db = request.app.state.db
    if await db.target_get(target_id) is None:
        raise HTTPException(status_code=404, detail="Target not found")
    await db.target_delete(target_id)

    broker: MessageBroker = request.app.state.broker
    await broker.broadcast(BrokerMessage(
        msg_type=BrokerMsgType.EVENT,
        packet_type=SyncPacketType.TARGETS_DELETE,
        data=msgpack.packb({"target_id": target_id}),
        category="targets",
    ))

    event_manager = request.app.state.event_manager
    await event_manager.emit_async("target.remove", {"target_id": target_id})


@router.put("/{target_id}/tag", status_code=status.HTTP_204_NO_CONTENT)
async def tag_target(
    target_id: str,
    body: dict,
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_OPERATOR, ROLE_ADMIN)),
):
    db = request.app.state.db
    if await db.target_get(target_id) is None:
        raise HTTPException(status_code=404, detail="Target not found")
    await db.target_update(target_id, tag=body.get("tag", ""))
