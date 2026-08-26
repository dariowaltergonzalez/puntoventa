import flet as ft

from app.ui.categorias_view import CategoriasView
from app.ui.movimientos_view import MovimientosView
from app.ui.productos_view import ProductosView
from app.ui.stock_view import StockView


def build_app(page: ft.Page) -> None:
    content = ft.Container(expand=True, padding=20)

    vistas = [
        lambda: CategoriasView(page),
        lambda: ProductosView(page),
        lambda: MovimientosView(page),
        lambda: StockView(page),
    ]

    def cambiar_vista(indice: int) -> None:
        content.content = vistas[indice]()
        page.update()

    rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        destinations=[
            ft.NavigationRailDestination(icon=ft.Icons.CATEGORY, label="Categorias"),
            ft.NavigationRailDestination(icon=ft.Icons.INVENTORY_2, label="Productos"),
            ft.NavigationRailDestination(icon=ft.Icons.SWAP_VERT, label="Movimientos"),
            ft.NavigationRailDestination(icon=ft.Icons.BAR_CHART, label="Stock"),
        ],
        on_change=lambda e: cambiar_vista(e.control.selected_index),
    )

    content.content = vistas[0]()
    page.add(ft.Row([rail, ft.VerticalDivider(width=1), content], expand=True))
