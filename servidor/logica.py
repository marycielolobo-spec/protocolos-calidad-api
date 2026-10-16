"""Flujo de los protocolos: estados, firmas, paquetes para KP/Hudbay y control de cambios.

borrador ─enviar─► firma_interna ─(firmas en la app)─► listo_revision ─paquete─► en_revision
   ▲                    │ rechazo                                              │ KP rechaza │ KP acepta y firma
   └──────────────── observado ◄───────────────────────────────────────────────┘            ▼
                                                                                       aprobado (PDF final
   aprobado ─ solicitud de cambio aprobada por KP + Jefatura de Calidad ─► en_modificacion (V+1)   + constancia)

Todas las firmas se hacen en el sistema (sin Acrobat Sign):
- Personal Stracon: con su sesión en la app.
- KP / Hudbay: enlace personal + código de un solo uso enviado a su correo + firma dibujada.
"""
import base64
import hashlib
import io
import re
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image as PilImage

from . import almacen, config, correo, db, pdf, reglas

ESTADOS = {
    "borrador": "Borrador", "firma_interna": "Firma interna", "listo_revision": "Listo para revisión",
    "en_revision": "En revisión (tercero)", "aprobado": "Aprobado", "observado": "Observado",
    "en_modificacion": "En modificación", "anulado": "Anulado",
}
EDITABLE = {"borrador", "observado", "en_modificacion"}
ORDEN_ADJUNTOS = ["topografia", "plano", "croquis", "laboratorio", "calidad", "otro"]
ROL_TITULO = {"elaborado": "Elaborado por", "revisado_aprobado": "Revisado / Aprobado por", "aceptado": "Aceptado por"}

# Roles de las personas (perfil.rol). es_admin es aparte: da de alta usuarios y firmantes externos.
ROLES = {"supervisor_calidad": "Calidad (elabora protocolos)", "jefe_calidad": "Jefatura de Calidad",
         "operaciones": "Operaciones (revisa y aprueba)", "topografia": "Topografía / Oficina Técnica"}
CALIDAD = {"supervisor_calidad", "jefe_calidad"}
TOPOGRAFICO = "ST.CA.PC.001.F001"         # el único formato que llena Topografía


class ErrorNegocio(Exception):
    """Error que se muestra tal cual al usuario."""
    def __init__(self, mensaje, estado=400):
        super().__init__(mensaje)
        self.estado = estado


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _hash(texto):
    return hashlib.sha256(texto.encode()).hexdigest()


def _evento(instancia_id, tipo, detalle=None, actor="sistema"):
    db.insertar("evento", {"id": db.nuevo_id(), "instancia_id": instancia_id, "tipo": tipo,
                           "detalle": detalle or {}, "actor": actor, "created_at": db.ahora()})


def _inst(id_):
    i = db.fila("select * from instancia where id = ?", id_)
    if not i:
        raise ErrorNegocio("Protocolo no encontrado", 404)
    i["conforme"] = None if i["conforme"] is None else bool(i["conforme"])
    return i


def _tipo(id_):
    t = db.fila("select * from tipo where id = ?", id_)
    t["plantilla"] = db.fila("select * from plantilla where id = ?", t["plantilla_id"])
    return t


def _numero_registro(tipo, correlativo):
    """Como en el QC Index: ST.CA.PC.002.F001 [10203002] - ACR-RC-001"""
    return f"{tipo['codigo']} [{proyecto()['codigo_contrato']}] - {correlativo}"


def _sello_svg(nombre):
    """Firma + sello ficticios para la pantalla (demo). En producción: imagen escaneada de cada persona."""
    nombre = re.sub(r"[<&]", "", nombre or "")
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="220" height="76"><circle cx="180" cy="38" r="30" fill="none" '
           'stroke="#0b5cad" stroke-width="2" opacity=".55"/><text x="180" y="42" font-size="9" text-anchor="middle" '
           'fill="#0b5cad" opacity=".7">STRACON</text><path d="M10 50 C40 10, 60 70, 90 30 S140 50, 150 28" fill="none" '
           f'stroke="#1d232b" stroke-width="2"/><text x="10" y="70" font-size="10" fill="#5b6673">{nombre}</text></svg>')
    return "data:image/svg+xml," + urllib.parse.quote(svg)


def _ruta_sello(perfil_id):
    return f"sellos/{perfil_id}.png"


def _firmas(instancia_id, version):
    """Firmas para mostrar en pantalla (con la imagen de cada firma)."""
    fs = db.filas("select * from firma where instancia_id = ? and version = ? order by orden", instancia_id, version)
    for f in fs:
        f["sello_url"] = None
        if f["estado"] == "firmado":
            f["sello_url"] = f["firma_imagen"] if f["canal"] == "externo" else _sello_svg(f["nombre"])
        f.pop("firma_imagen", None)
    return fs


def _imagen_firma(f):
    """PNG de la firma para el PDF."""
    if f["canal"] == "externo":
        return _png_de_data_url(f["firma_imagen"]) if f.get("firma_imagen") else None
    try:
        return almacen.leer(_ruta_sello(f["perfil_id"]))
    except almacen.ArchivoNoEncontrado:                # sin firma escaneada todavía: sello de ejemplo
        return pdf.sello_demo_png(f["nombre"] or "")


def _firmas_pdf(instancia_id, version):
    fs = db.filas("select * from firma where instancia_id = ? and version = ? order by orden", instancia_id, version)
    for f in fs:
        f["imagen"] = _imagen_firma(f) if f["estado"] == "firmado" else None
    return fs


def _png_de_data_url(url):
    return base64.b64decode(url.split(",", 1)[1])


def _validar_firma_dibujada(url):
    if not url or not url.startswith("data:image/png;base64,"):
        raise ErrorNegocio("Dibuje su firma en el recuadro")
    try:
        datos = _png_de_data_url(url)
        if len(datos) > 400_000:
            raise ErrorNegocio("La imagen de la firma es demasiado grande")
        img = PilImage.open(io.BytesIO(datos))
        img.verify()
    except ErrorNegocio:
        raise
    except Exception:
        raise ErrorNegocio("La firma no es una imagen válida")


def _exigir(condicion, mensaje):
    if not condicion:
        raise ErrorNegocio(mensaje, 403)


def _puede_elaborar(yo, tipo_id):
    """Calidad llena cualquier formato; Topografía, solo el Reporte Topográfico; Operaciones solo revisa y firma."""
    return yo["rol"] in CALIDAD or (yo["rol"] == "topografia" and tipo_id == TOPOGRAFICO)


def _exigir_elaborar(yo, tipo_id):
    _exigir(_puede_elaborar(yo, tipo_id), "Su rol no permite llenar este formato"
            + (" (Topografía solo llena el Reporte Topográfico)" if yo["rol"] == "topografia" else ""))


