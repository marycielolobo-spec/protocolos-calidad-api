"""Base de datos: SQLite local (demo y pruebas) o PostgreSQL de Supabase (piloto y producción).

- Sin DATABASE_URL en .env → SQLite, un solo archivo (datos/protocolos.db). Lo usan la demo local y las pruebas.
- Con DATABASE_URL → PostgreSQL de Supabase. Las tablas son las mismas (ESQUEMA se adapta solo) y todas tienen
  RLS activado sin políticas: nadie puede leerlas con la clave publicable; solo este servidor, con su conexión.
"""
import hashlib
import json
import re
import shutil
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

POSTGRES = bool(config.DATABASE_URL)
VERSION_ESQUEMA = 3      # subirlo cuando cambian las tablas (SQLite: la base de prueba anterior se respalda y se crea de nuevo)

ESQUEMA = """
-- rol: supervisor_calidad | jefe_calidad | operaciones | topografia. es_admin: da de alta usuarios.
-- Con Supabase, id = el id del usuario en Supabase Auth.
create table if not exists perfil (
  id text primary key, nombre text not null, cargo text, email text not null unique,
  empresa text, rol text not null, es_admin integer not null default 0,
  debe_cambiar_clave integer not null default 0, tiene_sello integer not null default 0,
  activo integer not null default 1);
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
create table if not exists meta (clave text primary key, valor text);
"""

# Tablas que se listan en orden de creación (SQLite usa su rowid interno; en PostgreSQL se agrega la columna)
_CON_ORDEN = ("perfil", "contacto", "evento", "paquete_item", "correo")


def _esquema_postgres():
    """La misma definición, adaptada a PostgreSQL: jsonb, numeración automática, orden de creación y RLS."""
    s = ESQUEMA
    for col in COLUMNAS_JSON:
        s = re.sub(rf"\b{col} text\b", f"{col} jsonb", s)
    s = s.replace("id integer primary key", "id bigint generated by default as identity primary key")
    for tabla in _CON_ORDEN:
        s = s.replace(f"create table if not exists {tabla} (",
                      f"create table if not exists {tabla} (\n  rowid bigint generated always as identity,")
    tablas = re.findall(r"create table if not exists (\w+)", s)
    return s + "\n" + "\n".join(f"alter table {x} enable row level security;" for x in tablas)


# Columnas que guardan JSON (se convierten solas a dict/list al leer)
COLUMNAS_JSON = {"roles", "schema", "qc_index", "solicitud", "cabecera", "respuestas", "detalle", "snapshot", "evidencia"}

_conexion = None
_candado = threading.RLock()


def ahora():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def nuevo_id():
    return str(uuid.uuid4())


def _conectar():
    if POSTGRES:
        import psycopg
        from psycopg.rows import dict_row
        # prepare_threshold=None: el "transaction pooler" de Supabase no admite sentencias preparadas
        return psycopg.connect(config.DATABASE_URL, autocommit=True, prepare_threshold=None,
                               row_factory=dict_row, connect_timeout=15)
    config.DATOS.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.BASE_DATOS, check_same_thread=False, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("pragma foreign_keys = on")
    c.execute("pragma journal_mode = wal")
    return c


def _con():
    global _conexion
    if _conexion is None or (POSTGRES and _conexion.closed):
        _conexion = _conectar()
    return _conexion


def _a_dict(row):
    if row is None:
        return None
    d = dict(row)
    for k, v in d.items():
        if k in COLUMNAS_JSON and isinstance(v, str):
            d[k] = json.loads(v)
    d.pop("rowid", None)
    return d


def _param(v):
    if isinstance(v, (dict, list)):
        if POSTGRES:
            from psycopg.types.json import Jsonb
            return Jsonb(v)
        return json.dumps(v, ensure_ascii=False)
    return v


def _sql(sql):
    """Las consultas se escriben con "?" (SQLite); PostgreSQL usa "%s"."""
    return sql.replace("%", "%%").replace("?", "%s") if POSTGRES else sql


