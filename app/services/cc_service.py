import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal

from app.repositories import cc_repo, cheques_repo
from app.services import clientes_service, log_service, medios_pago_service, proveedores_service
from app.services.exceptions import (
    AnulacionInvalidaError,
    CargoNoEncontradoError,
    ChequeEstadoInvalidoError,
    ClienteNoEncontradoError,
    MedioPagoNoEncontradoError,
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
        "origen_venta_id": fila["origen_venta_id"],
        "origen_cheque_id": fila["origen_cheque_id"],
        "observacion": fila["observacion"],
        "anulado_fecha": fila["anulado_fecha"],
        "anulado_motivo": fila["anulado_motivo"],
    }


def _pago_a_dict(fila: sqlite3.Row) -> dict:
    return {
        "id": fila["id"],
        "entidad_tipo": "cliente" if fila["cliente_id"] is not None else "proveedor",
        "entidad_id": fila["cliente_id"] if fila["cliente_id"] is not None else fila["proveedor_id"],
        "monto": entero_a_precio(fila["monto"]),
        "fecha": fila["fecha"],
        "observacion": fila["observacion"],
        "cheque_id": fila["cheque_id"],
        "medio_pago_id": fila["medio_pago_id"],
        "medio_nombre": fila["medio_nombre"],
        "anulado_fecha": fila["anulado_fecha"],
        "anulado_motivo": fila["anulado_motivo"],
        "reemplaza_pago_id": fila["reemplaza_pago_id"],
        "nota_credito_id": fila["nota_credito_id"],
        "nota_credito_numero": fila["nota_credito_numero"],
    }


def _saldos_pendientes(cargos: list[sqlite3.Row]) -> dict[int, Decimal]:
    cargo_ids = [c["id"] for c in cargos]
    aplicado_por_cargo: dict[int, int] = {}
    for a in cc_repo.listar_aplicaciones_por_cargos(cargo_ids):
        aplicado_por_cargo[a["cargo_id"]] = aplicado_por_cargo.get(a["cargo_id"], 0) + a["monto"]
    return {
        c["id"]: Decimal("0") if c["anulado_fecha"] else entero_a_precio(c["monto"] - aplicado_por_cargo.get(c["id"], 0))
        for c in cargos
    }


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
    """Cargos vigentes menos pagos vigentes. Negativo = saldo a favor: lo que sobro de un pago
    que supero la deuda no se pierde, se descuenta del total aunque no este aplicado a ningun cargo."""
    cargos = listar_cargos(entidad_tipo, entidad_id)
    pagos = listar_pagos(entidad_tipo, entidad_id)
    total_cargos = sum((c["monto"] for c in cargos if not c["anulado_fecha"]), Decimal("0"))
    total_pagos = sum((p["monto"] for p in pagos if not p["anulado_fecha"]), Decimal("0"))
    return total_cargos - total_pagos


def _validar_medio_pago(medio_pago_id: int) -> dict:
    medio = medios_pago_service.obtener_medio_pago(medio_pago_id)
    if medio is None or not medio["activo"]:
        raise MedioPagoNoEncontradoError(f"No existe o esta inactivo el medio de pago {medio_pago_id}")
    if medio["es_cuenta_corriente"]:
        raise ValueError("Un pago de cuenta corriente no puede hacerse con el medio 'cuenta corriente'")
    return medio


