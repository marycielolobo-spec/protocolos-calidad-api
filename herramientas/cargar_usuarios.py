"""Carga usuarios (Stracon) y firmantes externos (KP / Hudbay) desde el Excel de Calidad.

Uso:  .venv\\Scripts\\python herramientas\\cargar_usuarios.py "C:\\...\\Usuarios.xlsx" [--actualizar]

- Personal de Stracon → cuenta para entrar (Supabase Auth) con una contraseña aleatoria que nadie ve.
  Para dar acceso a alguien, un administrador usa "Restablecer contraseña" en la app y le entrega la temporal.
- Hudbay y KP → firmantes externos (sin cuenta: firman por enlace + código al correo).
- Quien ya existe (mismo correo) no se duplica; con --actualizar se actualizan nombre, cargo, rol y administrador.

Rol: de la columna "Cargo en el sistema" (Administrador, Supervisor de calidad, Operaciones, Topografía,
Control documentario; Hudbay y KP son firmantes externos). Si falta, se deduce del cargo:
  Jefe de Calidad → jefe_calidad · Jefe de Campo → operaciones ·
  Jefe de Topografía, Técnico Proyectista, Asistente de Oficina Técnica → topografia · el resto → supervisor_calidad
"""
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openpyxl import load_workbook  # noqa: E402

from servidor import auth, config, db  # noqa: E402


def _sin_tildes(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").lower()


def rol_por_cargo(cargo):
    c = _sin_tildes(cargo)
    if "control documentario" in c or "documentari" in c:
        return "control_documentario"
    if "jefe de calidad" in c:
        return "jefe_calidad"
    if "jefe de campo" in c:
        return "operaciones"
    if "proyectista" in c or "oficina tecnica" in c or "cadista" in c:
        return "cadista"
    if "topografia" in c or "topografo" in c:
        return "topografia"
    return "supervisor_calidad"


# "Cargo en el sistema" del Excel → rol. "Administrador" toma el rol según su cargo (el permiso de administrador
# lo da la columna ADMINISTRADOR).
ROL_SISTEMA = {"supervisor de calidad": "supervisor_calidad", "operaciones": "operaciones", "topografia": "topografia",
               "cadista": "cadista",
               "control documentario": "control_documentario", "jefe de calidad": "jefe_calidad"}


def rol_de(p):
    return ROL_SISTEMA.get(_sin_tildes(p.get("rol_sistema", "")).strip()) or rol_por_cargo(p["cargo"])


def empresa_corta(razon_social):
    r = _sin_tildes(razon_social)
    if "hudbay" in r:
        return "Hudbay"
    if "knight" in r:
        return "Knight Piésold"
    return "Stracon"


def leer_excel(ruta):
    hoja = load_workbook(ruta, data_only=True).worksheets[0]
    filas = list(hoja.iter_rows(values_only=True))
    cab = [_sin_tildes(str(x or "")).strip() for x in filas[0]]
    col = {nombre: cab.index(nombre) for nombre in ("nombre", "correo", "cargo") if nombre in cab}
    col["empresa"] = next(i for i, x in enumerate(cab) if x.startswith("empres"))
    col["admin"] = next(i for i, x in enumerate(cab) if x.startswith("administrador"))
    col["rol"] = next((i for i, x in enumerate(cab) if x.startswith("cargo en el sistema")), None)
    for f in filas[1:]:
        if not f or not f[col["correo"]]:
            continue
        yield {"nombre": str(f[col["nombre"]]).strip(), "email": str(f[col["correo"]]).strip().lower(),
               "cargo": str(f[col["cargo"]] or "").strip(), "empresa": empresa_corta(str(f[col["empresa"]] or "")),
               "admin": _sin_tildes(str(f[col["admin"]] or "")).strip() == "si",
               "rol_sistema": str(f[col["rol"]] or "") if col["rol"] is not None else ""}


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    actualizar = "--actualizar" in sys.argv
    db.iniciar()
    creados = actualizados = externos = 0
    for p in leer_excel(sys.argv[1]):
        if p["empresa"] != "Stracon":
            if db.fila("select id from contacto where email = ?", p["email"]):
                if actualizar:
                    db.ejecutar("update contacto set nombre = ?, cargo = ?, empresa = ? where email = ?",
                                p["nombre"], p["cargo"], p["empresa"], p["email"])
                continue
            db.insertar("contacto", {"id": db.nuevo_id(), "nombre": p["nombre"], "cargo": p["cargo"],
                                     "email": p["email"], "empresa": p["empresa"]})
            externos += 1
            print(f"  firmante externo: {p['nombre']} ({p['empresa']})")
            continue
        rol = rol_de(p)
        existente = db.fila("select id from perfil where email = ?", p["email"])
        if existente:
            if actualizar:
                db.actualizar("perfil", existente["id"], {"nombre": p["nombre"], "cargo": p["cargo"], "rol": rol,
                                                          "es_admin": int(p["admin"])})
                actualizados += 1
            continue
        uid = auth.crear_usuario(p["email"], auth.clave_temporal(), p["nombre"]) if config.SUPABASE else db.nuevo_id()
        db.insertar("perfil", {"id": uid, "nombre": p["nombre"], "cargo": p["cargo"], "email": p["email"],
                               "empresa": "Stracon", "rol": rol, "es_admin": int(p["admin"]), "debe_cambiar_clave": 1})
        creados += 1
        print(f"  usuario: {p['nombre']:32} {rol:20}{' (administrador)' if p['admin'] else ''}")
    print(f"\nListo: {creados} usuarios nuevos, {actualizados} actualizados, {externos} firmantes externos nuevos.")


if __name__ == "__main__":
    main()
