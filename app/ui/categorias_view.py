import flet as ft

from app.services import categorias_service, productos_service
from app.ui.componentes import (
    ESPACIO_PANTALLA,
    ERRORES_PARA_AVISAR,
    Columna,
    Lista,
    accion_abrir,
    avisar,
    barra,
    boton_principal,
    botones_formulario,
    campo_buscar,
    encabezado_pantalla,
    tarjeta,
)
from app.shared import textos
from app.ui.campos import aplicar_formato_texto


def CategoriasView(page: ft.Page) -> ft.Control:
    editando: dict | None = None

    # ================= Lista =================
    buscador_field = campo_buscar("Nombre de la categoria", al_cambiar=lambda: filtrar())
    lista = Lista(
        [Columna("Nombre", peso=3, orden="nombre"), Columna("Productos", ancho=100, derecha=True, orden="productos"),
         Columna("Acciones", ancho=60, derecha=True)],
        al_cambiar_pagina=lambda: refrescar(), nombre="categorias", orden_inicial=("nombre", False),
        sin_datos="Ninguna categoria coincide con la busqueda.",
    )

    def filtrar() -> None:
        lista.ir_al_principio()
        refrescar()

    def refrescar() -> None:
        cantidades: dict[int, int] = {}
        for p in productos_service.listar_productos():
            cantidades[p["categoria_id"]] = cantidades.get(p["categoria_id"], 0) + 1
        texto = (buscador_field.value or "").strip().lower()
        categorias = [dict(c, productos=cantidades.get(c["id"], 0)) for c in categorias_service.listar_categorias()
                      if texto in c["nombre"].lower()]
        lista.mostrar(categorias, lambda c: [
            c["nombre"], str(c["productos"]),
            accion_abrir(ft.Icons.EDIT, "Editar categoria", lambda c=c: ir_a_formulario(c)),
        ])
        page.update()

    seccion_lista = ft.Column([
        barra([buscador_field], [boton_principal("Nueva categoria", ft.Icons.ADD, lambda: ir_a_formulario(None))]),
        lista.control,
    ], spacing=ESPACIO_PANTALLA)

    # ================= Formulario (alta / edicion) =================
    form_titulo = ft.Text("", size=15, weight=ft.FontWeight.BOLD)
    guardar_texto = ft.Text("")
    nombre_field = ft.TextField(label="Nombre *", width=360)
    aplicar_formato_texto(textos.mayusculas, nombre_field)

    def ir_a_formulario(categoria: dict | None) -> None:
        nonlocal editando
        editando = categoria
        form_titulo.value = f"Editar categoria: {categoria['nombre']}" if categoria else "Nueva categoria"
        guardar_texto.value = "Guardar cambios" if categoria else "Agregar categoria"
        nombre_field.value = categoria["nombre"] if categoria else ""
        seccion_lista.visible = False
        seccion_formulario.visible = True
        page.update()

    def volver_a_lista() -> None:
        seccion_formulario.visible = False
        seccion_lista.visible = True
        refrescar()

    def guardar() -> None:
        try:
            if editando is None:
                categoria = categorias_service.crear_categoria(nombre_field.value or "")
                aviso = f"Categoria '{categoria['nombre']}' agregada"
            else:
                categoria = categorias_service.actualizar_categoria(editando["id"], nombre_field.value or "")
                aviso = f"Categoria '{categoria['nombre']}' guardada"
        except ERRORES_PARA_AVISAR as ex:
            avisar(page, str(ex), error=True)
            return
        volver_a_lista()
        avisar(page, aviso)

    seccion_formulario = ft.Column([
        tarjeta(
            ft.Row([nombre_field]),
            botones_formulario(guardar_texto, guardar, volver_a_lista),
            titulo=form_titulo,
            subtitulo="Al guardar o cancelar volves a la lista, donde la dejaste.",
        ),
    ], visible=False)

    refrescar()
    return ft.Column(
        [
            encabezado_pantalla("Categorias", "Agrupan los productos (Limpieza, Perfumeria, Descartables...)."),
            seccion_lista,
            seccion_formulario,
        ],
        expand=True, scroll=ft.ScrollMode.AUTO, spacing=ESPACIO_PANTALLA,
    )
