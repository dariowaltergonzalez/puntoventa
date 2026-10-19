"""Verificacion de notas de credito: parcial/total, vuelta al stock a los mismos lotes (o no),
reintegro (deuda de la venta en cuenta corriente, devolucion en un medio, saldo a favor,
devolucion del cheque), limites, ganancia neta, snapshot del descuento del cliente y que el
stock cierre con recalcular_stock. Corre contra una COPIA de la base real.
Correr con: python scripts/verificar_notas_credito.py
"""

import inspect
import shutil
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.db.connection as connection_module
from app.config import DB_PATH as DB_PATH_REAL

DB_PATH_TEST = DB_PATH_REAL.parent / "puntoventa_test.db"
shutil.copyfile(DB_PATH_REAL, DB_PATH_TEST)
connection_module.DB_PATH = DB_PATH_TEST

from app.repositories import lotes_repo, movimientos_repo
from app.services import (
    cc_service,
    cheques_service,
    clientes_service,
    medios_pago_service,
    notas_credito_service,
    productos_service,
    ventas_service,
)
from app.services.exceptions import AnulacionInvalidaError, NotaCreditoInvalidaError

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


def stock(producto_id: int) -> Decimal:
    return productos_service.obtener_producto(producto_id)["stock_actual"]


def restante_lotes(producto_id: int) -> int:
    return sum(l["cantidad_restante"] for l in lotes_repo.listar_por_producto(producto_id))


producto = next(p for p in productos_service.listar_productos(solo_activos=True)
                if p["stock_actual"] >= 10 and p["precio_venta"] > 0)
sufijo = datetime.now().strftime("%H%M%S%f")
cliente = clientes_service.crear_cliente(f"Cliente NC {sufijo}")
medios = medios_pago_service.listar_medios_pago(solo_activos=True)
efectivo = next(m for m in medios if m["nombre"] == "Efectivo")
medio_cc = next(m for m in medios if m["es_cuenta_corriente"])
medio_cheque = medios_pago_service.obtener_medio_cheque()
P, C = producto["id"], cliente["id"]
print(f"Producto: {producto['nombre']} (stock {producto['stock_actual']}), cliente id={C}\n")


def vender(cantidad: Decimal, medio: dict, cheque: dict | None = None) -> dict:
    items = [{"producto_id": P, "descripcion_libre": None, "cantidad": cantidad}]
    total = ventas_service.previsualizar_totales(items, cliente_id=C)["total"]
    pago = {"medio_pago_id": medio["id"], "monto": total}
    if cheque:
        pago["cheque"] = cheque
    return ventas_service.crear_venta(items=items, pagos=[pago], cliente_id=C)


# ================= Parcial, efectivo, vuelve al stock =================
print("=== Parcial en efectivo ===")
venta = vender(Decimal("3"), efectivo)
item_id = venta["items"][0]["id"]
stock_antes, lotes_antes = stock(P), restante_lotes(P)
ganancia_antes = ventas_service.calcular_ganancia_venta(venta)
nc = notas_credito_service.crear_nota_credito(
    venta["id"], [{"venta_item_id": item_id, "cantidad": Decimal("1"), "vuelve_stock": True}], "Perdia",
    destino_resto={"tipo": "medio_pago", "medio_pago_id": efectivo["id"]},
)
verificar("numero NC-xxxx", nc["numero"].startswith("NC-"))
verificar("total = un tercio de la venta", nc["total"] == (venta["total"] / 3).quantize(Decimal("1.00")))
verificar("el stock sube 1", stock(P) == stock_antes + 1)
verificar("los lotes recuperan 1 (mismo lote, mismo costo)", restante_lotes(P) == lotes_antes + 1000)
verificar("reintegro en efectivo", nc["reintegros"][0]["tipo"] == "medio_pago" and nc["reintegros"][0]["medio_pago_nombre"] == "Efectivo")
venta = ventas_service.obtener_venta(venta["id"])
verificar("la venta muestra lo devuelto y el total neto",
          venta["items"][0]["cantidad_devuelta"] == 1 and venta["total_neto"] == venta["total"] - nc["total"])
