import sqlite3
from contextlib import contextmanager
from typing import Any, Optional

from app.config import DB_PATH, IS_VERCEL, TURSO_AUTH_TOKEN, TURSO_DATABASE_URL, USE_TURSO
from app.db_row import DbRow


def _unwrap_turso_cell(value):
    """Turso HTTP v2 devuelve celdas como dict; null no trae 'value'."""
    if isinstance(value, dict) and "type" in value:
        if value.get("type") == "null":
            return None
        if "value" in value:
            return value["value"]
    return value


def _normalize_turso_value(column: str, value):
    """Turso/libsql puede devolver enteros como str; normaliza tipos."""
    value = _unwrap_turso_cell(value)
    if value is None:
        return None
    name = column.lower()
    if name in ("id", "active", "cnt", "count", "c") or name.endswith("_id"):
        return int(value)
    if name in ("amount", "retiro_fee", "total") or name.startswith("total_"):
        return float(value)
    return value


def parse_count(row, key: str = "c") -> int:
    if not row:
        return 0
    return int(row[key])


class _TursoResult:
    def __init__(self, response: dict):
        from turso_python.response_parser import TursoResponseParser

        normalized = TursoResponseParser.normalize_response(response)
        self.columns = tuple(normalized["columns"])
        self.rows = normalized["rows"]
        try:
            result = response["results"][0]["response"]["result"]
            rid = result.get("last_insert_rowid")
            self.last_insert_rowid = int(rid) if rid is not None else 0
        except (KeyError, IndexError, TypeError, ValueError):
            self.last_insert_rowid = 0


class _TursoCursor:
    def __init__(self, result_set: _TursoResult):
        self._result = result_set
        self._index = 0

    def _make_row(self, values: tuple) -> DbRow:
        cols = self._result.columns
        normalized = tuple(
            _normalize_turso_value(col, val) for col, val in zip(cols, values)
        )
        return DbRow(cols, normalized)

    def fetchone(self) -> Optional[DbRow]:
        if self._index >= len(self._result.rows):
            return None
        row = self._make_row(tuple(self._result.rows[self._index]))
        self._index += 1
        return row

    def fetchall(self) -> list[DbRow]:
        rows = []
        while True:
            row = self.fetchone()
            if row is None:
                break
            rows.append(row)
        return rows

    @property
    def lastrowid(self) -> int:
        return int(self._result.last_insert_rowid or 0)


class _BetproTursoClient:
    """Turso HTTP v2 con formato de args compatible con AWS."""

    def __init__(self, database_url: str, auth_token: str):
        from turso_python.connection import TursoConnection

        self._client = TursoConnection(
            database_url=database_url,
            auth_token=auth_token,
        )

    @staticmethod
    def _format_args(args: list | tuple | None) -> list[dict]:
        if not args:
            return []
        formatted: list[dict] = []
        for value in args:
            if isinstance(value, str):
                formatted.append({"type": "text", "value": value})
            elif isinstance(value, bool):
                formatted.append({"type": "integer", "value": "1" if value else "0"})
            elif isinstance(value, int):
                formatted.append({"type": "integer", "value": str(value)})
            elif isinstance(value, float):
                formatted.append({"type": "float", "value": value})
            elif value is None:
                formatted.append({"type": "null"})
            else:
                raise ValueError(f"Unsupported argument type: {type(value)}")
        return formatted

    def execute_query(self, sql: str, args: list | tuple | None = None) -> dict:
        payload = {
            "requests": [
                {
                    "type": "execute",
                    "stmt": {"sql": sql, "args": self._format_args(args)},
                },
                {"type": "close"},
            ]
        }
        response = self._client.session.post(
            f"{self._client.database_url}/v2/pipeline",
            json=payload,
            headers=self._client.headers,
            timeout=self._client.timeout,
        )
        return self._client._handle_response(response)

    def close(self) -> None:
        self._client.close()


class _TursoConnection:
    def __init__(self, client):
        self._client = client

    def execute(self, sql: str, params: tuple | list = ()):
        response = self._client.execute_query(sql, list(params) if params else None)
        return _TursoCursor(_TursoResult(response))

    def executescript(self, sql: str) -> None:
        statements = [part.strip() for part in sql.split(";") if part.strip()]
        for statement in statements:
            self._client.execute_query(statement)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        self._client.close()


