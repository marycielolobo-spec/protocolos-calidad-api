import { conectar, ESTADOS, EDITABLE } from './datos.js';
import { htmlProtocolo, montarFormulario, ROLES } from './motor.js';

const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fecha = (iso) => (iso ? new Date(iso).toLocaleString('es-PE', { dateStyle: 'short', timeStyle: 'short' }) : '');
const ROL_LABEL = Object.fromEntries(ROLES);
const CATEGORIAS = { topografia: 'Topografía', fundacion: 'Fundación', relleno: 'Relleno', vaciado: 'Vaciado' };
const nombreEntregable = (c) => maestros.entregables.find((e) => e.codigo === c)?.nombre || c || '';
const EVENTOS = {
  creado: 'Creado', enviado_firma: 'Enviado a firma', firmado: 'Firmado', rechazado: 'Rechazado', notificacion: 'Notificación enviada',
  aceptado_revision: 'Aceptado por el tercero', cambio_solicitado: 'Solicitud de cambio', cambio_rechazado: 'Cambio rechazado', version_nueva: 'Nueva versión abierta',
  cambio_aceptado_calidad: 'Cambio aprobado por Jefatura de Calidad', cambio_rechazado_calidad: 'Cambio rechazado por Jefatura de Calidad',
  cambio_aceptado_externo: 'Cambio aprobado por el tercero', cambio_rechazado_externo: 'Cambio rechazado por el tercero',
};

let api; let yo; let personas; let maestros;
const main = $('#app');

function toast(msg, err = false) {
  const t = document.createElement('div');
  t.className = `toast${err ? ' err' : ''}`; t.textContent = msg; t.setAttribute('role', 'status');
  document.body.append(t); setTimeout(() => t.remove(), err ? 6000 : 3000);
}
async function intentar(fn) {
  try { return await fn(); } catch (e) { console.error(e); toast(e.message, true); return undefined; }
}
function dialogo(html, onOk) {
  const d = document.createElement('dialog');
  d.innerHTML = `<form method="dialog">${html}<div class="pie"><button class="btn" value="cancel" formnovalidate>Cancelar</button><button class="btn pri" value="ok">Aceptar</button></div></form>`;
  document.body.append(d);
  const form = d.querySelector('form');
  // Se responde al botón presionado (submit), no al evento "close": así funciona igual en cualquier navegador
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const datos = new FormData(form);
    d.close();
    if (e.submitter?.value === 'ok') await intentar(() => onOk(datos, d));
    d.remove();
  });
  d.addEventListener('cancel', () => d.remove());          // tecla Esc
  d.showModal();
  return d;
}

// ---------- Cabecera / usuario ------------------------------------------------
function pintarTop() {
  const ruta = location.hash.split('/')[1] || '';
  const enlaces = [['', 'Protocolos'], ['nuevo', 'Nuevo'], ['paquetes', 'Paquetes a revisión']];
  if (!api.modo.correo_real) enlaces.push(['correos', 'Correos (simulados)']);
  $('#nav').innerHTML = enlaces.map(([r, l]) => `<a href="#/${r}" class="${r === ruta ? 'on' : ''}">${l}</a>`).join('');
  // Mientras no exista inicio de sesión corporativo, se elige el usuario con "Actuar como"
  $('#usuario').innerHTML = `<label>Actuar como <select id="sel-usuario">${personas.perfiles.map((p) =>
    `<option value="${p.id}"${p.id === yo.id ? ' selected' : ''}>${esc(p.nombre)}</option>`).join('')}</select></label>
    ${api.demo ? '<button class="btn" id="btn-reset" title="Borra los datos de prueba">Reiniciar demo</button>' : ''}`;
  $('#sel-usuario').onchange = (e) => { api.cambiarUsuario(e.target.value); yo = api.yo; ruteo(); };
  const reset = $('#btn-reset');
  if (reset) {
    reset.onclick = () => {
      if (!confirm('¿Borrar todos los datos del demo?')) return;
      intentar(async () => { await api.reiniciar(); location.hash = '#/'; location.reload(); });
    };
  }
}

