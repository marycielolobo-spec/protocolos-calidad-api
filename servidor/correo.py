"""Notificaciones por correo.

Dos formas de enviar (se configuran en .env):
- SMTP (p. ej. una cuenta de Gmail exclusiva del sistema con "contraseña de aplicación"): SMTP_USER + SMTP_PASSWORD.
- Resend (requiere un dominio verificado): RESEND_API_KEY.
Sin ninguna, los correos quedan en la "bandeja de salida" de la app (modo demo).
Todos los correos quedan registrados en la tabla `correo`.
"""
import html
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

import httpx

from . import config, db


def _por_smtp(para, asunto, cuerpo_html, texto):
    msg = EmailMessage()
    nombre, direccion = parseaddr(config.MAIL_FROM)
    msg["From"] = formataddr((nombre or "Protocolos de Calidad STRACON", config.SMTP_USER))   # Gmail exige enviar como la cuenta
    if "@" in direccion and direccion != config.SMTP_USER:
        msg["Reply-To"] = direccion
    msg["To"] = ", ".join(para)
    msg["Subject"] = asunto
    msg.set_content(texto)
    msg.add_alternative(cuerpo_html, subtype="html")
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(config.SMTP_USER, config.SMTP_PASSWORD)
        s.send_message(msg)


def _por_resend(para, asunto, cuerpo_html):
    r = httpx.post("https://api.resend.com/emails", timeout=20,
                   headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"},
                   json={"from": config.MAIL_FROM, "to": para, "subject": asunto, "html": cuerpo_html})
    if not r.is_success:
        raise RuntimeError(f"{r.status_code} {r.text[:300]}")


def enviar(para, asunto, parrafos, boton=None):
    cuerpo = "".join(f"<p>{html.escape(p)}</p>" for p in parrafos)
    if boton:
        cuerpo += (f'<p><a href="{html.escape(boton["url"])}" style="background:#15284B;color:#fff;padding:10px 18px;'
                   f'border-radius:6px;text-decoration:none;display:inline-block">{html.escape(boton["texto"])}</a></p>')
    cuerpo = (f'<div style="font-family:Arial,sans-serif;font-size:14px;color:#1d232b;max-width:560px">{cuerpo}'
              '<p style="color:#5b6673;font-size:12px;border-top:3px solid #F42534;padding-top:8px">'
              'Protocolos de Calidad · STRACON — Mina Constancia</p></div>')
    texto = "\n\n".join(parrafos) + (f"\n\n{boton['texto']}: {boton['url']}" if boton else "")

    enviado, error = False, None
    if config.CORREO_REAL:
        try:
            if config.SMTP_USER:
                _por_smtp(para, asunto, cuerpo, texto)
            else:
                _por_resend(para, asunto, cuerpo)
            enviado = True
        except Exception as e:                   # el flujo sigue; el error queda registrado y visible
            error = str(e)[:300]
            print(f"[correo] No enviado a {para}: {error}")

    db.insertar("correo", {"id": db.nuevo_id(), "para": ", ".join(para), "asunto": asunto, "cuerpo": cuerpo,
                           "enlace": boton["url"] if boton else None, "enviado": int(enviado), "error": error,
                           "created_at": db.ahora()})
    return enviado
