import hashlib
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

IS_VERCEL = os.getenv("VERCEL") == "1"

CANONICAL_HOST = os.getenv("BETPRO_CANONICAL_HOST", "www.betpro.management").strip()

APP_VERSION = "2026.06.22-3"

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


def get_session_secret() -> str:
    """Clave estable para firmar sesiones (crítico en Vercel serverless)."""
    secret = os.getenv("BETPRO_SECRET", "").strip()
    if secret:
        return secret

    if IS_VERCEL:
        for source in (
            TURSO_AUTH_TOKEN,
            os.getenv("VERCEL_PROJECT_ID", "").strip(),
            "betpro-vercel-default",
        ):
            if source:
                return hashlib.sha256(f"betpro-session:{source}".encode()).hexdigest()

    import secrets

    return secrets.token_hex(32)
