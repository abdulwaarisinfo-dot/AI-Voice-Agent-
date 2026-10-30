"""'Invalid restaurant or password' + empty menu: a restaurant made by hand (no password hash) must be repairable."""
import mongomock
from fastapi.testclient import TestClient

from app import set_owner_password as tool
from app.database import init_indexes
from app.main import create_app
from app.seed import ensure_restaurant, load_sample_menu
from tests.conftest import make_settings


def _client(db):
    return TestClient(create_app(make_settings(default_restaurant_id="my-place"), db=db, live_client=None))


def _login(c, pw):
    return c.post("/api/owner/login", json={"restaurant_id": "my-place", "password": pw})


def test_handmade_restaurant_without_password_cannot_login_then_repair_fixes_it():
    db = mongomock.MongoClient().db
    init_indexes(db)
    db.restaurants.insert_one({"_id": "my-place", "name": "My Place", "currency": "PKR"})  # e.g. typed into Compass/Atlas
    c = _client(db)
    assert c.get("/menu").status_code == 200 and c.get("/api/menu").json()["items"] == []
    assert _login(c, "anything123").status_code == 401                 # the reported symptom
    assert ensure_restaurant(db, "my-place", "newpass123") == "updated"
    assert _login(c, "wrongpass").status_code == 401 and _login(c, "newpass123").status_code == 200
    kept = db.restaurants.find_one({"_id": "my-place"})
    assert kept["name"] == "My Place"                                   # repair never renames the restaurant


def test_repair_unarchives_and_fills_missing_fields():
    db = mongomock.MongoClient().db
    db.restaurants.insert_one({"_id": "my-place", "name": "My Place", "status": "archived"})
    ensure_restaurant(db, "my-place", "newpass123")
    r = db.restaurants.find_one({"_id": "my-place"})
    assert r["status"] == "active" and r["currency"] == "PKR" and r["delivery_fee_minor"] == 15000


def test_sample_menu_only_when_empty_and_ids_do_not_collide_between_restaurants():
    db = mongomock.MongoClient().db
    init_indexes(db)
    assert load_sample_menu(db, "a-place") == 4 and load_sample_menu(db, "b-place") == 4   # used to raise DuplicateKeyError
    assert load_sample_menu(db, "a-place") == 0
    assert db.menu_items.count_documents({}) == 8


def test_cli_reports_state_and_never_prints_db_password(monkeypatch, capsys):
    db = mongomock.MongoClient().db
    monkeypatch.setattr(tool, "get_settings", lambda: make_settings(default_restaurant_id="my-place",
                                                                      mongodb_uri="mongodb://user:SECRETPW@db.example.com:27017"))
    monkeypatch.setattr(tool, "connect", lambda s: db)
    tool.main(["--password", "newpass123", "--sample"])
    out = capsys.readouterr().out
    assert "SECRETPW" not in out and "db.example.com" in out and "NOT FOUND" in out and "4 sample dishes added" in out
    assert _login(_client(db), "newpass123").status_code == 200
    assert _client(db).get("/api/menu").json()["items"][0]["price"].startswith("PKR")
