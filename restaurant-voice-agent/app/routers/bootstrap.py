"""Development convenience: the server makes OWNER_PASSWORD (from .env) the owner login for DEFAULT_RESTAURANT_ID.

It runs inside the SERVER process with the SERVER's settings, so it can never repair a different database than the one the
page uses (the usual cause of "Invalid restaurant or password" after running a separate script).
Disabled when APP_ENV=production or OWNER_PASSWORD is empty: production restaurants are managed explicitly
(python -m app.set_owner_password, or the admin API).
"""
import logging
from pathlib import Path

from .config import Settings
from .security import verify_password
from .seed import ensure_restaurant, load_sample_menu

log = logging.getLogger("bootstrap")


def sync_default_restaurant(db, settings: Settings) -> str | None:
    """Returns 'created', 'updated', 'ok' (already correct) or None (skipped)."""
    if settings.is_production:
        return None
    if not settings.owner_password:
        log.warning("OWNER_PASSWORD is empty (cwd=%s, .env %s). Owner login only works for restaurants that already have a "
                    "password. Put OWNER_PASSWORD=... in .env and start the server from the restaurant-voice-agent folder.",
                    Path.cwd(), "found" if Path(".env").is_file() else "NOT found here")
        return None
    rid = settings.default_restaurant_id
    existing = db.restaurants.find_one({"_id": rid})
    if existing is not None and existing.get("status") == "archived":
        log.warning("Restaurant %r is archived; not touching it.", rid)
        return None
    if existing is not None and verify_password(settings.owner_password, existing.get("owner_password_hash")):
        state = "ok"
    else:
        state = ensure_restaurant(db, rid, settings.owner_password)
        if state == "created":
            load_sample_menu(db, rid)          # brand-new restaurant: start with a few placeholder dishes
    log.info("Owner login ready for restaurant %r in database %r (%s). Sign in with OWNER_PASSWORD from .env.",
             rid, getattr(db, "name", "?"), state)
    return state
