"""Reporte de Ganancias por periodo.

  Ventas netas        = lo cobrado sin IVA (con todos los descuentos) - notas de credito del periodo
  Costo de lo vendido = costo real de los lotes vendidos - costo de lo que volvio al stock
  Ganancia bruta      = ventas netas - costo de lo vendido
  Perdidas de stock   = roturas, vencimientos, faltantes... a costo real (los sobrantes restan)
  Resultado           = ganancia bruta - perdidas de stock
  Ganancia neta       = resultado - gastos del negocio (alquiler, sueldos, servicios...)

Las notas de credito cuentan en el periodo en que se EMITEN (un mes ya cerrado no cambia solo).
Nada se guarda: se calcula al pedirlo.
"""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.repositories import ganancias_repo, lotes_repo, ventas_repo
from app.services import gastos_service, movimientos_service, ventas_service
from app.shared.money import entero_a_cantidad, entero_a_porcentaje, porcentaje_a_entero

CENTAVO = Decimal("0.01")
ESCALA_COSTO = Decimal("100000")  # cantidad x1000 * costo x100
CLAVE_ITEMS_LIBRES = "libres"


def peso_linea(linea) -> Decimal:
    """Lo que vale la linea antes de los descuentos de la venta entera (solo con el de linea)."""
    monto = Decimal(linea["cantidad"]) * Decimal(linea["precio_unitario"])
    if linea["descuento_item_porcentaje"] is not None:
        monto *= 1 - entero_a_porcentaje(linea["descuento_item_porcentaje"]) / 100
    return monto


def repartir(total: Decimal, pesos: list[Decimal]) -> list[Decimal]:
    """Reparte un monto entre lineas proporcional a su peso, centavo por centavo (metodo del
    mayor resto): la suma de las partes da exactamente el total, asi la tabla por producto
    cierra con la tarjeta de arriba."""
    if not pesos:
        return []
    suma = sum(pesos)
    centavos = int((total / CENTAVO).to_integral_value(ROUND_HALF_UP))
    if suma == 0:
        return [total] + [Decimal("0")] * (len(pesos) - 1)
    exactos = [Decimal(centavos) * p / suma for p in pesos]
    partes = [int(e) for e in exactos]
    sobrante = centavos - sum(partes)
    for i in sorted(range(len(pesos)), key=lambda i: exactos[i] - partes[i], reverse=True)[:sobrante]:
        partes[i] += 1
    return [Decimal(p) * CENTAVO for p in partes]


def _sin_iva_por_nota(venta_id: int, cache: dict) -> dict[int, Decimal]:
    """Cuanto acredito (sin IVA) cada nota de credito de una venta. Si la venta quedo acreditada
    entera, la ultima nota se lleva la diferencia de redondeo: entre todas suman justo lo que
    se cobro (mismo criterio que la ganancia de cada venta)."""
    if venta_id in cache:
        return cache[venta_id]
    venta_fila = ventas_repo.obtener_por_id(venta_id)
    lineas_venta = [dict(f) for f in ventas_repo.listar_items(venta_id)]
    notas = ventas_repo.listar_notas_credito_de_venta(venta_id)
    resultado = {
        nc["id"]: ventas_service.total_sin_iva(venta_fila, [dict(f) for f in ventas_repo.listar_items_nota_credito(nc["id"])])
        for nc in notas
    }
    devuelto = ventas_repo.cantidades_devueltas_por_item(venta_id)
    acreditada_entera = all(devuelto.get(l["id"], 0) >= l["cantidad"] for l in lineas_venta)
    if notas and acreditada_entera:
        ultima = notas[-1]["id"]
        resultado[ultima] = ventas_service.total_sin_iva(venta_fila, lineas_venta) - sum(
            v for k, v in resultado.items() if k != ultima
        )
    cache[venta_id] = resultado
    return resultado


def _clave_producto(linea) -> tuple:
    if linea["producto_id"] is None:
        return (CLAVE_ITEMS_LIBRES, "", "Items libres / servicios")
    return (linea["producto_id"], linea["producto_codigo"], linea["producto_nombre"])


