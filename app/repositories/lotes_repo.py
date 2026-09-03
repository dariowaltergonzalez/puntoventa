import sqlite3

from app.db.connection import get_connection


def obtener_por_id(lote_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM lotes WHERE id = ?", (lote_id,)).fetchone()
    finally:
        conn.close()


def listar_por_producto(producto_id: int, solo_con_stock: bool = False) -> list[sqlite3.Row]:
    """ORDER BY fecha ASC, id ASC: es el orden que va a necesitar el consumo FIFO en Fase 4."""
    conn = get_connection()
    try:
        sql = "SELECT * FROM lotes WHERE producto_id = ?"
        parametros = [producto_id]
        if solo_con_stock:
            sql += " AND cantidad_restante > 0"
        sql += " ORDER BY fecha ASC, id ASC"
        return conn.execute(sql, parametros).fetchall()
    finally:
        conn.close()


def listar_por_recepcion(recepcion_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM lotes WHERE recepcion_id = ? ORDER BY id", (recepcion_id,)).fetchall()
    finally:
        conn.close()


def listar_por_producto_con_oc(producto_id: int, solo_con_stock: bool = False) -> list[sqlite3.Row]:
    """Igual que listar_por_producto pero trae tambien de que OC/remito vino cada lote,
    para mostrar el detalle en pantalla (Stock)."""
    conn = get_connection()
    try:
        sql = """
            SELECT l.*, r.numero_remito, oc.numero AS numero_oc
            FROM lotes l
            LEFT JOIN recepciones r ON r.id = l.recepcion_id
            LEFT JOIN ordenes_compra oc ON oc.id = r.orden_compra_id
            WHERE l.producto_id = ?
        """
        parametros = [producto_id]
        if solo_con_stock:
            sql += " AND l.cantidad_restante > 0"
        sql += " ORDER BY l.fecha ASC, l.id ASC"
        return conn.execute(sql, parametros).fetchall()
    finally:
        conn.close()
