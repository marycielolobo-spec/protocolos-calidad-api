"""Servidor web (FastAPI). Entrega las pantallas de web/ y la API /api/... que usan.

Arranque:  iniciar.bat   (o:  .venv\\Scripts\\python -m uvicorn servidor.main:app --port 8000)
Documentación automática de la API:  http://localhost:8000/docs

Quién hace cada pedido:
- Con Supabase (SUPABASE_URL + claves en .env): sesión real. Las pantallas envían "Authorization: Bearer <token>".
- Sin Supabase (demo local y pruebas): el selector "Actuar como" envía "X-Usuario: <id de perfil>".
El portal de KP / Hudbay (/api/revision/...) no usa sesión: su credencial es el enlace + el código al correo.
"""
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import almacen, auth, config, db, logica, qc_index
from .logica import ErrorNegocio

app = FastAPI(title="Protocolos de Calidad — Stracon / Constancia", version="3.0")
db.iniciar()

# Las pantallas de Lovable viven en otra dirección: el navegador necesita este permiso para llamar a la API
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGENES, allow_methods=["*"],
                   allow_headers=["*"], expose_headers=["Content-Disposition"])


@app.exception_handler(ErrorNegocio)
def _error_negocio(request: Request, e: ErrorNegocio):
    return JSONResponse({"error": str(e), **({"codigo": e.codigo} if getattr(e, "codigo", None) else {})},
                        status_code=e.estado)


@app.exception_handler(auth.ErrorAuth)
def _error_auth(request: Request, e: auth.ErrorAuth):
    return JSONResponse({"error": str(e)}, status_code=e.estado)


@app.middleware("http")
async def _sin_cache(request: Request, siguiente):
    r = await siguiente(request)
    r.headers["Cache-Control"] = "no-store"
    return r


# ---------------------------------------------------------------------------
# Quién hace el pedido
# ---------------------------------------------------------------------------
def _token(request: Request):
    cabecera = request.headers.get("authorization", "")
    return cabecera[7:].strip() if cabecera.lower().startswith("bearer ") else ""


def _identificar(request: Request, admite_clave_pendiente=False):
    if config.SUPABASE:
        uid = auth.usuario_de_token(_token(request))
        p = db.fila("select * from perfil where id = ? and activo = 1", uid)
        if not p:
            raise ErrorNegocio("Su usuario no tiene acceso a Protocolos de Calidad", 403)
        if p["debe_cambiar_clave"] and not admite_clave_pendiente:
            e = ErrorNegocio("Debe cambiar su contraseña temporal antes de continuar", 403)
            e.codigo = "cambiar_clave"
            raise e
        return p
    x = request.headers.get("x-usuario")
    p = db.fila("select * from perfil where id = ? and activo = 1", x) if x else None
    if not p:
        raise ErrorNegocio("Usuario no identificado", 401)
    return p


def usuario(request: Request):
    return _identificar(request)


def usuario_con_clave_pendiente(request: Request):
    return _identificar(request, admite_clave_pendiente=True)


def usuario_si_hay_sesion(request: Request):
    """Con sesión real: el usuario (aunque deba cambiar su clave). En la demo local: nadie (no hace falta)."""
    return _identificar(request, admite_clave_pendiente=True) if config.SUPABASE else None


def _contexto(request: Request):
    """Evidencia de la firma: desde dónde se firmó."""
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or (request.client.host if request.client else "")
    return {"ip": ip, "dispositivo": request.headers.get("user-agent", "")[:300]}


def _archivo(ruta, nombre, tipo):
    """Entrega un archivo guardado (Supabase Storage o carpeta local) para verlo en el navegador."""
    try:
        datos = almacen.leer(ruta)
    except almacen.ArchivoNoEncontrado:
        raise ErrorNegocio("Archivo no encontrado", 404)
    nombre_ascii = nombre.encode("ascii", "ignore").decode() or "archivo"
    return Response(datos, media_type=tipo, headers={"Content-Disposition": f'inline; filename="{nombre_ascii}"'})


def _pdf(ruta_nombre):
    ruta, nombre = ruta_nombre
    return _archivo(ruta, nombre, "application/pdf")


def _perfil_publico(p):
    return {k: p[k] for k in ("id", "nombre", "cargo", "email", "empresa", "rol", "es_admin", "debe_cambiar_clave", "tiene_sello")}


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
    firma: str = ""          # firma dibujada o imagen cargada (PNG en data URL)
    origen: str = "dibujada"  # dibujada | imagen | guardada
    guardar: bool = False    # guardar la imagen cargada para próximas firmas


class Decision(BaseModel):
    decision: str
    motivo: str = ""
    codigo: str = ""


class NuevoCambio(BaseModel):
    motivo: str
    descripcion: str = ""
    contacto_id: str


class Ingreso(BaseModel):
    email: str
    clave: str


class Renovacion(BaseModel):
    refresh_token: str


