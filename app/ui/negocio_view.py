from decimal import Decimal

import flet as ft

from app.services import condiciones_iva_service, email_service, negocio_service
from app.services.exceptions import CorreoNoConfiguradoError, EnvioCorreoError, NegocioNoConfiguradoError
from app.ui.campos import FILTRO_CUIT, FILTRO_DECIMALES, FILTRO_ENTEROS, parsear_decimal_ar_opcional
from app.ui.listados import con_scroll_horizontal
from app.ui.theme import COLOR_SUCCESS, COLOR_TEXT_SOFT, COLOR_WARNING
from app.ui.componentes import ESPACIO_PANTALLA, encabezado_pantalla, tarjeta

EXCEPCIONES_NEGOCIO = (NegocioNoConfiguradoError, CorreoNoConfiguradoError, EnvioCorreoError, ValueError)

SEGURIDAD_LABEL = {"starttls": "STARTTLS (puerto 587)", "ssl": "SSL (puerto 465)", "ninguna": "Ninguna"}


def NegocioView(page: ft.Page) -> ft.Control:
    def mostrar_mensaje(texto: str) -> None:
        page.show_dialog(ft.SnackBar(ft.Text(texto)))

    # ================= Identidad legal =================
    razon_social_field = ft.TextField(label="Razon social / titular *", expand=True,
                                      helper="Nombre legal: el que figura en la chequera")
    cuit_field = ft.TextField(label="CUIT *", width=170, input_filter=FILTRO_CUIT)
    condicion_iva_dropdown = ft.Dropdown(label="Condicion frente al IVA", width=230, options=[])
    nombre_fantasia_field = ft.TextField(label="Nombre de fantasia", expand=True,
                                         helper="La marca: lo que va grande en el membrete")
    ingresos_brutos_field = ft.TextField(label="N° de Ingresos Brutos", width=200)
    inicio_actividades_field = ft.TextField(label="Inicio de actividades (AAAA-MM-DD)", width=260)
    # IVA: lo usa toda la app (ventas, presupuestos, compras, ganancia). Solo el Responsable
    # Inscripto cobra IVA; monotributo / exento venden sin IVA y no recuperan el de sus compras.
    precios_con_iva_switch = ft.Switch(label="El precio de los productos es el precio final (el que paga el cliente)", value=True)
    alicuota_iva_field = ft.TextField(label="Alicuota de IVA %", width=150, input_filter=FILTRO_DECIMALES)
    iva_explicacion_texto = ft.Text("", size=12, color=COLOR_TEXT_SOFT)

    def explicar_iva(e: ft.ControlEvent | None = None) -> None:
        nombre = next((o.text for o in condicion_iva_dropdown.options if o.key == condicion_iva_dropdown.value), "")
        es_ri = nombre == negocio_service.CONDICION_QUE_COBRA_IVA
        precios_con_iva_switch.disabled = not es_ri
        alicuota_iva_field.disabled = not es_ri
        if not condicion_iva_dropdown.value:
            iva_explicacion_texto.value = "Elegi la condicion frente al IVA: sin eso la app vende sin IVA y la caja lo avisa."
        elif not es_ri:
            iva_explicacion_texto.value = (f"{nombre}: las ventas van sin IVA, y el IVA de las compras se toma como costo "
                                           "(no se recupera).")
        elif precios_con_iva_switch.value:
            iva_explicacion_texto.value = ("El cliente paga el precio del producto, como en el cartel. La app separa adentro "
                                           "cuanto es del negocio y cuanto es IVA (para la ganancia y el comprobante).")
        else:
            iva_explicacion_texto.value = ("Precios '+ IVA' (como un mayorista): a cada venta se le suma el IVA encima "
                                           "del precio del producto.")
        if e is not None:
            page.update()

    condicion_iva_dropdown.on_select = explicar_iva
    precios_con_iva_switch.on_change = explicar_iva

    # ================= Contacto =================
    direccion_field = ft.TextField(label="Calle y numero", expand=True)
    ciudad_field = ft.TextField(label="Ciudad", width=200)
    provincia_field = ft.TextField(label="Provincia", width=180)
    codigo_postal_field = ft.TextField(label="Codigo postal", width=130)
    telefono_field = ft.TextField(label="Telefono", width=180)
    email_field = ft.TextField(label="Email", expand=True)
    web_field = ft.TextField(label="Web / redes", expand=True)

    # ================= Correo saliente =================
    smtp_servidor_field = ft.TextField(label="Servidor SMTP", width=240, hint_text="smtp.gmail.com")
    smtp_puerto_field = ft.TextField(label="Puerto", width=100, input_filter=FILTRO_ENTEROS)
    smtp_seguridad_dropdown = ft.Dropdown(
        label="Seguridad", width=220,
        options=[ft.dropdown.Option(key=k, text=v) for k, v in SEGURIDAD_LABEL.items()],
    )
    smtp_usuario_field = ft.TextField(label="Usuario", width=260)
    smtp_password_field = ft.TextField(label="Contrasena", width=240, password=True, can_reveal_password=True)
    smtp_password_estado = ft.Text("", size=12)
    smtp_remitente_nombre_field = ft.TextField(label="Nombre del remitente", width=260)
    smtp_remitente_email_field = ft.TextField(label="Email del remitente", expand=True)

    def usar_gmail(e: ft.ControlEvent) -> None:
        smtp_servidor_field.value = "smtp.gmail.com"
        smtp_puerto_field.value = "587"
        smtp_seguridad_dropdown.value = "starttls"
        page.update()

    usar_gmail_button = ft.TextButton("Completar con los datos de Gmail", on_click=usar_gmail)
    probar_mail_button = ft.ElevatedButton("Enviar mail de prueba")
    guardar_button = ft.ElevatedButton("Guardar datos del negocio")

    # ================= Cuentas bancarias =================
    tabla_cuentas = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(t)) for t in ["", "Banco", "Titular", "CUIT titular", "CBU", "Alias", ""]],
        rows=[],
    )
    cuenta_banco_field = ft.TextField(label="Banco *", width=180)
    cuenta_titular_field = ft.TextField(label="Titular (vacio = el negocio)", width=230)
    cuenta_cuit_field = ft.TextField(label="CUIT titular (vacio = el negocio)", width=230, input_filter=FILTRO_CUIT)
    cuenta_cbu_field = ft.TextField(label="CBU (22 digitos)", width=230, input_filter=FILTRO_ENTEROS, max_length=22)
    cuenta_alias_field = ft.TextField(label="Alias", width=180)
    cuenta_principal_switch = ft.Switch(label="Principal")
    agregar_cuenta_button = ft.ElevatedButton("+ Agregar cuenta")

    # ================= WhatsApp =================
    tabla_whatsapp = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(t)) for t in ["", "Numero", "Etiqueta", ""]],
        rows=[],
    )
    whatsapp_numero_field = ft.TextField(label="Numero *", width=220, hint_text="11 2233-4455")
    whatsapp_etiqueta_field = ft.TextField(label="Etiqueta (ej. Ventas)", width=200)
    whatsapp_principal_switch = ft.Switch(label="Principal")
    agregar_whatsapp_button = ft.ElevatedButton("+ Agregar WhatsApp")

    def boton_principal(es_principal: bool, on_click) -> ft.IconButton:
        return ft.IconButton(
            ft.Icons.STAR if es_principal else ft.Icons.STAR_BORDER,
            icon_color=COLOR_WARNING if es_principal else COLOR_TEXT_SOFT,
            tooltip="Principal" if es_principal else "Marcar como principal",
            on_click=on_click,
        )

    # ================= Carga / refresco =================
    def texto(valor) -> str:
        return "" if valor is None else str(valor)

    def refrescar() -> None:
        condicion_iva_dropdown.options = [ft.dropdown.Option(key="", text="Sin elegir")] + [
            ft.dropdown.Option(key=str(c["id"]), text=c["nombre"])
            for c in condiciones_iva_service.listar_condiciones_iva(solo_activas=True)
        ]
        negocio = negocio_service.obtener_negocio() or {}
        razon_social_field.value = texto(negocio.get("razon_social"))
        cuit_field.value = texto(negocio.get("cuit"))
        condicion_iva_dropdown.value = texto(negocio.get("condicion_iva_id"))
        precios_con_iva_switch.value = bool(negocio.get("precios_incluyen_iva", True))
        alicuota_iva_field.value = texto(negocio.get("alicuota_iva", "21")).replace(".00", "").replace(".", ",")
        explicar_iva()
        nombre_fantasia_field.value = texto(negocio.get("nombre_fantasia"))
        ingresos_brutos_field.value = texto(negocio.get("ingresos_brutos"))
        inicio_actividades_field.value = texto(negocio.get("inicio_actividades"))
        direccion_field.value = texto(negocio.get("direccion"))
        ciudad_field.value = texto(negocio.get("ciudad"))
        provincia_field.value = texto(negocio.get("provincia"))
        codigo_postal_field.value = texto(negocio.get("codigo_postal"))
        telefono_field.value = texto(negocio.get("telefono"))
        email_field.value = texto(negocio.get("email"))
        web_field.value = texto(negocio.get("web"))
        smtp_servidor_field.value = texto(negocio.get("smtp_servidor"))
        smtp_puerto_field.value = texto(negocio.get("smtp_puerto"))
        smtp_seguridad_dropdown.value = negocio.get("smtp_seguridad")
        smtp_usuario_field.value = texto(negocio.get("smtp_usuario"))
        smtp_remitente_nombre_field.value = texto(negocio.get("smtp_remitente_nombre"))
        smtp_remitente_email_field.value = texto(negocio.get("smtp_remitente_email"))
        smtp_password_field.value = ""
        if negocio.get("smtp_tiene_password"):
            smtp_password_estado.value = "Hay una contrasena guardada. Deja el campo vacio para no cambiarla."
            smtp_password_estado.color = COLOR_SUCCESS
        else:
            smtp_password_estado.value = "Todavia no hay contrasena guardada."
            smtp_password_estado.color = COLOR_TEXT_SOFT

        tabla_cuentas.rows = [
            ft.DataRow(cells=[
                ft.DataCell(boton_principal(c["es_principal"], lambda e, cid=c["id"]: marcar_cuenta_principal(cid))),
                ft.DataCell(ft.Text(c["banco"])),
                ft.DataCell(ft.Text(c["titular"])),
                ft.DataCell(ft.Text(c["cuit_titular"] or "-")),
                ft.DataCell(ft.Text(c["cbu"] or "-")),
                ft.DataCell(ft.Text(c["alias"] or "-")),
                ft.DataCell(ft.IconButton(ft.Icons.DELETE, tooltip="Quitar cuenta",
                                          on_click=lambda e, cid=c["id"]: quitar_cuenta(cid))),
            ])
            for c in negocio_service.listar_cuentas_bancarias()
        ]
        tabla_whatsapp.rows = [
            ft.DataRow(cells=[
                ft.DataCell(boton_principal(w["es_principal"], lambda e, wid=w["id"]: marcar_whatsapp_principal(wid))),
                ft.DataCell(ft.Text(f"+{w['numero']}")),
                ft.DataCell(ft.Text(w["etiqueta"] or "-")),
                ft.DataCell(ft.IconButton(ft.Icons.DELETE, tooltip="Quitar WhatsApp",
                                          on_click=lambda e, wid=w["id"]: quitar_whatsapp(wid))),
            ])
            for w in negocio_service.listar_whatsapp()
        ]
        page.update()

    # ================= Acciones =================
    def guardar(e: ft.ControlEvent | None = None) -> bool:
        try:
            puerto = (smtp_puerto_field.value or "").strip()
            negocio_service.guardar_negocio(
                razon_social=razon_social_field.value,
                cuit=cuit_field.value,
                condicion_iva_id=int(condicion_iva_dropdown.value) if condicion_iva_dropdown.value else None,
                nombre_fantasia=nombre_fantasia_field.value,
                ingresos_brutos=ingresos_brutos_field.value,
                inicio_actividades=inicio_actividades_field.value,
                direccion=direccion_field.value,
                ciudad=ciudad_field.value,
                provincia=provincia_field.value,
                codigo_postal=codigo_postal_field.value,
                telefono=telefono_field.value,
                email=email_field.value,
                web=web_field.value,
                smtp_servidor=smtp_servidor_field.value,
                smtp_puerto=int(puerto) if puerto else None,
                smtp_seguridad=smtp_seguridad_dropdown.value or None,
                smtp_usuario=smtp_usuario_field.value,
                smtp_remitente_nombre=smtp_remitente_nombre_field.value,
                smtp_remitente_email=smtp_remitente_email_field.value,
                precios_incluyen_iva=precios_con_iva_switch.value,
                alicuota_iva=parsear_decimal_ar_opcional(alicuota_iva_field.value, "La alicuota de IVA") or Decimal("21"),
            )
            if smtp_password_field.value:
                negocio_service.guardar_password_smtp(smtp_password_field.value)
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))
            return False
        refrescar()
        if e is not None:
            mostrar_mensaje("Datos del negocio guardados")
        return True

    guardar_button.on_click = guardar

    def probar_mail(e: ft.ControlEvent) -> None:
        # Se guarda primero: asi se prueba exactamente lo que se ve en pantalla.
        if not guardar():
            return
        probar_mail_button.disabled = True
        mostrar_mensaje("Enviando mail de prueba...")
        try:
            destinatario = email_service.enviar_mail_de_prueba()
            mostrar_mensaje(f"Mail de prueba enviado a {destinatario}. Revisa la bandeja de entrada.")
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))
        finally:
            probar_mail_button.disabled = False
            page.update()

    probar_mail_button.on_click = probar_mail

    def agregar_cuenta(e: ft.ControlEvent) -> None:
        try:
            negocio_service.agregar_cuenta_bancaria(
                cuenta_banco_field.value, cuenta_titular_field.value, cuenta_cuit_field.value,
                cuenta_cbu_field.value, cuenta_alias_field.value, cuenta_principal_switch.value,
            )
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))
            return
        for campo in (cuenta_banco_field, cuenta_titular_field, cuenta_cuit_field, cuenta_cbu_field, cuenta_alias_field):
            campo.value = ""
        cuenta_principal_switch.value = False
        refrescar()

    agregar_cuenta_button.on_click = agregar_cuenta

    def quitar_cuenta(cuenta_id: int) -> None:
        negocio_service.quitar_cuenta_bancaria(cuenta_id)
        refrescar()

    def marcar_cuenta_principal(cuenta_id: int) -> None:
        negocio_service.marcar_cuenta_bancaria_principal(cuenta_id)
        refrescar()

    def agregar_whatsapp(e: ft.ControlEvent) -> None:
        try:
            negocio_service.agregar_whatsapp(
                whatsapp_numero_field.value or "", whatsapp_etiqueta_field.value, whatsapp_principal_switch.value,
            )
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))
            return
        whatsapp_numero_field.value = ""
        whatsapp_etiqueta_field.value = ""
        whatsapp_principal_switch.value = False
        refrescar()

    agregar_whatsapp_button.on_click = agregar_whatsapp

    def quitar_whatsapp(whatsapp_id: int) -> None:
        negocio_service.quitar_whatsapp(whatsapp_id)
        refrescar()

    def marcar_whatsapp_principal(whatsapp_id: int) -> None:
        negocio_service.marcar_whatsapp_principal(whatsapp_id)
        refrescar()

    vista = ft.Column(
        [
            encabezado_pantalla("Datos del negocio", "Los datos que salen en los presupuestos, ordenes de compra y mails."),
            tarjeta(
                ft.Row([razon_social_field, cuit_field, condicion_iva_dropdown], vertical_alignment=ft.CrossAxisAlignment.START),
                ft.Row([precios_con_iva_switch, alicuota_iva_field, iva_explicacion_texto],
                       vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
                ft.Row([nombre_fantasia_field, ingresos_brutos_field, inicio_actividades_field],
                       vertical_alignment=ft.CrossAxisAlignment.START),
                titulo="Identidad legal",
            ),
            tarjeta(
                ft.Row([direccion_field, ciudad_field, provincia_field, codigo_postal_field]),
                ft.Row([telefono_field, email_field, web_field]),
                titulo="Contacto",
            ),
            tarjeta(
                ft.Row([smtp_servidor_field, smtp_puerto_field, smtp_seguridad_dropdown, usar_gmail_button]),
                ft.Row([smtp_usuario_field, ft.Column([smtp_password_field, smtp_password_estado], spacing=2)],
                       vertical_alignment=ft.CrossAxisAlignment.START),
                ft.Row([smtp_remitente_nombre_field, smtp_remitente_email_field]),
                ft.Row([probar_mail_button]),
                titulo="Correo saliente (SMTP)",
                subtitulo="Para mandar presupuestos y ordenes de compra por mail. Con Gmail hace falta una "
                          "'contrasena de aplicacion', no la contrasena normal de la cuenta.",
            ),
            ft.Row([guardar_button]),
            tarjeta(
                con_scroll_horizontal(tabla_cuentas),
                ft.Row([cuenta_banco_field, cuenta_titular_field, cuenta_cuit_field, cuenta_cbu_field, cuenta_alias_field,
                        cuenta_principal_switch, agregar_cuenta_button], wrap=True),
                titulo="Cuentas bancarias",
                subtitulo="La principal se propone al pagar con un cheque propio (banco, librador y CUIT).",
            ),
            tarjeta(
                con_scroll_horizontal(tabla_whatsapp),
                ft.Row([whatsapp_numero_field, whatsapp_etiqueta_field, whatsapp_principal_switch, agregar_whatsapp_button]),
                titulo="WhatsApp",
                subtitulo="Se guarda en formato internacional para poder mandar mensajes con un link.",
            ),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=ESPACIO_PANTALLA,
    )
    refrescar()
    return vista
