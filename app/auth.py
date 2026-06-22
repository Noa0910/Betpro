from typing import Optional

import bcrypt
from fastapi import Request
from fastapi.responses import RedirectResponse

from app import urls as U
from app.database import db_session


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def get_user_by_id(user_id: int) -> Optional[dict]:
    with db_session() as conn:
        row = conn.execute(
            "SELECT id, username, name, role, retiro_fee, active FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def get_user_by_username(username: str) -> Optional[dict]:
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username.strip().lower(),),
        ).fetchone()
        return dict(row) if row else None


def authenticate_user(username: str, password: str) -> Optional[dict]:
    user = get_user_by_username(username)
    if not user or not user["active"]:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return {
        "id": user["id"],
        "username": user["username"],
        "name": user["name"],
        "role": user["role"],
        "retiro_fee": user["retiro_fee"],
    }


def login_redirect() -> RedirectResponse:
    return RedirectResponse(U.ACCESO, status_code=303)


def check_user_session(request: Request) -> tuple[Optional[dict], Optional[RedirectResponse]]:
    user = request.session.get("user")
    if not user:
        return None, login_redirect()
    return user, None


def check_admin_session(request: Request) -> tuple[Optional[dict], Optional[RedirectResponse]]:
    user = request.session.get("user")
    if not user:
        return None, login_redirect()
    if user["role"] != "admin":
        return None, RedirectResponse(U.MIS_REPORTES, status_code=303)
    return user, None
