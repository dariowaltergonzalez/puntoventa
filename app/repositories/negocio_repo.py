import sqlite3

from app.db.connection import get_connection

CAMPOS_NEGOCIO = (
    "razon_social", "cuit", "condicion_iva_id", "nombre_fantasia", "ingresos_brutos", "inicio_actividades",
    "direccion", "ciudad", "provincia", "codigo_postal", "telefono", "email", "web",
    "smtp_servidor", "smtp_puerto", "smtp_seguridad", "smtp_usuario", "smtp_remitente_nombre", "smtp_remitente_email",
    "precios_incluyen_iva", "alicuota_iva",
)


def obtener() -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM negocio WHERE id = 1").fetchone()
    finally:
        conn.close()


def guardar(datos: dict) -> None:
    """Hay una sola fila (id = 1): la primera vez se inserta, despues se actualiza."""
    columnas = ", ".join(CAMPOS_NEGOCIO)
    marcadores = ", ".join("?" * len(CAMPOS_NEGOCIO))
    actualizaciones = ", ".join(f"{c} = excluded.{c}" for c in CAMPOS_NEGOCIO)
    conn = get_connection()
    try:
        conn.execute(
            f"INSERT INTO negocio (id, {columnas}) VALUES (1, {marcadores}) "
            f"ON CONFLICT(id) DO UPDATE SET {actualizaciones}",
            [datos[c] for c in CAMPOS_NEGOCIO],
        )
    finally:
        conn.close()


def _marcar_principal(conn: sqlite3.Connection, tabla: str, registro_id: int) -> None:
    conn.execute(f"UPDATE {tabla} SET es_principal = CASE WHEN id = ? THEN 1 ELSE 0 END", (registro_id,))


def _crear_en_lista(tabla: str, columnas: tuple[str, ...], valores: tuple, es_principal: bool) -> int:
    """Alta en una de las listas del negocio. Si es principal (o es la primera), desmarca las
    demas en la misma transaccion: siempre hay a lo sumo una principal."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        hay_otras = conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0] > 0
        cursor = conn.execute(
            f"INSERT INTO {tabla} ({', '.join(columnas)}) VALUES ({', '.join('?' * len(columnas))})", valores,
        )
        nuevo_id = cursor.lastrowid
        if es_principal or not hay_otras:
            _marcar_principal(conn, tabla, nuevo_id)
        conn.commit()
        return nuevo_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _eliminar_de_lista(tabla: str, registro_id: int) -> None:
    """Si se borra la principal, pasa a ser principal la mas vieja que quede."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        era_principal = conn.execute(f"SELECT es_principal FROM {tabla} WHERE id = ?", (registro_id,)).fetchone()
        conn.execute(f"DELETE FROM {tabla} WHERE id = ?", (registro_id,))
        if era_principal and era_principal[0]:
            siguiente = conn.execute(f"SELECT id FROM {tabla} ORDER BY id LIMIT 1").fetchone()
            if siguiente:
                _marcar_principal(conn, tabla, siguiente[0])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _marcar_principal_en_lista(tabla: str, registro_id: int) -> None:
    conn = get_connection()
    try:
        _marcar_principal(conn, tabla, registro_id)
    finally:
        conn.close()


def _listar(tabla: str) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(f"SELECT * FROM {tabla} ORDER BY es_principal DESC, id").fetchall()
    finally:
        conn.close()


def _obtener_de_lista(tabla: str, registro_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(f"SELECT * FROM {tabla} WHERE id = ?", (registro_id,)).fetchone()
    finally:
        conn.close()


# ---------- Cuentas bancarias ----------
def crear_cuenta_bancaria(
    banco: str, titular: str, cuit_titular: str | None, cbu: str | None, alias: str | None, es_principal: bool,
) -> int:
    return _crear_en_lista(
        "negocio_cuentas_bancarias", ("banco", "titular", "cuit_titular", "cbu", "alias"),
        (banco, titular, cuit_titular, cbu, alias), es_principal,
    )


def eliminar_cuenta_bancaria(cuenta_id: int) -> None:
    _eliminar_de_lista("negocio_cuentas_bancarias", cuenta_id)


def marcar_cuenta_bancaria_principal(cuenta_id: int) -> None:
    _marcar_principal_en_lista("negocio_cuentas_bancarias", cuenta_id)


def listar_cuentas_bancarias() -> list[sqlite3.Row]:
    return _listar("negocio_cuentas_bancarias")


def obtener_cuenta_bancaria(cuenta_id: int) -> sqlite3.Row | None:
    return _obtener_de_lista("negocio_cuentas_bancarias", cuenta_id)


# ---------- WhatsApp ----------
def crear_whatsapp(numero: str, etiqueta: str | None, es_principal: bool) -> int:
    return _crear_en_lista("negocio_whatsapp", ("numero", "etiqueta"), (numero, etiqueta), es_principal)


def eliminar_whatsapp(whatsapp_id: int) -> None:
    _eliminar_de_lista("negocio_whatsapp", whatsapp_id)


def marcar_whatsapp_principal(whatsapp_id: int) -> None:
    _marcar_principal_en_lista("negocio_whatsapp", whatsapp_id)


def listar_whatsapp() -> list[sqlite3.Row]:
    return _listar("negocio_whatsapp")


def obtener_whatsapp(whatsapp_id: int) -> sqlite3.Row | None:
    return _obtener_de_lista("negocio_whatsapp", whatsapp_id)