def _contacto(id_):
    c = db.fila("select * from contacto where id = ? and activo = 1", id_)
    if not c:
        raise ErrorNegocio("Destinatario no válido")
    return c


def _editable(i):
    if i["estado"] not in EDITABLE:
        raise ErrorNegocio(f'El protocolo está "{ESTADOS.get(i["estado"], i["estado"])}" y no puede editarse. '
                           "Para modificar un protocolo aprobado registre una solicitud de cambio.")


def _vence(dias=0, minutos=0):
    return (datetime.now(timezone.utc) + timedelta(days=dias, minutes=minutos)).isoformat()


def _vencido(iso):
    return datetime.fromisoformat(iso) < datetime.now(timezone.utc)


def _guardar_archivo(carpeta, nombre, datos):
    return almacen.guardar(f"{carpeta}/{nombre}", datos)


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------
def personas():
    return {"perfiles": db.filas("select id, nombre, cargo, email, empresa, rol, es_admin from perfil where activo = 1 order by rowid"),
            "contactos": db.filas("select * from contacto where activo = 1 order by rowid")}


def tipos():
    return [_tipo(t["id"]) for t in db.filas("select id from tipo where activo = 1 order by codigo")]


def proyecto():
    return db.fila("select * from proyecto where activo = 1 limit 1")


def maestros():
    """Desplegables: entregable → estructuras y planos; listas (turno, material, equipos…)."""
    entregables = db.filas("select codigo, nombre from entregable order by orden")
    for e in entregables:
        e["estructuras"] = db.filas("select codigo, nombre from estructura where entregable = ? order by orden", e["codigo"])
        e["planos"] = [p["codigo"] for p in db.filas("select codigo from plano where entregable = ? order by orden", e["codigo"])]
    listas = {}
    for f in db.filas("select clave, valor from lista order by clave, orden"):
        listas.setdefault(f["clave"], []).append(f["valor"])
    return {"proyecto": proyecto(), "entregables": entregables, "listas": listas}


def listar(estado=None):
    sql = "select * from instancia" + (" where estado = ?" if estado else "") + " order by updated_at desc limit 500"
    filas = db.filas(sql, *([estado] if estado else []))
    tipos_ = {t["id"]: t for t in db.filas("select id, codigo, sigla, nombre, categoria from tipo")}
    for i in filas:
        i["conforme"] = None if i["conforme"] is None else bool(i["conforme"])
        i["tipo"] = tipos_.get(i["tipo_id"])
    return filas


def obtener(id_):
    inst = _inst(id_)
    versiones = db.filas("select * from version where instancia_id = ? order by numero desc", id_)
    for v in versiones:
        v["firmas"] = _firmas(id_, v["numero"])
        v["tiene_pdf"] = bool(v["pdf_firmado"] or v["pdf_revision"])
        v["pdf_firmado_listo"] = bool(v["pdf_firmado"])
        for k in ("pdf_revision", "pdf_firmado", "snapshot"):
            v.pop(k, None)
    cambios = db.filas("select * from cambio where instancia_id = ? order by created_at desc", id_)
    for c in cambios:
        p = db.fila("select token_demo from paquete where cambio_id = ?", c["id"])
        c["enlace_demo"] = f"{config.URL_PORTAL}?t={p['token_demo']}" if p and p["token_demo"] else None
    tipo = _tipo(inst["tipo_id"])
    return {
        "inst": inst,
        "tipo": tipo,
        "numero_registro": _numero_registro(tipo, inst["correlativo"]) if inst["correlativo"] else None,
        "firmas": _firmas(id_, inst["version_actual"]),
        "versiones": versiones,
        "adjuntos": db.filas("select id, instancia_id, version, tipo, ref_schema, nombre_archivo, tamano, created_at "
                             "from adjunto where instancia_id = ? and version = ? order by created_at",
                             id_, inst["version_actual"]),
        "eventos": db.filas("select * from evento where instancia_id = ? order by created_at desc, rowid desc", id_),
        "cambios": cambios,
    }


# ---------------------------------------------------------------------------
# Crear y llenar
# ---------------------------------------------------------------------------
def crear(yo, tipo_id, origen, solicitud):
    if not db.fila("select id from tipo where id = ? and activo = 1", tipo_id):
        raise ErrorNegocio("Tipo de protocolo no válido")
    _exigir_elaborar(yo, tipo_id)
    if origen not in ("solicitud_operaciones", "backlog"):
        raise ErrorNegocio("Origen no válido")
    v = reglas.valor_vacio(proyecto())
    id_ = db.nuevo_id()
    with db.transaccion():
        db.insertar("instancia", {"id": id_, "tipo_id": tipo_id, "origen": origen, "solicitud": solicitud,
                                  "cabecera": v["cabecera"], "respuestas": v["respuestas"], "conforme": None,
                                  "estado": "borrador", "version_actual": 0, "creado_por": yo["id"],
                                  "created_at": db.ahora(), "updated_at": db.ahora()})
        _evento(id_, "creado", {"origen": origen}, yo["email"])
    return id_


def guardar_valor(yo, id_, valor):
    with db.transaccion():
        i = _inst(id_)
        _editable(i)
        _exigir_elaborar(yo, i["tipo_id"])
        p = proyecto()
        cabecera = dict(valor.get("cabecera") or {})
        # Lo que pone el sistema no se puede cambiar desde la pantalla
        cabecera.update({"correlativo": i["correlativo"] or "", "proyecto": p["nombre"], "cliente": p["cliente"]})
        if i["correlativo"]:
            # El correlativo lleva el código del entregable (ACR-RC-001): ya no puede cambiar de entregable
            cabecera["entregable"] = i["cabecera"].get("entregable")
        if not isinstance(cabecera.get("plano_ref"), list):
            cabecera["plano_ref"] = []
        conforme = valor.get("conforme")
        db.actualizar("instancia", id_, {"cabecera": cabecera, "respuestas": valor.get("respuestas") or {},
                                         "conforme": None if conforme is None else int(bool(conforme)),
                                         "updated_at": db.ahora()})


def subir_adjunto(yo, id_, nombre, datos, tipo, ref_schema):
    if not re.search(r"\.(pdf|png|jpe?g)$", nombre, re.I):
        raise ErrorNegocio("Solo se aceptan archivos PDF, PNG o JPG")
    with db.transaccion():
        i = _inst(id_)
        _editable(i)
        _exigir_elaborar(yo, i["tipo_id"])
        seguro = re.sub(r"[^\w.-]+", "_", nombre)
        ruta = _guardar_archivo(f"adjuntos/{id_}/V{i['version_actual']}", f"{db.nuevo_id()}-{seguro}", datos)
        a = {"id": db.nuevo_id(), "instancia_id": id_, "version": i["version_actual"], "tipo": tipo,
             "ref_schema": ref_schema or None, "nombre_archivo": nombre, "ruta": ruta, "tamano": len(datos),
             "subido_por": yo["id"], "created_at": db.ahora()}
        db.insertar("adjunto", a)
    return a


