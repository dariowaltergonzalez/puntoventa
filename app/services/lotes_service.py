from app.repositories import lotes_repo
from app.shared.money import entero_a_cantidad, entero_a_precio


def listar_lotes_producto(producto_id: int, solo_con_stock: bool = False) -> list[dict]:
    filas = lotes_repo.listar_por_producto_con_oc(producto_id, solo_con_stock=solo_con_stock)
    return [
        {
            "id": f["id"],
            "fecha": f["fecha"],
            "numero_oc": f["numero_oc"],
            "numero_remito": f["numero_remito"],
            "cantidad_recibida": entero_a_cantidad(f["cantidad_recibida"]),
            "cantidad_restante": entero_a_cantidad(f["cantidad_restante"]),
            "costo_unitario": entero_a_precio(f["costo_unitario"]),
        }
        for f in filas
    ]
