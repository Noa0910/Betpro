from typing import Optional

import bcrypt
from fastapi import Request
from fastapi.responses import RedirectResponse

from app import urls as U
from app.database import db_session

TEMP_RESET_PASSWORD = "123"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def get_user_by_id(user_id: int) -> Optional[dict]:
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT id, username, name, role, retiro_fee, currency, active,
                   must_change_password
            FROM users WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
        if not row:
            return None
        user = dict(row)
        from app.currencies import normalize_currency

        user["currency"] = normalize_currency(user.get("currency"))
        return user


def get_user_by_username(username: str) -> Optional[dict]:
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username.strip().lower(),),
        ).fetchone()
        return dict(row) if row else None


def session_user_payload(user: dict) -> dict:
    from app.settings import get_system_currency

    return {
        "id": int(user["id"]),
        "username": user["username"],
        "name": user["name"],
        "role": user["role"],
        "retiro_fee": float(user.get("retiro_fee") or 0),
        "currency": get_system_currency(),
        "must_change_password": bool(int(user.get("must_change_password") or 0)),
    }


def authenticate_user(username: str, password: str) -> Optional[dict]:
    user = get_user_by_username(username)
    if not user or not int(user.get("active") or 0):
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return session_user_payload(user)


def login_redirect() -> RedirectResponse:
    return RedirectResponse(U.ACCESO, status_code=303)


def password_change_redirect() -> RedirectResponse:
    return RedirectResponse(U.NUEVA_CONTRASENA, status_code=303)


def _paths_exempt_from_password_change(path: str) -> bool:
    return path in (U.NUEVA_CONTRASENA, U.SALIR) or path.startswith("/static")


def _password_change_redirect(request: Request, user: dict) -> Optional[RedirectResponse]:
    if not user.get("must_change_password"):
        return None
    if _paths_exempt_from_password_change(request.url.path):
        return None
    return password_change_redirect()


def _refresh_session_user(request: Request) -> tuple[Optional[dict], Optional[RedirectResponse]]:
    stored = request.session.get("user")
    if not stored:
        return None, login_redirect()

    try:
        user_id = int(stored["id"])
    except (KeyError, TypeError, ValueError):
        request.session.clear()
        return None, login_redirect()

    try:
        fresh = get_user_by_id(user_id)
    except Exception:
        # Si la BD falla momentáneamente, mantener la sesión activa.
        return session_user_payload(stored), None

    if not fresh:
        request.session.clear()
        return None, login_redirect()

    if not int(fresh.get("active") or 0):
        request.session.clear()
        return None, login_redirect()

    user = session_user_payload(fresh)
    if stored != user:
        request.session["user"] = user
    return user, None


def check_user_session(
    request: Request,
    *,
    allow_password_change_page: bool = False,
) -> tuple[Optional[dict], Optional[RedirectResponse]]:
    user, redirect = _refresh_session_user(request)
    if redirect:
        return None, redirect
    if not allow_password_change_page:
        pc_redirect = _password_change_redirect(request, user)
        if pc_redirect:
            return None, pc_redirect
    return user, None


def check_admin_session(
    request: Request,
    *,
    allow_password_change_page: bool = False,
) -> tuple[Optional[dict], Optional[RedirectResponse]]:
    user, redirect = check_user_session(
        request, allow_password_change_page=allow_password_change_page
    )
    if redirect:
        return None, redirect
    if user["role"] != "admin":
        return None, RedirectResponse(U.MIS_REPORTES, status_code=303)
    return user, None
