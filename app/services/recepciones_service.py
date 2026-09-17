import sqlite3
from datetime import datetime
from decimal import Decimal

from app.repositories import ordenes_compra_repo, productos_repo, recepciones_repo
from app.services import log_service
from app.services.exceptions import (
    CodigoDuplicadoError,
    LineasVaciasError,
    OrdenCompraCanceladaError,
    OrdenCompraNoEncontradaError,
    ProductoInactivoError,
    ProductoNoEncontradoError,
)
from app.shared.money import cantidad_a_entero, entero_a_cantidad, entero_a_precio, precio_a_entero


def validar_items_recepcion(items: list[dict]) -> list[dict]:
    """Reutilizada tanto por confirmar_recepcion como por la creacion rapida de OC. Cada item de
    entrada: {'orden_compra_item_id': int|None, 'producto_id': int|None,
    'producto_nuevo': {'codigo': str, 'nombre': str, 'categoria_id': int|None}|None,
    'descripcion_libre': str|None, 'cantidad_recibida': Decimal, 'costo_unitario': Decimal}.
    Exactamente uno de producto_id/producto_nuevo/descripcion_libre debe venir cargado."""
    if not items:
        raise LineasVaciasError("La recepcion debe tener al menos una linea")

    items_validados = []
    for item in items:
        producto_id = item.get("producto_id")
        producto_nuevo = item.get("producto_nuevo")
        descripcion_libre = (item.get("descripcion_libre") or "").strip() or None

        cargados = sum(x is not None for x in (producto_id, producto_nuevo, descripcion_libre))
        if cargados != 1:
            raise ValueError("Cada linea debe tener producto_id, producto_nuevo o descripcion_libre (una sola opcion)")

        if item["cantidad_recibida"] <= 0:
            raise ValueError("La cantidad recibida debe ser mayor a cero")
        if item["costo_unitario"] < 0:
            raise ValueError("El costo unitario no puede ser negativo")

        if producto_id is not None:
            producto = productos_repo.obtener_por_id(producto_id)
            if producto is None:
                raise ProductoNoEncontradoError(f"No existe el producto {producto_id}")
            if not producto["activo"]:
                raise ProductoInactivoError(f"El producto '{producto['nombre']}' esta inactivo")
        elif producto_nuevo is not None:
            codigo = (producto_nuevo.get("codigo") or "").strip()
            nombre = (producto_nuevo.get("nombre") or "").strip()
            if not codigo or not nombre:
                raise ValueError("Los productos nuevos requieren codigo y nombre")
            if productos_repo.obtener_por_codigo(codigo) is not None:
                raise CodigoDuplicadoError(f"Ya existe un producto con el codigo '{codigo}'")
            producto_nuevo = {"codigo": codigo, "nombre": nombre, "categoria_id": producto_nuevo.get("categoria_id")}

        items_validados.append({
            "orden_compra_item_id": item.get("orden_compra_item_id"),
            "producto_id": producto_id,
            "producto_nuevo": producto_nuevo,
            "descripcion_libre": descripcion_libre,
            "cantidad_recibida": cantidad_a_entero(item["cantidad_recibida"]),
            "costo_unitario": precio_a_entero(item["costo_unitario"]),
        })
    return items_validados


def calcular_monto_total_entero(items_validados: list[dict]) -> int:
    """Suma cantidad*costo de todas las lineas (incluidos items libres, como flete) usando
    aritmetica Decimal -- nunca multiplicando directamente dos columnas enteras de escalas
    distintas. Sirve para el monto del cargo en Cuentas Corrientes cuando la recepcion es a credito."""
    total = sum(
        (entero_a_cantidad(i["cantidad_recibida"]) * entero_a_precio(i["costo_unitario"]) for i in items_validados),
        Decimal("0"),
    )
    return precio_a_entero(total)


