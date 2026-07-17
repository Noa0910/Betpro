"""Cortes quincenales (días 1 y 15): al aceptar, los acumulados vuelven a 0."""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from app.database import db_session

CORTE_PENDING = "pending"
CORTE_ACCEPTED = "accepted"


def _as_int(value) -> int:
    return int(value)


def _as_float(value) -> float:
    if value is None:
        return 0.0
    return float(value)


def _last_day_of_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def period_bounds_for_end(period_end: date) -> tuple[date, date]:
    """Devuelve (inicio, fin) inclusive para un corte en period_end."""
    if period_end.day == 15:
        return date(period_end.year, period_end.month, 1), period_end
    last_day = _last_day_of_month(period_end.year, period_end.month)
    if period_end.day == last_day:
        return date(period_end.year, period_end.month, 16), period_end
    raise ValueError(f"Fecha de corte inválida: {period_end.isoformat()}")


def last_due_corte_end(today: date | None = None) -> date:
    """Última fecha de corte que ya debió cerrarse (día 1 o 15, o fin de mes)."""
    today = today or date.today()
    y, m = today.year, today.month
    if today.day > 15:
        return date(y, m, 15)
    if today.day > 1:
        return date(y, m, 1) - timedelta(days=1)
    prev_m = m - 1 if m > 1 else 12
    prev_y = y if m > 1 else y - 1
    return date(prev_y, prev_m, _last_day_of_month(prev_y, prev_m))


def next_corte_end_after(period_end: date) -> date:
    """Siguiente fecha de corte después de una aceptada."""
    if period_end.day == 15:
        last_day = _last_day_of_month(period_end.year, period_end.month)
        return date(period_end.year, period_end.month, last_day)
    if period_end.day == _last_day_of_month(period_end.year, period_end.month):
        next_m = period_end.month + 1 if period_end.month < 12 else 1
        next_y = period_end.year if period_end.month < 12 else period_end.year + 1
        return date(next_y, next_m, 15)
    raise ValueError(f"Fecha de corte inválida: {period_end.isoformat()}")


def format_period_label(period_start: str, period_end: str) -> str:
    return f"{period_start[8:10]}/{period_start[5:7]}/{period_start[:4]} — {period_end[8:10]}/{period_end[5:7]}/{period_end[:4]}"


def get_last_accepted_corte() -> dict | None:
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT c.*, u.name AS accepted_by_name
            FROM cortes c
            LEFT JOIN users u ON u.id = c.accepted_by
            WHERE c.status = ?
            ORDER BY c.period_end DESC, c.id DESC
            LIMIT 1
            """,
            (CORTE_ACCEPTED,),
        ).fetchone()
        return _enrich_corte(dict(row)) if row else None


def _enrich_corte(corte: dict) -> dict:
    corte["period_label"] = format_period_label(corte["period_start"], corte["period_end"])
    return corte


def get_pending_corte() -> dict | None:
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT * FROM cortes
            WHERE status = ?
            ORDER BY period_end DESC, id DESC
            LIMIT 1
            """,
            (CORTE_PENDING,),
        ).fetchone()
        return _enrich_corte(dict(row)) if row else None


def get_corte_cutoff_date() -> str | None:
    """Reportes con fecha <= cutoff ya fueron liquidados en el último corte."""
    last = get_last_accepted_corte()
    if not last:
        return None
    return last["period_end"]


def list_cortes(limit: int = 20) -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT c.*, u.name AS accepted_by_name
            FROM cortes c
            LEFT JOIN users u ON u.id = c.accepted_by
            ORDER BY c.period_end DESC, c.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_enrich_corte(dict(r)) for r in rows]


def _corte_exists(conn, period_end: str, status: str | None = None) -> bool:
    if status:
        row = conn.execute(
            "SELECT id FROM cortes WHERE period_end = ? AND status = ?",
            (period_end, status),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM cortes WHERE period_end = ?",
            (period_end,),
        ).fetchone()
    return row is not None


def ensure_pending_corte() -> dict | None:
    """Crea corte pendiente si ya pasó la fecha quincenal y no existe uno."""
    pending = get_pending_corte()
    if pending:
        return pending

    today = date.today()
    due_end = last_due_corte_end(today)
    if today <= due_end:
        return None

    last_accepted = get_last_accepted_corte()
    if last_accepted and last_accepted["period_end"] >= due_end.isoformat():
        return None

    with db_session() as conn:
        if _corte_exists(conn, due_end.isoformat()):
            return get_pending_corte()

    return _create_pending(due_end.isoformat())


