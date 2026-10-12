// =====================================================================
// Motor de protocolos: un solo componente para cualquier protocolo_tipo.
// - htmlProtocolo(): HTML en string (sin DOM) para la pantalla y el portal externo.
// - montarFormulario(): engancha la edición sobre ese HTML.
// - validar(): reglas comunes (el servidor las repite en servidor/reglas.py).
// El PDF lo dibuja el servidor en Python (servidor/pdf.py) con la misma definición.
//
// maestros = { proyecto, entregables: [{codigo, nombre, estructuras:[{codigo,nombre}], planos:[...]}], listas: {clave: [...]} }
// =====================================================================

export const OPCIONES = {
  SI_NO_NA: [['SI', 'SI'], ['NO', 'NO'], ['NA', 'N.A.']],
  C_NC_NA:  [['C', 'C'], ['NC', 'NC'], ['NA', 'NA'], ['-', '(-)']],
};
const NEGATIVAS = new Set(['NO', 'NC']);
export const LEYENDA_C_NC = '(-) No se requiere inspección · (C) Conforme · (NC) No conforme · (NA) No aplica';

export const CABECERA = [
  { id: 'proyecto', label: 'Nombre del proyecto', soloLectura: true },
  { id: 'cliente', label: 'Cliente', soloLectura: true },
  { id: 'entregable', label: 'Entregable / Área', tipo: 'entregable', requerido: true },
  { id: 'estructura', label: 'Estructura / Frente', tipo: 'estructura', requerido: true },
  { id: 'correlativo', label: 'N° correlativo', soloLectura: true },
  { id: 'fecha', label: 'Fecha', tipo: 'date', requerido: true },
  { id: 'elemento', label: 'Elemento' },
  { id: 'plano_ref', label: 'Plano ref.', tipo: 'planos' },
];

export const ROLES = [
  ['elaborado', 'Elaborado por'],
  ['revisado_aprobado', 'Revisado / Aprobado por'],
  ['aceptado', 'Aceptado por'],
];

// ---------- Utilidades ---------------------------------------------------
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const get = (o, path) => path.split('.').reduce((a, k) => (a == null ? a : a[k]), o);
function set(o, path, v) {
  const ks = path.split('.');
  let a = o;
  ks.slice(0, -1).forEach((k, i) => { if (a[k] == null || typeof a[k] !== 'object') a[k] = /^\d+$/.test(ks[i + 1]) ? [] : {}; a = a[k]; });
  a[ks.at(-1)] = v;
}
const fechaHora = (v) => (v ? v.replace(/^(\d{4})-(\d{2})-(\d{2})T?(.*)$/, (_, y, m, d, h) => `${d}/${m}/${y}${h ? ` ${h.slice(0, 5)}` : ''}`) : '');
const entregableDe = (m, codigo) => (m?.entregables || []).find((e) => e.codigo === codigo);

export function valorVacio(proyecto = {}) {
  const cabecera = { proyecto: proyecto.nombre ?? '', cliente: proyecto.cliente ?? '', entregable: '', estructura: '', plano_ref: [] };
  cabecera.fecha = new Date().toISOString().slice(0, 10);
  return { cabecera, respuestas: { checklist: {}, campos: {}, tablas: {}, adjuntos: {}, descripcion: '', observaciones: '' }, conforme: null };
}

