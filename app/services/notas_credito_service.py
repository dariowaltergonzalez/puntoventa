import sqlite3
from datetime import datetime
from decimal import Decimal

from app.repositories import cheques_repo, ventas_repo
from app.services import (
    cc_service,
    clientes_service,
    listas_precios_service,
    log_service,
    medios_pago_service,
    productos_service,
    ventas_service,
)
from app.services.exceptions import (
    LineasVaciasError,
    MedioPagoNoEncontradoError,
    NotaCreditoInvalidaError,
    VentaNoEncontradaError,
)
from app.shared.money import (
    cantidad_a_entero,
    entero_a_cantidad,
    entero_a_porcentaje,
    entero_a_precio,
    formatear_porcentaje,
    formatear_precio,
    precio_a_entero,
)

# Destinos posibles para la parte del reintegro que NO descuenta deuda de la propia venta.
DESTINO_MEDIO_PAGO = "medio_pago"   # se le devuelve la plata en ese medio
DESTINO_A_FAVOR = "a_favor"         # queda a favor en su cuenta corriente
DESTINO_CHEQUE = "cheque"           # se le devuelve el cheque con que pago


def _obtener_venta_fila(venta_id: int) -> sqlite3.Row:
    fila = ventas_repo.obtener_por_id(venta_id)
    if fila is None:
        raise VentaNoEncontradaError(f"No existe la venta {venta_id}")
    if fila["estado"] != "confirmada":
        raise NotaCreditoInvalidaError("Solo se puede hacer una nota de credito de una venta confirmada")
    return fila


def _validar_items(venta_id: int, items: list[dict]) -> list[dict]:
    """items: [{'venta_item_id', 'cantidad' (Decimal), 'vuelve_stock' (bool)}]. Las lineas con
    cantidad 0 se ignoran (son las que no se devuelven). Devuelve las validas, ya escaladas."""
    lineas_venta = {f["id"]: f for f in ventas_repo.listar_items(venta_id)}
    devueltas = ventas_repo.cantidades_devueltas_por_item(venta_id)
    validados = []
    for item in items:
        cantidad = item.get("cantidad") or Decimal("0")
        if cantidad == 0:
            continue
        if cantidad < 0:
            raise ValueError("La cantidad a devolver no puede ser negativa")
        linea = lineas_venta.get(item["venta_item_id"])
        if linea is None:
            raise NotaCreditoInvalidaError(f"La linea {item['venta_item_id']} no pertenece a esta venta")
        disponible = linea["cantidad"] - devueltas.get(linea["id"], 0)
        cantidad_entera = cantidad_a_entero(cantidad)
        if cantidad_entera > disponible:
            nombre = linea["descripcion_libre"] or linea["producto_nombre"]
            raise NotaCreditoInvalidaError(
                f"De '{nombre}' se puede devolver como maximo {entero_a_cantidad(disponible)}"
            )
        validados.append({
            "venta_item_id": linea["id"],
            "producto_id": linea["producto_id"],
            "cantidad": cantidad_entera,
            "precio_unitario": linea["precio_unitario"],
            "descuento_item_porcentaje": linea["descuento_item_porcentaje"],
            "vuelve_stock": bool(item.get("vuelve_stock", True)) and linea["producto_id"] is not None,
        })
    if not validados:
        raise LineasVaciasError("Indica al menos una linea y cantidad a devolver")
    return validados


def _calcular_total(venta_id: int, items_validados: list[dict]) -> Decimal:
    """Con los precios y descuentos de la venta. Si esta nota de credito termina de acreditar la
    venta entera, se lleva lo que falte para llegar justo al total (por redondeos, varias notas
    de credito parciales podrian sumar un centavo de mas o de menos)."""
    venta = ventas_service.obtener_venta(venta_id)
    por_item = {i["venta_item_id"]: i["cantidad"] for i in items_validados}
    completa = all(
        cantidad_a_entero(item["cantidad"]) == cantidad_a_entero(item["cantidad_devuelta"]) + por_item.get(item["id"], 0)
        for item in venta["items"]
    )
    if completa:
        return venta["total"] - venta["total_acreditado"]
    return ventas_service.calcular_total_lineas(ventas_repo.obtener_por_id(venta_id), items_validados)["total"]


def previsualizar_total(venta_id: int, items: list[dict]) -> Decimal:
    _obtener_venta_fila(venta_id)
    return _calcular_total(venta_id, _validar_items(venta_id, items))


