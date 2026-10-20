"""Verificacion de presupuestos: numero y validez, precios y % de cliente congelados (se cobran
aunque cambie la lista o el cliente), lo agregado al convertir va a precio de hoy, modificar
conservando el numero, vencido (no se cobra ni se modifica) y renovar con precios de hoy,
rechazar, filtros. Corre contra una COPIA de la base real.
Correr con: python scripts/verificar_presupuestos.py
"""

import inspect
import sqlite3
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.db.connection as connection_module
from app.config import DB_PATH as DB_PATH_REAL

DB_PATH_TEST = DB_PATH_REAL.parent / "puntoventa_test.db"
for sufijo in ("", "-wal", "-shm"):
    Path(f"{DB_PATH_TEST}{sufijo}").unlink(missing_ok=True)
origen = sqlite3.connect(DB_PATH_REAL)
destino = sqlite3.connect(DB_PATH_TEST)
origen.backup(destino)
destino.close()
origen.close()
connection_module.DB_PATH = DB_PATH_TEST

from app.services import clientes_service, medios_pago_service, presupuestos_service, productos_service, ventas_service
from app.services import condiciones_iva_service, negocio_service
from app.services.exceptions import PresupuestoNoDisponibleError

# Las cuentas de abajo son sin IVA: la copia se configura como Monotributista, sin importar
# lo que tenga la base real (el IVA en presupuestos lo cubre verificar_iva.py).
negocio_service.guardar_negocio("Negocio", "20-12345678-9", condicion_iva_id={
    c["nombre"]: c["id"] for c in condiciones_iva_service.listar_condiciones_iva()}["Monotributista"])

fallas = []


def verificar(nombre, condicion):
    estado = "OK" if condicion else "FALLO"
    print(f"[{estado}] {nombre}")
    if not condicion:
        fallas.append(nombre)


def lanza(excepcion, funcion, *args, **kwargs) -> bool:
    try:
        funcion(*args, **kwargs)
    except excepcion:
        return True
    return False


def ejecutar(sql: str, parametros: tuple) -> None:
    conn = connection_module.get_connection()
    conn.execute(sql, parametros)
    conn.close()


def actualizar_descuento_cliente(cliente_id: int, porcentaje: Decimal) -> None:
    parametros = inspect.signature(clientes_service.actualizar_cliente).parameters
    datos = {k: v for k, v in clientes_service.obtener_cliente(cliente_id).items() if k in parametros and k != "cliente_id"}
    clientes_service.actualizar_cliente(cliente_id, **(datos | {"porcentaje_descuento": porcentaje}))


productos = [p for p in productos_service.listar_productos(solo_activos=True) if p["stock_actual"] >= 5 and p["precio_venta"] > 0]
prod_a, prod_b, prod_c = productos[0], productos[1], productos[2]
cliente = clientes_service.crear_cliente(f"Cliente presupuesto {datetime.now():%H%M%S%f}", porcentaje_descuento=Decimal("10"))
efectivo = next(m for m in medios_pago_service.listar_medios_pago() if m["nombre"] == "Efectivo")
items = [
    {"producto_id": prod_a["id"], "descripcion_libre": None, "cantidad": Decimal("4"), "descuento_item_porcentaje": Decimal("10")},
    {"producto_id": None, "descripcion_libre": "Flete", "cantidad": Decimal("1"), "precio_unitario": Decimal("800")},
]
comunes = dict(cliente_id=cliente["id"], usar_cliente_generico=False, descuento_total_porcentaje=Decimal("5"))

print("=== Crear ===")
stock_antes = productos_service.obtener_producto(prod_a["id"])["stock_actual"]
p = presupuestos_service.guardar_presupuesto(None, items, **comunes)
verificar("numero P-xxxx", (p["numero"] or "").startswith("P-"))
verificar("vence en 15 dias y esta vigente", p["fecha_validez"] == date.today() + timedelta(days=15) and p["estado"] == "vigente")
verificar("no toca el stock", productos_service.obtener_producto(prod_a["id"])["stock_actual"] == stock_antes)
total_caja = ventas_service.previsualizar_totales(items, cliente_id=cliente["id"], descuento_total_porcentaje=Decimal("5"))["total"]
verificar(f"total = el de la caja hoy ({total_caja})", p["total"] == total_caja)
verificar("se puede presupuestar a Consumidor Final",
          presupuestos_service.guardar_presupuesto(None, items)["cliente_nombre"] == clientes_service.NOMBRE_CLIENTE_GENERICO)
