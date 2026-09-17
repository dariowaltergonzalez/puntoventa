import flet as ft

from app.services import log_service

ENTIDADES = [
    "venta", "orden_compra", "producto", "cliente", "proveedor",
    "lista_precio", "medio_pago", "categoria", "sistema",
]


def LogView(page: ft.Page) -> ft.Control:
    entidad_dropdown = ft.Dropdown(
        label="Filtrar por tipo",
        options=[ft.dropdown.Option(key="", text="Todas")] + [ft.dropdown.Option(e) for e in ENTIDADES],
        value="",
    )
    buscador_field = ft.TextField(label="Buscar en la descripcion", expand=True)

    tabla = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Fecha")),
            ft.DataColumn(ft.Text("Tipo")),
            ft.DataColumn(ft.Text("ID")),
            ft.DataColumn(ft.Text("Descripcion")),
        ],
        rows=[],
    )

    def refrescar_tabla() -> None:
        entidad = entidad_dropdown.value or None
        eventos = log_service.listar_eventos(entidad=entidad, texto=buscador_field.value or "")
        tabla.rows = [
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(e["fecha"])),
                    ft.DataCell(ft.Text(e["entidad"])),
                    ft.DataCell(ft.Text(str(e["entidad_id"]) if e["entidad_id"] is not None else "-")),
                    ft.DataCell(ft.Text(e["descripcion"])),
                ]
            )
            for e in eventos
        ]
        page.update()

    def filtrar(e: ft.ControlEvent) -> None:
        refrescar_tabla()

    entidad_dropdown.on_select = filtrar
    buscador_field.on_change = filtrar

    refrescar_tabla()

    return ft.Column(
        [
            ft.Text("Historial", size=20, weight=ft.FontWeight.BOLD),
            ft.Row([entidad_dropdown, buscador_field]),
            tabla,
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
