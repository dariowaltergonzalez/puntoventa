# Estándar de pantallas

Cómo se ve y se comporta **toda** pantalla de la app. Una pantalla nueva no inventa nada: se arma
con las piezas de `app/ui/componentes.py` siguiendo este documento. Si algo que hace falta no está
acá, primero se define y se escribe acá (y se agrega la pieza), después se usa.

Acordado con Dario el 20/10/2026, a partir del mockup "Estándar de Listas".

---

## 1. Forma de una pantalla de lista

De arriba hacia abajo, siempre en este orden:

1. **Encabezado**: título grande + una línea que dice para qué sirve la pantalla.
2. **Barra** (tarjeta blanca): filtros a la izquierda, botones de acción a la derecha
   (`Imprimir`, `+ Nuevo X`, `Volver` si corresponde). Todo en **una sola línea** y del mismo alto.
3. *(Opcional)* **Resumen**: tarjetas con totales, solo si la pantalla tiene números que importan
   (ej. Gastos: pagado / IVA recuperable / gastos del período).
4. **Lista** (tarjeta blanca): la tabla, y debajo de ella el **paginado**, centrado, con números de
   página (`|<  <  1 2 3  >  >|`, "Página 1 de 3 (46 clientes)" y filas por página).

La lista es lo principal. Nada de formularios fijos arriba de la lista.

## 2. Filtros

- **Texto y combos filtran al instante**, mientras se escribe o se elige.
- **Fechas (Desde / Hasta) filtran recién con el botón `Filtrar`** (o Enter en la fecha): mientras se
  tipea, está incompleta. El texto y los combos siguen filtrando al instante, pero con las **últimas
  fechas aplicadas** (no con lo que esté a medio escribir). Fecha mal escrita → aviso rojo con el
  formato (AAAA-MM-DD). Ejemplo: Compras.
- **Ningún campo lleva título afuera.** El nombre va en el borde de la caja (etiqueta flotante de
  Flet: adentro si está vacía, sobre el borde si tiene algo). Así todo queda en una línea.
- Buscador: siempre `campo_buscar("qué busca")` → etiqueta "Buscar", lupa, la ayuda adentro.

## 3. La lista

- Números alineados a la derecha. Textos a la izquierda.
- **Orden por columna**: clic en el título ordena por esa columna; otro clic invierte. La columna
  activa muestra ▲/▼; las ordenables sin activar, un ícono tenue (y tooltip "Ordenar por ...").
  Al cambiar el orden la lista vuelve a la página 1. Se ordenan las columnas de texto, número y
  fecha que tenga sentido (no Estado ni Acciones). Cada pantalla arranca con un orden pensado
  (Productos por nombre; lo que tiene fecha, lo más nuevo primero). Si la lista pagina en SQL, el
  orden se resuelve en la consulta, con una **lista cerrada** de columnas en el repositorio (nunca se
  arma el `ORDER BY` con texto que llega de la pantalla); ordenar solo la página visible estaría mal.
- **El estado va como etiqueta de color** (`etiqueta_estado`), siempre con los mismos colores:

  | Color | Significa | Ejemplos |
  |---|---|---|
  | Verde | terminado / bien | Activo, Recibida, Cobrado, Convertido |
  | Ámbar | espera algo | Pendiente, Vigente, En cartera |
  | Verde agua | en curso | Recibida en parte, Enviado |
  | Rojo | anulado / no vale | Cancelada, Anulado, Inactivo, Vencido, Rechazado |

