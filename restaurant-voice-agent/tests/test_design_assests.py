"""The redesign must stay inside the Content-Security-Policy (style-src 'self', script-src 'self', img/font from self or data:)."""
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def test_templates_use_no_inline_styles_or_scripts():
    for f in (APP / "templates").glob("*.html"):
        html = f.read_text(encoding="utf-8")
        assert not re.search(r"<style\b", html), f"{f.name}: <style> is blocked by CSP"
        assert not re.search(r"\sstyle\s*=", html), f"{f.name}: style= attribute is blocked by CSP"
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), f"{f.name}: inline <script> is blocked by CSP"
        assert not re.search(r"\son[a-z]+\s*=", html), f"{f.name}: inline event handler is blocked by CSP"


def test_css_loads_only_local_fonts_and_data_images():
    css = (APP / "static" / "css" / "style.css").read_text(encoding="utf-8")
    urls = re.findall(r"url\(\s*[\"']?([^\"')]+)", css)
    assert urls and all(u.startswith(("/static/", "data:image/svg+xml")) for u in urls), urls
    assert "@import" not in css and "http://" not in css.replace("http://www.w3.org/2000/svg", "")


def test_fonts_and_favicon_are_served(make_client):
    with make_client() as c:
        font = c.get("/static/fonts/plus-jakarta-sans-latin.woff2")
        assert font.status_code == 200 and font.content[:4] == b"wOF2"
        assert c.get("/static/fonts/plus-jakarta-sans-latin-ext.woff2").status_code == 200
        assert c.get("/static/favicon.svg").status_code == 200
        css = c.get("/static/css/style.css").text
        for name in ("plus-jakarta-sans-latin.woff2", "plus-jakarta-sans-latin-ext.woff2"):
            assert name in css


def test_menu_page_has_search_categories_and_both_navs(make_client):
    with make_client() as c:
        html = c.get("/menu").text
        assert 'id="menu-search"' in html and 'id="cat-chips"' in html and 'id="menu-list"' in html
        assert 'class="top"' in html and 'class="tabbar"' in html            # desktop nav + mobile bottom nav
        assert html.count('aria-current="page"') == 2                          # current page marked in both navs
        assert 'rel="icon"' in html and 'name="theme-color"' in html
        assert "Order by voice" in html


def test_call_page_keeps_every_element_call_js_needs(make_client):
    with make_client() as c:
        html = c.get("/call").text
        for i in ("btn-call", "btn-end", "btn-cancel", "status", "status-detail", "error", "transcript", "transcript-empty",
                  "remote-audio", "order-banner", "order-text", "order-link", "support-warning"):
            assert f'id="{i}"' in html, i
tes
