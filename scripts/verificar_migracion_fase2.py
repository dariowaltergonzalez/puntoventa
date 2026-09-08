import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.db.connection as connection_module
from app.config import DB_PATH as DB_PATH_REAL

connection_module.DB_PATH = DB_PATH_REAL.parent / "puntoventa_test.db"

from app.db.connection import get_connection

conn = get_connection()
for tabla in ["clientes", "cliente_contactos", "listas_precios", "listas_precios_categorias",
              "listas_precios_productos", "cliente_listas_precios"]:
    columnas = [f["name"] for f in conn.execute(f"PRAGMA table_info({tabla})")]
    print(f"{tabla}: {columnas}")
conn.close()
print("\nMigracion OK, sin errores")
