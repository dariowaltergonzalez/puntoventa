# Punto de Venta — Plan de producto

> Este documento vive versionado dentro del repo a propósito (recuperado el 2026-10-13
> después de perder la copia local que teníamos fuera del proyecto) — así no depende de
> una carpeta local que se puede perder entre sesiones. El **cómo** (convenciones de código,
> arquitectura) vive en `CLAUDE.md`, en la raíz del repo. Este archivo es el **qué**
> (requisitos de negocio, roadmap de fases).

## Contexto

Dario está preparando esta app de punto de venta para un amigo que empezó un negocio de
venta de artículos de limpieza. El objetivo es dejar bien resueltos los dos flujos que usa
todos los días — **comprar** a proveedores y **vender** a clientes —, con costeo real por
lote (FIFO/PEPS) para poder calcular ganancia verdadera por venta, no una aproximación con
el costo genérico del producto.

## Estado actual del proyecto

App de escritorio en Python con interfaz Flet y base SQLite. Construido y probado; la base
tiene solo datos de prueba (el negocio todavía no opera con ella):

- **Catálogo**: Categorías, Productos (marca, descripción, código de barras, proveedor
  asociado, stock mínimo con alerta visual), Proveedores, Clientes, Listas de precios.
- **Compras (Fase 1)**: Órdenes de Compra + recepciones + lotes FIFO. Completo.
- **Clientes + Listas de precios (Fase 2)**: Completo.
- **Cuentas Corrientes (Fase 3)**: clientes y proveedores, cargos/pagos, mora, límite de
  crédito. Completo.
- **Ventas (Fase 4)**: motor completo (FIFO, 3 capas de descuento acumulables, pago
  dividido, cargo automático en CC) + pantalla rediseñada como **consola de caja rápida a
  pantalla completa** (ventana maximizada, pestañas de ventas en paralelo, rail de
  cliente/lista/búsqueda, carrito con cantidad y descuento editables por línea, panel de
  cobro no-modal con atajos de teclado F1-F12, registro de cuánto entregó el cliente en
  efectivo y el vuelto derivado). Se bloquea la venta de productos sin precio cargado.
  Completo y probado.
- **Historial interno**: registra altas/cambios campo por campo, y además un resumen en
  JSON del impacto en stock de cada venta/compra (qué producto, cuánta cantidad).
- Formato de números estilo argentino, buscador en las grillas, paginación SQL en
  pantallas grandes, paleta de colores unificada en toda la app.
- **Cheques (Fase 6)**: cheques recibidos y propios, circulación a proveedores, baja,
  rechazo con reapertura de deuda. Medio de pago y anulación de pagos/cargos en Cuentas
  Corrientes. Completo.

**En curso**: Datos del negocio (ver sección propia más abajo).

**Pendiente**: Fase 5 (PDF/mail, presupuestos, pre-ventas, anulaciones de ventas).

## Estructura del menú

- **Catálogo**: Categorías, Productos, Proveedores, Clientes, Listas de precios
- **Operaciones**: Compras, Ventas, Movimientos
- **Cuentas**: Cuentas Corrientes, Medios de Pago, Cheques
- **Consultas**: Stock, Historial
- **Configuración**: Datos del negocio

## Roadmap de fases

1. **Fase 1 — Órdenes de Compra + lotes FIFO.** ✅ Completa.
2. **Fase 2 — Clientes + listas de precios.** ✅ Completa.
3. **Fase 3 — Cuentas Corrientes.** ✅ Completa.
4. **Fase 4 — Ventas.** ✅ Completa (backend + consola de caja rápida).
5. **Fase 5 — PDF + envío de mail**, presupuestos/pre-ventas temporales, edición/anulación
   de ventas cerradas (dirección ya definida: nota de crédito). No arrancada.
6. **Fase 6 — Cheques.** ✅ Completa (incluye medios de pago y anulaciones en Cuentas
   Corrientes).
7. **Datos del negocio** — identidad legal, contacto, cuentas bancarias, WhatsApp y correo
   saliente. Previo a Fase 5 (el membrete y el envío de mails salen de acá).

---

# FASE 1 — Órdenes de Compra + costeo por lotes (FIFO)

## Qué es una Orden de Compra (OC)

