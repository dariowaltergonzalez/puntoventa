import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.db.connection as connection_module
from app.config import DB_PATH as DB_PATH_REAL

connection_module.DB_PATH = DB_PATH_REAL.parent / "puntoventa_test.db"

from app.services import categorias_service, clientes_service, listas_precios_service, productos_service
from app.services.exceptions import ClienteDuplicadoError, ListaPrecioDuplicadaError

# --- Clientes ---
cliente = clientes_service.crear_cliente(
    razon_social="Almacen Don Jose SRL",
    nombre_fantasia="Almacen Don Jose",
    cuit="30-12345678-9",
    telefono="1122334455",
    email="donjose@test.com",
    plazo_pago_dias=30,
    porcentaje_descuento=Decimal("5"),
    limite_credito=Decimal("50000"),
    modo_limite_credito="avisar",
    tasa_interes_mora_diaria=Decimal("0.5"),
)
print(f"Cliente creado: {cliente['razon_social']} (id={cliente['id']})")
print(f"  descuento={cliente['porcentaje_descuento']}%  limite={cliente['limite_credito']}  modo={cliente['modo_limite_credito']}  mora={cliente['tasa_interes_mora_diaria']}%/dia")

try:
    clientes_service.crear_cliente(razon_social="Almacen Don Jose SRL")
    print("FALLO: deberia haber rechazado razon social duplicada")
except ClienteDuplicadoError:
    print("OK: razon social duplicada rechazada")

cliente = clientes_service.agregar_contacto(cliente["id"], "Maria (compras)", "maria@test.com", "1155667788", "Compras", True)
cliente = clientes_service.agregar_contacto(cliente["id"], "Deposito", None, "1199887766", "Deposito", False)
print(f"Contactos: {[(c['nombre'], c['sector'], c['es_principal']) for c in cliente['contactos']]}")

# --- Listas de precios ---
mayorista = listas_precios_service.crear_lista("Mayorista", Decimal("-15"))
con_flete = listas_precios_service.crear_lista("Con flete 100km", Decimal("10"))
print(f"\nListas creadas: {mayorista['nombre']} ({mayorista['porcentaje_general']}%), {con_flete['nombre']} ({con_flete['porcentaje_general']}%)")

try:
    listas_precios_service.crear_lista("Mayorista")
    print("FALLO: deberia haber rechazado nombre duplicado")
except ListaPrecioDuplicadaError:
    print("OK: nombre de lista duplicado rechazado")

productos = productos_service.listar_productos()
categorias = categorias_service.listar_categorias()
producto_arroz = next(p for p in productos if p["codigo"] == "ARR001")
categoria_almacen = next(c for c in categorias if c["nombre"] == "Almacen")
print(f"\nProducto de prueba: {producto_arroz['codigo']} - {producto_arroz['nombre']}  precio_venta normal={producto_arroz['precio_venta']}")

# Nivel 3: solo % general
precio = listas_precios_service.calcular_precio_producto(producto_arroz["id"], mayorista["id"])
esperado = (producto_arroz["precio_venta"] * Decimal("0.85")).quantize(Decimal("1.00"))
print(f"  Solo % general (-15%): calculado={precio}  esperado={esperado}  {'OK' if precio == esperado else 'FALLO'}")

# Nivel 2: % por categoria pisa el general
listas_precios_service.establecer_porcentaje_categoria(mayorista["id"], categoria_almacen["id"], Decimal("-20"))
precio = listas_precios_service.calcular_precio_producto(producto_arroz["id"], mayorista["id"])
esperado = (producto_arroz["precio_venta"] * Decimal("0.80")).quantize(Decimal("1.00"))
print(f"  Con % de categoria (-20%): calculado={precio}  esperado={esperado}  {'OK' if precio == esperado else 'FALLO'}")

# Nivel 1: precio manual pisa todo
listas_precios_service.establecer_precio_producto(mayorista["id"], producto_arroz["id"], Decimal("999.99"))
precio = listas_precios_service.calcular_precio_producto(producto_arroz["id"], mayorista["id"])
print(f"  Con precio manual (999.99): calculado={precio}  {'OK' if precio == Decimal('999.99') else 'FALLO'}")

# Nivel 4: lista sin nada -> precio normal
lista_vacia = listas_precios_service.crear_lista("Sin nada cargado")
precio = listas_precios_service.calcular_precio_producto(producto_arroz["id"], lista_vacia["id"])
print(f"  Lista sin % general ni overrides: calculado={precio}  esperado={producto_arroz['precio_venta']}  {'OK' if precio == producto_arroz['precio_venta'] else 'FALLO'}")

# Recargo positivo (caso "con flete")
precio = listas_precios_service.calcular_precio_producto(producto_arroz["id"], con_flete["id"])
esperado = (producto_arroz["precio_venta"] * Decimal("1.10")).quantize(Decimal("1.00"))
print(f"  Recargo (+10%): calculado={precio}  esperado={esperado}  {'OK' if precio == esperado else 'FALLO'}")

# --- Asignacion de listas a cliente, con prioridad ---
cliente = clientes_service.asignar_listas_precios(cliente["id"], [mayorista["id"], con_flete["id"]])
print(f"\nListas asignadas a {cliente['razon_social']}: {[(l['nombre'], l['prioridad']) for l in cliente['listas_precios']]}")

print("\nTodo OK")
