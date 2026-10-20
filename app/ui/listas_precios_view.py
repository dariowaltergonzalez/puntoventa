from decimal import Decimal, InvalidOperation

import flet as ft

from app.services import categorias_service, listas_precios_service, productos_service
from app.shared.money import formatear_porcentaje, formatear_precio
from app.ui.campos import FILTRO_DECIMALES_CON_SIGNO, aplicar_mascara_moneda, parsear_decimal_ar_opcional
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
    rotulo,
    tabla_simple,
    tarjeta,
)
from app.ui.theme import COLOR_TEXT_SOFT


def _decimal_opcional(valor: str | None, etiqueta: str) -> Decimal | None:
    texto = (valor or "").strip()
    if not texto:
        return None
    try:
        return Decimal(texto.replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"{etiqueta} invalido") from None


def _porcentaje(valor: Decimal | None) -> str | None:
    return None if valor is None else f"{formatear_porcentaje(valor)} %"


def ListasPreciosView(page: ft.Page) -> ft.Control:
    editando: dict | None = None

    # ================= Lista =================
    buscador_field = campo_buscar("Nombre de la lista", al_cambiar=lambda: filtrar())
    lista = Lista(
        [
            Columna("Nombre", peso=3, orden="nombre"), Columna("% general", ancho=110, derecha=True, orden="porcentaje_general"),
            Columna("Por categoria", ancho=120, derecha=True), Columna("Precios a mano", ancho=130, derecha=True),
            Columna("Estado", ancho=90), Columna("Acciones", ancho=84, derecha=True),
        ],
        al_cambiar_pagina=lambda: refrescar(), nombre="listas", con_hijos=True, orden_inicial=("nombre", False),
        sin_datos="Ninguna lista coincide con la busqueda.",
    )

    def filtrar() -> None:
        lista.ir_al_principio()
        refrescar()

    def hijos(l: dict) -> ft.Control:
        return ft.Row([
            ft.Column([rotulo("% especial por categoria"), tabla_simple(
                ["Categoria", "%"], [[c["categoria_nombre"], _porcentaje(c["porcentaje"])] for c in l["categorias"]],
                derecha=[1], vacio="Ninguna: todas usan el % general.")], spacing=6),
            ft.Column([rotulo("Precio a mano por producto"), tabla_simple(
                ["Producto", "Precio"], [[f"{p['producto_codigo']} - {p['producto_nombre']}", formatear_precio(p["precio_manual"])]
                                         for p in l["productos"]], derecha=[1], vacio="Ninguno.")], spacing=6),
        ], spacing=28, vertical_alignment=ft.CrossAxisAlignment.START, wrap=True)

    def refrescar() -> None:
        texto = (buscador_field.value or "").strip().lower()
        listas = [listas_precios_service.obtener_lista(l["id"]) for l in listas_precios_service.listar_listas()
                  if texto in l["nombre"].lower()]
        lista.mostrar(listas, lambda l: [
            l["nombre"], _porcentaje(l["porcentaje_general"]), str(len(l["categorias"])), str(len(l["productos"])),
            etiqueta_estado("Activa", TONO_OK) if l["activo"] else etiqueta_estado("Inactiva", TONO_NO),
            ft.Row([
                accion_abrir(ft.Icons.EDIT, "Editar lista", lambda l=l: ir_a_formulario(l)),
                accion_cambiar(ft.Icons.POWER_SETTINGS_NEW, "Desactivar lista" if l["activo"] else "Activar lista",
                               lambda l=l: cambiar_activo(l)),
            ], spacing=0, tight=True),
        ], hijos=hijos)
        page.update()

    def cambiar_activo(l: dict) -> str:
        listas_precios_service.cambiar_activo(l["id"], not l["activo"])
        refrescar()
        return (f"{l['nombre']}: activada" if not l["activo"]
                else f"{l['nombre']}: desactivada (ya no se ofrece para asignar a clientes)")

    seccion_lista = ft.Column([
        barra([buscador_field], [boton_principal("Nueva lista de precios", ft.Icons.ADD, lambda: ir_a_formulario(None))]),
        lista.control,
    ], spacing=ESPACIO_PANTALLA)

    # ================= Formulario: datos de la lista =================
    form_titulo = ft.Text("", size=15, weight=ft.FontWeight.BOLD)
    guardar_texto = ft.Text("")
    nombre_field = ft.TextField(label="Nombre *", width=300)
    porcentaje_general_field = ft.TextField(label="% general (opcional)", width=220, hint_text="-15 descuento, 15 recargo",
                                            input_filter=FILTRO_DECIMALES_CON_SIGNO)

    def ir_a_formulario(l: dict | None) -> None:
        nonlocal editando
        editando = listas_precios_service.obtener_lista(l["id"]) if l else None
        form_titulo.value = f"Editar lista: {editando['nombre']}" if editando else "Nueva lista de precios"
        guardar_texto.value = "Guardar cambios" if editando else "Crear lista"
        nombre_field.value = editando["nombre"] if editando else ""
        porcentaje_general_field.value = (str(editando["porcentaje_general"])
                                          if editando and editando["porcentaje_general"] is not None else "")
        tarjeta_categorias.visible = tarjeta_productos.visible = editando is not None
        aviso_hijos.visible = editando is None
        if editando:
            refrescar_hijos()
        seccion_lista.visible = False
        seccion_formulario.visible = True
        page.update()

    def volver_a_lista() -> None:
        seccion_formulario.visible = False
        seccion_lista.visible = True
        refrescar()

    def guardar() -> None:
        try:
            porcentaje = _decimal_opcional(porcentaje_general_field.value, "El % general")
            if editando is None:
                l = listas_precios_service.crear_lista(nombre_field.value or "", porcentaje)
                aviso = f"Lista '{l['nombre']}' creada. Para sumarle % por categoria o precios a mano, usa el lapiz."
            else:
                l = listas_precios_service.actualizar_lista(editando["id"], nombre_field.value or "", porcentaje, editando["activo"])
                aviso = f"Lista '{l['nombre']}' guardada"
        except ERRORES_PARA_AVISAR as ex:
            avisar(page, str(ex), error=True)
            return
        volver_a_lista()
        avisar(page, aviso)

    # ================= Formulario: hijos (se guardan al instante) =================
    categorias_tabla = ft.Column()
    categoria_dropdown = ft.Dropdown(label="Categoria", width=220, options=[])
    categoria_porcentaje_field = ft.TextField(label="%", width=120, input_filter=FILTRO_DECIMALES_CON_SIGNO)
    productos_tabla = ft.Column()
    producto_dropdown = ft.Dropdown(label="Producto", width=320, options=[])
    producto_precio_field = ft.TextField(label="Precio a mano", width=150)
    aplicar_mascara_moneda(producto_precio_field)

    def quitar(texto: str):
        return lambda funcion: ft.IconButton(ft.Icons.CLOSE, icon_size=18, icon_color=COLOR_TEXT_SOFT, tooltip=texto,
                                             on_click=lambda e: con_aviso(funcion))

    def refrescar_hijos() -> None:
        l = listas_precios_service.obtener_lista(editando["id"])
        categorias_tabla.controls = [tabla_simple(
            ["Categoria", "%", ""],
            [[c["categoria_nombre"], _porcentaje(c["porcentaje"]), quitar("Quitar % de la categoria")(
                lambda c=c: (listas_precios_service.quitar_porcentaje_categoria(editando["id"], c["categoria_id"]),
                             f"{c['categoria_nombre']}: vuelve al % general")[1])] for c in l["categorias"]],
            derecha=[1], vacio="Ninguna: todas usan el % general.",
        )]
        productos_tabla.controls = [tabla_simple(
            ["Producto", "Precio", ""],
            [[f"{p['producto_codigo']} - {p['producto_nombre']}", formatear_precio(p["precio_manual"]), quitar("Quitar precio a mano")(
                lambda p=p: (listas_precios_service.quitar_precio_producto(editando["id"], p["producto_id"]),
                             f"{p['producto_nombre']}: sin precio a mano")[1])] for p in l["productos"]],
            derecha=[1], vacio="Ninguno.",
        )]
        categoria_dropdown.options = [ft.dropdown.Option(key=str(c["id"]), text=c["nombre"]) for c in categorias_service.listar_categorias()]
        producto_dropdown.options = [ft.dropdown.Option(key=str(p["id"]), text=f"{p['codigo']} - {p['nombre']}")
                                     for p in productos_service.listar_productos(solo_activos=True)]

    def con_aviso(funcion) -> None:
        try:
            aviso = funcion()
        except ERRORES_PARA_AVISAR as ex:
            avisar(page, str(ex), error=True)
            return
        refrescar_hijos()
        page.update()
        if aviso:
            avisar(page, aviso)

    def agregar_categoria() -> str:
        if not categoria_dropdown.value:
            raise ValueError("Elegi una categoria")
        porcentaje = _decimal_opcional(categoria_porcentaje_field.value, "El %")
        if porcentaje is None:
            raise ValueError("Carga el % para esa categoria")
        listas_precios_service.establecer_porcentaje_categoria(editando["id"], int(categoria_dropdown.value), porcentaje)
        categoria_porcentaje_field.value = ""
        return "% por categoria guardado"

    def agregar_producto() -> str:
        if not producto_dropdown.value:
            raise ValueError("Elegi un producto")
        precio = parsear_decimal_ar_opcional(producto_precio_field.value, "El precio a mano")
        if precio is None:
            raise ValueError("Carga el precio a mano")
        listas_precios_service.establecer_precio_producto(editando["id"], int(producto_dropdown.value), precio)
        producto_precio_field.value = ""
        return "Precio a mano guardado"

    tarjeta_categorias = tarjeta(
        categorias_tabla,
        ft.Row([categoria_dropdown, categoria_porcentaje_field,
                ft.OutlinedButton("Agregar / cambiar", icon=ft.Icons.ADD, on_click=lambda e: con_aviso(agregar_categoria))],
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
        titulo="% especial por categoria", subtitulo="Pisa el % general para esa categoria. Se guarda al instante.",
    )
    tarjeta_productos = tarjeta(
        productos_tabla,
        ft.Row([producto_dropdown, producto_precio_field,
                ft.OutlinedButton("Agregar / cambiar", icon=ft.Icons.ADD, on_click=lambda e: con_aviso(agregar_producto))],
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
        titulo="Precio a mano por producto", subtitulo="Pisa todo lo demas para ese producto. Se guarda al instante.",
    )
    aviso_hijos = ft.Text("Los % por categoria y los precios a mano se agregan despues de crear la lista, con el lapiz.",
                          size=12.5, color=COLOR_TEXT_SOFT)

    seccion_formulario = ft.Column([
        tarjeta(
            ft.Row([nombre_field, porcentaje_general_field]),
            aviso_hijos,
            botones_formulario(guardar_texto, guardar, volver_a_lista),
            titulo=form_titulo,
            subtitulo="Al guardar o cancelar volves a la lista, donde la dejaste.",
        ),
        tarjeta_categorias,
        tarjeta_productos,
    ], visible=False, spacing=ESPACIO_PANTALLA)

    refrescar()
    return ft.Column(
        [
            encabezado_pantalla("Listas de precios", "Precios distintos para distintos clientes: un % general, por categoria o a mano por producto."),
            seccion_lista,
            seccion_formulario,
        ],
        expand=True, scroll=ft.ScrollMode.AUTO, spacing=ESPACIO_PANTALLA,
    )
