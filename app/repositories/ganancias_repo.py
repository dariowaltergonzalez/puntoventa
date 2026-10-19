"""Consultas para el reporte de Ganancias por periodo. Traen filas crudas (enteros escalados);
la cuenta (descuentos, reparto, agrupacion) la hace ganancias_service.
Rango de fechas: [desde, hasta_exclusivo) en ISO ('2026-10-01' <= fecha < '2026-10-20')."""

import sqlite3

from app.db.connection import get_connection

# Ajustes de stock que NO son perdida ni ganancia: el stock inicial es mercaderia que ya se
# tenia, no algo que se gano.
MOTIVOS_FUERA_DE_RESULTADO = ("venta", "compra", "devolucion", "stock_inicial")


def listar_ventas(desde: str, hasta: str) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT v.*, c.razon_social AS cliente_nombre
            FROM ventas v LEFT JOIN clientes c ON c.id = v.cliente_id
            WHERE v.estado = 'confirmada' AND v.fecha >= ? AND v.fecha < ?
            ORDER BY v.fecha, v.id
            """,
            (desde, hasta),
        ).fetchall()
    finally:
        conn.close()


def listar_lineas_de_ventas(desde: str, hasta: str) -> list[sqlite3.Row]:
    """Lineas de las ventas del periodo, con el costo real de los lotes que consumieron
    (costo_lotes: cantidad x1000 * costo x100, o sea escalado x100000)."""
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT vi.id, vi.venta_id, vi.producto_id, vi.descripcion_libre, vi.cantidad,
                   vi.precio_unitario, vi.descuento_item_porcentaje,
                   p.codigo AS producto_codigo, p.nombre AS producto_nombre,
                   COALESCE((SELECT SUM(vil.cantidad * vil.costo_unitario)
                             FROM venta_item_lotes vil WHERE vil.venta_item_id = vi.id), 0) AS costo_lotes
            FROM venta_items vi
            JOIN ventas v ON v.id = vi.venta_id
            LEFT JOIN productos p ON p.id = vi.producto_id
            WHERE v.estado = 'confirmada' AND v.fecha >= ? AND v.fecha < ?
            ORDER BY vi.venta_id, vi.id
            """,
            (desde, hasta),
        ).fetchall()
    finally:
        conn.close()


def listar_notas_credito(desde: str, hasta: str) -> list[sqlite3.Row]:
    """Notas de credito EMITIDAS en el periodo (cuentan en el periodo en que se emiten, no en
    el de la venta), con los descuentos de su venta."""
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT nc.id, nc.numero, nc.venta_id, nc.fecha,
                   v.descuento_cliente_porcentaje, v.descuento_total_porcentaje
            FROM notas_credito nc JOIN ventas v ON v.id = nc.venta_id
            WHERE nc.fecha >= ? AND nc.fecha < ?
            ORDER BY nc.fecha, nc.id
            """,
            (desde, hasta),
        ).fetchall()
    finally:
        conn.close()


def listar_lineas_de_notas_credito(desde: str, hasta: str) -> list[sqlite3.Row]:
    """Lineas de las notas de credito del periodo, con el precio/descuento de la linea vendida y
    el costo de lo que volvio al stock (costo_devuelto, escalado x100000)."""
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT nci.id, nci.nota_credito_id, nci.cantidad, nci.vuelve_stock,
                   vi.producto_id, vi.descripcion_libre, vi.precio_unitario, vi.descuento_item_porcentaje,
                   p.codigo AS producto_codigo, p.nombre AS producto_nombre,
                   COALESCE((SELECT SUM(ncl.cantidad * ncl.costo_unitario)
                             FROM nota_credito_item_lotes ncl WHERE ncl.nota_credito_item_id = nci.id), 0) AS costo_devuelto
            FROM nota_credito_items nci
            JOIN notas_credito nc ON nc.id = nci.nota_credito_id
            JOIN venta_items vi ON vi.id = nci.venta_item_id
            LEFT JOIN productos p ON p.id = vi.producto_id
            WHERE nc.fecha >= ? AND nc.fecha < ?
            ORDER BY nci.nota_credito_id, nci.id
            """,
            (desde, hasta),
        ).fetchall()
    finally:
        conn.close()


def listar_ajustes_de_stock(desde: str, hasta: str) -> list[sqlite3.Row]:
    """Ajustes manuales del periodo agrupados por motivo y tipo, valorizados al costo del lote
    (valor: escalado x100000)."""
    marcadores = ",".join("?" * len(MOTIVOS_FUERA_DE_RESULTADO))
    conn = get_connection()
    try:
        return conn.execute(
            f"""
            SELECT motivo, tipo, SUM(cantidad) AS cantidad, SUM(cantidad * COALESCE(precio_unitario, 0)) AS valor
            FROM movimientos
            WHERE fecha >= ? AND fecha < ? AND motivo NOT IN ({marcadores})
            GROUP BY motivo, tipo
            """,
            (desde, hasta, *MOTIVOS_FUERA_DE_RESULTADO),
        ).fetchall()
    finally:
        conn.close()