def _calcular_aplicaciones(
    entidad_tipo: str,
    entidad_id: int,
    monto_entero: int,
    aplicaciones: list[dict] | None,
    pago_liberado_id: int | None = None,
) -> list[dict]:
    """aplicaciones=None: FIFO automatico a los cargos abiertos mas viejos primero. Si no, valida
    las aplicaciones a mano. pago_liberado_id: en una correccion, el pago viejo que se va a anular
    en la misma transaccion -- lo que tenia aplicado cuenta como saldo disponible de esos cargos."""
    liberado_por_cargo: dict[int, int] = {}
    if pago_liberado_id is not None:
        for a in cc_repo.listar_aplicaciones_de_pago(pago_liberado_id):
            liberado_por_cargo[a["cargo_id"]] = liberado_por_cargo.get(a["cargo_id"], 0) + a["monto"]
    saldo_por_cargo = {}
    for cargo in listar_cargos(entidad_tipo, entidad_id):
        if cargo["anulado_fecha"]:
            continue
        saldo = precio_a_entero(cargo["saldo_pendiente"]) + liberado_por_cargo.get(cargo["id"], 0)
        if saldo > 0:
            saldo_por_cargo[cargo["id"]] = saldo

    aplicaciones_a_crear = []
    if aplicaciones is None:
        restante = monto_entero
        for cargo_id, saldo_cargo in saldo_por_cargo.items():
            if restante <= 0:
                break
            a_aplicar = min(restante, saldo_cargo)
            aplicaciones_a_crear.append({"cargo_id": cargo_id, "monto": a_aplicar})
            restante -= a_aplicar
        return aplicaciones_a_crear

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
    return aplicaciones_a_crear


def registrar_pago(
    entidad_tipo: str,
    entidad_id: int,
    monto: Decimal,
    fecha: str,
    aplicaciones: list[dict] | None = None,
    observacion: str | None = None,
    cheque_id: int | None = None,
    medio_pago_id: int | None = None,
) -> dict:
    """aplicaciones=None: se aplica FIFO automatico a los cargos abiertos mas viejos primero.
    aplicaciones=[{'cargo_id': int, 'monto': Decimal}, ...]: se aplica exactamente asi (a mano)."""
    _validar_entidad_existe(entidad_tipo, entidad_id)
    medio = _validar_medio_pago(medio_pago_id) if medio_pago_id is not None else None
    if monto <= 0:
        raise MontoPagoInvalidoError("El monto del pago debe ser mayor a cero")
    monto_entero = precio_a_entero(monto)
    aplicaciones_a_crear = _calcular_aplicaciones(entidad_tipo, entidad_id, monto_entero, aplicaciones)

    cliente_id = entidad_id if entidad_tipo == "cliente" else None
    proveedor_id = entidad_id if entidad_tipo == "proveedor" else None
    pago_id = cc_repo.crear_pago_con_aplicaciones(
        cliente_id, proveedor_id, monto_entero, fecha, observacion, aplicaciones_a_crear,
        cheque_id=cheque_id, medio_pago_id=medio_pago_id,
    )
    detalle_medio = f" ({medio['nombre']})" if medio else ""
    log_service.registrar(
        entidad_tipo, entidad_id,
        f"Se registro un pago de {formatear_precio(monto)}{detalle_medio} en cuenta corriente",
    )
    return obtener_pago(pago_id)


