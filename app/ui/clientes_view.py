from decimal import Decimal, InvalidOperation

import flet as ft

from app.services import clientes_service, condiciones_iva_service, listas_precios_service
from app.shared.money import formatear_porcentaje, formatear_precio
from app.ui.campos import (
    FILTRO_CUIT,
    FILTRO_DECIMALES,
    FILTRO_ENTEROS,
    aplicar_formato_texto,
    aplicar_mascara_moneda,
    parsear_decimal_ar_opcional,
)
from app.ui.componentes import (
    ESPACIO_PANTALLA,
    ERRORES_PARA_AVISAR,
    TONO_NO,
    TONO_OK,
    Columna,
    Lista,
    accion_abrir,
    accion_cambiar,
    accion_ver,
    avisar,
    barra,
    boton_principal,
    botones_formulario,
    campo_buscar,
    dato,
    encabezado_pantalla,
    etiqueta_estado,
    rotulo,
    tabla_simple,
    tarjeta,
    ventana_info,
)
from app.ui.theme import COLOR_TEXT_SOFT
from app.shared import textos


def _decimal_opcional(valor: str | None, etiqueta: str) -> Decimal | None:
    texto = (valor or "").strip()
    if not texto:
        return None
    try:
        return Decimal(texto.replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"{etiqueta} invalido") from None


def _entero_opcional(valor: str | None, etiqueta: str) -> int | None:
    texto = (valor or "").strip()
    if not texto:
        return None
    try:
        return int(texto)
    except ValueError:
        raise ValueError(f"{etiqueta} invalido") from None


