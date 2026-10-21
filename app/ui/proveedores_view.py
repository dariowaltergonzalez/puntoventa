import flet as ft

from app.services import proveedores_service
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
from app.shared import textos
from app.ui.campos import aplicar_formato_texto


def ProveedoresView(page: ft.Page) -> ft.Control:
    editando: dict | None = None

    # ================= Lista =================
    buscador_field = campo_buscar("Nombre, CUIT o contacto", al_cambiar=lambda: filtrar())
    estado_filtro = ft.Dropdown(label="Estado", width=160, value="", on_select=lambda e: filtrar(), options=[
        ft.dropdown.Option(key="", text="Todos"), ft.dropdown.Option(key="activos", text="Activos"),
        ft.dropdown.Option(key="inactivos", text="Inactivos"),
    ])
    lista = Lista(
        [
            Columna("Nombre", peso=3, orden="nombre"), Columna("CUIT", ancho=130, orden="cuit"),
            Columna("Contacto", peso=2, orden="contacto"), Columna("Telefono", peso=2), Columna("Email", peso=3),
            Columna("Estado", ancho=90), Columna("Acciones", ancho=84, derecha=True),
        ],
        al_cambiar_pagina=lambda: refrescar(), nombre="proveedores", orden_inicial=("nombre", False),
        sin_datos="Ningun proveedor coincide con la busqueda.",
    )

    def filtrar() -> None:
        lista.ir_al_principio()
        refrescar()

    def refrescar() -> None:
        texto = (buscador_field.value or "").strip().lower()
        proveedores = [
            p for p in proveedores_service.listar_proveedores()
            if texto in f"{p['nombre']} {p['cuit'] or ''} {p['contacto'] or ''}".lower()
            and (estado_filtro.value != "activos" or p["activo"])
            and (estado_filtro.value != "inactivos" or not p["activo"])
        ]
        lista.mostrar(proveedores, lambda p: [
            p["nombre"], p["cuit"], p["contacto"], p["telefono"], p["email"],
            etiqueta_estado("Activo", TONO_OK) if p["activo"] else etiqueta_estado("Inactivo", TONO_NO),
            ft.Row([
                accion_abrir(ft.Icons.EDIT, "Editar proveedor", lambda p=p: ir_a_formulario(p)),
                accion_cambiar(ft.Icons.POWER_SETTINGS_NEW, "Desactivar proveedor" if p["activo"] else "Activar proveedor",
                               lambda p=p: cambiar_activo(p)),
            ], spacing=0, tight=True),
        ])
        page.update()

    def cambiar_activo(p: dict) -> str:
        proveedores_service.cambiar_activo(p["id"], not p["activo"])
        refrescar()
        return (f"{p['nombre']}: activado" if not p["activo"]
                else f"{p['nombre']}: desactivado (ya no se ofrece en las compras)")

    seccion_lista = ft.Column([
        barra([buscador_field, estado_filtro],
              [boton_principal("Nuevo proveedor", ft.Icons.ADD, lambda: ir_a_formulario(None))]),
        lista.control,
    ], spacing=ESPACIO_PANTALLA)

    # ================= Formulario (alta / edicion) =================
    form_titulo = ft.Text("", size=15, weight=ft.FontWeight.BOLD)
    guardar_texto = ft.Text("")
    nombre_field = ft.TextField(label="Nombre *", expand=True)
    cuit_field = ft.TextField(label="CUIT (opcional)", width=200)
    contacto_field = ft.TextField(label="Contacto (opcional)", expand=True)
    telefono_field = ft.TextField(label="Telefono (opcional)", width=220)
    email_field = ft.TextField(label="Email (opcional)", expand=True)
    direccion_field = ft.TextField(label="Direccion (opcional)", expand=True)
    observaciones_field = ft.TextField(label="Observaciones (opcional)", multiline=True, min_lines=1, max_lines=3, expand=True)
    aplicar_formato_texto(textos.mayusculas, nombre_field)
    aplicar_formato_texto(textos.mayusculas, contacto_field)
    aplicar_formato_texto(textos.email, email_field)
    campos = {"nombre": nombre_field, "cuit": cuit_field, "contacto": contacto_field, "telefono": telefono_field,
              "email": email_field, "direccion": direccion_field, "observaciones": observaciones_field}

    def ir_a_formulario(proveedor: dict | None) -> None:
        nonlocal editando
        editando = proveedor
        form_titulo.value = f"Editar proveedor: {proveedor['nombre']}" if proveedor else "Nuevo proveedor"
        guardar_texto.value = "Guardar cambios" if proveedor else "Agregar proveedor"
        for clave, campo in campos.items():
            campo.value = (proveedor or {}).get(clave) or ""
        seccion_lista.visible = False
        seccion_formulario.visible = True
        page.update()

    def volver_a_lista() -> None:
        seccion_formulario.visible = False
        seccion_lista.visible = True
        refrescar()

    def guardar() -> None:
        datos = {clave: campo.value for clave, campo in campos.items()}
        datos["nombre"] = datos["nombre"] or ""
        try:
            if editando is None:
                proveedor = proveedores_service.crear_proveedor(**datos)
                aviso = f"Proveedor '{proveedor['nombre']}' agregado"
            else:
                proveedor = proveedores_service.actualizar_proveedor(proveedor_id=editando["id"], activo=editando["activo"], **datos)
                aviso = f"Proveedor '{proveedor['nombre']}' guardado"
        except ERRORES_PARA_AVISAR as ex:
            avisar(page, str(ex), error=True)
            return
        volver_a_lista()
        avisar(page, aviso)

    seccion_formulario = ft.Column([
        tarjeta(
            ft.Row([nombre_field, cuit_field, contacto_field]),
            ft.Row([telefono_field, email_field, direccion_field]),
            ft.Row([observaciones_field]),
            botones_formulario(guardar_texto, guardar, volver_a_lista),
            titulo=form_titulo,
            subtitulo="Al guardar o cancelar volves a la lista, donde la dejaste.",
        ),
    ], visible=False)

    refrescar()
    return ft.Column(
        [
            encabezado_pantalla("Proveedores", "A quienes les compra el negocio."),
            seccion_lista,
            seccion_formulario,
        ],
        expand=True, scroll=ft.ScrollMode.AUTO, spacing=ESPACIO_PANTALLA,
    )
