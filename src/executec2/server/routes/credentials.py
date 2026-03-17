"""Credential routes — Phase 12 implementation with at-rest encryption."""

import os
import uuid

import msgpack
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import APIRouter, Depends, HTTPException, Request, status

from executec2.server.broker import MessageBroker
from executec2.server.models import (
    BrokerMessage,
    BrokerMsgType,
    CredentialData,
    CredentialType,
    SyncPacketType,
)

router = APIRouter(prefix="/api/credentials", tags=["credentials"])

# Derive a stable encryption key from the JWT secret using HKDF
_CRED_INFO = b"credential-at-rest"


def _get_cred_key(request: Request) -> bytes:
    """Derive 32-byte AES key from JWT secret for credential encryption."""
    jwt_manager = request.app.state.jwt_manager
    hkdf = HKDF(algorithm=SHA256(), length=32, salt=None, info=_CRED_INFO)
    return hkdf.derive(jwt_manager._secret)


def _encrypt_secret(key: bytes, plaintext: str) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, plaintext.encode(), None)


def _decrypt_secret(key: bytes, blob: bytes) -> str:
    if not blob:
        return ""
    try:
        return AESGCM(key).decrypt(blob[:12], blob[12:], None).decode()
    except Exception:
        return ""


def get_current_user(request: Request):
    return request.app.state.get_current_user(request)


@router.get("")
async def list_credentials(request: Request, _=Depends(get_current_user)):
    db = request.app.state.db
    items = await db.credential_list()
    key = _get_cred_key(request)
    result = []
    for cred, blob in items:
        d = cred.model_dump(mode="json")
        d["secret"] = _decrypt_secret(key, blob)
        result.append(d)
    return result


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_credential(body: dict, request: Request, _=Depends(get_current_user)):
    db = request.app.state.db
    key = _get_cred_key(request)

    cred = CredentialData(
        cred_id=uuid.uuid4().hex,
        username=body.get("username", ""),
        secret="",  # stored encrypted separately
        realm=body.get("realm", ""),
        cred_type=CredentialType(body.get("cred_type", "password")),
        tag=body.get("tag", ""),
        source=body.get("source", ""),
        agent_id=body.get("agent_id", ""),
        host=body.get("host", ""),
    )
    secret_plaintext = body.get("secret", "")
    secret_blob = _encrypt_secret(key, secret_plaintext) if secret_plaintext else b""

    await db.credential_insert(cred, secret_blob)

    broker: MessageBroker = request.app.state.broker
    d = cred.model_dump(mode="json")
    d["secret"] = secret_plaintext
    await broker.broadcast(BrokerMessage(
        msg_type=BrokerMsgType.EVENT,
        packet_type=SyncPacketType.CREDS_CREATE,
        data=msgpack.packb(d),
        category="credentials",
    ))

    event_manager = request.app.state.event_manager
    await event_manager.emit_async("credential.add", {"cred_id": cred.cred_id})

    return d


@router.put("/{cred_id}")
async def update_credential(cred_id: str, body: dict, request: Request, _=Depends(get_current_user)):
    db = request.app.state.db
    result = await db.credential_get(cred_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Credential not found")

    cred, _ = result
    key = _get_cred_key(request)

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
        blob = _encrypt_secret(key, body["secret"]) if body["secret"] else b""
        updates["secret_blob"] = blob

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
async def delete_credential(cred_id: str, request: Request, _=Depends(get_current_user)):
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
async def tag_credential(cred_id: str, body: dict, request: Request, _=Depends(get_current_user)):
    db = request.app.state.db
    if await db.credential_get(cred_id) is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    await db.credential_update(cred_id, tag=body.get("tag", ""))