def _saldo_cargos_de_la_venta(venta_fila: sqlite3.Row) -> list[dict]:
    """Cargos de cuenta corriente que genero esta venta y siguen con saldo (lo que el cliente
    todavia debe de ESTA venta). Es lo primero que descuenta una nota de credito."""
    return [
        c for c in cc_service.listar_cargos("cliente", venta_fila["cliente_id"], solo_con_saldo=True)
        if c["origen"] == "venta" and c["origen_venta_id"] == venta_fila["id"]
    ]


def _es_cliente_generico(cliente_id: int) -> bool:
    cliente = clientes_service.obtener_cliente(cliente_id)
    return cliente is not None and clientes_service.es_cliente_generico(cliente)


def _cheques_devolvibles(venta_id: int) -> list[dict]:
    cheques = []
    for pago in ventas_repo.listar_pagos(venta_id):
        if pago["cheque_id"] is None:
            continue
        cheque = cheques_repo.obtener_por_id(pago["cheque_id"])
        if cheque["estado"] == "en_cartera":
            cheques.append({
                "id": cheque["id"], "banco": cheque["banco"], "numero": cheque["numero"],
                "monto": entero_a_precio(cheque["monto"]),
            })
    return cheques


def opciones_reintegro(venta_id: int, total: Decimal) -> dict:
    """Para armar la pantalla: cuanto descuenta solo de la deuda de la venta, cuanto queda por
    reintegrar, y que destinos hay para ese resto (con uno sugerido)."""
    venta_fila = _obtener_venta_fila(venta_id)
    deuda_venta = sum((c["saldo_pendiente"] for c in _saldo_cargos_de_la_venta(venta_fila)), Decimal("0"))
    a_cuenta_corriente = min(total, deuda_venta)
    resto = total - a_cuenta_corriente

    medios = [
        m for m in medios_pago_service.listar_medios_pago(solo_activos=True)
        if not m["es_cuenta_corriente"] and not medios_pago_service.es_medio_cheque(m)
    ]
    cheques = _cheques_devolvibles(venta_id)
    pagos_venta = ventas_repo.listar_pagos(venta_id)
    medio_sugerido = next(
        (p["medio_pago_id"] for p in pagos_venta
         if not p["es_cuenta_corriente"] and p["cheque_id"] is None and any(m["id"] == p["medio_pago_id"] for m in medios)),
        next((m["id"] for m in medios if m["nombre"].lower() == "efectivo"), medios[0]["id"] if medios else None),
    )
    cheque_sugerido = next((c for c in cheques if c["monto"] == resto), None)
    sugerido = (
        {"tipo": DESTINO_CHEQUE, "cheque_id": cheque_sugerido["id"]} if cheque_sugerido
        else {"tipo": DESTINO_MEDIO_PAGO, "medio_pago_id": medio_sugerido}
    )
    return {
        "a_cuenta_corriente": a_cuenta_corriente,
        "resto": resto,
        "medios": medios,
        "cheques": cheques,
        "permite_a_favor": not _es_cliente_generico(venta_fila["cliente_id"]),
        "destino_sugerido": sugerido,
    }


def avisos_correccion(venta_id: int) -> list[str]:
    """'Corregir venta' rehace el ticket con los precios y el descuento del cliente de HOY. Si
    algo cambio desde la venta, se avisa antes de confirmar (sin limite de tiempo: lo que importa
    es si el precio cambio, no cuanto paso). Lista vacia = nada cambio."""
    venta = ventas_service.obtener_venta(venta_id)
    avisos = []
    for item in venta["items"]:
        if item["producto_id"] is None or item["cantidad"] <= item["cantidad_devuelta"]:
            continue
        if venta["lista_precio_id"] is not None:
            precio_hoy = listas_precios_service.calcular_precio_producto(item["producto_id"], venta["lista_precio_id"])
        else:
            precio_hoy = productos_service.obtener_producto(item["producto_id"])["precio_venta"]
        if precio_hoy != item["precio_unitario"]:
            avisos.append(
                f"El precio de {item['producto_nombre']} cambio de {formatear_precio(item['precio_unitario'])} "
                f"a {formatear_precio(precio_hoy)}"
            )
    cliente = clientes_service.obtener_cliente(venta["cliente_id"])
    descuento_venta = venta["descuento_cliente_porcentaje"] or Decimal("0")
    descuento_hoy = (cliente["porcentaje_descuento"] if cliente else None) or Decimal("0")
    if descuento_hoy != descuento_venta:
        avisos.append(
            f"El descuento fijo del cliente cambio de {formatear_porcentaje(descuento_venta)}% "
            f"a {formatear_porcentaje(descuento_hoy)}%"
        )
    return avisos


