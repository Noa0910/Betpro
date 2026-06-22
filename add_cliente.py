"""Crea un cliente (trabajador) en la base de datos."""
import sys

from app.services import create_worker


def add_cliente(username: str, password: str, name: str, retiro_fee: float = 50) -> None:
    create_worker(username, password, name, retiro_fee)
    print(f"Cliente creado: {username} / {password} ({name}) — tarifa ${retiro_fee}")


if __name__ == "__main__":
    if len(sys.argv) >= 4:
        fee = float(sys.argv[4]) if len(sys.argv) > 4 else 50.0
        add_cliente(sys.argv[1], sys.argv[2], sys.argv[3], fee)
    else:
        print("Uso: python add_cliente.py usuario contraseña \"Nombre completo\" [tarifa]")
        print('Ejemplo: python add_cliente.py mgranada "Mgrana2026*" "M Granada" 50')
