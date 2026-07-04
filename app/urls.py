"""Rutas públicas de BetPro (reportes y clientes)."""

ACCESO = "/acceso"
SALIR = "/salir"
MIS_REPORTES = "/mis-reportes"
REPORTES = "/reportes"
CLIENTES = "/clientes"
ADMINISTRADORES = "/administradores"
DIVISA = "/divisa"


def mis_reportes_guardar() -> str:
    return f"{MIS_REPORTES}/guardar"


def cliente(worker_id: int) -> str:
    return f"{CLIENTES}/{worker_id}"


def cliente_tarifa(worker_id: int) -> str:
    return f"{CLIENTES}/{worker_id}/tarifa"


def cliente_estado(worker_id: int) -> str:
    return f"{CLIENTES}/{worker_id}/estado"


def cliente_descuentos(worker_id: int) -> str:
    return f"{CLIENTES}/{worker_id}/descuentos"


def cliente_confirmar(worker_id: int) -> str:
    return f"{CLIENTES}/{worker_id}/confirmar-reporte"


def cliente_reabrir(worker_id: int) -> str:
    return f"{CLIENTES}/{worker_id}/reabrir"


def cliente_guardar(worker_id: int) -> str:
    return f"{CLIENTES}/{worker_id}/guardar-datos"


def cliente_cambiar_fecha(worker_id: int) -> str:
    return f"{CLIENTES}/{worker_id}/cambiar-fecha"


def admin_estado(admin_id: int) -> str:
    return f"{ADMINISTRADORES}/{admin_id}/estado"
