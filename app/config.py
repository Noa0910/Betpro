import hashlib
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

IS_VERCEL = os.getenv("VERCEL") == "1"

CANONICAL_HOST = os.getenv("BETPRO_CANONICAL_HOST", "www.betpro.management").strip()

APP_VERSION = "2026.07.03-2"


def _normalize_turso_url(url: str) -> str:
    """Turso en AWS requiere HTTPS; libsql:// usa WebSocket (obsoleto)."""
    url = url.strip()
    if url.startswith("libsql://"):
        return "https://" + url[len("libsql://") :]
    return url


TURSO_DATABASE_URL = _normalize_turso_url(os.getenv("TURSO_DATABASE_URL", ""))
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()
USE_TURSO = bool(TURSO_DATABASE_URL and TURSO_AUTH_TOKEN)
DB_EPHEMERAL = IS_VERCEL and not USE_TURSO

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

    secret_file = BASE_DIR / ".betpro_session_secret"
    if secret_file.exists():
        return secret_file.read_text(encoding="utf-8").strip()

    import secrets

    secret = secrets.token_hex(32)
    secret_file.write_text(secret, encoding="utf-8")
    return secret
