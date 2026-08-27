import sqlite3
from decimal import Decimal

from app.repositories import categorias_repo, productos_repo
from app.services.exceptions import CategoriaNoEncontradaError, CodigoDuplicadoError, ProductoNoEncontradoError
from app.shared.money import cantidad_a_entero, entero_a_cantidad, entero_a_precio, precio_a_entero


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
    }


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


def crear_producto(
    codigo: str,
    nombre: str,
    categoria_id: int,
    unidad: str,
    precio_costo: Decimal,
    precio_venta: Decimal,
    stock_minimo: Decimal = Decimal("0"),
    activo: bool = True,
) -> dict:
    codigo = codigo.strip()
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
        )
    except sqlite3.IntegrityError as exc:
        raise CodigoDuplicadoError(f"Ya existe un producto con el codigo '{codigo}'") from exc

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
) -> dict:
    codigo = codigo.strip()
    _validar_datos(codigo, categoria_id, precio_costo, precio_venta, stock_minimo)

    if productos_repo.obtener_por_id(producto_id) is None:
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
        )
    except sqlite3.IntegrityError as exc:
        raise CodigoDuplicadoError(f"Ya existe un producto con el codigo '{codigo}'") from exc

    return obtener_producto(producto_id)


def obtener_producto(producto_id: int) -> dict | None:
    fila = productos_repo.obtener_por_id(producto_id)
    return _a_dict(fila) if fila is not None else None


def obtener_producto_por_codigo(codigo: str) -> dict | None:
    fila = productos_repo.obtener_por_codigo(codigo)
    return _a_dict(fila) if fila is not None else None


def listar_productos(solo_activos: bool = False, categoria_id: int | None = None) -> list[dict]:
    return [_a_dict(fila) for fila in productos_repo.listar(solo_activos, categoria_id)]