def _agrupacion(desde: date, hasta: date) -> str:
    dias = (hasta - desde).days + 1
    if dias <= 62:
        return "dia"
    if dias <= 400:
        return "semana"
    return "mes"


def _inicio_bucket(dia: date, agrupacion: str) -> date:
    if agrupacion == "semana":
        return dia - timedelta(days=dia.weekday())
    if agrupacion == "mes":
        return dia.replace(day=1)
    return dia


def _buckets_vacios(desde: date, hasta: date, agrupacion: str) -> dict[date, Decimal]:
    buckets = {}
    dia = desde
    while dia <= hasta:
        buckets.setdefault(_inicio_bucket(dia, agrupacion), Decimal("0"))
        dia += timedelta(days=1)
    return buckets


def resumen(desde: date, hasta: date) -> dict:
    if hasta < desde:
        raise ValueError("La fecha 'hasta' no puede ser anterior a 'desde'")
    desde_iso = desde.isoformat()
    hasta_excl = (hasta + timedelta(days=1)).isoformat()
    agrupacion = _agrupacion(desde, hasta)
    serie = _buckets_vacios(desde, hasta, agrupacion)
    productos: dict[tuple, dict] = {}

    def acumular(clave: tuple, unidades: Decimal, ventas: Decimal, costo: Decimal) -> None:
        p = productos.setdefault(clave, {"unidades": Decimal("0"), "ventas": Decimal("0"), "costo": Decimal("0")})
        p["unidades"] += unidades
        p["ventas"] += ventas
        p["costo"] += costo

    # ---------- ventas del periodo ----------
    ventas = ganancias_repo.listar_ventas(desde_iso, hasta_excl)
    lineas_por_venta: dict[int, list] = {}
    for linea in ganancias_repo.listar_lineas_de_ventas(desde_iso, hasta_excl):
        lineas_por_venta.setdefault(linea["venta_id"], []).append(linea)

    vendido = Decimal("0")
    costo_vendido = Decimal("0")
    ganancia_por_venta: dict[int, Decimal] = {}
    for venta in ventas:
        lineas = lineas_por_venta.get(venta["id"], [])
        total = ventas_service.total_sin_iva(venta, [dict(l) for l in lineas])
        ganancia_venta = Decimal("0")
        for linea, ingreso in zip(lineas, repartir(total, [peso_linea(l) for l in lineas])):
            costo = Decimal(linea["costo_lotes"]) / ESCALA_COSTO
            acumular(_clave_producto(linea), entero_a_cantidad(linea["cantidad"]), ingreso, costo)
            costo_vendido += costo
            ganancia_venta += ingreso - costo
        vendido += total
        ganancia_por_venta[venta["id"]] = ganancia_venta
        serie[_inicio_bucket(date.fromisoformat(venta["fecha"][:10]), agrupacion)] += ganancia_venta

    # ---------- notas de credito emitidas en el periodo ----------
    lineas_por_nota: dict[int, list] = {}
    for linea in ganancias_repo.listar_lineas_de_notas_credito(desde_iso, hasta_excl):
        lineas_por_nota.setdefault(linea["nota_credito_id"], []).append(linea)
    cache_notas: dict = {}
    acreditado = Decimal("0")
    costo_devuelto = Decimal("0")
    for nota in ganancias_repo.listar_notas_credito(desde_iso, hasta_excl):
        lineas = lineas_por_nota.get(nota["id"], [])
        total_nota = _sin_iva_por_nota(nota["venta_id"], cache_notas)[nota["id"]]
        efecto = Decimal("0")
        for linea, ingreso in zip(lineas, repartir(total_nota, [peso_linea(l) for l in lineas])):
            costo = Decimal(linea["costo_devuelto"]) / ESCALA_COSTO
            acumular(_clave_producto(linea), -entero_a_cantidad(linea["cantidad"]), -ingreso, -costo)
            costo_devuelto += costo
            efecto += ingreso - costo
        acreditado += total_nota
        serie[_inicio_bucket(date.fromisoformat(nota["fecha"][:10]), agrupacion)] -= efecto

    # ---------- perdidas de stock (ajustes) ----------
    perdidas_por_motivo = []
    perdidas = Decimal("0")
    for fila in ganancias_repo.listar_ajustes_de_stock(desde_iso, hasta_excl):
        valor = Decimal(fila["valor"]) / ESCALA_COSTO
        signo = 1 if fila["tipo"] == "egreso" else -1  # un sobrante (ingreso) resta perdida
        perdidas += signo * valor
        perdidas_por_motivo.append({
            "motivo": movimientos_service.MOTIVOS_LABEL.get(fila["motivo"], fila["motivo"]),
            "unidades": entero_a_cantidad(fila["cantidad"]),
            "valor": (signo * valor).quantize(CENTAVO),
        })
    perdidas_por_motivo.sort(key=lambda m: m["valor"], reverse=True)

    # ---------- totales ----------
    ventas_netas = vendido - acreditado
    costo = (costo_vendido - costo_devuelto).quantize(CENTAVO)
    bruta = ventas_netas - costo
    perdidas = perdidas.quantize(CENTAVO)
    resultado = bruta - perdidas
    cantidad = len(ventas)

    def porcentaje(parte: Decimal, total: Decimal) -> Decimal | None:
        return (parte * 100 / total).quantize(Decimal("0.1")) if total > 0 else None

    filas_productos = []
    for (_, codigo, nombre), p in productos.items():
        if p["unidades"] == 0 and p["ventas"] == 0:
            continue
        ganancia = p["ventas"] - p["costo"]
        filas_productos.append({
            "codigo": codigo, "nombre": nombre, "unidades": p["unidades"],
            "ventas": p["ventas"].quantize(CENTAVO), "costo": p["costo"].quantize(CENTAVO),
            "ganancia": ganancia.quantize(CENTAVO), "margen": porcentaje(ganancia, p["ventas"]),
        })
    filas_productos.sort(key=lambda f: f["ganancia"], reverse=True)

    puntos = [{"inicio": inicio, "ganancia": valor.quantize(CENTAVO)} for inicio, valor in sorted(serie.items())]
    mejor = max(puntos, key=lambda p: p["ganancia"]) if puntos and any(p["ganancia"] > 0 for p in puntos) else None

    # Ventas del periodo que, con sus notas de credito, dan perdida.
    candidatas = {vid for vid, g in ganancia_por_venta.items() if g < 0} | {
        n["venta_id"] for n in ganancias_repo.listar_notas_credito(desde_iso, hasta_excl)
    }
    gastos = gastos_service.resumen(desde, hasta)

    ventas_con_perdida = []
    for venta in ventas:
        if venta["id"] not in candidatas:
            continue
        detalle = ventas_service.detalle_ganancia_venta(ventas_service.obtener_venta(venta["id"]))
        if detalle["ganancia"] < 0:
            ventas_con_perdida.append({
                "venta_id": venta["id"], "numero": venta["numero"], "cliente": venta["cliente_nombre"],
                "ingresos": detalle["ingresos"], "costo": detalle["costo"], "ganancia": detalle["ganancia"],
            })

    return {
        "desde": desde, "hasta": hasta, "agrupacion": agrupacion,
        "vendido": vendido, "acreditado": acreditado,
        "ventas_netas": ventas_netas, "costo": costo, "ganancia_bruta": bruta,
        "margen": porcentaje(bruta, ventas_netas),
        "perdidas": perdidas, "resultado": resultado, "resultado_porcentaje": porcentaje(resultado, ventas_netas),
        "cantidad_ventas": cantidad,
        "ticket_promedio": (ventas_netas / cantidad).quantize(CENTAVO) if cantidad else None,
        "ganancia_por_venta": (bruta / cantidad).quantize(CENTAVO) if cantidad else None,
        "serie": puntos, "mejor": mejor,
        "productos": filas_productos,
        "perdidas_por_motivo": perdidas_por_motivo,
        "ventas_con_perdida": ventas_con_perdida,
        "gastos": gastos["gastos"],
        "gastos_por_categoria": gastos["por_categoria"],
        "ganancia_neta": resultado - gastos["gastos"],
        "ganancia_neta_porcentaje": porcentaje(resultado - gastos["gastos"], ventas_netas),
    }


