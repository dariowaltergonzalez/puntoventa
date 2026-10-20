import sqlite3
from datetime import datetime
from pathlib import Path

import app.db.connection as conexion
from app.db.connection import get_connection

CAMPOS_GASTO = (
    "fecha", "descripcion", "categoria_gasto_id", "monto_total", "iva_porcentaje", "medio_pago_id",
    "proveedor", "observacion",
)

_SELECT = """
    SELECT g.*, c.nombre AS categoria_nombre, m.nombre AS medio_pago_nombre
    FROM gastos g
    JOIN categorias_gasto c ON c.id = g.categoria_gasto_id
    LEFT JOIN medios_pago m ON m.id = g.medio_pago_id
"""


def carpeta_comprobantes() -> Path:
    """data/comprobantes/, al lado de la base en uso. Como la base, no viaja por git."""
    return Path(conexion.DB_PATH).parent / "comprobantes"


# ---------- categorias ----------
def listar_categorias(solo_activas: bool = True) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        sql = "SELECT * FROM categorias_gasto" + (" WHERE activo = 1" if solo_activas else "") + " ORDER BY nombre"
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def crear_categoria(nombre: str) -> int:
    conn = get_connection()
    try:
        return conn.execute("INSERT INTO categorias_gasto (nombre) VALUES (?)", (nombre,)).lastrowid
    finally:
        conn.close()


def obtener_categoria(categoria_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM categorias_gasto WHERE id = ?", (categoria_id,)).fetchone()
    finally:
        conn.close()


# ---------- gastos ----------
def crear(datos: dict, iva_recuperable: bool) -> int:
    conn = get_connection()
    try:
        return conn.execute(
            f"INSERT INTO gastos ({', '.join(CAMPOS_GASTO)}, iva_recuperable, fecha_creacion) "
            f"VALUES ({', '.join('?' * len(CAMPOS_GASTO))}, ?, ?)",
            (*[datos[c] for c in CAMPOS_GASTO], int(iva_recuperable), datetime.now().isoformat()),
        ).lastrowid
    finally:
        conn.close()


def actualizar(gasto_id: int, datos: dict) -> None:
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE gastos SET {', '.join(f'{c} = ?' for c in CAMPOS_GASTO)} WHERE id = ?",
            (*[datos[c] for c in CAMPOS_GASTO], gasto_id),
        )
    finally:
        conn.close()


def actualizar_comprobante(gasto_id: int, comprobante: str | None) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE gastos SET comprobante = ? WHERE id = ?", (comprobante, gasto_id))
    finally:
        conn.close()


def anular(gasto_id: int, fecha: str, motivo: str) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE gastos SET anulado_fecha = ?, anulado_motivo = ? WHERE id = ?", (fecha, motivo, gasto_id))
    finally:
        conn.close()


def obtener(gasto_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(_SELECT + " WHERE g.id = ?", (gasto_id,)).fetchone()
    finally:
        conn.close()


def listar(desde: str, hasta: str) -> list[sqlite3.Row]:
    """Gastos con fecha en [desde, hasta] (AAAA-MM-DD, inclusive), los mas nuevos primero.
    Incluye los anulados (la pantalla los muestra tachados; los totales los excluyen)."""
    conn = get_connection()
    try:
        return conn.execute(
            _SELECT + " WHERE g.fecha >= ? AND g.fecha <= ? ORDER BY g.fecha DESC, g.id DESC", (desde, hasta),
        ).fetchall()
    finally:
        conn.close()
