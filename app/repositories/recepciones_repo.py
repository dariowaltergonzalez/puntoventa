import sqlite3

from app.db.connection import get_connection
from app.repositories import movimientos_repo

NOMBRE_CATEGORIA_SIN_CATEGORIZAR = "Sin categorizar"
UNIDAD_PLACEHOLDER = "unidad"


def confirmar_recepcion(
    orden_compra_id: int,
    fecha: str,
    numero_remito: str | None,
    observacion: str | None,
    items: list[dict],
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Punto de entrada publico para el camino normal (OC ya pendiente, se recibe despues).
    Abre y cierra su propia transaccion si conn es None."""
    conexion_propia = conn is None
    if conexion_propia:
        conn = get_connection()
        conn.execute("BEGIN IMMEDIATE")
    try:
        resultado = aplicar_recepcion(conn, orden_compra_id, fecha, numero_remito, observacion, items)
        if conexion_propia:
            conn.commit()
        return resultado
    except Exception:
        if conexion_propia:
            conn.rollback()
        raise
    finally:
        if conexion_propia:
            conn.close()


def aplicar_recepcion(
    conn: sqlite3.Connection,
    orden_compra_id: int,
    fecha: str,
    numero_remito: str | None,
    observacion: str | None,
    items: list[dict],
) -> dict:
    """Nucleo reutilizable: asume que conn YA tiene una transaccion BEGIN IMMEDIATE abierta
    (propia, de confirmar_recepcion, o de ordenes_compra_repo.crear_con_recepcion_inmediata).
    No hace commit/rollback -- eso es responsabilidad de quien abrio la transaccion.

    items: lista de dicts ya validados/escalados por el servicio:
        {
            'orden_compra_item_id': int | None,
            'producto_id': int | None,                       # producto existente
            'producto_nuevo': {'codigo', 'nombre', 'categoria_id': int|None} | None,  # alta al vuelo
            'descripcion_libre': str | None,                  # item libre, sin stock ni catalogo
            'cantidad_recibida': int,                          # escalado x1000
            'costo_unitario': int,                             # escalado x100
        }
    Exactamente uno de producto_id / producto_nuevo / descripcion_libre viene cargado por linea.
    """
    cursor = conn.execute(
        "INSERT INTO recepciones (orden_compra_id, fecha, numero_remito, observacion) VALUES (?, ?, ?, ?)",
        (orden_compra_id, fecha, numero_remito, observacion),
    )
    recepcion_id = cursor.lastrowid

    fila_oc = conn.execute(
        "SELECT numero, proveedor_id FROM ordenes_compra WHERE id = ?", (orden_compra_id,)
    ).fetchone()
    numero_oc = fila_oc["numero"]
    proveedor_id_oc = fila_oc["proveedor_id"]

    productos_creados: list[int] = []

    for item in items:
        orden_compra_item_id = item.get("orden_compra_item_id")
        cantidad = item["cantidad_recibida"]
        costo_unitario = item["costo_unitario"]
        descripcion_libre = item.get("descripcion_libre")

        if descripcion_libre is not None:
            conn.execute(
                """
                INSERT INTO recepcion_items
                    (recepcion_id, orden_compra_item_id, producto_id, descripcion_libre,
                     cantidad_recibida, costo_unitario, lote_id)
                VALUES (?, ?, NULL, ?, ?, ?, NULL)
                """,
                (recepcion_id, orden_compra_item_id, descripcion_libre, cantidad, costo_unitario),
            )
            if orden_compra_item_id is not None:
                conn.execute(
                    "UPDATE orden_compra_items SET cantidad_recibida = cantidad_recibida + ? WHERE id = ?",
                    (cantidad, orden_compra_item_id),
                )
            continue

        producto_id = item.get("producto_id")
        if producto_id is None:
            producto_id = crear_producto_minimo(conn, item["producto_nuevo"], costo_unitario, proveedor_id_oc)
            productos_creados.append(producto_id)

        cursor_lote = conn.execute(
            """
            INSERT INTO lotes (producto_id, recepcion_id, cantidad_recibida, cantidad_restante, costo_unitario, fecha)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (producto_id, recepcion_id, cantidad, cantidad, costo_unitario, fecha),
        )
        lote_id = cursor_lote.lastrowid

        conn.execute(
            """
            INSERT INTO recepcion_items
                (recepcion_id, orden_compra_item_id, producto_id, descripcion_libre,
                 cantidad_recibida, costo_unitario, lote_id)
            VALUES (?, ?, ?, NULL, ?, ?, ?)
            """,
            (recepcion_id, orden_compra_item_id, producto_id, cantidad, costo_unitario, lote_id),
        )

        observacion_mov = f"Recepcion de {numero_oc}" + (f" (remito {numero_remito})" if numero_remito else "")
        movimientos_repo.registrar_movimiento_y_actualizar_stock(
            producto_id=producto_id,
            tipo="ingreso",
            cantidad=cantidad,
            motivo="compra",
            referencia=numero_oc,
            observacion=observacion_mov,
            lote_id=lote_id,
            precio_unitario=costo_unitario,
            conn=conn,
        )

        if orden_compra_item_id is not None:
            conn.execute(
                "UPDATE orden_compra_items SET cantidad_recibida = cantidad_recibida + ? WHERE id = ?",
                (cantidad, orden_compra_item_id),
            )

    nuevo_estado = _recalcular_estado_oc(conn, orden_compra_id)

    return {
        "recepcion_id": recepcion_id,
        "orden_compra_id": orden_compra_id,
        "numero_orden_compra": numero_oc,
        "estado_orden_compra": nuevo_estado,
        "productos_creados": productos_creados,
    }


