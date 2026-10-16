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
# Página del portal externo (KP / Hudbay). Con las pantallas de Lovable: <url del frontend>/revision
URL_PORTAL = os.environ.get("URL_PORTAL", f"{APP_URL}/revision.html").rstrip("/")
# Direcciones del frontend (Lovable) que pueden usar la API, separadas por coma. "*" = cualquiera (solo demo)
CORS_ORIGENES = [o.strip() for o in os.environ.get("CORS_ORIGENES", "*").split(",") if o.strip()]
# Dirección de las pantallas internas (enlaces "Abrir protocolo" de los correos)
URL_APP = os.environ.get("URL_APP", f"{APP_URL}/#").rstrip("/")

# Correo. Sin datos = se guarda en la "bandeja de salida" de la app (modo demo).
# Opción 1 (recomendada para el piloto): cuenta de Gmail del sistema con contraseña de aplicación.
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").replace(" ", "")   # Google la muestra en grupos de 4
# Opción 2: Resend (necesita un dominio verificado).
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
MAIL_FROM = os.environ.get("MAIL_FROM", "Protocolos de Calidad STRACON <calidad@example.com>")
CORREO_REAL = bool((SMTP_USER and SMTP_PASSWORD) or RESEND_API_KEY)

# Supabase. Sin estos datos el sistema usa SQLite y archivos locales, con el selector "Actuar como" (demo).
# DATABASE_URL → base de datos PostgreSQL · SUPABASE_URL + claves → archivos (Storage) e inicio de sesión (Auth).
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_PUBLISHABLE_KEY = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")
SUPABASE = bool(SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY and SUPABASE_SECRET_KEY)
BUCKET = os.environ.get("SUPABASE_BUCKET", "protocolos")

DIAS_VENCE_ENLACE = 15          # enlace del portal para KP / Hudbay
MINUTOS_VENCE_CODIGO = 10       # código de firma enviado al correo
INTENTOS_CODIGO = 5

ZONA_PERU = timezone(timedelta(hours=-5), "PET")   # Perú no tiene horario de verano
