import sqlite3
from datetime import datetime
from decimal import Decimal

from app.repositories import cheques_repo
from app.services import cc_service, clientes_service, log_service, medios_pago_service, proveedores_service
from app.services.exceptions import (
    ChequeEstadoInvalidoError,
    ChequeNoEncontradoError,
    ClienteNoEncontradoError,
    ProveedorNoEncontradoError,
)
from app.shared.money import entero_a_precio, formatear_precio, precio_a_entero


def _cheque_a_dict(fila: sqlite3.Row) -> dict:
    return {
        "id": fila["id"],
        "numero": fila["numero"],
        "banco": fila["banco"],
        "librador": fila["librador"],
        "cuit_librador": fila["cuit_librador"],
        "monto": entero_a_precio(fila["monto"]),
        "fecha_pago": fila["fecha_pago"],
        "fecha_recepcion": fila["fecha_recepcion"],
        "origen_tipo": fila["origen_tipo"],
        "cliente_id": fila["cliente_id"],
        "proveedor_id": fila["proveedor_id"],
        "estado": fila["estado"],
        "observacion": fila["observacion"],
        "cargo_generado_id": fila["cargo_generado_id"],
    }


def obtener_cheque(cheque_id: int) -> dict | None:
    fila = cheques_repo.obtener_por_id(cheque_id)
    return _cheque_a_dict(fila) if fila is not None else None


def listar_cheques(
    estado: str | None = None,
    cliente_id: int | None = None,
    proveedor_id: int | None = None,
    origen_tipo: str | None = None,
) -> list[dict]:
    return [
        _cheque_a_dict(f)
        for f in cheques_repo.listar(estado=estado, cliente_id=cliente_id, proveedor_id=proveedor_id, origen_tipo=origen_tipo)
    ]


def _medio_cheque_id() -> int | None:
    medio = medios_pago_service.obtener_medio_cheque()
    return medio["id"] if medio else None


def _validar_datos_cheque(banco: str, librador: str, monto: Decimal, fecha_pago: str) -> None:
    if not banco.strip():
        raise ValueError("El banco del cheque no puede estar vacio")
    if not librador.strip():
        raise ValueError("El librador del cheque no puede estar vacio")
    if monto <= 0:
        raise ValueError("El monto del cheque debe ser mayor a cero")
    if not fecha_pago:
        raise ValueError("La fecha de pago del cheque es obligatoria")


def recibir_de_cliente_para_cc(
    cliente_id: int,
    banco: str,
    librador: str,
    monto: Decimal,
    fecha_pago: str,
    numero: str | None = None,
    cuit_librador: str | None = None,
    observacion: str | None = None,
    aplicaciones: list[dict] | None = None,
    fecha: str | None = None,
) -> dict:
    """Entrada 'suelta' de un cheque (sin venta nueva de por medio): el cliente lo entrega para
    saldar una deuda vieja de su cuenta corriente. aplicaciones=None aplica FIFO automatico a los
    cargos abiertos mas viejos, igual que cualquier otro pago de cuenta corriente."""
    cliente = clientes_service.obtener_cliente(cliente_id)
    if cliente is None:
        raise ClienteNoEncontradoError(f"No existe el cliente {cliente_id}")
    _validar_datos_cheque(banco, librador, monto, fecha_pago)
    fecha = fecha or datetime.now().isoformat()

    cheque_id = cheques_repo.crear(
        banco=banco.strip(), librador=librador.strip(),
        cuit_librador=(cuit_librador or "").strip() or None,
        monto=precio_a_entero(monto), fecha_pago=fecha_pago, fecha_recepcion=fecha,
        origen_tipo="recibido_cliente", cliente_id=cliente_id,
        numero=(numero or "").strip() or None, observacion=(observacion or "").strip() or None,
    )
    try:
        cc_service.registrar_pago(
            entidad_tipo="cliente", entidad_id=cliente_id, monto=monto, fecha=fecha,
            aplicaciones=aplicaciones,
            observacion=f"Pago con cheque {numero or '(sin numero)'} - {banco}",
            cheque_id=cheque_id, medio_pago_id=_medio_cheque_id(),
        )
    except Exception:
        # Compensacion: si no se pudo aplicar el pago (ej. monto no coincide con la deuda), no
        # dejamos un cheque huerfano cargado sin ningun destino.
        cheques_repo.eliminar(cheque_id)
        raise

    log_service.registrar(
        "cliente", cliente_id,
        f"Se recibio un cheque de {formatear_precio(monto)} para saldar cuenta corriente",
    )
    return obtener_cheque(cheque_id)


