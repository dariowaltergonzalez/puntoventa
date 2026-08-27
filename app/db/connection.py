import sqlite3
from pathlib import Path

from app.config import DB_PATH, SCHEMA_PATH


def get_connection() -> sqlite3.Connection:
    """Abre una conexion con WAL y foreign_keys activados, inicializando el schema si falta."""
    is_new = not DB_PATH.exists()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    if is_new:
        _init_schema(conn)
    else:
        _migrar(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    sql = Path(SCHEMA_PATH).read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()


def _migrar(conn: sqlite3.Connection) -> None:
    """Migraciones aditivas simples para bases creadas con una version anterior del schema."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS proveedores (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre         TEXT NOT NULL UNIQUE,
            cuit           TEXT,
            contacto       TEXT,
            telefono       TEXT,
            email          TEXT,
            direccion      TEXT,
            observaciones  TEXT,
            activo         INTEGER NOT NULL DEFAULT 1,
            CHECK (activo IN (0, 1))
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS log_eventos (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha         TEXT NOT NULL,
            entidad       TEXT NOT NULL,
            entidad_id    INTEGER,
            descripcion   TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_log_eventos_fecha ON log_eventos (fecha)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_log_eventos_entidad ON log_eventos (entidad, entidad_id)")

    columnas = {fila["name"] for fila in conn.execute("PRAGMA table_info(productos)")}
    if "stock_minimo" not in columnas:
        conn.execute("ALTER TABLE productos ADD COLUMN stock_minimo INTEGER NOT NULL DEFAULT 0")
    if "marca" not in columnas:
        conn.execute("ALTER TABLE productos ADD COLUMN marca TEXT")
    if "descripcion" not in columnas:
        conn.execute("ALTER TABLE productos ADD COLUMN descripcion TEXT")
    if "codigo_barra" not in columnas:
        conn.execute("ALTER TABLE productos ADD COLUMN codigo_barra TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_productos_codigo_barra ON productos (codigo_barra)")
    if "proveedor_id" not in columnas:
        conn.execute("ALTER TABLE productos ADD COLUMN proveedor_id INTEGER")
