from datetime import date
from decimal import Decimal, InvalidOperation

import flet as ft

from app.services import categorias_service, ordenes_compra_service, productos_service, proveedores_service, recepciones_service
from app.shared.money import formatear_cantidad, formatear_porcentaje, formatear_precio
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
    accion_con_motivo,
    accion_ver,
    avisar,
    barra,
    boton_principal,
    boton_secundario,
    botones_formulario,
    campo_buscar,
    dato,
    encabezado_pantalla,
    etiqueta_estado,
    rotulo,
    tabla_simple,
    ventana_info,
    tarjeta,
)
from app.ui.theme import COLOR_TEXT_SOFT, COLOR_WARNING

TIPO_EXISTENTE = "Producto existente"
TIPO_NUEVO = "Producto nuevo"
TIPO_LIBRE = "Item libre"

ESTADOS_LABEL = {
    "pendiente": "Pendiente",
    "recibida_parcial": "Recibida en parte",
    "recibida": "Recibida",
    "cancelada": "Cancelada",
}
ESTADOS_ETIQUETA = {
    "pendiente": ("Pendiente", TONO_ESPERA),
    "recibida_parcial": ("Recibida en parte", TONO_CURSO),
    "recibida": ("Recibida", TONO_OK),
    "cancelada": ("Cancelada", TONO_NO),
}



