import sqlite3

from app.db.connection import get_connection


def crear(
    nombre: str,
    cuit: str | None = None,
    contacto: str | None = None,
    telefono: str | None = None,
    email: str | None = None,
    direccion: str | None = None,
    observaciones: str | None = None,
) -> int:
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO proveedores (nombre, cuit, contacto, telefono, email, direccion, observaciones, activo)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (nombre, cuit, contacto, telefono, email, direccion, observaciones),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def actualizar(
    proveedor_id: int,
    nombre: str,
    cuit: str | None,
    contacto: str | None,
    telefono: str | None,
    email: str | None,
    direccion: str | None,
    observaciones: str | None,
    activo: int,
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE proveedores
            SET nombre = ?, cuit = ?, contacto = ?, telefono = ?, email = ?,
                direccion = ?, observaciones = ?, activo = ?
            WHERE id = ?
            """,
            (nombre, cuit, contacto, telefono, email, direccion, observaciones, activo, proveedor_id),
        )
        conn.commit()
    finally:
        conn.close()


def obtener_por_id(proveedor_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM proveedores WHERE id = ?", (proveedor_id,)).fetchone()
    finally:
        conn.close()


def listar(solo_activos: bool = False) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        sql = "SELECT * FROM proveedores"
        if solo_activos:
            sql += " WHERE activo = 1"
        sql += " ORDER BY nombre"
        return conn.execute(sql).fetchall()
    finally:
        conn.close()
