"""PDF 100 % en Python (ReportLab + pypdf + Pillow). Sin Adobe ni navegador: funciona en cualquier servidor.

- protocolo_pdf(): dibuja cualquier formato desde su definición (protocolos/tipos.json), con el mismo orden
  que la pantalla: cabecera, secciones, conformidad, adjuntos, observaciones y firmas.
- constancia_pdf(): hoja final con la evidencia de cada firma y el código de verificación (SHA-256).
- hoja_cargo_pdf(): Hoja de Cargo de Distribución de Documentos (ST.CA.PG.001.F007) de cada paquete.
- imagen_a_pdf(), unir(), contar_paginas(): adjuntos y armado del PDF final.
"""
import io
import math
import re
from datetime import datetime
from functools import lru_cache
from xml.sax.saxutils import escape

from PIL import Image as PilImage, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import config

AZUL = colors.HexColor("#15284B")        # azul corporativo (Brandbook ST.MK.MA.001)
ROJO_MARCA = colors.HexColor("#F42534")  # rojo corporativo
LINEA = colors.HexColor("#8a96a3")
FONDO = colors.HexColor("#e6ecf2")
GRIS = colors.HexColor("#5b6673")
ROJO = colors.HexColor("#b42318")
ANCHO = A4[0] - 20 * mm            # ancho útil (márgenes de 10 mm)

OPCIONES = {"SI_NO_NA": [("SI", "SI"), ("NO", "NO"), ("NA", "N.A.")],
            "C_NC_NA": [("C", "C"), ("NC", "NC"), ("NA", "NA"), ("-", "(-)")]}
LEYENDA_C_NC = "(-) No se requiere inspección · (C) Conforme · (NC) No conforme · (NA) No aplica"
ROLES = [("elaborado", "ELABORADO POR"), ("revisado_aprobado", "REVISADO / APROBADO POR"), ("aceptado", "ACEPTADO POR")]

_base = ParagraphStyle("base", fontName="Helvetica", fontSize=7.5, leading=9.5)
E = {
    "base": _base,
    "neg": ParagraphStyle("neg", parent=_base, fontName="Helvetica-Bold"),
    "chico": ParagraphStyle("chico", parent=_base, fontSize=6.5, leading=8, textColor=GRIS),
    "etq": ParagraphStyle("etq", parent=_base, fontName="Helvetica-Bold", fontSize=6.5, leading=8, textColor=GRIS),
    "centro": ParagraphStyle("centro", parent=_base, alignment=TA_CENTER),
    "titulo": ParagraphStyle("titulo", parent=_base, fontName="Helvetica-Bold", fontSize=11, leading=13, alignment=TA_CENTER),
    "sec": ParagraphStyle("sec", parent=_base, fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=AZUL,
                          spaceBefore=6, spaceAfter=3),
    "logo": ParagraphStyle("logo", parent=_base, fontName="Helvetica-Bold", fontSize=12, leading=14, textColor=AZUL,
                           alignment=TA_CENTER),
}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _p(texto, estilo="base"):
    return Paragraph(escape(str(texto if texto is not None else "")).replace("\n", "<br/>"), E[estilo])


def _ph(html, estilo="base"):
    """Párrafo con marcas simples (<b>, <i>, <br/>) ya armadas."""
    return Paragraph(html, E[estilo])


def fecha_hora(v):
    """'2026-10-12' → '12/10/2026' · '2026-10-12T08:30' → '12/10/2026 08:30' · ISO UTC → hora de Perú."""
    if not v:
        return ""
    s = str(v)
    if s.endswith("Z") or "+" in s[10:]:
        d = datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(config.ZONA_PERU)
        return d.strftime("%d/%m/%Y %H:%M")
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}:\d{2}))?", s)
    if not m:
        return s
    y, mo, d, h = m.groups()
    return f"{d}/{mo}/{y}" + (f" {h}" if h else "")


def _texto(v, tipo=None):
    if v is None:
        return ""
    if isinstance(v, list):
        return ", ".join(str(x) for x in v if x)
    if tipo in ("date", "datetime"):
        return fecha_hora(v)
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _marca(valor, opciones, etiquetas=None):
    """Casillas marcadas como en el formato en papel: [X] Sí   [ ] No (devuelve HTML para _ph)."""
    return "&nbsp;&nbsp;&nbsp;&nbsp;".join(
        f"[{'X' if valor == o else '&nbsp;&nbsp;'}] {escape(etiquetas[i] if etiquetas else o)}" for i, o in enumerate(opciones))


