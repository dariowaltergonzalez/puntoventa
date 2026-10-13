"""Verificacion de punta a punta de Fase 6 (Cheques): entrada via venta, entrada suelta para
saldar cuenta corriente, circulacion a un proveedor (CC vieja y compra nueva), cheque propio,
baja, rechazo (de un recibido y de uno propio) con reapertura automatica de la deuda, y
validaciones de error incluida la compensacion (no deja cheques huerfanos). Corre contra una
COPIA de la base real. Correr con: python scripts/verificar_fase6_cheques.py
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
    cheques_service,
    clientes_service,
    medios_pago_service,
    movimientos_service,
    ordenes_compra_service,
    productos_service,
    proveedores_service,
    recepciones_service,
    ventas_service,
)
from app.services.exceptions import ChequeEstadoInvalidoError

fallas = []


def verificar(nombre, condicion):
    estado = "OK" if condicion else "FALLO"
    print(f"[{estado}] {nombre}")
    if not condicion:
        fallas.append(nombre)


cliente = clientes_service.listar_clientes()[0]
proveedor = proveedores_service.listar_proveedores()[0]
arroz = next(p for p in productos_service.listar_productos() if p["codigo"] == "ARR001")
efectivo = next(m for m in medios_pago_service.listar_medios_pago() if m["nombre"] == "Efectivo")

print(f"Cliente de prueba: {cliente['razon_social']} (id={cliente['id']})")
print(f"Proveedor de prueba: {proveedor['nombre']} (id={proveedor['id']})")
print()

# ================= Caso 1: entrada via venta, pagada con cheque =================
print("=== Caso 1: cheque recibido como pago de una venta ===")
totales = ventas_service.previsualizar_totales(
    items=[{"producto_id": arroz["id"], "descripcion_libre": None, "cantidad": Decimal("2")}],
    cliente_id=cliente["id"],
)
venta = ventas_service.crear_venta(
    items=[{"producto_id": arroz["id"], "descripcion_libre": None, "cantidad": Decimal("2")}],
    pagos=[{
        "medio_pago_id": efectivo["id"], "monto": totales["total"],
        "cheque": {"banco": "Banco Nacion", "librador": "Casa Juancho SA", "numero": "00012345",
                   "fecha_pago": "2026-11-15"},
    }],
    cliente_id=cliente["id"],
)
pago_venta = venta["pagos"][0]
cheque1_id = pago_venta["cheque_id"]
verificar("la venta persistio pagos[0].cheque_id", cheque1_id is not None)
cheque1 = cheques_service.obtener_cheque(cheque1_id)
verificar("cheque 1 estado='en_cartera'", cheque1["estado"] == "en_cartera")
verificar("cheque 1 origen_tipo='recibido_cliente'", cheque1["origen_tipo"] == "recibido_cliente")
verificar("cheque 1 cliente_id correcto", cheque1["cliente_id"] == cliente["id"])
verificar("cheque 1 monto correcto", cheque1["monto"] == totales["total"])
verificar("cheque 1 banco/librador/numero correctos",
          cheque1["banco"] == "Banco Nacion" and cheque1["librador"] == "Casa Juancho SA"
          and cheque1["numero"] == "00012345")
print()

# ================= Caso 2: entrada suelta para saldar CC vieja =================
print("=== Caso 2: cheque suelto para saldar una deuda vieja de cuenta corriente ===")
cargo_viejo = cc_service.registrar_cargo_manual(
    entidad_tipo="cliente", entidad_id=cliente["id"], monto=Decimal("5000"), fecha="2026-09-01",
    observacion="Deuda vieja de prueba",
)
saldo_antes = cc_service.calcular_saldo_total("cliente", cliente["id"])
cheque2 = cheques_service.recibir_de_cliente_para_cc(
    cliente_id=cliente["id"], banco="Banco Galicia", librador=cliente["razon_social"],
    monto=Decimal("5000"), fecha_pago="2026-11-20", numero="00054321",
)
saldo_despues = cc_service.calcular_saldo_total("cliente", cliente["id"])
verificar("cheque 2 estado='en_cartera'", cheque2["estado"] == "en_cartera")
verificar("el saldo del cliente bajo exactamente el monto del cheque",
          saldo_antes - saldo_despues == Decimal("5000"))
cargo_viejo_actualizado = cc_service.obtener_cargo(cargo_viejo["id"])
verificar("el cargo viejo quedo saldado", cargo_viejo_actualizado["saldo_pendiente"] == Decimal("0"))
print()

# ================= Caso 3: circular un cheque (cheque1) para saldar CC vieja de un proveedor =================
print("=== Caso 3: entregar un cheque recibido a un proveedor, saldando su CC vieja ===")
cargo_proveedor = cc_service.registrar_cargo_manual(
    entidad_tipo="proveedor", entidad_id=proveedor["id"], monto=cheque1["monto"], fecha="2026-09-05",
    observacion="Deuda vieja con el proveedor de prueba",
)
saldo_prov_antes = cc_service.calcular_saldo_total("proveedor", proveedor["id"])
cheque1_entregado = cheques_service.entregar_a_proveedor(
    cheque_id=cheque1_id, proveedor_id=proveedor["id"],
)
saldo_prov_despues = cc_service.calcular_saldo_total("proveedor", proveedor["id"])
verificar("cheque 1 paso a 'entregado_proveedor'", cheque1_entregado["estado"] == "entregado_proveedor")
verificar("cheque 1 quedo con el proveedor correcto", cheque1_entregado["proveedor_id"] == proveedor["id"])
verificar("el saldo del proveedor bajo exactamente el monto del cheque",
          saldo_prov_antes - saldo_prov_despues == cheque1["monto"])
print()

# ================= Caso 4: cheque suelto en cartera que paga una compra NUEVA (recepcion a credito) =================
print("=== Caso 4: usar un cheque en cartera para pagar una compra nueva ===")
oc = ordenes_compra_service.crear_orden_compra(
    items=[{"producto_id": arroz["id"], "producto_nuevo": None, "descripcion_libre": None,
            "cantidad_pedida": Decimal("5"), "costo_pactado": Decimal("300")}],
    proveedor_id=proveedor["id"],
)
recepcion = recepciones_service.confirmar_recepcion(
    orden_compra_id=oc["id"],
    items=[{"orden_compra_item_id": oc["items"][0]["id"], "producto_id": arroz["id"], "producto_nuevo": None,
            "descripcion_libre": None, "cantidad_recibida": Decimal("5"), "costo_unitario": Decimal("300")}],
    a_credito=True,
)
cargo_compra_nueva = next(
    c for c in cc_service.listar_cargos("proveedor", proveedor["id"], solo_con_saldo=True)
    if c["origen"] == "recepcion"
)
cheque4 = cheques_service.recibir_de_cliente_para_cc(
    cliente_id=cliente["id"], banco="Banco Santander", librador=cliente["razon_social"],
    monto=cargo_compra_nueva["monto"], fecha_pago="2026-12-01",
)
cheque4_entregado = cheques_service.entregar_a_proveedor(
    cheque_id=cheque4["id"], proveedor_id=proveedor["id"],
    aplicaciones=[{"cargo_id": cargo_compra_nueva["id"], "monto": cargo_compra_nueva["monto"]}],
)
cargo_compra_nueva_actualizado = cc_service.obtener_cargo(cargo_compra_nueva["id"])
verificar("el cheque 4 quedo entregado al proveedor correcto",
          cheque4_entregado["estado"] == "entregado_proveedor" and cheque4_entregado["proveedor_id"] == proveedor["id"])
verificar("el cargo de la compra nueva quedo saldado",
          cargo_compra_nueva_actualizado["saldo_pendiente"] == Decimal("0"))
print()

# ================= Caso 5: cheque propio, paga una compra nueva =================
print("=== Caso 5: cheque propio para pagar una compra nueva ===")
oc2 = ordenes_compra_service.crear_orden_compra(
    items=[{"producto_id": arroz["id"], "producto_nuevo": None, "descripcion_libre": None,
            "cantidad_pedida": Decimal("3"), "costo_pactado": Decimal("250")}],
    proveedor_id=proveedor["id"],
)
recepcion2 = recepciones_service.confirmar_recepcion(
    orden_compra_id=oc2["id"],
    items=[{"orden_compra_item_id": oc2["items"][0]["id"], "producto_id": arroz["id"], "producto_nuevo": None,
            "descripcion_libre": None, "cantidad_recibida": Decimal("3"), "costo_unitario": Decimal("250")}],
    a_credito=True,
)
cargo_compra2 = next(
    c for c in cc_service.listar_cargos("proveedor", proveedor["id"], solo_con_saldo=True)
    if c["origen"] == "recepcion"
)
cheque5 = cheques_service.crear_cheque_propio_y_entregar(
    proveedor_id=proveedor["id"], banco="Banco Nacion", librador="Negocio de Dario",
    monto=cargo_compra2["monto"], fecha_pago="2026-12-10", numero="PROPIO-0001",
    aplicaciones=[{"cargo_id": cargo_compra2["id"], "monto": cargo_compra2["monto"]}],
)
verificar("cheque propio nace 'entregado_proveedor' directamente", cheque5["estado"] == "entregado_proveedor")
verificar("cheque propio origen_tipo='propio' y sin cliente_id",
          cheque5["origen_tipo"] == "propio" and cheque5["cliente_id"] is None)
cargo_compra2_actualizado = cc_service.obtener_cargo(cargo_compra2["id"])
verificar("el cargo de la compra 2 quedo saldado", cargo_compra2_actualizado["saldo_pendiente"] == Decimal("0"))
print()

# ================= Caso 6: dar de baja un cheque en cartera =================
print("=== Caso 6: dar de baja un cheque (motivo libre) ===")
cargo_para_baja = cc_service.registrar_cargo_manual(
    entidad_tipo="cliente", entidad_id=cliente["id"], monto=Decimal("1000"), fecha="2026-09-01",
    observacion="Para generar un cheque y darlo de baja",
)
cheque6 = cheques_service.recibir_de_cliente_para_cc(
    cliente_id=cliente["id"], banco="Banco Macro", librador=cliente["razon_social"],
    monto=Decimal("1000"), fecha_pago="2026-12-15",
)
cheque6_baja = cheques_service.dar_de_baja(cheque6["id"], observacion="Se lo di a un amigo para un favor")
verificar("cheque 6 paso a estado 'baja'", cheque6_baja["estado"] == "baja")
verificar("cheque 6 guardo el motivo en observacion", "amigo" in cheque6_baja["observacion"])
print()

# ================= Caso 7: rechazo de un cheque recibido_cliente en cartera =================
print("=== Caso 7: un cheque recibido rebota -- se reabre la deuda del cliente ===")
cargo_para_rechazo = cc_service.registrar_cargo_manual(
    entidad_tipo="cliente", entidad_id=cliente["id"], monto=Decimal("2000"), fecha="2026-09-01",
    observacion="Para generar un cheque que despues rebota",
)
cheque7 = cheques_service.recibir_de_cliente_para_cc(
    cliente_id=cliente["id"], banco="Banco Nacion", librador=cliente["razon_social"],
    monto=Decimal("2000"), fecha_pago="2026-12-20",
)
saldo_cliente_antes_rechazo = cc_service.calcular_saldo_total("cliente", cliente["id"])
cheque7_rechazado = cheques_service.marcar_rechazado(cheque7["id"], observacion="Rebotado por falta de fondos")
saldo_cliente_despues_rechazo = cc_service.calcular_saldo_total("cliente", cliente["id"])
verificar("cheque 7 paso a 'rechazado'", cheque7_rechazado["estado"] == "rechazado")
verificar("se genero un cargo_generado_id", cheque7_rechazado["cargo_generado_id"] is not None)
verificar("la deuda del cliente volvio a subir por el mismo monto",
          saldo_cliente_despues_rechazo - saldo_cliente_antes_rechazo == Decimal("2000"))
cargo_reabierto = cc_service.obtener_cargo(cheque7_rechazado["cargo_generado_id"])
verificar("el cargo nuevo tiene origen='cheque_rechazado' y apunta al cheque",
          cargo_reabierto["origen"] == "cheque_rechazado" and cargo_reabierto["origen_cheque_id"] == cheque7["id"])
print()

# ================= Caso 8: rechazo de un cheque propio ya entregado -- reabre deuda del negocio =================
print("=== Caso 8: un cheque propio rebota -- se reabre la deuda hacia el proveedor ===")
saldo_prov_antes_rechazo = cc_service.calcular_saldo_total("proveedor", proveedor["id"])
cheque5_rechazado = cheques_service.marcar_rechazado(cheque5["id"], observacion="No habia fondos en la cuenta")
saldo_prov_despues_rechazo = cc_service.calcular_saldo_total("proveedor", proveedor["id"])
verificar("cheque propio (5) paso a 'rechazado'", cheque5_rechazado["estado"] == "rechazado")
verificar("la deuda del negocio hacia el proveedor volvio a subir",
          saldo_prov_despues_rechazo - saldo_prov_antes_rechazo == cheque5["monto"])
print()

# ================= Caso 9: validaciones de error =================
print("=== Caso 9: validaciones de error ===")
try:
    cheques_service.entregar_a_proveedor(cheque_id=cheque1_id, proveedor_id=proveedor["id"])
    verificar("rechaza entregar un cheque que ya no esta en cartera", False)
except ChequeEstadoInvalidoError:
    verificar("rechaza entregar un cheque que ya no esta en cartera", True)

try:
    cheques_service.dar_de_baja(cheque1_id, observacion="intento invalido")
    verificar("rechaza dar de baja un cheque que ya no esta en cartera", False)
except ChequeEstadoInvalidoError:
    verificar("rechaza dar de baja un cheque que ya no esta en cartera", True)

try:
    cheques_service.marcar_rechazado(cheque6_baja["id"], observacion="ya esta de baja, no deberia poder")
    verificar("rechaza marcar como rechazado un cheque que ya esta de baja", False)
except ChequeEstadoInvalidoError:
    verificar("rechaza marcar como rechazado un cheque que ya esta de baja", True)

cheques_antes_del_error = len(cheques_service.listar_cheques())
try:
    cheques_service.recibir_de_cliente_para_cc(
        cliente_id=cliente["id"], banco="Banco Falso", librador=cliente["razon_social"],
        monto=Decimal("999999"), fecha_pago="2026-12-25",
        aplicaciones=[{"cargo_id": 999999, "monto": Decimal("999999")}],  # cargo inexistente
    )
    verificar("la compensacion deja la lista de cheques sin cambios si falla la aplicacion", False)
except Exception:
    cheques_despues_del_error = len(cheques_service.listar_cheques())
    verificar(
        "la compensacion deja la lista de cheques sin cambios si falla la aplicacion (no huerfanos)",
        cheques_despues_del_error == cheques_antes_del_error,
    )

try:
    cheques_service.recibir_de_cliente_para_cc(
        cliente_id=cliente["id"], banco="", librador=cliente["razon_social"],
        monto=Decimal("100"), fecha_pago="2026-12-25",
    )
    verificar("rechaza un cheque sin banco", False)
except ValueError:
    verificar("rechaza un cheque sin banco", True)
print()

# ================= Chequeo final: stock sin diferencias =================
print("=== Chequeo final ===")
diferencias = movimientos_service.recalcular_stock()
verificar("recalcular_stock() no encuentra diferencias", diferencias == [])

print()
if fallas:
    print(f"\n{len(fallas)} VERIFICACION(ES) FALLARON:")
    for f in fallas:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("\nTODO OK")
