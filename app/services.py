from datetime import date, timedelta
from typing import Optional

from app.database import db_session

REPORT_DRAFT = "draft"
REPORT_SUBMITTED = "submitted"
REPORT_CONFIRMED = "confirmed"


def parse_amount(value: str) -> float:
    cleaned = value.strip().replace(",", ".")
    if not cleaned:
        raise ValueError("Monto vacío")
    amount = float(cleaned)
    if amount < 0:
        raise ValueError("El monto no puede ser negativo")
    return round(amount, 2)


def parse_amounts_form(values: list[str]) -> list[float]:
    return [parse_amount(v) for v in values if v and v.strip()]


def get_or_create_report(user_id: int, report_date: str) -> dict:
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT id, user_id, report_date, status, notes, submitted_at, confirmed_at
            FROM daily_reports
            WHERE user_id = ? AND report_date = ?
            """,
            (user_id, report_date),
        ).fetchone()
        if row:
            return dict(row)

        row = conn.execute(
            """
            INSERT INTO daily_reports (user_id, report_date, status)
            VALUES (?, ?, 'draft')
            RETURNING id
            """,
            (user_id, report_date),
        ).fetchone()
        return {
            "id": row["id"],
            "user_id": user_id,
            "report_date": report_date,
            "status": REPORT_DRAFT,
            "notes": None,
            "submitted_at": None,
            "confirmed_at": None,
        }


def get_report_details(report_id: int) -> Optional[dict]:
    with db_session() as conn:
        report = conn.execute(
            """
            SELECT dr.*, u.name AS user_name, u.retiro_fee
            FROM daily_reports dr
            JOIN users u ON u.id = dr.user_id
            WHERE dr.id = ?
            """,
            (report_id,),
        ).fetchone()
        if not report:
            return None

        cargues = conn.execute(
            "SELECT id, amount FROM cargues WHERE report_id = ? ORDER BY id",
            (report_id,),
        ).fetchall()
        retiros = conn.execute(
            "SELECT id, amount FROM retiros WHERE report_id = ? ORDER BY id",
            (report_id,),
        ).fetchall()
        discounts = conn.execute(
            "SELECT id, description, amount FROM discounts WHERE report_id = ? ORDER BY id",
            (report_id,),
        ).fetchall()

        data = dict(report)
        data["cargues"] = [dict(c) for c in cargues]
        data["retiros"] = [dict(r) for r in retiros]
        data["discounts"] = [dict(d) for d in discounts]
        data["summary"] = calculate_summary(data)
        data["is_locked"] = data["status"] in (REPORT_CONFIRMED, REPORT_SUBMITTED)
        data["client_can_edit"] = data["status"] == REPORT_DRAFT
        data["admin_can_edit_entries"] = data["status"] == REPORT_SUBMITTED
        return data


def _calc_totals(report: dict, include_in_official: bool) -> dict:
    total_cargues = round(sum(c["amount"] for c in report["cargues"]), 2)
    total_retiros = round(sum(r["amount"] for r in report["retiros"]), 2)
    num_retiros = len(report["retiros"])
    retiro_fee = float(report["retiro_fee"])
    total_fees = round(num_retiros * retiro_fee, 2)
    total_discounts = round(sum(d["amount"] for d in report["discounts"]), 2)
    computed = round(total_retiros - total_cargues - total_fees - total_discounts, 2)
    daily_total = computed if include_in_official else 0.0

    return {
        "total_cargues": total_cargues,
        "total_retiros": total_retiros,
        "num_retiros": num_retiros,
        "retiro_fee": retiro_fee,
        "total_fees": total_fees,
        "total_discounts": total_discounts,
        "preview_total": computed,
        "daily_total": daily_total,
    }


def calculate_summary(report: dict) -> dict:
    confirmed = report.get("status") == REPORT_CONFIRMED
    summary = _calc_totals(report, include_in_official=confirmed)
    summary["status"] = report.get("status", REPORT_DRAFT)
    summary["is_confirmed"] = confirmed
    summary["is_pending"] = report.get("status") == REPORT_SUBMITTED
    return summary


def get_user_reports(user_id: int, limit: int = 30) -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT dr.id, dr.report_date
            FROM daily_reports dr
            WHERE dr.user_id = ?
            ORDER BY dr.report_date DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()

        reports = []
        cumulative = 0.0
        for row in reversed(rows):
            details = get_report_details(row["id"])
            if not details:
                continue
            cumulative += details["summary"]["daily_total"]
            details["cumulative_total"] = round(cumulative, 2)
            reports.append(details)

        reports.reverse()
        return reports


def get_cumulative_total(user_id: int) -> float:
    reports = get_user_reports(user_id, limit=1000)
    if not reports:
        return 0.0
    return reports[0]["cumulative_total"]


def save_cargues(report_id: int, amounts: list[float]) -> None:
    with db_session() as conn:
        conn.execute("DELETE FROM cargues WHERE report_id = ?", (report_id,))
        for amount in amounts:
            conn.execute(
                "INSERT INTO cargues (report_id, amount) VALUES (?, ?)",
                (report_id, amount),
            )


def save_retiros(report_id: int, amounts: list[float]) -> None:
    with db_session() as conn:
        conn.execute("DELETE FROM retiros WHERE report_id = ?", (report_id,))
        for amount in amounts:
            conn.execute(
                "INSERT INTO retiros (report_id, amount) VALUES (?, ?)",
                (report_id, amount),
            )


def save_client_report(
    report_id: int,
    cargue_amounts: list[str],
    retiro_amounts: list[str],
    notes: str = "",
) -> dict:
    details = get_report_details(report_id)
    if not details:
        raise ValueError("Reporte no encontrado")
    if details["status"] == REPORT_CONFIRMED:
        raise ValueError("Este reporte ya fue confirmado por el admin y no se puede editar")
    if details["status"] == REPORT_SUBMITTED:
        raise ValueError("Reporte enviado. Solo el admin puede modificar cargues y retiros. Pídele que te habilite la edición.")

    save_cargues(report_id, parse_amounts_form(cargue_amounts))
    save_retiros(report_id, parse_amounts_form(retiro_amounts))

    with db_session() as conn:
        conn.execute(
            """
            UPDATE daily_reports
            SET notes = ?,
                status = 'submitted',
                submitted_at = datetime('now'),
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (notes.strip() or None, report_id),
        )

    return get_report_details(report_id)


