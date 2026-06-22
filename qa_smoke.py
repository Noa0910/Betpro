"""Prueba rápida de rutas principales."""
from fastapi.testclient import TestClient

from app.main import app
from app.services import create_worker

client = TestClient(app)

WORKER = "_qa_worker_"
WORKER_PASS = "QaWorker2026!"
ADMIN_USER = "nosorio"
ADMIN_PASS = "Nosorio2026!"

try:
    create_worker(WORKER, WORKER_PASS, "QA Worker", 50)
except ValueError:
    pass

errors = []


def check(name, response, expected=(200, 303)):
    ok = response.status_code in expected
    if not ok:
        errors.append(f"{name}: {response.status_code}")
    return ok


# Rutas públicas
check("acceso", client.get("/acceso"))
check("static css", client.get("/static/style.css"))
check("static logo", client.get("/static/logo.png"))

# Admin
r = client.post("/acceso", data={"username": ADMIN_USER, "password": ADMIN_PASS}, follow_redirects=False)
check("admin login", r)
for path in ("/reportes", "/clientes", "/administradores"):
    check(path, client.get(path))

# Worker
client.post("/salir", follow_redirects=False)
r = client.post("/acceso", data={"username": WORKER, "password": WORKER_PASS}, follow_redirects=False)
check("worker login", r)
check("mis-reportes", client.get("/mis-reportes"))

if errors:
    print("FALLÓ:", *errors, sep="\n  ")
    raise SystemExit(1)

print("OK: todas las rutas principales responden bien")
