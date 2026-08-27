from decimal import Decimal, InvalidOperation

import flet as ft

from app.services import categorias_service, productos_service
from app.services.exceptions import CategoriaNoEncontradaError, CodigoDuplicadoError, ProductoNoEncontradoError
from app.shared.money import formatear_cantidad, formatear_precio


def ProductosView(page: ft.Page) -> ft.Control:
    codigo_field = ft.TextField(label="Codigo")
    nombre_field = ft.TextField(label="Nombre")
    unidad_field = ft.TextField(label="Unidad", hint_text="kg, unidad, litro...")
    precio_costo_field = ft.TextField(label="Precio costo", hint_text="17,45")
    precio_venta_field = ft.TextField(label="Precio venta", hint_text="21,00")
    stock_minimo_field = ft.TextField(label="Stock minimo", hint_text="5,000")
    categoria_dropdown = ft.Dropdown(label="Categoria", options=[])
    activo_switch = ft.Switch(label="Activo", value=True, visible=False)
    guardar_button_texto = ft.Text("Agregar producto")
    guardar_button = ft.ElevatedButton(content=guardar_button_texto)
    cancelar_button = ft.TextButton("Cancelar", visible=False)
    buscador_field = ft.TextField(label="Buscar por nombre o codigo", expand=True)

    tabla = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Codigo")),
            ft.DataColumn(ft.Text("Nombre")),
            ft.DataColumn(ft.Text("Categoria")),
            ft.DataColumn(ft.Text("Unidad")),
            ft.DataColumn(ft.Text("Costo ($)")),
            ft.DataColumn(ft.Text("Venta ($)")),
            ft.DataColumn(ft.Text("Stock")),
            ft.DataColumn(ft.Text("Stock min.")),
            ft.DataColumn(ft.Text("")),
        ],
        rows=[],
    )

    editando_id = None

    def mostrar_error(mensaje: str) -> None:
        page.show_dialog(ft.SnackBar(ft.Text(mensaje)))

    def parsear_decimal(valor: str, etiqueta: str) -> Decimal:
        try:
            return Decimal((valor or "0").replace(",", "."))
        except InvalidOperation as exc:
            raise ValueError(f"'{etiqueta}' no es un numero valido") from exc

    def nombre_categoria(categoria_id: int) -> str:
        categoria = categorias_service.obtener_categoria(categoria_id)
        return categoria["nombre"] if categoria else "?"

    def refrescar_categorias() -> None:
        categoria_dropdown.options = [
            ft.dropdown.Option(key=str(c["id"]), text=c["nombre"])
            for c in categorias_service.listar_categorias()
        ]

    def limpiar_formulario() -> None:
        nonlocal editando_id
        editando_id = None
        codigo_field.value = ""
        nombre_field.value = ""
        unidad_field.value = ""
        precio_costo_field.value = ""
        precio_venta_field.value = ""
        stock_minimo_field.value = ""
        categoria_dropdown.value = None
        activo_switch.visible = False
        activo_switch.value = True
        guardar_button_texto.value = "Agregar producto"
        cancelar_button.visible = False

    def coincide_busqueda(producto: dict, texto: str) -> bool:
        texto = texto.strip().lower()
        if not texto:
            return True
        return texto in producto["nombre"].lower() or texto in producto["codigo"].lower()

    def refrescar_tabla() -> None:
        productos = [
            p for p in productos_service.listar_productos() if coincide_busqueda(p, buscador_field.value or "")
        ]
        tabla.rows = [
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(p["codigo"])),
                    ft.DataCell(ft.Text(p["nombre"])),
                    ft.DataCell(ft.Text(nombre_categoria(p["categoria_id"]))),
                    ft.DataCell(ft.Text(p["unidad"])),
                    ft.DataCell(ft.Text(formatear_precio(p["precio_costo"]))),
                    ft.DataCell(ft.Text(formatear_precio(p["precio_venta"]))),
                    ft.DataCell(ft.Text(formatear_cantidad(p["stock_actual"]))),
                    ft.DataCell(ft.Text(formatear_cantidad(p["stock_minimo"]))),
                    ft.DataCell(
                        ft.IconButton(ft.Icons.EDIT, tooltip="Editar", data=p["id"], on_click=iniciar_edicion)
                    ),
                ]
            )
            for p in productos
        ]
        page.update()

    def iniciar_edicion(e: ft.ControlEvent) -> None:
        nonlocal editando_id
        producto = productos_service.obtener_producto(e.control.data)
        if producto is None:
            return
        editando_id = producto["id"]
        codigo_field.value = producto["codigo"]
        nombre_field.value = producto["nombre"]
        unidad_field.value = producto["unidad"]
        precio_costo_field.value = str(producto["precio_costo"])
        precio_venta_field.value = str(producto["precio_venta"])
        stock_minimo_field.value = str(producto["stock_minimo"])
        categoria_dropdown.value = str(producto["categoria_id"])
        activo_switch.value = producto["activo"]
        activo_switch.visible = True
        guardar_button_texto.value = "Guardar cambios"
        cancelar_button.visible = True
        page.update()

    def cancelar(e: ft.ControlEvent) -> None:
        limpiar_formulario()
        page.update()

    def buscar(e: ft.ControlEvent) -> None:
        refrescar_tabla()

    def guardar(e: ft.ControlEvent) -> None:
        try:
            if not categoria_dropdown.value:
                raise ValueError("Elegi una categoria")

            categoria_id = int(categoria_dropdown.value)
            codigo = codigo_field.value or ""
            nombre = nombre_field.value or ""
            unidad = unidad_field.value or ""
            precio_costo = parsear_decimal(precio_costo_field.value, "Precio costo")
            precio_venta = parsear_decimal(precio_venta_field.value, "Precio venta")
            stock_minimo = parsear_decimal(stock_minimo_field.value, "Stock minimo")

            if editando_id is None:
                productos_service.crear_producto(
                    codigo=codigo,
                    nombre=nombre,
                    categoria_id=categoria_id,
                    unidad=unidad,
                    precio_costo=precio_costo,
                    precio_venta=precio_venta,
                    stock_minimo=stock_minimo,
                )
            else:
                productos_service.actualizar_producto(
                    producto_id=editando_id,
                    codigo=codigo,
                    nombre=nombre,
                    categoria_id=categoria_id,
                    unidad=unidad,
                    precio_costo=precio_costo,
                    precio_venta=precio_venta,
                    stock_minimo=stock_minimo,
                    activo=activo_switch.value,
                )
            limpiar_formulario()
            refrescar_tabla()
        except (CodigoDuplicadoError, CategoriaNoEncontradaError, ProductoNoEncontradoError, ValueError) as ex:
            mostrar_error(str(ex))

    guardar_button.on_click = guardar
    cancelar_button.on_click = cancelar
    buscador_field.on_change = buscar

    refrescar_categorias()
    refrescar_tabla()

    return ft.Column(
        [
            ft.Text("Productos", size=20, weight=ft.FontWeight.BOLD),
            ft.Row([codigo_field, nombre_field, unidad_field]),
            ft.Row([categoria_dropdown, precio_costo_field, precio_venta_field, stock_minimo_field, activo_switch]),
            ft.Row([guardar_button, cancelar_button]),
            ft.Row([buscador_field]),
            tabla,
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
