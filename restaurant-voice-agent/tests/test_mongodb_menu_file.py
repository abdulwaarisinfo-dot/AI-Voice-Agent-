"""mongodb/menu_items_20.json is inserted by hand (Compass); it must match exactly what the app expects."""
import json
from pathlib import Path

import mongomock
from bson import json_util

from app.config import Settings
from app.models.schemas import MenuItemIn
from app.services import menu_service

FILE = Path(__file__).resolve().parents[1] / "mongodb" / "menu_items_20.json"
RID = Settings(_env_file=None).default_restaurant_id


def docs():
    return json_util.loads(FILE.read_text(encoding="utf-8"))


def test_file_has_20_valid_unique_dishes_for_the_default_restaurant():
    rows = docs()
    assert len(rows) == 20 and len({r["_id"] for r in rows}) == 20
    assert len({(r["name"].lower(), r["category"].lower()) for r in rows}) == 20
    for r in rows:
        assert r["restaurant_id"] == RID and r["available"] is True
        assert isinstance(r["price_minor"], int) and r["price_minor"] % 100 == 0           # paisa, whole rupees
        MenuItemIn(name=r["name"], description=r["description"], category=r["category"],
                   price_minor=r["price_minor"], available=r["available"], options=r["options"])
        assert r["created_at"].year >= 2026 and r["updated_at"]                              # parsed as real dates


def test_dishes_inserted_by_hand_show_up_in_the_app_and_for_the_voice_agent():
    db = mongomock.MongoClient().db
    db.restaurants.insert_one({"_id": RID, "name": "R", "currency": "PKR"})
    db.menu_items.insert_many(docs())
    restaurant = menu_service.get_restaurant(db, RID)
    assert len(menu_service.list_menu(db, restaurant)) == 20
    found = menu_service.search_menu(db, restaurant, "chicken biryani")
    assert found["match"] == "exact" and found["matches"][0]["price_spoken"] == "550 rupees"


def test_the_mongosh_script_uses_the_same_ids_and_default_names():
    js = (FILE.parent / "insert_menu_items.js").read_text(encoding="utf-8")
    assert f'const RESTAURANT_ID = "{RID}"' in js and 'const DB_NAME = "restaurant_voice"' in js
    for r in json.loads(FILE.read_text(encoding="utf-8")):
        assert r["_id"] in js
