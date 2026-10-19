import sqlite3

from app.db.connection import get_connection
from app.repositories import cc_repo, cheques_repo, contadores_repo, movimientos_repo
from app.repositories.paginacion import paginar


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
    descuento_cliente_porcentaje: int | None = None,
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
                 iva_porcentaje, descuento_total_porcentaje, descuento_cliente_porcentaje, observacion)
            VALUES (?, ?, ?, 'confirmada', ?, ?, ?, ?, ?, ?)
            """,
            (numero, cliente_id, lista_precio_id, fecha, fecha, iva_porcentaje,
             descuento_total_porcentaje, descuento_cliente_porcentaje, observacion),
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
            cheque_id = None
            datos_cheque = pago.get("cheque")
            if datos_cheque is not None:
                cheque_id = cheques_repo.crear(
                    banco=datos_cheque["banco"],
                    librador=datos_cheque["librador"],
                    cuit_librador=datos_cheque.get("cuit_librador"),
                    monto=pago["monto"],
                    fecha_pago=datos_cheque["fecha_pago"],
                    fecha_recepcion=fecha,
                    origen_tipo="recibido_cliente",
                    cliente_id=cliente_id,
                    numero=datos_cheque.get("numero"),
                    observacion=datos_cheque.get("observacion"),
                    conn=conn,
                )
            conn.execute(
                "INSERT INTO venta_pagos (venta_id, medio_pago_id, monto, recibido, cheque_id) VALUES (?, ?, ?, ?, ?)",
                (venta_id, pago["medio_pago_id"], pago["monto"], pago.get("recibido"), cheque_id),
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


def listar_pagina(
    pagina: int, tamano_pagina: int, texto: str | None = None,
    estado: str | None = None, cliente_id: int | None = None,
) -> tuple[list[sqlite3.Row], int]:
    """Version paginada de `listar` -- esa trae TODAS las ventas de la historia del negocio
    sin limite; esta solo pide la pagina pedida. 'texto' busca por numero de venta o razon
    social del cliente (de ahi el JOIN, que 'listar' no necesita)."""
    conn = get_connection()
    try:
        condiciones = []
        parametros = []
        if estado:
            condiciones.append("v.estado = ?")
            parametros.append(estado)
        if cliente_id is not None:
            condiciones.append("v.cliente_id = ?")
            parametros.append(cliente_id)
        if texto:
            condiciones.append("(v.numero LIKE ? OR c.razon_social LIKE ?)")
            comodin = f"%{texto}%"
            parametros.extend([comodin, comodin])

        sql = "SELECT v.* FROM ventas v LEFT JOIN clientes c ON c.id = v.cliente_id"
        if condiciones:
            sql += " WHERE " + " AND ".join(condiciones)
        sql += " ORDER BY v.fecha DESC, v.id DESC"

        return paginar(conn, sql, parametros, pagina, tamano_pagina)
    finally:
        conn.close()


# ================= Notas de credito =================
def _devolver_a_lotes(conn: sqlite3.Connection, venta_item_id: int, cantidad: int) -> list[dict]:
    """Devuelve 'cantidad' (escalado x1000) a los mismos lotes de los que salio esa linea en la
    venta, con su costo original, sin pasarse de lo que cada lote le dio (descontando lo que
    otras notas de credito ya devolvieron a ese lote). Empieza por el ultimo lote consumido."""
    consumidos = conn.execute(
        "SELECT lote_id, cantidad, costo_unitario FROM venta_item_lotes WHERE venta_item_id = ? ORDER BY id DESC",
        (venta_item_id,),
    ).fetchall()
    ya_devuelto = {
        fila["lote_id"]: fila["devuelto"]
        for fila in conn.execute(
            """
            SELECT ncl.lote_id, SUM(ncl.cantidad) AS devuelto
            FROM nota_credito_item_lotes ncl
            JOIN nota_credito_items nci ON nci.id = ncl.nota_credito_item_id
            WHERE nci.venta_item_id = ?
            GROUP BY ncl.lote_id
            """,
            (venta_item_id,),
        ).fetchall()
    }
    devoluciones = []
    restante = cantidad
    for consumo in consumidos:
        if restante <= 0:
            break
        disponible = consumo["cantidad"] - ya_devuelto.get(consumo["lote_id"], 0)
        if disponible <= 0:
            continue
        devolver = min(restante, disponible)
        conn.execute("UPDATE lotes SET cantidad_restante = cantidad_restante + ? WHERE id = ?",
                     (devolver, consumo["lote_id"]))
        devoluciones.append({"lote_id": consumo["lote_id"], "cantidad": devolver, "costo_unitario": consumo["costo_unitario"]})
        restante -= devolver
    if restante > 0:
        raise RuntimeError(f"No hay lotes de la venta para devolver {restante} de la linea {venta_item_id}")
    return devoluciones


def crear_nota_credito(
    venta_id: int,
    cliente_id: int,
    fecha: str,
    motivo: str,
    es_correccion: bool,
    items: list[dict],
    reintegros: list[dict],
) -> dict:
    """Todo en una unica transaccion: la nota de credito, sus lineas, la mercaderia que vuelve a
    los lotes (con su movimiento de stock), y el reintegro de la plata. Ya validado por el
    servicio.

    items: [{'venta_item_id', 'producto_id' (None si item libre), 'cantidad' (x1000), 'vuelve_stock'}]
    reintegros: [{'tipo': 'cuenta_corriente', 'monto', 'aplicaciones': [{'cargo_id', 'monto'}]}
                 | {'tipo': 'medio_pago', 'monto', 'medio_pago_id'}
                 | {'tipo': 'cheque', 'monto', 'cheque_id', 'cheque_observacion'}]  (montos x100)
    """
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        numero = contadores_repo.siguiente_numero("nota_credito", "NC", conn=conn)
        nota_credito_id = conn.execute(
            "INSERT INTO notas_credito (numero, venta_id, cliente_id, fecha, motivo, es_correccion) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (numero, venta_id, cliente_id, fecha, motivo, int(es_correccion)),
        ).lastrowid

        for item in items:
            nc_item_id = conn.execute(
                "INSERT INTO nota_credito_items (nota_credito_id, venta_item_id, cantidad, vuelve_stock) "
                "VALUES (?, ?, ?, ?)",
                (nota_credito_id, item["venta_item_id"], item["cantidad"], int(item["vuelve_stock"])),
            ).lastrowid
            if item["producto_id"] is None or not item["vuelve_stock"]:
                continue
            for devolucion in _devolver_a_lotes(conn, item["venta_item_id"], item["cantidad"]):
                conn.execute(
                    "INSERT INTO nota_credito_item_lotes (nota_credito_item_id, lote_id, cantidad, costo_unitario) "
                    "VALUES (?, ?, ?, ?)",
                    (nc_item_id, devolucion["lote_id"], devolucion["cantidad"], devolucion["costo_unitario"]),
                )
                movimientos_repo.registrar_movimiento_y_actualizar_stock(
                    producto_id=item["producto_id"],
                    tipo="ingreso",
                    cantidad=devolucion["cantidad"],
                    motivo="devolucion",
                    referencia=numero,
                    observacion=f"Devolucion - nota de credito {numero}",
                    lote_id=devolucion["lote_id"],
                    precio_unitario=devolucion["costo_unitario"],
                    conn=conn,
                )

        for reintegro in reintegros:
            cc_pago_id = None
            if reintegro["tipo"] == "cuenta_corriente":
                cc_pago_id = cc_repo.crear_pago_con_aplicaciones(
                    cliente_id=cliente_id, proveedor_id=None, monto=reintegro["monto"], fecha=fecha,
                    observacion=f"Nota de credito {numero}", aplicaciones=reintegro["aplicaciones"],
                    nota_credito_id=nota_credito_id, conn=conn,
                )
            elif reintegro["tipo"] == "cheque":
                cheques_repo.actualizar_estado(
                    reintegro["cheque_id"], estado="baja", observacion=reintegro["cheque_observacion"], conn=conn,
                )
            conn.execute(
                "INSERT INTO nota_credito_reintegros (nota_credito_id, tipo, monto, medio_pago_id, cheque_id, cc_pago_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (nota_credito_id, reintegro["tipo"], reintegro["monto"], reintegro.get("medio_pago_id"),
                 reintegro.get("cheque_id"), cc_pago_id),
            )

        conn.commit()
        return {"nota_credito_id": nota_credito_id, "numero": numero}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def obtener_nota_credito(nota_credito_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM notas_credito WHERE id = ?", (nota_credito_id,)).fetchone()
    finally:
        conn.close()


def listar_notas_credito_de_venta(venta_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM notas_credito WHERE venta_id = ? ORDER BY fecha, id", (venta_id,)
        ).fetchall()
    finally:
        conn.close()


def listar_items_nota_credito(nota_credito_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT nci.*, vi.producto_id, vi.descripcion_libre, vi.precio_unitario, vi.descuento_item_porcentaje,
                   p.codigo AS producto_codigo, p.nombre AS producto_nombre
            FROM nota_credito_items nci
            JOIN venta_items vi ON vi.id = nci.venta_item_id
            LEFT JOIN productos p ON p.id = vi.producto_id
            WHERE nci.nota_credito_id = ?
            ORDER BY nci.id
            """,
            (nota_credito_id,),
        ).fetchall()
    finally:
        conn.close()


