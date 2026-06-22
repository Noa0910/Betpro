"""Crea los admins iniciales (si la BD está vacía)."""
from app.bootstrap import DEFAULT_ADMINS, seed_if_empty


if __name__ == "__main__":
    seed_if_empty()
    print("Listo. Administradores:")
    for username, password, name in DEFAULT_ADMINS:
        print(f"  - {username} / {password} ({name})")
