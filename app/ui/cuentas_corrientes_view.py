from datetime import date, datetime

import flet as ft

from app.services import (
    cc_service,
    cheques_service,
    clientes_service,
    medios_pago_service,
    negocio_service,
    proveedores_service,
)
from app.services.exceptions import (
    AnulacionInvalidaError,
    CargoNoEncontradoError,
    ChequeEstadoInvalidoError,
    ChequeNoEncontradoError,
    ClienteNoEncontradoError,
    MedioPagoNoEncontradoError,
    MontoPagoInvalidoError,
    ProveedorNoEncontradoError,
)
from app.shared.money import formatear_precio
from app.ui.campos import FILTRO_CUIT, FILTRO_DECIMALES, aplicar_mascara_moneda, parsear_decimal_ar_opcional
from app.ui.listados import coincide_texto, con_scroll_horizontal
from app.ui.theme import COLOR_DANGER, COLOR_SUCCESS, COLOR_TEXT_SOFT, COLOR_WARNING
from app.ui.componentes import ESPACIO_PANTALLA, campo_buscar, encabezado_pantalla, tarjeta

EXCEPCIONES_NEGOCIO = (
    AnulacionInvalidaError, CargoNoEncontradoError, ChequeEstadoInvalidoError, ChequeNoEncontradoError,
    ClienteNoEncontradoError, MedioPagoNoEncontradoError, MontoPagoInvalidoError,
    ProveedorNoEncontradoError, ValueError,
)

ORIGEN_LABEL = {
    "manual": "Manual", "recepcion": "Compra a credito", "venta": "Venta a credito",
    "cheque_rechazado": "Cheque rechazado",
}

CHEQUE_DE_CARTERA = "cartera"
CHEQUE_PROPIO = "propio"


