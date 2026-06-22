import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

IS_VERCEL = os.getenv("VERCEL") == "1"

TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "").strip()
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()
USE_TURSO = bool(TURSO_DATABASE_URL and TURSO_AUTH_TOKEN)

# SQLite local (gratis). En Vercel sin Turso usa /tmp (no persistente).
_default_db = "/tmp/betpro.db" if IS_VERCEL and not USE_TURSO else str(BASE_DIR / "betpro.db")
DB_PATH = Path(os.getenv("BETPRO_DB_PATH", _default_db))

BACKUP_DIR = BASE_DIR / "backups"

# Credenciales iniciales (solo si la BD está vacía)
ADMIN_USERNAME = os.getenv("BETPRO_ADMIN_USER", "nosorio")
ADMIN_PASSWORD = os.getenv("BETPRO_ADMIN_PASSWORD", "Nosorio2026!")
ADMIN_NAME = os.getenv("BETPRO_ADMIN_NAME", "Nicolas Osorio")
