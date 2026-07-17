from datetime import date, timedelta
from typing import Optional

from app.cortes import get_corte_cutoff_date, get_last_accepted_corte
from app.currencies import DEFAULT_CURRENCY, normalize_currency
from app.database import db_session
from app.settings import get_system_currency
from app.weekly_billing import (
    WEEKLY_DEDUCTION,
    apply_weekly_deductions,
    calculate_user_deduction,
    get_deductions_for_user_dates_batch,
    get_user_deduction_details_batch,
    get_weekly_deductions_batch,
)

REPORT_DRAFT = "draft"
REPORT_SUBMITTED = "submitted"
REPORT_CONFIRMED = "confirmed"

RETIRO_PROCESSING_FEE = 17.0

EMPTY_SUMMARY = {
    "total_cargues": 0.0,
    "total_retiros": 0.0,
    "num_retiros": 0,
    "retiro_fee": RETIRO_PROCESSING_FEE,
    "total_fees": 0.0,
    "total_discounts": 0.0,
    "preview_total": 0.0,
    "daily_total": 0.0,
    "status": REPORT_DRAFT,
    "is_confirmed": False,
    "is_pending": False,
}


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


def _as_int(value) -> int:
    return int(value)


def _as_float(value) -> float:
    if value is None:
        return 0.0
    return float(value)


def today_iso() -> str:
    return date.today().isoformat()


def parse_report_date(value: str | None) -> str:
    if not value:
        return today_iso()
    try:
        date.fromisoformat(value.strip())
        return value.strip()
    except ValueError:
        return today_iso()


def _system_currency(conn) -> str:
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = 'currency'"
    ).fetchone()
    if row:
        return normalize_currency(row["value"])
    return DEFAULT_CURRENCY


