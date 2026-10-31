"""The agent must answer in the customer's language, while facts stay exactly as in the database."""
from app.services.live_session import _search_instruction
from app.services.prompts import backend_instructions, live_instructions


def test_live_prompt_follows_customers_language_not_just_english_or_urdu():
    p = live_instructions("Demo Restaurant")
    assert "whatever language the customer speaks" in p
    assert "switches language" in p and "Punjabi" in p and "French" in p       # any language, not a fixed pair
    assert "Speak English or Urdu" not in p
    assert "never translate or rename" in p                                     # dish names stay as on the menu
    assert "Never change a number" in p and "digit by digit" in p              # facts survive translation
    assert "answers the full read-back" in p                                    # 'yes' in any language only after the read-back


def test_backend_returns_plain_english_facts_and_keeps_names_untranslated():
    b = backend_instructions("Demo Restaurant")
    assert "clear, simple English facts" in b and "never translate or transliterate" in b


def test_menu_refusal_is_spoken_in_customers_language():
    r = {"query": "pizza", "match": "none", "matches": [], "categories": ["Mains"], "menu_empty": False}
    msg = _search_instruction(r)
    assert "NOT on our menu" in msg and "customer's own language" in msg and "Do NOT guess a price" in msg


def test_call_page_no_longer_promises_only_english_or_urdu(make_client):
    with make_client() as c:
        html = c.get("/call").text
        assert "in English or Urdu." not in html and "any other" in html
