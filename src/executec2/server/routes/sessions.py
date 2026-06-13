"""Interactive session routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket

from executec2.server.auth import ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER, require_roles
from executec2.server.models import OTPType, SessionStatus, SessionType, TokenClaims

router = APIRouter(prefix="/api", tags=["sessions"])


@router.post("/agents/{agent_id}/shell", status_code=201)
async def create_shell_session(
    agent_id: str,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_OPERATOR, ROLE_ADMIN)),
):
    if await request.app.state.db.agent_get(agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        session = await request.app.state.session_manager.open_session(
            agent_id=agent_id,
            session_type=SessionType.SHELL,
            created_by=claims.username,
            metadata={},
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"session_id": session.session_id, "status": session.status.value}


@router.get("/sessions")
async def list_sessions(
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_VIEWER, ROLE_OPERATOR, ROLE_ADMIN)),
):
    sessions = await request.app.state.session_manager.list_sessions()
    return [session.model_dump(mode="json") for session in sessions]


@router.post("/sessions/{session_id}/stop", status_code=204)
async def stop_session(
    session_id: str,
    request: Request,
    _claims: TokenClaims = Depends(require_roles(ROLE_OPERATOR, ROLE_ADMIN)),
):
    session = await request.app.state.session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await request.app.state.session_manager.stop_session(
        session_id,
        status=SessionStatus.TERMINATED,
    )


@router.websocket("/sessions/ws")
async def session_ws(websocket: WebSocket, otp: str = "", session_id: str = ""):
    entry = websocket.app.state.otp_store.validate(otp, expected_type=OTPType.SESSION)
    if entry is None:
        await websocket.close(code=4001, reason="Invalid or expired OTP")
        return
    session = await websocket.app.state.session_manager.get_session(session_id)
    if session is None:
        await websocket.close(code=4004, reason="Unknown session")
        return
    await websocket.app.state.session_manager.attach_operator(websocket, session_id)
