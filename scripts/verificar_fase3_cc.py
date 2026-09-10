"""Verificacion de punta a punta de Fase 3 (Cuentas Corrientes): cargo manual, pagos FIFO y
puntuales, mora, limite de credito, y el enganche automatico con Compras (recepcion a credito).
Corre contra una COPIA de la base real. Correr con: python scripts/verificar_fase3_cc.py
"""

import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.db.connection as connection_module
from app.config import DB_PATH as DB_PATH_REAL

connection_module.DB_PATH = DB_PATH_REAL.parent / "puntoventa_test.db"

from app.services import (
    cc_service,
    clientes_service,
    movimientos_service,
    ordenes_compra_service,
    productos_service,
    proveedores_service,
    recepciones_service,
)
from app.services.exceptions import MontoPagoInvalidoError

# ================= Lado clientes: cargo manual, FIFO, mora, limite =================
cliente = clientes_service.listar_clientes()[0]
print(f"Cliente: {cliente['razon_social']}  plazo={cliente['plazo_pago_dias']}d  "
      f"mora={cliente['tasa_interes_mora_diaria']}%/dia  limite={cliente['limite_credito']}")

fecha_vieja = (datetime.now() - timedelta(days=100)).isoformat()
cargo1 = cc_service.registrar_cargo_manual("cliente", cliente["id"], Decimal("10000"), fecha_vieja, "Cargo viejo")
cargo2 = cc_service.registrar_cargo_manual("cliente", cliente["id"], Decimal("5000"), datetime.now().isoformat(), "Cargo reciente")
assert cc_service.calcular_saldo_total("cliente", cliente["id"]) >= Decimal("15000.00")

interes = cc_service.calcular_interes_mora(cliente["id"], cargo1)
print(f"Interes sobre cargo viejo (100 dias, deberia ser > 0): {interes}")
assert interes > 0
assert cc_service.calcular_interes_mora(cliente["id"], cargo2) == Decimal("0")

evaluacion = cc_service.evaluar_limite_credito(cliente["id"])
print(f"Evaluacion limite: supera={evaluacion['supera']}  avisar={evaluacion['avisar']}  bloquear={evaluacion['bloquear']}")

pago = cc_service.registrar_pago("cliente", cliente["id"], Decimal("12000"), datetime.now().isoformat(), observacion="Pago a cuenta")
cargos = cc_service.listar_cargos("cliente", cliente["id"])
c1 = next(c for c in cargos if c["id"] == cargo1["id"])
c2 = next(c for c in cargos if c["id"] == cargo2["id"])
print(f"FIFO: cargo1 saldo={c1['saldo_pendiente']} (esperado 0.00)  cargo2 saldo={c2['saldo_pendiente']} (esperado 3000.00)")
assert c1["saldo_pendiente"] == Decimal("0.00")
assert c2["saldo_pendiente"] == Decimal("3000.00")

cc_service.registrar_pago("cliente", cliente["id"], Decimal("3000"), datetime.now().isoformat(),
                           aplicaciones=[{"cargo_id": cargo2["id"], "monto": Decimal("3000")}])
assert next(c for c in cc_service.listar_cargos("cliente", cliente["id"]) if c["id"] == cargo2["id"])["saldo_pendiente"] == Decimal("0.00")

try:
    cc_service.registrar_pago("cliente", cliente["id"], Decimal("0"), datetime.now().isoformat())
    print("FALLO: deberia rechazar monto 0")
except MontoPagoInvalidoError:
    print("OK: pago con monto 0 rechazado")

print("Lado clientes: OK\n")

# ================= Lado proveedores: cargo manual + enganche automatico con Compras =================
proveedor = proveedores_service.listar_proveedores()[0]
saldo_antes = cc_service.calcular_saldo_total("proveedor", proveedor["id"])
cc_service.registrar_cargo_manual("proveedor", proveedor["id"], Decimal("8000"), datetime.now().isoformat(), "Cargo manual")
assert cc_service.calcular_saldo_total("proveedor", proveedor["id"]) == saldo_antes + Decimal("8000.00")
print(f"Cargo manual a proveedor: OK (saldo {saldo_antes} -> {saldo_antes + Decimal('8000.00')})")

# Recepcion normal (OC pendiente -> se recibe despues) marcada a credito
producto = productos_service.listar_productos()[0]
oc = ordenes_compra_service.crear_orden_compra(
    items=[{"producto_id": producto["id"], "descripcion_libre": None,
            "cantidad_pedida": Decimal("10"), "costo_pactado": Decimal("500")}],
    proveedor_id=proveedor["id"],
)
recepciones_service.confirmar_recepcion(
    orden_compra_id=oc["id"],
    items=[{"orden_compra_item_id": oc["items"][0]["id"], "producto_id": producto["id"], "producto_nuevo": None,
            "descripcion_libre": None, "cantidad_recibida": Decimal("10"), "costo_unitario": Decimal("500")}],
    a_credito=True,
)
saldo_con_recepcion = cc_service.calcular_saldo_total("proveedor", proveedor["id"])
print(f"Recepcion normal a credito (10 x 500 = 5000): saldo -> {saldo_con_recepcion} (esperado +5000 sobre el anterior)")
assert saldo_con_recepcion == saldo_antes + Decimal("8000.00") + Decimal("5000.00")

# Flujo rapido "ya la tenes en mano" marcado a credito
oc_rapida = ordenes_compra_service.crear_orden_compra_recibida(
    items=[{"producto_id": None, "producto_nuevo": None, "descripcion_libre": "Flete",
            "cantidad_pedida": Decimal("1"), "costo_pactado": Decimal("1500")}],
    recepcion_items=[{"orden_compra_item_id": None, "producto_id": None, "producto_nuevo": None,
                       "descripcion_libre": "Flete", "cantidad_recibida": Decimal("1"), "costo_unitario": Decimal("1500")}],
    proveedor_id=proveedor["id"],
    a_credito=True,
)
saldo_final = cc_service.calcular_saldo_total("proveedor", proveedor["id"])
print(f"'Ya la tenes en mano' a credito (1500): saldo -> {saldo_final} (esperado +1500 sobre el anterior)")
assert saldo_final == saldo_con_recepcion + Decimal("1500.00")

# La misma OC rapida SIN marcar a credito no debe generar cargo
oc_rapida_sin_credito = ordenes_compra_service.crear_orden_compra_recibida(
    items=[{"producto_id": None, "producto_nuevo": None, "descripcion_libre": "Flete pagado",
            "cantidad_pedida": Decimal("1"), "costo_pactado": Decimal("800")}],
    recepcion_items=[{"orden_compra_item_id": None, "producto_id": None, "producto_nuevo": None,
                       "descripcion_libre": "Flete pagado", "cantidad_recibida": Decimal("1"), "costo_unitario": Decimal("800")}],
    proveedor_id=proveedor["id"],
    a_credito=False,
)
assert cc_service.calcular_saldo_total("proveedor", proveedor["id"]) == saldo_final

print("Lado proveedores + enganche con Compras: OK\n")

diferencias = movimientos_service.recalcular_stock()
print(f"recalcular_stock: {len(diferencias)} diferencia(s) (esperado 0)")
assert len(diferencias) == 0

print("\nTodo OK")
