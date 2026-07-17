"""Cuota semanal por usuario y acumulado para pago empleado México."""

from __future__ import annotations

from datetime import date, timedelta

from app.cortes import get_corte_cutoff_date
from app.database import db_session

WEEKLY_DEDUCTION = 500.0
WEEKLY_WORK_DAYS = 6
MEXICO_EMPLOYEE_TARGET = 3000.0

# Transición 17–18 jul 2026 (antes del inicio de cuota semanal el lunes 20).
TRANSITION_DATES = frozenset({date(2026, 7, 17), date(2026, 7, 18)})
CLIENT_DAILY_DEDUCTION = 86.0
ADMIN_DAILY_DEDUCTION = 578.0
ADMIN_DAILY_USERNAMES = frozenset({"patachan", "nosorio"})
WEEKLY_DEDUCTION_START = date(2026, 7, 20)


def weekly_per_work_day() -> float:
    return round(WEEKLY_DEDUCTION / WEEKLY_WORK_DAYS, 2)


def _is_billable_work_day(d: date) -> bool:
    """Lun–sáb (6 días); domingo no cuenta."""
    return d.weekday() < 6


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


def _daily_deduction(username: str, role: str) -> float:
    if role == "admin" and username.lower() in ADMIN_DAILY_USERNAMES:
        return ADMIN_DAILY_DEDUCTION
    return CLIENT_DAILY_DEDUCTION


def get_user_confirmed_dates_batch(user_ids: list[int]) -> dict[int, list[str]]:
    if not user_ids:
        return {}
    since_sql, since_params = _report_since_filter("dr")
    placeholders = ",".join("?" * len(user_ids))
    dates_map: dict[int, list[str]] = {uid: [] for uid in user_ids}
    with db_session() as conn:
        rows = conn.execute(
            f"""
            SELECT dr.user_id, dr.report_date
            FROM daily_reports dr
            WHERE dr.user_id IN ({placeholders}) AND dr.status = 'confirmed'
            {since_sql}
            ORDER BY dr.user_id, dr.report_date
            """,
            tuple(user_ids) + tuple(since_params),
        ).fetchall()
    for row in rows:
        uid = _as_int(row["user_id"])
        dates_map[uid].append(row["report_date"])
    return dates_map


def get_user_confirmed_dates(user_id: int) -> list[str]:
    return get_user_confirmed_dates_batch([user_id]).get(user_id, [])


def calculate_user_deduction(username: str, role: str, confirmed_dates: list[str]) -> dict:
    transition_days = 0
    transition_amount = 0.0
    weekly_work_days = 0
    weekly_weeks: set[str] = set()

    for report_date_str in confirmed_dates:
        d = date.fromisoformat(report_date_str)
        if d in TRANSITION_DATES:
            transition_days += 1
            transition_amount += _daily_deduction(username, role)
        elif d >= WEEKLY_DEDUCTION_START and _is_billable_work_day(d):
            weekly_work_days += 1
            weekly_weeks.add(week_start(d).isoformat())

    weekly_amount = round(weekly_work_days * WEEKLY_DEDUCTION / WEEKLY_WORK_DAYS, 2)
    transition_amount = round(transition_amount, 2)
    total = round(transition_amount + weekly_amount, 2)

    return {
        "deduction": total,
        "transition_days": transition_days,
        "transition_amount": transition_amount,
        "weekly_work_days": weekly_work_days,
        "weeks_worked": len(weekly_weeks),
        "weekly_amount": weekly_amount,
        "week_labels": [week_label(w) for w in sorted(weekly_weeks)],
    }


