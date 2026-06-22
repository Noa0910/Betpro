"""Resetea la base de datos y deja solo el usuario admin inicial."""
from pathlib import Path

from app.bootstrap import seed_admin
from app.config import ADMIN_NAME, ADMIN_PASSWORD, ADMIN_USERNAME, DB_PATH, USE_TURSO
from app.database import db_session, init_db


def reset_db() -> None:
    if USE_TURSO:
        with db_session() as conn:
            conn.execute("DELETE FROM discounts")
            conn.execute("DELETE FROM retiros")
            conn.execute("DELETE FROM cargues")
            conn.execute("DELETE FROM daily_reports")
            conn.execute("DELETE FROM users")
    else:
        for path in (
            DB_PATH,
            Path(f"{DB_PATH}-wal"),
            Path(f"{DB_PATH}-shm"),
        ):
            if path.exists():
                path.unlink()

    init_db()
    seed_admin()
    print("Base de datos limpia.")
    print(f"  Admin: {ADMIN_USERNAME} / {ADMIN_PASSWORD}")
    print(f"  Nombre: {ADMIN_NAME}")


if __name__ == "__main__":
    reset_db()
