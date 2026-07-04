"""Divisas soportadas y formato de montos."""

DEFAULT_CURRENCY = "USD"

SUPPORTED_CURRENCIES: dict[str, dict[str, str]] = {
    "USD": {"label": "Dólar estadounidense (USD)", "symbol": "US$"},
    "MXN": {"label": "Peso mexicano (MXN)", "symbol": "MX$"},
    "COP": {"label": "Peso colombiano (COP)", "symbol": "COP$"},
    "EUR": {"label": "Euro (EUR)", "symbol": "€"},
}


def normalize_currency(code: str | None) -> str:
    value = (code or DEFAULT_CURRENCY).strip().upper()
    if value not in SUPPORTED_CURRENCIES:
        return DEFAULT_CURRENCY
    return value


def currency_symbol(code: str | None) -> str:
    return SUPPORTED_CURRENCIES[normalize_currency(code)]["symbol"]


def format_money(value, currency: str | None = None) -> str:
    if value is None:
        value = 0.0
    sym = currency_symbol(currency)
    amount = f"{float(value):,.2f}"
    if sym == "€":
        return f"{amount} {sym}"
    return f"{sym}{amount}"


def currency_choices() -> list[tuple[str, str]]:
    return [(code, meta["label"]) for code, meta in SUPPORTED_CURRENCIES.items()]