class NuevaClave(BaseModel):
    nueva: str


class DatosUsuario(BaseModel):
    nombre: str | None = None
    email: str | None = None
    cargo: str | None = None
    empresa: str | None = None
    rol: str | None = None
    es_admin: bool | None = None
    activo: bool | None = None


class DatosContacto(BaseModel):
    nombre: str | None = None
    email: str | None = None
    cargo: str | None = None
    empresa: str | None = None
    activo: bool | None = None


# ---------------------------------------------------------------------------
# Sesión
# ---------------------------------------------------------------------------
@app.get("/api/config")
def configuracion():
    """Pública: las pantallas la consultan al abrir para saber si piden inicio de sesión."""
    return {"auth": config.SUPABASE, "demo": not config.CORREO_REAL, "correo_real": config.CORREO_REAL}


@app.post("/api/auth/ingresar")
def ingresar(datos: Ingreso):
    if not config.SUPABASE:
        raise ErrorNegocio("En la demo local se usa el selector \"Actuar como\"", 400)
    s = auth.ingresar(datos.email, datos.clave)
    p = db.fila("select * from perfil where id = ? and activo = 1", s["usuario_id"])
    if not p:
        raise ErrorNegocio("Su usuario no tiene acceso a Protocolos de Calidad", 403)
    return {"sesion": s, "usuario": _perfil_publico(p)}


@app.post("/api/auth/renovar")
def renovar(datos: Renovacion):
    return {"sesion": auth.renovar(datos.refresh_token)}


@app.post("/api/auth/cambiar-clave")
def cambiar_clave(datos: NuevaClave, request: Request, yo: dict = Depends(usuario_con_clave_pendiente)):
    if config.SUPABASE:
        auth.cambiar_clave(_token(request), datos.nueva)
    db.actualizar("perfil", yo["id"], {"debe_cambiar_clave": 0})
    return {"ok": True}


@app.post("/api/auth/salir")
def salir(request: Request):
    if config.SUPABASE and _token(request):
        auth.cerrar_sesion(_token(request))
    return {"ok": True}


@app.get("/api/sesion")
def sesion(yo: dict | None = Depends(usuario_si_hay_sesion)):
    """Usuario actual (con sesión real) + personas para los desplegables de firmantes."""
    datos = {"modo": {**configuracion()}, **logica.personas()}
    if yo:
        datos["yo"] = _perfil_publico(yo)
    return datos


# ---------------------------------------------------------------------------
# App interna (personal Stracon)
# ---------------------------------------------------------------------------
@app.get("/api/tipos")
def tipos(_: dict = Depends(usuario)):
    return logica.tipos()


@app.get("/api/maestros")
def maestros(_: dict = Depends(usuario)):
    return logica.maestros()


@app.get("/api/protocolos")
def listar(estado: str | None = None, _: dict = Depends(usuario)):
    return logica.listar(estado)


@app.post("/api/protocolos")
def crear(datos: Nuevo, yo: dict = Depends(usuario)):
    return {"id": logica.crear(yo, datos.tipo_id, datos.origen, datos.solicitud)}


@app.get("/api/protocolos/{id_}")
def obtener(id_: str, _: dict = Depends(usuario)):
    return logica.obtener(id_)


@app.put("/api/protocolos/{id_}/valor")
def guardar_valor(id_: str, valor: Valor, yo: dict = Depends(usuario)):
    logica.guardar_valor(yo, id_, valor.model_dump())
    return {"ok": True}


@app.post("/api/protocolos/{id_}/adjuntos")
async def subir_adjunto(id_: str, archivo: UploadFile = File(...), tipo: str = Form("otro"),
                        ref_schema: str = Form(""), yo: dict = Depends(usuario)):
    return logica.subir_adjunto(yo, id_, archivo.filename or "archivo", await archivo.read(), tipo, ref_schema)


@app.get("/api/adjuntos/{adj_id}")
def bajar_adjunto(adj_id: str, _: dict = Depends(usuario)):
    ruta, nombre = logica.archivo_adjunto(adj_id)
    tipo = "application/pdf" if nombre.lower().endswith(".pdf") else "image/png" if nombre.lower().endswith(".png") else "image/jpeg"
    return _archivo(ruta, nombre, tipo)


@app.delete("/api/adjuntos/{adj_id}")
def quitar_adjunto(adj_id: str, yo: dict = Depends(usuario)):
    logica.quitar_adjunto(yo, adj_id)
    return {"ok": True}


@app.post("/api/protocolos/{id_}/enviar-firma")
def enviar_a_firma(id_: str, datos: Firmantes, yo: dict = Depends(usuario)):
    logica.enviar_a_firma(yo, id_, datos.firmantes)
    return {"ok": True}


@app.post("/api/firmas/{firma_id}/firmar")
def firmar(firma_id: str, request: Request, yo: dict = Depends(usuario)):
    return {"estado": logica.firmar(yo, firma_id, _contexto(request))}