// ---------- Controles (editable o solo lectura) ------------------------------------
// tipo: text | number | date | time | datetime | textarea | select (opciones) | lista (sugerencias + texto libre)
function input(path, val, { tipo = 'text', ro, opciones, lista, ph = '', cls = '' } = {}) {
  const v = val ?? '';
  if (ro) {
    const txt = ['date', 'datetime'].includes(tipo) ? fechaHora(v) : v;
    return `<span class="ro ${cls}">${esc(txt) || '&nbsp;'}</span>`;
  }
  if (tipo === 'textarea') return `<textarea data-k="${path}" rows="3" class="${cls}" placeholder="${esc(ph)}">${esc(v)}</textarea>`;
  if (tipo === 'select') {
    return `<select data-k="${path}" class="${cls}"><option value=""></option>${(opciones || []).map((o) => `<option${o === v ? ' selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
  }
  if (tipo === 'lista') return `<input type="text" data-k="${path}" value="${esc(v)}" class="${cls}" list="dl-${esc(lista)}" placeholder="Elija o escriba">`;
  const t = { number: 'number', date: 'date', time: 'time', datetime: 'datetime-local' }[tipo] || 'text';
  return `<input type="${t}" data-k="${path}" value="${esc(v)}" class="${cls}" placeholder="${esc(ph)}"${t === 'number' ? ' step="any" inputmode="decimal"' : ''}>`;
}

function radios(path, val, opciones, ro, etiquetas) {
  return `<span class="radios" role="radiogroup">${opciones.map((o, i) => {
    const lab = etiquetas ? etiquetas[i] : o;
    const on = val === o;
    if (ro) return `<span class="chk${on ? ' on' : ''}">${on ? '☒' : '☐'} ${esc(lab)}</span>`;
    return `<label class="chk${on ? ' on' : ''}"><input type="radio" name="${path}" data-k="${path}" value="${esc(o)}"${on ? ' checked' : ''}> ${esc(lab)}</label>`;
  }).join('')}</span>`;
}

// Entregable → Estructura → Planos (desplegables en cascada desde los maestros)
function controlCabecera(c, cab, ro, m) {
  const path = `cabecera.${c.id}`;
  const ent = entregableDe(m, cab.entregable);
  if (c.tipo === 'entregable') {
    if (ro) return input(path, ent?.nombre || cab.entregable, { ro });
    return `<select data-k="${path}" data-cascada="1"><option value="">Seleccione…</option>${(m?.entregables || []).map((e) =>
      `<option value="${esc(e.codigo)}"${e.codigo === cab.entregable ? ' selected' : ''}>${esc(e.nombre)} (${esc(e.codigo)})</option>`).join('')}</select>`;
  }
  if (c.tipo === 'estructura') {
    if (ro) return input(path, cab.estructura, { ro });
    if (!ent) return '<span class="muted-ctl">Elija primero el entregable</span>';
    return input(path, cab.estructura, { tipo: 'select', opciones: ent.estructuras.map((e) => e.nombre) });
  }
  if (c.tipo === 'planos') {
    const sel = Array.isArray(cab.plano_ref) ? cab.plano_ref : [];
    if (ro) return input(path, [...sel, cab.plano_otro].filter(Boolean).join(', '), { ro });
    if (!ent) return '<span class="muted-ctl">Elija primero el entregable</span>';
    const marcas = ent.planos.length
      ? `<div class="planos">${ent.planos.map((p) => `<label class="plano${sel.includes(p) ? ' on' : ''}"><input type="checkbox" data-multi="${path}" value="${esc(p)}"${sel.includes(p) ? ' checked' : ''}> ${esc(p)}</label>`).join('')}</div>`
      : '<span class="muted-ctl">Aún no hay planos cargados para este entregable</span>';
    return `${marcas}${input('cabecera.plano_otro', cab.plano_otro, { ph: 'Otro plano (escribir)' })}`;
  }
  return input(path, cab[c.id], { tipo: c.tipo, ro: ro || c.soloLectura });
}

// ---------- Secciones ------------------------------------------------------
function htmlChecklist(sec, r, ro, m) {
  const ops = OPCIONES[sec.opciones];
  const head = `<tr><th class="n">Ítem</th><th>Descripción</th>${ops.map(([, l]) => `<th class="op">${l}</th>`).join('')}<th class="obs">Observaciones</th></tr>`;
  let n = 0;
  const filas = sec.grupos.map((g) => {
    const tg = g.titulo ? `<tr class="grupo"><td colspan="${ops.length + 3}">${esc(g.titulo)}</td></tr>` : '';
    return tg + g.items.map((it) => {
      const base = `respuestas.checklist.${it.id}`;
      const a = get(r, `checklist.${it.id}`) || {};
      const optsExtra = { tipo: it.extra?.tipo, lista: it.extra?.lista, opciones: m?.listas?.[it.extra?.lista], ro };
      const extra = it.extra ? `<div class="extra"><small>${esc(it.extra.label)}:</small> ${input(`${base}.extra`, a.extra, optsExtra)}</div>` : '';
      const ayuda = it.ayuda ? `<div class="ayuda">${esc(it.ayuda)}</div>` : '';
      if (it.solo_extra) {
        return `<tr data-item="${it.id}"><td class="n"></td><td>${esc(it.texto)}${ayuda}</td><td colspan="${ops.length + 1}">${input(`${base}.extra`, a.extra, optsExtra)}</td></tr>`;
      }
      n += 1;
      const celdas = ops.map(([v, l]) => {
        const on = a.r === v;
        return ro
          ? `<td class="op${on ? ' on' : ''}" data-op="${l}">${on ? '✔' : ''}</td>`
          : `<td class="op" data-op="${l}"><label class="op-btn${on ? ' on' : ''}${NEGATIVAS.has(v) ? ' neg' : ''}" title="${l}"><input type="radio" name="${base}.r" data-k="${base}.r" value="${v}"${on ? ' checked' : ''}><span>${l}</span></label></td>`;
      }).join('');
      return `<tr data-item="${it.id}"><td class="n">${n}</td><td>${esc(it.texto)}${ayuda}${extra}</td>${celdas}<td class="obs">${input(`${base}.obs`, a.obs, { ro, ph: 'Observación' })}</td></tr>`;
    }).join('');
  }).join('');
  const ley = sec.opciones === 'C_NC_NA' ? `<p class="leyenda">${LEYENDA_C_NC}</p>` : '';
  return `<section class="sec"><h3>${esc(sec.titulo)}</h3>${ley}<div class="tabla-wrap"><table class="checklist">${head}${filas}</table></div></section>`;
}

function htmlCampos(sec, r, ro, m) {
  const campos = sec.campos.map((c) => {
    const path = `respuestas.campos.${c.id}`;
    const v = get(r, `campos.${c.id}`);
    const ctrl = c.tipo === 'radio' ? radios(path, v, c.opciones, ro)
      : input(path, v, { tipo: c.tipo, ro, lista: c.lista, opciones: c.opciones || m?.listas?.[c.lista] });
    const ancho = c.tipo === 'radio' || c.tipo === 'textarea' ? ' full' : '';
    return `<div class="campo${ancho}" data-campo="${c.id}"><label>${esc(c.label)}${c.requerido ? ' *' : ''}</label><div class="ctl">${ctrl}${c.unidad ? `<span class="unidad">${esc(c.unidad)}</span>` : ''}</div></div>`;
  }).join('');
  return `<section class="sec"><h3>${esc(sec.titulo)}</h3><div class="campos">${campos}</div></section>`;
}

function htmlTabla(sec, r, ro) {
  const filas = get(r, `tablas.${sec.id}`) || [];
  const nFilas = sec.filas_fijas ? sec.filas_fijas.length : Math.max(filas.length, sec.filas_min || 1);
  const head = `<tr>${sec.filas_fijas ? '<th></th>' : ''}${sec.columnas.map((c) => `<th>${esc(c.label)}</th>`).join('')}${!ro && !sec.filas_fijas ? '<th class="acc"></th>' : ''}</tr>`;
  let body = '';
  for (let i = 0; i < nFilas; i += 1) {
    body += `<tr>${sec.filas_fijas ? `<th>${esc(sec.filas_fijas[i])}</th>` : ''}${sec.columnas.map((c) =>
      `<td>${input(`respuestas.tablas.${sec.id}.${i}.${c.id}`, filas[i]?.[c.id], { tipo: c.tipo, opciones: c.opciones, ro })}</td>`).join('')}${
      !ro && !sec.filas_fijas ? `<td class="acc"><button type="button" class="btn-ico" data-quitar-fila="${sec.id}" data-i="${i}" aria-label="Quitar fila">×</button></td>` : ''}</tr>`;
  }
  const add = !ro && !sec.filas_fijas ? `<button type="button" class="btn-sec" data-agregar-fila="${sec.id}">+ Agregar fila</button>` : '';
  const nota = sec.nota ? `<p class="leyenda">${esc(sec.nota)}</p>` : '';
  return `<section class="sec"><h3>${esc(sec.titulo)}</h3><div class="tabla-wrap"><table class="grid">${head}${body}</table></div>${add}${nota}</section>`;
}

// ---------- Firmas -------------------------------------------------------
// firmas: [{rol, empresa_nombre, nombre, cargo, estado, firmado_at, sello_url, canal}]
function htmlFirmas(firmas = []) {
  const porRol = Object.fromEntries(firmas.map((f) => [f.rol, f]));
  return `<section class="firmas">${ROLES.map(([rol, titulo]) => {
    const f = porRol[rol] || {};
    let caja = '';
    if (f.estado === 'firmado' && f.sello_url) caja = `<img src="${esc(f.sello_url)}" alt="Firma y sello">`;
    else if (f.estado === 'firmado') caja = '<span class="firmado">Firmado electrónicamente</span>';
    else if (f.estado === 'rechazado') caja = '<span class="rechazado">Rechazado</span>';
    const fecha = f.firmado_at ? new Date(f.firmado_at).toLocaleDateString('es-PE') : '';
    return `<div class="firma"><div class="rol">${titulo}</div>
      <div class="caja">${caja}</div>
      <dl><dt>Nombre:</dt><dd>${esc(f.nombre)}</dd><dt>Cargo:</dt><dd>${esc(f.cargo)}</dd>
      <dt>Empresa:</dt><dd>${esc(f.empresa_nombre)}</dd><dt>Fecha:</dt><dd>${fecha}</dd></dl></div>`;
  }).join('')}</section>`;
}

// Sugerencias para los campos tipo "lista" (se escriben una vez al final de la hoja)
function htmlDatalists(m) {
  return Object.entries(m?.listas || {}).map(([k, vs]) => `<datalist id="dl-${esc(k)}">${vs.map((v) => `<option value="${esc(v)}">`).join('')}</datalist>`).join('');
}

// ---------- Protocolo completo ---------------------------------------------------
/**
 * @param tipo      { codigo, nombre, revision_formato, schema }
 * @param valor     { cabecera, respuestas, conforme }
 * @param opts      { soloLectura, firmas, version, maestros }
 */
export function htmlProtocolo(tipo, valor, opts = {}) {
  const ro = !!opts.soloLectura;
  const m = opts.maestros;
  const { cabecera = {}, respuestas = {}, conforme = null } = valor;
  const s = tipo.schema;
  const contrato = m?.proyecto?.codigo_contrato ? ` [${m.proyecto.codigo_contrato}]` : '';

  const enc = `<header class="enc">
    <div class="enc-l"><div class="logo"><img src="/img/logo.png" alt="STRACON"></div></div>
    <div class="enc-c"><div>REGISTRO</div><div>ÁREA CONTROL DE CALIDAD</div><h2>${esc(tipo.nombre.toUpperCase())}</h2></div>
    <div class="enc-r"><div><b>${esc(tipo.codigo)}${esc(contrato)}</b></div><div>Revisión formato: ${tipo.revision_formato ?? 0}</div>
      <div>Versión: <b>V${opts.version ?? 0}</b></div></div></header>`;

  const cab = `<section class="cabecera">${CABECERA.map((c) => {
    const ancho = c.tipo === 'planos' ? ' full' : '';
    return `<div class="campo${ancho}" data-campo="cab_${c.id}"><label>${c.label}${c.requerido ? ' *' : ''}</label><div class="ctl">${controlCabecera(c, cabecera, ro, m)}</div></div>`;
  }).join('')}
    <div class="campo full"><label>Descripción del trabajo</label><div class="ctl">${input('respuestas.descripcion', respuestas.descripcion, { tipo: 'textarea', ro })}</div></div>
  </section>`;

  const cuerpo = s.secciones.map((sec) => {
    if (sec.tipo === 'checklist') return htmlChecklist(sec, respuestas, ro, m);
    if (sec.tipo === 'campos') return htmlCampos(sec, respuestas, ro, m);
    if (sec.tipo === 'tabla') return htmlTabla(sec, respuestas, ro);
    return '';
  }).join('');

  const conf = s.conformidad
    ? `<div class="campo full conformidad" data-campo="conforme"><label>${esc(s.conformidad.pregunta)} *</label><div class="ctl">${
      radios('conforme', conforme === true ? 'SI' : conforme === false ? 'NO' : null, ['SI', 'NO'], ro, ['Sí', 'No'])}</div></div>`
    : '';

  const adj = (s.adjuntos || []).map((a) => {
    const base = `respuestas.adjuntos.${a.id}`;
    const v = get(respuestas, `adjuntos.${a.id}`) || {};
    return `<div class="campo full adj" data-campo="adj_${a.id}"><label>¿Se adjunta ${esc(a.label)}?</label><div class="ctl">
      ${radios(`${base}.adjunta`, v.adjunta, ['SI', 'NA'], ro, ['Sí', 'NA'])}
      <span class="num"><small>N°</small> ${input(`${base}.numero`, v.numero, { ro })}</span></div>
      <div class="slot-adjunto" data-slot-adjunto="${a.id}" data-tipo-adjunto="${a.tipo_adjunto}"></div></div>`;
  }).join('');

  const cierre = `<section class="sec cierre">${conf}${adj}
    <div class="campo full"><label>Observaciones</label><div class="ctl">${input('respuestas.observaciones', respuestas.observaciones, { tipo: 'textarea', ro })}</div></div></section>`;

  return `<article class="protocolo${ro ? ' ro' : ''}" data-tipo="${esc(tipo.codigo)}">${enc}${cab}${cuerpo}${cierre}${htmlFirmas(opts.firmas)}${ro ? '' : htmlDatalists(m)}</article>`;
}

// ---------- Validación -----------------------------------------------------
// Devuelve [{ campo, mensaje }]. campo = data-item / data-campo para enfocar el error.
export function validar(tipo, valor) {
  const errs = [];
  const { cabecera = {}, respuestas = {}, conforme } = valor;
  const s = tipo.schema;
  CABECERA.forEach((c) => { if (c.requerido && !String(cabecera[c.id] ?? '').trim()) errs.push({ campo: `cab_${c.id}`, mensaje: `${c.label}: obligatorio` }); });

  s.secciones.forEach((sec) => {
    if (sec.tipo === 'checklist') {
      sec.grupos.forEach((g) => g.items.forEach((it) => {
        if (it.solo_extra) return;
        const a = respuestas.checklist?.[it.id] || {};
        if (!a.r) errs.push({ campo: it.id, mensaje: `"${it.texto.slice(0, 60)}…": sin respuesta` });
        else if (NEGATIVAS.has(a.r) && !String(a.obs ?? '').trim()) errs.push({ campo: it.id, mensaje: `"${it.texto.slice(0, 60)}…": respuesta ${a.r} requiere observación` });
      }));
    }
    if (sec.tipo === 'campos') {
      sec.campos.forEach((c) => {
        if (c.requerido && !String(respuestas.campos?.[c.id] ?? '').trim()) errs.push({ campo: c.id, mensaje: `${c.label}: obligatorio` });
      });
    }
  });

  if (s.conformidad && conforme == null) errs.push({ campo: 'conforme', mensaje: `${s.conformidad.pregunta}: sin respuesta` });
  if (s.conformidad && conforme === false && !String(respuestas.observaciones ?? '').trim()) {
    errs.push({ campo: 'conforme', mensaje: 'Si no es conforme, indique el motivo en Observaciones' });
  }
  (s.adjuntos || []).forEach((a) => {
    const v = respuestas.adjuntos?.[a.id];
    if (!v?.adjunta) errs.push({ campo: `adj_${a.id}`, mensaje: `¿Se adjunta ${a.label}?: sin respuesta` });
  });
  return errs;
}

// ---------- Edición en navegador ------------------------------------------------
/**
 * Monta el protocolo editable en `cont`. Devuelve { valor(), validar(), marcarErrores(errs) }.
 * onCambio(valor) se llama en cada cambio (para autoguardado).
 */
export function montarFormulario(cont, tipo, valorInicial, { onCambio, firmas, version, onRender, maestros } = {}) {
  const valor = structuredClone(valorInicial);
  const pintar = () => {
    cont.innerHTML = htmlProtocolo(tipo, valor, { firmas, version, maestros });
    onRender?.(cont);
  };
  pintar();

  const leer = (el) => {
    const k = el.dataset.k;
    let v = el.type === 'number' ? (el.value === '' ? null : Number(el.value)) : el.value;
    if (k === 'conforme') v = v === 'SI' ? true : v === 'NO' ? false : null;
    set(valor, k, v);
    if (el.dataset.cascada) {
      // Cambió el entregable: se limpian estructura y planos (dependen de él)
      const ent = entregableDe(maestros, v);
      valor.cabecera.estructura = ent?.estructuras.length === 1 ? ent.estructuras[0].nombre : '';
      valor.cabecera.plano_ref = [];
      pintar();
    } else if (el.type === 'radio') {
      cont.querySelectorAll(`input[name="${CSS.escape(el.name)}"]`).forEach((r) => r.closest('label')?.classList.toggle('on', r.checked));
      el.closest('[data-item],[data-campo]')?.classList.remove('err');
    }
    onCambio?.(valor);
  };
  const leerMulti = (el) => {
    const k = el.dataset.multi;
    set(valor, k, [...cont.querySelectorAll(`input[data-multi="${CSS.escape(k)}"]:checked`)].map((c) => c.value));
    el.closest('label')?.classList.toggle('on', el.checked);
    onCambio?.(valor);
  };
  cont.addEventListener('input', (e) => { if (e.target.dataset.k && e.target.type !== 'radio' && e.target.tagName !== 'SELECT') leer(e.target); });
  cont.addEventListener('change', (e) => {
    if (e.target.dataset.multi) leerMulti(e.target);
    else if (e.target.dataset.k) leer(e.target);
  });
  cont.addEventListener('click', (e) => {
    const add = e.target.closest('[data-agregar-fila]');
    const del = e.target.closest('[data-quitar-fila]');
    if (!add && !del) return;
    const id = (add || del).dataset.agregarFila || (add || del).dataset.quitarFila;
    const filas = get(valor, `respuestas.tablas.${id}`) || [];
    if (add) filas.push({});
    else filas.splice(Number(del.dataset.i), 1);
    set(valor, `respuestas.tablas.${id}`, filas);
    pintar();
    onCambio?.(valor);
  });

  return {
    valor: () => structuredClone(valor),
    validar: () => validar(tipo, valor),
    marcarErrores(errs) {
      cont.querySelectorAll('.err').forEach((n) => n.classList.remove('err'));
      errs.forEach((e) => cont.querySelector(`[data-item="${e.campo}"],[data-campo="${e.campo}"]`)?.classList.add('err'));
      cont.querySelector('.err')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    },
  };
}
