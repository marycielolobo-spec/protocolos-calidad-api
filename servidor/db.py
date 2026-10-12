"""Base de datos SQLite (un solo archivo: datos/protocolos.db).

SQLite viene incluido en Python: no hay que instalar ni administrar un servidor de base de datos.
Al pasar a Supabase (PostgreSQL) se cambia solo este archivo; las tablas son las mismas.
"""
import json
import shutil
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

VERSION_ESQUEMA = 2      # subirlo cuando cambian las tablas: la base de prueba anterior se respalda y se crea de nuevo

ESQUEMA = """
create table if not exists perfil (
  id text primary key, nombre text not null, cargo text, email text not null unique,
  empresa text, rol text not null, activo integer not null default 1);
create table if not exists contacto (
  id text primary key, nombre text not null, cargo text, email text not null unique,
  empresa text, activo integer not null default 1);
create table if not exists plantilla (
  id text primary key, codigo text not null unique, nombre text not null, roles text not null);
create table if not exists proyecto (
  id text primary key, nombre text, nombre_contrato text, cliente text, codigo_contrato text,
  proyecto_distribucion text, activo integer not null default 1);

-- Maestros para los desplegables (fuente: protocolos/maestros.json)
create table if not exists entregable (codigo text primary key, nombre text not null, orden integer not null);
create table if not exists estructura (
  id integer primary key, entregable text not null references entregable(codigo), codigo text not null,
  nombre text not null, orden integer not null);
create table if not exists plano (
  id integer primary key, entregable text not null references entregable(codigo), codigo text not null, orden integer not null);
create table if not exists lista (clave text not null, valor text not null, orden integer not null, primary key (clave, valor));

create table if not exists tipo (
  id text primary key, codigo text not null unique, sigla text not null, nombre text not null, categoria text,
  revision_formato integer not null default 0, schema text not null, qc_index text,
  plantilla_id text references plantilla(id), activo integer not null default 1);
create table if not exists instancia (
  id text primary key, tipo_id text not null references tipo(id), origen text not null,
  solicitud text, correlativo text unique, cabecera text not null, respuestas text not null, conforme integer,
  estado text not null default 'borrador', version_actual integer not null default 0,
  creado_por text references perfil(id), created_at text not null, updated_at text not null);
create table if not exists version (
  id text primary key, instancia_id text not null references instancia(id), numero integer not null,
  motivo text, modificado_por text, snapshot text not null,
  pdf_revision text, pdf_firmado text, pdf_hash text, paginas integer, created_at text not null,
  unique (instancia_id, numero));
-- canal: 'app' (personal Stracon con sesión) | 'externo' (KP / Hudbay por enlace + código al correo)
create table if not exists firma (
  id text primary key, instancia_id text not null references instancia(id), version integer not null,
  rol text not null, orden integer not null, canal text not null, perfil_id text references perfil(id),
  contacto_id text references contacto(id), empresa_nombre text, nombre text, cargo text, email text,
  estado text not null default 'pendiente', motivo_rechazo text, firmado_at text,
  firma_imagen text, evidencia text);
create table if not exists adjunto (
  id text primary key, instancia_id text not null references instancia(id), version integer not null,
  tipo text, ref_schema text, nombre_archivo text not null, ruta text not null, tamano integer,
  subido_por text, created_at text not null);
create table if not exists paquete (
  id text primary key, codigo text not null unique, contacto_id text not null references contacto(id),
  token_hash text not null unique, token_demo text, enviado_por text references perfil(id),
  es_cambio integer not null default 0, cambio_id text, expira_at text not null, cerrado_at text,
  hoja_cargo text, recibido_firma text, recibido_at text,
  otp_hash text, otp_expira text, otp_intentos integer not null default 0,
  created_at text not null);
create table if not exists paquete_item (
  paquete_id text not null references paquete(id), instancia_id text not null references instancia(id),
  version integer not null, decision text not null default 'pendiente', motivo text, decidido_at text,
  primary key (paquete_id, instancia_id));
create table if not exists cambio (
  id text primary key, instancia_id text not null references instancia(id), version_base integer not null,
  solicitado_por text, motivo text not null, descripcion text,
  decision_calidad text not null default 'pendiente', motivo_calidad text, decidido_calidad_por text,
  decision_externo text not null default 'pendiente', motivo_externo text,
  contacto_id text references contacto(id), resuelta_at text, created_at text not null);
create table if not exists evento (
  id text primary key, instancia_id text references instancia(id), tipo text not null,
  detalle text, actor text, created_at text not null);
create table if not exists correo (
  id text primary key, para text not null, asunto text not null, cuerpo text not null,
  enlace text, enviado integer not null default 0, error text, created_at text not null);
create table if not exists contador (nombre text primary key, valor integer not null);
"""

# Columnas que guardan JSON (se convierten solas a dict/list al leer)
COLUMNAS_JSON = {"roles", "schema", "qc_index", "solicitud", "cabecera", "respuestas", "detalle", "snapshot", "evidencia"}

_conexion = None
_candado = threading.RLock()


