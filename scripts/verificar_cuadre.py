"""Cuadre del negocio: reglas que SIEMPRE tienen que cumplirse en la base, sin importar que
operacion las toco (venta, compra, nota de credito, ajuste, pago...). Cada operacion nueva que
se agregue a la app tiene que seguir pasando este control.

Solo lee: se puede correr contra la base real en cualquier momento.
Correr con: python scripts/verificar_cuadre.py            (base real)
            python scripts/verificar_cuadre.py otra.db    (otra base)
"""

import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.db.connection as connection_module
from app.config import DB_PATH as DB_PATH_REAL

ruta = Path(sys.argv[1]) if len(sys.argv) > 1 else DB_PATH_REAL
connection_module.DB_PATH = ruta

from app.services import ventas_service
from app.shared.money import entero_a_cantidad, entero_a_precio, formatear_precio

db = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
db.row_factory = sqlite3.Row
errores: list[str] = []
avisos: list[str] = []


def regla(nombre: str, problemas: list[str]) -> None:
    print(f"[{'OK' if not problemas else 'ERROR'}] {nombre}")
    for p in problemas[:10]:
        print(f"        - {p}")
    if len(problemas) > 10:
        print(f"        ... y {len(problemas) - 10} mas")
    errores.extend(problemas)


print(f"Base: {ruta}\n")

# ================= Stock =================
regla("El stock de cada producto es igual a lo que queda en sus lotes", [
    f"{r['codigo']}: stock {entero_a_cantidad(r['stock_actual'])} vs lotes {entero_a_cantidad(r['en_lotes'])}"
    for r in db.execute("""
        SELECT p.codigo, p.stock_actual, COALESCE(SUM(l.cantidad_restante), 0) AS en_lotes
        FROM productos p LEFT JOIN lotes l ON l.producto_id = p.id
        GROUP BY p.id HAVING p.stock_actual != en_lotes""")
])
regla("El stock de cada producto es igual a la suma de sus movimientos", [
    f"{r['codigo']}: stock {entero_a_cantidad(r['stock_actual'])} vs movimientos {entero_a_cantidad(r['por_movimientos'])}"
    for r in db.execute("""
        SELECT p.codigo, p.stock_actual,
               COALESCE(SUM(CASE WHEN m.tipo = 'ingreso' THEN m.cantidad ELSE -m.cantidad END), 0) AS por_movimientos
        FROM productos p LEFT JOIN movimientos m ON m.producto_id = p.id
        GROUP BY p.id HAVING p.stock_actual != por_movimientos""")
])
regla("Lo que queda en cada lote es igual a sus movimientos (entradas - salidas)", [
    f"lote {r['id']} ({r['codigo']}, origen {r['origen']}): restante {entero_a_cantidad(r['cantidad_restante'])} "
    f"vs movimientos {entero_a_cantidad(r['por_movimientos'])}"
    for r in db.execute("""
        SELECT l.id, l.origen, l.cantidad_restante, p.codigo,
               COALESCE(SUM(CASE WHEN m.tipo = 'ingreso' THEN m.cantidad ELSE -m.cantidad END), 0) AS por_movimientos
        FROM lotes l JOIN productos p ON p.id = l.producto_id
        LEFT JOIN movimientos m ON m.lote_id = l.id
        GROUP BY l.id HAVING l.cantidad_restante != por_movimientos""")
])
regla("Ningun movimiento de stock queda sin lote (cada unidad tiene un costo)", [
    f"movimiento {r['id']} ({r['codigo']}, {r['tipo']} {entero_a_cantidad(r['cantidad'])}, motivo {r['motivo']})"
    for r in db.execute("""
        SELECT m.id, m.tipo, m.cantidad, m.motivo, p.codigo
        FROM movimientos m JOIN productos p ON p.id = m.producto_id
        WHERE m.lote_id IS NULL""")
])

# ================= Ventas y notas de credito =================
problemas_cobro, problemas_nc = [], []
for (venta_id,) in db.execute("SELECT id FROM ventas WHERE estado = 'confirmada' ORDER BY id"):
    venta = ventas_service.obtener_venta(venta_id)
    cobrado = sum((p["monto"] for p in venta["pagos"]), Decimal("0"))
    if cobrado != venta["total"]:
        problemas_cobro.append(f"{venta['numero']}: total {formatear_precio(venta['total'])} vs cobrado {formatear_precio(cobrado)}")
    if venta["total_acreditado"] > venta["total"]:
        problemas_nc.append(f"{venta['numero']}: se acredito {formatear_precio(venta['total_acreditado'])} de una venta de {formatear_precio(venta['total'])}")
    for item in venta["items"]:
        if item["cantidad_devuelta"] > item["cantidad"]:
            problemas_nc.append(f"{venta['numero']}: se devolvio mas de lo vendido en una linea")
    ganancia = ventas_service.detalle_ganancia_venta(venta)
    if ganancia["ganancia"] < 0:
        avisos.append(
            f"{venta['numero']} da perdida: cobrado sin IVA {formatear_precio(ganancia['ingresos'])}, "
            f"costo {formatear_precio(ganancia['costo'])} (vendido por debajo del costo, o una devolucion que no volvio al stock)"
        )
