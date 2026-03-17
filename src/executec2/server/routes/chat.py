"""Chat route."""

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from executec2.server.models import ChatMessage

router = APIRouter(prefix="/api/chat", tags=["chat"])


def get_current_user(request: Request):
    return request.app.state.get_current_user(request)


class ChatRequest(BaseModel):
    message: str


@router.post("", status_code=status.HTTP_201_CREATED)
async def send_chat(body: ChatRequest, request: Request, user=Depends(get_current_user)):
    db = request.app.state.db
    msg = ChatMessage(username=user, message=body.message)
    msg_id = await db.chat_insert(msg)
    msg.id = msg_id
    return msg.model_dump(mode="json")
