import flet as ft

from app.ui.categorias_view import CategoriasView
from app.ui.clientes_view import ClientesView
from app.ui.cuentas_corrientes_view import CuentasCorrientesView
from app.ui.listas_precios_view import ListasPreciosView
from app.ui.log_view import LogView
from app.ui.medios_pago_view import MediosPagoView
from app.ui.movimientos_view import MovimientosView
from app.ui.ordenes_compra_view import OrdenesCompraView
from app.ui.productos_view import ProductosView
from app.ui.proveedores_view import ProveedoresView
from app.ui.stock_view import StockView
from app.ui.ventas_view import VentasView

# Agrupacion del menu por seccion (ver "Estructura del menu" en el plan de producto).
GRUPOS_MENU = [
    ("Catalogo", [
        ("Categorias", ft.Icons.CATEGORY, CategoriasView),
        ("Productos", ft.Icons.INVENTORY_2, ProductosView),
        ("Proveedores", ft.Icons.LOCAL_SHIPPING, ProveedoresView),
        ("Clientes", ft.Icons.PEOPLE, ClientesView),
        ("Listas de precios", ft.Icons.SELL, ListasPreciosView),
    ]),
    ("Operaciones", [
        ("Compras", ft.Icons.SHOPPING_CART, OrdenesCompraView),
        ("Ventas", ft.Icons.POINT_OF_SALE, VentasView),
        ("Movimientos", ft.Icons.SWAP_VERT, MovimientosView),
    ]),
    ("Cuentas", [
        ("Cuentas Corrientes", ft.Icons.ACCOUNT_BALANCE_WALLET, CuentasCorrientesView),
        ("Medios de Pago", ft.Icons.PAYMENTS, MediosPagoView),
    ]),
    ("Consultas", [
        ("Stock", ft.Icons.BAR_CHART, StockView),
        ("Historial", ft.Icons.HISTORY, LogView),
    ]),
]

COLOR_SELECCIONADO = ft.Colors.BLUE_100


def build_app(page: ft.Page) -> None:
    content = ft.Container(expand=True, padding=20)
    items_menu: list[tuple[ft.Container, callable]] = []

    def seleccionar(indice: int) -> None:
        for i, (contenedor, _) in enumerate(items_menu):
            contenedor.bgcolor = COLOR_SELECCIONADO if i == indice else None
        content.content = items_menu[indice][1](page)
        page.update()

    filas_menu = []
    indice_actual = 0
    for nombre_grupo, pantallas in GRUPOS_MENU:
        filas_menu.append(
            ft.Text(nombre_grupo.upper(), size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.OUTLINE)
        )
        for nombre_pantalla, icono, factory in pantallas:
            idx = indice_actual
            fila = ft.Container(
                content=ft.Row([ft.Icon(icono, size=18), ft.Text(nombre_pantalla)], spacing=8),
                padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                border_radius=6,
                on_click=lambda e, i=idx: seleccionar(i),
            )
            items_menu.append((fila, factory))
            filas_menu.append(fila)
            indice_actual += 1
        filas_menu.append(ft.Divider(height=1))

    menu = ft.Container(
        content=ft.Column(filas_menu, spacing=2, tight=True, scroll=ft.ScrollMode.AUTO),
        width=200,
        padding=10,
    )

    seleccionar(0)
    page.add(ft.Row([menu, ft.VerticalDivider(width=1), content], expand=True))
