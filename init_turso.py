"""Crea tablas e inicializa admins en Turso (o SQLite local)."""
from app.bootstrap import seed_if_empty
from app.config import USE_TURSO
from app.database import db_session, init_db

EXPECTED_TABLES = ("users", "daily_reports", "cargues", "retiros", "discounts")


def main() -> None:
    print("Inicializando base de datos...")
    init_db()
    seed_if_empty()

    with db_session() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        tables = [r["name"] for r in rows if not r["name"].startswith("sqlite_")]

    missing = [t for t in EXPECTED_TABLES if t not in tables]
    if missing:
        print(f"ERROR: faltan tablas: {missing}")
        raise SystemExit(1)

    print(f"Motor: {'Turso' if USE_TURSO else 'SQLite local'}")
    print("Tablas:", ", ".join(tables))
    for name in EXPECTED_TABLES:
        with db_session() as conn:
            count = conn.execute(f"SELECT COUNT(*) AS c FROM {name}").fetchone()["c"]
        print(f"  {name}: {count} filas")

    with db_session() as conn:
        admins = conn.execute(
            "SELECT username, name FROM users WHERE role='admin' ORDER BY username"
        ).fetchall()

    print("Admins listos:")
    for a in admins:
        print(f"  - {a['username']} ({a['name']})")
    print("OK: base de datos lista para usar")


if __name__ == "__main__":
    main()
