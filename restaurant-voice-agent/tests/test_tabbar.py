"""The phone tab bar is a CSS grid. If a link is added to base.html but the grid keeps the old column count, the extra
link wraps onto a second row, the bar doubles in height and covers the page (the chat Send button became untappable)."""
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def test_tabbar_grid_has_one_column_per_link():
    html = (APP / "templates" / "base.html").read_text(encoding="utf-8")
    bar = re.search(r'<nav class="tabbar".*?</nav>', html, re.S).group(0)
    links = len(re.findall(r"<a\s", bar))
    css = (APP / "static" / "css" / "style.css").read_text(encoding="utf-8")
    rule = re.search(r"nav\.tabbar\{([^}]*)\}", css).group(1)
    cols = re.search(r"grid-template-columns:([^;]+)", rule).group(1).strip()
    repeated = re.fullmatch(r"repeat\((\d+),\s*1fr\)", cols)
    count = int(repeated.group(1)) if repeated else len(cols.split())
    assert count == links, f"tab bar has {links} links but the grid has {count} columns"
