import sqlite3

from app.repositories import log_repo


def _a_dict(fila: sqlite3.Row) -> dict:
    return {
        "id": fila["id"],
        "fecha": fila["fecha"],
        "entidad": fila["entidad"],
        "entidad_id": fila["entidad_id"],
        "descripcion": fila["descripcion"],
    }


def registrar(entidad: str, entidad_id: int | None, descripcion: str) -> None:
    """Registra un evento en el log interno."""
    log_repo.crear(entidad, entidad_id, descripcion)


def _formatear_valor(valor) -> str:
    if valor is None:
        return "ninguno"
    if isinstance(valor, bool):
        return "si" if valor else "no"
    return str(valor)


def registrar_cambios(entidad: str, entidad_id: int, antes: dict, despues: dict, campos: list[str]) -> None:
    """Compara 'antes' y 'despues' campo por campo y registra un evento por cada diferencia.
    Los dicts deben tener valores ya listos para mostrar (ej: nombres resueltos en vez de ids)."""
    for campo in campos:
        valor_antes = antes.get(campo)
        valor_despues = despues.get(campo)
        if valor_antes != valor_despues:
            registrar(
                entidad,
                entidad_id,
                f"Se cambio el campo '{campo}' de '{_formatear_valor(valor_antes)}' a '{_formatear_valor(valor_despues)}'",
            )


def listar_eventos(entidad: str | None = None, texto: str | None = None, limite: int = 500) -> list[dict]:
    eventos = [_a_dict(fila) for fila in log_repo.listar(entidad=entidad, limite=limite)]
    if texto:
        texto = texto.strip().lower()
        eventos = [e for e in eventos if texto in e["descripcion"].lower()]
    return eventos
