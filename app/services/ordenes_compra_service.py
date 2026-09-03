import sqlite3
from datetime import datetime
from decimal import Decimal

from app.repositories import ordenes_compra_repo, productos_repo, recepciones_repo
from app.services import log_service, proveedores_service, recepciones_service
from app.services.exceptions import (
    CodigoDuplicadoError,
    LineasVaciasError,
    OrdenCompraCanceladaError,
    OrdenCompraNoEditableError,
    OrdenCompraNoEncontradaError,
    ProductoInactivoError,
    ProductoNoEncontradoError,
    ProveedorNoEncontradoError,
)
from app.shared.money import cantidad_a_entero, entero_a_cantidad, entero_a_precio, precio_a_entero


def _resolver_proveedor(
    proveedor_id: int | None, proveedor_nombre_nuevo: str | None, usar_generico: bool = False
) -> dict:
    if usar_generico:
        return proveedores_service.obtener_o_crear_proveedor_generico()
    if proveedor_id is not None:
        proveedor = proveedores_service.obtener_proveedor(proveedor_id)
        if proveedor is None:
            raise ProveedorNoEncontradoError(f"No existe el proveedor {proveedor_id}")
        return proveedor
    nombre = (proveedor_nombre_nuevo or "").strip()
    if not nombre:
        raise ValueError("Debe indicarse un proveedor")
    return proveedores_service.obtener_o_crear_proveedor_por_nombre(nombre)


def _validar_items(items: list[dict], permitir_producto_nuevo: bool = False) -> list[dict]:
    """items de la OC (lo pedido): {'producto_id': int|None, 'producto_nuevo': dict|None,
    'descripcion_libre': str|None, 'cantidad_pedida': Decimal, 'costo_pactado': Decimal}.
    Exactamente uno de producto_id/producto_nuevo/descripcion_libre.

    'producto_nuevo' solo se permite cuando la orden se recibe en el acto (permitir_producto_nuevo=True):
    en una OC comun (pendiente, sin recibir) no tiene sentido dar de alta un producto que todavia no llego."""
    if not items:
        raise LineasVaciasError("La orden de compra debe tener al menos una linea")

    items_validados = []
    for item in items:
        producto_id = item.get("producto_id")
        producto_nuevo = item.get("producto_nuevo")
        descripcion_libre = (item.get("descripcion_libre") or "").strip() or None

        cargados = sum(x is not None for x in (producto_id, producto_nuevo, descripcion_libre))
        if cargados != 1:
            raise ValueError("Cada linea debe tener producto_id, producto_nuevo o descripcion_libre (una sola opcion)")

        if producto_nuevo is not None and not permitir_producto_nuevo:
            raise ValueError(
                "Solo se puede dar de alta un producto nuevo si la orden se recibe en el acto "
                "('ya la tenes en mano'). Marca esa opcion, o usa un producto existente o item libre."
            )

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

        if item["cantidad_pedida"] <= 0:
            raise ValueError("La cantidad pedida debe ser mayor a cero")
        if item["costo_pactado"] < 0:
            raise ValueError("El costo pactado no puede ser negativo")

        items_validados.append({
            "producto_id": producto_id,
            "producto_nuevo": producto_nuevo,
            "descripcion_libre": descripcion_libre,
            "cantidad_pedida": cantidad_a_entero(item["cantidad_pedida"]),
            "costo_pactado": precio_a_entero(item["costo_pactado"]),
        })
    return items_validados


def crear_orden_compra(
    items: list[dict],
    proveedor_id: int | None = None,
    proveedor_nombre_nuevo: str | None = None,
    usar_proveedor_generico: bool = False,
    fecha_estimada: str | None = None,
    iva_porcentaje: Decimal | None = None,
    observacion: str | None = None,
) -> dict:
    proveedor = _resolver_proveedor(proveedor_id, proveedor_nombre_nuevo, usar_proveedor_generico)
    items_validados = _validar_items(items)

    resultado = ordenes_compra_repo.crear(
        proveedor_id=proveedor["id"],
        fecha_creacion=datetime.now().isoformat(),
        fecha_estimada=fecha_estimada,
        iva_porcentaje=int(iva_porcentaje) if iva_porcentaje is not None else None,
        observacion=(observacion or "").strip() or None,
        items=items_validados,
    )
    log_service.registrar(
        "orden_compra", resultado["id"],
        f"Se creo la orden de compra {resultado['numero']} a '{proveedor['nombre']}' ({len(items_validados)} linea(s))",
    )
    return obtener_orden_compra(resultado["id"])


