"""Prueba manual del modulo reutilizable app/ui/listados.py (filtros + paginacion).
Correr con: python scripts/verificar_listados.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui.listados import Paginador, coincide_exacto, coincide_texto, filtrar


def main():
    items = [{"nombre": f"Item {i}", "estado": "A" if i % 2 == 0 else "B"} for i in range(25)]

    solo_a = filtrar(items, [lambda x: coincide_exacto(x["estado"], "A")])
    print("Items estado A:", len(solo_a))
    assert len(solo_a) == 13

    busq = filtrar(items, [lambda x: coincide_texto(x["nombre"], "item 1")])
    print("Coinciden con 'item 1':", [x["nombre"] for x in busq])
    assert len(busq) == 11  # Item 1, 10-19

    combinado = filtrar(items, [
        lambda x: coincide_exacto(x["estado"], "A"),
        lambda x: coincide_texto(x["nombre"], "item 1"),
    ])
    print("Estado A + 'item 1':", [x["nombre"] for x in combinado])

    p = Paginador(on_cambio=lambda: None, tamano_inicial=10)
    pagina1 = p.aplicar(items)
    print("Pagina 1:", len(pagina1), "-", p.texto_estado.value)
    assert len(pagina1) == 10
    assert p.total_paginas() == 3
    assert p.primero_button.disabled is True
    assert p.siguiente_button.disabled is False

    p.pagina_actual = 3
    pagina3 = p.aplicar(items)
    print("Pagina 3:", len(pagina3), "-", p.texto_estado.value)
    assert len(pagina3) == 5
    assert p.siguiente_button.disabled is True

    print("\nOK: filtrar + Paginador funcionan correctamente")


if __name__ == "__main__":
    main()
