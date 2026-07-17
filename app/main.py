import json
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request as StarletteRequest

from jinja2 import pass_context

from app.currencies import currency_choices, format_money as format_money_value
from app import urls as U
from app.auth import authenticate_user, check_admin_session, check_user_session, get_user_by_username, login_redirect, verify_password
from app.config import CANONICAL_HOST, DB_EPHEMERAL, IS_VERCEL, USE_TURSO, get_session_secret, APP_VERSION
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
    change_report_date,
    parse_report_date,
    today_iso,
    update_worker_fee,
    update_worker_status,
    update_admin_status,
)
from app.settings import get_system_currency, set_system_currency
from app.cortes import (
    accept_corte,
    build_corte_preview,
    ensure_pending_corte,
    get_corte_detail,
    get_last_accepted_corte,
    get_pending_corte,
    list_cortes,
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
async def redirect_canonical_host(request: Request, call_next):
    if CANONICAL_HOST:
        host = request.headers.get("host", "").split(":")[0].lower()
        if host != CANONICAL_HOST and (
            host.endswith(".vercel.app") or host == "betpro.management"
        ):
            target = request.url.replace(scheme="https", netloc=CANONICAL_HOST)
            code = 307 if request.method == "POST" else 301
            return RedirectResponse(str(target), status_code=code)
    return await call_next(request)


@app.on_event("startup")
def startup() -> None:
    from app.bootstrap import seed_if_empty
    from app.database import check_db_connection

    if IS_VERCEL and not USE_TURSO:
        print(
            "ADVERTENCIA: Turso no configurado en Vercel. "
            "Los datos se pierden en cada reinicio. "
            "Agrega TURSO_DATABASE_URL y TURSO_AUTH_TOKEN en Vercel."
        )

    try:
        seed_if_empty()
        get_system_currency()
        status = check_db_connection()
        if status.get("ok"):
            print(
                f"BD OK ({status.get('engine')}): "
                f"{status.get('users')} usuarios, {status.get('reports')} reportes"
            )
        else:
            print(f"BD ERROR: {status.get('error')}")
    except Exception as exc:
        print(f"BD STARTUP ERROR: {type(exc).__name__}: {exc}")


@app.get("/api/salud")
async def health_check():
    from app.database import check_db_connection
    from app.settings import get_system_currency

    db = check_db_connection()
    payload = {
        "ok": db.get("ok", False),
        "version": APP_VERSION,
        "currency": get_system_currency(),
        "database": db,
    }
    return JSONResponse(payload, status_code=200 if db.get("ok") else 503)


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


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: StarletteRequest, exc: StarletteHTTPException):
    if exc.status_code in (301, 302, 303, 307, 308):
        location = exc.headers.get("location")
        if location:
            return RedirectResponse(location, status_code=exc.status_code)

    accept = request.headers.get("accept", "")
    if "text/html" in accept and exc.status_code == 404:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "Página no encontrada."},
            status_code=404,
        )
    return HTMLResponse(str(exc.detail), status_code=exc.status_code)


@app.exception_handler(Exception)
async def unhandled_error(request: StarletteRequest, exc: Exception):
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


@pass_context
def fmt_money(context, value, currency=None):
    if currency is None:
        currency = context.get("currency")
    if currency is None:
        currency = get_system_currency()
    return format_money_value(value, currency)


templates.env.filters["money"] = fmt_money
templates.env.filters["tojson"] = lambda v: json.dumps(v)
templates.env.globals["url"] = U
templates.env.globals["app_version"] = APP_VERSION
templates.env.globals["db_ephemeral"] = DB_EPHEMERAL
templates.env.globals["currency_choices"] = currency_choices
templates.env.globals["system_currency"] = get_system_currency


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


def cumulative_subtitle() -> str:
    last = get_last_accepted_corte()
    if last:
        pe = last["period_end"]
        return f"Periodo actual — desde {pe[8:10]}/{pe[5:7]}/{pe[:4]}"
    return "Suma de días confirmados del periodo actual"


def build_worker_panel_context(
    user: dict,
    report_date: str,
    *,
    message: str | None = None,
    error: str | None = None,
) -> dict:
    report_date = parse_report_date(report_date)
    report = get_or_create_report(user["id"], report_date)
    details = get_report_details(report["id"])
    if not details:
        raise RuntimeError("No se pudo cargar el reporte")

    ctx = report_context(details)
    return {
        "request": None,
        "user": user,
        "report": details,
        "report_date": report_date,
        "currency": get_system_currency(),
        "history": get_user_reports(user["id"], limit=15),
        "cumulative": get_cumulative_total(user["id"]),
        "cumulative_subtitle": cumulative_subtitle(),
        "message": message,
        "error": error,
        **ctx,
    }


