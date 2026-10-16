"""Archivos (adjuntos, PDF, Hojas de Cargo, firmas y sellos): Supabase Storage o carpeta local.

- Con Supabase configurado → bucket privado (config.BUCKET). Solo este servidor lo lee, con la clave secreta.
- Sin Supabase → carpeta datos/archivos (demo local y pruebas).
Las rutas son siempre relativas, p. ej. "pdfs/<id>/V0/firmado.pdf".
"""
import mimetypes
import threading

import httpx

from . import config

_bucket_listo = threading.Event()


class ArchivoNoEncontrado(Exception):
    pass


def _cabeceras():
    return {"apikey": config.SUPABASE_SECRET_KEY, "Authorization": f"Bearer {config.SUPABASE_SECRET_KEY}"}


def _url(ruta=""):
    return f"{config.SUPABASE_URL}/storage/v1/object/{config.BUCKET}/{ruta}"


def _asegurar_bucket():
    """Crea el bucket privado la primera vez (si ya existe, Supabase responde que está duplicado)."""
    if _bucket_listo.is_set():
        return
    r = httpx.post(f"{config.SUPABASE_URL}/storage/v1/bucket", headers=_cabeceras(), timeout=20,
                   json={"id": config.BUCKET, "name": config.BUCKET, "public": False})
    if r.status_code not in (200, 201) and "already exists" not in r.text.lower() and "duplicate" not in r.text.lower():
        raise RuntimeError(f"Storage: no se pudo crear el bucket ({r.status_code} {r.text[:200]})")
    _bucket_listo.set()


def guardar(ruta, datos, tipo=None):
    tipo = tipo or mimetypes.guess_type(ruta)[0] or "application/octet-stream"
    if config.SUPABASE:
        _asegurar_bucket()
        r = httpx.post(_url(ruta), content=datos, timeout=120,
                       headers={**_cabeceras(), "Content-Type": tipo, "x-upsert": "true"})
        if not r.is_success:
            raise RuntimeError(f"Storage: no se pudo guardar {ruta} ({r.status_code} {r.text[:200]})")
        return ruta
    destino = config.ARCHIVOS / ruta
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(datos)
    return ruta


def leer(ruta):
    if config.SUPABASE:
        r = httpx.get(_url(ruta), headers=_cabeceras(), timeout=120)
        if r.status_code in (400, 404):
            raise ArchivoNoEncontrado(ruta)
        if not r.is_success:
            raise RuntimeError(f"Storage: no se pudo leer {ruta} ({r.status_code})")
        return r.content
    origen = config.ARCHIVOS / ruta
    if not origen.exists():
        raise ArchivoNoEncontrado(ruta)
    return origen.read_bytes()


def existe(ruta):
    try:
        leer(ruta)
        return True
    except ArchivoNoEncontrado:
        return False


def borrar(ruta):
    if config.SUPABASE:
        httpx.request("DELETE", f"{config.SUPABASE_URL}/storage/v1/object/{config.BUCKET}", headers=_cabeceras(),
                      json={"prefixes": [ruta]}, timeout=30)
        return
    (config.ARCHIVOS / ruta).unlink(missing_ok=True)