def quitar_adjunto(yo, adj_id):
    with db.transaccion():
        a = db.fila("select * from adjunto where id = ?", adj_id)
        if not a:
            raise ErrorNegocio("Adjunto no encontrado", 404)
        i = _inst(a["instancia_id"])
        _editable(i)
        _exigir_elaborar(yo, i["tipo_id"])
        if a["version"] != i["version_actual"]:
            raise ErrorNegocio("Ese adjunto pertenece a una versión cerrada")
        db.ejecutar("delete from adjunto where id = ?", adj_id)
    almacen.borrar(a["ruta"])


def archivo_adjunto(adj_id):
    a = db.fila("select * from adjunto where id = ?", adj_id)
    if not a:
        raise ErrorNegocio("Adjunto no encontrado", 404)
    return a["ruta"], a["nombre_archivo"]


# ---------------------------------------------------------------------------
# Firmas internas (personal Stracon, en la app)
# ---------------------------------------------------------------------------
def enviar_a_firma(yo, id_, firmantes):
    with db.transaccion():
        i = _inst(id_)
        _editable(i)
        _exigir_elaborar(yo, i["tipo_id"])
        t = _tipo(i["tipo_id"])
        adjuntos = db.filas("select * from adjunto where instancia_id = ? and version = ?", id_, i["version_actual"])
        errores = reglas.validar(t, i, maestros())
        if errores:
            raise ErrorNegocio(f"Faltan {len(errores)} dato(s): " + "; ".join(e["mensaje"] for e in errores[:3])
                               + (" …" if len(errores) > 3 else ""))
        faltan = reglas.faltan_adjuntos(t, i, adjuntos)
        if faltan:
            raise ErrorNegocio(f'Marcó "Sí" pero falta subir: {", ".join(faltan)}')

        motivo = None
        if i["version_actual"] > 0:
            c = db.fila("select motivo from cambio where instancia_id = ? and decision_calidad = 'aceptado' and "
                        "decision_externo = 'aceptado' order by created_at desc", id_)
            motivo = c and c["motivo"]

        db.ejecutar("delete from firma where instancia_id = ? and version = ?", id_, i["version_actual"])
        db.ejecutar("delete from version where instancia_id = ? and numero = ?", id_, i["version_actual"])
        for orden, r in enumerate(t["plantilla"]["roles"], start=1):
            sel = firmantes.get(r["rol"]) or {}
            p = db.fila("select * from perfil where id = ? and activo = 1", sel.get("perfil_id")) if sel.get("perfil_id") else None
            c = db.fila("select * from contacto where id = ? and activo = 1", sel.get("contacto_id")) if sel.get("contacto_id") else None
            if r["canal"] == "app" and not p:
                raise ErrorNegocio(f'Falta firmante para "{ROL_TITULO[r["rol"]]}"')
            quien = p or c or {}
            db.insertar("firma", {"id": db.nuevo_id(), "instancia_id": id_, "version": i["version_actual"],
                                  "rol": r["rol"], "orden": orden, "canal": r["canal"],
                                  "perfil_id": p and p["id"], "contacto_id": c and c["id"],
                                  "empresa_nombre": r["empresa"], "nombre": quien.get("nombre"),
                                  "cargo": quien.get("cargo"), "email": quien.get("email"), "estado": "pendiente"})

        # Correlativo: sigla del formato + código del entregable + número (ACR-RC-001), uno por formato y entregable
        correlativo = i["correlativo"]
        if not correlativo:
            entregable = i["cabecera"]["entregable"]
            n = db.siguiente(f"correlativo:{t['codigo']}:{entregable}")
            correlativo = f"{t['sigla']}-{entregable}-{n:03d}"
        cabecera = {**i["cabecera"], "correlativo": correlativo}
        db.insertar("version", {"id": db.nuevo_id(), "instancia_id": id_, "numero": i["version_actual"],
                                "motivo": motivo, "modificado_por": yo["email"],
                                "snapshot": {"cabecera": cabecera, "respuestas": i["respuestas"], "conforme": i["conforme"]},
                                "created_at": db.ahora()})
        db.actualizar("instancia", id_, {"correlativo": correlativo, "cabecera": cabecera,
                                         "estado": "firma_interna", "updated_at": db.ahora()})
        _evento(id_, "enviado_firma", {"version": i["version_actual"], "correlativo": correlativo}, yo["email"])


def _recalcular(id_):
    i = _inst(id_)
    fs = db.filas("select * from firma where instancia_id = ? and version = ?", id_, i["version_actual"])
    if any(f["estado"] == "rechazado" for f in fs):
        estado = "observado"
    elif any(f["canal"] == "app" and f["estado"] == "pendiente" for f in fs):
        estado = "firma_interna"
    elif any(f["estado"] == "pendiente" for f in fs):
        estado = "listo_revision"          # falta un firmante externo (KP / Hudbay): va en un paquete
    else:
        estado = "aprobado"
    db.actualizar("instancia", id_, {"estado": estado, "updated_at": db.ahora()})
    return estado


def _firma_mia(yo, firma_id):
    f = db.fila("select * from firma where id = ?", firma_id)
    if not f:
        raise ErrorNegocio("Firma no encontrada", 404)
    if f["canal"] != "app" or f["perfil_id"] != yo["id"]:
        raise ErrorNegocio("Esta firma corresponde a otra persona", 403)
    if f["estado"] != "pendiente":
        raise ErrorNegocio("Esta firma ya fue registrada")
    i = _inst(f["instancia_id"])
    if i["estado"] != "firma_interna" or f["version"] != i["version_actual"]:
        raise ErrorNegocio("El protocolo no está en firma interna")
    return f


def firmar(yo, firma_id, contexto=None):
    with db.transaccion():
        f = _firma_mia(yo, firma_id)
        previas = db.filas("select estado from firma where instancia_id = ? and version = ? and orden < ?",
                           f["instancia_id"], f["version"], f["orden"])
        if any(x["estado"] != "firmado" for x in previas):
            raise ErrorNegocio("Firma secuencial: falta la firma previa")
        db.actualizar("firma", firma_id, {"estado": "firmado", "firmado_at": db.ahora(),
                                          "evidencia": {"metodo": "Sesión en la app (personal Stracon)", **(contexto or {})}})
        _evento(f["instancia_id"], "firmado", {"rol": f["rol"]}, yo["email"])
        estado = _recalcular(f["instancia_id"])
    if estado == "listo_revision":
        _intentar_pdf(f["instancia_id"])                 # PDF para que KP lo revise
    elif estado == "aprobado":
        _intentar_pdf(f["instancia_id"], final=True)     # plantilla sin firmante externo
    return estado


