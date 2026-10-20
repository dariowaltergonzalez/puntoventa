import sqlite3
from datetime import date, datetime
from decimal import Decimal

from app.repositories import borradores_repo, productos_repo, ventas_repo
from app.services import clientes_service, listas_precios_service, log_service, medios_pago_service, negocio_service
from app.services.exceptions import (
    ClienteNoEncontradoError,
    LineasVaciasError,
    ListaPrecioNoEncontradaError,
    MedioPagoNoEncontradoError,
    MontoPagoInvalidoError,
    PresupuestoNoDisponibleError,
    PreventaNoDisponibleError,
    ProductoInactivoError,
    ProductoNoEncontradoError,
    ProductoSinPrecioError,
    StockInsuficienteError,
    VentaNoEncontradaError,
)
from app.shared.money import (
    cantidad_a_entero,
    entero_a_cantidad,
    entero_a_porcentaje,
    entero_a_precio,
    formatear_precio,
    porcentaje_a_entero,
    precio_a_entero,
)


def _resolver_cliente(
    cliente_id: int | None, cliente_nombre_nuevo: str | None, usar_generico: bool = False,
) -> dict:
    if usar_generico:
        return clientes_service.obtener_o_crear_cliente_generico()
    if cliente_id is not None:
        cliente = clientes_service.obtener_cliente(cliente_id)
        if cliente is None:
            raise ClienteNoEncontradoError(f"No existe el cliente {cliente_id}")
        return cliente
    nombre = (cliente_nombre_nuevo or "").strip()
    if not nombre:
        raise ValueError("Debe indicarse un cliente")
    return clientes_service.obtener_o_crear_cliente_por_razon_social(nombre)


def condiciones_de_borrador(borrador_id: int | None) -> dict | None:
    """Si el carrito viene de una pre-venta o un presupuesto: lo valida (tiene que estar abierto, y
    un presupuesto ademas vigente) y devuelve sus condiciones. Un presupuesto congela el precio de
    cada producto y el % fijo del cliente: se cobra lo que se le prometio. Una pre-venta no congela
    nada (se cobra a precio de hoy)."""
    if borrador_id is None:
        return None
    fila = borradores_repo.obtener(borrador_id)
    es_presupuesto = fila is not None and fila["tipo"] == "presupuesto"
    error = PresupuestoNoDisponibleError if es_presupuesto else PreventaNoDisponibleError
    if fila is None:
        raise error(f"No existe el borrador {borrador_id}")
    nombre = fila["numero"] or f"'{fila['nombre']}'"
    if fila["estado"] != "abierta":
        raise error(f"{'El presupuesto' if es_presupuesto else 'La pre-venta'} {nombre} ya fue {fila['estado']}")
    condiciones = {"tipo": fila["tipo"], "nombre": nombre, "precios": {}, "descuento_cliente": None,
                   "iva": fila["iva_porcentaje"] or 0, "precios_con_iva": bool(fila["precios_con_iva"])}
    if es_presupuesto:
        if fila["fecha_validez"] < date.today().isoformat():
            raise error(f"El presupuesto {nombre} esta vencido: renovalo (con los precios de hoy) antes de cobrarlo")
        condiciones["precios"] = {
            f["producto_id"]: entero_a_precio(f["precio_unitario"])
            for f in borradores_repo.listar_items(borrador_id) if f["producto_id"] is not None
        }
        condiciones["descuento_cliente"] = (
            entero_a_porcentaje(fila["descuento_cliente_porcentaje"]) if fila["descuento_cliente_porcentaje"] else None
        )
    return condiciones


def condiciones_iva(borrador_id: int | None = None) -> tuple[int, bool]:
    """(% de IVA x100, precios con IVA incluido) para una venta. Un presupuesto trae las suyas
    (lo que se prometio); todo lo demas sale de la configuracion del negocio. El IVA nunca se
    tipea en la caja."""
    condiciones = condiciones_de_borrador(borrador_id)
    if condiciones and condiciones["tipo"] == "presupuesto":
        return condiciones["iva"], condiciones["precios_con_iva"]
    config = negocio_service.config_iva()
    return config["alicuota_entero"], config["precios_con_iva"]


