from datetime import datetime

import flet as ft

from app.services import cheques_service, clientes_service, proveedores_service
from app.services.exceptions import (
    CargoNoEncontradoError,
    ChequeEstadoInvalidoError,
    ChequeNoEncontradoError,
    ClienteNoEncontradoError,
    MontoPagoInvalidoError,
    ProveedorNoEncontradoError,
)
from app.shared.money import formatear_precio
from app.ui.campos import FILTRO_DECIMALES, aplicar_mascara_moneda, parsear_decimal_ar_opcional
from app.ui.listados import Paginador, coincide_texto, coincide_exacto, con_scroll_horizontal, filtrar
from app.ui.theme import COLOR_DANGER, COLOR_SUCCESS, COLOR_TEXT_SOFT, COLOR_WARNING

EXCEPCIONES_NEGOCIO = (
    CargoNoEncontradoError, ChequeEstadoInvalidoError, ChequeNoEncontradoError,
    ClienteNoEncontradoError, MontoPagoInvalidoError, ProveedorNoEncontradoError, ValueError,
)

ESTADO_LABEL = {
    "en_cartera": "En cartera",
    "entregado_proveedor": "Entregado a proveedor",
    "baja": "Baja",
    "rechazado": "Rechazado",
}
ESTADO_COLOR = {
    "en_cartera": COLOR_SUCCESS,
    "entregado_proveedor": COLOR_TEXT_SOFT,
    "baja": COLOR_TEXT_SOFT,
    "rechazado": COLOR_DANGER,
}
ORIGEN_LABEL = {"recibido_cliente": "Recibido de cliente", "propio": "Propio"}


