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
    FOREIGN KEY (proveedor_id) REFERENCES proveedores (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CHECK (estado IN ('pendiente', 'recibida_parcial', 'recibida', 'cancelada')),
    CHECK (iva_porcentaje IS NULL OR iva_porcentaje >= 0)
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
CREATE INDEX IF NOT EXISTS idx_recepciones_oc_id ON recepciones (orden_compra_id);
CREATE INDEX IF NOT EXISTS idx_recepciones_fecha ON recepciones (fecha);
CREATE INDEX IF NOT EXISTS idx_recepcion_items_recepcion_id ON recepcion_items (recepcion_id);
CREATE INDEX IF NOT EXISTS idx_recepcion_items_producto_id ON recepcion_items (producto_id);
CREATE INDEX IF NOT EXISTS idx_lotes_producto_id ON lotes (producto_id);
CREATE INDEX IF NOT EXISTS idx_lotes_producto_fecha ON lotes (producto_id, fecha);
CREATE INDEX IF NOT EXISTS idx_lotes_recepcion_id ON lotes (recepcion_id);
