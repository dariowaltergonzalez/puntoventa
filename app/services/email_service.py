import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from app.services import log_service, negocio_service
from app.services.exceptions import CorreoNoConfiguradoError, EnvioCorreoError

_TIMEOUT_SEGUNDOS = 20


def _configuracion() -> dict:
    negocio = negocio_service.obtener_negocio()
    if negocio is None:
        raise CorreoNoConfiguradoError("Primero guarda los datos del negocio")
    faltantes = [
        etiqueta for campo, etiqueta in (
            ("smtp_servidor", "servidor"), ("smtp_puerto", "puerto"), ("smtp_seguridad", "seguridad"),
            ("smtp_usuario", "usuario"), ("smtp_remitente_email", "email del remitente"),
        ) if not negocio[campo]
    ]
    password = negocio_service.obtener_password_smtp()
    if password is None:
        faltantes.append("contrasena")
    if faltantes:
        raise CorreoNoConfiguradoError(f"Falta configurar el correo saliente: {', '.join(faltantes)}")
    return {**negocio, "password": password}


def enviar_mail(destinatario: str, asunto: str, cuerpo: str) -> None:
    """Envia un mail de texto con la configuracion SMTP del negocio. Fase 5 lo reusa para
    mandar presupuestos y OCs (con adjuntos, a sumar ahi)."""
    config = _configuracion()
    mensaje = EmailMessage()
    mensaje["From"] = formataddr((config["smtp_remitente_nombre"] or "", config["smtp_remitente_email"]))
    mensaje["To"] = destinatario
    mensaje["Subject"] = asunto
    mensaje.set_content(cuerpo)

    try:
        if config["smtp_seguridad"] == "ssl":
            servidor = smtplib.SMTP_SSL(config["smtp_servidor"], config["smtp_puerto"],
                                        timeout=_TIMEOUT_SEGUNDOS, context=ssl.create_default_context())
        else:
            servidor = smtplib.SMTP(config["smtp_servidor"], config["smtp_puerto"], timeout=_TIMEOUT_SEGUNDOS)
        with servidor:
            if config["smtp_seguridad"] == "starttls":
                servidor.starttls(context=ssl.create_default_context())
            servidor.login(config["smtp_usuario"], config["password"])
            servidor.send_message(mensaje)
    except smtplib.SMTPAuthenticationError as exc:
        log_service.registrar("negocio", 1, f"Fallo el envio de mail a {destinatario}: usuario o contrasena incorrectos")
        raise EnvioCorreoError(
            "El servidor rechazo el usuario o la contrasena (con Gmail hace falta una 'contrasena de aplicacion')"
        ) from exc
    except (smtplib.SMTPException, OSError) as exc:
        log_service.registrar("negocio", 1, f"Fallo el envio de mail a {destinatario}: {exc}")
        raise EnvioCorreoError(f"No se pudo enviar el mail: {exc}") from exc
    log_service.registrar("negocio", 1, f"Se envio un mail a {destinatario}: '{asunto}'")


def enviar_mail_de_prueba() -> str:
    """Manda un mail de prueba al propio remitente. Devuelve a quien se envio."""
    config = _configuracion()
    destinatario = config["smtp_remitente_email"]
    enviar_mail(
        destinatario,
        "Prueba de correo - Punto de Venta",
        "Si estas leyendo esto, la configuracion de correo saliente del Punto de Venta funciona.",
    )
    return destinatario