def _ejecutar(sql, params):
    params = [_param(p) for p in params]
    try:
        return _con().execute(_sql(sql), params)
    except Exception as e:
        # Conexión cortada (p. ej. el servidor estuvo inactivo): se reconecta una vez, salvo dentro de una transacción
        if POSTGRES and _conexion is not None and _conexion.closed and not getattr(_local, "en_transaccion", False):
            return _con().execute(_sql(sql), params)
        raise e


_local = threading.local()


def filas(sql, *params):
    with _candado:
        cur = _ejecutar(sql, params)
        return [_a_dict(r) for r in cur.fetchall()] if cur.description else []


def fila(sql, *params):
    r = filas(sql, *params)
    return r[0] if r else None


def ejecutar(sql, *params):
    with _candado:
        return _ejecutar(sql, params)


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
        if POSTGRES:
            _local.en_transaccion = True
            try:
                with c.transaction():
                    yield
            finally:
                _local.en_transaccion = False
            return
        c.execute("begin immediate")
        try:
            yield
            c.execute("commit")
        except BaseException:
            c.execute("rollback")
            raise


def siguiente(nombre):
    """Contador atómico (correlativos, códigos de paquete): dos personas a la vez nunca reciben el mismo número."""
    return fila("insert into contador (nombre, valor) values (?, 1) "
                "on conflict(nombre) do update set valor = contador.valor + 1 returning valor", nombre)["valor"]


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
    """SQLite: si la base es de una versión anterior (solo datos de prueba), se respalda y se crea de nuevo."""
    global _conexion
    if POSTGRES or not config.BASE_DATOS.exists():
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


def _meta(clave, valor=None):
    if valor is None:
        f = fila("select valor from meta where clave = ?", clave)
        return f and f["valor"]
    ejecutar("insert into meta (clave, valor) values (?, ?) on conflict(clave) do update set valor = excluded.valor",
             clave, valor)
    return valor


def _crear_tablas():
    with _candado:
        if POSTGRES:
            _con().execute(_esquema_postgres())
            # Columnas agregadas después de crear las tablas por primera vez
            _con().execute("alter table perfil add column if not exists es_admin integer not null default 0")
            _con().execute("alter table perfil add column if not exists debe_cambiar_clave integer not null default 0")
            _con().execute("alter table perfil add column if not exists tiene_sello integer not null default 0")
        else:
            _con().executescript(ESQUEMA)
            _con().execute(f"pragma user_version = {VERSION_ESQUEMA}")


def iniciar():
    """Crea las tablas, carga los datos iniciales y actualiza formatos y maestros desde protocolos/.
    Formatos y maestros se recargan solo si cambiaron los archivos (con Supabase arrancan varias copias del servidor)."""
    _revisar_version()
    _crear_tablas()
    texto_maestros = config.MAESTROS_JSON.read_text(encoding="utf-8")
    texto_tipos = config.TIPOS_JSON.read_text(encoding="utf-8")
    huella = hashlib.sha256((texto_maestros + texto_tipos).encode()).hexdigest()
    if _meta("datos_iniciales") == huella:
        return
    maestros = json.loads(texto_maestros)
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
        if not POSTGRES and not fila("select id from perfil"):
            # Solo en la demo local: con Supabase los usuarios reales se cargan con herramientas/cargar_usuarios.py
            for nombre, cargo, email, rol in PERFILES_DEMO:
                insertar("perfil", {"id": nuevo_id(), "nombre": nombre, "cargo": cargo, "email": email,
                                    "empresa": "Stracon", "rol": rol, "es_admin": int(rol == "jefe_calidad")})
            for nombre, cargo, email, empresa in CONTACTOS_DEMO:
                insertar("contacto", {"id": nuevo_id(), "nombre": nombre, "cargo": cargo, "email": email,
                                      "empresa": empresa})
        cargar_maestros(maestros)
        cargar_tipos(json.loads(texto_tipos))
        _meta("datos_iniciales", huella)


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


def cargar_tipos(tipos):
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
    """Borra todo (solo para el modo demo local) y vuelve a cargar los datos iniciales."""
    global _conexion
    if POSTGRES:
        raise RuntimeError("Reiniciar solo está disponible en la demo local")
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
