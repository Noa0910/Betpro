"""Copia de seguridad de la base de datos SQLite de BetPro."""
import shutil
import sys
from datetime import datetime
from pathlib import Path

from app.config import BACKUP_DIR, DB_PATH


def backup() -> Path:
    if not DB_PATH.exists():
        print(f"No existe la base de datos: {DB_PATH}")
        print("Ejecuta primero: python seed.py")
        sys.exit(1)

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"betpro_{stamp}.db"
    shutil.copy2(DB_PATH, dest)

    # Mantener solo los últimos 30 respaldos
    backups = sorted(BACKUP_DIR.glob("betpro_*.db"), reverse=True)
    for old in backups[30:]:
        old.unlink(missing_ok=True)

    return dest


if __name__ == "__main__":
    path = backup()
    print(f"Respaldo creado: {path}")
