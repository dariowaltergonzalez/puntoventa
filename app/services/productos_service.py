import sqlite3
from decimal import Decimal

from app.repositories import categorias_repo, productos_repo, proveedores_repo
from app.services import log_service
from app.services.exceptions import (
    CategoriaNoEncontradaError,
    CodigoBarraDuplicadoError,
    CodigoDuplicadoError,
    ProductoNoEncontradoError,
)
from app.shared.money import cantidad_a_entero, entero_a_cantidad, entero_a_precio, precio_a_entero

_CAMPOS_LOG = [
    "codigo", "nombre", "categoria", "unidad", "precio_costo", "precio_venta",
    "stock_minimo", "marca", "descripcion", "codigo_barra", "proveedor", "activo",
]


def _a_dict(fila: sqlite3.Row) -> dict:
    return {
        "id": fila["id"],
        "codigo": fila["codigo"],
        "nombre": fila["nombre"],
        "categoria_id": fila["categoria_id"],
        "unidad": fila["unidad"],
        "precio_costo": entero_a_precio(fila["precio_costo"]),
        "precio_venta": entero_a_precio(fila["precio_venta"]),
        "activo": bool(fila["activo"]),
        "stock_actual": entero_a_cantidad(fila["stock_actual"]),
        "stock_minimo": entero_a_cantidad(fila["stock_minimo"]),
        "marca": fila["marca"],
        "descripcion": fila["descripcion"],
        "codigo_barra": fila["codigo_barra"],
        "proveedor_id": fila["proveedor_id"],
    }


def _vista_log(producto: dict) -> dict:
    """Version del producto con categoria_id/proveedor_id resueltos a nombre, para que el log
    interno sea legible ('de ninguno a Jorgito') en vez de mostrar ids crudos."""
    categoria = categorias_repo.obtener_por_id(producto["categoria_id"])
    proveedor = proveedores_repo.obtener_por_id(producto["proveedor_id"]) if producto["proveedor_id"] else None
    vista = dict(producto)
    vista["categoria"] = categoria["nombre"] if categoria else producto["categoria_id"]
    vista["proveedor"] = proveedor["nombre"] if proveedor else None
    return vista


def _texto_o_none(valor: str | None) -> str | None:
    valor = (valor or "").strip()
    return valor or None


def _validar_datos(
    codigo: str, categoria_id: int, precio_costo: Decimal, precio_venta: Decimal, stock_minimo: Decimal
) -> None:
    if not codigo.strip():
        raise ValueError("El codigo del producto no puede estar vacio")
    if categorias_repo.obtener_por_id(categoria_id) is None:
        raise CategoriaNoEncontradaError(f"No existe la categoria {categoria_id}")
    if precio_costo < 0 or precio_venta < 0:
        raise ValueError("Los precios no pueden ser negativos")
    if stock_minimo < 0:
        raise ValueError("El stock minimo no puede ser negativo")


def _traducir_integrity_error(exc: sqlite3.IntegrityError, codigo: str, codigo_barra: str | None) -> Exception:
    if "codigo_barra" in str(exc):
        return CodigoBarraDuplicadoError(f"Ya existe un producto con el codigo de barras '{codigo_barra}'")
    return CodigoDuplicadoError(f"Ya existe un producto con el codigo '{codigo}'")


def crear_producto(
    codigo: str,
    nombre: str,
    categoria_id: int,
    unidad: str,
    precio_costo: Decimal,
    precio_venta: Decimal,
    stock_minimo: Decimal = Decimal("0"),
    activo: bool = True,
    marca: str | None = None,
    descripcion: str | None = None,
    codigo_barra: str | None = None,
    proveedor_id: int | None = None,
) -> dict:
    codigo = codigo.strip()
    codigo_barra = _texto_o_none(codigo_barra)
    _validar_datos(codigo, categoria_id, precio_costo, precio_venta, stock_minimo)

    try:
        producto_id = productos_repo.crear(
            codigo=codigo,
            nombre=nombre.strip(),
            categoria_id=categoria_id,
            unidad=unidad.strip(),
            precio_costo=precio_a_entero(precio_costo),
            precio_venta=precio_a_entero(precio_venta),
            stock_minimo=cantidad_a_entero(stock_minimo),
            activo=1 if activo else 0,
            marca=_texto_o_none(marca),
            descripcion=_texto_o_none(descripcion),
            codigo_barra=codigo_barra,
            proveedor_id=proveedor_id,
        )
    except sqlite3.IntegrityError as exc:
        raise _traducir_integrity_error(exc, codigo, codigo_barra) from exc

    log_service.registrar("producto", producto_id, f"Se creo el producto '{codigo} - {nombre.strip()}'")
    return obtener_producto(producto_id)


def actualizar_producto(
    producto_id: int,
    codigo: str,
    nombre: str,
    categoria_id: int,
    unidad: str,
    precio_costo: Decimal,
    precio_venta: Decimal,
    stock_minimo: Decimal,
    activo: bool,
    marca: str | None = None,
    descripcion: str | None = None,
    codigo_barra: str | None = None,
    proveedor_id: int | None = None,
) -> dict:
    codigo = codigo.strip()
    codigo_barra = _texto_o_none(codigo_barra)
    _validar_datos(codigo, categoria_id, precio_costo, precio_venta, stock_minimo)

    antes = obtener_producto(producto_id)
    if antes is None:
        raise ProductoNoEncontradoError(f"No existe el producto {producto_id}")

    try:
        productos_repo.actualizar(
            producto_id=producto_id,
            codigo=codigo,
            nombre=nombre.strip(),
            categoria_id=categoria_id,
            unidad=unidad.strip(),
            precio_costo=precio_a_entero(precio_costo),
            precio_venta=precio_a_entero(precio_venta),
            stock_minimo=cantidad_a_entero(stock_minimo),
            activo=1 if activo else 0,
            marca=_texto_o_none(marca),
            descripcion=_texto_o_none(descripcion),
            codigo_barra=codigo_barra,
            proveedor_id=proveedor_id,
        )
    except sqlite3.IntegrityError as exc:
        raise _traducir_integrity_error(exc, codigo, codigo_barra) from exc

    despues = obtener_producto(producto_id)
    log_service.registrar_cambios("producto", producto_id, _vista_log(antes), _vista_log(despues), _CAMPOS_LOG)
    return despues


def obtener_producto(producto_id: int) -> dict | None:
    fila = productos_repo.obtener_por_id(producto_id)
    return _a_dict(fila) if fila is not None else None


def obtener_producto_por_codigo(codigo: str) -> dict | None:
    fila = productos_repo.obtener_por_codigo(codigo)
    return _a_dict(fila) if fila is not None else None


def listar_productos(solo_activos: bool = False, categoria_id: int | None = None) -> list[dict]:
    return [_a_dict(fila) for fila in productos_repo.listar(solo_activos, categoria_id)]