def get_connection() -> Any:
    if USE_TURSO:
        client = _BetproTursoClient(
            database_url=TURSO_DATABASE_URL,
            auth_token=TURSO_AUTH_TOKEN,
        )
        return _TursoConnection(client)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def db_session():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate_currency(conn) -> None:
    user_cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "currency" not in user_cols:
        conn.execute(
            "ALTER TABLE users ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD'"
        )

    report_cols = {row[1] for row in conn.execute("PRAGMA table_info(daily_reports)").fetchall()}
    if "currency" not in report_cols:
        conn.execute(
            "ALTER TABLE daily_reports ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD'"
        )

    conn.execute(
        """
        UPDATE daily_reports
        SET currency = COALESCE(
            (SELECT currency FROM users u WHERE u.id = daily_reports.user_id),
            'USD'
        )
        WHERE currency IS NULL OR currency = ''
        """
    )


def _migrate_app_settings(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO app_settings (key, value) VALUES ('currency', 'USD')"
    )


def _migrate_cortes(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cortes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            total_net REAL NOT NULL DEFAULT 0,
            total_clients INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            accepted_at TEXT,
            accepted_by INTEGER,
            notes TEXT,
            FOREIGN KEY(accepted_by) REFERENCES users(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS corte_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            corte_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            user_name TEXT NOT NULL,
            confirmed_days INTEGER NOT NULL DEFAULT 0,
            cumulative_at_corte REAL NOT NULL,
            FOREIGN KEY(corte_id) REFERENCES cortes(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(cortes)").fetchall()}
    if "total_net" not in cols:
        conn.execute("ALTER TABLE cortes ADD COLUMN total_net REAL NOT NULL DEFAULT 0")
    if "total_clients" not in cols:
        conn.execute("ALTER TABLE cortes ADD COLUMN total_clients INTEGER NOT NULL DEFAULT 0")
    snap_cols = {row[1] for row in conn.execute("PRAGMA table_info(corte_snapshots)").fetchall()}
    if snap_cols and "user_name" not in snap_cols:
        conn.execute("ALTER TABLE corte_snapshots ADD COLUMN user_name TEXT NOT NULL DEFAULT ''")
    if snap_cols and "confirmed_days" not in snap_cols:
        conn.execute("ALTER TABLE corte_snapshots ADD COLUMN confirmed_days INTEGER NOT NULL DEFAULT 0")


def _migrate(conn) -> None:
    _migrate_currency(conn)
    _migrate_app_settings(conn)
    _migrate_cortes(conn)
    if USE_TURSO:
        return

    report_cols = {row[1] for row in conn.execute("PRAGMA table_info(daily_reports)").fetchall()}
    if "status" not in report_cols:
        conn.execute(
            "ALTER TABLE daily_reports ADD COLUMN status TEXT NOT NULL DEFAULT 'draft'"
        )
    if "submitted_at" not in report_cols:
        conn.execute("ALTER TABLE daily_reports ADD COLUMN submitted_at TEXT")
    if "confirmed_at" not in report_cols:
        conn.execute("ALTER TABLE daily_reports ADD COLUMN confirmed_at TEXT")
    if "confirmed_by" not in report_cols:
        conn.execute("ALTER TABLE daily_reports ADD COLUMN confirmed_by INTEGER")

    retiro_cols = {row[1] for row in conn.execute("PRAGMA table_info(retiros)").fetchall()}
    if "confirmed" in retiro_cols:
        conn.execute(
            """
            UPDATE daily_reports
            SET status = 'confirmed', confirmed_at = COALESCE(confirmed_at, updated_at)
            WHERE status = 'draft'
              AND id IN (
                SELECT DISTINCT report_id FROM retiros WHERE confirmed = 1
              )
            """
        )
        conn.execute(
            """
            UPDATE daily_reports
            SET status = 'submitted', submitted_at = COALESCE(submitted_at, updated_at)
            WHERE status = 'draft'
              AND (EXISTS (SELECT 1 FROM cargues c WHERE c.report_id = daily_reports.id)
                   OR EXISTS (SELECT 1 FROM retiros r WHERE r.report_id = daily_reports.id))
            """
        )


def _create_indexes(conn) -> None:
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_reports_user_date
            ON daily_reports(user_id, report_date);
        CREATE INDEX IF NOT EXISTS idx_reports_status
            ON daily_reports(status);
        CREATE INDEX IF NOT EXISTS idx_cargues_report
            ON cargues(report_id);
        CREATE INDEX IF NOT EXISTS idx_retiros_report
            ON retiros(report_id);
        CREATE INDEX IF NOT EXISTS idx_discounts_report
            ON discounts(report_id);
        """
    )


def init_db() -> None:
    with db_session() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                name TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'worker')),
                retiro_fee REAL NOT NULL DEFAULT 50,
                currency TEXT NOT NULL DEFAULT 'USD',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS daily_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                report_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                currency TEXT NOT NULL DEFAULT 'USD',
                notes TEXT,
                submitted_at TEXT,
                confirmed_at TEXT,
                confirmed_by INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(user_id, report_date),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(confirmed_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS cargues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                FOREIGN KEY(report_id) REFERENCES daily_reports(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS retiros (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                FOREIGN KEY(report_id) REFERENCES daily_reports(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS discounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL,
                description TEXT NOT NULL,
                amount REAL NOT NULL,
                FOREIGN KEY(report_id) REFERENCES daily_reports(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cortes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                total_net REAL NOT NULL DEFAULT 0,
                total_clients INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                accepted_at TEXT,
                accepted_by INTEGER,
                notes TEXT,
                FOREIGN KEY(accepted_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS corte_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                corte_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                user_name TEXT NOT NULL,
                confirmed_days INTEGER NOT NULL DEFAULT 0,
                cumulative_at_corte REAL NOT NULL,
                FOREIGN KEY(corte_id) REFERENCES cortes(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO app_settings (key, value) VALUES ('currency', 'USD')"
        )
        _migrate(conn)
        _create_indexes(conn)


def check_db_connection() -> dict:
    """Comprueba que la base responde. Usado en /api/salud y scripts de diagnóstico."""
    try:
        info = db_info()
        ephemeral = IS_VERCEL and not USE_TURSO
        return {
            "ok": True,
            "engine": info.get("engine"),
            "users": info.get("users", 0),
            "reports": info.get("reports", 0),
            "turso": USE_TURSO,
            "ephemeral": ephemeral,
            "persistent": not ephemeral,
            "warning": (
                "Base de datos NO persistente. Configura TURSO_DATABASE_URL y TURSO_AUTH_TOKEN en Vercel."
                if ephemeral
                else None
            ),
        }
    except Exception as exc:
        return {
            "ok": False,
            "turso": USE_TURSO,
            "ephemeral": IS_VERCEL and not USE_TURSO,
            "error": f"{type(exc).__name__}: {exc}",
        }


def db_info() -> dict:
    engine = "Turso (SQLite en la nube)" if USE_TURSO else "SQLite 3 (archivo local)"

    if USE_TURSO:
        with db_session() as conn:
            users = parse_count(conn.execute("SELECT COUNT(*) AS c FROM users").fetchone())
            reports = parse_count(conn.execute("SELECT COUNT(*) AS c FROM daily_reports").fetchone())
        return {
            "exists": True,
            "path": TURSO_DATABASE_URL,
            "engine": engine,
            "users": users,
            "reports": reports,
        }

    if not DB_PATH.exists():
        return {"exists": False, "path": str(DB_PATH), "engine": engine}

    size_mb = round(DB_PATH.stat().st_size / (1024 * 1024), 2)
    with db_session() as conn:
        users = parse_count(conn.execute("SELECT COUNT(*) AS c FROM users").fetchone())
        reports = parse_count(conn.execute("SELECT COUNT(*) AS c FROM daily_reports").fetchone())

    return {
        "exists": True,
        "path": str(DB_PATH),
        "engine": engine,
        "size_mb": size_mb,
        "users": users,
        "reports": reports,
    }
