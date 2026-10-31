"""A customer who speaks Urdu may be transcribed in Urdu script. A dish that IS on the menu must be found, and the agent must
never be told 'not on the menu' for a spelling the server could not even read (that was the Malai Boti bug)."""
import json

import mongomock

from app.services import menu_service as ms
from app.services.live_session import CallController, _search_instruction
from tests.conftest import tool_event


def make_menu():
    db = mongomock.MongoClient().db
    db.restaurants.insert_one({"_id": "r", "name": "R", "currency": "PKR"})
    rows = [("Chicken Malai Boti", "BBQ", 80000), ("Chicken Biryani", "Rice", 55000), ("Seekh Kabab", "BBQ", 65000),
            ("Mutton Karahi", "Karahi and Handi", 220000), ("Chicken Samosa", "Starters", 25000), ("Sweet Lassi", "Drinks", 30000),
            ("Roghni Naan", "Breads", 12000), ("Gulab Jamun", "Desserts", 25000)]
    for i, (n, c, p) in enumerate(rows):
        db.menu_items.insert_one({"_id": f"d{i}", "restaurant_id": "r", "name": n, "description": "", "category": c,
                                  "price_minor": p, "available": True, "options": []})
    return db, ms.get_restaurant(db, "r")


def found(db, r, q):
    res = ms.search_menu(db, r, q)
    return res, [m["name"] for m in res["matches"]]


def test_the_reported_urdu_sentence_finds_chicken_malai_boti():
    db, r = make_menu()
    res, names = found(db, r, "مجھے ملائی بوٹی آرڈر کرنی ہے")
    assert names == ["Chicken Malai Boti"] and res["match"] in ("exact", "partial") and res["non_latin"] is True
    assert res["matches"][0]["price_spoken"] == "800 rupees"
    assert "NOT on our menu" not in _search_instruction(res)


def test_common_urdu_dish_names_are_found():
    db, r = make_menu()
    for q, want in [("ملائی بوٹی", "Chicken Malai Boti"), ("چکن بریانی", "Chicken Biryani"), ("بریانی کتنے کی ہے", "Chicken Biryani"),
                    ("سیخ کباب", "Seekh Kabab"), ("مٹن کڑاہی", "Mutton Karahi"), ("مجھے ایک سموسہ چاہیے", "Chicken Samosa"),
                    ("لسی", "Sweet Lassi"), ("نان", "Roghni Naan"), ("گلاب جامن", "Gulab Jamun")]:
        _, names = found(db, r, q)
        assert names and names[0] == want, (q, names)


def test_dish_missing_from_menu_in_urdu_script_asks_for_a_retry_not_a_refusal():
    db, r = make_menu()
    res, names = found(db, r, "پیزا")
    assert res["match"] == "none" and names == []
    msg = _search_instruction(res)
    assert "Do NOT tell the customer the dish is missing yet" in msg and "English letters" in msg
    devanagari, _ = found(db, r, "शाही पनीर")                          # a script we cannot read at all: same safe behaviour
    assert "English letters" in _search_instruction(devanagari)


def test_after_the_retry_in_english_letters_the_refusal_is_final():
    db, r = make_menu()
    res, _ = found(db, r, "pizza")
    assert res["match"] == "none" and res["non_latin"] is False
    assert "is NOT on our menu" in _search_instruction(res)


def test_only_filler_words_asks_which_dish():
    db, r = make_menu()
    res, _ = found(db, r, "مجھے آرڈر کرنا ہے")
    assert res.get("query_unclear") is True and "repeat" in _search_instruction(res)


def test_latin_misspelling_is_still_only_a_suggestion():
    db, r = make_menu()
    res, names = found(db, r, "karhai")                              # unchanged behaviour for English-letter queries
    assert res["match"] == "similar" or names == []                 # never a confident match from a guessed spelling


def test_menu_written_in_urdu_script_is_found_by_english_letters():
    db, r = make_menu()
    db.menu_items.insert_one({"_id": "u1", "restaurant_id": "r", "name": "چکن کڑاہی", "description": "", "category": "Mains",
                              "price_minor": 129900, "available": True, "options": []})
    res, names = found(db, r, "chicken karahi")
    assert names and names[0] == "چکن کڑاہی"


def test_tool_call_end_to_end_with_urdu_script(monkeypatch):
    db, r = make_menu()
    ctl = CallController(db, "r", "a" * 32)
    out = ctl.handle_event(tool_event("q1", "find_menu_item", {"query": "ملائی بوٹی"}))
    res = json.loads(out[0]["item"]["output"])
    assert res["ok"] and res["matches"][0]["name"] == "Chicken Malai Boti" and "NOT on our menu" not in res["instruction"]
