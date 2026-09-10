from datetime import datetime

import flet as ft

from app.services import cc_service, clientes_service, proveedores_service
from app.services.exceptions import (
    CargoNoEncontradoError,
    ClienteNoEncontradoError,
    MontoPagoInvalidoError,
    ProveedorNoEncontradoError,
)
from app.shared.money import formatear_porcentaje, formatear_precio
from app.ui.campos import FILTRO_DECIMALES, aplicar_mascara_moneda, parsear_decimal_ar_opcional
from app.ui.listados import coincide_texto

EXCEPCIONES_NEGOCIO = (
    CargoNoEncontradoError, ClienteNoEncontradoError, MontoPagoInvalidoError,
    ProveedorNoEncontradoError, ValueError,
)

ORIGEN_LABEL = {"manual": "Manual", "recepcion": "Compra a credito", "venta": "Venta a credito"}


def CuentasCorrientesView(page: ft.Page) -> ft.Control:
    def mostrar_mensaje(texto: str) -> None:
        page.show_dialog(ft.SnackBar(ft.Text(texto)))

    def nombre_entidad(tipo: str, entidad: dict) -> str:
        return entidad["razon_social"] if tipo == "cliente" else entidad["nombre"]

    def listar_entidades(tipo: str) -> list[dict]:
        return clientes_service.listar_clientes() if tipo == "cliente" else proveedores_service.listar_proveedores()

    # ================= SECCION LISTA =================
    tipo_dropdown = ft.Dropdown(
        label="Cuenta", width=180, value="cliente",
        options=[ft.dropdown.Option(key="cliente", text="Clientes"), ft.dropdown.Option(key="proveedor", text="Proveedores")],
    )
    buscador_field = ft.TextField(label="Buscar", expand=True)
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
                    formatear_precio(saldo),
                    color=ft.Colors.RED if saldo > 0 else None,
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
        ft.Text("Cuentas Corrientes", size=20, weight=ft.FontWeight.BOLD),
        ft.Row([tipo_dropdown, buscador_field]),
        tabla_lista,
    ])

    # ================= SECCION DETALLE =================
    detalle_tipo: str | None = None
    detalle_id: int | None = None

    detalle_titulo = ft.Text("", size=18, weight=ft.FontWeight.BOLD)
    detalle_saldo_texto = ft.Text("", size=16)
    volver_button = ft.TextButton("Volver al listado", on_click=lambda e: ir_a_lista(None))

    tabla_cargos = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(t)) for t in
                 ["Fecha", "Origen", "Monto", "Saldo pendiente", "Interes por mora", "Observacion"]],
        rows=[],
    )
    cargo_monto_field = ft.TextField(label="Monto", width=160, input_filter=FILTRO_DECIMALES)
    aplicar_mascara_moneda(cargo_monto_field)
    cargo_fecha_field = ft.TextField(label="Fecha (AAAA-MM-DD)", width=160, value=datetime.now().strftime("%Y-%m-%d"))
    cargo_observacion_field = ft.TextField(label="Observacion (opcional)", expand=True)
    agregar_cargo_button = ft.ElevatedButton("+ Agregar cargo")

    tabla_pagos = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(t)) for t in ["Fecha", "Monto", "Observacion"]],
        rows=[],
    )
    pago_monto_field = ft.TextField(label="Monto del pago", width=160, input_filter=FILTRO_DECIMALES)
    aplicar_mascara_moneda(pago_monto_field)
    pago_fecha_field = ft.TextField(label="Fecha (AAAA-MM-DD)", width=160, value=datetime.now().strftime("%Y-%m-%d"))
    pago_observacion_field = ft.TextField(label="Observacion (opcional)", expand=True)
    pago_puntual_switch = ft.Switch(label="Aplicar a cargos puntuales (si no, se aplica a cuenta: el mas viejo primero)")
    contenedor_cargos_puntuales = ft.Column([])
    registrar_pago_button = ft.ElevatedButton("Registrar pago")

    campos_aplicacion: dict[int, ft.TextField] = {}

    def toggle_puntual(e: ft.ControlEvent) -> None:
        contenedor_cargos_puntuales.visible = pago_puntual_switch.value
        page.update()

    pago_puntual_switch.on_change = toggle_puntual

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

    def refrescar_detalle() -> None:
        saldo = cc_service.calcular_saldo_total(detalle_tipo, detalle_id)
        if detalle_tipo == "cliente":
            entidad = clientes_service.obtener_cliente(detalle_id)
            nombre = entidad["razon_social"]
        else:
            entidad = proveedores_service.obtener_proveedor(detalle_id)
            nombre = entidad["nombre"]
        detalle_titulo.value = f"{nombre} ({'Clientes' if detalle_tipo == 'cliente' else 'Proveedores'})"
        detalle_saldo_texto.value = f"Saldo actual: {formatear_precio(saldo)}"
        detalle_saldo_texto.color = ft.Colors.RED if saldo > 0 else None

        cargos = cc_service.listar_cargos(detalle_tipo, detalle_id)
        filas_cargos = []
        for c in cargos:
            interes_texto = "-"
            if detalle_tipo == "cliente":
                interes = cc_service.calcular_interes_mora(detalle_id, c)
                if interes > 0:
                    interes_texto = formatear_precio(interes)
            filas_cargos.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(c["fecha"][:10])),
                ft.DataCell(ft.Text(ORIGEN_LABEL.get(c["origen"], c["origen"]))),
                ft.DataCell(ft.Text(formatear_precio(c["monto"]))),
                ft.DataCell(ft.Text(
                    formatear_precio(c["saldo_pendiente"]),
                    color=ft.Colors.RED if c["saldo_pendiente"] > 0 else None,
                )),
                ft.DataCell(ft.Text(interes_texto, color=ft.Colors.ORANGE if interes_texto != "-" else None)),
                ft.DataCell(ft.Text(c["observacion"] or "-")),
            ]))
        tabla_cargos.rows = filas_cargos

        pagos = cc_service.listar_pagos(detalle_tipo, detalle_id)
        tabla_pagos.rows = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Text(p["fecha"][:10])),
                ft.DataCell(ft.Text(formatear_precio(p["monto"]))),
                ft.DataCell(ft.Text(p["observacion"] or "-")),
            ])
            for p in pagos
        ]

        refrescar_cargos_puntuales()
        page.update()

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

    def registrar_pago(e: ft.ControlEvent) -> None:
        try:
            monto = parsear_decimal_ar_opcional(pago_monto_field.value, "El monto del pago")
            if monto is None:
                raise ValueError("El monto del pago es obligatorio")
            fecha = (pago_fecha_field.value or "").strip()
            if not fecha:
                raise ValueError("La fecha es obligatoria")

            aplicaciones = None
            if pago_puntual_switch.value:
                aplicaciones = []
                for cargo_id, campo in campos_aplicacion.items():
                    valor = parsear_decimal_ar_opcional(campo.value, "El monto aplicado")
                    if valor:
                        aplicaciones.append({"cargo_id": cargo_id, "monto": valor})
                if not aplicaciones:
                    raise ValueError("Cargaste 'aplicar a cargos puntuales' pero no pusiste ningun monto")

            cc_service.registrar_pago(
                detalle_tipo, detalle_id, monto, fecha, aplicaciones,
                (pago_observacion_field.value or "").strip() or None,
            )
            pago_monto_field.value = ""
            pago_observacion_field.value = ""
            pago_puntual_switch.value = False
            mostrar_mensaje("Pago registrado")
            refrescar_detalle()
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))

    registrar_pago_button.on_click = registrar_pago

    seccion_detalle = ft.Column(
        [
            detalle_titulo,
            detalle_saldo_texto,
            volver_button,
            ft.Text("Cargos", weight=ft.FontWeight.BOLD),
            tabla_cargos,
            ft.Row([cargo_monto_field, cargo_fecha_field, cargo_observacion_field, agregar_cargo_button]),
            ft.Text("Pagos / cobros", weight=ft.FontWeight.BOLD),
            tabla_pagos,
            ft.Row([pago_monto_field, pago_fecha_field, pago_observacion_field]),
            pago_puntual_switch,
            contenedor_cargos_puntuales,
            registrar_pago_button,
        ],
        visible=False,
        scroll=ft.ScrollMode.AUTO,
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
        refrescar_detalle()
        page.update()

    refrescar_lista()

    return ft.Column(
        [seccion_lista, seccion_detalle],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