def entregar_a_proveedor(
    cheque_id: int,
    proveedor_id: int,
    aplicaciones: list[dict] | None = None,
    observacion: str | None = None,
    fecha: str | None = None,
) -> dict:
    """Circula un cheque que ya tenemos 'en cartera' (recibido de un cliente) -- lo usamos para
    pagarle a un proveedor nuestro, en vez de depositarlo. Sirve tanto para saldar una cuenta
    corriente vieja del proveedor (aplicaciones apunta a cargos existentes) como para pagar una
    compra nueva (la recepcion se marca a credito primero, y aqui se le pasa ese cargo nuevo en
    aplicaciones)."""
    cheque = cheques_repo.obtener_por_id(cheque_id)
    if cheque is None:
        raise ChequeNoEncontradoError(f"No existe el cheque {cheque_id}")
    if cheque["estado"] != "en_cartera":
        raise ChequeEstadoInvalidoError(
            f"El cheque {cheque_id} no esta en cartera (estado actual: {cheque['estado']})"
        )
    proveedor = proveedores_service.obtener_proveedor(proveedor_id)
    if proveedor is None:
        raise ProveedorNoEncontradoError(f"No existe el proveedor {proveedor_id}")
    fecha = fecha or datetime.now().isoformat()
    monto = entero_a_precio(cheque["monto"])

    cc_service.registrar_pago(
        entidad_tipo="proveedor", entidad_id=proveedor_id, monto=monto, fecha=fecha,
        aplicaciones=aplicaciones,
        observacion=observacion or f"Pago con cheque {cheque['numero'] or '(sin numero)'} - {cheque['banco']}",
        cheque_id=cheque_id, medio_pago_id=_medio_cheque_id(),
    )
    cheques_repo.actualizar_estado(cheque_id, estado="entregado_proveedor", proveedor_id=proveedor_id)

    log_service.registrar(
        "proveedor", proveedor_id,
        f"Se entrego un cheque de {formatear_precio(monto)} para saldar cuenta corriente",
    )
    return obtener_cheque(cheque_id)


def crear_cheque_propio_y_entregar(
    proveedor_id: int,
    banco: str,
    librador: str,
    monto: Decimal,
    fecha_pago: str,
    numero: str | None = None,
    cuit_librador: str | None = None,
    observacion: str | None = None,
    aplicaciones: list[dict] | None = None,
    fecha: str | None = None,
) -> dict:
    """Cheque propio: nace directamente entregado a un proveedor (nunca pasa por 'en cartera',
    porque nunca lo recibimos nosotros). Mismo criterio que entregar_a_proveedor para
    aplicaciones: cargos existentes (saldar CC vieja) o un cargo nuevo recien creado (pagar una
    compra nueva marcada a credito)."""
    proveedor = proveedores_service.obtener_proveedor(proveedor_id)
    if proveedor is None:
        raise ProveedorNoEncontradoError(f"No existe el proveedor {proveedor_id}")
    _validar_datos_cheque(banco, librador, monto, fecha_pago)
    fecha = fecha or datetime.now().isoformat()

    cheque_id = cheques_repo.crear(
        banco=banco.strip(), librador=librador.strip(),
        cuit_librador=(cuit_librador or "").strip() or None,
        monto=precio_a_entero(monto), fecha_pago=fecha_pago, fecha_recepcion=fecha,
        origen_tipo="propio", cliente_id=None,
        numero=(numero or "").strip() or None, observacion=(observacion or "").strip() or None,
    )
    try:
        cc_service.registrar_pago(
            entidad_tipo="proveedor", entidad_id=proveedor_id, monto=monto, fecha=fecha,
            aplicaciones=aplicaciones,
            observacion=observacion or f"Pago con cheque propio {numero or ''}".strip(),
            cheque_id=cheque_id, medio_pago_id=_medio_cheque_id(),
        )
        cheques_repo.actualizar_estado(cheque_id, estado="entregado_proveedor", proveedor_id=proveedor_id)
    except Exception:
        cheques_repo.eliminar(cheque_id)
        raise

    log_service.registrar(
        "proveedor", proveedor_id,
        f"Se emitio un cheque propio de {formatear_precio(monto)} para saldar cuenta corriente",
    )
    return obtener_cheque(cheque_id)


