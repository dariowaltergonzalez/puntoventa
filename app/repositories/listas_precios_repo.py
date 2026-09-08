import sqlite3

from app.db.connection import get_connection


# ---- Listas de precios ----

def crear(nombre: str, porcentaje_general: int | None) -> int:
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO listas_precios (nombre, porcentaje_general, activo) VALUES (?, ?, 1)",
            (nombre, porcentaje_general),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def actualizar(lista_id: int, nombre: str, porcentaje_general: int | None, activo: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE listas_precios SET nombre = ?, porcentaje_general = ?, activo = ? WHERE id = ?",
            (nombre, porcentaje_general, activo, lista_id),
        )
        conn.commit()
    finally:
        conn.close()


def obtener_por_id(lista_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM listas_precios WHERE id = ?", (lista_id,)).fetchone()
    finally:
        conn.close()


def listar(solo_activas: bool = False) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        sql = "SELECT * FROM listas_precios"
        if solo_activas:
            sql += " WHERE activo = 1"
        sql += " ORDER BY nombre"
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


# ---- Overrides por categoria ----

def establecer_porcentaje_categoria(lista_id: int, categoria_id: int, porcentaje: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO listas_precios_categorias (lista_precio_id, categoria_id, porcentaje)
            VALUES (?, ?, ?)
            ON CONFLICT(lista_precio_id, categoria_id) DO UPDATE SET porcentaje = excluded.porcentaje
            """,
            (lista_id, categoria_id, porcentaje),
        )
        conn.commit()
    finally:
        conn.close()


def quitar_porcentaje_categoria(lista_id: int, categoria_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM listas_precios_categorias WHERE lista_precio_id = ? AND categoria_id = ?",
            (lista_id, categoria_id),
        )
        conn.commit()
    finally:
        conn.close()


def listar_porcentajes_categoria(lista_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT lpc.*, c.nombre AS categoria_nombre
            FROM listas_precios_categorias lpc
            JOIN categorias c ON c.id = lpc.categoria_id
            WHERE lpc.lista_precio_id = ?
            ORDER BY c.nombre
            """,
            (lista_id,),
        ).fetchall()
    finally:
        conn.close()


def obtener_porcentaje_categoria(lista_id: int, categoria_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM listas_precios_categorias WHERE lista_precio_id = ? AND categoria_id = ?",
            (lista_id, categoria_id),
        ).fetchone()
    finally:
        conn.close()


# ---- Overrides por producto (precio manual) ----

def establecer_precio_producto(lista_id: int, producto_id: int, precio_manual: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO listas_precios_productos (lista_precio_id, producto_id, precio_manual)
            VALUES (?, ?, ?)
            ON CONFLICT(lista_precio_id, producto_id) DO UPDATE SET precio_manual = excluded.precio_manual
            """,
            (lista_id, producto_id, precio_manual),
        )
        conn.commit()
    finally:
        conn.close()


def quitar_precio_producto(lista_id: int, producto_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM listas_precios_productos WHERE lista_precio_id = ? AND producto_id = ?",
            (lista_id, producto_id),
        )
        conn.commit()
    finally:
        conn.close()


def listar_precios_producto(lista_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT lpp.*, p.codigo AS producto_codigo, p.nombre AS producto_nombre
            FROM listas_precios_productos lpp
            JOIN productos p ON p.id = lpp.producto_id
            WHERE lpp.lista_precio_id = ?
            ORDER BY p.nombre
            """,
            (lista_id,),
        ).fetchall()
    finally:
        conn.close()


def obtener_precio_producto(lista_id: int, producto_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM listas_precios_productos WHERE lista_precio_id = ? AND producto_id = ?",
            (lista_id, producto_id),
        ).fetchone()
    finally:
        conn.close()


# ---- Asignacion de listas a un cliente, con prioridad ----

def asignar_listas_cliente(cliente_id: int, lista_ids_en_orden: list[int]) -> None:
    """Reemplaza por completo las listas asignadas al cliente. El orden de la lista de entrada
    define la prioridad (primero = mayor prioridad, se sugiere primero en la venta)."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM cliente_listas_precios WHERE cliente_id = ?", (cliente_id,))
        for prioridad, lista_id in enumerate(lista_ids_en_orden, start=1):
            conn.execute(
                "INSERT INTO cliente_listas_precios (cliente_id, lista_precio_id, prioridad) VALUES (?, ?, ?)",
                (cliente_id, lista_id, prioridad),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def listar_listas_cliente(cliente_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT clp.*, lp.nombre AS lista_nombre, lp.porcentaje_general, lp.activo AS lista_activa
            FROM cliente_listas_precios clp
            JOIN listas_precios lp ON lp.id = clp.lista_precio_id
            WHERE clp.cliente_id = ?
            ORDER BY clp.prioridad
            """,
            (cliente_id,),
        ).fetchall()
    finally:
        conn.close()
