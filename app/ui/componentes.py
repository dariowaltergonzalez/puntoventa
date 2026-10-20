"""Piezas visuales comunes a todas las pantallas, para que todas se vean iguales:

    encabezado_pantalla("Productos", "Alta y edicion de ...")   -> titulo + subtitulo
    tarjeta(fila1, fila2, titulo="Nuevo producto")              -> recuadro blanco con borde suave

Forma de toda pantalla: encabezado, una tarjeta con el formulario, los filtros sueltos sobre el
fondo, y una tarjeta con la lista (con expand=True si la lista tiene su propio scroll)."""

import flet as ft

from app.ui.theme import COLOR_BORDER, COLOR_SURFACE, COLOR_TEXT_SOFT

ESPACIO_PANTALLA = 14


def encabezado_pantalla(titulo: str, subtitulo: str | None = None) -> ft.Column:
    controles: list[ft.Control] = [ft.Text(titulo, size=22, weight=ft.FontWeight.BOLD)]
    if subtitulo:
        controles.append(ft.Text(subtitulo, size=13, color=COLOR_TEXT_SOFT))
    return ft.Column(controles, spacing=2)


def tarjeta(
    *controles: ft.Control, titulo: str | ft.Control | None = None, subtitulo: str | ft.Control | None = None,
    expand: bool | int | None = None, spacing: int = 10, visible: bool = True,
) -> ft.Container:
    """titulo/subtitulo pueden ser un texto fijo o un ft.Text que la pantalla va cambiando
    (ej. 'Nuevo producto' <-> 'Editar producto')."""
    cabecera: list[ft.Control] = []
    if titulo is not None:
        cabecera.append(titulo if isinstance(titulo, ft.Control) else ft.Text(titulo, size=15, weight=ft.FontWeight.BOLD))
    if subtitulo is not None:
        cabecera.append(subtitulo if isinstance(subtitulo, ft.Control) else ft.Text(subtitulo, size=12.5, color=COLOR_TEXT_SOFT))
    return ft.Container(
        expand=expand, visible=visible, bgcolor=COLOR_SURFACE, border=ft.Border.all(1, COLOR_BORDER), border_radius=12,
        padding=ft.Padding.symmetric(horizontal=18, vertical=16),
        content=ft.Column([*cabecera, *controles], spacing=spacing, expand=bool(expand)),
    )


def campo_buscar(ayuda: str) -> ft.TextField:
    """Buscador igual en todas las pantallas. Ancho fijo a proposito: con expand, dentro de una
    fila con wrap=True, Flet pinta un bloque gris (ver CLAUDE.md)."""
    return ft.TextField(label="Buscar", hint_text=ayuda, prefix_icon=ft.Icons.SEARCH, width=380)