Una OC es la intención de comprarle algo a un proveedor. Tiene un número propio
(correlativo, ej. "OC-0001"), un proveedor, una fecha de creación, opcionalmente una fecha
estimada de entrega, un porcentaje de IVA opcional, una observación general, y un total
estimado (calculado a partir de lo que se pidió). Cada línea de la OC indica: qué producto,
cuánta cantidad se pidió, y a qué costo se pactó con el proveedor (para poder comparar
después contra lo que realmente cobra al momento de entregar — puede pasar mucho tiempo
entre el pedido y la llegada).

**Mientras una OC no tiene ninguna recepción registrada, no impacta ni el stock ni el costo
de nada.** Es pura intención.

## Proveedor de la OC

Puede ser un proveedor ya registrado, o se puede escribir un nombre que todavía no existe
(por ejemplo "MercadoLibre") — en ese caso se crea automáticamente un proveedor mínimo con
ese nombre. También se puede elegir un proveedor **genérico** predefinido, para el caso de
no tener ningún dato del proveedor.

## Estados de la OC

- **Pendiente**: recién creada, todavía no llegó nada.
- **Recibida parcial**: ya llegó al menos una recepción contra esa OC.
- **Recibida**: todas las líneas pedidas ya llegaron completas.
- **Cancelada**: se decide no seguir con la orden (total o parcialmente).

Cerrar manualmente una OC que quedó incompleta para siempre **no es un estado nuevo** — se
marca como "Recibida" con una observación que explica el motivo del cierre manual.

## Edición de la OC

Se puede editar libremente mientras esté en estado Pendiente y sin ninguna recepción. En
cuanto tiene al menos una recepción, queda congelada.

## Creación rápida ("¿ya la tenés en mano?")

Al crear una OC, hay una opción para marcar que la mercadería ya se tiene en mano. En ese
caso, la orden se crea y se recibe en el mismo momento.

## Recepciones

Un evento en el que efectivamente llega mercadería. Puede haber más de una por OC. Puede
cubrir total o parcialmente lo pedido, traer ítems que no estaban en la OC original, traer
más cantidad de la pedida, e incluir opcionalmente número de remito/factura.

## Alta de producto nuevo durante una recepción

Se da de alta con los datos mínimos posibles (nombre, código, costo y cantidad). La
categoría es opcional; si no se elige, queda sin categorizar para completar después.

## Ítems libres

Al cargar una línea (OC o recepción), se puede optar por un ítem libre: solo descripción,
cantidad y precio, sin producto asociado, sin generar lote ni tocar stock. Sirve para
cargos puntuales (flete, impuestos, etc.).

## Costeo por lotes (FIFO)

Cada línea de una recepción genera un "lote" propio: cantidad, costo real, fecha. Al vender
(Fase 4), se consume primero del lote más viejo con stock disponible.

## Proveedores — contactos auxiliares

Lista de contactos adicionales por proveedor (nombre, email, teléfono), pensado para el
envío de OC por mail (Fase 5).

---

# FASE 2 — Clientes + listas de precios

- **Cliente registrado o nombre genérico**: mismo criterio que proveedores.
- **Datos del cliente**: razón social y nombre de fantasía por separado, DNI y CUIT
  separados, contacto principal, teléfono, email, dirección desglosada. Todos opcionales.
- **Condición ante el IVA** y **plazo de pago habitual (días)**: datos del cliente, sin
  funcionalidad de facturación real detrás (no hay AFIP en el alcance del proyecto).
- **% de descuento por cliente**: fijo, se aplica o no en cada venta puntual.
- **Contactos auxiliares por email**, con sector/descripción y flag de principal.
- **Ícono "Estado de cuenta"**: dispara la consulta de Cuentas Corrientes.

## Listas de precios

Una lista es un nombre con, como mínimo, un % general sobre el precio de venta normal.
Resolución de precio (de más específico a más general):
1. Precio manual cargado para ese producto puntual en esa lista.
2. % definido para la categoría del producto en esa lista.
3. % general de la lista.
4. Si la lista no tiene nada cargado: precio de venta normal.

Un cliente puede tener más de una lista asignada, con prioridad entre ellas. Al vender, se
sugiere la de mayor prioridad, pero el vendedor puede cambiarla.

