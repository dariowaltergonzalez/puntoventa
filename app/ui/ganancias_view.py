import math
from datetime import date
from decimal import Decimal

import flet as ft

from app.services import ganancias_service
from app.shared.money import formatear_cantidad, formatear_precio
from app.ui.listados import con_scroll_horizontal
from app.ui.theme import (
    COLOR_ACCENT,
    COLOR_ACCENT_STRONG,
    COLOR_ACCENT_WASH,
    COLOR_BG_ALT,
    COLOR_BORDER,
    COLOR_DANGER,
    COLOR_SUCCESS,
    COLOR_SUCCESS_WASH,
    COLOR_SURFACE,
    COLOR_TEXT,
    COLOR_TEXT_SOFT,
)

COLOR_GRILLA = "#e4eeec"
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
PERIODOS = [("hoy", "Hoy"), ("semana", "Esta semana"), ("mes", "Este mes"), ("mes_anterior", "Mes anterior")]
ALTO_GRAFICO = 230
EJE_Y = 48
EJE_X = 22
MARGEN_ARRIBA = 18


def pesos(valor: Decimal) -> str:
    if valor < 0:
        return f"−$ {formatear_precio(-valor)}"
    return f"$ {formatear_precio(valor)}"


def porcentaje(valor: Decimal | None) -> str:
    return "-" if valor is None else f"{str(valor).replace('.', ',')} %"


def unidades(valor: Decimal) -> str:
    return str(int(valor)) if valor == valor.to_integral_value() else formatear_cantidad(valor)


def paso_redondo(rango: Decimal) -> Decimal:
    """Paso 'lindo' para el eje (1, 2, 2,5 o 5 por potencia de 10), apuntando a ~4 lineas."""
    if rango <= 0:
        return Decimal("1000")
    crudo = float(rango) / 4
    potencia = 10 ** math.floor(math.log10(crudo))
    for factor in (1, 2, 2.5, 5, 10):
        if crudo <= factor * potencia:
            return Decimal(str(factor * potencia))
    return Decimal(str(10 * potencia))


def compacto(valor: Decimal) -> str:
    if abs(valor) >= 1000:
        texto = f"{valor / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{texto.replace('.', ',')}K"
    return str(int(valor))


