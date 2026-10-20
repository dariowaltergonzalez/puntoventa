"""Presupuestos: cotizaciones al cliente con numero (P-0001) y fecha de validez. No son ventas: no
tocan stock ni plata. Congelan el precio de cada producto y el % fijo del cliente: si se cobra
estando vigente, se respeta lo prometido. Vencido no se cobra: se renueva con precios de hoy."""

import sqlite3
from datetime import date, timedelta
from decimal import Decimal

from app.repositories import borradores_repo, productos_repo
from app.services import clientes_service, ganancias_service, listas_precios_service, log_service, negocio_service, ventas_service
from app.services.exceptions import PresupuestoNoDisponibleError
from app.services.preventas_service import validar_items_borrador
from app.shared.money import (
    entero_a_cantidad,
    entero_a_porcentaje,
    entero_a_precio,
    formatear_cantidad,
    formatear_precio,
    porcentaje_a_entero,
    precio_a_entero,
)

TIPO = "presupuesto"
VALIDEZ_DIAS = 15
ESTADOS = {"vigente": "Vigente", "vencido": "Vencido", "convertido": "Convertido en venta", "rechazado": "Rechazado"}


def _texto_o_none(valor: str | None) -> str | None:
    return (valor or "").strip() or None


def _precio_de_hoy(producto_id: int, lista_precio_id: int | None) -> int:
    if lista_precio_id is not None:
        return precio_a_entero(listas_precios_service.calcular_precio_producto(producto_id, lista_precio_id))
    return productos_repo.obtener_por_id(producto_id)["precio_venta"]


def _descuento_cliente_hoy(cliente_id: int | None) -> int | None:
    cliente = clientes_service.obtener_cliente(cliente_id) if cliente_id else None
    if cliente is None or not cliente["porcentaje_descuento"]:
        return None
    return porcentaje_a_entero(cliente["porcentaje_descuento"])


def _estado_visible(fila: sqlite3.Row) -> str:
    if fila["estado"] == "convertida":
        return "convertido"
    if fila["estado"] == "descartada":
        return "rechazado"
    return "vigente" if fila["fecha_validez"] >= date.today().isoformat() else "vencido"


def _exigir(presupuesto_id: int, vigente: bool = False) -> sqlite3.Row:
    fila = borradores_repo.obtener(presupuesto_id)
    if fila is None or fila["tipo"] != TIPO:
        raise PresupuestoNoDisponibleError(f"No existe el presupuesto {presupuesto_id}")
    estado = _estado_visible(fila)
    if estado in ("convertido", "rechazado"):
        raise PresupuestoNoDisponibleError(f"El presupuesto {fila['numero']} ya fue {ESTADOS[estado].lower()}")
    if vigente and estado == "vencido":
        raise PresupuestoNoDisponibleError(
            f"El presupuesto {fila['numero']} esta vencido: renovalo (con los precios de hoy) antes de modificarlo"
        )
    return fila