def rechazar(yo, firma_id, motivo):
    if not (motivo or "").strip():
        raise ErrorNegocio("El motivo es obligatorio")
    with db.transaccion():
        f = _firma_mia(yo, firma_id)
        db.actualizar("firma", firma_id, {"estado": "rechazado", "motivo_rechazo": motivo.strip(), "firmado_at": db.ahora()})
        _evento(f["instancia_id"], "rechazado", {"rol": f["rol"], "motivo": motivo.strip()}, yo["email"])
        _recalcular(f["instancia_id"])


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def generar_pdf(id_, final=False):
    """Arma el PDF de la versión vigente: formulario + adjuntos (PDF/imágenes) en orden.
    final=True agrega la hoja de constancia de firmas con el código de verificación (SHA-256)."""
    i = _inst(id_)
    n = i["version_actual"]
    v = db.fila("select * from version where instancia_id = ? and numero = ?", id_, n)
    if not v:
        raise ErrorNegocio("Este protocolo todavía no tiene una versión enviada a firma")
    tipo = _tipo(i["tipo_id"])
    numero = _numero_registro(tipo, i["correlativo"])
    firmas = _firmas_pdf(id_, n)
    formulario = pdf.protocolo_pdf(tipo, v["snapshot"], firmas, n, maestros(), numero, i["correlativo"])

    adjuntos = db.filas("select * from adjunto where instancia_id = ? and version = ?", id_, n)
    adjuntos.sort(key=lambda a: (ORDEN_ADJUNTOS.index(a["tipo"]) if a["tipo"] in ORDEN_ADJUNTOS else 99, a["created_at"]))
    partes = [formulario]
    for a in adjuntos:
        datos = almacen.leer(a["ruta"])
        partes.append(pdf.imagen_a_pdf(datos) if pdf.es_imagen(a["nombre_archivo"]) else datos)
    contenido = pdf.unir(partes)
    carpeta = f"pdfs/{id_}/V{n}"

    if not final:
        with db.transaccion():
            db.actualizar("version", v["id"], {"pdf_revision": _guardar_archivo(carpeta, "revision.pdf", contenido),
                                               "paginas": pdf.contar_paginas(contenido)})
        return contenido

    huella = hashlib.sha256(contenido).hexdigest()
    constancia = pdf.constancia_pdf({
        "numero_registro": numero, "titulo": tipo["nombre"], "version": n, "hash": huella, "generado": db.ahora(),
        "firmas": [{"rol": ROL_TITULO[f["rol"]], "nombre": f["nombre"], "cargo": f["cargo"], "empresa": f["empresa_nombre"],
                    "email": f["email"], "fecha": f["firmado_at"], "metodo": (f["evidencia"] or {}).get("metodo", "-"),
                    "ip": (f["evidencia"] or {}).get("ip"), "dispositivo": (f["evidencia"] or {}).get("dispositivo")}
                   for f in firmas if f["estado"] == "firmado"],
    })
    completo = pdf.unir([contenido, constancia])
    with db.transaccion():
        db.actualizar("version", v["id"], {"pdf_firmado": _guardar_archivo(carpeta, "firmado.pdf", completo),
                                           "pdf_hash": huella, "paginas": pdf.contar_paginas(contenido)})
    return completo


def _intentar_pdf(id_, final=False):
    try:
        generar_pdf(id_, final)
    except Exception as e:                      # el flujo sigue; el PDF se puede generar luego desde la app
        print(f"[pdf] No se pudo generar el PDF de {id_}: {e}")


def ruta_pdf(id_, numero=None):
    """Mejor PDF disponible de una versión: el firmado si existe, si no el de revisión (lo genera si falta)."""
    i = _inst(id_)
    numero = i["version_actual"] if numero is None else numero
    v = db.fila("select * from version where instancia_id = ? and numero = ?", id_, numero)
    if not v or (numero == i["version_actual"] and i["estado"] in EDITABLE | {"firma_interna"}):
        raise ErrorNegocio("El PDF se genera cuando terminan las firmas internas", 404)
    if numero == i["version_actual"] and i["estado"] == "aprobado" and not v["pdf_firmado"]:
        generar_pdf(id_, final=True)
    elif not (v["pdf_firmado"] or v["pdf_revision"]):
        generar_pdf(id_)
    v = db.fila("select * from version where id = ?", v["id"])
    ruta = v["pdf_firmado"] or v["pdf_revision"]
    sufijo = "" if v["pdf_firmado"] else "_para-revision"
    return ruta, f"{i['correlativo']}_V{numero}{sufijo}.pdf"