def get_user_deduction_details_batch(user_ids: list[int]) -> dict[int, dict]:
    if not user_ids:
        return {}
    dates_map = get_user_confirmed_dates_batch(user_ids)
    result: dict[int, dict] = {}
    with db_session() as conn:
        for uid in user_ids:
            row = conn.execute(
                "SELECT username, role FROM users WHERE id = ?",
                (uid,),
            ).fetchone()
            if not row:
                result[uid] = calculate_user_deduction("", "worker", dates_map.get(uid, []))
                continue
            result[uid] = calculate_user_deduction(
                row["username"],
                row["role"],
                dates_map.get(uid, []),
            )
    return result


def get_user_work_weeks(user_id: int) -> list[str]:
    confirmed = get_user_confirmed_dates(user_id)
    weeks = {
        week_start(date.fromisoformat(d)).isoformat()
        for d in confirmed
        if date.fromisoformat(d) >= WEEKLY_DEDUCTION_START
        and week_start(date.fromisoformat(d)) >= WEEKLY_DEDUCTION_START
    }
    return sorted(weeks)


def get_user_weeks_batch(user_ids: list[int]) -> dict[int, list[str]]:
    dates_map = get_user_confirmed_dates_batch(user_ids)
    result: dict[int, list[str]] = {uid: [] for uid in user_ids}
    for uid in user_ids:
        weeks = {
            week_start(date.fromisoformat(d)).isoformat()
            for d in dates_map.get(uid, [])
            if date.fromisoformat(d) >= WEEKLY_DEDUCTION_START
            and week_start(date.fromisoformat(d)) >= WEEKLY_DEDUCTION_START
        }
        result[uid] = sorted(weeks)
    return result


def get_deductions_for_user_dates_batch(user_dates: dict[int, list[str]]) -> float:
    """Suma cuotas aplicables a fechas concretas de reporte confirmado."""
    if not user_dates:
        return 0.0
    total = 0.0
    with db_session() as conn:
        for uid, dates in user_dates.items():
            if not dates:
                continue
            row = conn.execute(
                "SELECT username, role FROM users WHERE id = ?",
                (uid,),
            ).fetchone()
            if not row:
                continue
            total += calculate_user_deduction(
                row["username"], row["role"], dates
            )["deduction"]
    return round(total, 2)


def get_weekly_deductions_batch(user_ids: list[int]) -> dict[int, float]:
    details = get_user_deduction_details_batch(user_ids)
    return {uid: details.get(uid, {}).get("deduction", 0.0) for uid in user_ids}


def apply_weekly_deductions(gross: dict[int, float]) -> dict[int, float]:
    if not gross:
        return {}
    deductions = get_weekly_deductions_batch(list(gross.keys()))
    return {
        uid: round(gross.get(uid, 0.0) - deductions.get(uid, 0.0), 2)
        for uid in gross
    }


def get_user_billing_summary(user_id: int, gross: float) -> dict:
    with db_session() as conn:
        row = conn.execute(
            "SELECT username, role FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    username = row["username"] if row else ""
    role = row["role"] if row else "worker"
    details = calculate_user_deduction(username, role, get_user_confirmed_dates(user_id))
    deduction = details["deduction"]
    return {
        "weeks_worked": details["weeks_worked"],
        "weekly_work_days": details["weekly_work_days"],
        "transition_days": details["transition_days"],
        "transition_amount": details["transition_amount"],
        "weekly_amount": details["weekly_amount"],
        "weekly_per_work_day": weekly_per_work_day(),
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
    details_map = get_user_deduction_details_batch(user_ids)
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
            details = details_map.get(uid, {})
            amount = details.get("deduction", 0.0)
            contributions.append(
                {
                    "user_id": uid,
                    "name": row["name"],
                    "username": row["username"],
                    "role": row["role"],
                    "weeks_worked": details.get("weeks_worked", 0),
                    "weekly_work_days": details.get("weekly_work_days", 0),
                    "transition_days": details.get("transition_days", 0),
                    "amount": amount,
                    "week_labels": details.get("week_labels", []),
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
        "weekly_per_work_day": weekly_per_work_day(),
        "weekly_work_days_total": WEEKLY_WORK_DAYS,
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
