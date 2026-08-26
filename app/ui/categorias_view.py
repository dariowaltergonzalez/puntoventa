import flet as ft

from app.services import categorias_service
from app.services.exceptions import CategoriaDuplicadaError, CategoriaNoEncontradaError


def CategoriasView(page: ft.Page) -> ft.Control:
    nombre_field = ft.TextField(label="Nombre de categoria", expand=True)
    guardar_button_texto = ft.Text("Agregar")
    guardar_button = ft.ElevatedButton(content=guardar_button_texto)
    cancelar_button = ft.TextButton("Cancelar", visible=False)
    tabla = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("ID")),
            ft.DataColumn(ft.Text("Nombre")),
            ft.DataColumn(ft.Text("")),
        ],
        rows=[],
    )

    editando_id = None

    def mostrar_error(mensaje: str) -> None:
        page.show_dialog(ft.SnackBar(ft.Text(mensaje)))

    def limpiar_formulario() -> None:
        nonlocal editando_id
        editando_id = None
        nombre_field.value = ""
        guardar_button_texto.value = "Agregar"
        cancelar_button.visible = False

    def refrescar() -> None:
        tabla.rows = [
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(str(c["id"]))),
                    ft.DataCell(ft.Text(c["nombre"])),
                    ft.DataCell(
                        ft.IconButton(ft.Icons.EDIT, tooltip="Editar", data=c["id"], on_click=iniciar_edicion)
                    ),
                ]
            )
            for c in categorias_service.listar_categorias()
        ]
        page.update()

    def iniciar_edicion(e: ft.ControlEvent) -> None:
        nonlocal editando_id
        categoria = categorias_service.obtener_categoria(e.control.data)
        if categoria is None:
            return
        editando_id = categoria["id"]
        nombre_field.value = categoria["nombre"]
        guardar_button_texto.value = "Guardar cambios"
        cancelar_button.visible = True
        page.update()

    def cancelar(e: ft.ControlEvent) -> None:
        limpiar_formulario()
        page.update()

    def guardar(e: ft.ControlEvent) -> None:
        try:
            if editando_id is None:
                categorias_service.crear_categoria(nombre_field.value or "")
            else:
                categorias_service.actualizar_categoria(editando_id, nombre_field.value or "")
            limpiar_formulario()
            refrescar()
        except (CategoriaDuplicadaError, CategoriaNoEncontradaError, ValueError) as ex:
            mostrar_error(str(ex))

    guardar_button.on_click = guardar
    cancelar_button.on_click = cancelar

    refrescar()

    return ft.Column(
        [
            ft.Text("Categorias", size=20, weight=ft.FontWeight.BOLD),
            ft.Row([nombre_field, guardar_button, cancelar_button]),
            tabla,
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