def GananciasView(page: ft.Page) -> ft.Control:
    estado = {"periodo": "mes"}

    def mostrar_mensaje(texto: str) -> None:
        page.show_dialog(ft.SnackBar(ft.Text(texto)))

    # ================= Filtros =================
    chips: dict[str, ft.Container] = {}
    desde_field = ft.TextField(label="Desde", width=140, dense=True, hint_text="AAAA-MM-DD")
    hasta_field = ft.TextField(label="Hasta", width=140, dense=True, hint_text="AAAA-MM-DD")

    rango_personalizado_texto = ft.Text("✓ Rango personalizado", size=13, weight=ft.FontWeight.W_500,
                                        color=COLOR_ACCENT_STRONG, visible=False)

    def pintar_chips() -> None:
        """El filtro aplicado siempre queda a la vista: el boton del periodo con tilde, o
        'Rango personalizado' si las fechas no coinciden con ninguno."""
        for clave, texto in PERIODOS:
            chip, activo = chips[clave], clave == estado["periodo"]
            chip.bgcolor = COLOR_ACCENT if activo else COLOR_SURFACE
            chip.border = ft.Border.all(1, COLOR_ACCENT if activo else COLOR_BORDER)
            chip.content.value = f"✓ {texto}" if activo else texto
            chip.content.color = ft.Colors.WHITE if activo else COLOR_TEXT
            chip.content.weight = ft.FontWeight.W_500 if activo else None
        rango_personalizado_texto.visible = estado["periodo"] is None

    def elegir_periodo(clave: str) -> None:
        estado["periodo"] = clave
        desde, hasta = ganancias_service.periodo(clave)
        desde_field.value, hasta_field.value = desde.isoformat(), hasta.isoformat()
        refrescar()

    for clave, texto in PERIODOS:
        chips[clave] = ft.Container(
            content=ft.Text(texto, size=13), padding=ft.Padding.symmetric(horizontal=14, vertical=8),
            border_radius=999, on_click=lambda e, c=clave: elegir_periodo(c), ink=True,
        )

    def ver_rango(e: ft.ControlEvent | None = None) -> None:
        # Fechas escritas a mano: si coinciden con un periodo (ej. las de hoy), se marca ese boton.
        estado["periodo"] = None
        try:
            rango = (date.fromisoformat((desde_field.value or "").strip()), date.fromisoformat((hasta_field.value or "").strip()))
            estado["periodo"] = next((clave for clave, _ in PERIODOS if ganancias_service.periodo(clave) == rango), None)
        except ValueError:
            pass  # refrescar() avisa del formato
        refrescar()

    ver_button = ft.ElevatedButton("Ver", on_click=ver_rango)
    desde_field.on_submit = ver_rango
    hasta_field.on_submit = ver_rango

    # ================= Encabezado y KPIs =================
    subtitulo = ft.Text("", size=13, color=COLOR_TEXT_SOFT)
    # Alto fijo a proposito: CrossAxisAlignment.STRETCH dentro de una pantalla con scroll le da
    # alto "infinito" a la fila y Flet deja de dibujar todo lo que sigue, sin mostrar ningun error.
    ALTO_KPI = 116
    kpis_row = ft.Row(spacing=0, height=ALTO_KPI)
    contexto_row = ft.Row(spacing=24, wrap=True)

    def tile(etiqueta: str, valor: str, nota: ft.Control, color_valor: str = COLOR_TEXT,
             fondo: str = COLOR_SURFACE, grande: bool = False) -> ft.Container:
        return ft.Container(
            expand=True, height=ALTO_KPI, bgcolor=fondo, padding=ft.Padding.symmetric(horizontal=16, vertical=14),
            content=ft.Column([
                ft.Text(etiqueta.upper(), size=11.5, weight=ft.FontWeight.BOLD, color=COLOR_TEXT_SOFT),
                ft.Text(valor, size=27 if grande else 23, weight=ft.FontWeight.BOLD, color=color_valor, no_wrap=True),
                nota,
            ], spacing=4),
        )

    def operador(simbolo: str) -> ft.Container:
        return ft.Container(
            width=22, height=ALTO_KPI, alignment=ft.Alignment.CENTER, bgcolor=COLOR_BG_ALT,
            content=ft.Text(simbolo, size=14, weight=ft.FontWeight.BOLD, color=COLOR_TEXT_SOFT),
        )

    def nota(texto: str) -> ft.Text:
        return ft.Text(texto, size=12, color=COLOR_TEXT_SOFT)

    def dato(etiqueta: str, valor: str) -> ft.Text:
        return ft.Text(spans=[
            ft.TextSpan(f"{etiqueta} ", ft.TextStyle(color=COLOR_TEXT_SOFT)),
            ft.TextSpan(valor, ft.TextStyle(weight=ft.FontWeight.BOLD, color=COLOR_TEXT)),
        ], size=13)

    # ================= Grafico =================
    grafico_titulo = ft.Text("", size=15, weight=ft.FontWeight.BOLD)
    grafico_sub = ft.Text("Pasá el mouse por una barra para ver el detalle.", size=12, color=COLOR_TEXT_SOFT)
    grafico_cont = ft.Container(height=ALTO_GRAFICO)

    def etiqueta_bucket(inicio: date, agrupacion: str, larga: bool) -> str:
        if agrupacion == "dia":
            return f"{DIAS[inicio.weekday()]} {inicio:%d/%m}" if larga else str(inicio.day)
        if agrupacion == "semana":
            return f"Semana del {inicio:%d/%m}" if larga else f"{inicio:%d/%m}"
        return f"{MESES[inicio.month - 1]} {inicio:%y}"

    def construir_grafico(r: dict) -> None:
        serie, agrupacion = r["serie"], r["agrupacion"]
        valores = [p["ganancia"] for p in serie] or [Decimal("0")]
        paso = paso_redondo(max(max(valores), Decimal("0")) - min(min(valores), Decimal("0")))
        tope = paso * math.ceil(max(max(valores), Decimal("0")) / paso) if max(valores) > 0 else paso
        piso = -paso * math.ceil(-min(valores) / paso) if min(valores) < 0 else Decimal("0")
        alto_util = ALTO_GRAFICO - EJE_X - MARGEN_ARRIBA

        def y(valor: Decimal) -> float:
            return MARGEN_ARRIBA + alto_util * float((tope - valor) / (tope - piso))

        capas: list[ft.Control] = []
        tick = piso
        while tick <= tope:
            capas.append(ft.Container(left=EJE_Y, right=0, top=y(tick), height=1, bgcolor=COLOR_GRILLA))
            capas.append(ft.Container(left=0, width=EJE_Y - 8, top=y(tick) - 8, content=ft.Text(
                compacto(tick), size=11, color=COLOR_TEXT_SOFT, text_align=ft.TextAlign.RIGHT)))
            tick += paso

        cada = max(1, math.ceil(len(serie) / 16))
        ancho_barra = 22 if len(serie) <= 40 else None
        mejor = r["mejor"]
        columnas = []
        for i, punto in enumerate(serie):
            valor = punto["ganancia"]
            alto = max(abs(y(valor) - y(Decimal("0"))), 3.0)
            arriba = y(valor) if valor >= 0 else y(Decimal("0"))
            color = COLOR_GRILLA if valor == 0 else (COLOR_ACCENT if valor > 0 else COLOR_DANGER)
            radio = ft.BorderRadius.only(top_left=4, top_right=4) if valor >= 0 else ft.BorderRadius.only(bottom_left=4, bottom_right=4)
            capas_columna: list[ft.Control] = [ft.Container(
                left=0, right=0, top=arriba, height=alto, alignment=ft.Alignment.TOP_CENTER,
                content=ft.Container(width=ancho_barra, height=alto, bgcolor=color, border_radius=radio),
            )]
            if mejor is not None and punto["inicio"] == mejor["inicio"]:
                capas_columna.append(ft.Container(left=-30, right=-30, top=arriba - 17, content=ft.Text(
                    formatear_precio(valor), size=11.5, weight=ft.FontWeight.BOLD, color=COLOR_TEXT,
                    text_align=ft.TextAlign.CENTER)))
            if i % cada == 0 or i == len(serie) - 1:
                capas_columna.append(ft.Container(left=-20, right=-20, top=ALTO_GRAFICO - EJE_X + 4, content=ft.Text(
                    etiqueta_bucket(punto["inicio"], agrupacion, larga=False), size=11, color=COLOR_TEXT_SOFT,
                    text_align=ft.TextAlign.CENTER)))
            columnas.append(ft.Container(
                expand=True, height=ALTO_GRAFICO, padding=ft.Padding.symmetric(horizontal=1),
                tooltip=f"{etiqueta_bucket(punto['inicio'], agrupacion, larga=True)} · {pesos(valor)}",
                content=ft.Stack(capas_columna, clip_behavior=ft.ClipBehavior.NONE),
            ))
        capas.append(ft.Container(left=EJE_Y, right=0, top=0, bottom=0, content=ft.Row(columnas, spacing=2)))
        grafico_cont.content = ft.Stack(capas, clip_behavior=ft.ClipBehavior.NONE)
        nombre = {"dia": "día", "semana": "semana", "mes": "mes"}[agrupacion]
        grafico_titulo.value = f"Ganancia bruta por {nombre}"

    # ================= Tablas =================
    def celda_num(texto: str, color: str | None = None, negrita: bool = False) -> ft.DataCell:
        return ft.DataCell(ft.Text(texto, color=color, weight=ft.FontWeight.BOLD if negrita else None,
                                   text_align=ft.TextAlign.RIGHT))

    def columnas(*titulos: str, numericas: int = 0) -> list[ft.DataColumn]:
        return [ft.DataColumn(ft.Text(t), numeric=i >= len(titulos) - numericas) for i, t in enumerate(titulos)]

    tabla_productos = ft.DataTable(columns=columnas("Producto", "Unid.", "Ventas netas", "Costo", "Ganancia", "Margen", numericas=5), rows=[])
    tabla_perdidas = ft.DataTable(columns=columnas("Motivo", "Unid.", "A costo", numericas=2), rows=[])
    tabla_con_perdida = ft.DataTable(columns=columnas("Venta", "Cliente", "Ganancia", numericas=1), rows=[])
    sin_perdidas_texto = ft.Text("No hubo roturas ni ajustes en el período.", size=13, color=COLOR_SUCCESS)
    sin_ventas_con_perdida_texto = ft.Text("Ninguna venta por debajo del costo.", size=13, color=COLOR_SUCCESS)

    def panel(titulo: str, sub: str, *controles: ft.Control, expand: int | None = None) -> ft.Container:
        return ft.Container(
            expand=expand, bgcolor=COLOR_SURFACE, border=ft.Border.all(1, COLOR_BORDER), border_radius=12,
            padding=ft.Padding.symmetric(horizontal=18, vertical=16),
            content=ft.Column([
                ft.Text(titulo, size=15, weight=ft.FontWeight.BOLD),
                ft.Text(sub, size=12, color=COLOR_TEXT_SOFT),
                *controles,
            ], spacing=6),
        )

    # ================= Refresco =================
    def refrescar() -> None:
        try:
            desde = date.fromisoformat((desde_field.value or "").strip())
            hasta = date.fromisoformat((hasta_field.value or "").strip())
            r = ganancias_service.resumen(desde, hasta)
        except ValueError as ex:
            mensaje = str(ex) if "anterior" in str(ex) else "Las fechas van con formato AAAA-MM-DD (ej. 2026-10-01)"
            mostrar_mensaje(mensaje)
            return
        pintar_chips()
        cantidad = r["cantidad_ventas"]
        subtitulo.value = f"Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y} · {cantidad} venta{'' if cantidad == 1 else 's'}"

        margen = ft.Container(
            content=ft.Text(f"Margen {porcentaje(r['margen'])}", size=12, weight=ft.FontWeight.BOLD, color=COLOR_SUCCESS),
            bgcolor=COLOR_SUCCESS_WASH, border_radius=999, padding=ft.Padding.symmetric(horizontal=8, vertical=2),
        )
        kpis_row.controls = [
            tile("Ventas netas", pesos(r["ventas_netas"]),
                 nota(f"Vendido {formatear_precio(r['vendido'])} − notas de crédito {formatear_precio(r['acreditado'])} · sin IVA")),
            operador("−"),
            tile("Costo de lo vendido", pesos(r["costo"]), nota("Costo real de los lotes (FIFO)")),
            operador("="),
            tile("Ganancia bruta", pesos(r["ganancia_bruta"]), ft.Row([margen]),
                 color_valor=COLOR_ACCENT_STRONG if r["ganancia_bruta"] >= 0 else COLOR_DANGER),
            operador("−"),
            tile("Pérdidas de stock", pesos(r["perdidas"]), nota("Roturas, vencimientos y faltantes, a costo"),
                 color_valor=COLOR_DANGER if r["perdidas"] > 0 else COLOR_TEXT),
            operador("="),
            tile("Resultado de la mercadería", pesos(r["resultado"]),
                 nota(f"{porcentaje(r['resultado_porcentaje'])} de las ventas netas"),
                 color_valor=COLOR_ACCENT_STRONG if r["resultado"] >= 0 else COLOR_DANGER,
                 fondo=COLOR_ACCENT_WASH, grande=True),
        ]
        contexto = []
        if r["cantidad_ventas"]:
            contexto += [dato("Ticket promedio", pesos(r["ticket_promedio"])),
                         dato("Ganancia por venta", pesos(r["ganancia_por_venta"]))]
        if r["mejor"] is not None and r["agrupacion"] == "dia" and len(r["serie"]) > 1:
            m = r["mejor"]
            contexto.append(dato("Mejor día", f"{DIAS[m['inicio'].weekday()]} {m['inicio']:%d/%m} · {pesos(m['ganancia'])}"))
        if not r["cantidad_ventas"]:
            contexto.append(ft.Text("No hay ventas en el período.", size=13, color=COLOR_TEXT_SOFT))
        contexto_row.controls = contexto

        construir_grafico(r)

        maximo = max((p["ganancia"] for p in r["productos"]), default=Decimal("0"))
        tabla_productos.rows = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Row([ft.Text(p["codigo"], size=11.5, color=COLOR_TEXT_SOFT, font_family="Consolas"),
                                    ft.Text(p["nombre"])], spacing=6, tight=True)),
                celda_num(unidades(p["unidades"])),
                celda_num(formatear_precio(p["ventas"])),
                celda_num(formatear_precio(p["costo"])),
                ft.DataCell(ft.Row([
                    ft.Text(formatear_precio(p["ganancia"]), color=COLOR_DANGER if p["ganancia"] < 0 else None,
                            weight=ft.FontWeight.BOLD if p["ganancia"] < 0 else None),
                    ft.Container(width=max(2, int(48 * p["ganancia"] / maximo)) if maximo > 0 and p["ganancia"] > 0 else 0,
                                 height=6, border_radius=3, bgcolor=COLOR_ACCENT, opacity=0.55),
                ], spacing=8, tight=True)),
                celda_num(porcentaje(p["margen"]), COLOR_DANGER if p["margen"] is not None and p["margen"] < 0 else None),
            ])
            for p in r["productos"]
        ] + ([ft.DataRow(cells=[
            ft.DataCell(ft.Text("Total", weight=ft.FontWeight.BOLD)),
            celda_num(""),
            celda_num(formatear_precio(r["ventas_netas"]), negrita=True),
            celda_num(formatear_precio(r["costo"]), negrita=True),
            celda_num(formatear_precio(r["ganancia_bruta"]), negrita=True),
            celda_num(porcentaje(r["margen"]), negrita=True),
        ])] if r["productos"] else [])

        tabla_perdidas.rows = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Text(m["motivo"])),
                celda_num(unidades(m["unidades"])),
                celda_num(formatear_precio(m["valor"]), COLOR_DANGER if m["valor"] > 0 else COLOR_SUCCESS),
            ])
            for m in r["perdidas_por_motivo"]
        ]
        tabla_perdidas.visible = bool(r["perdidas_por_motivo"])
        sin_perdidas_texto.visible = not r["perdidas_por_motivo"]

        tabla_con_perdida.rows = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Text(v["numero"], weight=ft.FontWeight.BOLD, color=COLOR_DANGER)),
                ft.DataCell(ft.Text(v["cliente"] or "-")),
                celda_num(formatear_precio(v["ganancia"]), COLOR_DANGER, negrita=True),
            ])
            for v in r["ventas_con_perdida"]
        ]
        tabla_con_perdida.visible = bool(r["ventas_con_perdida"])
        sin_ventas_con_perdida_texto.visible = not r["ventas_con_perdida"]
        page.update()

    vista = ft.Column(
        [
            ft.Column([ft.Text("Ganancias", size=22, weight=ft.FontWeight.BOLD), subtitulo], spacing=2),
            ft.Row([*chips.values(), ft.Container(width=8), desde_field, hasta_field, ver_button, rango_personalizado_texto],
                   spacing=8, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Container(
                content=kpis_row, border=ft.Border.all(1, COLOR_BORDER), border_radius=12,
                bgcolor=COLOR_SURFACE, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            ),
            ft.Text("No incluye los gastos del negocio (alquiler, luz, sueldos): es lo que deja la mercadería.",
                    size=12.5, color=COLOR_TEXT_SOFT),
            contexto_row,
            ft.Container(
                bgcolor=COLOR_SURFACE, border=ft.Border.all(1, COLOR_BORDER), border_radius=12,
                padding=ft.Padding.symmetric(horizontal=18, vertical=16),
                content=ft.Column([grafico_titulo, grafico_sub, ft.Container(height=6), grafico_cont], spacing=4),
            ),
            ft.Row(
                [
                    panel("Por producto", "Ordenado por lo que deja cada producto en el período.",
                          con_scroll_horizontal(tabla_productos), expand=3),
                    ft.Column([
                        panel("Pérdidas de stock", "Ajustes de Movimientos, a costo real del lote.",
                              tabla_perdidas, sin_perdidas_texto),
                        panel("Ventas con pérdida", "Se vendieron por debajo del costo (con sus notas de crédito).",
                              tabla_con_perdida, sin_ventas_con_perdida_texto),
                    ], expand=2, spacing=18, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                ],
                spacing=18, vertical_alignment=ft.CrossAxisAlignment.START,
            ),
        ],
        expand=True, spacing=16, scroll=ft.ScrollMode.AUTO,
    )
    elegir_periodo("mes")
    return vista
