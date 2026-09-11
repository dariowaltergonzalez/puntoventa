"""Verificacion de punta a punta de Fase 4 (Ventas): consumo FIFO (incluido el lote 'inicial'
de arranque), resolucion de precio por lista, los 3 descuentos acumulados, pago dividido con
cargo automatico en Cuentas Corrientes, item libre, y validaciones de error. Corre contra una
COPIA de la base real. Correr con: python scripts/verificar_fase4_ventas.py
"""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.db.connection as connection_module
from app.config import DB_PATH as DB_PATH_REAL

connection_module.DB_PATH = DB_PATH_REAL.parent / "puntoventa_test.db"

from app.services import (
    cc_service,
    clientes_service,
    listas_precios_service,
    medios_pago_service,
    movimientos_service,
    productos_service,
    ventas_service,
)
from app.services.exceptions import MontoPagoInvalidoError, StockInsuficienteError

medios = {m["nombre"]: m for m in medios_pago_service.listar_medios_pago()}
efectivo = medios["Efectivo"]
cuenta_corriente = medios["Cuenta corriente"]

# ================= Caso 1: venta simple, consume el lote 'inicial' (Arroz) =================
arroz = next(p for p in productos_service.listar_productos() if p["codigo"] == "ARR001")
stock_antes = arroz["stock_actual"]
print(f"Arroz stock antes: {stock_antes}")

venta1 = ventas_service.crear_venta(
    items=[{"producto_id": arroz["id"], "descripcion_libre": None, "cantidad": Decimal("5")}],
    pagos=[{"medio_pago_id": efectivo["id"], "monto": Decimal(str(arroz["precio_venta"] * 5))}],
    usar_cliente_generico=True,
)
print(f"Venta 1: {venta1['numero']} estado={venta1['estado']} total={venta1['total']}")
item1 = venta1["items"][0]
print(f"  lotes consumidos: {item1['lotes']}")
assert sum(l["cantidad"] for l in item1["lotes"]) == Decimal("5.000")

arroz_despues = productos_service.obtener_producto(arroz["id"])
print(f"Arroz stock despues: {arroz_despues['stock_actual']} (esperado {stock_antes - Decimal('5')})")
assert arroz_despues["stock_actual"] == stock_antes - Decimal("5")

# ================= Caso 2: venta con lista de precios =================
listas = listas_precios_service.listar_listas()
if listas:
    lista = listas[0]
    precio_normal = arroz_despues["precio_venta"]
    precio_lista = listas_precios_service.calcular_precio_producto(arroz["id"], lista["id"])
    print(f"\nPrecio normal Arroz: {precio_normal}  Precio con lista '{lista['nombre']}': {precio_lista}")
    venta2 = ventas_service.crear_venta(
        items=[{"producto_id": arroz["id"], "descripcion_libre": None, "cantidad": Decimal("2")}],
        pagos=[{"medio_pago_id": efectivo["id"], "monto": (precio_lista * 2).quantize(Decimal("1.00"))}],
        usar_cliente_generico=True,
        lista_precio_id=lista["id"],
    )
    assert venta2["items"][0]["precio_unitario"] == precio_lista
    print(f"Venta 2 (con lista): precio_unitario usado={venta2['items'][0]['precio_unitario']} OK")

# ================= Caso 3: descuentos acumulados (item + cliente + total) =================
clientes = clientes_service.listar_clientes()
cliente_con_descuento = next((c for c in clientes if c["porcentaje_descuento"]), None)
if cliente_con_descuento:
    print(f"\nCliente con descuento fijo: {cliente_con_descuento['razon_social']} ({cliente_con_descuento['porcentaje_descuento']}%)")
    fideos = next(p for p in productos_service.listar_productos() if p["codigo"] == "FID001")
    precio = fideos["precio_venta"]
    cantidad = Decimal("3")
    descuento_item = Decimal("10")
    descuento_total = Decimal("5")

    monto_item = cantidad * precio * (Decimal("1") - descuento_item / 100)
    monto_con_cliente = monto_item * (Decimal("1") - cliente_con_descuento["porcentaje_descuento"] / 100)
    total_esperado = (monto_con_cliente * (Decimal("1") - descuento_total / 100)).quantize(Decimal("1.00"))

    venta3 = ventas_service.crear_venta(
        items=[{"producto_id": fideos["id"], "descripcion_libre": None, "cantidad": cantidad,
                "descuento_item_porcentaje": descuento_item}],
        pagos=[{"medio_pago_id": efectivo["id"], "monto": total_esperado}],
        cliente_id=cliente_con_descuento["id"],
        descuento_total_porcentaje=descuento_total,
    )
    print(f"Venta 3: total calculado={venta3['total']}  esperado={total_esperado}")
    assert venta3["total"] == total_esperado
