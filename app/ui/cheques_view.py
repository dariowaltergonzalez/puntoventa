from datetime import date, datetime

import flet as ft

from app.services import cheques_service, clientes_service, proveedores_service
from app.shared.money import formatear_precio
from app.ui.campos import FILTRO_DECIMALES, aplicar_mascara_moneda, parsear_decimal_ar_opcional
from app.ui.componentes import (
    ESPACIO_PANTALLA,
    ERRORES_PARA_AVISAR,
    TONO_ESPERA,
    TONO_NO,
    TONO_OK,
    Columna,
    Lista,
    accion_abrir,
    accion_anular,
    accion_con_motivo,
    accion_ver,
    avisar,
    barra,
    boton_principal,
    botones_formulario,
    campo_buscar,
    dato,
    encabezado_pantalla,
    etiqueta_estado,
    tarjeta,
    ventana_info,
)
from app.ui.theme import COLOR_TEXT_SOFT

ESTADOS = {
    "en_cartera": ("En cartera", TONO_ESPERA),
    "entregado_proveedor": ("Entregado a proveedor", TONO_OK),
    "baja": ("Baja", TONO_OK),
    "rechazado": ("Rechazado", TONO_NO),
}
ORIGEN_LABEL = {"recibido_cliente": "Recibido de cliente", "propio": "Propio"}


def _fecha(iso: str | None) -> str:
    return date.fromisoformat(iso[:10]).strftime("%d/%m/%Y") if iso else "-"


