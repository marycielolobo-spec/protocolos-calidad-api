"""Dossier de calidad: un PDF con los protocolos APROBADOS que se entrega al cliente (KP / Hudbay).

Se entrega cada mes, al cerrar el contrato o cuando el cliente pide un rango de fechas. Los filtros son los mismos
para todo: entregable, tipos de registro (formatos) y periodo (fecha del protocolo). El dossier lleva carátula,
índice con la página de cada registro, un separador por tipo de registro y cada protocolo con su reporte
topográfico, planos y constancia de firmas; se acompaña del QC Index con los mismos filtros.
Se envía como un paquete: el cliente descarga y confirma la recepción firmando la Hoja de Cargo.
"""
import secrets
from datetime import date, datetime

from . import almacen, config, correo, db, pdf, qc_index
from . import logica as L
from .logica import CALIDAD, TOPOGRAFICO, ErrorNegocio, _exigir

PUEDEN_ARMAR = CALIDAD | {"control_documentario"}
PUEDEN_VER = PUEDEN_ARMAR | {"consulta"}


def _exigir_armar(yo):
    _exigir(yo["rol"] in PUEDEN_ARMAR or yo.get("es_admin"), "Solo Calidad y Control Documentario arman y envían dossiers")


def _exigir_ver(yo):
    _exigir(yo["rol"] in PUEDEN_VER or yo.get("es_admin"), "Sin acceso a los dossiers")


def _fecha(v, campo):
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        raise ErrorNegocio(f"{campo}: fecha inválida (use AAAA-MM-DD)")


def filtros(entregable=None, tipos=None, desde=None, hasta=None):
    """Filtros normalizados. Sin formatos elegidos = todos (el reporte topográfico va dentro de cada protocolo)."""
    validos = [t["codigo"] for t in L.tipos() if t["codigo"] != TOPOGRAFICO]
    if isinstance(tipos, str):
        tipos = [x for x in tipos.split(",") if x]
    elegidos = [t for t in (tipos or []) if t in validos] or validos
    d, h = _fecha(desde, "Desde"), _fecha(hasta, "Hasta")
    if d and h and d > h:
        raise ErrorNegocio("La fecha inicial es posterior a la final")
    if entregable and entregable not in {e["codigo"] for e in L.maestros()["entregables"]}:
        raise ErrorNegocio("Entregable no válido")
    return {"entregable": entregable or None, "tipos": elegidos, "desde": d and d.isoformat(), "hasta": h and h.isoformat()}


def _grupos(f):
    """[(tipo, [(instancia, fecha), …]), …] de los aprobados que cumplen los filtros, por disciplina y formato."""
    d, h = _fecha(f["desde"], "Desde"), _fecha(f["hasta"], "Hasta")
    tipos = sorted((t for t in L.tipos() if t["codigo"] in f["tipos"]),
                   key=lambda t: ((t.get("qc_index") or {}).get("disciplina") or "", t["codigo"]))
    salida = []
    for t in tipos:
        filas = qc_index.filas_tipo(t, f["entregable"], None, d, h, solo_aprobados=True)
        if filas:
            salida.append((t, filas))
    return salida


def protocolos(yo, **kw):
    """Lo que entraría en el dossier (para revisar antes de armarlo)."""
    _exigir_ver(yo)
    f = filtros(**kw)
    ents = {e["codigo"]: e["nombre"] for e in L.maestros()["entregables"]}
    salida = []
    for t, filas in _grupos(f):
        for i, fecha in filas:
            cab = (i["snapshot"] or {}).get("cabecera") or {}
            rep = db.fila("select correlativo from instancia where vinculado_a = ?", i["id"])
            salida.append({"id": i["id"], "correlativo": i["correlativo"], "numero_registro": L._numero_registro(t, i["correlativo"]),
                           "formato": t["nombre"], "codigo_formato": t["codigo"],
                           "disciplina": (t.get("qc_index") or {}).get("disciplina") or "-",
                           "fecha": fecha and fecha.isoformat(), "entregable": ents.get(cab.get("entregable"), cab.get("entregable")),
                           "estructura": cab.get("estructura"), "reporte_topografico": rep and rep["correlativo"],
                           "descripcion": ((i["snapshot"] or {}).get("respuestas") or {}).get("descripcion") or ""})
    return {"filtros": f, "periodo": qc_index.etiqueta_periodo(_fecha(f["desde"], ""), _fecha(f["hasta"], "")),
            "protocolos": salida}


