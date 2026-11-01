"""Order confirmation page + delivery-address collection, checked for BOTH channels.

Every scenario below runs twice with the same assertions:
  * voice: real sideband WebSocket path (fake OpenAI socket) -> CallController -> MongoDB (mongomock)
  * chat:  real /api/chat/message path (scripted fake Responses model)   -> CallController -> MongoDB (mongomock)
Both channels use the same tools, so the same rules must hold. No network, no real MongoDB, no OpenAI spend.
The language model itself is scripted: these tests prove the SERVER enforces the rules, not that a real model
follows the prompts (that needs a live OpenAI key and is not covered here).
"""
import json

import pytest

from app.security import order_access_token
from app.services import order_service as os_
from app.services.order_service import address_looks_complete
from app.services.prompts import backend_instructions, chat_instructions, live_instructions
from tests.conftest import SDP, FakeConnect, call_id, tool_event, wait_for
from tests.test_chat import CHAT, FakeModel, H, last_output, reply, say, start, tools
from tests.test_chat import call as fn_call

ADDRESS = "12 Canal Road, Gulberg, Faisalabad"
KARAHI = {"item_id": "a-karahi", "quantity": 2, "customizations": ["extra spicy"]}
NAAN = {"item_id": "a-naan", "quantity": 1}
ITEMS = {"items": [KARAHI, NAAN]}
DELIVERY = {"customer_name": "Sara", "phone": "03001234567", "fulfillment": "delivery", "delivery_address": ADDRESS}
PICKUP = {"customer_name": "Sara", "phone": "03001234567", "fulfillment": "pickup"}
# 2 x 1299.00 + 1 x 120.00 = 2718.00 ; delivery fee at resto-a is 150.00
SUBTOTAL, FEE = "PKR 2,718.00", "PKR 150.00"


# ---------------------------------------------------------------- channel drivers
class Voice:
    name = "voice"

    def __init__(self, c, conn):
        self.c, self.conn, self.n, self.last_hash = c, conn, 0, None
        r = c.post("/api/call/session", json={"sdp": SDP, "client_call_id": call_id()}, headers=H)
        assert r.status_code == 200, r.text
        self.hdr = {"X-Call-Secret": r.json()["call_secret"]}
        self.ctl = c.app.state.live.calls[call_id()].controller

    def _tool(self, name, args):
        self.n += 1
        cid = f"v{self.n}"
        before = self.conn.ws.types().count("response.create")
        self.conn.ws.incoming.put(tool_event(cid, name, args))
        assert wait_for(lambda: self.conn.ws.types().count("response.create") == before + 1)
        sent = [m for m in self.conn.ws.sent if m["type"] == "response.item.create" and m["item"]["call_id"] == cid]
        return json.loads(sent[-1]["item"]["output"])

    def turn(self, said, *calls):
        """The customer says something, then the agent runs these tools in order. Returns their results."""
        self.conn.ws.incoming.put({"type": "session.input_transcript.delta", "delta": said})
        if self.ctl.awaiting_customer_reply:
            assert wait_for(lambda: self.ctl.customer_replied)
        out = []
        for name, args in calls:
            res = self._tool(name, args() if callable(args) else args)
            self.last_hash = res.get("quote_hash", self.last_hash)
            out.append(res)
        return out

    def order_url(self):
        body = self.c.get(f"/api/call/status?client_call_id={call_id()}", headers=self.hdr).json()
        return body["order"]["url"] if body["order"] else None

    session_id = call_id()


class Chat:
    name = "chat"
    session_id = CHAT

    def __init__(self, c, model):
        self.c, self.model, self.n, self.last_hash, self.order = c, model, 0, None, None
        self.secret = start(c)
        self.results = []

    def _record(self, kw):
        last = kw["input"][-1]
        if isinstance(last, dict) and last.get("type") == "function_call_output":
            out = last_output(kw)
            self.results.append(out)
            self.last_hash = out.get("quote_hash", self.last_hash)

    def turn(self, said, *calls):
        self.results = []

        def tool_step(name, args):
            def step(kw):
                self._record(kw)
                self.n += 1
                return tools(fn_call(name, args() if callable(args) else args, f"c{self.n}"), rid=f"r{self.n}")
            return step

        def final(kw):
            self._record(kw)
            self.n += 1
            return reply("ok", f"r{self.n}")

        self.model.steps.extend([tool_step(n, a) for n, a in calls] + [final])
        r = say(self.c, self.secret, said)
        assert r.status_code == 200, r.text
        self.order = r.json()["order"]
        return list(self.results)

    def order_url(self):
        return self.order["url"] if self.order else None