print()

print("=== Precios congelados ===")
ejecutar("UPDATE productos SET precio_venta = precio_venta + 10000 WHERE id = ?", (prod_a["id"],))
actualizar_descuento_cliente(cliente["id"], Decimal("30"))
verificar("el total del presupuesto no cambia", presupuestos_service.obtener_presupuesto(p["id"])["total"] == p["total"])
previa = ventas_service.previsualizar_totales(items, cliente_id=cliente["id"], descuento_total_porcentaje=Decimal("5"), borrador_id=p["id"])
verificar("la caja muestra el total prometido", previa["total"] == p["total"])
con_extra = items + [{"producto_id": prod_b["id"], "descripcion_libre": None, "cantidad": Decimal("1")}]
previa_extra = ventas_service.previsualizar_totales(con_extra, cliente_id=cliente["id"], descuento_total_porcentaje=Decimal("5"),
                                                    borrador_id=p["id"])
esperado_extra = (p["subtotal"] + prod_b["precio_venta"]) * Decimal("0.9") * Decimal("0.95")
verificar("lo agregado al convertir va al precio de hoy (con el % prometido)",
          previa_extra["total"] == esperado_extra.quantize(Decimal("1.00")))
venta = ventas_service.crear_venta(items=items, pagos=[{"medio_pago_id": efectivo["id"], "monto": p["total"]}],
                                   descuento_total_porcentaje=Decimal("5"), borrador_id=p["id"], **{k: v for k, v in comunes.items() if k != "descuento_total_porcentaje"})
verificar("la venta se cobra por el total prometido", venta["total"] == p["total"])
verificar("la venta guarda el % de cliente prometido (10)", venta["descuento_cliente_porcentaje"] == Decimal("10"))
convertido = presupuestos_service.obtener_presupuesto(p["id"])
verificar("queda convertido y vinculado a la venta", convertido["estado"] == "convertido" and convertido["venta_numero"] == venta["numero"])
verificar("no se cobra dos veces", lanza(PresupuestoNoDisponibleError, ventas_service.crear_venta, items=items,
          pagos=[{"medio_pago_id": efectivo["id"], "monto": p["total"]}], borrador_id=p["id"], usar_cliente_generico=True))
print()

print("=== Modificar ===")
p2 = presupuestos_service.guardar_presupuesto(None, items[:1], **comunes)
precio_prometido = p2["items"][0]["precio_unitario"]
ejecutar("UPDATE productos SET precio_venta = precio_venta + 500 WHERE id = ?", (prod_a["id"],))
mod = presupuestos_service.guardar_presupuesto(p2["id"], items[:1] + [{"producto_id": prod_c["id"], "descripcion_libre": None,
                                                                        "cantidad": Decimal("2")}], **comunes)
verificar("conserva el numero", mod["numero"] == p2["numero"])
verificar("lo que ya estaba conserva su precio prometido", mod["items"][0]["precio_unitario"] == precio_prometido)
verificar("lo nuevo va al precio de hoy", mod["items"][1]["precio_unitario"] == productos_service.obtener_producto(prod_c["id"])["precio_venta"])
print()

print("=== Vencido y renovar ===")
ejecutar("UPDATE borradores_venta SET fecha_validez = ? WHERE id = ?", ((date.today() - timedelta(days=1)).isoformat(), p2["id"]))
vencido = presupuestos_service.obtener_presupuesto(p2["id"])
verificar("figura vencido", vencido["estado"] == "vencido")
verificar("vencido no se cobra", lanza(PresupuestoNoDisponibleError, ventas_service.previsualizar_totales, items[:1], borrador_id=p2["id"]))
verificar("vencido no se modifica", lanza(PresupuestoNoDisponibleError, presupuestos_service.guardar_presupuesto, p2["id"], items[:1]))
renovado = presupuestos_service.renovar_presupuesto(p2["id"])
verificar("renovado: vigente, mismo numero", renovado["estado"] == "vigente" and renovado["numero"] == p2["numero"])
verificar("renovado: precio de hoy y % de cliente de hoy (30)",
          renovado["items"][0]["precio_unitario"] == productos_service.obtener_producto(prod_a["id"])["precio_venta"]
          and renovado["descuento_cliente_porcentaje"] == Decimal("30"))
print()