---

# FASE 3 — Cuentas Corrientes

Dos cuentas corrientes independientes: clientes y proveedores.

## Cómo funciona

- **Cargos** (generan deuda): automático desde Compras (recepción a crédito) o desde
  Ventas (pago con medio "Cuenta corriente"), o a mano para cualquier otro caso.
- **Pagos/cobros** (bajan la deuda): "a cuenta" (se aplica FIFO al cargo más viejo) o
  aplicado a un cargo específico.
- **Saldo**: se calcula siempre al momento de consultar, nunca se guarda cacheado.

## Vencimiento y mora (solo clientes)

Cada cargo tiene fecha de vencimiento (según el plazo de pago del cliente). Cada cliente
tiene su propia tasa de interés por mora diaria, calculada siempre al consultar. Cobrarlo
es opcional, se muestra al momento de registrar un cobro.

## Límite de crédito (solo clientes)

Monto + modo de comportamiento al superarlo (bloquear o solo avisar), configurable por
cliente.

---

# FASE 4 — Ventas

- **Estados**: "Pendiente" (existe en la base, reservado para Fase 5) y "Confirmada". Una
  venta normal nace directamente Confirmada en un solo paso.
- **Cliente**: siempre resuelto — registrado, nombre suelto creado al vuelo, o genérico.
- **Vendedor**: descartado por completo (ni como columna vacía).
- **Consumo FIFO**: igual criterio que Compras.
- **IVA opcional** en la venta, manual, sin lógica de facturación real.
- **Medios de pago**: catálogo propio (CRUD simple). Una venta puede tener más de un medio
  (pago dividido). "Cuenta corriente" es un medio de pago más, marcado con un check — así
  una venta con seña queda resuelta naturalmente (solo se genera cargo por lo que
  efectivamente quedó en cuenta corriente).
- **Selección de lista de precios**: sugerida por prioridad, el vendedor puede cambiarla.
- **Búsqueda de producto**: código de barras, código manual, nombre.
- **El stock se descuenta recién al confirmar la venta.**
- **Descuentos**: hasta 3 capas que se acumulan todas (lista de precios + % fijo del
  cliente + descuento manual libre, por ítem o sobre el total) — ninguna reemplaza a la
  otra.
- **Reimpresión**: PDF/pantalla alcanza, sin integración con impresora fiscal.
- **Restricción**: no se puede vender un producto de catálogo sin stock disponible, ni sin
  precio de venta cargado (bloqueado tanto en la pantalla como en el motor).
- **Ítems libres/servicios**: igual criterio que Compras.
- **Ganancia**: se calcula al momento, nunca se guarda pre-calculada.
- **Cambio de efectivo**: se carga cuánto entregó el cliente y se calcula el vuelto —
  ambos quedan persistidos en el pago (no solo mostrados en pantalla).
- **Aviso de stock bajo mínimo**: al agregar un producto bajo mínimo, se avisa (no
  bloquea).
- **Nota especial del cliente**: visible al momento de venderle si tiene observación
  cargada.
- **Productos rápidos**: accesos directos en la pantalla de venta.
- **Múltiples ventas en paralelo**: pestañas, se puede tener más de una venta abierta.
- Descartado: paquetes/combos, dos velocidades de cobro distintas.
- **Anulación de venta cerrada**: dirección definida (nota de crédito, Fase 5) — un
  comprobante nuevo que anula/reduce una venta existente sin borrar ni modificar el
  original, reversa stock y genera el efecto contrario en Cuentas Corrientes.

## Rediseño de la pantalla (post-implementación inicial)

Después de la primera versión (formulario clásico), Dario pidió una consola de caja rápida
a pantalla completa, inspirada en referencias de mercado (AVenta). Se construyó primero
como mockup HTML interactivo (varias rondas de ajuste) y después se portó a Flet:
ventana maximizada, pestañas de ventas en paralelo, rail izquierdo (cliente, lista de
precios, búsqueda con filtro en vivo, productos rápidos), carrito con cantidad y % de
descuento editables por línea, franja de IVA/descuento total/observación, panel de cobro
como overlay no-modal (sin `AlertDialog`), atajos de teclado (Tab, Enter, F1-F12), bloqueo
de productos sin precio, y desglose visible de los 3 descuentos acumulados junto al total
(para que nunca parezca un error de cálculo).