def ChequesView(page: ft.Page) -> ft.Control:
    def fecha_hoy() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    # ================= Lista =================
    buscador_field = campo_buscar("Banco, librador o numero", al_cambiar=lambda: filtrar())
    estado_dropdown = ft.Dropdown(label="Estado", width=210, value="", on_select=lambda e: filtrar(), options=[
        ft.dropdown.Option(key="", text="Todos"), *[ft.dropdown.Option(key=k, text=v[0]) for k, v in ESTADOS.items()]])
    origen_dropdown = ft.Dropdown(label="Origen", width=190, value="", on_select=lambda e: filtrar(), options=[
        ft.dropdown.Option(key="", text="Todos"), *[ft.dropdown.Option(key=k, text=v) for k, v in ORIGEN_LABEL.items()]])
    contadores_texto = ft.Text("", size=12.5, color=COLOR_TEXT_SOFT)
    lista = Lista(
        [
            Columna("Banco", peso=2, orden="banco"), Columna("Librador", peso=2, orden="librador"),
            Columna("Numero", ancho=110), Columna("Cliente / proveedor", peso=3, orden="entidad"),
            Columna("Monto ($)", ancho=120, derecha=True, orden="monto"), Columna("Fecha de pago", ancho=120, orden="fecha_pago"),
            Columna("Estado", ancho=170), Columna("Acciones", ancho=170, derecha=True),
        ],
        al_cambiar_pagina=lambda: refrescar(), nombre="cheques", orden_inicial=("fecha_pago", False),
        sin_datos="Ningun cheque coincide con los filtros.",
    )

    def filtrar() -> None:
        lista.ir_al_principio()
        refrescar()

    def refrescar() -> None:
        clientes = {c["id"]: c["razon_social"] for c in clientes_service.listar_clientes()}
        proveedores = {p["id"]: p["nombre"] for p in proveedores_service.listar_proveedores()}
        todos = []
        for c in cheques_service.listar_cheques():
            partes = ([f"De {clientes.get(c['cliente_id'], '?')}"] if c["cliente_id"] else []) + \
                     ([f"A {proveedores.get(c['proveedor_id'], '?')}"] if c["proveedor_id"] else [])
            todos.append(dict(c, entidad=" · ".join(partes) or None))
        en_cartera = [c for c in todos if c["estado"] == "en_cartera"]
        contadores_texto.value = (
            f"En cartera: {len(en_cartera)} (${formatear_precio(sum((c['monto'] for c in en_cartera), 0))})   ·   "
            + "   ·   ".join(f"{v[0]}: {sum(1 for c in todos if c['estado'] == k)}" for k, v in ESTADOS.items() if k != "en_cartera")
        )
        texto = (buscador_field.value or "").strip().lower()
        filtrados = [
            c for c in todos
            if texto in f"{c['banco']} {c['librador']} {c['numero'] or ''}".lower()
            and (not estado_dropdown.value or c["estado"] == estado_dropdown.value)
            and (not origen_dropdown.value or c["origen_tipo"] == origen_dropdown.value)
        ]
        lista.mostrar(filtrados, celdas, valor_orden=lambda c, k: c.get(k))
        page.update()

    def celdas(c: dict) -> list:
        estado, propio = c["estado"], c["origen_tipo"] == "propio"
        en_cartera = estado == "en_cartera"
        if propio:
            rechazable = None if estado == "entregado_proveedor" else f"esta {ESTADOS[estado][0].lower()}"
        else:
            rechazable = None if en_cartera else "solo un cheque en cartera se puede marcar rechazado"
        quien = "del proveedor (el negocio le vuelve a deber)" if propio else "del cliente (vuelve a deber ese monto)"
        return [
            ft.Text(c["banco"], weight=ft.FontWeight.W_500), c["librador"], c["numero"], c["entidad"],
            formatear_precio(c["monto"]), _fecha(c["fecha_pago"]), etiqueta_estado(*ESTADOS[estado]),
            ft.Row([
                accion_ver(ft.Icons.VISIBILITY, "Ver datos del cheque", lambda c=c: ver_cheque(c)),
                accion_abrir(ft.Icons.SEND, "Entregar a un proveedor", lambda c=c: ir_a_entregar(c),
                             por_que_no=None if en_cartera else f"esta {ESTADOS[estado][0].lower()}"),
                accion_con_motivo(
                    ft.Icons.ARCHIVE, "Dar de baja", "Dar de baja el cheque",
                    f"Sale de la cartera ({c['banco']}, ${formatear_precio(c['monto'])}): depositado, cobrado u otra "
                    "salida que no sea entregarlo a un proveedor.",
                    lambda motivo, c=c: dar_de_baja(c, motivo),
                    por_que_no=None if en_cartera else f"esta {ESTADOS[estado][0].lower()}",
                ),
                accion_anular(
                    "Marcar rechazado", "Marcar el cheque como rechazado",
                    f"Reboto o ya no sirve para cobrar. Se genera un cargo nuevo de ${formatear_precio(c['monto'])} "
                    f"en la cuenta corriente {quien}.",
                    lambda motivo, c=c: rechazar(c, motivo), por_que_no=rechazable,
                ),
            ], spacing=0, tight=True),
        ]

    def ver_cheque(c: dict) -> None:
        ventana_info(
            page, f"Cheque {c['banco']} · ${formatear_precio(c['monto'])}",
            dato("Estado", ESTADOS[c["estado"]][0]),
            dato("Origen", ORIGEN_LABEL.get(c["origen_tipo"], c["origen_tipo"])),
            dato("Cliente / proveedor", c["entidad"] or "-"),
            dato("Librador", c["librador"] + (f" (CUIT {c['cuit_librador']})" if c["cuit_librador"] else "")),
            dato("Numero", c["numero"] or "-"),
            dato("Fecha de pago", _fecha(c["fecha_pago"])),
            dato("Recibido el", _fecha(c["fecha_recepcion"])),
            dato("Observacion", c["observacion"] or "-"),
        )

    def dar_de_baja(c: dict, motivo: str) -> str:
        cheques_service.dar_de_baja(c["id"], motivo)
        refrescar()
        return f"Cheque {c['banco']} (${formatear_precio(c['monto'])}) dado de baja"

    def rechazar(c: dict, motivo: str) -> str:
        cheques_service.marcar_rechazado(c["id"], motivo)
        refrescar()
        return f"Cheque rechazado: se genero un cargo de ${formatear_precio(c['monto'])} en la cuenta corriente"

    seccion_lista = ft.Column([
        barra(
            [buscador_field, estado_dropdown, origen_dropdown],
            [boton_principal("Cheque recibido", ft.Icons.ADD, lambda: abrir_form(seccion_form_recibido)),
             boton_principal("Cheque propio", ft.Icons.ADD, lambda: abrir_form(seccion_form_propio))],
        ),
        contadores_texto,
        lista.control,
    ], spacing=ESPACIO_PANTALLA)

    # ================= Formulario: cheque recibido de un cliente =================
    cliente_dropdown = ft.Dropdown(label="Cliente *", width=280, options=[])
    recibido_banco_field = ft.TextField(label="Banco *", width=220)
    recibido_librador_field = ft.TextField(label="Librador *", width=220)
    recibido_cuit_field = ft.TextField(label="CUIT del librador (opcional)", width=200)
    recibido_numero_field = ft.TextField(label="Numero (opcional)", width=160)
    recibido_monto_field = ft.TextField(label="Monto *", width=160, input_filter=FILTRO_DECIMALES)
    aplicar_mascara_moneda(recibido_monto_field)
    recibido_fecha_field = ft.TextField(label="Fecha de pago * (AAAA-MM-DD)", width=220)
    recibido_observacion_field = ft.TextField(label="Observacion (opcional)", expand=True)

    def guardar_recibido() -> None:
        try:
            if not cliente_dropdown.value:
                raise ValueError("Elegi un cliente")
            monto = parsear_decimal_ar_opcional(recibido_monto_field.value, "El monto")
            if monto is None:
                raise ValueError("El monto es obligatorio")
            cheques_service.recibir_de_cliente_para_cc(
                cliente_id=int(cliente_dropdown.value), banco=recibido_banco_field.value or "",
                librador=recibido_librador_field.value or "", monto=monto,
                fecha_pago=(recibido_fecha_field.value or "").strip(), numero=recibido_numero_field.value,
                cuit_librador=recibido_cuit_field.value, observacion=recibido_observacion_field.value,
            )
        except ERRORES_PARA_AVISAR as ex:
            avisar(page, str(ex), error=True)
            return
        mostrar_lista()
        avisar(page, "Cheque recibido y aplicado a la cuenta corriente del cliente")

    seccion_form_recibido = ft.Column([tarjeta(
        ft.Row([cliente_dropdown]),
        ft.Row([recibido_banco_field, recibido_librador_field, recibido_cuit_field, recibido_numero_field]),
        ft.Row([recibido_monto_field, recibido_fecha_field]),
        ft.Row([recibido_observacion_field]),
        botones_formulario(ft.Text("Guardar cheque"), guardar_recibido, lambda: mostrar_lista()),
        titulo="Nuevo cheque recibido (para saldar una cuenta corriente vieja)",
        subtitulo="Se aplica a los cargos abiertos mas viejos de ese cliente. Un cheque que paga una venta nueva "
                  "se carga directamente al cobrar en Ventas.",
    )], visible=False)

    # ================= Formulario: cheque propio (nace entregado a un proveedor) =================
    propio_proveedor_dropdown = ft.Dropdown(label="Proveedor *", width=280, options=[])
    propio_banco_field = ft.TextField(label="Banco *", width=220)
    propio_librador_field = ft.TextField(label="Librador *", width=220)
    propio_cuit_field = ft.TextField(label="CUIT del librador (opcional)", width=200)
    propio_numero_field = ft.TextField(label="Numero (opcional)", width=160)
    propio_monto_field = ft.TextField(label="Monto *", width=160, input_filter=FILTRO_DECIMALES)
    aplicar_mascara_moneda(propio_monto_field)
    propio_fecha_field = ft.TextField(label="Fecha de pago * (AAAA-MM-DD)", width=220)
    propio_observacion_field = ft.TextField(label="Observacion (opcional)", expand=True)

    def guardar_propio() -> None:
        try:
            if not propio_proveedor_dropdown.value:
                raise ValueError("Elegi un proveedor")
            monto = parsear_decimal_ar_opcional(propio_monto_field.value, "El monto")
            if monto is None:
                raise ValueError("El monto es obligatorio")
            cheques_service.crear_cheque_propio_y_entregar(
                proveedor_id=int(propio_proveedor_dropdown.value), banco=propio_banco_field.value or "",
                librador=propio_librador_field.value or "", monto=monto,
                fecha_pago=(propio_fecha_field.value or "").strip(), numero=propio_numero_field.value,
                cuit_librador=propio_cuit_field.value, observacion=propio_observacion_field.value,
            )
        except ERRORES_PARA_AVISAR as ex:
            avisar(page, str(ex), error=True)
            return
        mostrar_lista()
        avisar(page, "Cheque propio emitido y aplicado a la cuenta corriente del proveedor")

    seccion_form_propio = ft.Column([tarjeta(
        ft.Row([propio_proveedor_dropdown]),
        ft.Row([propio_banco_field, propio_librador_field, propio_cuit_field, propio_numero_field]),
        ft.Row([propio_monto_field, propio_fecha_field]),
        ft.Row([propio_observacion_field]),
        botones_formulario(ft.Text("Guardar cheque"), guardar_propio, lambda: mostrar_lista()),
        titulo="Nuevo cheque propio (para pagarle a un proveedor)",
        subtitulo="Nace entregado al proveedor (nunca pasa por la cartera) y se aplica a sus cargos abiertos mas viejos. "
                  "Para pagar una compra nueva, primero marcala a credito en Compras.",
    )], visible=False)

    # ================= Entregar un cheque de la cartera =================
    entregar_titulo = ft.Text("", size=15, weight=ft.FontWeight.BOLD)
    entregar_proveedor_dropdown = ft.Dropdown(label="Proveedor *", width=300, options=[])
    cheque_a_entregar: dict = {}

    def ir_a_entregar(c: dict) -> None:
        cheque_a_entregar.clear()
        cheque_a_entregar.update(c)
        entregar_titulo.value = f"Entregar el cheque {c['banco']} (${formatear_precio(c['monto'])}) a un proveedor"
        entregar_proveedor_dropdown.options = [ft.dropdown.Option(key=str(p["id"]), text=p["nombre"])
                                               for p in proveedores_service.listar_proveedores(solo_activos=True)]
        entregar_proveedor_dropdown.value = None
        mostrar_seccion(seccion_entregar)

    def confirmar_entrega() -> None:
        try:
            if not entregar_proveedor_dropdown.value:
                raise ValueError("Elegi a que proveedor se lo entregas")
            cheques_service.entregar_a_proveedor(cheque_a_entregar["id"], int(entregar_proveedor_dropdown.value))
        except ERRORES_PARA_AVISAR as ex:
            avisar(page, str(ex), error=True)
            return
        mostrar_lista()
        avisar(page, "Cheque entregado al proveedor y aplicado a su cuenta corriente")

    seccion_entregar = ft.Column([tarjeta(
        ft.Row([entregar_proveedor_dropdown]),
        botones_formulario(ft.Text("Entregar"), confirmar_entrega, lambda: mostrar_lista()),
        titulo=entregar_titulo,
        subtitulo="Se usa para pagarle al proveedor en vez de depositarlo: se aplica a sus cargos abiertos mas viejos.",
    )], visible=False)

    # ================= Navegacion =================
    def mostrar_seccion(seccion: ft.Control) -> None:
        for s in (seccion_lista, seccion_form_recibido, seccion_form_propio, seccion_entregar):
            s.visible = s is seccion
        page.update()

    def abrir_form(seccion: ft.Control) -> None:
        cliente_dropdown.options = [ft.dropdown.Option(key=str(c["id"]), text=c["razon_social"])
                                    for c in clientes_service.listar_clientes(solo_activos=True)]
        propio_proveedor_dropdown.options = [ft.dropdown.Option(key=str(p["id"]), text=p["nombre"])
                                             for p in proveedores_service.listar_proveedores(solo_activos=True)]
        for campo in (recibido_banco_field, recibido_librador_field, recibido_cuit_field, recibido_numero_field,
                      recibido_monto_field, recibido_observacion_field, propio_banco_field, propio_cuit_field,
                      propio_numero_field, propio_monto_field, propio_observacion_field):
            campo.value = ""
        cliente_dropdown.value = propio_proveedor_dropdown.value = None
        recibido_fecha_field.value = propio_fecha_field.value = fecha_hoy()
        propio_librador_field.value = "Negocio propio"
        mostrar_seccion(seccion)

    def mostrar_lista() -> None:
        mostrar_seccion(seccion_lista)
        refrescar()

    refrescar()
    return ft.Column(
        [encabezado_pantalla("Cheques", "Los cheques recibidos de clientes y los propios entregados a proveedores, con su estado."),
         seccion_lista, seccion_form_recibido, seccion_form_propio, seccion_entregar],
        expand=True, scroll=ft.ScrollMode.AUTO, spacing=ESPACIO_PANTALLA,
    )
