import os
from datetime import date
from decimal import Decimal

import flet as ft

from app.services import ganancias_service, gastos_service, medios_pago_service, negocio_service
from app.services.exceptions import GastoNoEncontradoError
from app.shared.money import formatear_precio
from app.ui.campos import FILTRO_DECIMALES, aplicar_mascara_moneda, parsear_decimal_ar_opcional
from app.ui.listados import con_scroll_horizontal
from app.ui.theme import (
    COLOR_ACCENT,
    COLOR_ACCENT_STRONG,
    COLOR_ACCENT_WASH,
    COLOR_BORDER,
    COLOR_DANGER,
    COLOR_DANGER_WASH,
    COLOR_SURFACE,
    COLOR_TEXT,
    COLOR_TEXT_SOFT,
)
from app.ui.componentes import ESPACIO_PANTALLA, campo_buscar, encabezado_pantalla, tarjeta

EXCEPCIONES_NEGOCIO = (GastoNoEncontradoError, ValueError)
PERIODOS = [("hoy", "Hoy"), ("semana", "Esta semana"), ("mes", "Este mes"), ("mes_anterior", "Mes anterior")]
ALICUOTAS = [("0", "Sin IVA"), ("10.5", "10,5 %"), ("21", "21 %"), ("27", "27 %")]
ALTO_RESUMEN = 96


def pesos(valor: Decimal) -> str:
    return f"$ {formatear_precio(valor)}"


