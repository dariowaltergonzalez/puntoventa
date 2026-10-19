# Punto de Venta

App de escritorio (Python + Flet + SQLite) para un negocio de artículos de limpieza.

- Qué hace y qué falta: [`docs/plan.md`](docs/plan.md)
- Cómo está construida (convenciones de código): [`CLAUDE.md`](CLAUDE.md)

## Poner en marcha en otra PC (o después de un `git pull`)

Todos los comandos van en PowerShell, desde la carpeta del proyecto.

**La primera vez en una PC nueva:**

```powershell
git clone https://github.com/dariowaltergonzalez/puntoventa.git
cd puntoventa
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/resetear_base.py --confirmar
python main.py
```

**Cada vez que traés cambios de la otra PC:**

```powershell
git pull
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`pip install -r requirements.txt` hace falta solo si cambió `requirements.txt` (por ejemplo, cuando
se sumó `keyring` para la contraseña del correo), pero correrlo siempre no hace daño.

La base de datos (`data/puntoventa.db`) **no viaja por git**: cada PC tiene la suya. Los cambios
de estructura de la base se aplican solos al abrir la app.

## Scripts útiles

| Comando | Para qué |
|---|---|
| `python scripts/resetear_base.py --confirmar` | Borrón y cuenta nueva: guarda una copia en `data/backups/`, crea la base de cero y carga datos de prueba. **Con la app cerrada.** Solo mientras no haya datos reales. |
| `python scripts/verificar_cuadre.py` | Controla que stock, lotes, cobros, cuentas corrientes y ganancias cuadren. Solo lee: se puede correr cuando quieras. Tiene que decir "Todo cuadra". |
| `python scripts/seed_datos_basicos.py` | Carga los datos de prueba (productos, clientes, proveedores) sin borrar nada. |

Los demás `scripts/verificar_*.py` prueban cada parte de la app contra una copia de la base.

## Datos que no están en la base

- **Contraseña del correo (SMTP)**: se guarda en el administrador de credenciales de Windows,
  no en la base. En otra PC hay que volver a escribirla en Configuración → Datos del negocio.
