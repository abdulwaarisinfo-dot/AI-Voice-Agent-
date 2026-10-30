"""Voice agent must answer ONLY from the menu in the database: prices for dishes that exist,
a clear 'not on the menu' for dishes that don't, and a refusal when there is no menu at all."""
import json
from datetime import datetime, timezone

from app.services.live_session import CallController, TOOLS
from tests.conftest import tool_event

A, CALL = "resto-a", "e" * 32


def run(ctl, name, args, cid="q1"):
    out = ctl.handle_event(tool_event(cid, name, args))
    return json.loads(out[0]["item"]["output"])


def test_price_of_existing_dish_comes_from_database(db):
    res = run(CallController(db, A, CALL), "find_menu_item", {"query": "chicken karahi"})
    assert res["ok"] and res["match"] == "exact"
    m = res["matches"][0]
    assert m["id"] == "a-karahi" and m["price"] == "PKR 1,299.00" and m["price_spoken"] == "1299 rupees"


def test_price_question_with_filler_words_still_matches(db):
    res = run(CallController(db, A, CALL), "find_menu_item", {"query": "karahi ka price kya hai"})
    assert res["match"] in ("partial", "exact") and res["matches"][0]["id"] == "a-karahi"


def test_dish_not_on_menu_is_refused(db):
    res = run(CallController(db, A, CALL), "find_menu_item", {"query": "biryani"})
    assert res["ok"] and res["match"] == "none" and res["matches"] == []
    assert "NOT on our menu" in res["instruction"] and "Do NOT guess a price" in res["instruction"]
    assert "Mains" in res["categories"]


def test_other_restaurants_dish_is_not_found(db):
    res = run(CallController(db, A, CALL), "find_menu_item", {"query": "pizza"})  # pizza exists only at resto-b
    assert res["match"] == "none"


def test_misspelling_is_only_a_suggestion(db):
    res = run(CallController(db, A, CALL), "find_menu_item", {"query": "karhai"})
    assert res["match"] == "similar" and res["matches"][0]["id"] == "a-karahi"
    assert "Do not say the requested dish exists" in res["instruction"]


def test_unavailable_dish_is_reported_unavailable(db):
    res = run(CallController(db, A, CALL), "find_menu_item", {"query": "daal mash"})
    assert res["matches"][0]["available"] is False


def test_empty_menu_means_no_orders_and_no_prices(db):
    db.restaurants.insert_one({"_id": "resto-c", "name": "Resto C", "currency": "PKR", "delivery_fee_minor": 0,
                               "accepts_pickup": True, "accepts_delivery": True})
    ctl = CallController(db, "resto-c", "f" * 32)
    found = run(ctl, "find_menu_item", {"query": "karahi"})
    assert found["menu_empty"] is True and found["match"] == "none" and "NO menu" in found["instruction"]
    menu = run(ctl, "get_menu", {}, cid="q2")
    assert menu["menu_empty"] is True and menu["items"] == [] and "do not have" in menu["instruction"]
    order = run(ctl, "set_order_items", {"items": [{"item_id": "a-karahi", "quantity": 1}]}, cid="q3")
    assert order["ok"] is False and order["error_code"] == "unknown_item"


def test_blank_query_asks_customer(db):
    res = run(CallController(db, A, CALL), "find_menu_item", {"query": "  "})
    assert res["ok"] is False and res["error_code"] == "invalid_input"


def test_new_dish_added_on_menu_page_is_found_immediately(db):
    now = datetime.now(timezone.utc)
    db.menu_items.insert_one({"_id": "a-bir", "restaurant_id": A, "name": "Chicken Biryani", "description": "", "category": "Rice",
                              "price_minor": 45000, "available": True, "options": [], "created_at": now, "updated_at": now})
    res = run(CallController(db, A, CALL), "find_menu_item", {"query": "biryani"})
    assert res["match"] == "partial" and res["matches"][0]["price_spoken"] == "450 rupees"


def test_tool_is_registered_for_the_backend_model():
    assert "find_menu_item" in {t["name"] for t in TOOLS}
