import sqlite3

from app.repositories import medios_pago_repo
from app.services import log_service
from app.services.exceptions import MedioPagoDuplicadoError, MedioPagoNoEncontradoError

_CAMPOS_LOG = ["nombre", "es_cuenta_corriente", "activo"]


def _a_dict(fila: sqlite3.Row) -> dict:
    return {
        "id": fila["id"],
        "nombre": fila["nombre"],
        "es_cuenta_corriente": bool(fila["es_cuenta_corriente"]),
        "activo": bool(fila["activo"]),
    }


def crear_medio_pago(nombre: str, es_cuenta_corriente: bool = False) -> dict:
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre del medio de pago no puede estar vacio")

    try:
        medio_pago_id = medios_pago_repo.crear(nombre, es_cuenta_corriente)
    except sqlite3.IntegrityError as exc:
        raise MedioPagoDuplicadoError(f"Ya existe un medio de pago llamado '{nombre}'") from exc

    log_service.registrar("medio_pago", medio_pago_id, f"Se creo el medio de pago '{nombre}'")
    return obtener_medio_pago(medio_pago_id)


def actualizar_medio_pago(medio_pago_id: int, nombre: str, es_cuenta_corriente: bool, activo: bool) -> dict:
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre del medio de pago no puede estar vacio")

    antes = obtener_medio_pago(medio_pago_id)
    if antes is None:
        raise MedioPagoNoEncontradoError(f"No existe el medio de pago {medio_pago_id}")

    try:
        medios_pago_repo.actualizar(medio_pago_id, nombre, es_cuenta_corriente, 1 if activo else 0)
    except sqlite3.IntegrityError as exc:
        raise MedioPagoDuplicadoError(f"Ya existe un medio de pago llamado '{nombre}'") from exc

    despues = obtener_medio_pago(medio_pago_id)
    log_service.registrar_cambios("medio_pago", medio_pago_id, antes, despues, _CAMPOS_LOG)
    return despues


def obtener_medio_pago(medio_pago_id: int) -> dict | None:
    fila = medios_pago_repo.obtener_por_id(medio_pago_id)
    return _a_dict(fila) if fila is not None else None


def listar_medios_pago(solo_activos: bool = False) -> list[dict]:
    return [_a_dict(fila) for fila in medios_pago_repo.listar(solo_activos)]
