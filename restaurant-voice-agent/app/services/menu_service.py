"""Menu queries. Every query is scoped by restaurant_id."""
import re
import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from datetime import datetime, timezone
from difflib import SequenceMatcher

from pydantic import ValidationError

from ..money import format_money, spoken_money
from ..models.schemas import MenuItemIn


ARCHIVED = "archived"


def is_active(restaurant: dict | None) -> bool:
    """Records created before the `status` field existed have none: they are active."""
    return restaurant is not None and restaurant.get("status") != ARCHIVED


def get_restaurant(db, restaurant_id: str, include_archived: bool = False) -> dict | None:
    """Archived restaurants are invisible by default, so they can take no new calls, logins or orders."""
    doc = db.restaurants.find_one({"_id": restaurant_id})
    return doc if include_archived or is_active(doc) else None


def public_item(doc: dict, currency: str) -> dict:
    return {
        "id": doc["_id"],
        "name": doc["name"],
        "description": doc.get("description", ""),
        "category": doc["category"],
        "price_minor": doc["price_minor"],
        "price": format_money(doc["price_minor"], currency),
        "price_spoken": spoken_money(doc["price_minor"], currency),
        "available": bool(doc["available"]),
        "options": doc.get("options", []),
    }


def list_menu(db, restaurant: dict, category: str | None = None) -> list[dict]:
    query = {"restaurant_id": restaurant["_id"]}
    if category:
        query["category"] = category
    docs = db.menu_items.find(query).sort([("category", 1), ("name", 1)])
    return [public_item(d, restaurant["currency"]) for d in docs]


def create_item(db, restaurant: dict, data: MenuItemIn) -> dict:
    now = datetime.now(timezone.utc)
    doc = {"_id": uuid.uuid4().hex, "restaurant_id": restaurant["_id"], **data.model_dump(),
           "created_at": now, "updated_at": now}
    db.menu_items.insert_one(doc)
    return public_item(doc, restaurant["currency"])


def update_item(db, restaurant: dict, item_id: str, data: MenuItemIn) -> dict | None:
    doc = db.menu_items.find_one_and_update(
        {"_id": item_id, "restaurant_id": restaurant["_id"]},
        {"$set": {**data.model_dump(), "updated_at": datetime.now(timezone.utc)}},
        return_document=True,
    )
    return public_item(doc, restaurant["currency"]) if doc else None


def set_availability(db, restaurant: dict, item_id: str, available: bool) -> dict | None:
    doc = db.menu_items.find_one_and_update(
        {"_id": item_id, "restaurant_id": restaurant["_id"]},
        {"$set": {"available": available, "updated_at": datetime.now(timezone.utc)}},
        return_document=True,
    )
    return public_item(doc, restaurant["currency"]) if doc else None


def delete_item(db, restaurant: dict, item_id: str) -> bool:
    """Hard-delete one menu item. Orders keep their own name/price snapshot, so history is unaffected;
    a pending order that still references the item fails re-pricing and cannot be confirmed."""
    res = db.menu_items.delete_one({"_id": item_id, "restaurant_id": restaurant["_id"]})
    return res.deleted_count == 1


# ---------- menu lookup for the voice agent ----------
# Filler words people say around a dish name (English + Roman Urdu). They must not count as a match.
_STOP = {"the", "a", "an", "with", "and", "of", "for", "please", "do", "you", "have", "has", "is", "are", "there", "any",
         "me", "i", "we", "want", "need", "get", "price", "rate", "cost", "how", "much", "what", "whats", "tell", "about",
         "one", "some", "order", "ka", "ki", "ke", "ko", "hai", "hain", "kya", "aap", "ap", "ke", "paas", "kitne", "kitna",
         "kitni", "chahiye", "chahie", "dena", "dedo", "mujhe", "hamein", "bata", "batao", "bataye", "menu", "mein", "main"}


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"\w+", (text or "").lower(), flags=re.UNICODE) if t not in _STOP]


def _fuzzy_token(a: str, b: str) -> bool:
    return a == b or (len(a) >= 3 and len(b) >= 3 and SequenceMatcher(None, a, b).ratio() >= 0.8)


