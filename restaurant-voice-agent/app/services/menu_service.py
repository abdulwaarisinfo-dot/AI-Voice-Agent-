"""Menu queries. Every query is scoped by restaurant_id."""
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher

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


# --- Urdu / Arabic-script support -------------------------------------------------------------------------------------
# Customers speak Urdu, the transcript may arrive in Urdu script ("ملائی بوٹی") while the menu says "Chicken Malai Boti".
# Arabic-script words are converted to Latin letters ONLY to compare spellings (never shown to the customer), and
# spellings are compared by sound, so malai = malayi = ملائی, karahi = karhai = کڑاہی, biryani = بریانی.
_AR = {"ا": "a", "آ": "a", "أ": "a", "إ": "a", "ٱ": "a", "ب": "b", "پ": "p", "ت": "t", "ٹ": "t", "ث": "s", "ج": "j", "چ": "ch",
       "ح": "h", "خ": "kh", "د": "d", "ڈ": "d", "ذ": "z", "ر": "r", "ڑ": "r", "ز": "z", "ژ": "zh", "س": "s", "ش": "sh",
       "ص": "s", "ض": "z", "ط": "t", "ظ": "z", "ع": "a", "غ": "gh", "ف": "f", "ق": "q", "ک": "k", "ك": "k", "گ": "g",
       "ل": "l", "م": "m", "ن": "n", "ں": "n", "و": "o", "ؤ": "o", "ہ": "h", "ھ": "h", "ه": "h", "ة": "h", "ۃ": "h",
       "ء": "", "ی": "i", "ي": "i", "ى": "i", "ے": "e", "ئ": "i", "ۓ": "e"}
# Common Urdu filler words around a dish name (mujhe, order, karni, hai, price, kitne ...). They must not count as a dish word.
_URDU_STOP = set("""مجھے ہمیں مجھ میں ہم آپ آپکے کے کا کی کو سے پر پاس ہے ہیں ہو ہوں تھا ہوگا کیا کتنے کتنا کتنی قیمت ریٹ دام
آرڈر کرنا کرنی کرنے کریں کر چاہیے چاہئے چاہیئے چاہتا چاہتی چاہیں دو دیں دیجیے دیجئے دینا بتاؤ بتائیں بتائیے بتا بتانا ایک تین چار
پلیز اور بھی تو یہ وہ کوئی ڈش آئٹم مینو منگوانا منگواؤ منگوائیں لینا لوں لیں گا گی گے""".split())


def _has_non_latin(text: str) -> bool:
    return any(c.isalpha() and not unicodedata.name(c, "").startswith("LATIN") for c in (text or ""))


def _romanize(word: str) -> str:
    word = word.lower()
    if len(word) > 1 and word[-1] in "ہۃ":                      # a final heh sounds like 'a' (سموسہ = samosa), not 'h'
        word = word[:-1] + "a"
    out = []
    for c in word:
        if unicodedata.category(c) in ("Mn", "Cf"):               # vowel marks, joiners
            continue
        d = unicodedata.digit(c, None)
        out.append(str(d) if d is not None else _AR.get(c, c))
    return "".join(out)


def _latinize(text: str) -> str:
    plain = "".join(c for c in (text or "") if unicodedata.category(c) != "Mn")
    return " ".join(_romanize(w) for w in re.findall(r"\w+", plain, flags=re.UNICODE) if w not in _URDU_STOP)


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"\w+", _latinize(text).lower(), flags=re.UNICODE) if t not in _STOP]


_DIGRAPHS = (("sh", "S"), ("ch", "C"), ("kh", "K"), ("gh", "G"), ("zh", "Z"), ("ph", "f"), ("th", "t"), ("dh", "d"),
             ("bh", "b"), ("jh", "j"), ("rh", "r"), ("ck", "k"), ("q", "k"), ("x", "ks"), ("c", "k"))


def _squash(t: str) -> str:
    return re.sub(r"(.)\1+", r"\1", t)


def _skeleton(t: str) -> str:
    """Consonant skeleton: how a word 'sounds' ignoring vowel spelling (malai/malayi -> ml, chicken/چکن -> Ckn)."""
    for a, b in _DIGRAPHS:
        t = t.replace(a, b)
    return _squash(re.sub(r"[aeiouywh]", "", t))


def _same(a: str, b: str, by_sound: bool = False) -> bool:
    """Exact word match. With by_sound (used only for queries written in Urdu/other scripts, whose Latin spelling is a
    guess) words that sound the same also match. Latin queries keep the strict rule: a misspelling is only a suggestion."""
    if a == b:
        return True
    if not by_sound:
        return False
    if _squash(a) == _squash(b):                                    # naan = nan, daal = dal
        return True
    sa = _skeleton(a)
    return len(sa) >= 2 and sa == _skeleton(b)


def _fuzzy_token(a: str, b: str, by_sound: bool = False) -> bool:
    return _same(a, b, by_sound) or (len(a) >= 3 and len(b) >= 3 and SequenceMatcher(None, a, b).ratio() >= 0.8)


def search_menu(db, restaurant: dict, query: str, limit: int = 5) -> dict:
    """Deterministic, server-side check of 'is this dish on the menu?'. The model never decides this itself.

    match = exact   : the dish name equals the query
            partial : every word of the query is in the dish name/category/description
            similar : spelling/word close to a dish name (e.g. 'karhai' -> 'Chicken Karahi'); customer must confirm
            none    : not on the menu
    """
    items = list_menu(db, restaurant)
    categories = sorted({i["category"] for i in items})
    non_latin = _has_non_latin(query)
    base = {"query": query, "categories": categories, "item_count": len(items), "non_latin": non_latin}
    if not items:
        return {**base, "match": "none", "matches": [], "menu_empty": True}
    q = _tokens(query)
    if not q:
        return {**base, "match": "none", "matches": [], "menu_empty": False, "query_unclear": True}
    exact, partial, similar = [], [], []
    for it in items:
        name_t = _tokens(it["name"])
        all_t = name_t + _tokens(it["category"]) + _tokens(it["description"])
        by_sound = non_latin or _has_non_latin(it["name"])          # either side written in Urdu etc.: Latin spelling is a guess
        if len(q) == len(name_t) and all(_same(a, b, by_sound) for a, b in zip(q, name_t)):
            exact.append(it)
        elif all(any(_same(t, w, by_sound) for w in all_t) for t in q):
            partial.append(it)
        elif any(_fuzzy_token(t, w, by_sound) for t in q for w in name_t):
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
