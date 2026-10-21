"""Piezas visuales comunes a todas las pantallas. Implementan docs/estandar_pantallas.md: una
pantalla nueva se arma juntando estas piezas, sin inventar nada propio.

    encabezado_pantalla("Productos", "Los articulos que ...")     titulo + subtitulo
    barra([filtros...], [botones...])                             filtros a la izq., acciones a la der.
    Lista([Columna(...)], al_cambiar_pagina=refrescar)            lista + paginado + filas desplegables
    accion_abrir / accion_ver / accion_cambiar / accion_anular / accion_proceso
                                                                  los 5 tipos de accion de una fila
    etiqueta_estado("Activo", TONO_OK)                            estado con su color
    tarjeta(...), botones_formulario(...)                         formulario aparte
    ventana_info(...), avisar(...)                                ventana de solo lectura, aviso abajo
"""

from dataclasses import dataclass
from typing import Callable, Iterable

import flet as ft

from app.services.exceptions import ErrorDeNegocio
from app.ui.theme import (
    COLOR_ACCENT,
    COLOR_ACCENT_STRONG,
    COLOR_ACCENT_WASH,
    COLOR_BG,
    COLOR_BORDER,
    COLOR_DANGER,
    COLOR_DANGER_WASH,
    COLOR_SUCCESS,
    COLOR_SUCCESS_WASH,
    COLOR_SURFACE,
    COLOR_TEXT,
    COLOR_TEXT_SOFT,
    COLOR_WARNING,
    COLOR_WARNING_WASH,
)

ESPACIO_PANTALLA = 14
COLOR_LINEA = "#e4eeec"
TAMANOS_PAGINA = [10, 20, 50]
ERRORES_PARA_AVISAR = (ErrorDeNegocio, ValueError)


# ================= Estructura =================

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


def barra(filtros: Iterable[ft.Control], acciones: Iterable[ft.Control] = ()) -> ft.Container:
    """Filtros a la izquierda y botones de accion a la derecha, todo en una linea."""
    return tarjeta(ft.Row(
        [*filtros, ft.Container(expand=True), *acciones],
        spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
    ))


def campo_buscar(ayuda: str, al_cambiar: Callable[[], None] | None = None) -> ft.TextField:
    """Buscador igual en todas las pantallas: filtra mientras se escribe. Ancho fijo a proposito:
    con expand, dentro de una fila con wrap=True, Flet pinta un bloque gris (ver CLAUDE.md)."""
    campo = ft.TextField(label="Buscar", hint_text=ayuda, prefix_icon=ft.Icons.SEARCH, width=320)
    if al_cambiar is not None:
        campo.on_change = lambda e: al_cambiar()
    return campo


def boton_principal(texto: str, icono: ft.IconData | None, al_apretar: Callable[[], None]) -> ft.ElevatedButton:
    return ft.ElevatedButton(texto, icon=icono, on_click=lambda e: al_apretar())


def boton_secundario(texto: str, icono: ft.IconData | None, al_apretar: Callable[[], None]) -> ft.OutlinedButton:
    return ft.OutlinedButton(texto, icon=icono, on_click=lambda e: al_apretar())


def botones_formulario(texto_guardar: ft.Text, al_guardar: Callable[[], None], al_cancelar: Callable[[], None]) -> ft.Row:
    """Guardar + Cancelar al pie de un formulario. texto_guardar es un ft.Text para poder cambiarlo
    ('Agregar producto' <-> 'Guardar cambios'): mutar el texto de un boton no se ve (ver CLAUDE.md)."""
    return ft.Row([
        ft.ElevatedButton(content=texto_guardar, on_click=lambda e: al_guardar()),
        ft.TextButton("Cancelar", on_click=lambda e: al_cancelar()),
    ])


def rotulo(texto: str) -> ft.Text:
    """Titulo chico de una parte de lo desplegado o de una ventana ('LINEAS PEDIDAS')."""
    return ft.Text(texto.upper(), size=11.5, weight=ft.FontWeight.BOLD, color=COLOR_TEXT_SOFT)


