from decimal import Decimal, InvalidOperation

import flet as ft

from app.services import movimientos_service, productos_service
from app.services.movimientos_service import MOTIVOS_EGRESO, MOTIVOS_INGRESO
from app.shared.money import formatear_cantidad
from app.ui.campos import FILTRO_DECIMALES, parsear_decimal_ar_opcional
from app.ui.componentes import (
    ESPACIO_PANTALLA,
    ERRORES_PARA_AVISAR,
    TONO_ESPERA,
    TONO_OK,
    Columna,
    Lista,
    avisar,
    encabezado_pantalla,
    etiqueta_estado,
    tarjeta,
)
from app.ui.theme import COLOR_TEXT_SOFT

def MovimientosView(page: ft.Page) -> ft.Control:
    producto_dropdown = ft.Dropdown(label="Producto", options=[])
    tipo_dropdown = ft.Dropdown(
        label="Tipo",
        options=[ft.dropdown.Option("ingreso"), ft.dropdown.Option("egreso")],
        value="egreso",
    )
    cantidad_field = ft.TextField(label="Cantidad", hint_text="18,500")
    motivo_dropdown = ft.Dropdown(label="Motivo", width=280, options=[])
    costo_field = ft.TextField(
        label="Costo unitario (opcional)", width=220, input_filter=FILTRO_DECIMALES,
        helper="Vacio = el del ultimo lote del producto",
    )
    aviso_texto = ft.Text(
        "Aca solo se cargan ajustes (roturas, vencimientos, inventario). Las compras van por Compras, "
        "las ventas por la caja y las devoluciones con una nota de credito.",
        size=12, color=COLOR_TEXT_SOFT,
    )

    def actualizar_motivos(e: ft.ControlEvent | None = None) -> None:
        motivos = MOTIVOS_INGRESO if tipo_dropdown.value == "ingreso" else MOTIVOS_EGRESO
        motivo_dropdown.options = [ft.dropdown.Option(key=k, text=v) for k, v in motivos.items()]
        if motivo_dropdown.value not in motivos:
            motivo_dropdown.value = next(iter(motivos))
        costo_field.visible = tipo_dropdown.value == "ingreso"
        if e is not None:
            page.update()

    tipo_dropdown.on_select = actualizar_motivos
    actualizar_motivos()
    referencia_field = ft.TextField(label="Referencia (opcional)")
    observacion_field = ft.TextField(label="Observacion (opcional)")

    tipo_filtro = ft.Dropdown(label="Tipo", width=160, value="", on_select=lambda e: filtrar(), options=[
        ft.dropdown.Option(key="", text="Todos"), ft.dropdown.Option(key="ingreso", text="Entradas"),
        ft.dropdown.Option(key="egreso", text="Salidas"),
    ])
    lista = Lista(
        [Columna("Fecha", ancho=140), Columna("Producto", peso=4), Columna("Tipo", ancho=100),
         Columna("Cantidad", ancho=110, derecha=True), Columna("Motivo", peso=2), Columna("Referencia / observacion", peso=3)],
        al_cambiar_pagina=lambda: refrescar_tabla(), nombre="movimientos", sin_datos="No hay movimientos.",
    )

    def filtrar() -> None:
        lista.ir_al_principio()
        refrescar_tabla()

    def refrescar_productos() -> None:
        producto_dropdown.options = [
            ft.dropdown.Option(key=str(p["id"]), text=f"{p['codigo']} - {p['nombre']}")
            for p in productos_service.listar_productos(solo_activos=True)
        ]

    def refrescar_tabla() -> None:
        productos = {p["id"]: f"{p['codigo']} - {p['nombre']}" for p in productos_service.listar_productos()}
        resultado = movimientos_service.listar_movimientos_pagina(
            pagina=lista.pagina, tamano_pagina=lista.por_pagina, tipo=tipo_filtro.value or None,
        )
        lista.mostrar(resultado["items"], lambda m: [
            ft.Text(m["fecha"][:16].replace("T", " "), color=COLOR_TEXT_SOFT), productos.get(m["producto_id"], "?"),
            etiqueta_estado("Entrada", TONO_OK) if m["tipo"] == "ingreso" else etiqueta_estado("Salida", TONO_ESPERA),
            ("+" if m["tipo"] == "ingreso" else "-") + formatear_cantidad(m["cantidad"]), m["motivo_label"],
            " · ".join(x for x in (m["referencia"], m["observacion"]) if x) or None,
        ], total=resultado["total"])
        page.update()

    def guardar(e: ft.ControlEvent) -> None:
        try:
            if not producto_dropdown.value:
                raise ValueError("Elegi un producto")

            cantidad = Decimal((cantidad_field.value or "0").replace(",", "."))
            producto_id = int(producto_dropdown.value)
            motivo = motivo_dropdown.value
            referencia = referencia_field.value or None
            observacion = observacion_field.value or None

            if tipo_dropdown.value == "ingreso":
                movimientos_service.registrar_ingreso(
                    producto_id, cantidad, motivo, referencia, observacion,
                    costo_unitario=parsear_decimal_ar_opcional(costo_field.value, "El costo"),
                )
            else:
                movimientos_service.registrar_egreso(
                    producto_id, cantidad, motivo, referencia, observacion
                )

            cantidad_field.value = ""
            costo_field.value = ""
            referencia_field.value = ""
            observacion_field.value = ""
            lista.ir_al_principio()
            refrescar_tabla()
            es_ingreso = tipo_dropdown.value == "ingreso"
            motivos = MOTIVOS_INGRESO if es_ingreso else MOTIVOS_EGRESO
            avisar(page, f"Registrada la {'entrada' if es_ingreso else 'salida'} de {formatear_cantidad(cantidad)} "
                         f"({motivos.get(motivo, motivo)})")
        except InvalidOperation:
            avisar(page, "'Cantidad' no es un numero valido", error=True)
        except ERRORES_PARA_AVISAR as ex:
            avisar(page, str(ex), error=True)

    refrescar_productos()
    refrescar_tabla()

    encabezado = ft.Column(
        [
            encabezado_pantalla("Movimientos", "Entradas y salidas de stock. Los ajustes a mano (roturas, sobrantes) se cargan aca."),
            tarjeta(
                aviso_texto,
                ft.Row([producto_dropdown, tipo_dropdown, cantidad_field]),
                ft.Row([motivo_dropdown, costo_field, referencia_field, observacion_field],
                       vertical_alignment=ft.CrossAxisAlignment.START),
                ft.ElevatedButton("Registrar movimiento", on_click=guardar),
                titulo="Ajuste manual de stock",
            ),
        ],
        spacing=ESPACIO_PANTALLA,
    )

    return ft.Column(
        [encabezado, ft.Row([tipo_filtro]), lista.control],
        expand=True, scroll=ft.ScrollMode.AUTO, spacing=ESPACIO_PANTALLA,
    )
