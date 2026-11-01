"""Text chat: same tools and rules as voice, but no GPT-Live. No network, no real MongoDB, no OpenAI spend."""
import json
from types import SimpleNamespace

import pytest

from tests.conftest import KEY, FakeLive, make_settings

H = {"Origin": "http://testserver"}
CHAT = "c" * 32


def call(name, args, cid="call_1"):
    return SimpleNamespace(type="function_call", name=name, arguments=json.dumps(args), call_id=cid)


def reply(text, rid):
    return SimpleNamespace(id=rid, output=[SimpleNamespace(type="message")], output_text=text)


def tools(*calls, rid="resp"):
    return SimpleNamespace(id=rid, output=list(calls), output_text="")


class FakeModel:
    """Scripted Responses API. Each step is a response or a function(kwargs) -> response."""
    def __init__(self, *steps, fail=None):
        self.steps, self.calls, self.fail = list(steps), [], fail
        self.responses = SimpleNamespace(create=self._create)
        self.live = SimpleNamespace(create=self._no_live)  # chat must never touch GPT-Live
        self.live_used = False

    async def _no_live(self, **kw):
        self.live_used = True
        raise AssertionError("GPT-Live must not be used for chat")

    async def _create(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise self.fail
        step = self.steps.pop(0)
        return step(kw) if callable(step) else step


def last_output(kw):
    return json.loads(kw["input"][-1]["output"])


def start(c, n=CHAT, **extra):
    r = c.post("/api/chat/session", json={"client_chat_id": n, **extra}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()["chat_secret"]


def say(c, secret, text, n=CHAT):
    return c.post("/api/chat/message", json={"client_chat_id": n, "message": text},
                  headers={**H, "X-Chat-Secret": secret})


# ===== pages =====
def test_chat_page_renders_and_is_the_home_page(make_client):
    model = FakeModel()
    with make_client(live_client=model) as c:
        assert c.get("/", follow_redirects=False).headers["location"] == "/chat"
        html = c.get("/chat").text
        for i in ("chat-log", "chat-form", "chat-input", "chat-send", "chat-error", "order-banner", "order-link"):
            assert f'id="{i}"' in html, i
        assert "Welcome to Resto A" in html and "/static/js/chat.js" in html
        assert html.count('aria-current="page"') == 2
        assert c.get("/chat?restaurant_id=nope").status_code == 404
        assert KEY not in html and KEY not in c.get("/static/js/chat.js").text
    assert model.calls == [] and not model.live_used  # opening the page never reaches OpenAI


def test_chat_link_is_in_the_navigation(make_client):
    with make_client() as c:
        assert 'href="/chat?restaurant_id=resto-a"' in c.get("/menu").text
        assert "Order by voice" in c.get("/chat").text


def test_chat_setup_page_when_restaurant_missing(db):
    from fastapi.testclient import TestClient
    from app.main import create_app
    db.restaurants.delete_many({})
    app = create_app(make_settings(), db=db, live_client=FakeModel())
    with TestClient(app) as c:
        r = c.get("/chat")
        assert r.status_code == 200 and "Restaurant not configured" in r.text and "chat-form" not in r.text


# ===== conversation =====
def test_menu_question_runs_the_tool_against_the_database_and_uses_the_chat_model(make_client):
    model = FakeModel(
        tools(call("find_menu_item", {"query": "karahi"}), rid="r1"),
        lambda kw: reply(f"Chicken Karahi is {last_output(kw)['matches'][0]['price_spoken']}.", "r2"),
    )
    with make_client(live_client=model, settings=make_settings(openai_chat_model="chat-model-x")) as c:
        secret = start(c)
        r = say(c, secret, "karahi ka price?")
    assert r.status_code == 200 and "1299" in r.json()["reply"] and r.json()["order"] is None
    first, second = model.calls
    assert first["model"] == second["model"] == "chat-model-x"
    assert first["input"] == [{"role": "user", "content": "karahi ka price?"}] and first["previous_response_id"] is None
    assert second["previous_response_id"] == "r1" and second["input"][0]["type"] == "function_call_output"
    assert {t["name"] for t in first["tools"]} >= {"get_menu", "find_menu_item", "confirm_order"}
    assert "Resto A" in first["instructions"]
    assert not model.live_used


def test_chat_model_defaults_to_the_delegation_model(make_client):
    model = FakeModel(reply("Hello!", "r1"))
    with make_client(live_client=model, settings=make_settings(openai_delegation_model="delegate-1")) as c:
        assert say(c, start(c), "hi").status_code == 200
    assert model.calls[0]["model"] == "delegate-1"


def test_conversation_is_chained_with_previous_response_id(make_client):
    model = FakeModel(reply("one", "r1"), reply("two", "r2"))
    with make_client(live_client=model) as c:
        secret = start(c)
        assert say(c, secret, "hi").json()["reply"] == "one"
        assert say(c, secret, "again").json()["reply"] == "two"
    assert [k["previous_response_id"] for k in model.calls] == [None, "r1"]


def test_full_order_by_chat_and_the_chat_ends_after_confirmation(make_client, db):
    def set_customer(kw):
        assert last_output(kw)["ok"]
        return tools(call("set_customer_details", {"customer_name": "Ali", "phone": "03001234567", "fulfillment": "pickup"}, "c2"), rid="r2")

    def ask_confirm(kw):
        assert last_output(kw)["ok"]
        return tools(call("request_confirmation", {}, "c3"), rid="r3")

    def read_back(kw):
        out = last_output(kw)
        assert out["ok"] and out["quote_hash"]
        return reply(out["readback"], "r4")

    holder = {}

    def capture(kw):  # the turn after the customer said yes: the model passes the hash from its earlier tool result
        return tools(call("confirm_order", {"quote_hash": holder["hash"], "customer_confirmed": True}, "c4"), rid="r5")

    def spy_readback(kw):
        res = read_back(kw)
        holder["hash"] = db.orders.find_one({"voice_session_id": CHAT})["quote_hash"]
        return res

    model = FakeModel(
        tools(call("set_order_items", {"items": [{"item_id": "a-karahi", "quantity": 1}, {"item_id": "a-naan", "quantity": 2}]}, "c1"), rid="r1"),
        set_customer, ask_confirm, spy_readback,
        capture,
        lambda kw: reply(f"Placed! Reference {last_output(kw)['reference']}", "r6"),
    )
    with make_client(live_client=model) as c:
        secret = start(c)
        r1 = say(c, secret, "1 karahi and 2 naan, I am Ali 03001234567 pickup, please confirm")
        assert r1.status_code == 200 and r1.json()["order"] is None
        order = db.orders.find_one({"voice_session_id": CHAT})
        assert order["status"] == "awaiting_confirmation" and order["total_minor"] == 129900 + 2 * 12000  # server priced it
        r2 = say(c, secret, "yes")
        body = r2.json()
        assert body["order"]["reference"].startswith("ORD-") and body["order"]["url"].startswith("/confirmation/")
        assert db.orders.find_one({"voice_session_id": CHAT})["status"] == "confirmed"
        assert c.get(body["order"]["url"]).status_code == 200
        assert say(c, secret, "one more thing").status_code == 409  # finished chat, no second order
    assert db.orders.count_documents({}) == 1 and not model.live_used


def test_model_cannot_confirm_in_the_same_turn_as_the_read_back(make_client, db):
    """The customer must reply AFTER the read-back; the server enforces it even if the model skips ahead."""
    seen = {}

    def try_confirm(kw):
        seen["qh"] = last_output(kw)["quote_hash"]
        return tools(call("confirm_order", {"quote_hash": seen["qh"], "customer_confirmed": True}, "c5"), rid="r5")

    def after(kw):
        seen["result"] = last_output(kw)
        return reply("Please reply yes to confirm.", "r6")

    model = FakeModel(
        tools(call("set_order_items", {"items": [{"item_id": "a-naan", "quantity": 1}]}, "c1"), rid="r1"),
        tools(call("set_customer_details", {"customer_name": "Sara", "phone": "03111234567", "fulfillment": "pickup"}, "c2"), rid="r2"),
        tools(call("request_confirmation", {}, "c3"), rid="r3"),
        try_confirm, after)
    with make_client(live_client=model) as c:
        r = say(c, start(c), "1 naan, Sara 03111234567 pickup")
    assert r.status_code == 200 and r.json()["order"] is None
    assert seen["result"] == {"ok": False, "error_code": "customer_has_not_replied", "message": seen["result"]["message"]}
    assert db.orders.find_one({"voice_session_id": CHAT})["status"] == "awaiting_confirmation"


def test_chat_cannot_reach_another_restaurant_or_order(make_client, db):
    model = FakeModel(
        tools(call("set_order_items", {"items": [{"item_id": "b-pizza", "quantity": 1}]}, "c1"), rid="r1"),
        lambda kw: reply(json.dumps(last_output(kw)), "r2"))
    with make_client(live_client=model) as c:
        r = say(c, start(c), "pizza")
    assert json.loads(r.json()["reply"])["ok"] is False  # resto-b's dish is unknown to resto-a's chat
    for o in db.orders.find({}):  # at most an empty shell of THIS restaurant; resto-b's dish never got in
        assert o["restaurant_id"] == "resto-a" and o["lines"] == [] and o["status"] == "pending"


# ===== auth, limits, failures =====
def test_chat_endpoints_need_a_valid_secret_and_same_origin(make_client):
    model = FakeModel(reply("hi", "r1"))
    with make_client(live_client=model) as c:
        secret = start(c)
        assert say(c, "wrong", "hi").status_code == 404
        assert c.post("/api/chat/message", json={"client_chat_id": CHAT, "message": "hi"}, headers=H).status_code == 404
        assert say(c, secret, "hi", n="d" * 32).status_code == 404
        assert c.post("/api/chat/message", json={"client_chat_id": CHAT, "message": "hi"},
                      headers={"Origin": "http://evil.example", "X-Chat-Secret": secret}).status_code == 403
        assert c.post("/api/chat/end", json={"client_chat_id": CHAT}, headers={**H, "X-Chat-Secret": "wrong"}).status_code == 404
    assert model.calls == []  # none of the rejected requests reached OpenAI


def test_input_validation(make_client):
    with make_client(live_client=FakeModel()) as c:
        secret = start(c)
        for bad in ("", "   ", "x" * 1001):
            assert say(c, secret, bad).status_code == 422
        assert c.post("/api/chat/session", json={"client_chat_id": "nothex"}, headers=H).status_code == 422
        assert c.post("/api/chat/session", json={"client_chat_id": "e" * 32, "restaurant_id": "nope"}, headers=H).status_code == 404


def test_no_api_key_means_chat_is_unavailable(make_client):
    with make_client(live_client=FakeModel(), settings=make_settings(openai_api_key="")) as c:
        assert c.post("/api/chat/session", json={"client_chat_id": CHAT}, headers=H).status_code == 503


def test_duplicate_session_id_and_capacity(make_client):
    with make_client(live_client=FakeModel(), settings=make_settings(max_chat_sessions=1)) as c:
        start(c)
        assert c.post("/api/chat/session", json={"client_chat_id": CHAT}, headers=H).status_code == 409
        assert c.post("/api/chat/session", json={"client_chat_id": "f" * 32}, headers=H).status_code == 503


def test_message_limit_per_chat(make_client):
    model = FakeModel(reply("a", "r1"), reply("b", "r2"))
    with make_client(live_client=model, settings=make_settings(chat_max_messages=2)) as c:
        secret = start(c)
        assert say(c, secret, "1").status_code == 200 and say(c, secret, "2").status_code == 200
        assert say(c, secret, "3").status_code == 429
    assert len(model.calls) == 2


def test_rate_limit_on_new_chats(make_client):
    with make_client(live_client=FakeModel()) as c:
        codes = [c.post("/api/chat/session", json={"client_chat_id": f"{i:032x}"}, headers=H).status_code for i in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


def test_model_failure_is_a_clean_error_without_leaking_details(make_client):
    err = RuntimeError(f"upstream exploded {KEY}")
    err.status_code = 500
    with make_client(live_client=FakeModel(fail=err)) as c:
        r = say(c, start(c), "hi")
    assert r.status_code == 502 and KEY not in r.text and "exploded" not in r.text


def test_upstream_rate_limit_maps_to_503(make_client):
    err = RuntimeError("slow down")
    err.status_code = 429
    with make_client(live_client=FakeModel(fail=err)) as c:
        assert say(c, start(c), "hi").status_code == 503


def test_endless_tool_loop_is_stopped_and_not_committed(make_client):
    loop = [tools(call("get_menu", {}, f"c{i}"), rid=f"r{i}") for i in range(20)]
    model = FakeModel(*loop, reply("ok", "ok1"))
    with make_client(live_client=model) as c:
        secret = start(c)
        assert say(c, secret, "menu").status_code == 502
        n = len(model.calls)
        assert n == 8  # MAX_TOOL_ROUNDS
        model.steps = [reply("ok", "ok1")]
        assert say(c, secret, "hello?").status_code == 200
    assert model.calls[-1]["previous_response_id"] is None  # the broken turn was never chained


def test_end_forgets_the_chat(make_client):
    with make_client(live_client=FakeModel(reply("hi", "r1"))) as c:
        secret = start(c)
        assert c.post("/api/chat/end", json={"client_chat_id": CHAT}, headers={**H, "X-Chat-Secret": secret}).status_code == 200
        assert say(c, secret, "hi").status_code == 404


def test_voice_tests_helper_is_unchanged():
    assert FakeLive().calls == []
