from decimal import Decimal, InvalidOperation

import flet as ft

from app.services import clientes_service, condiciones_iva_service, listas_precios_service
from app.services.exceptions import (
    ClienteDuplicadoError,
    ClienteNoEncontradoError,
    CondicionIvaNoEncontradaError,
    ListaPrecioNoEncontradaError,
)
from app.shared.money import formatear_precio, formatear_porcentaje
from app.ui.campos import (
    FILTRO_CUIT,
    FILTRO_DECIMALES,
    FILTRO_ENTEROS,
    aplicar_mascara_moneda,
    parsear_decimal_ar_opcional,
)
from app.ui.listados import Paginador, coincide_exacto, coincide_texto, filtrar

EXCEPCIONES_NEGOCIO = (
    ClienteDuplicadoError, ClienteNoEncontradoError, CondicionIvaNoEncontradaError,
    ListaPrecioNoEncontradaError, ValueError,
)


def ClientesView(page: ft.Page) -> ft.Control:
    def mostrar_mensaje(texto: str) -> None:
        page.show_dialog(ft.SnackBar(ft.Text(texto)))

    def parsear_decimal_opcional(valor: str | None, etiqueta: str) -> Decimal | None:
        texto = (valor or "").strip()
        if not texto:
            return None
        try:
            return Decimal(texto.replace(",", "."))
        except InvalidOperation:
            raise ValueError(f"{etiqueta} invalido") from None

    def parsear_entero_opcional(valor: str | None, etiqueta: str) -> int | None:
        texto = (valor or "").strip()
        if not texto:
            return None
        try:
            return int(texto)
        except ValueError:
            raise ValueError(f"{etiqueta} invalido") from None

    # ================= SECCION LISTA =================
    buscador_field = ft.TextField(label="Buscar por razon social o nombre de fantasia", expand=True)
    activo_filtro_dropdown = ft.Dropdown(
        label="Filtrar por estado", width=180, value="",
        options=[ft.dropdown.Option(key="", text="Todos"), ft.dropdown.Option(key="1", text="Activos"),
                 ft.dropdown.Option(key="0", text="Inactivos")],
    )
    nuevo_cliente_button = ft.ElevatedButton("+ Nuevo cliente")

    tabla_lista = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(t)) for t in
                 ["Razon social", "Nombre fantasia", "Telefono", "Email", "Activo", ""]],
        rows=[],
    )

    paginador = Paginador(on_cambio=lambda: refrescar_lista())

    def construir_fila_cliente(c: dict) -> ft.DataRow:
        return ft.DataRow(cells=[
            ft.DataCell(ft.Text(c["razon_social"])),
            ft.DataCell(ft.Text(c["nombre_fantasia"] or "-")),
            ft.DataCell(ft.Text(c["telefono"] or "-")),
            ft.DataCell(ft.Text(c["email"] or "-")),
            ft.DataCell(ft.Text("Si" if c["activo"] else "No")),
            ft.DataCell(ft.Row([
                ft.IconButton(ft.Icons.VISIBILITY, tooltip="Ver detalle / editar", data=c["id"],
                              on_click=lambda e: ir_a_detalle(e.control.data)),
                ft.IconButton(ft.Icons.ACCOUNT_BALANCE_WALLET, tooltip="Estado de cuenta",
                              data=c["id"], on_click=mostrar_estado_cuenta_aviso),
            ])),
        ])

    def mostrar_estado_cuenta_aviso(e: ft.ControlEvent) -> None:
        mostrar_mensaje("Para ver el estado de cuenta, anda al menu 'Cuentas Corrientes' y buscá a este cliente.")

    def refrescar_lista(e: ft.ControlEvent | None = None) -> None:
        todos = clientes_service.listar_clientes()
        filtrados = filtrar(todos, [
            lambda c: coincide_texto(c["razon_social"], buscador_field.value) or coincide_texto(c["nombre_fantasia"], buscador_field.value),
            lambda c: coincide_exacto(1 if c["activo"] else 0, int(activo_filtro_dropdown.value) if activo_filtro_dropdown.value else None),
        ])
        pagina = paginador.aplicar(filtrados)
        tabla_lista.rows = [construir_fila_cliente(c) for c in pagina]
        page.update()

    buscador_field.on_change = refrescar_lista
    activo_filtro_dropdown.on_select = refrescar_lista
    nuevo_cliente_button.on_click = lambda e: ir_a_formulario(None)

    seccion_lista = ft.Column([
        ft.Text("Clientes", size=20, weight=ft.FontWeight.BOLD),
        ft.Row([buscador_field, activo_filtro_dropdown, nuevo_cliente_button]),
        tabla_lista,
        paginador.controles,
    ])

    # ================= SECCION FORMULARIO =================
    form_titulo = ft.Text("", size=18, weight=ft.FontWeight.BOLD)
    razon_social_field = ft.TextField(label="Razon social", expand=True)
    nombre_fantasia_field = ft.TextField(label="Nombre de fantasia (opcional)", expand=True)
    dni_field = ft.TextField(label="DNI (opcional)", width=150, input_filter=FILTRO_ENTEROS)
    cuit_field = ft.TextField(label="CUIT (opcional)", width=150, input_filter=FILTRO_CUIT)
    contacto_principal_field = ft.TextField(label="Contacto principal (opcional)", expand=True)
    telefono_field = ft.TextField(label="Telefono (opcional)", width=180)
    email_field = ft.TextField(label="Email (opcional)", expand=True)
    direccion_field = ft.TextField(label="Direccion (opcional)", expand=True)
    ciudad_field = ft.TextField(label="Ciudad (opcional)", width=180)
    provincia_field = ft.TextField(label="Provincia (opcional)", width=180)
    codigo_postal_field = ft.TextField(label="Codigo postal (opcional)", width=140)
    condicion_iva_options = [
        ft.dropdown.Option(key="", text="Sin elegir")
    ] + [
        ft.dropdown.Option(key=str(c["id"]), text=c["nombre"])
        for c in condiciones_iva_service.listar_condiciones_iva(solo_activas=True)
    ]
    condicion_iva_dropdown = ft.Dropdown(label="Condicion ante el IVA (opcional)", width=220, value="", options=condicion_iva_options)
    plazo_pago_field = ft.TextField(label="Plazo de pago habitual, en dias (opcional)", width=220, input_filter=FILTRO_ENTEROS)
    porcentaje_descuento_field = ft.TextField(label="% de descuento (opcional)", width=180, hint_text="ej: 10", input_filter=FILTRO_DECIMALES)
    limite_credito_field = ft.TextField(label="Limite de credito (opcional)", width=180, input_filter=FILTRO_DECIMALES)
    avisar_limite_switch = ft.Switch(label="Avisar al superar el limite", value=False)
    bloquear_limite_switch = ft.Switch(label="Bloquear al superar el limite", value=False)
    tasa_mora_field = ft.TextField(label="Interes por mora diario % (opcional)", width=220, input_filter=FILTRO_DECIMALES)
    observacion_field = ft.TextField(label="Observacion (opcional)", expand=True, multiline=True, min_lines=1, max_lines=3)
    activo_switch = ft.Switch(label="Activo", value=True, visible=False)

    aplicar_mascara_moneda(limite_credito_field)

    guardar_form_texto = ft.Text("Crear cliente")
    guardar_form_button = ft.ElevatedButton(content=guardar_form_texto)
    cancelar_form_button = ft.TextButton("Cancelar", on_click=lambda e: ir_a_lista(None))

    editando_cliente_id: int | None = None

    def limpiar_formulario() -> None:
        nonlocal editando_cliente_id
        editando_cliente_id = None
        for campo in (razon_social_field, nombre_fantasia_field, dni_field, cuit_field, contacto_principal_field,
                      telefono_field, email_field, direccion_field, ciudad_field, provincia_field,
                      codigo_postal_field, plazo_pago_field, porcentaje_descuento_field,
                      limite_credito_field, tasa_mora_field, observacion_field):
            campo.value = ""
        condicion_iva_dropdown.value = ""
        avisar_limite_switch.value = False
        bloquear_limite_switch.value = False
        activo_switch.value = True
        activo_switch.visible = False
        guardar_form_texto.value = "Crear cliente"
        form_titulo.value = "Nuevo cliente"

    def cargar_formulario(c: dict) -> None:
        nonlocal editando_cliente_id
        editando_cliente_id = c["id"]
        razon_social_field.value = c["razon_social"]
        nombre_fantasia_field.value = c["nombre_fantasia"] or ""
        dni_field.value = c["dni"] or ""
        cuit_field.value = c["cuit"] or ""
        contacto_principal_field.value = c["contacto_principal"] or ""
        telefono_field.value = c["telefono"] or ""
        email_field.value = c["email"] or ""
        direccion_field.value = c["direccion"] or ""
        ciudad_field.value = c["ciudad"] or ""
        provincia_field.value = c["provincia"] or ""
        codigo_postal_field.value = c["codigo_postal"] or ""
        condicion_iva_dropdown.value = str(c["condicion_iva_id"]) if c["condicion_iva_id"] is not None else ""
        plazo_pago_field.value = str(c["plazo_pago_dias"]) if c["plazo_pago_dias"] is not None else ""
        porcentaje_descuento_field.value = str(c["porcentaje_descuento"]) if c["porcentaje_descuento"] is not None else ""
        limite_credito_field.value = formatear_precio(c["limite_credito"]) if c["limite_credito"] is not None else ""
        avisar_limite_switch.value = c["avisar_limite_credito"]
        bloquear_limite_switch.value = c["bloquear_limite_credito"]
        tasa_mora_field.value = str(c["tasa_interes_mora_diaria"]) if c["tasa_interes_mora_diaria"] is not None else ""
        observacion_field.value = c["observacion"] or ""
        activo_switch.value = c["activo"]
        activo_switch.visible = True
        guardar_form_texto.value = "Guardar cambios"
        form_titulo.value = f"Editar cliente - {c['razon_social']}"

    def guardar_formulario(e: ft.ControlEvent) -> None:
        try:
            datos = dict(
                razon_social=razon_social_field.value or "",
                nombre_fantasia=nombre_fantasia_field.value,
                dni=dni_field.value,
                cuit=cuit_field.value,
                contacto_principal=contacto_principal_field.value,
                telefono=telefono_field.value,
                email=email_field.value,
                direccion=direccion_field.value,
                ciudad=ciudad_field.value,
                provincia=provincia_field.value,
                codigo_postal=codigo_postal_field.value,
                condicion_iva_id=int(condicion_iva_dropdown.value) if condicion_iva_dropdown.value else None,
                plazo_pago_dias=parsear_entero_opcional(plazo_pago_field.value, "El plazo de pago"),
                porcentaje_descuento=parsear_decimal_opcional(porcentaje_descuento_field.value, "El % de descuento"),
                limite_credito=parsear_decimal_ar_opcional(limite_credito_field.value, "El limite de credito"),
                avisar_limite_credito=avisar_limite_switch.value,
                bloquear_limite_credito=bloquear_limite_switch.value,
                tasa_interes_mora_diaria=parsear_decimal_opcional(tasa_mora_field.value, "La tasa de interes por mora"),
                observacion=observacion_field.value,
            )
            if editando_cliente_id is None:
                cliente = clientes_service.crear_cliente(**datos)
            else:
                cliente = clientes_service.actualizar_cliente(
                    cliente_id=editando_cliente_id, activo=activo_switch.value, **datos,
                )
            limpiar_formulario()
            ir_a_detalle(cliente["id"])
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))

    guardar_form_button.on_click = guardar_formulario

    seccion_formulario = ft.Column(
        [
            form_titulo,
            ft.Row([razon_social_field, nombre_fantasia_field]),
            ft.Row([dni_field, cuit_field, contacto_principal_field]),
            ft.Row([telefono_field, email_field]),
            ft.Row([direccion_field, ciudad_field, provincia_field, codigo_postal_field]),
            ft.Row([condicion_iva_dropdown, plazo_pago_field, porcentaje_descuento_field]),
            ft.Row([limite_credito_field, avisar_limite_switch, bloquear_limite_switch, tasa_mora_field]),
            ft.Row([observacion_field]),
            ft.Row([activo_switch]),
            ft.Row([guardar_form_button, cancelar_form_button]),
        ],
        visible=False,
        scroll=ft.ScrollMode.AUTO,
    )

    # ================= SECCION DETALLE =================
    detalle_cliente_id: int | None = None
    detalle_titulo = ft.Text("", size=18, weight=ft.FontWeight.BOLD)
    detalle_info = ft.Text("")
    editar_button = ft.ElevatedButton("Editar")
    volver_button = ft.TextButton("Volver al listado", on_click=lambda e: ir_a_lista(None))

    tabla_contactos = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(t)) for t in ["Nombre", "Sector", "Email", "Telefono", "Principal", ""]],
        rows=[],
    )
    contacto_nombre_field = ft.TextField(label="Nombre", width=180)
    contacto_sector_field = ft.TextField(label="Sector (opcional)", width=150)
    contacto_email_field = ft.TextField(label="Email (opcional)", width=200)
    contacto_telefono_field = ft.TextField(label="Telefono (opcional)", width=150)
    contacto_principal_switch = ft.Switch(label="Es el principal")
    agregar_contacto_button = ft.ElevatedButton("+ Agregar contacto")

    def agregar_contacto(e: ft.ControlEvent) -> None:
        try:
            clientes_service.agregar_contacto(
                detalle_cliente_id, contacto_nombre_field.value or "", contacto_email_field.value,
                contacto_telefono_field.value, contacto_sector_field.value, contacto_principal_switch.value,
            )
            contacto_nombre_field.value = ""
            contacto_sector_field.value = ""
            contacto_email_field.value = ""
            contacto_telefono_field.value = ""
            contacto_principal_switch.value = False
            refrescar_detalle()
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))

    agregar_contacto_button.on_click = agregar_contacto

    listas_dropdown = ft.Dropdown(label="Agregar lista de precios", width=250, options=[])
    agregar_lista_button = ft.ElevatedButton("+ Agregar")
    tabla_listas_cliente = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(t)) for t in ["Prioridad", "Lista", "", ""]],
        rows=[],
    )

    def refrescar_dropdown_listas(listas_ya_asignadas: set[int]) -> None:
        listas_dropdown.options = [
            ft.dropdown.Option(key=str(l["id"]), text=l["nombre"])
            for l in listas_precios_service.listar_listas(solo_activas=True)
            if l["id"] not in listas_ya_asignadas
        ]

    def agregar_lista(e: ft.ControlEvent) -> None:
        if not listas_dropdown.value:
            return
        try:
            cliente = clientes_service.obtener_cliente(detalle_cliente_id)
            orden_actual = [l["lista_precio_id"] for l in cliente["listas_precios"]]
            orden_actual.append(int(listas_dropdown.value))
            clientes_service.asignar_listas_precios(detalle_cliente_id, orden_actual)
            listas_dropdown.value = None
            refrescar_detalle()
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))

    def quitar_lista(e: ft.ControlEvent) -> None:
        try:
            cliente = clientes_service.obtener_cliente(detalle_cliente_id)
            orden_actual = [l["lista_precio_id"] for l in cliente["listas_precios"] if l["lista_precio_id"] != e.control.data]
            clientes_service.asignar_listas_precios(detalle_cliente_id, orden_actual)
            refrescar_detalle()
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))

    def mover_lista(lista_id: int, delta: int) -> None:
        cliente = clientes_service.obtener_cliente(detalle_cliente_id)
        orden_actual = [l["lista_precio_id"] for l in cliente["listas_precios"]]
        i = orden_actual.index(lista_id)
        j = i + delta
        if 0 <= j < len(orden_actual):
            orden_actual[i], orden_actual[j] = orden_actual[j], orden_actual[i]
            clientes_service.asignar_listas_precios(detalle_cliente_id, orden_actual)
            refrescar_detalle()

    agregar_lista_button.on_click = agregar_lista

    def refrescar_detalle() -> None:
        cliente = clientes_service.obtener_cliente(detalle_cliente_id)
        detalle_titulo.value = cliente["razon_social"] + (f" ({cliente['nombre_fantasia']})" if cliente["nombre_fantasia"] else "")
        partes = [f"Activo: {'Si' if cliente['activo'] else 'No'}"]
        if cliente["telefono"]:
            partes.append(f"Tel: {cliente['telefono']}")
        if cliente["email"]:
            partes.append(f"Email: {cliente['email']}")
        if cliente["condicion_iva_nombre"]:
            partes.append(f"IVA: {cliente['condicion_iva_nombre']}")
        if cliente["plazo_pago_dias"] is not None:
            partes.append(f"Plazo de pago: {cliente['plazo_pago_dias']} dias")
        if cliente["porcentaje_descuento"] is not None:
            partes.append(f"Descuento: {formatear_porcentaje(cliente['porcentaje_descuento'])}%")
        if cliente["limite_credito"] is not None:
            comportamiento = []
            if cliente["avisar_limite_credito"]:
                comportamiento.append("avisa")
            if cliente["bloquear_limite_credito"]:
                comportamiento.append("bloquea")
            sufijo = f" ({' y '.join(comportamiento)} al superarlo)" if comportamiento else ""
            partes.append(f"Limite de credito: {formatear_precio(cliente['limite_credito'])}{sufijo}")
        if cliente["tasa_interes_mora_diaria"] is not None:
            partes.append(f"Interes por mora: {formatear_porcentaje(cliente['tasa_interes_mora_diaria'])}% diario")
        detalle_info.value = "   |   ".join(partes)

        tabla_contactos.rows = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Text(c["nombre"])),
                ft.DataCell(ft.Text(c["sector"] or "-")),
                ft.DataCell(ft.Text(c["email"] or "-")),
                ft.DataCell(ft.Text(c["telefono"] or "-")),
                ft.DataCell(ft.Text("Si" if c["es_principal"] else "No")),
                ft.DataCell(ft.IconButton(ft.Icons.DELETE, tooltip="Quitar contacto", data=c["id"],
                                          on_click=lambda e, cid=c["id"]: quitar_contacto(cid))),
            ])
            for c in cliente["contactos"]
        ]

        listas_asignadas = cliente["listas_precios"]
        refrescar_dropdown_listas({l["lista_precio_id"] for l in listas_asignadas})
        tabla_listas_cliente.rows = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Text(str(l["prioridad"]))),
                ft.DataCell(ft.Text(l["nombre"])),
                ft.DataCell(ft.Row([
                    ft.IconButton(ft.Icons.ARROW_UPWARD, icon_size=16, tooltip="Subir prioridad",
                                  data=l["lista_precio_id"], on_click=lambda e, lid=l["lista_precio_id"]: mover_lista(lid, -1)),
                    ft.IconButton(ft.Icons.ARROW_DOWNWARD, icon_size=16, tooltip="Bajar prioridad",
                                  data=l["lista_precio_id"], on_click=lambda e, lid=l["lista_precio_id"]: mover_lista(lid, 1)),
                ])),
                ft.DataCell(ft.IconButton(ft.Icons.DELETE, tooltip="Quitar lista", data=l["lista_precio_id"],
                                          on_click=quitar_lista)),
            ])
            for l in listas_asignadas
        ]
        page.update()

    def quitar_contacto(contacto_id: int) -> None:
        clientes_service.quitar_contacto(contacto_id, detalle_cliente_id)
        refrescar_detalle()

    def editar_desde_detalle(e: ft.ControlEvent) -> None:
        cargar_formulario(clientes_service.obtener_cliente(detalle_cliente_id))
        ir_a_formulario_directo()

    editar_button.on_click = editar_desde_detalle

    seccion_detalle = ft.Column(
        [
            detalle_titulo,
            detalle_info,
            ft.Row([editar_button, volver_button]),
            ft.Text("Contactos auxiliares", weight=ft.FontWeight.BOLD),
            tabla_contactos,
            ft.Row([contacto_nombre_field, contacto_sector_field, contacto_email_field, contacto_telefono_field,
                    contacto_principal_switch, agregar_contacto_button]),
            ft.Text("Listas de precios asignadas (por orden de prioridad)", weight=ft.FontWeight.BOLD),
            tabla_listas_cliente,
            ft.Row([listas_dropdown, agregar_lista_button]),
        ],
        visible=False,
        scroll=ft.ScrollMode.AUTO,
    )

    # ================= NAVEGACION =================
    def ir_a_lista(e: ft.ControlEvent | None) -> None:
        seccion_lista.visible = True
        seccion_formulario.visible = False
        seccion_detalle.visible = False
        refrescar_lista()
        page.update()

    def ir_a_formulario(cliente_id: int | None) -> None:
        limpiar_formulario()
        if cliente_id is not None:
            cargar_formulario(clientes_service.obtener_cliente(cliente_id))
        seccion_lista.visible = False
        seccion_formulario.visible = True
        seccion_detalle.visible = False
        page.update()

    def ir_a_formulario_directo() -> None:
        seccion_lista.visible = False
        seccion_formulario.visible = True
        seccion_detalle.visible = False
        page.update()

    def ir_a_detalle(cliente_id: int) -> None:
        nonlocal detalle_cliente_id
        detalle_cliente_id = cliente_id
        seccion_lista.visible = False
        seccion_formulario.visible = False
        seccion_detalle.visible = True
        refrescar_detalle()
        page.update()

    refrescar_lista()

    return ft.Column(
        [seccion_lista, seccion_formulario, seccion_detalle],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
