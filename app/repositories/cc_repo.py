import sqlite3

from app.db.connection import get_connection


def crear_cargo(
    cliente_id: int | None,
    proveedor_id: int | None,
    monto: int,
    fecha: str,
    origen: str,
    origen_recepcion_id: int | None,
    observacion: str | None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Exactamente uno de cliente_id/proveedor_id. conn opcional: se usa con una conn ya abierta
    cuando el cargo se genera automaticamente dentro de otra transaccion (ej. recepcion a credito)."""
    conexion_propia = conn is None
    if conexion_propia:
        conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO cc_cargos
                (cliente_id, proveedor_id, monto, fecha, origen, origen_recepcion_id, observacion)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (cliente_id, proveedor_id, monto, fecha, origen, origen_recepcion_id, observacion),
        )
        if conexion_propia:
            conn.commit()
        return cursor.lastrowid
    finally:
        if conexion_propia:
            conn.close()


def obtener_cargo_por_id(cargo_id: int, conn: sqlite3.Connection | None = None) -> sqlite3.Row | None:
    conexion_propia = conn is None
    if conexion_propia:
        conn = get_connection()
    try:
        return conn.execute("SELECT * FROM cc_cargos WHERE id = ?", (cargo_id,)).fetchone()
    finally:
        if conexion_propia:
            conn.close()


def listar_cargos(cliente_id: int | None = None, proveedor_id: int | None = None) -> list[sqlite3.Row]:
    """ORDER BY fecha ASC, id ASC: orden FIFO para aplicar pagos 'a cuenta'."""
    conn = get_connection()
    try:
        if cliente_id is not None:
            return conn.execute(
                "SELECT * FROM cc_cargos WHERE cliente_id = ? ORDER BY fecha ASC, id ASC", (cliente_id,)
            ).fetchall()
        return conn.execute(
            "SELECT * FROM cc_cargos WHERE proveedor_id = ? ORDER BY fecha ASC, id ASC", (proveedor_id,)
        ).fetchall()
    finally:
        conn.close()


def crear_pago_con_aplicaciones(
    cliente_id: int | None,
    proveedor_id: int | None,
    monto: int,
    fecha: str,
    observacion: str | None,
    aplicaciones: list[dict],
    conn: sqlite3.Connection | None = None,
) -> int:
    """Crea el pago y sus aplicaciones a cargos en una unica transaccion atomica.
    aplicaciones: [{'cargo_id': int, 'monto': int}, ...] -- ya validadas por el servicio
    (saldo suficiente, suma <= monto del pago)."""
    conexion_propia = conn is None
    if conexion_propia:
        conn = get_connection()
        conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "INSERT INTO cc_pagos (cliente_id, proveedor_id, monto, fecha, observacion) VALUES (?, ?, ?, ?, ?)",
            (cliente_id, proveedor_id, monto, fecha, observacion),
        )
        pago_id = cursor.lastrowid
        for aplicacion in aplicaciones:
            conn.execute(
                "INSERT INTO cc_pago_aplicaciones (pago_id, cargo_id, monto) VALUES (?, ?, ?)",
                (pago_id, aplicacion["cargo_id"], aplicacion["monto"]),
            )
        if conexion_propia:
            conn.commit()
        return pago_id
    except Exception:
        if conexion_propia:
            conn.rollback()
        raise
    finally:
        if conexion_propia:
            conn.close()


def obtener_pago_por_id(pago_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM cc_pagos WHERE id = ?", (pago_id,)).fetchone()
    finally:
        conn.close()


def listar_pagos(cliente_id: int | None = None, proveedor_id: int | None = None) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        if cliente_id is not None:
            return conn.execute(
                "SELECT * FROM cc_pagos WHERE cliente_id = ? ORDER BY fecha DESC, id DESC", (cliente_id,)
            ).fetchall()
        return conn.execute(
            "SELECT * FROM cc_pagos WHERE proveedor_id = ? ORDER BY fecha DESC, id DESC", (proveedor_id,)
        ).fetchall()
    finally:
        conn.close()


def listar_aplicaciones_de_cargo(cargo_id: int, conn: sqlite3.Connection | None = None) -> list[sqlite3.Row]:
    conexion_propia = conn is None
    if conexion_propia:
        conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM cc_pago_aplicaciones WHERE cargo_id = ?", (cargo_id,)
        ).fetchall()
    finally:
        if conexion_propia:
            conn.close()


def listar_aplicaciones_de_pago(pago_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT pa.*, c.fecha AS cargo_fecha, c.observacion AS cargo_observacion
            FROM cc_pago_aplicaciones pa
            JOIN cc_cargos c ON c.id = pa.cargo_id
            WHERE pa.pago_id = ?
            """,
            (pago_id,),
        ).fetchall()
    finally:
        conn.close()


def listar_aplicaciones_por_cargos(cargo_ids: list[int]) -> list[sqlite3.Row]:
    """Todas las aplicaciones de una lista de cargos, en una sola consulta (para calcular saldo
    pendiente de varios cargos sin N+1 queries)."""
    if not cargo_ids:
        return []
    conn = get_connection()
    try:
        marcadores = ",".join("?" * len(cargo_ids))
        return conn.execute(
            f"SELECT * FROM cc_pago_aplicaciones WHERE cargo_id IN ({marcadores})", cargo_ids
        ).fetchall()
    finally:
        conn.close()
