import sqlite3

from app.db.connection import get_connection
from app.repositories.paginacion import paginar


def crear(
    codigo: str,
    nombre: str,
    categoria_id: int,
    unidad: str,
    precio_costo: int,
    precio_venta: int,
    stock_minimo: int = 0,
    activo: int = 1,
    marca: str | None = None,
    descripcion: str | None = None,
    codigo_barra: str | None = None,
    proveedor_id: int | None = None,
) -> int:
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO productos
                (codigo, nombre, categoria_id, unidad, precio_costo, precio_venta, activo, stock_actual,
                 stock_minimo, marca, descripcion, codigo_barra, proveedor_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
            """,
            (
                codigo, nombre, categoria_id, unidad, precio_costo, precio_venta, activo,
                stock_minimo, marca, descripcion, codigo_barra, proveedor_id,
            ),
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
    stock_minimo: int,
    activo: int,
    marca: str | None = None,
    descripcion: str | None = None,
    codigo_barra: str | None = None,
    proveedor_id: int | None = None,
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE productos
            SET codigo = ?, nombre = ?, categoria_id = ?, unidad = ?,
                precio_costo = ?, precio_venta = ?, activo = ?, stock_minimo = ?,
                marca = ?, descripcion = ?, codigo_barra = ?, proveedor_id = ?
            WHERE id = ?
            """,
            (
                codigo, nombre, categoria_id, unidad, precio_costo, precio_venta, activo, stock_minimo,
                marca, descripcion, codigo_barra, proveedor_id, producto_id,
            ),
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


def listar_pagina(
    pagina: int, tamano_pagina: int, texto: str | None = None,
    solo_activos: bool = False, categoria_id: int | None = None,
) -> tuple[list[sqlite3.Row], int]:
    """Igual que `listar`, pero resuelta en SQL: pide solo la pagina pedida (LIMIT/OFFSET) y
    el total de registros via COUNT, en vez de traer toda la tabla y recortar en Python --
    pensada para catalogos grandes donde cargar todo en memoria en cada busqueda no escala."""
    conn = get_connection()
    try:
        condiciones = []
        parametros = []
        if solo_activos:
            condiciones.append("activo = 1")
        if categoria_id is not None:
            condiciones.append("categoria_id = ?")
            parametros.append(categoria_id)
        if texto:
            condiciones.append("(codigo LIKE ? OR nombre LIKE ? OR codigo_barra LIKE ?)")
            comodin = f"%{texto}%"
            parametros.extend([comodin, comodin, comodin])

        sql = "SELECT * FROM productos"
        if condiciones:
            sql += " WHERE " + " AND ".join(condiciones)
        sql += " ORDER BY nombre"

        return paginar(conn, sql, parametros, pagina, tamano_pagina)
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
