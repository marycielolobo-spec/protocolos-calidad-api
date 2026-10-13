"""Prueba el envío de correo con los datos del archivo .env (Gmail u Outlook / Microsoft 365).

Uso:  .venv\\Scripts\\python pruebas\\probar_correo.py tu.correo@ejemplo.com
No muestra la contraseña: solo dice si se pudo conectar, iniciar sesión y enviar.
"""
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from servidor import config  # noqa: E402

if len(sys.argv) < 2:
    sys.exit("Indique a qué correo enviar la prueba:  probar_correo.py tu.correo@ejemplo.com")
if not (config.SMTP_USER and config.SMTP_PASSWORD):
    sys.exit("Faltan SMTP_USER y SMTP_PASSWORD en el archivo .env")

print(f"Servidor: {config.SMTP_HOST}:{config.SMTP_PORT}   Cuenta: {config.SMTP_USER}")
try:
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
        s.starttls(context=ssl.create_default_context())
        print("1. Conexión segura: OK")
        s.login(config.SMTP_USER, config.SMTP_PASSWORD)
        print("2. Inicio de sesión: OK")
        m = EmailMessage()
        m["From"], m["To"], m["Subject"] = config.SMTP_USER, sys.argv[1], "Prueba — Protocolos de Calidad STRACON"
        m.set_content("Si recibes este correo, el sistema ya puede enviar avisos y códigos de firma.")
        s.send_message(m)
        print(f"3. Correo enviado a {sys.argv[1]}: OK — revisa la bandeja (y la carpeta de spam).")
except smtplib.SMTPAuthenticationError as e:
    texto = e.smtp_error.decode(errors="ignore")
    print(f"2. Inicio de sesión: FALLÓ ({e.smtp_code})")
    if "SmtpClientAuthentication is disabled" in texto or "basic authentication is disabled" in texto.lower() or "5.7.139" in texto:
        print("   Microsoft 365 tiene bloqueado el envío con usuario y contraseña para esta cuenta.")
        print("   Solo TI puede habilitarlo. Alternativa: usar la cuenta de Gmail del sistema.")
    elif "gmail" in config.SMTP_HOST:
        print("   Revise que SMTP_PASSWORD sea la 'contraseña de aplicación' de 16 letras, no la normal.")
    else:
        print("   Revise el usuario y la contraseña del .env.")
    print(f"   Detalle técnico: {texto[:200]}")
except Exception as e:
    print(f"No se pudo enviar: {e}")