# ---------------------------------------------------------------------------
# Paquete para el tercero (KP / Hudbay) y Hoja de Cargo
# ---------------------------------------------------------------------------
def crear_paquete(yo, ids, contacto_id):
    _exigir(yo["rol"] in CALIDAD, "Solo Calidad envía paquetes a revisión")
    if not ids:
        raise ErrorNegocio("Seleccione al menos un protocolo")
    contacto = _contacto(contacto_id)
    insts = [_inst(x) for x in ids]
    no_listos = [i["correlativo"] for i in insts if i["estado"] != "listo_revision"]
    if no_listos:
        raise ErrorNegocio(f"No están listos para revisión: {', '.join(no_listos)}")

    for i in insts:                              # PDF faltantes (normalmente ya se generaron)
        v = db.fila("select pdf_revision from version where instancia_id = ? and numero = ?", i["id"], i["version_actual"])
        if not v["pdf_revision"]:
            _intentar_pdf(i["id"])

    token = secrets.token_urlsafe(32)
    with db.transaccion():
        for i in insts:
            f = db.fila("select * from firma where instancia_id = ? and version = ? and canal = 'externo' and "
                        "estado = 'pendiente' order by orden limit 1", i["id"], i["version_actual"])
            if not f:
                raise ErrorNegocio(f"{i['correlativo']}: no tiene firma externa pendiente")
            if f["contacto_id"] and f["contacto_id"] != contacto["id"]:
                raise ErrorNegocio(f"{i['correlativo']}: asignado a otro firmante externo")
            db.actualizar("firma", f["id"], {"contacto_id": contacto["id"], "nombre": contacto["nombre"],
                                             "cargo": contacto["cargo"], "email": contacto["email"]})
        codigo = f"PKG-{datetime.now().year}-{db.siguiente('paquete'):04d}"
        paq_id = db.nuevo_id()
        db.insertar("paquete", {"id": paq_id, "codigo": codigo, "contacto_id": contacto["id"], "token_hash": _hash(token),
                                "token_demo": None if config.CORREO_REAL else token, "enviado_por": yo["id"],
                                "es_cambio": 0, "expira_at": _vence(dias=config.DIAS_VENCE_ENLACE), "created_at": db.ahora()})
        for i in insts:
            db.insertar("paquete_item", {"paquete_id": paq_id, "instancia_id": i["id"], "version": i["version_actual"]})
            db.actualizar("instancia", i["id"], {"estado": "en_revision", "updated_at": db.ahora()})
            _evento(i["id"], "notificacion", {"a": contacto["email"], "paquete": codigo}, yo["email"])
        _generar_hoja_cargo(paq_id)
        correo.enviar([contacto["email"]], f"[Stracon] Paquete {codigo}: {len(insts)} protocolo(s) para revisión", [
            f"Estimado(a) {contacto['nombre']}:",
            f"{yo['nombre']} ({yo['cargo'] or 'Calidad Stracon'}) le envía {len(insts)} protocolo(s) para revisión: "
            f"{', '.join(i['correlativo'] for i in insts)}.",
            "Puede aceptar o rechazar cada uno (todo rechazo requiere motivo). Para registrar su respuesta le enviaremos "
            "un código a este correo y firmará en la misma página. Se incluye la Hoja de Cargo de los documentos entregados.",
            f"No necesita cuenta ni licencia. El enlace es personal y vence en {config.DIAS_VENCE_ENLACE} días.",
        ], {"texto": "Revisar protocolos", "url": f"{config.URL_PORTAL}?t={token}"})
    return {"codigo": codigo, "correo": contacto["email"]}


def _generar_hoja_cargo(paq_id):
    """Hoja de Cargo de Distribución (ST.CA.PG.001.F007): lista de registros entregados y firma de recepción."""
    p = db.fila("select * from paquete where id = ?", paq_id)
    c = db.fila("select * from contacto where id = ?", p["contacto_id"])
    proy = proyecto()
    registros = []
    for it in db.filas("select * from paquete_item where paquete_id = ? order by rowid", paq_id):
        i = _inst(it["instancia_id"])
        t = _tipo(i["tipo_id"])
        registros.append({"codigo": f"{t['codigo']} [{proy['codigo_contrato']}]", "reg": i["correlativo"],
                          "descripcion": f"{t['nombre']} — {i['cabecera'].get('estructura') or ''}"})
    firma = _png_de_data_url(p["recibido_firma"]) if p["recibido_firma"] else None
    datos = pdf.hoja_cargo_pdf({
        "contrato": proy["codigo_contrato"], "proyecto_distribucion": proy["proyecto_distribucion"],
        "nombre_proyecto": proy["nombre"], "cliente": proy["cliente"], "n_registro": p["codigo"], "fecha": p["created_at"],
        "areas": [("A", f"{c['empresa']} — Supervisión")], "registros": registros,
        "distribucion": [{"nombre": c["nombre"], "area": c["empresa"], "firma": firma, "fecha": p["recibido_at"]}],
    })
    db.actualizar("paquete", paq_id, {"hoja_cargo": _guardar_archivo(f"paquetes/{paq_id}", "hoja-cargo.pdf", datos)})


def ruta_hoja_cargo(paq_id):
    p = db.fila("select * from paquete where id = ?", paq_id)
    if not p or not p["hoja_cargo"]:
        raise ErrorNegocio("Hoja de cargo no encontrada", 404)
    return p["hoja_cargo"], f"{p['codigo']}_hoja-de-cargo.pdf"


def paquetes():
    ps = db.filas("select * from paquete where es_cambio = 0 order by created_at desc limit 50")
    for p in ps:
        p["items"] = db.filas("select * from paquete_item where paquete_id = ?", p["id"])
        p["enlace_demo"] = f"{config.URL_PORTAL}?t={p['token_demo']}" if p["token_demo"] else None
        p["firmado_recepcion"] = bool(p["recibido_at"])
        for k in ("token_hash", "token_demo", "otp_hash", "otp_expira", "recibido_firma"):
            p.pop(k, None)
    return ps


# ---------------------------------------------------------------------------
# Portal externo (sin cuenta: enlace personal + código al correo)
# ---------------------------------------------------------------------------
def _paquete_por_token(token):
    if not token or len(token) < 20:
        raise ErrorNegocio("Enlace inválido", 404)
    p = db.fila("select * from paquete where token_hash = ?", _hash(token))
    if not p:
        raise ErrorNegocio("Enlace inválido o vencido", 404)
    if _vencido(p["expira_at"]):
        raise ErrorNegocio("El enlace venció. Solicite uno nuevo a Calidad Stracon.", 410)
    return p


def _enmascarar(email):
    usuario, _, dominio = email.partition("@")
    return f"{usuario[:2]}{'•' * max(1, len(usuario) - 2)}@{dominio}"


def _detalle_externo(token, instancia_id, numero):
    """Lo que ve el tercero: la versión congelada (no el borrador en curso), sin datos internos."""
    i = _inst(instancia_id)
    v = db.fila("select * from version where instancia_id = ? and numero = ?", instancia_id, numero)
    t = _tipo(i["tipo_id"])
    firmas = [{k: f[k] for k in ("rol", "orden", "canal", "empresa_nombre", "nombre", "cargo", "estado",
                                  "firmado_at", "sello_url")} for f in _firmas(instancia_id, numero)]
    adjuntos = db.filas("select tipo, nombre_archivo from adjunto where instancia_id = ? and version = ?",
                        instancia_id, numero)
    vista = {"id": i["id"], "correlativo": i["correlativo"], **(v["snapshot"] if v else {})}
    return {"inst": vista, "tipo": {k: t[k] for k in ("codigo", "nombre", "revision_formato", "schema")},
            "numero_registro": _numero_registro(t, i["correlativo"]),
            "firmas": firmas, "adjuntos": adjuntos,
            "pdf_url": f"/api/revision/{token}/pdf/{instancia_id}" if v else None}