def _validar_items(items_entrada: list[dict], lista_precio_id: int | None, precios_fijos: dict | None = None) -> list[dict]:
    """items_entrada: {'producto_id': int|None, 'descripcion_libre': str|None, 'cantidad': Decimal,
    'precio_unitario': Decimal|None (solo para items libres, se ignora si hay producto_id),
    'descuento_item_porcentaje': Decimal|None}. Exactamente uno de producto_id/descripcion_libre.
    El precio de un producto de catalogo siempre lo resuelve el sistema (lista de precios si hay,
    si no el precio de venta normal) -- nunca se recibe tipeado."""
    if not items_entrada:
        raise LineasVaciasError("La venta debe tener al menos una linea")

    items_validados = []
    cantidad_reservada_por_producto: dict[int, Decimal] = {}

    for item in items_entrada:
        producto_id = item.get("producto_id")
        descripcion_libre = (item.get("descripcion_libre") or "").strip() or None
        if (producto_id is None) == (descripcion_libre is None):
            raise ValueError("Cada linea debe tener producto_id o descripcion_libre, pero no ambos ni ninguno")

        cantidad = item["cantidad"]
        if cantidad <= 0:
            raise ValueError("La cantidad debe ser mayor a cero")

        descuento_item = item.get("descuento_item_porcentaje")
        if descuento_item is not None and descuento_item < 0:
            raise ValueError("El descuento de una linea no puede ser negativo")

        if producto_id is not None:
            producto = productos_repo.obtener_por_id(producto_id)
            if producto is None:
                raise ProductoNoEncontradoError(f"No existe el producto {producto_id}")
            if not producto["activo"]:
                raise ProductoInactivoError(f"El producto '{producto['nombre']}' esta inactivo")

            if precios_fijos and producto_id in precios_fijos:
                precio_unitario = precios_fijos[producto_id]
            elif lista_precio_id is not None:
                precio_unitario = listas_precios_service.calcular_precio_producto(producto_id, lista_precio_id)
            else:
                precio_unitario = entero_a_precio(producto["precio_venta"])
            if precio_unitario <= 0:
                raise ProductoSinPrecioError(
                    f"El producto '{producto['nombre']}' no tiene precio de venta cargado -- "
                    f"complete el precio en Productos antes de venderlo"
                )

            stock_disponible = entero_a_cantidad(producto["stock_actual"])
            reservado = cantidad_reservada_por_producto.get(producto_id, Decimal("0")) + cantidad
            cantidad_reservada_por_producto[producto_id] = reservado
            if reservado > stock_disponible:
                raise StockInsuficienteError(
                    f"No hay stock suficiente de '{producto['nombre']}' "
                    f"(disponible: {stock_disponible}, se necesitan: {reservado})"
                )

            items_validados.append({
                "producto_id": producto_id,
                "descripcion_libre": None,
                "cantidad": cantidad_a_entero(cantidad),
                "precio_unitario": precio_a_entero(precio_unitario),
                "descuento_item_porcentaje": porcentaje_a_entero(descuento_item) if descuento_item is not None else None,
            })
        else:
            precio_unitario = item.get("precio_unitario")
            if precio_unitario is None or precio_unitario < 0:
                raise ValueError(f"El item libre '{descripcion_libre}' necesita un precio unitario valido")
            items_validados.append({
                "producto_id": None,
                "descripcion_libre": descripcion_libre,
                "cantidad": cantidad_a_entero(cantidad),
                "precio_unitario": precio_a_entero(precio_unitario),
                "descuento_item_porcentaje": porcentaje_a_entero(descuento_item) if descuento_item is not None else None,
            })
    return items_validados


