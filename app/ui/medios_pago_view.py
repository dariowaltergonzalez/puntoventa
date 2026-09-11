import flet as ft

from app.services import medios_pago_service
from app.services.exceptions import MedioPagoDuplicadoError, MedioPagoNoEncontradoError

EXCEPCIONES_NEGOCIO = (MedioPagoDuplicadoError, MedioPagoNoEncontradoError, ValueError)


def MediosPagoView(page: ft.Page) -> ft.Control:
    nombre_field = ft.TextField(label="Nombre del medio de pago", expand=True)
    cuenta_corriente_switch = ft.Switch(label="Es cuenta corriente (genera cargo en Cuentas Corrientes)")
    activo_switch = ft.Switch(label="Activo", value=True, visible=False)
    guardar_button_texto = ft.Text("Agregar")
    guardar_button = ft.ElevatedButton(content=guardar_button_texto)
    cancelar_button = ft.TextButton("Cancelar", visible=False)
    tabla = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Nombre")),
            ft.DataColumn(ft.Text("Cuenta corriente")),
            ft.DataColumn(ft.Text("Activo")),
            ft.DataColumn(ft.Text("")),
        ],
        rows=[],
    )

    editando_id = None

    def mostrar_error(mensaje: str) -> None:
        page.show_dialog(ft.SnackBar(ft.Text(mensaje)))

    def limpiar_formulario() -> None:
        nonlocal editando_id
        editando_id = None
        nombre_field.value = ""
        cuenta_corriente_switch.value = False
        activo_switch.value = True
        activo_switch.visible = False
        guardar_button_texto.value = "Agregar"
        cancelar_button.visible = False

    def refrescar() -> None:
        tabla.rows = [
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(m["nombre"])),
                    ft.DataCell(ft.Text("Si" if m["es_cuenta_corriente"] else "No")),
                    ft.DataCell(ft.Text("Si" if m["activo"] else "No")),
                    ft.DataCell(
                        ft.IconButton(ft.Icons.EDIT, tooltip="Editar", data=m["id"], on_click=iniciar_edicion)
                    ),
                ]
            )
            for m in medios_pago_service.listar_medios_pago()
        ]
        page.update()

    def iniciar_edicion(e: ft.ControlEvent) -> None:
        nonlocal editando_id
        medio = medios_pago_service.obtener_medio_pago(e.control.data)
        if medio is None:
            return
        editando_id = medio["id"]
        nombre_field.value = medio["nombre"]
        cuenta_corriente_switch.value = medio["es_cuenta_corriente"]
        activo_switch.value = medio["activo"]
        activo_switch.visible = True
        guardar_button_texto.value = "Guardar cambios"
        cancelar_button.visible = True
        page.update()

    def cancelar(e: ft.ControlEvent) -> None:
        limpiar_formulario()
        page.update()

    def guardar(e: ft.ControlEvent) -> None:
        try:
            if editando_id is None:
                medios_pago_service.crear_medio_pago(nombre_field.value or "", cuenta_corriente_switch.value)
            else:
                medios_pago_service.actualizar_medio_pago(
                    editando_id, nombre_field.value or "", cuenta_corriente_switch.value, activo_switch.value,
                )
            limpiar_formulario()
            refrescar()
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_error(str(ex))

    guardar_button.on_click = guardar
    cancelar_button.on_click = cancelar

    refrescar()

    return ft.Column(
        [
            ft.Text("Medios de Pago", size=20, weight=ft.FontWeight.BOLD),
            ft.Row([nombre_field, cuenta_corriente_switch, activo_switch]),
            ft.Row([guardar_button, cancelar_button]),
            tabla,
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