@pytest.fixture(params=["voice", "chat"])
def d(request, make_client):
    if request.param == "voice":
        conn = FakeConnect()
        with make_client(connect=conn) as c:
            yield Voice(c, conn)
    else:
        with make_client(live_client=FakeModel()) as c:
            yield Chat(c, c.app.state.chat.client)


def confirmed_orders(db):
    return db.orders.count_documents({"status": "confirmed"})


def read_back(d, details):
    """Items -> customer details -> read-back. Returns the read-back result."""
    d.turn("two spicy karahi and a naan", ("set_order_items", ITEMS))
    res = d.turn("my details", ("set_customer_details", details), ("request_confirmation", {}))
    assert [r["ok"] for r in res] == [True, True]
    return res[-1]


def say_yes_and_confirm(d):
    res = d.turn("yes, confirm", ("confirm_order", lambda: {"quote_hash": d.last_hash, "customer_confirmed": True}))
    assert res[0]["ok"] and res[0]["confirmed"] is True
    return res[0]


# ---------------------------------------------------------------- 1 / 4: delivery + valid address + confirmed
def test_delivery_with_valid_address_is_read_back_then_confirmed_then_page_shows_it(d, db):
    rb = read_back(d, DELIVERY)["readback"]
    # the read-back has everything the customer must hear before agreeing
    assert "2 x Chicken Karahi (extra spicy) at PKR 1,299.00 each = PKR 2,598.00" in rb
    assert "1 x Garlic Naan at PKR 120.00 each = PKR 120.00" in rb
    assert f"Delivery to {ADDRESS}" in rb                      # address read back exactly as given (not lowercased)
    assert f"delivery fee {FEE}" in rb and "Total PKR 2,868.00" in rb
    # a read-back is not an order
    assert d.order_url() is None and confirmed_orders(db) == 0
    assert db.orders.find_one({"voice_session_id": d.session_id})["status"] == "awaiting_confirmation"

    done = say_yes_and_confirm(d)
    assert confirmed_orders(db) == 1
    url = d.order_url()
    assert url and url.startswith(f"/confirmation/{done['reference']}?t=")

    page = d.c.get(url)
    assert page.status_code == 200
    html = page.text
    for expected in (done["reference"], "Order confirmed", "Resto A", "Confirmed", "Delivery address", ADDRESS, "Sara",
                     "Chicken Karahi", "extra spicy", "Garlic Naan", "PKR 1,299.00", "PKR 2,598.00", "PKR 120.00",
                     SUBTOTAL, FEE, "PKR 2,868.00", "Placed", "UTC"):
        assert expected in html, expected
    assert "<dt>Order type</dt><dd>Delivery</dd>" in html and "Collect from" not in html


# ---------------------------------------------------------------- 2 / 5: delivery + missing / incomplete address
def test_delivery_without_a_usable_address_cannot_reach_confirmation(d, db):
    d.turn("two karahi and a naan", ("set_order_items", ITEMS))
    no_addr = {k: v for k, v in DELIVERY.items() if k != "delivery_address"}

    missing = d.turn("delivery please", ("set_customer_details", no_addr))[0]
    assert missing["ok"] is False and missing["error_code"] == "address_required"

    for vague in ("home", "x", "Lahore", "12345678", "   "):
        res = d.turn("it is " + (vague.strip() or "nothing"), ("set_customer_details", {**DELIVERY, "delivery_address": vague}))[0]
        assert res["ok"] is False and res["error_code"] in ("address_required", "address_incomplete"), vague
        if res["error_code"] == "address_incomplete":
            assert "full address" in res["message"] and "never guess" in res["message"]

    # no customer details were stored, so no read-back and no confirmation are possible
    blocked = d.turn("go ahead", ("request_confirmation", {}))[0]
    assert blocked["ok"] is False and blocked["error_code"] == "details_missing"
    assert d.last_hash is None
    stray = d.turn("yes", ("confirm_order", {"quote_hash": "0" * 24, "customer_confirmed": True}))[0]
    assert stray["ok"] is False
    assert confirmed_orders(db) == 0 and d.order_url() is None

    # once the customer supplies the address, the flow proceeds normally
    ok = d.turn(ADDRESS, ("set_customer_details", DELIVERY), ("request_confirmation", {}))
    assert [r["ok"] for r in ok] == [True, True]
    assert db.orders.find_one({"voice_session_id": d.session_id})["delivery_address"] == ADDRESS


