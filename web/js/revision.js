// Portal para el tercero (Knight Piésold / Hudbay): sin cuenta ni licencia.
// El enlace lleva un token de un solo paquete. Para registrar sus decisiones, el revisor recibe un código
// en su correo y firma en la misma página (firma dibujada). Todo pasa por el servidor Python (/api/revision/...).
import { conectarExterno } from './datos.js';
import { htmlProtocolo } from './motor.js';

const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const main = $('#app');
const token = new URLSearchParams(location.search).get('t');
let api;

function aviso(msg, err) {
  const t = document.createElement('div');
  t.className = `toast${err ? ' err' : ''}`; t.textContent = msg; t.setAttribute('role', 'status');
  document.body.append(t); setTimeout(() => t.remove(), 6000);
}

// ---------- Recuadro de firma (dedo, lápiz o mouse) ----------------------------------
function montarFirma(cont) {
  cont.innerHTML = `<canvas class="pad" aria-label="Recuadro para firmar"></canvas>
    <div class="pad-pie"><span class="muted">Firme dentro del recuadro</span><button type="button" class="btn" id="pad-borrar">Borrar</button></div>`;
  const cv = cont.querySelector('canvas');
  const ctx = cv.getContext('2d');
  let dibujando = false; let trazos = 0;
  // Ajusta la resolución del lienzo a su tamaño en pantalla (al montar y si cambió antes de empezar a firmar)
  const ajustar = () => {
    const dpr = window.devicePixelRatio || 1;
    if (cv.width === Math.round(cv.clientWidth * dpr) && cv.height === Math.round(cv.clientHeight * dpr)) return;
    cv.width = Math.round(cv.clientWidth * dpr); cv.height = Math.round(cv.clientHeight * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.lineWidth = 2.2; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = '#1d232b';
  };
  ajustar();
  const punto = (e) => { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  cv.addEventListener('pointerdown', (e) => {
    if (!trazos) ajustar();
    dibujando = true;
    try { cv.setPointerCapture(e.pointerId); } catch { /* sin captura: igual se dibuja */ }
    ctx.beginPath(); ctx.moveTo(...punto(e));
  });
  cv.addEventListener('pointermove', (e) => { if (!dibujando) return; ctx.lineTo(...punto(e)); ctx.stroke(); trazos += 1; });
  cv.addEventListener('pointerup', () => { dibujando = false; });
  cont.querySelector('#pad-borrar').onclick = () => { ctx.clearRect(0, 0, cv.width, cv.height); trazos = 0; };
  return { vacia: () => trazos < 5, imagen: () => cv.toDataURL('image/png') };
}

// ---------- Código al correo -----------------------------------------------------------
function htmlCodigo(correo) {
  return `<div class="fila-codigo">
    <button type="button" class="btn" id="btn-codigo">Enviar código a mi correo (${esc(correo)})</button>
    <input id="codigo" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="Código de 6 dígitos" aria-label="Código de 6 dígitos">
  </div>`;
}
function engancharCodigo() {
  $('#btn-codigo').onclick = async (e) => {
    e.target.disabled = true;
    try {
      const r = await api.solicitarCodigo(token);
      aviso(`Le enviamos un código a ${r.correo}. Vence en ${r.minutos} minutos.`);
      $('#codigo').focus();
    } catch (err) { aviso(err.message, true); }
    setTimeout(() => { e.target.disabled = false; }, 30000);   // reenvío posible tras 30 s
  };
}

// ---------- Paquete ---------------------------------------------------------------
async function cargar() {
  let r;
  try { r = await api.revisionObtener(token); } catch (e) { main.innerHTML = `<p class="vacio">${esc(e.message)}</p>`; return; }
  const { paquete, contacto, items, cambios, maestros } = r;
  $('#quien').textContent = `${contacto.nombre} · ${contacto.empresa || ''}`;
  if (paquete.es_cambio) return pintarCambio(paquete, items[0], cambios[0], contacto, maestros);

  const pend = items.filter((i) => i.decision === 'pendiente');
  main.innerHTML = `<h1>Paquete ${esc(paquete.codigo)}</h1>
    <p class="muted">${items.length} protocolo(s). Puede aceptar unos y rechazar otros; todo rechazo requiere motivo.
    Al final firma una sola vez: su firma queda en los protocolos aceptados y en la Hoja de Cargo de recepción.</p>
    ${paquete.hoja_cargo_url ? `<p><a href="${esc(paquete.hoja_cargo_url)}" target="_blank" rel="noopener">Ver Hoja de Cargo de documentos entregados</a>${paquete.recibido_at ? ' (firmada)' : ''}</p>` : ''}
    ${items.map((it) => {
      const cerrado = it.decision !== 'pendiente';
      return `<div class="card rev-item" data-id="${it.instancia_id}">
        <div class="rev-head"><div class="titulo"><strong>${esc(it.inst.correlativo)}</strong> — ${esc(it.tipo.nombre)}
          <div class="muted">${esc(it.numero_registro)} · ${esc(it.inst.cabecera.estructura)} · V${it.version} · Adjuntos: ${it.adjuntos.length}</div></div>
          ${cerrado ? `<span class="chip ${it.decision === 'aceptado' ? 'aprobado' : 'observado'}">${it.decision}</span>` : ''}</div>
        ${it.motivo ? `<div class="muted">Motivo: ${esc(it.motivo)}</div>` : ''}
        ${it.pdf_url ? `<p><a href="${esc(it.pdf_url)}" target="_blank" rel="noopener">Abrir PDF completo (protocolo + adjuntos)</a></p>` : ''}
        <details><summary>Ver protocolo</summary>${htmlProtocolo(it.tipo, it.inst, { soloLectura: true, firmas: it.firmas, version: it.version, maestros })}</details>
        ${cerrado ? '' : `<div class="rev-decision" role="radiogroup" aria-label="Decisión">
          <label class="chk"><input type="radio" name="d-${it.instancia_id}" value="aceptado"> Aceptar</label>
          <label class="chk"><input type="radio" name="d-${it.instancia_id}" value="rechazado"> Rechazar</label>
          <textarea placeholder="Motivo (obligatorio si rechaza)" aria-label="Motivo"></textarea></div>`}
      </div>`;
    }).join('')}
    ${pend.length ? `<div class="card firma-externa"><h2>Firmar y enviar</h2>
        <div id="pad"></div>
        ${htmlCodigo(contacto.correo)}
        <div class="barra"><span class="guardado"></span><button class="btn pri" id="enviar">Firmar y enviar decisiones</button></div>
      </div>` : '<p class="vacio">Paquete cerrado. Gracias.</p>'}`;

  main.querySelectorAll('.rev-decision input').forEach((r2) => r2.addEventListener('change', () => {
    r2.closest('.rev-decision').querySelectorAll('label').forEach((l) => l.classList.toggle('on', l.querySelector('input').checked));
  }));
  if (!pend.length) return;
  const pad = montarFirma($('#pad'));
  engancharCodigo();
  $('#enviar').addEventListener('click', async (e) => {
    const decisiones = [...main.querySelectorAll('.rev-item')].map((c) => {
      const sel = c.querySelector('.rev-decision input:checked');
      return sel ? { instancia_id: c.dataset.id, decision: sel.value, motivo: c.querySelector('textarea').value.trim() } : null;
    }).filter(Boolean);
    if (!decisiones.length) return aviso('Marque Aceptar o Rechazar en al menos un protocolo', true);
    if (decisiones.some((d) => d.decision === 'rechazado' && !d.motivo)) return aviso('Todo rechazo requiere motivo', true);
    if (pad.vacia()) return aviso('Dibuje su firma en el recuadro', true);
    if (!/^\d{6}$/.test($('#codigo').value.trim())) return aviso('Ingrese el código de 6 dígitos que le llegó al correo', true);
    e.target.disabled = true;
    try {
      await api.revisionDecidir(token, decisiones, $('#codigo').value.trim(), pad.imagen());
      aviso('Decisiones firmadas y registradas');
      cargar();
    } catch (err) { aviso(err.message, true); e.target.disabled = false; }
    return undefined;
  });
}

function pintarCambio(paquete, it, cambio, contacto, maestros) {
  const cerrado = it.decision !== 'pendiente';
  main.innerHTML = `<h1>Solicitud de modificación</h1>
    <div class="card"><p><strong>${esc(it.inst.correlativo)}</strong> — ${esc(it.tipo.nombre)} (aprobado en V${it.version})</p>
    <p>Solicitado por <strong>${esc(cambio?.solicitado_por)}</strong>. Motivo: “${esc(cambio?.motivo)}”</p>
    ${cambio?.descripcion ? `<p>Cambios previstos: ${esc(cambio.descripcion)}</p>` : ''}
    <p class="muted">Si aprueba (y también la Jefatura de Calidad de Stracon), se abrirá la versión V${it.version + 1}; la versión aprobada actual se conserva.</p>
    <details><summary>Ver versión vigente</summary>${htmlProtocolo(it.tipo, it.inst, { soloLectura: true, firmas: it.firmas, version: it.version, maestros })}</details>
    ${cerrado ? `<p><span class="chip ${it.decision === 'aceptado' ? 'aprobado' : 'observado'}">${it.decision}</span></p>` : `
    <div class="rev-decision"><textarea id="mot" placeholder="Comentario (obligatorio si rechaza)" aria-label="Comentario"></textarea></div>
    ${htmlCodigo(contacto.correo)}
    <div class="barra"><span class="guardado"></span><button class="btn peligro" id="no">Rechazar</button><button class="btn pri" id="si">Aprobar modificación</button></div>`}</div>`;
  if (cerrado) return;
  engancharCodigo();
  const decidir = async (d) => {
    if (!/^\d{6}$/.test($('#codigo').value.trim())) return aviso('Ingrese el código de 6 dígitos que le llegó al correo', true);
    try { await api.decidirCambioExterno(token, d, $('#mot').value.trim(), $('#codigo').value.trim()); aviso('Respuesta registrada'); cargar(); } catch (e) { aviso(e.message, true); }
    return undefined;
  };
  $('#si').addEventListener('click', () => decidir('aceptado'));
  $('#no').addEventListener('click', () => decidir('rechazado'));
}

(async () => {
  if (!token) { main.innerHTML = '<p class="vacio">Enlace incompleto.</p>'; return; }
  api = conectarExterno();
  cargar();
})();
