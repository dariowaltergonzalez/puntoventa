"""Verificacion del cierre de Fase 6 en Cuentas Corrientes: medio de pago en cada pago, saldo a
favor cuando un pago supera la deuda, anulacion de pagos (con y sin cheque: vuelta a cartera,
baja, bloqueos) y anulacion de cargos manuales. Corre contra una COPIA de la base real.
Correr con: python scripts/verificar_cc_medios_anulaciones.py
"""

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

from app.services import cc_service, cheques_service, clientes_service, medios_pago_service, proveedores_service
from app.services.exceptions import AnulacionInvalidaError, ChequeEstadoInvalidoError

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


sufijo = datetime.now().strftime("%H%M%S%f")
proveedor = proveedores_service.crear_proveedor(f"Proveedor verif {sufijo}")
cliente = clientes_service.crear_cliente(f"Cliente verif {sufijo}")
medios = medios_pago_service.listar_medios_pago(solo_activos=True)
efectivo = next(m for m in medios if m["nombre"] == "Efectivo")
cuenta_corriente = next(m for m in medios if m["es_cuenta_corriente"])
medio_cheque = medios_pago_service.obtener_medio_cheque()
hoy = datetime.now().strftime("%Y-%m-%d")
P, C = proveedor["id"], cliente["id"]

# ================= Medio de pago =================
print("=== Medio de pago ===")
cargo1 = cc_service.registrar_cargo_manual("proveedor", P, Decimal("1000"), hoy, "cargo 1")
pago_ef = cc_service.registrar_pago("proveedor", P, Decimal("400"), hoy, medio_pago_id=efectivo["id"])
verificar("el pago guarda el medio", pago_ef["medio_pago_id"] == efectivo["id"] and pago_ef["medio_nombre"] == "Efectivo")
verificar("no se puede pagar con el medio 'cuenta corriente'",
          lanza(ValueError, cc_service.registrar_pago, "proveedor", P, Decimal("1"), hoy,
                medio_pago_id=cuenta_corriente["id"]))
verificar("saldo 600 tras pagar 400 de 1000", cc_service.calcular_saldo_total("proveedor", P) == Decimal("600"))
print()

# ================= Anular pago sin cheque =================
print("=== Anular pago sin cheque ===")
verificar("anular sin motivo falla", lanza(ValueError, cc_service.anular_pago, pago_ef["id"], "  "))
anulado = cc_service.anular_pago(pago_ef["id"], "cargado por error")
verificar("el pago queda marcado anulado con motivo",
          anulado["anulado_fecha"] is not None and anulado["anulado_motivo"] == "cargado por error")
verificar("el cargo vuelve a quedar pendiente completo",
          cc_service.obtener_cargo(cargo1["id"])["saldo_pendiente"] == Decimal("1000"))
verificar("saldo total vuelve a 1000", cc_service.calcular_saldo_total("proveedor", P) == Decimal("1000"))
verificar("anular dos veces falla", lanza(AnulacionInvalidaError, cc_service.anular_pago, pago_ef["id"], "otra vez"))
print()

# ================= Saldo a favor =================
print("=== Saldo a favor ===")
cc_service.registrar_pago("proveedor", P, Decimal("1500"), hoy, medio_pago_id=efectivo["id"])
verificar("pago de 1500 sobre deuda de 1000 deja saldo a favor de 500",
          cc_service.calcular_saldo_total("proveedor", P) == Decimal("-500"))
verificar("el cargo queda saldado", cc_service.obtener_cargo(cargo1["id"])["saldo_pendiente"] == Decimal("0"))
print()

# ================= Corregir pago =================
print("=== Corregir pago ===")
pago_a_corregir = next(p for p in cc_service.listar_pagos("proveedor", P)
                       if not p["anulado_fecha"] and p["monto"] == Decimal("1500"))
corregido = cc_service.corregir_pago(pago_a_corregir["id"], Decimal("1000"), hoy, efectivo["id"])
viejo = cc_service.obtener_pago(pago_a_corregir["id"])
verificar("el pago viejo queda anulado con motivo automatico",
          viejo["anulado_fecha"] is not None and "1.500,00 -> 1.000,00" in viejo["anulado_motivo"])
verificar("el pago nuevo tiene el monto corregido y el medio", corregido["monto"] == Decimal("1000")
          and corregido["medio_pago_id"] == efectivo["id"] and corregido["anulado_fecha"] is None)
verificar("tras corregir 1500 -> 1000 el saldo queda en 0", cc_service.calcular_saldo_total("proveedor", P) == Decimal("0"))
verificar("el cargo sigue saldado por el pago nuevo",
          cc_service.obtener_cargo(cargo1["id"])["saldo_pendiente"] == Decimal("0"))
fila_nueva = next(p for p in cc_service.listar_pagos("proveedor", P) if p["id"] == corregido["id"])
verificar("el pago nuevo sabe a quien reemplazo (corregido_de con el monto anterior)",
          fila_nueva["corregido_de"] is not None and fila_nueva["corregido_de"]["monto"] == Decimal("1500"))