def tabla_simple(titulos: list[str], filas: list[list], derecha: Iterable[int] = (),
                 vacio: str = "Nada cargado.") -> ft.Control:
    """Tabla chica de solo lectura: para lo que despliega una fila o para una ventana_info.
    derecha: indices de las columnas numericas."""
    if not filas:
        return ft.Text(vacio, size=13, color=COLOR_TEXT_SOFT)
    derecha = set(derecha)
    return ft.DataTable(
        columns=[ft.DataColumn(ft.Text(t), numeric=i in derecha) for i, t in enumerate(titulos)],
        rows=[ft.DataRow([ft.DataCell(Lista._como_control(v)) for v in fila]) for fila in filas],
        bgcolor=COLOR_SURFACE, border=ft.Border.all(1, COLOR_BORDER), border_radius=8,
        heading_row_height=36, data_row_min_height=34, data_row_max_height=44, column_spacing=28, horizontal_margin=12,
    )


# ================= Estados =================

TONO_OK = "ok"          # verde: terminado / bien
TONO_ESPERA = "espera"  # ambar: espera algo
TONO_CURSO = "curso"    # verde agua: en curso
TONO_NO = "no"          # rojo: anulado / no vale
_COLORES_TONO = {
    TONO_OK: (COLOR_SUCCESS, COLOR_SUCCESS_WASH),
    TONO_ESPERA: (COLOR_WARNING, COLOR_WARNING_WASH),
    TONO_CURSO: (COLOR_ACCENT_STRONG, COLOR_ACCENT_WASH),
    TONO_NO: (COLOR_DANGER, COLOR_DANGER_WASH),
}


def etiqueta_estado(texto: str, tono: str) -> ft.Container:
    color, fondo = _COLORES_TONO[tono]
    return ft.Container(
        ft.Text(texto, size=11.5, weight=ft.FontWeight.BOLD, color=color),
        bgcolor=fondo, border_radius=999, padding=ft.Padding.symmetric(horizontal=10, vertical=3),
    )


# ================= Avisos y ventanas =================

def avisar(page: ft.Page, texto: str, error: bool = False) -> None:
    page.show_dialog(ft.SnackBar(
        ft.Text(texto, color=ft.Colors.WHITE if error else None),
        bgcolor=COLOR_DANGER if error else None,
    ))


def _ejecutar(page: ft.Page, funcion: Callable, *args) -> tuple[bool, object]:
    """Corre una accion. Un error de negocio se avisa en rojo; cualquier otro es un error de
    programacion y se deja subir (no se esconde)."""
    try:
        return True, funcion(*args)
    except ERRORES_PARA_AVISAR as ex:
        avisar(page, str(ex), error=True)
        return False, None


def ventana_info(page: ft.Page, titulo: str, *controles: ft.Control) -> None:
    """Tipo 2: ventana chica de solo lectura."""
    page.show_dialog(ft.AlertDialog(
        title=ft.Text(titulo, size=16, weight=ft.FontWeight.BOLD),
        content=ft.Column(list(controles), tight=True, spacing=10, width=460),
        actions=[ft.ElevatedButton("Cerrar", on_click=lambda e: page.pop_dialog())],
        actions_alignment=ft.MainAxisAlignment.END,
    ))


def dato(etiqueta: str, valor: str) -> ft.Row:
    """Una linea 'etiqueta: valor' para ventana_info."""
    return ft.Row([
        ft.Text(etiqueta, color=COLOR_TEXT_SOFT, width=150),
        ft.Text(valor, weight=ft.FontWeight.W_500, expand=True),
    ], vertical_alignment=ft.CrossAxisAlignment.START)


