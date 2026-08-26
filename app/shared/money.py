from decimal import Decimal, ROUND_HALF_UP

CANTIDAD_ESCALA = 1000  # 3 decimales
PRECIO_ESCALA = 100  # 2 decimales


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
