from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import chat
from app.llm import LLMUnavailable
from app.routes.deps import state

router = APIRouter(prefix="/api/chat", tags=["chat"])

BUSY = "The assistant is busy, please try again in a minute."


class ChatRequest(BaseModel):
    message: str


@router.post("")
async def post_chat(body: ChatRequest, request: Request) -> dict:
    conn, cache, source = state(request)
    if not body.message.strip():
        raise HTTPException(400, "Message must not be empty")
    try:
        return await chat.handle_chat(conn, cache, source, body.message)
    except LLMUnavailable as exc:
        raise HTTPException(503, BUSY) from exc


@router.get("")
async def get_chat(request: Request) -> dict:
    conn, _, _ = state(request)
    return chat.chat_history(conn)