def listar_lotes_de_item_nota_credito(nota_credito_item_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM nota_credito_item_lotes WHERE nota_credito_item_id = ? ORDER BY id", (nota_credito_item_id,)
        ).fetchall()
    finally:
        conn.close()


def listar_reintegros(nota_credito_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT r.*, mp.nombre AS medio_pago_nombre, ch.banco AS cheque_banco, ch.numero AS cheque_numero
            FROM nota_credito_reintegros r
            LEFT JOIN medios_pago mp ON mp.id = r.medio_pago_id
            LEFT JOIN cheques ch ON ch.id = r.cheque_id
            WHERE r.nota_credito_id = ?
            ORDER BY r.id
            """,
            (nota_credito_id,),
        ).fetchall()
    finally:
        conn.close()


def cantidades_devueltas_por_item(venta_id: int) -> dict[int, int]:
    """{venta_item_id: cantidad ya acreditada (x1000), sumando todas las notas de credito}."""
    conn = get_connection()
    try:
        filas = conn.execute(
            """
            SELECT nci.venta_item_id, SUM(nci.cantidad) AS devuelto
            FROM nota_credito_items nci
            JOIN venta_items vi ON vi.id = nci.venta_item_id
            WHERE vi.venta_id = ?
            GROUP BY nci.venta_item_id
            """,
            (venta_id,),
        ).fetchall()
        return {f["venta_item_id"]: f["devuelto"] for f in filas}
    finally:
        conn.close()