def guardar_presupuesto(
    presupuesto_id: int | None,
    items: list[dict],
    cliente_id: int | None = None,
    cliente_nombre_nuevo: str | None = None,
    usar_cliente_generico: bool = True,
    lista_precio_id: int | None = None,
    descuento_total_porcentaje: Decimal | None = None,
    observacion: str | None = None,
    validez_dias: int = VALIDEZ_DIAS,
) -> dict:
    """Alta (presupuesto_id None) o modificacion de uno vigente, que conserva su numero.
    Precios: los productos que ya estaban conservan el precio prometido; los nuevos van al de hoy.
    Los items libres llevan el precio escrito."""
    existente = _exigir(presupuesto_id, vigente=True) if presupuesto_id is not None else None
    if validez_dias is None or validez_dias < 1:
        raise ValueError("La validez tiene que ser de al menos 1 dia")
    if descuento_total_porcentaje is not None and descuento_total_porcentaje < 0:
        raise ValueError("El descuento sobre el total no puede ser negativo")
    items_validados = validar_items_borrador(items)

    cliente_id = None if usar_cliente_generico else cliente_id
    # IVA: uno nuevo toma la configuracion de hoy; uno que se modifica conserva la suya (es parte
    # de lo prometido). Nunca se tipea.
    if existente is not None:
        iva_entero, precios_con_iva = existente["iva_porcentaje"], bool(existente["precios_con_iva"])
    else:
        config = negocio_service.config_iva()
        iva_entero, precios_con_iva = config["alicuota_entero"], config["precios_con_iva"]
    precios_prometidos = {}
    if existente is not None:
        precios_prometidos = {
            f["producto_id"]: (f["precio_unitario"], f["precio_manual"])
            for f in borradores_repo.listar_items(presupuesto_id) if f["producto_id"]
        }
    for item in items_validados:
        if item["producto_id"] is not None:
            if item["producto_id"] in precios_prometidos:
                item["precio_unitario"], item["precio_manual"] = precios_prometidos[item["producto_id"]]
            else:
                item["precio_unitario"] = _precio_de_hoy(item["producto_id"], lista_precio_id)
    if existente is not None and existente["cliente_id"] == cliente_id:
        descuento_cliente = existente["descuento_cliente_porcentaje"]
    else:
        descuento_cliente = _descuento_cliente_hoy(cliente_id)

    if cliente_id is not None:
        nombre = clientes_service.obtener_cliente(cliente_id)["razon_social"]
    else:
        nombre = (None if usar_cliente_generico else _texto_o_none(cliente_nombre_nuevo)) or clientes_service.NOMBRE_CLIENTE_GENERICO
    fecha_validez = (date.today() + timedelta(days=validez_dias)).isoformat()
    datos = {
        "nombre": nombre,
        "cliente_id": cliente_id,
        "cliente_nombre_nuevo": None if usar_cliente_generico or cliente_id else _texto_o_none(cliente_nombre_nuevo),
        "usar_cliente_generico": int(usar_cliente_generico),
        "lista_precio_id": lista_precio_id,
        "iva_porcentaje": iva_entero,
        "precios_con_iva": int(precios_con_iva),
        "descuento_total_porcentaje": (
            porcentaje_a_entero(descuento_total_porcentaje) if descuento_total_porcentaje is not None else None
        ),
        "observacion": _texto_o_none(observacion),
        "fecha_validez": fecha_validez,
        "descuento_cliente_porcentaje": descuento_cliente,
    }
    nuevo_id = borradores_repo.guardar(TIPO, presupuesto_id, datos, items_validados)
    presupuesto = obtener_presupuesto(nuevo_id)
    if existente is None:
        log_service.registrar(
            TIPO, nuevo_id,
            f"Se creo el presupuesto {presupuesto['numero']} para '{nombre}' por {formatear_precio(presupuesto['total'])} "
            f"(vence {date.fromisoformat(fecha_validez):%d/%m/%Y})",
        )
    else:
        log_service.registrar(
            TIPO, nuevo_id,
            f"Se modifico el presupuesto {presupuesto['numero']}: {len(items_validados)} lineas, "
            f"total {formatear_precio(presupuesto['total'])}, vence {date.fromisoformat(fecha_validez):%d/%m/%Y}",
        )
    return presupuesto


