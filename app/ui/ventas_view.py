from decimal import Decimal, InvalidOperation

import flet as ft

from app.services import clientes_service, listas_precios_service, medios_pago_service, productos_service, ventas_service
from app.services.exceptions import (
    ClienteNoEncontradoError,
    LineasVaciasError,
    ListaPrecioNoEncontradaError,
    MedioPagoNoEncontradoError,
    MontoPagoInvalidoError,
    ProductoInactivoError,
    ProductoNoEncontradoError,
    StockInsuficienteError,
)
from app.shared.money import formatear_cantidad, formatear_porcentaje, formatear_precio
from app.ui.campos import FILTRO_DECIMALES, aplicar_mascara_moneda, parsear_decimal_ar_opcional
from app.ui.listados import Paginador, coincide_texto, filtrar

TIPO_PRODUCTO = "Producto existente"
TIPO_LIBRE = "Item libre"

EXCEPCIONES_NEGOCIO = (
    ClienteNoEncontradoError, LineasVaciasError, ListaPrecioNoEncontradaError,
    MedioPagoNoEncontradoError, MontoPagoInvalidoError, ProductoInactivoError,
    ProductoNoEncontradoError, StockInsuficienteError, ValueError,
)


def VentasView(page: ft.Page) -> ft.Control:
    def mostrar_mensaje(texto: str) -> None:
        page.show_dialog(ft.SnackBar(ft.Text(texto)))

    def parsear_decimal_opcional(valor: str | None, etiqueta: str) -> Decimal | None:
        texto = (valor or "").strip()
        if not texto:
            return None
        try:
            return Decimal(texto.replace(",", "."))
        except InvalidOperation:
            raise ValueError(f"{etiqueta} invalido") from None

    # ================= SECCION LISTA (historial) =================
    buscador_field = ft.TextField(label="Buscar por numero o cliente", expand=True)
    tabla_lista = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(t)) for t in ["Numero", "Cliente", "Fecha", "Total", ""]],
        rows=[],
    )
    paginador = Paginador(on_cambio=lambda: refrescar_lista())
    nueva_venta_button = ft.ElevatedButton("+ Nueva venta")

    def refrescar_lista(e: ft.ControlEvent | None = None) -> None:
        todas = ventas_service.listar_ventas()
        filtradas = filtrar(todas, [
            lambda v: coincide_texto(v["numero"], buscador_field.value) or coincide_texto(v["cliente_nombre"], buscador_field.value),
        ])
        pagina = paginador.aplicar(filtradas)
        tabla_lista.rows = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Text(v["numero"])),
                ft.DataCell(ft.Text(v["cliente_nombre"] or "-")),
                ft.DataCell(ft.Text(v["fecha"][:16])),
                ft.DataCell(ft.Text(formatear_precio(v["total"]))),
                ft.DataCell(ft.IconButton(ft.Icons.VISIBILITY, tooltip="Ver detalle", data=v["id"],
                                          on_click=lambda e: ir_a_detalle(e.control.data))),
            ])
            for v in pagina
        ]
        page.update()

    buscador_field.on_change = refrescar_lista
    nueva_venta_button.on_click = lambda e: ir_a_formulario()

    seccion_lista = ft.Column([
        ft.Text("Ventas", size=20, weight=ft.FontWeight.BOLD),
        ft.Row([buscador_field, nueva_venta_button]),
        tabla_lista,
        paginador.controles,
    ])

    # ================= SECCION FORMULARIO (nueva venta) =================
    productos_activos = []

    cliente_dropdown = ft.Dropdown(label="Cliente existente", width=280, options=[])
    cliente_nuevo_field = ft.TextField(label="O escribi un cliente nuevo", width=250)
    cliente_generico_switch = ft.Switch(label="Consumidor Final (sin datos)")
    cliente_info_texto = ft.Text("", color=ft.Colors.BLUE_700)
    lista_precio_dropdown = ft.Dropdown(label="Lista de precios", width=280, options=[], value="")

    def refrescar_dropdown_clientes() -> None:
        cliente_dropdown.options = [
            ft.dropdown.Option(key=str(c["id"]), text=c["razon_social"])
            for c in clientes_service.listar_clientes(solo_activos=True)
        ]

    def actualizar_info_cliente(e: ft.ControlEvent | None = None) -> None:
        cliente_info_texto.value = ""
        lista_precio_dropdown.options = [ft.dropdown.Option(key="", text="Sin lista (precio normal)")]
        lista_precio_dropdown.value = ""
        if cliente_dropdown.value:
            cliente = clientes_service.obtener_cliente(int(cliente_dropdown.value))
            if cliente and cliente["observacion"]:
                cliente_info_texto.value = f"Nota del cliente: {cliente['observacion']}"
            if cliente:
                listas_asignadas = sorted(cliente["listas_precios"], key=lambda l: l["prioridad"])
                lista_precio_dropdown.options += [
                    ft.dropdown.Option(key=str(l["lista_precio_id"]), text=f"{l['nombre']} (prioridad {l['prioridad']})")
                    for l in listas_asignadas
                ]
                if listas_asignadas:
                    lista_precio_dropdown.value = str(listas_asignadas[0]["lista_precio_id"])
        refrescar_precios_lineas()
        page.update()

    cliente_dropdown.on_select = actualizar_info_cliente
    lista_precio_dropdown.on_select = lambda e: refrescar_precios_lineas()

    lineas_form: list[dict] = []
    contenedor_lineas = ft.Column([])

    def crear_linea_venta() -> dict:
        tipo_dropdown = ft.Dropdown(
            label="Tipo", width=160,
            options=[ft.dropdown.Option(TIPO_PRODUCTO), ft.dropdown.Option(TIPO_LIBRE)],
            value=TIPO_PRODUCTO,
        )
        producto_dropdown = ft.Dropdown(
            label="Producto", width=240,
            options=[ft.dropdown.Option(key=str(p["id"]), text=f"{p['codigo']} - {p['nombre']}") for p in productos_activos],
        )
        descripcion_field = ft.TextField(label="Descripcion", width=200, visible=False)
        precio_libre_field = ft.TextField(label="Precio unit.", width=110, visible=False, input_filter=FILTRO_DECIMALES)
        cantidad_field = ft.TextField(label="Cantidad", width=100, hint_text="1,000", input_filter=FILTRO_DECIMALES)
        descuento_field = ft.TextField(label="% desc. (opcional)", width=130, input_filter=FILTRO_DECIMALES)
        info_texto = ft.Text("", size=12, color=ft.Colors.GREY_700, width=220)
        eliminar_button = ft.IconButton(ft.Icons.DELETE, tooltip="Quitar linea")

        def cambiar_tipo(e: ft.ControlEvent) -> None:
            es_libre = tipo_dropdown.value == TIPO_LIBRE
            producto_dropdown.visible = not es_libre
            descripcion_field.visible = es_libre
            precio_libre_field.visible = es_libre
            info_texto.value = ""
            page.update()

        def cambiar_producto(e: ft.ControlEvent) -> None:
            actualizar_info_linea(linea)
            page.update()

        async def submit_descripcion(e: ft.ControlEvent) -> None:
            await precio_libre_field.focus()

        async def submit_precio_libre(e: ft.ControlEvent) -> None:
            await cantidad_field.focus()

        async def submit_cantidad(e: ft.ControlEvent) -> None:
            await descuento_field.focus()

        async def submit_descuento(e: ft.ControlEvent) -> None:
            # Enter en el ultimo campo de la linea agrega la siguiente sola y le pasa el foco --
            # para poder cargar muchos items en fila sin soltar el teclado.
            agregar_linea_venta()
            if lineas_form:
                await lineas_form[-1]["producto_dropdown"].focus()

        tipo_dropdown.on_select = cambiar_tipo
        producto_dropdown.on_select = cambiar_producto
        descripcion_field.on_submit = submit_descripcion
        precio_libre_field.on_submit = submit_precio_libre
        cantidad_field.on_submit = submit_cantidad
        descuento_field.on_submit = submit_descuento

        fila = ft.Column([
            ft.Row([tipo_dropdown, producto_dropdown, descripcion_field, precio_libre_field,
                    cantidad_field, descuento_field, eliminar_button]),
            info_texto,
        ])
        linea = {
            "tipo_dropdown": tipo_dropdown, "producto_dropdown": producto_dropdown,
            "descripcion_field": descripcion_field, "precio_libre_field": precio_libre_field,
            "cantidad_field": cantidad_field, "descuento_field": descuento_field,
            "info_texto": info_texto, "fila": fila,
        }
        eliminar_button.on_click = lambda e: quitar_linea_venta(linea)
        return linea

    def actualizar_info_linea(linea: dict) -> None:
        if linea["tipo_dropdown"].value != TIPO_PRODUCTO or not linea["producto_dropdown"].value:
            linea["info_texto"].value = ""
            return
        producto = productos_service.obtener_producto(int(linea["producto_dropdown"].value))
        if producto is None:
            return
        lista_id = int(lista_precio_dropdown.value) if lista_precio_dropdown.value else None
        precio = (
            listas_precios_service.calcular_precio_producto(producto["id"], lista_id)
            if lista_id else producto["precio_venta"]
        )
        aviso_stock = ""
        if producto["stock_minimo"] > 0 and producto["stock_actual"] < producto["stock_minimo"]:
            aviso_stock = "  ⚠ bajo el minimo"
        linea["info_texto"].value = (
            f"Precio: {formatear_precio(precio)}   |   Stock disponible: {formatear_cantidad(producto['stock_actual'])}{aviso_stock}"
        )

    def refrescar_precios_lineas() -> None:
        for linea in lineas_form:
            actualizar_info_linea(linea)
        page.update()

    def agregar_linea_venta(e: ft.ControlEvent | None = None) -> None:
        lineas_form.append(crear_linea_venta())
        refrescar_lineas_venta()

    def quitar_linea_venta(linea: dict) -> None:
        lineas_form.remove(linea)
        refrescar_lineas_venta()

    def refrescar_lineas_venta() -> None:
        contenedor_lineas.controls = [l["fila"] for l in lineas_form]
        page.update()

    agregar_linea_button = ft.TextButton("+ Agregar linea", on_click=agregar_linea_venta)

    iva_field = ft.TextField(label="IVA % (opcional)", width=140, input_filter=FILTRO_DECIMALES)
    descuento_total_field = ft.TextField(label="Descuento sobre el total % (opcional)", width=220, input_filter=FILTRO_DECIMALES)
    observacion_field = ft.TextField(label="Observacion (opcional)", expand=True)

    subtotal_texto = ft.Text("", size=14)
    total_texto = ft.Text("", size=18, weight=ft.FontWeight.BOLD)
    calcular_total_button = ft.ElevatedButton("Calcular total")

    pagos_form: list[dict] = []
    contenedor_pagos = ft.Column([])
    total_actual = {"valor": None}

    def construir_items_desde_form() -> list[dict]:
        items = []
        for linea in lineas_form:
            cantidad = parsear_decimal_opcional(linea["cantidad_field"].value, "Cantidad")
            if cantidad is None:
                raise ValueError("Falta la cantidad de una linea")
            descuento = parsear_decimal_opcional(linea["descuento_field"].value, "% de descuento de linea")
            if linea["tipo_dropdown"].value == TIPO_LIBRE:
                descripcion = (linea["descripcion_field"].value or "").strip()
                if not descripcion:
                    raise ValueError("Completa la descripcion del item libre")
                precio = parsear_decimal_opcional(linea["precio_libre_field"].value, "Precio del item libre")
                if precio is None:
                    raise ValueError(f"El item libre '{descripcion}' necesita un precio")
                items.append({"producto_id": None, "descripcion_libre": descripcion, "cantidad": cantidad,
                              "precio_unitario": precio, "descuento_item_porcentaje": descuento})
            else:
                if not linea["producto_dropdown"].value:
                    raise ValueError("Elegi un producto para la linea")
                items.append({"producto_id": int(linea["producto_dropdown"].value), "descripcion_libre": None,
                              "cantidad": cantidad, "descuento_item_porcentaje": descuento})
        return items

    def crear_linea_pago() -> dict:
        medios = medios_pago_service.listar_medios_pago(solo_activos=True)
        medio_dropdown = ft.Dropdown(
            label="Medio de pago", width=180,
            options=[ft.dropdown.Option(key=str(m["id"]), text=m["nombre"]) for m in medios],
        )
        monto_field = ft.TextField(label="Monto", width=140, input_filter=FILTRO_DECIMALES)
        aplicar_mascara_moneda(monto_field)
        recibido_field = ft.TextField(label="Recibio (para vuelto, opcional)", width=180, input_filter=FILTRO_DECIMALES, visible=False)
        vuelto_texto = ft.Text("", size=12, color=ft.Colors.GREEN_700, visible=False)
        eliminar_button = ft.IconButton(ft.Icons.DELETE, tooltip="Quitar")

        def cambiar_medio(e: ft.ControlEvent) -> None:
            medio = next((m for m in medios if str(m["id"]) == medio_dropdown.value), None)
            es_efectivo = bool(medio) and "efectivo" in medio["nombre"].lower()
            recibido_field.visible = es_efectivo
            vuelto_texto.visible = es_efectivo
            page.update()

        def calcular_vuelto(e: ft.ControlEvent) -> None:
            recibido = parsear_decimal_ar_opcional(recibido_field.value, "Recibido")
            monto = parsear_decimal_ar_opcional(monto_field.value, "Monto")
            if recibido is not None and monto is not None and recibido >= monto:
                vuelto_texto.value = f"Vuelto: {formatear_precio(recibido - monto)}"
            else:
                vuelto_texto.value = ""
            page.update()

        async def submit_monto(e: ft.ControlEvent) -> None:
            # Si es efectivo, Enter pasa al campo de "recibio" para calcular el vuelto; si no,
            # ya no falta nada mas que tipear -- Enter confirma la venta directamente.
            if recibido_field.visible:
                await recibido_field.focus()
            else:
                confirmar_venta_click(None)

        def submit_recibido(e: ft.ControlEvent) -> None:
            confirmar_venta_click(None)

        medio_dropdown.on_select = cambiar_medio
        recibido_field.on_change = calcular_vuelto
        monto_field.on_change = calcular_vuelto
        monto_field.on_submit = submit_monto
        recibido_field.on_submit = submit_recibido

        fila = ft.Row([medio_dropdown, monto_field, recibido_field, vuelto_texto, eliminar_button])
        linea = {"medio_dropdown": medio_dropdown, "monto_field": monto_field, "fila": fila}
        eliminar_button.on_click = lambda e: quitar_linea_pago(linea)
        return linea

    def agregar_linea_pago(e: ft.ControlEvent | None = None) -> None:
        pagos_form.append(crear_linea_pago())
        refrescar_lineas_pago()

    def quitar_linea_pago(linea: dict) -> None:
        pagos_form.remove(linea)
        refrescar_lineas_pago()

    def refrescar_lineas_pago() -> None:
        contenedor_pagos.controls = [l["fila"] for l in pagos_form]
        page.update()

    agregar_pago_button = ft.TextButton("+ Agregar medio de pago", on_click=agregar_linea_pago)
    confirmar_venta_button = ft.ElevatedButton("Confirmar venta")

    def calcular_total_click(e: ft.ControlEvent) -> None:
        try:
            items = construir_items_desde_form()
            cliente_id = int(cliente_dropdown.value) if cliente_dropdown.value else None
            lista_id = int(lista_precio_dropdown.value) if lista_precio_dropdown.value else None
            iva = parsear_decimal_opcional(iva_field.value, "IVA")
            descuento_total = parsear_decimal_opcional(descuento_total_field.value, "Descuento sobre el total")

            # si el cliente es nuevo/generico, el % de descuento fijo se resuelve recien al confirmar;
            # para la previsualizacion (sin crear el cliente todavia) se usa 0 en ese caso.
            totales = ventas_service.previsualizar_totales(
                items, lista_precio_id=lista_id, cliente_id=cliente_id,
                descuento_total_porcentaje=descuento_total, iva_porcentaje=iva,
            )
            total_actual["valor"] = totales["total"]
            subtotal_texto.value = f"Subtotal: {formatear_precio(totales['subtotal'])}"
            total_texto.value = f"Total: {formatear_precio(totales['total'])}"
            seccion_pago.visible = True
            if not pagos_form:
                agregar_linea_pago()
            page.update()
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))

    calcular_total_button.on_click = calcular_total_click

    async def submit_iva(e: ft.ControlEvent) -> None:
        await descuento_total_field.focus()

    async def submit_descuento_total(e: ft.ControlEvent) -> None:
        await observacion_field.focus()

    def submit_observacion(e: ft.ControlEvent) -> None:
        calcular_total_click(None)

    iva_field.on_submit = submit_iva
    descuento_total_field.on_submit = submit_descuento_total
    observacion_field.on_submit = submit_observacion

    def confirmar_venta_click(e: ft.ControlEvent) -> None:
        try:
            if total_actual["valor"] is None:
                raise ValueError("Primero calcula el total")
            items = construir_items_desde_form()
            pagos = []
            for linea in pagos_form:
                if not linea["medio_dropdown"].value:
                    raise ValueError("Elegi un medio de pago en cada linea de pago")
                monto = parsear_decimal_ar_opcional(linea["monto_field"].value, "Monto del pago")
                if monto is None:
                    raise ValueError("Falta el monto de un medio de pago")
                pagos.append({"medio_pago_id": int(linea["medio_dropdown"].value), "monto": monto})

            cliente_id = int(cliente_dropdown.value) if cliente_dropdown.value else None
            lista_id = int(lista_precio_dropdown.value) if lista_precio_dropdown.value else None
            iva = parsear_decimal_opcional(iva_field.value, "IVA")
            descuento_total = parsear_decimal_opcional(descuento_total_field.value, "Descuento sobre el total")

            venta = ventas_service.crear_venta(
                items=items, pagos=pagos,
                cliente_id=cliente_id,
                cliente_nombre_nuevo=cliente_nuevo_field.value or None,
                usar_cliente_generico=cliente_generico_switch.value,
                lista_precio_id=lista_id,
                iva_porcentaje=iva,
                descuento_total_porcentaje=descuento_total,
                observacion=observacion_field.value,
            )
            mostrar_mensaje(f"{venta['numero']} confirmada - Total {formatear_precio(venta['total'])}")
            ir_a_detalle(venta["id"])
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))

    confirmar_venta_button.on_click = confirmar_venta_click

    seccion_pago = ft.Column(
        [
            ft.Text("Pago", weight=ft.FontWeight.BOLD),
            contenedor_pagos,
            agregar_pago_button,
            confirmar_venta_button,
        ],
        visible=False,
    )

    volver_lista_desde_form_button = ft.TextButton("Cancelar / Volver al listado", on_click=lambda e: ir_a_lista(None))

    seccion_formulario = ft.Column(
        [
            ft.Text("Nueva venta", size=18, weight=ft.FontWeight.BOLD),
            ft.Text(
                "Enter pasa al siguiente campo. F1 Calcular total | F3 Agregar linea | "
                "F2 Confirmar venta | F4 Agregar medio de pago",
                size=11, color=ft.Colors.GREY_600,
            ),
            ft.Row([cliente_dropdown, cliente_nuevo_field, cliente_generico_switch]),
            cliente_info_texto,
            lista_precio_dropdown,
            ft.Text("Lineas", weight=ft.FontWeight.BOLD),
            contenedor_lineas,
            agregar_linea_button,
            ft.Row([iva_field, descuento_total_field]),
            ft.Row([observacion_field]),
            ft.Row([calcular_total_button]),
            subtotal_texto,
            total_texto,
            seccion_pago,
            volver_lista_desde_form_button,
        ],
        visible=False,
        scroll=ft.ScrollMode.AUTO,
    )

    def ir_a_formulario() -> None:
        nonlocal productos_activos
        productos_activos = productos_service.listar_productos(solo_activos=True)
        cliente_dropdown.value = None
        cliente_nuevo_field.value = ""
        cliente_generico_switch.value = False
        cliente_info_texto.value = ""
        lista_precio_dropdown.options = [ft.dropdown.Option(key="", text="Sin lista (precio normal)")]
        lista_precio_dropdown.value = ""
        lineas_form.clear()
        refrescar_lineas_venta()
        agregar_linea_venta()
        iva_field.value = ""
        descuento_total_field.value = ""
        observacion_field.value = ""
        subtotal_texto.value = ""
        total_texto.value = ""
        total_actual["valor"] = None
        pagos_form.clear()
        refrescar_lineas_pago()
        seccion_pago.visible = False
        refrescar_dropdown_clientes()
        seccion_lista.visible = False
        seccion_formulario.visible = True
        seccion_detalle.visible = False
        page.update()

    # ================= SECCION DETALLE (venta confirmada) =================
    detalle_venta_id: int | None = None
    detalle_titulo = ft.Text("", size=18, weight=ft.FontWeight.BOLD)
    detalle_info = ft.Text("")
    tabla_detalle_items = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(t)) for t in ["Producto / Descripcion", "Cantidad", "Precio unit.", "% desc.", "Subtotal"]],
        rows=[],
    )
    tabla_detalle_pagos = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(t)) for t in ["Medio de pago", "Monto"]],
        rows=[],
    )
    detalle_total_texto = ft.Text("", size=18, weight=ft.FontWeight.BOLD)
    volver_detalle_button = ft.TextButton("Volver al listado", on_click=lambda e: ir_a_lista(None))

    def refrescar_detalle() -> None:
        venta = ventas_service.obtener_venta(detalle_venta_id)
        detalle_titulo.value = f"{venta['numero']} - {venta['cliente_nombre']}"
        detalle_info.value = (
            f"Fecha: {venta['fecha'][:16]}   |   Estado: {venta['estado'].capitalize()}   |   "
            f"IVA: {venta['iva_porcentaje'] if venta['iva_porcentaje'] is not None else '-'}%"
        )
        if venta["observacion"]:
            detalle_info.value += f"\nObservacion: {venta['observacion']}"
        def _subtotal_linea(i: dict) -> Decimal:
            monto = i["cantidad"] * i["precio_unitario"]
            if i["descuento_item_porcentaje"] is not None:
                monto = monto * (Decimal("1") - i["descuento_item_porcentaje"] / Decimal("100"))
            return monto.quantize(Decimal("1.00"))

        tabla_detalle_items.rows = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Text(i["descripcion_libre"] or f"{i['producto_codigo']} - {i['producto_nombre']}")),
                ft.DataCell(ft.Text(formatear_cantidad(i["cantidad"]))),
                ft.DataCell(ft.Text(formatear_precio(i["precio_unitario"]))),
                ft.DataCell(ft.Text(
                    f"{formatear_porcentaje(i['descuento_item_porcentaje'])}%"
                    if i["descuento_item_porcentaje"] is not None else "-"
                )),
                ft.DataCell(ft.Text(formatear_precio(_subtotal_linea(i)))),
            ])
            for i in venta["items"]
        ]
        tabla_detalle_pagos.rows = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Text(p["medio_pago_nombre"] + (" (cta. cte.)" if p["es_cuenta_corriente"] else ""))),
                ft.DataCell(ft.Text(formatear_precio(p["monto"]))),
            ])
            for p in venta["pagos"]
        ]
        detalle_total_texto.value = f"Total: {formatear_precio(venta['total'])}"
        page.update()

    seccion_detalle = ft.Column(
        [
            detalle_titulo,
            detalle_info,
            volver_detalle_button,
            ft.Text("Items", weight=ft.FontWeight.BOLD),
            tabla_detalle_items,
            ft.Text("Pagos", weight=ft.FontWeight.BOLD),
            tabla_detalle_pagos,
            detalle_total_texto,
        ],
        visible=False,
        scroll=ft.ScrollMode.AUTO,
    )

    # ================= NAVEGACION =================
    def ir_a_lista(e: ft.ControlEvent | None) -> None:
        seccion_lista.visible = True
        seccion_formulario.visible = False
        seccion_detalle.visible = False
        refrescar_lista()
        page.update()

    def ir_a_detalle(venta_id: int) -> None:
        nonlocal detalle_venta_id
        detalle_venta_id = venta_id
        seccion_lista.visible = False
        seccion_formulario.visible = False
        seccion_detalle.visible = True
        refrescar_detalle()
        page.update()

    # ================= ATAJOS DE TECLADO (F1-F4) =================
    # Ojo: page.on_keyboard_event es global a la Page compartida por toda la app, no exclusivo de
    # esta pantalla -- app_shell.py lo resetea a None al navegar a otra pantalla del menu, si no
    # estas teclas seguirian disparando acciones de Ventas en cualquier otro lado.
    def manejar_teclado(e: ft.KeyboardEvent) -> None:
        if not seccion_formulario.visible:
            return
        tecla = (e.key or "").upper()
        if tecla == "F1":
            calcular_total_click(None)
        elif tecla == "F2" and seccion_pago.visible:
            confirmar_venta_click(None)
        elif tecla == "F3" and not seccion_pago.visible:
            agregar_linea_venta(None)
        elif tecla == "F4" and seccion_pago.visible:
            agregar_linea_pago(None)

    page.on_keyboard_event = manejar_teclado

    refrescar_lista()

    return ft.Column(
        [seccion_lista, seccion_formulario, seccion_detalle],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