# ---------------------------------------------------------------- 3 / 6: pickup never needs an address
def test_pickup_needs_no_address_and_the_page_shows_pickup_details(d, db):
    rb = read_back(d, PICKUP)["readback"]
    assert "Pickup." in rb and "Delivery" not in rb and "delivery fee" not in rb
    assert "Total PKR 2,718.00" in rb                      # no delivery fee for pickup

    done = say_yes_and_confirm(d)
    order = db.orders.find_one({"voice_session_id": d.session_id})
    assert order["status"] == "confirmed" and order["fulfillment"] == "pickup" and order["delivery_address"] is None

    html = d.c.get(d.order_url()).text
    assert done["reference"] in html and "<dt>Order type</dt><dd>Pickup</dd>" in html
    assert "Collect from Resto A" in html
    assert "Delivery address" not in html and "Delivery fee" not in html
    assert "PKR 2,718.00" in html


def test_an_address_sent_with_a_pickup_order_is_discarded(d, db):
    d.turn("pickup", ("set_order_items", ITEMS))
    d.turn("pickup", ("set_customer_details", {**PICKUP, "delivery_address": "somewhere I might never go"}))
    assert db.orders.find_one({"voice_session_id": d.session_id})["delivery_address"] is None


# ---------------------------------------------------------------- 7: declining never creates a confirmed order
def test_customer_who_declines_the_readback_gets_no_confirmed_order(d, db):
    read_back(d, DELIVERY)
    stale_hash = d.last_hash

    # the model must not confirm on its own say-so, and the server refuses even if it tries
    refused = d.turn("no, wait", ("confirm_order", {"quote_hash": stale_hash, "customer_confirmed": False}))[0]
    assert refused["ok"] is False and refused["error_code"] == "not_confirmed"
    assert confirmed_orders(db) == 0 and d.order_url() is None

    # customer changes the order instead: the old read-back is dead and cannot be confirmed
    d.turn("make it three karahi", ("set_order_items", {"items": [{**KARAHI, "quantity": 3}, NAAN]}))
    late = d.turn("yes", ("confirm_order", {"quote_hash": stale_hash, "customer_confirmed": True}))[0]
    assert late["ok"] is False and late["error_code"] == "not_read_back"
    order = db.orders.find_one({"voice_session_id": d.session_id})
    assert order["status"] == "pending" and confirmed_orders(db) == 0 and d.order_url() is None


# ---------------------------------------------------------------- 8: page shows exactly what was persisted
def test_confirmation_page_matches_the_persisted_order(d, db):
    read_back(d, DELIVERY)
    done = say_yes_and_confirm(d)
    order = db.orders.find_one({"voice_session_id": d.session_id})
    api = d.c.get("/api/orders/" + d.order_url().split("/confirmation/")[1]).json()
    html = d.c.get(d.order_url()).text

    assert api["reference"] == order["reference"] == done["reference"]
    assert api["total"] == "PKR 2,868.00" and api["delivery_address"] == order["delivery_address"] == ADDRESS
    assert [(l["name"], l["quantity"], l["customizations"]) for l in api["lines"]] == \
           [(l["name"], l["quantity"], l["customizations"]) for l in order["lines"]]
    for line in api["lines"]:
        assert line["unit_price"] in html and line["line_total"] in html and line["name"] in html
    # the displayed placement time is the persisted confirmation time
    assert order["confirmed_at"].strftime("%d %b %Y, %H:%M") in html


