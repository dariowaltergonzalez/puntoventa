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
