PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS categorias (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE
);

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
);

CREATE TABLE IF NOT EXISTS productos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo         TEXT NOT NULL UNIQUE,
    nombre         TEXT NOT NULL,
    categoria_id   INTEGER NOT NULL,
    unidad         TEXT NOT NULL,
    precio_costo   INTEGER NOT NULL DEFAULT 0,   -- escalado x100 (2 decimales)
    precio_venta   INTEGER NOT NULL DEFAULT 0,   -- escalado x100 (2 decimales)
    activo         INTEGER NOT NULL DEFAULT 1,
    stock_actual   INTEGER NOT NULL DEFAULT 0,   -- escalado x1000 (3 decimales)
    stock_minimo   INTEGER NOT NULL DEFAULT 0,   -- escalado x1000 (3 decimales); 0 = sin umbral
    marca          TEXT,
    descripcion    TEXT,
    codigo_barra   TEXT UNIQUE,                  -- nullable: productos sueltos pueden no tener
    proveedor_id   INTEGER,                      -- nullable: producto puede no tener proveedor cargado
    FOREIGN KEY (categoria_id) REFERENCES categorias (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    FOREIGN KEY (proveedor_id) REFERENCES proveedores (id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,
    CHECK (activo IN (0, 1)),
    CHECK (precio_costo >= 0),
    CHECK (precio_venta >= 0),
    CHECK (stock_minimo >= 0)
);

CREATE TABLE IF NOT EXISTS contadores (
    nombre  TEXT PRIMARY KEY,
    valor   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS proveedor_contactos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    proveedor_id   INTEGER NOT NULL,
    nombre         TEXT NOT NULL,
    email          TEXT,
    telefono       TEXT,
    FOREIGN KEY (proveedor_id) REFERENCES proveedores (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS ordenes_compra (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    numero            TEXT NOT NULL UNIQUE,               -- 'OC-0001'
    proveedor_id      INTEGER NOT NULL,                   -- siempre resuelto (auto-alta o generico)
    estado            TEXT NOT NULL DEFAULT 'pendiente',  -- pendiente|recibida_parcial|recibida|cancelada
    fecha_creacion    TEXT NOT NULL,
    fecha_estimada    TEXT,                               -- nullable
    iva_porcentaje    INTEGER,                            -- % IVA opcional (ej 21); NULL = sin IVA
    observacion       TEXT,
    recibida_en_el_acto INTEGER NOT NULL DEFAULT 0,        -- 1 si se creo y recibio en el mismo momento ('ya la tenes en mano')
    FOREIGN KEY (proveedor_id) REFERENCES proveedores (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CHECK (estado IN ('pendiente', 'recibida_parcial', 'recibida', 'cancelada')),
    CHECK (iva_porcentaje IS NULL OR iva_porcentaje >= 0),
    CHECK (recibida_en_el_acto IN (0, 1))
);

CREATE TABLE IF NOT EXISTS orden_compra_items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_compra_id     INTEGER NOT NULL,
    producto_id         INTEGER,                  -- nullable: NULL si es item libre
    descripcion_libre   TEXT,                      -- solo si producto_id es NULL
    cantidad_pedida     INTEGER NOT NULL,          -- escalado x1000
    costo_pactado       INTEGER NOT NULL,          -- escalado x100
    cantidad_recibida   INTEGER NOT NULL DEFAULT 0, -- escalado x1000, acumulado (sin CHECK <= pedida: se permite recibir de mas)
    FOREIGN KEY (orden_compra_id) REFERENCES ordenes_compra (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    FOREIGN KEY (producto_id) REFERENCES productos (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CHECK (cantidad_pedida > 0),
    CHECK (costo_pactado >= 0),
    CHECK (cantidad_recibida >= 0),
    CHECK ((producto_id IS NULL) != (descripcion_libre IS NULL))
);

CREATE TABLE IF NOT EXISTS recepciones (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_compra_id    INTEGER NOT NULL,
    fecha              TEXT NOT NULL,
    numero_remito      TEXT,       -- nullable
    observacion        TEXT,
    FOREIGN KEY (orden_compra_id) REFERENCES ordenes_compra (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS lotes (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id        INTEGER NOT NULL,
    recepcion_id       INTEGER NOT NULL,
    cantidad_recibida  INTEGER NOT NULL,   -- escalado x1000, snapshot original
    cantidad_restante  INTEGER NOT NULL,   -- escalado x1000, la consume Fase 4 (FIFO)
    costo_unitario     INTEGER NOT NULL,   -- escalado x100, costo REAL de esta recepcion
    fecha              TEXT NOT NULL,      -- define el orden FIFO
    FOREIGN KEY (producto_id) REFERENCES productos (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    FOREIGN KEY (recepcion_id) REFERENCES recepciones (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CHECK (cantidad_recibida > 0),
    CHECK (cantidad_restante >= 0),
    CHECK (costo_unitario >= 0)
);

CREATE TABLE IF NOT EXISTS recepcion_items (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    recepcion_id           INTEGER NOT NULL,
    orden_compra_item_id   INTEGER,           -- nullable: item extra no pedido
    producto_id            INTEGER,           -- nullable: NULL si es item libre
    descripcion_libre      TEXT,               -- solo si producto_id es NULL
    cantidad_recibida      INTEGER NOT NULL,  -- escalado x1000
    costo_unitario         INTEGER NOT NULL,  -- escalado x100
    lote_id                INTEGER,           -- nullable: NULL si es item libre (no genera lote)
    FOREIGN KEY (recepcion_id) REFERENCES recepciones (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    FOREIGN KEY (orden_compra_item_id) REFERENCES orden_compra_items (id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,
    FOREIGN KEY (producto_id) REFERENCES productos (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    FOREIGN KEY (lote_id) REFERENCES lotes (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CHECK (cantidad_recibida > 0),
    CHECK (costo_unitario >= 0),
    CHECK ((producto_id IS NULL) != (descripcion_libre IS NULL))
);

CREATE TABLE IF NOT EXISTS movimientos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id     INTEGER NOT NULL,
    tipo            TEXT NOT NULL,                -- 'ingreso' | 'egreso'
    cantidad        INTEGER NOT NULL,             -- escalado x1000, siempre positivo
    fecha           TEXT NOT NULL,                -- ISO 8601, generada por el sistema
    motivo          TEXT NOT NULL,                -- 'compra', 'venta', 'ajuste', etc.
    referencia      TEXT,
    observacion     TEXT,
    lote_id         INTEGER,                      -- nullable: solo ingresos por compra via recepcion
    precio_unitario INTEGER,                      -- escalado x100, nullable: costo real de esa linea
    FOREIGN KEY (producto_id) REFERENCES productos (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    FOREIGN KEY (lote_id) REFERENCES lotes (id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,
    CHECK (tipo IN ('ingreso', 'egreso')),
    CHECK (cantidad > 0),
    CHECK (precio_unitario IS NULL OR precio_unitario >= 0)
);

CREATE TABLE IF NOT EXISTS log_eventos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha         TEXT NOT NULL,                 -- ISO 8601, generada por el sistema
    entidad       TEXT NOT NULL,                 -- 'categoria' | 'producto' | 'proveedor' | 'movimiento' | 'sistema'
    entidad_id    INTEGER,                       -- nullable: acciones de sistema sin registro asociado
    descripcion   TEXT NOT NULL                  -- mensaje legible ya armado por quien loguea
);

CREATE INDEX IF NOT EXISTS idx_movimientos_producto_id ON movimientos (producto_id);
CREATE INDEX IF NOT EXISTS idx_movimientos_fecha ON movimientos (fecha);
CREATE INDEX IF NOT EXISTS idx_movimientos_producto_fecha ON movimientos (producto_id, fecha);
CREATE INDEX IF NOT EXISTS idx_productos_categoria_id ON productos (categoria_id);
CREATE INDEX IF NOT EXISTS idx_log_eventos_fecha ON log_eventos (fecha);
CREATE INDEX IF NOT EXISTS idx_log_eventos_entidad ON log_eventos (entidad, entidad_id);
CREATE INDEX IF NOT EXISTS idx_proveedor_contactos_proveedor_id ON proveedor_contactos (proveedor_id);
CREATE INDEX IF NOT EXISTS idx_ordenes_compra_proveedor_id ON ordenes_compra (proveedor_id);
CREATE INDEX IF NOT EXISTS idx_ordenes_compra_estado ON ordenes_compra (estado);
CREATE INDEX IF NOT EXISTS idx_orden_compra_items_oc_id ON orden_compra_items (orden_compra_id);
CREATE INDEX IF NOT EXISTS idx_orden_compra_items_producto_id ON orden_compra_items (producto_id);

-- Fase 2: Clientes + listas de precios

CREATE TABLE IF NOT EXISTS condiciones_iva (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE,
    activo  INTEGER NOT NULL DEFAULT 1,
    CHECK (activo IN (0, 1))
);

INSERT OR IGNORE INTO condiciones_iva (nombre) VALUES
    ('Responsable Inscripto'), ('Monotributista'), ('Exento'), ('Consumidor Final');

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
    condicion_iva_id        INTEGER,                 -- FK a condiciones_iva, nullable
    plazo_pago_dias         INTEGER,                 -- nullable: sin plazo habitual definido
    porcentaje_descuento    INTEGER,                 -- escalado x100, nullable: sin descuento
    limite_credito          INTEGER,                 -- escalado x100, nullable: sin limite
    avisar_limite_credito   INTEGER NOT NULL DEFAULT 0,  -- flags independientes: puede avisar sin bloquear,
    bloquear_limite_credito INTEGER NOT NULL DEFAULT 0,  -- bloquear sin avisar, ambos, o ninguno
    tasa_interes_mora_diaria INTEGER,                -- escalado x100 (% diario), nullable: sin mora
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
);

CREATE TABLE IF NOT EXISTS cliente_contactos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id     INTEGER NOT NULL,
    nombre         TEXT NOT NULL,
    email          TEXT,
    telefono       TEXT,
    sector         TEXT,                             -- ej. 'Compras', 'Deposito'; opcional
    es_principal   INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (cliente_id) REFERENCES clientes (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CHECK (es_principal IN (0, 1))
);

CREATE TABLE IF NOT EXISTS listas_precios (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre              TEXT NOT NULL UNIQUE,
    porcentaje_general  INTEGER,                     -- escalado x100, nullable: sin % general cargado
    activo              INTEGER NOT NULL DEFAULT 1,
    CHECK (activo IN (0, 1))
);

CREATE TABLE IF NOT EXISTS listas_precios_categorias (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    lista_precio_id  INTEGER NOT NULL,
    categoria_id     INTEGER NOT NULL,
    porcentaje       INTEGER NOT NULL,                -- escalado x100
    FOREIGN KEY (lista_precio_id) REFERENCES listas_precios (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    FOREIGN KEY (categoria_id) REFERENCES categorias (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    UNIQUE (lista_precio_id, categoria_id)
);

CREATE TABLE IF NOT EXISTS listas_precios_productos (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    lista_precio_id  INTEGER NOT NULL,
    producto_id      INTEGER NOT NULL,
    precio_manual    INTEGER NOT NULL,                -- escalado x100, precio absoluto (no porcentaje)
    FOREIGN KEY (lista_precio_id) REFERENCES listas_precios (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    FOREIGN KEY (producto_id) REFERENCES productos (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CHECK (precio_manual >= 0),
    UNIQUE (lista_precio_id, producto_id)
);

CREATE TABLE IF NOT EXISTS cliente_listas_precios (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id       INTEGER NOT NULL,
    lista_precio_id  INTEGER NOT NULL,
    prioridad        INTEGER NOT NULL,                -- menor numero = mayor prioridad (se sugiere primero)
    FOREIGN KEY (cliente_id) REFERENCES clientes (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    FOREIGN KEY (lista_precio_id) REFERENCES listas_precios (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    UNIQUE (cliente_id, lista_precio_id)
);

CREATE INDEX IF NOT EXISTS idx_cliente_contactos_cliente_id ON cliente_contactos (cliente_id);
CREATE INDEX IF NOT EXISTS idx_listas_precios_categorias_lista_id ON listas_precios_categorias (lista_precio_id);
CREATE INDEX IF NOT EXISTS idx_listas_precios_productos_lista_id ON listas_precios_productos (lista_precio_id);
CREATE INDEX IF NOT EXISTS idx_listas_precios_productos_producto_id ON listas_precios_productos (producto_id);
CREATE INDEX IF NOT EXISTS idx_cliente_listas_precios_cliente_id ON cliente_listas_precios (cliente_id);
CREATE INDEX IF NOT EXISTS idx_recepciones_oc_id ON recepciones (orden_compra_id);
CREATE INDEX IF NOT EXISTS idx_recepciones_fecha ON recepciones (fecha);
CREATE INDEX IF NOT EXISTS idx_recepcion_items_recepcion_id ON recepcion_items (recepcion_id);
CREATE INDEX IF NOT EXISTS idx_recepcion_items_producto_id ON recepcion_items (producto_id);
CREATE INDEX IF NOT EXISTS idx_lotes_producto_id ON lotes (producto_id);
CREATE INDEX IF NOT EXISTS idx_lotes_producto_fecha ON lotes (producto_id, fecha);

-- Fase 3: Cuentas Corrientes

CREATE TABLE IF NOT EXISTS cc_cargos (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id            INTEGER,                    -- exactamente uno de cliente_id/proveedor_id
    proveedor_id          INTEGER,
    monto                 INTEGER NOT NULL,            -- escalado x100
    fecha                 TEXT NOT NULL,
    origen                TEXT NOT NULL,               -- 'manual' | 'recepcion' (futuro: 'venta')
    origen_recepcion_id   INTEGER,                     -- nullable: solo si origen = 'recepcion'
    observacion           TEXT,
    FOREIGN KEY (cliente_id) REFERENCES clientes (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    FOREIGN KEY (proveedor_id) REFERENCES proveedores (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    FOREIGN KEY (origen_recepcion_id) REFERENCES recepciones (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CHECK ((cliente_id IS NULL) != (proveedor_id IS NULL)),
    CHECK (monto > 0),
    CHECK (origen IN ('manual', 'recepcion', 'venta')),
    CHECK (origen != 'recepcion' OR origen_recepcion_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS cc_pagos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id     INTEGER,                    -- exactamente uno de cliente_id/proveedor_id
    proveedor_id   INTEGER,
    monto          INTEGER NOT NULL,           -- escalado x100
    fecha          TEXT NOT NULL,
    observacion    TEXT,
    FOREIGN KEY (cliente_id) REFERENCES clientes (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    FOREIGN KEY (proveedor_id) REFERENCES proveedores (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CHECK ((cliente_id IS NULL) != (proveedor_id IS NULL)),
    CHECK (monto > 0)
);

CREATE TABLE IF NOT EXISTS cc_pago_aplicaciones (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    pago_id    INTEGER NOT NULL,
    cargo_id   INTEGER NOT NULL,
    monto      INTEGER NOT NULL,               -- escalado x100, cuanto de ese pago fue a ese cargo
    FOREIGN KEY (pago_id) REFERENCES cc_pagos (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    FOREIGN KEY (cargo_id) REFERENCES cc_cargos (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CHECK (monto > 0)
);

CREATE INDEX IF NOT EXISTS idx_cc_cargos_cliente_id ON cc_cargos (cliente_id);
CREATE INDEX IF NOT EXISTS idx_cc_cargos_proveedor_id ON cc_cargos (proveedor_id);
CREATE INDEX IF NOT EXISTS idx_cc_cargos_fecha ON cc_cargos (fecha);
CREATE INDEX IF NOT EXISTS idx_cc_pagos_cliente_id ON cc_pagos (cliente_id);
CREATE INDEX IF NOT EXISTS idx_cc_pagos_proveedor_id ON cc_pagos (proveedor_id);
CREATE INDEX IF NOT EXISTS idx_cc_pago_aplicaciones_pago_id ON cc_pago_aplicaciones (pago_id);
CREATE INDEX IF NOT EXISTS idx_cc_pago_aplicaciones_cargo_id ON cc_pago_aplicaciones (cargo_id);
CREATE INDEX IF NOT EXISTS idx_lotes_recepcion_id ON lotes (recepcion_id);