def confirmar_recepcion(
    orden_compra_id: int,
    items: list[dict],
    fecha: str | None = None,
    numero_remito: str | None = None,
    observacion: str | None = None,
    a_credito: bool = False,
) -> dict:
    oc = ordenes_compra_repo.obtener_por_id(orden_compra_id)
    if oc is None:
        raise OrdenCompraNoEncontradaError(f"No existe la orden de compra {orden_compra_id}")
    if oc["estado"] == "cancelada":
        raise OrdenCompraCanceladaError(f"La orden de compra {oc['numero']} esta cancelada")

    items_validados = validar_items_recepcion(items)
    monto_a_credito = calcular_monto_total_entero(items_validados) if a_credito else None

    resultado = recepciones_repo.confirmar_recepcion(
        orden_compra_id=orden_compra_id,
        fecha=fecha or datetime.now().isoformat(),
        numero_remito=(numero_remito or "").strip() or None,
        observacion=(observacion or "").strip() or None,
        items=items_validados,
        monto_a_credito=monto_a_credito,
    )

    log_service.registrar(
        "orden_compra", resultado["orden_compra_id"],
        f"Se registro una recepcion en {oc['numero']} (nuevo estado: {resultado['estado_orden_compra']})",
    )
    cantidades_por_producto: dict[int, Decimal] = {}
    for item in items_validados:
        if item["producto_id"] is None:
            continue
        cantidad = entero_a_cantidad(item["cantidad_recibida"])
        cantidades_por_producto[item["producto_id"]] = cantidades_por_producto.get(item["producto_id"], Decimal("0")) + cantidad
    log_service.registrar_resumen_stock(
        "orden_compra", resultado["orden_compra_id"], oc["numero"], "ingreso", cantidades_por_producto,
    )
    if resultado.get("cargo_id") is not None:
        log_service.registrar(
            "proveedor", oc["proveedor_id"],
            f"Se genero un cargo en cuenta corriente por la recepcion a credito de {oc['numero']}",
        )
    for producto_id in resultado["productos_creados"]:
        producto = productos_repo.obtener_por_id(producto_id)
        log_service.registrar(
            "producto", producto_id,
            f"Se creo el producto '{producto['codigo']} - {producto['nombre']}' automaticamente al recibir "
            f"la orden de compra {oc['numero']} (categoria/unidad placeholder si no se eligio una -- completar a mano)",
        )
    return obtener_recepcion(resultado["recepcion_id"])


def _item_a_dict(fila: sqlite3.Row) -> dict:
    cantidad = entero_a_cantidad(fila["cantidad_recibida"])
    costo = entero_a_precio(fila["costo_unitario"])
    return {
        "id": fila["id"],
        "orden_compra_item_id": fila["orden_compra_item_id"],
        "producto_id": fila["producto_id"],
        "producto_codigo": fila["producto_codigo"],
        "producto_nombre": fila["producto_nombre"],
        "descripcion_libre": fila["descripcion_libre"],
        "cantidad_recibida": cantidad,
        "costo_unitario": costo,
        "subtotal": cantidad * costo,
        "lote_id": fila["lote_id"],
    }


def _recepcion_a_dict(fila: sqlite3.Row) -> dict:
    return {
        "id": fila["id"],
        "orden_compra_id": fila["orden_compra_id"],
        "fecha": fila["fecha"],
        "numero_remito": fila["numero_remito"],
        "observacion": fila["observacion"],
    }


def obtener_recepcion(recepcion_id: int) -> dict | None:
    fila = recepciones_repo.obtener_por_id(recepcion_id)
    if fila is None:
        return None
    recepcion = _recepcion_a_dict(fila)
    recepcion["items"] = [_item_a_dict(f) for f in recepciones_repo.listar_items(recepcion_id)]
    return recepcion


def listar_recepciones_de_orden(orden_compra_id: int) -> list[dict]:
    return [_recepcion_a_dict(f) for f in recepciones_repo.listar_por_orden(orden_compra_id)]


def listar_items_recepcion(recepcion_id: int) -> list[dict]:
    return [_item_a_dict(f) for f in recepciones_repo.listar_items(recepcion_id)]