def CuentasCorrientesView(page: ft.Page) -> ft.Control:
    def mostrar_mensaje(texto: str) -> None:
        page.show_dialog(ft.SnackBar(ft.Text(texto)))

    def fecha_hoy() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def fecha_corta(fecha_iso: str) -> str:
        return date.fromisoformat(fecha_iso[:10]).strftime("%d/%m/%y")

    def nombre_entidad(tipo: str, entidad: dict) -> str:
        return entidad["razon_social"] if tipo == "cliente" else entidad["nombre"]

    def listar_entidades(tipo: str) -> list[dict]:
        return clientes_service.listar_clientes() if tipo == "cliente" else proveedores_service.listar_proveedores()

    def texto_saldo(saldo) -> str:
        if saldo < 0:
            return f"Saldo a favor: {formatear_precio(-saldo)}"
        return f"Saldo actual: {formatear_precio(saldo)}"

    # ================= SECCION LISTA =================
    tipo_dropdown = ft.Dropdown(
        label="Cuenta", width=180, value="cliente",
        options=[ft.dropdown.Option(key="cliente", text="Clientes"), ft.dropdown.Option(key="proveedor", text="Proveedores")],
    )
    buscador_field = campo_buscar("Cliente o proveedor")
    tabla_lista = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(t)) for t in ["Nombre", "Saldo", ""]],
        rows=[],
    )

    def refrescar_lista(e: ft.ControlEvent | None = None) -> None:
        tipo = tipo_dropdown.value
        entidades = [
            x for x in listar_entidades(tipo) if coincide_texto(nombre_entidad(tipo, x), buscador_field.value)
        ]
        filas = []
        for x in entidades:
            saldo = cc_service.calcular_saldo_total(tipo, x["id"])
            filas.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(nombre_entidad(tipo, x))),
                ft.DataCell(ft.Text(
                    formatear_precio(saldo) if saldo >= 0 else f"{formatear_precio(-saldo)} a favor",
                    color=COLOR_DANGER if saldo > 0 else (COLOR_SUCCESS if saldo < 0 else None),
                    weight=ft.FontWeight.BOLD if saldo > 0 else None,
                )),
                ft.DataCell(ft.IconButton(
                    ft.Icons.VISIBILITY, tooltip="Ver cuenta", data=x["id"],
                    on_click=lambda e, t=tipo: ir_a_detalle(t, e.control.data),
                )),
            ]))
        tabla_lista.rows = filas
        page.update()

    tipo_dropdown.on_select = refrescar_lista
    buscador_field.on_change = refrescar_lista

    seccion_lista = ft.Column([
        ft.Row([tipo_dropdown, buscador_field], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        tarjeta(con_scroll_horizontal(tabla_lista)),
    ], spacing=ESPACIO_PANTALLA)

    # ================= SECCION DETALLE =================
    detalle_tipo: str | None = None
    detalle_id: int | None = None
    detalle_nombre: str = ""

    detalle_titulo = ft.Text("", size=15, weight=ft.FontWeight.BOLD)
    detalle_saldo_texto = ft.Text("", size=16)
    volver_button = ft.ElevatedButton("Volver al listado", on_click=lambda e: ir_a_lista(None))
    # Apagado: la cuenta se ve "limpia" (una correccion parece una edicion). Prendido: todo el
    # rastro, incluidos los pagos reemplazados por una correccion y los anulados a mano.
    ver_anulados_switch = ft.Switch(label="Ver anulados", value=False)

    tabla_cargos = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(t)) for t in
                 ["Fecha", "Origen", "Monto", "Saldo pendiente", "Interes por mora", "Observacion", ""]],
        rows=[],
    )
    cargo_monto_field = ft.TextField(label="Monto", width=160, input_filter=FILTRO_DECIMALES)
    aplicar_mascara_moneda(cargo_monto_field)
    cargo_fecha_field = ft.TextField(label="Fecha (AAAA-MM-DD)", width=160, value=fecha_hoy())
    cargo_observacion_field = ft.TextField(label="Observacion (opcional)", expand=True)
    agregar_cargo_button = ft.ElevatedButton("+ Agregar cargo")

    tabla_pagos = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(t)) for t in ["Fecha", "Medio", "Monto", "Observacion", ""]],
        rows=[],
    )

    # ---------- Panel de anulacion (inline, sin AlertDialog) ----------
    # anulando = {'tipo': 'pago'|'cargo', 'registro': dict}
    anulando: dict | None = None
    anulacion_titulo = ft.Text("", weight=ft.FontWeight.BOLD, color=COLOR_DANGER)
    anulacion_motivo_field = ft.TextField(label="Motivo de la anulacion (obligatorio)", expand=True)
    anulacion_confirmar_button = ft.ElevatedButton("Confirmar anulacion")
    anulacion_cancelar_button = ft.TextButton("Cancelar")
    panel_anulacion = ft.Container(
        ft.Column([
            anulacion_titulo,
            ft.Row([anulacion_motivo_field, anulacion_confirmar_button, anulacion_cancelar_button]),
        ]),
        padding=12, border=ft.Border.all(1, COLOR_DANGER), border_radius=8, visible=False,
    )

    # ---------- Panel de correccion de un pago (para el usuario es "editar") ----------
    corrigiendo_pago: dict | None = None
    correccion_titulo = ft.Text("", weight=ft.FontWeight.BOLD)
    correccion_medio_dropdown = ft.Dropdown(label="Medio de pago", width=200, options=[])
    correccion_monto_field = ft.TextField(label="Monto", width=160, input_filter=FILTRO_DECIMALES)
    aplicar_mascara_moneda(correccion_monto_field)
    correccion_fecha_field = ft.TextField(label="Fecha (AAAA-MM-DD)", width=160)
    correccion_observacion_field = ft.TextField(label="Observacion (opcional)", expand=True)
    correccion_guardar_button = ft.ElevatedButton("Guardar correccion")
    correccion_cancelar_button = ft.TextButton("Cancelar")
    panel_correccion = ft.Container(
        ft.Column([
            correccion_titulo,
            ft.Row([correccion_medio_dropdown, correccion_monto_field, correccion_fecha_field,
                    correccion_observacion_field]),
            ft.Row([correccion_guardar_button, correccion_cancelar_button]),
        ]),
        padding=12, border=ft.Border.all(1, COLOR_WARNING), border_radius=8, visible=False,
    )

    # ---------- Formulario de pago ----------
    medio_dropdown = ft.Dropdown(label="Medio de pago", width=200, options=[])
    pago_monto_field = ft.TextField(label="Monto del pago", width=160, input_filter=FILTRO_DECIMALES)
    aplicar_mascara_moneda(pago_monto_field)
    pago_fecha_field = ft.TextField(label="Fecha (AAAA-MM-DD)", width=160, value=fecha_hoy())
    pago_observacion_field = ft.TextField(label="Observacion (opcional)", expand=True)

    cheque_tipo_dropdown = ft.Dropdown(
        label="Cheque", width=200, value=CHEQUE_DE_CARTERA,
        options=[ft.dropdown.Option(key=CHEQUE_DE_CARTERA, text="De cartera"),
                 ft.dropdown.Option(key=CHEQUE_PROPIO, text="Propio")],
    )
    cheque_cartera_dropdown = ft.Dropdown(label="Cheque en cartera", width=520, options=[])
    # Cheque propio: elegir la cuenta completa banco/librador/CUIT (Datos del negocio).
    cuenta_bancaria_dropdown = ft.Dropdown(label="Cuenta bancaria", width=420, options=[])
    cuentas_bancarias: dict[str, dict] = {}
    cheque_banco_field = ft.TextField(label="Banco", width=200)
    cheque_numero_field = ft.TextField(label="Numero (opcional)", width=150)
    cheque_fecha_pago_field = ft.TextField(label="Fecha de pago (AAAA-MM-DD)", width=200)
    cheque_librador_field = ft.TextField(label="Librador", width=220)
    cheque_cuit_field = ft.TextField(label="CUIT del librador (opcional)", width=190, input_filter=FILTRO_CUIT)
    fila_datos_cheque = ft.Row([
        cheque_banco_field, cheque_numero_field, cheque_fecha_pago_field, cheque_librador_field, cheque_cuit_field,
    ], wrap=True)
    panel_cheque = ft.Column([
        ft.Row([cheque_tipo_dropdown, cheque_cartera_dropdown, cuenta_bancaria_dropdown]),
        fila_datos_cheque,
    ], visible=False)

    pago_puntual_switch = ft.Switch(label="Aplicar a cargos puntuales (si no, se aplica a cuenta: el mas viejo primero)")
    contenedor_cargos_puntuales = ft.Column([])
    registrar_pago_button = ft.ElevatedButton("Registrar pago")

    campos_aplicacion: dict[int, ft.TextField] = {}
    medios_por_id: dict[str, dict] = {}
    cheques_en_cartera: dict[str, dict] = {}

    def medio_elegido_es_cheque() -> bool:
        medio = medios_por_id.get(medio_dropdown.value or "")
        return medio is not None and medios_pago_service.es_medio_cheque(medio)

    def cheque_de_cartera_elegido() -> bool:
        return detalle_tipo == "proveedor" and medio_elegido_es_cheque() and cheque_tipo_dropdown.value == CHEQUE_DE_CARTERA

    def actualizar_panel_cheque() -> None:
        es_cheque = medio_elegido_es_cheque()
        panel_cheque.visible = es_cheque
        cheque_tipo_dropdown.visible = detalle_tipo == "proveedor"
        de_cartera = cheque_de_cartera_elegido()
        cheque_cartera_dropdown.visible = de_cartera
        fila_datos_cheque.visible = es_cheque and not de_cartera
        es_propio = detalle_tipo == "proveedor" and es_cheque and not de_cartera
        cuenta_bancaria_dropdown.visible = es_propio and bool(cuentas_bancarias)
        if es_propio and not cuenta_bancaria_dropdown.value and not cheque_banco_field.value:
            principal = next((k for k, c in cuentas_bancarias.items() if c["es_principal"]), None)
            if principal:
                cuenta_bancaria_dropdown.value = principal
                completar_desde_cuenta()
        # El monto de un cheque de cartera es el del cheque: no se parte.
        pago_monto_field.read_only = de_cartera
        if de_cartera:
            cheque = cheques_en_cartera.get(cheque_cartera_dropdown.value or "")
            pago_monto_field.value = formatear_precio(cheque["monto"]) if cheque else ""

    def cambiar_medio(e: ft.ControlEvent | None = None) -> None:
        actualizar_panel_cheque()
        page.update()

    medio_dropdown.on_select = cambiar_medio
    cheque_tipo_dropdown.on_select = cambiar_medio
    cheque_cartera_dropdown.on_select = cambiar_medio

    def completar_desde_cuenta() -> None:
        cuenta = cuentas_bancarias.get(cuenta_bancaria_dropdown.value or "")
        if cuenta is None:
            return
        cheque_banco_field.value = cuenta["banco"]
        cheque_librador_field.value = cuenta["titular"]
        cheque_cuit_field.value = cuenta["cuit_titular"] or ""

    def elegir_cuenta_bancaria(e: ft.ControlEvent) -> None:
        completar_desde_cuenta()
        page.update()

    cuenta_bancaria_dropdown.on_select = elegir_cuenta_bancaria

    def toggle_puntual(e: ft.ControlEvent) -> None:
        contenedor_cargos_puntuales.visible = pago_puntual_switch.value
        page.update()

    pago_puntual_switch.on_change = toggle_puntual

    def refrescar_opciones_pago() -> None:
        medios = [m for m in medios_pago_service.listar_medios_pago(solo_activos=True) if not m["es_cuenta_corriente"]]
        medios_por_id.clear()
        medios_por_id.update({str(m["id"]): m for m in medios})
        medio_dropdown.options = [ft.dropdown.Option(key=str(m["id"]), text=m["nombre"]) for m in medios]
        if medio_dropdown.value not in medios_por_id:
            medio_dropdown.value = next(
                (str(m["id"]) for m in medios if m["nombre"].lower() == "efectivo"),
                str(medios[0]["id"]) if medios else None,
            )

        cheques_en_cartera.clear()
        if detalle_tipo == "proveedor":
            cheques_en_cartera.update({str(c["id"]): c for c in cheques_service.listar_cheques(estado="en_cartera")})
        cheque_cartera_dropdown.options = [
            ft.dropdown.Option(
                key=k,
                text=f"{c['banco']} n° {c['numero'] or 's/n'} - {c['librador']} - "
                     f"{formatear_precio(c['monto'])} - vence {fecha_corta(c['fecha_pago'])}",
            )
            for k, c in cheques_en_cartera.items()
        ]
        if cheque_cartera_dropdown.value not in cheques_en_cartera:
            cheque_cartera_dropdown.value = None

        cuentas_bancarias.clear()
        if detalle_tipo == "proveedor":
            cuentas_bancarias.update({str(c["id"]): c for c in negocio_service.listar_cuentas_bancarias()})
        cuenta_bancaria_dropdown.options = [
            ft.dropdown.Option(key=k, text=f"{c['banco']} - {c['titular']}" + (" (principal)" if c["es_principal"] else ""))
            for k, c in cuentas_bancarias.items()
        ]
        if cuenta_bancaria_dropdown.value not in cuentas_bancarias:
            cuenta_bancaria_dropdown.value = None

    def refrescar_cargos_puntuales() -> None:
        campos_aplicacion.clear()
        cargos_abiertos = cc_service.listar_cargos(detalle_tipo, detalle_id, solo_con_saldo=True)
        filas = []
        for c in cargos_abiertos:
            campo_monto = ft.TextField(label="Aplicar", width=120, input_filter=FILTRO_DECIMALES)
            campos_aplicacion[c["id"]] = campo_monto
            filas.append(ft.Row([
                ft.Container(ft.Text(c["fecha"][:10]), width=100),
                ft.Container(ft.Text(f"Saldo: {formatear_precio(c['saldo_pendiente'])}"), width=160),
                ft.Container(ft.Text(c["observacion"] or ORIGEN_LABEL.get(c["origen"], c["origen"])), width=220),
                campo_monto,
            ]))
        contenedor_cargos_puntuales.controls = filas
        contenedor_cargos_puntuales.visible = pago_puntual_switch.value

    def texto_medio(p: dict) -> str:
        if p["nota_credito_numero"]:
            return f"Nota de credito {p['nota_credito_numero']}"
        cheque = p["cheque"]
        if cheque is None:
            return p["medio_nombre"] or "-"
        tipo = " propio" if cheque["origen_tipo"] == "propio" else ""
        return f"Cheque{tipo} {cheque['banco']} n° {cheque['numero'] or 's/n'}"

    def celda(texto: str, anulado: bool, color: str | None = None) -> ft.DataCell:
        return ft.DataCell(ft.Text(
            texto,
            color=COLOR_TEXT_SOFT if anulado else color,
            style=ft.TextStyle(decoration=ft.TextDecoration.LINE_THROUGH) if anulado else None,
        ))

    def refrescar_detalle() -> None:
        nonlocal detalle_nombre
        saldo = cc_service.calcular_saldo_total(detalle_tipo, detalle_id)
        if detalle_tipo == "cliente":
            detalle_nombre = clientes_service.obtener_cliente(detalle_id)["razon_social"]
        else:
            detalle_nombre = proveedores_service.obtener_proveedor(detalle_id)["nombre"]
        detalle_titulo.value = f"{detalle_nombre} ({'Clientes' if detalle_tipo == 'cliente' else 'Proveedores'})"
        detalle_saldo_texto.value = texto_saldo(saldo)
        detalle_saldo_texto.color = COLOR_DANGER if saldo > 0 else (COLOR_SUCCESS if saldo < 0 else None)

        cargos = cc_service.listar_cargos(detalle_tipo, detalle_id)
        filas_cargos = []
        for c in cargos:
            anulado = bool(c["anulado_fecha"])
            if anulado and not ver_anulados_switch.value:
                continue
            interes_texto = "-"
            if detalle_tipo == "cliente" and not anulado:
                interes = cc_service.calcular_interes_mora(detalle_id, c)
                if interes > 0:
                    interes_texto = formatear_precio(interes)
            observacion = c["observacion"] or "-"
            if anulado:
                observacion = f"ANULADO {fecha_corta(c['anulado_fecha'])}: {c['anulado_motivo']}"
            accion = ft.DataCell(ft.Text(""))
            if not anulado and c["origen"] == "manual":
                accion = ft.DataCell(ft.IconButton(
                    ft.Icons.BLOCK, tooltip="Anular cargo", icon_color=COLOR_DANGER,
                    on_click=lambda e, cargo=c: mostrar_anulacion("cargo", cargo),
                ))
            filas_cargos.append(ft.DataRow(cells=[
                celda(c["fecha"][:10], anulado),
                celda(ORIGEN_LABEL.get(c["origen"], c["origen"]), anulado),
                celda(formatear_precio(c["monto"]), anulado),
                celda(formatear_precio(c["saldo_pendiente"]), anulado,
                      COLOR_DANGER if c["saldo_pendiente"] > 0 else None),
                celda(interes_texto, anulado, COLOR_WARNING if interes_texto != "-" else None),
                ft.DataCell(ft.Text(observacion, color=COLOR_DANGER if anulado else None)),
                accion,
            ]))
        tabla_cargos.rows = filas_cargos

        filas_pagos = []
        for p in cc_service.listar_pagos(detalle_tipo, detalle_id):
            anulado = bool(p["anulado_fecha"])
            if anulado and not ver_anulados_switch.value:
                continue
            observacion = p["observacion"] or "-"
            if anulado:
                observacion = f"ANULADO {fecha_corta(p['anulado_fecha'])}: {p['anulado_motivo']}"
                acciones = ft.Text("")
            elif p["nota_credito_id"] is not None:
                # Es parte de una nota de credito: se ve, pero no se toca desde Cuentas Corrientes.
                acciones = ft.Text("")
            else:
                botones = []
                if p["cheque"] is None:
                    botones.append(ft.IconButton(ft.Icons.EDIT, tooltip="Corregir pago",
                                                 on_click=lambda e, pago=p: mostrar_correccion(pago)))
                botones.append(ft.IconButton(ft.Icons.BLOCK, tooltip="Anular pago", icon_color=COLOR_DANGER,
                                             on_click=lambda e, pago=p: mostrar_anulacion("pago", pago)))
                acciones = ft.Row(botones, spacing=0)
            celda_monto = celda(formatear_precio(p["monto"]), anulado)
            antes = p["corregido_de"]
            if antes is not None and not anulado:
                celda_monto = ft.DataCell(ft.Row([
                    ft.Text(formatear_precio(p["monto"])),
                    ft.Container(
                        ft.Text("corregido", size=11, color=COLOR_WARNING, italic=True),
                        tooltip=(f"Antes: {formatear_precio(antes['monto'])} · {antes['medio_nombre'] or '-'} · "
                                 f"{fecha_corta(antes['fecha'])}\nCorregido el {fecha_corta(antes['fecha_correccion'])}"),
                    ),
                ], spacing=6))
            filas_pagos.append(ft.DataRow(cells=[
                celda(p["fecha"][:10], anulado),
                celda(texto_medio(p), anulado),
                celda_monto,
                ft.DataCell(ft.Text(observacion, color=COLOR_DANGER if anulado else None)),
                ft.DataCell(acciones),
            ]))
        tabla_pagos.rows = filas_pagos

        refrescar_opciones_pago()
        actualizar_panel_cheque()
        refrescar_cargos_puntuales()
        page.update()

    # ---------- Anulacion ----------
    def ocultar_paneles(e: ft.ControlEvent | None = None) -> None:
        nonlocal anulando, corrigiendo_pago
        anulando = None
        corrigiendo_pago = None
        panel_anulacion.visible = False
        panel_correccion.visible = False
        page.update()

    def mostrar_anulacion(tipo: str, registro: dict) -> None:
        nonlocal anulando
        ocultar_paneles()
        anulando = {"tipo": tipo, "registro": registro}
        anulacion_titulo.value = (
            f"Anular el {tipo} de {formatear_precio(registro['monto'])} del {fecha_corta(registro['fecha'])}"
        )
        anulacion_motivo_field.value = ""
        panel_anulacion.visible = True
        page.update()

    def confirmar_anulacion(e: ft.ControlEvent) -> None:
        if anulando is None:
            return
        tipo, registro = anulando["tipo"], anulando["registro"]
        try:
            if tipo == "pago":
                cc_service.anular_pago(registro["id"], anulacion_motivo_field.value or "")
            else:
                cc_service.anular_cargo(registro["id"], anulacion_motivo_field.value or "")
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))
            return
        ocultar_paneles()
        refrescar_detalle()
        mostrar_mensaje(f"{'Pago' if tipo == 'pago' else 'Cargo'} anulado")

    anulacion_confirmar_button.on_click = confirmar_anulacion
    anulacion_cancelar_button.on_click = ocultar_paneles

    def mostrar_correccion(pago: dict) -> None:
        nonlocal corrigiendo_pago
        ocultar_paneles()
        corrigiendo_pago = pago
        correccion_titulo.value = (
            f"Corregir el pago de {formatear_precio(pago['monto'])} del {fecha_corta(pago['fecha'])}"
        )
        correccion_medio_dropdown.options = [
            ft.dropdown.Option(key=k, text=m["nombre"])
            for k, m in medios_por_id.items() if not medios_pago_service.es_medio_cheque(m)
        ]
        correccion_medio_dropdown.value = str(pago["medio_pago_id"]) if pago["medio_pago_id"] else None
        correccion_monto_field.value = formatear_precio(pago["monto"])
        correccion_fecha_field.value = pago["fecha"][:10]
        correccion_observacion_field.value = pago["observacion"] or ""
        panel_correccion.visible = True
        page.update()

    def guardar_correccion(e: ft.ControlEvent) -> None:
        if corrigiendo_pago is None:
            return
        try:
            if not correccion_medio_dropdown.value:
                raise ValueError("Elegi un medio de pago")
            monto = parsear_decimal_ar_opcional(correccion_monto_field.value, "El monto")
            if monto is None:
                raise ValueError("El monto es obligatorio")
            cc_service.corregir_pago(
                corrigiendo_pago["id"], monto, (correccion_fecha_field.value or "").strip(),
                int(correccion_medio_dropdown.value),
                (correccion_observacion_field.value or "").strip() or None,
            )
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))
            return
        ocultar_paneles()
        refrescar_detalle()
        mostrar_mensaje("Pago corregido")

    correccion_guardar_button.on_click = guardar_correccion
    ver_anulados_switch.on_change = lambda e: refrescar_detalle()
    correccion_cancelar_button.on_click = ocultar_paneles

    # ---------- Alta de cargo / pago ----------
    def agregar_cargo(e: ft.ControlEvent) -> None:
        try:
            monto = parsear_decimal_ar_opcional(cargo_monto_field.value, "El monto")
            if monto is None:
                raise ValueError("El monto del cargo es obligatorio")
            fecha = (cargo_fecha_field.value or "").strip()
            if not fecha:
                raise ValueError("La fecha es obligatoria")
            cc_service.registrar_cargo_manual(
                detalle_tipo, detalle_id, monto, fecha, (cargo_observacion_field.value or "").strip() or None,
            )
            cargo_monto_field.value = ""
            cargo_observacion_field.value = ""
            mostrar_mensaje("Cargo registrado")
            refrescar_detalle()
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))

    agregar_cargo_button.on_click = agregar_cargo

    def limpiar_formulario_pago() -> None:
        pago_monto_field.value = ""
        pago_observacion_field.value = ""
        pago_puntual_switch.value = False
        cheque_cartera_dropdown.value = None
        cuenta_bancaria_dropdown.value = None
        for campo in (cheque_banco_field, cheque_numero_field, cheque_fecha_pago_field,
                      cheque_librador_field, cheque_cuit_field):
            campo.value = ""
        # Un cliente casi siempre paga con cheque propio suyo: se sugiere como librador.
        if detalle_tipo == "cliente":
            cheque_librador_field.value = detalle_nombre

    def registrar_pago(e: ft.ControlEvent) -> None:
        try:
            if not medio_dropdown.value:
                raise ValueError("Elegi un medio de pago")
            fecha = (pago_fecha_field.value or "").strip()
            if not fecha:
                raise ValueError("La fecha es obligatoria")
            observacion = (pago_observacion_field.value or "").strip() or None

            aplicaciones = None
            if pago_puntual_switch.value:
                aplicaciones = []
                for cargo_id, campo in campos_aplicacion.items():
                    valor = parsear_decimal_ar_opcional(campo.value, "El monto aplicado")
                    if valor:
                        aplicaciones.append({"cargo_id": cargo_id, "monto": valor})
                if not aplicaciones:
                    raise ValueError("Cargaste 'aplicar a cargos puntuales' pero no pusiste ningun monto")

            if cheque_de_cartera_elegido():
                if not cheque_cartera_dropdown.value:
                    raise ValueError("Elegi el cheque en cartera que le entregas")
                cheques_service.entregar_a_proveedor(
                    int(cheque_cartera_dropdown.value), detalle_id, aplicaciones, observacion, fecha,
                )
            else:
                monto = parsear_decimal_ar_opcional(pago_monto_field.value, "El monto del pago")
                if monto is None:
                    raise ValueError("El monto del pago es obligatorio")
                if medio_elegido_es_cheque():
                    datos_cheque = {
                        "banco": cheque_banco_field.value or "",
                        "librador": cheque_librador_field.value or "",
                        "monto": monto,
                        "fecha_pago": (cheque_fecha_pago_field.value or "").strip(),
                        "numero": cheque_numero_field.value,
                        "cuit_librador": cheque_cuit_field.value,
                        "observacion": observacion,
                        "aplicaciones": aplicaciones,
                        "fecha": fecha,
                    }
                    if detalle_tipo == "proveedor":
                        cheques_service.crear_cheque_propio_y_entregar(proveedor_id=detalle_id, **datos_cheque)
                    else:
                        cheques_service.recibir_de_cliente_para_cc(cliente_id=detalle_id, **datos_cheque)
                else:
                    cc_service.registrar_pago(
                        detalle_tipo, detalle_id, monto, fecha, aplicaciones, observacion,
                        medio_pago_id=int(medio_dropdown.value),
                    )
            limpiar_formulario_pago()
            mostrar_mensaje("Pago registrado")
            refrescar_detalle()
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))

    registrar_pago_button.on_click = registrar_pago

    seccion_detalle = ft.Column(
        [
            tarjeta(detalle_saldo_texto, ft.Row([volver_button, ver_anulados_switch], spacing=24), titulo=detalle_titulo),
            tarjeta(
                con_scroll_horizontal(tabla_cargos),
                ft.Row([cargo_monto_field, cargo_fecha_field, cargo_observacion_field, agregar_cargo_button]),
                titulo="Cargos",
            ),
            tarjeta(
                con_scroll_horizontal(tabla_pagos),
                panel_anulacion,
                panel_correccion,
                ft.Row([medio_dropdown, pago_monto_field, pago_fecha_field, pago_observacion_field]),
                panel_cheque,
                pago_puntual_switch,
                contenedor_cargos_puntuales,
                registrar_pago_button,
                titulo="Pagos / cobros",
            ),
        ],
        visible=False,
        scroll=ft.ScrollMode.AUTO,
        spacing=ESPACIO_PANTALLA,
    )

    # ================= NAVEGACION =================
    def ir_a_lista(e: ft.ControlEvent | None) -> None:
        seccion_lista.visible = True
        seccion_detalle.visible = False
        refrescar_lista()
        page.update()

    def ir_a_detalle(tipo: str, entidad_id: int) -> None:
        nonlocal detalle_tipo, detalle_id
        detalle_tipo = tipo
        detalle_id = entidad_id
        seccion_lista.visible = False
        seccion_detalle.visible = True
        panel_anulacion.visible = False
        panel_correccion.visible = False
        cheque_tipo_dropdown.value = CHEQUE_DE_CARTERA
        refrescar_detalle()
        limpiar_formulario_pago()
        actualizar_panel_cheque()
        page.update()

    refrescar_lista()

    return ft.Column(
        [encabezado_pantalla("Cuentas Corrientes", "Lo que deben los clientes y lo que el negocio les debe a los proveedores."),
         seccion_lista, seccion_detalle],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=ESPACIO_PANTALLA,
    )