def calcular_totales(
    items_validados: list[dict],
    cliente_porcentaje_descuento: Decimal | None,
    descuento_total_porcentaje_entero: int | None,
    iva_entero: int | None = None,
    precios_con_iva: bool = False,
) -> dict:
    """Aplica las 3 capas de descuento, todas acumulables (nunca se pisan): precio ya resuelto por
    item (con la lista de precios adentro) menos el descuento manual de esa linea si lo tiene ->
    subtotal -> % fijo del cliente -> % manual sobre el total -> IVA.
    Siempre devuelve neto + iva = total (exacto), aunque el IVA sea 0:
      precios sin IVA: el IVA (iva_entero, x100) se SUMA al neto
      precios con IVA: el total es lo cobrado y el IVA se DESGLOSA de adentro"""
    subtotal = Decimal("0")
    for item in items_validados:
        cantidad = entero_a_cantidad(item["cantidad"])
        precio = entero_a_precio(item["precio_unitario"])
        monto_item = cantidad * precio
        if item["descuento_item_porcentaje"] is not None:
            pct_item = entero_a_porcentaje(item["descuento_item_porcentaje"])
            monto_item = monto_item * (Decimal("1") - pct_item / Decimal("100"))
        subtotal += monto_item

    con_descuento_cliente = subtotal
    if cliente_porcentaje_descuento:
        con_descuento_cliente = subtotal * (Decimal("1") - cliente_porcentaje_descuento / Decimal("100"))

    con_descuento_total = con_descuento_cliente
    if descuento_total_porcentaje_entero is not None:
        pct_total = entero_a_porcentaje(descuento_total_porcentaje_entero)
        con_descuento_total = con_descuento_cliente * (Decimal("1") - pct_total / Decimal("100"))

    centavo = Decimal("1.00")
    tasa = entero_a_porcentaje(iva_entero) / Decimal("100") if iva_entero else Decimal("0")
    if precios_con_iva:
        total = con_descuento_total.quantize(centavo)
        neto = (total / (Decimal("1") + tasa)).quantize(centavo)
    else:
        neto = con_descuento_total.quantize(centavo)
        total = neto + (neto * tasa).quantize(centavo)

    return {
        "subtotal": subtotal.quantize(centavo),
        "neto": neto,
        "iva": total - neto,
        "total": total,
    }


def _validar_datos_cheque_pago(datos_cheque: dict) -> dict:
    banco = (datos_cheque.get("banco") or "").strip()
    librador = (datos_cheque.get("librador") or "").strip()
    fecha_pago = datos_cheque.get("fecha_pago")
    if not banco:
        raise ValueError("El banco del cheque no puede estar vacio")
    if not librador:
        raise ValueError("El librador del cheque no puede estar vacio")
    if not fecha_pago:
        raise ValueError("La fecha de pago del cheque es obligatoria")
    return {
        "banco": banco,
        "librador": librador,
        "cuit_librador": (datos_cheque.get("cuit_librador") or "").strip() or None,
        "numero": (datos_cheque.get("numero") or "").strip() or None,
        "fecha_pago": fecha_pago,
        "observacion": (datos_cheque.get("observacion") or "").strip() or None,
    }


