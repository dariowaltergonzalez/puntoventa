from decimal import Decimal, InvalidOperation

import flet as ft

from app.services import categorias_service, productos_service
from app.services.exceptions import CategoriaNoEncontradaError, CodigoDuplicadoError


def ProductosView(page: ft.Page) -> ft.Control:
    codigo_field = ft.TextField(label="Codigo")
    nombre_field = ft.TextField(label="Nombre")
    unidad_field = ft.TextField(label="Unidad", hint_text="kg, unidad, litro...")
    precio_costo_field = ft.TextField(label="Precio costo", hint_text="17,45")
    precio_venta_field = ft.TextField(label="Precio venta", hint_text="21,00")
    categoria_dropdown = ft.Dropdown(label="Categoria", options=[])

    tabla = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Codigo")),
            ft.DataColumn(ft.Text("Nombre")),
            ft.DataColumn(ft.Text("Categoria")),
            ft.DataColumn(ft.Text("Unidad")),
            ft.DataColumn(ft.Text("Costo")),
            ft.DataColumn(ft.Text("Venta")),
            ft.DataColumn(ft.Text("Stock")),
        ],
        rows=[],
    )

    def mostrar_error(mensaje: str) -> None:
        page.open(ft.SnackBar(ft.Text(mensaje)))

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

    def refrescar_tabla() -> None:
        tabla.rows = [
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(p["codigo"])),
                    ft.DataCell(ft.Text(p["nombre"])),
                    ft.DataCell(ft.Text(nombre_categoria(p["categoria_id"]))),
                    ft.DataCell(ft.Text(p["unidad"])),
                    ft.DataCell(ft.Text(str(p["precio_costo"]))),
                    ft.DataCell(ft.Text(str(p["precio_venta"]))),
                    ft.DataCell(ft.Text(str(p["stock_actual"]))),
                ]
            )
            for p in productos_service.listar_productos()
        ]
        page.update()

    def guardar(e: ft.ControlEvent) -> None:
        try:
            if not categoria_dropdown.value:
                raise ValueError("Elegi una categoria")

            productos_service.crear_producto(
                codigo=codigo_field.value or "",
                nombre=nombre_field.value or "",
                categoria_id=int(categoria_dropdown.value),
                unidad=unidad_field.value or "",
                precio_costo=parsear_decimal(precio_costo_field.value, "Precio costo"),
                precio_venta=parsear_decimal(precio_venta_field.value, "Precio venta"),
            )
            codigo_field.value = ""
            nombre_field.value = ""
            unidad_field.value = ""
            precio_costo_field.value = ""
            precio_venta_field.value = ""
            refrescar_tabla()
        except (CodigoDuplicadoError, CategoriaNoEncontradaError, ValueError) as ex:
            mostrar_error(str(ex))

    refrescar_categorias()
    refrescar_tabla()

    return ft.Column(
        [
            ft.Text("Productos", size=20, weight=ft.FontWeight.BOLD),
            ft.Row([codigo_field, nombre_field, unidad_field]),
            ft.Row([categoria_dropdown, precio_costo_field, precio_venta_field]),
            ft.ElevatedButton("Agregar producto", on_click=guardar),
            tabla,
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
