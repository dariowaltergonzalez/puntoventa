"""Prueba manual de la capa de repositorio de Fase 1 (OC) contra una COPIA de la base real.
Correr con: python scripts/verificar_repos_oc.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.db.connection as connection_module
from app.config import DB_PATH as DB_PATH_REAL

DB_COPIA = DB_PATH_REAL.parent / "puntoventa_test.db"
connection_module.DB_PATH = DB_COPIA

from app.repositories import ordenes_compra_repo, productos_repo, proveedores_repo, recepciones_repo


def main():
    print("1. Auto-alta de proveedor idempotente...")
    p1 = proveedores_repo.obtener_o_crear_por_nombre("MercadoLibre")
    p2 = proveedores_repo.obtener_o_crear_por_nombre("MercadoLibre")
    assert p1["id"] == p2["id"], "deberia devolver el mismo id la segunda vez"
    print(f"   OK: proveedor id={p1['id']} (mismo en ambas llamadas)")

    print("2. Producto existente para usar en la OC...")
    productos = productos_repo.listar()
    producto_existente = productos[0]
    stock_antes = producto_existente["stock_actual"]
    print(f"   Usando producto '{producto_existente['nombre']}' (id={producto_existente['id']}, stock_actual={stock_antes})")

    print("3. Crear OC con 2 lineas (producto existente + item libre 'Flete')...")
    oc = ordenes_compra_repo.crear(
        proveedor_id=p1["id"],
        fecha_creacion="2026-09-01T10:00:00",
        fecha_estimada=None,
        iva_porcentaje=21,
        observacion="OC de prueba",
        items=[
            {"producto_id": producto_existente["id"], "descripcion_libre": None, "cantidad_pedida": 10000, "costo_pactado": 500},
            {"producto_id": None, "descripcion_libre": "Flete", "cantidad_pedida": 1000, "costo_pactado": 2000},
        ],
    )
    print(f"   OK: OC creada {oc}")

    oc_fila = ordenes_compra_repo.obtener_por_id(oc["id"])
    assert oc_fila["estado"] == "pendiente"
    print(f"   OK: estado inicial = {oc_fila['estado']}")

    items_oc = ordenes_compra_repo.listar_items(oc["id"])
    item_producto = next(i for i in items_oc if i["producto_id"] is not None)
    item_libre = next(i for i in items_oc if i["producto_id"] is None)

    print("4. Confirmar recepcion PARCIAL: mitad del producto existente + producto nuevo + el item libre completo...")
    resultado = recepciones_repo.confirmar_recepcion(
        orden_compra_id=oc["id"],
        fecha="2026-09-01T11:00:00",
        numero_remito="R-0001",
        observacion="Primera entrega parcial",
        items=[
            {
                "orden_compra_item_id": item_producto["id"], "producto_id": producto_existente["id"],
                "producto_nuevo": None, "descripcion_libre": None,
                "cantidad_recibida": 5000, "costo_unitario": 520,
            },
            {
                "orden_compra_item_id": None, "producto_id": None,
                "producto_nuevo": {"codigo": "TESTNUEVO001", "nombre": "Producto nuevo de prueba", "categoria_id": None},
                "descripcion_libre": None,
                "cantidad_recibida": 3000, "costo_unitario": 800,
            },
            {
                "orden_compra_item_id": item_libre["id"], "producto_id": None,
                "producto_nuevo": None, "descripcion_libre": "Flete",
                "cantidad_recibida": 1000, "costo_unitario": 2000,
            },
        ],
    )
    print(f"   OK: recepcion aplicada {resultado}")
    assert resultado["estado_orden_compra"] == "recibida_parcial", f"esperaba recibida_parcial, dio {resultado['estado_orden_compra']}"
    print("   OK: estado = recibida_parcial (correcto, quedo la mitad del producto existente sin llegar)")

    producto_nuevo_id = resultado["productos_creados"][0]
    producto_nuevo = productos_repo.obtener_por_id(producto_nuevo_id)
    print(f"   OK: producto nuevo creado: {producto_nuevo['codigo']} - {producto_nuevo['nombre']}, "
          f"categoria_id={producto_nuevo['categoria_id']}, stock_actual={producto_nuevo['stock_actual']}, "
          f"precio_costo={producto_nuevo['precio_costo']}")
    assert producto_nuevo["stock_actual"] == 3000
    assert producto_nuevo["precio_costo"] == 800

    producto_existente_actualizado = productos_repo.obtener_por_id(producto_existente["id"])
    print(f"   Stock del producto existente: antes={stock_antes}, ahora={producto_existente_actualizado['stock_actual']}")
    assert producto_existente_actualizado["stock_actual"] == stock_antes + 5000

    print("5. Confirmar recepcion del resto del producto existente (debe pasar a 'recibida')...")
    items_oc_actualizados = ordenes_compra_repo.listar_items(oc["id"])
    item_producto_actualizado = next(i for i in items_oc_actualizados if i["id"] == item_producto["id"])
    pendiente = item_producto_actualizado["cantidad_pedida"] - item_producto_actualizado["cantidad_recibida"]
    print(f"   Pendiente de recibir del producto existente: {pendiente}")

    resultado2 = recepciones_repo.confirmar_recepcion(
        orden_compra_id=oc["id"],
        fecha="2026-09-02T09:00:00",
        numero_remito=None,
        observacion="Segunda entrega, completa el resto",
        items=[
            {
                "orden_compra_item_id": item_producto["id"], "producto_id": producto_existente["id"],
                "producto_nuevo": None, "descripcion_libre": None,
                "cantidad_recibida": pendiente, "costo_unitario": 520,
            },
        ],
    )
    print(f"   OK: {resultado2}")
    assert resultado2["estado_orden_compra"] == "recibida", f"esperaba recibida, dio {resultado2['estado_orden_compra']}"
    print("   OK: estado final = recibida")

    print("6. Probar crear_con_recepcion_inmediata (checkbox 'ya la tenes en mano')...")
    resultado3 = ordenes_compra_repo.crear_con_recepcion_inmediata(
        proveedor_id=p1["id"],
        fecha_creacion="2026-09-02T15:00:00",
        fecha_estimada=None,
        iva_porcentaje=None,
        observacion="Compra directa",
        items=[{"producto_id": producto_existente["id"], "descripcion_libre": None, "cantidad_pedida": 2000, "costo_pactado": 500}],
        recepcion_fecha="2026-09-02T15:00:00",
        recepcion_numero_remito=None,
        recepcion_observacion=None,
        items_recepcion=[
            {"producto_id": producto_existente["id"], "producto_nuevo": None,
             "descripcion_libre": None, "cantidad_recibida": 2000, "costo_unitario": 500},
        ],
    )
    print(f"   OK: {resultado3}")
    assert resultado3["estado_orden_compra"] == "recibida"
    print("   OK: OC nacio directo en estado 'recibida'")

    print("\nTodos los tests de repositorio pasaron correctamente.")


if __name__ == "__main__":
    main()
