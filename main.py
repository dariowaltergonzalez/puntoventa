import flet as ft

from app.ui.app_shell import build_app


def main(page: ft.Page) -> None:
    page.title = "Punto de Venta"
    build_app(page)


if __name__ == "__main__":
    ft.run(main)
