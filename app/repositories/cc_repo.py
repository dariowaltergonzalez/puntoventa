import sqlite3

from app.db.connection import get_connection
from app.repositories import cheques_repo


def crear_cargo(
    cliente_id: int | None,
    proveedor_id: int | None,
    monto: int,
    fecha: str,
    origen: str,
    origen_recepcion_id: int | None,
    observacion: str | None,
    origen_venta_id: int | None = None,
    origen_cheque_id: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Exactamente uno de cliente_id/proveedor_id. conn opcional: se usa con una conn ya abierta
    cuando el cargo se genera automaticamente dentro de otra transaccion (ej. recepcion a credito,
    venta con medio de pago 'cuenta corriente', cheque rechazado)."""
    conexion_propia = conn is None
    if conexion_propia:
        conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO cc_cargos
                (cliente_id, proveedor_id, monto, fecha, origen, origen_recepcion_id, origen_venta_id,
                 origen_cheque_id, observacion)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (cliente_id, proveedor_id, monto, fecha, origen, origen_recepcion_id, origen_venta_id,
             origen_cheque_id, observacion),
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
    cheque_id: int | None = None,
    medio_pago_id: int | None = None,
    reemplaza_pago_id: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Crea el pago y sus aplicaciones a cargos en una unica transaccion atomica.
    aplicaciones: [{'cargo_id': int, 'monto': int}, ...] -- ya validadas por el servicio
    (saldo suficiente, suma <= monto del pago). cheque_id: si el pago se hizo/recibio con un
    cheque (Fase 6), para poder rastrear despues con que cheque se salda cada cargo."""
    conexion_propia = conn is None
    if conexion_propia:
        conn = get_connection()
        conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "INSERT INTO cc_pagos (cliente_id, proveedor_id, monto, fecha, observacion, cheque_id, medio_pago_id, "
            "reemplaza_pago_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (cliente_id, proveedor_id, monto, fecha, observacion, cheque_id, medio_pago_id, reemplaza_pago_id),
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


_SELECT_PAGO = """
    SELECT p.*, m.nombre AS medio_nombre
    FROM cc_pagos p
    LEFT JOIN medios_pago m ON m.id = p.medio_pago_id
"""


def obtener_pago_por_id(pago_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(_SELECT_PAGO + " WHERE p.id = ?", (pago_id,)).fetchone()
    finally:
        conn.close()


def listar_pagos(cliente_id: int | None = None, proveedor_id: int | None = None) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        if cliente_id is not None:
            return conn.execute(
                _SELECT_PAGO + " WHERE p.cliente_id = ? ORDER BY p.fecha DESC, p.id DESC", (cliente_id,)
            ).fetchall()
        return conn.execute(
            _SELECT_PAGO + " WHERE p.proveedor_id = ? ORDER BY p.fecha DESC, p.id DESC", (proveedor_id,)
        ).fetchall()
    finally:
        conn.close()


def anular_pago(
    pago_id: int,
    fecha: str,
    motivo: str,
    accion_cheque: str | None = None,
    cheque_observacion: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Marca el pago como anulado (sus aplicaciones dejan de contar en los saldos) y, si se pago
    con un cheque, mueve el cheque en la misma transaccion. accion_cheque: None (no hay cheque),
    'volver_a_cartera' o 'baja' -- ya decidido y validado por el servicio."""
    conexion_propia = conn is None
    if conexion_propia:
        conn = get_connection()
        conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE cc_pagos SET anulado_fecha = ?, anulado_motivo = ? WHERE id = ?", (fecha, motivo, pago_id),
        )
        if accion_cheque is not None:
            cheque_id = conn.execute("SELECT cheque_id FROM cc_pagos WHERE id = ?", (pago_id,)).fetchone()[0]
            if accion_cheque == "volver_a_cartera":
                cheques_repo.volver_a_cartera(cheque_id, conn=conn)
            else:
                cheques_repo.actualizar_estado(cheque_id, estado="baja", observacion=cheque_observacion, conn=conn)
        if conexion_propia:
            conn.commit()
    except Exception:
        if conexion_propia:
            conn.rollback()
        raise
    finally:
        if conexion_propia:
            conn.close()


def reemplazar_pago(
    pago_id: int,
    fecha_anulacion: str,
    motivo: str,
    cliente_id: int | None,
    proveedor_id: int | None,
    monto: int,
    fecha: str,
    observacion: str | None,
    aplicaciones: list[dict],
    medio_pago_id: int | None,
) -> int:
    """Correccion de un pago: anula el viejo y crea el nuevo en una unica transaccion, para que
    nunca quede la cuenta con el pago viejo anulado y sin el nuevo (o con los dos vigentes)."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        anular_pago(pago_id, fecha_anulacion, motivo, conn=conn)
        nuevo_id = crear_pago_con_aplicaciones(
            cliente_id, proveedor_id, monto, fecha, observacion, aplicaciones,
            medio_pago_id=medio_pago_id, reemplaza_pago_id=pago_id, conn=conn,
        )
        conn.commit()
        return nuevo_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def anular_cargo(cargo_id: int, fecha: str, motivo: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE cc_cargos SET anulado_fecha = ?, anulado_motivo = ? WHERE id = ?", (fecha, motivo, cargo_id),
        )
    finally:
        conn.close()


def listar_aplicaciones_de_cargo(cargo_id: int, conn: sqlite3.Connection | None = None) -> list[sqlite3.Row]:
    conexion_propia = conn is None
    if conexion_propia:
        conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT pa.*
            FROM cc_pago_aplicaciones pa
            JOIN cc_pagos p ON p.id = pa.pago_id
            WHERE pa.cargo_id = ? AND p.anulado_fecha IS NULL
            """,
            (cargo_id,),
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
    """Todas las aplicaciones vigentes (de pagos no anulados) de una lista de cargos, en una sola
    consulta (para calcular saldo pendiente de varios cargos sin N+1 queries)."""
    if not cargo_ids:
        return []
    conn = get_connection()
    try:
        marcadores = ",".join("?" * len(cargo_ids))
        return conn.execute(
            f"""
            SELECT pa.*
            FROM cc_pago_aplicaciones pa
            JOIN cc_pagos p ON p.id = pa.pago_id
            WHERE pa.cargo_id IN ({marcadores}) AND p.anulado_fecha IS NULL
            """,
            cargo_ids,
        ).fetchall()
    finally:
        conn.close()
