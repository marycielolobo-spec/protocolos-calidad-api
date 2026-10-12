"""Notificaciones por correo.

Con RESEND_API_KEY en .env se envían de verdad (Resend: 3 000 correos/mes gratis).
Sin clave, quedan en la "bandeja de salida" de la app para poder seguir el flujo en la demo.
Todos los correos quedan registrados en la tabla `correo`.
"""
import html

import httpx

from . import config, db


def enviar(para, asunto, parrafos, boton=None):
    cuerpo = "".join(f"<p>{html.escape(p)}</p>" for p in parrafos)
    if boton:
        cuerpo += (f'<p><a href="{html.escape(boton["url"])}" style="background:#0b5cad;color:#fff;padding:10px 18px;'
                   f'border-radius:6px;text-decoration:none;display:inline-block">{html.escape(boton["texto"])}</a></p>')
    cuerpo = (f'<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#1d232b;max-width:560px">{cuerpo}'
              '<p style="color:#5b6673;font-size:12px">Protocolos de Calidad · Stracon — Mina Constancia</p></div>')

    enviado, error = False, None
    if config.CORREO_REAL:
        try:
            r = httpx.post("https://api.resend.com/emails", timeout=20,
                           headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"},
                           json={"from": config.MAIL_FROM, "to": para, "subject": asunto, "html": cuerpo})
            enviado = r.is_success
            error = None if enviado else f"{r.status_code} {r.text[:300]}"
        except httpx.HTTPError as e:
            error = str(e)
        if error:
            print(f"[correo] No enviado a {para}: {error}")

    db.insertar("correo", {"id": db.nuevo_id(), "para": ", ".join(para), "asunto": asunto, "cuerpo": cuerpo,
                           "enlace": boton["url"] if boton else None, "enviado": int(enviado), "error": error,
                           "created_at": db.ahora()})
    return enviado
