import sqlite3

from app.db.connection import get_connection
from app.repositories import cc_repo


def crear(
    banco: str,
    librador: str,
    cuit_librador: str | None,
    monto: int,
    fecha_pago: str,
    fecha_recepcion: str,
    origen_tipo: str,
    cliente_id: int | None,
    numero: str | None = None,
    observacion: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Crea un cheque con estado 'en_cartera' (default de la tabla). Para un cheque 'propio' que
    nace directamente entregado a un proveedor, el llamador actualiza el estado despues en la
    misma transaccion (ver actualizar_estado) -- crear() siempre deja el estado inicial."""
    conexion_propia = conn is None
    if conexion_propia:
        conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO cheques
                (numero, banco, librador, cuit_librador, monto, fecha_pago, fecha_recepcion,
                 origen_tipo, cliente_id, observacion)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (numero, banco, librador, cuit_librador, monto, fecha_pago, fecha_recepcion,
             origen_tipo, cliente_id, observacion),
        )
        if conexion_propia:
            conn.commit()
        return cursor.lastrowid
    finally:
        if conexion_propia:
            conn.close()


def actualizar_estado(
    cheque_id: int,
    estado: str,
    observacion: str | None = None,
    proveedor_id: int | None = None,
    cargo_generado_id: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Transicion generica de estado. Solo pisa observacion/proveedor_id/cargo_generado_id cuando
    se pasan explicitamente (None = 'no tocar ese campo'), asi sirve para los 3 casos de salida
    (entregado_proveedor, baja, rechazado) sin tres funciones casi identicas."""
    conexion_propia = conn is None
    if conexion_propia:
        conn = get_connection()
    try:
        campos = ["estado = ?"]
        valores: list = [estado]
        if observacion is not None:
            campos.append("observacion = ?")
            valores.append(observacion)
        if proveedor_id is not None:
            campos.append("proveedor_id = ?")
            valores.append(proveedor_id)
        if cargo_generado_id is not None:
            campos.append("cargo_generado_id = ?")
            valores.append(cargo_generado_id)
        valores.append(cheque_id)
        conn.execute(f"UPDATE cheques SET {', '.join(campos)} WHERE id = ?", valores)
        if conexion_propia:
            conn.commit()
    finally:
        if conexion_propia:
            conn.close()


def rechazar(
    cheque_id: int,
    cliente_id: int | None,
    proveedor_id: int | None,
    monto: int,
    fecha: str,
    observacion: str | None,
) -> dict:
    """Operacion atomica: genera el cargo nuevo que reabre la deuda (cliente si el cheque era
    'recibido_cliente', proveedor si era 'propio') y marca el cheque como 'rechazado', en una
    unica transaccion. Exactamente uno de cliente_id/proveedor_id."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cargo_id = cc_repo.crear_cargo(
            cliente_id=cliente_id,
            proveedor_id=proveedor_id,
            monto=monto,
            fecha=fecha,
            origen="cheque_rechazado",
            origen_recepcion_id=None,
            observacion=observacion,
            origen_cheque_id=cheque_id,
            conn=conn,
        )
        conn.execute(
            "UPDATE cheques SET estado = 'rechazado', observacion = ?, cargo_generado_id = ? WHERE id = ?",
            (observacion, cargo_id, cheque_id),
        )
        conn.commit()
        return {"cargo_id": cargo_id}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def eliminar(cheque_id: int) -> None:
    """Solo para la compensacion cuando crear un cheque funciono pero el paso siguiente (aplicarlo
    a un pago de cuenta corriente) fallo -- nunca se usa para 'dar de baja' un cheque real, eso es
    actualizar_estado(estado='baja')."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM cheques WHERE id = ?", (cheque_id,))
        conn.commit()
    finally:
        conn.close()


def obtener_por_id(cheque_id: int, conn: sqlite3.Connection | None = None) -> sqlite3.Row | None:
    conexion_propia = conn is None
    if conexion_propia:
        conn = get_connection()
    try:
        return conn.execute("SELECT * FROM cheques WHERE id = ?", (cheque_id,)).fetchone()
    finally:
        if conexion_propia:
            conn.close()


def listar(
    estado: str | None = None,
    cliente_id: int | None = None,
    proveedor_id: int | None = None,
    origen_tipo: str | None = None,
) -> list[sqlite3.Row]:
    """ORDER BY fecha_pago ASC: el orden natural para el reporte de 'cheques a cobrar'."""
    conn = get_connection()
    try:
        condiciones = []
        parametros = []
        if estado is not None:
            condiciones.append("estado = ?")
            parametros.append(estado)
        if cliente_id is not None:
            condiciones.append("cliente_id = ?")
            parametros.append(cliente_id)
        if proveedor_id is not None:
            condiciones.append("proveedor_id = ?")
            parametros.append(proveedor_id)
        if origen_tipo is not None:
            condiciones.append("origen_tipo = ?")
            parametros.append(origen_tipo)
        sql = "SELECT * FROM cheques"
        if condiciones:
            sql += " WHERE " + " AND ".join(condiciones)
        sql += " ORDER BY fecha_pago ASC, id ASC"
        return conn.execute(sql, parametros).fetchall()
    finally:
        conn.close()