def _corte_exists_with_conn(conn, period_end: str) -> bool:
    if conn is None:
        with db_session() as c:
            return _corte_exists(c, period_end)
    return _corte_exists(conn, period_end)


def _create_pending(period_end_iso: str) -> dict:
    period_end = date.fromisoformat(period_end_iso)
    period_start, _ = period_bounds_for_end(period_end)
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO cortes (period_start, period_end, status)
            VALUES (?, ?, ?)
            """,
            (period_start.isoformat(), period_end.isoformat(), CORTE_PENDING),
        )
        row = conn.execute(
            "SELECT * FROM cortes WHERE period_end = ? AND status = ? ORDER BY id DESC LIMIT 1",
            (period_end.isoformat(), CORTE_PENDING),
        ).fetchone()
        return _enrich_corte(dict(row))


def count_submitted_in_period(period_start: str, period_end: str) -> int:
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c FROM daily_reports
            WHERE status = 'submitted'
              AND report_date >= ? AND report_date <= ?
            """,
            (period_start, period_end),
        ).fetchone()
        return _as_int(row["c"]) if row else 0


def build_corte_preview(corte: dict) -> dict:
    """Totales confirmados por cliente en el periodo del corte."""
    period_start = corte["period_start"]
    period_end = corte["period_end"]
    from app.services import _build_report_row, _load_report_children

    clients: list[dict] = []
    total_net = 0.0

    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT dr.id, dr.user_id, dr.report_date, dr.status, u.name AS user_name,
                   u.username, u.role, u.retiro_fee
            FROM daily_reports dr
            JOIN users u ON u.id = dr.user_id
            WHERE dr.status = 'confirmed'
              AND dr.report_date >= ? AND dr.report_date <= ?
            ORDER BY u.name, dr.report_date
            """,
            (period_start, period_end),
        ).fetchall()
        if not rows:
            return {
                "clients": [],
                "total_net": 0.0,
                "total_clients": 0,
                "submitted_pending": count_submitted_in_period(period_start, period_end),
            }

        report_ids = [row["id"] for row in rows]
        cargues_map, retiros_map, discounts_map = _load_report_children(conn, report_ids)

    by_user: dict[int, dict] = {}
    for row in rows:
        report = _build_report_row(row, cargues_map, retiros_map, discounts_map)
        uid = _as_int(row["user_id"])
        if uid not in by_user:
            by_user[uid] = {
                "user_id": uid,
                "name": row["user_name"],
                "username": row["username"],
                "role": row["role"],
                "confirmed_days": 0,
                "total": 0.0,
            }
        entry = by_user[uid]
        entry["confirmed_days"] += 1
        entry["total"] = round(entry["total"] + report["summary"]["daily_total"], 2)

    clients = sorted(by_user.values(), key=lambda x: x["total"], reverse=True)
    total_net = round(sum(c["total"] for c in clients), 2)
    return {
        "clients": clients,
        "total_net": total_net,
        "total_clients": len(clients),
        "submitted_pending": count_submitted_in_period(period_start, period_end),
    }


def accept_corte(corte_id: int, admin_id: int) -> None:
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM cortes WHERE id = ? AND status = ?",
            (corte_id, CORTE_PENDING),
        ).fetchone()
        if not row:
            raise ValueError("Corte no encontrado o ya fue aceptado")

        corte = dict(row)
        pending = count_submitted_in_period(corte["period_start"], corte["period_end"])
        if pending > 0:
            raise ValueError(
                f"Hay {pending} reporte(s) sin confirmar en este periodo. "
                "Confírmalos o habilita edición antes de aceptar el corte."
            )

        preview = build_corte_preview(corte)
        for client in preview["clients"]:
            conn.execute(
                """
                INSERT INTO corte_snapshots (corte_id, user_id, cumulative_at_corte)
                VALUES (?, ?, ?)
                """,
                (corte_id, client["user_id"], client["total"]),
            )

        conn.execute(
            """
            UPDATE cortes
            SET status = ?, accepted_at = datetime('now'), accepted_by = ?
            WHERE id = ?
            """,
            (CORTE_ACCEPTED, admin_id, corte_id),
        )
