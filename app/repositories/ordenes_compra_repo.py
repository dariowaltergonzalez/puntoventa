import sqlite3

from app.db.connection import get_connection
from app.repositories import contadores_repo, recepciones_repo


def crear(
    proveedor_id: int,
    fecha_creacion: str,
    fecha_estimada: str | None,
    iva_porcentaje: int | None,
    observacion: str | None,
    items: list[dict],
    estado: str = "pendiente",
    conn: sqlite3.Connection | None = None,
) -> dict:
    """items: [{'producto_id': int|None, 'descripcion_libre': str|None, 'cantidad_pedida': int,
    'costo_pactado': int}] -- exactamente uno de producto_id/descripcion_libre por linea."""
    conexion_propia = conn is None
    if conexion_propia:
        conn = get_connection()
        conn.execute("BEGIN IMMEDIATE")
    try:
        numero = contadores_repo.siguiente_numero("orden_compra", "OC", conn=conn)
        cursor = conn.execute(
            """
            INSERT INTO ordenes_compra
                (numero, proveedor_id, estado, fecha_creacion, fecha_estimada, iva_porcentaje, observacion)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (numero, proveedor_id, estado, fecha_creacion, fecha_estimada, iva_porcentaje, observacion),
        )
        orden_compra_id = cursor.lastrowid
        for item in items:
            conn.execute(
                """
                INSERT INTO orden_compra_items
                    (orden_compra_id, producto_id, descripcion_libre, cantidad_pedida, costo_pactado, cantidad_recibida)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (orden_compra_id, item.get("producto_id"), item.get("descripcion_libre"),
                 item["cantidad_pedida"], item["costo_pactado"]),
            )
        if conexion_propia:
            conn.commit()
        return {"id": orden_compra_id, "numero": numero}
    except Exception:
        if conexion_propia:
            conn.rollback()
        raise
    finally:
        if conexion_propia:
            conn.close()


def crear_con_recepcion_inmediata(
    proveedor_id: int,
    fecha_creacion: str,
    fecha_estimada: str | None,
    iva_porcentaje: int | None,
    observacion: str | None,
    items: list[dict],
    recepcion_fecha: str,
    recepcion_numero_remito: str | None,
    recepcion_observacion: str | None,
    items_recepcion: list[dict],
) -> dict:
    """Checkbox '¿Ya la tenes en mano?': crea la OC y la recibe en el MISMO commit, reutilizando
    recepciones_repo.aplicar_recepcion -- no es un camino de codigo paralelo.

    `items_recepcion` debe tener la MISMA cantidad de lineas que `items`, en el mismo orden
    (son las mismas lineas pre-pobladas, con la cantidad recibida editable) -- se vinculan
    automaticamente por posicion a las orden_compra_items recien creadas."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        oc = crear(
            proveedor_id, fecha_creacion, fecha_estimada, iva_porcentaje, observacion,
            items, estado="pendiente", conn=conn,
        )
        items_oc_creados = conn.execute(
            "SELECT id FROM orden_compra_items WHERE orden_compra_id = ? ORDER BY id", (oc["id"],)
        ).fetchall()
        for item_recepcion, item_oc in zip(items_recepcion, items_oc_creados):
            item_recepcion["orden_compra_item_id"] = item_oc["id"]

        resultado = recepciones_repo.aplicar_recepcion(
            conn, oc["id"], recepcion_fecha, recepcion_numero_remito, recepcion_observacion, items_recepcion
        )
        conn.commit()
        return {"orden_compra_id": oc["id"], "numero": oc["numero"], **resultado}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def actualizar_cabecera_y_items(
    orden_compra_id: int,
    proveedor_id: int,
    fecha_estimada: str | None,
    iva_porcentaje: int | None,
    observacion: str | None,
    items: list[dict],
) -> None:
    """Solo debe llamarse si el servicio ya valido que la OC esta 'pendiente' y sin recepciones."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE ordenes_compra
            SET proveedor_id = ?, fecha_estimada = ?, iva_porcentaje = ?, observacion = ?
            WHERE id = ?
            """,
            (proveedor_id, fecha_estimada, iva_porcentaje, observacion, orden_compra_id),
        )
        conn.execute("DELETE FROM orden_compra_items WHERE orden_compra_id = ?", (orden_compra_id,))
        for item in items:
            conn.execute(
                """
                INSERT INTO orden_compra_items
                    (orden_compra_id, producto_id, descripcion_libre, cantidad_pedida, costo_pactado, cantidad_recibida)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (orden_compra_id, item.get("producto_id"), item.get("descripcion_libre"),
                 item["cantidad_pedida"], item["costo_pactado"]),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cancelar(orden_compra_id: int, observacion: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE ordenes_compra SET estado = 'cancelada', observacion = ? WHERE id = ?",
            (observacion, orden_compra_id),
        )
    finally:
        conn.close()


def marcar_recibida_manualmente(orden_compra_id: int, observacion: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE ordenes_compra SET estado = 'recibida', observacion = ? WHERE id = ?",
            (observacion, orden_compra_id),
        )
    finally:
        conn.close()


def tiene_recepciones(orden_compra_id: int) -> bool:
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT 1 FROM recepciones WHERE orden_compra_id = ? LIMIT 1", (orden_compra_id,)
        ).fetchone()
        return fila is not None
    finally:
        conn.close()


def obtener_por_id(orden_compra_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM ordenes_compra WHERE id = ?", (orden_compra_id,)).fetchone()
    finally:
        conn.close()


def listar(estado: str | None = None) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        sql = "SELECT * FROM ordenes_compra"
        parametros = []
        if estado:
            sql += " WHERE estado = ?"
            parametros.append(estado)
        sql += " ORDER BY fecha_creacion DESC, id DESC"
        return conn.execute(sql, parametros).fetchall()
    finally:
        conn.close()


def listar_items(orden_compra_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT oci.*, p.codigo AS producto_codigo, p.nombre AS producto_nombre
            FROM orden_compra_items oci
            LEFT JOIN productos p ON p.id = oci.producto_id
            WHERE oci.orden_compra_id = ?
            ORDER BY oci.id
            """,
            (orden_compra_id,),
        ).fetchall()
    finally:
        conn.close()
