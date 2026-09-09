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

    conn.execute("CREATE TABLE IF NOT EXISTS contadores (nombre TEXT PRIMARY KEY, valor INTEGER NOT NULL DEFAULT 0)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS proveedor_contactos (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            proveedor_id   INTEGER NOT NULL,
            nombre         TEXT NOT NULL,
            email          TEXT,
            telefono       TEXT,
            FOREIGN KEY (proveedor_id) REFERENCES proveedores (id) ON DELETE CASCADE ON UPDATE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_proveedor_contactos_proveedor_id ON proveedor_contactos (proveedor_id)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ordenes_compra (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            numero            TEXT NOT NULL UNIQUE,
            proveedor_id      INTEGER NOT NULL,
            estado            TEXT NOT NULL DEFAULT 'pendiente',
            fecha_creacion    TEXT NOT NULL,
            fecha_estimada    TEXT,
            iva_porcentaje    INTEGER,
            observacion       TEXT,
            FOREIGN KEY (proveedor_id) REFERENCES proveedores (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            CHECK (estado IN ('pendiente', 'recibida_parcial', 'recibida', 'cancelada')),
            CHECK (iva_porcentaje IS NULL OR iva_porcentaje >= 0)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ordenes_compra_proveedor_id ON ordenes_compra (proveedor_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ordenes_compra_estado ON ordenes_compra (estado)")

    columnas_ordenes_compra = {fila["name"] for fila in conn.execute("PRAGMA table_info(ordenes_compra)")}
    if "recibida_en_el_acto" not in columnas_ordenes_compra:
        conn.execute(
            "ALTER TABLE ordenes_compra ADD COLUMN recibida_en_el_acto INTEGER NOT NULL DEFAULT 0 "
            "CHECK (recibida_en_el_acto IN (0, 1))"
        )
        # Backfill unico, best-effort: para las OC creadas antes de que existiera esta columna no queda
        # registrado si nacieron con 'ya la tenes en mano' -- se infiere por unica recepcion a los pocos
        # segundos de la creacion (una recepcion diferida real tarda minutos/horas/dias, no segundos).
        conn.execute(
            """
            UPDATE ordenes_compra
            SET recibida_en_el_acto = 1
            WHERE id IN (
                SELECT oc.id
                FROM ordenes_compra oc
                JOIN recepciones r ON r.orden_compra_id = oc.id
                GROUP BY oc.id
                HAVING COUNT(r.id) = 1
                   AND ABS((julianday(MIN(r.fecha)) - julianday(oc.fecha_creacion)) * 86400.0) < 5
            )
            """
        )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orden_compra_items (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            orden_compra_id     INTEGER NOT NULL,
            producto_id         INTEGER,
            descripcion_libre   TEXT,
            cantidad_pedida     INTEGER NOT NULL,
            costo_pactado       INTEGER NOT NULL,
            cantidad_recibida   INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (orden_compra_id) REFERENCES ordenes_compra (id) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (producto_id) REFERENCES productos (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            CHECK (cantidad_pedida > 0), CHECK (costo_pactado >= 0), CHECK (cantidad_recibida >= 0),
            CHECK ((producto_id IS NULL) != (descripcion_libre IS NULL))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orden_compra_items_oc_id ON orden_compra_items (orden_compra_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orden_compra_items_producto_id ON orden_compra_items (producto_id)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS recepciones (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            orden_compra_id    INTEGER NOT NULL,
            fecha              TEXT NOT NULL,
            numero_remito      TEXT,
            observacion        TEXT,
            FOREIGN KEY (orden_compra_id) REFERENCES ordenes_compra (id) ON DELETE RESTRICT ON UPDATE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_recepciones_oc_id ON recepciones (orden_compra_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_recepciones_fecha ON recepciones (fecha)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lotes (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id        INTEGER NOT NULL,
            recepcion_id       INTEGER NOT NULL,
            cantidad_recibida  INTEGER NOT NULL,
            cantidad_restante  INTEGER NOT NULL,
            costo_unitario     INTEGER NOT NULL,
            fecha              TEXT NOT NULL,
            FOREIGN KEY (producto_id) REFERENCES productos (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            FOREIGN KEY (recepcion_id) REFERENCES recepciones (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            CHECK (cantidad_recibida > 0), CHECK (cantidad_restante >= 0), CHECK (costo_unitario >= 0)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lotes_producto_id ON lotes (producto_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lotes_producto_fecha ON lotes (producto_id, fecha)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lotes_recepcion_id ON lotes (recepcion_id)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS recepcion_items (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            recepcion_id           INTEGER NOT NULL,
            orden_compra_item_id   INTEGER,
            producto_id            INTEGER,
            descripcion_libre      TEXT,
            cantidad_recibida      INTEGER NOT NULL,
            costo_unitario         INTEGER NOT NULL,
            lote_id                INTEGER,
            FOREIGN KEY (recepcion_id) REFERENCES recepciones (id) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (orden_compra_item_id) REFERENCES orden_compra_items (id) ON DELETE SET NULL ON UPDATE CASCADE,
            FOREIGN KEY (producto_id) REFERENCES productos (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            FOREIGN KEY (lote_id) REFERENCES lotes (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            CHECK (cantidad_recibida > 0), CHECK (costo_unitario >= 0),
            CHECK ((producto_id IS NULL) != (descripcion_libre IS NULL))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_recepcion_items_recepcion_id ON recepcion_items (recepcion_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_recepcion_items_producto_id ON recepcion_items (producto_id)")

    columnas_movimientos = {fila["name"] for fila in conn.execute("PRAGMA table_info(movimientos)")}
    if "lote_id" not in columnas_movimientos:
        conn.execute("ALTER TABLE movimientos ADD COLUMN lote_id INTEGER REFERENCES lotes (id)")
    if "precio_unitario" not in columnas_movimientos:
        conn.execute(
            "ALTER TABLE movimientos ADD COLUMN precio_unitario INTEGER "
            "CHECK (precio_unitario IS NULL OR precio_unitario >= 0)"
        )

    # Fase 2: Clientes + listas de precios
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS clientes (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            razon_social            TEXT NOT NULL UNIQUE,
            nombre_fantasia         TEXT,
            dni                     TEXT,
            cuit                    TEXT,
            contacto_principal      TEXT,
            telefono                TEXT,
            email                   TEXT,
            direccion               TEXT,
            ciudad                  TEXT,
            provincia               TEXT,
            codigo_postal           TEXT,
            condicion_iva           TEXT,
            plazo_pago_dias         INTEGER,
            porcentaje_descuento    INTEGER,
            limite_credito          INTEGER,
            avisar_limite_credito   INTEGER NOT NULL DEFAULT 0,
            bloquear_limite_credito INTEGER NOT NULL DEFAULT 0,
            tasa_interes_mora_diaria INTEGER,
            observacion             TEXT,
            activo                  INTEGER NOT NULL DEFAULT 1,
            CHECK (activo IN (0, 1)),
            CHECK (plazo_pago_dias IS NULL OR plazo_pago_dias >= 0),
            CHECK (limite_credito IS NULL OR limite_credito >= 0),
            CHECK (avisar_limite_credito IN (0, 1)),
            CHECK (bloquear_limite_credito IN (0, 1))
        )
        """
    )
    columnas_clientes = {fila["name"] for fila in conn.execute("PRAGMA table_info(clientes)")}
    if "avisar_limite_credito" not in columnas_clientes:
        # Reemplaza al viejo 'modo_limite_credito' (columna unica bloquear/avisar mutuamente
        # excluyente) por dos flags independientes: un cliente puede querer avisar y no bloquear,
        # bloquear y no avisar, ambos, o ninguno.
        conn.execute(
            "ALTER TABLE clientes ADD COLUMN avisar_limite_credito INTEGER NOT NULL DEFAULT 0 "
            "CHECK (avisar_limite_credito IN (0, 1))"
        )
    if "bloquear_limite_credito" not in columnas_clientes:
        conn.execute(
            "ALTER TABLE clientes ADD COLUMN bloquear_limite_credito INTEGER NOT NULL DEFAULT 0 "
            "CHECK (bloquear_limite_credito IN (0, 1))"
        )
    if "modo_limite_credito" in columnas_clientes:
        # Todavia en desarrollo, sin datos reales de negocio en juego: se reconstruye la tabla
        # para sacar del todo la columna vieja en vez de dejarla huerfana. SQLite no permite
        # DROP COLUMN si hay un CHECK que la referencia, asi que se recrea la tabla completa
        # (patron recomendado por SQLite para este caso).
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("ALTER TABLE clientes RENAME TO clientes_old_modo_limite")
        conn.execute(
            """
            CREATE TABLE clientes (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                razon_social            TEXT NOT NULL UNIQUE,
                nombre_fantasia         TEXT,
                dni                     TEXT,
                cuit                    TEXT,
                contacto_principal      TEXT,
                telefono                TEXT,
                email                   TEXT,
                direccion               TEXT,
                ciudad                  TEXT,
                provincia               TEXT,
                codigo_postal           TEXT,
                condicion_iva           TEXT,
                plazo_pago_dias         INTEGER,
                porcentaje_descuento    INTEGER,
                limite_credito          INTEGER,
                avisar_limite_credito   INTEGER NOT NULL DEFAULT 0,
                bloquear_limite_credito INTEGER NOT NULL DEFAULT 0,
                tasa_interes_mora_diaria INTEGER,
                observacion             TEXT,
                activo                  INTEGER NOT NULL DEFAULT 1,
                CHECK (activo IN (0, 1)),
                CHECK (plazo_pago_dias IS NULL OR plazo_pago_dias >= 0),
                CHECK (limite_credito IS NULL OR limite_credito >= 0),
                CHECK (avisar_limite_credito IN (0, 1)),
                CHECK (bloquear_limite_credito IN (0, 1))
            )
            """
        )
        conn.execute(
            """
            INSERT INTO clientes
                (id, razon_social, nombre_fantasia, dni, cuit, contacto_principal, telefono, email,
                 direccion, ciudad, provincia, codigo_postal, condicion_iva, plazo_pago_dias,
                 porcentaje_descuento, limite_credito, avisar_limite_credito, bloquear_limite_credito,
                 tasa_interes_mora_diaria, observacion, activo)
            SELECT
                id, razon_social, nombre_fantasia, dni, cuit, contacto_principal, telefono, email,
                direccion, ciudad, provincia, codigo_postal, condicion_iva, plazo_pago_dias,
                porcentaje_descuento, limite_credito, avisar_limite_credito, bloquear_limite_credito,
                tasa_interes_mora_diaria, observacion, activo
            FROM clientes_old_modo_limite
            """
        )
        conn.execute("DROP TABLE clientes_old_modo_limite")
        conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cliente_contactos (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id     INTEGER NOT NULL,
            nombre         TEXT NOT NULL,
            email          TEXT,
            telefono       TEXT,
            sector         TEXT,
            es_principal   INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id) ON DELETE CASCADE ON UPDATE CASCADE,
            CHECK (es_principal IN (0, 1))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS listas_precios (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre              TEXT NOT NULL UNIQUE,
            porcentaje_general  INTEGER,
            activo              INTEGER NOT NULL DEFAULT 1,
            CHECK (activo IN (0, 1))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS listas_precios_categorias (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            lista_precio_id  INTEGER NOT NULL,
            categoria_id     INTEGER NOT NULL,
            porcentaje       INTEGER NOT NULL,
            FOREIGN KEY (lista_precio_id) REFERENCES listas_precios (id) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (categoria_id) REFERENCES categorias (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            UNIQUE (lista_precio_id, categoria_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS listas_precios_productos (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            lista_precio_id  INTEGER NOT NULL,
            producto_id      INTEGER NOT NULL,
            precio_manual    INTEGER NOT NULL,
            FOREIGN KEY (lista_precio_id) REFERENCES listas_precios (id) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (producto_id) REFERENCES productos (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            CHECK (precio_manual >= 0),
            UNIQUE (lista_precio_id, producto_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cliente_listas_precios (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id       INTEGER NOT NULL,
            lista_precio_id  INTEGER NOT NULL,
            prioridad        INTEGER NOT NULL,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (lista_precio_id) REFERENCES listas_precios (id) ON DELETE CASCADE ON UPDATE CASCADE,
            UNIQUE (cliente_id, lista_precio_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cliente_contactos_cliente_id ON cliente_contactos (cliente_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_listas_precios_categorias_lista_id "
        "ON listas_precios_categorias (lista_precio_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_listas_precios_productos_lista_id "
        "ON listas_precios_productos (lista_precio_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_listas_precios_productos_producto_id "
        "ON listas_precios_productos (producto_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cliente_listas_precios_cliente_id "
        "ON cliente_listas_precios (cliente_id)"
    )
