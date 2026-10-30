"""The menu page must always offer Add / Edit / Delete; the server still guards every change."""


def test_menu_page_has_add_edit_delete_controls(make_client):
    with make_client() as c:
        html = c.get("/menu").text
        assert 'id="btn-add"' in html and "+ Add new item" in html
        assert 'id="btn-signin"' in html and 'id="logout"' in html and 'id="item-form"' in html
        js = c.get("/static/js/menu.js").text
        assert "'Edit'" in js and "'Delete'" in js and "Mark unavailable" in js and "asOwner" in js


def test_changes_still_need_owner_login(make_client):
    with make_client() as c:
        body = {"name": "X", "category": "Y", "price_minor": 1, "available": True, "options": []}
        assert c.post("/api/menu/items", json=body).status_code == 401
        assert c.delete("/api/menu/items/a-naan").status_code == 401
