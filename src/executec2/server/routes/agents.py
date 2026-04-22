"""Agent routes."""

import base64
import secrets

import msgpack
from fastapi import APIRouter, Depends, HTTPException, Request, status

from executec2.server.auth import (
    ROLE_ADMIN,
    ROLE_OPERATOR,
    ROLE_VIEWER,
    enforce_limit,
    limit_key_user_ip,
    require_command_permission,
    require_roles,
)
from executec2.server.models import TaskData, TaskType, TokenClaims

router = APIRouter(prefix="/api/agents", tags=["agents"])

_EXCLUDE_FIELDS = {"session_key", "custom_data"}


def _agent_json(a) -> dict:
    return a.model_dump(mode="json", exclude=_EXCLUDE_FIELDS)


@router.get("")
async def list_agents(
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_VIEWER, ROLE_OPERATOR, ROLE_ADMIN)),
):
    db = request.app.state.db
    agents = await db.agent_list()
    return [_agent_json(a) for a in agents]


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str,
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_ADMIN)),
):
    db = request.app.state.db
    agent = await db.agent_get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found", headers={"X-Code": "NOT_FOUND"})
    await db.agent_delete(agent_id)


@router.post("/{agent_id}/commands", status_code=status.HTTP_201_CREATED)
async def execute_command(
    agent_id: str,
    body: dict,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_OPERATOR, ROLE_ADMIN)),
):
    """Dispatch a named command to an agent."""
    from executec2.agents import get_agent_class
    from executec2.commands.registry import get_registry

    enforce_limit(request, "command", limit_key_user_ip(request, claims.username))
    db = request.app.state.db
    agent_data = await db.agent_get(agent_id)
    if agent_data is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    command_name = body.get("command")
    args = body.get("args", {})
    if not command_name:
        raise HTTPException(status_code=400, detail="command is required")

    require_command_permission(command_name, claims)

    registry = get_registry()
    cmd_def = registry.get(agent_data.name, command_name)
    if cmd_def is None:
        raise HTTPException(status_code=400, detail=f"Unknown command: {command_name}")

    # Validate required args
    for arg in cmd_def.args:
        if arg.required and arg.name not in args:
            raise HTTPException(status_code=422, detail=f"Missing required argument: {arg.name}")

    # Pre-hook
    event_manager = request.app.state.event_manager
    proceed = await event_manager.emit("task.send", {"agent_id": agent_id, "command": command_name, "args": args})
    if not proceed:
        raise HTTPException(status_code=403, detail="Command blocked by pre-hook")

    # Build task payload via agent plugin
    agent_cls = get_agent_class(agent_data.name)
    plugin = agent_cls() if agent_cls else None
    if plugin is None:
        raise HTTPException(status_code=500, detail="Agent plugin not found")

    task_payload_dict = plugin.build_task(command_name, args)
    packed_payload = msgpack.packb(task_payload_dict)
    if len(packed_payload) > request.app.state.max_task_payload_bytes:
        raise HTTPException(status_code=413, detail="Task payload too large")

    # Create task record
    task_id = secrets.token_hex(4)
    command_line = command_name + (" " + str(args) if args else "")
    task = TaskData(
        task_id=task_id,
        agent_id=agent_id,
        task_type=TaskType.TASK,
        client=claims.username,
        command_line=command_line,
    )
    task.data = packed_payload

    # Dispatch via teamserver
    teamserver = request.app.state.teamserver
    await teamserver.dispatch_task(task, task.data)

    # Post-hook
    await event_manager.emit_async("task.send", {"task_id": task_id})

    return task.model_dump(mode="json", exclude={"data"})


@router.post("/{agent_id}/commands/raw", status_code=status.HTTP_201_CREATED)
async def execute_raw(
    agent_id: str,
    body: dict,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_ADMIN)),
):
    """Enqueue raw bytes as a task (bypasses registry)."""
    enforce_limit(request, "raw_command", limit_key_user_ip(request, claims.username))
    db = request.app.state.db
    if await db.agent_get(agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    raw_b64 = body.get("data")
    if not raw_b64:
        raise HTTPException(status_code=400, detail="data (base64) is required")

    try:
        raw_bytes = base64.b64decode(raw_b64)
    except Exception:
        raise HTTPException(status_code=422, detail="data must be valid base64")

    if len(raw_bytes) > request.app.state.max_task_payload_bytes:
        raise HTTPException(status_code=413, detail="Task payload too large")

    task_id = secrets.token_hex(4)
    task = TaskData(
        task_id=task_id,
        agent_id=agent_id,
        task_type=TaskType.TASK,
        client=claims.username,
        command_line="<raw>",
    )
    task.data = raw_bytes

    teamserver = request.app.state.teamserver
    await teamserver.dispatch_task(task, raw_bytes)

    return task.model_dump(mode="json", exclude={"data"})


@router.put("/{agent_id}/tag", status_code=status.HTTP_204_NO_CONTENT)
async def set_tag(
    agent_id: str,
    body: dict,
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_OPERATOR, ROLE_ADMIN)),
):
    db = request.app.state.db
    if await db.agent_get(agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    await db.agent_update(agent_id, tags=body.get("tag", ""))


@router.put("/{agent_id}/mark", status_code=status.HTTP_204_NO_CONTENT)
async def set_mark(
    agent_id: str,
    body: dict,
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_OPERATOR, ROLE_ADMIN)),
):
    db = request.app.state.db
    if await db.agent_get(agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    from executec2.server.models import AgentMark
    await db.agent_update(agent_id, mark=AgentMark(body.get("mark", "")))


@router.put("/{agent_id}/color", status_code=status.HTTP_204_NO_CONTENT)
async def set_color(
    agent_id: str,
    body: dict,
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_OPERATOR, ROLE_ADMIN)),
):
    db = request.app.state.db
    if await db.agent_get(agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    await db.agent_update(agent_id, color=body.get("color", ""))


@router.get("/{agent_id}/tasks")
async def list_tasks(
    agent_id: str,
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_VIEWER, ROLE_OPERATOR, ROLE_ADMIN)),
):
    db = request.app.state.db
    tasks = await db.task_list(agent_id)
    return [t.model_dump(mode="json", exclude={"data"}) for t in tasks]
