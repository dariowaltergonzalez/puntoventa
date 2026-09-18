from datetime import date
from decimal import Decimal, InvalidOperation

import flet as ft

from app.services import categorias_service, ordenes_compra_service, productos_service, proveedores_service, recepciones_service
from app.services.exceptions import (
    CodigoDuplicadoError,
    LineasVaciasError,
    OrdenCompraCanceladaError,
    OrdenCompraNoEditableError,
    OrdenCompraNoEncontradaError,
    ProductoInactivoError,
    ProductoNoEncontradoError,
    ProveedorNoEncontradoError,
)
from app.shared.money import formatear_cantidad, formatear_precio
from app.ui.listados import Paginador, coincide_exacto, coincide_texto, filtrar

TIPO_EXISTENTE = "Producto existente"
TIPO_NUEVO = "Producto nuevo"
TIPO_LIBRE = "Item libre"

ESTADOS_LABEL = {
    "pendiente": "Pendiente",
    "recibida_parcial": "Recibida parcial",
    "recibida": "Recibida",
    "cancelada": "Cancelada",
}

EXCEPCIONES_NEGOCIO = (
    LineasVaciasError,
    OrdenCompraCanceladaError,
    OrdenCompraNoEditableError,
    OrdenCompraNoEncontradaError,
    ProductoInactivoError,
    ProductoNoEncontradoError,
    ProveedorNoEncontradoError,
    CodigoDuplicadoError,
    ValueError,
)


