import sqlite3

from app.db.connection import get_connection


def crear(
    codigo: str,
    nombre: str,
    categoria_id: int,
    unidad: str,
    precio_costo: int,
    precio_venta: int,
    activo: int = 1,
) -> int:
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO productos
                (codigo, nombre, categoria_id, unidad, precio_costo, precio_venta, activo, stock_actual)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (codigo, nombre, categoria_id, unidad, precio_costo, precio_venta, activo),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def actualizar(
    producto_id: int,
    codigo: str,
    nombre: str,
    categoria_id: int,
    unidad: str,
    precio_costo: int,
    precio_venta: int,
    activo: int,
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE productos
            SET codigo = ?, nombre = ?, categoria_id = ?, unidad = ?,
                precio_costo = ?, precio_venta = ?, activo = ?
            WHERE id = ?
            """,
            (codigo, nombre, categoria_id, unidad, precio_costo, precio_venta, activo, producto_id),
        )
        conn.commit()
    finally:
        conn.close()


def obtener_por_id(producto_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
    finally:
        conn.close()


def obtener_por_codigo(codigo: str) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM productos WHERE codigo = ?", (codigo,)).fetchone()
    finally:
        conn.close()


def listar(solo_activos: bool = False, categoria_id: int | None = None) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        condiciones = []
        parametros = []
        if solo_activos:
            condiciones.append("activo = 1")
        if categoria_id is not None:
            condiciones.append("categoria_id = ?")
            parametros.append(categoria_id)

        sql = "SELECT * FROM productos"
        if condiciones:
            sql += " WHERE " + " AND ".join(condiciones)
        sql += " ORDER BY nombre"

        return conn.execute(sql, parametros).fetchall()
    finally:
        conn.close()


def actualizar_stock(producto_id: int, nuevo_stock: int, conn: sqlite3.Connection | None = None) -> None:
    """Setea stock_actual directamente. Uso interno: llamado dentro de una transaccion ya abierta
    (registrar_movimiento_y_actualizar_stock, recalcular_stock) o de forma standalone si conn es None."""
    conexion_propia = conn is None
    if conexion_propia:
        conn = get_connection()
    try:
        conn.execute("UPDATE productos SET stock_actual = ? WHERE id = ?", (nuevo_stock, producto_id))
        if conexion_propia:
            conn.commit()
    finally:
        if conexion_propia:
            conn.close()
