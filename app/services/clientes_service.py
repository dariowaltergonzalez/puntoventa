import sqlite3
from decimal import Decimal

from app.repositories import clientes_repo, condiciones_iva_repo, listas_precios_repo
from app.services import log_service
from app.services.exceptions import (
    ClienteDuplicadoError,
    ClienteNoEncontradoError,
    CondicionIvaNoEncontradaError,
    ListaPrecioNoEncontradaError,
)
from app.shared.money import entero_a_porcentaje, entero_a_precio, porcentaje_a_entero, precio_a_entero

_CAMPOS_LOG = [
    "razon_social", "nombre_fantasia", "dni", "cuit", "contacto_principal", "telefono", "email",
    "direccion", "ciudad", "provincia", "codigo_postal", "condicion_iva_nombre", "plazo_pago_dias",
    "porcentaje_descuento", "limite_credito", "avisar_limite_credito", "bloquear_limite_credito",
    "tasa_interes_mora_diaria", "observacion", "activo",
]


def _texto_o_none(valor: str | None) -> str | None:
    valor = (valor or "").strip()
    return valor or None


def _a_dict(fila: sqlite3.Row) -> dict:
    return {
        "id": fila["id"],
        "razon_social": fila["razon_social"],
        "nombre_fantasia": fila["nombre_fantasia"],
        "dni": fila["dni"],
        "cuit": fila["cuit"],
        "contacto_principal": fila["contacto_principal"],
        "telefono": fila["telefono"],
        "email": fila["email"],
        "direccion": fila["direccion"],
        "ciudad": fila["ciudad"],
        "provincia": fila["provincia"],
        "codigo_postal": fila["codigo_postal"],
        "condicion_iva_id": fila["condicion_iva_id"],
        "condicion_iva_nombre": fila["condicion_iva_nombre"],
        "plazo_pago_dias": fila["plazo_pago_dias"],
        "porcentaje_descuento": entero_a_porcentaje(fila["porcentaje_descuento"]) if fila["porcentaje_descuento"] is not None else None,
        "limite_credito": entero_a_precio(fila["limite_credito"]) if fila["limite_credito"] is not None else None,
        "avisar_limite_credito": bool(fila["avisar_limite_credito"]),
        "bloquear_limite_credito": bool(fila["bloquear_limite_credito"]),
        "tasa_interes_mora_diaria": entero_a_porcentaje(fila["tasa_interes_mora_diaria"]) if fila["tasa_interes_mora_diaria"] is not None else None,
        "observacion": fila["observacion"],
        "activo": bool(fila["activo"]),
    }


def _contacto_a_dict(fila: sqlite3.Row) -> dict:
    return {
        "id": fila["id"],
        "cliente_id": fila["cliente_id"],
        "nombre": fila["nombre"],
        "email": fila["email"],
        "telefono": fila["telefono"],
        "sector": fila["sector"],
        "es_principal": bool(fila["es_principal"]),
    }


PLAZO_PAGO_MAXIMO_DIAS = 120
PORCENTAJE_DESCUENTO_MAXIMO = Decimal("100")
TASA_INTERES_MORA_MAXIMA = Decimal("20")


def _validar_plazo_pago(plazo_pago_dias: int | None) -> None:
    if plazo_pago_dias is None:
        return
    if not (0 <= plazo_pago_dias <= PLAZO_PAGO_MAXIMO_DIAS):
        raise ValueError(f"El plazo de pago debe estar entre 0 y {PLAZO_PAGO_MAXIMO_DIAS} dias")


def _validar_porcentaje_descuento(porcentaje_descuento: Decimal | None) -> None:
    if porcentaje_descuento is None:
        return
    if not (0 <= porcentaje_descuento <= PORCENTAJE_DESCUENTO_MAXIMO):
        raise ValueError(f"El % de descuento debe estar entre 0 y {PORCENTAJE_DESCUENTO_MAXIMO}")


def _validar_tasa_interes_mora(tasa_interes_mora_diaria: Decimal | None) -> None:
    if tasa_interes_mora_diaria is None:
        return
    if not (0 <= tasa_interes_mora_diaria <= TASA_INTERES_MORA_MAXIMA):
        raise ValueError(f"El interes por mora diario debe estar entre 0 y {TASA_INTERES_MORA_MAXIMA}%")


