"""Verificacion del IVA en todo el circuito, con cada configuracion del negocio y numeros hechos a
mano: sin configurar, Responsable Inscripto con precios sin IVA (se suma), RI con precios con IVA
(se desglosa) y Monotributo. Ventas, notas de credito, presupuestos (congelan su IVA), ganancia
(siempre sobre el neto) y compras (cargo con IVA; costo del lote neto o con IVA). Corre contra una
COPIA de la base real. Correr con: python scripts/verificar_iva.py
"""

import sqlite3
import sys
from datetime import datetime
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

from app.repositories import lotes_repo
from app.services import (
    categorias_service,
    cc_service,
    condiciones_iva_service,
    ganancias_service,
    medios_pago_service,
    movimientos_service,
    negocio_service,
    notas_credito_service,
    ordenes_compra_service,
    presupuestos_service,
    productos_service,
    proveedores_service,
    ventas_service,
)

fallas = []
D = Decimal


def verificar(nombre, condicion):
    estado = "OK" if condicion else "FALLO"
    print(f"[{estado}] {nombre}")
    if not condicion:
        fallas.append(nombre)


def configurar(condicion: str | None, precios_con_iva: bool = False) -> None:
    conn = connection_module.get_connection()
    conn.execute("DELETE FROM negocio")
    conn.close()
    if condicion is None:
        return
    ids = {c["nombre"]: c["id"] for c in condiciones_iva_service.listar_condiciones_iva()}
    negocio_service.guardar_negocio("Negocio de prueba", "20-12345678-9", condicion_iva_id=ids[condicion],
                                    precios_incluyen_iva=precios_con_iva, alicuota_iva=D("21"))


# Producto propio: 20 unidades a costo 450, precio 690 (sin descuentos de cliente).
sufijo = datetime.now().strftime("%H%M%S%f")
producto = productos_service.crear_producto(
    codigo=f"IVA{sufijo}"[:20], nombre="Producto IVA", categoria_id=categorias_service.listar_categorias()[0]["id"],
    unidad="un", precio_costo=D("450"), precio_venta=D("690"),
)
movimientos_service.registrar_ingreso(producto["id"], D("20"), "stock_inicial", costo_unitario=D("450"))
efectivo = next(m for m in medios_pago_service.listar_medios_pago() if m["nombre"] == "Efectivo")
medio_cc = next(m for m in medios_pago_service.listar_medios_pago() if m["es_cuenta_corriente"])
proveedor = proveedores_service.crear_proveedor(f"Proveedor IVA {sufijo}")
dos = [{"producto_id": producto["id"], "descripcion_libre": None, "cantidad": D("2")}]


def vender(items, medio=efectivo, **kw):
    total = ventas_service.previsualizar_totales(items, **{k: v for k, v in kw.items() if k == "borrador_id"})["total"]
    return ventas_service.crear_venta(items=items, pagos=[{"medio_pago_id": medio["id"], "monto": total}],
                                      usar_cliente_generico=True, **kw)


print("=== Sin configurar ===")
configurar(None)
v = vender(dos)
verificar("sin IVA: neto = total = 1.380, IVA 0", v["neto"] == D("1380") and v["iva"] == 0 and v["total"] == D("1380"))
verificar("la config avisa que no esta configurado", not negocio_service.config_iva()["configurado"])
print()

print("=== Responsable Inscripto, precios SIN IVA (se suma) ===")
configurar("Responsable Inscripto", precios_con_iva=False)
v = vender(dos)
verificar("neto 1.380 + IVA 289,80 = total 1.669,80", v["neto"] == D("1380") and v["iva"] == D("289.80") and v["total"] == D("1669.80"))
verificar("la venta guarda 21% sumado", v["iva_porcentaje"] == D("21") and not v["precios_con_iva"])
g = ventas_service.detalle_ganancia_venta(v)
verificar("ganancia sobre el neto: 1.380 - 900 = 480", g["ingresos"] == D("1380") and g["ganancia"] == D("480"))
nc = notas_credito_service.crear_nota_credito(
    v["id"], [{"venta_item_id": v["items"][0]["id"], "cantidad": D("1"), "vuelve_stock": True}], "prueba IVA",
    {"tipo": "medio_pago", "medio_pago_id": efectivo["id"]},
)
verificar("nota de credito por 1: se reintegra con IVA (834,90)", nc["total"] == D("834.90"))
verificar("ganancia despues de la NC: 690 - 450 = 240",
          ventas_service.detalle_ganancia_venta(ventas_service.obtener_venta(v["id"]))["ganancia"] == D("240"))
