import json
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request as StarletteRequest

from app import urls as U
from app.auth import authenticate_user, check_admin_session, check_user_session, login_redirect
from app.config import CANONICAL_HOST, IS_VERCEL, get_session_secret
from app.services import (
    REPORT_CONFIRMED,
    REPORT_SUBMITTED,
    confirm_report,
    count_pending_reports,
    create_worker,
    create_admin,
    get_admin_analytics,
    get_cumulative_total,
    get_or_create_report,
    get_report_details,
    get_user_reports,
    list_pending_reports,
    list_admins,
    list_workers,
    parse_amount,
    reopen_report,
    save_admin_entries,
    save_client_report,
    save_discounts,
    today_iso,
    update_worker_fee,
    update_worker_status,
    update_admin_status,
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR.parent / "public" / "static"
if not STATIC_DIR.exists():
    STATIC_DIR = BASE_DIR / "static"
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="BetPro", version="1.0.0")

app.add_middleware(
    SessionMiddleware,
    secret_key=get_session_secret(),
    same_site="lax",
    https_only=IS_VERCEL,
    max_age=60 * 60 * 24 * 14,
    session_cookie="betpro_session",
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.middleware("http")
async def redirect_vercel_domain(request: Request, call_next):
    if CANONICAL_HOST and request.method in ("GET", "HEAD"):
        host = request.headers.get("host", "").split(":")[0].lower()
        if host.endswith(".vercel.app") and host != CANONICAL_HOST:
            target = request.url.replace(scheme="https", netloc=CANONICAL_HOST)
            return RedirectResponse(str(target), status_code=301)
    return await call_next(request)


@app.on_event("startup")
def startup() -> None:
    from app.bootstrap import seed_if_empty

    seed_if_empty()


@app.exception_handler(RequestValidationError)
async def validation_error(request: StarletteRequest, exc: RequestValidationError):
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "message": "Revisa que todos los campos del formulario estén completos.",
            },
            status_code=400,
        )
    return HTMLResponse("Datos inválidos", status_code=400)


@app.exception_handler(Exception)
async def unhandled_error(request: StarletteRequest, exc: Exception):
    if isinstance(exc, StarletteHTTPException):
        raise exc

    import traceback

    traceback.print_exc()
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "message": "Ocurrió un error al procesar la solicitud. Intenta de nuevo.",
            },
            status_code=500,
        )
    return HTMLResponse("Error interno del servidor", status_code=500)


def fmt_money(value: float) -> str:
    return f"${value:,.2f}"


templates.env.filters["money"] = fmt_money
templates.env.filters["tojson"] = lambda v: json.dumps(v)
templates.env.globals["url"] = U


def build_cargues_items(report: dict) -> list[dict]:
    return [{"amount": c["amount"]} for c in report["cargues"]]


def build_retiros_items(report: dict) -> list[dict]:
    return [{"amount": r["amount"]} for r in report["retiros"]]


def build_discount_items(report: dict) -> list[dict]:
    return [
        {"description": d["description"], "amount": d["amount"]}
        for d in report["discounts"]
    ]


def report_context(report: dict) -> dict:
    return {
        "cargues_items": build_cargues_items(report),
        "retiros_items": build_retiros_items(report),
        "discount_items": build_discount_items(report),
    }


def redirect_login() -> RedirectResponse:
    return login_redirect()


def redirect_home(user: dict) -> RedirectResponse:
    if user["role"] == "admin":
        return RedirectResponse(U.REPORTES, status_code=303)
    return RedirectResponse(U.MIS_REPORTES, status_code=303)


def with_query(path: str, **params) -> str:
    clean = {k: v for k, v in params.items() if v is not None}
    if not clean:
        return path
    return f"{path}?{urlencode(clean)}"


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    user = request.session.get("user")
    if not user:
        return redirect_login()
    return redirect_home(user)


@app.get(U.ACCESO, response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None},
    )


@app.post(U.ACCESO)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    user = authenticate_user(username, password)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Usuario o contraseña incorrectos"},
            status_code=400,
        )
    request.session["user"] = user
    return RedirectResponse("/", status_code=303)


@app.get(U.SALIR)
async def logout(request: Request):
    request.session.clear()
    return redirect_login()