// ---------- Bandeja -------------------------------------------------------
async function vistaBandeja() {
  const lista = await api.listar();
  main.innerHTML = `<h1>Protocolos</h1>
    <div class="filtros">
      <input id="f-txt" type="search" placeholder="Buscar por correlativo, formato, entregable, estructura…" aria-label="Buscar">
      <select id="f-estado" aria-label="Estado"><option value="">Todos los estados</option>${Object.entries(ESTADOS).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>
      <a class="btn pri" href="#/nuevo">+ Nuevo protocolo</a>
    </div>
    <div class="filtros qc"><label>QC Index (Excel):
      <select id="qc-ent" aria-label="Entregable del QC Index"><option value="">Todos los entregables</option>${maestros.entregables.map((e) => `<option value="${esc(e.codigo)}">${esc(e.nombre)}</option>`).join('')}</select></label>
      <a class="btn" id="btn-qc" href="${api.urlQcIndex('')}">Descargar QC Index</a></div>
    <div class="lista-wrap"><table class="lista"><thead><tr><th>Correlativo</th><th>Protocolo</th><th>Entregable / Estructura</th><th>Origen</th><th>Versión</th><th>Estado</th><th>Actualizado</th></tr></thead><tbody id="filas"></tbody></table></div>`;
  $('#qc-ent').onchange = (e) => { $('#btn-qc').href = api.urlQcIndex(e.target.value); };
  const pintar = () => {
    const q = $('#f-txt').value.toLowerCase(); const est = $('#f-estado').value;
    const fs = lista.filter((i) => (!est || i.estado === est) &&
      (!q || [i.correlativo, i.tipo?.codigo, i.tipo?.nombre, i.cabecera?.elemento, i.cabecera?.estructura, nombreEntregable(i.cabecera?.entregable)].join(' ').toLowerCase().includes(q)));
    $('#filas').innerHTML = fs.length ? fs.map((i) => `<tr data-href="#/p/${i.id}">
      <td>${esc(i.correlativo || '—')}</td><td><div>${esc(i.tipo?.nombre)}</div><div class="muted">${esc(i.tipo?.codigo)}</div></td>
      <td><div>${esc(nombreEntregable(i.cabecera?.entregable))}</div><div class="muted">${esc(i.cabecera?.estructura || '')}</div></td><td>${i.origen === 'backlog' ? 'Backlog' : 'Solicitud Op.'}</td>
      <td>V${i.version_actual}</td><td><span class="chip ${i.estado}">${ESTADOS[i.estado]}</span></td><td class="muted">${fecha(i.updated_at)}</td></tr>`).join('')
      : `<tr><td colspan="7" class="vacio">${lista.length ? 'Sin resultados para el filtro.' : 'Aún no hay protocolos. Crea el primero con “Nuevo protocolo”.'}</td></tr>`;
  };
  $('#f-txt').oninput = pintar; $('#f-estado').onchange = pintar;
  $('#filas').onclick = (e) => { const tr = e.target.closest('tr[data-href]'); if (tr) location.hash = tr.dataset.href; };
  pintar();
}

// ---------- Nuevo ---------------------------------------------------------
async function vistaNuevo() {
  const tipos = await api.tipos();
  main.innerHTML = `<h1>Nuevo protocolo</h1>
    <div class="filtros"><label>Disparador:
      <select id="origen"><option value="solicitud_operaciones">Solicitud de Operaciones</option><option value="backlog">Backlog / obligación periódica</option></select></label>
      <input id="ref" placeholder="Referencia de la solicitud (opcional)"></div>
    <div class="grid-tipos">${tipos.map((t) => `<button class="card tipo-card" data-id="${t.id}">
      <span class="chip cat">${CATEGORIAS[t.categoria] || t.categoria}</span><div class="cod">${esc(t.codigo)}</div><h2>${esc(t.nombre)}</h2>
      <div class="muted">Firmas: ${esc(t.plantilla?.nombre || '')}</div></button>`).join('')}</div>`;
  main.querySelector('.grid-tipos').onclick = (e) => {
    const b = e.target.closest('[data-id]'); if (!b) return;
    intentar(async () => {
      const id = await api.crear({ tipo_id: b.dataset.id, origen: $('#origen').value, solicitud: $('#ref').value ? { referencia: $('#ref').value } : null });
      location.hash = `#/p/${id}`;
    });
  };
}

