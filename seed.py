"""Crea el usuario admin inicial (si la BD está vacía)."""
from app.bootstrap import seed_if_empty
from app.config import ADMIN_NAME, ADMIN_PASSWORD, ADMIN_USERNAME


if __name__ == "__main__":
    seed_if_empty()
    print(f"Listo. Admin: {ADMIN_USERNAME} / {ADMIN_PASSWORD} ({ADMIN_NAME})")
