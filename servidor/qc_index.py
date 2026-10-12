"""QC Index (Control de Registros de Calidad, ST.CA.PR.005.F001) generado desde los protocolos.

Mismas hojas y columnas que el Excel que hoy llena Calidad a mano. Las columnas propias de cada formato
se definen en protocolos/tipos.json → "qc_index": {"hoja", "columnas": [[título, fuente], ...]}.
Fuentes: "c:<campo>" campo del formato · "k:<ítem>" dato extra de un ítem del checklist · "turno" ·
"prog:<campo>" progresiva 0+028.87 → 28.87 · "calc:longitud" progresiva final − inicial.
"""
import io
import re
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import db
from .logica import _numero_registro, maestros, proyecto, tipos

MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Set", "Oct", "Nov", "Dic"]
INICIO = ["ÍTEM", "FECHA", "CÓDIGO DEL FORMATO", "NOMBRE DEL FORMATO", "N° DE REGISTRO",
          "DESCRIPCIÓN DEL TRABAJO / ACTIVIDAD", "ENTREGABLE", "ESTRUCTURA", "ELEMENTO"]
AZUL = PatternFill("solid", fgColor="0B5CAD")
CELESTE = PatternFill("solid", fgColor="DCE8F5")
FINO = Side(style="thin", color="8A96A3")
BORDE = Border(left=FINO, right=FINO, top=FINO, bottom=FINO)


def _progresiva(v):
    """'0+028.87' → 28.87 · '2+039.90' → 2039.9 · número → número."""
    if v in (None, ""):
        return None
    s = str(v).strip().replace(",", "")
    m = re.fullmatch(r"(\d+)\+(\d+(?:\.\d+)?)", s)
    if m:
        return round(int(m.group(1)) * 1000 + float(m.group(2)), 3)
    try:
        return float(s)
    except ValueError:
        return s


def _valor(fuente, valor):
    r = valor.get("respuestas") or {}
    campos = r.get("campos") or {}
    if fuente == "turno":
        return f"Turno {campos['turno']}" if campos.get("turno") else "-"
    if fuente == "calc:longitud":
        a, b = _progresiva(campos.get("prog_inicial")), _progresiva(campos.get("prog_final"))
        return round(b - a, 3) if isinstance(a, float) and isinstance(b, float) else "-"
    tipo, _, clave = fuente.partition(":")
    if tipo == "c":
        v = campos.get(clave)
    elif tipo == "k":
        v = ((r.get("checklist") or {}).get(clave) or {}).get("extra")
    elif tipo == "prog":
        v = _progresiva(campos.get(clave))
    else:
        v = None
    return "-" if v in (None, "") else v


def _estado(inst, conforme):
    if inst["estado"] == "anulado":
        return "Anulado"
    if conforme is False:
        return "No Conforme"
    return "Conforme" if inst["estado"] == "aprobado" else "Revisión"


def _adjuntos(tipo, valor):
    marcados = (valor.get("respuestas") or {}).get("adjuntos") or {}
    lineas = [f".{a['label']} {marcados[a['id']].get('numero') or ''}".strip()
              for a in tipo["schema"].get("adjuntos") or [] if (marcados.get(a["id"]) or {}).get("adjunta") == "SI"]
    return "\n".join(lineas) or "-"


def _encabezado(ws, titulo, ncols, proy):
    ws.append([titulo])
    ws.append([f"NOMBRE DEL PROYECTO: {proy['nombre_contrato']}"])
    ws.append([f"CLIENTE: {proy['cliente']}"])
    ws.append([])
    ws["A1"].font = Font(bold=True, size=13, color="0B5CAD")
    for fila in (1, 2, 3):
        ws.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=max(ncols, 2))


def _cabecera_tabla(ws, titulos):
    ws.append(titulos)
    fila = ws.max_row
    for celda in ws[fila]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = AZUL
        celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        celda.border = BORDE
    ws.row_dimensions[fila].height = 32
    ws.freeze_panes = f"A{fila + 1}"
    return fila


def _anchos(ws, titulos):
    anchos = {"ÍTEM": 6, "FECHA": 11, "CÓDIGO DEL FORMATO": 26, "NOMBRE DEL FORMATO": 26, "N° DE REGISTRO": 38,
              "DESCRIPCIÓN DEL TRABAJO / ACTIVIDAD": 60, "DOCUMENTOS ADJUNTOS": 34,
              "DOCUMENTOS DE REFERENCIA (PLANOS REF.)": 30, "OBSERVACIONES / COMENTARIOS": 30}
    for i, t in enumerate(titulos, start=1):
        ws.column_dimensions[get_column_letter(i)].width = anchos.get(t, 16)


