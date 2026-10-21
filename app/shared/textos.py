"""Formato de los textos que se guardan (regla en CLAUDE.md, 'Formato de los textos'):

- mayusculas: todo nombre, de cosas y de personas (producto, cliente, proveedor, categoria, lista de
  precios, contactos). No rompe siglas: 'Limpihogar srl' -> 'LIMPIHOGAR SRL'.
- nombre_propio: no se usa al guardar; es para mostrar un nombre de persona en un texto armado (ej. el
  saludo de un mail): 'MARIA DE LOS ANGELES GOMEZ' -> 'Maria de los Angeles Gomez'.
- primera_mayuscula: configuracion interna (medios de pago, categorias de gasto): 'efectivo' -> 'Efectivo'.
- email: siempre en minusculas.

Todas sacan los espacios de mas, devuelven None si les llega None y son idempotentes (aplicarlas
dos veces da lo mismo), asi la migracion que normaliza los datos viejos se puede repetir sin
riesgo. Las usan los servicios al guardar; nunca la UI ni los repositorios."""

import re

_PARTICULAS = {"de", "del", "la", "las", "los", "y", "e", "da", "das", "do", "dos", "di", "van", "von"}


def _limpio(texto: str) -> str:
    return re.sub(r"\s+", " ", texto.strip())


def mayusculas(texto: str | None) -> str | None:
    return None if texto is None else _limpio(texto).upper()


def _palabra_propia(palabra: str) -> str:
    # 'gomez-rey' -> 'Gomez-Rey', "o'connor" -> "O'Connor", '(compras)' -> '(Compras)'
    return re.sub(r"[^\W\d_]+", lambda m: m.group(0)[0].upper() + m.group(0)[1:].lower(), palabra)


def nombre_propio(texto: str | None) -> str | None:
    if texto is None:
        return None
    palabras = _limpio(texto).split(" ")
    return " ".join(
        p.lower() if i > 0 and p.lower() in _PARTICULAS else _palabra_propia(p)
        for i, p in enumerate(palabras)
    )


def primera_mayuscula(texto: str | None) -> str | None:
    if texto is None:
        return None
    limpio = _limpio(texto)
    return limpio[:1].upper() + limpio[1:]


def email(texto: str | None) -> str | None:
    return None if texto is None else _limpio(texto).lower()