def ChequesView(page: ft.Page) -> ft.Control:
    def mostrar_mensaje(texto: str) -> None:
        page.show_dialog(ft.SnackBar(ft.Text(texto)))

    def fecha_hoy() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def nombre_cliente(cliente_id: int | None) -> str:
        if cliente_id is None:
            return "-"
        c = clientes_service.obtener_cliente(cliente_id)
        return c["razon_social"] if c else f"Cliente {cliente_id}"

    def nombre_proveedor(proveedor_id: int | None) -> str:
        if proveedor_id is None:
            return "-"
        p = proveedores_service.obtener_proveedor(proveedor_id)
        return p["nombre"] if p else f"Proveedor {proveedor_id}"

    # ================= FILTROS + CONTADORES =================
    estado_dropdown = ft.Dropdown(
        label="Estado", width=200, value="",
        options=[ft.dropdown.Option(key="", text="Todos")] + [
            ft.dropdown.Option(key=k, text=v) for k, v in ESTADO_LABEL.items()
        ],
    )
    origen_dropdown = ft.Dropdown(
        label="Origen", width=200, value="",
        options=[ft.dropdown.Option(key="", text="Todos")] + [
            ft.dropdown.Option(key=k, text=v) for k, v in ORIGEN_LABEL.items()
        ],
    )
    buscador_field = ft.TextField(label="Buscar por banco, librador o numero", expand=True)

    contadores_texto = ft.Text("", size=13, color=COLOR_TEXT_SOFT)

    nuevo_recibido_button = ft.ElevatedButton("+ Cheque recibido")
    nuevo_propio_button = ft.ElevatedButton("+ Cheque propio")

    contenedor_filas = ft.Column([], spacing=8)
    paginador = Paginador(on_cambio=lambda: refrescar_lista())

    # ================= FORMULARIO: cheque recibido de un cliente (entrada suelta, saldar CC) =================
    cliente_dropdown = ft.Dropdown(label="Cliente", width=280, options=[])
    recibido_banco_field = ft.TextField(label="Banco", width=220)
    recibido_librador_field = ft.TextField(label="Librador", width=220)
    recibido_cuit_field = ft.TextField(label="CUIT del librador (opcional)", width=180)
    recibido_numero_field = ft.TextField(label="Numero (opcional)", width=160)
    recibido_monto_field = ft.TextField(label="Monto", width=160, input_filter=FILTRO_DECIMALES)
    aplicar_mascara_moneda(recibido_monto_field)
    recibido_fecha_field = ft.TextField(label="Fecha de pago (AAAA-MM-DD)", width=200, value=fecha_hoy())
    recibido_observacion_field = ft.TextField(label="Observacion (opcional)", expand=True)
    guardar_recibido_button = ft.ElevatedButton("Guardar")
    cancelar_recibido_button = ft.TextButton("Cancelar")

    def limpiar_form_recibido() -> None:
        cliente_dropdown.value = None
        recibido_banco_field.value = ""
        recibido_librador_field.value = ""
        recibido_cuit_field.value = ""
        recibido_numero_field.value = ""
        recibido_monto_field.value = ""
        recibido_fecha_field.value = fecha_hoy()
        recibido_observacion_field.value = ""

    def guardar_recibido_click(e: ft.ControlEvent) -> None:
        try:
            if not cliente_dropdown.value:
                raise ValueError("Elegi un cliente")
            monto = parsear_decimal_ar_opcional(recibido_monto_field.value, "El monto")
            if monto is None:
                raise ValueError("El monto es obligatorio")
            fecha_pago = (recibido_fecha_field.value or "").strip()
            cheques_service.recibir_de_cliente_para_cc(
                cliente_id=int(cliente_dropdown.value),
                banco=recibido_banco_field.value or "",
                librador=recibido_librador_field.value or "",
                monto=monto,
                fecha_pago=fecha_pago,
                numero=recibido_numero_field.value,
                cuit_librador=recibido_cuit_field.value,
                observacion=recibido_observacion_field.value,
            )
            mostrar_mensaje("Cheque recibido y aplicado a la cuenta corriente del cliente")
            limpiar_form_recibido()
            mostrar_lista()
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))

    guardar_recibido_button.on_click = guardar_recibido_click
    cancelar_recibido_button.on_click = lambda e: mostrar_lista()

    seccion_form_recibido = ft.Column(
        [
            ft.Text("Nuevo cheque recibido (para saldar una cuenta corriente vieja)", size=16, weight=ft.FontWeight.BOLD),
            ft.Text(
                "Se aplica automaticamente a los cargos abiertos mas viejos de ese cliente (igual "
                "que cualquier pago de cuenta corriente). Para un cheque que paga una venta nueva, "
                "se carga directamente desde el cobro en Ventas.",
                size=11.5, color=COLOR_TEXT_SOFT,
            ),
            ft.Row([cliente_dropdown]),
            ft.Row([recibido_banco_field, recibido_librador_field, recibido_cuit_field, recibido_numero_field]),
            ft.Row([recibido_monto_field, recibido_fecha_field]),
            ft.Row([recibido_observacion_field]),
            ft.Row([guardar_recibido_button, cancelar_recibido_button]),
        ],
        visible=False, scroll=ft.ScrollMode.AUTO,
    )

    # ================= FORMULARIO: cheque propio (nace entregado a un proveedor) =================
    propio_proveedor_dropdown = ft.Dropdown(label="Proveedor", width=280, options=[])
    propio_banco_field = ft.TextField(label="Banco", width=220)
    propio_librador_field = ft.TextField(label="Librador", width=220, value="Negocio propio")
    propio_cuit_field = ft.TextField(label="CUIT del librador (opcional)", width=180)
    propio_numero_field = ft.TextField(label="Numero (opcional)", width=160)
    propio_monto_field = ft.TextField(label="Monto", width=160, input_filter=FILTRO_DECIMALES)
    aplicar_mascara_moneda(propio_monto_field)
    propio_fecha_field = ft.TextField(label="Fecha de pago (AAAA-MM-DD)", width=200, value=fecha_hoy())
    propio_observacion_field = ft.TextField(label="Observacion (opcional)", expand=True)
    guardar_propio_button = ft.ElevatedButton("Guardar")
    cancelar_propio_button = ft.TextButton("Cancelar")

    def limpiar_form_propio() -> None:
        propio_proveedor_dropdown.value = None
        propio_banco_field.value = ""
        propio_librador_field.value = "Negocio propio"
        propio_cuit_field.value = ""
        propio_numero_field.value = ""
        propio_monto_field.value = ""
        propio_fecha_field.value = fecha_hoy()
        propio_observacion_field.value = ""

    def guardar_propio_click(e: ft.ControlEvent) -> None:
        try:
            if not propio_proveedor_dropdown.value:
                raise ValueError("Elegi un proveedor")
            monto = parsear_decimal_ar_opcional(propio_monto_field.value, "El monto")
            if monto is None:
                raise ValueError("El monto es obligatorio")
            fecha_pago = (propio_fecha_field.value or "").strip()
            cheques_service.crear_cheque_propio_y_entregar(
                proveedor_id=int(propio_proveedor_dropdown.value),
                banco=propio_banco_field.value or "",
                librador=propio_librador_field.value or "",
                monto=monto,
                fecha_pago=fecha_pago,
                numero=propio_numero_field.value,
                cuit_librador=propio_cuit_field.value,
                observacion=propio_observacion_field.value,
            )
            mostrar_mensaje("Cheque propio emitido y aplicado a la cuenta corriente del proveedor")
            limpiar_form_propio()
            mostrar_lista()
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))

    guardar_propio_button.on_click = guardar_propio_click
    cancelar_propio_button.on_click = lambda e: mostrar_lista()

    seccion_form_propio = ft.Column(
        [
            ft.Text("Nuevo cheque propio (para pagarle a un proveedor)", size=16, weight=ft.FontWeight.BOLD),
            ft.Text(
                "Nace directamente entregado al proveedor -- nunca pasa por 'en cartera', porque "
                "nunca lo recibimos nosotros. Se aplica a los cargos abiertos mas viejos de ese "
                "proveedor (si es para pagar una compra nueva, primero marcala a credito en Compras "
                "para que se genere el cargo).",
                size=11.5, color=COLOR_TEXT_SOFT,
            ),
            ft.Row([propio_proveedor_dropdown]),
            ft.Row([propio_banco_field, propio_librador_field, propio_cuit_field, propio_numero_field]),
            ft.Row([propio_monto_field, propio_fecha_field]),
            ft.Row([propio_observacion_field]),
            ft.Row([guardar_propio_button, cancelar_propio_button]),
        ],
        visible=False, scroll=ft.ScrollMode.AUTO,
    )

    # ================= FILAS DE LA LISTA (con acciones inline segun estado) =================
    def construir_fila(c: dict, proveedores_activos: list[dict]) -> ft.Control:
        partes_entidad = []
        if c["cliente_id"]:
            partes_entidad.append(f"Cliente: {nombre_cliente(c['cliente_id'])}")
        if c["proveedor_id"]:
            partes_entidad.append(f"Proveedor: {nombre_proveedor(c['proveedor_id'])}")
        entidad_texto = "   |   ".join(partes_entidad) if partes_entidad else "-"
        titulo = ft.Row(
            [
                ft.Container(ft.Text(c["banco"], weight=ft.FontWeight.BOLD), width=160),
                ft.Container(ft.Text(c["librador"]), width=200),
                ft.Container(ft.Text(c["numero"] or "-"), width=120),
                ft.Container(ft.Text(formatear_precio(c["monto"]), weight=ft.FontWeight.BOLD), width=120),
                ft.Container(ft.Text(c["fecha_pago"]), width=110),
                ft.Container(
                    ft.Text(ESTADO_LABEL.get(c["estado"], c["estado"]), color=ESTADO_COLOR.get(c["estado"]),
                             weight=ft.FontWeight.BOLD),
                    width=170,
                ),
            ],
            wrap=True,
        )

        detalle_controles = [
            ft.Text(f"Origen: {ORIGEN_LABEL.get(c['origen_tipo'], c['origen_tipo'])}   |   {entidad_texto}"),
            ft.Text(f"CUIT librador: {c['cuit_librador'] or '-'}   |   Recibido el: {c['fecha_recepcion'][:10]}"),
        ]
        if c["observacion"]:
            detalle_controles.append(ft.Text(f"Observacion: {c['observacion']}"))

        if c["estado"] == "en_cartera":
            entregar_proveedor_dropdown = ft.Dropdown(
                label="Entregar a este proveedor", width=260,
                options=[ft.dropdown.Option(key=str(p["id"]), text=p["nombre"]) for p in proveedores_activos],
            )
            entregar_button = ft.ElevatedButton("Entregar a proveedor")

            def entregar_click(e: ft.ControlEvent, cheque_id=c["id"]) -> None:
                try:
                    if not entregar_proveedor_dropdown.value:
                        raise ValueError("Elegi a que proveedor se lo entregas")
                    cheques_service.entregar_a_proveedor(cheque_id, int(entregar_proveedor_dropdown.value))
                    mostrar_mensaje("Cheque entregado al proveedor")
                    refrescar_lista()
                except EXCEPCIONES_NEGOCIO as ex:
                    mostrar_mensaje(str(ex))

            entregar_button.on_click = entregar_click

            baja_obs_field = ft.TextField(label="Motivo de la baja", expand=True)
            baja_button = ft.ElevatedButton("Dar de baja")

            def baja_click(e: ft.ControlEvent, cheque_id=c["id"]) -> None:
                try:
                    cheques_service.dar_de_baja(cheque_id, baja_obs_field.value or "")
                    mostrar_mensaje("Cheque dado de baja")
                    refrescar_lista()
                except EXCEPCIONES_NEGOCIO as ex:
                    mostrar_mensaje(str(ex))

            baja_button.on_click = baja_click

            rechazo_obs_field = ft.TextField(label="Motivo del rechazo", expand=True)
            rechazar_button = ft.ElevatedButton("Marcar rechazado", bgcolor=COLOR_DANGER, color="#ffffff")

            def rechazar_click(e: ft.ControlEvent, cheque_id=c["id"]) -> None:
                try:
                    cheques_service.marcar_rechazado(cheque_id, rechazo_obs_field.value or "")
                    mostrar_mensaje("Cheque rechazado -- se genero un cargo nuevo en la cuenta corriente")
                    refrescar_lista()
                except EXCEPCIONES_NEGOCIO as ex:
                    mostrar_mensaje(str(ex))

            rechazar_button.on_click = rechazar_click

            detalle_controles += [
                ft.Divider(height=1),
                ft.Row([entregar_proveedor_dropdown, entregar_button]),
                ft.Row([baja_obs_field, baja_button]),
                ft.Row([rechazo_obs_field, rechazar_button]),
            ]
        elif c["estado"] == "entregado_proveedor" and c["origen_tipo"] == "propio":
            rechazo_obs_field = ft.TextField(label="Motivo del rechazo", expand=True)
            rechazar_button = ft.ElevatedButton("Marcar rechazado", bgcolor=COLOR_DANGER, color="#ffffff")

            def rechazar_propio_click(e: ft.ControlEvent, cheque_id=c["id"]) -> None:
                try:
                    cheques_service.marcar_rechazado(cheque_id, rechazo_obs_field.value or "")
                    mostrar_mensaje("Cheque rechazado -- se genero un cargo nuevo en la cuenta corriente del proveedor")
                    refrescar_lista()
                except EXCEPCIONES_NEGOCIO as ex:
                    mostrar_mensaje(str(ex))

            rechazar_button.on_click = rechazar_propio_click
            detalle_controles += [ft.Divider(height=1), ft.Row([rechazo_obs_field, rechazar_button])]

        return ft.ExpansionTile(
            title=titulo,
            controls=[ft.Container(content=ft.Column(detalle_controles, spacing=8), padding=12)],
            tile_padding=ft.Padding.symmetric(horizontal=4, vertical=2),
            affinity=ft.TileAffinity.LEADING,
        )

    # ================= REFRESCO DE LA LISTA =================
    def refrescar_lista(e: ft.ControlEvent | None = None) -> None:
        todos = cheques_service.listar_cheques()
        filtrados = filtrar(todos, [
            lambda c: coincide_exacto(c["estado"], estado_dropdown.value),
            lambda c: coincide_exacto(c["origen_tipo"], origen_dropdown.value),
            lambda c: (
                coincide_texto(c["banco"], buscador_field.value)
                or coincide_texto(c["librador"], buscador_field.value)
                or coincide_texto(c["numero"], buscador_field.value)
            ),
        ])
        en_cartera = [c for c in todos if c["estado"] == "en_cartera"]
        total_en_cartera = sum((c["monto"] for c in en_cartera), 0)
        contadores_texto.value = (
            f"En cartera: {len(en_cartera)} ({formatear_precio(total_en_cartera)})   |   "
            f"Entregados: {sum(1 for c in todos if c['estado'] == 'entregado_proveedor')}   |   "
            f"Baja: {sum(1 for c in todos if c['estado'] == 'baja')}   |   "
            f"Rechazados: {sum(1 for c in todos if c['estado'] == 'rechazado')}"
        )
        pagina = paginador.aplicar(filtrados)
        proveedores_activos = proveedores_service.listar_proveedores(solo_activos=True)
        contenedor_filas.controls = [construir_fila(c, proveedores_activos) for c in pagina]
        page.update()

    estado_dropdown.on_select = refrescar_lista
    origen_dropdown.on_select = refrescar_lista
    buscador_field.on_change = refrescar_lista

    def abrir_form_recibido(e: ft.ControlEvent) -> None:
        cliente_dropdown.options = [
            ft.dropdown.Option(key=str(c["id"]), text=c["razon_social"])
            for c in clientes_service.listar_clientes(solo_activos=True)
        ]
        limpiar_form_recibido()
        seccion_lista.visible = False
        seccion_form_recibido.visible = True
        seccion_form_propio.visible = False
        page.update()

    def abrir_form_propio(e: ft.ControlEvent) -> None:
        propio_proveedor_dropdown.options = [
            ft.dropdown.Option(key=str(p["id"]), text=p["nombre"])
            for p in proveedores_service.listar_proveedores(solo_activos=True)
        ]
        limpiar_form_propio()
        seccion_lista.visible = False
        seccion_form_recibido.visible = False
        seccion_form_propio.visible = True
        page.update()

    nuevo_recibido_button.on_click = abrir_form_recibido
    nuevo_propio_button.on_click = abrir_form_propio

    def mostrar_lista() -> None:
        seccion_lista.visible = True
        seccion_form_recibido.visible = False
        seccion_form_propio.visible = False
        refrescar_lista()
        page.update()

    encabezado_tabla = ft.Row(
        [
            ft.Container(ft.Text("Banco", weight=ft.FontWeight.BOLD), width=160),
            ft.Container(ft.Text("Librador", weight=ft.FontWeight.BOLD), width=200),
            ft.Container(ft.Text("Numero", weight=ft.FontWeight.BOLD), width=120),
            ft.Container(ft.Text("Monto", weight=ft.FontWeight.BOLD), width=120),
            ft.Container(ft.Text("Fecha de pago", weight=ft.FontWeight.BOLD), width=110),
            ft.Container(ft.Text("Estado", weight=ft.FontWeight.BOLD), width=170),
        ],
        wrap=True,
    )

    seccion_lista = ft.Column(
        [
            ft.Text("Cheques", size=20, weight=ft.FontWeight.BOLD),
            ft.Row([estado_dropdown, origen_dropdown, buscador_field]),
            contadores_texto,
            ft.Row([nuevo_recibido_button, nuevo_propio_button]),
            con_scroll_horizontal(encabezado_tabla),
            contenedor_filas,
            paginador.controles,
        ],
        spacing=10,
    )

    refrescar_lista()

    return ft.Column(
        [seccion_lista, seccion_form_recibido, seccion_form_propio],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
