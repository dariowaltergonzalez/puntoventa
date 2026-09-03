"""Verifica el calculo de costo real promedio por linea de OC, contra una COPIA de la base real.
Correr con: python scripts/verificar_costo_real.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.db.connection as connection_module
from app.config import DB_PATH as DB_PATH_REAL

DB_COPIA = DB_PATH_REAL.parent / "puntoventa_test.db"
connection_module.DB_PATH = DB_COPIA

from app.services import ordenes_compra_service


def main():
    ocs = ordenes_compra_service.listar_ordenes_compra()
    for oc in ocs:
        print(f"\n{oc['numero']} ({oc['estado']}):")
        for item in oc["items"]:
            nombre = item["descripcion_libre"] or f"{item['producto_codigo']} - {item['producto_nombre']}"
            print(
                f"  {nombre}: pedida={item['cantidad_pedida']} costo_pactado={item['costo_pactado']} "
                f"recibida={item['cantidad_recibida']} costo_real_promedio={item['costo_real_promedio']}"
            )


if __name__ == "__main__":
    main()
