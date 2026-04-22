"""Task routes — Phase 10 implementation."""

import msgpack
from fastapi import APIRouter, Depends, HTTPException, Request, status

from executec2.server.auth import ROLE_ADMIN, ROLE_OPERATOR, require_roles
from executec2.server.broker import MessageBroker
from executec2.server.models import (
    BrokerMessage,
    BrokerMsgType,
    SyncPacketType,
    TokenClaims,
)

router = APIRouter(prefix="/api", tags=["tasks"])

@router.post("/agents/{agent_id}/tasks/{task_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_task(
    agent_id: str,
    task_id: str,
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_OPERATOR, ROLE_ADMIN)),
):
    """Cancel a pending task (remove from agent queue if not yet delivered)."""
    db = request.app.state.db
    task = await db.task_get(task_id)
    if task is None or task.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.completed:
        raise HTTPException(status_code=409, detail="Task already completed")

    # Remove from in-memory queue if present
    agents: dict = request.app.state.agents
    agent = agents.get(agent_id)
    if agent is not None:
        # Drain and rebuild queue excluding this task
        pending = []
        while not agent.pending_tasks.empty():
            try:
                item = agent.pending_tasks.get_nowait()
                pending.append(item)
            except Exception:
                break
        for item in pending:
            try:
                import msgpack as _mp
                payload = _mp.unpackb(item, raw=False)
                if payload.get("task_id") != task_id:
                    agent.pending_tasks.put_nowait(item)
            except Exception:
                agent.pending_tasks.put_nowait(item)

    # Mark cancelled in DB
    await db.task_update(task_id, completed=True, message="Cancelled by operator")

    broker: MessageBroker = request.app.state.broker
    await broker.broadcast(BrokerMessage(
        msg_type=BrokerMsgType.EVENT,
        packet_type=SyncPacketType.AGENT_TASK_REMOVE,
        data=msgpack.packb({"task_id": task_id, "agent_id": agent_id}),
        category="agents",
    ))

    event_manager = request.app.state.event_manager
    await event_manager.emit_async("task.remove", {"task_id": task_id})


@router.delete("/agents/{agent_id}/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    agent_id: str,
    task_id: str,
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_OPERATOR, ROLE_ADMIN)),
):
    """Permanently delete a task record."""
    db = request.app.state.db
    task = await db.task_get(task_id)
    if task is None or task.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Task not found")

    await db.task_delete(task_id)

    broker: MessageBroker = request.app.state.broker
    await broker.broadcast(BrokerMessage(
        msg_type=BrokerMsgType.EVENT,
        packet_type=SyncPacketType.AGENT_TASK_REMOVE,
        data=msgpack.packb({"task_id": task_id, "agent_id": agent_id}),
        category="agents",
    ))