def save_admin_entries(
    report_id: int,
    cargue_amounts: list[str],
    retiro_amounts: list[str],
) -> dict:
    details = get_report_details(report_id)
    if not details:
        raise ValueError("Reporte no encontrado")
    if details["status"] == REPORT_CONFIRMED:
        raise ValueError("Reporte confirmado, no se puede modificar")
    if details["status"] != REPORT_SUBMITTED:
        raise ValueError("Solo se pueden editar cargues y retiros de reportes enviados")

    save_cargues(report_id, parse_amounts_form(cargue_amounts))
    save_retiros(report_id, parse_amounts_form(retiro_amounts))

    with db_session() as conn:
        conn.execute(
            "UPDATE daily_reports SET updated_at = datetime('now') WHERE id = ?",
            (report_id,),
        )

    return get_report_details(report_id)


def reopen_report(report_id: int) -> bool:
    details = get_report_details(report_id)
    if not details:
        return False
    if details["status"] != REPORT_SUBMITTED:
        return False

    with db_session() as conn:
        conn.execute(
            """
            UPDATE daily_reports
            SET status = 'draft',
                submitted_at = NULL,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (report_id,),
        )
    return True


def save_discounts(report_id: int, descriptions: list[str], amounts: list[str]) -> None:
    details = get_report_details(report_id)
    if details and details["status"] == REPORT_CONFIRMED:
        raise ValueError("No se pueden editar descuentos de un reporte confirmado")

    with db_session() as conn:
        conn.execute("DELETE FROM discounts WHERE report_id = ?", (report_id,))
        for desc, raw_amount in zip(descriptions, amounts):
            if not desc.strip() or not raw_amount.strip():
                continue
            conn.execute(
                """
                INSERT INTO discounts (report_id, description, amount)
                VALUES (?, ?, ?)
                """,
                (report_id, desc.strip(), parse_amount(raw_amount)),
            )
        conn.execute(
            "UPDATE daily_reports SET updated_at = datetime('now') WHERE id = ?",
            (report_id,),
        )


def confirm_report(report_id: int, admin_id: int) -> bool:
    details = get_report_details(report_id)
    if not details:
        return False
    if details["status"] == REPORT_CONFIRMED:
        return False
    if details["status"] != REPORT_SUBMITTED:
        return False
    if not details["cargues"] and not details["retiros"]:
        return False

    with db_session() as conn:
        conn.execute(
            """
            UPDATE daily_reports
            SET status = 'confirmed',
                confirmed_at = datetime('now'),
                confirmed_by = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (admin_id, report_id),
        )
    return True


