import flet as ft

from app.services import categorias_service, lotes_service, movimientos_service
from app.shared.money import formatear_cantidad, formatear_precio


def StockView(page: ft.Page) -> ft.Control:
    categoria_dropdown = ft.Dropdown(
        label="Filtrar por categoria",
        options=[ft.dropdown.Option(key="", text="Todas")],
        value="",
    )
    buscador_field = ft.TextField(label="Buscar por nombre o codigo", expand=True)

    contenedor_filas = ft.Column([])

    resultado_texto = ft.Text("")

    def construir_fila_producto(p: dict) -> ft.ExpansionTile:
        stock_bajo = p["stock_minimo"] > 0 and p["stock_actual"] < p["stock_minimo"]
        color = ft.Colors.RED if stock_bajo else None
        titulo = ft.Row([
            ft.Container(ft.Text(p["codigo"], color=color), width=100),
            ft.Container(ft.Text(p["nombre"], color=color), width=250),
            ft.Container(ft.Text(p["unidad"], color=color), width=80),
            ft.Container(
                ft.Text(formatear_cantidad(p["stock_actual"]), color=color,
                         weight=ft.FontWeight.BOLD if stock_bajo else None),
                width=100,
            ),
        ])
        lotes = lotes_service.listar_lotes_producto(p["id"])
        cantidad_sin_lote = p["stock_actual"] - sum(l["cantidad_restante"] for l in lotes)
        filas_lotes = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Text(l["fecha"][:16])),
                ft.DataCell(ft.Text(l["numero_oc"] or "-")),
                ft.DataCell(ft.Text(l["numero_remito"] or "-")),
                ft.DataCell(ft.Text(formatear_cantidad(l["cantidad_recibida"]))),
                ft.DataCell(ft.Text(formatear_cantidad(l["cantidad_restante"]))),
                ft.DataCell(ft.Text(formatear_precio(l["costo_unitario"]))),
            ])
            for l in lotes
        ]
        if cantidad_sin_lote > 0:
            filas_lotes.append(
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text("-")),
                    ft.DataCell(ft.Text("-")),
                    ft.DataCell(ft.Text("-")),
                    ft.DataCell(ft.Text("-")),
                    ft.DataCell(ft.Text(formatear_cantidad(cantidad_sin_lote), italic=True)),
                    ft.DataCell(ft.Text("Stock sin lote (carga previa a este sistema)", italic=True)),
                ])
            )
        tabla_lotes = ft.DataTable(
            columns=[ft.DataColumn(ft.Text(t)) for t in
                     ["Fecha recepcion", "OC", "Remito", "Cant. recibida", "Cant. restante", "Costo"]],
            rows=filas_lotes,
        )
        return ft.ExpansionTile(
            title=titulo,
            controls=[tabla_lotes],
            tile_padding=ft.Padding.symmetric(horizontal=4, vertical=2),
        )

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
        contenedor_filas.controls = [construir_fila_producto(p) for p in productos]
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
    categoria_dropdown.on_select = filtrar
    buscador_field.on_change = filtrar

    encabezado = ft.Row([
        ft.Container(ft.Text("Codigo", weight=ft.FontWeight.BOLD), width=100),
        ft.Container(ft.Text("Nombre", weight=ft.FontWeight.BOLD), width=250),
        ft.Container(ft.Text("Unidad", weight=ft.FontWeight.BOLD), width=80),
        ft.Container(ft.Text("Stock actual", weight=ft.FontWeight.BOLD), width=100),
    ])

    return ft.Column(
        [
            ft.Text("Stock", size=20, weight=ft.FontWeight.BOLD),
            ft.Row([categoria_dropdown, ft.ElevatedButton("Recalcular stock", on_click=recalcular)]),
            ft.Row([buscador_field]),
            resultado_texto,
            encabezado,
            contenedor_filas,
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
