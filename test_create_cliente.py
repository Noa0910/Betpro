"""Prueba crear cliente en local o producción."""
import sys
import urllib.parse
import urllib.request
import http.cookiejar
from urllib.parse import urlparse, parse_qs

from fastapi.testclient import TestClient

BASE = sys.argv[1] if len(sys.argv) > 1 else "local"


def test_local():
    from app.main import app
    from app.services import create_worker

    client = TestClient(app)
    user = f"_test_{__import__('time').time_ns()}"
    try:
        create_worker(user, "Test2026!", "Test Local", 50.0)
        print("OK local create_worker direct:", user)
    except Exception as exc:
        print("FAIL local create_worker:", type(exc).__name__, exc)
        return

    r = client.post(
        "/acceso",
        data={"username": "nosorio", "password": "Nosorio2026!"},
        follow_redirects=False,
    )
    r2 = client.post(
        "/clientes",
        data={
            "name": "Via HTTP",
            "username": user + "http",
            "password": "Test2026!",
            "password_confirm": "Test2026!",
            "retiro_fee": "50",
        },
        follow_redirects=False,
    )
    print("HTTP create status:", r2.status_code, "location:", r2.headers.get("location"))


def test_production():
    base = "https://www.betpro.management"
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    login = urllib.parse.urlencode(
        {"username": "nosorio", "password": "Nosorio2026!"}
    ).encode()
    op.open(
        urllib.request.Request(f"{base}/acceso", data=login, method="POST"),
        timeout=30,
    )
    user = f"test{__import__('time').time_ns() % 100000000}"
    payload = urllib.parse.urlencode(
        {
            "name": "Cliente Prueba",
            "username": user,
            "password": "Test2026!",
            "password_confirm": "Test2026!",
            "retiro_fee": "50",
        }
    ).encode()
    r = op.open(
        urllib.request.Request(f"{base}/clientes", data=payload, method="POST"),
        timeout=30,
    )
    url = r.geturl()
    html = r.read().decode("utf-8", "replace")
    qs = parse_qs(urlparse(url).query)
    print("final url:", url)
    if "error" in qs:
        print("ERROR:", qs["error"][0])
    if "msg" in qs:
        print("MSG:", qs["msg"][0])
    if "alert-success" in html and "Cliente creado" in html:
        print("OK: cliente creado en producción")
    elif "bg-red-500" in html:
        print("FAIL: página muestra error")


if __name__ == "__main__":
    if BASE == "prod":
        test_production()
    else:
        test_local()
        print("---")
        test_production()
