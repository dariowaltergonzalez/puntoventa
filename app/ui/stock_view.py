import flet as ft

from app.services import categorias_service, lotes_service, movimientos_service
from app.shared.money import formatear_cantidad, formatear_precio
from app.ui.componentes import (
    ESPACIO_PANTALLA,
    TONO_ESPERA,
    TONO_NO,
    TONO_OK,
    Columna,
    Lista,
    avisar,
    barra,
    boton_secundario,
    campo_buscar,
    encabezado_pantalla,
    etiqueta_estado,
    tabla_simple,
)
from app.ui.theme import COLOR_DANGER


def _situacion(p: dict) -> str:
    if p["stock_actual"] <= 0:
        return "sin_stock"
    if p["stock_minimo"] > 0 and p["stock_actual"] < p["stock_minimo"]:
        return "bajo"
    return "ok"


ETIQUETAS = {"sin_stock": ("Sin stock", TONO_NO), "bajo": ("Bajo el minimo", TONO_ESPERA), "ok": ("OK", TONO_OK)}


def StockView(page: ft.Page) -> ft.Control:
    buscador_field = campo_buscar("Nombre o codigo", al_cambiar=lambda: filtrar())
    categoria_dropdown = ft.Dropdown(label="Categoria", width=200, value="", on_select=lambda e: filtrar())
    situacion_dropdown = ft.Dropdown(label="Situacion", width=190, value="", on_select=lambda e: filtrar(), options=[
        ft.dropdown.Option(key="", text="Todos"), ft.dropdown.Option(key="faltantes", text="Para reponer"),
        ft.dropdown.Option(key="ok", text="OK"),
    ])
    lista = Lista(
        [
            Columna("Codigo", ancho=100, orden="codigo"), Columna("Nombre", peso=4, orden="nombre"),
            Columna("Categoria", peso=2, orden="categoria"), Columna("Unidad", ancho=80),
            Columna("Stock", ancho=100, derecha=True, orden="stock_actual"),
            Columna("Stock minimo", ancho=110, derecha=True, orden="stock_minimo"), Columna("Situacion", ancho=130),
        ],
        al_cambiar_pagina=lambda: refrescar(), nombre="productos", con_hijos=True, orden_inicial=("nombre", False),
        sin_datos="Ningun producto coincide con los filtros.",
    )

    def hijos(p: dict) -> ft.Control:
        lotes = lotes_service.listar_lotes_producto(p["id"])
        filas = [[l["fecha"][:10], l["numero_oc"], l["numero_remito"], formatear_cantidad(l["cantidad_recibida"]),
                  formatear_cantidad(l["cantidad_restante"]), formatear_precio(l["costo_unitario"])] for l in lotes]
        sin_lote = p["stock_actual"] - sum(l["cantidad_restante"] for l in lotes)
        if sin_lote > 0:
            filas.append(["-", None, None, None, formatear_cantidad(sin_lote), "Sin lote (carga previa)"])
        return tabla_simple(["Ingreso", "OC", "Remito", "Entraron", "Quedan", "Costo"], filas,
                            derecha=[3, 4, 5], vacio="Sin lotes: nunca entro mercaderia de este producto.")

    def filtrar() -> None:
        lista.ir_al_principio()
        refrescar()

    def refrescar() -> None:
        categorias = {c["id"]: c["nombre"] for c in categorias_service.listar_categorias()}
        texto = (buscador_field.value or "").strip().lower()
        productos = []
        for p in movimientos_service.consultar_stock(categoria_id=int(categoria_dropdown.value) if categoria_dropdown.value else None):
            situacion = _situacion(p)
            if texto not in f"{p['nombre']} {p['codigo']}".lower():
                continue
            if situacion_dropdown.value == "faltantes" and situacion == "ok":
                continue
            if situacion_dropdown.value == "ok" and situacion != "ok":
                continue
            productos.append(dict(p, categoria=categorias.get(p["categoria_id"], "?"), situacion=situacion))
        lista.mostrar(productos, lambda p: [
            ft.Text(p["codigo"], size=12.5, font_family="Consolas"), p["nombre"], p["categoria"], p["unidad"],
            ft.Text(formatear_cantidad(p["stock_actual"]), weight=ft.FontWeight.BOLD if p["situacion"] != "ok" else None,
                    color=COLOR_DANGER if p["situacion"] != "ok" else None),
            formatear_cantidad(p["stock_minimo"]), etiqueta_estado(*ETIQUETAS[p["situacion"]]),
        ], hijos=hijos)
        page.update()

    def recalcular() -> None:
        diferencias = movimientos_service.recalcular_stock()
        refrescar()
        avisar(page, f"Se corrigieron {len(diferencias)} producto(s) con stock desactualizado." if diferencias
               else "El stock ya estaba bien: no se encontraron diferencias.")

    categoria_dropdown.options = [ft.dropdown.Option(key="", text="Todas")] + [
        ft.dropdown.Option(key=str(c["id"]), text=c["nombre"]) for c in categorias_service.listar_categorias()
    ]
    refrescar()
    return ft.Column(
        [
            encabezado_pantalla("Stock", "Cuanto hay de cada producto. Abri una fila para ver sus lotes y su costo."),
            barra([buscador_field, categoria_dropdown, situacion_dropdown],
                  [boton_secundario("Recalcular stock", ft.Icons.REFRESH, recalcular)]),
            lista.control,
        ],
        expand=True, scroll=ft.ScrollMode.AUTO, spacing=ESPACIO_PANTALLA,
    )
