"""Dev bootstrap: OWNER_PASSWORD in .env becomes the owner login without running any extra command."""
import mongomock
from fastapi.testclient import TestClient

from app.bootstrap import sync_default_restaurant
from app.database import init_indexes
from app.main import create_app
from tests.conftest import make_settings


def _db():
    d = mongomock.MongoClient().db
    init_indexes(d)
    return d


def _app(db, **kw):
    return TestClient(create_app(make_settings(default_restaurant_id="my-place", owner_password="mypass123", app_env="development", **kw),
                                 db=db, live_client=None))


def _login(c, pw):
    return c.post("/api/owner/login", json={"restaurant_id": "my-place", "password": pw})


def test_empty_database_gets_restaurant_login_and_sample_menu_at_startup():
    db = _db()
    c = _app(db)
    assert _login(c, "mypass123").status_code == 200
    assert len(c.get("/api/menu").json()["items"]) == 4


def test_handmade_restaurant_without_password_is_fixed_at_startup_and_menu_left_alone():
    db = _db()
    db.restaurants.insert_one({"_id": "my-place", "name": "My Place", "currency": "PKR"})
    c = _app(db)
    assert _login(c, "mypass123").status_code == 200
    assert c.get("/api/menu").json()["items"] == []                     # existing restaurant: no surprise dishes
    assert db.restaurants.find_one({"_id": "my-place"})["name"] == "My Place"


def test_changed_env_password_replaces_the_old_one_on_restart():
    db = _db()
    _app(db)
    c = TestClient(create_app(make_settings(default_restaurant_id="my-place", owner_password="brandnew99", app_env="development"),
                              db=db, live_client=None))
    assert _login(c, "brandnew99").status_code == 200 and _login(c, "mypass123").status_code == 401


def test_dev_login_error_says_why_but_never_in_production():
    db = _db()
    c = _app(db)
    assert "Wrong password" in _login(c, "nope-nope").json()["detail"]
    assert "not found" in c.post("/api/owner/login", json={"restaurant_id": "zzz", "password": "x"}).json()["detail"]
    prod = TestClient(create_app(make_settings(default_restaurant_id="my-place", app_env="production"), db=db, live_client=None))
    assert _login(prod, "nope-nope").json()["detail"] == "Invalid restaurant or password"


def test_production_and_empty_password_do_nothing():
    db = _db()
    assert sync_default_restaurant(db, make_settings(default_restaurant_id="my-place", owner_password="x" * 10, app_env="production")) is None
    assert sync_default_restaurant(db, make_settings(default_restaurant_id="my-place", owner_password="")) is None
    assert db.restaurants.count_documents({}) == 0


def test_archived_restaurant_is_not_resurrected():
    db = _db()
    db.restaurants.insert_one({"_id": "my-place", "name": "Old", "currency": "PKR", "status": "archived"})
    assert sync_default_restaurant(db, make_settings(default_restaurant_id="my-place", owner_password="mypass123", app_env="development")) is None
    assert db.restaurants.find_one({"_id": "my-place"})["status"] == "archived"
