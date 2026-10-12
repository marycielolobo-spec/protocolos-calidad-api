"""Prueba automática del flujo completo, sin tocar los datos reales (usa una carpeta temporal).

Uso:  .venv\\Scripts\\python pruebas\\prueba_flujo.py
"""
import base64
import io
import os
import re
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ["PROTOCOLOS_DATOS"] = tempfile.mkdtemp(prefix="protocolos-prueba-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import load_workbook  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from servidor.main import app  # noqa: E402

c = TestClient(app)
pasos = 0


def ok(cond, msg):
    global pasos
    if not cond:
        raise AssertionError(msg)
    pasos += 1
    print(f"  OK  {msg}")


def api(metodo, ruta, usuario=None, esperado=200, **kw):
    r = c.request(metodo, f"/api{ruta}", headers={"X-Usuario": usuario or ""}, **kw)
    if r.status_code != esperado:
        raise AssertionError(f"{metodo} {ruta}: esperado {esperado}, llegó {r.status_code} {r.text[:300]}")
    return r.json() if "json" in r.headers.get("content-type", "") else r


def texto_pdf(datos):
    return "".join(p.extract_text() for p in PdfReader(io.BytesIO(datos)).pages)


def llenar(tipo):
    """Respuestas válidas para cualquier formato."""
    s = tipo["schema"]
    checklist, campos = {}, {}
    for sec in s["secciones"]:
        if sec["tipo"] == "checklist":
            positivo = "C" if sec["opciones"] == "C_NC_NA" else "SI"
            for g in sec["grupos"]:
                for it in g["items"]:
                    checklist[it["id"]] = {"extra": "x"} if it.get("solo_extra") else {"r": positivo}
        if sec["tipo"] == "campos":
            for cp in sec["campos"]:
                campos[cp["id"]] = cp["opciones"][0] if cp.get("tipo") == "radio" else 1 if cp.get("tipo") == "number" else "x"
    campos.update({"prog_inicial": "0+028.87", "prog_final": "0+048.38", "area": 440.306})
    adjuntos = {a["id"]: {"adjunta": "NA"} for a in s.get("adjuntos") or []}
    return {"checklist": checklist, "campos": campos, "tablas": {}, "adjuntos": adjuntos,
            "descripcion": "Se liberó terreno de fundación (prueba)", "observaciones": ""}


def cabecera(d, entregable, estructura, planos=()):
    return {**d["inst"]["cabecera"], "entregable": entregable, "estructura": estructura, "plano_ref": list(planos)}


def firma_png():
    img = Image.new("RGBA", (300, 100), (255, 255, 255, 0))
    ImageDraw.Draw(img).line([(10, 70), (80, 20), (150, 80), (290, 30)], fill=(0, 0, 0, 255), width=4)
    b = io.BytesIO()
    img.save(b, "PNG")
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


def ultimo_codigo():
    asunto = next(x["asunto"] for x in api("GET", "/correos") if "Código para firmar" in x["asunto"])
    return re.search(r"(\d{6})", asunto).group(1)


print("Flujo completo de protocolos")
ses = api("GET", "/sesion")
sup, jefe, ops = (p["id"] for p in ses["perfiles"])
kp = ses["contactos"][0]["id"]
tipos = api("GET", "/tipos")
ok(len(tipos) == 8 and all(t["sigla"] for t in tipos), "8 formatos cargados, cada uno con su sigla")
m = api("GET", "/maestros")
rc = next(e for e in m["entregables"] if e["codigo"] == "RC")
tmf = next(e for e in m["entregables"] if e["codigo"] == "TMF")
ok(len(m["entregables"]) == 3 and len(tmf["estructuras"]) == 6 and rc["planos"], "Maestros: 3 entregables, 6 estructuras en TMF, planos de RC")
ok("Relleno Común" in m["listas"]["material_relleno"], "Listas para desplegables cargadas")

fund = next(t for t in tipos if t["codigo"] == "ST.CA.PC.001.F001".replace("F001", "F002"))   # Terreno de fundación
otro = next(t for t in tipos if t["codigo"] == "ST.CA.PC.008.F002")                          # Drenes
A = api("POST", "/protocolos", sup, json={"tipo_id": fund["id"], "origen": "solicitud_operaciones"})["id"]
B = api("POST", "/protocolos", sup, json={"tipo_id": otro["id"], "origen": "backlog"})["id"]
C = api("POST", "/protocolos", sup, json={"tipo_id": fund["id"], "origen": "solicitud_operaciones"})["id"]
firmantes = {"firmantes": {"elaborado": {"perfil_id": sup}, "revisado_aprobado": {"perfil_id": ops}}}

r = api("POST", f"/protocolos/{A}/enviar-firma", sup, 400, json=firmantes)
ok("Entregable" in r["error"], "No deja enviar sin entregable ni datos")

# Estructura que no corresponde al entregable
d = api("GET", f"/protocolos/{A}")
resp_a = llenar(fund)
adj = fund["schema"]["adjuntos"][0]
resp_a["adjuntos"][adj["id"]] = {"adjunta": "SI", "numero": "RT-001"}
api("PUT", f"/protocolos/{A}/valor", sup, json={"cabecera": cabecera(d, "RC", tmf["estructuras"][0]["nombre"]),
                                              "respuestas": resp_a, "conforme": True})
r = api("POST", f"/protocolos/{A}/enviar-firma", sup, 400, json=firmantes)
ok("no pertenece" in r["error"], "Estructura de otro entregable: lo detiene")

cab_a = cabecera(d, "RC", "Reservorio Cunahuiri", rc["planos"][:2])
api("PUT", f"/protocolos/{A}/valor", sup, json={"cabecera": cab_a, "respuestas": resp_a, "conforme": True})
r = api("POST", f"/protocolos/{A}/enviar-firma", sup, 400, json=firmantes)
ok("falta subir" in r["error"], 'Marcó "Sí se adjunta" sin archivo: lo detiene')

png = io.BytesIO()
Image.new("RGB", (400, 300), "steelblue").save(png, "PNG")
api("POST", f"/protocolos/{A}/adjuntos", sup, files={"archivo": ("plano.png", png.getvalue(), "image/png")},
    data={"tipo": adj["tipo_adjunto"], "ref_schema": adj["id"]})

resp_neg = llenar(fund)
resp_neg["adjuntos"] = resp_a["adjuntos"]
primero = next(k for k, v in resp_neg["checklist"].items() if "r" in v)
resp_neg["checklist"][primero]["r"] = "NO"
api("PUT", f"/protocolos/{A}/valor", sup, json={"cabecera": cab_a, "respuestas": resp_neg, "conforme": True})
r = api("POST", f"/protocolos/{A}/enviar-firma", sup, 400, json=firmantes)
ok("requiere observación" in r["error"], "Respuesta NO sin observación: lo detiene")

api("PUT", f"/protocolos/{A}/valor", sup, json={"cabecera": cab_a, "respuestas": resp_a, "conforme": True})
api("POST", f"/protocolos/{A}/enviar-firma", sup, json=firmantes)
for X, t_, ent, est in ((B, otro, "TMF", tmf["estructuras"][0]["nombre"]), (C, fund, "RC", "Reservorio Cunahuiri")):
    d = api("GET", f"/protocolos/{X}")
    api("PUT", f"/protocolos/{X}/valor", sup, json={"cabecera": cabecera(d, ent, est), "respuestas": llenar(t_), "conforme": True})
    api("POST", f"/protocolos/{X}/enviar-firma", sup, json=firmantes)
a = api("GET", f"/protocolos/{A}")
ok(a["inst"]["correlativo"] == "ATF-RC-001", f"Correlativo con sigla y entregable: {a['inst']['correlativo']}")
ok(a["numero_registro"] == "ST.CA.PC.001.F002 [10203002] - ATF-RC-001", f"N° de registro como el QC Index: {a['numero_registro']}")
ok(api("GET", f"/protocolos/{C}")["inst"]["correlativo"] == "ATF-RC-002", "El número sigue por formato y entregable (ATF-RC-002)")
ok(api("GET", f"/protocolos/{B}")["inst"]["correlativo"] == "ID-TMF-001", "Otro formato y entregable empieza en 001 (ID-TMF-001)")
api("PUT", f"/protocolos/{A}/valor", sup, 400, json={"cabecera": cab_a, "respuestas": resp_a, "conforme": True})
ok(True, "En firma ya no se puede editar")

# Firmas internas (secuenciales)
f_elab, f_rev = a["firmas"][0]["id"], a["firmas"][1]["id"]
r = api("POST", f"/firmas/{f_rev}/firmar", ops, 400)
ok("secuencial" in r["error"], "Firma secuencial: Operaciones no firma antes que Calidad")
api("POST", f"/firmas/{f_elab}/firmar", ops, 403)
ok(True, "Nadie firma por otra persona")
api("POST", f"/firmas/{f_elab}/firmar", sup)
ok(api("POST", f"/firmas/{f_rev}/firmar", ops)["estado"] == "listo_revision", "A listo para revisión tras 2 firmas")
for X in (B, C):
    x = api("GET", f"/protocolos/{X}")
    api("POST", f"/firmas/{x['firmas'][0]['id']}/firmar", sup)
    api("POST", f"/firmas/{x['firmas'][1]['id']}/firmar", ops)

# PDF hecho en Python (ReportLab), sin Adobe ni navegador
r = c.get(f"/api/protocolos/{A}/pdf")
ok(r.status_code == 200 and r.content[:4] == b"%PDF", "PDF de revisión generado en Python")
lector = PdfReader(io.BytesIO(r.content))
ok(len(lector.pages) >= 2, f"PDF une formulario + imagen adjunta ({len(lector.pages)} páginas)")
texto = texto_pdf(r.content)
ok("ATF-RC-001" in texto and "Reservorio Cunahuiri" in texto and rc["planos"][0] in texto, "PDF muestra correlativo, entregable y planos")

# Paquete a KP + Hoja de Cargo
r = api("POST", "/paquetes", sup, json={"instancias": [A, B], "contacto_id": kp})
paq = api("GET", "/paquetes")[0]
ok(r["codigo"] == paq["codigo"] and paq["enlace_demo"], f"Paquete {r['codigo']} creado")
hc = c.get(f"/api/paquetes/{paq['id']}/hoja-cargo")
ok(hc.status_code == 200 and "ATF-RC-001" in texto_pdf(hc.content) and "ST.CA.PG.001.F007" in texto_pdf(hc.content),
   "Hoja de Cargo generada con los registros del paquete")
token = paq["enlace_demo"].split("t=")[1]
api("GET", "/revision/token-falso-que-no-existe-123", esperado=404)
ok(True, "Enlace falso: rechazado")
rev = api("GET", f"/revision/{token}")
ok(len(rev["items"]) == 2 and rev["contacto"]["empresa"] == "Knight Piésold" and "@" in rev["contacto"]["correo"],
   "Portal KP muestra los 2 protocolos (correo enmascarado)")
ok(c.get(rev["items"][0]["pdf_url"]).status_code == 200, "KP puede abrir el PDF desde el portal")

decisiones = {"decisiones": [{"instancia_id": A, "decision": "aceptado"},
                             {"instancia_id": B, "decision": "rechazado", "motivo": "Falta ensayo"}], "firma": firma_png()}
r = api("POST", f"/revision/{token}/decidir", esperado=400, json={**decisiones, "codigo": "123456"})
ok("solicite el código" in r["error"], "Sin pedir código no se puede firmar")
api("POST", f"/revision/{token}/codigo")
codigo = ultimo_codigo()
r = api("POST", f"/revision/{token}/decidir", esperado=400, json={**decisiones, "codigo": "000000" if codigo != "000000" else "111111"})
ok("incorrecto" in r["error"], "Código incorrecto: rechazado")
r = api("POST", f"/revision/{token}/decidir", esperado=400, json={**decisiones, "codigo": codigo, "firma": ""})
ok("firma" in r["error"].lower(), "Sin firma dibujada: rechazado")
api("POST", f"/revision/{token}/decidir", esperado=400,
    json={**decisiones, "codigo": codigo, "decisiones": [{"instancia_id": B, "decision": "rechazado", "motivo": ""}]})
ok(True, "Rechazo sin motivo: no se acepta")
api("POST", f"/revision/{token}/decidir", json={**decisiones, "codigo": codigo})
ok(api("GET", f"/protocolos/{A}")["inst"]["estado"] == "aprobado", "A aceptado y firmado por KP → Aprobado")
ok(api("GET", f"/protocolos/{B}")["inst"]["estado"] == "observado", "B rechazado → Observado (vuelve a Calidad)")
api("POST", f"/revision/{token}/decidir", esperado=400, json={**decisiones, "codigo": codigo})
ok(True, "El código sirve una sola vez")

# PDF final con constancia de firmas
r = c.get(f"/api/protocolos/{A}/pdf")
texto = texto_pdf(r.content)
ok(r.status_code == 200 and "revision" not in r.headers["content-disposition"], "PDF final firmado disponible")
ok("Constancia de firmas".upper() in texto.upper() and "revisor.kp@demo" in texto, "PDF final trae la constancia con el correo de KP")
ok(re.search(r"[0-9a-f]{64}", texto) is not None, "Constancia con código de verificación SHA-256")
paq = next(p for p in api("GET", "/paquetes") if p["id"] == paq["id"])
ok(paq["firmado_recepcion"], "Hoja de Cargo firmada por KP al registrar sus decisiones")

# QC Index
r = c.get("/api/qc-index?entregable=RC")
wb = load_workbook(io.BytesIO(r.content))
ok("A. Fundac" in wb.sheetnames and "A. Relleno" in wb.sheetnames, "QC Index con las mismas hojas que el Excel de Calidad")
ws = wb["A. Fundac"]
fila = [cel.value for cel in ws[6]]
ok(fila[4] == "ST.CA.PC.001.F002 [10203002] - ATF-RC-001" and "Conforme" in fila, "QC Index: registro ATF-RC-001 Conforme")
ok(fila[10] == 19.51, f"QC Index calcula la longitud desde las progresivas ({fila[10]})")
ok(ws.max_row == 7, "QC Index filtrado por entregable (solo RC)")

# Control de cambios
api("PUT", f"/protocolos/{A}/valor", sup, 400, json={"cabecera": cab_a, "respuestas": resp_a, "conforme": True})
ok(True, "Aprobado = bloqueado")
api("POST", f"/protocolos/{A}/cambios", sup, json={"motivo": "Error en cota", "descripcion": "Corregir", "contacto_id": kp})
cambio = api("GET", f"/protocolos/{A}")["cambios"][0]
api("POST", f"/cambios/{cambio['id']}/decidir", sup, 403, json={"decision": "aceptado"})
ok(True, "Solo la Jefatura de Calidad aprueba el cambio")
api("POST", f"/cambios/{cambio['id']}/decidir", jefe, json={"decision": "aceptado"})
ok(api("GET", f"/protocolos/{A}")["inst"]["estado"] == "aprobado", "Con una sola aprobación sigue aprobado")
t_cambio = cambio["enlace_demo"].split("t=")[1]
api("POST", f"/revision/{t_cambio}/codigo")
api("POST", f"/revision/{t_cambio}/cambio", json={"decision": "aceptado", "codigo": ultimo_codigo()})
a = api("GET", f"/protocolos/{A}")
ok(a["inst"]["estado"] == "en_modificacion" and a["inst"]["version_actual"] == 1, "KP (con código) + Jefatura aprueban → se abre V1")
ok(a["inst"]["correlativo"] == "ATF-RC-001", "La V1 conserva el mismo correlativo")
ok(c.get(f"/api/protocolos/{A}/pdf?version=0").status_code == 200, "V0 y su PDF firmado se conservan")

print(f"\nTodo correcto: {pasos} verificaciones.")