verificar("la ganancia baja", ventas_service.calcular_ganancia_venta(venta) < ganancia_antes)
verificar("no se puede devolver mas de lo que queda (2)",
          lanza(NotaCreditoInvalidaError, notas_credito_service.crear_nota_credito, venta["id"],
                [{"venta_item_id": item_id, "cantidad": Decimal("3"), "vuelve_stock": True}], "x",
                {"tipo": "medio_pago", "medio_pago_id": efectivo["id"]}))
verificar("motivo obligatorio",
          lanza(ValueError, notas_credito_service.crear_nota_credito, venta["id"],
                [{"venta_item_id": item_id, "cantidad": Decimal("1")}], "  "))

# Lo que no vuelve al stock
stock_antes = stock(P)
nc2 = notas_credito_service.crear_nota_credito(
    venta["id"], [{"venta_item_id": item_id, "cantidad": Decimal("2"), "vuelve_stock": False}], "Vencido",
    destino_resto={"tipo": "medio_pago", "medio_pago_id": efectivo["id"]},
)
verificar("lo que no vuelve al stock no toca el stock", stock(P) == stock_antes)
venta = ventas_service.obtener_venta(venta["id"])
verificar("venta totalmente acreditada: neto 0 y nada por acreditar",
          venta["total_neto"] == 0 and not venta["queda_por_acreditar"])
print()

# ================= Redondeo: varias NC parciales suman justo el total =================
print("=== Redondeo ===")
items_libre = [{"producto_id": None, "descripcion_libre": "Servicio", "cantidad": Decimal("3"),
                "precio_unitario": Decimal("0.35")}]
total_libre = ventas_service.previsualizar_totales(items_libre, cliente_id=C, descuento_total_porcentaje=Decimal("10"))["total"]
venta_libre = ventas_service.crear_venta(items=items_libre, pagos=[{"medio_pago_id": efectivo["id"], "monto": total_libre}],
                                         cliente_id=C, descuento_total_porcentaje=Decimal("10"))
for _ in range(3):
    notas_credito_service.crear_nota_credito(
        venta_libre["id"], [{"venta_item_id": venta_libre["items"][0]["id"], "cantidad": Decimal("1")}], "de a uno",
        destino_resto={"tipo": "medio_pago", "medio_pago_id": efectivo["id"]},
    )
venta_libre = ventas_service.obtener_venta(venta_libre["id"])
verificar(f"3 NC de a una unidad suman justo el total ({venta_libre['total']})",
          venta_libre["total_acreditado"] == venta_libre["total"] and venta_libre["total_neto"] == 0)
print()

# ================= Venta en cuenta corriente =================
print("=== Venta en cuenta corriente ===")
saldo_antes = cc_service.calcular_saldo_total("cliente", C)
venta_cc = vender(Decimal("2"), medio_cc)
verificar("la venta a credito suma deuda", cc_service.calcular_saldo_total("cliente", C) == saldo_antes + venta_cc["total"])
opciones = notas_credito_service.opciones_reintegro(venta_cc["id"], venta_cc["total"])
verificar("las opciones descuentan todo de la deuda de la venta",
          opciones["a_cuenta_corriente"] == venta_cc["total"] and opciones["resto"] == 0)
nc_cc = notas_credito_service.crear_nota_credito(
    venta_cc["id"], [{"venta_item_id": venta_cc["items"][0]["id"], "cantidad": Decimal("2"), "vuelve_stock": True}],
    "No era lo que pidio",
)
verificar("la NC total cancela la deuda de esa venta", cc_service.calcular_saldo_total("cliente", C) == saldo_antes)
cargo_venta = next(c for c in cc_service.listar_cargos("cliente", C) if c["origen_venta_id"] == venta_cc["id"])
verificar("el cargo de la venta queda saldado", cargo_venta["saldo_pendiente"] == 0)
pago_nc = next(p for p in cc_service.listar_pagos("cliente", C) if p["nota_credito_id"] == nc_cc["id"])
verificar("el credito aparece en CC vinculado a la NC", pago_nc["nota_credito_numero"] == nc_cc["numero"])
verificar("ese credito no se anula desde CC", lanza(AnulacionInvalidaError, cc_service.anular_pago, pago_nc["id"], "x"))
print()

