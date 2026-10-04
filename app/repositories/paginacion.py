"""Mecanica compartida de paginacion SQL -- la parte de LIMIT/OFFSET/COUNT es identica sin
importar que entidad se este paginando. Cada repo arma su propio SELECT con sus propios
filtros (columnas de busqueda, WHERE, joins) y le pasa el resultado a `paginar`; esta funcion
no sabe nada del modelo particular, solo recorta la consulta a la pagina pedida."""

import sqlite3


def paginar(
    conn: sqlite3.Connection, sql: str, parametros: list, pagina: int, tamano_pagina: int,
) -> tuple[list[sqlite3.Row], int]:
    """`sql` es una consulta SELECT completa (con su WHERE/ORDER BY ya armados, sin LIMIT).
    Devuelve (filas de esa pagina, total de registros que matchean sin paginar) -- el total
    se calcula envolviendo la misma consulta en un COUNT(*), asi siempre queda consistente
    con el WHERE real sin tener que duplicarlo a mano."""
    total = conn.execute(f"SELECT COUNT(*) FROM ({sql})", parametros).fetchone()[0]
    offset = (pagina - 1) * tamano_pagina
    filas = conn.execute(f"{sql} LIMIT ? OFFSET ?", parametros + [tamano_pagina, offset]).fetchall()
    return filas, total
