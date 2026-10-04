"""Carga datos basicos de prueba (categorias, proveedores, clientes, medios de pago,
productos y stock inicial) para poder seguir probando la app con datos reales.

Correr con: python scripts/seed_datos_basicos.py

Idempotente a nivel de "no rompe" si se corre dos veces: los duplicados por nombre/
razon social/codigo son detectados por las excepciones de dominio y simplemente se
omiten (se reusa el registro existente), no se duplican filas.
"""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import (
    categorias_service,
    clientes_service,
    condiciones_iva_service,
    medios_pago_service,
    movimientos_service,
    productos_service,
    proveedores_service,
)
from app.services.exceptions import (
    ClienteDuplicadoError,
    CodigoDuplicadoError,
    ProveedorDuplicadoError,
)


def _obtener_o_crear_categoria(nombre: str) -> dict:
    for cat in categorias_service.listar_categorias():
        if cat["nombre"] == nombre:
            return cat
    return categorias_service.crear_categoria(nombre)


def _crear_proveedor_seguro(**kwargs) -> dict:
    try:
        return proveedores_service.crear_proveedor(**kwargs)
    except ProveedorDuplicadoError:
        for p in proveedores_service.listar_proveedores():
            if p["nombre"] == kwargs["nombre"]:
                return p
        raise


def _crear_cliente_seguro(**kwargs) -> dict:
    try:
        return clientes_service.crear_cliente(**kwargs)
    except ClienteDuplicadoError:
        for c in clientes_service.listar_clientes():
            if c["razon_social"] == kwargs["razon_social"]:
                return c
        raise


def _crear_producto_seguro(**kwargs) -> dict:
    try:
        return productos_service.crear_producto(**kwargs)
    except CodigoDuplicadoError:
        existente = productos_service.obtener_producto_por_codigo(kwargs["codigo"])
        if existente:
            return existente
        raise


