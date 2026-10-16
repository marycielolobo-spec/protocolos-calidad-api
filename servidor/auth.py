"""Inicio de sesión con Supabase Auth (correo + contraseña), propio de Protocolos de Calidad.

- Las contraseñas las guarda Supabase Auth; este servidor nunca las almacena.
- Las pantallas envían el "access token" en cada pedido (Authorization: Bearer …); aquí se valida con Supabase.
- Un administrador da de alta a cada persona con una contraseña temporal; al primer ingreso debe cambiarla
  (columna perfil.debe_cambiar_clave).
"""
import secrets
import threading
import time

import httpx

from . import config

_cache = {}                 # token → (id de usuario, vence): evita consultar a Supabase en cada pedido
_candado = threading.Lock()
CACHE_SEGUNDOS = 60


class ErrorAuth(Exception):
    def __init__(self, mensaje, estado=401):
        super().__init__(mensaje)
        self.estado = estado


def _publica():
    return {"apikey": config.SUPABASE_PUBLISHABLE_KEY}


def _secreta():
    return {"apikey": config.SUPABASE_SECRET_KEY, "Authorization": f"Bearer {config.SUPABASE_SECRET_KEY}"}


def _url(ruta):
    return f"{config.SUPABASE_URL}/auth/v1{ruta}"


def _sesion(j):
    return {"access_token": j["access_token"], "refresh_token": j["refresh_token"],
            "expira_en": j.get("expires_in", 3600), "usuario_id": j["user"]["id"]}


def ingresar(email, clave):
    r = httpx.post(_url("/token?grant_type=password"), headers=_publica(), timeout=20,
                   json={"email": email.strip().lower(), "password": clave})
    if r.status_code in (400, 401):
        raise ErrorAuth("Correo o contraseña incorrectos")
    if r.status_code == 429:
        raise ErrorAuth("Demasiados intentos. Espere unos minutos.", 429)
    r.raise_for_status()
    return _sesion(r.json())


def renovar(refresh_token):
    r = httpx.post(_url("/token?grant_type=refresh_token"), headers=_publica(), timeout=20,
                   json={"refresh_token": refresh_token})
    if not r.is_success:
        raise ErrorAuth("La sesión venció. Vuelva a ingresar.")
    return _sesion(r.json())


def usuario_de_token(token):
    """Devuelve el id del usuario dueño del token, o lanza ErrorAuth."""
    if not token:
        raise ErrorAuth("Debe iniciar sesión")
    ahora = time.time()
    with _candado:
        guardado = _cache.get(token)
        if guardado and guardado[1] > ahora:
            return guardado[0]
    r = httpx.get(_url("/user"), headers={**_publica(), "Authorization": f"Bearer {token}"}, timeout=20)
    if not r.is_success:
        raise ErrorAuth("La sesión venció. Vuelva a ingresar.")
    uid = r.json()["id"]
    with _candado:
        if len(_cache) > 5000:
            _cache.clear()
        _cache[token] = (uid, ahora + CACHE_SEGUNDOS)
    return uid


def cerrar_sesion(token):
    with _candado:
        _cache.pop(token, None)
    httpx.post(_url("/logout"), headers={**_publica(), "Authorization": f"Bearer {token}"}, timeout=20)


def validar_clave(clave):
    if len(clave or "") < 8 or not any(c.isdigit() for c in clave) or not any(c.isalpha() for c in clave):
        raise ErrorAuth("La contraseña debe tener al menos 8 caracteres, con letras y números", 400)


def cambiar_clave(token, nueva):
    validar_clave(nueva)
    r = httpx.put(_url("/user"), headers={**_publica(), "Authorization": f"Bearer {token}"}, timeout=20,
                  json={"password": nueva})
    if r.status_code == 422 and "same" in r.text.lower():
        raise ErrorAuth("La nueva contraseña debe ser distinta de la anterior", 400)
    if not r.is_success:
        raise ErrorAuth(f"No se pudo cambiar la contraseña ({r.status_code})", 400)


def clave_temporal():
    """10 caracteres sin letras que se confunden (0/O, 1/l/I), con letras y números."""
    letras, numeros = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ", "23456789"
    while True:
        c = "".join(secrets.choice(letras + numeros) for _ in range(10))
        if any(x in numeros for x in c) and any(x in letras for x in c):
            return c


# ---------------------------------------------------------------------------
# Administración (con la clave secreta, solo desde este servidor)
# ---------------------------------------------------------------------------
def buscar_por_email(email):
    pagina = 1
    while True:
        r = httpx.get(_url(f"/admin/users?page={pagina}&per_page=1000"), headers=_secreta(), timeout=30)
        r.raise_for_status()
        usuarios = r.json().get("users", [])
        for u in usuarios:
            if (u.get("email") or "").lower() == email.lower():
                return u["id"]
        if len(usuarios) < 1000:
            return None
        pagina += 1


def crear_usuario(email, clave, nombre):
    """Crea la cuenta (sin enviar correo) o, si ya existía, le pone la contraseña dada. Devuelve su id."""
    r = httpx.post(_url("/admin/users"), headers=_secreta(), timeout=30, json={
        "email": email.strip().lower(), "password": clave, "email_confirm": True,
        "user_metadata": {"nombre": nombre, "sistema": "protocolos-calidad"}})
    if r.is_success:
        return r.json()["id"]
    if r.status_code == 422 and ("already" in r.text.lower() or "exists" in r.text.lower()):
        uid = buscar_por_email(email)
        if uid:
            fijar_clave(uid, clave)
            return uid
    raise ErrorAuth(f"No se pudo crear el usuario en Supabase ({r.status_code} {r.text[:150]})", 400)


def fijar_clave(uid, clave):
    r = httpx.put(_url(f"/admin/users/{uid}"), headers=_secreta(), timeout=30, json={"password": clave})
    if not r.is_success:
        raise ErrorAuth(f"No se pudo cambiar la contraseña ({r.status_code})", 400)


def bloquear(uid, bloqueado):
    """Un usuario desactivado no puede iniciar sesión (sus firmas y protocolos se conservan)."""
    r = httpx.put(_url(f"/admin/users/{uid}"), headers=_secreta(), timeout=30,
                  json={"ban_duration": "876000h" if bloqueado else "none"})
    if not r.is_success:
        raise ErrorAuth(f"No se pudo actualizar el acceso ({r.status_code})", 400)


def borrar_usuario(uid):
    """Solo para pruebas automáticas."""
    httpx.delete(_url(f"/admin/users/{uid}"), headers=_secreta(), timeout=30)
