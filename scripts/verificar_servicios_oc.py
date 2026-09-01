"""Prueba manual de la capa de servicios de Fase 1 (OC) contra una COPIA de la base real.
Correr con: python scripts/verificar_servicios_oc.py
"""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.db.connection as connection_module
from app.config import DB_PATH as DB_PATH_REAL

DB_COPIA = DB_PATH_REAL.parent / "puntoventa_test.db"
connection_module.DB_PATH = DB_COPIA

from app.services import log_service, ordenes_compra_service, productos_service
from app.services.exceptions import LineasVaciasError, OrdenCompraNoEditableError


def main():
    productos = productos_service.listar_productos()
    producto = productos[0]
    print(f"Usando producto '{producto['nombre']}' (id={producto['id']})")

    print("1. LineasVaciasError con OC sin lineas...")
    try:
        ordenes_compra_service.crear_orden_compra(items=[], usar_proveedor_generico=True)
        print("   FALLO: no lanzo LineasVaciasError")
    except LineasVaciasError:
        print("   OK: rechazado como se esperaba")

    print("2. Crear OC con proveedor generico, item de catalogo, item libre, e IVA...")
    oc = ordenes_compra_service.crear_orden_compra(
        items=[
            {"producto_id": producto["id"], "descripcion_libre": None, "cantidad_pedida": Decimal("10"), "costo_pactado": Decimal("5.00")},
            {"producto_id": None, "descripcion_libre": "Flete", "cantidad_pedida": Decimal("1"), "costo_pactado": Decimal("20.00")},
        ],
        usar_proveedor_generico=True,
        iva_porcentaje=Decimal("21"),
        observacion="OC de prueba de servicios",
    )
    print(f"   OK: {oc['numero']}, estado={oc['estado']}, total_estimado={oc['total_estimado']}, iva={oc['iva_porcentaje']}")
    assert oc["total_estimado"] == Decimal("70.00"), f"esperaba 70.00 (10*5 + 1*20), dio {oc['total_estimado']}"

    print("3. Editar la OC mientras esta pendiente sin recepciones (debe funcionar)...")
    oc_editada = ordenes_compra_service.actualizar_orden_compra(
        orden_compra_id=oc["id"],
        items=[
            {"producto_id": producto["id"], "descripcion_libre": None, "cantidad_pedida": Decimal("15"), "costo_pactado": Decimal("5.00")},
        ],
        usar_proveedor_generico=True,
        observacion="Edite la orden",
    )
    print(f"   OK: editada, ahora {len(oc_editada['items'])} linea(s), total_estimado={oc_editada['total_estimado']}")

    print("4. Confirmar una recepcion (con un producto nuevo SIN categoria elegida -> placeholder)...")
    items_oc = oc_editada["items"]
    item_id = items_oc[0]["id"]
    recepcion = ordenes_compra_service.__dict__  # solo para forzar import ya hecho
    from app.services import recepciones_service
    rec = recepciones_service.confirmar_recepcion(
        orden_compra_id=oc["id"],
        items=[
            {"orden_compra_item_id": item_id, "producto_id": producto["id"], "producto_nuevo": None,
             "descripcion_libre": None, "cantidad_recibida": Decimal("15"), "costo_unitario": Decimal("5.20")},
            {"orden_compra_item_id": None, "producto_id": None,
             "producto_nuevo": {"codigo": "SVCTEST001", "nombre": "Producto via servicio", "categoria_id": None},
             "descripcion_libre": None, "cantidad_recibida": Decimal("2"), "costo_unitario": Decimal("9.99")},
        ],
        numero_remito="R-9999",
    )
    print(f"   OK: recepcion {rec['id']} confirmada")

    print("5. La OC ya no se puede editar (tiene una recepcion)...")
    try:
        ordenes_compra_service.actualizar_orden_compra(
            orden_compra_id=oc["id"],
            items=[{"producto_id": producto["id"], "descripcion_libre": None, "cantidad_pedida": Decimal("1"), "costo_pactado": Decimal("1")}],
            usar_proveedor_generico=True,
        )
        print("   FALLO: no lanzo OrdenCompraNoEditableError")
    except OrdenCompraNoEditableError:
        print("   OK: rechazado como se esperaba")

    oc_actual = ordenes_compra_service.obtener_orden_compra(oc["id"])
    print(f"   Estado actual de la OC: {oc_actual['estado']}")
    assert oc_actual["estado"] == "recibida", f"esperaba recibida (15/15 recibido), dio {oc_actual['estado']}"

    print("6. Cancelacion: no se puede cancelar una OC ya en 'recibida' salvo que se use marcar_recibida_manualmente...")
    print("   (se prueba cancelacion sobre una OC nueva sin recepciones)")
    oc2 = ordenes_compra_service.crear_orden_compra(
        items=[{"producto_id": producto["id"], "descripcion_libre": None, "cantidad_pedida": Decimal("5"), "costo_pactado": Decimal("1")}],
        usar_proveedor_generico=True,
    )
    oc2_cancelada = ordenes_compra_service.cancelar_orden_compra(oc2["id"], "Me arrepenti, no hace falta")
    print(f"   OK: OC {oc2_cancelada['numero']} estado={oc2_cancelada['estado']}")
    assert oc2_cancelada["estado"] == "cancelada"

    print("7. Cancelacion con recepcion parcial ya hecha...")
    oc3 = ordenes_compra_service.crear_orden_compra(
        items=[{"producto_id": producto["id"], "descripcion_libre": None, "cantidad_pedida": Decimal("20"), "costo_pactado": Decimal("1")}],
        usar_proveedor_generico=True,
    )
    item_oc3 = oc3["items"][0]["id"]
    recepciones_service.confirmar_recepcion(
        orden_compra_id=oc3["id"],
        items=[{"orden_compra_item_id": item_oc3, "producto_id": producto["id"], "producto_nuevo": None,
                "descripcion_libre": None, "cantidad_recibida": Decimal("8"), "costo_unitario": Decimal("1")}],
    )
    oc3_parcial = ordenes_compra_service.obtener_orden_compra(oc3["id"])
    assert oc3_parcial["estado"] == "recibida_parcial"
    print(f"   OK: OC en recibida_parcial, cancelo el saldo pendiente...")
    oc3_cancelada = ordenes_compra_service.cancelar_orden_compra(oc3["id"], "El proveedor no tiene mas stock")
    print(f"   OK: {oc3_cancelada['numero']} ahora estado={oc3_cancelada['estado']}")
    assert oc3_cancelada["estado"] == "cancelada"

    print("8. Cierre manual solo permitido en 'recibida_parcial'...")
    oc4 = ordenes_compra_service.crear_orden_compra(
        items=[{"producto_id": producto["id"], "descripcion_libre": None, "cantidad_pedida": Decimal("20"), "costo_pactado": Decimal("1")}],
        usar_proveedor_generico=True,
    )
    try:
        ordenes_compra_service.marcar_recibida_manualmente(oc4["id"], "no debería andar, esta pendiente")
        print("   FALLO: dejo cerrar manualmente una OC pendiente sin recepciones")
    except ValueError:
        print("   OK: rechazado (esta 'pendiente', no 'recibida_parcial')")

    item_oc4 = oc4["items"][0]["id"]
    recepciones_service.confirmar_recepcion(
        orden_compra_id=oc4["id"],
        items=[{"orden_compra_item_id": item_oc4, "producto_id": producto["id"], "producto_nuevo": None,
                "descripcion_libre": None, "cantidad_recibida": Decimal("5"), "costo_unitario": Decimal("1")}],
    )
    oc4_cerrada = ordenes_compra_service.marcar_recibida_manualmente(oc4["id"], "El resto no va a llegar")
    print(f"   OK: cierre manual funciono, estado={oc4_cerrada['estado']}")
    assert oc4_cerrada["estado"] == "recibida"

    print("9. Verificando que todo quedo en el log de auditoria...")
    eventos = log_service.listar_eventos(entidad="orden_compra")
    print(f"   OK: {len(eventos)} eventos de tipo 'orden_compra' en el log")
    assert len(eventos) >= 6

    print("\nTodos los tests de servicios pasaron correctamente.")


if __name__ == "__main__":
    main()