---

# FASE 5 — PDF/mail, presupuestos, pre-ventas, anulaciones (no arrancada)

- **Envío de la OC por mail**: PDF + email al proveedor (contacto principal o auxiliares).
- **Presupuesto**: venta sin confirmar que no toca stock, persiste en el tiempo, PDF
  membretado por mail. Puede convertirse en venta real.
- **Pre-venta temporal**: venta sin confirmar guardada con un nombre, no toca stock, se
  borra sola al final del día si no se retoma. Recuperable antes de eso.
- **Edición/anulación de ventas cerradas**: nota de crédito — especificada abajo
  (2026-10-19), primera parte de Fase 5 en implementarse.
- **Reporte de estado de cuenta en PDF**: desde Cuentas Corrientes, descargable.

## Nota de crédito (especificada 2026-10-19)

El dueño todavía no dio requisitos de detalle (el negocio no abrió): estas decisiones las
tomamos con criterio de comercio chico, para revisar cuando opine.

- **La venta original nunca se toca.** La nota de crédito es un comprobante nuevo con
  numeración propia (**NC-0001**), que referencia a la venta, con **motivo obligatorio**. Una
  venta puede tener varias notas de crédito (devoluciones en distintos días). En el historial
  la venta muestra cuánto se le acreditó y su **total neto**.
- **Total o parcial**: se elige qué líneas y qué cantidad de cada una se devuelven (nunca más
  de lo vendido menos lo ya devuelto). El monto se calcula con los mismos precios y
  descuentos de la venta original (línea, % del cliente, % sobre el total, IVA): una nota de
  crédito por todo da exactamente el total de la venta.
- **Stock**: cada línea tiene un check **"vuelve al stock"** (marcado por defecto). Lo que
  vuelve entra a **los mismos lotes de los que salió, con su costo original** (FIFO y
  ganancia siguen exactos). Lo que no vuelve (roto, vencido) no toca el stock: queda como
  pérdida — la ganancia de la venta baja por el precio acreditado, el costo se mantiene.
- **La plata** (reintegro):
  - Si la venta tenía parte en **cuenta corriente** y esa deuda sigue pendiente, la nota de
    crédito primero la descuenta (automático).
  - El **resto** se elige: **devolver** en un medio de pago (Efectivo, Transferencia...),
    **dejar a favor** en la cuenta corriente del cliente (vale para la próxima compra; no
    para el cliente genérico), o **devolver el cheque** con que pagó, si sigue en cartera y el
    monto coincide (pasa a Baja).
  - En Cuentas Corrientes el crédito aparece como un pago "Nota de crédito NC-0001", que no se
    anula ni se corrige desde ahí (es parte de la nota de crédito).
- **Corregir venta** (para el usuario es "editar"): nota de crédito por todo lo que quede
  de la venta, con la mercadería de vuelta al stock, y se abre la caja en una pestaña nueva
  con el carrito precargado (cliente, productos, cantidades, descuentos). Se ajusta y se
  cobra de nuevo. Los precios se vuelven a resolver con la lista de precios vigente.
  Es para **errores de carga** (cliente, medio de pago, precio/descuento o producto
  equivocados); una devolución real del cliente es una nota de crédito. **Sin límite de
  tiempo** (cualquier corte sería arbitrario): en su lugar, si desde la venta cambió el
  precio de algún producto o el % fijo del cliente, el panel lo avisa antes de confirmar.
- La nota de crédito **no se anula** (si se emitió por error, se vuelve a vender).
- **Snapshot del descuento del cliente**: la venta guarda el % fijo del cliente que tenía al
  momento de vender (hasta ahora se leía del cliente cada vez, así que cambiarle el % a un
  cliente cambiaba el total de sus ventas viejas).
- Más adelante (resto de Fase 5): PDF de la nota de crédito. "Cambio de un producto por otro"
  = nota de crédito + venta nueva, sin pantalla propia.

---

# FASE 6 — Cheques (especificada 2026-10-13, completa 2026-10-19)

## Contexto del negocio