// ---------- Adjuntos (slots del motor + adjuntos libres) ------------------------------------
function pintarAdjuntos(cont, d, editable, recargar) {
  const chip = (a) => `<span class="adj-file"><a href="${api.urlAdjunto(a.id)}" target="_blank" rel="noopener">📎 ${esc(a.nombre_archivo)}</a>${editable ? `<button type="button" data-quitar-adj="${a.id}" aria-label="Quitar ${esc(a.nombre_archivo)}">×</button>` : ''}</span>`;
  const subir = (ref, tipo, label = 'Subir archivo') => (editable
    ? `<label class="adj-subir">+ ${label}<input type="file" accept=".pdf,image/*" data-ref="${ref}" data-tipo="${tipo}" multiple></label>` : '');
  cont.querySelectorAll('[data-slot-adjunto]').forEach((slot) => {
    const ref = slot.dataset.slotAdjunto;
    const propios = d.adjuntos.filter((a) => a.ref_schema === ref);
    slot.innerHTML = `<div class="adj-lista">${propios.map(chip).join('')}${subir(ref, slot.dataset.tipoAdjunto)}</div>`;
  });
  const libres = d.adjuntos.filter((a) => !a.ref_schema);
  const panel = $('#adj-libres');
  if (panel) {
    panel.innerHTML = `<h2>Otros adjuntos</h2><p class="muted">Ensayos de laboratorio u otros documentos que se unirán al PDF final.</p>
      <div class="adj-lista">${libres.map(chip).join('') || '<span class="muted">Ninguno</span>'}</div>
      ${editable ? `<div style="margin-top:8px">${subir('', 'laboratorio', 'Ensayo de laboratorio')} &nbsp; ${subir('', 'otro', 'Otro')}</div>` : ''}`;
  }
  const root = cont.closest('.editor') || cont;
  root.onchange = async (e) => {
    const inp = e.target.closest('input[type=file]'); if (!inp) return;
    for (const f of inp.files) await intentar(() => api.subirAdjunto(d.inst.id, f, { tipo: inp.dataset.tipo, ref_schema: inp.dataset.ref || null }));
    recargar();
  };
  if (root.dataset.adjListo) return;   // el motor re-pinta al agregar filas: no duplicar el listener
  root.dataset.adjListo = '1';
  root.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-quitar-adj]'); if (!b) return;
    await intentar(() => api.quitarAdjunto(b.dataset.quitarAdj)); recargar();
  });
}

// ---------- Protocolo: editor o detalle ---------------------------------------------
async function vistaProtocolo(id) {
  const d = await api.obtener(id);
  if (!d) { main.innerHTML = '<p class="vacio">Protocolo no encontrado.</p>'; return; }
  const { inst, tipo } = d;
  const editable = EDITABLE.has(inst.estado);
  const recargar = () => vistaProtocolo(id);

  main.innerHTML = `<div class="barra">
      <a href="#/" class="btn">← Volver</a>
      <span class="chip ${inst.estado}">${ESTADOS[inst.estado]}</span>
      <strong>${esc(inst.correlativo || 'Sin correlativo')}</strong><span class="muted">V${inst.version_actual}</span>
      ${d.numero_registro ? `<span class="muted nreg">${esc(d.numero_registro)}</span>` : ''}
      <span class="guardado" id="guardado"></span>
      ${editable ? '<button class="btn" id="btn-validar">Validar</button><button class="btn pri" id="btn-enviar">Enviar a firma</button>' : ''}
      ${!editable && inst.estado !== 'firma_interna' ? `<a class="btn pri" href="${api.urlPdf(inst.id)}" target="_blank" rel="noopener">Descargar PDF</a>` : ''}
      ${!editable ? '<button class="btn" id="btn-imprimir">Imprimir</button>' : ''}
    </div>
    <div id="errores"></div>
    <div class="editor"><div id="hoja"></div><aside class="lateral" id="lateral"></aside></div>`;

  const hoja = $('#hoja');
  let form;
  if (editable) {
    let t;
    form = montarFormulario(hoja, tipo, inst, {
      firmas: d.firmas, version: inst.version_actual, maestros,
      onRender: (c) => pintarAdjuntos(c, d, true, recargar),
      onCambio: (v) => {
        $('#guardado').textContent = 'Guardando…';
        clearTimeout(t);
        t = setTimeout(() => intentar(async () => { await api.guardarValor(id, v); $('#guardado').textContent = `Guardado ${new Date().toLocaleTimeString('es-PE')}`; }), 600);
      },
    });
    $('#btn-validar').onclick = () => mostrarErrores(form);
    $('#btn-enviar').onclick = () => {
      if (mostrarErrores(form).length) return;
      faltanAdjuntos(tipo, form.valor(), d.adjuntos).length
        ? toast(`Marcó "Sí" pero falta subir: ${faltanAdjuntos(tipo, form.valor(), d.adjuntos).join(', ')}`, true)
        : dialogoEnviar(d, async () => { await api.guardarValor(id, form.valor()); });
    };
  } else {
    hoja.innerHTML = htmlProtocolo(tipo, inst, { soloLectura: true, firmas: d.firmas, version: inst.version_actual, maestros });
    pintarAdjuntos(hoja, d, false, recargar);
    $('#btn-imprimir').onclick = () => window.print();
  }
  pintarLateral(d, editable, recargar);
}

