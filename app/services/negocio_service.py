import re
import sqlite3
from decimal import Decimal

import keyring
from keyring.errors import PasswordDeleteError

from app.repositories import negocio_repo
from app.services import condiciones_iva_service, log_service
from app.services.exceptions import NegocioNoConfiguradoError
from app.shared.money import entero_a_porcentaje, porcentaje_a_entero

SEGURIDADES_SMTP = ("ssl", "starttls", "ninguna")

# La contrasena del correo va al administrador de credenciales de Windows, nunca a la base:
# quien copie puntoventa.db no se la lleva.
_KEYRING_SERVICIO = "puntoventa-smtp"

_CAMPOS_LOG = [
    "razon_social", "cuit", "condicion_iva_nombre", "nombre_fantasia", "ingresos_brutos", "inicio_actividades",
    "direccion", "ciudad", "provincia", "codigo_postal", "telefono", "email", "web",
    "smtp_servidor", "smtp_puerto", "smtp_seguridad", "smtp_usuario", "smtp_remitente_nombre", "smtp_remitente_email",
    "precios_incluyen_iva", "alicuota_iva",
]
CONDICION_QUE_COBRA_IVA = "Responsable Inscripto"


def _texto_o_none(valor: str | None) -> str | None:
    valor = (valor or "").strip()
    return valor or None


def _solo_digitos(valor: str | None) -> str:
    return re.sub(r"\D", "", valor or "")


def _validar_cuit(cuit: str | None, etiqueta: str) -> None:
    if cuit and len(_solo_digitos(cuit)) != 11:
        raise ValueError(f"{etiqueta} debe tener 11 digitos")


def _validar_email(email: str | None, etiqueta: str) -> None:
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError(f"{etiqueta} no parece un email valido")


def _nombre_condicion_iva(condicion_iva_id: int | None) -> str | None:
    if condicion_iva_id is None:
        return None
    return next((c["nombre"] for c in condiciones_iva_service.listar_condiciones_iva() if c["id"] == condicion_iva_id), None)


def _a_dict(fila: sqlite3.Row) -> dict:
    datos = {campo: fila[campo] for campo in negocio_repo.CAMPOS_NEGOCIO}
    datos["condicion_iva_nombre"] = _nombre_condicion_iva(fila["condicion_iva_id"])
    datos["precios_incluyen_iva"] = bool(fila["precios_incluyen_iva"])
    datos["alicuota_iva"] = entero_a_porcentaje(fila["alicuota_iva"])
    return datos


def config_iva() -> dict:
    """Unica fuente de verdad del IVA para toda la app (ventas, presupuestos, compras, ganancia).
      cobra_iva:            solo el Responsable Inscripto cobra IVA (en todas sus ventas)
      alicuota_entero:      x100 (2100 = 21%); 0 si no cobra
      precios_con_iva:      los precios de venta ya lo incluyen (se desglosa) o se suma encima
      iva_compras_es_costo: quien no cobra IVA tampoco lo recupera: el IVA de sus compras es costo
      configurado:          False si todavia no se cargaron los datos del negocio"""
    fila = negocio_repo.obtener()
    if fila is None or fila["condicion_iva_id"] is None:
        return {"cobra_iva": False, "alicuota_entero": 0, "precios_con_iva": False,
                "iva_compras_es_costo": False, "configurado": False, "condicion": None}
    condicion = _nombre_condicion_iva(fila["condicion_iva_id"])
    cobra = condicion == CONDICION_QUE_COBRA_IVA
    return {
        "cobra_iva": cobra,
        "alicuota_entero": fila["alicuota_iva"] if cobra else 0,
        "precios_con_iva": bool(fila["precios_incluyen_iva"]) if cobra else False,
        "iva_compras_es_costo": not cobra,
        "configurado": True,
        "condicion": condicion,
    }


def _cuenta_a_dict(fila: sqlite3.Row) -> dict:
    return {
        "id": fila["id"], "banco": fila["banco"], "titular": fila["titular"], "cuit_titular": fila["cuit_titular"],
        "cbu": fila["cbu"], "alias": fila["alias"], "es_principal": bool(fila["es_principal"]),
    }


def _whatsapp_a_dict(fila: sqlite3.Row) -> dict:
    return {
        "id": fila["id"], "numero": fila["numero"], "etiqueta": fila["etiqueta"],
        "es_principal": bool(fila["es_principal"]),
        "link": f"https://wa.me/{fila['numero']}",
    }


