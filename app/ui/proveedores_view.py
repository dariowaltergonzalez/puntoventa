import flet as ft

from app.services import proveedores_service
from app.services.exceptions import ProveedorDuplicadoError, ProveedorNoEncontradoError


def ProveedoresView(page: ft.Page) -> ft.Control:
    nombre_field = ft.TextField(label="Nombre")
    cuit_field = ft.TextField(label="CUIT (opcional)")
    contacto_field = ft.TextField(label="Contacto (opcional)")
    telefono_field = ft.TextField(label="Telefono (opcional)")
    email_field = ft.TextField(label="Email (opcional)")
    direccion_field = ft.TextField(label="Direccion (opcional)")
    observaciones_field = ft.TextField(label="Observaciones (opcional)", multiline=True, min_lines=1, max_lines=3)
    activo_switch = ft.Switch(label="Activo", value=True, visible=False)
    guardar_button_texto = ft.Text("Agregar proveedor")
    guardar_button = ft.ElevatedButton(content=guardar_button_texto)
    cancelar_button = ft.TextButton("Cancelar", visible=False)
    buscador_field = ft.TextField(label="Buscar por nombre", expand=True)

    tabla = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Nombre")),
            ft.DataColumn(ft.Text("CUIT")),
            ft.DataColumn(ft.Text("Contacto")),
            ft.DataColumn(ft.Text("Telefono")),
            ft.DataColumn(ft.Text("Email")),
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
        cuit_field.value = ""
        contacto_field.value = ""
        telefono_field.value = ""
        email_field.value = ""
        direccion_field.value = ""
        observaciones_field.value = ""
        activo_switch.visible = False
        activo_switch.value = True
        guardar_button_texto.value = "Agregar proveedor"
        cancelar_button.visible = False

    def coincide_busqueda(proveedor: dict, texto: str) -> bool:
        texto = texto.strip().lower()
        if not texto:
            return True
        return texto in proveedor["nombre"].lower()

    def refrescar_tabla() -> None:
        proveedores = [
            p for p in proveedores_service.listar_proveedores() if coincide_busqueda(p, buscador_field.value or "")
        ]
        tabla.rows = [
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(p["nombre"])),
                    ft.DataCell(ft.Text(p["cuit"] or "-")),
                    ft.DataCell(ft.Text(p["contacto"] or "-")),
                    ft.DataCell(ft.Text(p["telefono"] or "-")),
                    ft.DataCell(ft.Text(p["email"] or "-")),
                    ft.DataCell(ft.Text("Si" if p["activo"] else "No")),
                    ft.DataCell(
                        ft.IconButton(ft.Icons.EDIT, tooltip="Editar", data=p["id"], on_click=iniciar_edicion)
                    ),
                ]
            )
            for p in proveedores
        ]
        page.update()

    def iniciar_edicion(e: ft.ControlEvent) -> None:
        nonlocal editando_id
        proveedor = proveedores_service.obtener_proveedor(e.control.data)
        if proveedor is None:
            return
        editando_id = proveedor["id"]
        nombre_field.value = proveedor["nombre"]
        cuit_field.value = proveedor["cuit"] or ""
        contacto_field.value = proveedor["contacto"] or ""
        telefono_field.value = proveedor["telefono"] or ""
        email_field.value = proveedor["email"] or ""
        direccion_field.value = proveedor["direccion"] or ""
        observaciones_field.value = proveedor["observaciones"] or ""
        activo_switch.value = proveedor["activo"]
        activo_switch.visible = True
        guardar_button_texto.value = "Guardar cambios"
        cancelar_button.visible = True
        page.update()

    def cancelar(e: ft.ControlEvent) -> None:
        limpiar_formulario()
        page.update()

    def buscar(e: ft.ControlEvent) -> None:
        refrescar_tabla()

    def guardar(e: ft.ControlEvent) -> None:
        try:
            if editando_id is None:
                proveedores_service.crear_proveedor(
                    nombre=nombre_field.value or "",
                    cuit=cuit_field.value,
                    contacto=contacto_field.value,
                    telefono=telefono_field.value,
                    email=email_field.value,
                    direccion=direccion_field.value,
                    observaciones=observaciones_field.value,
                )
            else:
                proveedores_service.actualizar_proveedor(
                    proveedor_id=editando_id,
                    nombre=nombre_field.value or "",
                    cuit=cuit_field.value,
                    contacto=contacto_field.value,
                    telefono=telefono_field.value,
                    email=email_field.value,
                    direccion=direccion_field.value,
                    observaciones=observaciones_field.value,
                    activo=activo_switch.value,
                )
            limpiar_formulario()
            refrescar_tabla()
        except (ProveedorDuplicadoError, ProveedorNoEncontradoError, ValueError) as ex:
            mostrar_error(str(ex))

    guardar_button.on_click = guardar
    cancelar_button.on_click = cancelar
    buscador_field.on_change = buscar

    refrescar_tabla()

    return ft.Column(
        [
            ft.Text("Proveedores", size=20, weight=ft.FontWeight.BOLD),
            ft.Row([nombre_field, cuit_field, contacto_field]),
            ft.Row([telefono_field, email_field, direccion_field, activo_switch]),
            ft.Row([observaciones_field]),
            ft.Row([guardar_button, cancelar_button]),
            ft.Row([buscador_field]),
            tabla,
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
