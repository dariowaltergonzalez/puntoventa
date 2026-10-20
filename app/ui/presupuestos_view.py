from decimal import Decimal

import flet as ft

from app.services import presupuestos_service
from app.services.exceptions import PresupuestoNoDisponibleError
from app.shared.money import formatear_cantidad, formatear_porcentaje, formatear_precio
from app.ui.campos import FILTRO_DECIMALES, parsear_decimal_ar_opcional
from app.ui.listados import con_scroll_horizontal
from app.ui.theme import (
    COLOR_ACCENT,
    COLOR_ACCENT_STRONG,
    COLOR_ACCENT_WASH,
    COLOR_BORDER,
    COLOR_DANGER,
    COLOR_DANGER_WASH,
    COLOR_SUCCESS,
    COLOR_SUCCESS_WASH,
    COLOR_SURFACE,
    COLOR_TEXT,
    COLOR_TEXT_SOFT,
    COLOR_WARNING,
    COLOR_WARNING_WASH,
)
from app.ui.componentes import ESPACIO_PANTALLA, campo_buscar, encabezado_pantalla

EXCEPCIONES_NEGOCIO = (PresupuestoNoDisponibleError, ValueError)
FILTROS = [("vigente", "Vigentes"), ("vencido", "Vencidos"), ("convertido", "Convertidos"), ("rechazado", "Rechazados"), (None, "Todos")]
COLORES_ESTADO = {
    "vigente": (COLOR_SUCCESS, COLOR_SUCCESS_WASH),
    "vencido": (COLOR_WARNING, COLOR_WARNING_WASH),
    "convertido": (COLOR_ACCENT_STRONG, COLOR_ACCENT_WASH),
    "rechazado": (COLOR_DANGER, COLOR_DANGER_WASH),
}
COLUMNAS = [("NUMERO", 70), ("CLIENTE", 180), ("EMISION", 80), ("NETO", 100), ("IVA", 85), ("TOTAL", 105),
            ("GANANCIA ($ / %)", 150), ("ESTADO", 105), ("VALIDEZ / RESULTADO", 220)]
CENTAVO = Decimal("1.00")


def pesos(valor: Decimal) -> str:
    return f"−{formatear_precio(-valor)}" if valor < 0 else formatear_precio(valor)


def margen(valor: Decimal | None) -> str:
    return "-" if valor is None else f"{str(valor).replace('.', ',')} %"


