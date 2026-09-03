"""Lista todos los movimientos de un producto (por codigo) contra una COPIA de la base real.
Correr con: python scripts/verificar_movimientos_producto.py <codigo>
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
    codigo = sys.argv[1] if len(sys.argv) > 1 else "ARR001"
    conn = get_connection()
    try:
        producto = conn.execute("SELECT id, codigo, nombre FROM productos WHERE codigo = ?", (codigo,)).fetchone()
        if producto is None:
            print(f"No existe producto con codigo {codigo}")
            return
        movs = conn.execute(
            """
            SELECT id, tipo, cantidad, motivo, referencia, observacion, lote_id, precio_unitario, fecha
            FROM movimientos
            WHERE producto_id = ?
            ORDER BY fecha ASC, id ASC
            """,
            (producto["id"],),
        ).fetchall()
        print(f"{producto['codigo']} - {producto['nombre']}  ({len(movs)} movimientos)")
        for m in movs:
            precio = entero_a_precio(m["precio_unitario"]) if m["precio_unitario"] is not None else None
            print(
                f"  #{m['id']} {m['fecha']}  {m['tipo']:8s} cant={entero_a_cantidad(m['cantidad'])}  "
                f"motivo={m['motivo']}  ref={m['referencia']}  lote_id={m['lote_id']}  precio={precio}  "
                f"obs={m['observacion']}"
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