def _titulo(f):
    ents = {e["codigo"]: e["nombre"] for e in L.maestros()["entregables"]}
    periodo = qc_index.etiqueta_periodo(_fecha(f["desde"], ""), _fecha(f["hasta"], ""))
    return f"Dossier de Calidad — {ents.get(f['entregable'], 'Todos los entregables')} — {periodo}"


def crear(yo, datos):
    """Registra el dossier (estado "pendiente"); el PDF se arma con generar(). Así la pantalla muestra "preparando…"."""
    _exigir_armar(yo)
    f = filtros(datos.get("entregable"), datos.get("tipos"), datos.get("desde"), datos.get("hasta"))
    if not sum(len(x) for _, x in _grupos(f)):
        raise ErrorNegocio("No hay protocolos aprobados con esos filtros")
    id_ = db.nuevo_id()
    codigo = f"DOS-{datetime.now().year}-{db.siguiente('dossier'):04d}"
    db.insertar("dossier", {"id": id_, "codigo": codigo, "titulo": (datos.get("titulo") or "").strip() or _titulo(f),
                            "filtros": f, "estado": "pendiente", "creado_por": yo["id"], "created_at": db.ahora()})
    return {"id": id_, "codigo": codigo}


def generar(yo, id_):
    """Arma el PDF (carátula + índice + separadores + protocolos) y el QC Index. Puede tardar con muchos registros."""
    _exigir_armar(yo)
    d = _dossier(id_)
    if d["estado"] == "listo":
        return _publico(d)
    db.actualizar("dossier", id_, {"estado": "preparando", "mensaje": None})
    try:
        f = d["filtros"]
        grupos = _grupos(f)
        if not grupos:
            raise ErrorNegocio("No hay protocolos aprobados con esos filtros")
        proy = L.proyecto()
        ents = {e["codigo"]: e["nombre"] for e in L.maestros()["entregables"]}
        periodo = qc_index.etiqueta_periodo(_fecha(f["desde"], ""), _fecha(f["hasta"], ""))
        cuerpo, filas_idx, pagina = [], [], 0
        for t, filas in grupos:
            disciplina = (t.get("qc_index") or {}).get("disciplina") or "-"
            sep = pdf.separador_pdf(t["nombre"], f"{t['codigo']} [{proy['codigo_contrato']}] · {disciplina} · {len(filas)} registro(s)",
                                    d["codigo"])
            cuerpo.append(sep)
            pagina += pdf.contar_paginas(sep)
            filas_idx.append({"grupo": f"{t['nombre']} — {t['codigo']}"})
            for i, fecha in filas:
                datos = almacen.leer(L.ruta_pdf(i["id"])[0])
                cab = (i["snapshot"] or {}).get("cabecera") or {}
                rep = db.fila("select correlativo from instancia where vinculado_a = ?", i["id"])
                filas_idx.append({"registro": L._numero_registro(t, i["correlativo"]), "fecha": fecha and fecha.isoformat(),
                                  "estructura": cab.get("estructura") or "-", "rt": rep and rep["correlativo"],
                                  "rel": pagina + 1})
                cuerpo.append(datos)
                pagina += pdf.contar_paginas(datos)
        total = sum(len(x) for _, x in grupos)
        info = {"codigo": d["codigo"], "titulo": d["titulo"], "proyecto": proy["nombre_contrato"], "obra": proy["nombre"],
                "contrato": proy["codigo_contrato"], "cliente": proy["cliente"],
                "entregable": ents.get(f["entregable"], "Todos"), "periodo": periodo, "protocolos": total,
                "generado": db.ahora(), "tipos": [(t["nombre"], len(x)) for t, x in grupos]}
        portada = pdf.dossier_portada(info)
        n_port, n_idx = pdf.contar_paginas(portada), 1
        for _ in range(4):                         # el índice dice en qué página empieza cada registro
            indice = pdf.dossier_indice(info, [{**x, "pagina": n_port + n_idx + x["rel"]} if "rel" in x else x for x in filas_idx])
            if pdf.contar_paginas(indice) == n_idx:
                break
            n_idx = pdf.contar_paginas(indice)
        completo = pdf.unir([portada, indice, *cuerpo])
        tipos_idx = list(f["tipos"]) + [TOPOGRAFICO]
        excel = qc_index.generar(f["entregable"], tipos_idx, _fecha(f["desde"], ""), _fecha(f["hasta"], ""), solo_aprobados=True)
        carpeta = f"dossiers/{id_}"
        db.actualizar("dossier", id_, {
            "estado": "listo", "protocolos": total, "paginas": pdf.contar_paginas(completo), "tamano": len(completo),
            "ruta_pdf": almacen.guardar(f"{carpeta}/{d['codigo']}.pdf", completo, "application/pdf"),
            "ruta_xlsx": almacen.guardar(f"{carpeta}/{d['codigo']}_QC-Index.xlsx", excel,
                                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            "generado_at": db.ahora()})
    except ErrorNegocio as e:
        db.actualizar("dossier", id_, {"estado": "error", "mensaje": str(e)})
        raise
    except Exception as e:                         # se informa y se puede reintentar
        db.actualizar("dossier", id_, {"estado": "error", "mensaje": f"No se pudo armar el dossier ({type(e).__name__})"})
        raise
    return _publico(_dossier(id_))


def _dossier(id_):
    d = db.fila("select * from dossier where id = ?", id_)
    if not d:
        raise ErrorNegocio("Dossier no encontrado", 404)
    return d


def _publico(d):
    envios = db.filas("select p.codigo, p.created_at, p.recibido_at, c.nombre, c.empresa from paquete p "
                      "join contacto c on c.id = p.contacto_id where p.dossier_id = ? order by p.created_at", d["id"])
    autor = db.fila("select nombre from perfil where id = ?", d["creado_por"]) if d["creado_por"] else None
    return {k: d[k] for k in ("id", "codigo", "titulo", "filtros", "estado", "mensaje", "protocolos", "paginas", "tamano",
                              "created_at", "generado_at")} | {"creado_por": autor and autor["nombre"], "envios": envios}


def lista(yo):
    _exigir_ver(yo)
    return [_publico(d) for d in db.filas("select * from dossier order by created_at desc limit 100")]


def archivo(yo, id_, cual):
    _exigir_ver(yo)
    d = _dossier(id_)
    ruta = d["ruta_pdf"] if cual == "pdf" else d["ruta_xlsx"]
    if d["estado"] != "listo" or not ruta:
        raise ErrorNegocio("El dossier aún no está listo", 409)
    return ruta, f"{d['codigo']}.pdf" if cual == "pdf" else f"{d['codigo']}_QC-Index.xlsx"


def enviar(yo, id_, contacto_id):
    """Al cliente: enlace personal para descargar el dossier y el QC Index y confirmar la recepción (Hoja de Cargo)."""
    _exigir_armar(yo)
    d = _dossier(id_)
    if d["estado"] != "listo":
        raise ErrorNegocio("Primero genere el dossier")
    c = L._contacto(contacto_id)
    token = secrets.token_urlsafe(32)
    with db.transaccion():
        paq_id = db.nuevo_id()
        codigo = f"PKG-{datetime.now().year}-{db.siguiente('paquete'):04d}"
        db.insertar("paquete", {"id": paq_id, "codigo": codigo, "contacto_id": c["id"], "token_hash": L._hash(token),
                                "token_demo": None if config.CORREO_REAL else token, "enviado_por": yo["id"],
                                "es_cambio": 0, "dossier_id": id_, "expira_at": L._vence(dias=config.DIAS_VENCE_ENLACE),
                                "created_at": db.ahora()})
        L._generar_hoja_cargo(paq_id)
        correo.enviar([c["email"]], f"[Stracon] {d['titulo']}", [
            f"Estimado(a) {c['nombre']}:",
            f"{yo['nombre']} le envía el {d['titulo']} ({d['protocolos']} registros, {d['paginas']} páginas) y su QC Index.",
            "Desde el enlace puede descargarlos y confirmar la recepción firmando la Hoja de Cargo "
            "(le enviaremos un código a este correo).",
            f"El enlace es personal y vence en {config.DIAS_VENCE_ENLACE} días.",
        ], {"texto": "Ver dossier", "url": f"{config.URL_PORTAL}?t={token}"})
    return {"codigo": codigo, "correo": c["email"], "enlace_demo": None if config.CORREO_REAL else f"{config.URL_PORTAL}?t={token}"}


def del_paquete(p):
    """Dossier entregado en un paquete (portal del cliente)."""
    return _dossier(p["dossier_id"]) if p.get("dossier_id") else None
