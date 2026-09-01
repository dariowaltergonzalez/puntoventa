import sqlite3

from app.db.connection import get_connection


def siguiente_numero(nombre: str, prefijo: str, ancho: int = 4, conn: sqlite3.Connection | None = None) -> str:
    """Incrementa atomicamente el contador `nombre` (lo crea en 0 si no existe) y devuelve el
    numero formateado 'PREFIJO-0001'. Si se pasa conn, participa de esa transaccion ya abierta."""
    conexion_propia = conn is None
    if conexion_propia:
        conn = get_connection()
        conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("INSERT INTO contadores (nombre, valor) VALUES (?, 0) ON CONFLICT(nombre) DO NOTHING", (nombre,))
        conn.execute("UPDATE contadores SET valor = valor + 1 WHERE nombre = ?", (nombre,))
        valor = conn.execute("SELECT valor FROM contadores WHERE nombre = ?", (nombre,)).fetchone()["valor"]
        if conexion_propia:
            conn.commit()
        return f"{prefijo}-{valor:0{ancho}d}"
    except Exception:
        if conexion_propia:
            conn.rollback()
        raise
    finally:
        if conexion_propia:
            conn.close()