def get_or_create_report(user_id: int, report_date: str) -> dict:
    report_date = parse_report_date(report_date)
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT id, user_id, report_date, status, notes, submitted_at, confirmed_at, currency
            FROM daily_reports
            WHERE user_id = ? AND report_date = ?
            """,
            (user_id, report_date),
        ).fetchone()
        if row:
            data = dict(row)
            data["currency"] = _system_currency(conn)
            return data

        currency = _system_currency(conn)
        try:
            cursor = conn.execute(
                """
                INSERT INTO daily_reports (user_id, report_date, status, currency)
                VALUES (?, ?, 'draft', ?)
                """,
                (user_id, report_date, currency),
            )
        except Exception:
            row = conn.execute(
                """
                SELECT id, user_id, report_date, status, notes, submitted_at, confirmed_at, currency
                FROM daily_reports
                WHERE user_id = ? AND report_date = ?
                """,
                (user_id, report_date),
            ).fetchone()
            if row:
                data = dict(row)
                data["currency"] = _system_currency(conn)
                return data
            raise

        new_id = cursor.lastrowid
        if not new_id:
            new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        return {
            "id": _as_int(new_id),
            "user_id": _as_int(user_id),
            "report_date": report_date,
            "status": REPORT_DRAFT,
            "currency": currency,
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
        data["currency"] = get_system_currency()
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
    total_fees = round(num_retiros * RETIRO_PROCESSING_FEE, 2)
    total_discounts = round(sum(d["amount"] for d in report["discounts"]), 2)
    computed = round(total_retiros - total_cargues - total_fees - total_discounts, 2)
    daily_total = computed if include_in_official else 0.0

    return {
        "total_cargues": total_cargues,
        "total_retiros": total_retiros,
        "num_retiros": num_retiros,
        "retiro_fee": RETIRO_PROCESSING_FEE,
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


def _load_report_children(conn, report_ids: list[int]) -> tuple[dict, dict, dict]:
    if not report_ids:
        return {}, {}, {}

    placeholders = ",".join("?" * len(report_ids))

    params = tuple(_as_int(rid) for rid in report_ids)
    cargues_map = {_as_int(rid): [] for rid in report_ids}
    retiros_map = {_as_int(rid): [] for rid in report_ids}
    discounts_map = {_as_int(rid): [] for rid in report_ids}

    for row in conn.execute(
        f"SELECT id, report_id, amount FROM cargues WHERE report_id IN ({placeholders}) ORDER BY id",
        params,
    ).fetchall():
        rid = _as_int(row["report_id"])
        cargues_map[rid].append({"id": _as_int(row["id"]), "amount": _as_float(row["amount"])})

    for row in conn.execute(
        f"SELECT id, report_id, amount FROM retiros WHERE report_id IN ({placeholders}) ORDER BY id",
        params,
    ).fetchall():
        rid = _as_int(row["report_id"])
        retiros_map[rid].append({"id": _as_int(row["id"]), "amount": _as_float(row["amount"])})

    for row in conn.execute(
        f"SELECT id, report_id, description, amount FROM discounts WHERE report_id IN ({placeholders}) ORDER BY id",
        params,
    ).fetchall():
        rid = _as_int(row["report_id"])
        discounts_map[rid].append(
            {
                "id": _as_int(row["id"]),
                "description": row["description"],
                "amount": _as_float(row["amount"]),
            }
        )

    return cargues_map, retiros_map, discounts_map


def _build_report_row(row, cargues_map, retiros_map, discounts_map) -> dict:
    data = dict(row)
    rid = _as_int(data["id"])
    data["id"] = rid
    if "user_id" in data:
        data["user_id"] = _as_int(data["user_id"])
    if "retiro_fee" in data:
        data["retiro_fee"] = _as_float(data["retiro_fee"])
    data["currency"] = get_system_currency()
    data["cargues"] = cargues_map.get(rid, [])
    data["retiros"] = retiros_map.get(rid, [])
    data["discounts"] = discounts_map.get(rid, [])
    data["summary"] = calculate_summary(data)
    data["is_locked"] = data["status"] in (REPORT_CONFIRMED, REPORT_SUBMITTED)
    data["client_can_edit"] = data["status"] == REPORT_DRAFT
    data["admin_can_edit_entries"] = data["status"] == REPORT_SUBMITTED
    return data


def _corte_sql_extra(alias: str = "dr") -> tuple[str, list]:
    cutoff = get_corte_cutoff_date()
    if cutoff:
        return f" AND {alias}.report_date > ?", [cutoff]
    return "", []


def get_cumulative_gross_batch(user_ids: list[int]) -> dict[int, float]:
    if not user_ids:
        return {}

    totals = {_as_int(uid): 0.0 for uid in user_ids}
    corte_sql, corte_params = _corte_sql_extra("dr")
    with db_session() as conn:
        placeholders = ",".join("?" * len(user_ids))
        rows = conn.execute(
            f"""
            SELECT dr.id, dr.user_id, dr.status, u.retiro_fee
            FROM daily_reports dr
            JOIN users u ON u.id = dr.user_id
            WHERE dr.user_id IN ({placeholders}) AND dr.status = 'confirmed'
            {corte_sql}
            ORDER BY dr.user_id, dr.report_date
            """,
            tuple(user_ids) + tuple(corte_params),
        ).fetchall()
        if not rows:
            return totals

        report_ids = [row["id"] for row in rows]
        cargues_map, retiros_map, discounts_map = _load_report_children(conn, report_ids)

    for row in rows:
        report = _build_report_row(row, cargues_map, retiros_map, discounts_map)
        uid = _as_int(row["user_id"])
        totals[uid] = round(totals[uid] + report["summary"]["daily_total"], 2)
    return totals


def get_cumulative_totals_batch(user_ids: list[int]) -> dict[int, float]:
    return apply_weekly_deductions(get_cumulative_gross_batch(user_ids))


def get_user_reports(user_id: int, limit: int = 30) -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT dr.*, u.name AS user_name, u.retiro_fee
            FROM daily_reports dr
            JOIN users u ON u.id = dr.user_id
            WHERE dr.user_id = ?
            ORDER BY dr.report_date DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        if not rows:
            return []

        report_ids = [row["id"] for row in rows]
        cargues_map, retiros_map, discounts_map = _load_report_children(conn, report_ids)

    cumulative = 0.0
    cutoff = get_corte_cutoff_date()
    reports = []
    for row in reversed(rows):
        details = _build_report_row(row, cargues_map, retiros_map, discounts_map)
        if details["status"] == REPORT_CONFIRMED:
            if not cutoff or details["report_date"] > cutoff:
                cumulative += details["summary"]["daily_total"]
        details["cumulative_total"] = round(cumulative, 2)
        reports.append(details)

    reports.reverse()
    return reports


def get_cumulative_total(user_id: int) -> float:
    return get_cumulative_totals_batch([user_id]).get(user_id, 0.0)


def _write_report_entries(
    conn,
    report_id: int,
    cargues: list[float],
    retiros: list[float],
) -> None:
    conn.execute("DELETE FROM cargues WHERE report_id = ?", (report_id,))
    for amount in cargues:
        conn.execute(
            "INSERT INTO cargues (report_id, amount) VALUES (?, ?)",
            (report_id, amount),
        )

    conn.execute("DELETE FROM retiros WHERE report_id = ?", (report_id,))
    for amount in retiros:
        conn.execute(
            "INSERT INTO retiros (report_id, amount) VALUES (?, ?)",
            (report_id, amount),
        )


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
    *,
    submit: bool = False,
) -> dict:
    details = get_report_details(report_id)
    if not details:
        raise ValueError("Reporte no encontrado")
    if details["status"] == REPORT_CONFIRMED:
        raise ValueError("Este reporte ya fue confirmado por el admin y no se puede editar")
    if details["status"] == REPORT_SUBMITTED:
        raise ValueError(
            "Reporte enviado. Solo el admin puede modificar cargues y retiros. "
            "Pídele que te habilite la edición."
        )

    cargues = parse_amounts_form(cargue_amounts)
    retiros = parse_amounts_form(retiro_amounts)

    if submit and not cargues and not retiros:
        raise ValueError("Agrega al menos un cargue o retiro antes de enviar.")

    user_id = _as_int(details["user_id"])
    with db_session() as conn:
        role_row = conn.execute(
            "SELECT role FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        is_admin = role_row and role_row["role"] == "admin"

        _write_report_entries(conn, report_id, cargues, retiros)
        if submit:
            if is_admin:
                conn.execute(
                    """
                    UPDATE daily_reports
                    SET notes = ?,
                        status = 'confirmed',
                        submitted_at = datetime('now'),
                        confirmed_at = datetime('now'),
                        confirmed_by = ?,
                        updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (notes.strip() or None, user_id, report_id),
                )
            else:
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
        else:
            conn.execute(
                """
                UPDATE daily_reports
                SET notes = ?,
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

    cargues = parse_amounts_form(cargue_amounts)
    retiros = parse_amounts_form(retiro_amounts)

    with db_session() as conn:
        _write_report_entries(conn, report_id, cargues, retiros)
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
    if _as_int(details["user_id"]) == admin_id:
        raise ValueError("No puedes confirmar tu propio reporte. Otro administrador debe confirmarlo.")

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


def change_report_date(report_id: int, new_date: str) -> str:
    """Mueve un reporte a otra fecha (solo si no está confirmado)."""
    new_date = parse_report_date(new_date)
    details = get_report_details(report_id)
    if not details:
        raise ValueError("Reporte no encontrado")
    if details["status"] == REPORT_CONFIRMED:
        raise ValueError("No se puede cambiar la fecha de un reporte ya confirmado")
    if details["report_date"] == new_date:
        raise ValueError("Selecciona una fecha diferente a la actual")

    user_id = _as_int(details["user_id"])
    with db_session() as conn:
        existing = conn.execute(
            """
            SELECT id FROM daily_reports
            WHERE user_id = ? AND report_date = ? AND id != ?
            """,
            (user_id, new_date, report_id),
        ).fetchone()
        if existing:
            other = get_report_details(_as_int(existing["id"]))
            if other and (
                other["cargues"]
                or other["retiros"]
                or other["discounts"]
                or other["status"] != REPORT_DRAFT
            ):
                raise ValueError(
                    f"Ya existe un reporte para el {new_date}. "
                    "Revisa esa fecha o elige otra."
                )
            conn.execute("DELETE FROM daily_reports WHERE id = ?", (_as_int(existing["id"]),))

        conn.execute(
            """
            UPDATE daily_reports
            SET report_date = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (new_date, report_id),
        )
    return new_date


