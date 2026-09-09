from decimal import Decimal, InvalidOperation

import flet as ft

from app.services import categorias_service, listas_precios_service, productos_service
from app.services.exceptions import (
    CategoriaNoEncontradaError,
    ListaPrecioDuplicadaError,
    ListaPrecioNoEncontradaError,
    ProductoNoEncontradoError,
)
from app.shared.money import formatear_precio, formatear_porcentaje
from app.ui.campos import FILTRO_DECIMALES_CON_SIGNO, aplicar_mascara_moneda, parsear_decimal_ar_opcional

EXCEPCIONES_NEGOCIO = (
    CategoriaNoEncontradaError, ListaPrecioDuplicadaError, ListaPrecioNoEncontradaError,
    ProductoNoEncontradoError, ValueError,
)


def ListasPreciosView(page: ft.Page) -> ft.Control:
    def mostrar_mensaje(texto: str) -> None:
        page.show_dialog(ft.SnackBar(ft.Text(texto)))

    def parsear_decimal(valor: str | None, etiqueta: str) -> Decimal:
        try:
            return Decimal((valor or "0").replace(",", "."))
        except InvalidOperation:
            raise ValueError(f"{etiqueta} invalido") from None

    def parsear_decimal_opcional(valor: str | None, etiqueta: str) -> Decimal | None:
        texto = (valor or "").strip()
        if not texto:
            return None
        return parsear_decimal(texto, etiqueta)

    # ================= SECCION LISTA =================
    tabla_lista = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(t)) for t in ["Nombre", "% general", "Activa", ""]],
        rows=[],
    )
    nueva_lista_button = ft.ElevatedButton("+ Nueva lista de precios")

    def construir_fila_lista(l: dict) -> ft.DataRow:
        return ft.DataRow(cells=[
            ft.DataCell(ft.Text(l["nombre"])),
            ft.DataCell(ft.Text(f"{formatear_porcentaje(l['porcentaje_general'])}%" if l["porcentaje_general"] is not None else "-")),
            ft.DataCell(ft.Text("Si" if l["activo"] else "No")),
            ft.DataCell(ft.IconButton(ft.Icons.VISIBILITY, tooltip="Ver detalle / editar", data=l["id"],
                                      on_click=lambda e: ir_a_detalle(e.control.data))),
        ])

    def refrescar_lista(e: ft.ControlEvent | None = None) -> None:
        tabla_lista.rows = [construir_fila_lista(l) for l in listas_precios_service.listar_listas()]
        page.update()

    nueva_lista_button.on_click = lambda e: ir_a_formulario(None)

    seccion_lista = ft.Column([
        ft.Text("Listas de precios", size=20, weight=ft.FontWeight.BOLD),
        ft.Row([nueva_lista_button]),
        tabla_lista,
    ])

    # ================= SECCION FORMULARIO =================
    form_titulo = ft.Text("", size=18, weight=ft.FontWeight.BOLD)
    nombre_field = ft.TextField(label="Nombre", width=250)
    porcentaje_general_field = ft.TextField(
        label="% general (opcional)", width=200,
        hint_text="ej: -15 (descuento) o 15 (recargo)",
        input_filter=FILTRO_DECIMALES_CON_SIGNO,
    )
    activo_switch = ft.Switch(label="Activa", value=True, visible=False)
    guardar_form_texto = ft.Text("Crear lista")
    guardar_form_button = ft.ElevatedButton(content=guardar_form_texto)
    cancelar_form_button = ft.TextButton("Cancelar", on_click=lambda e: ir_a_lista(None))

    editando_lista_id: int | None = None

    def limpiar_formulario() -> None:
        nonlocal editando_lista_id
        editando_lista_id = None
        nombre_field.value = ""
        porcentaje_general_field.value = ""
        activo_switch.value = True
        activo_switch.visible = False
        guardar_form_texto.value = "Crear lista"
        form_titulo.value = "Nueva lista de precios"

    def cargar_formulario(l: dict) -> None:
        nonlocal editando_lista_id
        editando_lista_id = l["id"]
        nombre_field.value = l["nombre"]
        porcentaje_general_field.value = str(l["porcentaje_general"]) if l["porcentaje_general"] is not None else ""
        activo_switch.value = l["activo"]
        activo_switch.visible = True
        guardar_form_texto.value = "Guardar cambios"
        form_titulo.value = f"Editar lista - {l['nombre']}"

    def guardar_formulario(e: ft.ControlEvent) -> None:
        try:
            porcentaje = parsear_decimal_opcional(porcentaje_general_field.value, "El % general")
            if editando_lista_id is None:
                lista = listas_precios_service.crear_lista(nombre_field.value or "", porcentaje)
            else:
                lista = listas_precios_service.actualizar_lista(
                    editando_lista_id, nombre_field.value or "", porcentaje, activo_switch.value,
                )
            limpiar_formulario()
            ir_a_detalle(lista["id"])
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))

    guardar_form_button.on_click = guardar_formulario

    seccion_formulario = ft.Column(
        [
            form_titulo,
            ft.Row([nombre_field, porcentaje_general_field]),
            ft.Row([activo_switch]),
            ft.Row([guardar_form_button, cancelar_form_button]),
        ],
        visible=False,
    )

    # ================= SECCION DETALLE =================
    detalle_lista_id: int | None = None
    detalle_titulo = ft.Text("", size=18, weight=ft.FontWeight.BOLD)
    detalle_info = ft.Text("")
    editar_button = ft.ElevatedButton("Editar")
    volver_button = ft.TextButton("Volver al listado", on_click=lambda e: ir_a_lista(None))

    categorias_options = [
        ft.dropdown.Option(key=str(c["id"]), text=c["nombre"]) for c in categorias_service.listar_categorias()
    ]
    categoria_dropdown = ft.Dropdown(label="Categoria", width=200, options=categorias_options)
    categoria_porcentaje_field = ft.TextField(label="%", width=120, input_filter=FILTRO_DECIMALES_CON_SIGNO)
    agregar_categoria_button = ft.ElevatedButton("+ Agregar / actualizar")
    tabla_categorias = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(t)) for t in ["Categoria", "%", ""]],
        rows=[],
    )

    productos_options = [
        ft.dropdown.Option(key=str(p["id"]), text=f"{p['codigo']} - {p['nombre']}")
        for p in productos_service.listar_productos(solo_activos=True)
    ]
    producto_dropdown = ft.Dropdown(label="Producto", width=250, options=productos_options)
    producto_precio_field = ft.TextField(label="Precio manual", width=140)
    aplicar_mascara_moneda(producto_precio_field)
    agregar_producto_button = ft.ElevatedButton("+ Agregar / actualizar")
    tabla_productos = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(t)) for t in ["Producto", "Precio manual", ""]],
        rows=[],
    )

    def agregar_categoria(e: ft.ControlEvent) -> None:
        if not categoria_dropdown.value:
            mostrar_mensaje("Elegi una categoria")
            return
        try:
            porcentaje = parsear_decimal(categoria_porcentaje_field.value, "El %")
            listas_precios_service.establecer_porcentaje_categoria(
                detalle_lista_id, int(categoria_dropdown.value), porcentaje,
            )
            categoria_porcentaje_field.value = ""
            refrescar_detalle()
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))

    def quitar_categoria(e: ft.ControlEvent) -> None:
        listas_precios_service.quitar_porcentaje_categoria(detalle_lista_id, e.control.data)
        refrescar_detalle()

    def agregar_producto(e: ft.ControlEvent) -> None:
        if not producto_dropdown.value:
            mostrar_mensaje("Elegi un producto")
            return
        try:
            precio = parsear_decimal_ar_opcional(producto_precio_field.value, "El precio manual")
            if precio is None:
                raise ValueError("Hace falta cargar el precio manual")
            listas_precios_service.establecer_precio_producto(
                detalle_lista_id, int(producto_dropdown.value), precio,
            )
            producto_precio_field.value = ""
            refrescar_detalle()
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))

    def quitar_producto(e: ft.ControlEvent) -> None:
        listas_precios_service.quitar_precio_producto(detalle_lista_id, e.control.data)
        refrescar_detalle()

    agregar_categoria_button.on_click = agregar_categoria
    agregar_producto_button.on_click = agregar_producto

    def refrescar_detalle() -> None:
        lista = listas_precios_service.obtener_lista(detalle_lista_id)
        detalle_titulo.value = lista["nombre"]
        detalle_info.value = (
            f"Activa: {'Si' if lista['activo'] else 'No'}   |   "
            f"% general: {formatear_porcentaje(lista['porcentaje_general']) + '%' if lista['porcentaje_general'] is not None else '-'}"
        )
        tabla_categorias.rows = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Text(c["categoria_nombre"])),
                ft.DataCell(ft.Text(f"{formatear_porcentaje(c['porcentaje'])}%")),
                ft.DataCell(ft.IconButton(ft.Icons.DELETE, tooltip="Quitar", data=c["categoria_id"], on_click=quitar_categoria)),
            ])
            for c in lista["categorias"]
        ]
        tabla_productos.rows = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Text(f"{p['producto_codigo']} - {p['producto_nombre']}")),
                ft.DataCell(ft.Text(formatear_precio(p["precio_manual"]))),
                ft.DataCell(ft.IconButton(ft.Icons.DELETE, tooltip="Quitar", data=p["producto_id"], on_click=quitar_producto)),
            ])
            for p in lista["productos"]
        ]
        page.update()

    def editar_desde_detalle(e: ft.ControlEvent) -> None:
        cargar_formulario(listas_precios_service.obtener_lista(detalle_lista_id))
        seccion_lista.visible = False
        seccion_formulario.visible = True
        seccion_detalle.visible = False
        page.update()

    editar_button.on_click = editar_desde_detalle

    seccion_detalle = ft.Column(
        [
            detalle_titulo,
            detalle_info,
            ft.Row([editar_button, volver_button]),
            ft.Text("% especial por categoria (pisa el % general para esa categoria)", weight=ft.FontWeight.BOLD),
            tabla_categorias,
            ft.Row([categoria_dropdown, categoria_porcentaje_field, agregar_categoria_button]),
            ft.Text("Precio manual por producto (pisa todo lo demas para ese producto)", weight=ft.FontWeight.BOLD),
            tabla_productos,
            ft.Row([producto_dropdown, producto_precio_field, agregar_producto_button]),
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

    def ir_a_formulario(lista_id: int | None) -> None:
        limpiar_formulario()
        if lista_id is not None:
            cargar_formulario(listas_precios_service.obtener_lista(lista_id))
        seccion_lista.visible = False
        seccion_formulario.visible = True
        seccion_detalle.visible = False
        page.update()

    def ir_a_detalle(lista_id: int) -> None:
        nonlocal detalle_lista_id
        detalle_lista_id = lista_id
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
