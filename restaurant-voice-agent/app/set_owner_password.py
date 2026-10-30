"""Fix 'Invalid restaurant or password' on /menu.

    python -m app.set_owner_password                   # asks for a new password
    python -m app.set_owner_password --sample          # also add sample dishes if the menu is empty
    python -m app.set_owner_password --restaurant-id my-place

Run it from the restaurant-voice-agent folder (so .env is read). It prints which database it is using, what is in it,
then creates the restaurant if needed and sets the owner password. Safe to run again.
"""
import argparse
import getpass
from urllib.parse import urlsplit

from .config import get_settings
from .database import connect, init_indexes
from .seed import ensure_restaurant, load_sample_menu


def safe_uri(uri: str) -> str:
    """Never print the database password."""
    p = urlsplit(uri)
    host = p.hostname or "?"
    return f"{p.scheme}://{host}" + (f":{p.port}" if p.port else "")


def describe(db, restaurant_id: str) -> list[str]:
    lines = []
    ids = [d["_id"] for d in db.restaurants.find({}, {"_id": 1})]
    lines.append(f"Restaurants in this database: {ids or 'none'}")
    r = db.restaurants.find_one({"_id": restaurant_id})
    if r is None:
        lines.append(f"'{restaurant_id}': NOT FOUND (it will be created)")
    else:
        lines.append(f"'{restaurant_id}': found, status={r.get('status', 'active')}, "
                     f"owner password {'SET' if r.get('owner_password_hash') else 'MISSING'}, currency={r.get('currency', 'MISSING')}")
    lines.append(f"Dishes for '{restaurant_id}': {db.menu_items.count_documents({'restaurant_id': restaurant_id})}")
    return lines


def main(argv=None) -> None:
    s = get_settings()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--restaurant-id", default=s.default_restaurant_id)
    ap.add_argument("--password", help="avoid this on shared machines: it ends up in shell history")
    ap.add_argument("--sample", action="store_true", help="add sample dishes if the menu is empty")
    args = ap.parse_args(argv)

    print(f"Database: {s.mongodb_database} on {safe_uri(s.mongodb_uri)}")
    db = connect(s)
    try:
        init_indexes(db)
    except Exception as exc:  # noqa: BLE001 - any connection problem should end in one readable line
        raise SystemExit(f"Cannot reach MongoDB ({exc.__class__.__name__}). Start MongoDB or fix MONGODB_URI in .env.") from None
    print("\n".join(describe(db, args.restaurant_id)))

    password = args.password
    if not password:
        password = getpass.getpass("New owner password (min 6 chars): ")
        if password != getpass.getpass("Repeat password: "):
            raise SystemExit("Passwords do not match. Nothing was changed.")
    if len(password) < 6:
        raise SystemExit("Password too short (min 6). Nothing was changed.")

    state = ensure_restaurant(db, args.restaurant_id, password)
    added = load_sample_menu(db, args.restaurant_id) if args.sample else 0
    print(f"\nDone: restaurant '{args.restaurant_id}' {state}; owner password set." + (f" {added} sample dishes added." if added else ""))
    print(f"Now open /menu?restaurant_id={args.restaurant_id} and sign in with that password.")


if __name__ == "__main__":
    main()
