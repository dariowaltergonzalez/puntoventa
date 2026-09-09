import sqlite3

from app.db.connection import get_connection


def crear(
    razon_social: str,
    nombre_fantasia: str | None = None,
    dni: str | None = None,
    cuit: str | None = None,
    contacto_principal: str | None = None,
    telefono: str | None = None,
    email: str | None = None,
    direccion: str | None = None,
    ciudad: str | None = None,
    provincia: str | None = None,
    codigo_postal: str | None = None,
    condicion_iva_id: int | None = None,
    plazo_pago_dias: int | None = None,
    porcentaje_descuento: int | None = None,
    limite_credito: int | None = None,
    avisar_limite_credito: bool = False,
    bloquear_limite_credito: bool = False,
    tasa_interes_mora_diaria: int | None = None,
    observacion: str | None = None,
) -> int:
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO clientes
                (razon_social, nombre_fantasia, dni, cuit, contacto_principal, telefono, email,
                 direccion, ciudad, provincia, codigo_postal, condicion_iva_id, plazo_pago_dias,
                 porcentaje_descuento, limite_credito, avisar_limite_credito, bloquear_limite_credito,
                 tasa_interes_mora_diaria, observacion, activo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                razon_social, nombre_fantasia, dni, cuit, contacto_principal, telefono, email,
                direccion, ciudad, provincia, codigo_postal, condicion_iva_id, plazo_pago_dias,
                porcentaje_descuento, limite_credito, int(avisar_limite_credito), int(bloquear_limite_credito),
                tasa_interes_mora_diaria, observacion,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def actualizar(
    cliente_id: int,
    razon_social: str,
    nombre_fantasia: str | None,
    dni: str | None,
    cuit: str | None,
    contacto_principal: str | None,
    telefono: str | None,
    email: str | None,
    direccion: str | None,
    ciudad: str | None,
    provincia: str | None,
    codigo_postal: str | None,
    condicion_iva_id: int | None,
    plazo_pago_dias: int | None,
    porcentaje_descuento: int | None,
    limite_credito: int | None,
    avisar_limite_credito: bool,
    bloquear_limite_credito: bool,
    tasa_interes_mora_diaria: int | None,
    observacion: str | None,
    activo: int,
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE clientes
            SET razon_social = ?, nombre_fantasia = ?, dni = ?, cuit = ?, contacto_principal = ?,
                telefono = ?, email = ?, direccion = ?, ciudad = ?, provincia = ?, codigo_postal = ?,
                condicion_iva_id = ?, plazo_pago_dias = ?, porcentaje_descuento = ?, limite_credito = ?,
                avisar_limite_credito = ?, bloquear_limite_credito = ?, tasa_interes_mora_diaria = ?,
                observacion = ?, activo = ?
            WHERE id = ?
            """,
            (
                razon_social, nombre_fantasia, dni, cuit, contacto_principal, telefono, email,
                direccion, ciudad, provincia, codigo_postal, condicion_iva_id, plazo_pago_dias,
                porcentaje_descuento, limite_credito, int(avisar_limite_credito), int(bloquear_limite_credito),
                tasa_interes_mora_diaria, observacion, activo, cliente_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def obtener_por_id(cliente_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT c.*, ci.nombre AS condicion_iva_nombre
            FROM clientes c
            LEFT JOIN condiciones_iva ci ON ci.id = c.condicion_iva_id
            WHERE c.id = ?
            """,
            (cliente_id,),
        ).fetchone()
    finally:
        conn.close()


def obtener_por_razon_social(razon_social: str, conn: sqlite3.Connection | None = None) -> sqlite3.Row | None:
    conexion_propia = conn is None
    if conexion_propia:
        conn = get_connection()
    try:
        return conn.execute("SELECT * FROM clientes WHERE razon_social = ?", (razon_social,)).fetchone()
    finally:
        if conexion_propia:
            conn.close()


def obtener_o_crear_por_razon_social(razon_social: str, conn: sqlite3.Connection | None = None) -> sqlite3.Row:
    """Get-or-create idempotente y atomico, mismo criterio que proveedores_repo. El cliente
    auto-creado solo tiene 'razon_social'."""
    conexion_propia = conn is None
    if conexion_propia:
        conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO clientes (razon_social, activo) VALUES (?, 1) ON CONFLICT(razon_social) DO NOTHING",
            (razon_social,),
        )
        return conn.execute("SELECT * FROM clientes WHERE razon_social = ?", (razon_social,)).fetchone()
    finally:
        if conexion_propia:
            conn.close()


def listar(solo_activos: bool = False) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        sql = """
            SELECT c.*, ci.nombre AS condicion_iva_nombre
            FROM clientes c
            LEFT JOIN condiciones_iva ci ON ci.id = c.condicion_iva_id
        """
        if solo_activos:
            sql += " WHERE c.activo = 1"
        sql += " ORDER BY c.razon_social"
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


# ---- Contactos auxiliares ----

def crear_contacto(
    cliente_id: int, nombre: str, email: str | None, telefono: str | None,
    sector: str | None, es_principal: bool,
) -> int:
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO cliente_contactos (cliente_id, nombre, email, telefono, sector, es_principal)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (cliente_id, nombre, email, telefono, sector, int(es_principal)),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def actualizar_contacto(
    contacto_id: int, nombre: str, email: str | None, telefono: str | None,
    sector: str | None, es_principal: bool,
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE cliente_contactos
            SET nombre = ?, email = ?, telefono = ?, sector = ?, es_principal = ?
            WHERE id = ?
            """,
            (nombre, email, telefono, sector, int(es_principal), contacto_id),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_contacto(contacto_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM cliente_contactos WHERE id = ?", (contacto_id,))
        conn.commit()
    finally:
        conn.close()


def listar_contactos(cliente_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM cliente_contactos WHERE cliente_id = ? ORDER BY es_principal DESC, nombre",
            (cliente_id,),
        ).fetchall()
    finally:
        conn.close()