else:
    print("\n(sin cliente con % de descuento cargado, salteo caso 3)")

# ================= Caso 4: pago dividido, cargo parcial en Cuentas Corrientes =================
cliente_generico = clientes_service.obtener_o_crear_cliente_generico()
saldo_cc_antes = cc_service.calcular_saldo_total("cliente", cliente_generico["id"])
garbanzos = next(p for p in productos_service.listar_productos() if p["codigo"] == "FF2565")
if garbanzos["stock_actual"] >= 1:
    precio_garbanzos = garbanzos["precio_venta"]
    total_venta4 = precio_garbanzos * 1
    mitad = (total_venta4 / 2).quantize(Decimal("1.00"))
    resto = (total_venta4 - mitad).quantize(Decimal("1.00"))
    venta4 = ventas_service.crear_venta(
        items=[{"producto_id": garbanzos["id"], "descripcion_libre": None, "cantidad": Decimal("1")}],
        pagos=[
            {"medio_pago_id": efectivo["id"], "monto": mitad},
            {"medio_pago_id": cuenta_corriente["id"], "monto": resto},
        ],
        cliente_id=cliente_generico["id"],
    )
    saldo_cc_despues = cc_service.calcular_saldo_total("cliente", cliente_generico["id"])
    print(f"\nVenta 4 (pago dividido): total={venta4['total']}  efectivo={mitad}  cuenta_corriente={resto}")
    print(f"Saldo CC del cliente: antes={saldo_cc_antes} despues={saldo_cc_despues} (esperado +{resto})")
    assert saldo_cc_despues == saldo_cc_antes + resto

# ================= Caso 5: item libre (no toca stock) =================
venta5 = ventas_service.crear_venta(
    items=[{"producto_id": None, "descripcion_libre": "Instalacion", "cantidad": Decimal("1"),
            "precio_unitario": Decimal("2500")}],
    pagos=[{"medio_pago_id": efectivo["id"], "monto": Decimal("2500")}],
    usar_cliente_generico=True,
)
print(f"\nVenta 5 (item libre): {venta5['items'][0]}")
assert venta5["items"][0]["producto_id"] is None
assert len(venta5["items"][0]["lotes"]) == 0

# ================= Caso 6: validaciones de error =================
try:
    ventas_service.crear_venta(
        items=[{"producto_id": arroz["id"], "descripcion_libre": None, "cantidad": Decimal("999999")}],
        pagos=[{"medio_pago_id": efectivo["id"], "monto": Decimal("1")}],
        usar_cliente_generico=True,
    )
    print("FALLO: deberia rechazar por stock insuficiente")
except StockInsuficienteError as ex:
    print(f"\nOK: stock insuficiente rechazado -> {ex}")

try:
    ventas_service.crear_venta(
        items=[{"producto_id": arroz["id"], "descripcion_libre": None, "cantidad": Decimal("1")}],
        pagos=[{"medio_pago_id": efectivo["id"], "monto": Decimal("1")}],
        usar_cliente_generico=True,
    )
    print("FALLO: deberia rechazar por monto de pago no coincide")
except MontoPagoInvalidoError as ex:
    print(f"OK: monto de pago no coincide rechazado -> {ex}")

# ================= Ganancia y consistencia general =================
ganancia1 = ventas_service.calcular_ganancia_venta(venta1)
print(f"\nGanancia venta 1: {ganancia1}")

diferencias = movimientos_service.recalcular_stock()
print(f"\nrecalcular_stock: {len(diferencias)} diferencia(s) (esperado 0)")
assert len(diferencias) == 0

print("\nTodo OK")
