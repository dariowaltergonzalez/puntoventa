import sqlite3

from app.db.connection import get_connection


def crear(nombre: str, es_cuenta_corriente: bool = False) -> int:
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO medios_pago (nombre, es_cuenta_corriente, activo) VALUES (?, ?, 1)",
            (nombre, int(es_cuenta_corriente)),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def actualizar(medio_pago_id: int, nombre: str, es_cuenta_corriente: bool, activo: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE medios_pago SET nombre = ?, es_cuenta_corriente = ?, activo = ? WHERE id = ?",
            (nombre, int(es_cuenta_corriente), activo, medio_pago_id),
        )
        conn.commit()
    finally:
        conn.close()


def obtener_por_id(medio_pago_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM medios_pago WHERE id = ?", (medio_pago_id,)).fetchone()
    finally:
        conn.close()


def listar(solo_activos: bool = False) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        sql = "SELECT * FROM medios_pago"
        if solo_activos:
            sql += " WHERE activo = 1"
        sql += " ORDER BY nombre"
        return conn.execute(sql).fetchall()
    finally:
        conn.close()