def ahora():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def nuevo_id():
    return str(uuid.uuid4())


def _con():
    global _conexion
    if _conexion is None:
        config.DATOS.mkdir(parents=True, exist_ok=True)
        _conexion = sqlite3.connect(config.BASE_DATOS, check_same_thread=False, isolation_level=None)
        _conexion.row_factory = sqlite3.Row
        _conexion.execute("pragma foreign_keys = on")
        _conexion.execute("pragma journal_mode = wal")
    return _conexion


def _a_dict(row):
    if row is None:
        return None
    d = dict(row)
    for k, v in d.items():
        if k in COLUMNAS_JSON and isinstance(v, str):
            d[k] = json.loads(v)
    return d


def _param(v):
    return json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v


def filas(sql, *params):
    with _candado:
        return [_a_dict(r) for r in _con().execute(sql, [_param(p) for p in params]).fetchall()]


def fila(sql, *params):
    r = filas(sql, *params)
    return r[0] if r else None


def ejecutar(sql, *params):
    with _candado:
        return _con().execute(sql, [_param(p) for p in params])


def insertar(tabla, datos):
    cols = ", ".join(datos)
    marcas = ", ".join("?" for _ in datos)
    ejecutar(f"insert into {tabla} ({cols}) values ({marcas})", *datos.values())


def actualizar(tabla, id_, datos, clave="id"):
    sets = ", ".join(f"{k} = ?" for k in datos)
    ejecutar(f"update {tabla} set {sets} where {clave} = ?", *datos.values(), id_)


@contextmanager
def transaccion():
    """Todo lo que pasa dentro se guarda junto, o no se guarda nada si hay un error."""
    with _candado:
        c = _con()
        c.execute("begin immediate")
        try:
            yield
            c.execute("commit")
        except BaseException:
            c.execute("rollback")
            raise


def siguiente(nombre):
    ejecutar("insert into contador (nombre, valor) values (?, 1) "
             "on conflict(nombre) do update set valor = valor + 1", nombre)
    return fila("select valor from contador where nombre = ?", nombre)["valor"]


# ---------------------------------------------------------------------------
# Datos iniciales
# ---------------------------------------------------------------------------
PLANTILLAS = [
    ("STRACON_OPS_KP", "Calidad Stracon + Operaciones Stracon + Knight Piésold", [
        {"rol": "elaborado", "empresa": "Stracon", "area": "Calidad", "canal": "app"},
        {"rol": "revisado_aprobado", "empresa": "Stracon", "area": "Operaciones", "canal": "app"},
        {"rol": "aceptado", "empresa": "Knight Piésold", "area": "Supervisión", "canal": "externo"}]),
    ("CALIDAD_KP_HUDBAY", "Calidad Stracon + Knight Piésold + Operaciones Hudbay", [
        {"rol": "elaborado", "empresa": "Stracon", "area": "Calidad", "canal": "app"},
        {"rol": "revisado_aprobado", "empresa": "Knight Piésold", "area": "Supervisión", "canal": "externo"},
        {"rol": "aceptado", "empresa": "Hudbay", "area": "Operaciones", "canal": "externo"}]),
    ("STRACON_OPS_HUDBAY", "Calidad Stracon + Operaciones Stracon + Hudbay (supervisión directa)", [
        {"rol": "elaborado", "empresa": "Stracon", "area": "Calidad", "canal": "app"},
        {"rol": "revisado_aprobado", "empresa": "Stracon", "area": "Operaciones", "canal": "app"},
        {"rol": "aceptado", "empresa": "Hudbay", "area": "Supervisión", "canal": "externo"}]),
]

PERFILES_DEMO = [
    ("Supervisor Calidad (demo)", "Supervisor de Calidad", "supervisor@demo", "supervisor_calidad"),
    ("Jefe de Calidad (demo)", "Jefe de Calidad", "jefe.calidad@demo", "jefe_calidad"),
    ("Ing. Operaciones (demo)", "Ingeniero de Campo", "operaciones@demo", "operaciones"),
]
CONTACTOS_DEMO = [
    ("Revisor KP (demo)", "Supervisor QA", "revisor.kp@demo", "Knight Piésold"),
    ("Supervisión Hudbay (demo)", "Supervisor", "hudbay@demo", "Hudbay"),
]


def _revisar_version():
    """Si la base de datos es de una versión anterior (solo datos de prueba), se respalda y se crea de nuevo."""
    global _conexion
    if not config.BASE_DATOS.exists():
        return
    with _candado:
        version = _con().execute("pragma user_version").fetchone()[0]
        if version == VERSION_ESQUEMA:
            return
        _conexion.close()
        _conexion = None
        sello = datetime.now().strftime("%Y%m%d-%H%M%S")
        respaldo = config.DATOS / f"respaldo-{sello}"
        respaldo.mkdir(parents=True)
        for sufijo in ("", "-wal", "-shm"):
            p = config.BASE_DATOS.with_name(config.BASE_DATOS.name + sufijo)
            if p.exists():
                shutil.move(p, respaldo / p.name)
        if config.ARCHIVOS.exists():
            shutil.move(config.ARCHIVOS, respaldo / "archivos")
        print(f"[db] Base de datos anterior respaldada en {respaldo}")


