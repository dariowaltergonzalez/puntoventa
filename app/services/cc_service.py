import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal

from app.repositories import cc_repo
from app.services import clientes_service, log_service, proveedores_service
from app.services.exceptions import (
    CargoNoEncontradoError,
    ClienteNoEncontradoError,
    MontoPagoInvalidoError,
    ProveedorNoEncontradoError,
)
from app.shared.money import entero_a_precio, formatear_precio, precio_a_entero

ENTIDADES = ("cliente", "proveedor")


def _validar_entidad_tipo(entidad_tipo: str) -> None:
    if entidad_tipo not in ENTIDADES:
        raise ValueError(f"entidad_tipo debe ser uno de {ENTIDADES}")


def _validar_entidad_existe(entidad_tipo: str, entidad_id: int) -> dict:
    _validar_entidad_tipo(entidad_tipo)
    if entidad_tipo == "cliente":
        entidad = clientes_service.obtener_cliente(entidad_id)
        if entidad is None:
            raise ClienteNoEncontradoError(f"No existe el cliente {entidad_id}")
    else:
        entidad = proveedores_service.obtener_proveedor(entidad_id)
        if entidad is None:
            raise ProveedorNoEncontradoError(f"No existe el proveedor {entidad_id}")
    return entidad


def _cargo_a_dict(fila: sqlite3.Row, saldo_pendiente: Decimal) -> dict:
    return {
        "id": fila["id"],
        "entidad_tipo": "cliente" if fila["cliente_id"] is not None else "proveedor",
        "entidad_id": fila["cliente_id"] if fila["cliente_id"] is not None else fila["proveedor_id"],
        "monto": entero_a_precio(fila["monto"]),
        "saldo_pendiente": saldo_pendiente,
        "fecha": fila["fecha"],
        "origen": fila["origen"],
        "origen_recepcion_id": fila["origen_recepcion_id"],
        "observacion": fila["observacion"],
    }


def _pago_a_dict(fila: sqlite3.Row) -> dict:
    return {
        "id": fila["id"],
        "entidad_tipo": "cliente" if fila["cliente_id"] is not None else "proveedor",
        "entidad_id": fila["cliente_id"] if fila["cliente_id"] is not None else fila["proveedor_id"],
        "monto": entero_a_precio(fila["monto"]),
        "fecha": fila["fecha"],
        "observacion": fila["observacion"],
    }


def _saldos_pendientes(cargos: list[sqlite3.Row]) -> dict[int, Decimal]:
    cargo_ids = [c["id"] for c in cargos]
    aplicado_por_cargo: dict[int, int] = {}
    for a in cc_repo.listar_aplicaciones_por_cargos(cargo_ids):
        aplicado_por_cargo[a["cargo_id"]] = aplicado_por_cargo.get(a["cargo_id"], 0) + a["monto"]
    return {c["id"]: entero_a_precio(c["monto"] - aplicado_por_cargo.get(c["id"], 0)) for c in cargos}


def registrar_cargo_manual(
    entidad_tipo: str, entidad_id: int, monto: Decimal, fecha: str, observacion: str | None = None,
) -> dict:
    _validar_entidad_existe(entidad_tipo, entidad_id)
    if monto <= 0:
        raise ValueError("El monto del cargo debe ser mayor a cero")
    cliente_id = entidad_id if entidad_tipo == "cliente" else None
    proveedor_id = entidad_id if entidad_tipo == "proveedor" else None
    cargo_id = cc_repo.crear_cargo(
        cliente_id, proveedor_id, precio_a_entero(monto), fecha, "manual", None, observacion,
    )
    log_service.registrar(
        entidad_tipo, entidad_id, f"Se registro un cargo manual de {formatear_precio(monto)} en cuenta corriente",
    )
    return obtener_cargo(cargo_id)


def obtener_cargo(cargo_id: int) -> dict | None:
    fila = cc_repo.obtener_cargo_por_id(cargo_id)
    if fila is None:
        return None
    saldos = _saldos_pendientes([fila])
    return _cargo_a_dict(fila, saldos[fila["id"]])


def listar_cargos(entidad_tipo: str, entidad_id: int, solo_con_saldo: bool = False) -> list[dict]:
    """Ordenados fecha ASC (orden FIFO)."""
    _validar_entidad_tipo(entidad_tipo)
    filas = cc_repo.listar_cargos(
        cliente_id=entidad_id if entidad_tipo == "cliente" else None,
        proveedor_id=entidad_id if entidad_tipo == "proveedor" else None,
    )
    saldos = _saldos_pendientes(filas)
    resultado = [_cargo_a_dict(f, saldos[f["id"]]) for f in filas]
    if solo_con_saldo:
        resultado = [c for c in resultado if c["saldo_pendiente"] > 0]
    return resultado


def calcular_saldo_total(entidad_tipo: str, entidad_id: int) -> Decimal:
    cargos = listar_cargos(entidad_tipo, entidad_id)
    return sum((c["saldo_pendiente"] for c in cargos), Decimal("0"))


