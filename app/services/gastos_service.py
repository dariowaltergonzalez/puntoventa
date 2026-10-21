"""Gastos del negocio: lo que cuesta mantenerlo abierto (alquiler, sueldos, servicios...).
Se restan del resultado de la mercaderia para llegar a la ganancia neta.

IVA, misma regla que las compras: si el negocio es Responsable Inscripto, el IVA del comprobante
es credito fiscal (se recupera) y cuenta como gasto solo el NETO; si no (monotributo), cuenta el
TOTAL. Cada gasto congela esa condicion al cargarse, como las ventas congelan la suya."""

import shutil
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from app.repositories import gastos_repo
from app.services import log_service, medios_pago_service, negocio_service
from app.services.exceptions import GastoNoEncontradoError
from app.shared.money import entero_a_porcentaje, entero_a_precio, formatear_precio, porcentaje_a_entero, precio_a_entero
from app.shared import textos

ALICUOTAS = (Decimal("0"), Decimal("10.5"), Decimal("21"), Decimal("27"))
EXTENSIONES_COMPROBANTE = ("jpg", "jpeg", "png", "webp", "pdf")
CENTAVO = Decimal("1.00")
_CAMPOS_LOG = ["fecha", "descripcion", "categoria", "monto_total", "iva_porcentaje", "medio_pago", "proveedor", "observacion"]


def carpeta_comprobantes() -> Path:
    return gastos_repo.carpeta_comprobantes()


def _texto_o_none(valor: str | None) -> str | None:
    return (valor or "").strip() or None


def desglosar(monto_total: Decimal, iva_porcentaje: Decimal | None) -> tuple[Decimal, Decimal]:
    """(neto, iva) de un comprobante cuyo total ya incluye el IVA. neto + iva = total exacto."""
    if not iva_porcentaje:
        return monto_total, Decimal("0")
    neto = (monto_total / (1 + iva_porcentaje / 100)).quantize(CENTAVO)
    return neto, monto_total - neto


def _a_dict(fila: sqlite3.Row) -> dict:
    total = entero_a_precio(fila["monto_total"])
    iva_porcentaje = entero_a_porcentaje(fila["iva_porcentaje"]) if fila["iva_porcentaje"] else Decimal("0")
    neto, iva = desglosar(total, iva_porcentaje)
    recuperable = bool(fila["iva_recuperable"])
    return {
        "id": fila["id"], "fecha": date.fromisoformat(fila["fecha"]), "descripcion": fila["descripcion"],
        "categoria_id": fila["categoria_gasto_id"], "categoria": fila["categoria_nombre"],
        "monto_total": total, "iva_porcentaje": iva_porcentaje, "neto": neto, "iva": iva,
        "iva_recuperable": recuperable,
        # Lo que se descuenta en Ganancias: el neto si el IVA se recupera, el total si no.
        "gasto": neto if recuperable else total,
        "iva_recuperado": iva if recuperable else Decimal("0"),
        "medio_pago_id": fila["medio_pago_id"], "medio_pago": fila["medio_pago_nombre"],
        "proveedor": fila["proveedor"], "observacion": fila["observacion"],
        "comprobante": str(carpeta_comprobantes() / fila["comprobante"]) if fila["comprobante"] else None,
        "anulado": fila["anulado_fecha"] is not None, "anulado_motivo": fila["anulado_motivo"],
    }


# ---------- categorias ----------
def listar_categorias() -> list[dict]:
    return [{"id": f["id"], "nombre": f["nombre"]} for f in gastos_repo.listar_categorias()]


def crear_categoria(nombre: str) -> dict:
    nombre = textos.primera_mayuscula(nombre or "")
    if not nombre:
        raise ValueError("El nombre de la categoria no puede estar vacio")
    if any(c["nombre"].lower() == nombre.lower() for c in listar_categorias()):
        raise ValueError(f"Ya existe la categoria '{nombre}'")
    categoria_id = gastos_repo.crear_categoria(nombre)
    log_service.registrar("categoria_gasto", categoria_id, f"Se creo la categoria de gasto '{nombre}'")
    return {"id": categoria_id, "nombre": nombre}