def _validar_pagos(pagos_entrada: list[dict], total_venta: Decimal) -> list[dict]:
    """pago de entrada: {'medio_pago_id': int, 'monto': Decimal, 'recibido': Decimal|None,
    'cheque': dict|None}. 'recibido' es lo que el cliente entrego fisicamente (solo tiene sentido
    en efectivo, para poder consultar despues con que billete pago y de donde salio el vuelto).
    'cheque': {'banco', 'librador', 'cuit_librador', 'numero', 'fecha_pago'} -- cuando el medio se
    paga con un cheque (Fase 6), se guarda como un cheque 'recibido_cliente' en cartera."""
    if not pagos_entrada:
        raise ValueError("La venta debe tener al menos un medio de pago")
    pagos_validados = []
    suma = Decimal("0")
    for pago in pagos_entrada:
        medio_pago_id = pago["medio_pago_id"]
        medio = medios_pago_service.obtener_medio_pago(medio_pago_id)
        if medio is None:
            raise MedioPagoNoEncontradoError(f"No existe el medio de pago {medio_pago_id}")
        monto = pago["monto"]
        if monto <= 0:
            raise ValueError("El monto de cada medio de pago debe ser mayor a cero")
        recibido = pago.get("recibido")
        if recibido is not None and recibido < monto:
            raise ValueError("Lo recibido no puede ser menor al monto aplicado de ese medio de pago")
        cheque = pago.get("cheque")
        datos_cheque_validados = _validar_datos_cheque_pago(cheque) if cheque is not None else None
        suma += monto
        pagos_validados.append({
            "medio_pago_id": medio_pago_id,
            "monto": precio_a_entero(monto),
            "recibido": precio_a_entero(recibido) if recibido is not None else None,
            "es_cuenta_corriente": medio["es_cuenta_corriente"],
            "cheque": datos_cheque_validados,
        })
    if suma != total_venta:
        raise MontoPagoInvalidoError(
            f"La suma de los medios de pago ({formatear_precio(suma)}) no coincide con el total "
            f"de la venta ({formatear_precio(total_venta)})"
        )
    return pagos_validados


def preparar_carrito(
    items: list[dict], lista_precio_id: int | None = None, cliente_id: int | None = None, borrador_id: int | None = None,
) -> tuple[list[dict], Decimal | None]:
    """Lineas validadas con su precio ya resuelto (lista, precio normal o el congelado de un
    presupuesto) y el % fijo del cliente que corresponde. Lo comparten la previsualizacion de la
    caja y la ganancia estimada del carrito, para que nunca calculen con precios distintos."""
    condiciones = condiciones_de_borrador(borrador_id)
    items_validados = _validar_items(items, lista_precio_id, condiciones["precios"] if condiciones else None)
    if condiciones and condiciones["tipo"] == "presupuesto":
        return items_validados, condiciones["descuento_cliente"]
    if cliente_id is not None:
        cliente = clientes_service.obtener_cliente(cliente_id)
        return items_validados, cliente["porcentaje_descuento"] if cliente else None
    return items_validados, None


def previsualizar_totales(
    items: list[dict],
    lista_precio_id: int | None = None,
    cliente_id: int | None = None,
    descuento_total_porcentaje: Decimal | None = None,
    borrador_id: int | None = None,
) -> dict:
    """Valida y calcula subtotal/total sin persistir nada -- para mostrar en vivo en la UI
    mientras se arma la venta, reutilizando exactamente la misma logica que crear_venta usa al
    confirmar (evita que la previsualizacion y el resultado final puedan llegar a diferir)."""
    items_validados, cliente_descuento = preparar_carrito(items, lista_precio_id, cliente_id, borrador_id)
    descuento_total_entero = (
        porcentaje_a_entero(descuento_total_porcentaje) if descuento_total_porcentaje is not None else None
    )
    iva_entero, precios_con_iva = condiciones_iva(borrador_id)
    return calcular_totales(items_validados, cliente_descuento, descuento_total_entero, iva_entero, precios_con_iva)