def obtener_negocio() -> dict | None:
    """None si todavia no se cargaron los datos del negocio."""
    fila = negocio_repo.obtener()
    if fila is None:
        return None
    negocio = _a_dict(fila)
    negocio["cuentas_bancarias"] = listar_cuentas_bancarias()
    negocio["whatsapp"] = listar_whatsapp()
    negocio["smtp_tiene_password"] = obtener_password_smtp() is not None
    return negocio


def guardar_negocio(
    razon_social: str,
    cuit: str,
    condicion_iva_id: int | None = None,
    nombre_fantasia: str | None = None,
    ingresos_brutos: str | None = None,
    inicio_actividades: str | None = None,
    direccion: str | None = None,
    ciudad: str | None = None,
    provincia: str | None = None,
    codigo_postal: str | None = None,
    telefono: str | None = None,
    email: str | None = None,
    web: str | None = None,
    smtp_servidor: str | None = None,
    smtp_puerto: int | None = None,
    smtp_seguridad: str | None = None,
    smtp_usuario: str | None = None,
    smtp_remitente_nombre: str | None = None,
    smtp_remitente_email: str | None = None,
    precios_incluyen_iva: bool = True,
    alicuota_iva: Decimal = Decimal("21"),
) -> dict:
    razon_social = (razon_social or "").strip()
    if not razon_social:
        raise ValueError("La razon social (nombre legal del titular) es obligatoria")
    cuit = (cuit or "").strip()
    if not cuit:
        raise ValueError("El CUIT es obligatorio")
    _validar_cuit(cuit, "El CUIT")
    email = _texto_o_none(email)
    _validar_email(email, "El email")
    smtp_remitente_email = _texto_o_none(smtp_remitente_email)
    _validar_email(smtp_remitente_email, "El email del remitente")
    if smtp_puerto is not None and not (0 < smtp_puerto <= 65535):
        raise ValueError("El puerto SMTP debe estar entre 1 y 65535")
    if smtp_seguridad is not None and smtp_seguridad not in SEGURIDADES_SMTP:
        raise ValueError(f"La seguridad SMTP debe ser una de {SEGURIDADES_SMTP}")
    if condicion_iva_id is not None and _nombre_condicion_iva(condicion_iva_id) is None:
        raise ValueError(f"No existe la condicion frente al IVA {condicion_iva_id}")
    if alicuota_iva is None or not (0 <= alicuota_iva <= 100):
        raise ValueError("La alicuota de IVA tiene que estar entre 0 y 100")

    datos = {
        "razon_social": razon_social, "cuit": cuit, "condicion_iva_id": condicion_iva_id,
        "nombre_fantasia": _texto_o_none(nombre_fantasia), "ingresos_brutos": _texto_o_none(ingresos_brutos),
        "inicio_actividades": _texto_o_none(inicio_actividades), "direccion": _texto_o_none(direccion),
        "ciudad": _texto_o_none(ciudad), "provincia": _texto_o_none(provincia),
        "codigo_postal": _texto_o_none(codigo_postal), "telefono": _texto_o_none(telefono), "email": email,
        "web": _texto_o_none(web), "smtp_servidor": _texto_o_none(smtp_servidor), "smtp_puerto": smtp_puerto,
        "smtp_seguridad": smtp_seguridad, "smtp_usuario": _texto_o_none(smtp_usuario),
        "smtp_remitente_nombre": _texto_o_none(smtp_remitente_nombre), "smtp_remitente_email": smtp_remitente_email,
        "precios_incluyen_iva": int(bool(precios_incluyen_iva)), "alicuota_iva": porcentaje_a_entero(alicuota_iva),
    }
    fila_antes = negocio_repo.obtener()
    negocio_repo.guardar(datos)
    despues = _a_dict(negocio_repo.obtener())
    if fila_antes is None:
        log_service.registrar("negocio", 1, f"Se cargaron los datos del negocio ({razon_social})")
    else:
        log_service.registrar_cambios("negocio", 1, _a_dict(fila_antes), despues, _CAMPOS_LOG)
    return obtener_negocio()


def _exigir_negocio() -> dict:
    negocio = obtener_negocio()
    if negocio is None:
        raise NegocioNoConfiguradoError("Primero guarda los datos del negocio (razon social y CUIT)")
    return negocio


# ---------- Contrasena SMTP (administrador de credenciales de Windows) ----------
def obtener_password_smtp() -> str | None:
    return keyring.get_password(_KEYRING_SERVICIO, "smtp")


def guardar_password_smtp(password: str | None) -> None:
    """None o vacio = borrar la contrasena guardada. El valor nunca se escribe en el Historial."""
    if password:
        keyring.set_password(_KEYRING_SERVICIO, "smtp", password)
        log_service.registrar("negocio", 1, "Se cambio la contrasena del correo saliente")
        return
    try:
        keyring.delete_password(_KEYRING_SERVICIO, "smtp")
    except PasswordDeleteError:
        return
    log_service.registrar("negocio", 1, "Se borro la contrasena del correo saliente")


