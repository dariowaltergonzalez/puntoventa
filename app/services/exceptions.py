class ErrorDeNegocio(Exception):
    """Base de todos los errores de reglas de negocio: la UI los muestra como aviso al usuario.
    Cualquier otra excepcion es un error de programacion y no se esconde."""


class CategoriaDuplicadaError(ErrorDeNegocio):
    pass


class CategoriaNoEncontradaError(ErrorDeNegocio):
    pass


class CodigoDuplicadoError(ErrorDeNegocio):
    pass


class CodigoBarraDuplicadoError(ErrorDeNegocio):
    pass


class ProductoNoEncontradoError(ErrorDeNegocio):
    pass


class ProductoInactivoError(ErrorDeNegocio):
    pass


class ProductoSinPrecioError(ErrorDeNegocio):
    pass


class StockInsuficienteError(ErrorDeNegocio):
    pass


class ProveedorDuplicadoError(ErrorDeNegocio):
    pass


class ProveedorNoEncontradoError(ErrorDeNegocio):
    pass


class LineasVaciasError(ErrorDeNegocio):
    pass


class OrdenCompraNoEncontradaError(ErrorDeNegocio):
    pass


class OrdenCompraCanceladaError(ErrorDeNegocio):
    pass


class OrdenCompraNoEditableError(ErrorDeNegocio):
    pass


class ClienteDuplicadoError(ErrorDeNegocio):
    pass


class ClienteNoEncontradoError(ErrorDeNegocio):
    pass


class ListaPrecioDuplicadaError(ErrorDeNegocio):
    pass


class ListaPrecioNoEncontradaError(ErrorDeNegocio):
    pass


class CondicionIvaNoEncontradaError(ErrorDeNegocio):
    pass


class CargoNoEncontradoError(ErrorDeNegocio):
    pass


class MontoPagoInvalidoError(ErrorDeNegocio):
    pass


class MedioPagoDuplicadoError(ErrorDeNegocio):
    pass


class MedioPagoNoEncontradoError(ErrorDeNegocio):
    pass


class VentaNoEncontradaError(ErrorDeNegocio):
    pass


class ChequeNoEncontradoError(ErrorDeNegocio):
    pass


class ChequeEstadoInvalidoError(ErrorDeNegocio):
    pass


class AnulacionInvalidaError(ErrorDeNegocio):
    pass


class NegocioNoConfiguradoError(ErrorDeNegocio):
    pass


class CorreoNoConfiguradoError(ErrorDeNegocio):
    pass


class EnvioCorreoError(ErrorDeNegocio):
    pass


class NotaCreditoInvalidaError(ErrorDeNegocio):
    pass


class PreventaNoDisponibleError(ErrorDeNegocio):
    pass


class PresupuestoNoDisponibleError(ErrorDeNegocio):
    pass


class GastoNoEncontradoError(ErrorDeNegocio):
    pass