def search_menu(db, restaurant: dict, query: str, limit: int = 5) -> dict:
    """Deterministic, server-side check of 'is this dish on the menu?'. The model never decides this itself.

    match = exact   : the dish name equals the query
            partial : every word of the query is in the dish name/category/description
            similar : spelling/word close to a dish name (e.g. 'karhai' -> 'Chicken Karahi'); customer must confirm
            none    : not on the menu
    """
    items = list_menu(db, restaurant)
    categories = sorted({i["category"] for i in items})
    base = {"query": query, "categories": categories, "item_count": len(items)}
    if not items:
        return {**base, "match": "none", "matches": [], "menu_empty": True}
    q = _tokens(query)
    if not q:
        return {**base, "match": "none", "matches": [], "menu_empty": False, "query_unclear": True}
    exact, partial, similar = [], [], []
    for it in items:
        name_t = _tokens(it["name"])
        all_t = name_t + _tokens(it["category"]) + _tokens(it["description"])
        if q == name_t:
            exact.append(it)
        elif all(any(t == w for w in all_t) for t in q):
            partial.append(it)
        elif any(_fuzzy_token(t, w) for t in q for w in name_t):
            similar.append(it)
    if exact:
        match, found = "exact", exact
    elif partial:
        match, found = "partial", partial
    elif similar:
        match, found = "similar", similar
    else:
        match, found = "none", []
    keep = ("id", "name", "description", "category", "price", "price_spoken", "available", "options")
    return {**base, "match": match, "menu_empty": False,
            "matches": [{k: i[k] for k in keep} for i in found[:limit]]}


# ---------- bulk import (JSON) ----------
def _price_minor(raw: dict) -> int:
    """Accept price_minor (integer paisa) or price (rupees, e.g. 450, 450.5, "1,299"). Decimal avoids float rounding."""
    if raw.get("price_minor") is not None:
        v = raw["price_minor"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("price_minor must be a whole number")
        return v
    if "price" not in raw:
        raise ValueError("price is required (for example \"price\": 450)")
    v = raw["price"]
    try:
        if isinstance(v, bool):
            raise InvalidOperation
        d = Decimal(str(v).replace(",", "").strip())
        if not d.is_finite() or d < 0:
            raise InvalidOperation
    except InvalidOperation:
        raise ValueError("price must be a number like 450 or 450.50") from None
    return int((d * 100).to_integral_value(rounding=ROUND_HALF_UP))


def import_items(db, restaurant: dict, raw_items: list) -> dict:
    """All-or-nothing validation: if any row is invalid NOTHING is written and every problem is reported.
    Rows whose name+category already exist (or repeat inside the file) are skipped, so re-importing never duplicates."""
    parsed, errors = [], []
    for n, raw in enumerate(raw_items, 1):
        label = raw.get("name") if isinstance(raw, dict) and isinstance(raw.get("name"), str) else ""
        try:
            if not isinstance(raw, dict):
                raise ValueError("each item must be an object like {\"name\": ..., \"category\": ..., \"price\": ...}")
            data = {k: raw[k] for k in ("name", "description", "category", "available", "options") if k in raw}
            data["price_minor"] = _price_minor(raw)
            parsed.append((n, MenuItemIn(**data)))
        except ValidationError as exc:
            msg = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            errors.append({"row": n, "name": label, "error": msg})
        except ValueError as exc:
            errors.append({"row": n, "name": label, "error": str(exc)})
    if errors:
        return {"added": 0, "skipped": [], "errors": errors, "items": []}

    rid = restaurant["_id"]
    seen = {(d["name"].strip().lower(), d["category"].strip().lower())
            for d in db.menu_items.find({"restaurant_id": rid}, {"name": 1, "category": 1})}
    now, docs, skipped = datetime.now(timezone.utc), [], []
    for n, item in parsed:
        key = (item.name.lower(), item.category.lower())
        if key in seen:
            skipped.append({"row": n, "name": item.name, "reason": "already on the menu"})
            continue
        seen.add(key)
        docs.append({"_id": uuid.uuid4().hex, "restaurant_id": rid, **item.model_dump(), "created_at": now, "updated_at": now})
    if docs:
        db.menu_items.insert_many(docs)
    return {"added": len(docs), "skipped": skipped, "errors": [],
            "items": [public_item(d, restaurant["currency"]) for d in docs]}