def iniciar():
    """Crea las tablas, carga los datos iniciales y actualiza formatos y maestros desde protocolos/."""
    _revisar_version()
    with _candado:
        _con().executescript(ESQUEMA)
        _con().execute(f"pragma user_version = {VERSION_ESQUEMA}")
    maestros = json.loads(config.MAESTROS_JSON.read_text(encoding="utf-8"))
    with transaccion():
        for codigo, nombre, roles in PLANTILLAS:
            if not fila("select id from plantilla where codigo = ?", codigo):
                insertar("plantilla", {"id": nuevo_id(), "codigo": codigo, "nombre": nombre, "roles": roles})
        p = maestros["proyecto"]
        actual = fila("select id from proyecto")
        datos = {k: p[k] for k in ("nombre", "nombre_contrato", "cliente", "codigo_contrato", "proyecto_distribucion")}
        if actual:
            actualizar("proyecto", actual["id"], datos)
        else:
            insertar("proyecto", {"id": nuevo_id(), **datos})
        if not fila("select id from perfil"):
            for nombre, cargo, email, rol in PERFILES_DEMO:
                insertar("perfil", {"id": nuevo_id(), "nombre": nombre, "cargo": cargo, "email": email,
                                    "empresa": "Stracon", "rol": rol})
            for nombre, cargo, email, empresa in CONTACTOS_DEMO:
                insertar("contacto", {"id": nuevo_id(), "nombre": nombre, "cargo": cargo, "email": email,
                                      "empresa": empresa})
        cargar_maestros(maestros)
        cargar_tipos()


def cargar_maestros(m):
    """Entregables, estructuras, planos y listas. Por ahora la fuente es protocolos/maestros.json
    (en la 2ª etapa se editarán desde la app)."""
    ejecutar("delete from plano")
    ejecutar("delete from estructura")
    ejecutar("delete from lista")
    codigos = [e["codigo"] for e in m["entregables"]]
    for i, e in enumerate(m["entregables"]):
        ejecutar("insert into entregable (codigo, nombre, orden) values (?, ?, ?) "
                 "on conflict(codigo) do update set nombre = excluded.nombre, orden = excluded.orden", e["codigo"], e["nombre"], i)
        for j, s in enumerate(e["estructuras"]):
            insertar("estructura", {"entregable": e["codigo"], "codigo": s["codigo"], "nombre": s["nombre"], "orden": j})
        for j, p in enumerate(e.get("planos", [])):
            insertar("plano", {"entregable": e["codigo"], "codigo": p, "orden": j})
    marcas = ", ".join("?" for _ in codigos)
    ejecutar(f"delete from entregable where codigo not in ({marcas})", *codigos)
    for clave, valores in m["listas"].items():
        for j, v in enumerate(valores):
            insertar("lista", {"clave": clave, "valor": v, "orden": j})


def cargar_tipos():
    tipos = json.loads(config.TIPOS_JSON.read_text(encoding="utf-8"))
    for t in tipos:
        _revisar_ids(t)
        plantilla = fila("select id from plantilla where codigo = ?", t["plantilla_firma"])
        if not plantilla:
            raise ValueError(f"{t['codigo']}: plantilla de firma desconocida {t['plantilla_firma']}")
        ejecutar("""insert into tipo (id, codigo, sigla, nombre, categoria, schema, qc_index, plantilla_id)
                    values (?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(codigo) do update set sigla = excluded.sigla, nombre = excluded.nombre,
                    categoria = excluded.categoria, schema = excluded.schema, qc_index = excluded.qc_index""",
                 t["codigo"], t["codigo"], t["sigla"], t["nombre"], t["categoria"], t["schema"], t.get("qc_index"),
                 plantilla["id"])


def _revisar_ids(t):
    """Las respuestas se guardan por id de ítem: no puede haber ids repetidos en un mismo formato."""
    ids = []
    for s in t["schema"]["secciones"]:
        if s["tipo"] == "checklist":
            ids += [it["id"] for g in s["grupos"] for it in g["items"]]
        if s["tipo"] == "campos":
            ids += [c["id"] for c in s["campos"]]
    repetidos = {i for i in ids if ids.count(i) > 1}
    if repetidos:
        raise ValueError(f"{t['codigo']}: ids duplicados -> {', '.join(sorted(repetidos))}")


def reiniciar():
    """Borra todo (solo para el modo demo) y vuelve a cargar los datos iniciales."""
    global _conexion
    with _candado:                  # nadie consulta la base mientras se vuelve a crear
        if _conexion is not None:
            _conexion.close()
            _conexion = None
        for sufijo in ("", "-wal", "-shm"):
            p = config.BASE_DATOS.with_name(config.BASE_DATOS.name + sufijo)
            if p.exists():
                p.unlink()
        if config.ARCHIVOS.exists():
            shutil.rmtree(config.ARCHIVOS)
        iniciar()
