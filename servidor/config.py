"""Configuración: rutas del proyecto y claves leídas del archivo .env (opcional).

Sin .env el sistema funciona en MODO DEMO: los correos quedan en la bandeja "Correos (simulados)";
todo lo demás (base de datos, reglas, firmas, PDF) es real.
"""
import os
from datetime import timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
WEB = RAIZ / "web"
TIPOS_JSON = RAIZ / "protocolos" / "tipos.json"
MAESTROS_JSON = RAIZ / "protocolos" / "maestros.json"
DATOS = Path(os.environ.get("PROTOCOLOS_DATOS", RAIZ / "datos"))   # base de datos, adjuntos y PDF (no va a GitLab)
BASE_DATOS = DATOS / "protocolos.db"
ARCHIVOS = DATOS / "archivos"


def _leer_env():
    archivo = RAIZ / ".env"
    if not archivo.exists():
        return
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip('"'))


_leer_env()

APP_URL = os.environ.get("APP_URL", "http://localhost:8000").rstrip("/")

# Correo (Resend). Vacío = se guarda en la "bandeja de salida" de la app.
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
MAIL_FROM = os.environ.get("MAIL_FROM", "Calidad Stracon <calidad@example.com>")
CORREO_REAL = bool(RESEND_API_KEY)

DIAS_VENCE_ENLACE = 15          # enlace del portal para KP / Hudbay
MINUTOS_VENCE_CODIGO = 10       # código de firma enviado al correo
INTENTOS_CODIGO = 5

ZONA_PERU = timezone(timedelta(hours=-5), "PET")   # Perú no tiene horario de verano
