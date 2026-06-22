"""Resetea la base de datos y deja los admins iniciales."""
from pathlib import Path

from app.bootstrap import DEFAULT_ADMINS, seed_admin
from app.config import DB_PATH, USE_TURSO
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
    print("Administradores:")
    for username, password, name in DEFAULT_ADMINS:
        print(f"  - {username} / {password} ({name})")


if __name__ == "__main__":
    reset_db()
