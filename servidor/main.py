"""Servidor web (FastAPI). Entrega las pantallas de web/ y la API /api/... que usan.

Arranque:  iniciar.bat   (o:  .venv\\Scripts\\python -m uvicorn servidor.main:app --port 8000)
Documentación automática de la API:  http://localhost:8000/docs
"""
from typing import Any

from fastapi import FastAPI, File, Form, Header, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, logica, qc_index
from .logica import ErrorNegocio

app = FastAPI(title="Protocolos de Calidad — Stracon / Constancia", version="2.0")
db.iniciar()


@app.exception_handler(ErrorNegocio)
def _error_negocio(request: Request, e: ErrorNegocio):
    return JSONResponse({"error": str(e)}, status_code=e.estado)


@app.middleware("http")
async def _sin_cache(request: Request, siguiente):
    r = await siguiente(request)
    r.headers["Cache-Control"] = "no-store"
    return r


def _yo(x_usuario):
    """Usuario que hace la acción. Hoy lo elige el selector "Actuar como" (demo).
    Con Supabase se reemplaza por el inicio de sesión (correo + contraseña)."""
    p = db.fila("select * from perfil where id = ? and activo = 1", x_usuario) if x_usuario else None
    if not p:
        raise ErrorNegocio("Usuario no identificado", 401)
    return p


def _contexto(request: Request):
    """Evidencia de la firma: desde dónde se firmó."""
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or (request.client.host if request.client else "")
    return {"ip": ip, "dispositivo": request.headers.get("user-agent", "")[:300]}


def _pdf(ruta_nombre):
    ruta, nombre = ruta_nombre
    return FileResponse(ruta, media_type="application/pdf", filename=nombre, content_disposition_type="inline")


# ---------------------------------------------------------------------------
# Modelos de entrada
# ---------------------------------------------------------------------------
class Nuevo(BaseModel):
    tipo_id: str
    origen: str = "solicitud_operaciones"
    solicitud: dict | None = None


class Valor(BaseModel):
    cabecera: dict = {}
    respuestas: dict = {}
    conforme: bool | None = None


class Firmantes(BaseModel):
    firmantes: dict[str, dict[str, Any]] = {}


class Motivo(BaseModel):
    motivo: str = ""


class NuevoPaquete(BaseModel):
    instancias: list[str]
    contacto_id: str


class Decisiones(BaseModel):
    decisiones: list[dict[str, Any]]
    codigo: str = ""
    firma: str = ""          # firma dibujada (PNG en data URL)


class Decision(BaseModel):
    decision: str
    motivo: str = ""
    codigo: str = ""


class NuevoCambio(BaseModel):
    motivo: str
    descripcion: str = ""
    contacto_id: str


# ---------------------------------------------------------------------------
# App interna (personal Stracon)
# ---------------------------------------------------------------------------
@app.get("/api/sesion")
def sesion():
    return {"modo": {"correo_real": config.CORREO_REAL, "demo": not config.CORREO_REAL}, **logica.personas()}


@app.get("/api/tipos")
def tipos():
    return logica.tipos()


@app.get("/api/maestros")
def maestros():
    return logica.maestros()


@app.get("/api/protocolos")
def listar(estado: str | None = None):
    return logica.listar(estado)


@app.post("/api/protocolos")
def crear(datos: Nuevo, x_usuario: str = Header(None)):
    return {"id": logica.crear(_yo(x_usuario), datos.tipo_id, datos.origen, datos.solicitud)}


@app.get("/api/protocolos/{id_}")
def obtener(id_: str):
    return logica.obtener(id_)


@app.put("/api/protocolos/{id_}/valor")
def guardar_valor(id_: str, valor: Valor, x_usuario: str = Header(None)):
    logica.guardar_valor(_yo(x_usuario), id_, valor.model_dump())
    return {"ok": True}


@app.post("/api/protocolos/{id_}/adjuntos")
async def subir_adjunto(id_: str, archivo: UploadFile = File(...), tipo: str = Form("otro"),
                        ref_schema: str = Form(""), x_usuario: str = Header(None)):
    yo = _yo(x_usuario)
    return logica.subir_adjunto(yo, id_, archivo.filename or "archivo", await archivo.read(), tipo, ref_schema)


