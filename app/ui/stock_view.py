import flet as ft

from app.services import categorias_service, movimientos_service
from app.shared.money import formatear_cantidad


def StockView(page: ft.Page) -> ft.Control:
    categoria_dropdown = ft.Dropdown(
        label="Filtrar por categoria",
        options=[ft.dropdown.Option(key="", text="Todas")],
        value="",
    )
    buscador_field = ft.TextField(label="Buscar por nombre o codigo", expand=True)

    tabla = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Codigo")),
            ft.DataColumn(ft.Text("Nombre")),
            ft.DataColumn(ft.Text("Unidad")),
            ft.DataColumn(ft.Text("Stock actual")),
        ],
        rows=[],
    )

    resultado_texto = ft.Text("")

    def refrescar_categorias() -> None:
        categoria_dropdown.options = [ft.dropdown.Option(key="", text="Todas")] + [
            ft.dropdown.Option(key=str(c["id"]), text=c["nombre"])
            for c in categorias_service.listar_categorias()
        ]

    def coincide_busqueda(producto: dict, texto: str) -> bool:
        texto = texto.strip().lower()
        if not texto:
            return True
        return texto in producto["nombre"].lower() or texto in producto["codigo"].lower()

    def refrescar_tabla() -> None:
        categoria_id = int(categoria_dropdown.value) if categoria_dropdown.value else None
        productos = [
            p
            for p in movimientos_service.consultar_stock(categoria_id=categoria_id)
            if coincide_busqueda(p, buscador_field.value or "")
        ]
        tabla.rows = []
        for p in productos:
            stock_bajo = p["stock_minimo"] > 0 and p["stock_actual"] < p["stock_minimo"]
            color = ft.Colors.RED if stock_bajo else None
            tabla.rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(p["codigo"], color=color)),
                        ft.DataCell(ft.Text(p["nombre"], color=color)),
                        ft.DataCell(ft.Text(p["unidad"], color=color)),
                        ft.DataCell(ft.Text(formatear_cantidad(p["stock_actual"]), color=color, weight=ft.FontWeight.BOLD if stock_bajo else None)),
                    ]
                )
            )
        page.update()

    def filtrar(e: ft.ControlEvent) -> None:
        refrescar_tabla()

    def recalcular(e: ft.ControlEvent) -> None:
        diferencias = movimientos_service.recalcular_stock()
        if diferencias:
            resultado_texto.value = f"Se corrigieron {len(diferencias)} producto(s) con stock desactualizado."
        else:
            resultado_texto.value = "El stock ya estaba consistente, no se encontraron diferencias."
        refrescar_tabla()
        page.update()

    refrescar_categorias()
    refrescar_tabla()
    categoria_dropdown.on_change = filtrar
    buscador_field.on_change = filtrar

    return ft.Column(
        [
            ft.Text("Stock", size=20, weight=ft.FontWeight.BOLD),
            ft.Row([categoria_dropdown, ft.ElevatedButton("Recalcular stock", on_click=recalcular)]),
            ft.Row([buscador_field]),
            resultado_texto,
            tabla,
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