def _a_dict(fila: sqlite3.Row) -> dict:
    items, lineas_para_total, avisos = [], [], []
    for f in borradores_repo.listar_items(fila["id"]):
        cantidad = entero_a_cantidad(f["cantidad"])
        if f["producto_id"] is not None:
            producto = productos_repo.obtener_por_id(f["producto_id"])
            stock = entero_a_cantidad(producto["stock_actual"])
            if cantidad > stock:
                avisos.append(
                    f"De {producto['nombre']} quedan {formatear_cantidad(stock)} y el presupuesto tiene {formatear_cantidad(cantidad)}"
                )
        items.append({
            "id": f["id"], "precio_manual": bool(f["precio_manual"]),
            "producto_id": f["producto_id"], "producto_codigo": f["producto_codigo"], "producto_nombre": f["producto_nombre"],
            "descripcion_libre": f["descripcion_libre"], "cantidad": cantidad,
            "precio_unitario": entero_a_precio(f["precio_unitario"]),
            "descuento_item_porcentaje": (
                entero_a_porcentaje(f["descuento_item_porcentaje"]) if f["descuento_item_porcentaje"] is not None else None
            ),
        })
        lineas_para_total.append({"producto_id": f["producto_id"], "cantidad": f["cantidad"], "precio_unitario": f["precio_unitario"],
                                  "descuento_item_porcentaje": f["descuento_item_porcentaje"]})
    iva_entero, precios_con_iva = fila["iva_porcentaje"] or 0, bool(fila["precios_con_iva"])
    descuento_cliente = entero_a_porcentaje(fila["descuento_cliente_porcentaje"]) if fila["descuento_cliente_porcentaje"] else None
    totales = ventas_service.calcular_totales(
        lineas_para_total, descuento_cliente, fila["descuento_total_porcentaje"], iva_entero, precios_con_iva,
    )
    estado = _estado_visible(fila)
    # Ganancia ESTIMADA (todavia no se vendio): FIFO simulado sobre el stock de hoy. Solo tiene
    # sentido mientras esta abierto; uno convertido tiene su ganancia real en la venta.
    estimacion = ganancias_service.estimar_ganancia(
        lineas_para_total, descuento_cliente, fila["descuento_total_porcentaje"], iva_entero, precios_con_iva,
    )
    for item, linea in zip(items, estimacion["lineas"]):
        item["costo_estimado"] = linea["costo"]
        item["ganancia_estimada"] = linea["ganancia"]
        item["margen_estimado"] = linea["margen"]
    validez = date.fromisoformat(fila["fecha_validez"])
    if fila["usar_cliente_generico"]:
        cliente_nombre = clientes_service.NOMBRE_CLIENTE_GENERICO
    elif fila["cliente_id"]:
        cliente = clientes_service.obtener_cliente(fila["cliente_id"])
        cliente_nombre = cliente["razon_social"] if cliente else "-"
    else:
        cliente_nombre = fila["cliente_nombre_nuevo"] or "-"
    venta = ventas_service.obtener_venta(fila["venta_id"]) if fila["venta_id"] else None
    # Convertido: ya no se estima, se muestra la ganancia REAL de la venta (con sus lotes y sus NC).
    ganancia_real = ventas_service.detalle_ganancia_venta(venta) if venta else None
    return {
        "id": fila["id"], "numero": fila["numero"], "nombre": fila["nombre"],
        "estado": estado, "estado_label": ESTADOS[estado],
        "cliente_id": fila["cliente_id"], "cliente_nombre_nuevo": fila["cliente_nombre_nuevo"],
        "usar_cliente_generico": bool(fila["usar_cliente_generico"]), "cliente_nombre": cliente_nombre,
        "lista_precio_id": fila["lista_precio_id"], "iva_porcentaje": entero_a_porcentaje(iva_entero),
        "precios_con_iva": precios_con_iva,
        "descuento_total_porcentaje": (
            entero_a_porcentaje(fila["descuento_total_porcentaje"]) if fila["descuento_total_porcentaje"] is not None else None
        ),
        "descuento_cliente_porcentaje": descuento_cliente,
        "observacion": fila["observacion"], "motivo_rechazo": fila["motivo_descarte"],
        "fecha_creacion": fila["fecha_creacion"], "fecha_validez": validez,
        "dias_restantes": (validez - date.today()).days,
        "venta_id": fila["venta_id"], "venta_numero": venta["numero"] if venta else None,
        "items": items, "subtotal": totales["subtotal"], "total": totales["total"], "avisos": avisos,
        "neto": totales["neto"], "iva_monto": totales["iva"],
        "costo_estimado": estimacion["costo"], "ganancia_estimada": estimacion["ganancia"],
        "margen_estimado": estimacion["margen"],
        "ganancia_real": ganancia_real["ganancia"] if ganancia_real else None,
        "margen_real": (
            (100 * ganancia_real["ganancia"] / ganancia_real["ingresos"]).quantize(Decimal("0.1"))
            if ganancia_real and ganancia_real["ingresos"] > 0 else None
        ),
        # Factor de los descuentos de la venta entera (cliente y total) sobre el subtotal de lineas:
        # le sirve a la pantalla para previsualizar el margen mientras se escribe un precio.
        "factor_descuentos": (totales["neto"] / totales["subtotal"]) if totales["subtotal"] else Decimal("1"),
    }


def obtener_presupuesto(presupuesto_id: int) -> dict | None:
    fila = borradores_repo.obtener(presupuesto_id)
    if fila is None or fila["tipo"] != TIPO:
        return None
    return _a_dict(fila)


def listar_presupuestos(estado: str | None = None, texto: str | None = None) -> list[dict]:
    """estado: 'vigente' | 'vencido' | 'convertido' | 'rechazado' | None (todos). texto busca en
    numero y cliente."""
    texto = (texto or "").strip().lower()
    resultado = []
    for fila in borradores_repo.listar_todos(TIPO):
        if estado and _estado_visible(fila) != estado:
            continue
        if texto and texto not in f"{fila['numero']} {fila['nombre']} {fila['cliente_razon_social'] or ''}".lower():
            continue
        resultado.append(_a_dict(fila))
    return resultado