def revision_obtener(token):
    p = _paquete_por_token(token)
    c = _contacto(p["contacto_id"])
    items = db.filas("select * from paquete_item where paquete_id = ? order by rowid", p["id"])
    items = [{**it, **_detalle_externo(token, it["instancia_id"], it["version"])} for it in items]
    cambios = []
    if p["es_cambio"]:
        cb = db.fila("select * from cambio where id = ?", p["cambio_id"])
        cambios = [{"motivo": cb["motivo"], "descripcion": cb["descripcion"], "solicitado_por": cb["solicitado_por"]}]
    return {"paquete": {"codigo": p["codigo"], "es_cambio": bool(p["es_cambio"]), "cerrado_at": p["cerrado_at"],
                        "hoja_cargo_url": f"/api/revision/{token}/hoja-cargo" if p["hoja_cargo"] else None,
                        "recibido_at": p["recibido_at"]},
            "contacto": {"nombre": c["nombre"], "empresa": c["empresa"], "correo": _enmascarar(c["email"])},
            "maestros": maestros(), "items": items, "cambios": cambios}


def revision_pdf(token, instancia_id):
    p = _paquete_por_token(token)
    it = db.fila("select * from paquete_item where paquete_id = ? and instancia_id = ?", p["id"], instancia_id)
    if not it:
        raise ErrorNegocio("Protocolo no encontrado en este paquete", 404)
    return ruta_pdf(instancia_id, it["version"])


def revision_hoja_cargo(token):
    return ruta_hoja_cargo(_paquete_por_token(token)["id"])


def solicitar_codigo(token):
    """Envía al correo del revisor un código de 6 dígitos (vence en 10 minutos) para confirmar su identidad."""
    p = _paquete_por_token(token)
    if p["cerrado_at"]:
        raise ErrorNegocio("Este paquete ya fue respondido")
    c = _contacto(p["contacto_id"])
    codigo = f"{secrets.randbelow(1_000_000):06d}"
    with db.transaccion():
        db.actualizar("paquete", p["id"], {"otp_hash": _hash(p["token_hash"] + codigo), "otp_intentos": 0,
                                           "otp_expira": _vence(minutos=config.MINUTOS_VENCE_CODIGO)})
        correo.enviar([c["email"]], f"[Stracon] Código para firmar: {codigo}", [
            f"Su código para firmar en el paquete {p['codigo']} es: {codigo}",
            f"Vence en {config.MINUTOS_VENCE_CODIGO} minutos. Si usted no lo solicitó, ignore este correo.",
        ])
    return {"correo": _enmascarar(c["email"]), "minutos": config.MINUTOS_VENCE_CODIGO}


def _verificar_codigo(p, codigo):
    """Se revisa fuera de la transacción: así cada intento fallido queda contado."""
    if not p["otp_hash"]:
        raise ErrorNegocio("Primero solicite el código de firma")
    if _vencido(p["otp_expira"]):
        raise ErrorNegocio("El código venció. Solicite uno nuevo.")
    if p["otp_intentos"] >= config.INTENTOS_CODIGO:
        raise ErrorNegocio("Demasiados intentos. Solicite un código nuevo.")
    if not secrets.compare_digest(_hash(p["token_hash"] + (codigo or "").strip()), p["otp_hash"]):
        db.actualizar("paquete", p["id"], {"otp_intentos": p["otp_intentos"] + 1})
        raise ErrorNegocio("Código incorrecto")


def _consumir_codigo(p):
    """El código sirve una sola vez (se llama dentro de la transacción de la decisión)."""
    db.actualizar("paquete", p["id"], {"otp_hash": None, "otp_expira": None, "otp_intentos": 0})


def _evidencia_externa(c, contexto):
    return {"metodo": f"Enlace personal + código enviado a {c['email']}", "codigo_verificado_at": db.ahora(),
            **(contexto or {})}


def revision_decidir(token, decisiones, codigo, firma_imagen, contexto=None):
    """KP / Hudbay acepta o rechaza cada protocolo y firma. Los aceptados quedan firmados en ese momento."""
    p = _paquete_por_token(token)
    if p["es_cambio"]:
        raise ErrorNegocio("Acción inválida")
    if not decisiones:
        raise ErrorNegocio("Marque Aceptar o Rechazar en al menos un protocolo")
    if any(d.get("decision") not in ("aceptado", "rechazado") for d in decisiones):
        raise ErrorNegocio("Decisión inválida")
    if any(d["decision"] == "rechazado" and not (d.get("motivo") or "").strip() for d in decisiones):
        raise ErrorNegocio("Todo rechazo requiere motivo")
    _validar_firma_dibujada(firma_imagen)
    c = _contacto(p["contacto_id"])
    evidencia = _evidencia_externa(c, contexto)

    _verificar_codigo(p, codigo)
    aprobados = []
    with db.transaccion():
        _consumir_codigo(p)
        for d in decisiones:
            it = db.fila("select * from paquete_item where paquete_id = ? and instancia_id = ? and decision = 'pendiente'",
                         p["id"], d["instancia_id"])
            if not it:
                continue                         # ya decidido o no pertenece al paquete
            motivo = (d.get("motivo") or "").strip() or None
            db.ejecutar("update paquete_item set decision = ?, motivo = ?, decidido_at = ? "
                        "where paquete_id = ? and instancia_id = ?", d["decision"], motivo, db.ahora(), p["id"], it["instancia_id"])
            f = db.fila("select * from firma where instancia_id = ? and version = ? and contacto_id = ? and estado = 'pendiente' "
                        "order by orden limit 1", it["instancia_id"], it["version"], c["id"])
            if d["decision"] == "rechazado":
                if f:
                    db.actualizar("firma", f["id"], {"estado": "rechazado", "motivo_rechazo": motivo, "firmado_at": db.ahora(),
                                                     "evidencia": evidencia})
                db.actualizar("instancia", it["instancia_id"], {"estado": "observado", "updated_at": db.ahora()})
                _evento(it["instancia_id"], "rechazado", {"rol": f and f["rol"], "motivo": motivo, "paquete": p["codigo"]}, c["email"])
            else:
                _evento(it["instancia_id"], "aceptado_revision", {"paquete": p["codigo"]}, c["email"])
                if f:
                    db.actualizar("firma", f["id"], {"estado": "firmado", "firmado_at": db.ahora(), "firma_imagen": firma_imagen,
                                                     "evidencia": evidencia})
                    _evento(it["instancia_id"], "firmado", {"rol": f["rol"], "canal": "externo"}, c["email"])
                if _recalcular(it["instancia_id"]) == "aprobado":
                    aprobados.append(it["instancia_id"])

        items = db.filas("select * from paquete_item where paquete_id = ?", p["id"])
        if all(x["decision"] != "pendiente" for x in items):
            db.actualizar("paquete", p["id"], {"cerrado_at": db.ahora()})
        if not p["recibido_at"]:                 # firma de recepción en la Hoja de Cargo
            db.actualizar("paquete", p["id"], {"recibido_firma": firma_imagen, "recibido_at": db.ahora()})
            _generar_hoja_cargo(p["id"])

        rech = sum(1 for d in decisiones if d["decision"] == "rechazado")
        emisor = db.fila("select * from perfil where id = ?", p["enviado_por"])
        correo.enviar([emisor["email"]], f"[Stracon] {p['codigo']}: {len(decisiones) - rech} aceptado(s), {rech} rechazado(s)", [
            f"{c['nombre']} ({c['empresa']}) registró y firmó sus decisiones en el paquete {p['codigo']}.",
            'Los rechazados volvieron a estado "Observado" con el motivo indicado.' if rech else "Sin rechazos.",
            "Los aceptados quedaron aprobados y su PDF final (con la constancia de firmas) ya está en el sistema.",
        ])

    for id_ in aprobados:
        _intentar_pdf(id_, final=True)