def list_pending_reports(limit: int = 20, after_date: str | None = None) -> list[dict]:
    with db_session() as conn:
        after_sql = ""
        params: list = []
        if after_date:
            after_sql = " AND dr.report_date > ?"
            params.append(after_date)
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT dr.id, dr.report_date, dr.submitted_at, u.id AS user_id,
                   u.name AS user_name, u.username
            FROM daily_reports dr
            JOIN users u ON u.id = dr.user_id
            WHERE dr.status = 'submitted'
            {after_sql}
            ORDER BY dr.submitted_at DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            details = get_report_details(_as_int(row["id"]))
            item["summary"] = details["summary"] if details else dict(EMPTY_SUMMARY)
            if details:
                item["currency"] = get_system_currency()
            results.append(item)
        return results


def count_pending_reports(user_id: int | None = None, after_date: str | None = None) -> int:
    after_sql = " AND report_date > ?" if after_date else ""
    with db_session() as conn:
        if user_id:
            params: list = [user_id]
            if after_date:
                params.append(after_date)
            row = conn.execute(
                f"SELECT COUNT(*) AS c FROM daily_reports WHERE user_id = ? AND status = 'submitted'{after_sql}",
                tuple(params),
            ).fetchone()
        else:
            params = [after_date] if after_date else []
            row = conn.execute(
                f"SELECT COUNT(*) AS c FROM daily_reports WHERE status = 'submitted'{after_sql}",
                tuple(params),
            ).fetchone()
        return _as_int(row["c"]) if row else 0