def periodo(nombre: str, hoy: date | None = None) -> tuple[date, date]:
    """Rangos de los botones de la pantalla: 'hoy', 'semana' (de lunes a hoy), 'mes' (del 1 a
    hoy) y 'mes_anterior' (completo)."""
    hoy = hoy or date.today()
    if nombre == "hoy":
        return hoy, hoy
    if nombre == "semana":
        return hoy - timedelta(days=hoy.weekday()), hoy
    if nombre == "mes":
        return hoy.replace(day=1), hoy
    if nombre == "mes_anterior":
        fin = hoy.replace(day=1) - timedelta(days=1)
        return fin.replace(day=1), fin
    raise ValueError(f"Periodo desconocido: {nombre}")


def estimar_ganancia(
    lineas: list[dict], descuento_cliente: Decimal | None, descuento_total_entero: int | None,
    iva_entero: int | None = None, precios_con_iva: bool = False,
) -> dict:
    """Ganancia ESTIMADA de un carrito o presupuesto que todavia no se vendio: lo que se cobraria
    sin IVA (con todos los descuentos, repartido entre las lineas centavo por centavo) menos el
    costo que tendria venderlo hoy (FIFO simulado, sin consumir lotes). Nunca entra en el reporte
    de Ganancias: la real recien existe cuando se vende.
    lineas: [{'producto_id', 'cantidad' (x1000), 'precio_unitario' (x100), 'descuento_item_porcentaje' (x100|None)}]"""
    neto = ventas_service.calcular_totales(lineas, descuento_cliente, descuento_total_entero, iva_entero, precios_con_iva)["neto"]
    ingresos = repartir(neto, [peso_linea(l) for l in lineas])
    ya_tomado: dict[int, int] = {}
    resultado = []
    for linea, ingreso in zip(lineas, ingresos):
        costo = Decimal("0")
        if linea["producto_id"] is not None:
            saltear = ya_tomado.get(linea["producto_id"], 0)
            costo = Decimal(lotes_repo.simular_costo_fifo(linea["producto_id"], linea["cantidad"], saltear)) / ESCALA_COSTO
            ya_tomado[linea["producto_id"]] = saltear + linea["cantidad"]
        costo = costo.quantize(CENTAVO)
        resultado.append({"ingreso": ingreso, "costo": costo, "ganancia": ingreso - costo,
                          "margen": (100 * (ingreso - costo) / ingreso).quantize(Decimal("0.1")) if ingreso > 0 else None})
    total_costo = sum((r["costo"] for r in resultado), Decimal("0"))
    ganancia = neto - total_costo
    return {
        "lineas": resultado, "ingresos": neto, "costo": total_costo, "ganancia": ganancia,
        "margen": (100 * ganancia / neto).quantize(Decimal("0.1")) if neto > 0 else None,
    }


def estimar_ganancia_carrito(
    items: list[dict], lista_precio_id: int | None = None, cliente_id: int | None = None,
    descuento_total_porcentaje: Decimal | None = None, borrador_id: int | None = None,
) -> dict:
    """La ganancia estimada del carrito que se esta armando en la caja (boton 'Ver ganancia')."""
    lineas, descuento_cliente = ventas_service.preparar_carrito(items, lista_precio_id, cliente_id, borrador_id)
    descuento_total = porcentaje_a_entero(descuento_total_porcentaje) if descuento_total_porcentaje is not None else None
    iva_entero, precios_con_iva = ventas_service.condiciones_iva(borrador_id)
    return estimar_ganancia(lineas, descuento_cliente, descuento_total, iva_entero, precios_con_iva)