@app.post("/api/firmas/{firma_id}/rechazar")
def rechazar(firma_id: str, datos: Motivo, yo: dict = Depends(usuario)):
    logica.rechazar(yo, firma_id, datos.motivo)
    return {"ok": True}


@app.get("/api/protocolos/{id_}/pdf")
def pdf_protocolo(id_: str, version: int | None = None, _: dict = Depends(usuario)):
    return _pdf(logica.ruta_pdf(id_, version))


@app.get("/api/paquetes")
def paquetes(_: dict = Depends(usuario)):
    return logica.paquetes()


@app.post("/api/paquetes")
def crear_paquete(datos: NuevoPaquete, yo: dict = Depends(usuario)):
    return logica.crear_paquete(yo, datos.instancias, datos.contacto_id)


@app.get("/api/paquetes/{paq_id}/hoja-cargo")
def hoja_cargo(paq_id: str, _: dict = Depends(usuario)):
    return _pdf(logica.ruta_hoja_cargo(paq_id))


@app.post("/api/protocolos/{id_}/cambios")
def solicitar_cambio(id_: str, datos: NuevoCambio, yo: dict = Depends(usuario)):
    return logica.solicitar_cambio(yo, id_, datos.motivo, datos.descripcion, datos.contacto_id)


@app.post("/api/cambios/{cambio_id}/decidir")
def decidir_cambio(cambio_id: str, datos: Decision, yo: dict = Depends(usuario)):
    logica.decidir_cambio_calidad(yo, cambio_id, datos.decision, datos.motivo)
    return {"ok": True}


@app.get("/api/qc-index")
def descargar_qc_index(entregable: str | None = None, _: dict = Depends(usuario)):
    sufijo = f"_{entregable}" if entregable else ""
    return Response(qc_index.generar(entregable or None),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="QC-Index{sufijo}.xlsx"'})


@app.get("/api/correos")
def correos(_: dict = Depends(usuario)):
    return logica.correos()


@app.post("/api/reiniciar")
def reiniciar():
    if config.CORREO_REAL or config.SUPABASE or db.POSTGRES:
        raise ErrorNegocio("Solo disponible en la demo local", 403)
    db.reiniciar()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Usuarios y firmantes externos (administradores; la firma escaneada, cada persona la suya)
# ---------------------------------------------------------------------------
@app.get("/api/usuarios")
def usuarios(yo: dict = Depends(usuario)):
    return logica.usuarios(yo)


@app.post("/api/usuarios")
def crear_usuario(datos: DatosUsuario, yo: dict = Depends(usuario)):
    return logica.crear_usuario(yo, datos.model_dump())


@app.patch("/api/usuarios/{uid}")
def editar_usuario(uid: str, datos: DatosUsuario, yo: dict = Depends(usuario)):
    return logica.editar_usuario(yo, uid, datos.model_dump())


@app.post("/api/usuarios/{uid}/restablecer")
def restablecer_clave(uid: str, yo: dict = Depends(usuario)):
    return logica.restablecer_clave(yo, uid)


@app.post("/api/usuarios/{uid}/sello")
async def subir_sello(uid: str, archivo: UploadFile = File(...), yo: dict = Depends(usuario)):
    return logica.subir_sello(yo, uid, await archivo.read())


@app.get("/api/usuarios/{uid}/sello")
def ver_sello(uid: str, _: dict = Depends(usuario)):
    return Response(logica.sello(uid), media_type="image/png")


@app.post("/api/contactos")
def crear_contacto(datos: DatosContacto, yo: dict = Depends(usuario)):
    return logica.guardar_contacto(yo, datos.model_dump(exclude_none=True))


@app.post("/api/contactos/{cid}/sello")
async def subir_firma_contacto(cid: str, archivo: UploadFile = File(...), yo: dict = Depends(usuario)):
    return logica.subir_firma_contacto(yo, cid, await archivo.read())


@app.get("/api/contactos/{cid}/sello")
def ver_firma_contacto(cid: str, _: dict = Depends(usuario)):
    return Response(logica.firma_contacto(cid), media_type="image/png")


@app.delete("/api/contactos/{cid}/sello")
def borrar_firma_contacto(cid: str, yo: dict = Depends(usuario)):
    return logica.borrar_firma_contacto(yo, cid)


@app.patch("/api/contactos/{cid}")
def editar_contacto(cid: str, datos: DatosContacto, yo: dict = Depends(usuario)):
    return logica.guardar_contacto(yo, datos.model_dump(exclude_none=True), cid)


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
    logica.revision_decidir(token, datos.decisiones, datos.codigo, datos.firma, _contexto(request), datos.origen, datos.guardar)
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


# Pantallas de la demo local (HTML/CSS/JS). Va al final para no tapar las rutas /api.
app.mount("/", StaticFiles(directory=config.WEB, html=True), name="web")
