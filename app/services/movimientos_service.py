import sqlite3
from decimal import Decimal

from app.repositories import movimientos_repo, productos_repo
from app.services.exceptions import ProductoInactivoError, ProductoNoEncontradoError, StockInsuficienteError
from app.shared.money import cantidad_a_entero, entero_a_cantidad


def _a_dict(fila: sqlite3.Row) -> dict:
    return {
        "id": fila["id"],
        "producto_id": fila["producto_id"],
        "tipo": fila["tipo"],
        "cantidad": entero_a_cantidad(fila["cantidad"]),
        "fecha": fila["fecha"],
        "motivo": fila["motivo"],
        "referencia": fila["referencia"],
        "observacion": fila["observacion"],
    }


def _obtener_producto_o_falla(producto_id: int) -> sqlite3.Row:
    producto = productos_repo.obtener_por_id(producto_id)
    if producto is None:
        raise ProductoNoEncontradoError(f"No existe el producto {producto_id}")
    if not producto["activo"]:
        raise ProductoInactivoError(f"El producto {producto_id} esta inactivo")
    return producto


def registrar_ingreso(
    producto_id: int,
    cantidad: Decimal,
    motivo: str,
    referencia: str | None = None,
    observacion: str | None = None,
) -> dict:
    _obtener_producto_o_falla(producto_id)
    if cantidad <= 0:
        raise ValueError("La cantidad debe ser mayor a cero")

    movimiento_id = movimientos_repo.registrar_movimiento_y_actualizar_stock(
        producto_id=producto_id,
        tipo="ingreso",
        cantidad=cantidad_a_entero(cantidad),
        motivo=motivo,
        referencia=referencia,
        observacion=observacion,
    )
    return _obtener_movimiento(movimiento_id)


def registrar_egreso(
    producto_id: int,
    cantidad: Decimal,
    motivo: str,
    referencia: str | None = None,
    observacion: str | None = None,
) -> dict:
    producto = _obtener_producto_o_falla(producto_id)
    if cantidad <= 0:
        raise ValueError("La cantidad debe ser mayor a cero")

    stock_actual = entero_a_cantidad(producto["stock_actual"])
    if cantidad > stock_actual:
        raise StockInsuficienteError(
            f"Stock insuficiente: hay {stock_actual}, se pidio egresar {cantidad}"
        )

    movimiento_id = movimientos_repo.registrar_movimiento_y_actualizar_stock(
        producto_id=producto_id,
        tipo="egreso",
        cantidad=cantidad_a_entero(cantidad),
        motivo=motivo,
        referencia=referencia,
        observacion=observacion,
    )
    return _obtener_movimiento(movimiento_id)


def registrar_ajuste(
    producto_id: int,
    cantidad: Decimal,
    tipo: str,
    observacion: str,
    referencia: str | None = None,
) -> dict:
    if tipo == "ingreso":
        return registrar_ingreso(producto_id, cantidad, motivo="ajuste", referencia=referencia, observacion=observacion)
    if tipo == "egreso":
        return registrar_egreso(producto_id, cantidad, motivo="ajuste", referencia=referencia, observacion=observacion)
    raise ValueError("tipo debe ser 'ingreso' o 'egreso'")


def _obtener_movimiento(movimiento_id: int) -> dict:
    fila = movimientos_repo.obtener_por_id(movimiento_id)
    return _a_dict(fila) if fila is not None else None


def listar_movimientos_producto(
    producto_id: int, desde: str | None = None, hasta: str | None = None
) -> list[dict]:
    return [_a_dict(f) for f in movimientos_repo.listar_por_producto(producto_id, desde, hasta)]


def listar_movimientos(
    desde: str | None = None, hasta: str | None = None, tipo: str | None = None
) -> list[dict]:
    return [_a_dict(f) for f in movimientos_repo.listar(desde, hasta, tipo)]


def consultar_stock(categoria_id: int | None = None, solo_activos: bool = True) -> list[dict]:
    productos = productos_repo.listar(solo_activos=solo_activos, categoria_id=categoria_id)
    return [
        {
            "id": p["id"],
            "codigo": p["codigo"],
            "nombre": p["nombre"],
            "categoria_id": p["categoria_id"],
            "unidad": p["unidad"],
            "stock_actual": entero_a_cantidad(p["stock_actual"]),
            "stock_minimo": entero_a_cantidad(p["stock_minimo"]),
        }
        for p in productos
    ]


def recalcular_stock() -> list[dict]:
    productos_antes = {p["id"]: p["stock_actual"] for p in productos_repo.listar()}
    resultado = movimientos_repo.recalcular_stock()

    diferencias = []
    for producto_id, stock_recalculado in resultado.items():
        stock_anterior = productos_antes.get(producto_id, 0)
        if stock_anterior != stock_recalculado:
            diferencias.append(
                {
                    "producto_id": producto_id,
                    "stock_anterior": entero_a_cantidad(stock_anterior),
                    "stock_recalculado": entero_a_cantidad(stock_recalculado),
                    "diferencia": entero_a_cantidad(stock_recalculado - stock_anterior),
                }
            )
    return diferencias
