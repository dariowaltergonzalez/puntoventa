"""Verificacion de gastos del negocio: IVA (RI: cuenta el neto; monotributo: el total; cada gasto
congela su condicion), editar con historial, anular (deja de sumar), validaciones, comprobantes
adjuntos, categorias, y el impacto en Ganancias (resultado - gastos = ganancia neta). Corre contra
una COPIA de la base real; los comprobantes van a una carpeta temporal.
Correr con: python scripts/verificar_gastos.py
"""

import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.db.connection as connection_module
from app.config import DB_PATH as DB_PATH_REAL

DB_PATH_TEST = DB_PATH_REAL.parent / "puntoventa_test.db"
for sufijo in ("", "-wal", "-shm"):
    Path(f"{DB_PATH_TEST}{sufijo}").unlink(missing_ok=True)
origen = sqlite3.connect(DB_PATH_REAL)
destino = sqlite3.connect(DB_PATH_TEST)
origen.backup(destino)
destino.close()
origen.close()
connection_module.DB_PATH = DB_PATH_TEST

from app.repositories import gastos_repo
from app.services import condiciones_iva_service, ganancias_service, gastos_service, log_service, negocio_service
from app.services.exceptions import GastoNoEncontradoError

CARPETA_PRUEBA = Path(tempfile.mkdtemp(prefix="comprobantes_prueba_"))
gastos_repo.carpeta_comprobantes = lambda: CARPETA_PRUEBA

fallas = []
D = Decimal
HOY = date.today().isoformat()


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


def configurar(condicion: str) -> None:
    ids = {c["nombre"]: c["id"] for c in condiciones_iva_service.listar_condiciones_iva()}
    negocio_service.guardar_negocio("Negocio", "20-12345678-9", condicion_iva_id=ids[condicion])


categorias = {c["nombre"]: c["id"] for c in gastos_service.listar_categorias()}
# La copia puede traer gastos de hoy cargados a mano: las cuentas de abajo se miden sobre lo que ya habia.
previo = gastos_service.resumen(date.today(), date.today())
previo_por_categoria = {c["categoria"]: c["gasto"] for c in previo["por_categoria"]}
print("=== Categorias ===")
verificar("vienen las 8 precargadas", {"Alquiler", "Sueldos", "Servicios", "Automotor", "Impositivos", "Bancarios",
                                       "Insumos del local", "Otros"} <= set(categorias))
nueva = gastos_service.crear_categoria("Publicidad")
verificar("se puede crear una nueva", nueva["nombre"] == "Publicidad")
verificar("no se duplica (sin importar mayusculas)", lanza(ValueError, gastos_service.crear_categoria, "publicidad"))
print()

print("=== IVA ===")
configurar("Responsable Inscripto")
nafta = gastos_service.crear_gasto(HOY, "Nafta camioneta", categorias["Automotor"], D("60500"), D("21"), proveedor="YPF")
verificar("RI: 60.500 con 21% = neto 50.000 + IVA 10.500, cuenta como gasto 50.000",
          nafta["neto"] == D("50000") and nafta["iva"] == D("10500") and nafta["gasto"] == D("50000"))
alquiler = gastos_service.crear_gasto(HOY, "Alquiler del local", categorias["Alquiler"], D("350000"))
verificar("sin IVA: todo es gasto (350.000)", alquiler["gasto"] == D("350000") and alquiler["iva"] == 0)
luz = gastos_service.crear_gasto(HOY, "Luz", categorias["Servicios"], D("50800"), D("27"))
verificar("27%: 50.800 = neto 40.000 + IVA 10.800", luz["neto"] == D("40000") and luz["iva"] == D("10800"))
configurar("Monotributista")
nafta_mono = gastos_service.crear_gasto(HOY, "Nafta (monotributo)", categorias["Automotor"], D("60500"), D("21"))
verificar("monotributo: el IVA no se recupera, cuenta los 60.500", nafta_mono["gasto"] == D("60500"))
configurar("Responsable Inscripto")
verificar("cambiar la config no altera gastos viejos (sigue 60.500)",
          gastos_service.obtener_gasto(nafta_mono["id"])["gasto"] == D("60500"))