function mostrarErrores(form) {
  const errs = form.validar();
  form.marcarErrores(errs);
  $('#errores').innerHTML = errs.length
    ? `<div class="errores" role="alert"><strong>${errs.length} pendiente(s) antes de enviar:</strong><ul>${errs.slice(0, 8).map((e) => `<li>${esc(e.mensaje)}</li>`).join('')}${errs.length > 8 ? `<li>… y ${errs.length - 8} más</li>` : ''}</ul></div>`
    : '';
  if (!errs.length) toast('Formulario completo ✔');
  return errs;
}

function faltanAdjuntos(tipo, valor, adjuntos) {
  return (tipo.schema.adjuntos || [])
    .filter((a) => valor.respuestas.adjuntos?.[a.id]?.adjunta === 'SI' && !adjuntos.some((x) => x.ref_schema === a.id))
    .map((a) => a.label);
}

function dialogoEnviar(d, antes) {
  const roles = d.tipo.plantilla.roles;
  const opP = (sel) => (sel ? '' : '<option value="">Seleccione…</option>') + personas.perfiles.map((p) => `<option value="${p.id}"${p.id === sel ? ' selected' : ''}>${esc(p.nombre)} — ${esc(p.cargo || p.rol)}</option>`).join('');
  const opC = (empresa) => `<option value="">(se asigna al armar el paquete)</option>${personas.contactos.filter((c) => !empresa || c.empresa === empresa)
    .map((c) => `<option value="${c.id}">${esc(c.nombre)} — ${esc(c.empresa)}</option>`).join('')}`;
  const filas = roles.map((r) => `<div class="fila"><label>${ROL_LABEL[r.rol]} · ${esc(r.empresa)} ${esc(r.area || '')} ${r.canal === 'externo' ? '(firma en el portal, con código a su correo)' : '(firma en la app)'}</label>
    <select name="${r.rol}" data-canal="${r.canal}" ${r.canal === 'app' ? 'required' : ''}>${r.canal === 'app' ? opP(r.rol === 'elaborado' ? yo.id : null) : opC(r.empresa)}</select></div>`).join('');
  dialogo(`<h2>Enviar a firma</h2><p class="muted">Se congela la versión V${d.inst.version_actual} y se asigna el correlativo (sigla-entregable-número). Las firmas son secuenciales.</p>${filas}`, async (fd, dlg) => {
    const firmantes = {};
    dlg.querySelectorAll('select[data-canal]').forEach((s) => {
      if (s.value) firmantes[s.name] = s.dataset.canal === 'app' ? { perfil_id: s.value } : { contacto_id: s.value };
    });
    await antes();
    await api.enviarAFirma(d.inst.id, firmantes);
    toast('Enviado a firma');
    vistaProtocolo(d.inst.id);
  });
}