def OrdenesCompraView(page: ft.Page) -> ft.Control:
    def parsear_decimal(valor: str | None, etiqueta: str) -> Decimal:
        try:
            return Decimal((valor or "0").replace(",", "."))
        except InvalidOperation as exc:
            raise ValueError(f"'{etiqueta}' no es un numero valido") from exc

    # ================= Estado interno =================
    editando_oc_id: int | None = None
    detalle_oc_id: int | None = None
    lineas_form: list[dict] = []
    lineas_extra_recepcion: list[dict] = []

    # ================= Constructores de linea =================
    def crear_linea_pedido() -> dict:
        productos_options = [
            ft.dropdown.Option(key=str(p["id"]), text=f"{p['codigo']} - {p['nombre']}")
            for p in productos_service.listar_productos(solo_activos=True)
        ]
        categorias_options = [ft.dropdown.Option(key="", text="Sin elegir")] + [
            ft.dropdown.Option(key=str(c["id"]), text=c["nombre"]) for c in categorias_service.listar_categorias()
        ]
        tipo_dropdown = ft.Dropdown(
            label="Tipo", width=170,
            options=[ft.dropdown.Option(TIPO_EXISTENTE), ft.dropdown.Option(TIPO_NUEVO), ft.dropdown.Option(TIPO_LIBRE)],
            value=TIPO_EXISTENTE,
        )
        producto_dropdown = ft.Dropdown(label="Producto", width=220, options=productos_options)
        codigo_field = ft.TextField(label="Codigo nuevo", width=110, visible=False)
        nombre_field = ft.TextField(label="Nombre nuevo", width=170, visible=False)
        categoria_dropdown = ft.Dropdown(label="Categoria (opcional)", width=150, visible=False, options=categorias_options, value="")
        descripcion_field = ft.TextField(label="Descripcion", width=220, visible=False)
        cantidad_field = ft.TextField(label="Cantidad", width=100, hint_text="10,000")
        costo_field = ft.TextField(label="Costo unit.", width=130, hint_text="5,00", helper_max_lines=2)
        eliminar_button = ft.IconButton(ft.Icons.DELETE, tooltip="Quitar linea")

        def cambiar_tipo(e: ft.ControlEvent) -> None:
            tipo = tipo_dropdown.value
            producto_dropdown.visible = tipo == TIPO_EXISTENTE
            codigo_field.visible = tipo == TIPO_NUEVO
            nombre_field.visible = tipo == TIPO_NUEVO
            categoria_dropdown.visible = tipo == TIPO_NUEVO
            descripcion_field.visible = tipo == TIPO_LIBRE
            page.update()

        tipo_dropdown.on_select = cambiar_tipo

        fila = ft.Row([tipo_dropdown, producto_dropdown, codigo_field, nombre_field, categoria_dropdown,
                       descripcion_field, cantidad_field, costo_field, eliminar_button],
                      vertical_alignment=ft.CrossAxisAlignment.START)
        linea = {
            "tipo_dropdown": tipo_dropdown, "producto_dropdown": producto_dropdown,
            "codigo_field": codigo_field, "nombre_field": nombre_field, "categoria_dropdown": categoria_dropdown,
            "descripcion_field": descripcion_field, "cantidad_field": cantidad_field,
            "costo_field": costo_field, "fila": fila, "costo_sugerido": None,
        }
        eliminar_button.on_click = lambda e: quitar_linea_pedido(linea)

        def elegir_producto(e: ft.ControlEvent) -> None:
            sugerir_costo(linea)
            page.update()

        producto_dropdown.on_select = elegir_producto
        return linea

    def sugerir_costo(linea: dict) -> None:
        """Completa el costo con el de la ultima compra de ese producto a ese proveedor.
        Solo pisa el campo si esta vacio o si todavia tiene la sugerencia anterior sin tocar."""
        costo_field = linea["costo_field"]
        if (costo_field.value or "") not in ("", linea["costo_sugerido"]):
            return
        producto_id = linea["producto_dropdown"].value
        ultimo = None
        if producto_id and proveedor_dropdown.value and not proveedor_generico_switch.value:
            ultimo = recepciones_service.obtener_ultimo_costo(int(producto_id), int(proveedor_dropdown.value))
        if ultimo is None:
            if linea["costo_sugerido"] is not None:
                costo_field.value = ""
            linea["costo_sugerido"] = None
            costo_field.helper = None
            return
        sugerido = str(ultimo["costo_unitario"]).replace(".", ",")
        costo_field.value = sugerido
        linea["costo_sugerido"] = sugerido
        costo_field.helper = f"Ultima compra {date.fromisoformat(ultimo['fecha'][:10]).strftime('%d/%m/%y')}"

    def sugerir_costos_de_todas_las_lineas(e: ft.ControlEvent | None = None) -> None:
        for linea in lineas_form:
            if linea["tipo_dropdown"].value == TIPO_EXISTENTE:
                sugerir_costo(linea)
        page.update()

    def agregar_linea_pedido(e: ft.ControlEvent | None = None) -> None:
        lineas_form.append(crear_linea_pedido())
        refrescar_lineas_pedido()

    def quitar_linea_pedido(linea: dict) -> None:
        lineas_form.remove(linea)
        refrescar_lineas_pedido()

    def refrescar_lineas_pedido() -> None:
        contenedor_lineas_pedido.controls = [l["fila"] for l in lineas_form]
        page.update()

    def construir_producto_nuevo_pedido(linea: dict) -> dict:
        categoria_id = int(linea["categoria_dropdown"].value) if linea["categoria_dropdown"].value else None
        return {
            "codigo": (linea["codigo_field"].value or "").strip(),
            "nombre": (linea["nombre_field"].value or "").strip(),
            "categoria_id": categoria_id,
        }

    def construir_items_pedido() -> list[dict]:
        items = []
        for linea in lineas_form:
            cantidad = parsear_decimal(linea["cantidad_field"].value, "Cantidad")
            costo = parsear_decimal(linea["costo_field"].value, "Costo unitario")
            tipo = linea["tipo_dropdown"].value
            if tipo == TIPO_LIBRE:
                descripcion = (linea["descripcion_field"].value or "").strip()
                if not descripcion:
                    raise ValueError("Completa la descripcion del item libre")
                items.append({"producto_id": None, "producto_nuevo": None, "descripcion_libre": descripcion,
                              "cantidad_pedida": cantidad, "costo_pactado": costo})
            elif tipo == TIPO_NUEVO:
                items.append({"producto_id": None, "producto_nuevo": construir_producto_nuevo_pedido(linea),
                              "descripcion_libre": None, "cantidad_pedida": cantidad, "costo_pactado": costo})
            else:
                if not linea["producto_dropdown"].value:
                    raise ValueError("Elegi un producto para la linea")
                items.append({"producto_id": int(linea["producto_dropdown"].value), "producto_nuevo": None,
                              "descripcion_libre": None, "cantidad_pedida": cantidad, "costo_pactado": costo})
        return items

    def construir_items_recepcion_desde_pedido() -> list[dict]:
        """Para 'ya la tenes en mano': la recepcion es 1 a 1 con lo pedido (misma cantidad/costo)."""
        items = []
        for linea in lineas_form:
            cantidad = parsear_decimal(linea["cantidad_field"].value, "Cantidad")
            costo = parsear_decimal(linea["costo_field"].value, "Costo unitario")
            tipo = linea["tipo_dropdown"].value
            if tipo == TIPO_LIBRE:
                items.append({"producto_id": None, "producto_nuevo": None,
                              "descripcion_libre": (linea["descripcion_field"].value or "").strip(),
                              "cantidad_recibida": cantidad, "costo_unitario": costo})
            elif tipo == TIPO_NUEVO:
                items.append({"producto_id": None, "producto_nuevo": construir_producto_nuevo_pedido(linea),
                              "descripcion_libre": None, "cantidad_recibida": cantidad, "costo_unitario": costo})
            else:
                items.append({"producto_id": int(linea["producto_dropdown"].value), "producto_nuevo": None,
                              "descripcion_libre": None, "cantidad_recibida": cantidad, "costo_unitario": costo})
        return items

    def crear_linea_extra_recepcion() -> dict:
        productos_options = [
            ft.dropdown.Option(key=str(p["id"]), text=f"{p['codigo']} - {p['nombre']}")
            for p in productos_service.listar_productos(solo_activos=True)
        ]
        categorias_options = [ft.dropdown.Option(key="", text="Sin elegir")] + [
            ft.dropdown.Option(key=str(c["id"]), text=c["nombre"]) for c in categorias_service.listar_categorias()
        ]
        tipo_dropdown = ft.Dropdown(
            label="Tipo", width=170,
            options=[ft.dropdown.Option(TIPO_EXISTENTE), ft.dropdown.Option(TIPO_NUEVO), ft.dropdown.Option(TIPO_LIBRE)],
            value=TIPO_EXISTENTE,
        )
        producto_dropdown = ft.Dropdown(label="Producto", width=200, options=productos_options)
        codigo_field = ft.TextField(label="Codigo nuevo", width=110, visible=False)
        nombre_field = ft.TextField(label="Nombre nuevo", width=170, visible=False)
        categoria_dropdown = ft.Dropdown(label="Categoria (opcional)", width=150, visible=False, options=categorias_options, value="")
        descripcion_field = ft.TextField(label="Descripcion", width=200, visible=False)
        cantidad_field = ft.TextField(label="Cant. recibida", width=100, hint_text="5,000")
        costo_field = ft.TextField(label="Costo real", width=100, hint_text="5,00")
        eliminar_button = ft.IconButton(ft.Icons.DELETE, tooltip="Quitar linea")

        def cambiar_tipo(e: ft.ControlEvent) -> None:
            tipo = tipo_dropdown.value
            producto_dropdown.visible = tipo == TIPO_EXISTENTE
            codigo_field.visible = tipo == TIPO_NUEVO
            nombre_field.visible = tipo == TIPO_NUEVO
            categoria_dropdown.visible = tipo == TIPO_NUEVO
            descripcion_field.visible = tipo == TIPO_LIBRE
            page.update()

        tipo_dropdown.on_select = cambiar_tipo

        fila = ft.Row([tipo_dropdown, producto_dropdown, codigo_field, nombre_field, categoria_dropdown,
                       descripcion_field, cantidad_field, costo_field, eliminar_button])
        linea = {
            "tipo_dropdown": tipo_dropdown, "producto_dropdown": producto_dropdown,
            "codigo_field": codigo_field, "nombre_field": nombre_field, "categoria_dropdown": categoria_dropdown,
            "descripcion_field": descripcion_field, "cantidad_field": cantidad_field,
            "costo_field": costo_field, "fila": fila,
        }
        eliminar_button.on_click = lambda e: quitar_linea_extra(linea)
        return linea

    def agregar_linea_extra(e: ft.ControlEvent | None = None) -> None:
        lineas_extra_recepcion.append(crear_linea_extra_recepcion())
        refrescar_lineas_extra()

    def quitar_linea_extra(linea: dict) -> None:
        lineas_extra_recepcion.remove(linea)
        refrescar_lineas_extra()

    def refrescar_lineas_extra() -> None:
        contenedor_lineas_extra.controls = [l["fila"] for l in lineas_extra_recepcion]
        page.update()

    def construir_item_extra(linea: dict) -> dict | None:
        cantidad_texto = (linea["cantidad_field"].value or "").strip()
        if not cantidad_texto:
            return None
        cantidad = parsear_decimal(cantidad_texto, "Cantidad")
        if cantidad <= 0:
            return None
        costo = parsear_decimal(linea["costo_field"].value, "Costo real")
        tipo = linea["tipo_dropdown"].value
        if tipo == TIPO_LIBRE:
            descripcion = (linea["descripcion_field"].value or "").strip()
            if not descripcion:
                raise ValueError("Completa la descripcion del item libre")
            return {"orden_compra_item_id": None, "producto_id": None, "producto_nuevo": None,
                    "descripcion_libre": descripcion, "cantidad_recibida": cantidad, "costo_unitario": costo}
        if tipo == TIPO_NUEVO:
            codigo = (linea["codigo_field"].value or "").strip()
            nombre = (linea["nombre_field"].value or "").strip()
            categoria_id = int(linea["categoria_dropdown"].value) if linea["categoria_dropdown"].value else None
            return {"orden_compra_item_id": None, "producto_id": None,
                    "producto_nuevo": {"codigo": codigo, "nombre": nombre, "categoria_id": categoria_id},
                    "descripcion_libre": None, "cantidad_recibida": cantidad, "costo_unitario": costo}
        if not linea["producto_dropdown"].value:
            raise ValueError("Elegi un producto para la linea extra")
        return {"orden_compra_item_id": None, "producto_id": int(linea["producto_dropdown"].value),
                "producto_nuevo": None, "descripcion_libre": None, "cantidad_recibida": cantidad, "costo_unitario": costo}

    # ================= LISTA =================
    estado_filtro_dropdown = ft.Dropdown(
        label="Estado", width=190, value="", on_select=lambda e: filtrar(),
        options=[ft.dropdown.Option(key="", text="Todos")] + [ft.dropdown.Option(key=k, text=v) for k, v in ESTADOS_LABEL.items()],
    )
    buscador_field = campo_buscar("Numero o proveedor", al_cambiar=lambda: filtrar())
    desde_field = ft.TextField(label="Desde", hint_text="AAAA-MM-DD", width=140, on_submit=lambda e: aplicar_fechas())
    hasta_field = ft.TextField(label="Hasta", hint_text="AAAA-MM-DD", width=140, on_submit=lambda e: aplicar_fechas())
    # Las fechas se aplican recien con Filtrar (mientras se tipean estan incompletas): el texto y el
    # estado filtran al instante pero usan las ultimas fechas aplicadas.
    fechas = {"desde": None, "hasta": None}
    contador_texto = ft.Text("", size=12.5, color=COLOR_TEXT_SOFT)
    lista = Lista(
        [
            Columna("Numero", ancho=110, orden="numero"), Columna("Proveedor", peso=3, orden="proveedor"),
            Columna("Fecha", ancho=100, orden="fecha_creacion"), Columna("Llega", ancho=100, orden="fecha_estimada"),
            Columna("Total ($)", ancho=120, derecha=True, orden="total_estimado"), Columna("Estado", ancho=130),
            Columna("Acciones", ancho=210, derecha=True),
        ],
        al_cambiar_pagina=lambda: refrescar_lista(), nombre="ordenes", con_hijos=True,
        orden_inicial=("fecha_creacion", True), sin_datos="Ninguna orden coincide con los filtros.",
    )

    def fecha_corta(iso: str | None) -> str:
        return date.fromisoformat(iso[:10]).strftime("%d/%m/%Y") if iso else "-"

    def costo_real_texto(item: dict) -> ft.Control:
        costo_real = item["costo_real_promedio"]
        if costo_real is None:
            return ft.Text("-")
        difiere = costo_real != item["costo_pactado"]
        return ft.Text(formatear_precio(costo_real), color=COLOR_WARNING if difiere else None,
                       weight=ft.FontWeight.BOLD if difiere else None,
                       tooltip="Distinto del costo pactado" if difiere else None)

    def hijos(oc: dict) -> ft.Control:
        lineas = tabla_simple(
            ["Producto / descripcion", "Pedido", "Costo pactado", "Recibido", "Costo real (prom.)"],
            [[item["descripcion_libre"] or f"{item['producto_codigo']} - {item['producto_nombre']}",
              formatear_cantidad(item["cantidad_pedida"]), formatear_precio(item["costo_pactado"]),
              ft.Text(formatear_cantidad(item["cantidad_recibida"]),
                      color=COLOR_WARNING if item["cantidad_recibida"] > item["cantidad_pedida"] else None),
              costo_real_texto(item)] for item in oc["items"]],
            derecha=[1, 2, 3, 4],
        )
        filas_recepciones = []
        for r in recepciones_service.listar_recepciones_de_orden(oc["id"]):
            items_r = recepciones_service.listar_items_recepcion(r["id"])
            no_pedidos = sum(1 for i in items_r if i["orden_compra_item_id"] is None)
            filas_recepciones.append([
                fecha_corta(r["fecha"]), r["numero_remito"],
                f"{len(items_r)} item{'' if len(items_r) == 1 else 's'}" + (f" ({no_pedidos} no pedido)" if no_pedidos else ""),
                formatear_precio(sum((i["subtotal"] for i in items_r), Decimal("0"))), r["observacion"],
            ])
        recepciones = tabla_simple(["Fecha", "Remito", "Que llego", "Subtotal", "Observacion"], filas_recepciones,
                                   derecha=[3], vacio="Todavia no llego nada.")
        return ft.Row([
            ft.Column([rotulo("Lineas pedidas"), lineas], spacing=6),
            ft.Column([rotulo("Recepciones"), recepciones], spacing=6),
        ], spacing=28, vertical_alignment=ft.CrossAxisAlignment.START, wrap=True)

    def filtrar() -> None:
        lista.ir_al_principio()
        refrescar_lista()

    def aplicar_fechas() -> None:
        try:
            fechas["desde"], fechas["hasta"] = (
                date.fromisoformat(campo.value.strip()).isoformat() if (campo.value or "").strip() else None
                for campo in (desde_field, hasta_field)
            )
        except ValueError:
            avisar(page, "Las fechas van con formato AAAA-MM-DD (ej. 2026-10-01)", error=True)
            return
        filtrar()

    def refrescar_lista() -> None:
        proveedores = {p["id"]: p["nombre"] for p in proveedores_service.listar_proveedores()}
        todas = [dict(o, proveedor=proveedores.get(o["proveedor_id"], "?")) for o in ordenes_compra_service.listar_ordenes_compra()]
        conteo = {k: sum(1 for o in todas if o["estado"] == k) for k in ESTADOS_LABEL}
        contador_texto.value = "   ·   ".join(f"{v}: {conteo[k]}" for k, v in ESTADOS_LABEL.items())
        texto = (buscador_field.value or "").strip().lower()
        desde, hasta = fechas["desde"], fechas["hasta"]
        filtradas = [
            o for o in todas
            if texto in f"{o['numero']} {o['proveedor']}".lower()
            and (not estado_filtro_dropdown.value or o["estado"] == estado_filtro_dropdown.value)
            and (not desde or o["fecha_creacion"][:10] >= desde) and (not hasta or o["fecha_creacion"][:10] <= hasta)
        ]
        lista.mostrar(filtradas, celdas, hijos=hijos, valor_orden=lambda o, k: o.get(k))
        page.update()

    def celdas(oc: dict) -> list:
        estado = oc["estado"]
        vigente = estado in ("pendiente", "recibida_parcial")
        cancelada = "esta cancelada" if estado == "cancelada" else None
        numero = ft.Row([ft.Text(oc["numero"], weight=ft.FontWeight.W_500)] + (
            [ft.Icon(ft.Icons.BOLT, size=16, color=COLOR_WARNING, tooltip="Creada y recibida en el acto")]
            if oc["recibida_en_el_acto"] else []), spacing=2, tight=True)
        tiene_recepciones = any(i["cantidad_recibida"] for i in oc["items"])
        return [
            numero, oc["proveedor"], fecha_corta(oc["fecha_creacion"]), fecha_corta(oc["fecha_estimada"]),
            formatear_precio(oc["total_estimado"]), etiqueta_estado(*ESTADOS_ETIQUETA[estado]),
            ft.Row([
                accion_ver(ft.Icons.VISIBILITY, "Ver resumen de la orden", lambda oc=oc: ver_resumen(oc)),
                accion_abrir(ft.Icons.LOCAL_SHIPPING, "Registrar recepcion", lambda oc=oc: ir_a_recepcion(oc),
                             por_que_no=None if vigente else (cancelada or "ya llego todo")),
                accion_abrir(ft.Icons.EDIT, "Editar orden", lambda oc=oc: ir_a_formulario(oc["id"]),
                             por_que_no=cancelada or (None if estado == "pendiente" and not tiene_recepciones
                                                      else "ya tiene recepciones")),
                accion_con_motivo(
                    ft.Icons.DONE_ALL, "Dar por recibida", f"Dar por recibida {oc['numero']}",
                    "Se cierra con lo que ya llego: lo que falta deja de esperarse.",
                    lambda motivo, oc=oc: cerrar_orden(oc, motivo),
                    por_que_no=None if estado == "recibida_parcial" else (
                        cancelada or ("todavia no llego nada: si no va a llegar, cancelala" if estado == "pendiente"
                                      else "ya llego todo")),
                ),
                accion_anular(
                    "Cancelar orden", f"Cancelar {oc['numero']}",
                    f"La orden a {oc['proveedor']} deja de esperarse. Lo que ya llego queda en el stock.",
                    lambda motivo, oc=oc: cancelar_orden(oc, motivo),
                    por_que_no=None if vigente else ("ya esta cancelada" if cancelada else "ya llego todo"),
                ),
            ], spacing=0, tight=True),
        ]

    def ver_resumen(oc: dict) -> None:
        iva = formatear_porcentaje(oc["iva_porcentaje"]).replace(",00", "") if oc["iva_porcentaje"] else "0"
        ventana_info(
            page, f"{oc['numero']} · {oc['proveedor']}",
            dato("Estado", ESTADOS_LABEL[oc["estado"]] + ("  (creada y recibida en el acto)" if oc["recibida_en_el_acto"] else "")),
            dato("Fecha", fecha_corta(oc["fecha_creacion"])),
            dato("Llega", fecha_corta(oc["fecha_estimada"])),
            dato("Neto estimado", f"$ {formatear_precio(oc['neto_estimado'])}"),
            dato(f"IVA {iva} %", f"$ {formatear_precio(oc['iva_estimado'])}"),
            dato("Total estimado", f"$ {formatear_precio(oc['total_estimado'])}"),
            dato("Observacion", oc["observacion"] or "-"),
        )

    def cancelar_orden(oc: dict, motivo: str) -> str:
        ordenes_compra_service.cancelar_orden_compra(oc["id"], motivo)
        refrescar_lista()
        return f"{oc['numero']} cancelada"

    def cerrar_orden(oc: dict, motivo: str) -> str:
        ordenes_compra_service.marcar_recibida_manualmente(oc["id"], motivo)
        refrescar_lista()
        return f"{oc['numero']} dada por recibida"

    seccion_lista = ft.Column([
        barra(
            [buscador_field, estado_filtro_dropdown, desde_field, hasta_field,
             boton_secundario("Filtrar", ft.Icons.FILTER_LIST, aplicar_fechas)],
            [boton_principal("Nueva orden de compra", ft.Icons.ADD, lambda: ir_a_formulario(None))],
        ),
        contador_texto,
        lista.control,
    ], spacing=ESPACIO_PANTALLA)

    # ================= FORMULARIO (alta / edicion) =================
    form_titulo = ft.Text("Nueva orden de compra", size=15, weight=ft.FontWeight.BOLD)
    proveedor_dropdown = ft.Dropdown(label="Proveedor existente", width=250, options=[])
    proveedor_nuevo_field = ft.TextField(label="O escribi un proveedor nuevo", width=250)
    proveedor_generico_switch = ft.Switch(label="Usar proveedor generico")
    fecha_estimada_field = ft.TextField(label="Fecha estimada de entrega (opcional)", width=220, hint_text="AAAA-MM-DD")
    iva_field = ft.TextField(label="IVA del proveedor %", width=170, hint_text="21",
                             helper="Vacio = la factura no trae IVA")
    observacion_field = ft.TextField(label="Observacion (opcional)", expand=True)
    contenedor_lineas_pedido = ft.Column([])
    agregar_linea_button = ft.TextButton("+ Agregar linea", on_click=agregar_linea_pedido)

    ya_en_mano_switch = ft.Switch(label="¿Ya la tenes en mano? (se recibe en el acto)")
    remito_field = ft.TextField(label="Numero de remito (opcional)", width=220, visible=False)
    recepcion_observacion_field = ft.TextField(label="Observacion de la recepcion (opcional)", expand=True, visible=False)
    recepcion_a_credito_switch = ft.Switch(
        label="Esta compra queda a credito (genera cargo en Cuentas Corrientes)", visible=False,
    )

    def toggle_ya_en_mano(e: ft.ControlEvent) -> None:
        remito_field.visible = ya_en_mano_switch.value
        recepcion_observacion_field.visible = ya_en_mano_switch.value
        recepcion_a_credito_switch.visible = ya_en_mano_switch.value
        if ya_en_mano_switch.value and not fecha_estimada_field.value:
            fecha_estimada_field.value = date.today().isoformat()
        page.update()

    ya_en_mano_switch.on_change = toggle_ya_en_mano
    proveedor_dropdown.on_select = sugerir_costos_de_todas_las_lineas
    proveedor_generico_switch.on_change = sugerir_costos_de_todas_las_lineas

    guardar_form_texto = ft.Text("Crear orden de compra")

    def limpiar_formulario() -> None:
        nonlocal editando_oc_id
        editando_oc_id = None
        lineas_form.clear()
        refrescar_lineas_pedido()
        proveedor_dropdown.options = [
            ft.dropdown.Option(key=str(p["id"]), text=p["nombre"]) for p in proveedores_service.listar_proveedores(solo_activos=True)
        ]
        proveedor_dropdown.value = None
        proveedor_nuevo_field.value = ""
        proveedor_generico_switch.value = False
        fecha_estimada_field.value = ""
        iva_field.value = ""
        observacion_field.value = ""
        ya_en_mano_switch.value = False
        ya_en_mano_switch.visible = True
        remito_field.value = ""
        remito_field.visible = False
        recepcion_observacion_field.value = ""
        recepcion_observacion_field.visible = False
        recepcion_a_credito_switch.value = False
        recepcion_a_credito_switch.visible = False
        guardar_form_texto.value = "Crear orden de compra"
        form_titulo.value = "Nueva orden de compra"
        agregar_linea_pedido()

    def guardar_formulario() -> None:
        try:
            items = construir_items_pedido()
            proveedor_id = int(proveedor_dropdown.value) if proveedor_dropdown.value else None
            proveedor_nombre_nuevo = proveedor_nuevo_field.value or None
            usar_generico = proveedor_generico_switch.value
            fecha_estimada = (fecha_estimada_field.value or "").strip() or None
            iva_texto = (iva_field.value or "").strip()
            iva = Decimal(iva_texto.replace(",", ".")) if iva_texto else None
            observacion = observacion_field.value

            if editando_oc_id is not None:
                oc = ordenes_compra_service.actualizar_orden_compra(
                    orden_compra_id=editando_oc_id, items=items,
                    proveedor_id=proveedor_id, proveedor_nombre_nuevo=proveedor_nombre_nuevo,
                    usar_proveedor_generico=usar_generico, fecha_estimada=fecha_estimada,
                    iva_porcentaje=iva, observacion=observacion,
                )
                aviso = f"{oc['numero']} guardada"
            elif ya_en_mano_switch.value:
                items_recepcion = construir_items_recepcion_desde_pedido()
                oc = ordenes_compra_service.crear_orden_compra_recibida(
                    items=items, recepcion_items=items_recepcion,
                    proveedor_id=proveedor_id, proveedor_nombre_nuevo=proveedor_nombre_nuevo,
                    usar_proveedor_generico=usar_generico, fecha_estimada=fecha_estimada,
                    iva_porcentaje=iva, observacion=observacion,
                    recepcion_numero_remito=remito_field.value, recepcion_observacion=recepcion_observacion_field.value,
                    a_credito=recepcion_a_credito_switch.value,
                )
                aviso = f"{oc['numero']} creada y recibida en el acto"
            else:
                oc = ordenes_compra_service.crear_orden_compra(
                    items=items, proveedor_id=proveedor_id, proveedor_nombre_nuevo=proveedor_nombre_nuevo,
                    usar_proveedor_generico=usar_generico, fecha_estimada=fecha_estimada,
                    iva_porcentaje=iva, observacion=observacion,
                )
                aviso = f"{oc['numero']} creada"
        except ERRORES_PARA_AVISAR as ex:
            avisar(page, str(ex), error=True)
            return
        ir_a_lista()
        avisar(page, aviso)

    seccion_formulario = ft.Column(
        [
            tarjeta(
                ft.Row([proveedor_dropdown, proveedor_nuevo_field, proveedor_generico_switch]),
                ft.Row([fecha_estimada_field, iva_field]),
                ft.Row([observacion_field]),
                titulo=form_titulo,
                subtitulo="Al guardar o cancelar volves a la lista, donde la dejaste.",
            ),
            tarjeta(contenedor_lineas_pedido, agregar_linea_button, titulo="Lineas"),
            tarjeta(
                ya_en_mano_switch,
                ft.Row([remito_field, recepcion_observacion_field]),
                recepcion_a_credito_switch,
            ),
            botones_formulario(guardar_form_texto, guardar_formulario, lambda: ir_a_lista()),
        ],
        visible=False,
        spacing=ESPACIO_PANTALLA,
    )

    def ir_a_formulario(oc_id: int | None) -> None:
        nonlocal editando_oc_id
        limpiar_formulario()
        if oc_id is not None:
            editando_oc_id = oc_id
            oc = ordenes_compra_service.obtener_orden_compra(oc_id)
            form_titulo.value = f"Editar {oc['numero']}"
            guardar_form_texto.value = "Guardar cambios"
            proveedor_dropdown.value = str(oc["proveedor_id"])
            fecha_estimada_field.value = oc["fecha_estimada"] or ""
            iva_field.value = formatear_porcentaje(oc["iva_porcentaje"]).replace(",00", "") if oc["iva_porcentaje"] else ""
            observacion_field.value = oc["observacion"] or ""
            ya_en_mano_switch.visible = False
            lineas_form.clear()
            for item in oc["items"]:
                linea = crear_linea_pedido()
                if item["descripcion_libre"] is not None:
                    linea["tipo_dropdown"].value = TIPO_LIBRE
                    linea["producto_dropdown"].visible = False
                    linea["descripcion_field"].visible = True
                    linea["descripcion_field"].value = item["descripcion_libre"]
                else:
                    linea["producto_dropdown"].value = str(item["producto_id"])
                linea["cantidad_field"].value = str(item["cantidad_pedida"])
                linea["costo_field"].value = str(item["costo_pactado"])
                lineas_form.append(linea)
            refrescar_lineas_pedido()
        mostrar_seccion(seccion_formulario)

    # ================= RECEPCION (pantalla aparte) =================
    recepcion_titulo = ft.Text("", size=15, weight=ft.FontWeight.BOLD)
    seccion_recepcion_numero_remito = ft.TextField(label="Numero de remito (opcional)", width=220)
    seccion_recepcion_observacion = ft.TextField(label="Observacion (opcional)", expand=True)
    seccion_recepcion_a_credito_switch = ft.Switch(label="Esta compra queda a credito (genera cargo en Cuentas Corrientes)")
    contenedor_pendientes_recepcion = ft.Column([])
    contenedor_lineas_extra = ft.Column([])
    agregar_extra_button = ft.TextButton("+ Agregar item extra (no pedido)", on_click=agregar_linea_extra)
    confirmar_recepcion_texto = ft.Text("Confirmar recepcion")
    campos_pendientes: list[dict] = []

    def ir_a_recepcion(oc: dict) -> None:
        nonlocal detalle_oc_id
        detalle_oc_id = oc["id"]
        oc = ordenes_compra_service.obtener_orden_compra(oc["id"])
        recepcion_titulo.value = f"Registrar recepcion: {oc['numero']}"
        campos_pendientes.clear()
        filas_pendientes = []
        for item in oc["items"]:
            pendiente = item["cantidad_pedida"] - item["cantidad_recibida"]
            if pendiente <= 0:
                continue
            nombre = item["descripcion_libre"] or f"{item['producto_codigo']} - {item['producto_nombre']}"
            cantidad_field = ft.TextField(label="Cant. a recibir", width=120, value=str(pendiente))
            costo_field = ft.TextField(label="Costo real", width=120, value=str(item["costo_pactado"]))
            campos_pendientes.append({
                "orden_compra_item_id": item["id"], "producto_id": item["producto_id"],
                "descripcion_libre": item["descripcion_libre"],
                "cantidad_field": cantidad_field, "costo_field": costo_field,
            })
            filas_pendientes.append(ft.Row([ft.Text(nombre, width=300), cantidad_field, costo_field]))
        contenedor_pendientes_recepcion.controls = filas_pendientes
        lineas_extra_recepcion.clear()
        refrescar_lineas_extra()
        seccion_recepcion_numero_remito.value = ""
        seccion_recepcion_observacion.value = ""
        seccion_recepcion_a_credito_switch.value = False
        mostrar_seccion(seccion_recepcion)

    def confirmar_recepcion() -> None:
        try:
            items = []
            for campo in campos_pendientes:
                cantidad_texto = (campo["cantidad_field"].value or "").strip()
                if not cantidad_texto:
                    continue
                cantidad = parsear_decimal(cantidad_texto, "Cantidad a recibir")
                if cantidad <= 0:
                    continue
                costo = parsear_decimal(campo["costo_field"].value, "Costo real")
                items.append({
                    "orden_compra_item_id": campo["orden_compra_item_id"],
                    "producto_id": campo["producto_id"], "producto_nuevo": None,
                    "descripcion_libre": campo["descripcion_libre"],
                    "cantidad_recibida": cantidad, "costo_unitario": costo,
                })
            for linea in lineas_extra_recepcion:
                item_extra = construir_item_extra(linea)
                if item_extra is not None:
                    items.append(item_extra)
            recepciones_service.confirmar_recepcion(
                orden_compra_id=detalle_oc_id, items=items,
                numero_remito=seccion_recepcion_numero_remito.value,
                observacion=seccion_recepcion_observacion.value,
                a_credito=seccion_recepcion_a_credito_switch.value,
            )
        except ERRORES_PARA_AVISAR as ex:
            avisar(page, str(ex), error=True)
            return
        a_credito = seccion_recepcion_a_credito_switch.value
        ir_a_lista()
        avisar(page, "Recepcion registrada" + (" (a credito: se genero el cargo en Cuentas Corrientes)" if a_credito else ""))

    seccion_recepcion = ft.Column([
        tarjeta(
            contenedor_pendientes_recepcion,
            titulo=recepcion_titulo,
            subtitulo="Cantidad que llega ahora por linea (dejar en 0 lo que no llega). Al confirmar o cancelar volves a la lista.",
        ),
        tarjeta(contenedor_lineas_extra, agregar_extra_button, titulo="Items extra (no pedidos)"),
        tarjeta(ft.Row([seccion_recepcion_numero_remito, seccion_recepcion_observacion]), seccion_recepcion_a_credito_switch),
        botones_formulario(confirmar_recepcion_texto, confirmar_recepcion, lambda: ir_a_lista()),
    ], visible=False, spacing=ESPACIO_PANTALLA)

    # ================= NAVEGACION =================
    def mostrar_seccion(seccion: ft.Control) -> None:
        for s in (seccion_lista, seccion_formulario, seccion_recepcion):
            s.visible = s is seccion
        page.update()

    def ir_a_lista() -> None:
        mostrar_seccion(seccion_lista)
        refrescar_lista()

    refrescar_lista()

    return ft.Column(
        [encabezado_pantalla("Ordenes de Compra", "Lo que se le pide a cada proveedor y lo que va llegando (recepciones)."),
         seccion_lista, seccion_formulario, seccion_recepcion],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=ESPACIO_PANTALLA,
    )