def _estilo_tabla(extra=()):
    return TableStyle([("GRID", (0, 0), (-1, -1), 0.5, LINEA), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                       ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                       ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2), *extra])


def _imagen(datos, ancho_max, alto_max):
    if not datos:
        return ""
    img = PilImage.open(io.BytesIO(datos))
    k = min(ancho_max / img.width, alto_max / img.height)
    return Image(io.BytesIO(datos), width=img.width * k, height=img.height * k)


class _Lienzo(rl_canvas.Canvas):
    """Pone "Página x de y" y el N° de registro al pie de cada página."""
    def __init__(self, *args, pie="", **kwargs):
        super().__init__(*args, **kwargs)
        self._estados, self._pie = [], pie

    def showPage(self):
        self._estados.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._estados)
        for estado in self._estados:
            self.__dict__.update(estado)
            self.setFont("Helvetica", 6.5)
            self.setFillColor(GRIS)
            self.drawString(10 * mm, 6 * mm, self._pie)
            self.drawRightString(A4[0] - 10 * mm, 6 * mm, f"Página {self._pageNumber} de {total}")
            super().showPage()
        super().save()


def _documento(historia, pie):
    salida = io.BytesIO()
    doc = SimpleDocTemplate(salida, pagesize=A4, leftMargin=10 * mm, rightMargin=10 * mm,
                            topMargin=10 * mm, bottomMargin=12 * mm, title=pie, author="Stracon — Control de Calidad")
    doc.build(historia, canvasmaker=lambda *a, **k: _Lienzo(*a, pie=pie, **k))
    return salida.getvalue()


def _logo():
    ruta = config.WEB / "img" / "logo.png"           # logo oficial (Brandbook: versión principal a color)
    if ruta.exists():
        return _imagen(ruta.read_bytes(), 31 * mm, 12 * mm)
    return _p("STRACON", "logo")


def _encabezado(titulo, codigo, lineas_derecha, subtitulo="REGISTRO<br/>ÁREA CONTROL DE CALIDAD"):
    centro = [_ph(subtitulo, "centro"), Spacer(1, 2), _p(titulo.upper(), "titulo")]
    derecha = [_ph(f"<b>{escape(codigo)}</b>")] + [_p(x) for x in lineas_derecha]
    t = Table([[_logo(), centro, derecha]], colWidths=[36 * mm, ANCHO - 86 * mm, 50 * mm])
    t.setStyle(_estilo_tabla([("ALIGN", (0, 0), (0, 0), "CENTER"), ("LINEBELOW", (0, 0), (-1, 0), 1.5, ROJO_MARCA)]))
    return t


