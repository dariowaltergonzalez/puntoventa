import sqlite3

from app.db.connection import get_connection
from app.repositories import cc_repo, contadores_repo, movimientos_repo


def _consumir_fifo(conn: sqlite3.Connection, producto_id: int, cantidad_necesaria: int) -> list[dict]:
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


def crear_venta_confirmada(
    cliente_id: int,
    lista_precio_id: int | None,
    fecha: str,
    iva_porcentaje: int | None,
    descuento_total_porcentaje: int | None,
    observacion: str | None,
    items: list[dict],
    pagos: list[dict],
) -> dict:
    """Camino unico y normal de una venta (Fase 4): arma las lineas, consume stock FIFO,
    registra los pagos, y genera cargo en Cuentas Corrientes por cada pago marcado
    'es_cuenta_corriente' -- todo en una unica transaccion atomica.

    items: [{'producto_id': int|None, 'descripcion_libre': str|None, 'cantidad': int,
             'precio_unitario': int, 'descuento_item_porcentaje': int|None}, ...]
    pagos: [{'medio_pago_id': int, 'monto': int, 'es_cuenta_corriente': bool}, ...]
    """
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        numero = contadores_repo.siguiente_numero("venta", "V", conn=conn)
        cursor = conn.execute(
            """
            INSERT INTO ventas
                (numero, cliente_id, lista_precio_id, estado, fecha, fecha_confirmacion,
                 iva_porcentaje, descuento_total_porcentaje, observacion)
            VALUES (?, ?, ?, 'confirmada', ?, ?, ?, ?, ?)
            """,
            (numero, cliente_id, lista_precio_id, fecha, fecha, iva_porcentaje,
             descuento_total_porcentaje, observacion),
        )
        venta_id = cursor.lastrowid

        for item in items:
            cursor_item = conn.execute(
                """
                INSERT INTO venta_items
                    (venta_id, producto_id, descripcion_libre, cantidad, precio_unitario, descuento_item_porcentaje)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (venta_id, item.get("producto_id"), item.get("descripcion_libre"), item["cantidad"],
                 item["precio_unitario"], item.get("descuento_item_porcentaje")),
            )
            venta_item_id = cursor_item.lastrowid

            producto_id = item.get("producto_id")
            if producto_id is not None:
                consumos = _consumir_fifo(conn, producto_id, item["cantidad"])
                for consumo in consumos:
                    conn.execute(
                        "INSERT INTO venta_item_lotes (venta_item_id, lote_id, cantidad, costo_unitario) "
                        "VALUES (?, ?, ?, ?)",
                        (venta_item_id, consumo["lote_id"], consumo["cantidad"], consumo["costo_unitario"]),
                    )
                    movimientos_repo.registrar_movimiento_y_actualizar_stock(
                        producto_id=producto_id,
                        tipo="egreso",
                        cantidad=consumo["cantidad"],
                        motivo="venta",
                        referencia=numero,
                        observacion=f"Venta {numero}",
                        lote_id=consumo["lote_id"],
                        precio_unitario=consumo["costo_unitario"],
                        conn=conn,
                    )

        cargos_generados: list[int] = []
        for pago in pagos:
            conn.execute(
                "INSERT INTO venta_pagos (venta_id, medio_pago_id, monto) VALUES (?, ?, ?)",
                (venta_id, pago["medio_pago_id"], pago["monto"]),
            )
            if pago.get("es_cuenta_corriente"):
                cargo_id = cc_repo.crear_cargo(
                    cliente_id=cliente_id,
                    proveedor_id=None,
                    monto=pago["monto"],
                    fecha=fecha,
                    origen="venta",
                    origen_recepcion_id=None,
                    observacion=f"Venta a credito - {numero}",
                    origen_venta_id=venta_id,
                    conn=conn,
                )
                cargos_generados.append(cargo_id)

        conn.commit()
        return {"venta_id": venta_id, "numero": numero, "cargos_generados": cargos_generados}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def obtener_por_id(venta_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
    finally:
        conn.close()


def obtener_por_numero(numero: str) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM ventas WHERE numero = ?", (numero,)).fetchone()
    finally:
        conn.close()


def listar_items(venta_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT vi.*, p.codigo AS producto_codigo, p.nombre AS producto_nombre
            FROM venta_items vi
            LEFT JOIN productos p ON p.id = vi.producto_id
            WHERE vi.venta_id = ?
            ORDER BY vi.id
            """,
            (venta_id,),
        ).fetchall()
    finally:
        conn.close()


def listar_lotes_de_item(venta_item_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM venta_item_lotes WHERE venta_item_id = ? ORDER BY id", (venta_item_id,)
        ).fetchall()
    finally:
        conn.close()


def listar_pagos(venta_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT vp.*, mp.nombre AS medio_pago_nombre, mp.es_cuenta_corriente
            FROM venta_pagos vp
            JOIN medios_pago mp ON mp.id = vp.medio_pago_id
            WHERE vp.venta_id = ?
            ORDER BY vp.id
            """,
            (venta_id,),
        ).fetchall()
    finally:
        conn.close()


def listar(estado: str | None = None, cliente_id: int | None = None) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        condiciones = []
        parametros = []
        if estado:
            condiciones.append("estado = ?")
            parametros.append(estado)
        if cliente_id is not None:
            condiciones.append("cliente_id = ?")
            parametros.append(cliente_id)
        sql = "SELECT * FROM ventas"
        if condiciones:
            sql += " WHERE " + " AND ".join(condiciones)
        sql += " ORDER BY fecha DESC, id DESC"
        return conn.execute(sql, parametros).fetchall()
    finally:
        conn.close()
