import os
from datetime import date
from decimal import Decimal

import flet as ft

from app.services import ganancias_service, gastos_service, medios_pago_service, negocio_service
from app.shared.money import formatear_precio
from app.ui.campos import FILTRO_DECIMALES, aplicar_mascara_moneda, parsear_decimal_ar_opcional
from app.ui.componentes import (
    ESPACIO_PANTALLA,
    ERRORES_PARA_AVISAR,
    TONO_NO,
    TONO_OK,
    Columna,
    Lista,
    accion_abrir,
    accion_anular,
    accion_ver,
    avisar,
    barra,
    boton_principal,
    botones_formulario,
    campo_buscar,
    encabezado_pantalla,
    etiqueta_estado,
    tarjeta,
)
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

PERIODOS = [("hoy", "Hoy"), ("semana", "Esta semana"), ("mes", "Este mes"), ("mes_anterior", "Mes anterior")]
ALICUOTAS = [("0", "Sin IVA"), ("10.5", "10,5 %"), ("21", "21 %"), ("27", "27 %")]
ALTO_RESUMEN = 96


def pesos(valor: Decimal) -> str:
    return f"$ {formatear_precio(valor)}"


def GastosView(page: ft.Page) -> ft.Control:
    estado = {"periodo": "mes", "categoria": None, "editando": None, "comprobante": None}
    # Selector de archivos del sistema (servicio de Flet: se registra solo en la pagina).
    selector_archivos = ft.FilePicker()

    # ================= Filtros =================
    chips: dict[str, ft.Container] = {}
    buscador_field = campo_buscar("Descripcion, proveedor u observacion", al_cambiar=lambda: filtrar())
    estado_filtro = ft.Dropdown(label="Estado", width=160, value="", on_select=lambda e: filtrar(), options=[
        ft.dropdown.Option(key="", text="Todos"), ft.dropdown.Option(key="vigentes", text="Vigentes"),
        ft.dropdown.Option(key="anulados", text="Anulados"),
    ])

    def elegir_periodo(clave: str) -> None:
        estado["periodo"] = clave
        filtrar()

    for clave, texto in PERIODOS:
        chips[clave] = ft.Container(
            content=ft.Text(texto, size=13), padding=ft.Padding.symmetric(horizontal=14, vertical=8),
            border_radius=999, on_click=lambda e, c=clave: elegir_periodo(c), ink=True,
        )

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

    # ================= Lista =================
    titulo_lista = ft.Text("", size=13, color=COLOR_TEXT_SOFT)
    lista = Lista(
        [
            Columna("Fecha", ancho=80, orden="fecha"), Columna("Descripcion", peso=3, orden="descripcion"),
            Columna("Categoria", ancho=140, orden="categoria"), Columna("Medio", peso=1),
            Columna("Total", ancho=110, derecha=True, orden="monto_total"), Columna("IVA", ancho=130, derecha=True),
            Columna("Gasto", ancho=110, derecha=True, orden="gasto"), Columna("Estado", ancho=90),
            Columna("Acciones", ancho=130, derecha=True),
        ],
        al_cambiar_pagina=lambda: refrescar(), nombre="gastos", orden_inicial=("fecha", True),
        sin_datos="No hay gastos con estos filtros.",
    )
    lista.control.expand = 3
    categorias_column = ft.Column(spacing=4)

    def tachado(texto: str, anulado: bool, **kw) -> ft.Text:
        color = kw.pop("color", None)
        return ft.Text(texto, color=COLOR_TEXT_SOFT if anulado else color,
                       style=ft.TextStyle(decoration=ft.TextDecoration.LINE_THROUGH) if anulado else None, **kw)

    def abrir_comprobante(ruta: str) -> None:
        try:
            os.startfile(ruta)
        except OSError:
            avisar(page, "No se pudo abrir el comprobante (¿se movio o se borro el archivo?)", error=True)

    def celdas(g: dict) -> list:
        anulado = g["anulado"]
        descripcion = [tachado(g["descripcion"], anulado, weight=ft.FontWeight.W_500)]
        if g["proveedor"]:
            descripcion.append(ft.Text(g["proveedor"], size=11.5, color=COLOR_TEXT_SOFT))
        if anulado:
            descripcion.append(ft.Text(f"Anulado: {g['anulado_motivo']}", size=11.5, color=COLOR_DANGER))
        iva = (f"{formatear_precio(g['iva'])} ({str(g['iva_porcentaje'].normalize()).replace('.', ',')}%)"
               if g["iva"] else None)
        return [
            tachado(g["fecha"].strftime("%d/%m"), anulado),
            ft.Column(descripcion, spacing=0, tight=True),
            ft.Container(ft.Text(g["categoria"], size=11.5, weight=ft.FontWeight.BOLD, color=COLOR_ACCENT_STRONG),
                         bgcolor=COLOR_ACCENT_WASH, border_radius=999, padding=ft.Padding.symmetric(horizontal=9, vertical=2)),
            g["medio_pago"],
            tachado(formatear_precio(g["monto_total"]), anulado),
            iva,
            tachado(formatear_precio(g["gasto"]), anulado, weight=ft.FontWeight.BOLD, color=COLOR_DANGER),
            etiqueta_estado("Anulado", TONO_NO) if anulado else etiqueta_estado("Vigente", TONO_OK),
            ft.Row([
                accion_ver(ft.Icons.ATTACH_FILE, "Ver comprobante", lambda g=g: abrir_comprobante(g["comprobante"]),
                           por_que_no=None if g["comprobante"] else "no tiene comprobante adjunto"),
                accion_abrir(ft.Icons.EDIT, "Editar gasto", lambda g=g: ir_a_formulario(g),
                             por_que_no="esta anulado" if anulado else None),
                accion_anular(
                    "Anular gasto", f"Anular '{g['descripcion']}'",
                    f"Deja de sumar en los gastos y en Ganancias ({pesos(g['gasto'])}). Queda en la lista, tachado.",
                    lambda motivo, g=g: anular(g, motivo), por_que_no="ya esta anulado" if anulado else None,
                ),
            ], spacing=0, tight=True),
        ]

    def anular(g: dict, motivo: str) -> str:
        gastos_service.anular_gasto(g["id"], motivo)
        refrescar()
        return f"Gasto '{g['descripcion']}' anulado"

    def elegir_categoria(categoria: str) -> None:
        estado["categoria"] = None if estado["categoria"] == categoria else categoria
        filtrar()

    def filtrar() -> None:
        lista.ir_al_principio()
        refrescar()

    def refrescar() -> None:
        desde, hasta = ganancias_service.periodo(estado["periodo"])
        for clave, texto in PERIODOS:
            chip, activo = chips[clave], clave == estado["periodo"]
            chip.content.value = f"✓ {texto}" if activo else texto
            chip.bgcolor = COLOR_ACCENT if activo else COLOR_SURFACE
            chip.border = ft.Border.all(1, COLOR_ACCENT if activo else COLOR_BORDER)
            chip.content.color = ft.Colors.WHITE if activo else COLOR_TEXT
        r = gastos_service.resumen(desde, hasta)
        todos = gastos_service.listar_gastos(desde, hasta)
        anulados = sum(1 for g in todos if g["anulado"])
        resumen_row.controls = [
            tarjeta_resumen("Pagado en el periodo", pesos(r["pagado"]),
                            f"{r['cantidad']} gasto{'' if r['cantidad'] == 1 else 's'}"
                            + (f" · sin contar {anulados} anulado{'' if anulados == 1 else 's'}" if anulados else "")),
            ft.Container(width=1, height=ALTO_RESUMEN, bgcolor=COLOR_BORDER),
            tarjeta_resumen("IVA recuperable", pesos(r["iva_recuperable"]), "Credito fiscal de los comprobantes con IVA"),
            ft.Container(width=1, height=ALTO_RESUMEN, bgcolor=COLOR_BORDER),
            tarjeta_resumen("Gastos del negocio", pesos(r["gastos"]), "Es lo que se descuenta en Ganancias", destacada=True),
        ]
        categorias_id = {c["nombre"]: c["id"] for c in gastos_service.listar_categorias()}
        gastos = [
            g for g in gastos_service.listar_gastos(desde, hasta, categorias_id.get(estado["categoria"]), buscador_field.value)
            if (estado_filtro.value != "vigentes" or not g["anulado"]) and (estado_filtro.value != "anulados" or g["anulado"])
        ]
        titulo_lista.value = (f"Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}"
                              + (f" · solo {estado['categoria']} (clic de nuevo en la categoria para ver todas)"
                                 if estado["categoria"] else ""))
        lista.mostrar(gastos, celdas, valor_orden=lambda g, k: g[k])
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

    seccion_lista = ft.Column([
        barra([*chips.values(), buscador_field, estado_filtro],
              [boton_principal("Nuevo gasto", ft.Icons.ADD, lambda: ir_a_formulario(None))]),
        ft.Container(resumen_row, border=ft.Border.all(1, COLOR_BORDER), border_radius=12, bgcolor=COLOR_SURFACE,
                     clip_behavior=ft.ClipBehavior.ANTI_ALIAS),
        titulo_lista,
        ft.Row([
            lista.control,
            tarjeta(categorias_column, titulo="Por categoria", subtitulo="Clic en una para filtrar la lista.", expand=1),
        ], spacing=16, vertical_alignment=ft.CrossAxisAlignment.START),
    ], spacing=ESPACIO_PANTALLA)

    # ================= Formulario (alta / edicion) =================
    form_titulo = ft.Text("", size=15, weight=ft.FontWeight.BOLD)
    guardar_texto = ft.Text("")
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
        desglose_texto.value = f"Neto {pesos(neto)}   ·   IVA {pesos(iva)}   ·   Cuenta como gasto {pesos(gasto)}"
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
            except ERRORES_PARA_AVISAR as ex:
                avisar(page, str(ex), error=True)
                return
            cargar_opciones()
            categoria_dropdown.value = str(categoria["id"])
            avisar(page, f"Categoria '{categoria['nombre']}' creada")
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
            comprobante_texto.value = f"📎 {archivos[0].name} (se guarda al guardar el gasto)"
            comprobante_texto.color = COLOR_ACCENT_STRONG
            page.update()

    adjuntar_button.on_click = elegir_comprobante

    def cargar_opciones() -> None:
        categoria_dropdown.options = [ft.dropdown.Option(key=str(c["id"]), text=c["nombre"]) for c in gastos_service.listar_categorias()]
        medio_dropdown.options = [ft.dropdown.Option(key="", text="Sin indicar")] + [
            ft.dropdown.Option(key=str(m["id"]), text=m["nombre"])
            for m in medios_pago_service.listar_medios_pago(solo_activos=True) if not m["es_cuenta_corriente"]
        ]

    def ir_a_formulario(gasto: dict | None) -> None:
        cargar_opciones()
        estado["editando"] = gasto["id"] if gasto else None
        estado["comprobante"] = None
        g = gasto or {}
        form_titulo.value = f"Editar gasto: {gasto['descripcion']}" if gasto else "Nuevo gasto"
        guardar_texto.value = "Guardar cambios" if gasto else "Guardar gasto"
        descripcion_field.value = g.get("descripcion", "")
        fecha_field.value = gasto["fecha"].isoformat() if gasto else date.today().isoformat()
        categoria_dropdown.value = str(gasto["categoria_id"]) if gasto else None
        monto_field.value = formatear_precio(gasto["monto_total"]) if gasto else ""
        iva_dropdown.value = str(gasto["iva_porcentaje"].normalize()) if gasto and gasto["iva_porcentaje"] else "0"
        medio_dropdown.value = str(gasto["medio_pago_id"]) if gasto and gasto["medio_pago_id"] else ""
        proveedor_field.value = g.get("proveedor") or ""
        observacion_field.value = g.get("observacion") or ""
        comprobante_texto.value = f"📎 {os.path.basename(gasto['comprobante'])}" if gasto and gasto["comprobante"] else "Sin comprobante"
        comprobante_texto.color = COLOR_ACCENT_STRONG if gasto and gasto["comprobante"] else COLOR_TEXT_SOFT
        nueva_categoria_field.visible = False
        nueva_categoria_texto.value = "+ Categoria"
        recalcular_desglose()
        seccion_lista.visible = False
        seccion_formulario.visible = True
        page.update()

    def volver_a_lista() -> None:
        seccion_formulario.visible = False
        seccion_lista.visible = True
        refrescar()

    def guardar() -> None:
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
                aviso = f"Gasto '{gasto['descripcion']}' guardado"
            else:
                gasto = gastos_service.crear_gasto(**datos)
                aviso = f"Gasto '{gasto['descripcion']}' guardado: cuenta {pesos(gasto['gasto'])}"
            if estado["comprobante"]:
                gastos_service.adjuntar_comprobante(gasto["id"], estado["comprobante"])
        except ERRORES_PARA_AVISAR as ex:
            avisar(page, str(ex), error=True)
            return
        volver_a_lista()
        avisar(page, aviso)

    seccion_formulario = ft.Column([
        tarjeta(
            ft.Row([descripcion_field, fecha_field, categoria_dropdown, nueva_categoria_field, nueva_categoria_button],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([monto_field, iva_dropdown, medio_dropdown, proveedor_field]),
            ft.Row([observacion_field, adjuntar_button, comprobante_texto], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Container(
                ft.Column([desglose_texto, desglose_nota], spacing=2),
                bgcolor=COLOR_ACCENT_WASH, border_radius=8, padding=ft.Padding.symmetric(horizontal=14, vertical=10),
            ),
            botones_formulario(guardar_texto, guardar, volver_a_lista),
            titulo=form_titulo,
            subtitulo="Carga el monto total del comprobante. Si trae IVA, elegi la alicuota y la app separa cuanto es gasto. "
                      "Al guardar o cancelar volves a la lista.",
        ),
    ], visible=False)

    refrescar()
    return ft.Column(
        [
            encabezado_pantalla("Gastos", "Lo que cuesta mantener el negocio abierto: alquiler, sueldos, servicios, combustible, impuestos."),
            seccion_lista,
            seccion_formulario,
        ],
        expand=True, spacing=ESPACIO_PANTALLA, scroll=ft.ScrollMode.AUTO,
    )