def corregir_pago(
    pago_id: int,
    monto: Decimal,
    fecha: str,
    medio_pago_id: int,
    observacion: str | None = None,
) -> dict:
    """Para el usuario es 'editar el pago'; por dentro nunca se pisa nada: el pago viejo queda
    anulado (motivo automatico con lo que cambio) y se crea uno nuevo, en una sola transaccion.
    El nuevo se aplica FIFO a cuenta. Los pagos con cheque no se corrigen (el monto de un cheque
    no se cambia): se anulan y se cargan de nuevo."""
    viejo = obtener_pago(pago_id)
    if viejo is None:
        raise AnulacionInvalidaError(f"No existe el pago {pago_id}")
    if viejo["anulado_fecha"]:
        raise AnulacionInvalidaError("Ese pago esta anulado: no se puede corregir")
    if viejo["cheque_id"] is not None:
        raise AnulacionInvalidaError("Un pago con cheque no se corrige: anulalo y cargalo de nuevo")
    if viejo["nota_credito_id"] is not None:
        raise AnulacionInvalidaError(
            f"Este credito es parte de la nota de credito {viejo['nota_credito_numero']}: no se corrige desde aca"
        )
    medio = _validar_medio_pago(medio_pago_id)
    if monto <= 0:
        raise MontoPagoInvalidoError("El monto del pago debe ser mayor a cero")
    if not (fecha or "").strip():
        raise ValueError("La fecha es obligatoria")

    cambios = []
    if monto != viejo["monto"]:
        cambios.append(f"monto {formatear_precio(viejo['monto'])} -> {formatear_precio(monto)}")
    if fecha[:10] != viejo["fecha"][:10]:
        cambios.append(f"fecha {viejo['fecha'][:10]} -> {fecha[:10]}")
    if medio_pago_id != viejo["medio_pago_id"]:
        cambios.append(f"medio {viejo['medio_nombre'] or '-'} -> {medio['nombre']}")
    if (observacion or None) != (viejo["observacion"] or None):
        cambios.append("observacion")
    if not cambios:
        raise ValueError("No cambiaste ningun dato del pago")
    motivo = "Corregido: " + ", ".join(cambios)

    entidad_tipo, entidad_id = viejo["entidad_tipo"], viejo["entidad_id"]
    monto_entero = precio_a_entero(monto)
    aplicaciones = _calcular_aplicaciones(entidad_tipo, entidad_id, monto_entero, None, pago_liberado_id=pago_id)
    nuevo_id = cc_repo.reemplazar_pago(
        pago_id, datetime.now().isoformat(), motivo,
        cliente_id=entidad_id if entidad_tipo == "cliente" else None,
        proveedor_id=entidad_id if entidad_tipo == "proveedor" else None,
        monto=monto_entero, fecha=fecha, observacion=observacion, aplicaciones=aplicaciones,
        medio_pago_id=medio_pago_id,
    )
    log_service.registrar(entidad_tipo, entidad_id, f"Se corrigio un pago en cuenta corriente ({motivo})")
    return obtener_pago(nuevo_id)


def anular_pago(pago_id: int, motivo: str, fecha: str | None = None) -> dict:
    """Nunca se borra ni se edita un pago: queda marcado como anulado y deja de contar, asi que
    los cargos que cubria vuelven a quedar pendientes. Si se pago con un cheque, el cheque se
    mueve en la misma transaccion: vuelve a cartera si era uno recibido que habiamos entregado a
    un proveedor, o pasa a baja si era propio o si lo habiamos recibido con este mismo cobro."""
    if not (motivo or "").strip():
        raise ValueError("Anular un pago requiere indicar el motivo")
    motivo = motivo.strip()
    pago = obtener_pago(pago_id)
    if pago is None:
        raise AnulacionInvalidaError(f"No existe el pago {pago_id}")
    if pago["anulado_fecha"]:
        raise AnulacionInvalidaError("Ese pago ya estaba anulado")
    if pago["nota_credito_id"] is not None:
        raise AnulacionInvalidaError(
            f"Este credito es parte de la nota de credito {pago['nota_credito_numero']}: no se anula desde aca"
        )

    accion_cheque = None
    cheque_observacion = None
    if pago["cheque_id"] is not None:
        cheque = cheques_repo.obtener_por_id(pago["cheque_id"])
        if cheque["estado"] == "rechazado":
            raise ChequeEstadoInvalidoError(
                "El cheque de este pago ya fue rechazado (la deuda ya se reabrio con un cargo nuevo): "
                "no se puede anular el pago"
            )
        if pago["entidad_tipo"] == "proveedor":
            if cheque["estado"] != "entregado_proveedor":
                raise ChequeEstadoInvalidoError(
                    f"El cheque de este pago no esta entregado al proveedor (estado actual: {cheque['estado']})"
                )
            accion_cheque = "volver_a_cartera" if cheque["origen_tipo"] == "recibido_cliente" else "baja"
        else:
            if cheque["estado"] == "entregado_proveedor":
                raise ChequeEstadoInvalidoError(
                    "El cheque de este cobro ya se le entrego a un proveedor: primero anula ese pago "
                    "en la cuenta del proveedor, y despues este"
                )
            if cheque["estado"] != "en_cartera":
                raise ChequeEstadoInvalidoError(
                    f"El cheque de este cobro ya no esta en cartera (estado actual: {cheque['estado']})"
                )
            accion_cheque = "baja"
        if accion_cheque == "baja":
            cheque_observacion = f"Anulado junto con el pago de cuenta corriente: {motivo}"

    cc_repo.anular_pago(
        pago_id, fecha or datetime.now().isoformat(), motivo,
        accion_cheque=accion_cheque, cheque_observacion=cheque_observacion,
    )
    log_service.registrar(
        pago["entidad_tipo"], pago["entidad_id"],
        f"Se anulo un pago de {formatear_precio(pago['monto'])} en cuenta corriente: {motivo}",
    )
    if accion_cheque == "volver_a_cartera":
        log_service.registrar("cheque", pago["cheque_id"], f"El cheque volvio a cartera por anulacion del pago: {motivo}")
    elif accion_cheque == "baja":
        log_service.registrar("cheque", pago["cheque_id"], cheque_observacion)
    return obtener_pago(pago_id)


