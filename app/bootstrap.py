"""Inicialización al arrancar la app (admins por defecto si la BD está vacía)."""
from app.auth import hash_password
from app.config import ADMIN_NAME, ADMIN_PASSWORD, ADMIN_USERNAME
from app.database import db_session, init_db, parse_count

DEFAULT_ADMINS = (
    (ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_NAME),
    ("cacevedo", "Cacevedo2026!", "Cesar Acevedo"),
)


def seed_admin() -> bool:
    """Crea los admins iniciales si no hay usuarios. Devuelve True si creó alguno."""
    with db_session() as conn:
        count = parse_count(conn.execute("SELECT COUNT(*) AS c FROM users").fetchone())
        if count > 0:
            return False

        for username, password, name in DEFAULT_ADMINS:
            conn.execute(
                """
                INSERT INTO users (username, password_hash, name, role, retiro_fee)
                VALUES (?, ?, ?, 'admin', 0)
                """,
                (username, hash_password(password), name),
            )
    return True


def ensure_default_admins() -> None:
    """Crea admins por defecto que falten (recuperación sin borrar datos)."""
    with db_session() as conn:
        for username, password, name in DEFAULT_ADMINS:
            exists = conn.execute(
                "SELECT id FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if exists:
                continue
            conn.execute(
                """
                INSERT INTO users (username, password_hash, name, role, retiro_fee)
                VALUES (?, ?, ?, 'admin', 0)
                """,
                (username, hash_password(password), name),
            )


def seed_if_empty() -> None:
    init_db()
    seed_admin()
    ensure_default_admins()
