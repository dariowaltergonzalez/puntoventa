"""Paleta de colores unica para toda la app ("Verde Agua", aprobada por Dario).

Unico lugar donde se definen los colores de la app -- cualquier pantalla que necesite
un color los importa de aca, nunca hardcodea un hex propio. Para cambiar el tema
completo alcanza con tocar los valores de este archivo.
"""

import flet as ft

# Fondo y superficies
COLOR_BG = "#eef5f4"
COLOR_BG_ALT = "#e3eeec"
COLOR_SURFACE = "#ffffff"
COLOR_BORDER = "#cfe0dd"

# Texto sobre fondo claro
COLOR_TEXT = "#132824"
COLOR_TEXT_SOFT = "#54706c"

# Barra lateral de navegacion (fondo oscuro, fija en toda la app)
COLOR_RAIL = "#0e3d3b"
COLOR_RAIL_SOFT = "#154e4b"
COLOR_RAIL_BORDE = "#2a6b66"
COLOR_RAIL_BORDE_FOCO = "#6fe3d4"
COLOR_TEXT_ON_RAIL = "#dceeeb"
COLOR_TEXT_ON_RAIL_SOFT = "#8fb5b0"

# Color de marca (acento primario)
COLOR_ACCENT = "#0f8b83"
COLOR_ACCENT_STRONG = "#0b6b64"
COLOR_ACCENT_WASH = "#e2f3f1"

# Accion principal (botones de "Cobrar", CTAs destacados)
COLOR_ACTION = "#ff6a3d"
COLOR_ACTION_STRONG = "#e2521f"
COLOR_ACTION_WASH = "#ffe6da"

# Estados semanticos (iguales en toda la app)
COLOR_SUCCESS = "#1f8f5f"
COLOR_SUCCESS_WASH = "#e2f6ec"
COLOR_WARNING = "#c9821c"
COLOR_WARNING_WASH = "#faf0dd"
COLOR_DANGER = "#d5493f"
COLOR_DANGER_WASH = "#fbe7e5"


def theme_claro() -> ft.Theme:
    """Theme de Flet/Material usado en page.theme -- hace que los controles sin estilo
    propio (ElevatedButton, TextField, DataTable, etc.) hereden el acento de marca
    en vez de los colores por defecto de Flet."""
    return ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=COLOR_ACCENT,
            on_primary="#ffffff",
            secondary=COLOR_ACTION,
            on_secondary="#ffffff",
            error=COLOR_DANGER,
            surface=COLOR_SURFACE,
            on_surface=COLOR_TEXT,
        ),
        # ElevatedButton es la accion principal de cada pantalla (Guardar, Agregar X) --
        # fondo solido en vez del relleno tenue por defecto de Material 3, para que resalte.
        # TextButton/OutlinedButton (ej. "Cancelar") quedan con el estilo por defecto a proposito,
        # para no competir visualmente con la accion principal.
        button_theme=ft.ButtonTheme(
            style=ft.ButtonStyle(bgcolor=COLOR_ACCENT, color="#ffffff"),
        ),
    )
