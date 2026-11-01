"""Browser <-> backend endpoints for text chat. The browser never sees the OpenAI key, model, prompts or tools.
There is still no HTTP endpoint that creates, edits or confirms an order: only the server-side tools can."""
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from ..models.schemas import ChatMessageIn, ChatRefIn, ChatSessionIn
from ..security import client_ip, order_access_token, require_same_origin
from ..services.chat_service import ChatError
from .deps import resolve_restaurant

router = APIRouter(prefix="/api/chat", dependencies=[Depends(require_same_origin)])


def _auth(request: Request, chat_id: str, secret: str | None):
    session = request.app.state.chat.authenticate(chat_id, secret or "")
    if session is None:
        raise HTTPException(404, "Unknown chat")
    return session


@router.post("/session")
async def create_session(request: Request, body: ChatSessionIn):
    app = request.app
    if not app.state.chat_session_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many chats started. Please wait a few minutes.")
    restaurant = resolve_restaurant(request, body.restaurant_id)
    try:
        secret, greeting = await app.state.chat.create(restaurant, body.client_chat_id)
    except ChatError as exc:
        raise HTTPException(exc.status, exc.message)
    return {"chat_secret": secret, "greeting": greeting}


@router.post("/message")
async def message(request: Request, body: ChatMessageIn, x_chat_secret: str | None = Header(None)):
    app = request.app
    if not app.state.chat_message_limiter.allow(client_ip(request)):
        raise HTTPException(429, "You are sending messages too fast. Please wait a moment.")
    session = _auth(request, body.client_chat_id, x_chat_secret)
    try:
        reply = await app.state.chat.send(session, body.message)
    except ChatError as exc:
        raise HTTPException(exc.status, exc.message)
    order = app.state.db.orders.find_one({"voice_session_id": session.chat_id, "restaurant_id": session.restaurant["_id"],
                                          "status": "confirmed"})
    payload = None
    if order:
        session.done = True
        token = order_access_token(app.state.secret, order["_id"])
        payload = {"reference": order["reference"], "url": f"/confirmation/{order['reference']}?t={token}"}
    return {"reply": reply, "order": payload}


@router.post("/end")
async def end(request: Request, body: ChatRefIn, x_chat_secret: str | None = Header(None)):
    _auth(request, body.client_chat_id, x_chat_secret)
    request.app.state.chat.end(body.client_chat_id)
    return {"ok": True}