def crear_producto_minimo(conn: sqlite3.Connection, datos: dict, costo_unitario: int, proveedor_id: int | None) -> int:
    categoria_id = datos.get("categoria_id")
    if categoria_id is None:
        categoria_id = _obtener_o_crear_categoria_placeholder(conn)
    cursor = conn.execute(
        """
        INSERT INTO productos
            (codigo, nombre, categoria_id, unidad, precio_costo, precio_venta,
             activo, stock_actual, stock_minimo, proveedor_id)
        VALUES (?, ?, ?, ?, ?, 0, 1, 0, 0, ?)
        """,
        (datos["codigo"], datos["nombre"], categoria_id, UNIDAD_PLACEHOLDER, costo_unitario, proveedor_id),
    )
    return cursor.lastrowid


def _obtener_o_crear_categoria_placeholder(conn: sqlite3.Connection) -> int:
    conn.execute(
        "INSERT INTO categorias (nombre) VALUES (?) ON CONFLICT(nombre) DO NOTHING",
        (NOMBRE_CATEGORIA_SIN_CATEGORIZAR,),
    )
    return conn.execute(
        "SELECT id FROM categorias WHERE nombre = ?", (NOMBRE_CATEGORIA_SIN_CATEGORIZAR,)
    ).fetchone()["id"]


def _recalcular_estado_oc(conn: sqlite3.Connection, orden_compra_id: int) -> str:
    """'recibida' si TODAS las lineas pedidas tienen cantidad_recibida >= cantidad_pedida.
    Si no, 'recibida_parcial' -- alcanza con que exista una recepcion contra la OC (la que se
    acaba de insertar), toque o no lineas pedidas."""
    filas = conn.execute(
        "SELECT cantidad_pedida, cantidad_recibida FROM orden_compra_items WHERE orden_compra_id = ?",
        (orden_compra_id,),
    ).fetchall()
    if filas and all(f["cantidad_recibida"] >= f["cantidad_pedida"] for f in filas):
        nuevo_estado = "recibida"
    else:
        nuevo_estado = "recibida_parcial"
    conn.execute("UPDATE ordenes_compra SET estado = ? WHERE id = ?", (nuevo_estado, orden_compra_id))
    return nuevo_estado


def obtener_por_id(recepcion_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM recepciones WHERE id = ?", (recepcion_id,)).fetchone()
    finally:
        conn.close()


def listar_items(recepcion_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT ri.*, p.codigo AS producto_codigo, p.nombre AS producto_nombre
            FROM recepcion_items ri
            LEFT JOIN productos p ON p.id = ri.producto_id
            WHERE ri.recepcion_id = ?
            ORDER BY ri.id
            """,
            (recepcion_id,),
        ).fetchall()
    finally:
        conn.close()


def listar_por_orden(orden_compra_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM recepciones WHERE orden_compra_id = ? ORDER BY fecha, id", (orden_compra_id,)
        ).fetchall()
    finally:
        conn.close()


def listar_items_por_orden_compra(orden_compra_id: int) -> list[sqlite3.Row]:
    """Todas las lineas de TODAS las recepciones de esta OC (de cualquier recepcion),
    para poder calcular el costo real pagado por cada linea pedida (una linea puede
    haberse recibido en mas de una tanda, a costos distintos)."""
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT ri.*
            FROM recepcion_items ri
            JOIN recepciones r ON r.id = ri.recepcion_id
            WHERE r.orden_compra_id = ? AND ri.orden_compra_item_id IS NOT NULL
            """,
            (orden_compra_id,),
        ).fetchall()
    finally:
        conn.close()
