from decimal import Decimal, InvalidOperation

import flet as ft

from app.services import categorias_service, productos_service, proveedores_service
from app.shared.money import formatear_cantidad, formatear_precio
from app.ui.componentes import (
    ESPACIO_PANTALLA,
    ERRORES_PARA_AVISAR,
    TONO_NO,
    TONO_OK,
    Columna,
    Lista,
    accion_abrir,
    accion_cambiar,
    avisar,
    barra,
    boton_principal,
    botones_formulario,
    campo_buscar,
    encabezado_pantalla,
    etiqueta_estado,
    tarjeta,
)
from app.ui.theme import COLOR_DANGER
from app.shared import textos
from app.ui.campos import aplicar_formato_texto


def ProductosView(page: ft.Page) -> ft.Control:
    editando: dict | None = None

    # ================= Lista =================
    buscador_field = campo_buscar("Nombre o codigo", al_cambiar=lambda: filtrar())
    categoria_filtro = ft.Dropdown(label="Categoria", width=200, value="", on_select=lambda e: filtrar())
    lista = Lista(
        [
            Columna("Codigo", ancho=90, orden="codigo"), Columna("Nombre", peso=3, orden="nombre"),
            Columna("Marca", peso=2, orden="marca"), Columna("Categoria", peso=2), Columna("Proveedor", peso=3),
            Columna("Costo ($)", ancho=100, derecha=True, orden="costo"),
            Columna("Venta ($)", ancho=100, derecha=True, orden="venta"),
            Columna("Stock", ancho=80, derecha=True, orden="stock"), Columna("Stock min.", ancho=80, derecha=True),
            Columna("Estado", ancho=80), Columna("Acciones", ancho=84, derecha=True),
        ],
        al_cambiar_pagina=lambda: refrescar(), nombre="productos", orden_inicial=("nombre", False),
        sin_datos="Ningun producto coincide con la busqueda.",
    )

    def filtrar() -> None:
        lista.ir_al_principio()
        refrescar()

    def refrescar() -> None:
        categorias = {c["id"]: c["nombre"] for c in categorias_service.listar_categorias()}
        proveedores = {p["id"]: p["nombre"] for p in proveedores_service.listar_proveedores()}
        resultado = productos_service.listar_productos_pagina(
            pagina=lista.pagina, tamano_pagina=lista.por_pagina, texto=buscador_field.value or None,
            categoria_id=int(categoria_filtro.value) if categoria_filtro.value else None,
            orden=lista.orden, descendente=lista.descendente,
        )

        def celdas(p: dict) -> list:
            stock_bajo = p["stock_minimo"] > 0 and p["stock_actual"] < p["stock_minimo"]
            return [
                ft.Text(p["codigo"], size=12.5, color=None, font_family="Consolas"),
                p["nombre"], p["marca"], categorias.get(p["categoria_id"], "?"),
                proveedores.get(p["proveedor_id"]) if p["proveedor_id"] else None,
                formatear_precio(p["precio_costo"]), formatear_precio(p["precio_venta"]),
                ft.Text(formatear_cantidad(p["stock_actual"]), color=COLOR_DANGER if stock_bajo else None,
                        weight=ft.FontWeight.BOLD if stock_bajo else None,
                        tooltip="Por debajo del stock minimo" if stock_bajo else None),
                formatear_cantidad(p["stock_minimo"]),
                etiqueta_estado("Activo", TONO_OK) if p["activo"] else etiqueta_estado("Inactivo", TONO_NO),
                ft.Row([
                    accion_abrir(ft.Icons.EDIT, "Editar producto", lambda p=p: ir_a_formulario(p)),
                    accion_cambiar(ft.Icons.POWER_SETTINGS_NEW, "Desactivar producto" if p["activo"] else "Activar producto",
                                   lambda p=p: cambiar_activo(p)),
                ], spacing=0, tight=True),
            ]

        lista.mostrar(resultado["items"], celdas, total=resultado["total"])
        page.update()

    def cambiar_activo(p: dict) -> str:
        productos_service.cambiar_activo(p["id"], not p["activo"])
        refrescar()
        return (f"{p['nombre']}: activado" if not p["activo"]
                else f"{p['nombre']}: desactivado (ya no se ofrece en la caja ni en las compras)")

    seccion_lista = ft.Column([
        barra(
            [buscador_field, categoria_filtro],
            [boton_principal("Nuevo producto", ft.Icons.ADD, lambda: ir_a_formulario(None))],
        ),
        lista.control,
    ], spacing=ESPACIO_PANTALLA)

    # ================= Formulario (alta / edicion) =================
    form_titulo = ft.Text("", size=15, weight=ft.FontWeight.BOLD)
    guardar_texto = ft.Text("")
    codigo_field = ft.TextField(label="Codigo *", width=160)
    nombre_field = ft.TextField(label="Nombre *", expand=True)
    unidad_field = ft.TextField(label="Unidad *", hint_text="kg, unidad, litro...", width=160)
    categoria_dropdown = ft.Dropdown(label="Categoria *", width=220, options=[])
    precio_costo_field = ft.TextField(label="Precio costo", hint_text="17,45", width=160)
    precio_venta_field = ft.TextField(label="Precio venta", hint_text="21,00", width=160)
    stock_minimo_field = ft.TextField(label="Stock minimo", hint_text="5,000", width=160)
    marca_field = ft.TextField(label="Marca (opcional)", expand=True)
    codigo_barra_field = ft.TextField(label="Codigo de barras (opcional)", width=240)
    proveedor_dropdown = ft.Dropdown(label="Proveedor (opcional)", width=280, options=[], value="")
    descripcion_field = ft.TextField(label="Descripcion (opcional)", multiline=True, min_lines=1, max_lines=3, expand=True)
    aplicar_formato_texto(textos.mayusculas, codigo_field, nombre_field)

    def parsear_decimal(valor: str, etiqueta: str) -> Decimal:
        try:
            return Decimal((valor or "0").replace(",", "."))
        except InvalidOperation as exc:
            raise ValueError(f"'{etiqueta}' no es un numero valido") from exc

    def ir_a_formulario(producto: dict | None) -> None:
        nonlocal editando
        editando = productos_service.obtener_producto(producto["id"]) if producto else None
        categoria_dropdown.options = [ft.dropdown.Option(key=str(c["id"]), text=c["nombre"])
                                      for c in categorias_service.listar_categorias()]
        proveedor_dropdown.options = [ft.dropdown.Option(key="", text="Sin proveedor")] + [
            ft.dropdown.Option(key=str(p["id"]), text=p["nombre"]) for p in proveedores_service.listar_proveedores(solo_activos=True)
        ]
        p = editando or {}
        form_titulo.value = f"Editar producto: {p['nombre']}" if editando else "Nuevo producto"
        guardar_texto.value = "Guardar cambios" if editando else "Agregar producto"
        codigo_field.value = p.get("codigo", "")
        nombre_field.value = p.get("nombre", "")
        unidad_field.value = p.get("unidad", "")
        precio_costo_field.value = str(p["precio_costo"]) if editando else ""
        precio_venta_field.value = str(p["precio_venta"]) if editando else ""
        stock_minimo_field.value = str(p["stock_minimo"]) if editando else ""
        marca_field.value = p.get("marca") or ""
        descripcion_field.value = p.get("descripcion") or ""
        codigo_barra_field.value = p.get("codigo_barra") or ""
        categoria_dropdown.value = str(p["categoria_id"]) if editando else None
        proveedor_dropdown.value = str(p["proveedor_id"]) if editando and p["proveedor_id"] else ""
        seccion_lista.visible = False
        seccion_formulario.visible = True
        page.update()

    def volver_a_lista() -> None:
        seccion_formulario.visible = False
        seccion_lista.visible = True
        refrescar()

    def guardar() -> None:
        try:
            if not categoria_dropdown.value:
                raise ValueError("Elegi una categoria")
            datos = dict(
                codigo=codigo_field.value or "", nombre=nombre_field.value or "",
                categoria_id=int(categoria_dropdown.value), unidad=unidad_field.value or "",
                precio_costo=parsear_decimal(precio_costo_field.value, "Precio costo"),
                precio_venta=parsear_decimal(precio_venta_field.value, "Precio venta"),
                stock_minimo=parsear_decimal(stock_minimo_field.value, "Stock minimo"),
                marca=marca_field.value, descripcion=descripcion_field.value, codigo_barra=codigo_barra_field.value,
                proveedor_id=int(proveedor_dropdown.value) if proveedor_dropdown.value else None,
            )
            if editando is None:
                producto = productos_service.crear_producto(**datos)
                aviso = f"Producto '{producto['nombre']}' agregado"
            else:
                producto = productos_service.actualizar_producto(producto_id=editando["id"], activo=editando["activo"], **datos)
                aviso = f"Producto '{producto['nombre']}' guardado"
        except ERRORES_PARA_AVISAR as ex:
            avisar(page, str(ex), error=True)
            return
        volver_a_lista()
        avisar(page, aviso)

    seccion_formulario = ft.Column([
        tarjeta(
            ft.Row([codigo_field, nombre_field, unidad_field]),
            ft.Row([categoria_dropdown, precio_costo_field, precio_venta_field, stock_minimo_field]),
            ft.Row([marca_field, codigo_barra_field, proveedor_dropdown]),
            ft.Row([descripcion_field]),
            botones_formulario(guardar_texto, guardar, volver_a_lista),
            titulo=form_titulo,
            subtitulo="Al guardar o cancelar volves a la lista, donde la dejaste.",
        ),
    ], visible=False)

    categoria_filtro.options = [ft.dropdown.Option(key="", text="Todas")] + [
        ft.dropdown.Option(key=str(c["id"]), text=c["nombre"]) for c in categorias_service.listar_categorias()
    ]
    refrescar()
    return ft.Column(
        [
            encabezado_pantalla("Productos", "Los articulos que vende el negocio, con su costo, precio y stock minimo."),
            seccion_lista,
            seccion_formulario,
        ],
        expand=True, scroll=ft.ScrollMode.AUTO, spacing=ESPACIO_PANTALLA,
    )