print("=== Rechazar y filtros ===")
presupuestos_service.rechazar_presupuesto(p2["id"], "Le parecio caro")
rechazado = presupuestos_service.obtener_presupuesto(p2["id"])
verificar("rechazado con motivo", rechazado["estado"] == "rechazado" and rechazado["motivo_rechazo"] == "Le parecio caro")
verificar("rechazado no se cobra", lanza(PresupuestoNoDisponibleError, ventas_service.previsualizar_totales, items[:1], borrador_id=p2["id"]))
verificar("filtro por estado", all(x["estado"] == "rechazado" for x in presupuestos_service.listar_presupuestos("rechazado")))
verificar("busqueda por numero", [x["id"] for x in presupuestos_service.listar_presupuestos(texto=p2["numero"])] == [p2["id"]])
conteo = presupuestos_service.contar_por_estado()
verificar("conteo por estado", conteo["convertido"] >= 1 and conteo["rechazado"] >= 1 and conteo["vigente"] >= 1)
print()

print("=== Ganancia estimada y precios a mano ===")
from app.repositories import lotes_repo
from app.services import categorias_service, movimientos_service

fifo = productos_service.crear_producto(
    codigo=f"FIFO{datetime.now():%H%M%S%f}"[:20], nombre="Producto FIFO de prueba",
    categoria_id=categorias_service.listar_categorias()[0]["id"], unidad="un",
    precio_costo=Decimal("100"), precio_venta=Decimal("300"),
)
movimientos_service.registrar_ingreso(fifo["id"], Decimal("5"), "stock_inicial", costo_unitario=Decimal("100"))
movimientos_service.registrar_ingreso(fifo["id"], Decimal("5"), "ajuste_sobrante", costo_unitario=Decimal("200"))
lineas_fifo = [{"producto_id": fifo["id"], "descripcion_libre": None, "cantidad": Decimal("7")}]
pf = presupuestos_service.guardar_presupuesto(None, lineas_fifo)
verificar("estimada a mano: 7 x 300 = 2.100 - (5 x 100 + 2 x 200 = 900) = 1.200 (57,1 %)",
          pf["neto"] == Decimal("2100") and pf["costo_estimado"] == Decimal("900")
          and pf["ganancia_estimada"] == Decimal("1200") and pf["margen_estimado"] == Decimal("57.1"))
verificar("estimar no consume lotes",
          sum(l["cantidad_restante"] for l in lotes_repo.listar_por_producto(fifo["id"])) == 10000)
partido = presupuestos_service.guardar_presupuesto(None, [dict(lineas_fifo[0], cantidad=Decimal("4")),
                                                          dict(lineas_fifo[0], cantidad=Decimal("3"))])
verificar("dos lineas del mismo producto siguen el FIFO en orden (400 + 500)",
          [i["costo_estimado"] for i in partido["items"]] == [Decimal("400"), Decimal("500")])

ajustado = presupuestos_service.ajustar_precios(pf["id"], {pf["items"][0]["id"]: Decimal("280")})
verificar("ajustar precio: nuevo total, linea marcada manual, ganancia recalculada",
          ajustado["total"] == Decimal("1960") and ajustado["items"][0]["precio_manual"]
          and ajustado["ganancia_estimada"] == Decimal("1060"))
extendido = presupuestos_service.extender_validez(pf["id"], 30)
verificar("extender validez: 30 dias mas y conserva el precio puesto a mano",
          extendido["fecha_validez"] == date.today() + timedelta(days=30)
          and extendido["items"][0]["precio_unitario"] == Decimal("280") and extendido["items"][0]["precio_manual"])
mod_manual = presupuestos_service.guardar_presupuesto(pf["id"], lineas_fifo)
verificar("modificar desde la caja conserva el precio puesto a mano",
          mod_manual["items"][0]["precio_unitario"] == Decimal("280") and mod_manual["items"][0]["precio_manual"])
venta_fifo = ventas_service.crear_venta(items=lineas_fifo, pagos=[{"medio_pago_id": efectivo["id"], "monto": mod_manual["total"]}],
                                        usar_cliente_generico=True, borrador_id=pf["id"])
real = ventas_service.detalle_ganancia_venta(venta_fifo)
verificar(f"la venta cobra el precio a mano y la ganancia real = la estimada ({real['ganancia']})",
          venta_fifo["total"] == Decimal("1960") and real["ganancia"] == mod_manual["ganancia_estimada"])
print()

print("=" * 60)
if fallas:
    print(f"{len(fallas)} verificaciones FALLARON:")
    for f in fallas:
        print(f"  - {f}")
    sys.exit(1)
print("Todas las verificaciones OK")
