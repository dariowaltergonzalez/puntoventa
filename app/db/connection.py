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
            FOREIGN KEY (venta_id) REFERENCES ventas (id) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (medio_pago_id) REFERENCES medios_pago (id) ON DELETE RESTRICT ON UPDATE CASCADE,
            CHECK (monto > 0)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_venta_pagos_venta_id ON venta_pagos (venta_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_venta_pagos_medio_pago_id ON venta_pagos (medio_pago_id)")
