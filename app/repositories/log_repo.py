import sqlite3
from datetime import datetime

from app.db.connection import get_connection
from app.repositories.paginacion import paginar


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


def listar_pagina(
    pagina: int, tamano_pagina: int, entidad: str | None = None, texto: str | None = None,
) -> tuple[list[sqlite3.Row], int]:
    """Version paginada de `listar`, sin el tope de 500 -- a diferencia de ese, este si permite
    llegar a cualquier evento viejo navegando las paginas. 'texto' se busca en SQL (antes se
    filtraba en Python sobre los ultimos 500, ahora busca sobre toda la tabla)."""
    conn = get_connection()
    try:
        condiciones = []
        parametros = []
        if entidad:
            condiciones.append("entidad = ?")
            parametros.append(entidad)
        if texto:
            condiciones.append("descripcion LIKE ?")
            parametros.append(f"%{texto}%")

        sql = "SELECT * FROM log_eventos"
        if condiciones:
            sql += " WHERE " + " AND ".join(condiciones)
        sql += " ORDER BY fecha DESC, id DESC"

        return paginar(conn, sql, parametros, pagina, tamano_pagina)
    finally:
        conn.close()