def generar(entregable=None):
    """Devuelve el Excel (bytes). Incluye todo protocolo con correlativo (enviado a firma), con los datos
    de su versión vigente. entregable="RC" filtra por entregable."""
    proy = proyecto()
    ents = {e["codigo"]: e["nombre"] for e in maestros()["entregables"]}
    wb = Workbook()
    resumen = wb.active
    resumen.title = "ST.CA.PR.005.F001"
    totales = []

    for t in tipos():
        q = t.get("qc_index")
        if not q:
            continue
        titulos = INICIO + [c[0] for c in q["columnas"]]
        if not q.get("sin_adjuntos"):
            titulos.append("DOCUMENTOS ADJUNTOS")
        titulos.append("DOCUMENTOS DE REFERENCIA (PLANOS REF.)")
        if not q.get("sin_originador"):
            titulos.append("ORIGINADOR")
        titulos += ["ESTADO", "OBSERVACIONES / COMENTARIOS"]

        ws = wb.create_sheet(q["hoja"])
        _encabezado(ws, "CONTROL DE REGISTROS DE CALIDAD", len(titulos), proy)
        _cabecera_tabla(ws, titulos)
        _anchos(ws, titulos)

        filas = db.filas("""select i.*, v.snapshot from instancia i
                            join version v on v.instancia_id = i.id and v.numero = i.version_actual
                            where i.tipo_id = ? and i.correlativo is not null order by i.created_at""", t["id"])
        conteo = {"total": 0, "conformes": 0, "no_conformes": 0, "meses": [0] * 12}
        for n, i in enumerate((f for f in filas if not entregable or f["cabecera"].get("entregable") == entregable), start=1):
            valor = i["snapshot"]
            cab = valor.get("cabecera") or {}
            conforme = valor.get("conforme")
            elaborado = db.fila("select nombre from firma where instancia_id = ? and version = ? and rol = 'elaborado'",
                                i["id"], i["version_actual"])
            try:
                fecha = date.fromisoformat(cab.get("fecha") or "")
            except ValueError:
                fecha = None
            planos = "\n".join([*(cab.get("plano_ref") or []), *([cab["plano_otro"]] if cab.get("plano_otro") else [])]) or "-"
            fila = [n, fecha, f"{t['codigo']} [{proy['codigo_contrato']}]", t["nombre"], _numero_registro(t, i["correlativo"]),
                    (valor.get("respuestas") or {}).get("descripcion") or "-", ents.get(cab.get("entregable"), cab.get("entregable")),
                    cab.get("estructura") or "-", cab.get("elemento") or "-"]
            fila += [_valor(c[1], valor) for c in q["columnas"]]
            if not q.get("sin_adjuntos"):
                fila.append(_adjuntos(t, valor))
            fila.append(planos)
            if not q.get("sin_originador"):
                fila.append(elaborado["nombre"] if elaborado else "-")
            estado = _estado(i, conforme)
            fila += [estado, (valor.get("respuestas") or {}).get("observaciones") or "-"]
            ws.append(fila)
            for celda in ws[ws.max_row]:
                celda.border = BORDE
                celda.alignment = Alignment(vertical="top", wrap_text=True)
            ws.cell(row=ws.max_row, column=2).number_format = "DD/MM/YYYY"

            conteo["total"] += 1
            conteo["conformes"] += estado == "Conforme"
            conteo["no_conformes"] += estado == "No Conforme"
            if fecha:
                conteo["meses"][fecha.month - 1] += 1
        totales.append((t, conteo))

    # Hoja resumen (como ST.CA.PR.005.F001): totales, conformes, no conformes, ICRC y registros por mes
    titulos = ["CÓDIGO DEL FORMATO", "NOMBRE DEL FORMATO", "TOTAL DE REGISTROS", "CONFORMES", "NO CONFORMES", "ICRC", *MESES]
    _encabezado(resumen, "CONTROL DE REGISTROS DE CALIDAD — RESUMEN", len(titulos), proy)
    if entregable:
        resumen["A3"].value = f"{resumen['A3'].value}    ·    ENTREGABLE: {ents.get(entregable, entregable)}"
    _cabecera_tabla(resumen, titulos)
    for t, c in totales:
        icrc = round(c["conformes"] / c["total"], 2) if c["total"] else None
        resumen.append([f"{t['codigo']} [{proy['codigo_contrato']}]", t["nombre"], c["total"], c["conformes"],
                        c["no_conformes"], icrc, *c["meses"]])
        for celda in resumen[resumen.max_row]:
            celda.border = BORDE
    total = [sum(c[k] for _, c in totales) for k in ("total", "conformes", "no_conformes")]
    resumen.append(["", "TOTAL", *total, round(total[1] / total[0], 2) if total[0] else None,
                    *[sum(c["meses"][m] for _, c in totales) for m in range(12)]])
    for celda in resumen[resumen.max_row]:
        celda.font = Font(bold=True)
        celda.fill = CELESTE
        celda.border = BORDE
    resumen.column_dimensions["A"].width = 30
    resumen.column_dimensions["B"].width = 42
    for col in range(3, len(titulos) + 1):
        resumen.column_dimensions[get_column_letter(col)].width = 12 if col <= 6 else 6

    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()