venta_cc = vender(dos, medio=medio_cc, cliente_id=None)
cargo = next(c for c in cc_service.listar_cargos("cliente", venta_cc["cliente_id"]) if c["origen_venta_id"] == venta_cc["id"])
verificar("venta a cuenta corriente: el cargo es el total con IVA (1.669,80)", cargo["monto"] == D("1669.80"))
pr = presupuestos_service.guardar_presupuesto(None, dos)
verificar("presupuesto: neto 1.380 + IVA 289,80", pr["neto"] == D("1380") and pr["iva_monto"] == D("289.80") and pr["total"] == D("1669.80"))
verificar("ganancia estimada sobre el neto: 480", pr["ganancia_estimada"] == D("480"))
print()

print("=== Responsable Inscripto, precios CON IVA (se desglosa) ===")
configurar("Responsable Inscripto", precios_con_iva=True)
v = vender(dos)
verificar("total 1.380 = neto 1.140,50 + IVA 239,50", v["total"] == D("1380") and v["neto"] == D("1140.50") and v["iva"] == D("239.50"))
g = ventas_service.detalle_ganancia_venta(v)
verificar("ganancia sobre el neto: 1.140,50 - 900 = 240,50 (no se infla con el IVA)", g["ganancia"] == D("240.50"))
estimada = ganancias_service.estimar_ganancia_carrito(dos)
verificar("ganancia estimada en la caja tambien sobre el neto (240,50)", estimada["ganancia"] == D("240.50"))
verificar("el presupuesto viejo conserva su IVA sumado (1.669,80)",
          presupuestos_service.obtener_presupuesto(pr["id"])["total"] == D("1669.80"))
venta_pr = vender(dos, borrador_id=pr["id"])
verificar("al cobrarlo se respeta lo prometido (1.669,80, IVA sumado)",
          venta_pr["total"] == D("1669.80") and not venta_pr["precios_con_iva"])
pr2 = presupuestos_service.guardar_presupuesto(None, dos)
pr2 = presupuestos_service.renovar_presupuesto(pr2["id"])
verificar("uno nuevo toma el IVA de hoy (incluido: total 1.380)", pr2["total"] == D("1380") and pr2["precios_con_iva"])
print()

print("=== Monotributo ===")
configurar("Monotributista")
v = vender(dos)
verificar("sin IVA aunque la alicuota este cargada: total 1.380", v["iva"] == 0 and v["total"] == D("1380"))
print()

print("=== Compras ===")
items_oc = [{"producto_id": producto["id"], "descripcion_libre": None, "cantidad_pedida": D("10"), "costo_pactado": D("100")}]
items_rec = [{"producto_id": producto["id"], "cantidad_recibida": D("10"), "costo_unitario": D("100")}]


def comprar():
    oc = ordenes_compra_service.crear_orden_compra_recibida(items_oc, items_rec, proveedor_id=proveedor["id"],
                                                            iva_porcentaje=D("21"), a_credito=True)
    lote = lotes_repo.listar_por_producto(producto["id"])[-1]
    cargo = next(c for c in cc_service.listar_cargos("proveedor", proveedor["id"]) if c["observacion"].startswith(f"Compra a credito - {oc['numero']}"))
    return oc, D(lote["costo_unitario"]) / 100, cargo["monto"]


oc, costo_lote, deuda = comprar()
verificar("OC: neto 1.000 + IVA 210 = total 1.210", oc["neto_estimado"] == D("1000") and oc["iva_estimado"] == D("210")
          and oc["total_estimado"] == D("1210"))
verificar("compra a credito: se le debe al proveedor CON IVA (1.210)", deuda == D("1210"))
verificar("monotributo: el IVA de la compra es costo (lote a 121)", costo_lote == D("121"))
configurar("Responsable Inscripto")
oc, costo_lote, deuda = comprar()
verificar("RI: la deuda sigue siendo con IVA (1.210)", deuda == D("1210"))
verificar("RI: el lote queda al costo neto (100): el IVA se recupera", costo_lote == D("100"))
print()

print("=" * 60)
if fallas:
    print(f"{len(fallas)} verificaciones FALLARON:")
    for f in fallas:
        print(f"  - {f}")
    sys.exit(1)
print("Todas las verificaciones OK")
