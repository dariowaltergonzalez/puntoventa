from decimal import Decimal

import flet as ft

from app.services import presupuestos_service
from app.shared.money import formatear_cantidad, formatear_porcentaje, formatear_precio
from app.ui.campos import FILTRO_DECIMALES, parsear_decimal_ar_opcional
from app.ui.componentes import (
    ESPACIO_PANTALLA,
    ERRORES_PARA_AVISAR,
    TONO_CURSO,
    TONO_ESPERA,
    TONO_NO,
    TONO_OK,
    Columna,
    Lista,
    accion_abrir,
    accion_cambiar,
    accion_con_motivo,
    avisar,
    barra,
    boton_principal,
    botones_formulario,
    campo_buscar,
    encabezado_pantalla,
    etiqueta_estado,
    tabla_simple,
    tarjeta,
)
from app.ui.theme import (
    COLOR_ACCENT,
    COLOR_ACCENT_STRONG,
    COLOR_BORDER,
    COLOR_DANGER,
    COLOR_SURFACE,
    COLOR_TEXT,
    COLOR_TEXT_SOFT,
    COLOR_WARNING,
    COLOR_WARNING_WASH,
)

FILTROS = [("vigente", "Vigentes"), ("vencido", "Vencidos"), ("convertido", "Convertidos"), ("rechazado", "Rechazados"), (None, "Todos")]
TONOS_ESTADO = {"vigente": TONO_OK, "vencido": TONO_ESPERA, "convertido": TONO_CURSO, "rechazado": TONO_NO}
CENTAVO = Decimal("1.00")


def pesos(valor: Decimal) -> str:
    return f"−{formatear_precio(-valor)}" if valor < 0 else formatear_precio(valor)


def margen(valor: Decimal | None) -> str:
    return "-" if valor is None else f"{str(valor).replace('.', ',')} %"