def list_workers() -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT id, username, name, role, retiro_fee, currency, active, created_at
            FROM users
            WHERE role IN ('worker', 'admin')
            ORDER BY role DESC, name
            """
        ).fetchall()
        workers = []
        user_ids = [row["id"] for row in rows]
        cumulative_map = get_cumulative_totals_batch(user_ids)
        deductions_map = get_weekly_deductions_batch(user_ids)
        deduction_details = get_user_deduction_details_batch(user_ids)
        for row in rows:
            worker = dict(row)
            wid = _as_int(worker["id"])
            worker["id"] = wid
            worker["cumulative_total"] = cumulative_map.get(wid, 0.0)
            worker["weekly_deduction"] = deductions_map.get(wid, 0.0)
            details = deduction_details.get(wid, {})
            worker["weeks_worked"] = details.get("weeks_worked", 0)
            worker["weekly_work_days"] = details.get("weekly_work_days", 0)
            worker["transition_days"] = details.get("transition_days", 0)
            worker["pending_reports"] = count_pending_reports(wid)
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
            INSERT INTO users (username, password_hash, name, role, retiro_fee, currency)
            VALUES (?, ?, ?, 'admin', 0, ?)
            """,
            (username, hash_password(password), name, get_system_currency()),
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


def create_worker(
    username: str, password: str, name: str, retiro_fee: float
) -> None:
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
            INSERT INTO users (username, password_hash, name, role, retiro_fee, currency)
            VALUES (?, ?, ?, 'worker', ?, ?)
            """,
            (username, hash_password(password), name, retiro_fee, get_system_currency()),
        )


def update_worker_fee(worker_id: int, retiro_fee: float) -> None:
    with db_session() as conn:
        conn.execute(
            "UPDATE users SET retiro_fee = ? WHERE id = ?",
            (retiro_fee, worker_id),
        )


def update_worker_status(worker_id: int, active: bool) -> None:
    with db_session() as conn:
        conn.execute(
            "UPDATE users SET active = ? WHERE id = ? AND role = 'worker'",
            (1 if active else 0, worker_id),
        )


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


def _after_corte(report_date: str, cutoff: str | None) -> bool:
    if not cutoff:
        return True
    return report_date > cutoff


def _corte_period_label(cutoff: str | None) -> str | None:
    if not cutoff:
        return None
    return f"{cutoff[8:10]}/{cutoff[5:7]}/{cutoff[:4]}"


def _load_reports_index() -> tuple[list[dict], dict, dict, dict]:
    with db_session() as conn:
        reports = [
            dict(r)
            for r in conn.execute(
                """
                SELECT dr.id, dr.user_id, dr.report_date, dr.status, dr.currency,
                       dr.submitted_at, dr.confirmed_at, u.name AS user_name, u.retiro_fee
                FROM daily_reports dr
                JOIN users u ON u.id = dr.user_id
                WHERE u.role IN ('worker', 'admin')
                ORDER BY dr.report_date DESC
                """
            ).fetchall()
        ]
        cargues = {
            _as_int(row["report_id"]): _as_float(row["total"])
            for row in conn.execute(
                "SELECT report_id, SUM(amount) AS total FROM cargues GROUP BY report_id"
            ).fetchall()
        }
        retiros = {
            _as_int(row["report_id"]): {
                "total": _as_float(row["total"]),
                "count": _as_int(row["cnt"]),
            }
            for row in conn.execute(
                """
                SELECT report_id, SUM(amount) AS total, COUNT(*) AS cnt
                FROM retiros GROUP BY report_id
                """
            ).fetchall()
        }
        discounts = {
            _as_int(row["report_id"]): _as_float(row["total"])
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
    rid = _as_int(report["id"])
    total_cargues = round(float(cargues.get(rid, 0) or 0), 2)
    retiro_data = retiros.get(rid, {"total": 0, "count": 0})
    total_retiros = round(float(retiro_data["total"] or 0), 2)
    num_retiros = int(retiro_data["count"] or 0)
    retiro_fee = RETIRO_PROCESSING_FEE
    total_fees = round(num_retiros * RETIRO_PROCESSING_FEE, 2)
    total_discounts = round(float(discounts.get(rid, 0) or 0), 2)
    preview = round(total_retiros - total_cargues - total_fees - total_discounts, 2)
    confirmed = report["status"] == REPORT_CONFIRMED
    return {
        **report,
        "currency": get_system_currency(),
        "total_cargues": total_cargues,
        "total_retiros": total_retiros,
        "num_retiros": num_retiros,
        "total_fees": total_fees,
        "total_discounts": total_discounts,
        "preview_total": preview,
        "daily_total": preview if confirmed else 0.0,
    }


def get_admin_analytics(period: str = "all") -> dict:
    cutoff = get_corte_cutoff_date()
    last_corte = get_last_accepted_corte()
    start, end = _period_range(period)
    reports_raw, cargues, retiros, discounts = _load_reports_index()
    enriched = [_report_summary_row(r, cargues, retiros, discounts) for r in reports_raw]
    enriched = [r for r in enriched if _after_corte(r["report_date"], cutoff)]

    period_reports = [r for r in enriched if _in_period(r["report_date"], start, end)]
    confirmed_period = [r for r in period_reports if r["status"] == REPORT_CONFIRMED]
    submitted_period = [r for r in period_reports if r["status"] == REPORT_SUBMITTED]

    period_user_dates: dict[int, list[str]] = {}
    for r in confirmed_period:
        uid = r["user_id"]
        period_user_dates.setdefault(uid, []).append(r["report_date"])
    period_quota = get_deductions_for_user_dates_batch(period_user_dates)
    gross_income = round(sum(r["daily_total"] for r in confirmed_period), 2)
    retiro_fees = round(sum(r["total_fees"] for r in confirmed_period), 2)

    totals = {
        "gross_income": gross_income,
        "net_income": round(gross_income - period_quota, 2),
        "quota_deductions": period_quota,
        "retiros": round(sum(r["total_retiros"] for r in confirmed_period), 2),
        "cargues": round(sum(r["total_cargues"] for r in confirmed_period), 2),
        "fees": retiro_fees,
        "retiro_fees": retiro_fees,
        "weekly_deductions": period_quota,
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
    user_ids = [c["user_id"] for c in progress]
    deductions_map = get_weekly_deductions_batch(user_ids)
    deduction_details = get_user_deduction_details_batch(user_ids)
    total_quota_all = round(sum(deductions_map.values()), 2)
    totals["weekly_deductions"] = total_quota_all if period == "all" else totals["quota_deductions"]

    max_cumulative = 0.0
    for c in progress:
        uid = c["user_id"]
        weekly = deductions_map.get(uid, 0.0)
        details = deduction_details.get(uid, {})
        c["weekly_deduction"] = weekly
        c["weeks_worked"] = details.get("weeks_worked", 0)
        c["weekly_work_days"] = details.get("weekly_work_days", 0)
        c["transition_days"] = details.get("transition_days", 0)
        c["cumulative"] = round(c["cumulative"] - weekly, 2)
        c["retiros"] = round(c["retiros"], 2)
        c["cargues"] = round(c["cargues"], 2)
        c["fees"] = round(c["fees"], 2)
        max_cumulative = max(max_cumulative, c["cumulative"])

    progress.sort(key=lambda x: x["cumulative"], reverse=True)
    for c in progress:
        if max_cumulative > 0:
            c["progress_pct"] = round((c["cumulative"] / max_cumulative) * 100, 1)
        else:
            c["progress_pct"] = 0.0

    trend_days = 14
    today = date.today()
    if cutoff:
        corte_day_after = date.fromisoformat(cutoff) + timedelta(days=1)
        window_start = today - timedelta(days=trend_days - 1)
        trend_start = max(corte_day_after, window_start)
    else:
        trend_start = today - timedelta(days=trend_days - 1)

    trend_map: dict[str, dict] = {}
    d = trend_start
    while d <= today:
        iso = d.isoformat()
        trend_map[iso] = {"date": iso, "net": 0.0, "retiros": 0.0, "cargues": 0.0}
        d += timedelta(days=1)

    user_meta: dict[int, dict] = {}
    with db_session() as conn:
        for row in conn.execute(
            "SELECT id, username, role FROM users WHERE role IN ('worker', 'admin')"
        ).fetchall():
            user_meta[_as_int(row["id"])] = dict(row)

    for r in enriched:
        if r["status"] != REPORT_CONFIRMED:
            continue
        if r["report_date"] in trend_map:
            uid = r["user_id"]
            meta = user_meta.get(uid, {})
            day_quota = calculate_user_deduction(
                meta.get("username", ""),
                meta.get("role", "worker"),
                [r["report_date"]],
            )["deduction"]
            trend_map[r["report_date"]]["net"] += r["daily_total"] - day_quota
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
        "all": "Periodo actual" if cutoff else "Histórico total",
        "today": "Hoy",
        "week": "Últimos 7 días",
        "month": "Este mes",
    }
    period_label = period_labels.get(period, "Histórico total")
    corte_since = _corte_period_label(cutoff)
    if period == "all" and corte_since:
        period_label = f"Periodo actual (desde {corte_since})"

    gross_period = round(
        sum(r["daily_total"] for r in enriched if r["status"] == REPORT_CONFIRMED), 2
    )
    period_net = round(gross_period - total_quota_all, 2)

    return {
        "period": period,
        "period_label": period_label,
        "totals": totals,
        "period_net": period_net,
        "gross_period": gross_period,
        "all_time_net": period_net,
        "clients_progress": progress,
        "daily_trend": daily_trend,
        "active_clients": len(clients),
        "total_pending": count_pending_reports(after_date=cutoff),
        "current_corte": last_corte,
        "corte_cutoff": cutoff,
    }
