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
    iva_porcentaje    INTEGER,                            -- % IVA del proveedor, escalado x100 (2100 = 21%); NULL = sin IVA
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
    recepcion_id       INTEGER,              -- nullable: NULL si origen = 'inicial'
    origen             TEXT NOT NULL DEFAULT 'recepcion',  -- 'recepcion' | 'inicial' (stock de arranque) | 'ajuste' (sobrante de inventario)
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
    CHECK (costo_unitario >= 0),
    CHECK (origen IN ('recepcion', 'inicial', 'ajuste')),
    CHECK (origen != 'recepcion' OR recepcion_id IS NOT NULL)
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
    origen                TEXT NOT NULL,               -- 'manual' | 'recepcion' | 'venta' | 'cheque_rechazado'
    origen_recepcion_id   INTEGER,                     -- nullable: solo si origen = 'recepcion'
    origen_venta_id       INTEGER,                     -- nullable: solo si origen = 'venta'
    origen_cheque_id      INTEGER,                     -- nullable: solo si origen = 'cheque_rechazado'
    observacion           TEXT,
    anulado_fecha         TEXT,                        -- NULL = vigente (solo se anulan cargos manuales)
    anulado_motivo        TEXT,
    FOREIGN KEY (cliente_id) REFERENCES clientes (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    FOREIGN KEY (proveedor_id) REFERENCES proveedores (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    FOREIGN KEY (origen_recepcion_id) REFERENCES recepciones (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    FOREIGN KEY (origen_venta_id) REFERENCES ventas (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    FOREIGN KEY (origen_cheque_id) REFERENCES cheques (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CHECK ((cliente_id IS NULL) != (proveedor_id IS NULL)),
    CHECK (monto > 0),
    CHECK (origen IN ('manual', 'recepcion', 'venta', 'cheque_rechazado')),
    CHECK (origen != 'recepcion' OR origen_recepcion_id IS NOT NULL),
    CHECK (origen != 'venta' OR origen_venta_id IS NOT NULL),
    CHECK (origen != 'cheque_rechazado' OR origen_cheque_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS cc_pagos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id     INTEGER,                    -- exactamente uno de cliente_id/proveedor_id
    proveedor_id   INTEGER,
    monto          INTEGER NOT NULL,           -- escalado x100
    fecha          TEXT NOT NULL,
    observacion    TEXT,
    cheque_id      INTEGER,                    -- nullable: si el pago se hizo/recibio con un cheque
    medio_pago_id  INTEGER,                    -- nullable solo por pagos viejos; la app siempre lo carga
    anulado_fecha  TEXT,                       -- NULL = vigente; si no, el pago no cuenta en los saldos
    anulado_motivo TEXT,
    reemplaza_pago_id INTEGER,                 -- si nacio de una correccion: el pago viejo (anulado) que reemplaza
    nota_credito_id INTEGER,                   -- si es el credito de una nota de credito (no se anula desde CC)
    FOREIGN KEY (cliente_id) REFERENCES clientes (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    FOREIGN KEY (proveedor_id) REFERENCES proveedores (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    FOREIGN KEY (cheque_id) REFERENCES cheques (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    FOREIGN KEY (medio_pago_id) REFERENCES medios_pago (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    FOREIGN KEY (reemplaza_pago_id) REFERENCES cc_pagos (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    FOREIGN KEY (nota_credito_id) REFERENCES notas_credito (id)
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
CREATE INDEX IF NOT EXISTS idx_cc_pagos_cheque_id ON cc_pagos (cheque_id);
CREATE INDEX IF NOT EXISTS idx_cc_pago_aplicaciones_pago_id ON cc_pago_aplicaciones (pago_id);
CREATE INDEX IF NOT EXISTS idx_cc_pago_aplicaciones_cargo_id ON cc_pago_aplicaciones (cargo_id);
CREATE INDEX IF NOT EXISTS idx_lotes_recepcion_id ON lotes (recepcion_id);

-- Fase 4: Ventas

CREATE TABLE IF NOT EXISTS medios_pago (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre               TEXT NOT NULL UNIQUE,
    es_cuenta_corriente  INTEGER NOT NULL DEFAULT 0,  -- si se marca, ese pago genera cargo en Cuentas Corrientes
    activo               INTEGER NOT NULL DEFAULT 1,
    CHECK (es_cuenta_corriente IN (0, 1)),
    CHECK (activo IN (0, 1))
);

INSERT OR IGNORE INTO medios_pago (nombre, es_cuenta_corriente) VALUES
    ('Efectivo', 0), ('Tarjeta', 0), ('Transferencia', 0), ('Cuenta corriente', 1);

CREATE TABLE IF NOT EXISTS ventas (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    numero                      TEXT NOT NULL UNIQUE,               -- 'V-0001'
    cliente_id                  INTEGER NOT NULL,                   -- siempre resuelto (auto-alta o generico)
    lista_precio_id             INTEGER,                            -- nullable: sin lista, precio normal
    estado                      TEXT NOT NULL DEFAULT 'pendiente',  -- pendiente|confirmada (una venta normal nace confirmada)
    fecha                       TEXT NOT NULL,
    fecha_confirmacion          TEXT,                               -- nullable: cuando paso a confirmada
    iva_porcentaje              INTEGER,                            -- % IVA escalado x100 (2100 = 21%); NULL/0 = sin IVA
    precios_con_iva             INTEGER NOT NULL DEFAULT 0,         -- 1 = los precios ya incluian el IVA (se desglosa)
    descuento_total_porcentaje  INTEGER,                            -- escalado x100, descuento manual sobre el total
    descuento_cliente_porcentaje INTEGER,                           -- escalado x100, % fijo del cliente AL MOMENTO de vender
    observacion                 TEXT,
    FOREIGN KEY (cliente_id) REFERENCES clientes (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    FOREIGN KEY (lista_precio_id) REFERENCES listas_precios (id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,
    CHECK (estado IN ('pendiente', 'confirmada')),
    CHECK (iva_porcentaje IS NULL OR iva_porcentaje >= 0),
    CHECK (descuento_total_porcentaje IS NULL OR descuento_total_porcentaje >= 0)
);

CREATE TABLE IF NOT EXISTS venta_items (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    venta_id                    INTEGER NOT NULL,
    producto_id                 INTEGER,                  -- nullable: NULL si es item libre
    descripcion_libre           TEXT,                      -- solo si producto_id es NULL
    cantidad                    INTEGER NOT NULL,          -- escalado x1000
    precio_unitario             INTEGER NOT NULL,          -- escalado x100, ya resuelto por la lista (o precio normal), antes de descuentos
    descuento_item_porcentaje   INTEGER,                    -- escalado x100, descuento manual de esta linea puntual
    FOREIGN KEY (venta_id) REFERENCES ventas (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    FOREIGN KEY (producto_id) REFERENCES productos (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CHECK (cantidad > 0),
    CHECK (precio_unitario >= 0),
    CHECK (descuento_item_porcentaje IS NULL OR descuento_item_porcentaje >= 0),
    CHECK ((producto_id IS NULL) != (descripcion_libre IS NULL))
);

CREATE TABLE IF NOT EXISTS venta_item_lotes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    venta_item_id    INTEGER NOT NULL,
    lote_id          INTEGER NOT NULL,
    cantidad         INTEGER NOT NULL,          -- escalado x1000, cuanto de ese lote se consumio para esta linea
    costo_unitario   INTEGER NOT NULL,          -- escalado x100, snapshot del costo del lote al momento de vender
    FOREIGN KEY (venta_item_id) REFERENCES venta_items (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    FOREIGN KEY (lote_id) REFERENCES lotes (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CHECK (cantidad > 0),
    CHECK (costo_unitario >= 0)
);

CREATE TABLE IF NOT EXISTS venta_pagos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    venta_id       INTEGER NOT NULL,
    medio_pago_id  INTEGER NOT NULL,
    monto          INTEGER NOT NULL,            -- escalado x100
    recibido       INTEGER,                     -- escalado x100; solo efectivo, NULL en el resto
    cheque_id      INTEGER,                     -- nullable: si se pago con un cheque
    FOREIGN KEY (venta_id) REFERENCES ventas (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    FOREIGN KEY (medio_pago_id) REFERENCES medios_pago (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    FOREIGN KEY (cheque_id) REFERENCES cheques (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CHECK (monto > 0),
    CHECK (recibido IS NULL OR recibido >= monto)
);

-- Fase 6: Cheques
CREATE TABLE IF NOT EXISTS cheques (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    numero            TEXT,                     -- opcional
    banco             TEXT NOT NULL,
    librador          TEXT NOT NULL,             -- quien lo firmo (no siempre es el cliente mismo)
    cuit_librador     TEXT,                      -- opcional
    monto             INTEGER NOT NULL,          -- escalado x100
    fecha_pago        TEXT NOT NULL,             -- vencimiento/cuando se puede cobrar
    fecha_recepcion   TEXT NOT NULL,
    origen_tipo       TEXT NOT NULL,             -- 'recibido_cliente' | 'propio'
    cliente_id        INTEGER,                   -- solo si origen_tipo = 'recibido_cliente'
    proveedor_id      INTEGER,                   -- seteado cuando estado = 'entregado_proveedor'
    estado            TEXT NOT NULL DEFAULT 'en_cartera',
    observacion       TEXT,                      -- tambien se usa como motivo de baja/rechazo
    cargo_generado_id INTEGER,                   -- si estado = 'rechazado': el cargo que reabrio la deuda
    FOREIGN KEY (cliente_id) REFERENCES clientes (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    FOREIGN KEY (proveedor_id) REFERENCES proveedores (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    FOREIGN KEY (cargo_generado_id) REFERENCES cc_cargos (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CHECK (monto > 0),
    CHECK (origen_tipo IN ('recibido_cliente', 'propio')),
    CHECK (origen_tipo != 'recibido_cliente' OR cliente_id IS NOT NULL),
    CHECK (origen_tipo != 'propio' OR cliente_id IS NULL),
    CHECK (estado IN ('en_cartera', 'entregado_proveedor', 'baja', 'rechazado')),
    CHECK (estado != 'entregado_proveedor' OR proveedor_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_cheques_cliente_id ON cheques (cliente_id);
CREATE INDEX IF NOT EXISTS idx_cheques_proveedor_id ON cheques (proveedor_id);
CREATE INDEX IF NOT EXISTS idx_cheques_estado ON cheques (estado);
CREATE INDEX IF NOT EXISTS idx_cheques_fecha_pago ON cheques (fecha_pago);

CREATE INDEX IF NOT EXISTS idx_ventas_cliente_id ON ventas (cliente_id);
CREATE INDEX IF NOT EXISTS idx_ventas_fecha ON ventas (fecha);
CREATE INDEX IF NOT EXISTS idx_ventas_estado ON ventas (estado);
CREATE INDEX IF NOT EXISTS idx_venta_items_venta_id ON venta_items (venta_id);
CREATE INDEX IF NOT EXISTS idx_venta_items_producto_id ON venta_items (producto_id);
CREATE INDEX IF NOT EXISTS idx_venta_item_lotes_venta_item_id ON venta_item_lotes (venta_item_id);
CREATE INDEX IF NOT EXISTS idx_venta_item_lotes_lote_id ON venta_item_lotes (lote_id);
CREATE INDEX IF NOT EXISTS idx_venta_pagos_venta_id ON venta_pagos (venta_id);
CREATE INDEX IF NOT EXISTS idx_venta_pagos_medio_pago_id ON venta_pagos (medio_pago_id);
CREATE INDEX IF NOT EXISTS idx_venta_pagos_cheque_id ON venta_pagos (cheque_id);

-- Datos del negocio

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
    precios_incluyen_iva   INTEGER NOT NULL DEFAULT 1,  -- 1 = el precio del producto es el final (IVA adentro)
    alicuota_iva           INTEGER NOT NULL DEFAULT 2100,  -- escalado x100 (21%)
    FOREIGN KEY (condicion_iva_id) REFERENCES condiciones_iva (id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,
    CHECK (smtp_seguridad IS NULL OR smtp_seguridad IN ('ssl', 'starttls', 'ninguna')),
    CHECK (smtp_puerto IS NULL OR (smtp_puerto > 0 AND smtp_puerto <= 65535))
);

CREATE TABLE IF NOT EXISTS negocio_cuentas_bancarias (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    banco         TEXT NOT NULL,
    titular       TEXT NOT NULL,                      -- el librador de los cheques propios de esta cuenta
    cuit_titular  TEXT,
    cbu           TEXT,
    alias         TEXT,
    es_principal  INTEGER NOT NULL DEFAULT 0,
    CHECK (es_principal IN (0, 1))
);

CREATE TABLE IF NOT EXISTS negocio_whatsapp (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    numero        TEXT NOT NULL,                      -- formato internacional sin '+' ni espacios (ej. 5491122334455), para links wa.me
    etiqueta      TEXT,                               -- ej. 'Ventas', 'Administracion'
    es_principal  INTEGER NOT NULL DEFAULT 0,
    CHECK (es_principal IN (0, 1))
);

-- Fase 5: Notas de credito

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
);

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
);

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
);

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
);

CREATE INDEX IF NOT EXISTS idx_notas_credito_venta_id ON notas_credito (venta_id);
CREATE INDEX IF NOT EXISTS idx_nota_credito_items_venta_item_id ON nota_credito_items (venta_item_id);

-- Fase 5: borradores de venta (pre-ventas y presupuestos)

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
    precios_con_iva             INTEGER NOT NULL DEFAULT 0,
    descuento_total_porcentaje  INTEGER,                   -- escalado x100
    observacion                 TEXT,
    estado                      TEXT NOT NULL DEFAULT 'abierta',  -- abierta | convertida | descartada
    venta_id                    INTEGER,                   -- la venta en que se convirtio
    motivo_descarte             TEXT,
    fecha_validez               TEXT,                      -- solo presupuestos (AAAA-MM-DD, inclusive)
    descuento_cliente_porcentaje INTEGER,                  -- solo presupuestos: % fijo del cliente congelado (x100)
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
);

CREATE TABLE IF NOT EXISTS borrador_venta_items (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    borrador_id                 INTEGER NOT NULL,
    producto_id                 INTEGER,                   -- NULL si es item libre
    descripcion_libre           TEXT,
    cantidad                    INTEGER NOT NULL,          -- escalado x1000
    precio_unitario             INTEGER,                   -- escalado x100 (en una pre-venta, solo los items libres)
    descuento_item_porcentaje   INTEGER,                   -- escalado x100
    precio_manual               INTEGER NOT NULL DEFAULT 0,  -- 1 = precio cambiado a mano en un presupuesto
    FOREIGN KEY (borrador_id) REFERENCES borradores_venta (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    FOREIGN KEY (producto_id) REFERENCES productos (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CHECK (cantidad > 0),
    CHECK (precio_unitario IS NULL OR precio_unitario >= 0),
    CHECK ((producto_id IS NULL) != (descripcion_libre IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_borradores_venta_tipo_fecha ON borradores_venta (tipo, fecha_creacion);
CREATE INDEX IF NOT EXISTS idx_borrador_venta_items_borrador_id ON borrador_venta_items (borrador_id);

-- Gastos del negocio

CREATE TABLE IF NOT EXISTS categorias_gasto (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE,
    activo  INTEGER NOT NULL DEFAULT 1,
    CHECK (activo IN (0, 1))
);

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
);

INSERT INTO categorias_gasto (nombre)
    SELECT nombre FROM (SELECT 'Alquiler' AS nombre UNION ALL SELECT 'Sueldos' UNION ALL SELECT 'Servicios'
        UNION ALL SELECT 'Automotor' UNION ALL SELECT 'Impositivos' UNION ALL SELECT 'Bancarios'
        UNION ALL SELECT 'Insumos del local' UNION ALL SELECT 'Otros')
    WHERE NOT EXISTS (SELECT 1 FROM categorias_gasto);
CREATE INDEX IF NOT EXISTS idx_gastos_fecha ON gastos (fecha);