def list_pending_reports(limit: int = 20) -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT dr.id, dr.report_date, dr.submitted_at, u.id AS user_id,
                   u.name AS user_name, u.username
            FROM daily_reports dr
            JOIN users u ON u.id = dr.user_id
            WHERE dr.status = 'submitted'
            ORDER BY dr.submitted_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            details = get_report_details(row["id"])
            item["summary"] = details["summary"] if details else {}
            results.append(item)
        return results


def count_pending_reports(user_id: int | None = None) -> int:
    with db_session() as conn:
        if user_id:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM daily_reports WHERE user_id = ? AND status = 'submitted'",
                (user_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM daily_reports WHERE status = 'submitted'"
            ).fetchone()
        return row["c"] if row else 0


def list_workers() -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT id, username, name, role, retiro_fee, active, created_at
            FROM users
            WHERE role = 'worker'
            ORDER BY name
            """
        ).fetchall()
        workers = []
        for row in rows:
            worker = dict(row)
            worker["cumulative_total"] = get_cumulative_total(worker["id"])
            worker["pending_reports"] = count_pending_reports(worker["id"])
            workers.append(worker)
        return workers


def create_admin(username: str, password: str, name: str) -> None:
    from app.auth import hash_password

    username = username.strip().lower()
    name = name.strip()
    if not username or not name or not password:
        raise ValueError("Nombre, usuario y contraseña son obligatorios")

    with db_session() as conn:
        exists = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if exists:
            raise ValueError("Ese usuario ya está registrado")

        conn.execute(
            """
            INSERT INTO users (username, password_hash, name, role, retiro_fee)
            VALUES (?, ?, ?, 'admin', 0)
            """,
            (username, hash_password(password), name),
        )


def list_admins() -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT id, username, name, role, active, created_at
            FROM users
            WHERE role = 'admin'
            ORDER BY name
            """
        ).fetchall()
        return [dict(row) for row in rows]


def update_admin_status(admin_id: int, active: bool, actor_id: int) -> None:
    if admin_id == actor_id and not active:
        raise ValueError("No puedes desactivar tu propia cuenta")

    with db_session() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE id = ? AND role = 'admin'",
            (admin_id,),
        ).fetchone()
        if not row:
            raise ValueError("Administrador no encontrado")

        conn.execute(
            "UPDATE users SET active = ? WHERE id = ? AND role = 'admin'",
            (1 if active else 0, admin_id),
        )