# ---------- gastos ----------
def _validar(fecha: str, descripcion: str, categoria_id: int, monto_total: Decimal, iva_porcentaje: Decimal | None,
             medio_pago_id: int | None) -> dict:
    try:
        fecha_valida = date.fromisoformat((fecha or "").strip())
    except ValueError as exc:
        raise ValueError("La fecha va con formato AAAA-MM-DD") from exc
    if fecha_valida > date.today():
        raise ValueError("La fecha del gasto no puede ser futura")
    descripcion = (descripcion or "").strip()
    if not descripcion:
        raise ValueError("La descripcion es obligatoria")
    if gastos_repo.obtener_categoria(categoria_id or 0) is None:
        raise ValueError("Elegi una categoria")
    if monto_total is None or monto_total <= 0:
        raise ValueError("El monto tiene que ser mayor a cero")
    iva_porcentaje = iva_porcentaje or Decimal("0")
    if iva_porcentaje not in ALICUOTAS:
        raise ValueError("El IVA del comprobante tiene que ser 0, 10,5, 21 o 27 %")
    if medio_pago_id is not None and medios_pago_service.obtener_medio_pago(medio_pago_id) is None:
        raise ValueError("El medio de pago no existe")
    return {
        "fecha": fecha_valida.isoformat(), "descripcion": descripcion, "categoria_gasto_id": categoria_id,
        "monto_total": precio_a_entero(monto_total),
        "iva_porcentaje": porcentaje_a_entero(iva_porcentaje) if iva_porcentaje else None,
        "medio_pago_id": medio_pago_id,
    }


def crear_gasto(
    fecha: str, descripcion: str, categoria_id: int, monto_total: Decimal, iva_porcentaje: Decimal | None = None,
    medio_pago_id: int | None = None, proveedor: str | None = None, observacion: str | None = None,
) -> dict:
    datos = _validar(fecha, descripcion, categoria_id, monto_total, iva_porcentaje, medio_pago_id)
    datos.update(proveedor=_texto_o_none(proveedor), observacion=_texto_o_none(observacion))
    recuperable = negocio_service.config_iva()["cobra_iva"]
    gasto_id = gastos_repo.crear(datos, iva_recuperable=recuperable)
    gasto = obtener_gasto(gasto_id)
    log_service.registrar(
        "gasto", gasto_id,
        f"Se cargo el gasto '{gasto['descripcion']}' ({gasto['categoria']}) por {formatear_precio(gasto['monto_total'])}"
        + (f", cuenta como gasto {formatear_precio(gasto['gasto'])}" if gasto["gasto"] != gasto["monto_total"] else ""),
    )
    return gasto


def _para_log(gasto: dict) -> dict:
    return {
        "fecha": gasto["fecha"].strftime("%d/%m/%Y"), "descripcion": gasto["descripcion"], "categoria": gasto["categoria"],
        "monto_total": formatear_precio(gasto["monto_total"]), "iva_porcentaje": f"{gasto['iva_porcentaje']}%",
        "medio_pago": gasto["medio_pago"], "proveedor": gasto["proveedor"], "observacion": gasto["observacion"],
    }


def editar_gasto(
    gasto_id: int, fecha: str, descripcion: str, categoria_id: int, monto_total: Decimal,
    iva_porcentaje: Decimal | None = None, medio_pago_id: int | None = None, proveedor: str | None = None,
    observacion: str | None = None,
) -> dict:
    """Conserva la condicion de IVA con la que se cargo (iva_recuperable no se toca)."""
    antes = _exigir_vigente(gasto_id)
    datos = _validar(fecha, descripcion, categoria_id, monto_total, iva_porcentaje, medio_pago_id)
    datos.update(proveedor=_texto_o_none(proveedor), observacion=_texto_o_none(observacion))
    gastos_repo.actualizar(gasto_id, datos)
    despues = obtener_gasto(gasto_id)
    log_service.registrar_cambios("gasto", gasto_id, _para_log(antes), _para_log(despues), _CAMPOS_LOG)
    return despues


