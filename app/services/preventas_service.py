"""Pre-ventas: carritos a medio armar guardados con un nombre para retomarlos mas tarde. No son
ventas: no descuentan ni reservan stock, no mueven plata. Las de dias anteriores dejan de
listarse y se borran solas a la semana."""

import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.repositories import borradores_repo, productos_repo
from app.services import clientes_service, listas_precios_service, log_service, negocio_service, ventas_service
from app.services.exceptions import LineasVaciasError, PreventaNoDisponibleError, ProductoNoEncontradoError
from app.shared.money import (
    cantidad_a_entero,
    entero_a_cantidad,
    entero_a_porcentaje,
    entero_a_precio,
    formatear_cantidad,
    formatear_precio,
    porcentaje_a_entero,
    precio_a_entero,
)

TIPO = "preventa"
DIAS_HASTA_BORRAR = 7


def _hoy_iso() -> str:
    return date.today().isoformat()


def _texto_o_none(valor: str | None) -> str | None:
    return (valor or "").strip() or None


def nombre_sugerido(cliente_id: int | None, cliente_nombre_nuevo: str | None, usar_generico: bool) -> str:
    """El del cliente si hay uno elegido; si no 'Pre-venta N' (N = las de hoy + 1)."""
    if not usar_generico and cliente_id is not None:
        cliente = clientes_service.obtener_cliente(cliente_id)
        if cliente is not None:
            return cliente["razon_social"]
    if not usar_generico and _texto_o_none(cliente_nombre_nuevo):
        return cliente_nombre_nuevo.strip()
    return f"Pre-venta {borradores_repo.contar_creados_desde(TIPO, _hoy_iso()) + 1}"


def validar_items_borrador(items: list[dict]) -> list[dict]:
    """items: [{'producto_id', 'descripcion_libre', 'cantidad' (Decimal), 'precio_unitario' (Decimal,
    solo items libres), 'descuento_item_porcentaje' (Decimal|None)}]. No valida stock: una
    pre-venta no lo reserva (se controla al retomarla y al cobrar)."""
    if not items:
        raise LineasVaciasError("La pre-venta no tiene productos: agrega al menos uno antes de guardarla")
    validados = []
    for item in items:
        cantidad = item.get("cantidad") or Decimal("0")
        if cantidad <= 0:
            raise ValueError("Cada linea tiene que tener una cantidad mayor a cero")
        descuento = item.get("descuento_item_porcentaje")
        if descuento is not None and descuento < 0:
            raise ValueError("El descuento de una linea no puede ser negativo")
        producto_id = item.get("producto_id")
        if producto_id is not None:
            if productos_repo.obtener_por_id(producto_id) is None:
                raise ProductoNoEncontradoError(f"No existe el producto {producto_id}")
            precio = None
            descripcion = None
        else:
            descripcion = _texto_o_none(item.get("descripcion_libre"))
            if descripcion is None:
                raise ValueError("Los items libres necesitan una descripcion")
            precio_decimal = item.get("precio_unitario") or Decimal("0")
            if precio_decimal < 0:
                raise ValueError(f"El precio de '{descripcion}' no puede ser negativo")
            precio = precio_a_entero(precio_decimal)
        validados.append({
            "producto_id": producto_id, "descripcion_libre": descripcion,
            "cantidad": cantidad_a_entero(cantidad), "precio_unitario": precio,
            "descuento_item_porcentaje": porcentaje_a_entero(descuento) if descuento else None,
        })
    return validados