@app.get("/api/adjuntos/{adj_id}")
def bajar_adjunto(adj_id: str):
    ruta, nombre = logica.archivo_adjunto(adj_id)
    return FileResponse(ruta, filename=nombre, content_disposition_type="inline")


@app.delete("/api/adjuntos/{adj_id}")
def quitar_adjunto(adj_id: str, x_usuario: str = Header(None)):
    logica.quitar_adjunto(_yo(x_usuario), adj_id)
    return {"ok": True}


@app.post("/api/protocolos/{id_}/enviar-firma")
def enviar_a_firma(id_: str, datos: Firmantes, x_usuario: str = Header(None)):
    logica.enviar_a_firma(_yo(x_usuario), id_, datos.firmantes)
    return {"ok": True}


@app.post("/api/firmas/{firma_id}/firmar")
def firmar(firma_id: str, request: Request, x_usuario: str = Header(None)):
    return {"estado": logica.firmar(_yo(x_usuario), firma_id, _contexto(request))}


@app.post("/api/firmas/{firma_id}/rechazar")
def rechazar(firma_id: str, datos: Motivo, x_usuario: str = Header(None)):
    logica.rechazar(_yo(x_usuario), firma_id, datos.motivo)
    return {"ok": True}


@app.get("/api/protocolos/{id_}/pdf")
def pdf_protocolo(id_: str, version: int | None = None):
    return _pdf(logica.ruta_pdf(id_, version))


@app.get("/api/paquetes")
def paquetes():
    return logica.paquetes()


@app.post("/api/paquetes")
def crear_paquete(datos: NuevoPaquete, x_usuario: str = Header(None)):
    return logica.crear_paquete(_yo(x_usuario), datos.instancias, datos.contacto_id)


@app.get("/api/paquetes/{paq_id}/hoja-cargo")
def hoja_cargo(paq_id: str):
    return _pdf(logica.ruta_hoja_cargo(paq_id))


@app.post("/api/protocolos/{id_}/cambios")
def solicitar_cambio(id_: str, datos: NuevoCambio, x_usuario: str = Header(None)):
    return logica.solicitar_cambio(_yo(x_usuario), id_, datos.motivo, datos.descripcion, datos.contacto_id)


@app.post("/api/cambios/{cambio_id}/decidir")
def decidir_cambio(cambio_id: str, datos: Decision, x_usuario: str = Header(None)):
    logica.decidir_cambio_calidad(_yo(x_usuario), cambio_id, datos.decision, datos.motivo)
    return {"ok": True}


@app.get("/api/qc-index")
def descargar_qc_index(entregable: str | None = None):
    sufijo = f"_{entregable}" if entregable else ""
    return Response(qc_index.generar(entregable or None),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="QC-Index{sufijo}.xlsx"'})


@app.get("/api/correos")
def correos():
    return logica.correos()


@app.post("/api/reiniciar")
def reiniciar():
    if config.CORREO_REAL:
        raise ErrorNegocio("Solo disponible en modo demo", 403)
    db.reiniciar()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Portal externo (KP / Hudbay): sin cuenta. Enlace personal + código al correo para firmar.
# ---------------------------------------------------------------------------
@app.get("/api/revision/{token}")
def revision_obtener(token: str):
    return logica.revision_obtener(token)


@app.post("/api/revision/{token}/codigo")
def revision_codigo(token: str):
    return logica.solicitar_codigo(token)


@app.post("/api/revision/{token}/decidir")
def revision_decidir(token: str, datos: Decisiones, request: Request):
    logica.revision_decidir(token, datos.decisiones, datos.codigo, datos.firma, _contexto(request))
    return {"ok": True}


@app.post("/api/revision/{token}/cambio")
def revision_cambio(token: str, datos: Decision):
    logica.decidir_cambio_externo(token, datos.decision, datos.motivo, datos.codigo)
    return {"ok": True}


@app.get("/api/revision/{token}/pdf/{instancia_id}")
def revision_pdf(token: str, instancia_id: str):
    return _pdf(logica.revision_pdf(token, instancia_id))


@app.get("/api/revision/{token}/hoja-cargo")
def revision_hoja_cargo(token: str):
    return _pdf(logica.revision_hoja_cargo(token))


# Pantallas (HTML/CSS/JS). Va al final para no tapar las rutas /api.
app.mount("/", StaticFiles(directory=config.WEB, html=True), name="web")