# ---------- Cuentas bancarias ----------
def listar_cuentas_bancarias() -> list[dict]:
    return [_cuenta_a_dict(f) for f in negocio_repo.listar_cuentas_bancarias()]


def agregar_cuenta_bancaria(
    banco: str,
    titular: str | None = None,
    cuit_titular: str | None = None,
    cbu: str | None = None,
    alias: str | None = None,
    es_principal: bool = False,
) -> dict:
    """titular/cuit_titular vacios = los del negocio (el caso normal)."""
    negocio = _exigir_negocio()
    banco = (banco or "").strip()
    if not banco:
        raise ValueError("El banco es obligatorio")
    titular = _texto_o_none(titular) or negocio["razon_social"]
    cuit_titular = _texto_o_none(cuit_titular) or negocio["cuit"]
    _validar_cuit(cuit_titular, "El CUIT del titular")
    cbu = _texto_o_none(cbu)
    if cbu and (not cbu.isdigit() or len(cbu) != 22):
        raise ValueError("El CBU debe tener 22 digitos")
    cuenta_id = negocio_repo.crear_cuenta_bancaria(banco, titular, cuit_titular, cbu, _texto_o_none(alias), es_principal)
    log_service.registrar("negocio", 1, f"Se agrego la cuenta bancaria {banco} (titular {titular})")
    return _cuenta_a_dict(negocio_repo.obtener_cuenta_bancaria(cuenta_id))


def quitar_cuenta_bancaria(cuenta_id: int) -> None:
    cuenta = negocio_repo.obtener_cuenta_bancaria(cuenta_id)
    if cuenta is None:
        raise ValueError(f"No existe la cuenta bancaria {cuenta_id}")
    negocio_repo.eliminar_cuenta_bancaria(cuenta_id)
    log_service.registrar("negocio", 1, f"Se quito la cuenta bancaria {cuenta['banco']} (titular {cuenta['titular']})")


def marcar_cuenta_bancaria_principal(cuenta_id: int) -> None:
    cuenta = negocio_repo.obtener_cuenta_bancaria(cuenta_id)
    if cuenta is None:
        raise ValueError(f"No existe la cuenta bancaria {cuenta_id}")
    negocio_repo.marcar_cuenta_bancaria_principal(cuenta_id)
    log_service.registrar("negocio", 1, f"La cuenta bancaria {cuenta['banco']} paso a ser la principal")


# ---------- WhatsApp ----------
def normalizar_whatsapp(numero: str) -> str:
    """Formato internacional sin '+' ni espacios, el que piden los links wa.me. Para un celular
    argentino escrito 'a la local' (ej. 11 2233-4455) agrega el 549 adelante."""
    digitos = _solo_digitos(numero)
    if len(digitos) == 10:
        digitos = "549" + digitos
    if not 11 <= len(digitos) <= 15:
        raise ValueError("El numero de WhatsApp no parece valido (ej: 11 2233-4455 o +54 9 11 2233-4455)")
    return digitos


def listar_whatsapp() -> list[dict]:
    return [_whatsapp_a_dict(f) for f in negocio_repo.listar_whatsapp()]


def agregar_whatsapp(numero: str, etiqueta: str | None = None, es_principal: bool = False) -> dict:
    _exigir_negocio()
    numero = normalizar_whatsapp(numero)
    whatsapp_id = negocio_repo.crear_whatsapp(numero, _texto_o_none(etiqueta), es_principal)
    log_service.registrar("negocio", 1, f"Se agrego el WhatsApp {numero}")
    return _whatsapp_a_dict(negocio_repo.obtener_whatsapp(whatsapp_id))


def quitar_whatsapp(whatsapp_id: int) -> None:
    fila = negocio_repo.obtener_whatsapp(whatsapp_id)
    if fila is None:
        raise ValueError(f"No existe el WhatsApp {whatsapp_id}")
    negocio_repo.eliminar_whatsapp(whatsapp_id)
    log_service.registrar("negocio", 1, f"Se quito el WhatsApp {fila['numero']}")


def marcar_whatsapp_principal(whatsapp_id: int) -> None:
    fila = negocio_repo.obtener_whatsapp(whatsapp_id)
    if fila is None:
        raise ValueError(f"No existe el WhatsApp {whatsapp_id}")
    negocio_repo.marcar_whatsapp_principal(whatsapp_id)
    log_service.registrar("negocio", 1, f"El WhatsApp {fila['numero']} paso a ser el principal")
