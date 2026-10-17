"""Reglas de llenado de un protocolo (las mismas que muestra el formulario en pantalla).

El servidor las vuelve a revisar antes de enviar a firma: así nadie puede saltárselas
aunque manipule el navegador.
"""
from datetime import date

NEGATIVAS = {"NO", "NC"}

CABECERA = [
    {"id": "proyecto", "label": "Nombre del proyecto"},
    {"id": "cliente", "label": "Cliente"},
    {"id": "entregable", "label": "Entregable / Área", "requerido": True},
    {"id": "estructura", "label": "Estructura / Frente", "requerido": True},
    {"id": "correlativo", "label": "N° correlativo"},
    {"id": "fecha", "label": "Fecha", "requerido": True},
    {"id": "elemento", "label": "Elemento"},
    {"id": "plano_ref", "label": "Plano ref."},
]


def valor_vacio(proyecto):
    cabecera = {"proyecto": proyecto.get("nombre") or "", "cliente": proyecto.get("cliente") or "",
                "entregable": "", "estructura": "", "plano_ref": [], "fecha": date.today().isoformat()}
    respuestas = {"checklist": {}, "campos": {}, "tablas": {}, "adjuntos": {}, "descripcion": "", "observaciones": ""}
    return {"cabecera": cabecera, "respuestas": respuestas, "conforme": None}


def _vacio(v):
    return not str(v if v is not None else "").strip()


def validar(tipo, valor, maestros=None):
    """Devuelve la lista de errores [{campo, mensaje}]. Lista vacía = protocolo completo.
    Con maestros, además revisa que entregable y estructura existan y correspondan entre sí."""
    errs = []
    cabecera = valor.get("cabecera") or {}
    respuestas = valor.get("respuestas") or {}
    conforme = valor.get("conforme")
    s = tipo["schema"]

    for c in CABECERA:
        if c.get("requerido") and _vacio(cabecera.get(c["id"])):
            errs.append({"campo": f"cab_{c['id']}", "mensaje": f"{c['label']}: obligatorio"})

    if maestros and cabecera.get("entregable"):
        ent = next((e for e in maestros["entregables"] if e["codigo"] == cabecera["entregable"]), None)
        if not ent:
            errs.append({"campo": "cab_entregable", "mensaje": "Entregable / Área: no existe en la lista"})
        elif cabecera.get("estructura") and cabecera["estructura"] not in [x["nombre"] for x in ent["estructuras"]]:
            errs.append({"campo": "cab_estructura", "mensaje": "Estructura / Frente: no pertenece al entregable elegido"})

    for sec in s["secciones"]:
        if sec["tipo"] == "checklist" and not sec.get("fijo"):          # las fijas las pone el sistema
            for g in sec["grupos"]:
                for it in g["items"]:
                    if it.get("solo_extra"):
                        continue
                    a = (respuestas.get("checklist") or {}).get(it["id"]) or {}
                    texto = it["texto"][:60]
                    if not a.get("r"):
                        errs.append({"campo": it["id"], "mensaje": f'"{texto}…": sin respuesta'})
                    elif a["r"] in NEGATIVAS and _vacio(a.get("obs")):
                        errs.append({"campo": it["id"], "mensaje": f'"{texto}…": respuesta {a["r"]} requiere observación'})
        if sec["tipo"] == "tabla" and sec.get("requerida"):
            filas = (respuestas.get("tablas") or {}).get(sec["id"]) or []
            if not any(any(str(v or "").strip() for v in f.values()) for f in filas):
                errs.append({"campo": f"tabla:{sec['id']}", "mensaje": f"{sec['titulo']}: sin datos"})
        if sec["tipo"] == "campos":
            for c in sec["campos"]:
                if c.get("requerido") and _vacio((respuestas.get("campos") or {}).get(c["id"])):
                    errs.append({"campo": c["id"], "mensaje": f"{c['label']}: obligatorio"})

    if s.get("conformidad"):
        if conforme is None:
            errs.append({"campo": "conforme", "mensaje": f"{s['conformidad']['pregunta']}: sin respuesta"})
        elif conforme is False and _vacio(respuestas.get("observaciones")):
            errs.append({"campo": "conforme", "mensaje": "Si no es conforme, indique el motivo en Observaciones"})

    for a in s.get("adjuntos") or []:
        if not ((respuestas.get("adjuntos") or {}).get(a["id"]) or {}).get("adjunta"):
            errs.append({"campo": f"adj_{a['id']}", "mensaje": f"¿Se adjunta {a['label']}?: sin respuesta"})
    return errs


def faltan_adjuntos(tipo, valor, adjuntos):
    """Si marcó "Sí se adjunta…", el archivo tiene que estar subido. El reporte topográfico no se sube: se elige
    de los validados (y su plano viaja en el mismo PDF)."""
    marcados = (valor.get("respuestas") or {}).get("adjuntos") or {}
    faltan = []
    for a in tipo["schema"].get("adjuntos") or []:
        m = marcados.get(a["id"]) or {}
        if m.get("adjunta") != "SI" or m.get("en_reporte"):
            continue
        if a.get("fuente") == "reporte_topo":
            if not m.get("reporte_id"):
                faltan.append(f"{a['label']} (elíjalo de la lista de reportes validados)")
        elif not any(x["ref_schema"] == a["id"] for x in adjuntos):
            faltan.append(a["label"])
    return faltan