def _validar_limite_credito(
    limite_credito: Decimal | None, avisar: bool, bloquear: bool,
) -> tuple[int | None, bool, bool]:
    if limite_credito is None:
        if avisar or bloquear:
            raise ValueError("Para avisar o bloquear al superar un limite, primero hay que cargar el limite de credito")
        return None, False, False
    if limite_credito < 0:
        raise ValueError("El limite de credito no puede ser negativo")
    return precio_a_entero(limite_credito), avisar, bloquear


def _validar_condicion_iva(condicion_iva_id: int | None) -> None:
    if condicion_iva_id is None:
        return
    if condiciones_iva_repo.obtener_por_id(condicion_iva_id) is None:
        raise CondicionIvaNoEncontradaError(f"No existe la condicion ante el IVA {condicion_iva_id}")


def crear_cliente(
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
    porcentaje_descuento: Decimal | None = None,
    limite_credito: Decimal | None = None,
    avisar_limite_credito: bool = False,
    bloquear_limite_credito: bool = False,
    tasa_interes_mora_diaria: Decimal | None = None,
    observacion: str | None = None,
) -> dict:
    razon_social = razon_social.strip()
    if not razon_social:
        raise ValueError("La razon social del cliente no puede estar vacia")
    _validar_plazo_pago(plazo_pago_dias)
    _validar_porcentaje_descuento(porcentaje_descuento)
    _validar_tasa_interes_mora(tasa_interes_mora_diaria)
    _validar_condicion_iva(condicion_iva_id)

    limite_entero, avisar, bloquear = _validar_limite_credito(
        limite_credito, avisar_limite_credito, bloquear_limite_credito,
    )

    try:
        cliente_id = clientes_repo.crear(
            razon_social=razon_social,
            nombre_fantasia=_texto_o_none(nombre_fantasia),
            dni=_texto_o_none(dni),
            cuit=_texto_o_none(cuit),
            contacto_principal=_texto_o_none(contacto_principal),
            telefono=_texto_o_none(telefono),
            email=_texto_o_none(email),
            direccion=_texto_o_none(direccion),
            ciudad=_texto_o_none(ciudad),
            provincia=_texto_o_none(provincia),
            codigo_postal=_texto_o_none(codigo_postal),
            condicion_iva_id=condicion_iva_id,
            plazo_pago_dias=plazo_pago_dias,
            porcentaje_descuento=porcentaje_a_entero(porcentaje_descuento) if porcentaje_descuento is not None else None,
            limite_credito=limite_entero,
            avisar_limite_credito=avisar,
            bloquear_limite_credito=bloquear,
            tasa_interes_mora_diaria=porcentaje_a_entero(tasa_interes_mora_diaria) if tasa_interes_mora_diaria is not None else None,
            observacion=_texto_o_none(observacion),
        )
    except sqlite3.IntegrityError as exc:
        raise ClienteDuplicadoError(f"Ya existe un cliente con la razon social '{razon_social}'") from exc

    log_service.registrar("cliente", cliente_id, f"Se creo el cliente '{razon_social}'")
    return obtener_cliente(cliente_id)


def actualizar_cliente(
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
    porcentaje_descuento: Decimal | None,
    limite_credito: Decimal | None,
    avisar_limite_credito: bool,
    bloquear_limite_credito: bool,
    tasa_interes_mora_diaria: Decimal | None,
    observacion: str | None,
    activo: bool,
) -> dict:
    razon_social = razon_social.strip()
    if not razon_social:
        raise ValueError("La razon social del cliente no puede estar vacia")
    _validar_plazo_pago(plazo_pago_dias)
    _validar_porcentaje_descuento(porcentaje_descuento)
    _validar_tasa_interes_mora(tasa_interes_mora_diaria)
    _validar_condicion_iva(condicion_iva_id)

    antes = obtener_cliente(cliente_id)
    if antes is None:
        raise ClienteNoEncontradoError(f"No existe el cliente {cliente_id}")

    limite_entero, avisar, bloquear = _validar_limite_credito(
        limite_credito, avisar_limite_credito, bloquear_limite_credito,
    )

    try:
        clientes_repo.actualizar(
            cliente_id=cliente_id,
            razon_social=razon_social,
            nombre_fantasia=_texto_o_none(nombre_fantasia),
            dni=_texto_o_none(dni),
            cuit=_texto_o_none(cuit),
            contacto_principal=_texto_o_none(contacto_principal),
            telefono=_texto_o_none(telefono),
            email=_texto_o_none(email),
            direccion=_texto_o_none(direccion),
            ciudad=_texto_o_none(ciudad),
            provincia=_texto_o_none(provincia),
            codigo_postal=_texto_o_none(codigo_postal),
            condicion_iva_id=condicion_iva_id,
            plazo_pago_dias=plazo_pago_dias,
            porcentaje_descuento=porcentaje_a_entero(porcentaje_descuento) if porcentaje_descuento is not None else None,
            limite_credito=limite_entero,
            avisar_limite_credito=avisar,
            bloquear_limite_credito=bloquear,
            tasa_interes_mora_diaria=porcentaje_a_entero(tasa_interes_mora_diaria) if tasa_interes_mora_diaria is not None else None,
            observacion=_texto_o_none(observacion),
            activo=1 if activo else 0,
        )
    except sqlite3.IntegrityError as exc:
        raise ClienteDuplicadoError(f"Ya existe un cliente con la razon social '{razon_social}'") from exc

    despues = obtener_cliente(cliente_id)
    log_service.registrar_cambios("cliente", cliente_id, antes, despues, _CAMPOS_LOG)
    return despues