def GastosView(page: ft.Page) -> ft.Control:
    estado = {"periodo": "mes", "categoria": None, "editando": None, "anulando": None, "comprobante": None}
    # Selector de archivos del sistema (servicio de Flet: se registra solo en la pagina).
    selector_archivos = ft.FilePicker()

    def mostrar_mensaje(texto: str) -> None:
        page.show_dialog(ft.SnackBar(ft.Text(texto)))

    # ================= Formulario =================
    form_titulo = ft.Text("Nuevo gasto", size=15, weight=ft.FontWeight.BOLD)
    descripcion_field = ft.TextField(label="Descripcion *", expand=3)
    fecha_field = ft.TextField(label="Fecha * (AAAA-MM-DD)", width=170)
    categoria_dropdown = ft.Dropdown(label="Categoria *", width=210, options=[])
    nueva_categoria_field = ft.TextField(label="Nueva categoria", width=180, visible=False)
    nueva_categoria_texto = ft.Text("+ Categoria")
    nueva_categoria_button = ft.TextButton(content=nueva_categoria_texto)
    monto_field = ft.TextField(label="Monto total $ *", width=160, input_filter=FILTRO_DECIMALES)
    aplicar_mascara_moneda(monto_field)
    iva_dropdown = ft.Dropdown(label="IVA del comprobante", width=170, value="0",
                               options=[ft.dropdown.Option(key=k, text=t) for k, t in ALICUOTAS])
    medio_dropdown = ft.Dropdown(label="Medio de pago", width=190, options=[])
    proveedor_field = ft.TextField(label="Proveedor (opcional)", expand=1)
    observacion_field = ft.TextField(label="Observaciones", expand=2)
    comprobante_texto = ft.Text("Sin comprobante", size=12.5, color=COLOR_TEXT_SOFT)
    adjuntar_button = ft.OutlinedButton("Adjuntar foto o PDF", icon=ft.Icons.ATTACH_FILE)
    desglose_texto = ft.Text("", size=14, weight=ft.FontWeight.BOLD)
    desglose_nota = ft.Text("", size=12, color=COLOR_TEXT_SOFT)
    guardar_texto = ft.Text("Guardar gasto")
    guardar_button = ft.ElevatedButton(content=guardar_texto)
    cancelar_button = ft.TextButton("Cancelar")

    def recalcular_desglose(e: ft.ControlEvent | None = None) -> None:
        """Vista previa de cuanto cuenta como gasto: misma cuenta que el servicio."""
        try:
            total = parsear_decimal_ar_opcional(monto_field.value, "El monto") or Decimal("0")
        except ValueError:
            total = Decimal("0")
        alicuota = Decimal(iva_dropdown.value or "0")
        neto, iva = gastos_service.desglosar(total, alicuota)
        recupera = negocio_service.config_iva()["cobra_iva"]
        gasto = neto if (alicuota and recupera) else total
        desglose_texto.value = f"Neto {pesos(neto)}   Â·   IVA {pesos(iva)}   Â·   Cuenta como gasto {pesos(gasto)}"
        if not alicuota:
            desglose_nota.value = "Sin IVA: todo el monto es gasto."
        elif recupera:
            desglose_nota.value = "Negocio Responsable Inscripto: el IVA de este comprobante es credito fiscal (se recupera), asi que no es gasto."
        else:
            desglose_nota.value = "El negocio no recupera el IVA (no es Responsable Inscripto): el IVA tambien es gasto."
        if e is not None:
            page.update()

    monto_field.on_change = recalcular_desglose
    iva_dropdown.on_select = recalcular_desglose

    def alternar_nueva_categoria(e: ft.ControlEvent) -> None:
        if nueva_categoria_field.visible and (nueva_categoria_field.value or "").strip():
            try:
                categoria = gastos_service.crear_categoria(nueva_categoria_field.value)
            except ValueError as ex:
                mostrar_mensaje(str(ex))
                return
            cargar_opciones()
            categoria_dropdown.value = str(categoria["id"])
            mostrar_mensaje(f"Categoria '{categoria['nombre']}' creada")
        nueva_categoria_field.visible = not nueva_categoria_field.visible
        nueva_categoria_field.value = ""
        nueva_categoria_texto.value = "Crear" if nueva_categoria_field.visible else "+ Categoria"
        page.update()

    nueva_categoria_button.on_click = alternar_nueva_categoria

    async def elegir_comprobante(e: ft.ControlEvent) -> None:
        archivos = await selector_archivos.pick_files(
            dialog_title="Elegi la foto o el PDF del comprobante", file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=list(gastos_service.EXTENSIONES_COMPROBANTE),
        )
        if archivos and archivos[0].path:
            estado["comprobante"] = archivos[0].path
            comprobante_texto.value = f"ðŸ“Ž {archivos[0].name} (se guarda al guardar el gasto)"
            comprobante_texto.color = COLOR_ACCENT_STRONG
            page.update()

    adjuntar_button.on_click = elegir_comprobante

    def cargar_opciones() -> None:
        categoria_dropdown.options = [ft.dropdown.Option(key=str(c["id"]), text=c["nombre"]) for c in gastos_service.listar_categorias()]
        medio_dropdown.options = [ft.dropdown.Option(key="", text="Sin indicar")] + [
            ft.dropdown.Option(key=str(m["id"]), text=m["nombre"])
            for m in medios_pago_service.listar_medios_pago(solo_activos=True) if not m["es_cuenta_corriente"]
        ]

    def limpiar_formulario() -> None:
        estado["editando"] = None
        estado["comprobante"] = None
        form_titulo.value = "Nuevo gasto"
        guardar_texto.value = "Guardar gasto"
        for campo in (descripcion_field, monto_field, proveedor_field, observacion_field):
            campo.value = ""
        fecha_field.value = date.today().isoformat()
        categoria_dropdown.value = None
        iva_dropdown.value = "0"
        medio_dropdown.value = ""
        comprobante_texto.value = "Sin comprobante"
        comprobante_texto.color = COLOR_TEXT_SOFT
        cancelar_button.visible = False
        recalcular_desglose()

    def cargar_para_editar(gasto: dict) -> None:
        estado["editando"] = gasto["id"]
        estado["comprobante"] = None
        form_titulo.value = f"Editar gasto: {gasto['descripcion']}"
        guardar_texto.value = "Guardar cambios"
        descripcion_field.value = gasto["descripcion"]
        fecha_field.value = gasto["fecha"].isoformat()
        categoria_dropdown.value = str(gasto["categoria_id"])
        monto_field.value = formatear_precio(gasto["monto_total"])
        iva_dropdown.value = str(gasto["iva_porcentaje"].normalize()) if gasto["iva_porcentaje"] else "0"
        medio_dropdown.value = str(gasto["medio_pago_id"]) if gasto["medio_pago_id"] else ""
        proveedor_field.value = gasto["proveedor"] or ""
        observacion_field.value = gasto["observacion"] or ""
        comprobante_texto.value = f"ðŸ“Ž {os.path.basename(gasto['comprobante'])}" if gasto["comprobante"] else "Sin comprobante"
        comprobante_texto.color = COLOR_ACCENT_STRONG if gasto["comprobante"] else COLOR_TEXT_SOFT
        cancelar_button.visible = True
        recalcular_desglose()
        page.update()

    def guardar(e: ft.ControlEvent) -> None:
        try:
            datos = dict(
                fecha=fecha_field.value, descripcion=descripcion_field.value,
                categoria_id=int(categoria_dropdown.value) if categoria_dropdown.value else 0,
                monto_total=parsear_decimal_ar_opcional(monto_field.value, "El monto"),
                iva_porcentaje=Decimal(iva_dropdown.value or "0"),
                medio_pago_id=int(medio_dropdown.value) if medio_dropdown.value else None,
                proveedor=proveedor_field.value, observacion=observacion_field.value,
            )
            if estado["editando"] is not None:
                gasto = gastos_service.editar_gasto(estado["editando"], **datos)
                mensaje = f"Gasto '{gasto['descripcion']}' actualizado"
            else:
                gasto = gastos_service.crear_gasto(**datos)
                mensaje = f"Gasto '{gasto['descripcion']}' guardado: cuenta {pesos(gasto['gasto'])}"
            if estado["comprobante"]:
                gastos_service.adjuntar_comprobante(gasto["id"], estado["comprobante"])
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))
            return
        limpiar_formulario()
        refrescar()
        mostrar_mensaje(mensaje)

    guardar_button.on_click = guardar
    cancelar_button.on_click = lambda e: (limpiar_formulario(), page.update())

    formulario = tarjeta(
        ft.Row([descripcion_field, fecha_field, categoria_dropdown, nueva_categoria_field, nueva_categoria_button],
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ft.Row([monto_field, iva_dropdown, medio_dropdown, proveedor_field]),
        ft.Row([observacion_field, adjuntar_button, comprobante_texto], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ft.Container(
            ft.Column([desglose_texto, desglose_nota], spacing=2),
            bgcolor=COLOR_ACCENT_WASH, border_radius=8, padding=ft.Padding.symmetric(horizontal=14, vertical=10),
        ),
        ft.Row([guardar_button, cancelar_button]),
        titulo=form_titulo,
        subtitulo="Carga el monto total del comprobante. Si trae IVA, elegi la alicuota y la app separa cuanto es gasto.",
    )

    # ================= Filtros =================
    chips: dict[str, ft.Container] = {}
    buscador_field = campo_buscar("Descripcion, proveedor u observacion")

    def elegir_periodo(clave: str) -> None:
        estado["periodo"] = clave
        refrescar()

    for clave, texto in PERIODOS:
        chips[clave] = ft.Container(
            content=ft.Text(texto, size=13), padding=ft.Padding.symmetric(horizontal=14, vertical=8),
            border_radius=999, on_click=lambda e, c=clave: elegir_periodo(c), ink=True,
        )
    buscador_field.on_change = lambda e: refrescar()

    # ================= Resumen =================
    resumen_row = ft.Row(spacing=0, height=ALTO_RESUMEN)

    def tarjeta_resumen(etiqueta: str, valor: str, nota: str, destacada: bool = False) -> ft.Container:
        return ft.Container(
            expand=True, height=ALTO_RESUMEN, bgcolor=COLOR_DANGER_WASH if destacada else COLOR_SURFACE,
            padding=ft.Padding.symmetric(horizontal=18, vertical=12),
            content=ft.Column([
                ft.Text(etiqueta.upper(), size=11.5, weight=ft.FontWeight.BOLD, color=COLOR_TEXT_SOFT),
                ft.Text(valor, size=22, weight=ft.FontWeight.BOLD, color=COLOR_DANGER if destacada else COLOR_TEXT),
                ft.Text(nota, size=12, color=COLOR_TEXT_SOFT),
            ], spacing=2),
        )

    # ================= Lista y categorias =================
    tabla = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(t), numeric=n) for t, n in [
            ("Fecha", False), ("Descripcion", False), ("Categoria", False), ("Medio", False),
            ("Total", True), ("IVA", True), ("Gasto", True), ("", False), ("", False)]],
        rows=[], column_spacing=16, horizontal_margin=8,
    )
    sin_gastos_texto = ft.Text("", color=COLOR_TEXT_SOFT)
    categorias_column = ft.Column(spacing=4)
    titulo_lista = ft.Text("", size=15, weight=ft.FontWeight.BOLD)
    anular_titulo = ft.Text("", weight=ft.FontWeight.BOLD, color=COLOR_DANGER)
    anular_motivo_field = ft.TextField(label="Motivo (obligatorio)", expand=True)
    anular_franja = ft.Container(
        visible=False, padding=10, border=ft.Border.all(1, COLOR_DANGER), border_radius=8,
        content=ft.Row([
            anular_titulo, anular_motivo_field,
            ft.ElevatedButton("Anular", on_click=lambda e: confirmar_anulacion()),
            ft.TextButton("Cancelar", on_click=lambda e: ocultar_anulacion()),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )

    def tachado(texto: str, anulado: bool, **kw) -> ft.Text:
        color = kw.pop("color", None)
        return ft.Text(texto, color=COLOR_TEXT_SOFT if anulado else color,
                       style=ft.TextStyle(decoration=ft.TextDecoration.LINE_THROUGH) if anulado else None, **kw)

    def abrir_comprobante(ruta: str) -> None:
        try:
            os.startfile(ruta)
        except OSError:
            mostrar_mensaje("No se pudo abrir el comprobante (Â¿se movio o borro el archivo?)")

    def mostrar_anulacion(gasto: dict) -> None:
        estado["anulando"] = gasto
        anular_titulo.value = f"Anular '{gasto['descripcion']}' ({pesos(gasto['monto_total'])})"
        anular_motivo_field.value = ""
        anular_franja.visible = True
        page.update()

    def ocultar_anulacion() -> None:
        estado["anulando"] = None
        anular_franja.visible = False
        page.update()

    def confirmar_anulacion() -> None:
        gasto = estado["anulando"]
        try:
            gastos_service.anular_gasto(gasto["id"], anular_motivo_field.value)
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))
            return
        anular_franja.visible = False
        estado["anulando"] = None
        refrescar()
        mostrar_mensaje(f"Gasto '{gasto['descripcion']}' anulado")

    def fila(g: dict) -> ft.DataRow:
        anulado = g["anulado"]
        descripcion = [tachado(g["descripcion"], anulado, weight=ft.FontWeight.W_500)]
        if g["proveedor"]:
            descripcion.append(ft.Text(g["proveedor"], size=11.5, color=COLOR_TEXT_SOFT))
        if anulado:
            descripcion.append(ft.Text(f"ANULADO: {g['anulado_motivo']}", size=11.5, color=COLOR_DANGER, weight=ft.FontWeight.W_500))
        acciones = ft.Row([
            ft.IconButton(ft.Icons.EDIT, tooltip="Editar", icon_size=18, on_click=lambda e, x=g: cargar_para_editar(x)),
            ft.IconButton(ft.Icons.BLOCK, tooltip="Anular", icon_size=18, icon_color=COLOR_DANGER,
                          on_click=lambda e, x=g: mostrar_anulacion(x)),
        ], spacing=0, tight=True) if not anulado else ft.Text("")
        return ft.DataRow(cells=[
            ft.DataCell(tachado(g["fecha"].strftime("%d/%m"), anulado)),
            ft.DataCell(ft.Column(descripcion, spacing=0, tight=True)),
            ft.DataCell(ft.Container(ft.Text(g["categoria"], size=11.5, weight=ft.FontWeight.BOLD, color=COLOR_ACCENT_STRONG),
                                     bgcolor=COLOR_ACCENT_WASH, border_radius=999, padding=ft.Padding.symmetric(horizontal=9, vertical=2))),
            ft.DataCell(ft.Text(g["medio_pago"] or "-", color=COLOR_TEXT_SOFT)),
            ft.DataCell(tachado(formatear_precio(g["monto_total"]), anulado)),
            ft.DataCell(ft.Text(f"{formatear_precio(g['iva'])} ({str(g['iva_porcentaje'].normalize()).replace('.', ',')}%)"
                                if g["iva"] else "-", color=COLOR_TEXT_SOFT)),
            ft.DataCell(tachado(formatear_precio(g["gasto"]), anulado, weight=ft.FontWeight.BOLD, color=COLOR_DANGER)),
            ft.DataCell(ft.IconButton(ft.Icons.ATTACH_FILE, tooltip="Ver comprobante", icon_size=18, icon_color=COLOR_ACCENT_STRONG,
                                      on_click=lambda e, r=g["comprobante"]: abrir_comprobante(r)) if g["comprobante"] else ft.Text("")),
            ft.DataCell(acciones),
        ])

    def elegir_categoria(categoria: str) -> None:
        estado["categoria"] = None if estado["categoria"] == categoria else categoria
        refrescar()

    # ================= Refresco =================
    def refrescar() -> None:
        desde, hasta = ganancias_service.periodo(estado["periodo"])
        for clave, texto in PERIODOS:
            chip, activo = chips[clave], clave == estado["periodo"]
            chip.content.value = f"âœ“ {texto}" if activo else texto
            chip.bgcolor = COLOR_ACCENT if activo else COLOR_SURFACE
            chip.border = ft.Border.all(1, COLOR_ACCENT if activo else COLOR_BORDER)
            chip.content.color = ft.Colors.WHITE if activo else COLOR_TEXT
        r = gastos_service.resumen(desde, hasta)
        anulados = sum(1 for g in gastos_service.listar_gastos(desde, hasta) if g["anulado"])
        resumen_row.controls = [
            tarjeta_resumen("Pagado en el periodo", pesos(r["pagado"]),
                    f"{r['cantidad']} gasto{'' if r['cantidad'] == 1 else 's'}" + (f" Â· sin contar {anulados} anulado{'' if anulados == 1 else 's'}" if anulados else "")),
            ft.Container(width=1, height=ALTO_RESUMEN, bgcolor=COLOR_BORDER),
            tarjeta_resumen("IVA recuperable", pesos(r["iva_recuperable"]), "Credito fiscal de los comprobantes con IVA"),
            ft.Container(width=1, height=ALTO_RESUMEN, bgcolor=COLOR_BORDER),
            tarjeta_resumen("Gastos del negocio", pesos(r["gastos"]), "Es lo que se descuenta en Ganancias", destacada=True),
        ]
        categorias_id = {c["nombre"]: c["id"] for c in gastos_service.listar_categorias()}
        gastos = gastos_service.listar_gastos(desde, hasta, categorias_id.get(estado["categoria"]), buscador_field.value)
        titulo_lista.value = f"Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}" + (f" Â· {estado['categoria']}" if estado["categoria"] else "")
        tabla.rows = [fila(g) for g in gastos]
        tabla.visible = bool(gastos)
        sin_gastos_texto.visible = not gastos
        sin_gastos_texto.value = "No hay gastos en el periodo." if not (buscador_field.value or "").strip() else "Ningun gasto coincide con la busqueda."
        maximo = max((c["gasto"] for c in r["por_categoria"]), default=Decimal("0"))
        categorias_column.controls = [
            ft.Container(
                on_click=lambda e, c=c["categoria"]: elegir_categoria(c), ink=True, border_radius=6,
                padding=ft.Padding.symmetric(horizontal=6, vertical=6),
                opacity=0.45 if estado["categoria"] and estado["categoria"] != c["categoria"] else 1,
                content=ft.Column([
                    ft.Row([ft.Text(c["categoria"], expand=True), ft.Text(formatear_precio(c["gasto"]), weight=ft.FontWeight.BOLD)]),
                    ft.Container(height=6, border_radius=3, bgcolor=COLOR_BORDER, content=ft.Row([
                        ft.Container(height=6, border_radius=3, bgcolor=COLOR_ACCENT,
                                     expand=max(1, int(100 * c["gasto"] / maximo)) if maximo else 1),
                        ft.Container(expand=max(0, 100 - int(100 * c["gasto"] / maximo)) if maximo else 0),
                    ], spacing=0)),
                ], spacing=4),
            )
            for c in r["por_categoria"]
        ] or [ft.Text("Sin gastos en el periodo.", color=COLOR_TEXT_SOFT)]
        page.update()

    vista = ft.Column(
        [
            encabezado_pantalla("Gastos", "Lo que cuesta mantener el negocio abierto: alquiler, sueldos, servicios, combustible, impuestos."),
            formulario,
            ft.Row([*chips.values(), buscador_field], spacing=8, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Container(resumen_row, border=ft.Border.all(1, COLOR_BORDER), border_radius=12, bgcolor=COLOR_SURFACE,
                         clip_behavior=ft.ClipBehavior.ANTI_ALIAS),
            ft.Row([
                ft.Container(
                    expand=3, bgcolor=COLOR_SURFACE, border=ft.Border.all(1, COLOR_BORDER), border_radius=12,
                    padding=ft.Padding.symmetric(horizontal=18, vertical=16),
                    content=ft.Column([titulo_lista,
                                       ft.Text("Un gasto anulado queda tachado y deja de sumar.", size=12, color=COLOR_TEXT_SOFT),
                                       anular_franja, con_scroll_horizontal(tabla), sin_gastos_texto], spacing=8),
                ),
                ft.Container(
                    expand=1, bgcolor=COLOR_SURFACE, border=ft.Border.all(1, COLOR_BORDER), border_radius=12,
                    padding=ft.Padding.symmetric(horizontal=18, vertical=16),
                    content=ft.Column([ft.Text("Por categoria", size=15, weight=ft.FontWeight.BOLD),
                                       ft.Text("Hace clic en una para filtrar la lista.", size=12, color=COLOR_TEXT_SOFT),
                                       categorias_column], spacing=6),
                ),
            ], spacing=16, vertical_alignment=ft.CrossAxisAlignment.START),
        ],
        expand=True, spacing=ESPACIO_PANTALLA, scroll=ft.ScrollMode.AUTO,
    )
    cargar_opciones()
    limpiar_formulario()
    refrescar()
    return vista
