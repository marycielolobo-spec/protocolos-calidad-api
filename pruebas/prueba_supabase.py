"""Prueba de punta a punta contra Supabase REAL (base de datos, archivos e inicio de sesión), usando el .env.

Uso:  .venv\\Scripts\\python pruebas\\prueba_supabase.py
Crea usuarios, protocolos y archivos temporales y AL FINAL LOS BORRA (también si algo falla).
Usa el entregable MIS y devuelve los contadores a su valor anterior: no consume correlativos ni códigos de paquete.
"""
import base64
import io
import os
import re
import secrets
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
for _k in ("SMTP_USER", "SMTP_PASSWORD", "RESEND_API_KEY"):
    os.environ[_k] = ""                       # correos simulados: el código de firma se lee de la tabla correo
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from servidor import almacen, auth, config, db  # noqa: E402
from servidor.main import app  # noqa: E402

if not (db.POSTGRES and config.SUPABASE):
    sys.exit("Esta prueba necesita DATABASE_URL, SUPABASE_URL y las dos claves en .env")

c = TestClient(app)
pasos = 0
marca = secrets.token_hex(3)
creados = {"usuarios": [], "instancias": [], "paquetes": [], "contactos": [], "archivos": []}
contadores = {f["nombre"]: f["valor"] for f in db.filas("select nombre, valor from contador")}


def ok(cond, msg):
    global pasos
    if not cond:
        raise AssertionError(msg)
    pasos += 1
    print(f"  OK  {msg}")


def api(metodo, ruta, token=None, esperado=200, **kw):
    r = c.request(metodo, f"/api{ruta}", headers={"Authorization": f"Bearer {token}"} if token else {}, **kw)
    if r.status_code != esperado:
        raise AssertionError(f"{metodo} {ruta}: esperado {esperado}, llegó {r.status_code} {r.text[:300]}")
    return r.json() if "json" in r.headers.get("content-type", "") else r


def entrar(email, clave):
    return api("POST", "/auth/ingresar", json={"email": email, "clave": clave})


def limpiar():
    print("\nLimpieza de los datos de prueba…")
    for i in creados["instancias"]:
        for a in db.filas("select ruta from adjunto where instancia_id = ?", i):
            almacen.borrar(a["ruta"])
        for v in db.filas("select pdf_revision, pdf_firmado from version where instancia_id = ?", i):
            for ruta in (v["pdf_revision"], v["pdf_firmado"]):
                if ruta:
                    almacen.borrar(ruta)
    for p in creados["paquetes"]:
        f = db.fila("select hoja_cargo from paquete where id = ?", p)
        if f and f["hoja_cargo"]:
            almacen.borrar(f["hoja_cargo"])
    for ruta in creados["archivos"]:
        almacen.borrar(ruta)
    ids = creados["instancias"]
    if ids:
        marcas = ", ".join("?" for _ in ids)
        for tabla in ("evento", "firma", "adjunto", "version", "paquete_item", "cambio"):
            db.ejecutar(f"delete from {tabla} where instancia_id in ({marcas})", *ids)
    for p in creados["paquetes"]:
        db.ejecutar("delete from paquete_item where paquete_id = ?", p)
        db.ejecutar("delete from paquete where id = ?", p)
    if ids:
        db.ejecutar(f"delete from instancia where id in ({', '.join('?' for _ in ids)})", *ids)
    db.ejecutar("delete from correo where para like ?", f"%{marca}%")
    for cid in creados["contactos"]:
        db.ejecutar("delete from contacto where id = ?", cid)
    for uid in creados["usuarios"]:
        db.ejecutar("delete from perfil where id = ?", uid)
        auth.borrar_usuario(uid)
    for f in db.filas("select nombre from contador"):
        if f["nombre"] not in contadores:
            db.ejecutar("delete from contador where nombre = ?", f["nombre"])
    for nombre, valor in contadores.items():
        db.ejecutar("update contador set valor = ? where nombre = ?", valor, nombre)
    print("  Listo: usuarios, protocolos, archivos y contadores como estaban.")