@app.get(U.MIS_REPORTES, response_class=HTMLResponse)
async def worker_panel(request: Request, fecha: str | None = None):
    user, auth_redirect = check_user_session(request)
    if auth_redirect:
        return auth_redirect

    if user["role"] == "admin":
        return RedirectResponse(U.REPORTES, status_code=303)

    report_date = fecha or today_iso()
    report = get_or_create_report(user["id"], report_date)
    details = get_report_details(report["id"])
    history = get_user_reports(user["id"], limit=15)
    cumulative = get_cumulative_total(user["id"])
    ctx = report_context(details)

    return templates.TemplateResponse(
        "worker_panel.html",
        {
            "request": request,
            "user": user,
            "report": details,
            "report_date": report_date,
            "history": history,
            "cumulative": cumulative,
            "message": request.query_params.get("msg"),
            "error": request.query_params.get("error"),
            **ctx,
        },
    )


@app.post(U.mis_reportes_guardar())
async def worker_save_report(
    request: Request,
    report_date: str = Form(...),
    cargue_amount: list[str] = Form(default=[]),
    retiro_amount: list[str] = Form(default=[]),
    notes: str = Form(""),
):
    user, auth_redirect = check_user_session(request)
    if auth_redirect:
        return auth_redirect

    report = get_or_create_report(user["id"], report_date)
    try:
        save_client_report(report["id"], cargue_amount, retiro_amount, notes)
    except ValueError as exc:
        details = get_report_details(report["id"])
        ctx = report_context(details)
        return templates.TemplateResponse(
            "worker_panel.html",
            {
                "request": request,
                "user": user,
                "report": details,
                "report_date": report_date,
                "history": get_user_reports(user["id"], limit=15),
                "cumulative": get_cumulative_total(user["id"]),
                "error": str(exc),
                **ctx,
            },
            status_code=400,
        )

    return RedirectResponse(
        with_query(
            U.MIS_REPORTES,
            fecha=report_date,
            msg="Reporte enviado al admin para confirmación",
        ),
        status_code=303,
    )


@app.get(U.REPORTES, response_class=HTMLResponse)
async def admin_dashboard(request: Request, period: str = "all"):
    user, auth_redirect = check_admin_session(request)
    if auth_redirect:
        return auth_redirect

    if period not in ("all", "today", "week", "month"):
        period = "all"

    analytics = get_admin_analytics(period)
    pending = list_pending_reports()

    return templates.TemplateResponse(
        "admin_analytics.html",
        {
            "request": request,
            "user": user,
            "analytics": analytics,
            "pending_reports": pending,
            "period": period,
            "message": request.query_params.get("msg"),
            "error": request.query_params.get("error"),
        },
    )


@app.get(U.CLIENTES, response_class=HTMLResponse)
async def admin_clients(request: Request):
    user, auth_redirect = check_admin_session(request)
    if auth_redirect:
        return auth_redirect

    workers = list_workers()
    pending = list_pending_reports()

    return templates.TemplateResponse(
        "admin_clients.html",
        {
            "request": request,
            "user": user,
            "workers": workers,
            "pending_reports": pending,
            "total_pending": count_pending_reports(),
            "message": request.query_params.get("msg"),
            "error": request.query_params.get("error"),
        },
    )


@app.post(U.CLIENTES)
async def admin_create_worker(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    name: str = Form(...),
    retiro_fee: str = Form("50"),
):
    _, auth_redirect = check_admin_session(request)
    if auth_redirect:
        return auth_redirect
    try:
        if password != password_confirm:
            raise ValueError("Las contraseñas no coinciden")
        create_worker(username, password, name, parse_amount(retiro_fee))
    except ValueError as exc:
        return RedirectResponse(with_query(U.CLIENTES, error=str(exc)), status_code=303)
    return RedirectResponse(with_query(U.CLIENTES, msg="Cliente creado"), status_code=303)


@app.get(U.ADMINISTRADORES, response_class=HTMLResponse)
async def admin_users_page(request: Request):
    user, auth_redirect = check_admin_session(request)
    if auth_redirect:
        return auth_redirect

    return templates.TemplateResponse(
        "admin_admins.html",
        {
            "request": request,
            "user": user,
            "admins": list_admins(),
            "message": request.query_params.get("msg"),
            "error": request.query_params.get("error"),
        },
    )


