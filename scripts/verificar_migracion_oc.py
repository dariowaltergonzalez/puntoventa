"""Verifica la migracion de Fase 1 (Ordenes de Compra) contra una COPIA de la base real.
Correr con: python scripts/verificar_migracion_oc.py
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.db.connection as connection_module
from app.config import DB_PATH as DB_PATH_REAL

DB_COPIA = DB_PATH_REAL.parent / "puntoventa_test.db"
connection_module.DB_PATH = DB_COPIA


def contar_filas(conn, tabla):
    return conn.execute(f"SELECT COUNT(*) AS c FROM {tabla}").fetchone()["c"]


def main():
    conn_directa = sqlite3.connect(DB_COPIA)
    conn_directa.row_factory = sqlite3.Row
    antes = {t: contar_filas(conn_directa, t) for t in ("categorias", "productos", "proveedores", "movimientos", "log_eventos")}
    conn_directa.close()
    print("Filas antes de migrar:", antes)

    conn = connection_module.get_connection()

    tablas_nuevas = [
        "contadores", "proveedor_contactos", "ordenes_compra",
        "orden_compra_items", "recepciones", "lotes", "recepcion_items",
    ]
    for tabla in tablas_nuevas:
        columnas = [f["name"] for f in conn.execute(f"PRAGMA table_info({tabla})")]
        print(f"OK: tabla '{tabla}' existe con columnas {columnas}")

    columnas_mov = [f["name"] for f in conn.execute("PRAGMA table_info(movimientos)")]
    assert "lote_id" in columnas_mov and "precio_unitario" in columnas_mov
    print(f"OK: movimientos tiene lote_id y precio_unitario. Columnas: {columnas_mov}")

    despues = {t: contar_filas(conn, t) for t in ("categorias", "productos", "proveedores", "movimientos", "log_eventos")}
    print("Filas despues de migrar:", despues)
    assert antes == despues, "PERDIMOS DATOS EN LA MIGRACION"
    print("OK: no se perdio ninguna fila existente")

    conn.close()
    print("\nMigracion verificada correctamente contra la copia.")


if __name__ == "__main__":
    main()
