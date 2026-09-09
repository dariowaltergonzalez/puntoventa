"""Filtros de entrada y mascaras reutilizables para TextFields numericos. Cualquier pantalla
con un campo de solo-numeros (DNI, plazos, porcentajes, montos) usa esto en vez de reinventar
la restriccion de caracteres o el parseo."""

from decimal import Decimal, InvalidOperation

import flet as ft

FILTRO_ENTEROS = ft.InputFilter(regex_string=r"^[0-9]*$", allow=True)
FILTRO_DECIMALES = ft.InputFilter(regex_string=r"^[0-9]*[.,]?[0-9]*$", allow=True)
FILTRO_DECIMALES_CON_SIGNO = ft.InputFilter(regex_string=r"^-?[0-9]*[.,]?[0-9]*$", allow=True)
FILTRO_CUIT = ft.InputFilter(regex_string=r"^[0-9-]*$", allow=True)


def aplicar_mascara_moneda(field: ft.TextField) -> None:
    """Al perder el foco, reformatea el valor tipeado al estilo moneda argentina
    (punto de miles, coma decimal). No se reformatea en cada tecla a proposito --
    eso hace saltar el cursor de lugar en cualquier framework, Flet incluido."""
    handler_previo = field.on_blur

    def on_blur(e: ft.ControlEvent) -> None:
        texto = (field.value or "").strip()
        if texto:
            try:
                valor = Decimal(texto.replace(".", "").replace(",", "."))
                field.value = f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
            except InvalidOperation:
                pass
        if handler_previo:
            handler_previo(e)
        e.page.update()

    field.on_blur = on_blur


def parsear_decimal_ar_opcional(valor: str | None, etiqueta: str) -> Decimal | None:
    """Parsea un texto que puede o no venir con formato argentino (punto de miles,
    coma decimal) -- sirve tanto para un campo con mascara de moneda como para uno
    tipeado libremente con coma o punto decimal simple."""
    texto = (valor or "").strip()
    if not texto:
        return None
    try:
        return Decimal(texto.replace(".", "").replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"{etiqueta} invalido") from None
