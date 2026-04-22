"""Credential routes."""

import uuid

import msgpack
from fastapi import APIRouter, Depends, HTTPException, Request, status

from executec2.server.auth import ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER, require_roles
from executec2.server.broker import MessageBroker
from executec2.server.models import (
    BrokerMessage,
    BrokerMsgType,
    CredentialData,
    CredentialType,
    SyncPacketType,
    TokenClaims,
)

router = APIRouter(prefix="/api/credentials", tags=["credentials"])


@router.get("")
async def list_credentials(
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_VIEWER, ROLE_OPERATOR, ROLE_ADMIN)),
):
    db = request.app.state.db
    items = await db.credential_list()
    return [cred.model_dump(mode="json") for cred in items]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_credential(
    body: dict,
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_OPERATOR, ROLE_ADMIN)),
):
    db = request.app.state.db

    cred = CredentialData(
        cred_id=uuid.uuid4().hex,
        username=body.get("username", ""),
        secret=body.get("secret", ""),
        realm=body.get("realm", ""),
        cred_type=CredentialType(body.get("cred_type", "password")),
        tag=body.get("tag", ""),
        source=body.get("source", ""),
        agent_id=body.get("agent_id", ""),
        host=body.get("host", ""),
    )

    await db.credential_insert(cred)

    broker: MessageBroker = request.app.state.broker
    await broker.broadcast(BrokerMessage(
        msg_type=BrokerMsgType.EVENT,
        packet_type=SyncPacketType.CREDS_CREATE,
        data=msgpack.packb(cred.model_dump(mode="json")),
        category="credentials",
    ))

    event_manager = request.app.state.event_manager
    await event_manager.emit_async("credential.add", {"cred_id": cred.cred_id})

    return cred.model_dump(mode="json")


@router.put("/{cred_id}")
async def update_credential(
    cred_id: str,
    body: dict,
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_OPERATOR, ROLE_ADMIN)),
):
    db = request.app.state.db
    if await db.credential_get(cred_id) is None:
        raise HTTPException(status_code=404, detail="Credential not found")

    updates = {}
    if "username" in body:
        updates["username"] = body["username"]
    if "realm" in body:
        updates["realm"] = body["realm"]
    if "tag" in body:
        updates["tag"] = body["tag"]
    if "source" in body:
        updates["source"] = body["source"]
    if "cred_type" in body:
        updates["cred_type"] = body["cred_type"]
    if "secret" in body:
        updates["secret"] = body["secret"]

    if updates:
        await db.credential_update(cred_id, **updates)

    broker: MessageBroker = request.app.state.broker
    await broker.broadcast(BrokerMessage(
        msg_type=BrokerMsgType.EVENT,
        packet_type=SyncPacketType.CREDS_UPDATE,
        data=msgpack.packb({"cred_id": cred_id, **updates}),
        category="credentials",
    ))

    event_manager = request.app.state.event_manager
    await event_manager.emit_async("credential.edit", {"cred_id": cred_id})

    return {"cred_id": cred_id}


@router.delete("/{cred_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    cred_id: str,
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_OPERATOR, ROLE_ADMIN)),
):
    db = request.app.state.db
    if await db.credential_get(cred_id) is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    await db.credential_delete(cred_id)

    broker: MessageBroker = request.app.state.broker
    await broker.broadcast(BrokerMessage(
        msg_type=BrokerMsgType.EVENT,
        packet_type=SyncPacketType.CREDS_DELETE,
        data=msgpack.packb({"cred_id": cred_id}),
        category="credentials",
    ))

    event_manager = request.app.state.event_manager
    await event_manager.emit_async("credential.remove", {"cred_id": cred_id})


@router.put("/{cred_id}/tag", status_code=status.HTTP_204_NO_CONTENT)
async def tag_credential(
    cred_id: str,
    body: dict,
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_OPERATOR, ROLE_ADMIN)),
):
    db = request.app.state.db
    if await db.credential_get(cred_id) is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    await db.credential_update(cred_id, tag=body.get("tag", ""))
