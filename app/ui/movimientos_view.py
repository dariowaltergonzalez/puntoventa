from decimal import Decimal, InvalidOperation

import flet as ft

from app.services import movimientos_service, productos_service
from app.services.exceptions import ProductoInactivoError, ProductoNoEncontradoError, StockInsuficienteError

MOTIVOS = ["compra", "venta", "devolucion", "ajuste"]


def MovimientosView(page: ft.Page) -> ft.Control:
    producto_dropdown = ft.Dropdown(label="Producto", options=[])
    tipo_dropdown = ft.Dropdown(
        label="Tipo",
        options=[ft.dropdown.Option("ingreso"), ft.dropdown.Option("egreso")],
        value="ingreso",
    )
    cantidad_field = ft.TextField(label="Cantidad", hint_text="18,500")
    motivo_dropdown = ft.Dropdown(
        label="Motivo",
        options=[ft.dropdown.Option(m) for m in MOTIVOS],
        value="compra",
    )
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
        tabla.rows = [
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(m["fecha"])),
                    ft.DataCell(ft.Text(nombre_producto(m["producto_id"]))),
                    ft.DataCell(ft.Text(m["tipo"])),
                    ft.DataCell(ft.Text(str(m["cantidad"]))),
                    ft.DataCell(ft.Text(m["motivo"])),
                ]
            )
            for m in movimientos_service.listar_movimientos()[:50]
        ]
        page.update()

    def guardar(e: ft.ControlEvent) -> None:
        try:
            if not producto_dropdown.value:
                raise ValueError("Elegi un producto")

            cantidad = Decimal((cantidad_field.value or "0").replace(",", "."))
            producto_id = int(producto_dropdown.value)
            motivo = motivo_dropdown.value or "ajuste"
            referencia = referencia_field.value or None
            observacion = observacion_field.value or None

            if tipo_dropdown.value == "ingreso":
                movimientos_service.registrar_ingreso(
                    producto_id, cantidad, motivo, referencia, observacion
                )
            else:
                movimientos_service.registrar_egreso(
                    producto_id, cantidad, motivo, referencia, observacion
                )

            cantidad_field.value = ""
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

    return ft.Column(
        [
            ft.Text("Movimientos", size=20, weight=ft.FontWeight.BOLD),
            ft.Row([producto_dropdown, tipo_dropdown, cantidad_field]),
            ft.Row([motivo_dropdown, referencia_field, observacion_field]),
            ft.ElevatedButton("Registrar movimiento", on_click=guardar),
            tabla,
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
