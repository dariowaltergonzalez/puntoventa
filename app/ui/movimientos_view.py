from decimal import Decimal, InvalidOperation

import flet as ft

from app.services import movimientos_service, productos_service
from app.services.movimientos_service import MOTIVOS_EGRESO, MOTIVOS_INGRESO
from app.services.exceptions import ProductoInactivoError, ProductoNoEncontradoError, StockInsuficienteError
from app.shared.money import formatear_cantidad
from app.ui.campos import FILTRO_DECIMALES, parsear_decimal_ar_opcional
from app.ui.listados import Paginador, con_scroll_horizontal
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

    tabla = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Fecha")),
            ft.DataColumn(ft.Text("Producto")),
            ft.DataColumn(ft.Text("Tipo")),
            ft.DataColumn(ft.Text("Cantidad")),
            ft.DataColumn(ft.Text("Motivo")),
        ],
        rows=[],
    )

    paginador = Paginador(on_cambio=lambda: refrescar_tabla())

    def mostrar_error(mensaje: str) -> None:
        page.show_dialog(ft.SnackBar(ft.Text(mensaje)))

    def nombre_producto(producto_id: int) -> str:
        producto = productos_service.obtener_producto(producto_id)
        return f"{producto['codigo']} - {producto['nombre']}" if producto else "?"

    def refrescar_productos() -> None:
        producto_dropdown.options = [
            ft.dropdown.Option(key=str(p["id"]), text=f"{p['codigo']} - {p['nombre']}")
            for p in productos_service.listar_productos(solo_activos=True)
        ]

    def refrescar_tabla() -> None:
        resultado = movimientos_service.listar_movimientos_pagina(
            pagina=paginador.pagina_actual, tamano_pagina=paginador.tamano_pagina,
        )
        paginador.fijar_total(resultado["total"])
        tabla.rows = [
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(m["fecha"])),
                    ft.DataCell(ft.Text(nombre_producto(m["producto_id"]))),
                    ft.DataCell(ft.Text(m["tipo"])),
                    ft.DataCell(ft.Text(formatear_cantidad(m["cantidad"]))),
                    ft.DataCell(ft.Text(m["motivo_label"])),
                ]
            )
            for m in resultado["items"]
        ]
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
            refrescar_tabla()
        except InvalidOperation:
            mostrar_error("'Cantidad' no es un numero valido")
        except (
            ProductoNoEncontradoError,
            ProductoInactivoError,
            StockInsuficienteError,
            ValueError,
        ) as ex:
            mostrar_error(str(ex))

    refrescar_productos()
    refrescar_tabla()

    encabezado = ft.Column(
        [
            ft.Text("Movimientos", size=20, weight=ft.FontWeight.BOLD),
            aviso_texto,
            ft.Row([producto_dropdown, tipo_dropdown, cantidad_field]),
            ft.Row([motivo_dropdown, costo_field, referencia_field, observacion_field],
                   vertical_alignment=ft.CrossAxisAlignment.START),
            ft.ElevatedButton("Registrar movimiento", on_click=guardar),
        ],
        spacing=10,
    )

    zona_tabla = ft.Column(
        [
            con_scroll_horizontal(tabla),
            paginador.controles,
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=10,
    )

    return ft.Column([encabezado, zona_tabla], expand=True, spacing=10)
