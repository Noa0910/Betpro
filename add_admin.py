"""Añade un usuario administrador a la base de datos."""
import sys

from app.services import create_admin


def add_admin(username: str, password: str, name: str) -> None:
    create_admin(username, password, name)
    print(f"Admin creado: {username} / {password} ({name})")


if __name__ == "__main__":
    if len(sys.argv) >= 4:
        add_admin(sys.argv[1], sys.argv[2], " ".join(sys.argv[3:]))
    else:
        add_admin("cacevedo", "Cacevedo2026!", "Cesar Acevedo")