def _ventana_motivo(page: ft.Page, texto_boton: str, titulo: str, explicacion: str,
                    al_confirmar: Callable[[str], str | None], peligro: bool = True) -> None:
    motivo_field = ft.TextField(label="Motivo (obligatorio)", multiline=True, min_lines=2, max_lines=4, autofocus=True)

    def confirmar(e: ft.ControlEvent) -> None:
        motivo = (motivo_field.value or "").strip()
        if not motivo:
            motivo_field.error_text = "Escribi el motivo para poder seguir"
            page.update()
            return
        ok, aviso = _ejecutar(page, al_confirmar, motivo)
        if ok:
            page.pop_dialog()
            if aviso:
                avisar(page, aviso)

    page.show_dialog(ft.AlertDialog(
        modal=True,
        title=ft.Text(titulo, size=16, weight=ft.FontWeight.BOLD),
        content=ft.Column([ft.Text(explicacion), motivo_field], tight=True, spacing=12, width=460),
        actions=[
            ft.TextButton("Volver", on_click=lambda e: page.pop_dialog()),
            ft.ElevatedButton(texto_boton, on_click=confirmar,
                              style=ft.ButtonStyle(bgcolor=COLOR_DANGER, color=ft.Colors.WHITE) if peligro else None),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    ))


# ================= Acciones de una fila (los 5 tipos) =================

def _boton_accion(icono: ft.IconData, tooltip: str, por_que_no: str | None,
                  al_click: Callable[[ft.ControlEvent], None], peligro: bool = False) -> ft.IconButton:
    """Si la accion no corresponde (por_que_no), queda apagada y el tooltip dice por que; si igual
    se aprieta, lo avisa. No se usa disabled porque un boton deshabilitado no explica nada."""
    titulo = f"{tooltip}: {por_que_no}" if por_que_no else tooltip

    def click(e: ft.ControlEvent) -> None:
        if por_que_no:
            avisar(e.page, titulo)
        else:
            al_click(e)

    return ft.IconButton(
        icono, tooltip=titulo, icon_size=19, on_click=click, opacity=0.3 if por_que_no else 1,
        icon_color=COLOR_DANGER if peligro else COLOR_TEXT_SOFT,
    )


def accion_abrir(icono: ft.IconData, tooltip: str, al_apretar: Callable[[], None],
                 por_que_no: str | None = None) -> ft.IconButton:
    """Tipo 1: lleva al formulario (editar, registrar recepcion)."""
    return _boton_accion(icono, tooltip, por_que_no, lambda e: al_apretar())


def accion_ver(icono: ft.IconData, tooltip: str, al_apretar: Callable[[], None],
               por_que_no: str | None = None) -> ft.IconButton:
    """Tipo 2: al_apretar abre una ventana_info."""
    return _boton_accion(icono, tooltip, por_que_no, lambda e: al_apretar())


def accion_cambiar(icono: ft.IconData, tooltip: str, al_apretar: Callable[[], str | None],
                   por_que_no: str | None = None) -> ft.IconButton:
    """Tipo 3: cambia al instante. al_apretar hace el cambio, refresca la lista y devuelve el aviso."""
    def click(e: ft.ControlEvent) -> None:
        pagina = e.page  # antes de refrescar: al redibujar la lista este boton deja de existir
        ok, aviso = _ejecutar(pagina, al_apretar)
        if ok and aviso:
            avisar(pagina, aviso)
    return _boton_accion(icono, tooltip, por_que_no, click)


def accion_anular(tooltip: str, titulo: str, explicacion: str, al_confirmar: Callable[[str], str | None],
                  por_que_no: str | None = None) -> ft.IconButton:
    """Tipo 4: unica en rojo. Pide confirmacion y motivo. al_confirmar(motivo) anula, refresca y
    devuelve el aviso."""
    return _boton_accion(
        ft.Icons.BLOCK, tooltip, por_que_no,
        lambda e: _ventana_motivo(e.page, tooltip, titulo, explicacion, al_confirmar), peligro=True,
    )


def accion_con_motivo(icono: ft.IconData, tooltip: str, titulo: str, explicacion: str,
                      al_confirmar: Callable[[str], str | None], por_que_no: str | None = None) -> ft.IconButton:
    """Tipo 4 sin rojo: un cierre que pide confirmacion y motivo pero no anula nada (ej. 'Dar por
    recibida' una orden a la que no le va a llegar lo que falta)."""
    return _boton_accion(
        icono, tooltip, por_que_no,
        lambda e: _ventana_motivo(e.page, tooltip, titulo, explicacion, al_confirmar, peligro=False),
    )


def accion_proceso(icono: ft.IconData, tooltip: str, al_apretar: Callable[[], str | None],
                   por_que_no: str | None = None) -> ft.Container:
    """Tipo 5: mail, PDF. Mientras trabaja, el icono gira; al final avisa como salio."""
    contenedor = ft.Container(width=40, height=40, alignment=ft.Alignment.CENTER)
    ruedita = ft.ProgressRing(width=18, height=18, stroke_width=2)

    def click(e: ft.ControlEvent) -> None:
        pagina = e.page  # antes de refrescar: al redibujar la lista este boton deja de existir
        contenedor.content = ruedita
        pagina.update()
        try:
            ok, aviso = _ejecutar(pagina, al_apretar)
        finally:
            contenedor.content = boton
            pagina.update()
        if ok and aviso:
            avisar(pagina, aviso)

    boton = _boton_accion(icono, tooltip, por_que_no, click)
    contenedor.content = boton
    return contenedor


# ================= Lista =================

@dataclass
class Columna:
    titulo: str
    ancho: int | None = None   # px fijos; None = se reparte el ancho que queda segun 'peso'
    peso: int = 1
    derecha: bool = False      # numeros y acciones a la derecha
    orden: str | None = None   # clave para ordenar al apretar el titulo (None = no se ordena)


class Lista:
    """Lista estandar: encabezado, filas, filas desplegables (solo lectura) y paginado numerado
    abajo. La pantalla pide los datos y llama a mostrar(); la Lista no sabe de servicios.

        lista = Lista(columnas, al_cambiar_pagina=refrescar, nombre="productos", orden_inicial=("nombre", False))
        def refrescar():
            r = productos_service.listar_productos_pagina(lista.pagina, lista.por_pagina, ...,
                                                          orden=lista.orden, descendente=lista.descendente)
            lista.mostrar(r["items"], celdas, total=r["total"])     # paginado y orden en SQL
            # o lista.mostrar(todos, celdas)                        # paginado y orden aca

    Orden: las columnas con Columna(orden="clave") se ordenan al apretar su titulo (otro clic
    invierte). Con total= el orden lo resuelve la consulta (lista.orden / lista.descendente); sin
    total, la Lista ordena por item[clave] (o por valor_orden(item, clave) si se pasa).
    """

    ANCHO_FLECHA = 40

    def __init__(self, columnas: list[Columna], al_cambiar_pagina: Callable[[], None], nombre: str = "registros",
                 con_hijos: bool = False, por_pagina: int = 20, sin_datos: str = "No hay nada para mostrar.",
                 orden_inicial: tuple[str, bool] | None = None):
        self.columnas = columnas
        self.nombre = nombre
        self.con_hijos = con_hijos
        self.pagina = 1
        self.por_pagina = por_pagina
        self.total = 0
        self.sin_datos = sin_datos
        self._al_cambiar_pagina = al_cambiar_pagina
        self._abiertas: set = set()
        self._ultimo: tuple | None = None
        self.orden, self.descendente = orden_inicial if orden_inicial else (None, False)

        self._filas = ft.Column(spacing=0)
        self._vacio = ft.Text("", color=COLOR_TEXT_SOFT, visible=False)
        self._paginado = ft.Row(spacing=6, alignment=ft.MainAxisAlignment.CENTER, wrap=True,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self._encabezado = ft.Container()
        self._dibujar_encabezado()
        self.control = tarjeta(
            self._encabezado, self._filas, ft.Container(self._vacio, padding=ft.Padding.symmetric(horizontal=8, vertical=12)),
            ft.Container(self._paginado, padding=ft.Padding.only(top=12)),
            spacing=0,
        )

    def ir_al_principio(self) -> None:
        """Para cuando cambia un filtro: la pagina 4 de la busqueda anterior no tiene sentido."""
        self.pagina = 1

    # ---------- orden ----------
    def _titulo(self, c: Columna) -> ft.Control:
        texto = ft.Text(c.titulo, size=13, weight=ft.FontWeight.W_600,
                        color=COLOR_ACCENT_STRONG if c.orden and c.orden == self.orden else COLOR_TEXT_SOFT)
        if not c.orden:
            return texto
        if c.orden == self.orden:
            icono = ft.Icon(ft.Icons.ARROW_DOWNWARD if self.descendente else ft.Icons.ARROW_UPWARD,
                            size=15, color=COLOR_ACCENT_STRONG)
            ayuda = "Ordenado de mayor a menor: clic para invertir" if self.descendente else "Ordenado de menor a mayor: clic para invertir"
        else:
            icono = ft.Icon(ft.Icons.UNFOLD_MORE, size=15, color=COLOR_BORDER)
            ayuda = f"Ordenar por {c.titulo.lower()}"
        return ft.Container(
            ft.Row([texto, icono], spacing=2, tight=True), tooltip=ayuda, ink=True, border_radius=6,
            padding=ft.Padding.symmetric(horizontal=2, vertical=2), on_click=lambda e, k=c.orden: self._ordenar(k),
        )

    def _dibujar_encabezado(self) -> None:
        self._encabezado.content = self._fila(
            [self._titulo(c) for c in self.columnas],
            flecha=ft.Container(width=self.ANCHO_FLECHA) if self.con_hijos else None, borde=COLOR_BORDER,
        ).content
        self._encabezado.padding = ft.Padding.symmetric(horizontal=8, vertical=6)
        self._encabezado.border = ft.Border.only(bottom=ft.BorderSide(1, COLOR_BORDER))

    def _ordenar(self, clave: str) -> None:
        self.descendente = not self.descendente if clave == self.orden else False
        self.orden = clave
        self.pagina = 1
        self._dibujar_encabezado()
        self._al_cambiar_pagina()

    # ---------- armado ----------
    def _celda(self, columna: Columna, contenido: ft.Control) -> ft.Container:
        alineacion = ft.Alignment.CENTER_RIGHT if columna.derecha else ft.Alignment.CENTER_LEFT
        if columna.ancho is not None:
            return ft.Container(contenido, width=columna.ancho, alignment=alineacion)
        return ft.Container(contenido, expand=columna.peso, alignment=alineacion)

    def _fila(self, contenidos: list[ft.Control], flecha: ft.Control | None, borde: str = COLOR_LINEA) -> ft.Container:
        celdas = [self._celda(c, x) for c, x in zip(self.columnas, contenidos)]
        if flecha is not None:
            celdas.insert(0, flecha)
        return ft.Container(
            ft.Row(celdas, spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.symmetric(horizontal=8, vertical=6),
            border=ft.Border.only(bottom=ft.BorderSide(1, borde)),
        )

    @staticmethod
    def _como_control(valor: ft.Control | str | None) -> ft.Control:
        if isinstance(valor, ft.Control):
            return valor
        return ft.Text("-" if valor in (None, "") else str(valor), color=COLOR_TEXT)

    # ---------- mostrar ----------
    def mostrar(self, items: list, celdas: Callable[[object], list], total: int | None = None,
                clave: Callable[[object], object] = lambda x: x["id"],
                hijos: Callable[[object], ft.Control] | None = None,
                valor_orden: Callable[[object, str], object] = lambda x, k: x[k]) -> None:
        """items: la pagina actual (si se pasa total, paginado en SQL) o todos (sin total: pagina aca).
        celdas(item): una entrada por columna (texto o control). hijos(item): lo que se despliega."""
        if total is None:
            if self.orden:
                def llave(item):
                    v = valor_orden(item, self.orden)
                    return (v is None, v.casefold() if isinstance(v, str) else v)
                vacios = [i for i in items if valor_orden(i, self.orden) is None]
                items = sorted((i for i in items if valor_orden(i, self.orden) is not None), key=llave,
                               reverse=self.descendente) + vacios
            self.total = len(items)
            self._ajustar_pagina()
            inicio = (self.pagina - 1) * self.por_pagina
            items = items[inicio:inicio + self.por_pagina]
        else:
            self.total = total
            self._ajustar_pagina()
        self._ultimo = (items, celdas, clave, hijos)
        self._dibujar()

    def _ajustar_pagina(self) -> None:
        self.pagina = max(1, min(self.pagina, self.total_paginas()))

    def total_paginas(self) -> int:
        return max(1, -(-self.total // self.por_pagina))

    def _dibujar(self) -> None:
        items, celdas, clave, hijos = self._ultimo
        filas: list[ft.Control] = []
        for item in items:
            flecha = None
            abierta = False
            if self.con_hijos:
                k = clave(item)
                abierta = k in self._abiertas
                flecha = ft.Container(ft.IconButton(
                    ft.Icons.EXPAND_MORE if abierta else ft.Icons.CHEVRON_RIGHT, icon_size=20,
                    tooltip="Ocultar detalle" if abierta else "Ver detalle", icon_color=COLOR_TEXT_SOFT,
                    on_click=lambda e, k=k: self._alternar(e, k),
                ), width=self.ANCHO_FLECHA)
            filas.append(self._fila([self._como_control(v) for v in celdas(item)], flecha))
            if abierta and hijos is not None:
                filas.append(ft.Container(
                    ft.Column([
                        hijos(item),
                        ft.Text("Solo para mirar. Para cambiar algo, el lapiz de la fila abre el formulario.",
                                size=11.5, color=COLOR_TEXT_SOFT),
                    ], spacing=8),
                    bgcolor=COLOR_BG, padding=ft.Padding.only(left=self.ANCHO_FLECHA + 16, right=16, top=10, bottom=14),
                    border=ft.Border.only(bottom=ft.BorderSide(1, COLOR_LINEA)),
                ))
        self._filas.controls = filas
        self._vacio.value = self.sin_datos
        self._vacio.visible = not items
        self._dibujar_paginado()

    def _alternar(self, e: ft.ControlEvent, k) -> None:
        pagina = e.page  # antes de redibujar: la flecha que se apreto deja de existir
        if k in self._abiertas:
            self._abiertas.remove(k)
        else:
            self._abiertas.add(k)
        self._dibujar()
        pagina.update()

    # ---------- paginado ----------
    def _ir(self, pagina: int) -> None:
        self.pagina = max(1, min(pagina, self.total_paginas()))
        self._al_cambiar_pagina()

    def _cambiar_tamano(self, e: ft.ControlEvent) -> None:
        self.por_pagina = int(e.control.value)
        self.pagina = 1
        self._al_cambiar_pagina()

    def _boton_pagina(self, numero: int) -> ft.Container:
        actual = numero == self.pagina
        return ft.Container(
            ft.Text(str(numero), weight=ft.FontWeight.W_500, color=ft.Colors.WHITE if actual else COLOR_ACCENT_STRONG),
            width=36, height=32, border_radius=8, alignment=ft.Alignment.CENTER, ink=not actual,
            bgcolor=COLOR_ACCENT if actual else COLOR_SURFACE, border=ft.Border.all(1, COLOR_ACCENT if actual else COLOR_BORDER),
            on_click=None if actual else (lambda e, n=numero: self._ir(n)),
        )

    def _dibujar_paginado(self) -> None:
        paginas, p = self.total_paginas(), self.pagina
        desde = max(1, min(p - 3, paginas - 6))
        numeros = range(desde, min(paginas, desde + 6) + 1)

        def flecha(icono, destino, deshabilitada, tooltip):
            return ft.IconButton(icono, icon_size=20, tooltip=tooltip, disabled=deshabilitada,
                                 on_click=lambda e: self._ir(destino))

        self._paginado.controls = [
            flecha(ft.Icons.FIRST_PAGE, 1, p <= 1, "Primera pagina"),
            flecha(ft.Icons.CHEVRON_LEFT, p - 1, p <= 1, "Anterior"),
            *[self._boton_pagina(n) for n in numeros],
            flecha(ft.Icons.CHEVRON_RIGHT, p + 1, p >= paginas, "Siguiente"),
            flecha(ft.Icons.LAST_PAGE, paginas, p >= paginas, "Ultima pagina"),
            ft.Container(width=8),
            ft.Text(f"Pagina {p} de {paginas} ({self.total} {self.nombre})", color=COLOR_TEXT_SOFT),
            ft.Dropdown(
                label="Por pagina", width=110, value=str(self.por_pagina), on_select=self._cambiar_tamano,
                options=[ft.dropdown.Option(str(t)) for t in TAMANOS_PAGINA],
            ),
        ]
