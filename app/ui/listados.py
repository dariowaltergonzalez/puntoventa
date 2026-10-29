"""con_scroll_horizontal: para una tabla ancha (ft.DataTable) que no es una lista estandar, ej. las
de Ganancias o Datos del negocio. Las pantallas de lista usan componentes.Lista
(ver docs/estandar_pantallas.md)."""

import flet as ft


def con_scroll_horizontal(tabla: ft.Control) -> ft.Row:
    """Envuelve un DataTable para que se pueda desplazar horizontalmente -- Column (donde vive
    el resto de la pantalla) solo scrollea vertical, asi que una tabla con muchas columnas
    queda cortada sin ninguna pista de que hay mas contenido a la derecha si no se envuelve
    asi. scroll=ALWAYS en vez de AUTO para que la barra se vea siempre, no solo al pasar
    el mouse -- es la pista de que se puede desplazar."""
    return ft.Row([tabla], scroll=ft.ScrollMode.ALWAYS)
