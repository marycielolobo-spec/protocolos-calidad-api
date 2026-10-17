"""Demo completa en esta PC, sin tocar Supabase ni enviar correos.

Usa una base de datos de prueba local (datos/demo-local, no se sube a git) con usuarios de ejemplo
y el selector "Actuar como". Las pantallas de Lovable se abren aparte apuntando a esta API (puerto 8001).

Uso:  .venv\\Scripts\\python herramientas\\demo_local.py
"""
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
for clave in ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SECRET_KEY", "SMTP_HOST", "SMTP_USER",
              "SMTP_PASSWORD", "RESEND_API_KEY"):
    os.environ[clave] = ""                       # ignora el .env: nada va a Supabase ni al correo
os.environ["PROTOCOLOS_DATOS"] = str(RAIZ / "datos" / "demo-local")
os.environ["URL_PORTAL"] = "http://localhost:5182/revision"
os.environ["URL_APP"] = "http://localhost:5182"
os.environ["CORS_ORIGENES"] = "http://localhost:5182"
sys.path.insert(0, str(RAIZ))

import uvicorn  # noqa: E402

print("API de demo local en http://localhost:8001 — abra las pantallas en http://localhost:5182")
uvicorn.run("servidor.main:app", host="127.0.0.1", port=8001)