@app.post(U.ADMINISTRADORES)
async def admin_create_admin(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    name: str = Form(...),
):
    _, auth_redirect = check_admin_session(request)
    if auth_redirect:
        return auth_redirect
    try:
        if password != password_confirm:
            raise ValueError("Las contraseñas no coinciden")
        create_admin(username, password, name)
    except ValueError as exc:
        return RedirectResponse(
            with_query(U.ADMINISTRADORES, error=str(exc)),
            status_code=303,
        )
    return RedirectResponse(
        with_query(U.ADMINISTRADORES, msg="Administrador creado"),
        status_code=303,
    )


@app.post("/administradores/{admin_id}/estado")
async def admin_toggle_admin(request: Request, admin_id: int, active: str = Form(...)):
    actor, auth_redirect = check_admin_session(request)
    if auth_redirect:
        return auth_redirect
    try:
        update_admin_status(admin_id, active == "1", actor["id"])
    except ValueError as exc:
        return RedirectResponse(
            with_query(U.ADMINISTRADORES, error=str(exc)),
            status_code=303,
        )
    return RedirectResponse(
        with_query(U.ADMINISTRADORES, msg="Estado actualizado"),
        status_code=303,
    )


@app.post("/clientes/{worker_id}/tarifa")
async def admin_update_fee(
    request: Request,
    worker_id: int,
    retiro_fee: str = Form(...),
):
    _, auth_redirect = check_admin_session(request)
    if auth_redirect:
        return auth_redirect
    try:
        update_worker_fee(worker_id, parse_amount(retiro_fee))
    except ValueError as exc:
        return RedirectResponse(with_query(U.CLIENTES, error=str(exc)), status_code=303)
    return RedirectResponse(with_query(U.CLIENTES, msg="Tarifa actualizada"), status_code=303)


@app.post("/clientes/{worker_id}/estado")
async def admin_toggle_worker(request: Request, worker_id: int, active: str = Form(...)):
    _, auth_redirect = check_admin_session(request)
    if auth_redirect:
        return auth_redirect
    try:
        update_worker_status(worker_id, active == "1")
    except ValueError as exc:
        return RedirectResponse(with_query(U.CLIENTES, error=str(exc)), status_code=303)
    return RedirectResponse(with_query(U.CLIENTES, msg="Estado actualizado"), status_code=303)


@app.get("/clientes/{worker_id}", response_class=HTMLResponse)
async def admin_worker_detail(request: Request, worker_id: int, fecha: str | None = None):
    user, auth_redirect = check_admin_session(request)
    if auth_redirect:
        return auth_redirect

    from app.auth import get_user_by_id

    worker = get_user_by_id(worker_id)
    if not worker or worker["role"] != "worker":
        return RedirectResponse(U.REPORTES, status_code=303)

    report_date = fecha or today_iso()
    report = get_or_create_report(worker_id, report_date)
    details = get_report_details(report["id"])
    history = get_user_reports(worker_id, limit=30)
    cumulative = get_cumulative_total(worker_id)
    ctx = report_context(details)

    return templates.TemplateResponse(
        "admin_worker_detail.html",
        {
            "request": request,
            "user": user,
            "worker": worker,
            "report": details,
            "report_date": report_date,
            "history": history,
            "cumulative": cumulative,
            "can_confirm": details["status"] == REPORT_SUBMITTED,
            "is_confirmed": details["status"] == REPORT_CONFIRMED,
            "can_reopen": details["status"] == REPORT_SUBMITTED,
            "admin_can_edit": details["admin_can_edit_entries"],
            "message": request.query_params.get("msg"),
            "error": request.query_params.get("error"),
            **ctx,
        },
    )