def _aplicaciones_fifo(saldos: dict[int, int], monto: int) -> list[dict]:
    aplicaciones = []
    for cargo_id in list(saldos):
        if monto <= 0:
            break
        aplicar = min(monto, saldos[cargo_id])
        if aplicar > 0:
            aplicaciones.append({"cargo_id": cargo_id, "monto": aplicar})
            saldos[cargo_id] -= aplicar
            monto -= aplicar
    return aplicaciones


def crear_nota_credito(
    venta_id: int,
    items: list[dict],
    motivo: str,
    destino_resto: dict | None = None,
    es_correccion: bool = False,
    fecha: str | None = None,
) -> dict:
    """items: [{'venta_item_id', 'cantidad' (Decimal), 'vuelve_stock' (bool)}].
    El reintegro se arma solo: primero descuenta la deuda que quede de esta misma venta en
    cuenta corriente; el resto va a destino_resto:
      {'tipo': 'medio_pago', 'medio_pago_id'} | {'tipo': 'a_favor'} | {'tipo': 'cheque', 'cheque_id'}
    """
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("La nota de credito requiere un motivo")
    venta_fila = _obtener_venta_fila(venta_id)
    items_validados = _validar_items(venta_id, items)
    total = _calcular_total(venta_id, items_validados)
    if total <= 0:
        raise NotaCreditoInvalidaError("El total de la nota de credito tiene que ser mayor a cero")
    cliente_id = venta_fila["cliente_id"]

    # Saldo abierto de todos los cargos del cliente, en orden FIFO, con los de esta venta primero.
    cargos_venta = _saldo_cargos_de_la_venta(venta_fila)
    saldos_venta = {c["id"]: precio_a_entero(c["saldo_pendiente"]) for c in cargos_venta}
    total_entero = precio_a_entero(total)
    a_cc = min(total_entero, sum(saldos_venta.values()))
    resto = total_entero - a_cc

    reintegros = []
    if a_cc > 0:
        reintegros.append({"tipo": "cuenta_corriente", "monto": a_cc, "aplicaciones": _aplicaciones_fifo(saldos_venta, a_cc)})

    descripcion_resto = ""
    if resto > 0:
        if not destino_resto:
            raise ValueError(f"Indica que se hace con los {formatear_precio(entero_a_precio(resto))} a reintegrar")
        tipo = destino_resto.get("tipo")
        if tipo == DESTINO_MEDIO_PAGO:
            medio = medios_pago_service.obtener_medio_pago(destino_resto.get("medio_pago_id") or 0)
            if medio is None or not medio["activo"]:
                raise MedioPagoNoEncontradoError("Elegi un medio de pago valido para devolver la plata")
            if medio["es_cuenta_corriente"]:
                raise ValueError("Para dejarlo en la cuenta corriente elegi 'dejar a favor'")
            reintegros.append({"tipo": "medio_pago", "monto": resto, "medio_pago_id": medio["id"]})
            descripcion_resto = f"se devolvieron {formatear_precio(entero_a_precio(resto))} en {medio['nombre']}"
        elif tipo == DESTINO_A_FAVOR:
            if _es_cliente_generico(cliente_id):
                raise NotaCreditoInvalidaError("Al cliente generico no se le puede dejar saldo a favor: devolvele la plata")
            otros_cargos = {
                c["id"]: precio_a_entero(c["saldo_pendiente"])
                for c in cc_service.listar_cargos("cliente", cliente_id, solo_con_saldo=True)
                if c["id"] not in saldos_venta
            }
            reintegros.append({"tipo": "cuenta_corriente", "monto": resto, "aplicaciones": _aplicaciones_fifo(otros_cargos, resto)})
            descripcion_resto = f"quedaron {formatear_precio(entero_a_precio(resto))} a favor en su cuenta corriente"
        elif tipo == DESTINO_CHEQUE:
            cheque = next((c for c in _cheques_devolvibles(venta_id) if c["id"] == destino_resto.get("cheque_id")), None)
            if cheque is None:
                raise NotaCreditoInvalidaError("Ese cheque no es de esta venta o ya no esta en cartera")
            if precio_a_entero(cheque["monto"]) != resto:
                raise NotaCreditoInvalidaError(
                    f"El cheque es de {formatear_precio(cheque['monto'])} y hay que reintegrar "
                    f"{formatear_precio(entero_a_precio(resto))}: devolve la plata en otro medio"
                )
            reintegros.append({
                "tipo": "cheque", "monto": resto, "cheque_id": cheque["id"],
                "cheque_observacion": f"Devuelto al cliente con la nota de credito ({motivo})",
            })
            descripcion_resto = f"se devolvio el cheque {cheque['banco']} n° {cheque['numero'] or 's/n'}"
        else:
            raise ValueError("Destino del reintegro invalido")

    resultado = ventas_repo.crear_nota_credito(
        venta_id=venta_id, cliente_id=cliente_id, fecha=fecha or datetime.now().isoformat(), motivo=motivo,
        es_correccion=es_correccion, items=items_validados, reintegros=reintegros,
    )

    numero = resultado["numero"]
    partes = []
    if a_cc > 0:
        partes.append(f"se descontaron {formatear_precio(entero_a_precio(a_cc))} de su deuda")
    if descripcion_resto:
        partes.append(descripcion_resto)
    log_service.registrar(
        "venta", venta_id,
        f"Se emitio la nota de credito {numero} por {formatear_precio(total)} ({motivo}): {', '.join(partes)}",
    )
    if any(r["tipo"] == "cuenta_corriente" for r in reintegros):
        log_service.registrar("cliente", cliente_id, f"La nota de credito {numero} acredito su cuenta corriente")
    if any(r["tipo"] == "cheque" for r in reintegros):
        log_service.registrar("cheque", destino_resto["cheque_id"], f"Devuelto al cliente con la nota de credito {numero}")
    cantidades_por_producto: dict[int, Decimal] = {}
    for item in items_validados:
        if item["vuelve_stock"]:
            cantidades_por_producto[item["producto_id"]] = (
                cantidades_por_producto.get(item["producto_id"], Decimal("0")) + entero_a_cantidad(item["cantidad"])
            )
    log_service.registrar_resumen_stock("venta", venta_id, numero, "ingreso", cantidades_por_producto)
    return obtener_nota_credito(resultado["nota_credito_id"])