def crear_orden_compra_recibida(
    items: list[dict],
    recepcion_items: list[dict],
    proveedor_id: int | None = None,
    proveedor_nombre_nuevo: str | None = None,
    usar_proveedor_generico: bool = False,
    fecha_estimada: str | None = None,
    iva_porcentaje: Decimal | None = None,
    observacion: str | None = None,
    recepcion_fecha: str | None = None,
    recepcion_numero_remito: str | None = None,
    recepcion_observacion: str | None = None,
) -> dict:
    """Checkbox '¿ya la tenes en mano?'. Misma validacion que crear_orden_compra +
    confirmar_recepcion, pero la persistencia va toda en un solo commit."""
    proveedor = _resolver_proveedor(proveedor_id, proveedor_nombre_nuevo, usar_proveedor_generico)
    items_validados = _validar_items(items, permitir_producto_nuevo=True)
    items_recepcion_validados = recepciones_service.validar_items_recepcion(recepcion_items)

    resultado = ordenes_compra_repo.crear_con_recepcion_inmediata(
        proveedor_id=proveedor["id"],
        fecha_creacion=datetime.now().isoformat(),
        fecha_estimada=fecha_estimada,
        iva_porcentaje=int(iva_porcentaje) if iva_porcentaje is not None else None,
        observacion=(observacion or "").strip() or None,
        items=items_validados,
        recepcion_fecha=recepcion_fecha or datetime.now().isoformat(),
        recepcion_numero_remito=(recepcion_numero_remito or "").strip() or None,
        recepcion_observacion=(recepcion_observacion or "").strip() or None,
        items_recepcion=items_recepcion_validados,
    )
    log_service.registrar(
        "orden_compra", resultado["orden_compra_id"],
        f"Se creo la orden de compra {resultado['numero']} a '{proveedor['nombre']}' y se recibio en el acto "
        f"(estado: {resultado['estado_orden_compra']})",
    )
    for producto_id in resultado["productos_creados"]:
        producto = productos_repo.obtener_por_id(producto_id)
        log_service.registrar(
            "producto", producto_id,
            f"Se creo el producto '{producto['codigo']} - {producto['nombre']}' automaticamente al recibir "
            f"la orden de compra {resultado['numero']}",
        )
    return obtener_orden_compra(resultado["orden_compra_id"])


def actualizar_orden_compra(
    orden_compra_id: int,
    items: list[dict],
    proveedor_id: int | None = None,
    proveedor_nombre_nuevo: str | None = None,
    usar_proveedor_generico: bool = False,
    fecha_estimada: str | None = None,
    iva_porcentaje: Decimal | None = None,
    observacion: str | None = None,
) -> dict:
    oc = ordenes_compra_repo.obtener_por_id(orden_compra_id)
    if oc is None:
        raise OrdenCompraNoEncontradaError(f"No existe la orden de compra {orden_compra_id}")
    if oc["estado"] != "pendiente" or ordenes_compra_repo.tiene_recepciones(orden_compra_id):
        raise OrdenCompraNoEditableError(
            f"La orden de compra {oc['numero']} ya no se puede editar (tiene recepciones o no esta pendiente)"
        )
    proveedor = _resolver_proveedor(proveedor_id, proveedor_nombre_nuevo, usar_proveedor_generico)
    items_validados = _validar_items(items)
    ordenes_compra_repo.actualizar_cabecera_y_items(
        orden_compra_id, proveedor["id"], fecha_estimada,
        int(iva_porcentaje) if iva_porcentaje is not None else None,
        (observacion or "").strip() or None, items_validados,
    )
    log_service.registrar("orden_compra", orden_compra_id, f"Se edito la orden de compra {oc['numero']}")
    return obtener_orden_compra(orden_compra_id)


def cancelar_orden_compra(orden_compra_id: int, motivo: str) -> dict:
    oc = ordenes_compra_repo.obtener_por_id(orden_compra_id)
    if oc is None:
        raise OrdenCompraNoEncontradaError(f"No existe la orden de compra {orden_compra_id}")
    if oc["estado"] == "cancelada":
        raise OrdenCompraCanceladaError(f"La orden de compra {oc['numero']} ya esta cancelada")
    motivo = motivo.strip()
    if not motivo:
        raise ValueError("Debe indicarse un motivo de cancelacion")
    observacion_final = f"{oc['observacion']}\n[Cancelada] {motivo}" if oc["observacion"] else f"[Cancelada] {motivo}"
    ordenes_compra_repo.cancelar(orden_compra_id, observacion_final)
    log_service.registrar("orden_compra", orden_compra_id, f"Se cancelo la orden de compra {oc['numero']}: {motivo}")
    return obtener_orden_compra(orden_compra_id)