# ---------------------------------------------------------------------------
# Control de cambios (modificar un protocolo aprobado → V+1)
# ---------------------------------------------------------------------------
def solicitar_cambio(yo, id_, motivo, descripcion, contacto_id):
    _exigir(yo["rol"] in CALIDAD, "Solo Calidad solicita modificaciones")
    if not (motivo or "").strip():
        raise ErrorNegocio("El motivo es obligatorio")
    contacto = _contacto(contacto_id)
    token = secrets.token_urlsafe(32)
    with db.transaccion():
        i = _inst(id_)
        if i["estado"] != "aprobado":
            raise ErrorNegocio("Solo aplica a protocolos aprobados")
        if db.fila("select id from cambio where instancia_id = ? and resuelta_at is null", id_):
            raise ErrorNegocio("Ya hay una solicitud de cambio pendiente")
        cambio_id = db.nuevo_id()
        db.insertar("cambio", {"id": cambio_id, "instancia_id": id_, "version_base": i["version_actual"],
                               "solicitado_por": yo["email"], "motivo": motivo.strip(), "descripcion": descripcion,
                               "contacto_id": contacto["id"], "created_at": db.ahora()})
        # Para el portal externo la solicitud viaja como un "paquete" de un solo protocolo
        paq_id = db.nuevo_id()
        db.insertar("paquete", {"id": paq_id, "codigo": f"CAMBIO-{i['correlativo']}-V{i['version_actual'] + 1}",
                                "contacto_id": contacto["id"], "token_hash": _hash(token),
                                "token_demo": None if config.CORREO_REAL else token, "enviado_por": yo["id"],
                                "es_cambio": 1, "cambio_id": cambio_id, "expira_at": _vence(dias=config.DIAS_VENCE_ENLACE),
                                "created_at": db.ahora()})
        db.insertar("paquete_item", {"paquete_id": paq_id, "instancia_id": id_, "version": i["version_actual"]})
        jefes = [p["email"] for p in db.filas("select email from perfil where rol = 'jefe_calidad' and activo = 1")]
        _evento(id_, "cambio_solicitado", {"motivo": motivo.strip(), "a": [contacto["email"], *jefes]}, yo["email"])
        asunto = f"[Stracon] Solicitud de modificación de {i['correlativo']}"
        texto = [f"{yo['nombre']} solicita modificar el protocolo aprobado {i['correlativo']} (V{i['version_actual']}).",
                 f"Motivo: {motivo.strip()}", f"Cambios previstos: {descripcion or '—'}",
                 f"Si la Jefatura de Calidad y la supervisión aprueban, se abrirá la versión V{i['version_actual'] + 1}."]
        correo.enviar([contacto["email"]], asunto, texto,
                      {"texto": "Revisar solicitud", "url": f"{config.URL_PORTAL}?t={token}"})
        if jefes:
            correo.enviar(jefes, asunto, texto, {"texto": "Abrir protocolo", "url": f"{config.URL_APP}/p/{id_}"})
    return {"correo": contacto["email"]}


def decidir_cambio_calidad(yo, cambio_id, decision, motivo):
    _exigir(yo["rol"] == "jefe_calidad", "Solo la Jefatura de Calidad decide")
    if decision not in ("aceptado", "rechazado"):
        raise ErrorNegocio("Decisión inválida")
    if decision == "rechazado" and not (motivo or "").strip():
        raise ErrorNegocio("El motivo es obligatorio")
    with db.transaccion():
        c = db.fila("select * from cambio where id = ?", cambio_id)
        if not c or c["resuelta_at"] or c["decision_calidad"] != "pendiente":
            raise ErrorNegocio("Esta solicitud ya fue respondida")
        db.actualizar("cambio", cambio_id, {"decision_calidad": decision, "motivo_calidad": motivo,
                                            "decidido_calidad_por": yo["email"]})
        _evento(c["instancia_id"], f"cambio_{decision}_calidad", {"motivo": motivo}, yo["email"])
        _aplicar_cambio(cambio_id)


def decidir_cambio_externo(token, decision, motivo, codigo):
    p = _paquete_por_token(token)
    if not p["es_cambio"]:
        raise ErrorNegocio("Enlace inválido")
    if decision not in ("aceptado", "rechazado"):
        raise ErrorNegocio("Decisión inválida")
    if decision == "rechazado" and not (motivo or "").strip():
        raise ErrorNegocio("El motivo es obligatorio")
    c_ext = _contacto(p["contacto_id"])
    _verificar_codigo(p, codigo)
    with db.transaccion():
        _consumir_codigo(p)
        c = db.fila("select * from cambio where id = ?", p["cambio_id"])
        if c["decision_externo"] != "pendiente" or c["resuelta_at"]:
            raise ErrorNegocio("Esta solicitud ya fue respondida")
        db.actualizar("cambio", c["id"], {"decision_externo": decision, "motivo_externo": motivo or None})
        db.ejecutar("update paquete_item set decision = ?, motivo = ?, decidido_at = ? where paquete_id = ?",
                    decision, motivo or None, db.ahora(), p["id"])
        db.actualizar("paquete", p["id"], {"cerrado_at": db.ahora()})
        _evento(c["instancia_id"], f"cambio_{decision}_externo", {"motivo": motivo}, c_ext["email"])
        _aplicar_cambio(c["id"])


def _aplicar_cambio(cambio_id):
    """Rechazo de cualquiera = se cierra. Aprobación de ambos = se abre V+1 (la versión anterior queda intacta)."""
    c = db.fila("select * from cambio where id = ?", cambio_id)
    if c["resuelta_at"]:
        return
    if "rechazado" in (c["decision_calidad"], c["decision_externo"]):
        db.actualizar("cambio", cambio_id, {"resuelta_at": db.ahora()})
        _evento(c["instancia_id"], "cambio_rechazado", {})
    elif c["decision_calidad"] == "aceptado" and c["decision_externo"] == "aceptado":
        db.actualizar("cambio", cambio_id, {"resuelta_at": db.ahora()})
        nueva = c["version_base"] + 1
        db.actualizar("instancia", c["instancia_id"], {"version_actual": nueva, "estado": "en_modificacion",
                                                       "updated_at": db.ahora()})
        _evento(c["instancia_id"], "version_nueva", {"version": nueva, "motivo": c["motivo"]})