def ClientesView(page: ft.Page) -> ft.Control:
    editando: dict | None = None

    # ================= Lista =================
    buscador_field = campo_buscar("Razon social, nombre de fantasia o CUIT", al_cambiar=lambda: filtrar())
    estado_filtro = ft.Dropdown(label="Estado", width=160, value="", on_select=lambda e: filtrar(), options=[
        ft.dropdown.Option(key="", text="Todos"), ft.dropdown.Option(key="activos", text="Activos"),
        ft.dropdown.Option(key="inactivos", text="Inactivos"),
    ])
    lista = Lista(
        [
            Columna("Razon social", peso=3, orden="razon_social"), Columna("Nombre de fantasia", peso=2, orden="nombre_fantasia"),
            Columna("CUIT / DNI", ancho=130), Columna("Telefono", peso=2), Columna("Email", peso=3),
            Columna("Estado", ancho=90), Columna("Acciones", ancho=170, derecha=True),
        ],
        al_cambiar_pagina=lambda: refrescar(), nombre="clientes", con_hijos=True, orden_inicial=("razon_social", False),
        sin_datos="Ningun cliente coincide con la busqueda.",
    )

    def filtrar() -> None:
        lista.ir_al_principio()
        refrescar()

    def hijos(c: dict) -> ft.Control:
        completo = clientes_service.obtener_cliente(c["id"])
        return ft.Row([
            ft.Column([rotulo("Contactos"), tabla_simple(
                ["Nombre", "Sector", "Email", "Telefono", ""],
                [[x["nombre"], x["sector"], x["email"], x["telefono"], "Principal" if x["es_principal"] else ""]
                 for x in completo["contactos"]], vacio="Sin contactos cargados.")], spacing=6),
            ft.Column([rotulo("Listas de precios, por prioridad"), tabla_simple(
                ["#", "Lista"], [[str(x["prioridad"]), x["nombre"]] for x in completo["listas_precios"]],
                vacio="Sin listas asignadas.")], spacing=6),
        ], spacing=28, vertical_alignment=ft.CrossAxisAlignment.START, wrap=True)

    def refrescar() -> None:
        texto = (buscador_field.value or "").strip().lower()
        clientes = [
            c for c in clientes_service.listar_clientes()
            if texto in f"{c['razon_social']} {c['nombre_fantasia'] or ''} {c['cuit'] or ''}".lower()
            and (estado_filtro.value != "activos" or c["activo"])
            and (estado_filtro.value != "inactivos" or not c["activo"])
        ]
        lista.mostrar(clientes, lambda c: [
            c["razon_social"], c["nombre_fantasia"], c["cuit"] or c["dni"], c["telefono"], c["email"],
            etiqueta_estado("Activo", TONO_OK) if c["activo"] else etiqueta_estado("Inactivo", TONO_NO),
            ft.Row([
                accion_ver(ft.Icons.VISIBILITY, "Ver ficha del cliente", lambda c=c: ver_ficha(c)),
                accion_abrir(ft.Icons.ACCOUNT_BALANCE_WALLET, "Ver cuenta corriente",
                             lambda c=c: page.abrir_cuenta_corriente("cliente", c["id"])),
                accion_abrir(ft.Icons.EDIT, "Editar cliente", lambda c=c: ir_a_formulario(c)),
                accion_cambiar(
                    ft.Icons.POWER_SETTINGS_NEW, "Desactivar cliente" if c["activo"] else "Activar cliente",
                    lambda c=c: cambiar_activo(c),
                    por_que_no="lo usa la caja para las ventas sin cliente"
                    if c["activo"] and clientes_service.es_cliente_generico(c) else None,
                ),
            ], spacing=0, tight=True),
        ], hijos=hijos)
        page.update()

    def cambiar_activo(c: dict) -> str:
        clientes_service.cambiar_activo(c["id"], not c["activo"])
        refrescar()
        return (f"{c['razon_social']}: activado" if not c["activo"]
                else f"{c['razon_social']}: desactivado (ya no se ofrece en la caja)")

    def ver_ficha(c: dict) -> None:
        c = clientes_service.obtener_cliente(c["id"])
        limite = "-"
        if c["limite_credito"] is not None:
            que_hace = [x for x, si in (("avisa", c["avisar_limite_credito"]), ("bloquea", c["bloquear_limite_credito"])) if si]
            limite = f"$ {formatear_precio(c['limite_credito'])}" + (f" ({' y '.join(que_hace)} al superarlo)" if que_hace else "")
        direccion = ", ".join(x for x in (c["direccion"], c["ciudad"], c["provincia"], c["codigo_postal"]) if x)
        ventana_info(
            page, c["razon_social"],
            dato("Nombre de fantasia", c["nombre_fantasia"] or "-"),
            dato("CUIT / DNI", " / ".join(x for x in (c["cuit"], c["dni"]) if x) or "-"),
            dato("Condicion de IVA", c["condicion_iva_nombre"] or "-"),
            dato("Contacto principal", c["contacto_principal"] or "-"),
            dato("Telefono / email", " / ".join(x for x in (c["telefono"], c["email"]) if x) or "-"),
            dato("Direccion", direccion or "-"),
            dato("Plazo de pago", f"{c['plazo_pago_dias']} dias" if c["plazo_pago_dias"] is not None else "-"),
            dato("Descuento", f"{formatear_porcentaje(c['porcentaje_descuento'])} %" if c["porcentaje_descuento"] is not None else "-"),
            dato("Limite de credito", limite),
            dato("Interes por mora", f"{formatear_porcentaje(c['tasa_interes_mora_diaria'])} % diario"
                 if c["tasa_interes_mora_diaria"] is not None else "-"),
            dato("Observacion", c["observacion"] or "-"),
        )

    seccion_lista = ft.Column([
        barra([buscador_field, estado_filtro],
              [boton_principal("Nuevo cliente", ft.Icons.ADD, lambda: ir_a_formulario(None))]),
        lista.control,
    ], spacing=ESPACIO_PANTALLA)

    # ================= Formulario: datos del cliente =================
    form_titulo = ft.Text("", size=15, weight=ft.FontWeight.BOLD)
    guardar_texto = ft.Text("")
    razon_social_field = ft.TextField(label="Razon social *", expand=True)
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
    condicion_iva_dropdown = ft.Dropdown(label="Condicion ante el IVA (opcional)", width=240, value="", options=[
        ft.dropdown.Option(key="", text="Sin elegir"),
        *[ft.dropdown.Option(key=str(c["id"]), text=c["nombre"]) for c in condiciones_iva_service.listar_condiciones_iva(solo_activas=True)],
    ])
    plazo_pago_field = ft.TextField(label="Plazo de pago, en dias (opcional)", width=220, input_filter=FILTRO_ENTEROS)
    porcentaje_descuento_field = ft.TextField(label="% de descuento (opcional)", width=180, hint_text="ej: 10", input_filter=FILTRO_DECIMALES)
    limite_credito_field = ft.TextField(label="Limite de credito (opcional)", width=180, input_filter=FILTRO_DECIMALES)
    aplicar_mascara_moneda(limite_credito_field)
    avisar_limite_switch = ft.Switch(label="Avisar al superar el limite")
    bloquear_limite_switch = ft.Switch(label="Bloquear al superar el limite")
    tasa_mora_field = ft.TextField(label="Interes por mora diario % (opcional)", width=240, input_filter=FILTRO_DECIMALES)
    observacion_field = ft.TextField(label="Observacion (opcional)", expand=True, multiline=True, min_lines=1, max_lines=3)
    aplicar_formato_texto(textos.mayusculas, razon_social_field)
    aplicar_formato_texto(textos.mayusculas, contacto_principal_field)
    aplicar_formato_texto(textos.email, email_field)
    campos_texto = {
        "razon_social": razon_social_field, "nombre_fantasia": nombre_fantasia_field, "dni": dni_field, "cuit": cuit_field,
        "contacto_principal": contacto_principal_field, "telefono": telefono_field, "email": email_field,
        "direccion": direccion_field, "ciudad": ciudad_field, "provincia": provincia_field, "codigo_postal": codigo_postal_field,
        "observacion": observacion_field,
    }

    def ir_a_formulario(cliente: dict | None) -> None:
        nonlocal editando
        editando = clientes_service.obtener_cliente(cliente["id"]) if cliente else None
        c = editando or {}
        form_titulo.value = f"Editar cliente: {c['razon_social']}" if editando else "Nuevo cliente"
        guardar_texto.value = "Guardar cambios" if editando else "Crear cliente"
        for clave, campo in campos_texto.items():
            campo.value = c.get(clave) or ""
        condicion_iva_dropdown.value = str(c["condicion_iva_id"]) if c.get("condicion_iva_id") is not None else ""
        plazo_pago_field.value = str(c["plazo_pago_dias"]) if c.get("plazo_pago_dias") is not None else ""
        porcentaje_descuento_field.value = str(c["porcentaje_descuento"]) if c.get("porcentaje_descuento") is not None else ""
        limite_credito_field.value = formatear_precio(c["limite_credito"]) if c.get("limite_credito") is not None else ""
        tasa_mora_field.value = str(c["tasa_interes_mora_diaria"]) if c.get("tasa_interes_mora_diaria") is not None else ""
        avisar_limite_switch.value = bool(c.get("avisar_limite_credito"))
        bloquear_limite_switch.value = bool(c.get("bloquear_limite_credito"))
        tarjeta_contactos.visible = tarjeta_listas.visible = editando is not None
        aviso_hijos.visible = editando is None
        if editando:
            refrescar_hijos()
        seccion_lista.visible = False
        seccion_formulario.visible = True
        page.update()

    def volver_a_lista() -> None:
        seccion_formulario.visible = False
        seccion_lista.visible = True
        refrescar()

    def guardar() -> None:
        try:
            datos = {clave: campo.value for clave, campo in campos_texto.items()}
            datos["razon_social"] = datos["razon_social"] or ""
            datos.update(
                condicion_iva_id=int(condicion_iva_dropdown.value) if condicion_iva_dropdown.value else None,
                plazo_pago_dias=_entero_opcional(plazo_pago_field.value, "El plazo de pago"),
                porcentaje_descuento=_decimal_opcional(porcentaje_descuento_field.value, "El % de descuento"),
                limite_credito=parsear_decimal_ar_opcional(limite_credito_field.value, "El limite de credito"),
                avisar_limite_credito=avisar_limite_switch.value, bloquear_limite_credito=bloquear_limite_switch.value,
                tasa_interes_mora_diaria=_decimal_opcional(tasa_mora_field.value, "La tasa de interes por mora"),
            )
            if editando is None:
                cliente = clientes_service.crear_cliente(**datos)
                aviso = f"Cliente '{cliente['razon_social']}' creado. Para sumarle contactos o listas, usa el lapiz."
            else:
                cliente = clientes_service.actualizar_cliente(cliente_id=editando["id"], activo=editando["activo"], **datos)
                aviso = f"Cliente '{cliente['razon_social']}' guardado"
        except ERRORES_PARA_AVISAR as ex:
            avisar(page, str(ex), error=True)
            return
        volver_a_lista()
        avisar(page, aviso)

    # ================= Formulario: hijos (se guardan al instante) =================
    contactos_tabla = ft.Column(spacing=6)
    contacto_nombre_field = ft.TextField(label="Nombre *", width=180)
    contacto_sector_field = ft.TextField(label="Sector (opcional)", width=150)
    contacto_email_field = ft.TextField(label="Email (opcional)", width=220)
    contacto_telefono_field = ft.TextField(label="Telefono (opcional)", width=160)
    contacto_principal_switch = ft.Switch(label="Es el principal")
    aplicar_formato_texto(textos.mayusculas, contacto_nombre_field)
    aplicar_formato_texto(textos.email, contacto_email_field)
    listas_tabla = ft.Column(spacing=6)
    listas_dropdown = ft.Dropdown(label="Lista de precios", width=250, options=[])

    def refrescar_hijos() -> None:
        c = clientes_service.obtener_cliente(editando["id"])
        contactos_tabla.controls = [tabla_simple(
            ["Nombre", "Sector", "Email", "Telefono", "", ""],
            [[x["nombre"], x["sector"], x["email"], x["telefono"], "Principal" if x["es_principal"] else "",
              ft.IconButton(ft.Icons.CLOSE, icon_size=18, icon_color=COLOR_TEXT_SOFT, tooltip="Quitar contacto",
                            on_click=lambda e, x=x: quitar_contacto(x))] for x in c["contactos"]],
            vacio="Sin contactos cargados.",
        )]
        asignadas = c["listas_precios"]
        listas_tabla.controls = [tabla_simple(
            ["#", "Lista", ""],
            [[str(x["prioridad"]), x["nombre"], ft.Row([
                ft.IconButton(ft.Icons.ARROW_UPWARD, icon_size=18, icon_color=COLOR_TEXT_SOFT, tooltip="Subir prioridad",
                              on_click=lambda e, x=x: mover_lista(x["lista_precio_id"], -1)),
                ft.IconButton(ft.Icons.ARROW_DOWNWARD, icon_size=18, icon_color=COLOR_TEXT_SOFT, tooltip="Bajar prioridad",
                              on_click=lambda e, x=x: mover_lista(x["lista_precio_id"], 1)),
                ft.IconButton(ft.Icons.CLOSE, icon_size=18, icon_color=COLOR_TEXT_SOFT, tooltip="Quitar lista",
                              on_click=lambda e, x=x: quitar_lista(x)),
            ], spacing=0, tight=True)] for x in asignadas],
            vacio="Sin listas asignadas.",
        )]
        ya = {x["lista_precio_id"] for x in asignadas}
        listas_dropdown.options = [ft.dropdown.Option(key=str(x["id"]), text=x["nombre"])
                                   for x in listas_precios_service.listar_listas(solo_activas=True) if x["id"] not in ya]
        listas_dropdown.value = None

    def con_aviso(funcion, *args) -> None:
        try:
            aviso = funcion(*args)
        except ERRORES_PARA_AVISAR as ex:
            avisar(page, str(ex), error=True)
            return
        refrescar_hijos()
        page.update()
        if aviso:
            avisar(page, aviso)

    def agregar_contacto() -> str:
        clientes_service.agregar_contacto(
            editando["id"], contacto_nombre_field.value or "", contacto_email_field.value,
            contacto_telefono_field.value, contacto_sector_field.value, contacto_principal_switch.value,
        )
        nombre = textos.mayusculas(contacto_nombre_field.value or "")
        for campo in (contacto_nombre_field, contacto_sector_field, contacto_email_field, contacto_telefono_field):
            campo.value = ""
        contacto_principal_switch.value = False
        return f"Contacto '{nombre}' agregado"

    def quitar_contacto(x: dict) -> None:
        con_aviso(lambda: (clientes_service.quitar_contacto(x["id"], editando["id"]), f"Contacto '{x['nombre']}' quitado")[1])

    def orden_listas() -> list[int]:
        return [x["lista_precio_id"] for x in clientes_service.obtener_cliente(editando["id"])["listas_precios"]]

    def agregar_lista() -> str | None:
        if not listas_dropdown.value:
            raise ValueError("Elegi una lista de precios")
        clientes_service.asignar_listas_precios(editando["id"], orden_listas() + [int(listas_dropdown.value)])
        return "Lista de precios agregada"

    def quitar_lista(x: dict) -> None:
        con_aviso(lambda: (clientes_service.asignar_listas_precios(
            editando["id"], [i for i in orden_listas() if i != x["lista_precio_id"]]), f"Lista '{x['nombre']}' quitada")[1])

    def mover_lista(lista_id: int, delta: int) -> None:
        orden = orden_listas()
        i, j = orden.index(lista_id), orden.index(lista_id) + delta
        if 0 <= j < len(orden):
            orden[i], orden[j] = orden[j], orden[i]
            con_aviso(lambda: clientes_service.asignar_listas_precios(editando["id"], orden) and None)

    tarjeta_contactos = tarjeta(
        contactos_tabla,
        ft.Row([contacto_nombre_field, contacto_sector_field, contacto_email_field, contacto_telefono_field,
                contacto_principal_switch, ft.OutlinedButton("Agregar contacto", icon=ft.Icons.ADD,
                                                            on_click=lambda e: con_aviso(agregar_contacto))],
               wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        titulo="Contactos", subtitulo="Se guardan al instante, sin apretar Guardar.",
    )
    tarjeta_listas = tarjeta(
        listas_tabla,
        ft.Row([listas_dropdown, ft.OutlinedButton("Agregar lista", icon=ft.Icons.ADD, on_click=lambda e: con_aviso(agregar_lista))],
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
        titulo="Listas de precios",
        subtitulo="La caja propone la de prioridad 1 al elegir este cliente (se puede cambiar en la venta). Se guardan al instante.",
    )
    aviso_hijos = ft.Text("Los contactos y las listas de precios se agregan despues de crear el cliente, con el lapiz.",
                          size=12.5, color=COLOR_TEXT_SOFT)

    seccion_formulario = ft.Column([
        tarjeta(
            ft.Row([razon_social_field, nombre_fantasia_field]),
            ft.Row([dni_field, cuit_field, contacto_principal_field]),
            ft.Row([telefono_field, email_field]),
            ft.Row([direccion_field, ciudad_field, provincia_field, codigo_postal_field]),
            ft.Row([condicion_iva_dropdown, plazo_pago_field, porcentaje_descuento_field]),
            ft.Row([limite_credito_field, avisar_limite_switch, bloquear_limite_switch, tasa_mora_field],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([observacion_field]),
            aviso_hijos,
            botones_formulario(guardar_texto, guardar, volver_a_lista),
            titulo=form_titulo,
            subtitulo="Al guardar o cancelar volves a la lista, donde la dejaste.",
        ),
        tarjeta_contactos,
        tarjeta_listas,
    ], visible=False, spacing=ESPACIO_PANTALLA)

    refrescar()
    return ft.Column(
        [
            encabezado_pantalla("Clientes", "Los clientes del negocio: datos, condicion de IVA, cuenta corriente y listas de precios."),
            seccion_lista,
            seccion_formulario,
        ],
        expand=True, scroll=ft.ScrollMode.AUTO, spacing=ESPACIO_PANTALLA,
    )
