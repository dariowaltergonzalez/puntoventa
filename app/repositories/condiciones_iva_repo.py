import sqlite3

from app.db.connection import get_connection


def obtener_por_id(condicion_iva_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM condiciones_iva WHERE id = ?", (condicion_iva_id,)).fetchone()
    finally:
        conn.close()


def listar(solo_activas: bool = False) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        sql = "SELECT * FROM condiciones_iva"
        if solo_activas:
            sql += " WHERE activo = 1"
        sql += " ORDER BY nombre"
        return conn.execute(sql).fetchall()
    finally:
        conn.close()
