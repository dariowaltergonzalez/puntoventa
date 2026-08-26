import sqlite3

from app.repositories import categorias_repo
from app.services.exceptions import CategoriaDuplicadaError, CategoriaNoEncontradaError


def _a_dict(fila: sqlite3.Row) -> dict:
    return {"id": fila["id"], "nombre": fila["nombre"]}


def crear_categoria(nombre: str) -> dict:
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre de la categoria no puede estar vacio")

    try:
        categoria_id = categorias_repo.crear(nombre)
    except sqlite3.IntegrityError as exc:
        raise CategoriaDuplicadaError(f"Ya existe una categoria llamada '{nombre}'") from exc

    return obtener_categoria(categoria_id)


def actualizar_categoria(categoria_id: int, nombre: str) -> dict:
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre de la categoria no puede estar vacio")

    if categorias_repo.obtener_por_id(categoria_id) is None:
        raise CategoriaNoEncontradaError(f"No existe la categoria {categoria_id}")

    try:
        categorias_repo.actualizar(categoria_id, nombre)
    except sqlite3.IntegrityError as exc:
        raise CategoriaDuplicadaError(f"Ya existe una categoria llamada '{nombre}'") from exc

    return obtener_categoria(categoria_id)


def obtener_categoria(categoria_id: int) -> dict | None:
    fila = categorias_repo.obtener_por_id(categoria_id)
    return _a_dict(fila) if fila is not None else None


def listar_categorias() -> list[dict]:
    return [_a_dict(fila) for fila in categorias_repo.listar()]