def main() -> None:
    print("1. Condiciones IVA (ya vienen precargadas por el schema)...")
    condiciones = {c["nombre"]: c["id"] for c in condiciones_iva_service.listar_condiciones_iva()}
    print(f"   OK: {condiciones}")

    print("2. Creando categorias...")
    cat_limpieza = _obtener_o_crear_categoria("Limpieza")
    cat_perfumeria = _obtener_o_crear_categoria("Perfumeria")
    cat_descartables = _obtener_o_crear_categoria("Descartables")
    print(f"   OK: {cat_limpieza['nombre']}, {cat_perfumeria['nombre']}, {cat_descartables['nombre']}")

    print("3. Creando proveedores...")
    prov_distrilimp = _crear_proveedor_seguro(
        nombre="Distribuidora Limpieza SA",
        cuit="30-71234567-8",
        contacto="Marcela Fernandez",
        telefono="011-4555-1234",
        email="ventas@distrilimp.com.ar",
        direccion="Av. Mitre 2450, San Martin",
    )
    prov_quimicasur = _crear_proveedor_seguro(
        nombre="Quimica del Sur SRL",
        cuit="30-70987654-3",
        contacto="Jorge Benitez",
        telefono="011-4777-5678",
        email="pedidos@quimicadelsur.com.ar",
        direccion="Ruta 8 Km 45, Pilar",
    )
    prov_mayohogar = _crear_proveedor_seguro(
        nombre="Mayorista Hogar",
        cuit="30-69876543-1",
        contacto="Laura Gimenez",
        telefono="011-4333-9012",
        email="contacto@mayoristahogar.com.ar",
    )
    print(f"   OK: {prov_distrilimp['nombre']}, {prov_quimicasur['nombre']}, {prov_mayohogar['nombre']}")

    print("4. Creando medios de pago...")
    medios_existentes = {m["nombre"] for m in medios_pago_service.listar_medios_pago()}
    medios_a_crear = [
        ("Efectivo", False),
        ("Tarjeta de debito", False),
        ("Tarjeta de credito", False),
        ("Transferencia", False),
        ("Cuenta corriente", True),
    ]
    for nombre, es_cc in medios_a_crear:
        if nombre not in medios_existentes:
            medios_pago_service.crear_medio_pago(nombre, es_cuenta_corriente=es_cc)
    print(f"   OK: {[n for n, _ in medios_a_crear]}")

    print("5. Creando clientes...")
    cli_generico = clientes_service.obtener_o_crear_cliente_generico()
    cli_perez = _crear_cliente_seguro(
        razon_social="Perez, Juan",
        dni="28456123",
        telefono="011-15-4321-0001",
        email="juanperez@gmail.com",
        direccion="Calle Falsa 123",
        ciudad="San Martin",
        provincia="Buenos Aires",
        condicion_iva_id=condiciones.get("Consumidor Final"),
    )
    cli_limpihogar = _crear_cliente_seguro(
        razon_social="Limpihogar SRL",
        cuit="30-65412378-9",
        contacto_principal="Sandra Lopez",
        telefono="011-15-4321-0002",
        email="compras@limpihogar.com.ar",
        direccion="Av. Rivadavia 5600",
        ciudad="CABA",
        provincia="CABA",
        condicion_iva_id=condiciones.get("Responsable Inscripto"),
        plazo_pago_dias=30,
        limite_credito=Decimal("50000.00"),
        avisar_limite_credito=True,
    )
    cli_gonzalez = _crear_cliente_seguro(
        razon_social="Gonzalez, Maria",
        dni="30112233",
        telefono="011-15-4321-0003",
        condicion_iva_id=condiciones.get("Monotributista"),
    )
    print(f"   OK: {cli_generico['razon_social']}, {cli_perez['razon_social']}, {cli_limpihogar['razon_social']}, {cli_gonzalez['razon_social']}")

    print("6. Creando productos...")
    productos_data = [
        dict(codigo="LAV001", nombre="Lavandina 1L", categoria_id=cat_limpieza["id"], unidad="un",
             precio_costo=Decimal("450.00"), precio_venta=Decimal("690.00"), stock_minimo=Decimal("10"),
             marca="Ayudin", proveedor_id=prov_distrilimp["id"]),
        dict(codigo="DET001", nombre="Detergente 750ml", categoria_id=cat_limpieza["id"], unidad="un",
             precio_costo=Decimal("680.00"), precio_venta=Decimal("990.00"), stock_minimo=Decimal("10"),
             marca="Magistral", proveedor_id=prov_distrilimp["id"]),
        dict(codigo="DES001", nombre="Desodorante de ambiente", categoria_id=cat_perfumeria["id"], unidad="un",
             precio_costo=Decimal("1200.00"), precio_venta=Decimal("1850.00"), stock_minimo=Decimal("5"),
             marca="Poett", proveedor_id=prov_quimicasur["id"]),
        dict(codigo="JAB001", nombre="Jabon en polvo 3kg", categoria_id=cat_limpieza["id"], unidad="un",
             precio_costo=Decimal("3200.00"), precio_venta=Decimal("4650.00"), stock_minimo=Decimal("5"),
             marca="Skip", proveedor_id=prov_quimicasur["id"]),
        dict(codigo="SRV001", nombre="Servilletas x50", categoria_id=cat_descartables["id"], unidad="un",
             precio_costo=Decimal("350.00"), precio_venta=Decimal("520.00"), stock_minimo=Decimal("15"),
             marca="Elite", proveedor_id=prov_mayohogar["id"]),
        dict(codigo="GUA001", nombre="Guantes de latex caja x100", categoria_id=cat_descartables["id"], unidad="un",
             precio_costo=Decimal("2800.00"), precio_venta=Decimal("4200.00"), stock_minimo=Decimal("3"),
             marca="Virtus", proveedor_id=prov_mayohogar["id"]),
        dict(codigo="TRA001", nombre="Bolsas de residuo 50x60 x10", categoria_id=cat_descartables["id"], unidad="un",
             precio_costo=Decimal("520.00"), precio_venta=Decimal("780.00"), stock_minimo=Decimal("10"),
             marca="Plastar", proveedor_id=prov_distrilimp["id"]),
        dict(codigo="PER001", nombre="Perfumina para pisos 500ml", categoria_id=cat_perfumeria["id"], unidad="un",
             precio_costo=Decimal("890.00"), precio_venta=Decimal("1350.00"), stock_minimo=Decimal("8"),
             marca="Ayudin", proveedor_id=prov_quimicasur["id"]),
    ]
    productos_creados = [_crear_producto_seguro(**datos) for datos in productos_data]
    for p in productos_creados:
        print(f"   OK: {p['codigo']} - {p['nombre']}")

    print("7. Cargando stock inicial (ingreso por compra)...")
    cantidades_iniciales = [30, 25, 15, 10, 40, 8, 20, 12]
    for producto, cantidad in zip(productos_creados, cantidades_iniciales):
        if producto["stock_actual"] == 0:
            movimientos_service.registrar_ingreso(
                producto["id"], Decimal(cantidad), motivo="carga inicial de stock (seed)"
            )
    print("   OK: stock inicial cargado")

    print("8. Verificando consistencia de stock...")
    diferencias = movimientos_service.recalcular_stock()
    if diferencias:
        print(f"   ATENCION: diferencias encontradas: {diferencias}")
    else:
        print("   OK: stock consistente")

    print("\nListo. Datos basicos cargados:")
    print(f"  - {len(categorias_service.listar_categorias())} categorias")
    print(f"  - {len(proveedores_service.listar_proveedores())} proveedores")
    print(f"  - {len(clientes_service.listar_clientes())} clientes")
    print(f"  - {len(medios_pago_service.listar_medios_pago())} medios de pago")
    print(f"  - {len(productos_service.listar_productos())} productos")


if __name__ == "__main__":
    main()
