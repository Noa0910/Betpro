"""Verifica que todos los datos se guarden y persistan correctamente."""
from fastapi.testclient import TestClient

from datetime import date

from app.database import db_session, parse_count
from app.main import app
from app.services import (
    REPORT_DRAFT,
    REPORT_SUBMITTED,
    create_worker,
    get_report_details,
    today_iso,
)

client = TestClient(app)

WORKER = "_persist_worker_"
WORKER_PASS = "Persist2026!"
ADMIN = "nosorio"
ADMIN_PASS = "Nosorio2026!"

errors = []


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "OK" if ok else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        errors.append(f"{name}: {detail}")


try:
    create_worker(WORKER, WORKER_PASS, "Persist Test", 50)
except ValueError:
    pass

# 1. Login worker
r = client.post("/acceso", data={"username": WORKER, "password": WORKER_PASS})
check("login worker", r.status_code in (200, 303))

# 2. Guardar borrador (fecha única por ejecución)
fecha = date.today().isoformat()
with db_session() as conn:
    uid = conn.execute("SELECT id FROM users WHERE username = ?", (WORKER,)).fetchone()["id"]
    conn.execute("DELETE FROM daily_reports WHERE user_id = ? AND report_date = ?", (uid, fecha))
r = client.post(
    "/mis-reportes/guardar",
    data={
        "report_date": fecha,
        "action": "draft",
        "cargue_amount": ["200", "100"],
        "retiro_amount": ["1300", "500"],
        "notes": "borrador test",
    },
)
check("guardar borrador HTTP", r.status_code == 200)
check("sesion tras guardar", r.status_code != 303 or "/acceso" not in str(r.headers.get("location", "")))

# 3. Verificar datos en BD
with db_session() as conn:
    user_row = conn.execute(
        "SELECT id FROM users WHERE username = ?", (WORKER,)
    ).fetchone()
    report_row = conn.execute(
        "SELECT id, status, notes FROM daily_reports WHERE user_id = ? AND report_date = ?",
        (user_row["id"], fecha),
    ).fetchone()
    cargues = parse_count(
        conn.execute(
            "SELECT COUNT(*) AS c FROM cargues WHERE report_id = ?",
            (report_row["id"],),
        ).fetchone()
    )
    retiros = parse_count(
        conn.execute(
            "SELECT COUNT(*) AS c FROM retiros WHERE report_id = ?",
            (report_row["id"],),
        ).fetchone()
    )

check("reporte existe", report_row is not None)
check("estado borrador", report_row and report_row["status"] == REPORT_DRAFT)
check("notas guardadas", report_row and report_row["notes"] == "borrador test")
check("2 cargues", cargues == 2, f"got {cargues}")
check("2 retiros", retiros == 2, f"got {retiros}")

details = get_report_details(report_row["id"])
check(
    "totales calculados",
    details
    and details["summary"]["total_cargues"] == 300
    and details["summary"]["total_retiros"] == 1800
    and details["summary"]["total_fees"] == 100,
    str(details["summary"] if details else None),
)

# 4. Re-login y verificar persistencia
client.post("/salir")
r = client.post("/acceso", data={"username": WORKER, "password": WORKER_PASS})
r = client.get(f"/mis-reportes?fecha={fecha}")
check("datos tras re-login", r.status_code == 200 and "1300" in r.text)

# 5. Guardar y enviar
r = client.post(
    "/mis-reportes/guardar",
    data={
        "report_date": fecha,
        "action": "submit",
        "cargue_amount": ["200", "100"],
        "retiro_amount": ["1300", "500"],
        "notes": "enviado test",
    },
    follow_redirects=False,
)
check("guardar y enviar", r.status_code == 303)

with db_session() as conn:
    status = conn.execute(
        "SELECT status FROM daily_reports WHERE id = ?", (report_row["id"],)
    ).fetchone()["status"]
check("estado enviado", status == REPORT_SUBMITTED)

# 6. Admin confirma con descuento
client.post("/salir")
client.post("/acceso", data={"username": ADMIN, "password": ADMIN_PASS})

with db_session() as conn:
    wid = conn.execute("SELECT id FROM users WHERE username = ?", (WORKER,)).fetchone()["id"]

r = client.post(
    f"/clientes/{wid}/confirmar-reporte",
    data={
        "report_date": fecha,
        "discount_desc": ["Cuenta test"],
        "discount_amount": ["50"],
    },
    follow_redirects=False,
)
check("admin confirmar", r.status_code == 303)

with db_session() as conn:
    status = conn.execute(
        "SELECT status FROM daily_reports WHERE id = ?", (report_row["id"],)
    ).fetchone()["status"]
    discounts = parse_count(
        conn.execute(
            "SELECT COUNT(*) AS c FROM discounts WHERE report_id = ?",
            (report_row["id"],),
        ).fetchone()
    )

check("estado confirmado", status == "confirmed")
check("descuento guardado", discounts == 1)

# 7. Usuarios no borrados
with db_session() as conn:
    users = parse_count(conn.execute("SELECT COUNT(*) AS c FROM users").fetchone())
    admins = parse_count(
        conn.execute("SELECT COUNT(*) AS c FROM users WHERE role = 'admin'").fetchone()
    )

check("usuarios persisten", users >= 3, f"total {users}")
check("admins persisten", admins >= 2, f"admins {admins}")

print()
if errors:
    print("FALLÓ:")
    for e in errors:
        print(" -", e)
    raise SystemExit(1)

print("TODO OK: guardado, sesión, re-login, envío y confirmación funcionan.")
