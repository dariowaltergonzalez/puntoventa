PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS categorias (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE
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
    proveedor_id   INTEGER,                      -- nullable, sin FK todavia (no existe tabla proveedores aun)
    FOREIGN KEY (categoria_id) REFERENCES categorias (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CHECK (activo IN (0, 1)),
    CHECK (precio_costo >= 0),
    CHECK (precio_venta >= 0),
    CHECK (stock_minimo >= 0)
);

CREATE TABLE IF NOT EXISTS movimientos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id    INTEGER NOT NULL,
    tipo           TEXT NOT NULL,                -- 'ingreso' | 'egreso'
    cantidad       INTEGER NOT NULL,             -- escalado x1000, siempre positivo
    fecha          TEXT NOT NULL,                -- ISO 8601, generada por el sistema
    motivo         TEXT NOT NULL,                -- 'compra', 'venta', 'ajuste', etc.
    referencia     TEXT,
    observacion    TEXT,
    FOREIGN KEY (producto_id) REFERENCES productos (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CHECK (tipo IN ('ingreso', 'egreso')),
    CHECK (cantidad > 0)
);

CREATE INDEX IF NOT EXISTS idx_movimientos_producto_id ON movimientos (producto_id);
CREATE INDEX IF NOT EXISTS idx_movimientos_fecha ON movimientos (fecha);
CREATE INDEX IF NOT EXISTS idx_movimientos_producto_fecha ON movimientos (producto_id, fecha);
CREATE INDEX IF NOT EXISTS idx_productos_categoria_id ON productos (categoria_id);