def create_worker(username: str, password: str, name: str, retiro_fee: float) -> None:
    from app.auth import hash_password

    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO users (username, password_hash, name, role, retiro_fee)
            VALUES (?, ?, ?, 'worker', ?)
            """,
            (username.strip().lower(), hash_password(password), name.strip(), retiro_fee),
        )


def update_worker_fee(worker_id: int, retiro_fee: float) -> None:
    with db_session() as conn:
        conn.execute(
            "UPDATE users SET retiro_fee = ? WHERE id = ? AND role = 'worker'",
            (retiro_fee, worker_id),
        )


def update_worker_status(worker_id: int, active: bool) -> None:
    with db_session() as conn:
        conn.execute(
            "UPDATE users SET active = ? WHERE id = ? AND role = 'worker'",
            (1 if active else 0, worker_id),
        )


def today_iso() -> str:
    return date.today().isoformat()


def _period_range(period: str) -> tuple[str | None, str | None]:
    today = date.today()
    if period == "today":
        d = today.isoformat()
        return d, d
    if period == "week":
        return (today - timedelta(days=6)).isoformat(), today.isoformat()
    if period == "month":
        return today.replace(day=1).isoformat(), today.isoformat()
    return None, None


def _in_period(report_date: str, start: str | None, end: str | None) -> bool:
    if not start or not end:
        return True
    return start <= report_date <= end


def _load_reports_index() -> tuple[list[dict], dict, dict, dict]:
    with db_session() as conn:
        reports = [
            dict(r)
            for r in conn.execute(
                """
                SELECT dr.id, dr.user_id, dr.report_date, dr.status,
                       dr.submitted_at, dr.confirmed_at, u.name AS user_name, u.retiro_fee
                FROM daily_reports dr
                JOIN users u ON u.id = dr.user_id
                WHERE u.role = 'worker'
                ORDER BY dr.report_date DESC
                """
            ).fetchall()
        ]
        cargues = {
            row["report_id"]: row["total"]
            for row in conn.execute(
                "SELECT report_id, SUM(amount) AS total FROM cargues GROUP BY report_id"
            ).fetchall()
        }
        retiros = {
            row["report_id"]: {"total": row["total"], "count": row["cnt"]}
            for row in conn.execute(
                """
                SELECT report_id, SUM(amount) AS total, COUNT(*) AS cnt
                FROM retiros GROUP BY report_id
                """
            ).fetchall()
        }
        discounts = {
            row["report_id"]: row["total"]
            for row in conn.execute(
                "SELECT report_id, SUM(amount) AS total FROM discounts GROUP BY report_id"
            ).fetchall()
        }
    return reports, cargues, retiros, discounts


def _report_summary_row(
    report: dict,
    cargues: dict,
    retiros: dict,
    discounts: dict,
) -> dict:
    rid = report["id"]
    total_cargues = round(float(cargues.get(rid, 0) or 0), 2)
    retiro_data = retiros.get(rid, {"total": 0, "count": 0})
    total_retiros = round(float(retiro_data["total"] or 0), 2)
    num_retiros = int(retiro_data["count"] or 0)
    retiro_fee = float(report["retiro_fee"])
    total_fees = round(num_retiros * retiro_fee, 2)
    total_discounts = round(float(discounts.get(rid, 0) or 0), 2)
    preview = round(total_retiros - total_cargues - total_fees - total_discounts, 2)
    confirmed = report["status"] == REPORT_CONFIRMED
    return {
        **report,
        "total_cargues": total_cargues,
        "total_retiros": total_retiros,
        "num_retiros": num_retiros,
        "total_fees": total_fees,
        "total_discounts": total_discounts,
        "preview_total": preview,
        "daily_total": preview if confirmed else 0.0,
    }


def get_admin_analytics(period: str = "all") -> dict:
    start, end = _period_range(period)
    reports_raw, cargues, retiros, discounts = _load_reports_index()
    enriched = [_report_summary_row(r, cargues, retiros, discounts) for r in reports_raw]

    period_reports = [r for r in enriched if _in_period(r["report_date"], start, end)]
    confirmed_period = [r for r in period_reports if r["status"] == REPORT_CONFIRMED]
    submitted_period = [r for r in period_reports if r["status"] == REPORT_SUBMITTED]

    totals = {
        "net_income": round(sum(r["daily_total"] for r in confirmed_period), 2),
        "retiros": round(sum(r["total_retiros"] for r in confirmed_period), 2),
        "cargues": round(sum(r["total_cargues"] for r in confirmed_period), 2),
        "fees": round(sum(r["total_fees"] for r in confirmed_period), 2),
        "discounts": round(sum(r["total_discounts"] for r in confirmed_period), 2),
        "retiro_count": sum(r["num_retiros"] for r in confirmed_period),
        "confirmed_reports": len(confirmed_period),
        "pending_reports": len(submitted_period),
        "pending_estimated": round(sum(r["preview_total"] for r in submitted_period), 2),
    }

    clients: dict[int, dict] = {}
    for r in enriched:
        uid = r["user_id"]
        if uid not in clients:
            clients[uid] = {
                "user_id": uid,
                "name": r["user_name"],
                "cumulative": 0.0,
                "retiros": 0.0,
                "cargues": 0.0,
                "fees": 0.0,
                "retiro_count": 0,
                "confirmed_days": 0,
                "pending_days": 0,
                "last_date": None,
            }
        c = clients[uid]
        if r["status"] == REPORT_CONFIRMED:
            c["cumulative"] += r["daily_total"]
            c["retiros"] += r["total_retiros"]
            c["cargues"] += r["total_cargues"]
            c["fees"] += r["total_fees"]
            c["retiro_count"] += r["num_retiros"]
            c["confirmed_days"] += 1
        if r["status"] == REPORT_SUBMITTED:
            c["pending_days"] += 1
        if not c["last_date"] or r["report_date"] > c["last_date"]:
            c["last_date"] = r["report_date"]

    progress = sorted(clients.values(), key=lambda x: x["cumulative"], reverse=True)
    max_cumulative = progress[0]["cumulative"] if progress else 0
    for c in progress:
        c["cumulative"] = round(c["cumulative"], 2)
        c["retiros"] = round(c["retiros"], 2)
        c["cargues"] = round(c["cargues"], 2)
        c["fees"] = round(c["fees"], 2)
        if max_cumulative > 0:
            c["progress_pct"] = round((c["cumulative"] / max_cumulative) * 100, 1)
        else:
            c["progress_pct"] = 0.0

    trend_days = 14
    today = date.today()
    trend_map: dict[str, dict] = {}
    for i in range(trend_days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        trend_map[d] = {"date": d, "net": 0.0, "retiros": 0.0, "cargues": 0.0}

    for r in enriched:
        if r["status"] != REPORT_CONFIRMED:
            continue
        if r["report_date"] in trend_map:
            trend_map[r["report_date"]]["net"] += r["daily_total"]
            trend_map[r["report_date"]]["retiros"] += r["total_retiros"]
            trend_map[r["report_date"]]["cargues"] += r["total_cargues"]

    daily_trend = []
    max_net = 0.0
    for d in sorted(trend_map.keys()):
        item = trend_map[d]
        item["net"] = round(item["net"], 2)
        item["retiros"] = round(item["retiros"], 2)
        item["cargues"] = round(item["cargues"], 2)
        max_net = max(max_net, abs(item["net"]))
        daily_trend.append(item)

    for item in daily_trend:
        item["bar_pct"] = round((abs(item["net"]) / max_net * 100), 1) if max_net else 0

    period_labels = {
        "all": "Histórico total",
        "today": "Hoy",
        "week": "Últimos 7 días",
        "month": "Este mes",
    }

    all_time_net = round(sum(r["daily_total"] for r in enriched if r["status"] == REPORT_CONFIRMED), 2)

    return {
        "period": period,
        "period_label": period_labels.get(period, "Histórico total"),
        "totals": totals,
        "all_time_net": all_time_net,
        "clients_progress": progress,
        "daily_trend": daily_trend,
        "active_clients": len(clients),
        "total_pending": count_pending_reports(),
    }