Es común en pymes argentinas que un cheque de un cliente **circule**: el negocio lo recibe
como pago, y en vez de depositarlo, lo usa él mismo para pagarle a uno de sus propios
proveedores (se "endosa"). El alcance de esta fase es justamente dejar clara la trazabilidad
de esa circulación — en particular, qué cheques siguen siendo del negocio (y hay que
cobrarlos a futuro) y cuáles ya no.

**Explícitamente fuera de alcance**: si un cheque terminó depositado en el banco o no, es
indiferente para la app — no se modela ningún estado de "depositado". Lo único que importa
es si el cheque sigue siendo nuestro (pendiente de cobro) o ya no.

## Tipos de cheque (origen)

- **Recibido de un cliente**: entra al sistema de dos formas —
  1. Como parte del cobro de una venta (junto a otros medios de pago, en el mismo cobro).
  2. Suelto, para saldar una deuda vieja de cuenta corriente de ese cliente (sin venta
     nueva de por medio).

  En ambos casos queda con estado **"En cartera"**.

- **Propio** (emitido por el negocio): nace directamente en el momento de pagarle a un
  proveedor — nunca pasa por "En cartera", porque nunca lo "recibimos", lo emitimos
  nosotros.

## Estados y ciclo de vida

Un cheque **recibido de un cliente** pasa por:

1. **En cartera** — lo tenemos, pendiente de su fecha de pago.
2. Desde ahí, sale por uno de 3 caminos (todos finales — una vez que sale, no se vuelve a
   tocar; no hay seguimiento de qué hace el proveedor con él después):
   - **Entregado a un proveedor** — para pagar una compra nueva (recepción de OC) o para
     saldar una deuda vieja de cuenta corriente de ese proveedor.
   - **Baja** — motivo libre (campo Observación), para cualquier otro caso que no encaje
     en los anteriores (ej. "se lo di a un amigo").
   - **Rechazado** — rebotó, se rompió, o cualquier motivo por el cual el cheque no sirve
     para cobrar. Ver más abajo el efecto automático en Cuentas Corrientes.

Un cheque **propio** nace directamente en estado **"Entregado a proveedor"** (para pagar
una OC o una cuenta corriente), sin pasar por "En cartera". También puede marcarse
**Rechazado** si rebota al querer cobrarlo el proveedor.

## Efecto del rechazo en Cuentas Corrientes

Mismo criterio que toda la app: **nunca se edita ni se borra nada**, se agrega un registro
nuevo que compensa.

- Si rebota un cheque **recibido de un cliente**: se genera automáticamente un **cargo
  nuevo** en la cuenta corriente de ese cliente, por el mismo monto — la deuda vuelve a
  estar pendiente, sin que Dario (o su amigo) tenga que recrearla a mano.
- Si rebota un cheque **propio**: se genera automáticamente un **cargo nuevo** en la cuenta
  corriente de ese **proveedor** — la deuda del negocio hacia él vuelve a estar pendiente.

## Datos de un cheque

| Campo             | Obligatorio | Notas |
|--------------------|:-----------:|-------|
| Banco              | Sí          | |
| Librador            | Sí          | Nombre de quien lo firmó — no siempre es el cliente mismo (puede ser un cheque de un tercero que el cliente recibió y nos pasó a nosotros). |
| Monto              | Sí          | |
| Fecha de pago       | Sí          | Vencimiento — el dato clave para el reporte de "cheques a cobrar". |
| Número de cheque    | No          | |
| CUIT del librador   | No          | |
| Fecha de recepción  | —           | Por defecto hoy, como el resto de la app. |
| Estado             | —           | No editable a mano — cambia solo por las acciones del ciclo de vida (igual criterio que el estado de una OC). |
| Observación         | No          | Texto libre. También se usa para dejar asentado el motivo cuando se da de Baja o se marca Rechazado (no hay un campo "motivo" separado). |

## Reporte "cheques a cobrar"

Sale directamente de filtrar los cheques en estado **"En cartera"**, agrupados u
ordenados por **fecha de pago** — para saber de un vistazo cuánto hay para cobrar este mes
o el que viene.

## Diseño técnico y estado de implementación (2026-10-13)

**Motor (repositorios + servicios) completo y verificado** contra una copia de la base real
(`scripts/verificar_fase6_cheques.py`, 30 verificaciones, todas OK) — reutiliza casi todo lo
que ya existía en vez de armar un circuito paralelo:

- **Tabla nueva `cheques`**: datos propios (banco, librador, CUIT, monto, número, fecha de
  pago, fecha de recepción) + `origen_tipo` ('recibido_cliente' | 'propio') + `estado`
  ('en_cartera' | 'entregado_proveedor' | 'baja' | 'rechazado') + `cliente_id`/`proveedor_id`
  + `cargo_generado_id` (el cargo de CC que reabrió la deuda, si rebotó).
- **`venta_pagos.cheque_id`** (nullable): entrada de un cheque pagando una venta directamente.
- **`cc_pagos.cheque_id`** (nullable): entrada suelta (saldar CC vieja de un cliente) **y**
  las dos formas de salida (circular un cheque recibido a un proveedor, o un cheque propio) —
  las tres son, ni más ni menos, un pago de Cuenta Corriente de siempre, con el cheque como
  dato extra.
- **`cc_cargos`**: nuevo origen `'cheque_rechazado'` + columna `origen_cheque_id`, para el
  cargo que se genera automáticamente al rechazar un cheque.
- **Pagar una compra nueva con un cheque** (recibido o propio) se resuelve como "la recepción
  queda a crédito" + "se aplica el cheque a ese cargo recién creado", sin tocar nada de
  Compras — dos pasos que ya existían por separado, encadenados.
- `app/repositories/cheques_repo.py` + `app/services/cheques_service.py`: CRUD, las 3
  funciones de entrada/salida (`recibir_de_cliente_para_cc`, `entregar_a_proveedor`,
  `crear_cheque_propio_y_entregar`), `dar_de_baja`, `marcar_rechazado` (genera el cargo nuevo
  de forma atómica), y una compensación manual (si falla aplicar el pago, se borra el cheque
  recién creado — no quedan huérfanos).

**Pantallas**: grilla de Cheques propia (entrada suelta, salida a proveedor, baja, rechazo) +
cheque como medio de pago en el cobro de Ventas.

## Cierre de Fase 6: medios de pago y anulaciones en Cuentas Corrientes (2026-10-19)

Surgió al probar el circuito completo "recibo la OC a crédito → le pago al proveedor":