def registrar_pago(
    entidad_tipo: str,
    entidad_id: int,
    monto: Decimal,
    fecha: str,
    aplicaciones: list[dict] | None = None,
    observacion: str | None = None,
) -> dict:
    """aplicaciones=None: se aplica FIFO automatico a los cargos abiertos mas viejos primero.
    aplicaciones=[{'cargo_id': int, 'monto': Decimal}, ...]: se aplica exactamente asi (a mano)."""
    _validar_entidad_existe(entidad_tipo, entidad_id)
    if monto <= 0:
        raise MontoPagoInvalidoError("El monto del pago debe ser mayor a cero")
    monto_entero = precio_a_entero(monto)

    cargos_abiertos = listar_cargos(entidad_tipo, entidad_id, solo_con_saldo=True)

    if aplicaciones is None:
        aplicaciones_a_crear = []
        restante = monto_entero
        for cargo in cargos_abiertos:
            if restante <= 0:
                break
            saldo_cargo = precio_a_entero(cargo["saldo_pendiente"])
            a_aplicar = min(restante, saldo_cargo)
            aplicaciones_a_crear.append({"cargo_id": cargo["id"], "monto": a_aplicar})
            restante -= a_aplicar
    else:
        saldo_por_cargo = {c["id"]: precio_a_entero(c["saldo_pendiente"]) for c in cargos_abiertos}
        aplicaciones_a_crear = []
        suma = 0
        for item in aplicaciones:
            cargo_id = item["cargo_id"]
            monto_aplicado = precio_a_entero(item["monto"])
            if cargo_id not in saldo_por_cargo:
                raise CargoNoEncontradoError(
                    f"El cargo {cargo_id} no existe, no pertenece a esta cuenta, o ya esta saldado",
                )
            if monto_aplicado <= 0:
                raise ValueError("El monto aplicado a un cargo debe ser mayor a cero")
            if monto_aplicado > saldo_por_cargo[cargo_id]:
                raise ValueError(f"El monto aplicado al cargo {cargo_id} supera su saldo pendiente")
            aplicaciones_a_crear.append({"cargo_id": cargo_id, "monto": monto_aplicado})
            suma += monto_aplicado
        if suma > monto_entero:
            raise MontoPagoInvalidoError("La suma de lo aplicado a los cargos no puede superar el monto del pago")

    cliente_id = entidad_id if entidad_tipo == "cliente" else None
    proveedor_id = entidad_id if entidad_tipo == "proveedor" else None
    pago_id = cc_repo.crear_pago_con_aplicaciones(
        cliente_id, proveedor_id, monto_entero, fecha, observacion, aplicaciones_a_crear,
    )
    log_service.registrar(
        entidad_tipo, entidad_id, f"Se registro un pago de {formatear_precio(monto)} en cuenta corriente",
    )
    return obtener_pago(pago_id)


def obtener_pago(pago_id: int) -> dict | None:
    fila = cc_repo.obtener_pago_por_id(pago_id)
    return _pago_a_dict(fila) if fila is not None else None


def listar_pagos(entidad_tipo: str, entidad_id: int) -> list[dict]:
    _validar_entidad_tipo(entidad_tipo)
    filas = cc_repo.listar_pagos(
        cliente_id=entidad_id if entidad_tipo == "cliente" else None,
        proveedor_id=entidad_id if entidad_tipo == "proveedor" else None,
    )
    return [_pago_a_dict(f) for f in filas]


def calcular_interes_mora(cliente_id: int, cargo: dict, fecha_referencia: datetime | None = None) -> Decimal:
    """Interes acumulado hasta fecha_referencia (default: ahora) sobre el saldo pendiente de un
    cargo de cliente, segun su tasa diaria y su plazo de pago (define el vencimiento). Solo
    aplica del lado clientes -- del lado proveedores siempre es 0."""
    if cargo["entidad_tipo"] != "cliente":
        return Decimal("0")
    cliente = clientes_service.obtener_cliente(cliente_id)
    if cliente is None or cliente["tasa_interes_mora_diaria"] is None or cliente["plazo_pago_dias"] is None:
        return Decimal("0")
    if cargo["saldo_pendiente"] <= 0:
        return Decimal("0")

    fecha_cargo = datetime.fromisoformat(cargo["fecha"])
    fecha_vencimiento = fecha_cargo + timedelta(days=cliente["plazo_pago_dias"])
    fecha_ref = fecha_referencia or datetime.now()
    dias_atraso = (fecha_ref - fecha_vencimiento).days
    if dias_atraso <= 0:
        return Decimal("0")

    tasa_diaria = cliente["tasa_interes_mora_diaria"] / Decimal("100")
    return (cargo["saldo_pendiente"] * tasa_diaria * dias_atraso).quantize(Decimal("1.00"))


def evaluar_limite_credito(cliente_id: int) -> dict | None:
    """None si el cliente no tiene limite cargado. Si tiene, devuelve saldo actual, limite,
    si lo supera, y que hacer en ese caso (avisar/bloquear), para que Ventas (Fase 4) lo use."""
    cliente = clientes_service.obtener_cliente(cliente_id)
    if cliente is None or cliente["limite_credito"] is None:
        return None
    saldo = calcular_saldo_total("cliente", cliente_id)
    return {
        "saldo": saldo,
        "limite": cliente["limite_credito"],
        "supera": saldo > cliente["limite_credito"],
        "avisar": cliente["avisar_limite_credito"],
        "bloquear": cliente["bloquear_limite_credito"],
    }
