"""Money is stored as integer minor units (e.g. paisa/cents) to avoid float errors."""


def format_money(minor: int, currency: str = "PKR") -> str:
    sign = "-" if minor < 0 else ""
    minor = abs(int(minor))
    return f"{sign}{currency} {minor // 100:,}.{minor % 100:02d}"


def spoken_money(minor: int, currency: str = "PKR") -> str:
    """Price as it should be SPOKEN: '1299 rupees' / '120 rupees 50 paisa' (no commas, no 'PKR 1,299.00')."""
    minor = abs(int(minor))
    major, frac = divmod(minor, 100)
    if currency.upper() == "PKR":
        return f"{major} rupees" + (f" {frac} paisa" if frac else "")
    return f"{major} {currency}" + (f" {frac:02d}" if frac else "")
