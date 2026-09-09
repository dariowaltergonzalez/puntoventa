import sqlite3

from app.repositories import condiciones_iva_repo


def _a_dict(fila: sqlite3.Row) -> dict:
    return {"id": fila["id"], "nombre": fila["nombre"], "activo": bool(fila["activo"])}


def listar_condiciones_iva(solo_activas: bool = False) -> list[dict]:
    return [_a_dict(f) for f in condiciones_iva_repo.listar(solo_activas)]
