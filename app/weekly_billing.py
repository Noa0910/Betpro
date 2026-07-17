"""Cuota semanal por usuario y acumulado para pago empleado México."""

from __future__ import annotations

from datetime import date, timedelta

from app.cortes import get_corte_cutoff_date
from app.database import db_session

WEEKLY_DEDUCTION = 500.0
MEXICO_EMPLOYEE_TARGET = 3000.0


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_start_iso(report_date: str) -> str:
    return week_start(date.fromisoformat(report_date)).isoformat()


def week_label(week_start_iso_str: str) -> str:
    start = date.fromisoformat(week_start_iso_str)
    end = start + timedelta(days=6)
    return f"{start.strftime('%d/%m')} — {end.strftime('%d/%m/%Y')}"


def _report_since_filter(alias: str = "dr") -> tuple[str, list]:
    cutoff = get_corte_cutoff_date()
    if cutoff:
        return f" AND {alias}.report_date > ?", [cutoff]
    return "", []


def get_active_billable_user_ids() -> list[int]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT id FROM users
            WHERE active = 1 AND role IN ('worker', 'admin')
            ORDER BY name
            """
        ).fetchall()
        return [_as_int(r["id"]) for r in rows]


def _as_int(value) -> int:
    return int(value)


def _as_float(value) -> float:
    if value is None:
        return 0.0
    return float(value)


def get_user_work_weeks(user_id: int) -> list[str]:
    since_sql, since_params = _report_since_filter("dr")
    with db_session() as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT dr.report_date
            FROM daily_reports dr
            WHERE dr.user_id = ? AND dr.status = 'confirmed'
            {since_sql}
            ORDER BY dr.report_date
            """,
            (user_id, *since_params),
        ).fetchall()
    weeks = sorted({week_start_iso(r["report_date"]) for r in rows})
    return weeks


def get_user_weeks_batch(user_ids: list[int]) -> dict[int, list[str]]:
    if not user_ids:
        return {}
    since_sql, since_params = _report_since_filter("dr")
    placeholders = ",".join("?" * len(user_ids))
    user_weeks: dict[int, set[str]] = {uid: set() for uid in user_ids}
    with db_session() as conn:
        rows = conn.execute(
            f"""
            SELECT dr.user_id, dr.report_date
            FROM daily_reports dr
            WHERE dr.user_id IN ({placeholders}) AND dr.status = 'confirmed'
            {since_sql}
            """,
            tuple(user_ids) + tuple(since_params),
        ).fetchall()
    for row in rows:
        uid = _as_int(row["user_id"])
        user_weeks[uid].add(week_start_iso(row["report_date"]))
    return {uid: sorted(weeks) for uid, weeks in user_weeks.items()}


def get_weekly_deductions_batch(user_ids: list[int]) -> dict[int, float]:
    if not user_ids:
        return {}
    weeks_map = get_user_weeks_batch(user_ids)
    return {
        uid: round(len(weeks_map.get(uid, [])) * WEEKLY_DEDUCTION, 2)
        for uid in user_ids
    }


def apply_weekly_deductions(gross: dict[int, float]) -> dict[int, float]:
    if not gross:
        return {}
    deductions = get_weekly_deductions_batch(list(gross.keys()))
    return {
        uid: round(gross.get(uid, 0.0) - deductions.get(uid, 0.0), 2)
        for uid in gross
    }


def get_user_billing_summary(user_id: int, gross: float) -> dict:
    weeks = get_user_work_weeks(user_id)
    deduction = round(len(weeks) * WEEKLY_DEDUCTION, 2)
    return {
        "weeks_worked": len(weeks),
        "weekly_deduction_total": deduction,
        "gross_cumulative": round(gross, 2),
        "net_cumulative": round(gross - deduction, 2),
    }


def get_mexico_pay_paid_total() -> float:
    cutoff = get_corte_cutoff_date()
    with db_session() as conn:
        if cutoff:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(amount), 0) AS total
                FROM mexico_pay_payouts
                WHERE paid_at > (
                    SELECT COALESCE(accepted_at, '1970-01-01')
                    FROM cortes WHERE status = 'accepted'
                    ORDER BY period_end DESC LIMIT 1
                )
                """
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) AS total FROM mexico_pay_payouts"
            ).fetchone()
        return round(_as_float(row["total"] if row else 0), 2)


def get_mexico_pay_status() -> dict:
    user_ids = get_active_billable_user_ids()
    deductions = get_weekly_deductions_batch(user_ids)
    weeks_map = get_user_weeks_batch(user_ids)
    contributions = []
    total_accrued = 0.0

    with db_session() as conn:
        for uid in user_ids:
            row = conn.execute(
                "SELECT id, name, username, role FROM users WHERE id = ?",
                (uid,),
            ).fetchone()
            if not row:
                continue
            amount = deductions.get(uid, 0.0)
            weeks = weeks_map.get(uid, [])
            contributions.append(
                {
                    "user_id": uid,
                    "name": row["name"],
                    "username": row["username"],
                    "role": row["role"],
                    "weeks_worked": len(weeks),
                    "amount": amount,
                    "week_labels": [week_label(w) for w in weeks],
                }
            )
            total_accrued += amount

    total_accrued = round(total_accrued, 2)
    total_paid = get_mexico_pay_paid_total()
    balance = round(total_accrued - total_paid, 2)
    target = MEXICO_EMPLOYEE_TARGET
    progress_pct = round(min(100.0, (balance / target) * 100), 1) if target else 0.0
    is_complete = balance >= target

    return {
        "target": target,
        "weekly_per_person": WEEKLY_DEDUCTION,
        "total_accrued": total_accrued,
        "total_paid": total_paid,
        "balance": balance,
        "progress_pct": progress_pct,
        "is_complete": is_complete,
        "contributions": sorted(contributions, key=lambda x: x["amount"], reverse=True),
        "people_count": len(contributions),
    }


def register_mexico_pay(admin_id: int, amount: float | None = None) -> None:
    status = get_mexico_pay_status()
    pay_amount = amount if amount is not None else MEXICO_EMPLOYEE_TARGET
    if status["balance"] < pay_amount:
        raise ValueError(
            f"Saldo insuficiente ({status['balance']:,.2f}). "
            f"Se necesitan {pay_amount:,.2f} para registrar el pago."
        )
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO mexico_pay_payouts (amount, paid_by, notes)
            VALUES (?, ?, ?)
            """,
            (pay_amount, admin_id, "Pago empleado México"),
        )


def list_mexico_pay_payouts(limit: int = 20) -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT p.*, u.name AS paid_by_name
            FROM mexico_pay_payouts p
            LEFT JOIN users u ON u.id = p.paid_by
            ORDER BY p.paid_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
