import asyncio
from datetime import date, datetime
from decimal import Decimal

import flet as ft

from app.services import (
    clientes_service,
    ganancias_service,
    negocio_service,
    listas_precios_service,
    medios_pago_service,
    notas_credito_service,
    presupuestos_service,
    preventas_service,
    productos_service,
    ventas_service,
)
from app.services.exceptions import (
    ClienteNoEncontradoError,
    LineasVaciasError,
    ListaPrecioNoEncontradaError,
    MedioPagoNoEncontradoError,
    MontoPagoInvalidoError,
    NotaCreditoInvalidaError,
    PresupuestoNoDisponibleError,
    PreventaNoDisponibleError,
    ProductoInactivoError,
    ProductoNoEncontradoError,
    ProductoSinPrecioError,
    StockInsuficienteError,
    VentaNoEncontradaError,
)
from app.shared.money import formatear_cantidad, formatear_porcentaje, formatear_precio
from app.ui.campos import FILTRO_DECIMALES, aplicar_mascara_moneda, parsear_decimal_ar_opcional
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
    accion_anular,
    accion_ver,
    avisar,
    barra,
    boton_secundario,
    campo_buscar,
    dato,
    encabezado_pantalla,
    etiqueta_estado,
    rotulo,
    tabla_simple,
    tarjeta,
    ventana_info,
)
from app.ui.theme import (
    COLOR_ACCENT,
    COLOR_ACCENT_STRONG,
    COLOR_ACCENT_WASH,
    COLOR_ACTION,
    COLOR_ACTION_STRONG,
    COLOR_ACTION_WASH,
    COLOR_BG_ALT,
    COLOR_BORDER,
    COLOR_DANGER,
    COLOR_RAIL,
    COLOR_RAIL_BORDE,
    COLOR_RAIL_BORDE_FOCO,
    COLOR_RAIL_SOFT,
    COLOR_SUCCESS,
    COLOR_SUCCESS_WASH,
    COLOR_TEXT,
    COLOR_TEXT_ON_RAIL,
    COLOR_TEXT_ON_RAIL_SOFT,
    COLOR_TEXT_SOFT,
    COLOR_WARNING,
)

EXCEPCIONES_NEGOCIO = (
    ClienteNoEncontradoError, LineasVaciasError, ListaPrecioNoEncontradaError,
    MedioPagoNoEncontradoError, MontoPagoInvalidoError, ProductoInactivoError,
    ProductoNoEncontradoError, ProductoSinPrecioError, StockInsuficienteError, ValueError,
    NotaCreditoInvalidaError, VentaNoEncontradaError, PreventaNoDisponibleError, PresupuestoNoDisponibleError,
)

ANCHO_CANT_COL = 158
ANCHO_PRECIO = 110
ANCHO_DESC = 78
ANCHO_SUBTOTAL = 118
ANCHO_ACCION = 44
ANCHO_COBRO_PANEL = 920
MARGEN_COBRO_PANEL = 16
ALTO_COBRO_PANEL_COMPLETO = 440
ALTO_RESERVADO_VENTAS = 200
TAM_TEXTO_COBRO = 12


def _estilizar_dropdown_rail(campo: ft.Dropdown) -> None:
    """Dropdown no hereda FormFieldControl (define sus propios campos, ver dropdown.py) --
    no tiene bgcolor/focused_color como TextField, solo fill_color. Sin este estilo el
    texto se dibuja con el gris oscuro por default de Flet, invisible sobre el rail oscuro."""
    campo.color = COLOR_TEXT_ON_RAIL
    campo.label_style = ft.TextStyle(color=COLOR_TEXT_ON_RAIL_SOFT)
    campo.hint_style = ft.TextStyle(color=COLOR_TEXT_ON_RAIL_SOFT)
    campo.fill_color = COLOR_RAIL_SOFT
    campo.filled = True
    campo.border_color = COLOR_RAIL_BORDE
    campo.focused_border_color = COLOR_RAIL_BORDE_FOCO


def _estilizar_textfield_rail(campo: ft.TextField) -> None:
    campo.color = COLOR_TEXT_ON_RAIL
    campo.focused_color = COLOR_TEXT_ON_RAIL
    campo.label_style = ft.TextStyle(color=COLOR_TEXT_ON_RAIL_SOFT)
    campo.hint_style = ft.TextStyle(color=COLOR_TEXT_ON_RAIL_SOFT)
    campo.bgcolor = COLOR_RAIL_SOFT
    campo.border_color = COLOR_RAIL_BORDE
    campo.focused_border_color = COLOR_RAIL_BORDE_FOCO