print()

print("=== Editar y anular ===")
editado = gastos_service.editar_gasto(nafta["id"], HOY, "Nafta camioneta", categorias["Automotor"], D("72600"), D("21"),
                                      proveedor="YPF")
verificar("editar: nuevo monto, neto 60.000", editado["monto_total"] == D("72600") and editado["neto"] == D("60000"))
eventos = [e["descripcion"] for e in log_service.listar_eventos(entidad="gasto", limite=10)]
verificar("el cambio queda en el Historial", any("monto_total" in e and "72.600,00" in e for e in eventos))
antes = gastos_service.resumen(date.today(), date.today())
gastos_service.anular_gasto(luz["id"], "Era de otro mes")
despues = gastos_service.resumen(date.today(), date.today())
verificar("anular: deja de sumar (resta los 40.000 de la luz)", despues["gastos"] == antes["gastos"] - D("40000"))
verificar("anulado sigue en la lista, marcado", any(g["id"] == luz["id"] and g["anulado"]
                                                     for g in gastos_service.listar_gastos(date.today(), date.today())))
verificar("un anulado no se edita",
          lanza(GastoNoEncontradoError, gastos_service.editar_gasto, luz["id"], HOY, "x", categorias["Otros"], D("1")))
print()

print("=== Validaciones ===")
manana = (date.today() + timedelta(days=1)).isoformat()
verificar("fecha futura", lanza(ValueError, gastos_service.crear_gasto, manana, "x", categorias["Otros"], D("10")))
verificar("monto cero", lanza(ValueError, gastos_service.crear_gasto, HOY, "x", categorias["Otros"], D("0")))
verificar("alicuota invalida (15%)", lanza(ValueError, gastos_service.crear_gasto, HOY, "x", categorias["Otros"], D("10"), D("15")))
verificar("sin descripcion", lanza(ValueError, gastos_service.crear_gasto, HOY, "  ", categorias["Otros"], D("10")))
print()

print("=== Comprobantes ===")
ticket = CARPETA_PRUEBA.parent / "ticket_prueba.jpg"
ticket.write_bytes(b"imagen de prueba")
con_ticket = gastos_service.adjuntar_comprobante(nafta["id"], str(ticket))
verificar("se copia a la carpeta de comprobantes con el id adelante",
          Path(con_ticket["comprobante"]).is_file() and Path(con_ticket["comprobante"]).name == f"gasto_{nafta['id']}_ticket_prueba.jpg")
texto = CARPETA_PRUEBA.parent / "nota.txt"
texto.write_text("x")
verificar("solo fotos o PDF", lanza(ValueError, gastos_service.adjuntar_comprobante, nafta["id"], str(texto)))
print()

print("=== Ganancias ===")
r = ganancias_service.resumen(date.today(), date.today())
g = gastos_service.resumen(date.today(), date.today())
verificar(f"gastos en Ganancias = los de la pantalla ({g['gastos']})", r["gastos"] == g["gastos"])
verificar("ganancia neta = resultado de la mercaderia - gastos", r["ganancia_neta"] == r["resultado"] - r["gastos"])
esperado = D("60000") + D("350000") + D("60500")
verificar(f"gastos del dia a mano: lo que ya habia + 60.000 + 350.000 + 60.500 = {esperado}",
          g["gastos"] == previo["gastos"] + esperado)
montos = [c["gasto"] for c in g["por_categoria"]]
por_categoria = {c["categoria"]: c["gasto"] for c in g["por_categoria"]}
verificar("por categoria, de mayor a menor (Automotor suma 60.000 + 60.500)",
          montos == sorted(montos, reverse=True)
          and por_categoria["Automotor"] == previo_por_categoria.get("Automotor", D("0")) + D("120500"))
print()

print("=" * 60)
if fallas:
    print(f"{len(fallas)} verificaciones FALLARON:")
    for f in fallas:
        print(f"  - {f}")
    sys.exit(1)
print("Todas las verificaciones OK")
