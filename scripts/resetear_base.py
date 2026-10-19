"""Borron y cuenta nueva: guarda una copia de seguridad de la base, la borra, la crea de cero
desde data/schema.sql y carga los datos basicos de prueba (seed_datos_basicos.py).

SOLO mientras el negocio no opere con datos reales. Con la app CERRADA.
Correr con: python scripts/resetear_base.py --confirmar
            python scripts/resetear_base.py --confirmar --base otra.db   (para probar contra otra base)
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.db.connection as connection_module
from app.config import DB_PATH as DB_PATH_REAL


def main() -> None:
    if "--confirmar" not in sys.argv:
        print(__doc__)
        print("No se hizo nada: falta --confirmar.")
        sys.exit(1)
    base = Path(sys.argv[sys.argv.index("--base") + 1]) if "--base" in sys.argv else DB_PATH_REAL
    connection_module.DB_PATH = base

    if base.exists():
        carpeta_backups = base.parent / "backups"
        carpeta_backups.mkdir(exist_ok=True)
        copia = carpeta_backups / f"{base.stem}_antes_reset_{datetime.now():%Y%m%d_%H%M%S}.db"
        # backup() de sqlite (y no copiar el archivo): incluye lo que todavia esta en el -wal.
        origen = sqlite3.connect(base)
        destino = sqlite3.connect(copia)
        origen.backup(destino)
        destino.close()
        origen.close()
        print(f"1. Copia de seguridad: {copia}")

        try:
            for archivo in (base, Path(f"{base}-wal"), Path(f"{base}-shm")):
                archivo.unlink(missing_ok=True)
        except PermissionError:
            print("ERROR: la base esta en uso. Cerra la app (y cualquier otro programa que la tenga abierta) y volve a correrlo.")
            sys.exit(1)
        print("2. Base borrada")
    else:
        print("1-2. No habia base previa")

    connection_module.get_connection().close()
    print("3. Base nueva creada desde data/schema.sql\n")

    from scripts import seed_datos_basicos
    seed_datos_basicos.main()


if __name__ == "__main__":
    main()
