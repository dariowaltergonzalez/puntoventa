"""Verificacion de pre-ventas: guardar (nombre sugerido o propio), conservar descuentos/lista,
no tocar stock, actualizar la misma, total aproximado igual al de la caja, avisos de stock,
convertir, descartar, vencer (dias anteriores) y borrar a la semana. Corre contra una COPIA
de la base real. Correr con: python scripts/verificar_preventas.py
"""

import shutil
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

from app.services import clientes_service, medios_pago_service, preventas_service, productos_service, ventas_service
from app.services.exceptions import LineasVaciasError, PreventaNoDisponibleError

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


def fechar(preventa_id: int, dias_atras: int) -> None:
    conn = connection_module.get_connection()
    conn.execute("UPDATE borradores_venta SET fecha_creacion = ? WHERE id = ?",
                 ((datetime.now() - timedelta(days=dias_atras)).isoformat(), preventa_id))
    conn.close()


producto = next(p for p in productos_service.listar_productos(solo_activos=True) if p["stock_actual"] >= 5 and p["precio_venta"] > 0)
cliente = next(c for c in clientes_service.listar_clientes() if c["razon_social"] != clientes_service.NOMBRE_CLIENTE_GENERICO)
efectivo = next(m for m in medios_pago_service.listar_medios_pago() if m["nombre"] == "Efectivo")
items = [
    {"producto_id": producto["id"], "descripcion_libre": None, "cantidad": Decimal("3"), "descuento_item_porcentaje": Decimal("10")},
    {"producto_id": None, "descripcion_libre": "Envio a domicilio", "cantidad": Decimal("1"), "precio_unitario": Decimal("500")},
]

print("=== Guardar ===")
stock_antes = productos_service.obtener_producto(producto["id"])["stock_actual"]
p1 = preventas_service.guardar_preventa(None, None, items, cliente_id=cliente["id"], usar_cliente_generico=False,
                                       descuento_total_porcentaje=Decimal("5"),
                                       observacion="Pasa a las 18")
verificar("nombre sugerido = el del cliente", p1["nombre"] == cliente["razon_social"])
verificar("no toca el stock", productos_service.obtener_producto(producto["id"])["stock_actual"] == stock_antes)
verificar("conserva % de linea, % total y observacion",
          p1["items"][0]["descuento_item_porcentaje"] == Decimal("10") and p1["descuento_total_porcentaje"] == Decimal("5")
          and p1["observacion"] == "Pasa a las 18")
verificar("el item libre conserva su precio", p1["items"][1]["precio_unitario"] == Decimal("500"))
esperado = ventas_service.previsualizar_totales(items, cliente_id=cliente["id"], descuento_total_porcentaje=Decimal("5"))["total"]
verificar(f"total aproximado = el de la caja ({esperado})", p1["total_aproximado"] == esperado)

p2 = preventas_service.guardar_preventa(None, "  ", items[:1])
verificar("sin cliente: nombre 'Pre-venta N'", p2["nombre"].startswith("Pre-venta "))
p3 = preventas_service.guardar_preventa(None, "Senora con anteojos", items[:1])
verificar("nombre propio", p3["nombre"] == "Senora con anteojos")
verificar("sin lineas no se guarda", lanza(LineasVaciasError, preventas_service.guardar_preventa, None, "x", []))
ids_hoy = {p["id"] for p in preventas_service.listar_preventas_del_dia()}
verificar("las tres aparecen en la lista del dia", {p1["id"], p2["id"], p3["id"]} <= ids_hoy)
print()

print("=== Actualizar la misma ===")
act = preventas_service.guardar_preventa(p3["id"], None, items)
verificar("mismo id, lineas reemplazadas, conserva el nombre",
          act["id"] == p3["id"] and len(act["items"]) == 2 and act["nombre"] == "Senora con anteojos")
print()

print("=== Avisos de stock ===")
mucho = preventas_service.guardar_preventa(None, "Pedido grande", [{"producto_id": producto["id"], "descripcion_libre": None,
                                                                    "cantidad": stock_antes + 10}])
verificar("avisa si ya no alcanza el stock", any(producto["nombre"] in a for a in mucho["avisos"]))
print()

print("=== Convertir y descartar ===")
venta = ventas_service.crear_venta(items=items[:1], pagos=[{"medio_pago_id": efectivo["id"],
                                   "monto": ventas_service.previsualizar_totales(items[:1])["total"]}], usar_cliente_generico=True,
                                   borrador_id=p2["id"])
verificar("la venta deja la pre-venta convertida y vinculada",
          preventas_service.obtener_preventa(p2["id"])["estado"] == "convertida"
          and preventas_service.obtener_preventa(p2["id"])["venta_id"] == venta["id"])
verificar("convertida: sale de la lista", p2["id"] not in {p["id"] for p in preventas_service.listar_preventas_del_dia()})
verificar("convertida: no se puede volver a guardar",
          lanza(PreventaNoDisponibleError, preventas_service.guardar_preventa, p2["id"], None, items))
preventas_service.descartar_preventa(mucho["id"], "No volvio")
verificar("descartada: sale de la lista", mucho["id"] not in {p["id"] for p in preventas_service.listar_preventas_del_dia()})
verificar("no se descarta dos veces", lanza(PreventaNoDisponibleError, preventas_service.descartar_preventa, mucho["id"]))
print()

print("=== Vencimiento ===")
fechar(p1["id"], 1)
verificar("la de ayer ya no aparece", p1["id"] not in {p["id"] for p in preventas_service.listar_preventas_del_dia()})
verificar("pero sigue guardada", preventas_service.obtener_preventa(p1["id"]) is not None)
fechar(p1["id"], 8)
preventas_service.listar_preventas_del_dia()
verificar("la de hace 8 dias se borro sola", preventas_service.obtener_preventa(p1["id"]) is None)
print()

print("=" * 60)
if fallas:
    print(f"{len(fallas)} verificaciones FALLARON:")
    for f in fallas:
        print(f"  - {f}")
    sys.exit(1)
print("Todas las verificaciones OK")