try:
    print("Prueba contra Supabase real")
    # 1. Administrador de prueba (en producción lo crea herramientas/cargar_usuarios.py)
    clave_admin = auth.clave_temporal() + "9a"
    admin_email = f"admin.{marca}@example.com"
    admin_id = auth.crear_usuario(admin_email, clave_admin, "Admin de prueba")
    creados["usuarios"].append(admin_id)
    db.insertar("perfil", {"id": admin_id, "nombre": "Admin de prueba", "cargo": "Jefe de Calidad", "email": admin_email,
                           "empresa": "Stracon", "rol": "jefe_calidad", "es_admin": 1, "debe_cambiar_clave": 0})
    ok(api("GET", "/config")["auth"] is True, "El servidor pide inicio de sesión (Supabase Auth)")
    api("GET", "/tipos", None, 401)
    ok(True, "Sin sesión no se ve nada")
    api("POST", "/auth/ingresar", esperado=401, json={"email": admin_email, "clave": "incorrecta123"})
    ok(True, "Contraseña incorrecta: rechazada")
    s = entrar(admin_email, clave_admin)
    ADM = s["sesion"]["access_token"]
    ok(s["usuario"]["es_admin"] == 1, "El administrador inicia sesión con correo y contraseña")
    ok(api("GET", "/sesion", ADM)["yo"]["email"] == admin_email, "La sesión identifica a la persona")
    ok(api("POST", "/auth/renovar", json={"refresh_token": s["sesion"]["refresh_token"]})["sesion"]["access_token"],
       "La sesión se renueva sin volver a escribir la contraseña")

    # 2. Alta de usuarios por el administrador
    nuevos = {}
    for clave_rol, rol in (("sup", "supervisor_calidad"), ("ana", "control_documentario"), ("ops", "operaciones")):
        r = api("POST", "/usuarios", ADM, json={"nombre": f"Prueba {clave_rol}", "email": f"{clave_rol}.{marca}@example.com",
                                                "cargo": "Prueba", "rol": rol})
        creados["usuarios"].append(r["usuario"]["id"])
        nuevos[clave_rol] = (r["usuario"], r["clave_temporal"])
    ok(all(len(x[1]) == 10 for x in nuevos.values()), "El alta entrega una contraseña temporal")
    tokens = {}
    for k, (u, temporal) in nuevos.items():
        t_ = entrar(u["email"], temporal)["sesion"]["access_token"]
        r = api("GET", "/tipos", t_, 403)
        assert r.get("codigo") == "cambiar_clave", r
        api("POST", "/auth/cambiar-clave", t_, 400, json={"nueva": "corta"})
        api("POST", "/auth/cambiar-clave", t_, json={"nueva": f"Calidad{marca}2026"})
        tokens[k] = entrar(u["email"], f"Calidad{marca}2026")["sesion"]["access_token"]
    ok(True, "Con contraseña temporal solo puede cambiarla; luego entra con la nueva")
    SUP, ANA, OPS = tokens["sup"], tokens["ana"], tokens["ops"]

    # 3. Firmante externo
    kp = api("POST", "/contactos", ADM, json={"nombre": f"KP prueba {marca}", "email": f"kp.{marca}@example.com",
                                              "cargo": "Supervisor CQA", "empresa": "Knight Piésold"})
    creados["contactos"].append(kp["id"])

    # 4. Protocolo en MIS (no toca la numeración de TMF ni RC)
    tipos = {t["codigo"]: t for t in api("GET", "/tipos", SUP)}
    fund = tipos["ST.CA.PC.001.F002"]
    pid = api("POST", "/protocolos", SUP, json={"tipo_id": fund["id"], "origen": "solicitud_operaciones"})["id"]
    creados["instancias"].append(pid)
    d = api("GET", f"/protocolos/{pid}", SUP)
    checklist = {it["id"]: {"r": "SI"} for s_ in fund["schema"]["secciones"] if s_["tipo"] == "checklist"
                 for g in s_["grupos"] for it in g["items"]}
    adjuntos = {a["id"]: {"adjunta": "NA"} for a in fund["schema"]["adjuntos"]}
    adjuntos["reporte_topografico"] = {"adjunta": "SI", "numero": "RT-PRUEBA"}
    valor = {"cabecera": {**d["inst"]["cabecera"], "entregable": "MIS", "estructura": "Plataforma CG01"},
             "respuestas": {"checklist": checklist, "adjuntos": adjuntos, "descripcion": "Prueba automática Supabase",
                            "campos": {"area": 100, "nivel_terreno": "variable", "prog_inicial": "0+000", "prog_final": "0+010",
                                       "rt_numero": "RT-1", "turno": "Día"}}, "conforme": True}
    api("PUT", f"/protocolos/{pid}/valor", SUP, json=valor)
    api("PUT", f"/protocolos/{pid}/valor", OPS, 403, json=valor)
    ok(True, "Operaciones no puede editar el protocolo")
    img = io.BytesIO()
    Image.new("RGB", (300, 200), "steelblue").save(img, "PNG")
    api("POST", f"/protocolos/{pid}/adjuntos", SUP, files={"archivo": ("plano.png", img.getvalue(), "image/png")},
        data={"tipo": "topografia", "ref_schema": "reporte_topografico"})
    ruta_adj = db.fila("select ruta from adjunto where instancia_id = ?", pid)["ruta"]
    ok(almacen.existe(ruta_adj), "El adjunto quedó en Supabase Storage (privado)")
    api("POST", f"/protocolos/{pid}/enviar-firma", SUP, json={"firmantes": {
        "elaborado": {"perfil_id": nuevos["sup"][0]["id"]}, "revisado_aprobado": {"perfil_id": nuevos["ops"][0]["id"]}}})
    d = api("GET", f"/protocolos/{pid}", SUP)
    ok(d["inst"]["correlativo"].startswith("ATF-MIS-"), f"Correlativo asignado en Supabase: {d['inst']['correlativo']}")
    ok(d["inst"]["estado"] == "validacion_doc" and d["firmas"][0]["estado"] == "firmado", "Firmar y enviar: va a Control Documentario")
    checks = [x["id"] for x in api("GET", "/validacion", ANA)["checks"]]
    api("POST", f"/protocolos/{pid}/validacion", ANA, json={"decision": "aceptado", "checks": checks})
    api("POST", f"/firmas/{d['firmas'][1]['id']}/firmar", SUP, 403)
    ok(api("POST", f"/firmas/{d['firmas'][1]['id']}/firmar", OPS)["estado"] == "listo_revision",
       "Validado por el analista; Operaciones firma con su sesión")
    r = c.get(f"/api/protocolos/{pid}/pdf", headers={"Authorization": f"Bearer {SUP}"})
    ok(r.status_code == 200 and len(PdfReader(io.BytesIO(r.content)).pages) >= 2, "PDF de revisión generado y guardado en Storage")

    # 5. Paquete y portal de KP
    paq = api("POST", "/paquetes", SUP, json={"instancias": [pid], "contacto_id": kp["id"]})
    p_ = next(x for x in api("GET", "/paquetes", SUP) if x["codigo"] == paq["codigo"])
    creados["paquetes"].append(p_["id"])
    token = p_["enlace_demo"].split("t=")[1]
    def codigo_kp():
        api("POST", f"/revision/{token}/codigo")
        return re.search(r"(\d{6})", db.fila("select asunto from correo where para = ? and asunto like ? "
                                             "order by created_at desc, rowid desc", kp["email"], "%Código%")["asunto"]).group(1)
    firma = Image.new("RGBA", (300, 100), (255, 255, 255, 0))
    ImageDraw.Draw(firma).line([(10, 70), (90, 20), (180, 80), (290, 30)], fill=(0, 0, 0, 255), width=4)
    b = io.BytesIO()
    firma.save(b, "PNG")
    firma_url = "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()
    api("POST", f"/revision/{token}/recepcion", json={"codigo": codigo_kp(), "firma": firma_url})
    api("POST", f"/revision/{token}/decidir", json={"codigo": codigo_kp(), "decisiones": [{"instancia_id": pid, "decision": "aceptado"}],
                                                    "firma": firma_url})
    ok(api("GET", f"/protocolos/{pid}", SUP)["inst"]["estado"] == "aprobado", "KP firma por el portal → Aprobado")
    r = c.get(f"/api/protocolos/{pid}/pdf", headers={"Authorization": f"Bearer {SUP}"})
    texto = "".join(pg.extract_text() for pg in PdfReader(io.BytesIO(r.content)).pages)
    ok("CONSTANCIA" in texto.upper() and kp["email"] in texto, "PDF final con constancia, desde Storage")
    hc = c.get(f"/api/paquetes/{p_['id']}/hoja-cargo", headers={"Authorization": f"Bearer {SUP}"})
    ok(hc.status_code == 200 and hc.content[:4] == b"%PDF", "Hoja de Cargo firmada, desde Storage")
    xl = c.get("/api/qc-index?entregable=MIS", headers={"Authorization": f"Bearer {SUP}"})
    ok(xl.status_code == 200 and xl.content[:2] == b"PK", "QC Index generado desde Supabase")

    # 6. Administración
    api("PATCH", f"/usuarios/{nuevos['ops'][0]['id']}", ADM, json={"activo": False})
    api("POST", "/auth/ingresar", esperado=401, json={"email": nuevos["ops"][0]["email"], "clave": f"Calidad{marca}2026"})
    ok(True, "Usuario desactivado: Supabase ya no le deja entrar")
    r = api("POST", f"/usuarios/{nuevos['sup'][0]['id']}/restablecer", ADM)
    ok(entrar(nuevos["sup"][0]["email"], r["clave_temporal"])["usuario"]["debe_cambiar_clave"] == 1,
       "Restablecer contraseña: nueva temporal y cambio obligatorio")
    creados["archivos"].append(f"sellos/{nuevos['sup'][0]['id']}.png")
    print(f"\nTodo correcto contra Supabase: {pasos} verificaciones.")
finally:
    limpiar()
