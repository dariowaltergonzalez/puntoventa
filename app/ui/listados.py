"""Utilidades reutilizables para pantallas de listado (grilla + filtros + paginacion).
Cualquier pantalla nueva con una lista de registros (Ordenes de Compra, Clientes, Ventas,
etc.) usa esto en vez de reescribir su propia logica de filtrado/paginacion."""

from typing import Callable

import flet as ft

TAMANOS_PAGINA = [10, 20, 50]


# ================= Filtros genericos (funcionan para cualquier entidad) =================

def coincide_texto(valor: str | None, busqueda: str | None) -> bool:
    """True si no hay busqueda cargada, o si 'busqueda' aparece (sin importar mayus/minus)
    dentro de 'valor'. Sirve para cualquier campo de texto libre (nombre, proveedor, etc.)."""
    busqueda = (busqueda or "").strip().lower()
    if not busqueda:
        return True
    return busqueda in (valor or "").lower()


def coincide_exacto(valor, filtro) -> bool:
    """True si 'filtro' esta vacio (None o ""), o si valor == filtro. Sirve para dropdowns
    de seleccion exacta (estado, categoria_id, etc.)."""
    if filtro in (None, ""):
        return True
    return valor == filtro


def coincide_rango_fecha(fecha: str, desde: str | None, hasta: str | None) -> bool:
    """Compara strings ISO (funciona por orden lexicografico). 'desde'/'hasta' vacios = sin tope."""
    if desde and fecha < desde:
        return False
    if hasta and fecha > hasta:
        return False
    return True


def filtrar(items: list[dict], predicados: list[Callable[[dict], bool]]) -> list[dict]:
    """Devuelve los items que cumplen TODOS los predicados. Cada predicado es una funcion
    item(dict) -> bool. Cada pantalla arma su propia lista de predicados segun sus filtros,
    esta funcion no sabe nada del modelo particular."""
    return [item for item in items if all(p(item) for p in predicados)]


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
        self.tamano_dropdown.on_change = self._cambiar_tamano

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
        habilitados/deshabilitados, y devuelve solo la porcion de la pagina actual."""
        self.total_items = len(items)
        if self.pagina_actual > self.total_paginas():
            self.pagina_actual = self.total_paginas()
        inicio = (self.pagina_actual - 1) * self.tamano_pagina
        fin = inicio + self.tamano_pagina
        self.texto_estado.value = f"Pagina {self.pagina_actual} de {self.total_paginas()} ({self.total_items} registros)"
        self.primero_button.disabled = self.pagina_actual <= 1
        self.anterior_button.disabled = self.pagina_actual <= 1
        self.siguiente_button.disabled = self.pagina_actual >= self.total_paginas()
        self.ultimo_button.disabled = self.pagina_actual >= self.total_paginas()
        return items[inicio:fin]
