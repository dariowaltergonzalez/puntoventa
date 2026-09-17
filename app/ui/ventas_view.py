from decimal import Decimal

import flet as ft

from app.services import clientes_service, listas_precios_service, medios_pago_service, productos_service, ventas_service
from app.services.exceptions import (
    ClienteNoEncontradoError,
    LineasVaciasError,
    ListaPrecioNoEncontradaError,
    MedioPagoNoEncontradoError,
    MontoPagoInvalidoError,
    ProductoInactivoError,
    ProductoNoEncontradoError,
    StockInsuficienteError,
)
from app.shared.money import formatear_cantidad, formatear_porcentaje, formatear_precio
from app.ui.campos import FILTRO_DECIMALES, aplicar_mascara_moneda, parsear_decimal_ar_opcional
from app.ui.listados import Paginador, coincide_texto, filtrar

EXCEPCIONES_NEGOCIO = (
    ClienteNoEncontradoError, LineasVaciasError, ListaPrecioNoEncontradaError,
    MedioPagoNoEncontradoError, MontoPagoInvalidoError, ProductoInactivoError,
    ProductoNoEncontradoError, StockInsuficienteError, ValueError,
)

# Paleta "Caja Rapida" (ver mockup aprobado por Dario) -- especifica de esta pantalla, no es
# el theme general de la app, por su naturaleza de consola de venta rapida a pantalla completa.
COLOR_BG = "#eef5f4"
COLOR_BG_ALT = "#e3eeec"
COLOR_RAIL = "#0e3d3b"
COLOR_RAIL_SOFT = "#154e4b"
COLOR_BORDER = "#cfe0dd"
COLOR_TEXT = "#132824"
COLOR_TEXT_SOFT = "#54706c"
COLOR_TEXT_ON_RAIL = "#dceeeb"
COLOR_TEXT_ON_RAIL_SOFT = "#8fb5b0"
COLOR_ACCENT = "#0f8b83"
COLOR_ACCENT_STRONG = "#0b6b64"
COLOR_ACCENT_WASH = "#e2f3f1"
COLOR_ACTION = "#ff6a3d"
COLOR_ACTION_STRONG = "#e2521f"
COLOR_ACTION_WASH = "#ffe6da"
COLOR_SUCCESS = "#1f8f5f"
COLOR_SUCCESS_WASH = "#e2f6ec"
COLOR_WARNING = "#c9821c"
COLOR_DANGER = "#d5493f"

ANCHO_CANT_COL = 158
ANCHO_PRECIO = 110
ANCHO_DESC = 78
ANCHO_SUBTOTAL = 118
ANCHO_ACCION = 44