def guardar_preventa(
    preventa_id: int | None,
    nombre: str | None,
    items: list[dict],
    cliente_id: int | None = None,
    cliente_nombre_nuevo: str | None = None,
    usar_cliente_generico: bool = True,
    lista_precio_id: int | None = None,
    descuento_total_porcentaje: Decimal | None = None,
    observacion: str | None = None,
) -> dict:
    """preventa_id None = nueva; si no, actualiza esa misma (la pestaña venia de una pre-venta).
    Nombre vacio = el sugerido (o el que ya tenia, si se esta actualizando)."""
    existente = None
    if preventa_id is not None:
        existente = borradores_repo.obtener(preventa_id)
        if existente is None or existente["tipo"] != TIPO:
            raise PreventaNoDisponibleError(f"No existe la pre-venta {preventa_id}")
        if existente["estado"] != "abierta":
            raise PreventaNoDisponibleError(f"La pre-venta '{existente['nombre']}' ya fue {existente['estado']}")
    if descuento_total_porcentaje is not None and descuento_total_porcentaje < 0:
        raise ValueError("El descuento sobre el total no puede ser negativo")
    items_validados = validar_items_borrador(items)

    nombre = _texto_o_none(nombre)
    if nombre is None:
        nombre = existente["nombre"] if existente else nombre_sugerido(cliente_id, cliente_nombre_nuevo, usar_cliente_generico)
    datos = {
        "nombre": nombre,
        "cliente_id": None if usar_cliente_generico else cliente_id,
        "cliente_nombre_nuevo": None if usar_cliente_generico or cliente_id else _texto_o_none(cliente_nombre_nuevo),
        "usar_cliente_generico": int(usar_cliente_generico),
        "lista_precio_id": lista_precio_id,
        # Una pre-venta no congela el IVA: se cobra con la configuracion del dia en que se cobra.
        "iva_porcentaje": None,
        "precios_con_iva": 0,
        "descuento_total_porcentaje": (
            porcentaje_a_entero(descuento_total_porcentaje) if descuento_total_porcentaje is not None else None
        ),
        "observacion": _texto_o_none(observacion),
        "fecha_validez": None,
        "descuento_cliente_porcentaje": None,
    }
    nuevo_id = borradores_repo.guardar(TIPO, preventa_id, datos, items_validados)
    accion = "actualizo" if existente else "guardo"
    log_service.registrar("preventa", nuevo_id, f"Se {accion} la pre-venta '{nombre}' ({len(items_validados)} lineas)")
    return obtener_preventa(nuevo_id)


def _precio_hoy(producto: sqlite3.Row, lista_precio_id: int | None) -> Decimal:
    if lista_precio_id is not None:
        return listas_precios_service.calcular_precio_producto(producto["id"], lista_precio_id)
    return entero_a_precio(producto["precio_venta"])