function pintarLateral(d, editable, recargar) {
  const { inst } = d;
  const turno = d.firmas.find((f) => f.estado === 'pendiente');
  const firmas = d.firmas.length ? d.firmas.map((f) => {
    const mia = f.canal === 'app' && f.perfil_id === yo.id && turno?.id === f.id && inst.estado === 'firma_interna';
    return `<div class="firma-item"><div><strong>${ROL_LABEL[f.rol]}</strong> · <span class="muted">${esc(f.empresa_nombre)}${f.canal === 'externo' ? ' · portal externo' : ''}</span></div>
      <div>${esc(f.nombre || 'Por asignar')}</div>
      <div><span class="chip ${f.estado === 'firmado' ? 'aprobado' : f.estado === 'rechazado' ? 'observado' : ''}">${f.estado}</span> <span class="muted">${fecha(f.firmado_at)}</span></div>
      ${f.motivo_rechazo ? `<div class="muted">Motivo: ${esc(f.motivo_rechazo)}</div>` : ''}
      ${mia ? `<div class="acciones"><button class="btn pri" data-firmar="${f.id}">Firmar</button><button class="btn peligro" data-rechazar="${f.id}">Rechazar</button></div>` : ''}</div>`;
  }).join('') : '<p class="muted">Se generan al enviar a firma.</p>';


  const cambioPend = d.cambios.find((c) => !c.resuelta_at);
  let cambios = '';
  if (inst.estado === 'aprobado' && !cambioPend) cambios = '<button class="btn" id="btn-cambio">Solicitar modificación</button><p class="muted">Requiere aprobación de la Jefatura de Calidad y del tercero (KP/Hudbay). Genera V' + (inst.version_actual + 1) + '.</p>';
  if (cambioPend) {
    const puedeDecidir = ['jefe_calidad', 'admin'].includes(yo.rol) && cambioPend.decision_calidad === 'pendiente';
    cambios = `<div><strong>Solicitud pendiente</strong> <span class="muted">por ${esc(cambioPend.solicitado_por)}</span></div>
      <div>Motivo: ${esc(cambioPend.motivo)}</div>
      <div class="muted">Jefatura Calidad: ${cambioPend.decision_calidad} · Tercero: ${cambioPend.decision_externo}</div>
      ${puedeDecidir ? `<div class="acciones" style="display:flex;gap:6px;margin-top:6px"><button class="btn pri" data-cambio-ok="${cambioPend.id}">Aprobar</button><button class="btn peligro" data-cambio-no="${cambioPend.id}">Rechazar</button></div>` : ''}
      ${cambioPend.enlace_demo && cambioPend.decision_externo === 'pendiente' ? `<p class="muted">Demo: <a href="${cambioPend.enlace_demo}" target="_blank">abrir portal del tercero</a></p>` : ''}`;
  }

  $('#lateral').innerHTML = `
    <div class="card"><h2>Firmas — V${inst.version_actual}</h2>${firmas}</div>
    ${editable ? '<div class="card" id="adj-libres"></div>' : ''}
    ${cambios ? `<div class="card"><h2>Control de cambios</h2>${cambios}</div>` : ''}
    <div class="card"><h2>Versiones</h2><ul class="lista-simple">${d.versiones.map((v) => `<li><strong>V${v.numero}</strong> <span class="muted">${fecha(v.created_at)}</span>${v.tiene_pdf ? ` · <a href="${api.urlPdf(inst.id, v.numero)}" target="_blank" rel="noopener">PDF${v.pdf_firmado_listo ? ' firmado' : ''}</a>` : ''}${v.motivo ? `<div class="muted">Motivo: ${esc(v.motivo)}</div>` : ''}</li>`).join('') || '<li class="muted">Aún sin versiones cerradas</li>'}</ul></div>
    <div class="card"><h2>Historial</h2><ul class="lista-simple">${d.eventos.map((e) => `<li>${EVENTOS[e.tipo] || e.tipo}${e.detalle?.rol ? ` · ${ROL_LABEL[e.detalle.rol]}` : ''}${e.detalle?.motivo ? ` — “${esc(e.detalle.motivo)}”` : ''}<div class="muted">${esc(e.actor)} · ${fecha(e.created_at)}</div></li>`).join('')}</ul></div>`;
  if (editable) pintarAdjuntos($('#hoja'), d, true, recargar);

  const lat = $('#lateral');
  lat.onclick = (e) => {
    const t = e.target;
    if (t.dataset.firmar) intentar(async () => { t.disabled = true; await api.firmar(t.dataset.firmar); toast('Firmado'); recargar(); });
    if (t.dataset.rechazar) {
      dialogo('<h2>Rechazar</h2><div class="fila"><label for="m">Motivo (obligatorio)</label><textarea id="m" name="motivo" required></textarea></div>',
        async (fd) => { await api.rechazar(t.dataset.rechazar, fd.get('motivo')); toast('Rechazado: vuelve a Calidad como “Observado”'); recargar(); });
    }
    if (t.id === 'btn-cambio') {
      dialogo(`<h2>Solicitar modificación de ${esc(inst.correlativo)}</h2>
        <p class="muted">Se notificará a la Jefatura de Calidad y al tercero. Ambos deben aprobar para abrir V${inst.version_actual + 1}.</p>
        <div class="fila"><label for="mo">Motivo (obligatorio)</label><textarea id="mo" name="motivo" required></textarea></div>
        <div class="fila"><label for="de">Qué se cambiará</label><textarea id="de" name="descripcion"></textarea></div>
        <div class="fila"><label for="co">Notificar a (tercero)</label><select id="co" name="contacto" required>${personas.contactos.map((c) => `<option value="${c.id}">${esc(c.nombre)} — ${esc(c.empresa)}</option>`).join('')}</select></div>`,
      async (fd) => {
        const r = await api.solicitarCambio(inst.id, { motivo: fd.get('motivo'), descripcion: fd.get('descripcion'), contactoId: fd.get('contacto') });
        toast(`Solicitud enviada a ${r.correo} y a la Jefatura de Calidad`); recargar();
      });
    }
    if (t.dataset.cambioOk) intentar(async () => { await api.decidirCambioCalidad(t.dataset.cambioOk, 'aceptado'); toast('Aprobado por Jefatura'); recargar(); });
    if (t.dataset.cambioNo) {
      dialogo('<h2>Rechazar modificación</h2><div class="fila"><label for="m2">Motivo (obligatorio)</label><textarea id="m2" name="motivo" required></textarea></div>',
        async (fd) => { await api.decidirCambioCalidad(t.dataset.cambioNo, 'rechazado', fd.get('motivo')); recargar(); });
    }
  };
}