def obtener_nota_credito(nota_credito_id: int) -> dict | None:
    fila = ventas_repo.obtener_nota_credito(nota_credito_id)
    if fila is None:
        return None
    venta_fila = ventas_repo.obtener_por_id(fila["venta_id"])
    filas_items = ventas_repo.listar_items_nota_credito(nota_credito_id)
    items = [
        {
            "venta_item_id": f["venta_item_id"],
            "producto_id": f["producto_id"],
            "descripcion": f["descripcion_libre"] or f"{f['producto_codigo']} - {f['producto_nombre']}",
            "cantidad": entero_a_cantidad(f["cantidad"]),
            "precio_unitario": entero_a_precio(f["precio_unitario"]),
            "descuento_item_porcentaje": (
                entero_a_porcentaje(f["descuento_item_porcentaje"]) if f["descuento_item_porcentaje"] is not None else None
            ),
            "vuelve_stock": bool(f["vuelve_stock"]),
        }
        for f in filas_items
    ]
    reintegros = [
        {
            "tipo": r["tipo"], "monto": entero_a_precio(r["monto"]), "medio_pago_nombre": r["medio_pago_nombre"],
            "cheque_id": r["cheque_id"], "cheque_banco": r["cheque_banco"], "cheque_numero": r["cheque_numero"],
            "cc_pago_id": r["cc_pago_id"],
        }
        for r in ventas_repo.listar_reintegros(nota_credito_id)
    ]
    return {
        "id": fila["id"], "numero": fila["numero"], "venta_id": fila["venta_id"], "venta_numero": venta_fila["numero"],
        "cliente_id": fila["cliente_id"], "fecha": fila["fecha"], "motivo": fila["motivo"],
        "es_correccion": bool(fila["es_correccion"]),
        "items": items, "reintegros": reintegros,
        "total": ventas_service.total_nota_credito(nota_credito_id),
    }