def anular_gasto(gasto_id: int, motivo: str) -> dict:
    gasto = _exigir_vigente(gasto_id)
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("Anular un gasto requiere indicar el motivo")
    gastos_repo.anular(gasto_id, datetime.now().isoformat(), motivo)
    log_service.registrar("gasto", gasto_id, f"Se anulo el gasto '{gasto['descripcion']}' ({formatear_precio(gasto['monto_total'])}): {motivo}")
    return obtener_gasto(gasto_id)


def adjuntar_comprobante(gasto_id: int, ruta_origen: str) -> dict:
    """Copia la foto o el PDF a data/comprobantes/ (con el id del gasto adelante para que no se
    pisen dos archivos con el mismo nombre). Si ya tenia uno, lo reemplaza."""
    gasto = _exigir_vigente(gasto_id)
    origen = Path(ruta_origen)
    if not origen.is_file():
        raise ValueError("No se encontro el archivo elegido")
    if origen.suffix.lower().lstrip(".") not in EXTENSIONES_COMPROBANTE:
        raise ValueError("El comprobante tiene que ser una foto (JPG, PNG, WEBP) o un PDF")
    carpeta = carpeta_comprobantes()
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = f"gasto_{gasto_id}_{origen.name}"
    shutil.copy2(origen, carpeta / nombre)
    gastos_repo.actualizar_comprobante(gasto_id, nombre)
    log_service.registrar("gasto", gasto_id, f"Se adjunto el comprobante '{origen.name}' al gasto '{gasto['descripcion']}'")
    return obtener_gasto(gasto_id)


def _exigir_vigente(gasto_id: int) -> dict:
    gasto = obtener_gasto(gasto_id)
    if gasto is None:
        raise GastoNoEncontradoError(f"No existe el gasto {gasto_id}")
    if gasto["anulado"]:
        raise GastoNoEncontradoError(f"El gasto '{gasto['descripcion']}' esta anulado")
    return gasto


def obtener_gasto(gasto_id: int) -> dict | None:
    fila = gastos_repo.obtener(gasto_id)
    return _a_dict(fila) if fila is not None else None


def listar_gastos(desde: date, hasta: date, categoria_id: int | None = None, texto: str | None = None) -> list[dict]:
    texto = (texto or "").strip().lower()
    resultado = []
    for fila in gastos_repo.listar(desde.isoformat(), hasta.isoformat()):
        if categoria_id is not None and fila["categoria_gasto_id"] != categoria_id:
            continue
        if texto and texto not in f"{fila['descripcion']} {fila['proveedor'] or ''} {fila['observacion'] or ''}".lower():
            continue
        resultado.append(_a_dict(fila))
    return resultado


def resumen(desde: date, hasta: date) -> dict:
    """Totales del periodo sin contar los anulados: pagado (lo que salio), IVA recuperable y gastos
    del negocio (lo que se descuenta en Ganancias), y el gasto por categoria."""
    vigentes = [g for g in listar_gastos(desde, hasta) if not g["anulado"]]
    por_categoria: dict[str, Decimal] = {}
    for g in vigentes:
        por_categoria[g["categoria"]] = por_categoria.get(g["categoria"], Decimal("0")) + g["gasto"]
    return {
        "cantidad": len(vigentes),
        "pagado": sum((g["monto_total"] for g in vigentes), Decimal("0")),
        "iva_recuperable": sum((g["iva_recuperado"] for g in vigentes), Decimal("0")),
        "gastos": sum((g["gasto"] for g in vigentes), Decimal("0")),
        "por_categoria": sorted(({"categoria": k, "gasto": v} for k, v in por_categoria.items()),
                                key=lambda c: c["gasto"], reverse=True),
    }