def PresupuestosView(page: ft.Page) -> ft.Control:
    estado = {"filtro": "vigente", "rechazando": None, "abierto": None}

    def mostrar_mensaje(texto: str) -> None:
        page.show_dialog(ft.SnackBar(ft.Text(texto)))

    def abrir_en_caja(presupuesto_id: int | None) -> None:
        # La caja (Ventas) es otra pantalla: app_shell sabe navegar hasta ahi y dejarle el pedido.
        navegar = getattr(page, "abrir_presupuesto_en_caja", None)
        if navegar is not None:
            navegar(presupuesto_id)

    # ================= Filtros =================
    chips: dict = {}
    buscador_field = campo_buscar("Numero o cliente")
    lista = ft.Column(spacing=8)
    sin_resultados_texto = ft.Text("", color=COLOR_TEXT_SOFT)

    def elegir_filtro(clave: str | None) -> None:
        estado.update({"filtro": clave, "rechazando": None, "abierto": None})
        refrescar()

    for clave, texto in FILTROS:
        chips[clave] = ft.Container(
            content=ft.Text(texto, size=13), padding=ft.Padding.symmetric(horizontal=14, vertical=8),
            border_radius=999, on_click=lambda e, c=clave: elegir_filtro(c), ink=True,
        )
    buscador_field.on_change = lambda e: refrescar()

    # ================= Piezas de la fila =================
    def pastilla(estado_clave: str, texto: str) -> ft.Container:
        color, fondo = COLORES_ESTADO[estado_clave]
        return ft.Container(
            content=ft.Text(texto, size=12, weight=ft.FontWeight.BOLD, color=color),
            bgcolor=fondo, border_radius=999, padding=ft.Padding.symmetric(horizontal=10, vertical=3),
        )

    def texto_validez(pr: dict) -> str:
        if pr["estado"] == "vigente":
            dias = pr["dias_restantes"]
            cuando = "hoy" if dias == 0 else ("mañana" if dias == 1 else f"en {dias} dias")
            return f"Vence {pr['fecha_validez']:%d/%m} ({cuando})"
        if pr["estado"] == "vencido":
            return f"Vencio el {pr['fecha_validez']:%d/%m}"
        if pr["estado"] == "convertido":
            return f"Venta {pr['venta_numero']}"
        return pr["motivo_rechazo"] or "Sin motivo"

    def celda_ganancia(pr: dict) -> ft.Control:
        """Estimada mientras esta abierto (todavia no se vendio); real una vez convertido."""
        if pr["estado"] == "convertido":
            valor, porc, rotulo = pr["ganancia_real"], pr["margen_real"], "real"
        elif pr["estado"] == "rechazado":
            return ft.Text("-", color=COLOR_TEXT_SOFT)
        else:
            valor, porc, rotulo = pr["ganancia_estimada"], pr["margen_estimado"], "estimada"
        return ft.Column([
            ft.Text(f"{pesos(valor)} ({margen(porc)})", weight=ft.FontWeight.BOLD,
                    color=COLOR_DANGER if valor < 0 else COLOR_ACCENT_STRONG),
            ft.Text(rotulo, size=10.5, color=COLOR_TEXT_SOFT, italic=True),
        ], spacing=0, tight=True)

    # ================= Detalle (la mesa de trabajo del dueño) =================
    def detalle(pr: dict) -> list[ft.Control]:
        editable = pr["estado"] == "vigente"
        campos_precio: dict[int, ft.TextField] = {}
        guardar_precios_button = ft.ElevatedButton("Guardar precios", icon=ft.Icons.SAVE, visible=False)

        def fila_item(i: dict) -> ft.DataRow:
            desc = (i["descuento_item_porcentaje"] or Decimal("0")) / 100
            subtotal_texto = ft.Text(pesos((i["cantidad"] * i["precio_unitario"] * (1 - desc)).quantize(CENTAVO)))
            ganancia_texto = ft.Text(f"{pesos(i['ganancia_estimada'])} ({margen(i['margen_estimado'])})",
                                     weight=ft.FontWeight.BOLD,
                                     color=COLOR_DANGER if i["ganancia_estimada"] < 0 else COLOR_ACCENT_STRONG)
            nombre = ft.Row([ft.Text(i["descripcion_libre"] or f"{i['producto_codigo']} - {i['producto_nombre']}")]
                            + ([ft.Container(ft.Text("a mano", size=10.5, color=COLOR_WARNING, weight=ft.FontWeight.BOLD),
                                             bgcolor=COLOR_WARNING_WASH, border_radius=999,
                                             padding=ft.Padding.symmetric(horizontal=7, vertical=1),
                                             tooltip="Precio cambiado a mano: no es el de la lista")]
                               if i["precio_manual"] else []), spacing=6, tight=True)
            if editable:
                campo = ft.TextField(value=formatear_precio(i["precio_unitario"]), width=120, dense=True,
                                     text_align=ft.TextAlign.RIGHT, input_filter=FILTRO_DECIMALES)
                campos_precio[i["id"]] = campo

                def previsualizar(e: ft.ControlEvent, item=i, sub=subtotal_texto, gan=ganancia_texto, c=campo) -> None:
                    # Vista previa al tipear: misma cuenta que el servicio (precio x cantidad con sus
                    # descuentos, menos el costo estimado). Al guardar se recalcula todo exacto.
                    try:
                        precio = parsear_decimal_ar_opcional(c.value, "El precio") or Decimal("0")
                    except ValueError:
                        return
                    bruto = item["cantidad"] * precio * (1 - (item["descuento_item_porcentaje"] or Decimal("0")) / 100)
                    ingreso = bruto * pr["factor_descuentos"]
                    ganancia = (ingreso - item["costo_estimado"]).quantize(CENTAVO)
                    porc = (100 * ganancia / ingreso).quantize(Decimal("0.1")) if ingreso > 0 else None
                    sub.value = pesos(bruto.quantize(CENTAVO))
                    gan.value = f"{pesos(ganancia)} ({margen(porc)})"
                    gan.color = COLOR_DANGER if ganancia < 0 else COLOR_ACCENT_STRONG
                    guardar_precios_button.visible = True
                    page.update()

                campo.on_change = previsualizar
                precio_celda = ft.DataCell(campo)
            else:
                precio_celda = ft.DataCell(ft.Text(formatear_precio(i["precio_unitario"])))
            return ft.DataRow(cells=[
                ft.DataCell(nombre),
                ft.DataCell(ft.Text(formatear_cantidad(i["cantidad"]))),
                precio_celda,
                ft.DataCell(ft.Text(f"{formatear_porcentaje(i['descuento_item_porcentaje'])}%" if i["descuento_item_porcentaje"] else "-")),
                ft.DataCell(subtotal_texto),
                ft.DataCell(ft.Text(pesos(i["costo_estimado"]), color=COLOR_TEXT_SOFT)),
                ft.DataCell(ganancia_texto),
            ])

        def guardar_precios(e: ft.ControlEvent) -> None:
            try:
                precios = {item_id: parsear_decimal_ar_opcional(c.value, "El precio") for item_id, c in campos_precio.items()}
                nuevo = presupuestos_service.ajustar_precios(pr["id"], precios)
            except EXCEPCIONES_NEGOCIO as ex:
                mostrar_mensaje(str(ex))
                return
            mostrar_mensaje(f"Precios de {pr['numero']} guardados: total {formatear_precio(nuevo['total'])}, "
                            f"ganancia estimada {pesos(nuevo['ganancia_estimada'])} ({margen(nuevo['margen_estimado'])})")
            estado["abierto"] = pr["id"]
            refrescar()

        guardar_precios_button.on_click = guardar_precios
        tabla = ft.DataTable(
            columns=[ft.DataColumn(ft.Text(t), numeric=i > 0) for i, t in enumerate(
                ["Producto / Descripcion", "Cantidad", "Precio" + (" (editable)" if editable else ""), "% desc.",
                 "Subtotal", "Costo est.", "Ganancia est."])],
            rows=[fila_item(i) for i in pr["items"]],
        )
        condiciones = [f"Subtotal {formatear_precio(pr['subtotal'])}"]
        if pr["descuento_cliente_porcentaje"]:
            condiciones.append(f"cliente -{formatear_porcentaje(pr['descuento_cliente_porcentaje'])}%")
        if pr["descuento_total_porcentaje"]:
            condiciones.append(f"desc. total -{formatear_porcentaje(pr['descuento_total_porcentaje'])}%")
        condiciones += [f"Neto {formatear_precio(pr['neto'])}", f"IVA {formatear_precio(pr['iva_monto'])}",
                        f"Total {formatear_precio(pr['total'])}"]
        controles: list[ft.Control] = [
            con_scroll_horizontal(tabla),
            ft.Text("  ·  ".join(condiciones), color=COLOR_TEXT_SOFT),
        ]
        if pr["estado"] in ("vigente", "vencido"):
            controles.append(ft.Text(
                "Ganancia estimada: lo que dejaria si se vendiera hoy (costo de los lotes que saldrian primero). "
                "La real se calcula recien al venderlo.", size=12, color=COLOR_TEXT_SOFT, italic=True))
        if pr["observacion"]:
            controles.append(ft.Text(f"Observacion: {pr['observacion']}", color=COLOR_TEXT_SOFT))
        if pr["avisos"] and pr["estado"] in ("vigente", "vencido"):
            controles.append(ft.Text("Ojo: " + "; ".join(pr["avisos"]), color=COLOR_WARNING))
        if estado["rechazando"] == pr["id"]:
            motivo_field = ft.TextField(label="Motivo (opcional): caro, compro en otro lado...", expand=True, dense=True,
                                        autofocus=True)
            controles.append(ft.Container(
                padding=10, border=ft.Border.all(1, COLOR_DANGER), border_radius=8,
                content=ft.Row([
                    ft.Text(f"Marcar {pr['numero']} como rechazado", weight=ft.FontWeight.BOLD, color=COLOR_DANGER),
                    motivo_field,
                    ft.ElevatedButton("Confirmar", on_click=lambda e: rechazar(pr, motivo_field.value)),
                    ft.TextButton("Cancelar", on_click=lambda e: mostrar_rechazo(None)),
                ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ))
        botones = ([guardar_precios_button] if editable else []) + acciones(pr)
        if botones:
            controles.append(ft.Row(botones, spacing=8, wrap=True))
        return [ft.Container(ft.Column(controles, spacing=10), padding=ft.Padding.symmetric(horizontal=16, vertical=8))]

    def acciones(pr: dict) -> list[ft.Control]:
        if pr["estado"] == "vigente":
            return [
                ft.ElevatedButton("Abrir en la caja", icon=ft.Icons.POINT_OF_SALE,
                                  tooltip="Para cobrarlo (se convierte en venta) o modificar los productos y guardar con F4",
                                  on_click=lambda e: abrir_en_caja(pr["id"])),
                ft.TextButton("Extender validez", icon=ft.Icons.EVENT_REPEAT,
                              tooltip="Le da 15 dias mas desde hoy, con los mismos precios",
                              on_click=lambda e: extender(pr)),
                ft.TextButton("Rechazado", icon=ft.Icons.THUMB_DOWN_OUTLINED, on_click=lambda e: mostrar_rechazo(pr)),
            ]
        if pr["estado"] == "vencido":
            return [
                ft.ElevatedButton("Renovar con precios de hoy", icon=ft.Icons.EVENT_REPEAT, on_click=lambda e: renovar(pr)),
                ft.TextButton("Rechazado", icon=ft.Icons.THUMB_DOWN_OUTLINED, on_click=lambda e: mostrar_rechazo(pr)),
            ]
        return []

    def fila(pr: dict) -> ft.Control:
        valores = [
            ft.Text(pr["numero"], weight=ft.FontWeight.BOLD, color=COLOR_TEXT),
            ft.Text(pr["cliente_nombre"], no_wrap=True),
            ft.Text(pr["fecha_creacion"][8:10] + "/" + pr["fecha_creacion"][5:7]),
            ft.Text(formatear_precio(pr["neto"])),
            ft.Text(formatear_precio(pr["iva_monto"]), color=COLOR_TEXT_SOFT),
            ft.Text(formatear_precio(pr["total"]), weight=ft.FontWeight.BOLD),
            celda_ganancia(pr),
            ft.Row([pastilla(pr["estado"], pr["estado_label"].split(" ")[0])], tight=True),
            ft.Text(texto_validez(pr), color=COLOR_DANGER if pr["estado"] == "vencido" else COLOR_TEXT_SOFT, no_wrap=True),
        ]
        titulo = ft.Row([ft.Container(v, width=w) for v, (_, w) in zip(valores, COLUMNAS)], spacing=12)
        return ft.Container(
            bgcolor=COLOR_SURFACE, border=ft.Border.all(1, COLOR_BORDER), border_radius=10,
            content=ft.ExpansionTile(
                title=titulo, controls=detalle(pr), affinity=ft.TileAffinity.LEADING,
                tile_padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                expanded=pr["id"] in (estado["rechazando"], estado["abierto"]),
            ),
        )

    # ================= Acciones =================
    def renovar(pr: dict) -> None:
        try:
            nuevo = presupuestos_service.renovar_presupuesto(pr["id"])
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))
            return
        cambio = "" if nuevo["total"] == pr["total"] else f" (total {formatear_precio(pr['total'])} → {formatear_precio(nuevo['total'])})"
        mostrar_mensaje(f"{pr['numero']} renovado con los precios de hoy, vence el {nuevo['fecha_validez']:%d/%m}{cambio}")
        if estado["filtro"] == "vencido":
            estado["filtro"] = "vigente"
        estado["abierto"] = pr["id"]
        refrescar()

    def extender(pr: dict) -> None:
        try:
            nuevo = presupuestos_service.extender_validez(pr["id"])
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))
            return
        mostrar_mensaje(f"{pr['numero']} ahora vence el {nuevo['fecha_validez']:%d/%m}, con los mismos precios")
        estado["abierto"] = pr["id"]
        refrescar()

    def mostrar_rechazo(pr: dict | None) -> None:
        estado["rechazando"] = pr["id"] if pr else None
        refrescar()

    def rechazar(pr: dict, motivo: str | None) -> None:
        try:
            presupuestos_service.rechazar_presupuesto(pr["id"], motivo)
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))
            return
        estado["rechazando"] = None
        mostrar_mensaje(f"{pr['numero']} marcado como rechazado")
        refrescar()

    # ================= Refresco =================
    def refrescar() -> None:
        conteo = presupuestos_service.contar_por_estado()
        for clave, texto in FILTROS:
            chip, activo = chips[clave], clave == estado["filtro"]
            cantidad = sum(conteo.values()) if clave is None else conteo[clave]
            chip.content.value = f"{'✓ ' if activo else ''}{texto} ({cantidad})"
            chip.bgcolor = COLOR_ACCENT if activo else COLOR_SURFACE
            chip.border = ft.Border.all(1, COLOR_ACCENT if activo else COLOR_BORDER)
            chip.content.color = ft.Colors.WHITE if activo else COLOR_TEXT
            chip.content.weight = ft.FontWeight.W_500 if activo else None
        presupuestos = presupuestos_service.listar_presupuestos(estado["filtro"], buscador_field.value)
        lista.controls = [fila(pr) for pr in presupuestos]
        sin_resultados_texto.visible = not presupuestos
        sin_resultados_texto.value = (
            "No hay presupuestos con ese filtro. Se arman en la caja: cargás los productos y apretás F4."
            if not (buscador_field.value or "").strip() else "Ningún presupuesto coincide con la búsqueda."
        )
        page.update()

    encabezado_columnas = ft.Row(
        [ft.Container(ft.Text(t, size=11.5, weight=ft.FontWeight.BOLD, color=COLOR_TEXT_SOFT), width=w) for t, w in COLUMNAS],
        spacing=12,
    )
    vista = ft.Column(
        [
            ft.Row([
                ft.Container(encabezado_pantalla(
                    "Presupuestos", "Cotizaciones con precios congelados. Se arman en la caja (F4); acá se ajustan los precios "
                    "mirando la ganancia estimada, y se abren para cobrarlos."), expand=True),
                ft.ElevatedButton("Nuevo presupuesto", icon=ft.Icons.ADD, on_click=lambda e: abrir_en_caja(None)),
            ], vertical_alignment=ft.CrossAxisAlignment.START),
            ft.Row([*chips.values(), buscador_field], spacing=8, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Container(encabezado_columnas, padding=ft.Padding.only(left=52)),
            lista,
            sin_resultados_texto,
        ],
        expand=True, spacing=ESPACIO_PANTALLA, scroll=ft.ScrollMode.AUTO,
    )
    refrescar()
    return vista