# ================= Saldo a favor =================
print("=== Saldo a favor ===")
saldo_antes = cc_service.calcular_saldo_total("cliente", C)
venta_ef = vender(Decimal("1"), efectivo)
notas_credito_service.crear_nota_credito(
    venta_ef["id"], [{"venta_item_id": venta_ef["items"][0]["id"], "cantidad": Decimal("1"), "vuelve_stock": True}],
    "Lo deja a cuenta", destino_resto={"tipo": "a_favor"},
)
verificar("queda a favor en su cuenta corriente", cc_service.calcular_saldo_total("cliente", C) == saldo_antes - venta_ef["total"])
generico = clientes_service.obtener_o_crear_cliente_generico()
items_gen = [{"producto_id": P, "descripcion_libre": None, "cantidad": Decimal("1")}]
total_gen = ventas_service.previsualizar_totales(items_gen, cliente_id=generico["id"])["total"]
venta_gen = ventas_service.crear_venta(items=items_gen, pagos=[{"medio_pago_id": efectivo["id"], "monto": total_gen}],
                                       usar_cliente_generico=True)
verificar("al cliente generico no se le deja saldo a favor",
          lanza(NotaCreditoInvalidaError, notas_credito_service.crear_nota_credito, venta_gen["id"],
                [{"venta_item_id": venta_gen["items"][0]["id"], "cantidad": Decimal("1")}], "x", {"tipo": "a_favor"}))
print()

# ================= Devolver el cheque =================
print("=== Devolver el cheque ===")
venta_ch = vender(Decimal("1"), medio_cheque, {"banco": "Banco NC", "librador": "Librador NC", "fecha_pago": "2026-12-31"})
cheque_id = venta_ch["pagos"][0]["cheque_id"]
opciones = notas_credito_service.opciones_reintegro(venta_ch["id"], venta_ch["total"])
verificar("sugiere devolver el cheque", opciones["destino_sugerido"] == {"tipo": "cheque", "cheque_id": cheque_id})
notas_credito_service.crear_nota_credito(
    venta_ch["id"], [{"venta_item_id": venta_ch["items"][0]["id"], "cantidad": Decimal("1"), "vuelve_stock": True}],
    "Se arrepintio", destino_resto={"tipo": "cheque", "cheque_id": cheque_id},
)
verificar("el cheque pasa a baja", cheques_service.obtener_cheque(cheque_id)["estado"] == "baja")
print()

# ================= Snapshot del descuento del cliente =================
print("=== Snapshot del descuento del cliente ===")
venta_snap = vender(Decimal("1"), efectivo)
parametros = inspect.signature(clientes_service.actualizar_cliente).parameters
datos_cliente = {k: v for k, v in clientes_service.obtener_cliente(C).items() if k in parametros and k != "cliente_id"}
clientes_service.actualizar_cliente(C, **(datos_cliente | {"porcentaje_descuento": Decimal("50")}))
verificar("cambiar el % del cliente no cambia el total de una venta vieja",
          ventas_service.obtener_venta(venta_snap["id"])["total"] == venta_snap["total"])
print()

# ================= Stock =================
print("=== Stock ===")
antes = {p["id"]: p["stock_actual"] for p in productos_service.listar_productos()}
movimientos_repo.recalcular_stock()
despues = {p["id"]: p["stock_actual"] for p in productos_service.listar_productos()}
verificar("recalcular_stock no encuentra diferencias", antes == despues)
print()

print("=" * 60)
if fallas:
    print(f"{len(fallas)} verificaciones FALLARON:")
    for f in fallas:
        print(f"  - {f}")
    sys.exit(1)
print("Todas las verificaciones OK")