def anular_cargo(cargo_id: int, motivo: str, fecha: str | None = None) -> dict:
    """Solo cargos manuales (los de compras/ventas/cheques se corrigen desde su origen), y solo si
    no tienen pagos vigentes aplicados -- si los tiene, primero se anulan esos pagos."""
    if not (motivo or "").strip():
        raise ValueError("Anular un cargo requiere indicar el motivo")
    motivo = motivo.strip()
    cargo = obtener_cargo(cargo_id)
    if cargo is None:
        raise CargoNoEncontradoError(f"No existe el cargo {cargo_id}")
    if cargo["anulado_fecha"]:
        raise AnulacionInvalidaError("Ese cargo ya estaba anulado")
    if cargo["origen"] != "manual":
        raise AnulacionInvalidaError(
            "Solo se pueden anular cargos manuales: este se genero desde otra operacion y se corrige desde ahi"
        )
    if cc_repo.listar_aplicaciones_de_cargo(cargo_id):
        raise AnulacionInvalidaError("Este cargo tiene pagos aplicados: primero anula esos pagos")

    cc_repo.anular_cargo(cargo_id, fecha or datetime.now().isoformat(), motivo)
    log_service.registrar(
        cargo["entidad_tipo"], cargo["entidad_id"],
        f"Se anulo un cargo manual de {formatear_precio(cargo['monto'])} en cuenta corriente: {motivo}",
    )
    return obtener_cargo(cargo_id)


def obtener_pago(pago_id: int) -> dict | None:
    fila = cc_repo.obtener_pago_por_id(pago_id)
    return _pago_a_dict(fila) if fila is not None else None


def listar_pagos(entidad_tipo: str, entidad_id: int) -> list[dict]:
    _validar_entidad_tipo(entidad_tipo)
    filas = cc_repo.listar_pagos(
        cliente_id=entidad_id if entidad_tipo == "cliente" else None,
        proveedor_id=entidad_id if entidad_tipo == "proveedor" else None,
    )
    pagos = [_pago_a_dict(f) for f in filas]
    pagos_por_id = {p["id"]: p for p in pagos}
    for pago in pagos:
        # 'corregido_de': el pago anulado al que este reemplazo, para mostrar "antes: ..." en la
        # fila vigente sin necesidad de mostrar la fila anulada.
        reemplazado = pagos_por_id.get(pago["reemplaza_pago_id"])
        pago["corregido_de"] = None
        if reemplazado is not None:
            pago["corregido_de"] = {
                "monto": reemplazado["monto"], "fecha": reemplazado["fecha"],
                "medio_nombre": reemplazado["medio_nombre"], "observacion": reemplazado["observacion"],
                "fecha_correccion": reemplazado["anulado_fecha"],
            }
        pago["cheque"] = None
        if pago["cheque_id"] is not None:
            cheque = cheques_repo.obtener_por_id(pago["cheque_id"])
            pago["cheque"] = {
                "numero": cheque["numero"], "banco": cheque["banco"], "librador": cheque["librador"],
                "cuit_librador": cheque["cuit_librador"], "fecha_pago": cheque["fecha_pago"],
                "monto": entero_a_precio(cheque["monto"]),
                "origen_tipo": cheque["origen_tipo"], "estado": cheque["estado"],
            }
    return pagos


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