def dar_de_baja(cheque_id: int, observacion: str, fecha: str | None = None) -> dict:
    """Salida libre para cualquier caso que no sea entregarlo a un proveedor -- el motivo va en
    observacion, no hay un campo 'motivo' separado."""
    cheque = cheques_repo.obtener_por_id(cheque_id)
    if cheque is None:
        raise ChequeNoEncontradoError(f"No existe el cheque {cheque_id}")
    if cheque["estado"] != "en_cartera":
        raise ChequeEstadoInvalidoError(
            f"El cheque {cheque_id} no esta en cartera (estado actual: {cheque['estado']})"
        )
    if not observacion.strip():
        raise ValueError("Dar de baja un cheque requiere indicar el motivo en la observacion")

    cheques_repo.actualizar_estado(cheque_id, estado="baja", observacion=observacion.strip())
    log_service.registrar("cheque", cheque_id, f"Se dio de baja el cheque: {observacion.strip()}")
    return obtener_cheque(cheque_id)


def marcar_rechazado(cheque_id: int, observacion: str, fecha: str | None = None) -> dict:
    """Rebotó, se rompió, o cualquier motivo por el cual el cheque ya no sirve para cobrar.
    Nunca se edita ni se borra nada -- se genera un cargo nuevo que reabre la deuda (del cliente
    si el cheque era recibido, del negocio hacia el proveedor si era propio), mismo criterio que
    el resto del sistema."""
    cheque = cheques_repo.obtener_por_id(cheque_id)
    if cheque is None:
        raise ChequeNoEncontradoError(f"No existe el cheque {cheque_id}")
    if not observacion.strip():
        raise ValueError("Rechazar un cheque requiere indicar el motivo en la observacion")

    if cheque["origen_tipo"] == "recibido_cliente":
        if cheque["estado"] != "en_cartera":
            raise ChequeEstadoInvalidoError(
                "Solo se puede rechazar un cheque recibido mientras esta en cartera "
                f"(estado actual: {cheque['estado']})"
            )
        cliente_id, proveedor_id = cheque["cliente_id"], None
        entidad_tipo, entidad_id = "cliente", cheque["cliente_id"]
    else:
        if cheque["estado"] != "entregado_proveedor":
            raise ChequeEstadoInvalidoError(
                "Solo se puede rechazar un cheque propio mientras esta entregado a un proveedor "
                f"(estado actual: {cheque['estado']})"
            )
        cliente_id, proveedor_id = None, cheque["proveedor_id"]
        entidad_tipo, entidad_id = "proveedor", cheque["proveedor_id"]

    fecha = fecha or datetime.now().isoformat()
    cheques_repo.rechazar(
        cheque_id=cheque_id, cliente_id=cliente_id, proveedor_id=proveedor_id,
        monto=cheque["monto"], fecha=fecha, observacion=observacion.strip(),
    )

    monto = entero_a_precio(cheque["monto"])
    log_service.registrar(
        entidad_tipo, entidad_id,
        f"Se genero un cargo de {formatear_precio(monto)} en cuenta corriente por el rechazo de un cheque",
    )
    log_service.registrar("cheque", cheque_id, f"Cheque rechazado: {observacion.strip()}")
    return obtener_cheque(cheque_id)
