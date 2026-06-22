"""Crea usuarios iniciales para BetPro (uso local)."""
from app.bootstrap import seed_if_empty
from app.config import ADMIN_PASSWORD, ADMIN_USERNAME


if __name__ == "__main__":
    seed_if_empty()
    print("Usuarios creados (si la BD estaba vacía).")
    print(f"  Admin: {ADMIN_USERNAME} / {ADMIN_PASSWORD}")
