import sqlite3
from datetime import datetime

from app.db.connection import get_connection


def crear(entidad: str, entidad_id: int | None, descripcion: str) -> int:
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO log_eventos (fecha, entidad, entidad_id, descripcion) VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(), entidad, entidad_id, descripcion),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def listar(entidad: str | None = None, limite: int = 500) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        if entidad:
            sql = "SELECT * FROM log_eventos WHERE entidad = ? ORDER BY fecha DESC, id DESC LIMIT ?"
            parametros = (entidad, limite)
        else:
            sql = "SELECT * FROM log_eventos ORDER BY fecha DESC, id DESC LIMIT ?"
            parametros = (limite,)
        return conn.execute(sql, parametros).fetchall()
    finally:
        conn.close()
