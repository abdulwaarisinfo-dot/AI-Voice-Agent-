"""Bulk JSON import: 20 sample dishes, duplicates skipped, all-or-nothing validation, owner-only, per-restaurant."""
import json
from pathlib import Path

from app import import_menu
from app.models.schemas import MenuItemIn
from app.services import menu_service
from tests.test_restaurants_and_menu import H, owner_login

SAMPLE = Path(import_menu.SAMPLE)


def sample_items():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))["items"]


def test_bundled_sample_has_20_valid_unique_dishes():
    items = sample_items()
    assert len(items) == 20
    assert len({(i["name"].lower(), i["category"].lower()) for i in items}) == 20
    for i in items:
        MenuItemIn(name=i["name"], description=i["description"], category=i["category"],
                   price_minor=menu_service._price_minor(i), available=i["available"], options=i["options"])


def test_import_adds_all_20_then_skips_them_on_second_run(make_client):
    with make_client() as c:
        owner_login(c)
        before = len(c.get("/api/menu").json()["items"])
        r = c.post("/api/menu/import", json={"items": sample_items()}, headers=H)
        assert r.status_code == 200 and r.json()["added"] == 20 and r.json()["skipped"] == []
        assert len(c.get("/api/menu").json()["items"]) == before + 20
        again = c.post("/api/menu/import", json={"items": sample_items()}, headers=H).json()
        assert again["added"] == 0 and len(again["skipped"]) == 20
        assert len(c.get("/api/menu").json()["items"]) == before + 20


def test_rupee_prices_become_exact_paisa_and_duplicates_inside_the_file_are_skipped(make_client):
    with make_client() as c:
        owner_login(c)
        rows = [{"name": "A", "category": "X", "price": 450.5}, {"name": "B", "category": "X", "price": "1,299"},
                {"name": "C", "category": "X", "price": 0.29}, {"name": "D", "category": "X", "price_minor": 1000},
                {"name": "a", "category": "x", "price": 5}]                       # same as row 1 ignoring case
        r = c.post("/api/menu/import", json={"items": rows}, headers=H).json()
        assert r["added"] == 4 and r["skipped"][0]["row"] == 5
        got = {i["name"]: i["price_minor"] for i in c.get("/api/menu").json()["items"]}
        assert got["A"] == 45050 and got["B"] == 129900 and got["C"] == 29 and got["D"] == 1000


def test_one_bad_row_imports_nothing_and_names_the_row(make_client):
    with make_client() as c:
        owner_login(c)
        before = len(c.get("/api/menu").json()["items"])
        rows = [{"name": "Good", "category": "X", "price": 10}, {"name": "Bad", "category": "X", "price": "abc"},
                {"category": "X", "price": 5}, "not an object"]
        r = c.post("/api/menu/import", json={"items": rows}, headers=H)
        assert r.status_code == 422
        d = r.json()["detail"]
        assert "Nothing was imported" in d and "item 2 (Bad)" in d and "item 3" in d and "item 4" in d
        assert len(c.get("/api/menu").json()["items"]) == before          # the good row was NOT added either


def test_import_requires_owner_login_and_valid_origin(make_client):
    with make_client() as c:
        assert c.post("/api/menu/import", json={"items": sample_items()[:1]}, headers=H).status_code == 401
        owner_login(c)
        assert c.post("/api/menu/import", json={"items": sample_items()[:1]}, headers={"Origin": "http://evil.example"}).status_code in (403, 400)


def test_import_limits(make_client):
    with make_client() as c:
        owner_login(c)
        assert c.post("/api/menu/import", json={"items": []}, headers=H).status_code == 422
        many = [{"name": f"N{i}", "category": "X", "price": 1} for i in range(201)]
        assert c.post("/api/menu/import", json={"items": many}, headers=H).status_code == 422


def test_import_goes_only_to_the_logged_in_restaurant(make_client, db):
    with make_client() as c:
        owner_login(c, "resto-a")
        c.post("/api/menu/import", json={"items": [{"name": "Only A", "category": "X", "price": 10}]}, headers=H)
    assert db.menu_items.count_documents({"restaurant_id": "resto-a", "name": "Only A"}) == 1
    assert db.menu_items.count_documents({"restaurant_id": "resto-b", "name": "Only A"}) == 0


def test_imported_dish_is_immediately_known_to_the_voice_agent(make_client, db):
    with make_client() as c:
        owner_login(c)
        c.post("/api/menu/import", json={"items": sample_items()}, headers=H)
    from app.services.live_session import CallController
    from tests.conftest import tool_event
    out = CallController(db, "resto-a", "c" * 32).handle_event(tool_event("q1", "find_menu_item", {"query": "chicken biryani"}))
    res = json.loads(out[0]["item"]["output"])
    assert res["match"] == "exact" and res["matches"][0]["price_spoken"] == "550 rupees"


def test_cli_imports_sample_and_reports_bad_file(db, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(import_menu, "connect", lambda s: db)
    monkeypatch.setattr(import_menu, "get_settings", lambda: __import__("tests.conftest", fromlist=["x"]).make_settings())
    import_menu.main([])
    assert "added 20" in capsys.readouterr().out
    import_menu.main([])
    assert "added 0, skipped 20" in capsys.readouterr().out
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    try:
        import_menu.main([str(bad)])
        raise AssertionError("expected SystemExit")
    except SystemExit as e:
        assert "Cannot read" in str(e)
    bom = tmp_path / "bom.json"
    bom.write_bytes(b"\xef\xbb\xbf" + json.dumps([{"name": "Bom Dish", "category": "X", "price": 5}]).encode())
    import_menu.main([str(bom)])
    assert "added 1" in capsys.readouterr().out
