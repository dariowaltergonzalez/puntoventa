from decimal import Decimal, ROUND_HALF_UP

CANTIDAD_ESCALA = 1000  # 3 decimales
PRECIO_ESCALA = 100  # 2 decimales
PORCENTAJE_ESCALA = 100  # 2 decimales; puede ser negativo (descuento) o positivo (recargo)


def cantidad_a_entero(valor: Decimal) -> int:
    escalado = (Decimal(valor) * CANTIDAD_ESCALA).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(escalado)


def entero_a_cantidad(valor: int) -> Decimal:
    return (Decimal(valor) / CANTIDAD_ESCALA).quantize(Decimal("1.000"))


def precio_a_entero(valor: Decimal) -> int:
    escalado = (Decimal(valor) * PRECIO_ESCALA).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(escalado)


def entero_a_precio(valor: int) -> Decimal:
    return (Decimal(valor) / PRECIO_ESCALA).quantize(Decimal("1.00"))


def porcentaje_a_entero(valor: Decimal) -> int:
    escalado = (Decimal(valor) * PORCENTAJE_ESCALA).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(escalado)


def entero_a_porcentaje(valor: int) -> Decimal:
    return (Decimal(valor) / PORCENTAJE_ESCALA).quantize(Decimal("1.00"))


def _formatear_es_ar(valor: Decimal, decimales: int) -> str:
    """Formatea un Decimal al estilo argentino: punto para miles, coma para decimales."""
    texto = f"{valor:,.{decimales}f}"
    return texto.replace(",", "_").replace(".", ",").replace("_", ".")


def formatear_precio(valor: Decimal) -> str:
    return _formatear_es_ar(valor, 2)


def formatear_cantidad(valor: Decimal) -> str:
    return _formatear_es_ar(valor, 3)


def formatear_porcentaje(valor: Decimal) -> str:
    return _formatear_es_ar(valor, 2)
