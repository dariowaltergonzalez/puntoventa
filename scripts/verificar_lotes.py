"""Verifica que el stock recibido este separado en lotes por costo, y que
stock_actual de cada producto coincida con la suma de cantidad_restante de sus lotes.
Corre contra una COPIA de la base real. Correr con: python scripts/verificar_lotes.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.db.connection as connection_module
from app.config import DB_PATH as DB_PATH_REAL

DB_COPIA = DB_PATH_REAL.parent / "puntoventa_test.db"
connection_module.DB_PATH = DB_COPIA

from app.db.connection import get_connection
from app.shared.money import entero_a_cantidad, entero_a_precio


def main():
    conn = get_connection()
    try:
        productos = conn.execute(
            "SELECT id, codigo, nombre, stock_actual FROM productos ORDER BY id"
        ).fetchall()

        for p in productos:
            lotes = conn.execute(
                """
                SELECT l.id, l.cantidad_recibida, l.cantidad_restante, l.costo_unitario, l.fecha,
                       r.numero_remito, oc.numero AS numero_oc
                FROM lotes l
                LEFT JOIN recepciones r ON r.id = l.recepcion_id
                LEFT JOIN ordenes_compra oc ON oc.id = r.orden_compra_id
                WHERE l.producto_id = ?
                ORDER BY l.fecha ASC, l.id ASC
                """,
                (p["id"],),
            ).fetchall()

            if not lotes:
                continue

            suma_restante = sum(l["cantidad_restante"] for l in lotes)
            stock_actual = p["stock_actual"]
            ok = "OK" if suma_restante == stock_actual else "DESCUADRA!!"

            print(f"\n{p['codigo']} - {p['nombre']}  (stock_actual={entero_a_cantidad(stock_actual)})  [{ok}]")
            for l in lotes:
                print(
                    f"  lote #{l['id']}  {l['numero_oc'] or '-'}  fecha={l['fecha']}  "
                    f"recibido={entero_a_cantidad(l['cantidad_recibida'])}  "
                    f"restante={entero_a_cantidad(l['cantidad_restante'])}  "
                    f"costo=${entero_a_precio(l['costo_unitario'])}"
                )
            print(f"  suma restante de lotes = {entero_a_cantidad(suma_restante)}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