COLOR_RAIL_BORDE = "#2a6b66"
COLOR_RAIL_BORDE_FOCO = "#6fe3d4"


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
            "iva": "",
            "descuento_total": "",
            "observacion": "",
            "pagos": [],
            "total_calculado": None,
            "desglose_texto": "",
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
                            ft.Text(f"Venta {t['tab_id']}", size=12, weight=ft.FontWeight.BOLD,
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
    rapidos_column = ft.Column([], spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)

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
            tiles.append(
                ft.Container(
                    bgcolor=COLOR_RAIL_SOFT, border_radius=10, padding=10, ink=True,
                    on_click=lambda e, prod=p: agregar_desde_rapido(prod),
                    content=ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(p["nombre"], size=12.5, weight=ft.FontWeight.BOLD, color=COLOR_TEXT_ON_RAIL),
                                    ft.Text(p["codigo"], size=10, color=COLOR_TEXT_ON_RAIL_SOFT),
                                    ft.Text(("⚠ " if bajo else "") + f"Stock: {formatear_cantidad(p['stock_actual'])}",
                                             size=9.5, color=COLOR_WARNING if bajo else COLOR_TEXT_ON_RAIL_SOFT),
                                ],
                                expand=True, spacing=1,
                            ),
                            ft.Text(money(p["precio_venta"]), size=12.5, weight=ft.FontWeight.BOLD, color="#6fe3d4"),
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
        width=300, bgcolor=COLOR_RAIL, padding=16,
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
            "subtotal_texto": subtotal_texto, "stock_texto": stock_texto,
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
    iva_field = ft.TextField(label="IVA %", width=110, input_filter=FILTRO_DECIMALES)
    descuento_total_field = ft.TextField(label="Desc. total %", width=140, input_filter=FILTRO_DECIMALES)
    observacion_field = ft.TextField(label="Observacion del ticket", expand=True)

    def on_iva_change(e: ft.ControlEvent) -> None:
        activo()["iva"] = iva_field.value or ""
        recalcular_totales_activo()
        page.update()

    def on_descuento_total_change(e: ft.ControlEvent) -> None:
        activo()["descuento_total"] = descuento_total_field.value or ""
        recalcular_totales_activo()
        page.update()

    def on_observacion_change(e: ft.ControlEvent) -> None:
        activo()["observacion"] = observacion_field.value or ""

    iva_field.on_change = on_iva_change
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
    btn_cobrar = ft.ElevatedButton(
        content=ft.Text("Cobrar  (F12)", size=16, weight=ft.FontWeight.BOLD),
        bgcolor=COLOR_ACTION, color=ft.Colors.WHITE, height=54, disabled=True,
    )
    cancelar_venta_button = ft.OutlinedButton("Cancelar venta (F5)")
    reimprimir_button = ft.OutlinedButton("Reimprimir ultimo (F8)")

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
                cancelar_venta_button, reimprimir_button,
                ft.Container(expand=True),
                ft.Column(
                    [
                        ft.Text("TOTAL", size=13, weight=ft.FontWeight.BOLD, color=COLOR_TEXT_SOFT),
                        ft.Row(
                            [dock_desglose_texto, dock_total_texto],
                            spacing=14, alignment=ft.MainAxisAlignment.END,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.END, spacing=0,
                ),
                btn_cobrar,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=16,
        ),
    )

    def construir_desglose(t: dict, totales: dict) -> str:
        # Hace visible por que el total no coincide con la simple suma de subtotales de linea --
        # el descuento fijo del cliente (Fase 2) se aplica solo sobre el total y no tiene
        # ninguna otra marca en pantalla, asi que sin esto parecia un error de calculo.
        partes = [f"Subtotal {money(totales['subtotal'])}"]
        if t["cliente_id"]:
            cliente = clientes_service.obtener_cliente(t["cliente_id"])
            if cliente and cliente["porcentaje_descuento"]:
                partes.append(f"cliente -{formatear_porcentaje(cliente['porcentaje_descuento'])}%")
        if (descuento_total_field.value or "").strip():
            partes.append(f"desc. total -{descuento_total_field.value}%")
        if (iva_field.value or "").strip():
            partes.append(f"IVA +{iva_field.value}%")
        return "  ·  ".join(partes)

    def recalcular_totales_activo() -> None:
        t = activo()
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
            iva = parsear_decimal_ar_opcional(iva_field.value, "IVA")
            descuento_total = parsear_decimal_ar_opcional(descuento_total_field.value, "Descuento sobre el total")
            totales = ventas_service.previsualizar_totales(
                items, lista_precio_id=t["lista_precio_id"], cliente_id=t["cliente_id"],
                descuento_total_porcentaje=descuento_total, iva_porcentaje=iva,
            )
            t["total_calculado"] = totales["total"]
            t["desglose_texto"] = construir_desglose(t, totales)
            dock_total_texto.value = money(totales["total"])
            dock_desglose_texto.value = t["desglose_texto"]
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
    cobro_items_texto = ft.Text("", size=11.5, color=COLOR_TEXT_SOFT)
    cobro_total_texto = ft.Text("$ 0,00", size=36, weight=ft.FontWeight.BOLD, color=COLOR_ACCENT_STRONG)
    cobro_desglose_texto = ft.Text("", size=11, color=COLOR_TEXT_SOFT)
    cobro_restante_texto = ft.Text("", size=12.5, weight=ft.FontWeight.BOLD)
    medios_grid = ft.Row([], spacing=10, wrap=True)
    recibido_field = ft.TextField(label="El cliente entrego", width=220, input_filter=FILTRO_DECIMALES)
    aplicar_mascara_moneda(recibido_field)
    vuelto_texto = ft.Text("Vuelto: $ 0,00", size=16, weight=ft.FontWeight.BOLD, color=COLOR_SUCCESS)
    efectivo_box = ft.Row([recibido_field, vuelto_texto], visible=False, spacing=20,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER)
    pagos_aplicados_column = ft.Column([], spacing=6)
    btn_confirmar_cobro = ft.ElevatedButton("Confirmar cobro", bgcolor=COLOR_SUCCESS, color=ft.Colors.WHITE, disabled=True)
    btn_cerrar_cobro = ft.IconButton(ft.Icons.CLOSE)

    cobro_atajos_texto = ft.Text("F1-F4 elige el medio de pago  ·  ESC vuelve al carrito", size=10.5, color=COLOR_TEXT_SOFT)

    cobro_overlay = ft.Container(
        left=0, top=0, right=0, bottom=0, visible=False,
        bgcolor=ft.Colors.with_opacity(0.45, "#0a201e"),
        alignment=ft.Alignment.CENTER,
        content=ft.Container(
            bgcolor=ft.Colors.WHITE, border_radius=18, padding=20, width=560,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Column([ft.Text("Cobrar venta", size=17, weight=ft.FontWeight.BOLD), cobro_items_texto],
                                       expand=True, spacing=2),
                            btn_cerrar_cobro,
                        ]
                    ),
                    ft.Column(
                        [ft.Text("TOTAL A COBRAR", size=11, color=COLOR_TEXT_SOFT), cobro_total_texto,
                         cobro_desglose_texto, cobro_restante_texto],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2,
                    ),
                    medios_grid,
                    cobro_atajos_texto,
                    efectivo_box,
                    pagos_aplicados_column,
                    ft.Row(
                        [ft.OutlinedButton("Volver al carrito", expand=True, on_click=lambda e: cerrar_cobro()),
                         btn_confirmar_cobro],
                        spacing=10,
                    ),
                ],
                spacing=12, tight=True,
            ),
        ),
    )
    btn_confirmar_cobro.expand = True

    def restante_cobro(t: dict) -> Decimal:
        pagado = sum((p["monto"] for p in t["pagos"]), Decimal("0"))
        return (t["total_calculado"] - pagado).quantize(Decimal("1.00"))

    def construir_chip_pago(idx: int, p: dict) -> ft.Control:
        return ft.Container(
            bgcolor=COLOR_SUCCESS_WASH, border_radius=10, padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            content=ft.Row(
                [
                    ft.Text(f"{p['medio_nombre']} · {money(p['monto'])}", weight=ft.FontWeight.BOLD,
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
        refrescar_cobro()
        cobro_overlay.visible = True
        page.update()

    def cerrar_cobro() -> None:
        cobro_overlay.visible = False
        page.update()

    async def elegir_medio(medio: dict) -> None:
        t = activo()
        restante = restante_cobro(t)
        if restante <= 0:
            return
        if "efectivo" in medio["nombre"].lower():
            efectivo_box.visible = True
            recibido_field.value = ""
            vuelto_texto.value = "Vuelto: $ 0,00"
            page.update()
            await recibido_field.focus()
            return
        efectivo_box.visible = False
        recibido_field.value = ""
        vuelto_texto.value = "Vuelto: $ 0,00"
        t["pagos"].append({"medio_pago_id": medio["id"], "medio_nombre": medio["nombre"], "monto": restante})
        refrescar_cobro()
        page.update()

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
            width=136, height=88,
            on_click=click_medio,
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET if es_cta else ft.Icons.PAYMENTS, color=color_texto, size=22),
                    ft.Text(m["nombre"], size=12, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER, color=color_texto),
                    ft.Text(atajo, size=9.5, color=color_texto) if atajo else ft.Container(height=0),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=3, tight=True,
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

    def confirmar_efectivo(e: ft.ControlEvent | None = None) -> None:
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

    recibido_field.on_change = on_recibido_change
    recibido_field.on_submit = confirmar_efectivo
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

    def confirmar_cobro_click(e: ft.ControlEvent | None = None) -> None:
        t = activo()
        if t["total_calculado"] is None or restante_cobro(t) > Decimal("0.004") or not t["pagos"]:
            return
        try:
            items = construir_items_ticket(t)
            pagos = [
                {"medio_pago_id": p["medio_pago_id"], "monto": p["monto"], "recibido": p.get("recibido")}
                for p in t["pagos"]
            ]
            iva = parsear_decimal_ar_opcional(iva_field.value, "IVA")
            descuento_total = parsear_decimal_ar_opcional(descuento_total_field.value, "Descuento sobre el total")
            venta = ventas_service.crear_venta(
                items=items, pagos=pagos,
                cliente_id=t["cliente_id"],
                cliente_nombre_nuevo=t["cliente_nombre_nuevo"] or None,
                usar_cliente_generico=t["usar_generico"],
                lista_precio_id=t["lista_precio_id"],
                iva_porcentaje=iva,
                descuento_total_porcentaje=descuento_total,
                observacion=observacion_field.value,
            )
            mostrar_mensaje(f"{venta['numero']} confirmada — Total {money(venta['total'])}")
            cerrar_cobro()
            cerrar_ticket_actual()
        except EXCEPCIONES_NEGOCIO as ex:
            mostrar_mensaje(str(ex))

    btn_confirmar_cobro.on_click = confirmar_cobro_click

    main_columna = ft.Column([cart_wrap, ajustes_strip, dock], expand=True, spacing=0)
    main_stack = ft.Stack([main_columna, cobro_overlay], expand=True)

    def abrir_cobro_click(e: ft.ControlEvent) -> None:
        abrir_cobro()

    btn_cobrar.on_click = abrir_cobro_click

    # ================= SECCION HISTORIAL (ventas ya confirmadas) =================
    buscador_field = ft.TextField(label="Buscar por numero o cliente", expand=True)
    tabla_historial = ft.DataTable(columns=[ft.DataColumn(ft.Text(t)) for t in ["Numero", "Cliente", "Fecha", "Total", ""]], rows=[])
    paginador = Paginador(on_cambio=lambda: refrescar_lista_historial())

    def refrescar_lista_historial(e: ft.ControlEvent | None = None) -> None:
        todas = ventas_service.listar_ventas()
        filtradas = filtrar(todas, [
            lambda v: coincide_texto(v["numero"], buscador_field.value) or coincide_texto(v["cliente_nombre"], buscador_field.value),
        ])
        pagina = paginador.aplicar(filtradas)
        tabla_historial.rows = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Text(v["numero"])),
                ft.DataCell(ft.Text(v["cliente_nombre"] or "-")),
                ft.DataCell(ft.Text(v["fecha"][:16])),
                ft.DataCell(ft.Text(formatear_precio(v["total"]))),
                ft.DataCell(ft.IconButton(ft.Icons.VISIBILITY, tooltip="Ver detalle", data=v["id"],
                                            on_click=lambda e: ir_a_detalle_historial(e.control.data))),
            ])
            for v in pagina
        ]
        page.update()

    buscador_field.on_change = refrescar_lista_historial

    seccion_historial = ft.Column(
        [
            ft.Row([ft.Text("Ventas confirmadas", size=20, weight=ft.FontWeight.BOLD),
                    ft.Container(expand=True), ft.TextButton("Volver a la caja", on_click=lambda e: mostrar_caja())]),
            ft.Row([buscador_field]),
            tabla_historial,
            paginador.controles,
        ],
        visible=False, expand=True, scroll=ft.ScrollMode.AUTO,
        spacing=12,
    )

    # ================= SECCION DETALLE (venta ya confirmada) =================
    detalle_titulo = ft.Text("", size=18, weight=ft.FontWeight.BOLD)
    detalle_info = ft.Text("")
    tabla_detalle_items = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(t)) for t in ["Producto / Descripcion", "Cantidad", "Precio unit.", "% desc.", "Subtotal"]],
        rows=[],
    )
    tabla_detalle_pagos = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(t)) for t in ["Medio de pago", "Monto", "Recibio", "Vuelto"]], rows=[],
    )
    detalle_total_texto = ft.Text("", size=18, weight=ft.FontWeight.BOLD)

    def refrescar_detalle() -> None:
        venta = ventas_service.obtener_venta(detalle_venta_id["valor"])

        def subtotal_linea(i: dict) -> Decimal:
            monto = i["cantidad"] * i["precio_unitario"]
            if i["descuento_item_porcentaje"] is not None:
                monto = monto * (Decimal("1") - i["descuento_item_porcentaje"] / Decimal("100"))
            return monto.quantize(Decimal("1.00"))

        detalle_titulo.value = f"{venta['numero']} - {venta['cliente_nombre']}"
        detalle_info.value = (
            f"Fecha: {venta['fecha'][:16]}   |   Estado: {venta['estado'].capitalize()}   |   "
            f"IVA: {venta['iva_porcentaje'] if venta['iva_porcentaje'] is not None else '-'}%"
        )
        if venta["observacion"]:
            detalle_info.value += f"\nObservacion: {venta['observacion']}"
        tabla_detalle_items.rows = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Text(i["descripcion_libre"] or f"{i['producto_codigo']} - {i['producto_nombre']}")),
                ft.DataCell(ft.Text(formatear_cantidad(i["cantidad"]))),
                ft.DataCell(ft.Text(formatear_precio(i["precio_unitario"]))),
                ft.DataCell(ft.Text(f"{formatear_porcentaje(i['descuento_item_porcentaje'])}%" if i["descuento_item_porcentaje"] is not None else "-")),
                ft.DataCell(ft.Text(formatear_precio(subtotal_linea(i)))),
            ])
            for i in venta["items"]
        ]
        tabla_detalle_pagos.rows = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Text(p["medio_pago_nombre"] + (" (cta. cte.)" if p["es_cuenta_corriente"] else ""))),
                ft.DataCell(ft.Text(formatear_precio(p["monto"]))),
                ft.DataCell(ft.Text(formatear_precio(p["recibido"]) if p["recibido"] is not None else "-")),
                ft.DataCell(ft.Text(formatear_precio(p["vuelto"]) if p["vuelto"] is not None else "-")),
            ])
            for p in venta["pagos"]
        ]
        detalle_total_texto.value = f"Total: {formatear_precio(venta['total'])}"
        page.update()

    seccion_detalle = ft.Column(
        [
            detalle_titulo, detalle_info,
            ft.TextButton("Volver al listado", on_click=lambda e: mostrar_historial()),
            ft.Text("Items", weight=ft.FontWeight.BOLD), tabla_detalle_items,
            ft.Text("Pagos", weight=ft.FontWeight.BOLD), tabla_detalle_pagos,
            detalle_total_texto,
        ],
        visible=False, expand=True, scroll=ft.ScrollMode.AUTO, spacing=8,
    )

    # ================= SECCION CAJA (pantalla por defecto) =================
    ayuda_teclado_texto = ft.Text(
        "Tab pasa al siguiente campo   ·   Enter agrega producto   ·   F3 Item libre   ·   "
        "F5 Cancelar venta   ·   F8 Reimprimir ultimo   ·   F9 Nueva venta   ·   "
        "F12 Cobrar / confirmar cobro   ·   (dentro del cobro) F1-F4 elige medio de pago, ESC vuelve",
        size=11, color=COLOR_TEXT_SOFT,
    )

    seccion_caja = ft.Column(
        [
            ft.Row(
                [
                    ft.Text("Punto de Venta", size=16, weight=ft.FontWeight.BOLD, color=COLOR_ACCENT_STRONG),
                    ft.Container(expand=True),
                    ft.TextButton("Ver ventas anteriores", on_click=lambda e: mostrar_historial()),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ayuda_teclado_texto,
            tabs_row,
            ft.Row([rail, ft.Container(content=main_stack, expand=True)], expand=True, spacing=0),
        ],
        expand=True, spacing=8,
    )

    # ================= NAVEGACION ENTRE SECCIONES =================
    def mostrar_caja() -> None:
        seccion_caja.visible = True
        seccion_historial.visible = False
        seccion_detalle.visible = False
        page.update()

    def mostrar_historial() -> None:
        seccion_caja.visible = False
        seccion_historial.visible = True
        seccion_detalle.visible = False
        refrescar_lista_historial()
        page.update()

    def ir_a_detalle_historial(venta_id: int) -> None:
        detalle_venta_id["valor"] = venta_id
        seccion_caja.visible = False
        seccion_historial.visible = False
        seccion_detalle.visible = True
        refrescar_detalle()
        page.update()

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
                confirmar_cobro_click()
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

    page.on_keyboard_event = manejar_teclado

    # ================= INICIALIZACION =================
    def renderizar_ticket_activo() -> None:
        t = activo()
        cliente_dropdown.value = str(t["cliente_id"]) if t["cliente_id"] else None
        cliente_nuevo_field.value = t["cliente_nombre_nuevo"]
        cliente_generico_switch.value = t["usar_generico"]
        reconstruir_opciones_cliente(t)
        iva_field.value = t["iva"]
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
    tickets.append(nuevo_ticket())
    renderizar_ticket_activo()

    return ft.Column([seccion_caja, seccion_historial, seccion_detalle], expand=True)