def marcar_recibida_manualmente(orden_compra_id: int, motivo: str) -> dict:
    oc = ordenes_compra_repo.obtener_por_id(orden_compra_id)
    if oc is None:
        raise OrdenCompraNoEncontradaError(f"No existe la orden de compra {orden_compra_id}")
    if oc["estado"] != "recibida_parcial":
        raise ValueError("Solo se puede cerrar manualmente una orden en estado 'recibida parcial'")
    motivo = motivo.strip()
    if not motivo:
        raise ValueError("Debe indicarse un motivo del cierre manual")
    observacion_final = f"{oc['observacion']}\n[Cierre manual] {motivo}" if oc["observacion"] else f"[Cierre manual] {motivo}"
    ordenes_compra_repo.marcar_recibida_manualmente(orden_compra_id, observacion_final)
    log_service.registrar("orden_compra", orden_compra_id, f"Se cerro manualmente {oc['numero']}: {motivo}")
    return obtener_orden_compra(orden_compra_id)


def _item_a_dict(fila: sqlite3.Row) -> dict:
    return {
        "id": fila["id"],
        "orden_compra_id": fila["orden_compra_id"],
        "producto_id": fila["producto_id"],
        "producto_codigo": fila["producto_codigo"],
        "producto_nombre": fila["producto_nombre"],
        "descripcion_libre": fila["descripcion_libre"],
        "cantidad_pedida": entero_a_cantidad(fila["cantidad_pedida"]),
        "costo_pactado": entero_a_precio(fila["costo_pactado"]),
        "cantidad_recibida": entero_a_cantidad(fila["cantidad_recibida"]),
    }


def _costos_reales_por_item(orden_compra_id: int) -> dict[int, Decimal]:
    """Costo real promedio ponderado por orden_compra_item_id, a partir de todas las
    recepciones de esta OC (una linea puede haberse recibido en mas de una tanda a
    costos distintos). Devuelve solo los items que ya recibieron algo."""
    filas = recepciones_repo.listar_items_por_orden_compra(orden_compra_id)
    cantidad_por_item: dict[int, Decimal] = {}
    monto_por_item: dict[int, Decimal] = {}
    for fila in filas:
        item_id = fila["orden_compra_item_id"]
        cantidad = entero_a_cantidad(fila["cantidad_recibida"])
        costo = entero_a_precio(fila["costo_unitario"])
        cantidad_por_item[item_id] = cantidad_por_item.get(item_id, Decimal("0")) + cantidad
        monto_por_item[item_id] = monto_por_item.get(item_id, Decimal("0")) + cantidad * costo
    return {
        item_id: (monto_por_item[item_id] / cantidad_por_item[item_id])
        for item_id in cantidad_por_item
        if cantidad_por_item[item_id] > 0
    }


def _oc_a_dict(fila: sqlite3.Row, items: list[dict]) -> dict:
    total_estimado = sum((i["cantidad_pedida"] * i["costo_pactado"] for i in items), Decimal("0"))
    return {
        "id": fila["id"],
        "numero": fila["numero"],
        "proveedor_id": fila["proveedor_id"],
        "estado": fila["estado"],
        "fecha_creacion": fila["fecha_creacion"],
        "fecha_estimada": fila["fecha_estimada"],
        "iva_porcentaje": fila["iva_porcentaje"],
        "observacion": fila["observacion"],
        "recibida_en_el_acto": bool(fila["recibida_en_el_acto"]),
        "items": items,
        "total_estimado": total_estimado,
    }


def obtener_orden_compra(orden_compra_id: int) -> dict | None:
    fila = ordenes_compra_repo.obtener_por_id(orden_compra_id)
    if fila is None:
        return None
    items = [_item_a_dict(f) for f in ordenes_compra_repo.listar_items(orden_compra_id)]
    costos_reales = _costos_reales_por_item(orden_compra_id)
    for item in items:
        item["costo_real_promedio"] = costos_reales.get(item["id"])
    return _oc_a_dict(fila, items)


def listar_ordenes_compra(estado: str | None = None) -> list[dict]:
    return [obtener_orden_compra(f["id"]) for f in ordenes_compra_repo.listar(estado=estado)]
