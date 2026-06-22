"""Inicialización al arrancar la app (usuarios por defecto)."""
import os

from app.auth import hash_password
from app.config import ADMIN_NAME, ADMIN_PASSWORD, ADMIN_USERNAME
from app.database import db_session, init_db


def seed_if_empty() -> None:
    init_db()
    with db_session() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if count:
        return

    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO users (username, password_hash, name, role, retiro_fee)
            VALUES (?, ?, ?, 'admin', 0)
            """,
            (ADMIN_USERNAME, hash_password(ADMIN_PASSWORD), ADMIN_NAME),
        )

        if os.getenv("VERCEL") != "1":
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
