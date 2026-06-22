"""Inicialización al arrancar la app (usuario admin por defecto)."""
from app.auth import hash_password
from app.config import ADMIN_NAME, ADMIN_PASSWORD, ADMIN_USERNAME
from app.database import db_session, init_db


def seed_admin() -> bool:
    """Crea el admin inicial si no hay usuarios. Devuelve True si creó uno."""
    with db_session() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if count:
            return False

        conn.execute(
            """
            INSERT INTO users (username, password_hash, name, role, retiro_fee)
            VALUES (?, ?, ?, 'admin', 0)
            """,
            (ADMIN_USERNAME, hash_password(ADMIN_PASSWORD), ADMIN_NAME),
        )
    return True


def seed_if_empty() -> None:
    init_db()
    seed_admin()