def crear_venta(
    items: list[dict],
    pagos: list[dict],
    cliente_id: int | None = None,
    cliente_nombre_nuevo: str | None = None,
    usar_cliente_generico: bool = False,
    lista_precio_id: int | None = None,
    descuento_total_porcentaje: Decimal | None = None,
    fecha: str | None = None,
    observacion: str | None = None,
    borrador_id: int | None = None,
) -> dict:
    """Camino unico y normal de Fase 4: la venta nace directamente confirmada (descuenta stock,
    registra los pagos, genera cargo en Cuentas Corrientes si corresponde), todo en un commit.
    borrador_id: la pre-venta o el presupuesto del que sale el carrito (queda convertido; un
    presupuesto ademas aporta sus precios y su % de cliente congelados)."""
    condiciones = condiciones_de_borrador(borrador_id)
    cliente = _resolver_cliente(cliente_id, cliente_nombre_nuevo, usar_cliente_generico)
    if condiciones and condiciones["tipo"] == "presupuesto":
        descuento_cliente = condiciones["descuento_cliente"]
    else:
        descuento_cliente = cliente["porcentaje_descuento"]

    if lista_precio_id is not None and listas_precios_service.obtener_lista(lista_precio_id) is None:
        raise ListaPrecioNoEncontradaError(f"No existe la lista de precios {lista_precio_id}")

    if descuento_total_porcentaje is not None and descuento_total_porcentaje < 0:
        raise ValueError("El descuento sobre el total no puede ser negativo")
    descuento_total_entero = (
        porcentaje_a_entero(descuento_total_porcentaje) if descuento_total_porcentaje is not None else None
    )

    items_validados = _validar_items(items, lista_precio_id, condiciones["precios"] if condiciones else None)
    iva_entero, precios_con_iva = condiciones_iva(borrador_id)
    totales = calcular_totales(items_validados, descuento_cliente, descuento_total_entero, iva_entero, precios_con_iva)
    pagos_validados = _validar_pagos(pagos, totales["total"])

    resultado = ventas_repo.crear_venta_confirmada(
        cliente_id=cliente["id"],
        lista_precio_id=lista_precio_id,
        fecha=fecha or datetime.now().isoformat(),
        iva_porcentaje=iva_entero,
        precios_con_iva=precios_con_iva,
        descuento_total_porcentaje=descuento_total_entero,
        observacion=(observacion or "").strip() or None,
        items=items_validados,
        pagos=pagos_validados,
        descuento_cliente_porcentaje=porcentaje_a_entero(descuento_cliente) if descuento_cliente else None,
        borrador_id=borrador_id,
    )
    if condiciones:
        que = "El presupuesto" if condiciones["tipo"] == "presupuesto" else "La pre-venta"
        log_service.registrar(condiciones["tipo"], borrador_id, f"{que} {condiciones['nombre']} se cobro como {resultado['numero']}")

    log_service.registrar(
        "venta", resultado["venta_id"],
        f"Se creo y confirmo la venta {resultado['numero']} a '{cliente['razon_social']}' "
        f"por {formatear_precio(totales['total'])}",
    )
    cantidades_por_producto: dict[int, Decimal] = {}
    for item in items_validados:
        if item["producto_id"] is None:
            continue
        cantidad = entero_a_cantidad(item["cantidad"])
        cantidades_por_producto[item["producto_id"]] = cantidades_por_producto.get(item["producto_id"], Decimal("0")) + cantidad
    log_service.registrar_resumen_stock(
        "venta", resultado["venta_id"], resultado["numero"], "egreso", cantidades_por_producto,
    )
    if resultado["cargos_generados"]:
        log_service.registrar(
            "cliente", cliente["id"],
            f"Se genero un cargo en cuenta corriente por la venta a credito {resultado['numero']}",
        )

    return obtener_venta(resultado["venta_id"])


def _item_a_dict(fila: sqlite3.Row) -> dict:
    lotes = ventas_repo.listar_lotes_de_item(fila["id"])
    return {
        "id": fila["id"],
        "producto_id": fila["producto_id"],
        "producto_codigo": fila["producto_codigo"],
        "producto_nombre": fila["producto_nombre"],
        "descripcion_libre": fila["descripcion_libre"],
        "cantidad": entero_a_cantidad(fila["cantidad"]),
        "precio_unitario": entero_a_precio(fila["precio_unitario"]),
        "descuento_item_porcentaje": (
            entero_a_porcentaje(fila["descuento_item_porcentaje"])
            if fila["descuento_item_porcentaje"] is not None else None
        ),
        "lotes": [
            {
                "lote_id": l["lote_id"],
                "cantidad": entero_a_cantidad(l["cantidad"]),
                "costo_unitario": entero_a_precio(l["costo_unitario"]),
            }
            for l in lotes
        ],
    }