- **Las acciones son íconos en la última columna**, ver sección 5.
- Lista vacía: una línea que dice por qué ("No hay gastos en el período", "Ningún producto coincide
  con la búsqueda"), nunca una tabla vacía muda.

## 4. Filas con hijos

Si un registro tiene "hijos" (las líneas de una OC, los lotes de un producto, los cargos de una
cuenta corriente), la fila lleva una **flecha a la izquierda** que la despliega ahí mismo.

- Lo desplegado es **solo para mirar**. Para cambiar algo, el lápiz de la fila abre el formulario.
- Lleva el aviso "Solo para mirar. Para cambiar algo, el lápiz de la fila abre el formulario."

| Pantalla | Qué despliega |
|---|---|
| Compras | líneas pedidas + recepciones |
| Presupuestos | artículos |
| Stock | lotes con su costo |
| Cuentas corrientes | lo que queda por pagar + últimos pagos |
| Listas de precios | % por categoría + precios a mano |
| Clientes | contactos + listas asignadas |

## 5. Acciones de una fila: 5 tipos

Cada ícono es de uno de estos tipos, y cada tipo se comporta siempre igual:

| Tipo | Ejemplos | Qué pasa al apretar |
|---|---|---|
| **1. Abrir** | editar, registrar recepción | Lleva al formulario (pantalla aparte). Guardar o Cancelar vuelven a la lista **como estaba** (mismos filtros, misma página) y avisa abajo qué pasó. |
| **2. Ver info** | ver resumen, historial | **Ventana chica** de solo lectura, con botón Cerrar. No cambia nada. |
| **3. Cambiar estado** | activar / desactivar, marcar enviado | Cambia **al instante**, la etiqueta de la fila se actualiza y avisa abajo ("Lavandina 1L: desactivado"). Es algo que se puede volver atrás. |
| **4. Anular** | anular gasto, cancelar OC, anular pago | **Única en rojo.** Ventana chica que confirma y pide el **motivo** (obligatorio). Sin motivo no deja seguir. Al confirmar, la etiqueta pasa a rojo y avisa abajo. Variante **sin rojo** para un cierre con motivo que no anula nada (ej. "Dar por recibida" una OC): misma ventana, botón normal (`accion_con_motivo`). |
| **5. Proceso** | enviar por mail, generar PDF | El ícono **gira** mientras trabaja y al final avisa abajo cómo salió ("Mail enviado a ventas@...", o el error). |

Reglas para todos los íconos:

- **Tooltip siempre**, verbo + qué: "Cancelar orden", "Enviar por mail al proveedor".
- **Si no corresponde, queda apagado y el tooltip dice por qué**: "Editar orden: ya tiene
  recepciones". Si igual se aprieta, lo avisa abajo.
- **Orden**: primero los que miran (ver, mail, PDF), después los que cambian (recibir, editar,
  activar), el rojo siempre último.
- **Mismo ícono = mismo significado en toda la app** (diccionario abajo).

### Diccionario de íconos

| Acción | Ícono (`ft.Icons.`) |
|---|---|
| Ver info / detalle | `VISIBILITY` |
| Editar | `EDIT` |
| Anular / cancelar | `BLOCK` (rojo) |
| Activar / desactivar | `POWER_SETTINGS_NEW` |
| Enviar por mail | `EMAIL` |
| Imprimir / PDF | `PRINT` |
| Registrar recepción | `LOCAL_SHIPPING` |
| Dar por recibida / cerrar con lo que hay | `DONE_ALL` |
| Entregar (un cheque a un proveedor) | `SEND` |
| Dar de baja (sale sin anular: depositado, cobrado) | `ARCHIVE` |
| Cuenta corriente | `ACCOUNT_BALANCE_WALLET` |
| Abrir en la caja | `POINT_OF_SALE` |
| Ver comprobante adjunto | `ATTACH_FILE` |
| Desplegar hijos | `CHEVRON_RIGHT` (abierta: `EXPAND_MORE`) |
| Quitar un hijo (dentro del formulario) | `CLOSE` |
| Subir / bajar prioridad | `ARROW_UPWARD` / `ARROW_DOWNWARD` |
| Nuevo | `ADD` |
| Buscar | `SEARCH` |
| Filtrar | `FILTER_LIST` |

Una acción nueva que no esté en la tabla: se elige el ícono, **se agrega acá**, y recién ahí se usa.

## 6. Formulario de alta y edición

- Es una **pantalla aparte**: reemplaza la lista (la lista se oculta, no se mezclan).
- Título: "Nuevo producto" / "Editar producto: Lavandina 1L".
- Botones abajo: **Guardar** (o "Agregar X" / "Guardar cambios") y **Cancelar**. Los dos vuelven a la
  lista donde estaba. Al guardar, aviso abajo ("Producto guardado").
- Campos agrupados en tarjetas por tema si son muchos (ej. Datos del negocio).
- **Nunca en una ventana modal.**
- **Hijos** (contactos de un cliente, % por categoría de una lista): se editan en tarjetas propias
  debajo de los datos, **solo al editar** (necesitan que el padre ya exista; al crear, un aviso dice
  "se agregan después, con el lápiz"). Cada alta o baja de un hijo **se guarda al instante** y avisa
  abajo; la tarjeta lo dice en su subtítulo. Para quitar un hijo: ícono `CLOSE`, sin motivo (no es
  anular, es sacar algo de una lista).
- Ir a otra pantalla ya parada en un registro (ej. de Clientes a su cuenta corriente): acción tipo 1
  con un enlace de la app (`page.abrir_cuenta_corriente(tipo, id)`, `page.abrir_presupuesto_en_caja(id)`),
  nunca un aviso de "andá al menú".

## 7. Ventanas modales

Solo para los tipos **2 (ver info)** y **4 (anular)**, y siempre **chicas** (título, poco contenido,
botones abajo a la derecha). Los formularios de alta y edición nunca van en modal.

## 8. Avisos

Todo resultado se avisa abajo (`SnackBar`), en una frase que dice qué pasó y sobre qué:
"OC-0004 cancelada", "Mail enviado a ventas@quimicadelsur.com.ar". Los errores dicen qué está mal y
cómo arreglarlo: "Escribí el motivo para poder cancelar".

## 9. Excepciones (pantallas que no son de lista)

- **Ventas (la caja)**: pantalla de trabajo propia, su función es cargar rápido. *Pendiente*: su historial
  de ventas y la lista de pre-ventas todavía usan el paginador viejo (`listados.Paginador`).
- **Movimientos**: es para cargar ajustes de stock; el formulario queda a la vista (la lista de abajo sí es
  una `Lista` estándar).
- **Ganancias**: es un tablero (números y gráficos), no una lista.
- **Datos del negocio**: es un único formulario, no hay lista.
- **Cuentas corrientes, detalle de una cuenta**: es la mesa de trabajo de esa cuenta (cargos, pagos,
  cobros, anulaciones); se llega con la acción "Abrir la cuenta" de la lista.

Aun así usan el mismo encabezado, las mismas tarjetas, el mismo diccionario de íconos y los mismos
avisos.

---

## Piezas (`app/ui/componentes.py`)

| Para | Pieza |
|---|---|
| Título + subtítulo | `encabezado_pantalla(titulo, subtitulo)` |
| Barra de filtros y acciones | `barra([filtros], [botones])` |
| Buscador | `campo_buscar("qué busca", al_cambiar=filtrar)` |
| Botón "+ Nuevo X" / secundario | `boton_principal(...)` / `boton_secundario(...)` |
| Lista + paginado + filas desplegables | `Lista([Columna(...)], al_cambiar_pagina=refrescar, con_hijos=..., orden_inicial=("clave", desc))` y `lista.mostrar(items, celdas, total=?, hijos=?)`; al cambiar un filtro, `lista.ir_al_principio()` |
| Columna ordenable | `Columna("Venta ($)", orden="venta")`; si pagina en SQL, pasar `lista.orden` / `lista.descendente` al servicio |
| Etiqueta de estado | `etiqueta_estado("Activo", TONO_OK)` — `TONO_OK`, `TONO_ESPERA`, `TONO_CURSO`, `TONO_NO` |
| Acción tipo 1 a 5 | `accion_abrir`, `accion_ver`, `accion_cambiar`, `accion_anular`, `accion_proceso` (todas con `por_que_no=`) |
| Ventana de solo lectura | `ventana_info(page, titulo, dato("Estado", "Pendiente"), ...)` |
| Formulario aparte | `tarjeta(filas..., botones_formulario(texto_guardar, al_guardar, al_cancelar), titulo=form_titulo)` |
| Aviso abajo | `avisar(page, texto, error=False)` |

Las acciones atrapan solo `ErrorDeNegocio` (base de todas las excepciones de
`app/services/exceptions.py`) y `ValueError`, y los muestran como aviso rojo. Cualquier otro error
es de programación y no se esconde.

Ejemplo completo y de referencia: **`app/ui/productos_view.py`** (lista simple, formulario aparte,
acciones tipo 1 y 3).

---

## Para armar una pantalla nueva

1. ¿Es de lista? → secciones 1 a 8. ¿Es una excepción? → sección 9.
2. Encabezado → barra (filtros + acciones) → lista con paginado → formulario aparte.
3. ¿Los registros tienen hijos? → flecha desplegable, solo lectura.
4. Cada acción: elegir su tipo (1 a 5), su ícono del diccionario, su tooltip y su "por qué no".
5. Estados → etiqueta con los colores de la tabla.
6. Todo con las piezas de `app/ui/componentes.py`. Si falta una pieza, se agrega ahí (no en la
   pantalla) para que la próxima ya la tenga.
