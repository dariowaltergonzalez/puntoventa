import sqlite3

from app.db.connection import get_connection


def obtener_por_id(lote_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM lotes WHERE id = ?", (lote_id,)).fetchone()
    finally:
        conn.close()


def listar_por_producto(producto_id: int, solo_con_stock: bool = False) -> list[sqlite3.Row]:
    """ORDER BY fecha ASC, id ASC: es el orden que va a necesitar el consumo FIFO en Fase 4."""
    conn = get_connection()
    try:
        sql = "SELECT * FROM lotes WHERE producto_id = ?"
        parametros = [producto_id]
        if solo_con_stock:
            sql += " AND cantidad_restante > 0"
        sql += " ORDER BY fecha ASC, id ASC"
        return conn.execute(sql, parametros).fetchall()
    finally:
        conn.close()


def listar_por_recepcion(recepcion_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM lotes WHERE recepcion_id = ? ORDER BY id", (recepcion_id,)).fetchall()
    finally:
        conn.close()


def listar_por_producto_con_oc(producto_id: int, solo_con_stock: bool = False) -> list[sqlite3.Row]:
    """Igual que listar_por_producto pero trae tambien de que OC/remito vino cada lote,
    para mostrar el detalle en pantalla (Stock)."""
    conn = get_connection()
    try:
        sql = """
            SELECT l.*, r.numero_remito, oc.numero AS numero_oc
            FROM lotes l
            LEFT JOIN recepciones r ON r.id = l.recepcion_id
            LEFT JOIN ordenes_compra oc ON oc.id = r.orden_compra_id
            WHERE l.producto_id = ?
        """
        parametros = [producto_id]
        if solo_con_stock:
            sql += " AND l.cantidad_restante > 0"
        sql += " ORDER BY l.fecha ASC, l.id ASC"
        return conn.execute(sql, parametros).fetchall()
    finally:
        conn.close()


def consumir_fifo(conn: sqlite3.Connection, producto_id: int, cantidad_necesaria: int) -> list[dict]:
    """Consume lotes en orden FIFO (fecha ASC, id ASC) hasta cubrir cantidad_necesaria (escalado
    x1000), descontando cantidad_restante en cada uno. Devuelve el detalle de que lote(s) se
    tocaron y a que costo. Asume que la capa de servicio ya valido que hay stock suficiente --
    si de todas formas no alcanza (bug o carrera), rompe fuerte en vez de vender fantasma."""
    lotes = conn.execute(
        "SELECT id, cantidad_restante, costo_unitario FROM lotes "
        "WHERE producto_id = ? AND cantidad_restante > 0 ORDER BY fecha ASC, id ASC",
        (producto_id,),
    ).fetchall()
    consumos = []
    restante = cantidad_necesaria
    for lote in lotes:
        if restante <= 0:
            break
        tomar = min(restante, lote["cantidad_restante"])
        conn.execute(
            "UPDATE lotes SET cantidad_restante = cantidad_restante - ? WHERE id = ?", (tomar, lote["id"]),
        )
        consumos.append({"lote_id": lote["id"], "cantidad": tomar, "costo_unitario": lote["costo_unitario"]})
        restante -= tomar
    if restante > 0:
        raise RuntimeError(f"Stock insuficiente en lotes para producto {producto_id}: faltan {restante}")
    return consumos


def crear_lote(
    conn: sqlite3.Connection, producto_id: int, origen: str, cantidad: int, costo_unitario: int, fecha: str,
) -> int:
    """Lote sin recepcion detras (origen 'inicial' o 'ajuste'): el stock que entra por un ajuste
    manual tambien tiene que tener lote y costo, si no la proxima venta no sabe de donde salio."""
    return conn.execute(
        "INSERT INTO lotes (producto_id, recepcion_id, origen, cantidad_recibida, cantidad_restante, costo_unitario, fecha) "
        "VALUES (?, NULL, ?, ?, ?, ?, ?)",
        (producto_id, origen, cantidad, cantidad, costo_unitario, fecha),
    ).lastrowid


def obtener_ultimo_costo(producto_id: int) -> int | None:
    """Costo (x100) del lote mas reciente del producto, None si nunca tuvo lotes."""
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT costo_unitario FROM lotes WHERE producto_id = ? ORDER BY fecha DESC, id DESC LIMIT 1", (producto_id,)
        ).fetchone()
        return fila["costo_unitario"] if fila else None
    finally:
        conn.close()



def simular_costo_fifo(producto_id: int, cantidad: int, saltear: int = 0) -> int:
    """Costo (x100000: cantidad x1000 * costo x100) que tendria vender 'cantidad' HOY, recorriendo
    los lotes en orden FIFO SIN consumirlos -- para la ganancia estimada de un presupuesto o de un
    carrito. 'saltear': lo que otras lineas del mismo producto ya 'tomaron' antes en la simulacion.
    Si el stock no alcanza, lo que falta se valoriza al costo del lote mas reciente (o al precio de
    costo de la ficha si el producto nunca tuvo lotes)."""
    conn = get_connection()
    try:
        lotes = conn.execute(
            "SELECT cantidad_restante, costo_unitario FROM lotes "
            "WHERE producto_id = ? AND cantidad_restante > 0 ORDER BY fecha ASC, id ASC",
            (producto_id,),
        ).fetchall()
        costo, restante = 0, cantidad
        for lote in lotes:
            disponible = lote["cantidad_restante"]
            if saltear >= disponible:
                saltear -= disponible
                continue
            disponible -= saltear
            saltear = 0
            tomar = min(restante, disponible)
            costo += tomar * lote["costo_unitario"]
            restante -= tomar
            if restante == 0:
                return costo
        ultimo = conn.execute(
            "SELECT costo_unitario FROM lotes WHERE producto_id = ? ORDER BY fecha DESC, id DESC LIMIT 1", (producto_id,)
        ).fetchone()
        if ultimo is None:
            ultimo = conn.execute("SELECT precio_costo AS costo_unitario FROM productos WHERE id = ?", (producto_id,)).fetchone()
        return costo + restante * ultimo["costo_unitario"]
    finally:
        conn.close()
