"""Restos del armado viejo de listas: con_scroll_horizontal (tablas anchas) y el Paginador que
todavia usa el historial de la caja. Las pantallas de lista nuevas usan componentes.Lista
(ver docs/estandar_pantallas.md)."""

from typing import Callable

import flet as ft

TAMANOS_PAGINA = [10, 20, 50]


def con_scroll_horizontal(tabla: ft.Control) -> ft.Row:
    """Envuelve un DataTable para que se pueda desplazar horizontalmente -- Column (donde vive
    el resto de la pantalla) solo scrollea vertical, asi que una tabla con muchas columnas
    queda cortada sin ninguna pista de que hay mas contenido a la derecha si no se envuelve
    asi. scroll=ALWAYS en vez de AUTO para que la barra se vea siempre, no solo al pasar
    el mouse -- es la pista de que se puede desplazar."""
    return ft.Row([tabla], scroll=ft.ScrollMode.ALWAYS)


# ================= Paginacion (controles + estado, reutilizable) =================

class Paginador:
    """Estado y controles de paginacion. Uso tipico dentro de una pantalla:

        paginador = Paginador(on_cambio=refrescar_lista)
        ...
        def refrescar_lista(e=None):
            items = filtrar(todos_los_items, [...])
            pagina = paginador.aplicar(items)
            grilla.controls = [construir_fila(x) for x in pagina]
            page.update()

    El propio `Paginador` no sabe renderizar filas -- solo recorta la lista y expone los
    controles (dropdown de tamano + botones primero/anterior/siguiente/ultimo + texto de estado)
    para agregar al layout de la pantalla.
    """

    def __init__(self, on_cambio: Callable[[], None], tamano_inicial: int = 20):
        self.pagina_actual = 1
        self.tamano_pagina = tamano_inicial
        self.total_items = 0
        self._on_cambio = on_cambio

        self.tamano_dropdown = ft.Dropdown(
            label="Por pagina", width=110, value=str(tamano_inicial),
            options=[ft.dropdown.Option(str(t)) for t in TAMANOS_PAGINA],
        )
        self.texto_estado = ft.Text("")
        self.primero_button = ft.IconButton(ft.Icons.FIRST_PAGE, tooltip="Primera pagina", on_click=lambda e: self._ir(1))
        self.anterior_button = ft.IconButton(ft.Icons.CHEVRON_LEFT, tooltip="Anterior", on_click=lambda e: self._ir(self.pagina_actual - 1))
        self.siguiente_button = ft.IconButton(ft.Icons.CHEVRON_RIGHT, tooltip="Siguiente", on_click=lambda e: self._ir(self.pagina_actual + 1))
        self.ultimo_button = ft.IconButton(ft.Icons.LAST_PAGE, tooltip="Ultima pagina", on_click=lambda e: self._ir(self.total_paginas()))
        self.tamano_dropdown.on_select = self._cambiar_tamano

        self.controles = ft.Row([
            self.tamano_dropdown, self.primero_button, self.anterior_button,
            self.texto_estado, self.siguiente_button, self.ultimo_button,
        ])

    def total_paginas(self) -> int:
        if self.total_items == 0:
            return 1
        return -(-self.total_items // self.tamano_pagina)  # ceil entero sin importar math

    def _ir(self, pagina: int) -> None:
        self.pagina_actual = max(1, min(pagina, self.total_paginas()))
        self._on_cambio()

    def _cambiar_tamano(self, e: ft.ControlEvent) -> None:
        self.tamano_pagina = int(self.tamano_dropdown.value)
        self.pagina_actual = 1
        self._on_cambio()

    def aplicar(self, items: list) -> list:
        """Recibe la lista COMPLETA ya filtrada, actualiza el texto de estado y los botones
        habilitados/deshabilitados, y devuelve solo la porcion de la pagina actual. Para
        paginacion del lado del cliente (se trajo todo de la base y se recorta en Python)."""
        self.total_items = len(items)
        self._actualizar_estado()
        inicio = (self.pagina_actual - 1) * self.tamano_pagina
        fin = inicio + self.tamano_pagina
        return items[inicio:fin]

    def fijar_total(self, total_items: int) -> None:
        """Para paginacion resuelta en SQL (LIMIT/OFFSET): el propio service ya devolvio
        solo los items de esta pagina, y el 'total' de registros que matchean el filtro
        viene calculado aparte (ver productos_service.listar_productos_pagina). Esta funcion
        solo actualiza el texto de estado y los botones -- no recorta nada."""
        self.total_items = total_items
        self._actualizar_estado()

    def _actualizar_estado(self) -> None:
        if self.pagina_actual > self.total_paginas():
            self.pagina_actual = self.total_paginas()
        self.texto_estado.value = f"Pagina {self.pagina_actual} de {self.total_paginas()} ({self.total_items} registros)"
        self.primero_button.disabled = self.pagina_actual <= 1
        self.anterior_button.disabled = self.pagina_actual <= 1
        self.siguiente_button.disabled = self.pagina_actual >= self.total_paginas()
        self.ultimo_button.disabled = self.pagina_actual >= self.total_paginas()
