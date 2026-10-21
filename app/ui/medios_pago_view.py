import flet as ft

from app.services import medios_pago_service
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


def MediosPagoView(page: ft.Page) -> ft.Control:
    editando: dict | None = None

    # ================= Lista =================
    buscador_field = campo_buscar("Nombre del medio de pago", al_cambiar=lambda: filtrar())
    lista = Lista(
        [Columna("Nombre", peso=3, orden="nombre"), Columna("Tipo", peso=2), Columna("Estado", ancho=90),
         Columna("Acciones", ancho=84, derecha=True)],
        al_cambiar_pagina=lambda: refrescar(), nombre="medios de pago", orden_inicial=("nombre", False),
        sin_datos="Ningun medio de pago coincide con la busqueda.",
    )

    def filtrar() -> None:
        lista.ir_al_principio()
        refrescar()

    def refrescar() -> None:
        texto = (buscador_field.value or "").strip().lower()
        medios = [m for m in medios_pago_service.listar_medios_pago() if texto in m["nombre"].lower()]
        lista.mostrar(medios, lambda m: [
            m["nombre"],
            "Cuenta corriente (genera un cargo)" if m["es_cuenta_corriente"] else "Pago en el momento",
            etiqueta_estado("Activo", TONO_OK) if m["activo"] else etiqueta_estado("Inactivo", TONO_NO),
            ft.Row([
                accion_abrir(ft.Icons.EDIT, "Editar medio de pago", lambda m=m: ir_a_formulario(m)),
                accion_cambiar(ft.Icons.POWER_SETTINGS_NEW, "Desactivar medio de pago" if m["activo"] else "Activar medio de pago",
                               lambda m=m: cambiar_activo(m)),
            ], spacing=0, tight=True),
        ])
        page.update()

    def cambiar_activo(m: dict) -> str:
        medios_pago_service.cambiar_activo(m["id"], not m["activo"])
        refrescar()
        return (f"{m['nombre']}: activado" if not m["activo"]
                else f"{m['nombre']}: desactivado (ya no se ofrece al cobrar ni al pagar)")

    seccion_lista = ft.Column([
        barra([buscador_field], [boton_principal("Nuevo medio de pago", ft.Icons.ADD, lambda: ir_a_formulario(None))]),
        lista.control,
    ], spacing=ESPACIO_PANTALLA)

    # ================= Formulario (alta / edicion) =================
    form_titulo = ft.Text("", size=15, weight=ft.FontWeight.BOLD)
    guardar_texto = ft.Text("")
    nombre_field = ft.TextField(label="Nombre *", width=360)
    aplicar_formato_texto(textos.primera_mayuscula, nombre_field)
    cuenta_corriente_switch = ft.Switch(label="Es cuenta corriente (genera un cargo en Cuentas Corrientes)")

    def ir_a_formulario(medio: dict | None) -> None:
        nonlocal editando
        editando = medio
        form_titulo.value = f"Editar medio de pago: {medio['nombre']}" if medio else "Nuevo medio de pago"
        guardar_texto.value = "Guardar cambios" if medio else "Agregar medio de pago"
        nombre_field.value = medio["nombre"] if medio else ""
        cuenta_corriente_switch.value = medio["es_cuenta_corriente"] if medio else False
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
                medio = medios_pago_service.crear_medio_pago(nombre_field.value or "", cuenta_corriente_switch.value)
                aviso = f"Medio de pago '{medio['nombre']}' agregado"
            else:
                medio = medios_pago_service.actualizar_medio_pago(
                    editando["id"], nombre_field.value or "", cuenta_corriente_switch.value, editando["activo"],
                )
                aviso = f"Medio de pago '{medio['nombre']}' guardado"
        except ERRORES_PARA_AVISAR as ex:
            avisar(page, str(ex), error=True)
            return
        volver_a_lista()
        avisar(page, aviso)

    seccion_formulario = ft.Column([
        tarjeta(
            ft.Row([nombre_field, cuenta_corriente_switch], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            botones_formulario(guardar_texto, guardar, volver_a_lista),
            titulo=form_titulo,
            subtitulo="Al guardar o cancelar volves a la lista, donde la dejaste.",
        ),
    ], visible=False)

    refrescar()
    return ft.Column(
        [
            encabezado_pantalla("Medios de Pago", "Las formas de cobrar y pagar: efectivo, transferencia, cheque, cuenta corriente..."),
            seccion_lista,
            seccion_formulario,
        ],
        expand=True, scroll=ft.ScrollMode.AUTO, spacing=ESPACIO_PANTALLA,
    )
