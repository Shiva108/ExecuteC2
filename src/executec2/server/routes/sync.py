"""WebSocket sync routes — operator connection and event streaming."""

import asyncio
import logging

import msgpack
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel

from executec2.server.broker import MessageBroker, encode_packet
from executec2.server.models import ClientHandler, OTPType, SyncPacketType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["sync"])

DEFAULT_SYNC_CATEGORIES = ["listeners", "agents"]


def get_current_user(request: Request) -> str:
    return request.app.state.get_current_user(request)


async def _get_db_snapshot(db, categories: list[str]) -> dict:
    """Build snapshot dict of current DB state per category."""
    snapshot: dict[str, list] = {}
    for cat in categories:
        if cat == "listeners":
            items = await db.listener_list()
            snapshot[cat] = [i.model_dump(mode="json") for i in items]
        elif cat == "agents":
            items = await db.agent_list()
            snapshot[cat] = [i.model_dump(mode="json") for i in items]
        elif cat == "tasks":
            agents = await db.agent_list()
            tasks = []
            for agent in agents:
                tasks.extend(await db.task_list(agent.id))
            snapshot[cat] = [t.model_dump(mode="json") for t in tasks]
        elif cat == "credentials":
            rows = await db.credential_list()
            snapshot[cat] = [cred.model_dump(mode="json") for cred, _ in rows]
        elif cat == "targets":
            items = await db.target_list()
            snapshot[cat] = [i.model_dump(mode="json") for i in items]
        elif cat == "downloads":
            items = await db.download_list()
            snapshot[cat] = [i.model_dump(mode="json") for i in items]
        elif cat == "chat":
            items = await db.chat_list()
            snapshot[cat] = [i.model_dump(mode="json") for i in items]
        else:
            snapshot[cat] = []
    return snapshot


async def _send_sync_sequence(ws: WebSocket, db, categories: list[str], broker: MessageBroker) -> None:
    """Send SYNC_START → category batches → SYNC_FINISH."""
    await ws.send_bytes(encode_packet(SyncPacketType.SYNC_START, msgpack.packb({})))
    snapshot = await _get_db_snapshot(db, categories)
    for category in categories:
        for frame in broker.get_presync_frames(category, snapshot):
            await ws.send_bytes(frame)
    await ws.send_bytes(encode_packet(SyncPacketType.SYNC_FINISH, msgpack.packb({})))


async def _send_loop(ws: WebSocket, client: ClientHandler) -> None:
    while True:
        frame = await client.send_queue.get()
        try:
            await ws.send_bytes(frame)
        except Exception:
            break
        finally:
            client.send_queue.task_done()


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, otp: str = ""):
    """Primary operator sync WebSocket. Requires connect-type OTP."""
    otp_store = websocket.app.state.otp_store
    entry = otp_store.validate(otp, expected_type=OTPType.CONNECT)
    if entry is None:
        await websocket.close(code=4001, reason="Invalid or expired OTP")
        return

    await websocket.accept()
    broker: MessageBroker = websocket.app.state.broker
    db = websocket.app.state.db
    event_manager = websocket.app.state.event_manager

    client = ClientHandler(ws=websocket, username=entry.username)
    client.subscriptions = set(DEFAULT_SYNC_CATEGORIES)
    broker.register(client)
    await event_manager.emit_async("client.connect", {"username": entry.username})

    try:
        await _send_sync_sequence(websocket, db, DEFAULT_SYNC_CATEGORIES, broker)
        client.synced = True
        send_task = asyncio.create_task(_send_loop(websocket, client))
        try:
            while True:
                try:
                    await asyncio.wait_for(websocket.receive_bytes(), timeout=30.0)
                except TimeoutError:
                    continue
        except WebSocketDisconnect:
            pass
        finally:
            send_task.cancel()
    finally:
        broker.unregister(client)
        await event_manager.emit_async("client.disconnect", {"username": entry.username})


@router.websocket("/channel")
async def channel_endpoint(websocket: WebSocket, otp: str = ""):
    """Data channel for tunnel traffic. Requires tunnel-type OTP."""
    otp_store = websocket.app.state.otp_store
    entry = otp_store.validate(otp, expected_type=OTPType.TUNNEL)
    if entry is None:
        await websocket.close(code=4001, reason="Invalid or expired OTP")
        return

    await websocket.accept()
    try:
        while True:
            await websocket.receive_bytes()
    except WebSocketDisconnect:
        pass


class SubscribeRequest(BaseModel):
    categories: list[str]


@router.post("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe(body: SubscribeRequest, request: Request, user: str = Depends(get_current_user)):
    """Add categories to the operator's WebSocket subscription."""
    broker: MessageBroker = request.app.state.broker
    db = request.app.state.db

    client = next((c for c in broker._clients if c.username == user), None)
    if client is None:
        raise HTTPException(status_code=404, detail="No active WebSocket connection")

    new_cats = [c for c in body.categories if c not in client.subscriptions]
    client.subscriptions.update(body.categories)

    if new_cats:
        snapshot = await _get_db_snapshot(db, new_cats)
        for cat in new_cats:
            for frame in broker.get_presync_frames(cat, snapshot):
                try:
                    client.send_queue.put_nowait(frame)
                except asyncio.QueueFull:
                    logger.warning("Client %s queue full during subscribe", user)
