// Capa de datos: todas las acciones van al servidor Python (servidor/main.py) por /api/...
// Las reglas (estados, firmas, versiones, paquetes) viven en el servidor (servidor/logica.py).

export const ESTADOS = {
  borrador: 'Borrador', firma_interna: 'Firma interna', listo_revision: 'Listo para revisión',
  en_revision: 'En revisión (tercero)', aprobado: 'Aprobado',
  observado: 'Observado', en_modificacion: 'En modificación', anulado: 'Anulado',
};
export const EDITABLE = new Set(['borrador', 'observado', 'en_modificacion']);

const CLAVE_USUARIO = 'protocolos-usuario';
const leerUsuario = () => { try { return localStorage.getItem(CLAVE_USUARIO); } catch { return null; } };
const guardarUsuario = (id) => { try { localStorage.setItem(CLAVE_USUARIO, id); } catch { /* modo privado */ } };

class Api {
  constructor(sesion) {
    this.modo = sesion.modo;              // { demo, correo_real }
    this.demo = sesion.modo.demo;
    this.perfiles = sesion.perfiles;
    this.contactos = sesion.contactos;
    const guardado = leerUsuario();
    this.usuarioId = this.perfiles.some((p) => p.id === guardado) ? guardado : this.perfiles[0]?.id;
  }

  async pedir(metodo, ruta, cuerpo) {
    const opciones = { method: metodo, headers: { 'X-Usuario': this.usuarioId || '' } };
    if (cuerpo instanceof FormData) opciones.body = cuerpo;
    else if (cuerpo !== undefined) { opciones.body = JSON.stringify(cuerpo); opciones.headers['Content-Type'] = 'application/json'; }
    const r = await fetch(`/api${ruta}`, opciones);
    const datos = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(datos.error || (Array.isArray(datos.detail) ? 'Datos incompletos' : datos.detail) || `Error ${r.status}`);
    return datos;
  }

  get yo() { return this.perfiles.find((p) => p.id === this.usuarioId); }
  cambiarUsuario(id) { this.usuarioId = id; guardarUsuario(id); }
  async reiniciar() { await this.pedir('POST', '/reiniciar'); }

  async usuario() { return this.yo; }
  async personas() { return { perfiles: this.perfiles, contactos: this.contactos }; }
  tipos() { return this.pedir('GET', '/tipos'); }
  maestros() { return this.pedir('GET', '/maestros'); }
  listar() { return this.pedir('GET', '/protocolos'); }
  async crear({ tipo_id, origen, solicitud }) { return (await this.pedir('POST', '/protocolos', { tipo_id, origen, solicitud })).id; }
  obtener(id) { return this.pedir('GET', `/protocolos/${id}`).catch((e) => { if (/no encontrado/i.test(e.message)) return null; throw e; }); }
  guardarValor(id, valor) { return this.pedir('PUT', `/protocolos/${id}/valor`, valor); }
  subirAdjunto(id, archivo, { tipo, ref_schema }) {
    const fd = new FormData();
    fd.append('archivo', archivo); fd.append('tipo', tipo || 'otro'); fd.append('ref_schema', ref_schema || '');
    return this.pedir('POST', `/protocolos/${id}/adjuntos`, fd);
  }
  quitarAdjunto(adjId) { return this.pedir('DELETE', `/adjuntos/${adjId}`); }
  urlAdjunto(adjId) { return `/api/adjuntos/${adjId}`; }
  urlPdf(id, version) { return `/api/protocolos/${id}/pdf${version != null ? `?version=${version}` : ''}`; }

  enviarAFirma(id, firmantes) { return this.pedir('POST', `/protocolos/${id}/enviar-firma`, { firmantes }); }
  firmar(firmaId) { return this.pedir('POST', `/firmas/${firmaId}/firmar`); }
  rechazar(firmaId, motivo) { return this.pedir('POST', `/firmas/${firmaId}/rechazar`, { motivo }); }

  listosParaRevision() { return this.pedir('GET', '/protocolos?estado=listo_revision'); }
  crearPaquete(ids, contactoId) { return this.pedir('POST', '/paquetes', { instancias: ids, contacto_id: contactoId }); }
  paquetes() { return this.pedir('GET', '/paquetes'); }
  urlHojaCargo(paqId) { return `/api/paquetes/${paqId}/hoja-cargo`; }
  urlQcIndex(entregable) { return `/api/qc-index${entregable ? `?entregable=${encodeURIComponent(entregable)}` : ''}`; }

  solicitarCambio(id, { motivo, descripcion, contactoId }) {
    return this.pedir('POST', `/protocolos/${id}/cambios`, { motivo, descripcion, contacto_id: contactoId });
  }
  decidirCambioCalidad(cambioId, decision, motivo) { return this.pedir('POST', `/cambios/${cambioId}/decidir`, { decision, motivo }); }
  correos() { return this.pedir('GET', '/correos'); }

  // Portal externo (KP / Hudbay): enlace personal + código al correo + firma dibujada
  revisionObtener(token) { return this.pedir('GET', `/revision/${encodeURIComponent(token)}`); }
  solicitarCodigo(token) { return this.pedir('POST', `/revision/${encodeURIComponent(token)}/codigo`); }
  revisionDecidir(token, decisiones, codigo, firma) {
    return this.pedir('POST', `/revision/${encodeURIComponent(token)}/decidir`, { decisiones, codigo, firma });
  }
  decidirCambioExterno(token, decision, motivo, codigo) {
    return this.pedir('POST', `/revision/${encodeURIComponent(token)}/cambio`, { decision, motivo, codigo });
  }
}

export async function conectar() {
  const r = await fetch('/api/sesion');
  if (!r.ok) throw new Error('No se pudo conectar con el servidor. ¿Está abierto iniciar.bat?');
  return new Api(await r.json());
}

// Portal externo: no necesita la lista de usuarios internos
export function conectarExterno() {
  return new Api({ modo: {}, perfiles: [], contactos: [] });
}
