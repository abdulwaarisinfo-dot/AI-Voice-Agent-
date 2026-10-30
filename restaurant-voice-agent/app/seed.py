"""Optional demo data / owner-login repair.

    python -m app.seed                      # uses OWNER_PASSWORD from .env
    python -m app.set_owner_password        # same thing, but asks for the password and shows what is in the database

Creates (or repairs) ONE restaurant and, only if its menu is empty, a few SAMPLE dishes (placeholders: edit them on /menu).
Re-running it is safe: it never overwrites the restaurant's name/fees, never deletes dishes, and always (re)sets the owner password.
"""
from datetime import datetime, timezone

from .config import get_settings
from .database import connect, init_indexes
from .security import hash_password

SAMPLE = [
    ("Chicken Karahi", "Tomato-based karahi with green chilli and ginger", "Mains", 129900, ["extra spicy", "mild"]),
    ("Daal Mash", "Slow-cooked white lentils with butter", "Mains", 59900, []),
    ("Garlic Naan", "Tandoor-baked bread with garlic", "Breads", 12000, []),
    ("Mint Lassi", "Yoghurt drink with mint", "Drinks", 35000, ["no sugar"]),
]
DEFAULTS = {"name": "Demo Restaurant", "currency": "PKR", "delivery_fee_minor": 15000,
            "accepts_pickup": True, "accepts_delivery": True}


def ensure_restaurant(db, restaurant_id: str, password: str) -> str:
    """Create the restaurant if missing, fill any missing fields, un-archive it and set the owner password.
    Returns 'created' or 'updated'. Existing name/currency/fees are kept."""
    now = datetime.now(timezone.utc)
    existing = db.restaurants.find_one({"_id": restaurant_id})
    fill = {k: v for k, v in DEFAULTS.items() if existing is None or k not in existing}
    db.restaurants.update_one({"_id": restaurant_id}, {
        "$set": {**fill, "owner_password_hash": hash_password(password), "status": "active", "updated_at": now},
        "$setOnInsert": {"created_at": now}}, upsert=True)
    return "created" if existing is None else "updated"


def load_sample_menu(db, restaurant_id: str) -> int:
    """Insert the sample dishes only when this restaurant has no dishes at all. Returns how many were added."""
    if db.menu_items.count_documents({"restaurant_id": restaurant_id}) > 0:
        return 0
    now = datetime.now(timezone.utc)
    for i, (name, desc, cat, price, opts) in enumerate(SAMPLE, 1):
        db.menu_items.insert_one({"_id": f"{restaurant_id}-sample-{i}", "restaurant_id": restaurant_id, "name": name,
                                  "description": desc, "category": cat, "price_minor": price, "available": True,
                                  "options": opts, "created_at": now, "updated_at": now})
    return len(SAMPLE)


def main() -> None:
    s = get_settings()
    if not s.owner_password:
        raise SystemExit("OWNER_PASSWORD is empty. Put OWNER_PASSWORD=... in .env (run this from the restaurant-voice-agent "
                         "folder so .env is found) or use:  python -m app.set_owner_password")
    db = connect(s)
    init_indexes(db)
    state = ensure_restaurant(db, s.default_restaurant_id, s.owner_password)
    added = load_sample_menu(db, s.default_restaurant_id)
    print(f"Restaurant '{s.default_restaurant_id}' {state} in database '{s.mongodb_database}'. Owner password set from OWNER_PASSWORD.")
    print(f"Sample dishes added: {added}" + ("" if added else " (menu already had dishes, left untouched)"))


if __name__ == "__main__":
    main()
