"""Add many dishes from a JSON file.

    python -m app.import_menu                       # imports the bundled 20-dish sample
    python -m app.import_menu my_menu.json          # your own file
    python -m app.import_menu my_menu.json --restaurant-id my-place

File format: {"items": [{"name": "Chicken Karahi", "category": "Mains", "price": 1299, "description": "...",
                          "available": true, "options": ["extra spicy"]}]}   (a bare list also works; price is in rupees)
Dishes already on the menu (same name + category) are skipped, so running it twice is safe.
Run from the restaurant-voice-agent folder so .env is read. The same import is available on /menu (owner login -> Import JSON).
"""
import argparse
import json
from pathlib import Path

from .config import get_settings
from .database import connect, init_indexes
from .services import menu_service

SAMPLE = Path(__file__).parent / "static" / "data" / "menu_20_items.json"


def load_items(path: Path) -> list:
    data = json.loads(path.read_text(encoding="utf-8-sig"))      # utf-8-sig: Windows Notepad adds a BOM
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError('The file must contain {"items": [...]} or a list of dishes.')
    return items


def main(argv=None) -> None:
    s = get_settings()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?", default=str(SAMPLE))
    ap.add_argument("--restaurant-id", default=s.default_restaurant_id)
    args = ap.parse_args(argv)
    try:
        items = load_items(Path(args.file))
    except (OSError, ValueError) as exc:        # json.JSONDecodeError is a ValueError
        raise SystemExit(f"Cannot read {args.file}: {exc}") from None
    db = connect(s)
    try:
        init_indexes(db)
    except Exception as exc:  # noqa: BLE001 - one readable line for any connection problem
        raise SystemExit(f"Cannot reach MongoDB ({exc.__class__.__name__}). Start MongoDB or fix MONGODB_URI in .env.") from None
    restaurant = menu_service.get_restaurant(db, args.restaurant_id)
    if restaurant is None:
        raise SystemExit(f"Restaurant '{args.restaurant_id}' not found in database '{s.mongodb_database}'. "
                         "Start the server once (it creates it) or run: python -m app.set_owner_password")
    result = menu_service.import_items(db, restaurant, items)
    if result["errors"]:
        print("Nothing was imported. Fix these rows:")
        for e in result["errors"]:
            print(f"  item {e['row']} {e['name']!r}: {e['error']}")
        raise SystemExit(1)
    print(f"Restaurant '{args.restaurant_id}' ({s.mongodb_database}): added {result['added']}, skipped {len(result['skipped'])} already on the menu.")


if __name__ == "__main__":
    main()
