"""Crea usuarios iniciales para BetPro."""
import os

from app.auth import hash_password
from app.config import ADMIN_NAME, ADMIN_PASSWORD, ADMIN_USERNAME
from app.database import db_session, init_db


def seed(include_demo_clients: bool = True) -> None:
    init_db()
    with db_session() as conn:
        existing = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if existing:
            return

        conn.execute(
            """
            INSERT INTO users (username, password_hash, name, role, retiro_fee)
            VALUES (?, ?, ?, 'admin', 0)
            """,
            (ADMIN_USERNAME, hash_password(ADMIN_PASSWORD), ADMIN_NAME),
        )

        if include_demo_clients:
            conn.execute(
                """
                INSERT INTO users (username, password_hash, name, role, retiro_fee)
                VALUES (?, ?, ?, 'worker', 50)
                """,
                ("juan", hash_password("juan123"), "Juan Pérez"),
            )
            conn.execute(
                """
                INSERT INTO users (username, password_hash, name, role, retiro_fee)
                VALUES (?, ?, ?, 'worker', 50)
                """,
                ("maria", hash_password("maria123"), "María López"),
            )


def seed_if_empty() -> None:
    """Ejecutar al iniciar la app (local o Vercel)."""
    init_db()
    with db_session() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if count == 0:
        demo = os.getenv("VERCEL") != "1"
        seed(include_demo_clients=demo)


if __name__ == "__main__":
    seed()
    print("Usuarios creados (si la BD estaba vacía).")
    print(f"  Admin: {ADMIN_USERNAME} / (ver BETPRO_ADMIN_PASSWORD)")