def VentasView(page: ft.Page) -> ft.Control:
    def mostrar_mensaje(texto: str, aviso: bool = False) -> None:
        page.show_dialog(ft.SnackBar(ft.Text(texto), bgcolor=COLOR_WARNING if aviso else None))

    def money(valor: Decimal) -> str:
        # formatear_precio (app.shared.money) no lleva "$" a proposito -- es la convencion del
        # resto de la app (Cuentas Corrientes, OC, Clientes). Pero en la caja rapida el mockup
        # que Dario aprobo SIEMPRE mostraba el signo, asi que en esta pantalla puntual se agrega.
        return f"$ {formatear_precio(valor)}"

    # ================= ESTADO =================
    tickets: list[dict] = []
    estado = {"activo_idx": 0, "productos": [], "medios": [], "contador_tab": 0, "filtro": ""}
    detalle_venta_id: dict = {"valor": None}

    def nuevo_ticket() -> dict:
        estado["contador_tab"] += 1
        return {
            "tab_id": estado["contador_tab"],
            "cliente_id": None,
            "cliente_nombre_nuevo": "",
            "usar_generico": True,
            "lista_precio_id": None,
            "lineas": [],
            "descuento_total": "",
            "observacion": "",
            "pagos": [],
            "total_calculado": None,
            "desglose_texto": "",
            # Si la pestaña se armo desde una pre-venta o un presupuesto: al guardar se actualiza
            # ese mismo, y al cobrar queda convertido (en la misma transaccion de la venta).
            "borrador_id": None,
            "borrador_tipo": None,
            "borrador_etiqueta": None,
            # Presupuesto: precios y % de cliente congelados (lo prometido). El servicio los vuelve
            # a validar al cobrar; aca solo sirven para mostrar los mismos numeros en pantalla.
            "precios_fijos": {},
            "descuento_cliente_fijo": None,
        }

    def activo() -> dict:
        return tickets[estado["activo_idx"]]

    def nombre_cliente_actual(t: dict) -> str:
        if t["cliente_id"]:
            cliente = clientes_service.obtener_cliente(t["cliente_id"])
            return cliente["razon_social"] if cliente else "Cliente"
        if t["cliente_nombre_nuevo"]:
            return t["cliente_nombre_nuevo"]
        return clientes_service.NOMBRE_CLIENTE_GENERICO

    def resolver_precio(t: dict, producto_id: int, producto: dict | None = None) -> Decimal:
        if producto_id in t["precios_fijos"]:
            return t["precios_fijos"][producto_id]
        if producto is None:
            producto = productos_service.obtener_producto(producto_id)
        if t["lista_precio_id"]:
            return listas_precios_service.calcular_precio_producto(producto_id, t["lista_precio_id"])
        return producto["precio_venta"]

    def total_cantidad_ticket(t: dict) -> Decimal:
        return sum((l["cantidad"] for l in t["lineas"]), Decimal("0"))

    def construir_items_ticket(t: dict) -> list[dict]:
        items = []
        for l in t["lineas"]:
            if l["tipo"] == "producto":
                items.append({
                    "producto_id": l["producto_id"], "descripcion_libre": None,
                    "cantidad": l["cantidad"], "descuento_item_porcentaje": l["descuento_item_porcentaje"],
                })
            else:
                items.append({
                    "producto_id": None, "descripcion_libre": l["descripcion_libre"],
                    "cantidad": l["cantidad"], "precio_unitario": l["precio_unitario"],
                    "descuento_item_porcentaje": l["descuento_item_porcentaje"],
                })
        return items

    # ================= TOPBAR + TABS =================
    tabs_row = ft.Row([], spacing=6, wrap=True)

    def cambiar_pestana(idx: int) -> None:
        estado["activo_idx"] = idx
        renderizar_ticket_activo()

    def cerrar_tab(idx: int) -> None:
        if len(tickets) == 1:
            tickets[0] = nuevo_ticket()
            estado["activo_idx"] = 0
        else:
            tickets.pop(idx)
            if estado["activo_idx"] >= len(tickets):
                estado["activo_idx"] = len(tickets) - 1
            elif estado["activo_idx"] > idx:
                estado["activo_idx"] -= 1
        renderizar_ticket_activo()

    def nueva_pestana(e: ft.ControlEvent | None = None) -> None:
        tickets.append(nuevo_ticket())
        estado["activo_idx"] = len(tickets) - 1
        renderizar_ticket_activo()

    def refrescar_tabs() -> None:
        filas = []
        for idx, t in enumerate(tickets):
            es_activa = idx == estado["activo_idx"]
            filas.append(
                ft.Container(
                    bgcolor=ft.Colors.WHITE if es_activa else COLOR_BG_ALT,
                    border=ft.Border.all(1, COLOR_BORDER),
                    border_radius=8,
                    padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                    on_click=lambda e, i=idx: cambiar_pestana(i),
                    content=ft.Row(
                        [
                            ft.Text(t["borrador_etiqueta"] or f"Venta {t['tab_id']}", size=12, weight=ft.FontWeight.BOLD,
                                     color=COLOR_ACCENT_STRONG if es_activa else COLOR_TEXT_SOFT),
                            ft.Container(
                                bgcolor=COLOR_ACCENT if es_activa else COLOR_ACCENT_WASH,
                                border_radius=6,
                                padding=ft.Padding.symmetric(horizontal=5, vertical=1),
                                content=ft.Text(str(int(total_cantidad_ticket(t))), size=10,
                                                 color=ft.Colors.WHITE if es_activa else COLOR_ACCENT_STRONG),
                            ),
                            ft.IconButton(ft.Icons.CLOSE, icon_size=13, tooltip="Cerrar venta",
                                          on_click=lambda e, i=idx: cerrar_tab(i)),
                        ],
                        spacing=6, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            )
        filas.append(ft.IconButton(ft.Icons.ADD, tooltip="Nueva venta (F9)", on_click=nueva_pestana))
        tabs_row.controls = filas

    # ================= RAIL: cliente / lista / busqueda =================
    cliente_dropdown = ft.Dropdown(label="Cliente", options=[], autofocus=True)
    cliente_nuevo_field = ft.TextField(label="O nombre nuevo (sin ficha)")
    cliente_generico_switch = ft.Switch(label="Consumidor Final", value=True,
                                          label_text_style=ft.TextStyle(color=COLOR_TEXT_ON_RAIL))
    cliente_nota_texto = ft.Text("", size=11.5, color=COLOR_ACTION_WASH, visible=False)
    cliente_descuento_texto = ft.Text("", size=11.5, weight=ft.FontWeight.BOLD, color="#6fe3d4", visible=False)
    lista_dropdown = ft.Dropdown(label="Lista de precios", options=[ft.dropdown.Option(key="", text="Precio normal")], value="")
    _estilizar_dropdown_rail(cliente_dropdown)
    _estilizar_textfield_rail(cliente_nuevo_field)
    _estilizar_dropdown_rail(lista_dropdown)

    def refrescar_dropdown_clientes() -> None:
        cliente_dropdown.options = [
            ft.dropdown.Option(key=str(c["id"]), text=c["razon_social"])
            for c in clientes_service.listar_clientes(solo_activos=True)
        ]

    def reconstruir_opciones_cliente(t: dict) -> None:
        lista_dropdown.options = [ft.dropdown.Option(key="", text="Precio normal")]
        cliente_nota_texto.value = ""
        cliente_nota_texto.visible = False
        cliente_descuento_texto.value = ""
        cliente_descuento_texto.visible = False
        listas_asignadas = []
        if t["cliente_id"]:
            cliente = clientes_service.obtener_cliente(t["cliente_id"])
            if cliente:
                if cliente["observacion"]:
                    cliente_nota_texto.value = f"Nota del cliente: {cliente['observacion']}"
                    cliente_nota_texto.visible = True
                if cliente["porcentaje_descuento"]:
                    cliente_descuento_texto.value = (
                        f"Este cliente tiene {formatear_porcentaje(cliente['porcentaje_descuento'])}% de descuento "
                        f"fijo -- se aplica solo sobre el total final"
                    )
                    cliente_descuento_texto.visible = True
                listas_asignadas = sorted(cliente["listas_precios"], key=lambda l: l["prioridad"])
                lista_dropdown.options += [
                    ft.dropdown.Option(key=str(l["lista_precio_id"]), text=f"{l['nombre']} (prioridad {l['prioridad']})")
                    for l in listas_asignadas
                ]
        ids_validos = {l["lista_precio_id"] for l in listas_asignadas}
        if t["lista_precio_id"] in ids_validos:
            lista_dropdown.value = str(t["lista_precio_id"])
        elif listas_asignadas:
            t["lista_precio_id"] = listas_asignadas[0]["lista_precio_id"]
            lista_dropdown.value = str(t["lista_precio_id"])
        else:
            t["lista_precio_id"] = None
            lista_dropdown.value = ""

    def refrescar_precios_lineas(t: dict) -> None:
        for l in t["lineas"]:
            actualizar_linea(t, l)

    def cliente_click(e: ft.ControlEvent) -> None:
        t = activo()
        t["cliente_id"] = int(cliente_dropdown.value) if cliente_dropdown.value else None
        t["usar_generico"] = False
        t["cliente_nombre_nuevo"] = ""
        cliente_generico_switch.value = False
        cliente_nuevo_field.value = ""
        reconstruir_opciones_cliente(t)
        refrescar_precios_lineas(t)
        recalcular_totales_activo()
        page.update()

    def cliente_generico_change(e: ft.ControlEvent) -> None:
        t = activo()
        t["usar_generico"] = cliente_generico_switch.value
        if t["usar_generico"]:
            t["cliente_id"] = None
            t["cliente_nombre_nuevo"] = ""
            cliente_dropdown.value = None
            cliente_nuevo_field.value = ""
            reconstruir_opciones_cliente(t)
            refrescar_precios_lineas(t)
            recalcular_totales_activo()
        page.update()

    def cliente_nuevo_change(e: ft.ControlEvent) -> None:
        t = activo()
        t["cliente_nombre_nuevo"] = cliente_nuevo_field.value or ""
        if t["cliente_nombre_nuevo"]:
            t["usar_generico"] = False
            t["cliente_id"] = None
            cliente_generico_switch.value = False
            cliente_dropdown.value = None
            reconstruir_opciones_cliente(t)
            refrescar_precios_lineas(t)
            recalcular_totales_activo()
        page.update()

    def lista_click(e: ft.ControlEvent) -> None:
        t = activo()
        t["lista_precio_id"] = int(lista_dropdown.value) if lista_dropdown.value else None
        refrescar_precios_lineas(t)
        recalcular_totales_activo()
        page.update()

    cliente_dropdown.on_select = cliente_click
    cliente_generico_switch.on_change = cliente_generico_change
    cliente_nuevo_field.on_change = cliente_nuevo_change
    lista_dropdown.on_select = lista_click

    codigo_field = ft.TextField(label="Codigo o nombre")
    cant_field = ft.TextField(label="Cant.", value="1", width=70, input_filter=FILTRO_DECIMALES)
    _estilizar_textfield_rail(codigo_field)
    _estilizar_textfield_rail(cant_field)
    resultados_texto = ft.Text("", size=11, color=COLOR_TEXT_ON_RAIL_SOFT)
    rapidos_column = ft.Column([], spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)

    def coincide_producto(p: dict, texto: str) -> bool:
        if not texto:
            return True
        texto = texto.upper()
        return p["codigo"].upper().startswith(texto) or texto in p["nombre"].upper()

    def refrescar_rapidos() -> None:
        texto = estado["filtro"]
        lista = [p for p in estado["productos"] if coincide_producto(p, texto)]
        resultados_texto.value = f"{len(lista)} de {len(estado['productos'])}" if texto else f"{len(estado['productos'])} en total"
        if not lista:
            rapidos_column.controls = [ft.Text(f'Sin coincidencias para "{texto}"', size=12, color=COLOR_TEXT_ON_RAIL_SOFT)]
            return
        tiles = []
        for p in lista[:80]:
            bajo = p["stock_minimo"] > 0 and p["stock_actual"] < p["stock_minimo"]
            sin_precio = p["precio_venta"] <= 0
            precio_control = (
                ft.Text("Sin precio ⚠", size=13, weight=ft.FontWeight.BOLD, color=COLOR_WARNING)
                if sin_precio else
                ft.Text(money(p["precio_venta"]), size=15, weight=ft.FontWeight.BOLD, color="#6fe3d4")
            )
            tiles.append(
                ft.Container(
                    bgcolor=COLOR_RAIL_SOFT, border_radius=10, padding=12, ink=True,
                    opacity=0.55 if sin_precio else 1,
                    on_click=lambda e, prod=p: agregar_desde_rapido(prod),
                    content=ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(p["nombre"], size=14.5, weight=ft.FontWeight.BOLD, color=COLOR_TEXT_ON_RAIL),
                                    ft.Text(p["codigo"], size=13, weight=ft.FontWeight.W_600, color=COLOR_TEXT_ON_RAIL_SOFT),
                                    ft.Text(("⚠ " if bajo else "") + f"Stock: {formatear_cantidad(p['stock_actual'])}",
                                             size=12.5, weight=ft.FontWeight.W_600,
                                             color=COLOR_WARNING if bajo else COLOR_TEXT_ON_RAIL_SOFT),
                                ],
                                expand=True, spacing=2,
                            ),
                            precio_control,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            )
        rapidos_column.controls = tiles

    def on_codigo_change(e: ft.ControlEvent) -> None:
        estado["filtro"] = codigo_field.value or ""
        refrescar_rapidos()
        page.update()

    def limpiar_busqueda() -> None:
        codigo_field.value = ""
        cant_field.value = "1"
        estado["filtro"] = ""
        refrescar_rapidos()

    def agregar_desde_rapido(producto: dict) -> None:
        cantidad = parsear_decimal_ar_opcional(cant_field.value, "Cantidad") or Decimal("1")
        agregar_producto(activo(), producto, cantidad)
        limpiar_busqueda()
        page.update()

    def intentar_agregar_por_codigo(e: ft.ControlEvent | None = None) -> None:
        texto = (codigo_field.value or "").strip()
        if not texto:
            return
        cantidad = parsear_decimal_ar_opcional(cant_field.value, "Cantidad") or Decimal("1")
        texto_upper = texto.upper()
        producto = next((p for p in estado["productos"] if p["codigo"].upper() == texto_upper), None)
        if producto is None:
            producto = next((p for p in estado["productos"] if p["nombre"].upper().startswith(texto_upper)), None)
        if producto is None:
            mostrar_mensaje(f'No se encontro un producto activo para "{texto}"', aviso=True)
            return
        agregar_producto(activo(), producto, cantidad)
        limpiar_busqueda()
        page.update()

    codigo_field.on_change = on_codigo_change
    codigo_field.on_submit = intentar_agregar_por_codigo
    cant_field.on_submit = intentar_agregar_por_codigo

    item_libre_button = ft.OutlinedButton(
        "+ Item libre (F3)",
        style=ft.ButtonStyle(color=COLOR_TEXT_ON_RAIL, side=ft.BorderSide(1, COLOR_TEXT_ON_RAIL_SOFT)),
    )

    rail = ft.Container(
        width=340, bgcolor=COLOR_RAIL, padding=16,
        content=ft.Column(
            [
                cliente_dropdown, cliente_nuevo_field, cliente_generico_switch, cliente_nota_texto,
                cliente_descuento_texto,
                lista_dropdown,
                ft.Divider(height=1, color=COLOR_RAIL_SOFT),
                ft.Row([codigo_field], expand=True),
                ft.Row([cant_field, ft.Text("Enter agrega  ·  escribi para filtrar", size=10, color=COLOR_TEXT_ON_RAIL_SOFT, expand=True)]),
                ft.Row([ft.Text("PRODUCTOS", size=10.5, weight=ft.FontWeight.BOLD, color=COLOR_TEXT_ON_RAIL_SOFT), ft.Container(expand=True), resultados_texto]),
                rapidos_column,
                item_libre_button,
            ],
            spacing=12, expand=True, scroll=ft.ScrollMode.AUTO,
        ),
    )

    # ================= CARRITO =================
    contenedor_lineas = ft.Column([], spacing=8)
    errores_texto = ft.Text("", size=11.5, color=COLOR_DANGER)

    def actualizar_linea(t: dict, linea: dict) -> None:
        if linea["tipo"] == "producto":
            producto = productos_service.obtener_producto(linea["producto_id"])
            if producto is None:
                return
            precio = resolver_precio(t, linea["producto_id"], producto)
            linea["precio_texto"].value = money(precio)
            bajo = producto["stock_minimo"] > 0 and producto["stock_actual"] < producto["stock_minimo"]
            linea["stock_texto"].value = ("⚠ " if bajo else "") + f"Stock: {formatear_cantidad(producto['stock_actual'])}"
            linea["stock_texto"].color = COLOR_WARNING if bajo else COLOR_TEXT_SOFT
            subtotal = precio * linea["cantidad"]
        else:
            precio = linea["precio_unitario"] or Decimal("0")
            subtotal = precio * linea["cantidad"]
        if linea["descuento_item_porcentaje"]:
            subtotal = subtotal * (Decimal("1") - linea["descuento_item_porcentaje"] / Decimal("100"))
        linea["subtotal_texto"].value = money(subtotal.quantize(Decimal("1.00")))

    def quitar_linea(t: dict, linea: dict) -> None:
        t["lineas"].remove(linea)
        refrescar_contenedor_lineas(t)
        recalcular_totales_activo()
        refrescar_tabs()
        page.update()

    def refrescar_contenedor_lineas(t: dict) -> None:
        if not t["lineas"]:
            contenedor_lineas.controls = [
                ft.Container(
                    padding=40, alignment=ft.Alignment.CENTER,
                    content=ft.Column(
                        [
                            ft.Text("🧺", size=32),
                            ft.Text("Escanea un codigo o elegi un producto para empezar la venta",
                                     size=13, color=COLOR_TEXT_SOFT),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8,
                    ),
                )
            ]
        else:
            contenedor_lineas.controls = [l["fila"] for l in t["lineas"]]

    def crear_linea_producto(t: dict, producto: dict) -> dict:
        cantidad_field = ft.TextField(value="1", width=72, text_align=ft.TextAlign.CENTER, text_size=16,
                                        input_filter=FILTRO_DECIMALES, dense=True)
        desc_field = ft.TextField(value="", width=ANCHO_DESC, text_align=ft.TextAlign.CENTER, text_size=15,
                                    input_filter=FILTRO_DECIMALES, dense=True, hint_text="0")
        precio_texto = ft.Text("", size=15, width=ANCHO_PRECIO, text_align=ft.TextAlign.RIGHT)
        subtotal_texto = ft.Text("", size=17, weight=ft.FontWeight.BOLD, color=COLOR_ACCENT_STRONG,
                                   width=ANCHO_SUBTOTAL, text_align=ft.TextAlign.RIGHT)
        stock_texto = ft.Text("", size=12.5)
        eliminar_button = ft.IconButton(ft.Icons.CLOSE, icon_size=19, tooltip="Quitar")
        menos_button = ft.IconButton(ft.Icons.REMOVE, icon_size=18, tooltip="Restar")
        mas_button = ft.IconButton(ft.Icons.ADD, icon_size=18, tooltip="Sumar")

        linea = {
            "tipo": "producto", "producto_id": producto["id"],
            "producto_codigo": producto["codigo"], "producto_nombre": producto["nombre"],
            "cantidad": Decimal("1"), "descuento_item_porcentaje": None,
            "cantidad_field": cantidad_field, "precio_texto": precio_texto,
            "subtotal_texto": subtotal_texto, "stock_texto": stock_texto, "desc_field": desc_field,
        }

        def cambiar_cantidad(delta: Decimal) -> None:
            nueva = linea["cantidad"] + delta
            if nueva < Decimal("0.001"):
                return
            if delta > 0:
                prod = productos_service.obtener_producto(linea["producto_id"])
                otras = sum((l["cantidad"] for l in t["lineas"] if l is not linea and l["tipo"] == "producto"
                             and l["producto_id"] == linea["producto_id"]), Decimal("0"))
                disponible = prod["stock_actual"] - otras
                if nueva > disponible:
                    mostrar_mensaje(f"No hay mas stock disponible (max. {formatear_cantidad(disponible)})", aviso=True)
                    return
            linea["cantidad"] = nueva
            cantidad_field.value = formatear_cantidad(nueva)
            actualizar_linea(t, linea)
            recalcular_totales_activo()
            refrescar_tabs()
            page.update()

        def on_cantidad_change(e: ft.ControlEvent) -> None:
            valor = parsear_decimal_ar_opcional(cantidad_field.value, "Cantidad")
            if valor is None or valor <= 0:
                return
            linea["cantidad"] = valor
            actualizar_linea(t, linea)
            recalcular_totales_activo()
            refrescar_tabs()
            page.update()

        def on_desc_change(e: ft.ControlEvent) -> None:
            linea["descuento_item_porcentaje"] = parsear_decimal_ar_opcional(desc_field.value, "Descuento")
            actualizar_linea(t, linea)
            recalcular_totales_activo()
            page.update()

        cantidad_field.on_change = on_cantidad_change
        desc_field.on_change = on_desc_change
        menos_button.on_click = lambda e: cambiar_cantidad(Decimal("-1"))
        mas_button.on_click = lambda e: cambiar_cantidad(Decimal("1"))
        eliminar_button.on_click = lambda e: quitar_linea(t, linea)

        fila = ft.Container(
            bgcolor=ft.Colors.WHITE, border=ft.Border.all(1, COLOR_BORDER), border_radius=10, padding=14,
            content=ft.Row(
                [
                    ft.Column(
                        [ft.Text(f"{producto['codigo']} - {producto['nombre']}", weight=ft.FontWeight.BOLD, size=16),
                         stock_texto],
                        expand=True, spacing=2,
                    ),
                    ft.Row([menos_button, cantidad_field, mas_button], spacing=0, width=ANCHO_CANT_COL,
                           alignment=ft.MainAxisAlignment.CENTER),
                    precio_texto, desc_field, subtotal_texto, eliminar_button,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
        linea["fila"] = fila
        return linea

    def crear_linea_libre(t: dict) -> dict:
        descripcion_field = ft.TextField(value="Item libre / servicio", dense=True, expand=True, text_size=16)
        cantidad_field = ft.TextField(value="1", width=72, text_align=ft.TextAlign.CENTER, text_size=16,
                                        input_filter=FILTRO_DECIMALES, dense=True)
        precio_field = ft.TextField(value="", width=ANCHO_PRECIO, text_align=ft.TextAlign.RIGHT, text_size=15,
                                      input_filter=FILTRO_DECIMALES, dense=True, hint_text="Precio")
        desc_field = ft.TextField(value="", width=ANCHO_DESC, text_align=ft.TextAlign.CENTER, text_size=15,
                                    input_filter=FILTRO_DECIMALES, dense=True, hint_text="0")
        subtotal_texto = ft.Text("", size=17, weight=ft.FontWeight.BOLD, color=COLOR_ACCENT_STRONG,
                                   width=ANCHO_SUBTOTAL, text_align=ft.TextAlign.RIGHT)
        eliminar_button = ft.IconButton(ft.Icons.CLOSE, icon_size=19, tooltip="Quitar")
        menos_button = ft.IconButton(ft.Icons.REMOVE, icon_size=18, tooltip="Restar")
        mas_button = ft.IconButton(ft.Icons.ADD, icon_size=18, tooltip="Sumar")

        linea = {
            "tipo": "libre", "descripcion_libre": descripcion_field.value, "precio_unitario": None,
            "cantidad": Decimal("1"), "descuento_item_porcentaje": None, "subtotal_texto": subtotal_texto,
            "descripcion_field": descripcion_field, "precio_field": precio_field,
            "cantidad_field": cantidad_field, "desc_field": desc_field,
        }

        def on_descripcion_change(e: ft.ControlEvent) -> None:
            linea["descripcion_libre"] = descripcion_field.value

        def on_precio_change(e: ft.ControlEvent) -> None:
            linea["precio_unitario"] = parsear_decimal_ar_opcional(precio_field.value, "Precio")
            actualizar_linea(t, linea)
            recalcular_totales_activo()
            page.update()

        def cambiar_cantidad(delta: Decimal) -> None:
            nueva = linea["cantidad"] + delta
            if nueva < Decimal("0.001"):
                return
            linea["cantidad"] = nueva
            cantidad_field.value = formatear_cantidad(nueva)
            actualizar_linea(t, linea)
            recalcular_totales_activo()
            refrescar_tabs()
            page.update()

        def on_cantidad_change(e: ft.ControlEvent) -> None:
            valor = parsear_decimal_ar_opcional(cantidad_field.value, "Cantidad")
            if valor is None or valor <= 0:
                return
            linea["cantidad"] = valor
            actualizar_linea(t, linea)
            recalcular_totales_activo()
            refrescar_tabs()
            page.update()

        def on_desc_change(e: ft.ControlEvent) -> None:
            linea["descuento_item_porcentaje"] = parsear_decimal_ar_opcional(desc_field.value, "Descuento")
            actualizar_linea(t, linea)
            recalcular_totales_activo()
            page.update()

        descripcion_field.on_change = on_descripcion_change
        precio_field.on_change = on_precio_change
        cantidad_field.on_change = on_cantidad_change
        desc_field.on_change = on_desc_change
        menos_button.on_click = lambda e: cambiar_cantidad(Decimal("-1"))
        mas_button.on_click = lambda e: cambiar_cantidad(Decimal("1"))
        eliminar_button.on_click = lambda e: quitar_linea(t, linea)

        fila = ft.Container(
            bgcolor=ft.Colors.WHITE, border=ft.Border.all(1, COLOR_BORDER), border_radius=10, padding=14,
            content=ft.Row(
                [
                    ft.Column(
                        [descripcion_field, ft.Text("Item libre - no descuenta stock", size=10.5, color=COLOR_TEXT_SOFT)],
                        expand=True, spacing=2,
                    ),
                    ft.Row([menos_button, cantidad_field, mas_button], spacing=0, width=ANCHO_CANT_COL,
                           alignment=ft.MainAxisAlignment.CENTER),
                    precio_field, desc_field, subtotal_texto, eliminar_button,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
        linea["fila"] = fila
        return linea

    def agregar_producto(t: dict, producto: dict, cantidad: Decimal) -> None:
        if resolver_precio(t, producto["id"], producto) <= 0:
            mostrar_mensaje(
                f"'{producto['nombre']}' no tiene precio de venta cargado -- completalo en Productos antes de venderlo",
                aviso=True,
            )
            return
        ya = sum((l["cantidad"] for l in t["lineas"] if l["tipo"] == "producto" and l["producto_id"] == producto["id"]),
                 Decimal("0"))
        disponible = producto["stock_actual"] - ya
        if disponible <= 0:
            mostrar_mensaje(f"Sin stock disponible de {producto['nombre']}", aviso=True)
            return
        if cantidad > disponible:
            cantidad = disponible
            mostrar_mensaje(f"Solo quedan {formatear_cantidad(disponible)} de {producto['nombre']}", aviso=True)
        existente = next((l for l in t["lineas"] if l["tipo"] == "producto" and l["producto_id"] == producto["id"]), None)
        if existente:
            existente["cantidad"] += cantidad
            existente["cantidad_field"].value = formatear_cantidad(existente["cantidad"])
            actualizar_linea(t, existente)
        else:
            linea = crear_linea_producto(t, producto)
            linea["cantidad"] = cantidad
            linea["cantidad_field"].value = formatear_cantidad(cantidad)
            actualizar_linea(t, linea)
            t["lineas"].append(linea)
        refrescar_contenedor_lineas(t)
        recalcular_totales_activo()
        refrescar_tabs()

    def agregar_item_libre(e: ft.ControlEvent | None = None) -> None:
        t = activo()
        linea = crear_linea_libre(t)
        t["lineas"].append(linea)
        refrescar_contenedor_lineas(t)
        recalcular_totales_activo()
        refrescar_tabs()
        page.update()

    item_libre_button.on_click = agregar_item_libre

    cart_header = ft.Container(
        bgcolor=COLOR_ACCENT, border_radius=8, padding=ft.Padding.symmetric(horizontal=12, vertical=9),
        content=ft.Row(
            [
                ft.Container(content=ft.Text("PRODUCTO", size=15, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE), expand=True),
                ft.Container(content=ft.Text("CANT.", size=15, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                             width=ANCHO_CANT_COL, alignment=ft.Alignment.CENTER),
                ft.Container(content=ft.Text("PRECIO", size=15, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                             width=ANCHO_PRECIO, alignment=ft.Alignment.CENTER_RIGHT),
                ft.Container(content=ft.Text("DESC. %", size=15, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                             width=ANCHO_DESC, alignment=ft.Alignment.CENTER),
                ft.Container(content=ft.Text("SUBTOTAL", size=15, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                             width=ANCHO_SUBTOTAL, alignment=ft.Alignment.CENTER_RIGHT),
                ft.Container(width=ANCHO_ACCION),
            ]
        ),
    )

    cart_wrap = ft.Container(
        expand=True, padding=ft.Padding.symmetric(horizontal=16, vertical=8),
        content=ft.Column([cart_header, contenedor_lineas], expand=True, scroll=ft.ScrollMode.AUTO, spacing=4),
    )

    # ================= AJUSTES (IVA / descuento total / observacion) =================
    # El IVA no se tipea: lo pone la app segun Datos del negocio (o el presupuesto, si el carrito
    # viene de uno). Este campo solo lo muestra.
    iva_field = ft.TextField(label="IVA", width=210, read_only=True)
    descuento_total_field = ft.TextField(label="Desc. total %", width=140, input_filter=FILTRO_DECIMALES)
    observacion_field = ft.TextField(label="Observacion del ticket", expand=True)

    def on_descuento_total_change(e: ft.ControlEvent) -> None:
        activo()["descuento_total"] = descuento_total_field.value or ""
        recalcular_totales_activo()
        page.update()

    def on_observacion_change(e: ft.ControlEvent) -> None:
        activo()["observacion"] = observacion_field.value or ""

    descuento_total_field.on_change = on_descuento_total_change
    observacion_field.on_change = on_observacion_change

    ajustes_strip = ft.Container(
        padding=ft.Padding.symmetric(horizontal=16, vertical=10),
        border=ft.Border(top=ft.BorderSide(1, COLOR_BORDER)),
        content=ft.Row([iva_field, descuento_total_field, observacion_field, errores_texto], spacing=14,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )

    # ================= DOCK (total + cobrar) =================
    dock_total_texto = ft.Text("$ 0,00", size=30, weight=ft.FontWeight.BOLD, color=COLOR_TEXT)
    dock_desglose_texto = ft.Text("", size=15, weight=ft.FontWeight.W_600, color=COLOR_TEXT_SOFT)
    # Ganancia estimada del carrito: oculta por defecto, porque la pantalla de la caja la puede ver
    # el cliente que esta del otro lado del mostrador. Se muestra con el ojito.
    dock_ganancia_texto = ft.Text("", size=13, weight=ft.FontWeight.BOLD, visible=False)
    ver_ganancia = {"activo": False}
    ver_ganancia_button = ft.IconButton(ft.Icons.VISIBILITY_OUTLINED, tooltip="Ver ganancia estimada", icon_size=20)

    def alternar_ganancia(e: ft.ControlEvent | None = None) -> None:
        ver_ganancia["activo"] = not ver_ganancia["activo"]
        ver_ganancia_button.icon = ft.Icons.VISIBILITY_OFF_OUTLINED if ver_ganancia["activo"] else ft.Icons.VISIBILITY_OUTLINED
        ver_ganancia_button.tooltip = "Ocultar ganancia" if ver_ganancia["activo"] else "Ver ganancia estimada"
        recalcular_totales_activo()
        page.update()

    ver_ganancia_button.on_click = alternar_ganancia
    btn_cobrar = ft.ElevatedButton(
        content=ft.Text("Cobrar  (F12)", size=16, weight=ft.FontWeight.BOLD),
        bgcolor=COLOR_ACTION, color=ft.Colors.WHITE, height=54, disabled=True,
    )
    cancelar_venta_button = ft.OutlinedButton("Cancelar venta (F5)")
    reimprimir_button = ft.OutlinedButton("Reimprimir ultimo (F8)")
    guardar_preventa_button = ft.OutlinedButton("Guardar para despues (F7)", icon=ft.Icons.BOOKMARK_ADD_OUTLINED)
    guardar_presupuesto_button = ft.OutlinedButton("Presupuesto (F4)", icon=ft.Icons.REQUEST_QUOTE_OUTLINED)

    # Franja inline (sin AlertDialog) para guardar el carrito como pre-venta (con un nombre) o
    # como presupuesto (con dias de validez). franja_modo: 'preventa' | 'presupuesto'.
    franja_modo = {"valor": "preventa"}
    franja_icono = ft.Icon(ft.Icons.BOOKMARK_ADD_OUTLINED, color=COLOR_ACCENT_STRONG)
    franja_titulo = ft.Text("", weight=ft.FontWeight.BOLD, color=COLOR_ACCENT_STRONG)
    preventa_nombre_field = ft.TextField(label="Nombre de la pre-venta", expand=True, dense=True)
    validez_field = ft.TextField(label="Validez (dias)", width=130, dense=True, input_filter=FILTRO_DECIMALES)
    franja_espacio = ft.Container(expand=True)
    preventa_franja = ft.Container(
        visible=False, bgcolor=COLOR_ACCENT_WASH,
        padding=ft.Padding.symmetric(horizontal=16, vertical=10),
        border=ft.Border(top=ft.BorderSide(1, COLOR_BORDER)),
        content=ft.Row([
            franja_icono, franja_titulo, preventa_nombre_field, validez_field, franja_espacio,
            ft.ElevatedButton("Guardar", on_click=lambda e: guardar_desde_franja()),
            ft.TextButton("Cancelar", on_click=lambda e: ocultar_franja_preventa()),
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )

    async def mostrar_franja(modo: str) -> None:
        t = activo()
        if not t["lineas"]:
            mostrar_mensaje("El carrito esta vacio: no hay nada para guardar", aviso=True)
            return
        if modo == "preventa" and t["borrador_tipo"] == "presupuesto":
            mostrar_mensaje(f"Este carrito es el presupuesto {t['borrador_etiqueta']}: guardalo con F4", aviso=True)
            return
        franja_modo["valor"] = modo
        es_presupuesto = modo == "presupuesto"
        franja_icono.icon = ft.Icons.REQUEST_QUOTE_OUTLINED if es_presupuesto else ft.Icons.BOOKMARK_ADD_OUTLINED
        preventa_nombre_field.visible = not es_presupuesto
        validez_field.visible = es_presupuesto
        franja_espacio.visible = es_presupuesto
        if es_presupuesto:
            if t["borrador_tipo"] == "presupuesto":
                franja_titulo.value = f"Guardar cambios del presupuesto {t['borrador_etiqueta'].split(' ')[0]} (conserva su numero):"
                actual = presupuestos_service.obtener_presupuesto(t["borrador_id"])
                validez_field.value = str(max(actual["dias_restantes"], 1)) if actual else str(presupuestos_service.VALIDEZ_DIAS)
            else:
                franja_titulo.value = "Guardar como presupuesto (no descuenta stock, congela los precios):"
                validez_field.value = str(presupuestos_service.VALIDEZ_DIAS)
        else:
            franja_titulo.value = "Guardar para retomar despues (no descuenta stock):"
            preventa_nombre_field.value = t["borrador_etiqueta"] if t["borrador_tipo"] == "preventa" else preventas_service.nombre_sugerido(
                t["cliente_id"], t["cliente_nombre_nuevo"], t["usar_generico"],
            )
        preventa_franja.visible = True
        page.update()
        await (validez_field if es_presupuesto else preventa_nombre_field).focus()

    async def mostrar_franja_preventa(e: ft.ControlEvent | None = None) -> None:
        await mostrar_franja("preventa")

    async def mostrar_franja_presupuesto(e: ft.ControlEvent | None = None) -> None:
        await mostrar_franja("presupuesto")

    def ocultar_franja_preventa() -> None:
        preventa_franja.visible = False
        page.update()

    def guardar_desde_franja(e: ft.ControlEvent | None = None) -> None:
        t = activo()
        comunes = dict(
            cliente_id=t["cliente_id"], cliente_nombre_nuevo=t["cliente_nombre_nuevo"],
            usar_cliente_generico=t["usar_generico"], lista_precio_id=t["lista_precio_id"],
            observacion=observacion_field.value,
        )
        try:
            descuento_total = parsear_decimal_ar_opcional(descuento_total_field.value, "Descuento sobre el total")
            if franja_modo["valor"] == "presupuesto":
                dias = parsear_decimal_ar_opcional(validez_field.value, "La validez")
                presupuesto = presupuestos_service.guardar_presupuesto(
                    t["borrador_id"] if t["borrador_tipo"] == "presupuesto" else None, construir_items_ticket(t),
                    descuento_total_porcentaje=descuento_total,
                    validez_dias=int(dias) if dias is not None else presupuestos_service.VALIDEZ_DIAS, **comunes,
                )
                mensaje = (f"Presupuesto {presupuesto['numero']} guardado por {money(presupuesto['total'])}, "
                           f"vence el {presupuesto['fecha_validez']:%d/%m}. Lo ves en Operaciones → Presupuestos.")
            else:
                preventa = preventas_service.guardar_preventa(
                    t["borrador_id"] if t["borrador_tipo"] == "preventa" else None, preventa_nombre_field.value,
                    construir_items_ticket(t), descuento_total_porcentaje=descuento_total, **comunes,
                )
                mensaje = f"Pre-venta '{preventa['nombre']}' guardada. La retomas desde 'Pre-ventas'."
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex), aviso=True)
            return
        preventa_franja.visible = False
        cerrar_ticket_actual()
        refrescar_contador_preventas()
        mostrar_mensaje(mensaje)

    guardar_preventa_button.on_click = mostrar_franja_preventa
    guardar_presupuesto_button.on_click = mostrar_franja_presupuesto
    preventa_nombre_field.on_submit = guardar_desde_franja
    validez_field.on_submit = guardar_desde_franja

    def cancelar_venta_click(e: ft.ControlEvent | None = None) -> None:
        t = activo()
        t["lineas"] = []
        refrescar_contenedor_lineas(t)
        recalcular_totales_activo()
        refrescar_tabs()
        mostrar_mensaje("Venta cancelada")
        page.update()

    def reimprimir_click(e: ft.ControlEvent | None = None) -> None:
        mostrar_mensaje("La reimpresion de ticket todavia no esta implementada", aviso=True)

    cancelar_venta_button.on_click = cancelar_venta_click
    reimprimir_button.on_click = reimprimir_click

    dock = ft.Container(
        padding=ft.Padding.symmetric(horizontal=16, vertical=12),
        border=ft.Border(top=ft.BorderSide(1, COLOR_BORDER)),
        bgcolor=ft.Colors.WHITE,
        content=ft.Row(
            [
                cancelar_venta_button, reimprimir_button, guardar_preventa_button, guardar_presupuesto_button,
                ft.Container(expand=True),
                ft.Column(
                    [
                        ft.Row([ver_ganancia_button, ft.Text("TOTAL", size=13, weight=ft.FontWeight.BOLD, color=COLOR_TEXT_SOFT)],
                               spacing=2, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Row(
                            [dock_desglose_texto, dock_total_texto],
                            spacing=14, alignment=ft.MainAxisAlignment.END,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        dock_ganancia_texto,
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.END, spacing=0,
                ),
                btn_cobrar,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=16,
        ),
    )

    def texto_iva(iva_entero: int, precios_con_iva: bool) -> str:
        if not negocio_service.config_iva()["configurado"]:
            return "Sin configurar (Datos del negocio)"
        if not iva_entero:
            return "Sin IVA"
        porcentaje = formatear_porcentaje(Decimal(iva_entero) / 100).replace(",00", "")
        return f"{porcentaje}% incluido" if precios_con_iva else f"{porcentaje}% (se suma)"

    def construir_desglose(t: dict, totales: dict) -> str:
        # Hace visible por que el total no coincide con la simple suma de subtotales de linea --
        # el descuento fijo del cliente (Fase 2) se aplica solo sobre el total y no tiene
        # ninguna otra marca en pantalla, asi que sin esto parecia un error de calculo.
        partes = [f"Subtotal {money(totales['subtotal'])}"]
        if t["borrador_tipo"] == "presupuesto":
            if t["descuento_cliente_fijo"]:
                partes.append(f"cliente -{formatear_porcentaje(t['descuento_cliente_fijo'])}% (del presupuesto)")
        elif t["cliente_id"]:
            cliente = clientes_service.obtener_cliente(t["cliente_id"])
            if cliente and cliente["porcentaje_descuento"]:
                partes.append(f"cliente -{formatear_porcentaje(cliente['porcentaje_descuento'])}%")
        if (descuento_total_field.value or "").strip():
            partes.append(f"desc. total -{descuento_total_field.value}%")
        if totales["iva"]:
            iva_entero, precios_con_iva = ventas_service.condiciones_iva(t["borrador_id"])
            porcentaje = formatear_porcentaje(Decimal(iva_entero) / 100).replace(",00", "")
            partes.append(f"IVA {porcentaje}% incluido {money(totales['iva'])}" if precios_con_iva
                          else f"+ IVA {porcentaje}% {money(totales['iva'])}")
        return "  ·  ".join(partes)

    def recalcular_totales_activo() -> None:
        t = activo()
        dock_ganancia_texto.visible = False
        if not t["lineas"]:
            t["total_calculado"] = None
            t["desglose_texto"] = ""
            dock_total_texto.value = money(Decimal("0"))
            dock_desglose_texto.value = ""
            errores_texto.value = ""
            btn_cobrar.disabled = True
            refrescar_tabs()
            return
        try:
            items = construir_items_ticket(t)
            descuento_total = parsear_decimal_ar_opcional(descuento_total_field.value, "Descuento sobre el total")
            iva_field.value = texto_iva(*ventas_service.condiciones_iva(t["borrador_id"]))
            totales = ventas_service.previsualizar_totales(
                items, lista_precio_id=t["lista_precio_id"], cliente_id=t["cliente_id"],
                descuento_total_porcentaje=descuento_total, borrador_id=t["borrador_id"],
            )
            t["total_calculado"] = totales["total"]
            t["desglose_texto"] = construir_desglose(t, totales)
            dock_total_texto.value = money(totales["total"])
            dock_desglose_texto.value = t["desglose_texto"]
            if ver_ganancia["activo"]:
                estimada = ganancias_service.estimar_ganancia_carrito(
                    items, t["lista_precio_id"], t["cliente_id"], descuento_total, t["borrador_id"],
                )
                margen = f"{str(estimada['margen']).replace('.', ',')} %" if estimada["margen"] is not None else "-"
                dock_ganancia_texto.value = f"Ganancia estimada {money(estimada['ganancia'])} ({margen}) · costo {money(estimada['costo'])}"
                dock_ganancia_texto.color = COLOR_DANGER if estimada["ganancia"] < 0 else COLOR_SUCCESS
                dock_ganancia_texto.visible = True
            errores_texto.value = ""
            btn_cobrar.disabled = False
        except EXCEPCIONES_NEGOCIO as ex:
            t["total_calculado"] = None
            t["desglose_texto"] = ""
            dock_total_texto.value = "—"
            dock_desglose_texto.value = ""
            errores_texto.value = str(ex)
            btn_cobrar.disabled = True
        refrescar_tabs()

    # ================= PANEL DE COBRO (overlay no-modal, Stack + visible) =================
    cobro_items_texto = ft.Text("", size=TAM_TEXTO_COBRO, color=COLOR_TEXT_SOFT)
    cobro_total_texto = ft.Text("$ 0,00", size=30, weight=ft.FontWeight.BOLD, color=COLOR_ACCENT_STRONG)
    cobro_desglose_texto = ft.Text("", size=TAM_TEXTO_COBRO, color=COLOR_TEXT_SOFT)
    cobro_restante_texto = ft.Text("", size=TAM_TEXTO_COBRO, weight=ft.FontWeight.BOLD)
    medios_grid = ft.Row([], spacing=8, run_spacing=8, wrap=True)
    recibido_field = ft.TextField(label="El cliente entrego", width=220, input_filter=FILTRO_DECIMALES)
    aplicar_mascara_moneda(recibido_field)
    vuelto_texto = ft.Text("Vuelto: $ 0,00", size=16, weight=ft.FontWeight.BOLD, color=COLOR_SUCCESS)
    efectivo_box = ft.Row([recibido_field, vuelto_texto], visible=False, spacing=20,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER)

    cheque_banco_field = ft.TextField(label="Banco", width=150)
    cheque_librador_field = ft.TextField(label="Librador", width=170)
    cheque_numero_field = ft.TextField(label="Numero (opc.)", width=150)
    cheque_cuit_field = ft.TextField(label="CUIT (opc.)", width=130)
    cheque_fecha_pago_field = ft.TextField(label="Fecha pago (AAAA-MM-DD)", width=210)
    cheque_confirmar_button = ft.ElevatedButton("Confirmar cheque")
    cheque_box = ft.Column(
        [
            ft.Row([cheque_banco_field, cheque_librador_field, cheque_numero_field, cheque_cuit_field,
                    cheque_fecha_pago_field], spacing=8, run_spacing=8, wrap=True),
            cheque_confirmar_button,
        ],
        visible=False, spacing=10,
    )

    pagos_aplicados_column = ft.Column([], spacing=6)
    btn_confirmar_cobro = ft.ElevatedButton(
        "Confirmar cobro  (F12)", bgcolor=COLOR_SUCCESS, color=ft.Colors.WHITE, disabled=True,
    )
    btn_cerrar_cobro = ft.IconButton(ft.Icons.CLOSE)

    cobro_atajos_texto = ft.Text("F1-F4 elige el medio de pago  ·  ESC vuelve al carrito", size=10.5, color=COLOR_TEXT_SOFT)

    cobro_panel = ft.Container(
        bgcolor=ft.Colors.WHITE, border_radius=18, padding=16, width=ANCHO_COBRO_PANEL,
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Column([ft.Text("Cobrar venta", size=17, weight=ft.FontWeight.BOLD), cobro_items_texto],
                                   expand=1, spacing=2),
                        ft.Column([ft.Text("TOTAL A COBRAR", size=TAM_TEXTO_COBRO, color=COLOR_TEXT_SOFT), cobro_total_texto],
                                   expand=1, spacing=0),
                        ft.Column([cobro_desglose_texto, cobro_restante_texto], expand=1, spacing=2),
                        btn_cerrar_cobro,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=16,
                ),
                medios_grid,
                cobro_atajos_texto,
                efectivo_box,
                cheque_box,
                pagos_aplicados_column,
                ft.Row(
                    [ft.OutlinedButton("Volver al carrito", expand=True, on_click=lambda e: cerrar_cobro()),
                     btn_confirmar_cobro],
                    spacing=10,
                ),
            ],
            spacing=8, tight=True,
        ),
    )
    cobro_columna = cobro_panel.content

    def ajustar_panel_cobro() -> None:
        ancho = (page.width or 0) - 2 * MARGEN_COBRO_PANEL
        alto = (page.height or 0) - ALTO_RESERVADO_VENTAS - 2 * MARGEN_COBRO_PANEL
        if ancho > 0:
            cobro_panel.width = min(ANCHO_COBRO_PANEL, ancho)
        if 0 < alto < ALTO_COBRO_PANEL_COMPLETO:
            cobro_panel.height = alto
            cobro_columna.scroll = ft.ScrollMode.AUTO
        else:
            cobro_panel.height = None
            cobro_columna.scroll = None

    cobro_overlay = ft.Container(
        left=0, top=0, right=0, bottom=0, visible=False,
        bgcolor=ft.Colors.with_opacity(0.45, "#0a201e"),
        alignment=ft.Alignment.CENTER,
        content=cobro_panel,
    )
    btn_confirmar_cobro.expand = True

    def restante_cobro(t: dict) -> Decimal:
        pagado = sum((p["monto"] for p in t["pagos"]), Decimal("0"))
        return (t["total_calculado"] - pagado).quantize(Decimal("1.00"))

    def construir_chip_pago(idx: int, p: dict) -> ft.Control:
        cheque = p.get("cheque")
        etiqueta = f"{p['medio_nombre']} ({cheque['banco']})" if cheque else p["medio_nombre"]
        return ft.Container(
            bgcolor=COLOR_SUCCESS_WASH, border_radius=10, padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            content=ft.Row(
                [
                    ft.Text(f"{etiqueta} · {money(p['monto'])}", weight=ft.FontWeight.BOLD,
                             color="#175c3f", expand=True, size=12.5),
                    ft.TextButton("Quitar", on_click=lambda e, i=idx: quitar_pago(i)),
                ]
            ),
        )

    def refrescar_cobro() -> None:
        t = activo()
        cobro_items_texto.value = f"{len(t['lineas'])} lineas · {nombre_cliente_actual(t)}"
        cobro_total_texto.value = money(t["total_calculado"]) if t["total_calculado"] is not None else "—"
        cobro_desglose_texto.value = t.get("desglose_texto", "")
        restante = restante_cobro(t) if t["total_calculado"] is not None else Decimal("0")
        if restante > Decimal("0.004"):
            cobro_restante_texto.value = f"Falta cubrir {money(restante)}"
            cobro_restante_texto.color = COLOR_ACTION_STRONG
        else:
            cobro_restante_texto.value = "Cubierto ✓"
            cobro_restante_texto.color = COLOR_SUCCESS
        pagos_aplicados_column.controls = [construir_chip_pago(idx, p) for idx, p in enumerate(t["pagos"])]
        btn_confirmar_cobro.disabled = restante > Decimal("0.004") or not t["pagos"]

    def abrir_cobro() -> None:
        t = activo()
        if not t["lineas"] or t["total_calculado"] is None:
            mostrar_mensaje("Primero carga al menos un producto con precio valido")
            return
        t["pagos"] = []
        efectivo_box.visible = False
        recibido_field.value = ""
        vuelto_texto.value = "Vuelto: $ 0,00"
        cheque_box.visible = False
        limpiar_campos_cheque()
        refrescar_cobro()
        ajustar_panel_cobro()
        cobro_overlay.visible = True
        page.update()

    def cerrar_cobro() -> None:
        cobro_overlay.visible = False
        page.update()

    def limpiar_campos_cheque() -> None:
        cheque_banco_field.value = ""
        cheque_librador_field.value = ""
        cheque_numero_field.value = ""
        cheque_cuit_field.value = ""
        cheque_fecha_pago_field.value = datetime.now().strftime("%Y-%m-%d")

    async def enfocar_confirmar_cobro() -> None:
        # Pausa corta: el campo que acaba de ocultarse (efectivo/cheque) le quita el foco al
        # redibujarse; si se pide el foco al boton antes, se pierde.
        await asyncio.sleep(0.08)
        await btn_confirmar_cobro.focus()

    async def elegir_medio(medio: dict) -> None:
        t = activo()
        restante = restante_cobro(t)
        if restante <= 0:
            return
        if "efectivo" in medio["nombre"].lower():
            efectivo_box.visible = True
            cheque_box.visible = False
            recibido_field.value = ""
            vuelto_texto.value = "Vuelto: $ 0,00"
            btn_confirmar_cobro.disabled = False
            page.update()
            await recibido_field.focus()
            return
        if "cheque" in medio["nombre"].lower():
            efectivo_box.visible = False
            cheque_box.visible = True
            limpiar_campos_cheque()
            btn_confirmar_cobro.disabled = False
            page.update()
            await cheque_banco_field.focus()
            return
        efectivo_box.visible = False
        cheque_box.visible = False
        recibido_field.value = ""
        vuelto_texto.value = "Vuelto: $ 0,00"
        t["pagos"].append({"medio_pago_id": medio["id"], "medio_nombre": medio["nombre"], "monto": restante})
        refrescar_cobro()
        page.update()
        if not btn_confirmar_cobro.disabled:
            # Queda cubierto con un solo medio -- foco directo al boton para que un Enter mas
            # lo confirme, sin tener que soltar el teclado para clickearlo.
            await enfocar_confirmar_cobro()

    def construir_boton_medio(m: dict, atajo: str | None) -> ft.Control:
        # ElevatedButton (no Container+ink) a proposito: es un control real de formulario,
        # entra en el orden de Tab y se puede activar con Enter/Espacio -- Dario pidio poder
        # moverse por el panel de cobro con teclado, no solo con el mouse.
        es_cta = m["es_cuenta_corriente"]
        color_texto = COLOR_ACTION_STRONG if es_cta else COLOR_ACCENT_STRONG

        async def click_medio(e: ft.ControlEvent, medio: dict = m) -> None:
            await elegir_medio(medio)

        return ft.ElevatedButton(
            bgcolor=COLOR_ACTION_WASH if es_cta else COLOR_ACCENT_WASH,
            width=120, height=84,
            style=ft.ButtonStyle(padding=ft.Padding.symmetric(horizontal=2, vertical=0)),
            on_click=click_medio,
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET if es_cta else ft.Icons.PAYMENTS, color=color_texto, size=22),
                    ft.Text(m["nombre"], size=12, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER, color=color_texto),
                    ft.Text(atajo, size=9, color=color_texto) if atajo else ft.Container(height=0),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=1, tight=True,
            ),
        )

    def on_recibido_change(e: ft.ControlEvent) -> None:
        t = activo()
        recibido = parsear_decimal_ar_opcional(recibido_field.value, "Recibido")
        restante = restante_cobro(t)
        if recibido is not None and recibido > 0:
            vuelto = recibido - restante
            vuelto_texto.value = f"Vuelto: {money(vuelto if vuelto > 0 else Decimal('0'))}"
        else:
            vuelto_texto.value = "Vuelto: $ 0,00"
        page.update()

    async def confirmar_efectivo(e: ft.ControlEvent | None = None) -> None:
        t = activo()
        restante = restante_cobro(t)
        if restante <= 0:
            return
        texto = (recibido_field.value or "").strip()
        if texto:
            recibido = parsear_decimal_ar_opcional(texto, "Recibido")
            if not recibido or recibido <= 0:
                return
        else:
            # Enter con el campo vacio = "pago justo" (sin vuelto): evita tener que tipear
            # el mismo importe que ya se ve arriba en TOTAL A COBRAR / Falta cubrir.
            recibido = restante
            recibido_field.value = formatear_precio(restante)
        medio_efectivo = next((m for m in estado["medios"] if "efectivo" in m["nombre"].lower()), None)
        if medio_efectivo is None:
            mostrar_mensaje("No hay un medio de pago 'Efectivo' cargado en Medios de Pago", aviso=True)
            return
        aplicado = min(recibido, restante)
        t["pagos"].append({
            "medio_pago_id": medio_efectivo["id"], "medio_nombre": medio_efectivo["nombre"],
            "monto": aplicado, "recibido": recibido,
        })
        efectivo_box.visible = False
        recibido_field.value = ""
        refrescar_cobro()
        page.update()
        if not btn_confirmar_cobro.disabled:
            await enfocar_confirmar_cobro()

    recibido_field.on_change = on_recibido_change
    recibido_field.on_submit = confirmar_efectivo

    async def confirmar_cheque(e: ft.ControlEvent | None = None) -> None:
        t = activo()
        restante = restante_cobro(t)
        if restante <= 0:
            return
        banco = (cheque_banco_field.value or "").strip()
        librador = (cheque_librador_field.value or "").strip()
        fecha_pago = (cheque_fecha_pago_field.value or "").strip()
        if not banco or not librador or not fecha_pago:
            mostrar_mensaje("Banco, librador y fecha de pago son obligatorios para cargar un cheque", aviso=True)
            return
        medio_cheque = next((m for m in estado["medios"] if "cheque" in m["nombre"].lower()), None)
        if medio_cheque is None:
            mostrar_mensaje("No hay un medio de pago 'Cheque' cargado en Medios de Pago", aviso=True)
            return
        t["pagos"].append({
            "medio_pago_id": medio_cheque["id"], "medio_nombre": medio_cheque["nombre"], "monto": restante,
            "cheque": {
                "banco": banco, "librador": librador, "fecha_pago": fecha_pago,
                "numero": (cheque_numero_field.value or "").strip() or None,
                "cuit_librador": (cheque_cuit_field.value or "").strip() or None,
            },
        })
        cheque_box.visible = False
        limpiar_campos_cheque()
        refrescar_cobro()
        page.update()
        if not btn_confirmar_cobro.disabled:
            await enfocar_confirmar_cobro()

    async def submit_cheque_banco(e: ft.ControlEvent) -> None:
        await cheque_librador_field.focus()

    async def submit_cheque_librador(e: ft.ControlEvent) -> None:
        await cheque_numero_field.focus()

    async def submit_cheque_numero(e: ft.ControlEvent) -> None:
        await cheque_cuit_field.focus()

    async def submit_cheque_cuit(e: ft.ControlEvent) -> None:
        await cheque_fecha_pago_field.focus()

    cheque_banco_field.on_submit = submit_cheque_banco
    cheque_librador_field.on_submit = submit_cheque_librador
    cheque_numero_field.on_submit = submit_cheque_numero
    cheque_cuit_field.on_submit = submit_cheque_cuit
    cheque_fecha_pago_field.on_submit = confirmar_cheque
    cheque_confirmar_button.on_click = confirmar_cheque

    btn_cerrar_cobro.on_click = lambda e: cerrar_cobro()

    def quitar_pago(idx: int) -> None:
        activo()["pagos"].pop(idx)
        refrescar_cobro()
        page.update()

    def cerrar_ticket_actual() -> None:
        idx = estado["activo_idx"]
        if len(tickets) == 1:
            tickets[0] = nuevo_ticket()
        else:
            tickets.pop(idx)
            if estado["activo_idx"] >= len(tickets):
                estado["activo_idx"] = len(tickets) - 1
        renderizar_ticket_activo()

    async def confirmar_cobro_click(e: ft.ControlEvent | None = None) -> None:
        t = activo()
        if t["total_calculado"] is None:
            return
        # Un efectivo o cheque a medio cargar (se eligio el medio pero no se dio Enter) se carga
        # solo: antes F12 no hacia nada y no avisaba, aunque en pantalla ya se viera el vuelto.
        if restante_cobro(t) > Decimal("0.004") and efectivo_box.visible:
            await confirmar_efectivo()
        if restante_cobro(t) > Decimal("0.004") and cheque_box.visible:
            await confirmar_cheque()
            if cheque_box.visible:
                return  # faltan datos del cheque: confirmar_cheque ya aviso cuales
        restante = restante_cobro(t)
        if restante > Decimal("0.004") or not t["pagos"]:
            mostrar_mensaje(f"Falta cubrir {money(restante)}: elegi un medio de pago (F1-F6)", aviso=True)
            return
        try:
            items = construir_items_ticket(t)
            pagos = [
                {
                    "medio_pago_id": p["medio_pago_id"], "monto": p["monto"], "recibido": p.get("recibido"),
                    "cheque": p.get("cheque"),
                }
                for p in t["pagos"]
            ]
            descuento_total = parsear_decimal_ar_opcional(descuento_total_field.value, "Descuento sobre el total")
            venta = ventas_service.crear_venta(
                items=items, pagos=pagos,
                cliente_id=t["cliente_id"],
                cliente_nombre_nuevo=t["cliente_nombre_nuevo"] or None,
                usar_cliente_generico=t["usar_generico"],
                lista_precio_id=t["lista_precio_id"],
                descuento_total_porcentaje=descuento_total,
                observacion=observacion_field.value,
                borrador_id=t["borrador_id"],
            )
            if t["borrador_id"] is not None:
                refrescar_contador_preventas()
            mostrar_mensaje(f"{venta['numero']} confirmada — Total {money(venta['total'])}")
            cerrar_cobro()
            cerrar_ticket_actual()
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))

    btn_confirmar_cobro.on_click = confirmar_cobro_click

    main_columna = ft.Column([cart_wrap, ajustes_strip, preventa_franja, dock], expand=True, spacing=0)
    main_stack = ft.Stack([main_columna, cobro_overlay], expand=True)

    def abrir_cobro_click(e: ft.ControlEvent) -> None:
        abrir_cobro()

    btn_cobrar.on_click = abrir_cobro_click

    # ================= SECCION HISTORIAL (ventas ya confirmadas) =================
    historial_buscador = campo_buscar("Numero o cliente", al_cambiar=lambda: filtrar_historial())
    historial_desde = ft.TextField(label="Desde", hint_text="AAAA-MM-DD", width=140, on_submit=lambda e: aplicar_fechas_historial())
    historial_hasta = ft.TextField(label="Hasta", hint_text="AAAA-MM-DD", width=140, on_submit=lambda e: aplicar_fechas_historial())
    # Las fechas se aplican recien con Filtrar; el buscador filtra al instante con las ultimas aplicadas.
    historial_fechas: dict = {"desde": None, "hasta": None}
    lista_ventas = Lista(
        [
            Columna("Numero", ancho=100, orden="numero"), Columna("Cliente", peso=3, orden="cliente"),
            Columna("Fecha", ancho=140, orden="fecha"), Columna("Total ($)", ancho=160, derecha=True),
            Columna("Estado", ancho=170), Columna("Acciones", ancho=130, derecha=True),
        ],
        al_cambiar_pagina=lambda: refrescar_lista_historial(), nombre="ventas", con_hijos=True,
        orden_inicial=("fecha", True), sin_datos="Ninguna venta coincide con los filtros.",
    )

    def fecha_hora(iso: str) -> str:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")

    def subtotal_linea(i: dict) -> Decimal:
        monto = i["cantidad"] * i["precio_unitario"]
        if i["descuento_item_porcentaje"] is not None:
            monto = monto * (Decimal("1") - i["descuento_item_porcentaje"] / Decimal("100"))
        return monto.quantize(Decimal("1.00"))

    def celda_total_historial(v: dict) -> ft.Control:
        if not v["notas_credito"]:
            return ft.Text(formatear_precio(v["total"]), weight=ft.FontWeight.BOLD)
        # Con notas de credito se muestra lo que realmente quedo vendido (el neto).
        return ft.Row([
            ft.Container(ft.Text("con NC", size=11, color=COLOR_WARNING, italic=True),
                         tooltip=f"Vendido {formatear_precio(v['total'])} - acreditado {formatear_precio(v['total_acreditado'])}"),
            ft.Text(formatear_precio(v["total_neto"]), weight=ft.FontWeight.BOLD),
        ], spacing=6, tight=True)

    def etiqueta_venta(v: dict) -> ft.Control:
        if not v["notas_credito"]:
            return etiqueta_estado("Confirmada", TONO_OK)
        if v["queda_por_acreditar"]:
            return etiqueta_estado("Con nota de credito", TONO_CURSO)
        return etiqueta_estado("Devuelta toda", TONO_NO)

    def hijos_venta(v: dict) -> ft.Control:
        partes = [
            ft.Column([rotulo("Productos"), tabla_simple(
                ["Producto / descripcion", "Cantidad", "Devuelto", "Precio", "% desc.", "Subtotal"],
                [[i["descripcion_libre"] or f"{i['producto_codigo']} - {i['producto_nombre']}",
                  formatear_cantidad(i["cantidad"]),
                  ft.Text(formatear_cantidad(i["cantidad_devuelta"]), color=COLOR_WARNING) if i["cantidad_devuelta"] > 0 else "-",
                  formatear_precio(i["precio_unitario"]),
                  f"{formatear_porcentaje(i['descuento_item_porcentaje'])}%" if i["descuento_item_porcentaje"] is not None else "-",
                  formatear_precio(subtotal_linea(i))] for i in v["items"]],
                derecha=[1, 2, 3, 4, 5],
            )], spacing=6),
            ft.Column([rotulo("Pagos"), tabla_simple(
                ["Medio de pago", "Monto", "Recibio", "Vuelto"],
                [[p["medio_pago_nombre"] + (" (cta. cte.)" if p["es_cuenta_corriente"] else ""), formatear_precio(p["monto"]),
                  formatear_precio(p["recibido"]) if p["recibido"] is not None else "-",
                  formatear_precio(p["vuelto"]) if p["vuelto"] is not None else "-"] for p in v["pagos"]],
                derecha=[1, 2, 3],
            )], spacing=6),
        ]
        if v["notas_credito"]:
            partes.append(ft.Column([rotulo("Notas de credito"), tabla_simple(
                ["Numero", "Fecha", "Motivo", "Total"],
                [[nc["numero"] + (" (correccion)" if nc["es_correccion"] else ""), fecha_hora(nc["fecha"]), nc["motivo"],
                  formatear_precio(nc["total"])] for nc in v["notas_credito"]],
                derecha=[3],
            )], spacing=6))
        return ft.Row(partes, spacing=28, vertical_alignment=ft.CrossAxisAlignment.START, wrap=True)

    def celdas_venta(v: dict) -> list:
        sin_saldo = None if v["queda_por_acreditar"] else "ya se acredito todo"
        return [
            ft.Text(v["numero"], weight=ft.FontWeight.BOLD), v["cliente_nombre"],
            ft.Text(fecha_hora(v["fecha"]), color=COLOR_TEXT_SOFT), celda_total_historial(v), etiqueta_venta(v),
            ft.Row([
                accion_ver(ft.Icons.VISIBILITY, "Ver totales y ganancia", lambda v=v: ver_venta(v)),
                accion_abrir(ft.Icons.ASSIGNMENT_RETURN, "Nota de credito (devolucion)",
                             lambda v=v: ir_a_nota_credito(v, "nota_credito"), por_que_no=sin_saldo),
                accion_abrir(ft.Icons.EDIT, "Corregir venta", lambda v=v: ir_a_nota_credito(v, "corregir"), por_que_no=sin_saldo),
            ], spacing=0, tight=True),
        ]

    def ver_venta(v: dict) -> None:
        ganancia = ventas_service.detalle_ganancia_venta(v)
        iva = texto_iva(int(v["iva_porcentaje"] * 100), v["precios_con_iva"]) if v["iva_porcentaje"] else "Sin IVA"
        datos = [
            dato("Fecha", fecha_hora(v["fecha"])),
            dato("Cliente", v["cliente_nombre"] or "-"),
            dato("IVA", iva),
            dato("Total", f"$ {formatear_precio(v['total'])}  (neto {formatear_precio(v['neto'])} + IVA {formatear_precio(v['iva'])})"),
        ]
        if v["notas_credito"]:
            datos.append(dato("Acreditado", f"$ {formatear_precio(v['total_acreditado'])}  ·  quedo vendido $ {formatear_precio(v['total_neto'])}"))
        datos.append(dato("Ganancia", f"$ {formatear_precio(ganancia['ganancia'])}  (cobrado sin IVA {formatear_precio(ganancia['ingresos'])} "
                                      f"- costo {formatear_precio(ganancia['costo'])})"))
        if v["observacion"]:
            datos.append(dato("Observacion", v["observacion"]))
        ventana_info(page, f"Venta {v['numero']}", *datos)

    def filtrar_historial() -> None:
        lista_ventas.ir_al_principio()
        refrescar_lista_historial()

    def aplicar_fechas_historial() -> None:
        try:
            historial_fechas["desde"], historial_fechas["hasta"] = (
                date.fromisoformat(campo.value.strip()) if (campo.value or "").strip() else None
                for campo in (historial_desde, historial_hasta)
            )
        except ValueError:
            avisar(page, "Las fechas van con formato AAAA-MM-DD (ej. 2026-10-01)", error=True)
            return
        filtrar_historial()

    def refrescar_lista_historial() -> None:
        try:
            resultado = ventas_service.listar_ventas_pagina(
                pagina=lista_ventas.pagina, tamano_pagina=lista_ventas.por_pagina, texto=historial_buscador.value or None,
                desde=historial_fechas["desde"], hasta=historial_fechas["hasta"],
                orden=lista_ventas.orden, descendente=lista_ventas.descendente,
            )
        except ERRORES_PARA_AVISAR as ex:
            avisar(page, str(ex), error=True)
            return
        lista_ventas.mostrar(resultado["items"], celdas_venta, total=resultado["total"], hijos=hijos_venta)
        page.update()

    seccion_historial = ft.Column(
        [
            encabezado_pantalla("Ventas confirmadas", "Lo vendido, con sus pagos y devoluciones. La flecha de cada venta muestra "
                                                      "sus productos y pagos."),
            barra(
                [historial_buscador, historial_desde, historial_hasta,
                 boton_secundario("Filtrar", ft.Icons.FILTER_LIST, aplicar_fechas_historial)],
                [boton_secundario("Volver a la caja", ft.Icons.ARROW_BACK, lambda: mostrar_caja())],
            ),
            lista_ventas.control,
        ],
        visible=False, expand=True, scroll=ft.ScrollMode.AUTO, spacing=ESPACIO_PANTALLA,
    )

    # ================= SECCION NOTA DE CREDITO / CORREGIR VENTA (pantalla aparte) =================
    # nc_estado["modo"]: 'nota_credito' (se eligen lineas y cantidades) | 'corregir' (todo lo que queda)
    nc_estado: dict = {"venta": None, "modo": "nota_credito", "lineas": [], "resto": Decimal("0")}
    nc_titulo = ft.Text("", size=15, weight=ft.FontWeight.BOLD)
    nc_ayuda = ft.Text("", size=12.5, color=COLOR_TEXT_SOFT)
    nc_avisos_texto = ft.Text("", size=13, color=COLOR_WARNING, weight=ft.FontWeight.BOLD)
    nc_lineas_column = ft.Column([], spacing=6)
    nc_devolver_todo_button = ft.TextButton("Devolver todo")
    nc_motivo_field = ft.TextField(label="Motivo (obligatorio)", expand=True)
    nc_total_texto = ft.Text("", size=16, weight=ft.FontWeight.BOLD)
    nc_reintegro_cc_texto = ft.Text("", size=13)
    nc_destino_dropdown = ft.Dropdown(label="El resto", width=420, options=[])
    nc_confirmar_texto = ft.Text("Emitir nota de credito")
    nc_confirmar_button = ft.ElevatedButton(content=nc_confirmar_texto)

    def nc_items_elegidos() -> list[dict]:
        items = []
        for l in nc_estado["lineas"]:
            cantidad = parsear_decimal_ar_opcional(l["cantidad_field"].value, "La cantidad a devolver") or Decimal("0")
            items.append({"venta_item_id": l["item"]["id"], "cantidad": cantidad, "vuelve_stock": l["stock_checkbox"].value})
        return items

    def nc_recalcular(e: ft.ControlEvent | None = None) -> None:
        venta = nc_estado["venta"]
        nc_confirmar_button.disabled = True
        nc_reintegro_cc_texto.value = ""
        nc_destino_dropdown.visible = False
        try:
            total = notas_credito_service.previsualizar_total(venta["id"], nc_items_elegidos())
        except EXCEPCIONES_NEGOCIO as ex:
            nc_total_texto.value = str(ex)
            nc_total_texto.color = COLOR_DANGER
            page.update()
            return
        nc_total_texto.value = f"Total de la nota de credito: {money(total)}"
        nc_total_texto.color = None
        opciones = notas_credito_service.opciones_reintegro(venta["id"], total)
        if opciones["a_cuenta_corriente"] > 0:
            nc_reintegro_cc_texto.value = (
                f"Se descuentan {money(opciones['a_cuenta_corriente'])} de lo que debe de esta venta en su cuenta corriente."
            )
        nc_estado["resto"] = opciones["resto"]
        if opciones["resto"] > 0:
            claves = []
            nc_destino_dropdown.label = f"Que se hace con los {money(opciones['resto'])} restantes"
            nc_destino_dropdown.options = []
            for m in opciones["medios"]:
                claves.append(f"medio:{m['id']}")
                nc_destino_dropdown.options.append(ft.dropdown.Option(key=f"medio:{m['id']}", text=f"Se le devuelven en {m['nombre']}"))
            if opciones["permite_a_favor"]:
                claves.append("a_favor")
                nc_destino_dropdown.options.append(ft.dropdown.Option(key="a_favor", text="Quedan a favor en su cuenta corriente"))
            for c in opciones["cheques"]:
                claves.append(f"cheque:{c['id']}")
                nc_destino_dropdown.options.append(ft.dropdown.Option(
                    key=f"cheque:{c['id']}",
                    text=f"Se le devuelve el cheque {c['banco']} n° {c['numero'] or 's/n'} ({money(c['monto'])})",
                ))
            if nc_destino_dropdown.value not in claves:
                sugerido = opciones["destino_sugerido"]
                nc_destino_dropdown.value = (
                    f"cheque:{sugerido['cheque_id']}" if sugerido["tipo"] == "cheque"
                    else f"medio:{sugerido['medio_pago_id']}" if sugerido.get("medio_pago_id") else None
                )
            nc_destino_dropdown.visible = True
        nc_confirmar_button.disabled = False
        page.update()

    def nc_destino_elegido() -> dict | None:
        if nc_estado["resto"] <= 0:
            return None
        valor = nc_destino_dropdown.value or ""
        if valor == "a_favor":
            return {"tipo": "a_favor"}
        if valor.startswith("medio:"):
            return {"tipo": "medio_pago", "medio_pago_id": int(valor.split(":")[1])}
        if valor.startswith("cheque:"):
            return {"tipo": "cheque", "cheque_id": int(valor.split(":")[1])}
        return None

    def nc_devolver_todo(e: ft.ControlEvent | None = None) -> None:
        for l in nc_estado["lineas"]:
            l["cantidad_field"].value = formatear_cantidad(l["disponible"])
        nc_recalcular()

    nc_devolver_todo_button.on_click = nc_devolver_todo

    def ir_a_nota_credito(venta_resumen: dict, modo: str) -> None:
        detalle_venta_id["valor"] = venta_resumen["id"]
        venta = ventas_service.obtener_venta(venta_resumen["id"])
        nc_estado.update({"venta": venta, "modo": modo, "lineas": []})
        es_correccion = modo == "corregir"
        nc_titulo.value = f"Corregir la venta {venta['numero']}" if es_correccion else f"Nota de credito de la venta {venta['numero']}"
        nc_ayuda.value = (
            "Se acredita todo lo que queda de la venta (la mercaderia vuelve al stock) y se abre la caja "
            "en una pestaña nueva con el mismo carrito, para ajustarlo y cobrar de nuevo."
            if es_correccion else
            "Indica cuanto se devuelve de cada linea. Si algo no vuelve al stock (roto, vencido), destilda el casillero."
        )
        avisos = notas_credito_service.avisos_correccion(venta["id"]) if es_correccion else []
        nc_avisos_texto.visible = bool(avisos)
        nc_avisos_texto.value = (
            "Ojo: " + "; ".join(avisos) + ". El ticket nuevo sale con los valores de hoy "
            "(si queres respetar los de la venta, usa una nota de credito parcial)."
        ) if avisos else ""
        nc_motivo_field.value = "Correccion de la venta" if es_correccion else ""
        nc_confirmar_texto.value = "Acreditar y abrir en la caja" if es_correccion else "Emitir nota de credito"
        nc_devolver_todo_button.visible = not es_correccion
        nc_destino_dropdown.value = None
        filas = []
        for item in venta["items"]:
            disponible = item["cantidad"] - item["cantidad_devuelta"]
            if disponible <= 0:
                continue
            cantidad_field = ft.TextField(
                label="Devolver", width=110, value=formatear_cantidad(disponible) if es_correccion else "0",
                input_filter=FILTRO_DECIMALES, read_only=es_correccion, on_change=nc_recalcular,
            )
            stock_checkbox = ft.Checkbox(
                label="Vuelve al stock", value=True, visible=item["producto_id"] is not None and not es_correccion,
                on_change=nc_recalcular,
            )
            nombre = item["descripcion_libre"] or f"{item['producto_codigo']} - {item['producto_nombre']}"
            detalle = f"Vendido {formatear_cantidad(item['cantidad'])}"
            if item["cantidad_devuelta"] > 0:
                detalle += f" · ya devuelto {formatear_cantidad(item['cantidad_devuelta'])}"
            nc_estado["lineas"].append({"item": item, "disponible": disponible,
                                        "cantidad_field": cantidad_field, "stock_checkbox": stock_checkbox})
            filas.append(ft.Row([
                ft.Column([ft.Text(nombre, weight=ft.FontWeight.BOLD), ft.Text(detalle, size=12, color=COLOR_TEXT_SOFT)],
                          spacing=0, width=320),
                cantidad_field, stock_checkbox,
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER))
        nc_lineas_column.controls = filas
        mostrar_seccion(seccion_nota_credito)
        nc_recalcular()

    def confirmar_nota_credito(e: ft.ControlEvent) -> None:
        venta = nc_estado["venta"]
        es_correccion = nc_estado["modo"] == "corregir"
        items = nc_items_elegidos()
        try:
            nota = notas_credito_service.crear_nota_credito(
                venta["id"], items, nc_motivo_field.value or "", nc_destino_elegido(), es_correccion=es_correccion,
            )
        except EXCEPCIONES_NEGOCIO as ex:
            avisar(page, str(ex), error=True)
            return
        if es_correccion:
            cargar_venta_en_caja(venta, items)
            avisar(page, f"Se emitio la {nota['numero']}. Ajusta el carrito y cobra de nuevo.")
            return
        mostrar_historial()
        avisar(page, f"Se emitio la nota de credito {nota['numero']} por {money(nota['total'])}")

    nc_confirmar_button.on_click = confirmar_nota_credito

    seccion_nota_credito = ft.Column([
        tarjeta(
            nc_avisos_texto, nc_lineas_column, nc_devolver_todo_button,
            nc_motivo_field, nc_total_texto, nc_reintegro_cc_texto, nc_destino_dropdown,
            ft.Row([nc_confirmar_button, ft.TextButton("Cancelar", on_click=lambda e: mostrar_historial())]),
            titulo=nc_titulo, subtitulo=nc_ayuda,
        ),
    ], visible=False, expand=True, scroll=ft.ScrollMode.AUTO)

    def abrir_carrito_en_pestana_nueva(
        cliente_id: int | None, cliente_nombre_nuevo: str | None, es_generico: bool, lista_precio_id: int | None,
        descuento_total: Decimal | None, observacion: str | None, lineas: list[dict],
        precios_fijos: dict | None = None,
    ) -> dict:
        """Abre una pestaña nueva con un carrito ya armado ('Corregir venta', 'Retomar pre-venta').
        lineas: [{'producto_id', 'descripcion_libre', 'cantidad', 'precio_unitario' (solo libres),
        'descuento_item_porcentaje'}]. Los productos se agregan con agregar_producto, que avisa si
        ya no alcanza el stock y carga lo que hay."""
        t = nuevo_ticket()
        tickets.append(t)
        estado["activo_idx"] = len(tickets) - 1
        t["precios_fijos"] = dict(precios_fijos or {})
        t["usar_generico"] = es_generico
        t["cliente_id"] = None if es_generico else cliente_id
        t["cliente_nombre_nuevo"] = "" if es_generico or cliente_id else (cliente_nombre_nuevo or "")
        t["lista_precio_id"] = lista_precio_id
        t["descuento_total"] = formatear_porcentaje(descuento_total) if descuento_total is not None else ""
        t["observacion"] = observacion or ""
        for item in lineas:
            cantidad, descuento = item["cantidad"], item["descuento_item_porcentaje"]
            if cantidad <= 0:
                continue
            if item["producto_id"] is not None:
                agregar_producto(t, productos_service.obtener_producto(item["producto_id"]), cantidad)
                linea = next((l for l in t["lineas"] if l["tipo"] == "producto" and l["producto_id"] == item["producto_id"]), None)
            else:
                linea = crear_linea_libre(t)
                linea["descripcion_libre"] = item["descripcion_libre"]
                linea["descripcion_field"].value = item["descripcion_libre"]
                linea["precio_unitario"] = item["precio_unitario"]
                linea["precio_field"].value = formatear_precio(item["precio_unitario"])
                linea["cantidad"] = cantidad
                linea["cantidad_field"].value = formatear_cantidad(cantidad)
                t["lineas"].append(linea)
            if linea is not None and descuento is not None:
                linea["descuento_item_porcentaje"] = descuento
                linea["desc_field"].value = formatear_porcentaje(descuento)
        return t

    def cargar_venta_en_caja(venta: dict, items_acreditados: list[dict]) -> None:
        """'Corregir venta': mismo cliente, ajustes y lineas (las cantidades recien acreditadas)."""
        cantidades = {i["venta_item_id"]: i["cantidad"] for i in items_acreditados}
        abrir_carrito_en_pestana_nueva(
            venta["cliente_id"], None, (venta["cliente_nombre"] or "").upper() == clientes_service.NOMBRE_CLIENTE_GENERICO,
            venta["lista_precio_id"],
            venta["descuento_total_porcentaje"], venta["observacion"],
            [{**item, "cantidad": cantidades.get(item["id"], Decimal("0"))} for item in venta["items"]],
        )
        mostrar_caja()
        renderizar_ticket_activo()

    # ================= SECCION PRE-VENTAS (carritos guardados para despues) =================
    preventas_boton_texto = ft.Text("Pre-ventas", weight=ft.FontWeight.BOLD)
    lista_preventas = Lista(
        [
            Columna("Nombre", peso=2, orden="nombre"), Columna("Cliente", peso=2, orden="cliente_nombre"),
            Columna("Productos", ancho=100, derecha=True), Columna("Total aprox. ($)", ancho=140, derecha=True),
            Columna("Guardada", ancho=100, orden="fecha_creacion"), Columna("Estado", ancho=190),
            Columna("Acciones", ancho=90, derecha=True),
        ],
        al_cambiar_pagina=lambda: refrescar_lista_preventas(), nombre="pre-ventas", orden_inicial=("fecha_creacion", False),
        sin_datos="No hay pre-ventas guardadas hoy. Desde la caja: 'Guardar para despues (F7)'.",
    )

    def refrescar_contador_preventas() -> None:
        cantidad = len(preventas_service.listar_preventas_del_dia())
        preventas_boton_texto.value = f"Pre-ventas ({cantidad})" if cantidad else "Pre-ventas"

    def pestana_de_preventa(preventa_id: int) -> int | None:
        return next((i for i, t in enumerate(tickets) if t["borrador_id"] == preventa_id), None)

    def celdas_preventa(pv: dict) -> list:
        abierta = pestana_de_preventa(pv["id"]) is not None
        return [
            ft.Text(pv["nombre"], weight=ft.FontWeight.BOLD), pv["cliente_nombre"], str(len(pv["items"])),
            money(pv["total_aproximado"]), preventas_service.hora(pv["fecha_creacion"]),
            etiqueta_estado("Abierta en una pestaña", TONO_CURSO) if abierta else etiqueta_estado("Guardada", TONO_ESPERA),
            ft.Row([
                accion_abrir(ft.Icons.SHOPPING_CART_CHECKOUT, "Retomar en la caja", lambda pv=pv: retomar_preventa(pv["id"])),
                accion_anular(
                    "Descartar pre-venta", f"Descartar '{pv['nombre']}'",
                    "Se descarta el carrito guardado (no habia tocado el stock). Queda anotado con el motivo.",
                    lambda motivo, pv=pv: descartar_preventa(pv, motivo),
                    por_que_no="esta abierta en una pestaña: cerrala antes" if abierta else None,
                ),
            ], spacing=0, tight=True),
        ]

    def refrescar_lista_preventas() -> None:
        preventas = preventas_service.listar_preventas_del_dia()
        lista_preventas.mostrar(preventas, celdas_preventa, valor_orden=lambda pv, k: pv[k])
        preventas_boton_texto.value = f"Pre-ventas ({len(preventas)})" if preventas else "Pre-ventas"
        page.update()

    def descartar_preventa(pv: dict, motivo: str) -> str:
        preventas_service.descartar_preventa(pv["id"], motivo)
        refrescar_lista_preventas()
        return f"Pre-venta '{pv['nombre']}' descartada"

    def retomar_preventa(preventa_id: int) -> None:
        idx = pestana_de_preventa(preventa_id)
        if idx is not None:
            estado["activo_idx"] = idx
            mostrar_caja()
            renderizar_ticket_activo()
            return
        pv = preventas_service.obtener_preventa(preventa_id)
        if pv is None or pv["estado"] != "abierta":
            mostrar_mensaje("Esa pre-venta ya no esta disponible", aviso=True)
            refrescar_lista_preventas()
            return
        t = abrir_carrito_en_pestana_nueva(
            pv["cliente_id"], pv["cliente_nombre_nuevo"], pv["usar_cliente_generico"], pv["lista_precio_id"],
            pv["descuento_total_porcentaje"], pv["observacion"], pv["items"],
        )
        t["borrador_id"], t["borrador_tipo"], t["borrador_etiqueta"] = pv["id"], "preventa", pv["nombre"]
        mostrar_caja()
        renderizar_ticket_activo()
        if pv["avisos"]:
            mostrar_mensaje("Ojo: " + "; ".join(pv["avisos"]) + ". Se cargo lo que hay.", aviso=True)
        else:
            mostrar_mensaje(f"Pre-venta '{pv['nombre']}' retomada")

    seccion_preventas = ft.Column(
        [
            encabezado_pantalla("Pre-ventas de hoy", "Carritos guardados para retomar mas tarde. No descuentan stock. "
                                                     "Las de dias anteriores ya no aparecen y se borran solas a la semana."),
            barra([], [boton_secundario("Volver a la caja", ft.Icons.ARROW_BACK, lambda: mostrar_caja())]),
            lista_preventas.control,
        ],
        visible=False, expand=True, scroll=ft.ScrollMode.AUTO, spacing=ESPACIO_PANTALLA,
    )

    # ================= SECCION CAJA (pantalla por defecto) =================
    ayuda_teclado_texto = ft.Text(
        "Tab pasa al siguiente campo   ·   Enter agrega producto   ·   F3 Item libre   ·   "
        "F4 Presupuesto   ·   F5 Cancelar venta   ·   F7 Guardar para despues   ·   F8 Reimprimir ultimo   ·   F9 Nueva venta   ·   "
        "F12 Cobrar / confirmar cobro   ·   (dentro del cobro) F1-F4 elige medio de pago, ESC vuelve",
        size=11, color=COLOR_TEXT_SOFT,
    )

    # El menu general esta oculto en esta pantalla (ver app_shell.py) para ganar ancho --
    # este botoncito, a la misma altura que el titulo, es la unica forma de volver a abrirlo.
    mostrar_menu_general = getattr(page, "mostrar_menu_general", None)
    encabezado_izquierda = [
        ft.Text("Punto de Venta", size=16, weight=ft.FontWeight.BOLD, color=COLOR_ACCENT_STRONG),
    ]
    if mostrar_menu_general is not None:
        encabezado_izquierda.insert(0, ft.Container(
            content=ft.IconButton(ft.Icons.MENU, icon_color=ft.Colors.WHITE, icon_size=18,
                                   tooltip="Mostrar menu", on_click=mostrar_menu_general,
                                   style=ft.ButtonStyle(padding=0)),
            bgcolor=COLOR_RAIL, border_radius=8, width=36, height=36, alignment=ft.Alignment.CENTER,
        ))

    seccion_caja = ft.Column(
        [
            ft.Row(
                [
                    *encabezado_izquierda,
                    ft.Container(expand=True),
                    ft.TextButton(content=preventas_boton_texto, icon=ft.Icons.BOOKMARKS_OUTLINED,
                                  on_click=lambda e: mostrar_preventas()),
                    ft.TextButton("Ver ventas anteriores", on_click=lambda e: mostrar_historial()),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ayuda_teclado_texto,
            tabs_row,
            ft.Row([rail, ft.Container(content=main_stack, expand=True)], expand=True, spacing=0),
        ],
        expand=True, spacing=8,
    )

    # ================= NAVEGACION ENTRE SECCIONES =================
    def mostrar_seccion(seccion: ft.Control) -> None:
        for sec in (seccion_caja, seccion_preventas, seccion_historial, seccion_nota_credito):
            sec.visible = sec is seccion
        page.update()

    def mostrar_caja() -> None:
        refrescar_contador_preventas()
        mostrar_seccion(seccion_caja)

    def mostrar_preventas() -> None:
        mostrar_seccion(seccion_preventas)
        refrescar_lista_preventas()

    def mostrar_historial() -> None:
        mostrar_seccion(seccion_historial)
        refrescar_lista_historial()

    # ================= ATAJOS DE TECLADO GLOBALES =================
    # page.on_keyboard_event es global a la Page compartida por toda la app -- app_shell.py lo
    # resetea a None al navegar a otra pantalla del menu, si no estas teclas seguirian
    # disparando acciones de Ventas en cualquier otro lado.
    async def manejar_teclado(e: ft.KeyboardEvent) -> None:
        if not seccion_caja.visible:
            return
        tecla = (e.key or "").upper()
        if cobro_overlay.visible:
            if tecla == "ESCAPE":
                cerrar_cobro()
            elif tecla == "F12":
                await confirmar_cobro_click()
            elif len(tecla) in (2, 3) and tecla[0] == "F" and tecla[1:].isdigit():
                # F1..F6 eligen el medio de pago en ese orden -- F12 queda reservado arriba para
                # confirmar, por eso el tope en 6 (nunca hay tantos medios como para chocar).
                idx = int(tecla[1:]) - 1
                if 0 <= idx < min(len(estado["medios"]), 6):
                    await elegir_medio(estado["medios"][idx])
            return
        if tecla == "F12":
            abrir_cobro()
        elif tecla == "F3":
            agregar_item_libre()
        elif tecla == "F5":
            cancelar_venta_click()
        elif tecla == "F9":
            nueva_pestana()
        elif tecla == "F7":
            await mostrar_franja_preventa()
        elif tecla == "F4":
            await mostrar_franja_presupuesto()
        elif tecla == "ESCAPE" and preventa_franja.visible:
            ocultar_franja_preventa()

    page.on_keyboard_event = manejar_teclado

    # ================= INICIALIZACION =================
    def renderizar_ticket_activo() -> None:
        t = activo()
        cliente_dropdown.value = str(t["cliente_id"]) if t["cliente_id"] else None
        cliente_nuevo_field.value = t["cliente_nombre_nuevo"]
        cliente_generico_switch.value = t["usar_generico"]
        reconstruir_opciones_cliente(t)
        iva_field.value = texto_iva(*ventas_service.condiciones_iva(t["borrador_id"]))
        descuento_total_field.value = t["descuento_total"]
        observacion_field.value = t["observacion"]
        refrescar_contenedor_lineas(t)
        for l in t["lineas"]:
            actualizar_linea(t, l)
        recalcular_totales_activo()
        limpiar_busqueda()
        refrescar_tabs()
        page.update()

    estado["productos"] = productos_service.listar_productos(solo_activos=True)
    estado["medios"] = medios_pago_service.listar_medios_pago(solo_activos=True)
    refrescar_dropdown_clientes()
    medios_grid.controls = [
        construir_boton_medio(m, f"F{idx + 1}" if idx < 6 else None)
        for idx, m in enumerate(estado["medios"])
    ]
    def abrir_presupuesto(presupuesto_id: int) -> None:
        """Abre un presupuesto vigente en una pestaña, con sus precios y % de cliente congelados.
        Desde ahi se cobra (se convierte en venta) o se modifica y se guarda con F4."""
        idx = next((i for i, t in enumerate(tickets) if t["borrador_id"] == presupuesto_id), None)
        if idx is not None:
            estado["activo_idx"] = idx
            renderizar_ticket_activo()
            return
        pr = presupuestos_service.obtener_presupuesto(presupuesto_id)
        if pr is None or pr["estado"] != "vigente":
            mostrar_mensaje("Ese presupuesto no esta vigente: renovalo o revisalo desde Presupuestos", aviso=True)
            return
        t = abrir_carrito_en_pestana_nueva(
            pr["cliente_id"], pr["cliente_nombre_nuevo"], pr["usar_cliente_generico"], pr["lista_precio_id"],
            pr["descuento_total_porcentaje"], pr["observacion"], pr["items"],
            precios_fijos={i["producto_id"]: i["precio_unitario"] for i in pr["items"] if i["producto_id"] is not None},
        )
        t["borrador_id"], t["borrador_tipo"] = pr["id"], "presupuesto"
        t["borrador_etiqueta"] = f"{pr['numero']} · {pr['cliente_nombre']}"
        t["descuento_cliente_fijo"] = pr["descuento_cliente_porcentaje"]
        renderizar_ticket_activo()
        if pr["avisos"]:
            mostrar_mensaje("Ojo: " + "; ".join(pr["avisos"]) + ". Se cargo lo que hay.", aviso=True)
        else:
            mostrar_mensaje(f"Presupuesto {pr['numero']} abierto con sus precios: cobralo (F12) o modificalo y guardalo (F4)")

    tickets.append(nuevo_ticket())
    refrescar_contador_preventas()
    renderizar_ticket_activo()
    presupuesto_pedido = getattr(page, "presupuesto_a_abrir", None)
    if presupuesto_pedido is not None:
        page.presupuesto_a_abrir = None
        abrir_presupuesto(presupuesto_pedido)

    return ft.Column([seccion_caja, seccion_preventas, seccion_historial, seccion_nota_credito], expand=True)
