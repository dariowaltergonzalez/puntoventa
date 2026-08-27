import sqlite3

from app.repositories import proveedores_repo
from app.services.exceptions import ProveedorDuplicadoError, ProveedorNoEncontradoError


def _a_dict(fila: sqlite3.Row) -> dict:
    return {
        "id": fila["id"],
        "nombre": fila["nombre"],
        "cuit": fila["cuit"],
        "contacto": fila["contacto"],
        "telefono": fila["telefono"],
        "email": fila["email"],
        "direccion": fila["direccion"],
        "observaciones": fila["observaciones"],
        "activo": bool(fila["activo"]),
    }


def _texto_o_none(valor: str | None) -> str | None:
    valor = (valor or "").strip()
    return valor or None


def crear_proveedor(
    nombre: str,
    cuit: str | None = None,
    contacto: str | None = None,
    telefono: str | None = None,
    email: str | None = None,
    direccion: str | None = None,
    observaciones: str | None = None,
) -> dict:
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre del proveedor no puede estar vacio")

    try:
        proveedor_id = proveedores_repo.crear(
            nombre=nombre,
            cuit=_texto_o_none(cuit),
            contacto=_texto_o_none(contacto),
            telefono=_texto_o_none(telefono),
            email=_texto_o_none(email),
            direccion=_texto_o_none(direccion),
            observaciones=_texto_o_none(observaciones),
        )
    except sqlite3.IntegrityError as exc:
        raise ProveedorDuplicadoError(f"Ya existe un proveedor llamado '{nombre}'") from exc

    return obtener_proveedor(proveedor_id)


def actualizar_proveedor(
    proveedor_id: int,
    nombre: str,
    cuit: str | None,
    contacto: str | None,
    telefono: str | None,
    email: str | None,
    direccion: str | None,
    observaciones: str | None,
    activo: bool,
) -> dict:
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre del proveedor no puede estar vacio")

    if proveedores_repo.obtener_por_id(proveedor_id) is None:
        raise ProveedorNoEncontradoError(f"No existe el proveedor {proveedor_id}")

    try:
        proveedores_repo.actualizar(
            proveedor_id=proveedor_id,
            nombre=nombre,
            cuit=_texto_o_none(cuit),
            contacto=_texto_o_none(contacto),
            telefono=_texto_o_none(telefono),
            email=_texto_o_none(email),
            direccion=_texto_o_none(direccion),
            observaciones=_texto_o_none(observaciones),
            activo=1 if activo else 0,
        )
    except sqlite3.IntegrityError as exc:
        raise ProveedorDuplicadoError(f"Ya existe un proveedor llamado '{nombre}'") from exc

    return obtener_proveedor(proveedor_id)


def obtener_proveedor(proveedor_id: int) -> dict | None:
    fila = proveedores_repo.obtener_por_id(proveedor_id)
    return _a_dict(fila) if fila is not None else None


def listar_proveedores(solo_activos: bool = False) -> list[dict]:
    return [_a_dict(fila) for fila in proveedores_repo.listar(solo_activos)]