# ---------------------------------------------------------------------------
# Sello de demostración (cuando la persona aún no tiene su firma escaneada)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=64)
def sello_demo_png(nombre):
    img = PilImage.new("RGBA", (440, 152), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    azul = (11, 92, 173, 150)
    d.ellipse((300, 16, 420, 136), outline=azul, width=4)
    fuente = ImageFont.load_default(size=18)
    d.text((360, 76), "STRACON", fill=azul, font=fuente, anchor="mm")
    puntos = [(20 + x, 92 - 34 * math.sin(x / 26) * (1 - x / 400)) for x in range(0, 280, 4)]
    d.line(puntos, fill=(29, 35, 43, 255), width=4, joint="curve")
    d.text((20, 130), nombre[:40], fill=(91, 102, 115, 255), font=ImageFont.load_default(size=17))
    salida = io.BytesIO()
    img.save(salida, "PNG")
    return salida.getvalue()


# ---------------------------------------------------------------------------
# Protocolo
# ---------------------------------------------------------------------------
def _cabecera(cab, maestros, correlativo):
    ent = next((e for e in maestros["entregables"] if e["codigo"] == cab.get("entregable")), None)
    planos = _texto([*(cab.get("plano_ref") or []), cab.get("plano_otro")])
    filas = [
        ("NOMBRE DEL PROYECTO", cab.get("proyecto"), "N° CORRELATIVO", correlativo),
        ("CLIENTE", cab.get("cliente"), "FECHA", fecha_hora(cab.get("fecha"))),
        ("ENTREGABLE / ÁREA", ent["nombre"] if ent else cab.get("entregable"), "ELEMENTO", cab.get("elemento") or "-"),
        ("ESTRUCTURA / FRENTE", cab.get("estructura"), "PLANO REF.", planos or "-"),
    ]
    datos = [[_p(a, "etq"), _p(b), _p(c, "etq"), _p(d)] for a, b, c, d in filas]
    t = Table(datos, colWidths=[32 * mm, 63 * mm, 27 * mm, ANCHO - 122 * mm])
    t.setStyle(_estilo_tabla([("BACKGROUND", (0, 0), (0, -1), FONDO), ("BACKGROUND", (2, 0), (2, -1), FONDO)]))
    return t


def _checklist(sec, r):
    ops = OPCIONES[sec["opciones"]]
    an_op, an_obs, an_n = 9 * mm, 42 * mm, 8 * mm
    an_desc = ANCHO - an_n - an_op * len(ops) - an_obs
    datos = [[_p("ÍTEM", "etq"), _p("DESCRIPCIÓN DE ACTIVIDADES", "etq"), *[_p(l, "etq") for _, l in ops], _p("OBSERVACIONES", "etq")]]
    estilo = [("BACKGROUND", (0, 0), (-1, 0), FONDO), ("ALIGN", (2, 0), (-2, -1), "CENTER"), ("ALIGN", (0, 0), (0, -1), "CENTER")]
    respuestas = r.get("checklist") or {}
    n = 0
    for g in sec["grupos"]:
        if g.get("titulo"):
            fila = len(datos)
            datos.append([_p(g["titulo"].upper(), "neg")] + [""] * (len(ops) + 2))
            estilo += [("SPAN", (0, fila), (-1, fila)), ("BACKGROUND", (0, fila), (-1, fila), FONDO)]
        for it in g["items"]:
            a = respuestas.get(it["id"]) or {}
            texto = escape(it["texto"])
            if it.get("ayuda"):
                texto += f"<br/><i><font color='#5b6673'>{escape(it['ayuda'])}</font></i>"
            if it.get("solo_extra"):
                fila = len(datos)
                datos.append(["", _ph(texto), _p(_texto(a.get("extra"), (it.get("extra") or {}).get("tipo")))] + [""] * len(ops))
                estilo.append(("SPAN", (2, fila), (-1, fila)))
                continue
            n += 1
            if it.get("extra"):
                texto += (f"<br/><font color='#5b6673'>{escape(it['extra']['label'])}:</font> "
                          f"<b>{escape(_texto(a.get('extra'), it['extra'].get('tipo')))}</b>")
            datos.append([_p(n), _ph(texto), *[_p("X" if a.get("r") == v else "", "neg") for v, _ in ops], _p(a.get("obs"))])
    t = Table(datos, colWidths=[an_n, an_desc, *[an_op] * len(ops), an_obs], repeatRows=1)
    t.setStyle(_estilo_tabla(estilo))
    salida = [_p(sec["titulo"].upper(), "sec")]
    if sec["opciones"] == "C_NC_NA":
        salida.append(_p(LEYENDA_C_NC, "chico"))
    return salida + [t]


def _campos(sec, r):
    valores = r.get("campos") or {}
    celdas, radios = [], []
    for c in sec["campos"]:
        v = valores.get(c["id"])
        etq = _p(c["label"].upper(), "etq")
        if c.get("tipo") == "radio":
            radios.append([etq, _ph(_marca(v, c["opciones"]))])
        else:
            celdas.append([etq, _p(f"{_texto(v, c.get('tipo'))} {c.get('unidad', '') if v not in (None, '') else ''}".strip())])
    datos = [radio + ["", ""] for radio in radios]
    estilo = [("SPAN", (1, i), (3, i)) for i in range(len(radios))]
    for i in range(0, len(celdas), 2):
        par = celdas[i] + (celdas[i + 1] if i + 1 < len(celdas) else ["", ""])
        datos.append(par)
    estilo.append(("BACKGROUND", (0, 0), (0, -1), FONDO))
    if celdas:
        estilo.append(("BACKGROUND", (2, len(radios)), (2, -1), FONDO))
    t = Table(datos, colWidths=[38 * mm, ANCHO / 2 - 38 * mm, 38 * mm, ANCHO / 2 - 38 * mm])
    t.setStyle(_estilo_tabla(estilo))
    return [_p(sec["titulo"].upper(), "sec"), t]


def _tabla(sec, r):
    filas = (r.get("tablas") or {}).get(sec["id"]) or []
    fijas = sec.get("filas_fijas")
    n = len(fijas) if fijas else max(len(filas), sec.get("filas_min") or 1)
    cab = ([""] if fijas else []) + [c["label"] for c in sec["columnas"]]
    datos = [[_p(x.upper(), "etq") for x in cab]]
    for i in range(n):
        f = filas[i] if i < len(filas) else {}
        datos.append(([_p(fijas[i], "neg")] if fijas else []) + [_p(_texto(f.get(c["id"]), c.get("tipo"))) for c in sec["columnas"]])
    t = Table(datos, colWidths=[ANCHO / len(cab)] * len(cab), repeatRows=1)
    t.setStyle(_estilo_tabla([("BACKGROUND", (0, 0), (-1, 0), FONDO)]))
    salida = [_p(sec["titulo"].upper(), "sec"), t]
    if sec.get("nota"):
        salida.append(_p(sec["nota"], "chico"))
    return salida


def _cierre(schema, r, conforme):
    datos, estilo = [], []
    if schema.get("conformidad"):
        v = "SI" if conforme is True else "NO" if conforme is False else None
        datos.append([_p(schema["conformidad"]["pregunta"], "neg"), _ph(_marca(v, ["SI", "NO"], ["Sí", "No"]))])
    for a in schema.get("adjuntos") or []:
        v = (r.get("adjuntos") or {}).get(a["id"]) or {}
        numero = f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;N° {escape(str(v['numero']))}" if v.get("numero") else ""
        datos.append([_p(a.get("pregunta") or f"¿Se adjunta {a['label']}?"),
                      _ph(_marca(v.get("adjunta"), ["SI", "NA"], ["Sí", "NA"]) + numero)])
    salida = []
    if datos:
        t = Table(datos, colWidths=[95 * mm, ANCHO - 95 * mm])
        t.setStyle(_estilo_tabla(estilo))
        salida += [Spacer(1, 6), t]
    obs = Table([[_p("OBSERVACIONES", "etq")], [_p(r.get("observaciones") or ("" if schema.get("sin_observaciones") else "-"))]],
                colWidths=[ANCHO])
    obs.setStyle(_estilo_tabla([("BACKGROUND", (0, 0), (-1, 0), FONDO), ("TOPPADDING", (0, 1), (-1, 1), 4),
                                ("BOTTOMPADDING", (0, 1), (-1, 1), 8)]))
    return salida + [Spacer(1, 6), obs]


def _firmas(firmas):
    por_rol = {f["rol"]: f for f in firmas}
    titulos, cajas, datos_f = [], [], []
    for rol, titulo in ROLES:
        f = por_rol.get(rol) or {}
        titulos.append(_p(titulo, "neg"))
        if f.get("estado") == "firmado":
            caja = _imagen(f.get("imagen"), 55 * mm, 20 * mm) or _p("Firmado electrónicamente", "centro")
        elif f.get("estado") == "rechazado":
            caja = _ph("<font color='#b42318'><b>RECHAZADO</b></font>", "centro")
        else:
            caja = ""
        cajas.append(caja)
        datos_f.append(_ph(f"<font color='#5b6673'>Nombre:</font> {escape(f.get('nombre') or '')}<br/>"
                           f"<font color='#5b6673'>Cargo:</font> {escape(f.get('cargo') or '')}<br/>"
                           f"<font color='#5b6673'>Empresa:</font> {escape(f.get('empresa_nombre') or '')}<br/>"
                           f"<font color='#5b6673'>Fecha:</font> "
                           f"{fecha_hora(f.get('fecha_mostrar') or f.get('firmado_at')) if f.get('estado') == 'firmado' else ''}"))
    t = Table([titulos, cajas, datos_f], colWidths=[ANCHO / 3] * 3, rowHeights=[None, 23 * mm, None])
    t.setStyle(_estilo_tabla([("ALIGN", (0, 1), (-1, 1), "CENTER"), ("VALIGN", (0, 2), (-1, 2), "TOP")]))
    return KeepTogether([Spacer(1, 10), t])


def protocolo_pdf(tipo, valor, firmas, version, maestros, numero_registro, correlativo):
    """firmas: [{rol, nombre, cargo, empresa_nombre, estado, firmado_at, imagen (PNG en bytes)}]"""
    contrato = maestros["proyecto"]["codigo_contrato"]
    cab = valor.get("cabecera") or {}
    r = valor.get("respuestas") or {}
    historia = [
        _encabezado(tipo["nombre"], f"{tipo['codigo']} [{contrato}]",
                    [f"Revisión: {tipo.get('revision_formato') or 0}", f"Versión del registro: V{version}"]),
        Spacer(1, 6), _cabecera(cab, maestros, correlativo),
        Spacer(1, 4),
    ]
    desc = Table([[_p("DESCRIPCIÓN DEL TRABAJO", "etq")], [_p(r.get("descripcion") or "-")]], colWidths=[ANCHO])
    desc.setStyle(_estilo_tabla([("BACKGROUND", (0, 0), (-1, 0), FONDO)]))
    historia.append(desc)
    for sec in tipo["schema"]["secciones"]:
        if sec["tipo"] == "checklist":
            historia += _checklist(sec, r)
        elif sec["tipo"] == "campos":
            historia += _campos(sec, r)
        elif sec["tipo"] == "tabla":
            historia += _tabla(sec, r)
    historia += _cierre(tipo["schema"], r, valor.get("conforme"))
    historia.append(_firmas(firmas))
    return _documento(historia, numero_registro)


# ---------------------------------------------------------------------------
# Constancia de firmas
# ---------------------------------------------------------------------------
def constancia_pdf(info):
    """info: {numero_registro, titulo, version, hash, generado, firmas: [{rol, nombre, cargo, empresa, email, fecha,
    metodo, ip, dispositivo}]}"""
    historia = [
        _encabezado("Constancia de firmas electrónicas", info["numero_registro"], [f"Versión del registro: V{info['version']}"]),
        Spacer(1, 8),
        _ph(f"Documento: <b>{escape(info['titulo'])}</b> — {escape(info['numero_registro'])} (V{info['version']})"),
        Spacer(1, 4),
        _ph("Código de verificación del documento firmado (SHA-256 de las páginas anteriores a esta constancia):"),
        _ph(f"<font name='Courier' size='8'>{info['hash']}</font>"),
        Spacer(1, 8),
    ]
    datos = [[_p(x, "etq") for x in ("ROL", "FIRMANTE", "FECHA Y HORA (PERÚ)", "MÉTODO DE IDENTIFICACIÓN", "IP / DISPOSITIVO")]]
    for f in info["firmas"]:
        datos.append([
            _p(f["rol"], "neg"),
            _ph(f"{escape(f['nombre'] or '')}<br/><font color='#5b6673'>{escape(f.get('cargo') or '')} — "
                f"{escape(f.get('empresa') or '')}<br/>{escape(f.get('email') or '')}</font>"),
            _p(fecha_hora(f["fecha"])), _p(f["metodo"]),
            _p(f"{f.get('ip') or '-'}\n{(f.get('dispositivo') or '-')[:90]}", "chico"),
        ])
    t = Table(datos, colWidths=[26 * mm, 50 * mm, 26 * mm, 46 * mm, ANCHO - 148 * mm], repeatRows=1)
    t.setStyle(_estilo_tabla([("BACKGROUND", (0, 0), (-1, 0), FONDO), ("VALIGN", (0, 1), (-1, -1), "TOP")]))
    historia += [t, Spacer(1, 10), _p(
        "Firmas electrónicas simples registradas por el sistema Protocolos de Calidad de Stracon. Cada firmante se "
        "identificó con su sesión en la aplicación (personal Stracon) o con un enlace personal y un código de un solo uso "
        "enviado a su correo (supervisión externa). Cualquier modificación del documento cambia su código de verificación. "
        f"Constancia generada el {fecha_hora(info['generado'])}.", "chico")]
    return _documento(historia, f"{info['numero_registro']} — Constancia de firmas")


# ---------------------------------------------------------------------------
# Hoja de Cargo de Distribución de Documentos (ST.CA.PG.001.F007)
# ---------------------------------------------------------------------------
def hoja_cargo_pdf(info):
    """info: {contrato, proyecto_distribucion, nombre_proyecto, cliente, n_registro, fecha,
    areas: [(letra, nombre)], registros: [{codigo, descripcion, reg}], distribucion: [{nombre, area, firma, fecha}]}"""
    letras = [a for a, _ in info["areas"]]
    historia = [
        _encabezado("Hoja de cargo de distribución de documentos", f"ST.CA.PG.001.F007 [{info['contrato']}]",
                    ["Versión: 00", "Fecha: 08/04/2026"], subtitulo="FORMATO"),
        Spacer(1, 6),
    ]
    cab = Table([
        [_p("PROYECTO", "etq"), _p(info["proyecto_distribucion"]), _p("CONTRATO", "etq"), _p(info["contrato"])],
        [_p("NOMBRE DEL PROYECTO", "etq"), _p(info["nombre_proyecto"]), _p("N° REGISTRO", "etq"), _p(info["n_registro"])],
        [_p("CLIENTE", "etq"), _p(info["cliente"]), _p("FECHA", "etq"), _p(fecha_hora(info["fecha"]))],
    ], colWidths=[32 * mm, 80 * mm, 25 * mm, ANCHO - 137 * mm])
    cab.setStyle(_estilo_tabla([("BACKGROUND", (0, 0), (0, -1), FONDO), ("BACKGROUND", (2, 0), (2, -1), FONDO)]))
    historia += [cab, _p("1. ÁREAS DE DISTRIBUCIÓN (marcar con aspa)", "sec")]
    areas = Table([[_p(f"{l}.  {n}"), _p("X", "neg")] for l, n in info["areas"]], colWidths=[100 * mm, 10 * mm])
    areas.setStyle(_estilo_tabla([("ALIGN", (1, 0), (1, -1), "CENTER")]))
    historia += [areas, _p("2. DOCUMENTOS ENTREGADOS — 2.2 REGISTROS", "sec")]
    datos = [[_p(x, "etq") for x in ("ITEM", "CÓDIGO", "DESCRIPCIÓN", "REG. N°", *letras)]]
    for i, r in enumerate(info["registros"], start=1):
        datos.append([_p(i), _p(r["codigo"]), _p(r["descripcion"]), _p(r["reg"]), *[_p("1") for _ in letras]])
    an_l = 9 * mm
    t = Table(datos, colWidths=[10 * mm, 38 * mm, ANCHO - 98 * mm - an_l * len(letras), 50 * mm, *[an_l] * len(letras)], repeatRows=1)
    t.setStyle(_estilo_tabla([("BACKGROUND", (0, 0), (-1, 0), FONDO), ("ALIGN", (4, 0), (-1, -1), "CENTER")]))
    historia += [t, _p("3. LISTA DE DISTRIBUCIÓN", "sec")]
    dist = [[_p(x, "etq") for x in ("NRO", "NOMBRES Y APELLIDOS", "ÁREA", "FIRMA", "FECHA")]]
    for i, d in enumerate(info["distribucion"], start=1):
        dist.append([_p(i), _p(d["nombre"]), _p(d["area"]), _imagen(d.get("firma"), 40 * mm, 12 * mm) or "",
                     _p(fecha_hora(d.get("fecha")))])
    t = Table(dist, colWidths=[10 * mm, 60 * mm, 40 * mm, 50 * mm, ANCHO - 160 * mm], rowHeights=[None] + [15 * mm] * len(info["distribucion"]))
    t.setStyle(_estilo_tabla([("BACKGROUND", (0, 0), (-1, 0), FONDO), ("ALIGN", (3, 1), (3, -1), "CENTER")]))
    historia.append(t)
    return _documento(historia, f"{info['n_registro']} — Hoja de cargo")


# ---------------------------------------------------------------------------
# Adjuntos y armado
# ---------------------------------------------------------------------------
def dossier_portada(info):
    """info: {codigo, titulo, proyecto, obra, contrato, cliente, entregable, periodo, protocolos, generado, tipos: [(nombre, n)]}"""
    grande = ParagraphStyle("dos-t", parent=E["titulo"], fontSize=20, leading=24, textColor=AZUL)
    datos = [[_p("PROYECTO", "etq"), _p(info["proyecto"])], [_p("OBRA", "etq"), _p(info["obra"])],
             [_p("CONTRATO", "etq"), _p(info["contrato"])], [_p("CLIENTE", "etq"), _p(info["cliente"])],
             [_p("ENTREGABLE", "etq"), _p(info["entregable"])], [_p("PERIODO", "etq"), _p(info["periodo"])],
             [_p("REGISTROS", "etq"), _p(str(info["protocolos"]))], [_p("GENERADO", "etq"), _p(fecha_hora(info["generado"]))]]
    t = Table(datos, colWidths=[40 * mm, ANCHO - 40 * mm])
    t.setStyle(_estilo_tabla([("BACKGROUND", (0, 0), (0, -1), FONDO)]))
    tipos = Table([[_p("TIPO DE REGISTRO", "etq"), _p("REGISTROS", "etq")]] + [[_p(n), _p(str(c))] for n, c in info["tipos"]],
                  colWidths=[ANCHO - 30 * mm, 30 * mm])
    tipos.setStyle(_estilo_tabla([("BACKGROUND", (0, 0), (-1, 0), FONDO), ("ALIGN", (1, 0), (1, -1), "CENTER")]))
    historia = [_encabezado("Dossier de calidad", info["codigo"], ["Protocolos aprobados"]), Spacer(1, 40 * mm),
                Paragraph(escape(info["titulo"]), grande), Spacer(1, 18 * mm), t, Spacer(1, 10 * mm), tipos]
    return _documento(historia, f"{info['codigo']} — Carátula")


def dossier_indice(info, filas):
    """filas: [{grupo}] (título de cada tipo de registro) o [{registro, fecha, estructura, rt, pagina}]."""
    datos = [[_p("N°", "etq"), _p("N° DE REGISTRO", "etq"), _p("FECHA", "etq"), _p("ESTRUCTURA", "etq"),
              _p("REPORTE TOPOGRÁFICO", "etq"), _p("PÁG.", "etq")]]
    estilo = [("BACKGROUND", (0, 0), (-1, 0), FONDO), ("ALIGN", (-1, 0), (-1, -1), "RIGHT")]
    n = 0
    for f in filas:
        if "grupo" in f:
            estilo += [("SPAN", (0, len(datos)), (-1, len(datos))), ("BACKGROUND", (0, len(datos)), (-1, len(datos)), FONDO)]
            datos.append([_p(f["grupo"].upper(), "neg"), "", "", "", "", ""])
            continue
        n += 1
        datos.append([_p(str(n)), _p(f["registro"]), _p(fecha_hora(f["fecha"])), _p(f["estructura"]),
                      _p(f["rt"] or "-"), _p(str(f.get("pagina", "")))])
    t = Table(datos, colWidths=[10 * mm, 70 * mm, 20 * mm, ANCHO - 140 * mm, 26 * mm, 14 * mm], repeatRows=1)
    t.setStyle(_estilo_tabla(estilo))
    historia = [_encabezado("Índice del dossier", info["codigo"], [info["periodo"]]), Spacer(1, 6), t]
    return _documento(historia, f"{info['codigo']} — Índice")


def separador_pdf(titulo, subtitulo, codigo):
    grande = ParagraphStyle("dos-s", parent=E["titulo"], fontSize=18, leading=22, textColor=AZUL)
    historia = [_encabezado("Dossier de calidad", codigo, []), Spacer(1, 90 * mm), Paragraph(escape(titulo.upper()), grande),
                Spacer(1, 6 * mm), _p(subtitulo, "centro")]
    return _documento(historia, f"{codigo} — {titulo}")


def imagen_a_pdf(datos):
    """Una foto o escaneo (PNG/JPG) → una página A4 centrada."""
    img = PilImage.open(io.BytesIO(datos))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    ancho, alto = 595, 842
    k = min((ancho - 40) / img.width, (alto - 40) / img.height, 1)
    hoja = PilImage.new("RGB", (ancho * 2, alto * 2), "white")
    chica = img.resize((max(1, int(img.width * k * 2)), max(1, int(img.height * k * 2))))
    hoja.paste(chica, ((hoja.width - chica.width) // 2, (hoja.height - chica.height) // 2))
    salida = io.BytesIO()
    hoja.save(salida, "PDF", resolution=144)
    return salida.getvalue()


def es_imagen(nombre):
    return bool(re.search(r"\.(png|jpe?g)$", nombre, re.I))


def unir(partes):
    if len(partes) == 1:
        return partes[0]
    w = PdfWriter()
    for p in partes:
        w.append(PdfReader(io.BytesIO(p)))
    salida = io.BytesIO()
    w.write(salida)
    return salida.getvalue()


def contar_paginas(pdf):
    return len(PdfReader(io.BytesIO(pdf)).pages)