def ajustar_precios(presupuesto_id: int, precios: dict[int, Decimal]) -> dict:
    """El dueno acomoda el precio de una o mas lineas mirando el margen (sube o baja cada
    articulo). precios: {item_id: precio nuevo}. Solo presupuestos vigentes; queda en el Historial
    y la linea marcada como precio manual."""
    fila = _exigir(presupuesto_id, vigente=True)
    actuales = {f["id"]: f for f in borradores_repo.listar_items(presupuesto_id)}
    cambios, detalle = [], []
    for item_id, precio in precios.items():
        if item_id not in actuales:
            raise PresupuestoNoDisponibleError(f"La linea {item_id} no es de este presupuesto")
        if precio is None or precio < 0:
            raise ValueError("El precio no puede estar vacio ni ser negativo")
        linea = actuales[item_id]
        nuevo = precio_a_entero(precio)
        if nuevo == linea["precio_unitario"]:
            continue
        cambios.append({"item_id": item_id, "precio_unitario": nuevo, "precio_manual": True})
        nombre = linea["descripcion_libre"] or linea["producto_nombre"]
        detalle.append(f"{nombre} {formatear_precio(entero_a_precio(linea['precio_unitario']))} -> {formatear_precio(precio)}")
    if not cambios:
        return obtener_presupuesto(presupuesto_id)
    antes = _a_dict(fila)["total"]
    borradores_repo.actualizar_precios_items(presupuesto_id, cambios)
    despues = obtener_presupuesto(presupuesto_id)
    log_service.registrar(
        TIPO, presupuesto_id,
        f"Se ajustaron precios del presupuesto {fila['numero']}: {'; '.join(detalle)} "
        f"(total {formatear_precio(antes)} -> {formatear_precio(despues['total'])})",
    )
    return despues


def contar_por_estado() -> dict[str, int]:
    conteo = {clave: 0 for clave in ESTADOS}
    for fila in borradores_repo.listar_todos(TIPO):
        conteo[_estado_visible(fila)] += 1
    return conteo


def renovar_presupuesto(presupuesto_id: int, validez_dias: int = VALIDEZ_DIAS) -> dict:
    """Para uno vencido (o vigente que se quiera extender): recalcula los precios de los productos
    y el % del cliente con lo de HOY, y le da una validez nueva. Conserva el numero."""
    fila = _exigir(presupuesto_id)
    antes = _a_dict(fila)
    items = [{**i, "precio_unitario": i["precio_unitario"] if i["producto_id"] is None else None} for i in antes["items"]]
    items_validados = validar_items_borrador(items)
    for item in items_validados:
        if item["producto_id"] is not None:
            item["precio_unitario"] = _precio_de_hoy(item["producto_id"], fila["lista_precio_id"])
    datos = {campo: fila[campo] for campo in borradores_repo.CAMPOS_BORRADOR}
    datos["fecha_validez"] = (date.today() + timedelta(days=validez_dias)).isoformat()
    datos["descuento_cliente_porcentaje"] = _descuento_cliente_hoy(fila["cliente_id"])
    config = negocio_service.config_iva()
    datos["iva_porcentaje"], datos["precios_con_iva"] = config["alicuota_entero"], int(config["precios_con_iva"])
    borradores_repo.guardar(TIPO, presupuesto_id, datos, items_validados)
    despues = obtener_presupuesto(presupuesto_id)
    log_service.registrar(
        TIPO, presupuesto_id,
        f"Se renovo el presupuesto {despues['numero']} con los precios de hoy: total {formatear_precio(antes['total'])} "
        f"-> {formatear_precio(despues['total'])}, vence {despues['fecha_validez']:%d/%m/%Y}",
    )
    return despues


def extender_validez(presupuesto_id: int, validez_dias: int = VALIDEZ_DIAS) -> dict:
    """Solo corre la fecha de validez de uno VIGENTE, sin tocar ningun precio (ni los puestos a
    mano). Para uno vencido esta renovar_presupuesto, que recalcula con los precios de hoy."""
    fila = _exigir(presupuesto_id, vigente=True)
    datos = {campo: fila[campo] for campo in borradores_repo.CAMPOS_BORRADOR}
    datos["fecha_validez"] = (date.today() + timedelta(days=validez_dias)).isoformat()
    items = [dict(f) for f in borradores_repo.listar_items(presupuesto_id)]
    borradores_repo.guardar(TIPO, presupuesto_id, datos, items)
    despues = obtener_presupuesto(presupuesto_id)
    log_service.registrar(
        TIPO, presupuesto_id,
        f"Se extendio la validez del presupuesto {fila['numero']} hasta el {despues['fecha_validez']:%d/%m/%Y} (mismos precios)",
    )
    return despues


def rechazar_presupuesto(presupuesto_id: int, motivo: str | None = None) -> None:
    fila = _exigir(presupuesto_id)
    motivo = _texto_o_none(motivo)
    borradores_repo.descartar(presupuesto_id, motivo)
    log_service.registrar(
        TIPO, presupuesto_id, f"El presupuesto {fila['numero']} fue rechazado" + (f": {motivo}" if motivo else ""),
    )
