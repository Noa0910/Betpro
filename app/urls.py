"""Rutas públicas de BetPro (reportes y clientes)."""

ACCESO = "/acceso"
NUEVA_CONTRASENA = "/nueva-contrasena"
SALIR = "/salir"
MIS_REPORTES = "/mis-reportes"
REPORTES = "/reportes"
CLIENTES = "/clientes"
ADMINISTRADORES = "/administradores"
CORTES = "/cortes"
DIVISA = "/divisa"
PAGO_MEXICO = "/reportes/pago-mexico"


def mis_reportes_guardar() -> str:
    return f"{MIS_REPORTES}/guardar"


def cliente(worker_id: int) -> str:
    return f"{CLIENTES}/{worker_id}"


def cliente_tarifa(worker_id: int) -> str:
    return f"{CLIENTES}/{worker_id}/tarifa"


def cliente_estado(worker_id: int) -> str:
    return f"{CLIENTES}/{worker_id}/estado"


def cliente_restablecer_contrasena(worker_id: int) -> str:
    return f"{CLIENTES}/{worker_id}/restablecer-contrasena"


def cliente_descuentos(worker_id: int) -> str:
    return f"{CLIENTES}/{worker_id}/descuentos"


def cliente_gastos(worker_id: int) -> str:
    return f"{CLIENTES}/{worker_id}/gastos"


def cliente_gasto_eliminar(worker_id: int, expense_id: int) -> str:
    return f"{CLIENTES}/{worker_id}/gastos/{expense_id}/eliminar"


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


def admin_restablecer_contrasena(admin_id: int) -> str:
    return f"{ADMINISTRADORES}/{admin_id}/restablecer-contrasena"


def corte_aceptar(corte_id: int) -> str:
    return f"{CORTES}/{corte_id}/aceptar"


def corte_detalle(corte_id: int) -> str:
    return f"{CORTES}/{corte_id}"
