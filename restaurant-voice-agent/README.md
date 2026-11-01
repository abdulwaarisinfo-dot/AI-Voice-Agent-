# Restaurant Voice Agent (FastAPI + MongoDB + GPT-Live voice + text chat)

A customer opens `/call`, talks to an AI order-taker in the browser (WebRTC), hears it answer, and ends up on a
confirmation page for an order that the **server** priced, validated and saved.

> This is a **browser voice call**, not a telephone call. Phone/PSTN calling needs a telephony provider
> (OpenAI documents SIP for GPT-Live) and is **not** implemented here.

## How it works

```
call.js ──SDP offer──► POST /api/call/session ──► POST api.openai.com/v1/live/sessions   (API key: server only)
        ◄─SDP answer + call_secret─┘                      │
        ◄══════════ WebRTC audio + "oai-events" data channel ══════════► OpenAI (GPT-Live)
                                                          │ delegates to a Responses model
server ◄──── sideband wss://api.openai.com/v1/live/sessions/{id}/attach ────┘
   runs the tool calls (get_menu, set_order_items, set_customer_details, request_confirmation, confirm_order)
   against MongoDB, bound to THIS call's restaurant, and returns results
```

Why this shape: the browser and the model are both untrusted. There is **no HTTP endpoint that creates, edits or
confirms an order**. Only the server-side tools can, and they are fixed to the restaurant and call that created the
session. The browser only gets the SDP answer and an opaque `call_secret` (never the API key or OpenAI session id).

Menu answers: the agent never answers from memory. `find_menu_item` (one dish) and `get_menu` (whole menu / category) read the
database on every question, so a dish added or edited on `/menu` is known to the agent immediately. Dish exists -> it says the
name and price. Dish not on the menu -> it says so plainly and invents nothing. Menu empty -> it says it cannot take orders
or quote prices. Misspelt dish ("karhai") -> it only *suggests* the close match and asks the customer to confirm.

Order lifecycle: `pending → awaiting_confirmation → confirmed`
* any change resets to `pending`; `request_confirmation` re-prices from the DB and fixes a `quote_hash`
* `confirm_order` needs that hash, re-checks availability, requires `customer_confirmed=true`, and requires that the
  customer **spoke after the read-back** (server saw an input transcript event). Atomic DB transition + one order per
  call (unique index) = idempotent, no duplicates.
* Ending/cancelling a call never confirms or discards an order. Unconfirmed orders are purged by a 24h MongoDB TTL.

## Text chat (`/chat`, the home page)
The site now opens on a **text chat**. Customers type, the assistant answers in the same language, and orders go through the
exact same tools and rules as voice (`get_menu`, `find_menu_item`, `set_order_items`, ... `confirm_order`), run by the same
`CallController`. **GPT-Live is not used for chat** (no audio, no per-minute voice billing): one Responses model
(`OPENAI_CHAT_MODEL`, empty = `OPENAI_DELEGATION_MODEL`) talks to the customer and calls the tools. Voice at `/call` is unchanged.

```
chat.js --POST /api/chat/session--> server (no OpenAI call yet; returns chat_secret)
chat.js --POST /api/chat/message (X-Chat-Secret)--> server --Responses API + tools--> OpenAI
                                                 <-- {reply, order|null}
```
* Same safety as voice: no HTTP endpoint creates/edits/confirms an order; the server prices everything; `confirm_order` needs the
  read-back `quote_hash` **and** a customer message that arrived after the read-back; one order per chat; a confirmed chat is finished.
* Memory: OpenAI keeps the conversation via `previous_response_id` (responses are stored by OpenAI under its default retention);
  the server keeps only the last response id plus the tool state, in memory (per process, like the call limiter).
* Guards: 10 new chats / IP / 10 min, 30 messages / IP / min, 1000 chars / message, `MAX_CHAT_SESSIONS`, `CHAT_MAX_MESSAGES`,
  idle chats dropped after `CHAT_IDLE_SECONDS`, tool loop capped at 8 rounds. Mongo `chat_sessions` holds metadata only (24h TTL).

