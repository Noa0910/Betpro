import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

IS_VERCEL = os.getenv("VERCEL") == "1"

# SQLite local (gratis). En Vercel usa /tmp (efímero) o BETPRO_DB_PATH externo.
_default_db = "/tmp/betpro.db" if IS_VERCEL else str(BASE_DIR / "betpro.db")
DB_PATH = Path(os.getenv("BETPRO_DB_PATH", _default_db))

BACKUP_DIR = BASE_DIR / "backups"

# Credenciales iniciales (solo si la BD está vacía)
ADMIN_USERNAME = os.getenv("BETPRO_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("BETPRO_ADMIN_PASSWORD", "admin123")
ADMIN_NAME = os.getenv("BETPRO_ADMIN_NAME", "Administrador BetPro")