def OrdenesCompraView(page: ft.Page) -> ft.Control:
    def mostrar_mensaje(texto: str) -> None:
        page.show_dialog(ft.SnackBar(ft.Text(texto)))

    def parsear_decimal(valor: str | None, etiqueta: str) -> Decimal:
        try:
            return Decimal((valor or "0").replace(",", "."))
        except InvalidOperation as exc:
            raise ValueError(f"'{etiqueta}' no es un numero valido") from exc

    # ================= Estado interno =================
    editando_oc_id: int | None = None
    detalle_oc_id: int | None = None
    lineas_form: list[dict] = []
    lineas_extra_recepcion: list[dict] = []

    # ================= Constructores de linea =================
    def crear_linea_pedido() -> dict:
        productos_options = [
            ft.dropdown.Option(key=str(p["id"]), text=f"{p['codigo']} - {p['nombre']}")
            for p in productos_service.listar_productos(solo_activos=True)
        ]
        categorias_options = [ft.dropdown.Option(key="", text="Sin elegir")] + [
            ft.dropdown.Option(key=str(c["id"]), text=c["nombre"]) for c in categorias_service.listar_categorias()
        ]
        tipo_dropdown = ft.Dropdown(
            label="Tipo", width=170,
            options=[ft.dropdown.Option(TIPO_EXISTENTE), ft.dropdown.Option(TIPO_NUEVO), ft.dropdown.Option(TIPO_LIBRE)],
            value=TIPO_EXISTENTE,
        )
        producto_dropdown = ft.Dropdown(label="Producto", width=220, options=productos_options)
        codigo_field = ft.TextField(label="Codigo nuevo", width=110, visible=False)
        nombre_field = ft.TextField(label="Nombre nuevo", width=170, visible=False)
        categoria_dropdown = ft.Dropdown(label="Categoria (opcional)", width=150, visible=False, options=categorias_options, value="")
        descripcion_field = ft.TextField(label="Descripcion", width=220, visible=False)
        cantidad_field = ft.TextField(label="Cantidad", width=100, hint_text="10,000")
        costo_field = ft.TextField(label="Costo unit.", width=100, hint_text="5,00")
        eliminar_button = ft.IconButton(ft.Icons.DELETE, tooltip="Quitar linea")

        def cambiar_tipo(e: ft.ControlEvent) -> None:
            tipo = tipo_dropdown.value
            producto_dropdown.visible = tipo == TIPO_EXISTENTE
            codigo_field.visible = tipo == TIPO_NUEVO
            nombre_field.visible = tipo == TIPO_NUEVO
            categoria_dropdown.visible = tipo == TIPO_NUEVO
            descripcion_field.visible = tipo == TIPO_LIBRE
            page.update()

        tipo_dropdown.on_select = cambiar_tipo

        fila = ft.Row([tipo_dropdown, producto_dropdown, codigo_field, nombre_field, categoria_dropdown,
                       descripcion_field, cantidad_field, costo_field, eliminar_button])
        linea = {
            "tipo_dropdown": tipo_dropdown, "producto_dropdown": producto_dropdown,
            "codigo_field": codigo_field, "nombre_field": nombre_field, "categoria_dropdown": categoria_dropdown,
            "descripcion_field": descripcion_field, "cantidad_field": cantidad_field,
            "costo_field": costo_field, "fila": fila,
        }
        eliminar_button.on_click = lambda e: quitar_linea_pedido(linea)
        return linea

    def agregar_linea_pedido(e: ft.ControlEvent | None = None) -> None:
        lineas_form.append(crear_linea_pedido())
        refrescar_lineas_pedido()

    def quitar_linea_pedido(linea: dict) -> None:
        lineas_form.remove(linea)
        refrescar_lineas_pedido()

    def refrescar_lineas_pedido() -> None:
        contenedor_lineas_pedido.controls = [l["fila"] for l in lineas_form]
        page.update()

    def construir_producto_nuevo_pedido(linea: dict) -> dict:
        categoria_id = int(linea["categoria_dropdown"].value) if linea["categoria_dropdown"].value else None
        return {
            "codigo": (linea["codigo_field"].value or "").strip(),
            "nombre": (linea["nombre_field"].value or "").strip(),
            "categoria_id": categoria_id,
        }

    def construir_items_pedido() -> list[dict]:
        items = []
        for linea in lineas_form:
            cantidad = parsear_decimal(linea["cantidad_field"].value, "Cantidad")
            costo = parsear_decimal(linea["costo_field"].value, "Costo unitario")
            tipo = linea["tipo_dropdown"].value
            if tipo == TIPO_LIBRE:
                descripcion = (linea["descripcion_field"].value or "").strip()
                if not descripcion:
                    raise ValueError("Completa la descripcion del item libre")
                items.append({"producto_id": None, "producto_nuevo": None, "descripcion_libre": descripcion,
                              "cantidad_pedida": cantidad, "costo_pactado": costo})
            elif tipo == TIPO_NUEVO:
                items.append({"producto_id": None, "producto_nuevo": construir_producto_nuevo_pedido(linea),
                              "descripcion_libre": None, "cantidad_pedida": cantidad, "costo_pactado": costo})
            else:
                if not linea["producto_dropdown"].value:
                    raise ValueError("Elegi un producto para la linea")
                items.append({"producto_id": int(linea["producto_dropdown"].value), "producto_nuevo": None,
                              "descripcion_libre": None, "cantidad_pedida": cantidad, "costo_pactado": costo})
        return items

    def construir_items_recepcion_desde_pedido() -> list[dict]:
        """Para 'ya la tenes en mano': la recepcion es 1 a 1 con lo pedido (misma cantidad/costo)."""
        items = []
        for linea in lineas_form:
            cantidad = parsear_decimal(linea["cantidad_field"].value, "Cantidad")
            costo = parsear_decimal(linea["costo_field"].value, "Costo unitario")
            tipo = linea["tipo_dropdown"].value
            if tipo == TIPO_LIBRE:
                items.append({"producto_id": None, "producto_nuevo": None,
                              "descripcion_libre": (linea["descripcion_field"].value or "").strip(),
                              "cantidad_recibida": cantidad, "costo_unitario": costo})
            elif tipo == TIPO_NUEVO:
                items.append({"producto_id": None, "producto_nuevo": construir_producto_nuevo_pedido(linea),
                              "descripcion_libre": None, "cantidad_recibida": cantidad, "costo_unitario": costo})
            else:
                items.append({"producto_id": int(linea["producto_dropdown"].value), "producto_nuevo": None,
                              "descripcion_libre": None, "cantidad_recibida": cantidad, "costo_unitario": costo})
        return items

    def crear_linea_extra_recepcion() -> dict:
        productos_options = [
            ft.dropdown.Option(key=str(p["id"]), text=f"{p['codigo']} - {p['nombre']}")
            for p in productos_service.listar_productos(solo_activos=True)
        ]
        categorias_options = [ft.dropdown.Option(key="", text="Sin elegir")] + [
            ft.dropdown.Option(key=str(c["id"]), text=c["nombre"]) for c in categorias_service.listar_categorias()
        ]
        tipo_dropdown = ft.Dropdown(
            label="Tipo", width=170,
            options=[ft.dropdown.Option(TIPO_EXISTENTE), ft.dropdown.Option(TIPO_NUEVO), ft.dropdown.Option(TIPO_LIBRE)],
            value=TIPO_EXISTENTE,
        )
        producto_dropdown = ft.Dropdown(label="Producto", width=200, options=productos_options)
        codigo_field = ft.TextField(label="Codigo nuevo", width=110, visible=False)
        nombre_field = ft.TextField(label="Nombre nuevo", width=170, visible=False)
        categoria_dropdown = ft.Dropdown(label="Categoria (opcional)", width=150, visible=False, options=categorias_options, value="")
        descripcion_field = ft.TextField(label="Descripcion", width=200, visible=False)
        cantidad_field = ft.TextField(label="Cant. recibida", width=100, hint_text="5,000")
        costo_field = ft.TextField(label="Costo real", width=100, hint_text="5,00")
        eliminar_button = ft.IconButton(ft.Icons.DELETE, tooltip="Quitar linea")

        def cambiar_tipo(e: ft.ControlEvent) -> None:
            tipo = tipo_dropdown.value
            producto_dropdown.visible = tipo == TIPO_EXISTENTE
            codigo_field.visible = tipo == TIPO_NUEVO
            nombre_field.visible = tipo == TIPO_NUEVO
            categoria_dropdown.visible = tipo == TIPO_NUEVO
            descripcion_field.visible = tipo == TIPO_LIBRE
            page.update()

        tipo_dropdown.on_select = cambiar_tipo

        fila = ft.Row([tipo_dropdown, producto_dropdown, codigo_field, nombre_field, categoria_dropdown,
                       descripcion_field, cantidad_field, costo_field, eliminar_button])
        linea = {
            "tipo_dropdown": tipo_dropdown, "producto_dropdown": producto_dropdown,
            "codigo_field": codigo_field, "nombre_field": nombre_field, "categoria_dropdown": categoria_dropdown,
            "descripcion_field": descripcion_field, "cantidad_field": cantidad_field,
            "costo_field": costo_field, "fila": fila,
        }
        eliminar_button.on_click = lambda e: quitar_linea_extra(linea)
        return linea

    def agregar_linea_extra(e: ft.ControlEvent | None = None) -> None:
        lineas_extra_recepcion.append(crear_linea_extra_recepcion())
        refrescar_lineas_extra()

    def quitar_linea_extra(linea: dict) -> None:
        lineas_extra_recepcion.remove(linea)
        refrescar_lineas_extra()

    def refrescar_lineas_extra() -> None:
        contenedor_lineas_extra.controls = [l["fila"] for l in lineas_extra_recepcion]
        page.update()

    def construir_item_extra(linea: dict) -> dict | None:
        cantidad_texto = (linea["cantidad_field"].value or "").strip()
        if not cantidad_texto:
            return None
        cantidad = parsear_decimal(cantidad_texto, "Cantidad")
        if cantidad <= 0:
            return None
        costo = parsear_decimal(linea["costo_field"].value, "Costo real")
        tipo = linea["tipo_dropdown"].value
        if tipo == TIPO_LIBRE:
            descripcion = (linea["descripcion_field"].value or "").strip()
            if not descripcion:
                raise ValueError("Completa la descripcion del item libre")
            return {"orden_compra_item_id": None, "producto_id": None, "producto_nuevo": None,
                    "descripcion_libre": descripcion, "cantidad_recibida": cantidad, "costo_unitario": costo}
        if tipo == TIPO_NUEVO:
            codigo = (linea["codigo_field"].value or "").strip()
            nombre = (linea["nombre_field"].value or "").strip()
            categoria_id = int(linea["categoria_dropdown"].value) if linea["categoria_dropdown"].value else None
            return {"orden_compra_item_id": None, "producto_id": None,
                    "producto_nuevo": {"codigo": codigo, "nombre": nombre, "categoria_id": categoria_id},
                    "descripcion_libre": None, "cantidad_recibida": cantidad, "costo_unitario": costo}
        if not linea["producto_dropdown"].value:
            raise ValueError("Elegi un producto para la linea extra")
        return {"orden_compra_item_id": None, "producto_id": int(linea["producto_dropdown"].value),
                "producto_nuevo": None, "descripcion_libre": None, "cantidad_recibida": cantidad, "costo_unitario": costo}

    # ================= SECCION LISTA =================
    estado_filtro_dropdown = ft.Dropdown(
        label="Filtrar por estado", width=220,
        options=[ft.dropdown.Option(key="", text="Todas")] + [
            ft.dropdown.Option(key=k, text=v) for k, v in ESTADOS_LABEL.items()
        ],
        value="",
    )
    buscador_field = ft.TextField(label="Buscar por numero o proveedor", width=280)
    contador_texto = ft.Text("")
    nueva_oc_button = ft.ElevatedButton("+ Nueva orden de compra")
    imprimir_button = ft.ElevatedButton(
        "Imprimir", icon=ft.Icons.PRINT,
        on_click=lambda e: mostrar_mensaje("La exportacion a PDF va a estar disponible en una fase futura"),
    )

    _ANCHOS_COLUMNAS_LISTA = [90, 160, 130, 90, 90, 60, 110]
    _TITULOS_COLUMNAS_LISTA = ["Numero", "Proveedor", "Estado", "Fecha", "F. estimada", "IVA %", "Total estimado"]
    encabezado_lista = ft.Row(
        [
            ft.Container(ft.Text(t, weight=ft.FontWeight.BOLD), width=w)
            for t, w in zip(_TITULOS_COLUMNAS_LISTA, _ANCHOS_COLUMNAS_LISTA)
        ]
        + [ft.Container(width=40)]
    )
    lista_filas = ft.Column([])

    def nombre_proveedor(proveedor_id: int) -> str:
        proveedor = proveedores_service.obtener_proveedor(proveedor_id)
        return proveedor["nombre"] if proveedor else "?"

    def costo_real_texto(item: dict) -> ft.Text:
        costo_real = item["costo_real_promedio"]
        if costo_real is None:
            return ft.Text("-")
        difiere = costo_real != item["costo_pactado"]
        return ft.Text(
            formatear_precio(costo_real),
            color=ft.Colors.ORANGE if difiere else None,
            weight=ft.FontWeight.BOLD if difiere else None,
        )

    def construir_fila_oc(oc: dict) -> ft.ExpansionTile:
        valores = [
            oc["numero"],
            nombre_proveedor(oc["proveedor_id"]),
            ESTADOS_LABEL.get(oc["estado"], oc["estado"]),
            oc["fecha_creacion"][:10],
            oc["fecha_estimada"] or "-",
            str(oc["iva_porcentaje"]) if oc["iva_porcentaje"] is not None else "-",
            formatear_precio(oc["total_estimado"]),
        ]
        celdas = [ft.Container(ft.Text(v), width=w) for v, w in zip(valores, _ANCHOS_COLUMNAS_LISTA)]
        if oc["recibida_en_el_acto"]:
            celdas[0] = ft.Container(
                ft.Row([
                    ft.Text(oc["numero"]),
                    ft.Icon(ft.Icons.BOLT, size=16, color=ft.Colors.AMBER_700,
                            tooltip="Creada y recibida en el acto (\"ya la tenes en mano\")"),
                ], spacing=2, tight=True),
                width=_ANCHOS_COLUMNAS_LISTA[0],
            )
        titulo = ft.Row(
            celdas
            + [ft.IconButton(ft.Icons.VISIBILITY, tooltip="Ver detalle / acciones", data=oc["id"],
                              on_click=lambda e: ir_a_detalle(e.control.data))]
        )
        items_tabla = ft.DataTable(
            columns=[ft.DataColumn(ft.Text(t)) for t in
                     ["Producto / Descripcion", "Cant. pedida", "Costo pactado", "Cant. recibida", "Costo real (prom.)"]],
            rows=[
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(item["descripcion_libre"] or f"{item['producto_codigo']} - {item['producto_nombre']}")),
                    ft.DataCell(ft.Text(formatear_cantidad(item["cantidad_pedida"]))),
                    ft.DataCell(ft.Text(formatear_precio(item["costo_pactado"]))),
                    ft.DataCell(ft.Text(formatear_cantidad(item["cantidad_recibida"]))),
                    ft.DataCell(costo_real_texto(item)),
                ])
                for item in oc["items"]
            ],
        )
        return ft.ExpansionTile(
            title=titulo,
            controls=[items_tabla],
            tile_padding=ft.Padding.symmetric(horizontal=4, vertical=2),
            affinity=ft.TileAffinity.LEADING,
        )

    def refrescar_lista(e: ft.ControlEvent | None = None) -> None:
        todas = ordenes_compra_service.listar_ordenes_compra()
        pendientes = sum(1 for o in todas if o["estado"] == "pendiente")
        parciales = sum(1 for o in todas if o["estado"] == "recibida_parcial")
        recibidas = sum(1 for o in todas if o["estado"] == "recibida")
        canceladas = sum(1 for o in todas if o["estado"] == "cancelada")
        contador_texto.value = (
            f"Pendientes: {pendientes}   |   Recibidas parcial: {parciales}   |   "
            f"Recibidas: {recibidas}   |   Canceladas: {canceladas}"
        )

        def texto_busqueda_oc(oc: dict) -> str:
            return f"{oc['numero']} {nombre_proveedor(oc['proveedor_id'])}"

        filtradas = filtrar(todas, [
            lambda o: coincide_exacto(o["estado"], estado_filtro_dropdown.value or None),
            lambda o: coincide_texto(texto_busqueda_oc(o), buscador_field.value),
        ])
        pagina = paginador.aplicar(filtradas)
        lista_filas.controls = [construir_fila_oc(o) for o in pagina]
        page.update()

    paginador = Paginador(on_cambio=refrescar_lista)
    estado_filtro_dropdown.on_select = refrescar_lista
    buscador_field.on_change = refrescar_lista
    nueva_oc_button.on_click = lambda e: ir_a_formulario(None)

    seccion_lista = ft.Column(
        [
            ft.Text("Ordenes de Compra", size=20, weight=ft.FontWeight.BOLD),
            ft.Row([estado_filtro_dropdown, buscador_field, imprimir_button, nueva_oc_button]),
            contador_texto,
            encabezado_lista,
            ft.Divider(height=1),
            lista_filas,
            paginador.controles,
        ],
        visible=True,
    )

    # ================= SECCION FORMULARIO (alta/edicion) =================
    form_titulo = ft.Text("Nueva orden de compra", size=18, weight=ft.FontWeight.BOLD)
    proveedor_dropdown = ft.Dropdown(label="Proveedor existente", width=250, options=[])
    proveedor_nuevo_field = ft.TextField(label="O escribi un proveedor nuevo", width=250)
    proveedor_generico_switch = ft.Switch(label="Usar proveedor generico")
    fecha_estimada_field = ft.TextField(label="Fecha estimada de entrega (opcional)", width=220, hint_text="AAAA-MM-DD")
    iva_field = ft.TextField(label="IVA % (opcional)", width=120)
    observacion_field = ft.TextField(label="Observacion (opcional)", expand=True)
    contenedor_lineas_pedido = ft.Column([])
    agregar_linea_button = ft.TextButton("+ Agregar linea", on_click=agregar_linea_pedido)

    ya_en_mano_switch = ft.Switch(label="¿Ya la tenes en mano? (se recibe en el acto)")
    remito_field = ft.TextField(label="Numero de remito (opcional)", width=220, visible=False)
    recepcion_observacion_field = ft.TextField(label="Observacion de la recepcion (opcional)", expand=True, visible=False)
    recepcion_a_credito_switch = ft.Switch(
        label="Esta compra queda a credito (genera cargo en Cuentas Corrientes)", visible=False,
    )

    def toggle_ya_en_mano(e: ft.ControlEvent) -> None:
        remito_field.visible = ya_en_mano_switch.value
        recepcion_observacion_field.visible = ya_en_mano_switch.value
        recepcion_a_credito_switch.visible = ya_en_mano_switch.value
        if ya_en_mano_switch.value and not fecha_estimada_field.value:
            fecha_estimada_field.value = date.today().isoformat()
        page.update()

    ya_en_mano_switch.on_change = toggle_ya_en_mano

    guardar_form_texto = ft.Text("Crear orden de compra")
    guardar_form_button = ft.ElevatedButton(content=guardar_form_texto)
    cancelar_form_button = ft.TextButton("Cancelar", on_click=lambda e: ir_a_lista(None))

    def limpiar_formulario() -> None:
        nonlocal editando_oc_id
        editando_oc_id = None
        lineas_form.clear()
        refrescar_lineas_pedido()
        proveedor_dropdown.options = [
            ft.dropdown.Option(key=str(p["id"]), text=p["nombre"]) for p in proveedores_service.listar_proveedores(solo_activos=True)
        ]
        proveedor_dropdown.value = None
        proveedor_nuevo_field.value = ""
        proveedor_generico_switch.value = False
        fecha_estimada_field.value = ""
        iva_field.value = ""
        observacion_field.value = ""
        ya_en_mano_switch.value = False
        ya_en_mano_switch.visible = True
        remito_field.value = ""
        remito_field.visible = False
        recepcion_observacion_field.value = ""
        recepcion_observacion_field.visible = False
        recepcion_a_credito_switch.value = False
        recepcion_a_credito_switch.visible = False
        guardar_form_texto.value = "Crear orden de compra"
        form_titulo.value = "Nueva orden de compra"
        agregar_linea_pedido()

    def guardar_formulario(e: ft.ControlEvent) -> None:
        try:
            items = construir_items_pedido()
            proveedor_id = int(proveedor_dropdown.value) if proveedor_dropdown.value else None
            proveedor_nombre_nuevo = proveedor_nuevo_field.value or None
            usar_generico = proveedor_generico_switch.value
            fecha_estimada = (fecha_estimada_field.value or "").strip() or None
            iva_texto = (iva_field.value or "").strip()
            iva = Decimal(iva_texto.replace(",", ".")) if iva_texto else None
            observacion = observacion_field.value

            if editando_oc_id is not None:
                ordenes_compra_service.actualizar_orden_compra(
                    orden_compra_id=editando_oc_id, items=items,
                    proveedor_id=proveedor_id, proveedor_nombre_nuevo=proveedor_nombre_nuevo,
                    usar_proveedor_generico=usar_generico, fecha_estimada=fecha_estimada,
                    iva_porcentaje=iva, observacion=observacion,
                )
                mostrar_mensaje("Orden de compra actualizada")
                ir_a_detalle(editando_oc_id)
                return

            if ya_en_mano_switch.value:
                items_recepcion = construir_items_recepcion_desde_pedido()
                oc = ordenes_compra_service.crear_orden_compra_recibida(
                    items=items, recepcion_items=items_recepcion,
                    proveedor_id=proveedor_id, proveedor_nombre_nuevo=proveedor_nombre_nuevo,
                    usar_proveedor_generico=usar_generico, fecha_estimada=fecha_estimada,
                    iva_porcentaje=iva, observacion=observacion,
                    recepcion_numero_remito=remito_field.value, recepcion_observacion=recepcion_observacion_field.value,
                    a_credito=recepcion_a_credito_switch.value,
                )
            else:
                oc = ordenes_compra_service.crear_orden_compra(
                    items=items, proveedor_id=proveedor_id, proveedor_nombre_nuevo=proveedor_nombre_nuevo,
                    usar_proveedor_generico=usar_generico, fecha_estimada=fecha_estimada,
                    iva_porcentaje=iva, observacion=observacion,
                )
            mostrar_mensaje(f"{oc['numero']} creada (estado: {ESTADOS_LABEL.get(oc['estado'], oc['estado'])})")
            ir_a_detalle(oc["id"])
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))

    guardar_form_button.on_click = guardar_formulario

    seccion_formulario = ft.Column(
        [
            form_titulo,
            ft.Row([proveedor_dropdown, proveedor_nuevo_field, proveedor_generico_switch]),
            ft.Row([fecha_estimada_field, iva_field]),
            ft.Row([observacion_field]),
            ft.Text("Lineas", weight=ft.FontWeight.BOLD),
            contenedor_lineas_pedido,
            agregar_linea_button,
            ya_en_mano_switch,
            ft.Row([remito_field, recepcion_observacion_field]),
            recepcion_a_credito_switch,
            ft.Row([guardar_form_button, cancelar_form_button]),
        ],
        visible=False,
        scroll=ft.ScrollMode.AUTO,
    )

    def ir_a_formulario(oc_id: int | None) -> None:
        nonlocal editando_oc_id
        limpiar_formulario()
        if oc_id is not None:
            editando_oc_id = oc_id
            oc = ordenes_compra_service.obtener_orden_compra(oc_id)
            form_titulo.value = f"Editar {oc['numero']}"
            guardar_form_texto.value = "Guardar cambios"
            proveedor_dropdown.value = str(oc["proveedor_id"])
            fecha_estimada_field.value = oc["fecha_estimada"] or ""
            iva_field.value = str(oc["iva_porcentaje"]) if oc["iva_porcentaje"] is not None else ""
            observacion_field.value = oc["observacion"] or ""
            ya_en_mano_switch.visible = False
            lineas_form.clear()
            for item in oc["items"]:
                linea = crear_linea_pedido()
                if item["descripcion_libre"] is not None:
                    linea["tipo_dropdown"].value = TIPO_LIBRE
                    linea["producto_dropdown"].visible = False
                    linea["descripcion_field"].visible = True
                    linea["descripcion_field"].value = item["descripcion_libre"]
                else:
                    linea["producto_dropdown"].value = str(item["producto_id"])
                linea["cantidad_field"].value = str(item["cantidad_pedida"])
                linea["costo_field"].value = str(item["costo_pactado"])
                lineas_form.append(linea)
            refrescar_lineas_pedido()
        seccion_lista.visible = False
        seccion_formulario.visible = True
        seccion_detalle.visible = False
        page.update()

    # ================= SECCION DETALLE =================
    detalle_titulo = ft.Text("", size=18, weight=ft.FontWeight.BOLD)
    detalle_info = ft.Text("")
    tabla_items_oc = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(t)) for t in
                 ["Producto / Descripcion", "Cant. pedida", "Costo pactado", "Cant. recibida", "Costo real (prom.)", ""]],
        rows=[],
    )
    contenedor_recepciones = ft.Column([])

    editar_oc_button = ft.ElevatedButton("Editar")
    cancelar_oc_button = ft.ElevatedButton("Cancelar orden", bgcolor=ft.Colors.RED_100)
    registrar_recepcion_button = ft.ElevatedButton("Registrar recepcion")
    dar_por_recibida_button = ft.ElevatedButton("Dar por recibida")
    volver_lista_button = ft.TextButton("Volver al listado", on_click=lambda e: ir_a_lista(None))

    motivo_cancelacion_field = ft.TextField(label="Motivo de la cancelacion", visible=False, expand=True)
    confirmar_cancelacion_button = ft.ElevatedButton("Confirmar cancelacion", visible=False)

    motivo_cierre_field = ft.TextField(label="Motivo del cierre manual", visible=False, expand=True)
    confirmar_cierre_button = ft.ElevatedButton("Confirmar cierre manual", visible=False)

    seccion_recepcion_numero_remito = ft.TextField(label="Numero de remito (opcional)", width=220)
    seccion_recepcion_observacion = ft.TextField(label="Observacion (opcional)", expand=True)
    seccion_recepcion_a_credito_switch = ft.Switch(label="Esta compra queda a credito (genera cargo en Cuentas Corrientes)")
    contenedor_pendientes_recepcion = ft.Column([])
    contenedor_lineas_extra = ft.Column([])
    agregar_extra_button = ft.TextButton("+ Agregar item extra (no pedido)", on_click=agregar_linea_extra)
    confirmar_recepcion_button = ft.ElevatedButton("Confirmar recepcion")
    seccion_recepcion = ft.Column(
        [
            ft.Text("Registrar recepcion", weight=ft.FontWeight.BOLD),
            ft.Text("Cantidad pendiente de recibir por linea (dejar en 0 lo que no llega ahora):"),
            contenedor_pendientes_recepcion,
            ft.Text("Items extra (no pedidos):"),
            contenedor_lineas_extra,
            agregar_extra_button,
            ft.Row([seccion_recepcion_numero_remito, seccion_recepcion_observacion]),
            seccion_recepcion_a_credito_switch,
            confirmar_recepcion_button,
        ],
        visible=False,
    )
    campos_pendientes: list[dict] = []

    def refrescar_detalle() -> None:
        oc = ordenes_compra_service.obtener_orden_compra(detalle_oc_id)
        detalle_titulo.value = f"{oc['numero']} - {nombre_proveedor(oc['proveedor_id'])}"
        detalle_info.value = (
            ("Creada y recibida en el acto   |   " if oc["recibida_en_el_acto"] else "")
            + f"Estado: {ESTADOS_LABEL.get(oc['estado'], oc['estado'])}   |   "
            f"Fecha: {oc['fecha_creacion'][:10]}   |   "
            f"F. estimada: {oc['fecha_estimada'] or '-'}   |   "
            f"IVA: {oc['iva_porcentaje'] if oc['iva_porcentaje'] is not None else '-'}%   |   "
            f"Total estimado: {formatear_precio(oc['total_estimado'])}"
        )
        if oc["observacion"]:
            detalle_info.value += f"\nObservacion: {oc['observacion']}"

        tabla_items_oc.rows = []
        for item in oc["items"]:
            nombre = item["descripcion_libre"] or f"{item['producto_codigo']} - {item['producto_nombre']}"
            recibida_excede = item["cantidad_recibida"] > item["cantidad_pedida"]
            tabla_items_oc.rows.append(
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(nombre)),
                    ft.DataCell(ft.Text(formatear_cantidad(item["cantidad_pedida"]))),
                    ft.DataCell(ft.Text(formatear_precio(item["costo_pactado"]))),
                    ft.DataCell(ft.Text(
                        formatear_cantidad(item["cantidad_recibida"]),
                        color=ft.Colors.ORANGE if recibida_excede else None,
                        weight=ft.FontWeight.BOLD if recibida_excede else None,
                    )),
                    ft.DataCell(costo_real_texto(item)),
                    ft.DataCell(ft.Text("")),
                ])
            )

        recepciones = recepciones_service.listar_recepciones_de_orden(detalle_oc_id)
        contenedor_recepciones.controls = []
        for r in recepciones:
            items_r = recepciones_service.listar_items_recepcion(r["id"])
            tabla_items_r = ft.DataTable(
                columns=[ft.DataColumn(ft.Text(t)) for t in
                         ["Producto / Descripcion", "Cantidad", "Costo real", "Subtotal", ""]],
                rows=[
                    ft.DataRow(cells=[
                        ft.DataCell(ft.Text(
                            item["descripcion_libre"] or f"{item['producto_codigo']} - {item['producto_nombre']}"
                        )),
                        ft.DataCell(ft.Text(formatear_cantidad(item["cantidad_recibida"]))),
                        ft.DataCell(ft.Text(formatear_precio(item["costo_unitario"]))),
                        ft.DataCell(ft.Text(formatear_precio(item["subtotal"]))),
                        ft.DataCell(
                            ft.Text("No pedido", color=ft.Colors.ORANGE, weight=ft.FontWeight.BOLD)
                            if item["orden_compra_item_id"] is None
                            else ft.Text("")
                        ),
                    ])
                    for item in items_r
                ],
            )
            contenedor_recepciones.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Text(
                            f"{r['fecha'][:16]}   |   Remito: {r['numero_remito'] or '-'}"
                            + (f"   |   {r['observacion']}" if r["observacion"] else "")
                        ),
                        tabla_items_r,
                    ]),
                    padding=ft.Padding.symmetric(vertical=8),
                )
            )

        editar_oc_button.visible = oc["estado"] == "pendiente" and not recepciones
        cancelar_oc_button.visible = oc["estado"] in ("pendiente", "recibida_parcial")
        registrar_recepcion_button.visible = oc["estado"] in ("pendiente", "recibida_parcial")
        dar_por_recibida_button.visible = oc["estado"] == "recibida_parcial"

        motivo_cancelacion_field.visible = False
        confirmar_cancelacion_button.visible = False
        motivo_cierre_field.visible = False
        confirmar_cierre_button.visible = False
        seccion_recepcion.visible = False

        page.update()

    def preparar_seccion_recepcion() -> None:
        oc = ordenes_compra_service.obtener_orden_compra(detalle_oc_id)
        campos_pendientes.clear()
        filas_pendientes = []
        for item in oc["items"]:
            pendiente = item["cantidad_pedida"] - item["cantidad_recibida"]
            if pendiente <= 0:
                continue
            nombre = item["descripcion_libre"] or f"{item['producto_codigo']} - {item['producto_nombre']}"
            cantidad_field = ft.TextField(label="Cant. a recibir", width=120, value=str(pendiente))
            costo_field = ft.TextField(label="Costo real", width=120, value=str(item["costo_pactado"]))
            campos_pendientes.append({
                "orden_compra_item_id": item["id"], "producto_id": item["producto_id"],
                "descripcion_libre": item["descripcion_libre"],
                "cantidad_field": cantidad_field, "costo_field": costo_field,
            })
            filas_pendientes.append(ft.Row([ft.Text(nombre, width=250), cantidad_field, costo_field]))
        contenedor_pendientes_recepcion.controls = filas_pendientes
        lineas_extra_recepcion.clear()
        refrescar_lineas_extra()
        seccion_recepcion_numero_remito.value = ""
        seccion_recepcion_observacion.value = ""
        seccion_recepcion_a_credito_switch.value = False
        seccion_recepcion.visible = True
        page.update()

    def confirmar_recepcion_click(e: ft.ControlEvent) -> None:
        try:
            items = []
            for campo in campos_pendientes:
                cantidad_texto = (campo["cantidad_field"].value or "").strip()
                if not cantidad_texto:
                    continue
                cantidad = parsear_decimal(cantidad_texto, "Cantidad a recibir")
                if cantidad <= 0:
                    continue
                costo = parsear_decimal(campo["costo_field"].value, "Costo real")
                items.append({
                    "orden_compra_item_id": campo["orden_compra_item_id"],
                    "producto_id": campo["producto_id"], "producto_nuevo": None,
                    "descripcion_libre": campo["descripcion_libre"],
                    "cantidad_recibida": cantidad, "costo_unitario": costo,
                })
            for linea in lineas_extra_recepcion:
                item_extra = construir_item_extra(linea)
                if item_extra is not None:
                    items.append(item_extra)

            recepciones_service.confirmar_recepcion(
                orden_compra_id=detalle_oc_id, items=items,
                numero_remito=seccion_recepcion_numero_remito.value,
                observacion=seccion_recepcion_observacion.value,
                a_credito=seccion_recepcion_a_credito_switch.value,
            )
            mostrar_mensaje(
                "Recepcion registrada" + (" (a credito, se genero el cargo en Cuentas Corrientes)"
                                           if seccion_recepcion_a_credito_switch.value else "")
            )
            refrescar_detalle()
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))

    confirmar_recepcion_button.on_click = confirmar_recepcion_click
    registrar_recepcion_button.on_click = lambda e: preparar_seccion_recepcion()

    def mostrar_cancelacion(e: ft.ControlEvent) -> None:
        motivo_cancelacion_field.value = ""
        motivo_cancelacion_field.visible = True
        confirmar_cancelacion_button.visible = True
        page.update()

    def confirmar_cancelacion(e: ft.ControlEvent) -> None:
        try:
            ordenes_compra_service.cancelar_orden_compra(detalle_oc_id, motivo_cancelacion_field.value or "")
            mostrar_mensaje("Orden de compra cancelada")
            refrescar_detalle()
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))

    cancelar_oc_button.on_click = mostrar_cancelacion
    confirmar_cancelacion_button.on_click = confirmar_cancelacion

    def mostrar_cierre_manual(e: ft.ControlEvent) -> None:
        motivo_cierre_field.value = ""
        motivo_cierre_field.visible = True
        confirmar_cierre_button.visible = True
        page.update()

    def confirmar_cierre_manual(e: ft.ControlEvent) -> None:
        try:
            ordenes_compra_service.marcar_recibida_manualmente(detalle_oc_id, motivo_cierre_field.value or "")
            mostrar_mensaje("Orden de compra dada por recibida")
            refrescar_detalle()
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))

    dar_por_recibida_button.on_click = mostrar_cierre_manual
    confirmar_cierre_button.on_click = confirmar_cierre_manual
    editar_oc_button.on_click = lambda e: ir_a_formulario(detalle_oc_id)

    seccion_detalle = ft.Column(
        [
            detalle_titulo,
            detalle_info,
            ft.Row([editar_oc_button, registrar_recepcion_button, dar_por_recibida_button, cancelar_oc_button, volver_lista_button]),
            ft.Row([motivo_cancelacion_field, confirmar_cancelacion_button]),
            ft.Row([motivo_cierre_field, confirmar_cierre_button]),
            seccion_recepcion,
            ft.Text("Lineas pedidas", weight=ft.FontWeight.BOLD),
            tabla_items_oc,
            ft.Text("Historial de recepciones", weight=ft.FontWeight.BOLD),
            contenedor_recepciones,
        ],
        visible=False,
        scroll=ft.ScrollMode.AUTO,
    )

    def ir_a_lista(e: ft.ControlEvent | None) -> None:
        seccion_lista.visible = True
        seccion_formulario.visible = False
        seccion_detalle.visible = False
        refrescar_lista()
        page.update()

    def ir_a_detalle(oc_id: int) -> None:
        nonlocal detalle_oc_id
        detalle_oc_id = oc_id
        seccion_lista.visible = False
        seccion_formulario.visible = False
        seccion_detalle.visible = True
        refrescar_detalle()
        page.update()

    refrescar_lista()

    return ft.Column(
        [seccion_lista, seccion_formulario, seccion_detalle],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