def _pago_a_dict(fila: sqlite3.Row) -> dict:
    recibido = entero_a_precio(fila["recibido"]) if fila["recibido"] is not None else None
    return {
        "id": fila["id"],
        "medio_pago_id": fila["medio_pago_id"],
        "medio_pago_nombre": fila["medio_pago_nombre"],
        "es_cuenta_corriente": bool(fila["es_cuenta_corriente"]),
        "monto": entero_a_precio(fila["monto"]),
        "recibido": recibido,
        "vuelto": (recibido - entero_a_precio(fila["monto"])) if recibido is not None else None,
        "cheque_id": fila["cheque_id"],
    }


def calcular_total_lineas(venta_fila: sqlite3.Row, lineas: list[dict]) -> dict:
    """Total de un conjunto de lineas con los descuentos e IVA de ESA venta (el % del cliente
    que tenia al vender, el % sobre el total y el IVA). Lo usan la venta misma y sus notas de
    credito: asi una nota de credito por todo da exactamente el total de la venta.
    lineas: [{'cantidad' (x1000), 'precio_unitario' (x100), 'descuento_item_porcentaje' (x100|None)}]"""
    descuento_cliente = venta_fila["descuento_cliente_porcentaje"]
    return calcular_totales(
        lineas,
        entero_a_porcentaje(descuento_cliente) if descuento_cliente is not None else None,
        venta_fila["descuento_total_porcentaje"],
        venta_fila["iva_porcentaje"],
        bool(venta_fila["precios_con_iva"]),
    )


def total_nota_credito(nota_credito_id: int) -> Decimal:
    """Lo que efectivamente se reintegro (queda guardado en cada reintegro): es la plata que se
    movio, no un total recalculado -- asi nunca difiere por un centavo de redondeo."""
    return sum((entero_a_precio(r["monto"]) for r in ventas_repo.listar_reintegros(nota_credito_id)), Decimal("0"))


def obtener_venta(venta_id: int) -> dict | None:
    fila = ventas_repo.obtener_por_id(venta_id)
    if fila is None:
        return None
    items = [_item_a_dict(f) for f in ventas_repo.listar_items(venta_id)]
    devueltas = ventas_repo.cantidades_devueltas_por_item(venta_id)
    for item in items:
        item["cantidad_devuelta"] = entero_a_cantidad(devueltas.get(item["id"], 0))
    pagos = [_pago_a_dict(f) for f in ventas_repo.listar_pagos(venta_id)]
    cliente = clientes_service.obtener_cliente(fila["cliente_id"])
    descuento_total = (
        entero_a_porcentaje(fila["descuento_total_porcentaje"])
        if fila["descuento_total_porcentaje"] is not None else None
    )
    totales = calcular_total_lineas(
        fila,
        [
            {
                "cantidad": cantidad_a_entero(i["cantidad"]),
                "precio_unitario": precio_a_entero(i["precio_unitario"]),
                "descuento_item_porcentaje": (
                    porcentaje_a_entero(i["descuento_item_porcentaje"])
                    if i["descuento_item_porcentaje"] is not None else None
                ),
            }
            for i in items
        ],
    )
    notas_credito = [
        {
            "id": nc["id"], "numero": nc["numero"], "fecha": nc["fecha"], "motivo": nc["motivo"],
            "es_correccion": bool(nc["es_correccion"]), "total": total_nota_credito(nc["id"]),
        }
        for nc in ventas_repo.listar_notas_credito_de_venta(venta_id)
    ]
    total_acreditado = sum((nc["total"] for nc in notas_credito), Decimal("0"))
    return {
        "id": fila["id"],
        "numero": fila["numero"],
        "cliente_id": fila["cliente_id"],
        "cliente_nombre": cliente["razon_social"] if cliente else None,
        "lista_precio_id": fila["lista_precio_id"],
        "estado": fila["estado"],
        "fecha": fila["fecha"],
        "fecha_confirmacion": fila["fecha_confirmacion"],
        "iva_porcentaje": entero_a_porcentaje(fila["iva_porcentaje"]) if fila["iva_porcentaje"] else Decimal("0"),
        "precios_con_iva": bool(fila["precios_con_iva"]),
        "descuento_total_porcentaje": descuento_total,
        "observacion": fila["observacion"],
        "items": items,
        "pagos": pagos,
        "subtotal": totales["subtotal"],
        "neto": totales["neto"],
        "iva": totales["iva"],
        "total": totales["total"],
        "descuento_cliente_porcentaje": (
            entero_a_porcentaje(fila["descuento_cliente_porcentaje"])
            if fila["descuento_cliente_porcentaje"] is not None else None
        ),
        "notas_credito": notas_credito,
        "total_acreditado": total_acreditado,
        "total_neto": totales["total"] - total_acreditado,
        "queda_por_acreditar": any(i["cantidad"] > i["cantidad_devuelta"] for i in items),
    }


