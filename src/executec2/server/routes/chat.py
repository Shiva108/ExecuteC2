"""Chat route."""

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from executec2.server.auth import ROLE_ADMIN, ROLE_OPERATOR, require_roles
from executec2.server.models import ChatMessage, TokenClaims

router = APIRouter(prefix="/api/chat", tags=["chat"])

class ChatRequest(BaseModel):
    message: str


@router.post("", status_code=status.HTTP_201_CREATED)
async def send_chat(
    body: ChatRequest,
    request: Request,
    claims: TokenClaims = Depends(require_roles(ROLE_OPERATOR, ROLE_ADMIN)),
):
    db = request.app.state.db
    msg = ChatMessage(username=claims.username, message=body.message)
    msg_id = await db.chat_insert(msg)
    msg.id = msg_id
    return msg.model_dump(mode="json")