// ---------- Paquetes al tercero ------------------------------------------------
async function vistaPaquetes() {
  const [listos, paquetes] = await Promise.all([api.listosParaRevision(), api.paquetes()]);
  main.innerHTML = `<h1>Paquetes a revisión</h1>
    <div class="card"><h2>Listos para enviar (${listos.length})</h2>
      <p class="muted">Protocolos con firmas internas completas. El tercero recibe un enlace por correo, sin cuenta ni licencia; puede aceptar unos y rechazar otros (con motivo). Firma en la misma página con un código que le llega al correo. Cada paquete genera su Hoja de Cargo.</p>
      ${listos.length ? `<div class="lista-wrap"><table class="lista"><thead><tr><th><input type="checkbox" id="todos" aria-label="Seleccionar todos"></th><th>Correlativo</th><th>Protocolo</th><th>Estructura</th><th>Versión</th></tr></thead><tbody>
        ${listos.map((i) => `<tr><td><input type="checkbox" class="sel" value="${i.id}" aria-label="${esc(i.correlativo)}"></td><td><a href="#/p/${i.id}">${esc(i.correlativo)}</a></td><td>${esc(i.tipo?.nombre)}</td><td>${esc(i.cabecera?.estructura)}</td><td>V${i.version_actual}</td></tr>`).join('')}
        </tbody></table></div>
        <div class="filtros" style="margin-top:12px"><select id="contacto" aria-label="Destinatario">${personas.contactos.map((c) => `<option value="${c.id}">${esc(c.nombre)} — ${esc(c.empresa)}</option>`).join('')}</select>
        <button class="btn pri" id="btn-paquete">Enviar paquete</button></div>` : '<p class="vacio">No hay protocolos listos. Aparecen aquí cuando Elaborado y Revisado/Aprobado ya firmaron.</p>'}
    </div>
    <div class="card" style="margin-top:16px"><h2>Enviados</h2>
      ${paquetes.length ? `<ul class="lista-simple">${paquetes.map((p) => {
        const n = p.items.length; const ok = p.items.filter((x) => x.decision === 'aceptado').length; const no = p.items.filter((x) => x.decision === 'rechazado').length;
        return `<li><strong>${esc(p.codigo)}</strong> · ${n} protocolo(s) · <span class="chip aprobado">${ok} aceptados</span> <span class="chip observado">${no} rechazados</span> <span class="muted">${fecha(p.created_at)}</span>
          · <a href="${api.urlHojaCargo(p.id)}" target="_blank" rel="noopener">Hoja de cargo${p.firmado_recepcion ? ' (firmada)' : ''}</a>
          ${p.enlace_demo ? ` · <a href="${p.enlace_demo}" target="_blank">Abrir como tercero (demo)</a>` : ''}</li>`;
      }).join('')}</ul>` : '<p class="muted">Ninguno aún.</p>'}
    </div>`;
  $('#todos')?.addEventListener('change', (e) => main.querySelectorAll('.sel').forEach((c) => { c.checked = e.target.checked; }));
  $('#btn-paquete')?.addEventListener('click', () => intentar(async () => {
    const ids = [...main.querySelectorAll('.sel:checked')].map((c) => c.value);
    if (!ids.length) throw new Error('Seleccione al menos un protocolo');
    const r = await api.crearPaquete(ids, $('#contacto').value);
    toast(`Paquete ${r.codigo} enviado a ${r.correo}`);
    vistaPaquetes();
  }));
}

