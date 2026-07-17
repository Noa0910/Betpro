"""Gastos adicionales por cliente (COP/MXN), independientes del acumulado."""

from __future__ import annotations

from app.database import db_session
from app.services import parse_amount

EXPENSE_CURRENCIES = ("COP", "MXN")

EXPENSE_CURRENCY_LABELS = {
    "COP": "Peso colombiano (COP)",
    "MXN": "Peso mexicano (MXN)",
}


def expense_currency_choices() -> list[tuple[str, str]]:
    return [(code, EXPENSE_CURRENCY_LABELS[code]) for code in EXPENSE_CURRENCIES]


def normalize_expense_currency(code: str | None) -> str:
    value = (code or "MXN").strip().upper()
    if value not in EXPENSE_CURRENCIES:
        raise ValueError("Moneda inválida. Use COP (Colombia) o MXN (México).")
    return value


def _as_int(value) -> int:
    return int(value)


def _as_float(value) -> float:
    if value is None:
        return 0.0
    return float(value)


def list_client_expenses(user_id: int, limit: int = 100) -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT e.*, u.name AS created_by_name
            FROM client_expenses e
            LEFT JOIN users u ON u.id = e.created_by
            WHERE e.user_id = ?
            ORDER BY e.created_at DESC, e.id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["id"] = _as_int(item["id"])
            item["user_id"] = _as_int(item["user_id"])
            item["amount"] = round(_as_float(item["amount"]), 2)
            item["currency"] = normalize_expense_currency(item["currency"])
            result.append(item)
        return result


def get_client_expense_totals(user_id: int) -> dict[str, float]:
    totals = {code: 0.0 for code in EXPENSE_CURRENCIES}
    for expense in list_client_expenses(user_id):
        totals[expense["currency"]] = round(
            totals[expense["currency"]] + expense["amount"], 2
        )
    return totals


def add_client_expense(
    user_id: int,
    description: str,
    amount: str,
    currency: str,
    admin_id: int,
) -> None:
    desc = description.strip()
    if not desc:
        raise ValueError("La descripción del gasto es obligatoria")
    parsed_amount = parse_amount(amount)
    if parsed_amount <= 0:
        raise ValueError("El monto debe ser mayor a cero")
    curr = normalize_expense_currency(currency)

    with db_session() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE id = ? AND role IN ('worker', 'admin')",
            (user_id,),
        ).fetchone()
        if not user:
            raise ValueError("Cliente no encontrado")

        conn.execute(
            """
            INSERT INTO client_expenses (user_id, description, amount, currency, created_by)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, desc, parsed_amount, curr, admin_id),
        )


def delete_client_expense(expense_id: int, user_id: int) -> None:
    with db_session() as conn:
        row = conn.execute(
            "SELECT id FROM client_expenses WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        ).fetchone()
        if not row:
            raise ValueError("Gasto no encontrado")
        conn.execute("DELETE FROM client_expenses WHERE id = ?", (expense_id,))
