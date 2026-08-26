import sqlite3

from app.db.connection import get_connection


def crear(nombre: str) -> int:
    conn = get_connection()
    try:
        cursor = conn.execute("INSERT INTO categorias (nombre) VALUES (?)", (nombre,))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def actualizar(categoria_id: int, nombre: str) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE categorias SET nombre = ? WHERE id = ?", (nombre, categoria_id))
        conn.commit()
    finally:
        conn.close()


def obtener_por_id(categoria_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM categorias WHERE id = ?", (categoria_id,)).fetchone()
    finally:
        conn.close()


def listar() -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM categorias ORDER BY nombre").fetchall()
    finally:
        conn.close()