- **Medio de pago en cada pago/cobro de Cuenta Corriente**: el formulario de pago elige un
  medio del catálogo (Efectivo, Transferencia, Mercado Pago, etc. — nunca "Cuenta
  corriente", no tiene sentido). Si el medio es **Cheque**:
  - en la cuenta de un **proveedor**: se elige entre un cheque **en cartera** (el monto es el
    del cheque, no se parte) o uno **propio** (se cargan sus datos);
  - en la cuenta de un **cliente**: se cargan los datos del cheque que entrega (queda en
    cartera).
  Un pago con dos medios (parte efectivo, parte cheque) son dos pagos seguidos.
- **Pagar una compra con cheque** queda resuelto así, sin tocar Compras: la recepción queda a
  crédito y se paga desde la Cuenta Corriente del proveedor con el medio que sea.
- **Saldo a favor**: si un pago supera la deuda, lo que sobra se descuenta del saldo total
  de la cuenta (y se muestra como "Saldo a favor" si queda negativo), en vez de perderse.
- **Anular un pago** (nunca se edita ni se borra): motivo obligatorio, el pago queda en la
  grilla marcado como anulado y deja de contar, así que los cargos que cubría vuelven a
  quedar pendientes.
- **Corregir un pago** (para el usuario es "editar"): el lápiz abre un panel con el medio,
  monto, fecha y observación del pago; se cambia lo que esté mal y se guarda en un solo paso.
  Por dentro, el pago viejo queda anulado con un motivo automático ("Corregido: monto
  70.000,00 -> 67.500,00") y se crea uno nuevo, todo en una sola operación. Los pagos con
  cheque no se corrigen (el monto de un cheque no cambia): se anulan y se cargan de nuevo.
  Con cheques:
  - pago a proveedor con cheque que estaba en cartera → el cheque vuelve a **En cartera**;
  - pago a proveedor con cheque propio → el cheque pasa a **Baja** (motivo: anulado);
  - cobro a cliente con cheque → el cheque pasa a **Baja**, salvo que ya se haya entregado a
    un proveedor: ahí no deja anular hasta anular primero ese otro pago;
  - si el cheque ya fue rechazado, no se puede anular el pago (la deuda ya se reabrió).
- **Anular un cargo manual**: mismo criterio (motivo obligatorio, queda marcado). Solo cargos
  manuales — los de compras/ventas/cheques rechazados se corrigen desde su origen — y solo si
  no tiene pagos aplicados (primero se anulan esos pagos).

---

# Datos del negocio (especificado 2026-10-19)

**Terminología**: a quien usa la app (el amigo de Dario) se le dice **el dueño**, y a su
comercio **el negocio**. "Cliente" queda reservado para los Clientes del negocio (la gente
que le compra).

Pantalla única en **Configuración → Datos del negocio**: un formulario, sin listado (hay un
solo negocio). Todo cambio queda en el Historial campo por campo.

## Identidad legal

| Campo | Obligatorio | Notas |
|---|:---:|---|
| Razón social / titular | Sí | Nombre legal: el nombre y apellido si es persona física, la razón social si es sociedad. Es lo que figura en la chequera y en los comprobantes formales. |
| CUIT | Sí | |
| Condición frente al IVA | No | Mismo catálogo que Clientes. |
| Nombre de fantasía | No | La marca comercial — lo que va grande en el membrete. No tiene valor legal. |
| Nº de Ingresos Brutos | No | Suele ir en el pie de los comprobantes. |
| Inicio de actividades | No | Idem. |

## Contacto

Dirección (calle y número, ciudad, provincia, código postal — mismo desglose que Clientes),
teléfono, email, web/redes.

## Cuentas bancarias (lista)

El negocio puede tener más de una. Cada una: banco, titular y CUIT del titular (por defecto
los del negocio, editables — una cuenta puede estar a nombre de otra persona), CBU, alias, y
una marcada como **principal**.

- **Cheque propio**: al pagarle a un proveedor con un cheque propio se elige la cuenta
  bancaria y se completan solos banco, librador (= titular) y CUIT. Siguen editables.
- **Fase 5**: CBU/alias para un "Datos para transferir" en presupuestos.

## WhatsApp (lista)

Uno o más números, cada uno con una etiqueta (ej. "Ventas", "Administración") y uno marcado
como principal. Se guardan en formato internacional para poder armar links de WhatsApp
(`wa.me`) en Fase 5 (mandar un presupuesto por WhatsApp).

## Correo saliente (SMTP)

Servidor, puerto, seguridad (SSL / STARTTLS / ninguna), usuario, contraseña, nombre y email
del remitente. Botón **"Enviar mail de prueba"** al email del remitente, para confirmar que
la configuración funciona antes de necesitarla en Fase 5.

- La **contraseña no se guarda en la base**: va al administrador de credenciales de Windows.
  Así, quien copie el archivo de la base no se lleva la contraseña. Contra: si se pasa la base
  a otra PC hay que volver a escribirla una vez.
- Con Gmail hace falta una "contraseña de aplicación" (no la contraseña normal de la cuenta).

## Fuera de alcance por ahora

- **Logo**: recién tiene sentido con los PDF — se suma en Fase 5.
- **Facturación electrónica AFIP** (puntos de venta, certificados): fuera de alcance, como
  siempre.

---

# Modelo de UI (patrón general para pantallas con listado)

Cada módulo que se maneje como una lista de registros sigue el mismo patrón:

- **Filtros** arriba de la grilla, con un botón para imprimir un PDF de lo filtrado/visible.
- **Grilla principal** con las columnas clave y una columna de acciones por fila, con
  íconos condicionados al estado del registro.
- **Contadores resumen** arriba de la grilla, con la cantidad de registros en cada estado
  relevante.
- **Filas expandibles**: si un registro tiene ítems asociados, se expande con un "+" para
  ver el detalle ahí mismo, sin navegar a otra pantalla. La flecha de expandir va al
  **inicio** de la fila (no al final) — más visible.
- **Paginación**: indicador de total de registros y página actual, con controles para
  moverse entre páginas. En pantallas grandes, la paginación se resuelve en la consulta
  SQL, no trayendo todo a memoria.
