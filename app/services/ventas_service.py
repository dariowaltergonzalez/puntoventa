import sqlite3
from datetime import datetime
from decimal import Decimal

from app.repositories import productos_repo, ventas_repo
from app.services import clientes_service, listas_precios_service, log_service, medios_pago_service
from app.services.exceptions import (
    ClienteNoEncontradoError,
    LineasVaciasError,
    ListaPrecioNoEncontradaError,
    MedioPagoNoEncontradoError,
    MontoPagoInvalidoError,
    ProductoInactivoError,
    ProductoNoEncontradoError,
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


def _validar_items(items_entrada: list[dict], lista_precio_id: int | None) -> list[dict]:
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

            if lista_precio_id is not None:
                precio_unitario = listas_precios_service.calcular_precio_producto(producto_id, lista_precio_id)
            else:
                precio_unitario = entero_a_precio(producto["precio_venta"])

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
    iva_porcentaje: int | None,
) -> dict:
    """Aplica las 3 capas de descuento, todas acumulables (nunca se pisan): precio ya resuelto por
    item (con la lista de precios adentro) menos el descuento manual de esa linea si lo tiene ->
    subtotal -> % fijo del cliente -> % manual sobre el total -> IVA si corresponde."""
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

    total = con_descuento_total
    if iva_porcentaje is not None:
        total = con_descuento_total * (Decimal("1") + Decimal(iva_porcentaje) / Decimal("100"))

    return {
        "subtotal": subtotal.quantize(Decimal("1.00")),
        "total": total.quantize(Decimal("1.00")),
    }


def _validar_pagos(pagos_entrada: list[dict], total_venta: Decimal) -> list[dict]:
    """pago de entrada: {'medio_pago_id': int, 'monto': Decimal, 'recibido': Decimal|None}.
    'recibido' es lo que el cliente entrego fisicamente (solo tiene sentido en efectivo, para
    poder consultar despues con que billete pago y de donde salio el vuelto) -- opcional,
    None para medios sin vuelto."""
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
        suma += monto
        pagos_validados.append({
            "medio_pago_id": medio_pago_id,
            "monto": precio_a_entero(monto),
            "recibido": precio_a_entero(recibido) if recibido is not None else None,
            "es_cuenta_corriente": medio["es_cuenta_corriente"],
        })
    if suma != total_venta:
        raise MontoPagoInvalidoError(
            f"La suma de los medios de pago ({formatear_precio(suma)}) no coincide con el total "
            f"de la venta ({formatear_precio(total_venta)})"
        )
    return pagos_validados


def previsualizar_totales(
    items: list[dict],
    lista_precio_id: int | None = None,
    cliente_id: int | None = None,
    descuento_total_porcentaje: Decimal | None = None,
    iva_porcentaje: Decimal | None = None,
) -> dict:
    """Valida y calcula subtotal/total sin persistir nada -- para mostrar en vivo en la UI
    mientras se arma la venta, reutilizando exactamente la misma logica que crear_venta usa al
    confirmar (evita que la previsualizacion y el resultado final puedan llegar a diferir)."""
    items_validados = _validar_items(items, lista_precio_id)
    cliente_descuento = None
    if cliente_id is not None:
        cliente = clientes_service.obtener_cliente(cliente_id)
        cliente_descuento = cliente["porcentaje_descuento"] if cliente else None
    descuento_total_entero = (
        porcentaje_a_entero(descuento_total_porcentaje) if descuento_total_porcentaje is not None else None
    )
    return calcular_totales(
        items_validados, cliente_descuento, descuento_total_entero,
        int(iva_porcentaje) if iva_porcentaje is not None else None,
    )