@app.post("/clientes/{worker_id}/descuentos")
async def admin_save_discounts(
    request: Request,
    worker_id: int,
    report_date: str = Form(...),
    discount_desc: list[str] = Form(default=[]),
    discount_amount: list[str] = Form(default=[]),
):
    _, auth_redirect = check_admin_session(request)
    if auth_redirect:
        return auth_redirect

    report = get_or_create_report(worker_id, report_date)
    try:
        save_discounts(report["id"], discount_desc, discount_amount)
    except ValueError as exc:
        return RedirectResponse(
            with_query(U.cliente(worker_id), fecha=report_date, error=str(exc)),
            status_code=303,
        )

    return RedirectResponse(
        with_query(U.cliente(worker_id), fecha=report_date, msg="Descuentos guardados"),
        status_code=303,
    )


@app.post("/clientes/{worker_id}/confirmar-reporte")
async def admin_confirm_report(
    request: Request,
    worker_id: int,
    report_date: str = Form(...),
    discount_desc: list[str] = Form(default=[]),
    discount_amount: list[str] = Form(default=[]),
):
    admin, auth_redirect = check_admin_session(request)
    if auth_redirect:
        return auth_redirect

    report = get_or_create_report(worker_id, report_date)
    try:
        if discount_desc or discount_amount:
            save_discounts(report["id"], discount_desc, discount_amount)
        if not confirm_report(report["id"], admin["id"]):
            return RedirectResponse(
                with_query(
                    U.cliente(worker_id),
                    fecha=report_date,
                    error="No se pudo confirmar. El cliente debe enviar el reporte primero.",
                ),
                status_code=303,
            )
    except ValueError as exc:
        return RedirectResponse(
            with_query(U.cliente(worker_id), fecha=report_date, error=str(exc)),
            status_code=303,
        )

    return RedirectResponse(
        with_query(
            U.cliente(worker_id),
            fecha=report_date,
            msg="Reporte confirmado. Ya cuenta en el total acumulado.",
        ),
        status_code=303,
    )


@app.post("/clientes/{worker_id}/reabrir")
async def admin_reopen_report(
    request: Request,
    worker_id: int,
    report_date: str = Form(...),
):
    _, auth_redirect = check_admin_session(request)
    if auth_redirect:
        return auth_redirect

    report = get_or_create_report(worker_id, report_date)
    if not reopen_report(report["id"]):
        return RedirectResponse(
            with_query(
                U.cliente(worker_id),
                fecha=report_date,
                error="No se pudo reabrir. Solo reportes enviados pendientes de confirmar.",
            ),
            status_code=303,
        )

    return RedirectResponse(
        with_query(
            U.cliente(worker_id),
            fecha=report_date,
            msg="Reporte habilitado. El cliente puede editar y volver a enviar.",
        ),
        status_code=303,
    )


@app.post("/clientes/{worker_id}/guardar-datos")
async def admin_save_entries(
    request: Request,
    worker_id: int,
    report_date: str = Form(...),
    cargue_amount: list[str] = Form(default=[]),
    retiro_amount: list[str] = Form(default=[]),
):
    _, auth_redirect = check_admin_session(request)
    if auth_redirect:
        return auth_redirect

    report = get_or_create_report(worker_id, report_date)
    try:
        save_admin_entries(report["id"], cargue_amount, retiro_amount)
    except ValueError as exc:
        return RedirectResponse(
            with_query(U.cliente(worker_id), fecha=report_date, error=str(exc)),
            status_code=303,
        )

    return RedirectResponse(
        with_query(
            U.cliente(worker_id),
            fecha=report_date,
            msg="Cargues y retiros actualizados",
        ),
        status_code=303,
    )


# Rutas antiguas → nuevas (compatibilidad)
@app.get("/login")
async def legacy_login():
    return RedirectResponse(U.ACCESO, status_code=301)


@app.get("/logout")
async def legacy_logout():
    return RedirectResponse(U.SALIR, status_code=301)


@app.get("/panel")
async def legacy_panel():
    return RedirectResponse(U.MIS_REPORTES, status_code=301)


@app.get("/admin")
async def legacy_admin():
    return RedirectResponse(U.REPORTES, status_code=301)


@app.get("/admin/clientes")
async def legacy_admin_clientes():
    return RedirectResponse(U.CLIENTES, status_code=301)


@app.get("/admin/clientes/{worker_id}")
async def legacy_admin_cliente(worker_id: int):
    return RedirectResponse(U.cliente(worker_id), status_code=301)