def _a_dict(fila: sqlite3.Row) -> dict:
    """La pre-venta lista para la caja: lineas con los precios de HOY (los items libres con el
    suyo), total aproximado, y avisos si ya no alcanza el stock."""
    items, lineas_para_total, avisos = [], [], []
    for f in borradores_repo.listar_items(fila["id"]):
        cantidad = entero_a_cantidad(f["cantidad"])
        descuento = entero_a_porcentaje(f["descuento_item_porcentaje"]) if f["descuento_item_porcentaje"] is not None else None
        if f["producto_id"] is not None:
            producto = productos_repo.obtener_por_id(f["producto_id"])
            precio = _precio_hoy(producto, fila["lista_precio_id"])
            stock = entero_a_cantidad(producto["stock_actual"])
            if cantidad > stock:
                avisos.append(
                    f"De {producto['nombre']} quedan {formatear_cantidad(stock)} y la pre-venta tenia {formatear_cantidad(cantidad)}"
                )
            if not producto["activo"]:
                avisos.append(f"{producto['nombre']} esta inactivo")
        else:
            precio = entero_a_precio(f["precio_unitario"] or 0)
        items.append({
            "producto_id": f["producto_id"], "producto_codigo": f["producto_codigo"], "producto_nombre": f["producto_nombre"],
            "descripcion_libre": f["descripcion_libre"], "cantidad": cantidad, "precio_unitario": precio,
            "descuento_item_porcentaje": descuento,
        })
        lineas_para_total.append({
            "cantidad": f["cantidad"], "precio_unitario": precio_a_entero(precio),
            "descuento_item_porcentaje": f["descuento_item_porcentaje"],
        })

    cliente = clientes_service.obtener_cliente(fila["cliente_id"]) if fila["cliente_id"] else None
    config = negocio_service.config_iva()
    total = ventas_service.calcular_totales(
        lineas_para_total,
        cliente["porcentaje_descuento"] if cliente else None,
        fila["descuento_total_porcentaje"],
        config["alicuota_entero"],
        config["precios_con_iva"],
    )["total"]
    if fila["usar_cliente_generico"]:
        cliente_nombre = clientes_service.NOMBRE_CLIENTE_GENERICO
    else:
        cliente_nombre = cliente["razon_social"] if cliente else (fila["cliente_nombre_nuevo"] or "-")
    return {
        "id": fila["id"], "nombre": fila["nombre"], "estado": fila["estado"],
        "cliente_id": fila["cliente_id"], "cliente_nombre_nuevo": fila["cliente_nombre_nuevo"],
        "usar_cliente_generico": bool(fila["usar_cliente_generico"]), "cliente_nombre": cliente_nombre,
        "lista_precio_id": fila["lista_precio_id"],
        "descuento_total_porcentaje": (
            entero_a_porcentaje(fila["descuento_total_porcentaje"]) if fila["descuento_total_porcentaje"] is not None else None
        ),
        "observacion": fila["observacion"], "fecha_creacion": fila["fecha_creacion"],
        "fecha_actualizacion": fila["fecha_actualizacion"], "venta_id": fila["venta_id"],
        "items": items, "total_aproximado": total, "avisos": avisos,
    }


def obtener_preventa(preventa_id: int) -> dict | None:
    fila = borradores_repo.obtener(preventa_id)
    if fila is None or fila["tipo"] != TIPO:
        return None
    return _a_dict(fila)


def purgar_viejas() -> int:
    """Borra las pre-ventas de hace mas de una semana (cualquier estado)."""
    limite = (date.today() - timedelta(days=DIAS_HASTA_BORRAR)).isoformat()
    borradas = borradores_repo.purgar(TIPO, limite)
    if borradas:
        log_service.registrar("preventa", None, f"Se borraron {borradas} pre-ventas de hace mas de {DIAS_HASTA_BORRAR} dias")
    return borradas


def listar_preventas_del_dia() -> list[dict]:
    """Las abiertas de hoy (las de dias anteriores ya vencieron). Aprovecha para borrar las viejas."""
    purgar_viejas()
    return [_a_dict(f) for f in borradores_repo.listar(TIPO, "abierta", _hoy_iso())]


def _exigir_abierta(preventa_id: int) -> sqlite3.Row:
    fila = borradores_repo.obtener(preventa_id)
    if fila is None or fila["tipo"] != TIPO:
        raise PreventaNoDisponibleError(f"No existe la pre-venta {preventa_id}")
    if fila["estado"] != "abierta":
        raise PreventaNoDisponibleError(f"La pre-venta '{fila['nombre']}' ya fue {fila['estado']}")
    return fila


def descartar_preventa(preventa_id: int, motivo: str | None = None) -> None:
    fila = _exigir_abierta(preventa_id)
    motivo = _texto_o_none(motivo)
    borradores_repo.descartar(preventa_id, motivo)
    log_service.registrar(
        "preventa", preventa_id, f"Se descarto la pre-venta '{fila['nombre']}'" + (f": {motivo}" if motivo else ""),
    )


def hora(fecha_iso: str) -> str:
    return datetime.fromisoformat(fecha_iso).strftime("%H:%M")


def resumen_lineas(preventa: dict) -> str:
    return f"{len(preventa['items'])} producto{'' if len(preventa['items']) == 1 else 's'} · aprox. {formatear_precio(preventa['total_aproximado'])}"
