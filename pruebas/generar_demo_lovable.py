"""Genera documentos REALES (PDF y Excel hechos por la API) para el modo demo de las pantallas de Lovable.

Uso:  .venv\\Scripts\\python pruebas\\generar_demo_lovable.py <ruta>\\public\\demo
Crea: protocolo-aprobado.pdf (con firmas y constancia), protocolo-revision.pdf, reporte-topografico.pdf,
      hoja-cargo.pdf y qc-index.xlsx. Usa una base temporal: no toca los datos reales.
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
os.environ["PROTOCOLOS_DATOS"] = tempfile.mkdtemp(prefix="protocolos-demo-")
for k in ("SMTP_USER", "SMTP_PASSWORD", "RESEND_API_KEY", "DATABASE_URL", "SUPABASE_URL",
          "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SECRET_KEY"):      # siempre local, correos simulados
    os.environ[k] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from servidor.main import app  # noqa: E402

if len(sys.argv) < 2:
    sys.exit("Indique la carpeta de salida, p. ej. ..\\quality-standards-hub\\public\\demo")
salida = Path(sys.argv[1])
salida.mkdir(parents=True, exist_ok=True)
c = TestClient(app)


def api(metodo, ruta, usuario="", **kw):
    r = c.request(metodo, f"/api{ruta}", headers={"X-Usuario": usuario}, **kw)
    if r.status_code >= 400:
        raise SystemExit(f"{metodo} {ruta}: {r.status_code} {r.text[:300]}")
    return r.json() if "json" in r.headers.get("content-type", "") else r


ses = api("GET", "/sesion")
sup, _jefe, ops = (p["id"] for p in ses["perfiles"])
kp = ses["contactos"][0]["id"]
tipos = {t["codigo"]: t for t in api("GET", "/tipos")}
firmantes = {"firmantes": {"elaborado": {"perfil_id": sup}, "revisado_aprobado": {"perfil_id": ops}}}


def checklist(tipo, extras=None, na=()):
    r = {}
    for s in tipo["schema"]["secciones"]:
        if s["tipo"] == "checklist":
            si = "C" if s["opciones"] == "C_NC_NA" else "SI"
            for g in s["grupos"]:
                for it in g["items"]:
                    r[it["id"]] = {} if it.get("solo_extra") else {"r": "NA" if it["id"] in na else si}
    for k, v in (extras or {}).items():
        r.setdefault(k, {})["extra"] = v
    return r


def crear(codigo, cabecera, respuestas, conforme=True):
    t = tipos[codigo]
    id_ = api("POST", "/protocolos", sup, json={"tipo_id": t["id"], "origen": "solicitud_operaciones"})["id"]
    d = api("GET", f"/protocolos/{id_}")
    adjuntos = {a["id"]: {"adjunta": "NA"} for a in t["schema"].get("adjuntos") or []}
    adjuntos.update(respuestas.pop("adjuntos", {}))
    api("PUT", f"/protocolos/{id_}/valor", sup, json={"cabecera": {**d["inst"]["cabecera"], **cabecera},
        "respuestas": {"tablas": {}, "observaciones": "", **respuestas, "adjuntos": adjuntos}, "conforme": conforme})
    for a in t["schema"].get("adjuntos") or []:          # todo "Sí se adjunta" lleva su archivo
        if adjuntos[a["id"]].get("adjunta") == "SI":
            api("POST", f"/protocolos/{id_}/adjuntos", sup, files={"archivo": ("plano-topografico.png", PLANO, "image/png")},
                data={"tipo": a["tipo_adjunto"], "ref_schema": a["id"]})
    api("POST", f"/protocolos/{id_}/enviar-firma", sup, json=firmantes)
    f = api("GET", f"/protocolos/{id_}")["firmas"]
    api("POST", f"/firmas/{f[0]['id']}/firmar", sup)
    api("POST", f"/firmas/{f[1]['id']}/firmar", ops)
    return id_


# Adjunto de ejemplo (plano topográfico como imagen) para mostrar la unión de adjuntos en el PDF
img = Image.new("RGB", (1400, 900), "white")
dib = ImageDraw.Draw(img)
dib.rectangle((40, 40, 1360, 860), outline=(21, 40, 75), width=6)
for i in range(12):
    dib.line((100 + i * 100, 780 - i * 40, 200 + i * 100, 760 - i * 40), fill=(244, 37, 52), width=5)
dib.text((80, 70), "PLANO TOPOGRÁFICO 2611-2026-PCR-RC-TS-109 (ejemplo)", fill=(21, 40, 75))
b = io.BytesIO()
img.save(b, "PNG")

PLANO = b.getvalue()

RC = {"entregable": "RC", "estructura": "Reservorio Cunahuiri", "fecha": "2026-10-12", "elemento": "-"}

# 1. Capa de relleno (como el REG 133, adaptado a RC) → se aprueba con firma de KP
relleno = tipos["ST.CA.PC.002.F001"]
A = crear("ST.CA.PC.002.F001", {**RC, "plano_ref": ["LI 201.557.64.1330 (Rev. 3)", "LI 201.557.64.1355 (Rev. 3)"]}, {
    "descripcion": "Se liberó la capa 4, material de baja permeabilidad, elevación 4216.50 msnm, espesor 200 mm, entre las "
                   "progresivas 0+587.50 @ 0+606.60, área 86.655 m2, Reservorio Cunahuiri, alcantarilla 4.",
    "checklist": checklist(relleno, {"c1": "ACR-RC-067", "c4": "WRF/Constancia", "c4b": "Material de Baja Permeabilidad",
                                     "c12": "200", "c13": "6", "c7": "11.2"}, na={f"c{i}" for i in range(20, 27)} | {"c14", "c15", "c16"}),
    "campos": {"tipo_relleno": "Relleno Estructural Controlado", "equipo_compactacion": "Rodillo vibratorio",
               "plataforma_prueba": "IE-26-001 rev.1", "stage": "-", "capa_n": "4", "area": 86.655, "cota": "4216.50",
               "volumen": 17.33, "prog_inicial": "0+587.50", "prog_final": "0+606.60", "inicio_capa": "2026-10-11T07:30",
               "fin_capa": "2026-10-11T16:00", "turno": "Día"},
    "tablas": {"prestamo": [{"fase": "9", "banco": "4075", "poligono": "23-NAG-1"}]},
    "adjuntos": {"reporte_topografico": {"adjunta": "SI", "numero": "RT-109"}},
    "observaciones": "Ensayos de densidad de campo por reemplazo de agua: DDR-RRE-RA-011 (conforme).",
})
# 2. Terreno de fundación → queda listo para revisión (PDF para KP)
fund = tipos["ST.CA.PC.001.F002"]
B = crear("ST.CA.PC.001.F002", {**RC, "plano_ref": ["LI 201.557.64.1330 (Rev. 3)"]}, {
    "descripcion": "Liberación de terreno de fundación, cota variable, área 736.91 m2, entre las progresivas 0+505.85 @ "
                   "0+563.00, vaso de reservorio lado sur.",
    "checklist": checklist(fund, na={"c4", "c9", "c10", "c11"}),
    "campos": {"area": 736.91, "nivel_terreno": "variable", "prog_inicial": "0+505.85", "prog_final": "0+563.00",
               "rt_numero": "RT-163", "turno": "Día"},
    "adjuntos": {"reporte_topografico": {"adjunta": "SI", "numero": "163"}},
    "observaciones": "Mapeo geológico realizado el 11/10/2026.",
})

# 3. Reporte topográfico (se usa como "adjunto" de ejemplo en la demo)
topo = tipos["ST.CA.PC.001.F001"]
T = crear("ST.CA.PC.001.F001", {**RC, "plano_ref": ["LI 201.557.64.1330 (Rev. 3)"]}, {
    "descripcion": "Levantamiento topográfico de capa nivelante, área 590.670 m2, progresiva 0+781.50 @ 0+876.50.",
    "checklist": checklist(topo, {"c9": "-"}, na={"c1", "c3", "c9"}),
    "campos": {"equipo_medicion": "GPS TRIMBLE R12 6025F00988", "topografo": "Luis Medrano Reyes", "archivo": "RT-109.dwg",
               "plano_adjunto": "SI"},
    "tablas": {"equipos": [{"marca": "Trimble", "modelo": "R12", "serie": "6025F00988", "calibracion": "SI", "certificado": "CAL-2026-118"}],
               "georreferencia": [{"punto": "BM-RC-03", "tipo": "BM", "este": 279845.312, "norte": 8396541.208, "elevacion": 4215.402}]},
}, conforme=None)

# Paquete a KP con A y B: KP acepta A y firma; B queda pendiente
api("POST", "/paquetes", sup, json={"instancias": [A, B, T], "contacto_id": kp})
paq = api("GET", "/paquetes")[0]
token = paq["enlace_demo"].split("t=")[1]
firma = Image.new("RGBA", (420, 130), (255, 255, 255, 0))
ImageDraw.Draw(firma).line([(15, 95), (70, 30), (120, 100), (170, 40), (230, 90), (300, 35), (400, 70)], fill=(20, 30, 60, 255), width=5)
fb = io.BytesIO()
firma.save(fb, "PNG")
api("POST", f"/revision/{token}/codigo")
codigo = re.search(r"(\d{6})", next(x["asunto"] for x in api("GET", "/correos") if "Código" in x["asunto"])).group(1)
api("POST", f"/revision/{token}/decidir", json={"codigo": codigo, "firma": "data:image/png;base64," + base64.b64encode(fb.getvalue()).decode(),
    "decisiones": [{"instancia_id": A, "decision": "aceptado"}, {"instancia_id": T, "decision": "aceptado"}]})

archivos = {
    "protocolo-aprobado.pdf": c.get(f"/api/protocolos/{A}/pdf").content,
    "protocolo-revision.pdf": c.get(f"/api/protocolos/{B}/pdf").content,
    "reporte-topografico.pdf": c.get(f"/api/protocolos/{T}/pdf").content,
    "hoja-cargo.pdf": c.get(f"/api/paquetes/{paq['id']}/hoja-cargo").content,
    "qc-index.xlsx": c.get("/api/qc-index").content,
}
for nombre, datos in archivos.items():
    (salida / nombre).write_bytes(datos)
    print(f"{nombre:26} {len(datos) // 1024:5} KB")
