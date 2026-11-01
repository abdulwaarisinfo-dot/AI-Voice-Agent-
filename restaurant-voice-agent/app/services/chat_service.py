"""Text chat ordering. No GPT-Live, no audio, no WebRTC.

One Responses-API model (OPENAI_CHAT_MODEL, default = OPENAI_DELEGATION_MODEL, the same backend model the voice
call delegates to) talks to the customer directly and calls the SAME tools as the voice agent. Tools are executed
by the same CallController, so pricing, menu truth, the read-back rule and the one-order-per-session guard are
identical for voice and chat. The chat session id is stored as orders.voice_session_id.

Conversation memory is kept by OpenAI via previous_response_id; this server keeps only the last response id.
State (controller + response id) is in memory, per process, like the voice call limiter.
"""
import asyncio
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..config import Settings
from ..security import hash_token
from .live_session import TOOLS, CallController
from .prompts import chat_instructions

log = logging.getLogger("chat")


class ChatError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


@dataclass
class ChatSession:
    chat_id: str
    restaurant: dict
    secret_hash: str
    controller: CallController
    last_response_id: str | None = None
    messages: int = 0
    done: bool = False                      # an order was confirmed: the chat is finished
    last_seen: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def greeting_for(restaurant_name: str) -> str:
    return (f"Hi! Welcome to {restaurant_name}. You can type in English, Urdu or any language you like. "
            "Ask about the menu or tell me what you would like to order.")


class ChatService:
    MAX_TOOL_ROUNDS = 8

    def __init__(self, db, settings: Settings, client):
        self.db, self.settings, self.client = db, settings, client
        self.sessions: dict[str, ChatSession] = {}

    # ----- housekeeping -----
    def _purge(self) -> None:
        now = time.monotonic()
        for cid, s in list(self.sessions.items()):
            if now - s.last_seen > self.settings.chat_idle_seconds and not s.lock.locked():
                self.sessions.pop(cid, None)

    def active_count(self) -> int:
        self._purge()
        return len(self.sessions)

    async def _db(self, fn, *args) -> None:
        try:
            await asyncio.to_thread(fn, *args)
        except Exception as exc:  # metadata only: never let a database hiccup break the conversation
            log.error("chat_sessions write failed: %s", type(exc).__name__)

    # ----- lifecycle -----
    async def create(self, restaurant: dict, chat_id: str) -> tuple[str, str]:
        """Returns (chat_secret, greeting). Costs nothing: no OpenAI call is made until the first message."""
        if not self.settings.openai_api_key:
            raise ChatError(503, "Chat is not configured.")
        if chat_id in self.sessions:
            raise ChatError(409, "Chat already exists.")
        if self.active_count() >= self.settings.max_chat_sessions:
            raise ChatError(503, "Chat is busy. Please try again shortly.")
        secret = secrets.token_urlsafe(24)
        self.sessions[chat_id] = ChatSession(
            chat_id, restaurant, hash_token(secret), CallController(self.db, restaurant["_id"], chat_id))
        now = datetime.now(timezone.utc)
        await self._db(self.db.chat_sessions.insert_one, {
            "_id": chat_id, "restaurant_id": restaurant["_id"], "created_at": now, "message_count": 0,
            "expires_at": now + timedelta(hours=24)})
        return secret, greeting_for(restaurant["name"])

    def authenticate(self, chat_id: str, secret: str) -> ChatSession | None:
        s = self.sessions.get(chat_id)
        if s is None or not secrets.compare_digest(s.secret_hash, hash_token(secret or "")):
            return None
        s.last_seen = time.monotonic()
        return s

    def end(self, chat_id: str) -> None:
        self.sessions.pop(chat_id, None)  # ending never confirms or discards an order (unconfirmed ones expire by TTL)

    # ----- one customer message -----
    async def send(self, s: ChatSession, text: str) -> str:
        """Runs the model + tool loop for one customer message and returns the assistant's reply text."""
        async with s.lock:
            if s.done:
                raise ChatError(409, "This order is complete. Start a new chat to order again.")
            if s.messages >= self.settings.chat_max_messages:
                raise ChatError(429, "This chat reached its message limit. Please start a new chat.")
            s.messages += 1
            # The server saw the customer speak: this is what lets confirm_order pass after a read-back.
            s.controller.handle_event({"type": "session.input_transcript.delta", "delta": text})

            instructions = chat_instructions(s.restaurant["name"])
            model = self.settings.chat_model
            prev, items = s.last_response_id, [{"role": "user", "content": text}]
            resp = None
            try:
                for _ in range(self.MAX_TOOL_ROUNDS):
                    resp = await self.client.responses.create(
                        model=model, instructions=instructions, input=items, previous_response_id=prev,
                        tools=TOOLS, tool_choice="auto", parallel_tool_calls=False)
                    prev = resp.id
                    calls = [i for i in (resp.output or []) if getattr(i, "type", None) == "function_call"]
                    if not calls:
                        break
                    items = []
                    for c in calls:
                        out = await asyncio.to_thread(s.controller.execute_tool, c.name, c.arguments or "{}")
                        items.append({"type": "function_call_output", "call_id": c.call_id, "output": json.dumps(out)})
                else:
                    resp = None  # the model kept calling tools: give up instead of looping (and paying) forever
            except Exception as exc:  # log class/status only: never the prompt, the key or the customer's text
                log.error("chat model call failed: %s status=%s", type(exc).__name__, getattr(exc, "status_code", None))
                status = 503 if getattr(exc, "status_code", None) == 429 else 502
                raise ChatError(status, "Chat is unavailable right now. Please try again.")

            if resp is None:
                raise ChatError(502, "Sorry, I could not finish that. Please try sending it again.")
            s.last_response_id = prev  # committed only after a complete turn, so it never points at an unanswered tool call
            await self._db(self.db.chat_sessions.update_one, {"_id": s.chat_id},
                           {"$set": {"last_message_at": datetime.now(timezone.utc), "message_count": s.messages}})
            return (getattr(resp, "output_text", "") or "").strip() or "Sorry, I did not catch that. Could you say it again?"