# ---------------------------------------------------------------- 9: invalid / foreign / unconfirmed references show nothing
def test_unknown_foreign_or_unconfirmed_references_expose_no_customer_data(d, db):
    read_back(d, DELIVERY)
    order = db.orders.find_one({"voice_session_id": d.session_id})
    secret = d.c.app.state.secret
    token = order_access_token(secret, order["_id"])
    ref = order["reference"]

    # not confirmed yet: even the CORRECT token must not show a success page
    pre = d.c.get(f"/confirmation/{ref}?t={token}")
    assert pre.status_code == 404 and "Order confirmed" not in pre.text
    assert d.c.get(f"/api/orders/{ref}?t={token}").status_code == 404

    say_yes_and_confirm(d)
    assert d.c.get(f"/confirmation/{ref}?t={token}").status_code == 200

    other = {"_id": "other-order", "reference": "ORD-ZZZZZZZZ", "restaurant_id": "resto-a", "voice_session_id": "9" * 32,
             "status": "confirmed", "lines": [], "currency": "PKR", "fulfillment": "pickup", "customer": {"name": "Zed", "phone": "0"}}
    db.orders.insert_one(other)
    wrong = [f"/confirmation/{ref}", f"/confirmation/{ref}?t=", f"/confirmation/{ref}?t=deadbeef",
             f"/confirmation/ORD-AAAAAAAA?t={token}",                               # unknown reference
             f"/confirmation/ORD-ZZZZZZZZ?t={token}",                               # someone else's order, my token
             f"/confirmation/{ref}?t={order_access_token(secret, 'other-order')}",  # my order, someone else's token
             f"/confirmation/{ref.lower()}?t={token}", "/confirmation/not-a-reference?t=x"]
    for url in wrong:
        r = d.c.get(url)
        assert r.status_code == 404, url
        for private in (ADDRESS, "Sara", "03001234567", "Zed", "Chicken Karahi", ref, "ORD-ZZZZZZZZ", "Order confirmed"):
            assert private not in r.text, (url, private)
        assert "Order not found" in r.text
        api = d.c.get(url.replace("/confirmation/", "/api/orders/"))
        assert api.status_code == 404 and ADDRESS not in api.text and "Sara" not in api.text


# ---------------------------------------------------------------- unit level
@pytest.mark.parametrize("good", ["12 Canal Rd", "House 5, Street 3, Gulberg, Faisalabad", "گلبرگ فیصل آباد",
                                  "Flat 4B Main Blvd", "  Shop 7 Jail Road  "])
def test_realistic_addresses_are_accepted(good):
    assert address_looks_complete(good)


@pytest.mark.parametrize("bad", [None, "", "   ", "x", "home", "Lahore", "12345678", "1234 5678", "ab cd", "a" * 30])
def test_vague_addresses_are_rejected(bad):
    assert not address_looks_complete(bad)


def test_pickup_and_delivery_prompts_for_both_channels_say_the_same_things():
    for text in (live_instructions("R"), backend_instructions("R"), chat_instructions("R")):
        low = text.lower()
        assert "never assume" in low or "never guess or invent an address" in low
        assert "pickup" in low and "delivery" in low and "address" in low
    for text in (live_instructions("R"), chat_instructions("R")):
        assert "do not ask for an address" in text.lower()
        assert "house or flat number, street, area and city" in text
        assert "price" in text and "final total" in text
    assert "never ask a pickup customer for an address" in backend_instructions("R").lower()
    # customer-facing sentences the existing tests rely on are still there
    assert "answers the full read-back" in live_instructions("R")
    assert "clear, simple English facts" in backend_instructions("R")


def test_readback_keeps_the_address_exactly_as_given(db):
    os_.set_items(db, "resto-a", "e" * 32, [os_.OrderLineIn(item_id="a-naan", quantity=1)])
    os_.set_customer(db, "resto-a", "e" * 32, os_.CustomerIn(customer_name="Ali", phone="03001234567",
                                                              fulfillment="delivery", delivery_address="Flat 4B, Askari Tower, DHA Phase 5"))
    assert "Delivery to Flat 4B, Askari Tower, DHA Phase 5" in os_.request_confirmation(db, "resto-a", "e" * 32)["readback"]
