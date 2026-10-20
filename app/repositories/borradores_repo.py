import sqlite3
from datetime import datetime

from app.db.connection import get_connection
from app.repositories import contadores_repo

CAMPOS_BORRADOR = (
    "nombre", "cliente_id", "cliente_nombre_nuevo", "usar_cliente_generico", "lista_precio_id",
    "iva_porcentaje", "descuento_total_porcentaje", "observacion", "fecha_validez", "descuento_cliente_porcentaje",
    "precios_con_iva",
)


def guardar(tipo: str, borrador_id: int | None, datos: dict, items: list[dict]) -> int:
    """Alta o actualizacion de un borrador con todas sus lineas, en una unica transaccion (las
    lineas se reemplazan enteras: es un carrito, no hay historia de lineas que conservar).
    items: [{'producto_id', 'descripcion_libre', 'cantidad', 'precio_unitario', 'descuento_item_porcentaje'}]"""
    ahora = datetime.now().isoformat()
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        valores = [datos[c] for c in CAMPOS_BORRADOR]
        if borrador_id is None:
            # Los presupuestos llevan numero propio (P-0001); las pre-ventas no.
            numero = contadores_repo.siguiente_numero("presupuesto", "P", conn=conn) if tipo == "presupuesto" else None
            borrador_id = conn.execute(
                f"INSERT INTO borradores_venta (tipo, numero, {', '.join(CAMPOS_BORRADOR)}, fecha_creacion, fecha_actualizacion) "
                f"VALUES (?, ?, {', '.join('?' * len(CAMPOS_BORRADOR))}, ?, ?)",
                (tipo, numero, *valores, ahora, ahora),
            ).lastrowid
        else:
            conn.execute(
                f"UPDATE borradores_venta SET {', '.join(f'{c} = ?' for c in CAMPOS_BORRADOR)}, fecha_actualizacion = ? "
                "WHERE id = ?",
                (*valores, ahora, borrador_id),
            )
            conn.execute("DELETE FROM borrador_venta_items WHERE borrador_id = ?", (borrador_id,))
        for item in items:
            conn.execute(
                "INSERT INTO borrador_venta_items (borrador_id, producto_id, descripcion_libre, cantidad, "
                "precio_unitario, descuento_item_porcentaje, precio_manual) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (borrador_id, item["producto_id"], item["descripcion_libre"], item["cantidad"],
                 item["precio_unitario"], item["descuento_item_porcentaje"], int(item.get("precio_manual", 0))),
            )
        conn.commit()
        return borrador_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def actualizar_precios_items(borrador_id: int, cambios: list[dict]) -> None:
    """cambios: [{'item_id', 'precio_unitario' (x100), 'precio_manual' (bool)}], en una transaccion."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for cambio in cambios:
            conn.execute(
                "UPDATE borrador_venta_items SET precio_unitario = ?, precio_manual = ? WHERE id = ? AND borrador_id = ?",
                (cambio["precio_unitario"], int(cambio["precio_manual"]), cambio["item_id"], borrador_id),
            )
        conn.execute("UPDATE borradores_venta SET fecha_actualizacion = ? WHERE id = ?", (datetime.now().isoformat(), borrador_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def obtener(borrador_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM borradores_venta WHERE id = ?", (borrador_id,)).fetchone()
    finally:
        conn.close()


def listar_items(borrador_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT bi.*, p.codigo AS producto_codigo, p.nombre AS producto_nombre
            FROM borrador_venta_items bi LEFT JOIN productos p ON p.id = bi.producto_id
            WHERE bi.borrador_id = ? ORDER BY bi.id
            """,
            (borrador_id,),
        ).fetchall()
    finally:
        conn.close()


def listar(tipo: str, estado: str, desde: str) -> list[sqlite3.Row]:
    """Borradores de un tipo y estado creados desde una fecha (ISO), los mas nuevos primero."""
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT b.*, c.razon_social AS cliente_razon_social,
                   (SELECT COUNT(*) FROM borrador_venta_items bi WHERE bi.borrador_id = b.id) AS cantidad_lineas
            FROM borradores_venta b LEFT JOIN clientes c ON c.id = b.cliente_id
            WHERE b.tipo = ? AND b.estado = ? AND b.fecha_creacion >= ?
            ORDER BY b.fecha_creacion DESC, b.id DESC
            """,
            (tipo, estado, desde),
        ).fetchall()
    finally:
        conn.close()


def listar_todos(tipo: str) -> list[sqlite3.Row]:
    """Todos los borradores de un tipo (los presupuestos no se purgan), los mas nuevos primero."""
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT b.*, c.razon_social AS cliente_razon_social, v.numero AS venta_numero
            FROM borradores_venta b
            LEFT JOIN clientes c ON c.id = b.cliente_id
            LEFT JOIN ventas v ON v.id = b.venta_id
            WHERE b.tipo = ?
            ORDER BY b.fecha_creacion DESC, b.id DESC
            """,
            (tipo,),
        ).fetchall()
    finally:
        conn.close()


def contar_creados_desde(tipo: str, desde: str) -> int:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM borradores_venta WHERE tipo = ? AND fecha_creacion >= ?", (tipo, desde)
        ).fetchone()[0]
    finally:
        conn.close()


def marcar_convertido(borrador_id: int, venta_id: int, conn: sqlite3.Connection | None = None) -> None:
    """Se llama dentro de la transaccion de la venta: venta y borrador cambian juntos o ninguno."""
    conexion_propia = conn is None
    if conexion_propia:
        conn = get_connection()
    try:
        conn.execute(
            "UPDATE borradores_venta SET estado = 'convertida', venta_id = ?, fecha_actualizacion = ? WHERE id = ?",
            (venta_id, datetime.now().isoformat(), borrador_id),
        )
    finally:
        if conexion_propia:
            conn.close()


def descartar(borrador_id: int, motivo: str | None) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE borradores_venta SET estado = 'descartada', motivo_descarte = ?, fecha_actualizacion = ? WHERE id = ?",
            (motivo, datetime.now().isoformat(), borrador_id),
        )
    finally:
        conn.close()


def purgar(tipo: str, creados_antes_de: str) -> int:
    """Borra (con sus lineas, por CASCADE) los borradores de un tipo creados antes de esa fecha.
    Devuelve cuantos borro."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        borrados = conn.execute(
            "DELETE FROM borradores_venta WHERE tipo = ? AND fecha_creacion < ?", (tipo, creados_antes_de)
        ).rowcount
        conn.commit()
        return borrados
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