def obtener_cliente(cliente_id: int) -> dict | None:
    fila = clientes_repo.obtener_por_id(cliente_id)
    if fila is None:
        return None
    cliente = _a_dict(fila)
    cliente["contactos"] = [_contacto_a_dict(f) for f in clientes_repo.listar_contactos(cliente_id)]
    cliente["listas_precios"] = [
        {"lista_precio_id": f["lista_precio_id"], "nombre": f["lista_nombre"], "prioridad": f["prioridad"]}
        for f in listas_precios_repo.listar_listas_cliente(cliente_id)
    ]
    return cliente


def listar_clientes(solo_activos: bool = False) -> list[dict]:
    return [_a_dict(fila) for fila in clientes_repo.listar(solo_activos)]


def obtener_o_crear_cliente_por_razon_social(razon_social: str) -> dict:
    razon_social = razon_social.strip()
    if not razon_social:
        raise ValueError("La razon social del cliente no puede estar vacia")
    return _a_dict(clientes_repo.obtener_o_crear_por_razon_social(razon_social))


NOMBRE_CLIENTE_GENERICO = "Consumidor Final"


def obtener_o_crear_cliente_generico() -> dict:
    return _a_dict(clientes_repo.obtener_o_crear_por_razon_social(NOMBRE_CLIENTE_GENERICO))


# ---- Contactos auxiliares ----

def agregar_contacto(
    cliente_id: int, nombre: str, email: str | None, telefono: str | None,
    sector: str | None, es_principal: bool = False,
) -> dict:
    if obtener_cliente(cliente_id) is None:
        raise ClienteNoEncontradoError(f"No existe el cliente {cliente_id}")
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre del contacto no puede estar vacio")
    contacto_id = clientes_repo.crear_contacto(
        cliente_id, nombre, _texto_o_none(email), _texto_o_none(telefono), _texto_o_none(sector), es_principal,
    )
    log_service.registrar("cliente", cliente_id, f"Se agrego el contacto '{nombre}'")
    return obtener_cliente(cliente_id)


def editar_contacto(
    contacto_id: int, cliente_id: int, nombre: str, email: str | None, telefono: str | None,
    sector: str | None, es_principal: bool,
) -> dict:
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre del contacto no puede estar vacio")
    clientes_repo.actualizar_contacto(
        contacto_id, nombre, _texto_o_none(email), _texto_o_none(telefono), _texto_o_none(sector), es_principal,
    )
    log_service.registrar("cliente", cliente_id, f"Se edito el contacto '{nombre}'")
    return obtener_cliente(cliente_id)


def quitar_contacto(contacto_id: int, cliente_id: int) -> dict:
    clientes_repo.eliminar_contacto(contacto_id)
    log_service.registrar("cliente", cliente_id, "Se elimino un contacto")
    return obtener_cliente(cliente_id)


# ---- Listas de precios asignadas ----

def asignar_listas_precios(cliente_id: int, lista_ids_en_orden: list[int]) -> dict:
    """lista_ids_en_orden define la prioridad: la primera es la sugerida por defecto en la venta."""
    if obtener_cliente(cliente_id) is None:
        raise ClienteNoEncontradoError(f"No existe el cliente {cliente_id}")
    for lista_id in lista_ids_en_orden:
        if listas_precios_repo.obtener_por_id(lista_id) is None:
            raise ListaPrecioNoEncontradaError(f"No existe la lista de precios {lista_id}")
    listas_precios_repo.asignar_listas_cliente(cliente_id, lista_ids_en_orden)
    log_service.registrar("cliente", cliente_id, "Se actualizaron las listas de precios asignadas")
    return obtener_cliente(cliente_id)