regla("Cada venta se cobro exactamente por su total", problemas_cobro)
problemas_iva = []
for (venta_id,) in db.execute("SELECT id FROM ventas WHERE estado = 'confirmada'"):
    v = ventas_service.obtener_venta(venta_id)
    if v["neto"] + v["iva"] != v["total"]:
        problemas_iva.append(f"{v['numero']}: neto {formatear_precio(v['neto'])} + IVA {formatear_precio(v['iva'])} != total {formatear_precio(v['total'])}")
regla("En cada venta, neto + IVA = total (aunque el IVA sea 0)", problemas_iva)

# ================= Reporte de Ganancias =================
# Tomando toda la historia, el reporte por periodo y la ganancia de cada venta (detalle) son dos
# caminos distintos a la misma cuenta: tienen que dar igual al centavo.
from datetime import date

from app.services import ganancias_service

primera = db.execute("SELECT MIN(fecha) FROM (SELECT fecha FROM ventas UNION ALL SELECT fecha FROM notas_credito)").fetchone()[0]
problemas_reporte = []
if primera:
    reporte = ganancias_service.resumen(date.fromisoformat(primera[:10]), date.today())
    suma_ventas = sum(
        (ventas_service.detalle_ganancia_venta(ventas_service.obtener_venta(vid))["ganancia"]
         for (vid,) in db.execute("SELECT id FROM ventas WHERE estado = 'confirmada'")),
        Decimal("0"),
    )
    if reporte["ganancia_bruta"] != suma_ventas:
        problemas_reporte.append(
            f"reporte {formatear_precio(reporte['ganancia_bruta'])} vs suma de las ventas {formatear_precio(suma_ventas)}"
        )
    if sum((p["ganancia"] for p in reporte["productos"]), Decimal("0")) != reporte["ganancia_bruta"]:
        problemas_reporte.append("la tabla por producto no suma la ganancia bruta")
regla("El reporte de Ganancias coincide con la ganancia de cada venta (toda la historia)", problemas_reporte)
regla("Ninguna venta tiene acreditado mas de lo que se vendio", problemas_nc)

# ================= Gastos del negocio =================
problemas_gastos = []
rango_gastos = db.execute("SELECT MIN(fecha), MAX(fecha) FROM gastos").fetchone()
if rango_gastos[0]:
    a_mano = Decimal("0")
    for g in db.execute("SELECT monto_total, iva_porcentaje, iva_recuperable FROM gastos WHERE anulado_fecha IS NULL"):
        total = entero_a_precio(g["monto_total"])
        if g["iva_recuperable"] and g["iva_porcentaje"]:
            total = (total / (1 + Decimal(g["iva_porcentaje"]) / 10000)).quantize(Decimal("0.01"))
        a_mano += total
    desde_g, hasta_g = date.fromisoformat(rango_gastos[0]), max(date.fromisoformat(rango_gastos[1]), date.today())
    reporte_g = ganancias_service.resumen(desde_g, hasta_g)
    if reporte_g["gastos"] != a_mano:
        problemas_gastos.append(f"Ganancias descuenta {formatear_precio(reporte_g['gastos'])}, los gastos vigentes suman {formatear_precio(a_mano)}")
    if reporte_g["ganancia_neta"] != reporte_g["resultado"] - reporte_g["gastos"]:
        problemas_gastos.append("la ganancia neta no es resultado de la mercaderia - gastos")
regla("Ganancias descuenta exactamente los gastos vigentes (sin los anulados)", problemas_gastos)

# ================= Cuentas corrientes =================
regla("Ningun cargo de cuenta corriente tiene aplicado mas que su monto", [
    f"cargo {r['id']}: monto {formatear_precio(entero_a_precio(r['monto']))}, aplicado {formatear_precio(entero_a_precio(r['aplicado']))}"
    for r in db.execute("""
        SELECT c.id, c.monto, SUM(pa.monto) AS aplicado
        FROM cc_cargos c JOIN cc_pago_aplicaciones pa ON pa.cargo_id = c.id
        JOIN cc_pagos p ON p.id = pa.pago_id AND p.anulado_fecha IS NULL
        GROUP BY c.id HAVING aplicado > c.monto""")
])
regla("Ningun pago de cuenta corriente reparte mas que su monto", [
    f"pago {r['id']}: monto {formatear_precio(entero_a_precio(r['monto']))}, repartido {formatear_precio(entero_a_precio(r['repartido']))}"
    for r in db.execute("""
        SELECT p.id, p.monto, SUM(pa.monto) AS repartido
        FROM cc_pagos p JOIN cc_pago_aplicaciones pa ON pa.pago_id = p.id
        GROUP BY p.id HAVING repartido > p.monto""")
])

print()
for a in avisos:
    print(f"[AVISO] {a}")
print("=" * 60)
if errores:
    print(f"{len(errores)} problema(s) de cuadre")
    sys.exit(1)
print("Todo cuadra" + (f" ({len(avisos)} aviso(s) para revisar)" if avisos else ""))