def correos():
    return db.filas("select * from correo order by created_at desc, rowid desc limit 100")


# ---------------------------------------------------------------------------
# Usuarios (personal Stracon) y firmantes externos (KP / Hudbay)
# ---------------------------------------------------------------------------
_CAMPOS_PERFIL = "id, nombre, cargo, email, empresa, rol, es_admin, debe_cambiar_clave, tiene_sello, activo"


def _exigir_admin(yo):
    _exigir(yo.get("es_admin"), "Solo un administrador puede gestionar usuarios")


def _validar_rol(rol):
    if rol not in ROLES:
        raise ErrorNegocio(f"Rol no válido. Opciones: {', '.join(ROLES)}")


def _normalizar_email(email):
    email = (email or "").strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ErrorNegocio("Correo no válido")
    return email


def usuarios(yo):
    _exigir_admin(yo)
    return {"usuarios": db.filas(f"select {_CAMPOS_PERFIL} from perfil order by activo desc, nombre"),
            "contactos": db.filas("select * from contacto order by activo desc, empresa, nombre"), "roles": ROLES}


def crear_usuario(yo, datos):
    """Alta de una persona de Stracon. Devuelve la contraseña temporal (se muestra una sola vez al administrador)."""
    _exigir_admin(yo)
    from . import auth
    nombre = (datos.get("nombre") or "").strip()
    if not nombre:
        raise ErrorNegocio("El nombre es obligatorio")
    email = _normalizar_email(datos.get("email"))
    rol = datos.get("rol") or "supervisor_calidad"
    _validar_rol(rol)
    if db.fila("select id from perfil where email = ?", email):
        raise ErrorNegocio("Ya existe un usuario con ese correo")
    clave = auth.clave_temporal()
    uid = auth.crear_usuario(email, clave, nombre) if config.SUPABASE else db.nuevo_id()
    with db.transaccion():
        db.insertar("perfil", {"id": uid, "nombre": nombre, "cargo": (datos.get("cargo") or "").strip(), "email": email,
                               "empresa": datos.get("empresa") or "Stracon", "rol": rol,
                               "es_admin": int(bool(datos.get("es_admin"))), "debe_cambiar_clave": 1})
    return {"usuario": db.fila(f"select {_CAMPOS_PERFIL} from perfil where id = ?", uid),
            "clave_temporal": clave if config.SUPABASE else None}


def editar_usuario(yo, uid, cambios):
    _exigir_admin(yo)
    u = db.fila("select * from perfil where id = ?", uid)
    if not u:
        raise ErrorNegocio("Usuario no encontrado", 404)
    datos = {}
    for k in ("nombre", "cargo"):
        if k in cambios and cambios[k] is not None:
            datos[k] = str(cambios[k]).strip()
    if cambios.get("rol") is not None:
        _validar_rol(cambios["rol"])
        datos["rol"] = cambios["rol"]
    for k in ("es_admin", "activo"):
        if cambios.get(k) is not None:
            datos[k] = int(bool(cambios[k]))
    if uid == yo["id"] and (datos.get("es_admin") == 0 or datos.get("activo") == 0):
        raise ErrorNegocio("No puede quitarse a sí mismo el acceso de administrador")
    if not datos:
        return u
    if "activo" in datos and datos["activo"] != u["activo"] and config.SUPABASE:
        from . import auth
        auth.bloquear(uid, not datos["activo"])
    db.actualizar("perfil", uid, datos)
    return db.fila(f"select {_CAMPOS_PERFIL} from perfil where id = ?", uid)


def restablecer_clave(yo, uid):
    _exigir_admin(yo)
    if not db.fila("select id from perfil where id = ?", uid):
        raise ErrorNegocio("Usuario no encontrado", 404)
    from . import auth
    clave = auth.clave_temporal()
    if config.SUPABASE:
        auth.fijar_clave(uid, clave)
    db.actualizar("perfil", uid, {"debe_cambiar_clave": 1})
    return {"clave_temporal": clave if config.SUPABASE else None}


def subir_sello(yo, uid, datos):
    """Firma y sello escaneados de un firmante interno (la persona misma o un administrador). Se guarda como PNG."""
    _exigir(uid == yo["id"] or yo.get("es_admin"), "Solo puede cambiar su propia firma")
    if not db.fila("select id from perfil where id = ?", uid):
        raise ErrorNegocio("Usuario no encontrado", 404)
    if len(datos) > 3_000_000:
        raise ErrorNegocio("La imagen es demasiado grande (máximo 3 MB)")
    try:
        img = PilImage.open(io.BytesIO(datos))
        img.load()
    except Exception:
        raise ErrorNegocio("La firma debe ser una imagen PNG o JPG")
    img.thumbnail((900, 360))
    salida = io.BytesIO()
    img.convert("RGBA").save(salida, "PNG")
    almacen.guardar(_ruta_sello(uid), salida.getvalue(), "image/png")
    db.actualizar("perfil", uid, {"tiene_sello": 1})
    return {"ok": True}


def sello(uid):
    try:
        return almacen.leer(_ruta_sello(uid))
    except almacen.ArchivoNoEncontrado:
        raise ErrorNegocio("Sin firma escaneada", 404)


def guardar_contacto(yo, datos, cid=None):
    """Alta o edición de un firmante externo (KP / Hudbay). No tiene cuenta: firma por enlace + código."""
    _exigir_admin(yo)
    valores = {"nombre": (datos.get("nombre") or "").strip(), "cargo": (datos.get("cargo") or "").strip(),
               "empresa": (datos.get("empresa") or "").strip()}
    if "email" in datos or not cid:
        valores["email"] = _normalizar_email(datos.get("email"))
    if datos.get("activo") is not None:
        valores["activo"] = int(bool(datos["activo"]))
    if not cid:
        if not valores["nombre"] or not valores["empresa"]:
            raise ErrorNegocio("Nombre y empresa son obligatorios")
        if db.fila("select id from contacto where email = ?", valores["email"]):
            raise ErrorNegocio("Ya existe un firmante con ese correo")
        cid = db.nuevo_id()
        db.insertar("contacto", {"id": cid, **valores})
    else:
        db.actualizar("contacto", cid, {k: v for k, v in valores.items() if v != "" or k == "cargo"})
    return db.fila("select * from contacto where id = ?", cid)