def PresupuestosView(page: ft.Page) -> ft.Control:
    estado = {"filtro": "vigente"}

    def abrir_en_caja(presupuesto_id: int | None) -> None:
        # La caja (Ventas) es otra pantalla: app_shell sabe navegar hasta ahi y dejarle el pedido.
        navegar = getattr(page, "abrir_presupuesto_en_caja", None)
        if navegar is not None:
            navegar(presupuesto_id)

    # ================= Filtros =================
    chips: dict = {}
    buscador_field = campo_buscar("Numero o cliente", al_cambiar=lambda: filtrar())

    def elegir_filtro(clave: str | None) -> None:
        estado["filtro"] = clave
        filtrar()

    for clave, texto in FILTROS:
        chips[clave] = ft.Container(
            content=ft.Text(texto, size=13), padding=ft.Padding.symmetric(horizontal=14, vertical=8),
            border_radius=999, on_click=lambda e, c=clave: elegir_filtro(c), ink=True,
        )

    # ================= Lista =================
    lista = Lista(
        [
            Columna("Numero", ancho=80, orden="numero"), Columna("Cliente", peso=3, orden="cliente_nombre"),
            Columna("Emision", ancho=80, orden="fecha_creacion"), Columna("Neto", ancho=100, derecha=True),
            Columna("IVA", ancho=90, derecha=True), Columna("Total", ancho=110, derecha=True, orden="total"),
            Columna("Ganancia ($ / %)", ancho=160, derecha=True), Columna("Estado", ancho=100),
            Columna("Validez / resultado", peso=2), Columna("Acciones", ancho=170, derecha=True),
        ],
        al_cambiar_pagina=lambda: refrescar(), nombre="presupuestos", con_hijos=True,
        orden_inicial=("fecha_creacion", True), sin_datos="",
    )

    def texto_validez(pr: dict) -> ft.Text:
        if pr["estado"] == "vigente":
            dias = pr["dias_restantes"]
            cuando = "hoy" if dias == 0 else ("mañana" if dias == 1 else f"en {dias} dias")
            texto = f"Vence {pr['fecha_validez']:%d/%m} ({cuando})"
        elif pr["estado"] == "vencido":
            texto = f"Vencio el {pr['fecha_validez']:%d/%m}"
        elif pr["estado"] == "convertido":
            texto = f"Venta {pr['venta_numero']}"
        else:
            texto = pr["motivo_rechazo"] or "Sin motivo"
        return ft.Text(texto, color=COLOR_DANGER if pr["estado"] == "vencido" else COLOR_TEXT_SOFT)

    def celda_ganancia(pr: dict) -> ft.Control:
        """Estimada mientras esta abierto (todavia no se vendio); real una vez convertido."""
        if pr["estado"] == "rechazado":
            return ft.Text("-", color=COLOR_TEXT_SOFT)
        real = pr["estado"] == "convertido"
        valor, porc = (pr["ganancia_real"], pr["margen_real"]) if real else (pr["ganancia_estimada"], pr["margen_estimado"])
        return ft.Column([
            ft.Text(f"{pesos(valor)} ({margen(porc)})", weight=ft.FontWeight.BOLD,
                    color=COLOR_DANGER if valor < 0 else COLOR_ACCENT_STRONG),
            ft.Text("real" if real else "estimada", size=10.5, color=COLOR_TEXT_SOFT, italic=True),
        ], spacing=0, tight=True, horizontal_alignment=ft.CrossAxisAlignment.END)

    def nombre_item(i: dict) -> ft.Control:
        return ft.Row([ft.Text(i["descripcion_libre"] or f"{i['producto_codigo']} - {i['producto_nombre']}")]
                      + ([ft.Container(ft.Text("a mano", size=10.5, color=COLOR_WARNING, weight=ft.FontWeight.BOLD),
                                       bgcolor=COLOR_WARNING_WASH, border_radius=999,
                                       padding=ft.Padding.symmetric(horizontal=7, vertical=1),
                                       tooltip="Precio cambiado a mano: no es el de la lista")]
                         if i["precio_manual"] else []), spacing=6, tight=True)

    def condiciones(pr: dict) -> ft.Text:
        partes = [f"Subtotal {formatear_precio(pr['subtotal'])}"]
        if pr["descuento_cliente_porcentaje"]:
            partes.append(f"cliente -{formatear_porcentaje(pr['descuento_cliente_porcentaje'])}%")
        if pr["descuento_total_porcentaje"]:
            partes.append(f"desc. total -{formatear_porcentaje(pr['descuento_total_porcentaje'])}%")
        partes += [f"Neto {formatear_precio(pr['neto'])}", f"IVA {formatear_precio(pr['iva_monto'])}",
                   f"Total {formatear_precio(pr['total'])}"]
        return ft.Text("  ·  ".join(partes), color=COLOR_TEXT_SOFT)

    def hijos(pr: dict) -> ft.Control:
        controles: list[ft.Control] = [
            tabla_simple(
                ["Producto / descripcion", "Cantidad", "Precio", "% desc.", "Subtotal", "Costo est.", "Ganancia est."],
                [[nombre_item(i), formatear_cantidad(i["cantidad"]), formatear_precio(i["precio_unitario"]),
                  f"{formatear_porcentaje(i['descuento_item_porcentaje'])}%" if i["descuento_item_porcentaje"] else "-",
                  pesos((i["cantidad"] * i["precio_unitario"] * (1 - (i["descuento_item_porcentaje"] or Decimal("0")) / 100)).quantize(CENTAVO)),
                  pesos(i["costo_estimado"]),
                  ft.Text(f"{pesos(i['ganancia_estimada'])} ({margen(i['margen_estimado'])})", weight=ft.FontWeight.BOLD,
                          color=COLOR_DANGER if i["ganancia_estimada"] < 0 else COLOR_ACCENT_STRONG)]
                 for i in pr["items"]],
                derecha=[1, 2, 3, 4, 5, 6],
            ),
            condiciones(pr),
        ]
        if pr["observacion"]:
            controles.append(ft.Text(f"Observacion: {pr['observacion']}", color=COLOR_TEXT_SOFT))
        if pr["avisos"] and pr["estado"] in ("vigente", "vencido"):
            controles.append(ft.Text("Ojo: " + "; ".join(pr["avisos"]), color=COLOR_WARNING))
        return ft.Column(controles, spacing=8)

    def celdas(pr: dict) -> list:
        e = pr["estado"]
        no_vigente = None if e == "vigente" else f"esta {pr['estado_label'].split(' ')[0].lower()}"
        abierto = e in ("vigente", "vencido")
        return [
            ft.Text(pr["numero"], weight=ft.FontWeight.BOLD), pr["cliente_nombre"],
            f"{pr['fecha_creacion'][8:10]}/{pr['fecha_creacion'][5:7]}",
            formatear_precio(pr["neto"]), ft.Text(formatear_precio(pr["iva_monto"]), color=COLOR_TEXT_SOFT),
            ft.Text(formatear_precio(pr["total"]), weight=ft.FontWeight.BOLD), celda_ganancia(pr),
            etiqueta_estado(pr["estado_label"].split(" ")[0], TONOS_ESTADO[e]), texto_validez(pr),
            ft.Row([
                accion_abrir(ft.Icons.POINT_OF_SALE, "Abrir en la caja (para cobrarlo o cambiar productos)",
                             lambda pr=pr: abrir_en_caja(pr["id"]), por_que_no=no_vigente),
                accion_abrir(ft.Icons.EDIT, "Ajustar precios mirando la ganancia", lambda pr=pr: ir_a_ajustar(pr),
                             por_que_no=no_vigente),
                accion_cambiar(
                    ft.Icons.EVENT_REPEAT,
                    "Renovar con los precios de hoy" if e == "vencido" else "Extender la validez 15 dias, mismos precios",
                    lambda pr=pr: renovar(pr) if pr["estado"] == "vencido" else extender(pr),
                    por_que_no=None if abierto else f"esta {pr['estado_label'].split(' ')[0].lower()}",
                ),
                accion_con_motivo(
                    ft.Icons.THUMB_DOWN_OUTLINED, "Marcar rechazado", f"{pr['numero']}: el cliente no lo acepto",
                    "Queda como rechazado, con el motivo a la vista (caro, compro en otro lado...).",
                    lambda motivo, pr=pr: rechazar(pr, motivo),
                    por_que_no=None if abierto else f"esta {pr['estado_label'].split(' ')[0].lower()}",
                ),
            ], spacing=0, tight=True),
        ]

    # ================= Acciones =================
    def renovar(pr: dict) -> str:
        nuevo = presupuestos_service.renovar_presupuesto(pr["id"])
        if estado["filtro"] == "vencido":
            estado["filtro"] = "vigente"
        refrescar()
        cambio = "" if nuevo["total"] == pr["total"] else f" (total {formatear_precio(pr['total'])} → {formatear_precio(nuevo['total'])})"
        return f"{pr['numero']} renovado con los precios de hoy, vence el {nuevo['fecha_validez']:%d/%m}{cambio}"

    def extender(pr: dict) -> str:
        nuevo = presupuestos_service.extender_validez(pr["id"])
        refrescar()
        return f"{pr['numero']} ahora vence el {nuevo['fecha_validez']:%d/%m}, con los mismos precios"

    def rechazar(pr: dict, motivo: str) -> str:
        presupuestos_service.rechazar_presupuesto(pr["id"], motivo)
        refrescar()
        return f"{pr['numero']} marcado como rechazado"

    def filtrar() -> None:
        lista.ir_al_principio()
        refrescar()

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
        lista.sin_datos = ("No hay presupuestos con ese filtro. Se arman en la caja: cargas los productos y apretas F4."
                           if not (buscador_field.value or "").strip() else "Ningun presupuesto coincide con la busqueda.")
        lista.mostrar(presupuestos_service.listar_presupuestos(estado["filtro"], buscador_field.value), celdas,
                      hijos=hijos, valor_orden=lambda pr, k: pr[k])
        page.update()

    seccion_lista = ft.Column([
        barra([*chips.values(), buscador_field],
              [boton_principal("Nuevo presupuesto", ft.Icons.ADD, lambda: abrir_en_caja(None))]),
        lista.control,
    ], spacing=ESPACIO_PANTALLA)

    # ================= Ajustar precios (pantalla aparte) =================
    ajustar_titulo = ft.Text("", size=15, weight=ft.FontWeight.BOLD)
    ajustar_tabla = ft.Column()
    ajustar_condiciones = ft.Column()
    ajustando: dict = {}
    campos_precio: dict[int, ft.TextField] = {}

    def ir_a_ajustar(pr: dict) -> None:
        ajustando.clear()
        ajustando.update(pr)
        campos_precio.clear()
        ajustar_titulo.value = f"Ajustar precios: {pr['numero']} · {pr['cliente_nombre']}"
        filas = []
        for i in pr["items"]:
            subtotal = ft.Text(pesos((i["cantidad"] * i["precio_unitario"] * (1 - (i["descuento_item_porcentaje"] or Decimal("0")) / 100)).quantize(CENTAVO)))
            ganancia = ft.Text(f"{pesos(i['ganancia_estimada'])} ({margen(i['margen_estimado'])})", weight=ft.FontWeight.BOLD,
                               color=COLOR_DANGER if i["ganancia_estimada"] < 0 else COLOR_ACCENT_STRONG)
            campo = ft.TextField(value=formatear_precio(i["precio_unitario"]), width=130, text_align=ft.TextAlign.RIGHT,
                                 input_filter=FILTRO_DECIMALES)
            campos_precio[i["id"]] = campo

            def previsualizar(e: ft.ControlEvent, item=i, sub=subtotal, gan=ganancia, c=campo) -> None:
                # Vista previa al tipear: misma cuenta que el servicio (precio x cantidad con sus
                # descuentos, menos el costo estimado). Al guardar se recalcula todo exacto.
                try:
                    precio = parsear_decimal_ar_opcional(c.value, "El precio") or Decimal("0")
                except ValueError:
                    return
                bruto = item["cantidad"] * precio * (1 - (item["descuento_item_porcentaje"] or Decimal("0")) / 100)
                ingreso = bruto * ajustando["factor_descuentos"]
                g = (ingreso - item["costo_estimado"]).quantize(CENTAVO)
                porc = (100 * g / ingreso).quantize(Decimal("0.1")) if ingreso > 0 else None
                sub.value = pesos(bruto.quantize(CENTAVO))
                gan.value = f"{pesos(g)} ({margen(porc)})"
                gan.color = COLOR_DANGER if g < 0 else COLOR_ACCENT_STRONG
                page.update()

            campo.on_change = previsualizar
            filas.append([nombre_item(i), formatear_cantidad(i["cantidad"]), campo,
                          f"{formatear_porcentaje(i['descuento_item_porcentaje'])}%" if i["descuento_item_porcentaje"] else "-",
                          subtotal, pesos(i["costo_estimado"]), ganancia])
        ajustar_tabla.controls = [tabla_simple(
            ["Producto / descripcion", "Cantidad", "Precio", "% desc.", "Subtotal", "Costo est.", "Ganancia est."],
            filas, derecha=[1, 3, 4, 5, 6],
        )]
        ajustar_condiciones.controls = [condiciones(pr)]
        seccion_lista.visible = False
        seccion_ajustar.visible = True
        page.update()

    def volver_a_lista() -> None:
        seccion_ajustar.visible = False
        seccion_lista.visible = True
        refrescar()

    def guardar_precios() -> None:
        try:
            precios = {item_id: parsear_decimal_ar_opcional(c.value, "El precio") for item_id, c in campos_precio.items()}
            nuevo = presupuestos_service.ajustar_precios(ajustando["id"], precios)
        except ERRORES_PARA_AVISAR as ex:
            avisar(page, str(ex), error=True)
            return
        volver_a_lista()
        avisar(page, f"Precios de {ajustando['numero']} guardados: total {formatear_precio(nuevo['total'])}, "
                     f"ganancia estimada {pesos(nuevo['ganancia_estimada'])} ({margen(nuevo['margen_estimado'])})")

    seccion_ajustar = ft.Column([tarjeta(
        ajustar_tabla,
        ajustar_condiciones,
        ft.Text("Ganancia estimada: lo que dejaria si se vendiera hoy (costo de los lotes que saldrian primero). "
                "La real se calcula recien al venderlo.", size=12, color=COLOR_TEXT_SOFT, italic=True),
        botones_formulario(ft.Text("Guardar precios"), guardar_precios, volver_a_lista),
        titulo=ajustar_titulo,
        subtitulo="Cambia el precio y mira al instante cuanto deja cada linea. Al guardar o cancelar volves a la lista.",
    )], visible=False)

    refrescar()
    return ft.Column(
        [
            encabezado_pantalla("Presupuestos", "Cotizaciones con precios congelados. Se arman en la caja (F4); aca se "
                                                "ajustan los precios mirando la ganancia estimada, y se abren para cobrarlos."),
            seccion_lista,
            seccion_ajustar,
        ],
        expand=True, spacing=ESPACIO_PANTALLA, scroll=ft.ScrollMode.AUTO,
    )
