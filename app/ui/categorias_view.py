import flet as ft

from app.services import categorias_service
from app.services.exceptions import CategoriaDuplicadaError, CategoriaNoEncontradaError


def CategoriasView(page: ft.Page) -> ft.Control:
    nombre_field = ft.TextField(label="Nombre de categoria", expand=True)
    tabla = ft.DataTable(
        columns=[ft.DataColumn(ft.Text("ID")), ft.DataColumn(ft.Text("Nombre"))],
        rows=[],
    )

    def mostrar_error(mensaje: str) -> None:
        page.open(ft.SnackBar(ft.Text(mensaje)))

    def refrescar() -> None:
        tabla.rows = [
            ft.DataRow(cells=[ft.DataCell(ft.Text(str(c["id"]))), ft.DataCell(ft.Text(c["nombre"]))])
            for c in categorias_service.listar_categorias()
        ]
        page.update()

    def guardar(e: ft.ControlEvent) -> None:
        try:
            categorias_service.crear_categoria(nombre_field.value or "")
            nombre_field.value = ""
            refrescar()
        except (CategoriaDuplicadaError, CategoriaNoEncontradaError, ValueError) as ex:
            mostrar_error(str(ex))

    refrescar()

    return ft.Column(
        [
            ft.Text("Categorias", size=20, weight=ft.FontWeight.BOLD),
            ft.Row([nombre_field, ft.ElevatedButton("Agregar", on_click=guardar)]),
            tabla,
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
