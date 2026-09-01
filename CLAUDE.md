# Punto de Venta — Guía del proyecto

App de escritorio (Python + Flet + SQLite) para un negocio de venta de artículos de limpieza. Este archivo documenta **cómo** se construye este proyecto — convenciones de código y arquitectura ya establecidas. El **qué** (requisitos de negocio, roadmap de fases) vive aparte, en el plan de producto activo (preguntar dónde está si no es evidente).

## Arquitectura: 3 capas estrictas

```
app/repositories/  →  único lugar que importa sqlite3 y contiene SQL
app/services/       →  reglas de negocio, valida, convierte tipos, expone dicts planos
app/ui/             →  pantallas Flet, solo llaman a servicios
```

Reglas que no se rompen:
- Nunca una consulta SQL fuera de `app/repositories/`.
- Nunca `import flet` dentro de `app/services/`.
- `app/services/` no importa `sqlite3` directamente — todo acceso a datos pasa por un repositorio.

## Capa de datos (`app/repositories/`)

- `app/db/connection.py::get_connection()` abre la conexión: `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`, `isolation_level=None` (autocommit), `row_factory=sqlite3.Row`.
- **Patrón de conexión opcional**, usado en toda función que pueda participar de una transacción más grande:
  ```python
  def f(..., conn: sqlite3.Connection | None = None):
      conexion_propia = conn is None
      if conexion_propia:
          conn = get_connection()
          conn.execute("BEGIN IMMEDIATE")
      try:
          ...
          if conexion_propia:
              conn.commit()
          return resultado
      except Exception:
          if conexion_propia:
              conn.rollback()
          raise
      finally:
          if conexion_propia:
              conn.close()
  ```
  Si te pasan una `conn` ya abierta, no gestionás su ciclo de vida (ni commit ni close) — eso es responsabilidad de quien la abrió.
- **Toda operación que toque más de una tabla es atómica**: una única transacción (`BEGIN IMMEDIATE` / `commit` / `rollback`), nunca varias operaciones sueltas que puedan dejar datos a medias.
- **No se usan triggers de SQLite.** La lógica derivada (por ejemplo, actualizar `stock_actual` al insertar un movimiento) se resuelve en código Python, dentro de la misma transacción, no en el motor.
- Los repositorios **no validan reglas de negocio** (stock negativo, producto inactivo, etc.) — eso ya viene validado desde la capa de servicios antes de llamar. El repo solo ejecuta.
- **Migraciones siempre aditivas**, en `app/db/connection.py::_migrar()`: `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ADD COLUMN` con chequeo previo vía `PRAGMA table_info`. Nunca `DROP`, nunca cambiar el tipo de una columna existente. El mismo cambio de esquema va también en `data/schema.sql` (instalaciones nuevas).
- **Antes de aplicar una migración a la base real, probarla contra una copia** (`cp data/puntoventa.db data/puntoventa_test.db`, apuntar `app.db.connection.DB_PATH` a la copia desde un script de prueba). Nunca experimentar directo contra `data/puntoventa.db`.

## Capa de servicios (`app/services/`)

- Valida **todo** antes de tocar el repositorio: existencia de entidades relacionadas, reglas de negocio, formato de los datos. Traduce `sqlite3.IntegrityError` a excepciones de dominio (ej. `CodigoDuplicadoError`).
- **Cantidades escaladas x1000** (3 decimales), **precios escalados x100** (2 decimales) — se guardan como `INTEGER` en SQLite para evitar errores de redondeo de floats. La conversión Decimal ↔ entero vive en `app/shared/money.py` (`cantidad_a_entero`, `entero_a_cantidad`, `precio_a_entero`, `entero_a_precio`, `formatear_precio`, `formatear_cantidad`) y se aplica **siempre en el borde del servicio** — nunca en el repositorio, nunca en la UI.
- Los servicios devuelven **dicts planos** (nunca `sqlite3.Row`) con valores ya en `Decimal`, no en enteros escalados.
- **Los valores calculados nunca se persisten cacheados** (totales, ganancias, etc.) — se calculan al momento de leer, para no arriesgarse a desincronizar un valor guardado si algo que lo compone cambia.
- **Auditoría obligatoria**: toda alta, edición o cancelación relevante de una entidad llama a `log_service.registrar(...)` o `log_service.registrar_cambios(...)` (éste último para diffs campo a campo, con nombres resueltos en vez de ids crudos). No es opcional — es la convención de auditoría del proyecto, cumplida por función/módulo, sin necesidad de una interfaz formal (el proyecto es funciones sueltas, no clases).
- Excepciones de negocio con nombres descriptivos, todas en `app/services/exceptions.py`.

## Capa de UI (`app/ui/`, Flet 0.86.5)

Peculiaridades de esta versión de Flet que ya nos mordieron — no asumir que la documentación vieja de Flet aplica tal cual:
- `page.show_dialog(ft.SnackBar(ft.Text(mensaje)))` para mostrar mensajes — **no** `page.open(...)` (no existe en esta versión).
- `ft.Padding.symmetric(...)` (con mayúscula) — **no** `ft.padding.symmetric` (no existe).
- Mutar `.text` de un `ElevatedButton` ya construido **no se refleja visualmente**. Para un botón cuyo texto cambia (ej. "Agregar" ↔ "Guardar cambios"), usar un `ft.Text` separado como `content=` del botón y mutar `.value` de ese `Text`.
- `ft.run(main)` para arrancar la app — `ft.app(target=main)` está deprecado.

Patrones de este proyecto (no son limitaciones de Flet, son decisiones de estilo):
- No se usan `AlertDialog` ni navegación modal. Las pantallas con múltiples secciones (lista/formulario/detalle) son `Column`s que togglean `.visible`.
- Filas expandibles con detalle inline: `ft.ExpansionTile`, no una pantalla aparte.
- Estado editable de una pantalla: closures + `nonlocal` (no hay manejo de estado global ni clases).
- Ninguna pantalla contiene SQL ni lógica de negocio — solo arma controles y llama a servicios.

## Base de datos

- SQLite en modo WAL. `data/puntoventa.db` (y sus `-wal`/`-shm`) están en `.gitignore` a propósito — nunca versionarlos, nunca editarlos a mano.

## Verificación / testing

- No hay suite de tests automatizada todavía — se verifica con scripts sueltos en `scripts/` (`seed_and_verify.py`, `verificar_*.py`) que se corren manualmente contra una copia de la base.
- Antes de dar por terminada una feature que toca movimientos o stock, correr `movimientos_service.recalcular_stock()` y confirmar que no aparecen diferencias.

## Idioma y convenciones de nombres

- Todo el código (funciones, variables, mensajes de error, nombres de tablas/columnas) está en **español**, sin comentarios innecesarios (solo cuando el *por qué* no es obvio).
- `snake_case` en Python y en SQL.

## Entorno de desarrollo

- Windows, PowerShell como shell principal. El estado de shell (incluido `$env:Path`) **no persiste entre comandos** — cada comando que necesite `python`/`git`/`gh` debe empezar refrescando el PATH:
  ```powershell
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
  ```
- Entorno virtual en `venv/` (activar con `.\venv\Scripts\Activate.ps1` en una terminal interactiva).
- Repo en GitHub: `https://github.com/dariowaltergonzalez/puntoventa` (privado).
