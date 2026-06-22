"""Diagnóstico de base de datos BetPro."""
from app.bootstrap import seed_if_empty
from app.config import DB_PATH, IS_VERCEL, TURSO_DATABASE_URL, USE_TURSO
from app.database import check_db_connection, db_session, parse_count


def main() -> None:
    print("=== BetPro DB Check ===")
    print(f"USE_TURSO: {USE_TURSO}")
    print(f"IS_VERCEL: {IS_VERCEL}")
    print(f"DB_PATH: {DB_PATH}")
    print(f"TURSO_URL: {'(configurada)' if TURSO_DATABASE_URL else '(no configurada)'}")

    if IS_VERCEL and not USE_TURSO:
        print()
        print("AVISO: En Vercel sin Turso los datos NO persisten.")
        print("Configura TURSO_DATABASE_URL y TURSO_AUTH_TOKEN en vercel.com")

    try:
        seed_if_empty()
        status = check_db_connection()
        if not status.get("ok"):
            print(f"ERROR: {status.get('error')}")
            raise SystemExit(1)

        print(f"Motor: {status.get('engine')}")
        print(f"Usuarios: {status.get('users')}")
        print(f"Reportes: {status.get('reports')}")

        with db_session() as conn:
            admins = conn.execute(
                "SELECT username, active FROM users WHERE role = 'admin' ORDER BY username"
            ).fetchall()
            workers = parse_count(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM users WHERE role = 'worker'"
                ).fetchone()
            )
        print(f"Admins: {[dict(a) for a in admins]}")
        print(f"Clientes: {workers}")
        print("OK: base de datos operativa")
    except SystemExit:
        raise
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

