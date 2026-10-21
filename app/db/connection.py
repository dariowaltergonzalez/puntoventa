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
            recepcion_id       INTEGER,
            origen             TEXT NOT NULL DEFAULT 'recepcion',
            cantidad_recibida  INTEGER NOT NULL,
            cantidad_restante  INTEGER NOT NULL,
            costo_unitario     INTEGER NOT NULL,
            fecha              TEXT NOT NULL,
            FOREIGN KEY (producto_id) REFERENCES productos (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            FOREIGN KEY (recepcion_id) REFERENCES recepciones (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            CHECK (cantidad_recibida > 0), CHECK (cantidad_restante >= 0), CHECK (costo_unitario >= 0),
            CHECK (origen IN ('recepcion', 'inicial')),
            CHECK (origen != 'recepcion' OR recepcion_id IS NOT NULL)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lotes_producto_id ON lotes (producto_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lotes_producto_fecha ON lotes (producto_id, fecha)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lotes_recepcion_id ON lotes (recepcion_id)")

    columnas_lotes = {fila["name"] for fila in conn.execute("PRAGMA table_info(lotes)")}
    recepcion_id_nullable = any(
        fila["name"] == "recepcion_id" and fila["notnull"] == 0
        for fila in conn.execute("PRAGMA table_info(lotes)")
    )
    if "origen" not in columnas_lotes or not recepcion_id_nullable:
        # Se necesita poder tener lotes "de arranque" sin recepcion real (ver backfill mas abajo).
        # recepcion_id era NOT NULL -- no se puede relajar con ALTER simple, se reconstruye la tabla
        # (mismo patron ya usado antes; legacy_alter_table=ON evita que se rompan las FK de
        # recepcion_items/movimientos que apuntan a lotes).
        conn.execute("PRAGMA legacy_alter_table = ON")
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("ALTER TABLE lotes RENAME TO lotes_old_origen")
        conn.execute(
            """
            CREATE TABLE lotes (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                producto_id        INTEGER NOT NULL,
                recepcion_id       INTEGER,
                origen             TEXT NOT NULL DEFAULT 'recepcion',
                cantidad_recibida  INTEGER NOT NULL,
                cantidad_restante  INTEGER NOT NULL,
                costo_unitario     INTEGER NOT NULL,
                fecha              TEXT NOT NULL,
                FOREIGN KEY (producto_id) REFERENCES productos (id) ON DELETE RESTRICT ON UPDATE CASCADE,
                FOREIGN KEY (recepcion_id) REFERENCES recepciones (id) ON DELETE RESTRICT ON UPDATE CASCADE,
                CHECK (cantidad_recibida > 0), CHECK (cantidad_restante >= 0), CHECK (costo_unitario >= 0),
                CHECK (origen IN ('recepcion', 'inicial')),
                CHECK (origen != 'recepcion' OR recepcion_id IS NOT NULL)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO lotes (id, producto_id, recepcion_id, origen, cantidad_recibida, cantidad_restante, costo_unitario, fecha)
            SELECT id, producto_id, recepcion_id, 'recepcion', cantidad_recibida, cantidad_restante, costo_unitario, fecha
            FROM lotes_old_origen
            """
        )
        conn.execute("DROP TABLE lotes_old_origen")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lotes_producto_id ON lotes (producto_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lotes_producto_fecha ON lotes (producto_id, fecha)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lotes_recepcion_id ON lotes (recepcion_id)")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA legacy_alter_table = OFF")

    # Backfill unico: stock cargado antes de que existiera el sistema de lotes (ajustes/movimientos
    # viejos sin recepcion) no tiene lote que lo respalde -- se le crea un lote "de arranque" por la
    # diferencia, al costo de costo actual del producto y con fecha vieja para que FIFO lo consuma
    # primero. Idempotente por producto: si ya tiene un lote 'inicial', no se vuelve a crear.
    for fila_producto in conn.execute("SELECT id, precio_costo FROM productos"):
        producto_id = fila_producto["id"]
        ya_tiene_inicial = conn.execute(
            "SELECT 1 FROM lotes WHERE producto_id = ? AND origen = 'inicial'", (producto_id,)
        ).fetchone()
        if ya_tiene_inicial:
            continue
        stock_actual = conn.execute(
            "SELECT stock_actual FROM productos WHERE id = ?", (producto_id,)
        ).fetchone()["stock_actual"]
        suma_lotes = conn.execute(
            "SELECT COALESCE(SUM(cantidad_restante), 0) AS total FROM lotes WHERE producto_id = ?", (producto_id,)
        ).fetchone()["total"]
        diferencia = stock_actual - suma_lotes
        if diferencia > 0:
            conn.execute(
                """
                INSERT INTO lotes (producto_id, recepcion_id, origen, cantidad_recibida, cantidad_restante, costo_unitario, fecha)
                VALUES (?, NULL, 'inicial', ?, ?, ?, '1970-01-01T00:00:00')
                """,
                (producto_id, diferencia, diferencia, fila_producto["precio_costo"]),
            )

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
        CREATE TABLE IF NOT EXISTS condiciones_iva (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre  TEXT NOT NULL UNIQUE,
            activo  INTEGER NOT NULL DEFAULT 1,
            CHECK (activo IN (0, 1))
        )
        """
    )
    for nombre_condicion in ("Responsable Inscripto", "Monotributista", "Exento", "Consumidor Final"):
        conn.execute(
            "INSERT INTO condiciones_iva (nombre) VALUES (?) ON CONFLICT(nombre) DO NOTHING",
            (nombre_condicion,),
        )

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
            condicion_iva_id        INTEGER,
            plazo_pago_dias         INTEGER,
            porcentaje_descuento    INTEGER,
            limite_credito          INTEGER,
            avisar_limite_credito   INTEGER NOT NULL DEFAULT 0,
            bloquear_limite_credito INTEGER NOT NULL DEFAULT 0,
            tasa_interes_mora_diaria INTEGER,
            observacion             TEXT,
            activo                  INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (condicion_iva_id) REFERENCES condiciones_iva (id)
                ON DELETE SET NULL
                ON UPDATE CASCADE,
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
        #
        # OJO: por defecto, "ALTER TABLE x RENAME TO y" hace que SQLite reescriba automaticamente
        # las FOREIGN KEY de OTRAS tablas que apuntaban a "x" para que ahora apunten a "y" --
        # asi que cliente_contactos/cliente_listas_precios (que referencian clientes) quedarian
        # apuntando a "clientes_old_modo_limite" y se rompen en cuanto esa tabla se borra mas
        # abajo. legacy_alter_table=ON desactiva esa reescritura automatica (mismo comportamiento
        # que SQLite < 3.25), que es lo que queremos aca porque la tabla "clientes" se vuelve a
        # crear con ese mismo nombre al final.
        conn.execute("PRAGMA legacy_alter_table = ON")
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
        conn.execute("PRAGMA legacy_alter_table = OFF")

    columnas_clientes = {fila["name"] for fila in conn.execute("PRAGMA table_info(clientes)")}
    if "condicion_iva" in columnas_clientes:
        # 'condicion_iva' era texto libre; se reemplaza por 'condicion_iva_id' (referencia a la
        # tabla condiciones_iva de arriba) para no permitir cualquier texto. Todavia en desarrollo,
        # mismo criterio que el rebuild de arriba: se reconstruye la tabla en vez de dejar la
        # columna vieja sin usar. Si habia texto cargado que coincide con el nombre de una
        # condicion existente, se conserva la referencia; si no matchea nada, queda NULL.
        # legacy_alter_table=ON: ver comentario largo en el rebuild de arriba (evita que SQLite
        # reescriba las FK de cliente_contactos/cliente_listas_precios).
        conn.execute("PRAGMA legacy_alter_table = ON")
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("ALTER TABLE clientes RENAME TO clientes_old_condicion_iva")
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
                condicion_iva_id        INTEGER,
                plazo_pago_dias         INTEGER,
                porcentaje_descuento    INTEGER,
                limite_credito          INTEGER,
                avisar_limite_credito   INTEGER NOT NULL DEFAULT 0,
                bloquear_limite_credito INTEGER NOT NULL DEFAULT 0,
                tasa_interes_mora_diaria INTEGER,
                observacion             TEXT,
                activo                  INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (condicion_iva_id) REFERENCES condiciones_iva (id)
                    ON DELETE SET NULL
                    ON UPDATE CASCADE,
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
                 direccion, ciudad, provincia, codigo_postal, condicion_iva_id, plazo_pago_dias,
                 porcentaje_descuento, limite_credito, avisar_limite_credito, bloquear_limite_credito,
                 tasa_interes_mora_diaria, observacion, activo)
            SELECT
                o.id, o.razon_social, o.nombre_fantasia, o.dni, o.cuit, o.contacto_principal, o.telefono, o.email,
                o.direccion, o.ciudad, o.provincia, o.codigo_postal, ci.id, o.plazo_pago_dias,
                o.porcentaje_descuento, o.limite_credito, o.avisar_limite_credito, o.bloquear_limite_credito,
                o.tasa_interes_mora_diaria, o.observacion, o.activo
            FROM clientes_old_condicion_iva o
            LEFT JOIN condiciones_iva ci ON ci.nombre = o.condicion_iva
            """
        )
        conn.execute("DROP TABLE clientes_old_condicion_iva")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA legacy_alter_table = OFF")

    # Reparacion puntual: las dos reconstrucciones de arriba (antes de agregar legacy_alter_table)
    # ya le rompieron la FK a estas dos tablas en instalaciones existentes -- quedaron apuntando
    # a "clientes_old_modo_limite", una tabla que ya no existe. Estan vacias (0 filas siempre,
    # son solo datos auxiliares de un cliente), asi que se recrean directo con la FK correcta.
    def _fk_referencia(tabla: str, columna: str) -> str | None:
        for fila in conn.execute(f"PRAGMA foreign_key_list({tabla})"):
            if fila["from"] == columna:
                return fila["table"]
        return None

    if _fk_referencia("cliente_contactos", "cliente_id") == "clientes_old_modo_limite":
        conn.execute("PRAGMA foreign_keys = OFF")
        filas_existentes = conn.execute("SELECT * FROM cliente_contactos").fetchall()
        conn.execute("DROP TABLE cliente_contactos")
        conn.execute(
            """
            CREATE TABLE cliente_contactos (
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
        for f in filas_existentes:
            conn.execute(
                "INSERT INTO cliente_contactos (id, cliente_id, nombre, email, telefono, sector, es_principal) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f["id"], f["cliente_id"], f["nombre"], f["email"], f["telefono"], f["sector"], f["es_principal"]),
            )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cliente_contactos_cliente_id ON cliente_contactos (cliente_id)")
        conn.execute("PRAGMA foreign_keys = ON")

    if _fk_referencia("cliente_listas_precios", "cliente_id") == "clientes_old_modo_limite":
        conn.execute("PRAGMA foreign_keys = OFF")
        filas_existentes = conn.execute("SELECT * FROM cliente_listas_precios").fetchall()
        conn.execute("DROP TABLE cliente_listas_precios")
        conn.execute(
            """
            CREATE TABLE cliente_listas_precios (
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
        for f in filas_existentes:
            conn.execute(
                "INSERT INTO cliente_listas_precios (id, cliente_id, lista_precio_id, prioridad) VALUES (?, ?, ?, ?)",
                (f["id"], f["cliente_id"], f["lista_precio_id"], f["prioridad"]),
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cliente_listas_precios_cliente_id ON cliente_listas_precios (cliente_id)"
        )
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

    # Fase 3: Cuentas Corrientes
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cc_cargos (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id            INTEGER,
            proveedor_id          INTEGER,
            monto                 INTEGER NOT NULL,
            fecha                 TEXT NOT NULL,
            origen                TEXT NOT NULL,
            origen_recepcion_id   INTEGER,
            origen_venta_id       INTEGER,
            observacion           TEXT,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            FOREIGN KEY (proveedor_id) REFERENCES proveedores (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            FOREIGN KEY (origen_recepcion_id) REFERENCES recepciones (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            FOREIGN KEY (origen_venta_id) REFERENCES ventas (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            CHECK ((cliente_id IS NULL) != (proveedor_id IS NULL)),
            CHECK (monto > 0),
            CHECK (origen IN ('manual', 'recepcion', 'venta')),
            CHECK (origen != 'recepcion' OR origen_recepcion_id IS NOT NULL),
            CHECK (origen != 'venta' OR origen_venta_id IS NOT NULL)
        )
        """
    )
    columnas_cc_cargos = {fila["name"] for fila in conn.execute("PRAGMA table_info(cc_cargos)")}
    if "origen_venta_id" not in columnas_cc_cargos:
        # 'ventas' se crea mas abajo en esta misma migracion, pero SQLite permite referencias
        # hacia adelante en FOREIGN KEY (recien se valida cuando se inserta, no al crear la columna).
        conn.execute("ALTER TABLE cc_cargos ADD COLUMN origen_venta_id INTEGER REFERENCES ventas (id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cc_pagos (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id     INTEGER,
            proveedor_id   INTEGER,
            monto          INTEGER NOT NULL,
            fecha          TEXT NOT NULL,
            observacion    TEXT,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            FOREIGN KEY (proveedor_id) REFERENCES proveedores (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            CHECK ((cliente_id IS NULL) != (proveedor_id IS NULL)),
            CHECK (monto > 0)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cc_pago_aplicaciones (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            pago_id    INTEGER NOT NULL,
            cargo_id   INTEGER NOT NULL,
            monto      INTEGER NOT NULL,
            FOREIGN KEY (pago_id) REFERENCES cc_pagos (id) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (cargo_id) REFERENCES cc_cargos (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            CHECK (monto > 0)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cc_cargos_cliente_id ON cc_cargos (cliente_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cc_cargos_proveedor_id ON cc_cargos (proveedor_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cc_cargos_fecha ON cc_cargos (fecha)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cc_pagos_cliente_id ON cc_pagos (cliente_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cc_pagos_proveedor_id ON cc_pagos (proveedor_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cc_pago_aplicaciones_pago_id ON cc_pago_aplicaciones (pago_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cc_pago_aplicaciones_cargo_id ON cc_pago_aplicaciones (cargo_id)")

    # Fase 4: Ventas
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS medios_pago (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre               TEXT NOT NULL UNIQUE,
            es_cuenta_corriente  INTEGER NOT NULL DEFAULT 0,
            activo               INTEGER NOT NULL DEFAULT 1,
            CHECK (es_cuenta_corriente IN (0, 1)),
            CHECK (activo IN (0, 1))
        )
        """
    )
    for nombre_medio, es_cc in (
        ("Efectivo", 0), ("Tarjeta", 0), ("Transferencia", 0), ("Cuenta corriente", 1),
    ):
        conn.execute(
            "INSERT INTO medios_pago (nombre, es_cuenta_corriente) VALUES (?, ?) ON CONFLICT(nombre) DO NOTHING",
            (nombre_medio, es_cc),
        )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ventas (
            id                          INTEGER PRIMARY KEY AUTOINCREMENT,
            numero                      TEXT NOT NULL UNIQUE,
            cliente_id                  INTEGER NOT NULL,
            lista_precio_id             INTEGER,
            estado                      TEXT NOT NULL DEFAULT 'pendiente',
            fecha                       TEXT NOT NULL,
            fecha_confirmacion          TEXT,
            iva_porcentaje              INTEGER,
            descuento_total_porcentaje  INTEGER,
            observacion                 TEXT,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            FOREIGN KEY (lista_precio_id) REFERENCES listas_precios (id) ON DELETE SET NULL ON UPDATE CASCADE,
            CHECK (estado IN ('pendiente', 'confirmada')),
            CHECK (iva_porcentaje IS NULL OR iva_porcentaje >= 0),
            CHECK (descuento_total_porcentaje IS NULL OR descuento_total_porcentaje >= 0)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ventas_cliente_id ON ventas (cliente_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ventas_fecha ON ventas (fecha)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ventas_estado ON ventas (estado)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS venta_items (
            id                          INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id                    INTEGER NOT NULL,
            producto_id                 INTEGER,
            descripcion_libre           TEXT,
            cantidad                    INTEGER NOT NULL,
            precio_unitario             INTEGER NOT NULL,
            descuento_item_porcentaje   INTEGER,
            FOREIGN KEY (venta_id) REFERENCES ventas (id) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (producto_id) REFERENCES productos (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            CHECK (cantidad > 0),
            CHECK (precio_unitario >= 0),
            CHECK (descuento_item_porcentaje IS NULL OR descuento_item_porcentaje >= 0),
            CHECK ((producto_id IS NULL) != (descripcion_libre IS NULL))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_venta_items_venta_id ON venta_items (venta_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_venta_items_producto_id ON venta_items (producto_id)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS venta_item_lotes (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_item_id    INTEGER NOT NULL,
            lote_id          INTEGER NOT NULL,
            cantidad         INTEGER NOT NULL,
            costo_unitario   INTEGER NOT NULL,
            FOREIGN KEY (venta_item_id) REFERENCES venta_items (id) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (lote_id) REFERENCES lotes (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            CHECK (cantidad > 0),
            CHECK (costo_unitario >= 0)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_venta_item_lotes_venta_item_id ON venta_item_lotes (venta_item_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_venta_item_lotes_lote_id ON venta_item_lotes (lote_id)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS venta_pagos (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id       INTEGER NOT NULL,
            medio_pago_id  INTEGER NOT NULL,
            monto          INTEGER NOT NULL,
            recibido       INTEGER,
            FOREIGN KEY (venta_id) REFERENCES ventas (id) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (medio_pago_id) REFERENCES medios_pago (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            CHECK (monto > 0),
            CHECK (recibido IS NULL OR recibido >= monto)
        )
        """
    )
    columnas_venta_pagos = {fila["name"] for fila in conn.execute("PRAGMA table_info(venta_pagos)")}
    if "recibido" not in columnas_venta_pagos:
        # Cuanto entrego el cliente en efectivo (para poder recordar despues con que billete pago
        # y de donde salio el vuelto) -- NULL para medios sin vuelto (tarjeta, transferencia, cta cte).
        conn.execute("ALTER TABLE venta_pagos ADD COLUMN recibido INTEGER")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_venta_pagos_venta_id ON venta_pagos (venta_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_venta_pagos_medio_pago_id ON venta_pagos (medio_pago_id)")

    # Fase 6: Cheques
    # cc_cargos necesita una forma nueva de origen ('cheque_rechazado') y una columna nueva
    # (origen_cheque_id) -- un CHECK no se puede ampliar con ALTER TABLE en SQLite, asi que si la
    # base ya tiene cc_cargos sin esta columna, se reconstruye con el mismo patron ya usado para
    # 'lotes' (legacy_alter_table=ON antes del RENAME, para que no se rompan las FK de
    # cc_pago_aplicaciones, que apunta a esta tabla).
    columnas_cc_cargos_actual = {fila["name"] for fila in conn.execute("PRAGMA table_info(cc_cargos)")}
    if "origen_cheque_id" not in columnas_cc_cargos_actual:
        conn.execute("PRAGMA legacy_alter_table = ON")
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("ALTER TABLE cc_cargos RENAME TO cc_cargos_old_sin_cheques")
        conn.execute(
            """
            CREATE TABLE cc_cargos (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id            INTEGER,
                proveedor_id          INTEGER,
                monto                 INTEGER NOT NULL,
                fecha                 TEXT NOT NULL,
                origen                TEXT NOT NULL,
                origen_recepcion_id   INTEGER,
                origen_venta_id       INTEGER,
                origen_cheque_id      INTEGER,
                observacion           TEXT,
                FOREIGN KEY (cliente_id) REFERENCES clientes (id) ON DELETE RESTRICT ON UPDATE CASCADE,
                FOREIGN KEY (proveedor_id) REFERENCES proveedores (id) ON DELETE RESTRICT ON UPDATE CASCADE,
                FOREIGN KEY (origen_recepcion_id) REFERENCES recepciones (id) ON DELETE RESTRICT ON UPDATE CASCADE,
                FOREIGN KEY (origen_venta_id) REFERENCES ventas (id) ON DELETE RESTRICT ON UPDATE CASCADE,
                FOREIGN KEY (origen_cheque_id) REFERENCES cheques (id) ON DELETE RESTRICT ON UPDATE CASCADE,
                CHECK ((cliente_id IS NULL) != (proveedor_id IS NULL)),
                CHECK (monto > 0),
                CHECK (origen IN ('manual', 'recepcion', 'venta', 'cheque_rechazado')),
                CHECK (origen != 'recepcion' OR origen_recepcion_id IS NOT NULL),
                CHECK (origen != 'venta' OR origen_venta_id IS NOT NULL),
                CHECK (origen != 'cheque_rechazado' OR origen_cheque_id IS NOT NULL)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO cc_cargos
                (id, cliente_id, proveedor_id, monto, fecha, origen, origen_recepcion_id,
                 origen_venta_id, origen_cheque_id, observacion)
            SELECT id, cliente_id, proveedor_id, monto, fecha, origen, origen_recepcion_id,
                   origen_venta_id, NULL, observacion
            FROM cc_cargos_old_sin_cheques
            """
        )
        conn.execute("DROP TABLE cc_cargos_old_sin_cheques")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cc_cargos_cliente_id ON cc_cargos (cliente_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cc_cargos_proveedor_id ON cc_cargos (proveedor_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cc_cargos_fecha ON cc_cargos (fecha)")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA legacy_alter_table = OFF")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cheques (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            numero            TEXT,
            banco             TEXT NOT NULL,
            librador          TEXT NOT NULL,
            cuit_librador     TEXT,
            monto             INTEGER NOT NULL,
            fecha_pago        TEXT NOT NULL,
            fecha_recepcion   TEXT NOT NULL,
            origen_tipo       TEXT NOT NULL,
            cliente_id        INTEGER,
            proveedor_id      INTEGER,
            estado            TEXT NOT NULL DEFAULT 'en_cartera',
            observacion       TEXT,
            cargo_generado_id INTEGER,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            FOREIGN KEY (proveedor_id) REFERENCES proveedores (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            FOREIGN KEY (cargo_generado_id) REFERENCES cc_cargos (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            CHECK (monto > 0),
            CHECK (origen_tipo IN ('recibido_cliente', 'propio')),
            CHECK (origen_tipo != 'recibido_cliente' OR cliente_id IS NOT NULL),
            CHECK (origen_tipo != 'propio' OR cliente_id IS NULL),
            CHECK (estado IN ('en_cartera', 'entregado_proveedor', 'baja', 'rechazado')),
            CHECK (estado != 'entregado_proveedor' OR proveedor_id IS NOT NULL)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cheques_cliente_id ON cheques (cliente_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cheques_proveedor_id ON cheques (proveedor_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cheques_estado ON cheques (estado)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cheques_fecha_pago ON cheques (fecha_pago)")

    columnas_venta_pagos_cheque = {fila["name"] for fila in conn.execute("PRAGMA table_info(venta_pagos)")}
    if "cheque_id" not in columnas_venta_pagos_cheque:
        conn.execute("ALTER TABLE venta_pagos ADD COLUMN cheque_id INTEGER REFERENCES cheques (id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_venta_pagos_cheque_id ON venta_pagos (cheque_id)")

    columnas_cc_pagos = {fila["name"] for fila in conn.execute("PRAGMA table_info(cc_pagos)")}
    if "cheque_id" not in columnas_cc_pagos:
        conn.execute("ALTER TABLE cc_pagos ADD COLUMN cheque_id INTEGER REFERENCES cheques (id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cc_pagos_cheque_id ON cc_pagos (cheque_id)")

    # Cierre de Fase 6: medio de pago en cada pago de CC + anulacion de pagos y cargos manuales
    # (nunca se borran: quedan marcados con fecha y motivo, y dejan de contar en los saldos).
    columnas_cc_pagos = {fila["name"] for fila in conn.execute("PRAGMA table_info(cc_pagos)")}
    if "medio_pago_id" not in columnas_cc_pagos:
        conn.execute("ALTER TABLE cc_pagos ADD COLUMN medio_pago_id INTEGER REFERENCES medios_pago (id)")
    if "anulado_fecha" not in columnas_cc_pagos:
        conn.execute("ALTER TABLE cc_pagos ADD COLUMN anulado_fecha TEXT")
    if "anulado_motivo" not in columnas_cc_pagos:
        conn.execute("ALTER TABLE cc_pagos ADD COLUMN anulado_motivo TEXT")
    if "reemplaza_pago_id" not in columnas_cc_pagos:
        # Si el pago nacio de una correccion, el pago viejo (anulado) al que reemplaza -- para
        # mostrar "antes: ..." en la fila vigente sin tener que ver la fila anulada.
        conn.execute("ALTER TABLE cc_pagos ADD COLUMN reemplaza_pago_id INTEGER REFERENCES cc_pagos (id)")
    columnas_cc_cargos = {fila["name"] for fila in conn.execute("PRAGMA table_info(cc_cargos)")}
    if "anulado_fecha" not in columnas_cc_cargos:
        conn.execute("ALTER TABLE cc_cargos ADD COLUMN anulado_fecha TEXT")
    if "anulado_motivo" not in columnas_cc_cargos:
        conn.execute("ALTER TABLE cc_cargos ADD COLUMN anulado_motivo TEXT")

    # Datos del negocio: una sola fila en 'negocio' + listas de cuentas bancarias y WhatsApp.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS negocio (
            id                     INTEGER PRIMARY KEY CHECK (id = 1),   -- una sola fila: hay un solo negocio
            razon_social           TEXT NOT NULL,             -- nombre legal (persona fisica o sociedad): el de la chequera
            cuit                   TEXT NOT NULL,
            condicion_iva_id       INTEGER,
            nombre_fantasia        TEXT,                      -- marca comercial, para el membrete
            ingresos_brutos        TEXT,
            inicio_actividades     TEXT,
            direccion              TEXT,
            ciudad                 TEXT,
            provincia              TEXT,
            codigo_postal          TEXT,
            telefono               TEXT,
            email                  TEXT,
            web                    TEXT,
            smtp_servidor          TEXT,                      -- la contrasena NO va aca: va al administrador de credenciales de Windows
            smtp_puerto            INTEGER,
            smtp_seguridad         TEXT,                      -- 'ssl' | 'starttls' | 'ninguna'
            smtp_usuario           TEXT,
            smtp_remitente_nombre  TEXT,
            smtp_remitente_email   TEXT,
            FOREIGN KEY (condicion_iva_id) REFERENCES condiciones_iva (id)
                ON DELETE SET NULL
                ON UPDATE CASCADE,
            CHECK (smtp_seguridad IS NULL OR smtp_seguridad IN ('ssl', 'starttls', 'ninguna')),
            CHECK (smtp_puerto IS NULL OR (smtp_puerto > 0 AND smtp_puerto <= 65535))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS negocio_cuentas_bancarias (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            banco         TEXT NOT NULL,
            titular       TEXT NOT NULL,                      -- el librador de los cheques propios de esta cuenta
            cuit_titular  TEXT,
            cbu           TEXT,
            alias         TEXT,
            es_principal  INTEGER NOT NULL DEFAULT 0,
            CHECK (es_principal IN (0, 1))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS negocio_whatsapp (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            numero        TEXT NOT NULL,                      -- formato internacional sin '+' ni espacios (ej. 5491122334455), para links wa.me
            etiqueta      TEXT,                               -- ej. 'Ventas', 'Administracion'
            es_principal  INTEGER NOT NULL DEFAULT 0,
            CHECK (es_principal IN (0, 1))
        )
        """
    )

    # Fase 5: notas de credito. La venta guarda el % de descuento fijo que tenia el cliente al
    # vender (hasta ahora se leia del cliente cada vez, y cambiarselo alteraba ventas viejas).
    columnas_ventas = {fila["name"] for fila in conn.execute("PRAGMA table_info(ventas)")}
    if "descuento_cliente_porcentaje" not in columnas_ventas:
        conn.execute("ALTER TABLE ventas ADD COLUMN descuento_cliente_porcentaje INTEGER")
        # Unica vez, al agregar la columna: las ventas existentes toman el % actual del cliente,
        # que es justamente con el que se venian mostrando hasta ahora.
        conn.execute(
            "UPDATE ventas SET descuento_cliente_porcentaje = "
            "(SELECT porcentaje_descuento FROM clientes WHERE clientes.id = ventas.cliente_id)"
        )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notas_credito (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            numero          TEXT NOT NULL UNIQUE,              -- 'NC-0001'
            venta_id        INTEGER NOT NULL,                  -- la venta que acredita (nunca se modifica)
            cliente_id      INTEGER NOT NULL,
            fecha           TEXT NOT NULL,
            motivo          TEXT NOT NULL,
            es_correccion   INTEGER NOT NULL DEFAULT 0,        -- 1 si se emitio desde "Corregir venta"
            FOREIGN KEY (venta_id) REFERENCES ventas (id)
                ON DELETE RESTRICT
                ON UPDATE CASCADE,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id)
                ON DELETE RESTRICT
                ON UPDATE CASCADE,
            CHECK (es_correccion IN (0, 1))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS nota_credito_items (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            nota_credito_id   INTEGER NOT NULL,
            venta_item_id     INTEGER NOT NULL,                -- precio y descuento salen de la linea vendida
            cantidad          INTEGER NOT NULL,                -- escalado x1000
            vuelve_stock      INTEGER NOT NULL DEFAULT 1,      -- 0 = roto/vencido: no vuelve, queda como perdida
            FOREIGN KEY (nota_credito_id) REFERENCES notas_credito (id)
                ON DELETE CASCADE
                ON UPDATE CASCADE,
            FOREIGN KEY (venta_item_id) REFERENCES venta_items (id)
                ON DELETE RESTRICT
                ON UPDATE CASCADE,
            CHECK (cantidad > 0),
            CHECK (vuelve_stock IN (0, 1))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS nota_credito_item_lotes (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            nota_credito_item_id   INTEGER NOT NULL,
            lote_id                INTEGER NOT NULL,           -- el mismo lote del que salio en la venta
            cantidad               INTEGER NOT NULL,           -- escalado x1000
            costo_unitario         INTEGER NOT NULL,           -- escalado x100, el costo con que salio
            FOREIGN KEY (nota_credito_item_id) REFERENCES nota_credito_items (id)
                ON DELETE CASCADE
                ON UPDATE CASCADE,
            FOREIGN KEY (lote_id) REFERENCES lotes (id)
                ON DELETE RESTRICT
                ON UPDATE CASCADE,
            CHECK (cantidad > 0),
            CHECK (costo_unitario >= 0)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS nota_credito_reintegros (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            nota_credito_id   INTEGER NOT NULL,
            tipo              TEXT NOT NULL,                   -- 'cuenta_corriente' | 'medio_pago' | 'cheque'
            monto             INTEGER NOT NULL,                -- escalado x100
            medio_pago_id     INTEGER,                         -- tipo 'medio_pago': en que se devolvio la plata
            cheque_id         INTEGER,                         -- tipo 'cheque': el cheque que se le devolvio
            cc_pago_id        INTEGER,                         -- tipo 'cuenta_corriente': el pago de CC que lo acredita
            FOREIGN KEY (nota_credito_id) REFERENCES notas_credito (id)
                ON DELETE CASCADE
                ON UPDATE CASCADE,
            FOREIGN KEY (medio_pago_id) REFERENCES medios_pago (id)
                ON DELETE RESTRICT
                ON UPDATE CASCADE,
            FOREIGN KEY (cheque_id) REFERENCES cheques (id)
                ON DELETE RESTRICT
                ON UPDATE CASCADE,
            FOREIGN KEY (cc_pago_id) REFERENCES cc_pagos (id)
                ON DELETE RESTRICT
                ON UPDATE CASCADE,
            CHECK (monto > 0),
            CHECK (tipo IN ('cuenta_corriente', 'medio_pago', 'cheque')),
            CHECK (tipo != 'medio_pago' OR medio_pago_id IS NOT NULL),
            CHECK (tipo != 'cheque' OR cheque_id IS NOT NULL),
            CHECK (tipo != 'cuenta_corriente' OR cc_pago_id IS NOT NULL)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notas_credito_venta_id ON notas_credito (venta_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nota_credito_items_venta_item_id ON nota_credito_items (venta_item_id)")
    columnas_cc_pagos = {fila["name"] for fila in conn.execute("PRAGMA table_info(cc_pagos)")}
    if "nota_credito_id" not in columnas_cc_pagos:
        # El credito que una nota de credito deja en la cuenta corriente del cliente.
        conn.execute("ALTER TABLE cc_pagos ADD COLUMN nota_credito_id INTEGER REFERENCES notas_credito (id)")

    # Ajustes de stock con lotes: un ingreso manual (stock inicial, sobrante de inventario) crea
    # su propio lote con origen 'ajuste' -- antes los ajustes no tocaban los lotes y stock y lotes
    # podian quedar descuadrados. El CHECK de 'origen' no se puede ampliar con ALTER: se
    # reconstruye la tabla (legacy_alter_table=ON para no romper las FK que apuntan a lotes).
    sql_lotes = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'lotes'").fetchone()[0]
    if "'ajuste'" not in sql_lotes:
        conn.execute("PRAGMA legacy_alter_table = ON")
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("ALTER TABLE lotes RENAME TO lotes_old_ajuste")
        conn.execute(
            """
            CREATE TABLE lotes (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                producto_id        INTEGER NOT NULL,
                recepcion_id       INTEGER,
                origen             TEXT NOT NULL DEFAULT 'recepcion',
                cantidad_recibida  INTEGER NOT NULL,
                cantidad_restante  INTEGER NOT NULL,
                costo_unitario     INTEGER NOT NULL,
                fecha              TEXT NOT NULL,
                FOREIGN KEY (producto_id) REFERENCES productos (id) ON DELETE RESTRICT ON UPDATE CASCADE,
                FOREIGN KEY (recepcion_id) REFERENCES recepciones (id) ON DELETE RESTRICT ON UPDATE CASCADE,
                CHECK (cantidad_recibida > 0), CHECK (cantidad_restante >= 0), CHECK (costo_unitario >= 0),
                CHECK (origen IN ('recepcion', 'inicial', 'ajuste')),
                CHECK (origen != 'recepcion' OR recepcion_id IS NOT NULL)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO lotes (id, producto_id, recepcion_id, origen, cantidad_recibida, cantidad_restante, costo_unitario, fecha)
            SELECT id, producto_id, recepcion_id, origen, cantidad_recibida, cantidad_restante, costo_unitario, fecha
            FROM lotes_old_ajuste
            """
        )
        conn.execute("DROP TABLE lotes_old_ajuste")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lotes_producto_id ON lotes (producto_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lotes_producto_fecha ON lotes (producto_id, fecha)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lotes_recepcion_id ON lotes (recepcion_id)")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA legacy_alter_table = OFF")

    # Fase 5: borradores de venta (pre-ventas; despues tambien presupuestos).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS borradores_venta (
            id                          INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo                        TEXT NOT NULL,             -- 'preventa' | 'presupuesto' (no son ventas: no tocan stock ni plata)
            nombre                      TEXT NOT NULL,             -- ej. 'Senora con anteojos'
            numero                      TEXT UNIQUE,               -- solo presupuestos ('P-0001')
            cliente_id                  INTEGER,
            cliente_nombre_nuevo        TEXT,
            usar_cliente_generico       INTEGER NOT NULL DEFAULT 1,
            lista_precio_id             INTEGER,
            iva_porcentaje              INTEGER,                   -- escalado x100
            descuento_total_porcentaje  INTEGER,                   -- escalado x100
            observacion                 TEXT,
            estado                      TEXT NOT NULL DEFAULT 'abierta',  -- abierta | convertida | descartada
            venta_id                    INTEGER,                   -- la venta en que se convirtio
            motivo_descarte             TEXT,
            fecha_creacion              TEXT NOT NULL,
            fecha_actualizacion         TEXT NOT NULL,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id)
                ON DELETE SET NULL
                ON UPDATE CASCADE,
            FOREIGN KEY (lista_precio_id) REFERENCES listas_precios (id)
                ON DELETE SET NULL
                ON UPDATE CASCADE,
            FOREIGN KEY (venta_id) REFERENCES ventas (id)
                ON DELETE SET NULL
                ON UPDATE CASCADE,
            CHECK (tipo IN ('preventa', 'presupuesto')),
            CHECK (estado IN ('abierta', 'convertida', 'descartada')),
            CHECK (usar_cliente_generico IN (0, 1)),
            CHECK (estado != 'convertida' OR venta_id IS NOT NULL)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS borrador_venta_items (
            id                          INTEGER PRIMARY KEY AUTOINCREMENT,
            borrador_id                 INTEGER NOT NULL,
            producto_id                 INTEGER,                   -- NULL si es item libre
            descripcion_libre           TEXT,
            cantidad                    INTEGER NOT NULL,          -- escalado x1000
            precio_unitario             INTEGER,                   -- escalado x100 (en una pre-venta, solo los items libres)
            descuento_item_porcentaje   INTEGER,                   -- escalado x100
            FOREIGN KEY (borrador_id) REFERENCES borradores_venta (id)
                ON DELETE CASCADE
                ON UPDATE CASCADE,
            FOREIGN KEY (producto_id) REFERENCES productos (id)
                ON DELETE RESTRICT
                ON UPDATE CASCADE,
            CHECK (cantidad > 0),
            CHECK (precio_unitario IS NULL OR precio_unitario >= 0),
            CHECK ((producto_id IS NULL) != (descripcion_libre IS NULL))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_borradores_venta_tipo_fecha ON borradores_venta (tipo, fecha_creacion)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_borrador_venta_items_borrador_id ON borrador_venta_items (borrador_id)")
    # Presupuestos: validez y % fijo del cliente congelado al presupuestar.
    columnas_borradores = {fila["name"] for fila in conn.execute("PRAGMA table_info(borradores_venta)")}
    if "fecha_validez" not in columnas_borradores:
        conn.execute("ALTER TABLE borradores_venta ADD COLUMN fecha_validez TEXT")
    if "descuento_cliente_porcentaje" not in columnas_borradores:
        conn.execute("ALTER TABLE borradores_venta ADD COLUMN descuento_cliente_porcentaje INTEGER")
    # Presupuestos: marca de las lineas cuyo precio el dueno cambio a mano (no es el de lista).
    columnas_borrador_items = {fila["name"] for fila in conn.execute("PRAGMA table_info(borrador_venta_items)")}
    if "precio_manual" not in columnas_borrador_items:
        conn.execute("ALTER TABLE borrador_venta_items ADD COLUMN precio_manual INTEGER NOT NULL DEFAULT 0")

    # IVA en todo el circuito: configuracion del negocio + cada venta/presupuesto sabe si sus
    # precios ya incluian IVA. De paso, el % de IVA de ventas y OC pasa a guardarse escalado x100
    # (como los demas porcentajes): asi admite alicuotas como 10,5. Todo en un solo paso: la
    # columna nueva de 'negocio' marca que esta conversion ya se hizo (nunca se repite).
    columnas_negocio = {fila["name"] for fila in conn.execute("PRAGMA table_info(negocio)")}
    if "alicuota_iva" not in columnas_negocio:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("ALTER TABLE negocio ADD COLUMN precios_incluyen_iva INTEGER NOT NULL DEFAULT 0")
            conn.execute("ALTER TABLE negocio ADD COLUMN alicuota_iva INTEGER NOT NULL DEFAULT 2100")
            conn.execute("ALTER TABLE ventas ADD COLUMN precios_con_iva INTEGER NOT NULL DEFAULT 0")
            conn.execute("ALTER TABLE borradores_venta ADD COLUMN precios_con_iva INTEGER NOT NULL DEFAULT 0")
            conn.execute("UPDATE ventas SET iva_porcentaje = iva_porcentaje * 100 WHERE iva_porcentaje IS NOT NULL")
            conn.execute("UPDATE ordenes_compra SET iva_porcentaje = iva_porcentaje * 100 WHERE iva_porcentaje IS NOT NULL")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    # Gastos del negocio (alquiler, sueldos, servicios...): la ganancia neta.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS categorias_gasto (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre  TEXT NOT NULL UNIQUE,
            activo  INTEGER NOT NULL DEFAULT 1,
            CHECK (activo IN (0, 1))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gastos (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha                 TEXT NOT NULL,                 -- AAAA-MM-DD
            descripcion           TEXT NOT NULL,
            categoria_gasto_id    INTEGER NOT NULL,
            monto_total           INTEGER NOT NULL,              -- escalado x100: lo que dice el comprobante
            iva_porcentaje        INTEGER,                       -- escalado x100 (2100 = 21%), NULL = sin IVA
            iva_recuperable       INTEGER NOT NULL DEFAULT 0,    -- 1 = el negocio era RI al cargarlo: el IVA no es gasto
            medio_pago_id         INTEGER,
            proveedor             TEXT,                          -- texto libre (YPF, Edesur...): no hace falta ficha
            observacion           TEXT,
            comprobante           TEXT,                          -- nombre del archivo en data/comprobantes/
            anulado_fecha         TEXT,
            anulado_motivo        TEXT,
            fecha_creacion        TEXT NOT NULL,
            FOREIGN KEY (categoria_gasto_id) REFERENCES categorias_gasto (id)
                ON DELETE RESTRICT
                ON UPDATE CASCADE,
            FOREIGN KEY (medio_pago_id) REFERENCES medios_pago (id)
                ON DELETE SET NULL
                ON UPDATE CASCADE,
            CHECK (monto_total > 0),
            CHECK (iva_porcentaje IS NULL OR iva_porcentaje >= 0),
            CHECK (iva_recuperable IN (0, 1))
        )
        """
    )
    # Solo si la tabla esta vacia: con AUTOINCREMENT, un INSERT que choca contra el UNIQUE igual
    # gasta un numero de la secuencia, y esto corre en cada conexion.
    if conn.execute("SELECT COUNT(*) FROM categorias_gasto").fetchone()[0] == 0:
        for nombre in ("Alquiler", "Sueldos", "Servicios", "Automotor", "Impositivos", "Bancarios", "Insumos del local", "Otros"):
            conn.execute("INSERT INTO categorias_gasto (nombre) VALUES (?)", (nombre,))
    conn.execute("CREATE INDEX IF NOT EXISTS idx_gastos_fecha ON gastos (fecha)")
    _migrar_formato_textos(conn, "formato_textos", _COLUMNAS_CON_FORMATO)
    # Despues se decidio que los nombres de personas tambien van en mayusculas.
    _migrar_formato_textos(conn, "contactos_en_mayusculas", [
        ("proveedores", "contacto", "mayusculas", False),
        ("clientes", "contacto_principal", "mayusculas", False),
        ("cliente_contactos", "nombre", "mayusculas", False),
        ("proveedor_contactos", "nombre", "mayusculas", False),
    ])


# Formato de los textos (ver app/shared/textos.py): (tabla, columna, formato, es UNIQUE).
_COLUMNAS_CON_FORMATO = [
    ("productos", "codigo", "mayusculas", True),
    ("productos", "nombre", "mayusculas", False),
    ("categorias", "nombre", "mayusculas", True),
    ("proveedores", "nombre", "mayusculas", True),
    ("proveedores", "contacto", "mayusculas", False),
    ("proveedores", "email", "email", False),
    ("clientes", "razon_social", "mayusculas", True),
    ("clientes", "contacto_principal", "mayusculas", False),
    ("clientes", "email", "email", False),
    ("cliente_contactos", "nombre", "mayusculas", False),
    ("cliente_contactos", "email", "email", False),
    ("proveedor_contactos", "nombre", "mayusculas", False),
    ("proveedor_contactos", "email", "email", False),
    ("listas_precios", "nombre", "mayusculas", True),
    ("medios_pago", "nombre", "primera_mayuscula", True),
    ("categorias_gasto", "nombre", "primera_mayuscula", True),
]


def _migrar_formato_textos(conn: sqlite3.Connection, nombre_migracion: str, columnas: list[tuple]) -> None:
    """Migracion de datos, una sola vez por nombre: pasa los textos ya cargados al formato que hoy
    aplican los servicios al guardar. Si al normalizar un valor UNIQUE chocaria con otra fila (ej.
    'Limpieza' y 'LIMPIEZA'), esa fila se deja como esta y queda anotada en el Historial."""
    conn.execute("CREATE TABLE IF NOT EXISTS migraciones_datos (nombre TEXT PRIMARY KEY, fecha TEXT NOT NULL)")
    if conn.execute("SELECT 1 FROM migraciones_datos WHERE nombre = ?", (nombre_migracion,)).fetchone():
        return
    from datetime import datetime

    from app.shared import textos

    conn.execute("BEGIN IMMEDIATE")
    try:
        cambiados, sin_cambiar = 0, []
        for tabla, columna, formato, unico in columnas:
            convertir = getattr(textos, formato)
            for fila in conn.execute(f"SELECT id, {columna} AS valor FROM {tabla} WHERE {columna} IS NOT NULL").fetchall():
                nuevo = convertir(fila["valor"])
                if nuevo == fila["valor"]:
                    continue
                if unico and conn.execute(f"SELECT 1 FROM {tabla} WHERE {columna} = ? AND id <> ?", (nuevo, fila["id"])).fetchone():
                    sin_cambiar.append(f"{tabla} #{fila['id']} '{fila['valor']}'")
                    continue
                conn.execute(f"UPDATE {tabla} SET {columna} = ? WHERE id = ?", (nuevo, fila["id"]))
                cambiados += 1
        ahora = datetime.now().isoformat()
        if cambiados or sin_cambiar:
            conn.execute(
                "INSERT INTO log_eventos (fecha, entidad, entidad_id, descripcion) VALUES (?, 'sistema', NULL, ?)",
                (ahora, f"Formato de textos ({nombre_migracion}): se unificaron {cambiados} valores"
                        + (f". Quedaron sin cambiar porque chocaban con otro igual: {', '.join(sin_cambiar)}" if sin_cambiar else "")),
            )
        conn.execute("INSERT INTO migraciones_datos (nombre, fecha) VALUES (?, ?)", (nombre_migracion, ahora))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
