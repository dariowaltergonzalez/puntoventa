"""Verificacion de Datos del negocio: alta/edicion con auditoria, validaciones, cuentas
bancarias y WhatsApp (principal unica), contrasena SMTP en el administrador de credenciales
(nunca en la base) y configuracion incompleta del correo. Corre contra una COPIA de la base real
y con un nombre de credencial de prueba (no toca la contrasena real).
Correr con: python scripts/verificar_negocio.py
"""

import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.db.connection as connection_module
from app.config import DB_PATH as DB_PATH_REAL

DB_PATH_TEST = DB_PATH_REAL.parent / "puntoventa_test.db"
shutil.copyfile(DB_PATH_REAL, DB_PATH_TEST)
connection_module.DB_PATH = DB_PATH_TEST

from app.services import email_service, log_service, negocio_service
from app.services.exceptions import CorreoNoConfiguradoError, NegocioNoConfiguradoError

negocio_service._KEYRING_SERVICIO = "puntoventa-smtp-verificacion"

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


conn = connection_module.get_connection()
for tabla in ("negocio_whatsapp", "negocio_cuentas_bancarias", "negocio"):
    conn.execute(f"DELETE FROM {tabla}")
conn.close()

print("=== Identidad ===")
verificar("sin datos cargados, obtener_negocio devuelve None", negocio_service.obtener_negocio() is None)
verificar("no se puede agregar una cuenta sin datos del negocio",
          lanza(NegocioNoConfiguradoError, negocio_service.agregar_cuenta_bancaria, "Nacion"))
verificar("razon social obligatoria", lanza(ValueError, negocio_service.guardar_negocio, "  ", "20-12345678-9"))
verificar("CUIT con 11 digitos", lanza(ValueError, negocio_service.guardar_negocio, "Juan Perez", "20-123"))
verificar("email invalido", lanza(ValueError, negocio_service.guardar_negocio, "Juan Perez", "20-12345678-9",
                                  email="no-es-mail"))
negocio = negocio_service.guardar_negocio("Juan Perez", "20-12345678-9", nombre_fantasia="Todo Limpio")
verificar("se guardan los datos", negocio["razon_social"] == "Juan Perez" and negocio["nombre_fantasia"] == "Todo Limpio")
negocio_service.guardar_negocio("Juan Perez", "20-12345678-9", nombre_fantasia="Todo Limpio SRL")
eventos = [e["descripcion"] for e in log_service.listar_eventos(entidad="negocio", limite=5)]
verificar("el cambio queda en el historial campo por campo",
          any("nombre_fantasia" in d and "Todo Limpio SRL" in d for d in eventos))
print()

print("=== Cuentas bancarias ===")
c1 = negocio_service.agregar_cuenta_bancaria("Nacion", cbu="0110012345678901234567")
verificar("titular y CUIT vacios toman los del negocio", c1["titular"] == "Juan Perez" and c1["cuit_titular"] == "20-12345678-9")
verificar("la primera cuenta queda como principal", c1["es_principal"])
verificar("CBU con 22 digitos", lanza(ValueError, negocio_service.agregar_cuenta_bancaria, "Galicia", cbu="123"))
c2 = negocio_service.agregar_cuenta_bancaria("Galicia", titular="Ana Gomez", cuit_titular="27-87654321-0", es_principal=True)
cuentas = {c["id"]: c for c in negocio_service.listar_cuentas_bancarias()}
verificar("marcar otra como principal desmarca la anterior",
          cuentas[c2["id"]]["es_principal"] and not cuentas[c1["id"]]["es_principal"])
negocio_service.quitar_cuenta_bancaria(c2["id"])
verificar("al quitar la principal, la que queda pasa a principal",
          negocio_service.listar_cuentas_bancarias()[0]["es_principal"])
print()

print("=== WhatsApp ===")
w = negocio_service.agregar_whatsapp("11 2233-4455", "Ventas")
verificar("numero local se normaliza a formato internacional", w["numero"] == "5491122334455")
verificar("link wa.me", w["link"] == "https://wa.me/5491122334455")
verificar("+54 9 11 ... tambien se normaliza", negocio_service.normalizar_whatsapp("+54 9 11 2233-4455") == "5491122334455")
verificar("numero invalido", lanza(ValueError, negocio_service.agregar_whatsapp, "123"))
print()

print("=== Correo ===")
verificar("sin SMTP configurado, enviar falla con mensaje claro",
          lanza(CorreoNoConfiguradoError, email_service.enviar_mail_de_prueba))
negocio_service.guardar_negocio("Juan Perez", "20-12345678-9", smtp_servidor="smtp.gmail.com", smtp_puerto=587,
                                smtp_seguridad="starttls", smtp_usuario="x@gmail.com", smtp_remitente_email="x@gmail.com")
verificar("puerto fuera de rango", lanza(ValueError, negocio_service.guardar_negocio, "Juan Perez", "20-12345678-9",
                                          smtp_puerto=70000))
negocio_service.guardar_password_smtp("secreto-de-prueba")
verificar("la contrasena se recupera del administrador de credenciales",
          negocio_service.obtener_password_smtp() == "secreto-de-prueba")
verificar("obtener_negocio informa que hay contrasena", negocio_service.obtener_negocio()["smtp_tiene_password"])
crudo = sqlite3.connect(DB_PATH_TEST)
volcado = "\n".join(crudo.iterdump())
crudo.close()
verificar("la contrasena NO esta en ningun lado de la base", "secreto-de-prueba" not in volcado)
negocio_service.guardar_password_smtp(None)
verificar("se puede borrar la contrasena", negocio_service.obtener_password_smtp() is None)
print()

print("=" * 60)
if fallas:
    print(f"{len(fallas)} verificaciones FALLARON:")
    for f in fallas:
        print(f"  - {f}")
    sys.exit(1)
print("Todas las verificaciones OK")
