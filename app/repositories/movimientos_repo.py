import sqlite3
from datetime import datetime

from app.db.connection import get_connection


def registrar_movimiento_y_actualizar_stock(
    producto_id: int,
    tipo: str,
    cantidad: int,
    motivo: str,
    referencia: str | None = None,
    observacion: str | None = None,
    lote_id: int | None = None,
    precio_unitario: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Operacion atomica: inserta el movimiento y actualiza productos.stock_actual en una unica
    transaccion. No valida reglas de negocio (stock negativo, producto activo, etc.) -- eso ya
    vino validado desde la capa de servicios antes de llamar aca. Si se pasa conn, participa de
    esa transaccion ya abierta (uso desde recepciones_repo) en vez de abrir la propia."""
    conexion_propia = conn is None
    if conexion_propia:
        conn = get_connection()
        conn.execute("BEGIN IMMEDIATE")
    try:
        fila = conn.execute(
            "SELECT stock_actual FROM productos WHERE id = ?", (producto_id,)
        ).fetchone()
        stock_actual = fila["stock_actual"]

        if tipo == "ingreso":
            nuevo_stock = stock_actual + cantidad
        else:
            nuevo_stock = stock_actual - cantidad

        fecha = datetime.now().isoformat()

        cursor = conn.execute(
            """
            INSERT INTO movimientos
                (producto_id, tipo, cantidad, fecha, motivo, referencia, observacion, lote_id, precio_unitario)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (producto_id, tipo, cantidad, fecha, motivo, referencia, observacion, lote_id, precio_unitario),
        )
        movimiento_id = cursor.lastrowid

        conn.execute(
            "UPDATE productos SET stock_actual = ? WHERE id = ?", (nuevo_stock, producto_id)
        )

        if conexion_propia:
            conn.commit()
        return movimiento_id
    except Exception:
        if conexion_propia:
            conn.rollback()
        raise
    finally:
        if conexion_propia:
            conn.close()


def obtener_por_id(movimiento_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM movimientos WHERE id = ?", (movimiento_id,)).fetchone()
    finally:
        conn.close()


def listar_por_producto(
    producto_id: int, desde: str | None = None, hasta: str | None = None
) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        condiciones = ["producto_id = ?"]
        parametros = [producto_id]
        if desde is not None:
            condiciones.append("fecha >= ?")
            parametros.append(desde)
        if hasta is not None:
            condiciones.append("fecha <= ?")
            parametros.append(hasta)

        sql = "SELECT * FROM movimientos WHERE " + " AND ".join(condiciones) + " ORDER BY fecha DESC"
        return conn.execute(sql, parametros).fetchall()
    finally:
        conn.close()


def listar(
    desde: str | None = None, hasta: str | None = None, tipo: str | None = None
) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        condiciones = []
        parametros = []
        if desde is not None:
            condiciones.append("fecha >= ?")
            parametros.append(desde)
        if hasta is not None:
            condiciones.append("fecha <= ?")
            parametros.append(hasta)
        if tipo is not None:
            condiciones.append("tipo = ?")
            parametros.append(tipo)

        sql = "SELECT * FROM movimientos"
        if condiciones:
            sql += " WHERE " + " AND ".join(condiciones)
        sql += " ORDER BY fecha DESC"

        return conn.execute(sql, parametros).fetchall()
    finally:
        conn.close()


def recalcular_stock() -> dict[int, int]:
    """Reconstruye stock_actual de todos los productos sumando/restando desde movimientos,
    en una unica transaccion. Devuelve {producto_id: stock_recalculado}."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")

        productos_ids = [fila["id"] for fila in conn.execute("SELECT id FROM productos").fetchall()]

        agregados = conn.execute(
            """
            SELECT producto_id,
                   SUM(CASE WHEN tipo = 'ingreso' THEN cantidad ELSE -cantidad END) AS stock_calculado
            FROM movimientos
            GROUP BY producto_id
            """
        ).fetchall()
        stock_por_producto = {fila["producto_id"]: fila["stock_calculado"] for fila in agregados}

        resultado: dict[int, int] = {}
        for producto_id in productos_ids:
            nuevo_stock = stock_por_producto.get(producto_id, 0)
            conn.execute(
                "UPDATE productos SET stock_actual = ? WHERE id = ?", (nuevo_stock, producto_id)
            )
            resultado[producto_id] = nuevo_stock

        conn.commit()
        return resultado
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