def render_worker_panel(
    request: Request,
    user: dict,
    report_date: str,
    *,
    message: str | None = None,
    error: str | None = None,
    status_code: int = 200,
):
    try:
        context = build_worker_panel_context(
            user,
            report_date,
            message=message,
            error=error,
        )
    except RuntimeError as exc:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": str(exc)},
            status_code=500,
        )

    context["request"] = request
    return templates.TemplateResponse(
        "worker_panel.html",
        context,
        status_code=status_code,
    )


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


def login_error_message(username: str, password: str) -> str:
    user = get_user_by_username(username)
    if not user:
        if DB_EPHEMERAL:
            return (
                "Usuario no encontrado. En Vercel sin Turso la base se reinicia y "
                "los clientes creados se pierden. Configura Turso y vuelve a crear el cliente."
            )
        return "Usuario no encontrado. Verifica el nombre o pide al admin que te cree la cuenta."
    if not int(user.get("active") or 0):
        return "Tu cuenta está desactivada. Contacta al administrador."
    if not verify_password(password, user["password_hash"]):
        return "Contraseña incorrecta."
    return "No se pudo iniciar sesión."


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
            {"request": request, "error": login_error_message(username, password)},
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

    report_date = parse_report_date(fecha)
    return render_worker_panel(
        request,
        user,
        report_date,
        message=request.query_params.get("msg"),
        error=request.query_params.get("error"),
    )


@app.post(U.mis_reportes_guardar())
async def worker_save_report(
    request: Request,
    report_date: str = Form(...),
    cargue_amount: list[str] = Form(default=[]),
    retiro_amount: list[str] = Form(default=[]),
    notes: str = Form(""),
    action: str = Form("draft"),
):
    user, auth_redirect = check_user_session(request)
    if auth_redirect:
        return auth_redirect

    submit = action == "submit"
    report = get_or_create_report(user["id"], report_date)
    try:
        save_client_report(
            report["id"],
            cargue_amount,
            retiro_amount,
            notes,
            submit=submit,
        )
    except ValueError as exc:
        return render_worker_panel(
            request,
            user,
            report_date,
            error=str(exc),
            status_code=400,
        )

    if submit:
        msg = (
            "Reporte guardado y confirmado. Ya suma en tu total acumulado."
            if user["role"] == "admin"
            else "Reporte enviado al admin para confirmación"
        )
        return RedirectResponse(
            with_query(U.MIS_REPORTES, fecha=report_date, msg=msg),
            status_code=303,
        )

    return render_worker_panel(
        request,
        user,
        report_date,
        message="Borrador guardado. Puedes salir y continuar más tarde.",
    )


@app.get(U.REPORTES, response_class=HTMLResponse)
async def admin_dashboard(request: Request, period: str = "all"):
    user, auth_redirect = check_admin_session(request)
    if auth_redirect:
        return auth_redirect

    if period not in ("all", "today", "week", "month"):
        period = "all"

    try:
        ensure_pending_corte()
        analytics = get_admin_analytics(period)
        pending = list_pending_reports()
        pending_corte = get_pending_corte()
    except Exception:
        return RedirectResponse(
            with_query(U.REPORTES, error="No se pudo cargar el dashboard. Intenta de nuevo."),
            status_code=303,
        )

    return templates.TemplateResponse(
        "admin_analytics.html",
        {
            "request": request,
            "user": user,
            "analytics": analytics,
            "pending_reports": pending,
            "pending_corte": pending_corte,
            "period": period,
            "message": request.query_params.get("msg"),
            "error": request.query_params.get("error"),
        },
    )


@app.get(U.CORTES, response_class=HTMLResponse)
async def admin_cortes_page(request: Request):
    user, auth_redirect = check_admin_session(request)
    if auth_redirect:
        return auth_redirect

    ensure_pending_corte()
    pending_corte = get_pending_corte()
    preview = build_corte_preview(pending_corte) if pending_corte else None

    return templates.TemplateResponse(
        "admin_cortes.html",
        {
            "request": request,
            "user": user,
            "pending_corte": pending_corte,
            "preview": preview or {"clients": [], "total_net": 0, "total_clients": 0, "submitted_pending": 0},
            "last_accepted": get_last_accepted_corte(),
            "cortes_history": list_cortes(),
            "message": request.query_params.get("msg"),
            "error": request.query_params.get("error"),
        },
    )


@app.get("/cortes/{corte_id}", response_class=HTMLResponse)
async def admin_corte_detail(request: Request, corte_id: int):
    user, auth_redirect = check_admin_session(request)
    if auth_redirect:
        return auth_redirect

    detail = get_corte_detail(corte_id)
    if not detail:
        return RedirectResponse(with_query(U.CORTES, error="Corte no encontrado"), status_code=303)

    return templates.TemplateResponse(
        "admin_corte_detail.html",
        {
            "request": request,
            "user": user,
            "detail": detail,
            "corte": detail["corte"],
            "snapshots": detail["snapshots"],
            "message": request.query_params.get("msg"),
            "error": request.query_params.get("error"),
        },
    )


