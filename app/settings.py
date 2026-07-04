"""Configuración global del sistema (divisa, etc.)."""

from app.currencies import DEFAULT_CURRENCY, normalize_currency
from app.database import db_session

_currency_cache: str | None = None


def get_system_currency() -> str:
    global _currency_cache
    if _currency_cache is not None:
        return _currency_cache
    with db_session() as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = 'currency'"
        ).fetchone()
        if row:
            _currency_cache = normalize_currency(row["value"])
        else:
            _currency_cache = DEFAULT_CURRENCY
    return _currency_cache


def set_system_currency(code: str) -> str:
    global _currency_cache
    normalized = normalize_currency(code)
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value) VALUES ('currency', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (normalized,),
        )
        conn.execute("UPDATE users SET currency = ?", (normalized,))
        conn.execute("UPDATE daily_reports SET currency = ?", (normalized,))
    _currency_cache = normalized
    return normalized


def clear_currency_cache() -> None:
    global _currency_cache
    _currency_cache = None