verificar("corregir sin cambiar nada falla",
          lanza(ValueError, cc_service.corregir_pago, corregido["id"], Decimal("1000"), hoy, efectivo["id"]))
verificar("corregir un pago anulado falla",
          lanza(AnulacionInvalidaError, cc_service.corregir_pago, viejo["id"], Decimal("900"), hoy, efectivo["id"]))
print()

# ================= Anular cargo manual =================
print("=== Anular cargo manual ===")
verificar("no se anula un cargo con pagos aplicados",
          lanza(AnulacionInvalidaError, cc_service.anular_cargo, cargo1["id"], "error"))
cargo2 = cc_service.registrar_cargo_manual("proveedor", P, Decimal("300"), hoy, "cargo 2 por error")
saldo_antes = cc_service.calcular_saldo_total("proveedor", P)
cargo2_anulado = cc_service.anular_cargo(cargo2["id"], "duplicado")
verificar("el cargo queda anulado con saldo pendiente 0",
          cargo2_anulado["anulado_fecha"] is not None and cargo2_anulado["saldo_pendiente"] == Decimal("0"))
verificar("el cargo anulado no suma al saldo total",
          cc_service.calcular_saldo_total("proveedor", P) == saldo_antes - Decimal("300"))
verificar("el cargo anulado no aparece entre los abiertos",
          all(c["id"] != cargo2["id"] for c in cc_service.listar_cargos("proveedor", P, solo_con_saldo=True)))
print()

# ================= Cheques =================
print("=== Anular pagos con cheque ===")
verificar("existe el medio de pago 'Cheque'", medio_cheque is not None)
cc_service.registrar_cargo_manual("cliente", C, Decimal("2000"), hoy, "deuda cliente")
cheque_cli = cheques_service.recibir_de_cliente_para_cc(
    cliente_id=C, banco="Banco Prueba", librador="Librador Prueba", monto=Decimal("2000"), fecha_pago="2026-12-01",
)
pago_cobro = next(p for p in cc_service.listar_pagos("cliente", C) if p["cheque_id"] == cheque_cli["id"])
verificar("el cobro con cheque guarda el medio 'Cheque'", pago_cobro["medio_pago_id"] == medio_cheque["id"])

cargo_prov = cc_service.registrar_cargo_manual("proveedor", P, Decimal("2500"), hoy, "deuda para cheque")
cheques_service.entregar_a_proveedor(cheque_cli["id"], P)
pago_entrega = next(p for p in cc_service.listar_pagos("proveedor", P) if p["cheque_id"] == cheque_cli["id"])
verificar("no se anula el cobro si el cheque ya se entrego a un proveedor",
          lanza(ChequeEstadoInvalidoError, cc_service.anular_pago, pago_cobro["id"], "error"))

cc_service.anular_pago(pago_entrega["id"], "le di otro cheque")
cheque_vuelto = cheques_service.obtener_cheque(cheque_cli["id"])
verificar("al anular la entrega, el cheque vuelve a cartera sin proveedor",
          cheque_vuelto["estado"] == "en_cartera" and cheque_vuelto["proveedor_id"] is None)

cc_service.anular_pago(pago_cobro["id"], "el cheque era de otro cliente")
cheque_baja = cheques_service.obtener_cheque(cheque_cli["id"])
verificar("al anular el cobro, el cheque recibido pasa a baja", cheque_baja["estado"] == "baja")
verificar("y la deuda del cliente vuelve a 2000", cc_service.calcular_saldo_total("cliente", C) == Decimal("2000"))

propio = cheques_service.crear_cheque_propio_y_entregar(
    proveedor_id=P, banco="Mi Banco", librador="Mi negocio", monto=Decimal("100"), fecha_pago="2026-12-10",
)
pago_propio = next(p for p in cc_service.listar_pagos("proveedor", P) if p["cheque_id"] == propio["id"])
cc_service.anular_pago(pago_propio["id"], "monto mal cargado")
verificar("al anular un pago con cheque propio, el cheque pasa a baja",
          cheques_service.obtener_cheque(propio["id"])["estado"] == "baja")

propio2 = cheques_service.crear_cheque_propio_y_entregar(
    proveedor_id=P, banco="Mi Banco", librador="Mi negocio", monto=Decimal("50"), fecha_pago="2026-12-10",
)
cheques_service.marcar_rechazado(propio2["id"], "sin fondos")
pago_propio2 = next(p for p in cc_service.listar_pagos("proveedor", P) if p["cheque_id"] == propio2["id"])
verificar("no se anula un pago cuyo cheque ya fue rechazado",
          lanza(ChequeEstadoInvalidoError, cc_service.anular_pago, pago_propio2["id"], "error"))
verificar("un pago con cheque no se corrige",
          lanza(AnulacionInvalidaError, cc_service.corregir_pago, pago_propio2["id"], Decimal("60"), hoy, efectivo["id"]))
print()

print("=" * 60)
if fallas:
    print(f"{len(fallas)} verificaciones FALLARON:")
    for f in fallas:
        print(f"  - {f}")
    sys.exit(1)
print("Todas las verificaciones OK")