@app.post("/cortes/{corte_id}/aceptar")
async def admin_accept_corte(request: Request, corte_id: int):
    user, auth_redirect = check_admin_session(request)
    if auth_redirect:
        return auth_redirect
    try:
        accept_corte(corte_id, user["id"])
    except ValueError as exc:
        return RedirectResponse(with_query(U.CORTES, error=str(exc)), status_code=303)
    return RedirectResponse(
        with_query(U.CORTES, msg="Corte aceptado. Todos los acumulados reiniciaron en 0."),
        status_code=303,
    )


@app.get(U.CLIENTES, response_class=HTMLResponse)
async def admin_clients(request: Request):
    user, auth_redirect = check_admin_session(request)
    if auth_redirect:
        return auth_redirect

    try:
        workers = list_workers()
        pending = list_pending_reports()
    except Exception:
        return RedirectResponse(
            with_query(U.CLIENTES, error="No se pudo cargar clientes. Intenta de nuevo."),
            status_code=303,
        )

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
    password_confirm: str = Form(""),
    name: str = Form(...),
    retiro_fee: str = Form("50"),
):
    _, auth_redirect = check_admin_session(request)
    if auth_redirect:
        return auth_redirect
    username_clean = username.strip().lower()
    try:
        if password != password_confirm:
            raise ValueError("Las contraseñas no coinciden")
        create_worker(username_clean, password, name, parse_amount(retiro_fee))
    except ValueError as exc:
        return RedirectResponse(with_query(U.CLIENTES, error=str(exc)), status_code=303)

    msg = f"Cliente creado: {username_clean}"
    if DB_EPHEMERAL:
        msg += " — URGENTE: configure Turso en Vercel o se perderá al reiniciar."
    return RedirectResponse(with_query(U.CLIENTES, msg=msg), status_code=303)


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
    password_confirm: str = Form(""),
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


@app.post(U.DIVISA)
async def admin_set_system_currency(
    request: Request,
    currency: str = Form(...),
    redirect_to: str = Form(""),
):
    _, auth_redirect = check_admin_session(request)
    if auth_redirect:
        return auth_redirect
    try:
        set_system_currency(currency)
    except ValueError as exc:
        target = redirect_to or U.REPORTES
        return RedirectResponse(with_query(target, error=str(exc)), status_code=303)
    target = redirect_to or str(request.headers.get("referer") or U.REPORTES)
    if not target.startswith("/"):
        target = U.REPORTES
    return RedirectResponse(with_query(target, msg="Divisa actualizada para todo el sistema"), status_code=303)


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
    if not worker or worker["role"] not in ("worker", "admin"):
        return RedirectResponse(U.REPORTES, status_code=303)

    report_date = parse_report_date(fecha)
    report = get_or_create_report(worker_id, report_date)
    details = get_report_details(report["id"])
    if not details:
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "message": "No se pudo cargar el reporte del cliente.",
            },
            status_code=500,
        )
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
            "currency": get_system_currency(),
            "history": history,
            "cumulative": cumulative,
            "cumulative_subtitle": cumulative_subtitle(),
            "can_confirm": details["status"] == REPORT_SUBMITTED and worker_id != user["id"],
            "is_confirmed": details["status"] == REPORT_CONFIRMED,
            "can_reopen": details["status"] == REPORT_SUBMITTED and worker_id != user["id"],
            "admin_can_edit": details["admin_can_edit_entries"] and worker_id != user["id"],
            "can_change_date": details["status"] != REPORT_CONFIRMED
            and (
                details["status"] == REPORT_SUBMITTED
                or details["cargues"]
                or details["retiros"]
            ),
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
    details = get_report_details(report["id"])
    if not details or details["status"] != REPORT_SUBMITTED:
        return RedirectResponse(
            with_query(
                U.cliente(worker_id),
                fecha=report_date,
                error="No se pudo confirmar. El cliente debe enviar el reporte primero.",
            ),
            status_code=303,
        )

    try:
        if discount_desc or discount_amount:
            save_discounts(report["id"], discount_desc, discount_amount)
        if not confirm_report(report["id"], admin["id"]):
            return RedirectResponse(
                with_query(
                    U.cliente(worker_id),
                    fecha=report_date,
                    error="No se pudo confirmar el reporte.",
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


@app.post("/clientes/{worker_id}/cambiar-fecha")
async def admin_change_report_date(
    request: Request,
    worker_id: int,
    report_date: str = Form(...),
    new_report_date: str = Form(...),
):
    _, auth_redirect = check_admin_session(request)
    if auth_redirect:
        return auth_redirect

    report = get_or_create_report(worker_id, report_date)
    try:
        new_date = change_report_date(report["id"], new_report_date)
    except ValueError as exc:
        return RedirectResponse(
            with_query(U.cliente(worker_id), fecha=report_date, error=str(exc)),
            status_code=303,
        )

    return RedirectResponse(
        with_query(
            U.cliente(worker_id),
            fecha=new_date,
            msg=f"Reporte movido al {new_date}",
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