**Delivery vs pickup (voice and chat, same rules):** the assistant always asks which one. Delivery needs a complete address (house or flat number, street,
area, city): the server rejects a missing or obviously incomplete one (`address_required` / `address_incomplete`), so the assistant has to ask again. Pickup never asks for an address.
The read-back lists every item with quantity, customizations and price, pickup or delivery, the address, and the total. After the customer says yes and the server confirms,
chat shows the final reply and opens `/confirmation/…` after ~2.5 s; voice does the same after ~7.5 s (time for the assistant to say the reference).

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill OPENAI_API_KEY, SESSION_SECRET, OWNER_PASSWORD (= your /menu login password)
python -m app.seed          # optional SAMPLE restaurant + dishes (placeholders, edit on /menu)
python -m app.set_owner_password --sample   # menu says "Invalid restaurant or password"? run this: shows what is in the DB and resets the owner password
uvicorn app.main:app_factory --factory --reload
```
In development (`APP_ENV=development`) the server applies `OWNER_PASSWORD` at startup: it creates the restaurant if missing and makes that password the `/menu` owner login (restart after changing it). Start the server from the `restaurant-voice-agent` folder so `.env` is found. Production never does this automatically.
Open http://localhost:8000/ (text chat) or http://localhost:8000/call (voice; microphone needs HTTPS or localhost). MongoDB must be running at `MONGODB_URI`.

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Server only. Never sent to the browser or logged. |
| `OPENAI_LIVE_MODEL` | Default `gpt-live-1` |
| `OPENAI_DELEGATION_MODEL` | Backend Responses model (docs currently suggest `gpt-6-luna`); billed separately. Check your account has access. |
| `MONGODB_URI`, `MONGODB_DATABASE` | Database |
| `DEFAULT_RESTAURANT_ID` | Restaurant used when the URL has no `?restaurant_id=` |
| `APP_ENV` | `production` requires `SESSION_SECRET` and sets secure cookies |
| `SESSION_SECRET` | Signs owner cookies and derives order-link tokens |
| `OWNER_PASSWORD` | Only used by `python -m app.seed` |
| `MAX_CALL_SECONDS`, `MAX_CONCURRENT_CALLS` | Cost guards (defaults 600 / 5) |

## Try it
* Voice: open `/call`, press **Call restaurant**, allow the mic, wait for **Connected**, order something, say yes to the read-back; once the server has saved the confirmed order the assistant says the reference, the call ends by itself a few seconds later and you land on `/confirmation/ORD-…?t=…` (you can also end the call yourself, or use the banner link).
* Menu: `/menu` → sign in with the owner password → add/edit/mark unavailable. The agent reads the DB each time.
* Cancel: while "Connecting", **Cancel** aborts the request, closes the peer connection, releases the mic, asks the server to close any session already created, and goes back.

## Tests (no OpenAI spend, no real MongoDB)
```bash
python -m pytest -q                      # services, tools, API, lifecycle, local real-WebSocket sideband test
node --test tests/frontend/call.test.mjs tests/frontend/chat.test.mjs # run the real call.js / chat.js against fake DOM/WebRTC/fetch
```

## Costs
`gpt-live-1`: **$0.05/min, billed per second**, plus **15 s billed at WebRTC init** (credited once the session runs).
**Backend model tokens and tools are billed separately** (e.g. `gpt-6-luna` tokens, any hosted tool). So $0.05/min is
not the full cost. Measure real cost: the sideband stores the `usage` from `session.closed` in `voice_sessions.usage`,
and the OpenAI usage dashboard shows backend tokens. Not added: telephony, payments.

## Limitations / honest notes
* **Not verified against real OpenAI or a real browser call** (no API key or microphone in the build environment). Verified: the contract against OpenAI docs, the SDK call signature, the real `websockets` client against a local stand-in server, and all logic with mocks.
* Sideband headers: docs say to "include the same connection headers required when creating the session"; only `Authorization` is sent. If attach is rejected, check this first.
* Tool-argument shape for `delegation.responses.tools` follows the Responses function-tool format; confirm in your first live call.
* No documented REST "delete session" exists. Cleanup is `session.close` over the sideband/data channel. If the sideband can't attach after creation, the session cannot be closed by us and its billing behaviour is unknown.
* The "customer replied after read-back" check proves the customer spoke, not that they said yes. The model still judges the yes/no; the server blocks the order until read-back + a reply + matching hash.
* `/api/call/session` is anonymous by design (public ordering). Protection: per-IP rate limit, concurrent-call cap, max duration, idle watchdog (browser heartbeat). The limiter is in-memory (per process); use Redis with several workers. Add CAPTCHA/auth for public deployment.
* Owner login is one password per restaurant (scrypt-hashed). Order status after `confirmed` (preparing, delivered…) has no staff UI yet.
* Urdu is requested in the prompts; quality depends on the model and is untested here. Delivery fee is the only fee; no tax or payments.
* Not deployed, no git operations performed.

## Add products directly in MongoDB
Collection `menu_items` in database `restaurant_voice`. Ready-made 20 dishes are in `mongodb/`:
- **Compass:** open `menu_items` -> ADD DATA -> Import JSON file -> choose `mongodb/menu_items_20.json`.
- **mongosh:** `mongosh "YOUR_MONGODB_URI" mongodb/insert_menu_items.js` (safe to run again).

`restaurant_id` must equal your restaurant's `_id` (default `demo-restaurant`) and `price_minor` is in paisa (55000 = PKR 550.00).

## Design
Pages use one stylesheet (`app/static/css/style.css`) and a self-hosted font (Plus Jakarta Sans, SIL OFL, in `app/static/fonts/`), so the
Content-Security-Policy stays strict: no inline styles or scripts, no external fonts or images. Dish tiles use emoji chosen from the dish name
(see `GLYPHS` in `app/static/js/menu.js`), so no photos are needed.