def obtener_venta_por_numero(numero: str) -> dict | None:
    fila = ventas_repo.obtener_por_numero(numero)
    return obtener_venta(fila["id"]) if fila is not None else None


def listar_ventas(estado: str | None = None, cliente_id: int | None = None) -> list[dict]:
    return [obtener_venta(f["id"]) for f in ventas_repo.listar(estado=estado, cliente_id=cliente_id)]


def listar_ventas_pagina(
    pagina: int, tamano_pagina: int, texto: str | None = None,
    estado: str | None = None, cliente_id: int | None = None,
) -> dict:
    """Version paginada de `listar_ventas` -- esa recalcula el detalle completo (items, pagos,
    totales) de TODAS las ventas de la historia en cada refresco, aunque la pantalla solo
    muestre numero/cliente/fecha/total de una pagina a la vez. Esta solo hace ese calculo caro
    para las ventas de la pagina pedida. Devuelve {'items': [...], 'total': N}."""
    filas, total = ventas_repo.listar_pagina(pagina, tamano_pagina, texto, estado, cliente_id)
    return {"items": [obtener_venta(f["id"]) for f in filas], "total": total}


def total_sin_iva(venta_fila: sqlite3.Row, lineas: list[dict]) -> Decimal:
    """Lo cobrado por esas lineas con TODOS los descuentos de la venta (linea, % del cliente,
    % sobre el total) pero sin IVA: el IVA no es plata del negocio, es del fisco. Es el NETO
    tanto si el IVA se sumo encima como si venia incluido en los precios."""
    return calcular_total_lineas(venta_fila, lineas)["neto"]


def detalle_ganancia_venta(venta: dict) -> dict:
    """Ganancia real de una venta, siempre calculada al momento (nunca se guarda):
      ingresos = lo cobrado sin IVA, con todos los descuentos, menos lo acreditado por notas de credito
      costo    = costo real de los lotes FIFO consumidos, menos el de lo que volvio al stock
    Lo que una nota de credito no devolvio al stock (roto, vencido) sigue en el costo: es perdida."""
    venta_fila = ventas_repo.obtener_por_id(venta["id"])
    lineas_venta = [dict(f) for f in ventas_repo.listar_items(venta["id"])]
    ingresos = total_sin_iva(venta_fila, lineas_venta)
    costo = sum(
        (l["cantidad"] * l["costo_unitario"] for item in venta["items"] for l in item["lotes"]), Decimal("0"),
    )
    for nc in venta["notas_credito"]:
        lineas_nc = [dict(f) for f in ventas_repo.listar_items_nota_credito(nc["id"])]
        ingresos -= total_sin_iva(venta_fila, lineas_nc)
        for f in lineas_nc:
            for l in ventas_repo.listar_lotes_de_item_nota_credito(f["id"]):
                costo -= entero_a_cantidad(l["cantidad"]) * entero_a_precio(l["costo_unitario"])
    if venta["notas_credito"] and not venta["queda_por_acreditar"]:
        ingresos = Decimal("0")  # acreditada entera: sin centavos sueltos de redondeo
    costo = costo.quantize(Decimal("1.00"))
    return {"ingresos": ingresos, "costo": costo, "ganancia": ingresos - costo}


def calcular_ganancia_venta(venta: dict) -> Decimal:
    return detalle_ganancia_venta(venta)["ganancia"]