def crear_venta(
    items: list[dict],
    pagos: list[dict],
    cliente_id: int | None = None,
    cliente_nombre_nuevo: str | None = None,
    usar_cliente_generico: bool = False,
    lista_precio_id: int | None = None,
    iva_porcentaje: Decimal | None = None,
    descuento_total_porcentaje: Decimal | None = None,
    fecha: str | None = None,
    observacion: str | None = None,
) -> dict:
    """Camino unico y normal de Fase 4: la venta nace directamente confirmada (descuenta stock,
    registra los pagos, genera cargo en Cuentas Corrientes si corresponde), todo en un commit."""
    cliente = _resolver_cliente(cliente_id, cliente_nombre_nuevo, usar_cliente_generico)

    if lista_precio_id is not None and listas_precios_service.obtener_lista(lista_precio_id) is None:
        raise ListaPrecioNoEncontradaError(f"No existe la lista de precios {lista_precio_id}")

    if descuento_total_porcentaje is not None and descuento_total_porcentaje < 0:
        raise ValueError("El descuento sobre el total no puede ser negativo")
    descuento_total_entero = (
        porcentaje_a_entero(descuento_total_porcentaje) if descuento_total_porcentaje is not None else None
    )

    items_validados = _validar_items(items, lista_precio_id)
    totales = calcular_totales(
        items_validados, cliente["porcentaje_descuento"], descuento_total_entero,
        int(iva_porcentaje) if iva_porcentaje is not None else None,
    )
    pagos_validados = _validar_pagos(pagos, totales["total"])

    resultado = ventas_repo.crear_venta_confirmada(
        cliente_id=cliente["id"],
        lista_precio_id=lista_precio_id,
        fecha=fecha or datetime.now().isoformat(),
        iva_porcentaje=int(iva_porcentaje) if iva_porcentaje is not None else None,
        descuento_total_porcentaje=descuento_total_entero,
        observacion=(observacion or "").strip() or None,
        items=items_validados,
        pagos=pagos_validados,
    )

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
    }


def obtener_venta(venta_id: int) -> dict | None:
    fila = ventas_repo.obtener_por_id(venta_id)
    if fila is None:
        return None
    items = [_item_a_dict(f) for f in ventas_repo.listar_items(venta_id)]
    pagos = [_pago_a_dict(f) for f in ventas_repo.listar_pagos(venta_id)]
    cliente = clientes_service.obtener_cliente(fila["cliente_id"])
    descuento_total = (
        entero_a_porcentaje(fila["descuento_total_porcentaje"])
        if fila["descuento_total_porcentaje"] is not None else None
    )
    totales = calcular_totales(
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
        cliente["porcentaje_descuento"] if cliente else None,
        fila["descuento_total_porcentaje"],
        fila["iva_porcentaje"],
    )
    return {
        "id": fila["id"],
        "numero": fila["numero"],
        "cliente_id": fila["cliente_id"],
        "cliente_nombre": cliente["razon_social"] if cliente else None,
        "lista_precio_id": fila["lista_precio_id"],
        "estado": fila["estado"],
        "fecha": fila["fecha"],
        "fecha_confirmacion": fila["fecha_confirmacion"],
        "iva_porcentaje": fila["iva_porcentaje"],
        "descuento_total_porcentaje": descuento_total,
        "observacion": fila["observacion"],
        "items": items,
        "pagos": pagos,
        "subtotal": totales["subtotal"],
        "total": totales["total"],
    }


def obtener_venta_por_numero(numero: str) -> dict | None:
    fila = ventas_repo.obtener_por_numero(numero)
    return obtener_venta(fila["id"]) if fila is not None else None


def listar_ventas(estado: str | None = None, cliente_id: int | None = None) -> list[dict]:
    return [obtener_venta(f["id"]) for f in ventas_repo.listar(estado=estado, cliente_id=cliente_id)]


def calcular_ganancia_venta(venta: dict) -> Decimal:
    """Ganancia real: precio de venta (ya con descuentos aplicados a nivel linea) menos el costo
    real de los lotes efectivamente consumidos. Se calcula siempre al momento, nunca se guarda."""
    ganancia = Decimal("0")
    for item in venta["items"]:
        precio_neto = item["cantidad"] * item["precio_unitario"]
        if item["descuento_item_porcentaje"] is not None:
            precio_neto = precio_neto * (Decimal("1") - item["descuento_item_porcentaje"] / Decimal("100"))
        costo_lotes = sum((l["cantidad"] * l["costo_unitario"] for l in item["lotes"]), Decimal("0"))
        ganancia += precio_neto - costo_lotes
    return ganancia.quantize(Decimal("1.00"))
