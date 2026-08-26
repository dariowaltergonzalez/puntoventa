"""Script de verificacion manual end-to-end. Correr con: python scripts/seed_and_verify.py

Crea categorias y productos de prueba, registra movimientos (ingreso/egreso/ajuste),
prueba que un egreso que excede el stock se rechaza, y confirma que el recalculo de
stock no encuentra diferencias contra lo que ya se fue actualizando en cada movimiento.
"""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import categorias_service, movimientos_service, productos_service
from app.services.exceptions import StockInsuficienteError


def main() -> None:
    print("1. Creando categoria...")
    categoria = categorias_service.crear_categoria("Almacen")
    print(f"   OK: categoria {categoria}")

    print("2. Creando productos...")
    fideos = productos_service.crear_producto(
        codigo="FID001",
        nombre="Fideos",
        categoria_id=categoria["id"],
        unidad="kg",
        precio_costo=Decimal("17.45"),
        precio_venta=Decimal("21.00"),
    )
    print(f"   OK: producto {fideos}")

    arroz = productos_service.crear_producto(
        codigo="ARR001",
        nombre="Arroz",
        categoria_id=categoria["id"],
        unidad="kg",
        precio_costo=Decimal("10.00"),
        precio_venta=Decimal("14.50"),
    )
    print(f"   OK: producto {arroz}")

    print("3. Registrando movimientos...")
    movimientos_service.registrar_ingreso(fideos["id"], Decimal("18.500"), motivo="compra")
    movimientos_service.registrar_ingreso(arroz["id"], Decimal("50.000"), motivo="compra")
    movimientos_service.registrar_egreso(fideos["id"], Decimal("5.250"), motivo="venta")
    movimientos_service.registrar_ajuste(arroz["id"], Decimal("1.000"), tipo="egreso", observacion="rotura de bolsa")
    print("   OK: movimientos registrados")

    print("4. Probando rechazo de egreso mayor al stock disponible...")
    try:
        movimientos_service.registrar_egreso(fideos["id"], Decimal("999.000"), motivo="venta")
        print("   FALLO: se esperaba StockInsuficienteError y no se lanzo")
    except StockInsuficienteError:
        print("   OK: rechazado como se esperaba")

    print("5. Consultando stock actual...")
    stock = {p["id"]: p["stock_actual"] for p in movimientos_service.consultar_stock()}
    print(f"   stock actual: {stock}")

    print("6. Recalculando stock desde movimientos...")
    diferencias = movimientos_service.recalcular_stock()
    if diferencias:
        print(f"   ATENCION: se encontraron diferencias: {diferencias}")
    else:
        print("   OK: sin diferencias, stock_actual ya estaba consistente")

    print("\nListo. Todos los pasos se ejecutaron.")


if __name__ == "__main__":
    main()
