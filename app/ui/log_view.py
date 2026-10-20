from datetime import datetime

import flet as ft

from app.services import log_service
from app.ui.componentes import ESPACIO_PANTALLA, Columna, Lista, barra, campo_buscar, encabezado_pantalla
from app.ui.theme import COLOR_TEXT_SOFT

ENTIDADES = {
    "venta": "Ventas", "presupuesto": "Presupuestos", "preventa": "Pre-ventas", "orden_compra": "Compras",
    "producto": "Productos", "categoria": "Categorias", "cliente": "Clientes", "proveedor": "Proveedores",
    "lista_precio": "Listas de precios", "medio_pago": "Medios de pago", "cheque": "Cheques", "gasto": "Gastos",
    "categoria_gasto": "Categorias de gasto", "negocio": "Datos del negocio", "sistema": "Sistema",
}


def LogView(page: ft.Page) -> ft.Control:
    entidad_dropdown = ft.Dropdown(
        label="Tipo", width=220, value="", on_select=lambda e: filtrar(),
        options=[ft.dropdown.Option(key="", text="Todos")] + [ft.dropdown.Option(key=k, text=v) for k, v in ENTIDADES.items()],
    )
    buscador_field = campo_buscar("Texto de la descripcion", al_cambiar=lambda: filtrar())
    lista = Lista(
        [Columna("Fecha", ancho=140), Columna("Tipo", ancho=170), Columna("Que paso", peso=6)],
        al_cambiar_pagina=lambda: refrescar(), nombre="registros", por_pagina=50,
        sin_datos="Nada registrado con estos filtros.",
    )

    def filtrar() -> None:
        lista.ir_al_principio()
        refrescar()

    def refrescar() -> None:
        resultado = log_service.listar_eventos_pagina(
            pagina=lista.pagina, tamano_pagina=lista.por_pagina,
            entidad=entidad_dropdown.value or None, texto=buscador_field.value or None,
        )
        lista.mostrar(resultado["items"], lambda e: [
            ft.Text(datetime.fromisoformat(e["fecha"]).strftime("%d/%m/%Y %H:%M"), color=COLOR_TEXT_SOFT),
            ENTIDADES.get(e["entidad"], e["entidad"]) + (f" #{e['entidad_id']}" if e["entidad_id"] is not None else ""),
            ft.Text(e["descripcion"], selectable=True),
        ], total=resultado["total"])
        page.update()

    refrescar()
    return ft.Column(
        [
            encabezado_pantalla("Historial", "Todo lo que se dio de alta, se modifico o se anulo, del mas nuevo al mas viejo."),
            barra([buscador_field, entidad_dropdown]),
            lista.control,
        ],
        expand=True, scroll=ft.ScrollMode.AUTO, spacing=ESPACIO_PANTALLA,
    )
