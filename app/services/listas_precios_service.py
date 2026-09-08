import sqlite3
from decimal import Decimal

from app.repositories import categorias_repo, listas_precios_repo, productos_repo
from app.services import log_service
from app.services.exceptions import (
    CategoriaNoEncontradaError,
    ListaPrecioDuplicadaError,
    ListaPrecioNoEncontradaError,
    ProductoNoEncontradoError,
)
from app.shared.money import entero_a_porcentaje, entero_a_precio, porcentaje_a_entero, precio_a_entero

_CAMPOS_LOG = ["nombre", "porcentaje_general", "activo"]


def _a_dict(fila: sqlite3.Row) -> dict:
    return {
        "id": fila["id"],
        "nombre": fila["nombre"],
        "porcentaje_general": entero_a_porcentaje(fila["porcentaje_general"]) if fila["porcentaje_general"] is not None else None,
        "activo": bool(fila["activo"]),
    }


def crear_lista(nombre: str, porcentaje_general: Decimal | None = None) -> dict:
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre de la lista de precios no puede estar vacio")
    try:
        lista_id = listas_precios_repo.crear(
            nombre, porcentaje_a_entero(porcentaje_general) if porcentaje_general is not None else None,
        )
    except sqlite3.IntegrityError as exc:
        raise ListaPrecioDuplicadaError(f"Ya existe una lista de precios llamada '{nombre}'") from exc
    log_service.registrar("lista_precio", lista_id, f"Se creo la lista de precios '{nombre}'")
    return obtener_lista(lista_id)


def actualizar_lista(lista_id: int, nombre: str, porcentaje_general: Decimal | None, activo: bool) -> dict:
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre de la lista de precios no puede estar vacio")
    antes = obtener_lista(lista_id)
    if antes is None:
        raise ListaPrecioNoEncontradaError(f"No existe la lista de precios {lista_id}")
    try:
        listas_precios_repo.actualizar(
            lista_id, nombre, porcentaje_a_entero(porcentaje_general) if porcentaje_general is not None else None,
            1 if activo else 0,
        )
    except sqlite3.IntegrityError as exc:
        raise ListaPrecioDuplicadaError(f"Ya existe una lista de precios llamada '{nombre}'") from exc
    despues = obtener_lista(lista_id)
    log_service.registrar_cambios("lista_precio", lista_id, antes, despues, _CAMPOS_LOG)
    return despues


def obtener_lista(lista_id: int) -> dict | None:
    fila = listas_precios_repo.obtener_por_id(lista_id)
    if fila is None:
        return None
    lista = _a_dict(fila)
    lista["categorias"] = [
        {
            "categoria_id": f["categoria_id"],
            "categoria_nombre": f["categoria_nombre"],
            "porcentaje": entero_a_porcentaje(f["porcentaje"]),
        }
        for f in listas_precios_repo.listar_porcentajes_categoria(lista_id)
    ]
    lista["productos"] = [
        {
            "producto_id": f["producto_id"],
            "producto_codigo": f["producto_codigo"],
            "producto_nombre": f["producto_nombre"],
            "precio_manual": entero_a_precio(f["precio_manual"]),
        }
        for f in listas_precios_repo.listar_precios_producto(lista_id)
    ]
    return lista


def listar_listas(solo_activas: bool = False) -> list[dict]:
    return [_a_dict(fila) for fila in listas_precios_repo.listar(solo_activas)]


def establecer_porcentaje_categoria(lista_id: int, categoria_id: int, porcentaje: Decimal) -> dict:
    if listas_precios_repo.obtener_por_id(lista_id) is None:
        raise ListaPrecioNoEncontradaError(f"No existe la lista de precios {lista_id}")
    if categorias_repo.obtener_por_id(categoria_id) is None:
        raise CategoriaNoEncontradaError(f"No existe la categoria {categoria_id}")
    listas_precios_repo.establecer_porcentaje_categoria(lista_id, categoria_id, porcentaje_a_entero(porcentaje))
    log_service.registrar("lista_precio", lista_id, f"Se establecio un % especial para la categoria {categoria_id}")
    return obtener_lista(lista_id)


def quitar_porcentaje_categoria(lista_id: int, categoria_id: int) -> dict:
    listas_precios_repo.quitar_porcentaje_categoria(lista_id, categoria_id)
    log_service.registrar("lista_precio", lista_id, f"Se quito el % especial de la categoria {categoria_id}")
    return obtener_lista(lista_id)


def establecer_precio_producto(lista_id: int, producto_id: int, precio_manual: Decimal) -> dict:
    if listas_precios_repo.obtener_por_id(lista_id) is None:
        raise ListaPrecioNoEncontradaError(f"No existe la lista de precios {lista_id}")
    if productos_repo.obtener_por_id(producto_id) is None:
        raise ProductoNoEncontradoError(f"No existe el producto {producto_id}")
    if precio_manual < 0:
        raise ValueError("El precio manual no puede ser negativo")
    listas_precios_repo.establecer_precio_producto(lista_id, producto_id, precio_a_entero(precio_manual))
    log_service.registrar("lista_precio", lista_id, f"Se establecio un precio manual para el producto {producto_id}")
    return obtener_lista(lista_id)


def quitar_precio_producto(lista_id: int, producto_id: int) -> dict:
    listas_precios_repo.quitar_precio_producto(lista_id, producto_id)
    log_service.registrar("lista_precio", lista_id, f"Se quito el precio manual del producto {producto_id}")
    return obtener_lista(lista_id)


def calcular_precio_producto(producto_id: int, lista_id: int) -> Decimal:
    """Precio de un producto dentro de una lista, de mas especifico a mas general:
    1) precio manual del producto en esa lista
    2) % de la categoria del producto en esa lista
    3) % general de la lista
    4) si la lista no tiene nada cargado: el precio de venta normal del producto"""
    producto = productos_repo.obtener_por_id(producto_id)
    if producto is None:
        raise ProductoNoEncontradoError(f"No existe el producto {producto_id}")
    precio_normal = entero_a_precio(producto["precio_venta"])

    precio_manual = listas_precios_repo.obtener_precio_producto(lista_id, producto_id)
    if precio_manual is not None:
        return entero_a_precio(precio_manual["precio_manual"])

    porcentaje_categoria = listas_precios_repo.obtener_porcentaje_categoria(lista_id, producto["categoria_id"])
    if porcentaje_categoria is not None:
        porcentaje = entero_a_porcentaje(porcentaje_categoria["porcentaje"])
        return (precio_normal * (Decimal("1") + porcentaje / Decimal("100"))).quantize(Decimal("1.00"))

    lista = listas_precios_repo.obtener_por_id(lista_id)
    if lista is None:
        raise ListaPrecioNoEncontradaError(f"No existe la lista de precios {lista_id}")
    if lista["porcentaje_general"] is not None:
        porcentaje = entero_a_porcentaje(lista["porcentaje_general"])
        return (precio_normal * (Decimal("1") + porcentaje / Decimal("100"))).quantize(Decimal("1.00"))

    return precio_normal