// ---------- Correos simulados (sin servicio de correo configurado) ------------------------
async function vistaCorreos() {
  const lista = await api.correos();
  main.innerHTML = `<h1>Correos (simulados)</h1>
    <p class="muted">Sin servicio de correo configurado, los avisos quedan aquí en lugar de enviarse. Con la clave de Resend en <code>.env</code> se envían de verdad.</p>
    ${lista.length ? lista.map((c) => `<div class="card" style="margin-top:12px">
      <div><strong>${esc(c.asunto)}</strong></div>
      <div class="muted">Para: ${esc(c.para)} · ${fecha(c.created_at)}${c.error ? ` · <span class="chip observado">No enviado: ${esc(c.error)}</span>` : ''}</div>
      <div class="correo-cuerpo">${c.cuerpo}</div></div>`).join('')
    : '<p class="vacio">Aún no hay correos.</p>'}`;
  // El enlace de revisión es para el tercero: se abre en otra pestaña
  main.querySelectorAll('.correo-cuerpo a').forEach((a) => { a.target = '_blank'; a.rel = 'noopener'; });
}

// ---------- Router ---------------------------------------------------------
async function ruteo() {
  pintarTop();
  const [, r, id] = location.hash.split('/');
  main.innerHTML = '<p class="vacio">Cargando…</p>';
  try {
    if (r === 'nuevo') return await vistaNuevo();
    if (r === 'p' && id) return await vistaProtocolo(id);
    if (r === 'paquetes') return await vistaPaquetes();
    if (r === 'correos') return await vistaCorreos();
    return await vistaBandeja();
  } catch (e) {
    console.error(e);
    main.innerHTML = `<p class="vacio">${esc(e.message)}</p>`;
    return undefined;
  }
}

(async () => {
  try { api = await conectar(); } catch (e) { main.innerHTML = `<p class="vacio">${esc(e.message)}</p>`; return; }
  if (api.demo) $('#demo-banner').hidden = false;
  yo = await api.usuario();
  [personas, maestros] = await Promise.all([api.personas(), api.maestros()]);
  window.addEventListener('hashchange', ruteo);
  ruteo();
})();
