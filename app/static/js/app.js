/* PokéVision Pi — lógica de interfaz. Vanilla JS, sin dependencias. */
'use strict';

const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));
const fmt = (v, c) => v == null ? '—' : (c || '€') + Number(v).toFixed(Number(v) < 10 ? 2 : 2);
let LAST = null, STREAM = null, BUSY = false, AUTO = null;

/* ------------------------------------------------------------------ toast */
let toastT;
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg; t.classList.add('on');
  clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('on'), 2600);
}

/* ------------------------------------------------------------------ tabs */
function moveGlider() {
  const on = $('#tabs button.on'), g = $('#tabs .glider');
  g.style.width = on.offsetWidth + 'px';
  g.style.transform = `translateX(${on.offsetLeft - 6}px)`;
}
function show(id) {
  const go = () => {
    $$('section.view').forEach(s => s.classList.toggle('on', s.id === id));
    $$('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.v === id));
    moveGlider();
    if (id === 'v-col') loadCollection();
    if (id === 'v-models') loadMetrics();
  };
  if (document.startViewTransition && !document.body.classList.contains('calm')) {
    document.startViewTransition(go);
  } else { go(); }
}
$('#tabs').addEventListener('click', e => {
  const b = e.target.closest('button[data-v]'); if (b) show(b.dataset.v);
});
addEventListener('resize', moveGlider);

/* ------------------------------------------------------- movimiento reducido */
if (localStorage.getItem('calm') === '1') document.body.classList.add('calm');
$('#calm').addEventListener('click', () => {
  const on = document.body.classList.toggle('calm');
  localStorage.setItem('calm', on ? '1' : '0');
  toast(on ? 'Movimiento reducido' : 'Animaciones activas');
});

/* ------------------------------------------------- polish: luz y fisica
   Spotlight: cada tarjeta enciende su borde donde pasa el puntero.
   Ripple: los botones sueltan una gota de tinta al pulsarse.
   Ambos son baratos: solo escriben CSS custom props. */
document.addEventListener('pointermove', (e) => {
  const card = e.target.closest?.('.card');
  if (!card) return;
  const r = card.getBoundingClientRect();
  card.style.setProperty('--mx', (e.clientX - r.left) + 'px');
  card.style.setProperty('--my', (e.clientY - r.top) + 'px');
}, { passive: true });

document.addEventListener('pointerdown', (e) => {
  const b = e.target.closest?.('.btn');
  if (!b) return;
  const r = b.getBoundingClientRect();
  const ink = document.createElement('span');
  ink.className = 'ink';
  const s = Math.max(r.width, r.height) * 1.3;
  ink.style.cssText = `width:${s}px;height:${s}px;left:${e.clientX - r.left - s/2}px;top:${e.clientY - r.top - s/2}px`;
  b.appendChild(ink);
  setTimeout(() => ink.remove(), 650);
}, { passive: true });

addEventListener('scroll', () => {
  document.body.classList.toggle('scrolled', scrollY > 24);
}, { passive: true });

$('#tour-btn').addEventListener('click', playTour);
loadExamples();

$('#qr-link').addEventListener('click', () => {
  window.open('/qr', '_blank');
  toast('Abre esa URL en el teléfono fijo');
});

/* -------------------------------------------------------------------- tema */
const themeIcon = () => document.documentElement.dataset.theme === 'dark' ? '☾' : '☀︎';
$('#theme').textContent = themeIcon();
$('#theme').addEventListener('click', () => {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  localStorage.setItem('theme', next);
  $('#theme').textContent = themeIcon();
  document.querySelector('meta[name=theme-color]').content =
    next === 'dark' ? '#000244' : '#eef1fa';
});

/* ------------------------------------------- fuente de video: telefono/adb
   La camara real vive en la Pi (scripts/adb_camera.py escribe /tmp/frame.jpg).
   Si existe ese stream, el visor lo consume; si no, cae a getUserMedia local. */
async function usarFramePi() {
  try {
    const r = await fetch('/api/frame', {cache: 'no-store'});
    if (!r.ok) return false;
    const b = await r.blob();
    if (b.size < 1024) return false;
    return URL.createObjectURL(b);
  } catch { return false; }
}

let PI_FRAME_TIMER = null;
async function iniciarCamara() {
  const v = $('#video');
  const url = await usarFramePi();
  if (url) {
    // refresco del frame: mas rapido en demo (2 fps) y suave en produccion
    let busy = false;
    PI_FRAME_TIMER = setInterval(async () => {
      if (busy || !STREAM.on) return; busy = true;
      try {
        const u2 = await usarFramePi();
        if (u2) { v.src = u2; URL.revokeObjectURL(url); }
      } catch {} busy = false;
    }, 500);
    v.src = url; v.classList.add('on');
    toast('Cámara de la Pi conectada');
    return;
  }
  // fallback: camara del propio laptop
  try {
    const s = await navigator.mediaDevices.getUserMedia({video: {facingMode: 'environment'}});
    v.srcObject = s; v.classList.add('on');
  } catch (e) { toast('Sin cámara: usa el botón de imagen'); }
}

/* ------------------------------------------------------------------ cámara */
async function startCam() {
  const v = $('#video');
  // primero la camara de la Pi (telefono por ADB); getUserMedia solo como fallback
  try {
    const ok = await usarFramePi();
    if (ok) {
      STREAM = { on: true, pi: true };
      v.src = ok; v.classList.add('on');
      $('#btn-cam').textContent = 'Apagar cámara';
      toast('Cámara Pi (teléfono) conectada');
      if (!PI_FRAME_TIMER) {
        PI_FRAME_TIMER = setInterval(async () => {
          if (!STREAM || !STREAM.pi || !STREAM.on) return;
          const u2 = await usarFramePi();
          if (u2) { URL.revokeObjectURL(v.src); v.src = u2; }
        }, 500);
      }
      return;
    }
  } catch (e) { /* seguimos con getUserMedia */ }
  try {
    STREAM = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 960 } },
      audio: false
    });
    const v = $('#video');
    v.srcObject = STREAM; await v.play();
    $('#vph').hidden = true;
    $('#btn-cam').textContent = 'Apagar cámara';
    toast('Cámara activa');
  } catch (e) {
    $('#vph').innerHTML = 'No se pudo abrir la cámara.<br><small>' + e.message +
      '</small><br>Usa <b>Subir imagen</b>.';
    toast('Sin acceso a la cámara');
  }
}
function stopCam() {
  if (PI_FRAME_TIMER) { clearInterval(PI_FRAME_TIMER); PI_FRAME_TIMER = null; }
  if (STREAM) { STREAM.getTracks().forEach(t => t.stop()); STREAM = null; }
  $('#vph').hidden = false;
  $('#btn-cam').textContent = 'Activar cámara';
}
$('#btn-cam').addEventListener('click', () => STREAM ? stopCam() : startCam());
$('#btn-file').addEventListener('click', () => $('#file').click());
$('#file').addEventListener('change', e => {
  const f = e.target.files[0]; if (f) sendBlob(f);
});

/* recorta el marco guía (proporción de carta) antes de enviar */
function grabFrame() {
  const v = $('#video');
  if (!v.videoWidth) return null;
  const vw = v.videoWidth, vh = v.videoHeight;
  const boxH = vh * 0.82, boxW = boxH * 0.716;
  const sx = (vw - boxW) / 2, sy = (vh - boxH) / 2;
  const c = document.createElement('canvas');
  c.width = 480; c.height = Math.round(480 / 0.716);
  c.getContext('2d').drawImage(v, sx, sy, boxW, boxH, 0, 0, c.width, c.height);
  return new Promise(r => c.toBlob(r, 'image/jpeg', 0.9));
}

/* ------------------------------------------------------------------ escaneo */
async function scan() {
  if (BUSY) return;
  if (!STREAM) { toast('Activa la cámara o sube una imagen'); return; }
  const blob = await grabFrame();
  if (!blob) { toast('La cámara aún no da imagen'); return; }
  sendBlob(blob);
}
async function sendBlob(blob) {
  if (BUSY) return;
  BUSY = true;
  aiLiveReset();
  $('#viewer').classList.add('scanning');
  $('#result').innerHTML = skeleton();
  const fd = new FormData();
  fd.append('file', blob, 'scan.jpg');
  try {
    const r = await fetch('/api/scan', { method: 'POST', body: fd });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    LAST = data;
    render(data);
  } catch (e) {
    $('#result').innerHTML = `<div class="empty">Error en el análisis.<br><small>${e.message}</small></div>`;
  } finally {
    BUSY = false;
    $('#viewer').classList.remove('scanning');
  }
}
$('#btn-scan').addEventListener('click', scan);
$('#auto').addEventListener('change', e => {
  clearInterval(AUTO);
  if (e.target.checked) { AUTO = setInterval(scan, 2500); toast('Modo continuo activo'); }
});

const skeleton = () => `
  <div class="holo-wrap"><div class="skel" style="width:min(252px,62vw);aspect-ratio:.716;border-radius:14px"></div></div>
  <div class="skel" style="height:26px;margin:10px auto;width:62%"></div>
  <div class="skel" style="height:62px;margin-top:16px"></div>`;

/* ------------------------------------------------------------------ render */
function tween(el, to, prefix, dec) {
  el.classList?.remove('flash');
  void el.offsetWidth;                    // reinicia la animación CSS
  el.classList?.add('flash');
  const dur = 900, t0 = performance.now(), from = 0;
  if (document.body.classList.contains('calm')) {
    el.textContent = (prefix || '') + to.toFixed(dec); return;
  }
  (function step(now) {
    const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
    el.textContent = (prefix || '') + (from + (to - from) * e).toFixed(dec);
    if (p < 1) requestAnimationFrame(step);
  })(t0);
}

function render(d) {
  if (!d.ok || !d.card) {
    $('#result').innerHTML = '<div class="empty">No se reconoció ninguna carta. Mejora la luz y encuadra mejor.</div>';
    return;
  }
  const c = d.card, p = d.price || {}, f = d.forecast, cond = d.condition || {};
  const dirClass = !f ? 'flat' : (f.change_pct_180d > 2 ? 'up' : f.change_pct_180d < -2 ? 'down' : 'flat');
  const arrow = dirClass === 'up' ? '▲' : dirClass === 'down' ? '▼' : '●';

  $('#result').innerHTML = `
    ${dialogShell(d)}
    <div class="stagger after-dialog">
      <div class="holo-wrap">
        <div class="holo enter" id="holo">
          <img src="${c.image || ''}" alt="${c.name || ''}" loading="lazy">
          <div class="sheen"></div>
          <div class="back" aria-hidden="true"></div>
        </div>
      </div>
      <div class="identity">
        <h2>${c.name || '—'}</h2>
        <div class="chips">
          <span class="chip">${c.set_name || '—'}</span>
          <span class="chip">#${c.local_id || '?'}</span>
          ${c.rarity && c.rarity !== 'None' ? `<span class="chip gold">${c.rarity}</span>` : ''}
          <span class="chip lime">${Math.round((c.match_score || 0) * 100)}% coincidencia</span>
          ${d.demo ? '<span class="chip">modo demo</span>' : ''}
        </div>
      </div>

      <div style="margin-top:18px">
        <span class="label">Valor actual</span>
        <div class="price-hero">
          <div class="price-main" id="pmain">€0.00</div>
          <div class="price-alt">${p.usd ? '$' + p.usd + ' · ' : ''}${p.cop ? p.cop.toLocaleString('es-CO') + ' COP' : ''}</div>
          <div class="spacer"></div>
          ${f ? `<span class="delta ${dirClass}">${arrow} ${f.change_pct_180d > 0 ? '+' : ''}${f.change_pct_180d}% a 180 días</span>` : ''}
        </div>
        <div class="price-grid">
          <div class="stat"><span class="label">Mínimo</span><b>${fmt(p.low)}</b></div>
          <div class="stat"><span class="label">Tendencia</span><b>${fmt(p.trend)}</b></div>
          <div class="stat"><span class="label">Media 7d</span><b>${fmt(p.avg7)}</b></div>
          <div class="stat"><span class="label">Media 30d</span><b>${fmt(p.avg30)}</b></div>
        </div>
      </div>

      <div style="margin-top:20px">
        <span class="label">Autenticidad y estado</span>
        <div class="verdict" style="margin-top:10px">
          <div class="ring">
            <svg width="76" height="76">
              <circle cx="38" cy="38" r="32" fill="none" stroke="rgba(255,255,255,.12)" stroke-width="7"/>
              <circle id="ringc" cx="38" cy="38" r="32" fill="none" stroke="currentColor" stroke-width="7"
                      stroke-linecap="round" stroke-dasharray="201" stroke-dashoffset="201"
                      class="v-${cond.verdict}"/>
            </svg>
            <span>${Math.round((cond.confidence || 0) * 100)}%</span>
          </div>
          <div class="txt">
            <h3 class="v-${cond.verdict}">${(cond.verdict || '—').toUpperCase()}</h3>
            <small class="dim">${cond.modelo || ''}</small>
          </div>
        </div>
        <div class="bars">
          ${Object.entries(cond.signals || {}).map(([k, v]) => `
            <div class="bar"><span class="dim">${k}</span>
              <span class="track"><span class="fill" data-v="${v}"></span></span>
              <b class="mono">${Math.round(v * 100)}</b></div>`).join('')}
        </div>
        <ul class="notes">${(cond.notes || []).map(n => `<li>${n}</li>`).join('')}</ul>
      </div>

      ${gradeBlock(d.grade, p.eur)}

      <div class="controls" style="margin-top:18px">
        <button class="btn primary" id="btn-save">＋ Guardar en colección</button>
        <button class="btn" id="btn-market">Ver mercado</button>
        <span class="pill"><span class="dot"></span>${d.ms} ms</span>
      </div>
    </div>`;

  aiLive(d);
  makeFlippable();
  speak(d);
  tween($('#pmain'), p.eur || 0, '€', 2);
  requestAnimationFrame(() => {
    $$('#result .fill').forEach(el => { el.style.transform = `scaleX(${el.dataset.v})`; });
    const ring = $('#ringc');
    if (ring) ring.style.strokeDashoffset = 201 * (1 - (cond.confidence || 0));
  });
  holoTilt($('#holo'));

  $('#btn-save').addEventListener('click', () => addToCollection(c.id, cond.verdict));
  $('#btn-market').addEventListener('click', () => { show('v-market'); openCard(c.id); });

  const alts = d.alternatives || [];
  $('#alts-card').hidden = !alts.length;
  $('#alts').innerHTML = alts.map(a => `
    <button class="alt" data-id="${a.id}">
      <img src="${a.image || ''}" alt="${a.name || ''}" loading="lazy">
      <b>${a.name || '—'}</b><small>${Math.round((a.match_score || 0) * 100)}%</small>
    </button>`).join('');
  $$('#alts .alt').forEach(b => b.addEventListener('click',
    () => { show('v-market'); openCard(b.dataset.id); }));
}

/* --------------------------------------------- IA EN VIVO: el pipeline andando
   Cada paso se enciende cuando la respuesta dice que corrio, con su ms REAL
   medido en la Pi, y el top-3 de coincidencias se dibuja en barras. */
function aiLive(d) {
  const panel = $('#ai-live');
  if (!panel) return;
  const steps = (d.pipeline && d.pipeline.steps) || {};
  const order = ['frame','pre','embed','search','condition','grade','price'];
  panel.classList.add('busy');
  $('#ai-ms').textContent = '—';
  let i = 0;
  const li = (k) => panel.querySelector(`li[data-step="${k}"]`);
  // encendido secuencial: cada etapa tarda lo que tardo de verdad (minimo 90ms)
  order.forEach((k, n) => {
    const el = li(k); if (!el) return;
    setTimeout(() => {
      el.classList.add('run');
      const ms = steps[k];
      if (ms != null) el.querySelector('small').textContent += ` · ${ms} ms`;
    }, i = n * 110);
  });
  setTimeout(() => {
    panel.querySelectorAll('li').forEach(el => el.classList.replace('run', 'done'));
    panel.classList.remove('busy');
    // contador que sube y clava en el numero real (AAA feel, sin layout thrash)
    const total = (d.pipeline && d.pipeline.ms != null ? d.pipeline.ms : d.ms) || 0;
    const t0m = performance.now(), dur = 620;
    const tickMs = (t) => {
      const k = Math.min(1, (t - t0m) / dur), e = 1 - Math.pow(1 - k, 3);
      $('#ai-ms').textContent = Math.round(total * e) + ' ms';
      if (k < 1) requestAnimationFrame(tickMs);
    };
    requestAnimationFrame(tickMs);
    // top-3
    const top = (d.pipeline && d.pipeline.top) || [];
    [1, 2, 3].forEach((n, ix) => {
      const bar = $('#bar-top' + n);
      if (!bar) return;
      const m = top[ix];
      if (m) {
        bar.querySelector('i').style.width = Math.min(100, (m[1] * 100).toFixed(1)) + '%';
        bar.querySelector('em').textContent = `${m[0]} · ${(m[1] * 100).toFixed(1)}%`;
      }
    });
    const note = $('#ai-note');
    if (note) note.textContent = d.ok
      ? `Identificada en ${d.ms} ms con ${(d.condition.confidence * 100) | 0}% de confianza en el estado.`
      : 'Sin coincidencia razonable en el catálogo.';
  }, order.length * 110 + 260);
}

function aiLiveReset() {
  const panel = $('#ai-live');
  if (!panel) return;
  panel.classList.remove('busy');
  panel.querySelectorAll('li').forEach(el => el.classList.remove('run', 'done'));
  [1, 2, 3].forEach(n => { const b = $('#bar-top' + n);
    if (b) { b.querySelector('i').style.width = '0%'; b.querySelector('em').textContent = '—'; } });
  $('#ai-ms').textContent = '—';
}

/* ------------------------------------------- CARTAS EJEMPLO + presentación
   /api/examples trae ids REALES del catalogo: al escanearlas pasa por todo el
   pipeline de verdad (embedder, condicion, PSA, mercado). La presentación las
   pasa una a una con el visor encendido, como si el torneo estuviera andando. */
let EX_CARDS = [], TOUR = null;

async function loadExamples() {
  const d = await fetch('/api/examples').then(r => r.json()).catch(() => null);
  const strip = $('#ex-strip');
  if (!d || !d.cards || !d.cards.length) { strip.textContent = 'sin ejemplos'; return; }
  EX_CARDS = d.cards;
  strip.innerHTML = EX_CARDS.map((c, i) => `
    <button class="ex-card" data-i="${i}" title="${c.name}">
      <img src="${c.image}" alt="${c.name}" loading="lazy">
      <small>${c.name}</small>
    </button>`).join('');
  strip.querySelectorAll('.ex-card').forEach(b =>
    b.addEventListener('click', () => scanExample(+b.dataset.i)));
}

async function scanExample(i) {
  const c = EX_CARDS[i];
  if (!c) return;
  [...document.querySelectorAll('.ex-card')].forEach(el => el.classList.remove('playing'));
  const el = document.querySelector(`.ex-card[data-i="${i}"]`);
  if (el) { el.classList.add('playing'); el.scrollIntoView({block:'nearest',inline:'center',behavior:'smooth'}); }
  // descarga la imagen y la mete por el MISMO camino que la camara
  const b = await fetch(c.image).then(r => r.blob());
  await sendBlob(new File([b], c.id + '.webp', {type: 'image/webp'}));
}

async function playTour() {
  if (TOUR) { stopTour(); return; }
  const btn = $('#tour-btn');
  TOUR = setInterval(() => {
    const i = Math.floor(Math.random() * EX_CARDS.length);
    scanExample(i);
  }, 7000);
  btn.textContent = '■ PARAR';
  btn.classList.add('primary');
  scanExample(0);
}

function stopTour() {
  if (TOUR) clearInterval(TOUR);
  TOUR = null;
  const btn = $('#tour-btn');
  if (btn) { btn.textContent = '▶ PRESENTACIÓN'; btn.classList.remove('primary'); }
}

/* ----------------------------------------------- girar la carta (TCG Pocket)
   Tap en la carta: gira 180° y muestra el reverso oficial; tap otra vez y
   vuelve por donde vino. El giro mantiene el foil vivo en ambas caras. */
function makeFlippable() {
  const w = document.querySelector('.holo-wrap');
  if (!w) return;
  w.style.cursor = 'pointer';
  let _down = null;
  w.addEventListener('pointerdown', e => { _down = [e.clientX, e.clientY]; });
  w.addEventListener('click', (e) => {
    if (_down && (Math.abs(e.clientX - _down[0]) > 6 || Math.abs(e.clientY - _down[1]) > 6)) return;
    const h = w.querySelector('.holo');
    if (!h) return;
    const flipped = h.classList.toggle('flipped');
    h.style.transform = flipped
      ? 'rotateY(180deg)'
      : 'rotateY(0deg)';
    h.style.transition = 'transform .9s var(--ease)';
    toast(flipped ? 'Reverso' : 'Cara', 900);
  });
}
const _mkFlip = makeFlippable;

/* --------------------------------------------- mensaje del entrenador
   El resultado se "cuenta" primero, como en los juegos: un entrenador aparece y
   lo dice escribiendo. Cuando termina, el mensaje se queda fijo y debajo entra la
   ficha con todos los datos. */
const TRAINERS = {
  gem:    { img: 'cynthia',    name: 'Cynthia, Campeona' },
  fake:   { img: 'policeman',  name: 'Agente Mirto' },
  suspect:{ img: 'scientist',  name: 'Científico' },
  damaged:{ img: 'nurse',      name: 'Enfermera Joy' },
  rich:   { img: 'collector',  name: 'Coleccionista' },
  normal: { img: 'oak',        name: 'Profesor Oak' },
  none:   { img: 'psychic',    name: 'Vidente' },
};

function pickTrainer(d) {
  const v = (d.condition || {}).verdict, g = (d.grade || {}).psa, eur = (d.price || {}).eur;
  if (v === 'falsa') return TRAINERS.fake;
  if (v === 'sospechosa') return TRAINERS.suspect;
  if (v === 'danada' || v === 'dañada') return TRAINERS.damaged;
  if (g >= 9.5) return TRAINERS.gem;
  if (eur >= 40) return TRAINERS.rich;
  return TRAINERS.normal;
}

function dialogShell(d) {
  const t = pickTrainer(d);
  return `
    <div class="dialog" id="dialog">
      <div class="who"><img src="/static/img/trainers/${t.img}.png" alt="${t.name}"></div>
      <div class="bubble">
        <span class="who-name">${t.name}</span>
        <p class="say" id="say"></p>
      </div>
      <span class="next" id="dnext" hidden>▼</span>
    </div>`;
}

function buildMessage(d) {
  const c = d.card || {}, p = d.price || {}, f = d.forecast, g = d.grade || {},
        cond = d.condition || {};
  const parts = [];
  parts.push(`¡Es <b>${c.name || 'una carta desconocida'}</b> de ${c.set_name || 'un set que no reconozco'}!`);
  if (p.eur) {
    parts.push(`Ahora mismo se paga a <span class="hl">€${p.eur.toFixed(2)}</span>` +
      (p.cop ? ` (${p.cop.toLocaleString('es-CO')} COP)` : '') + '.');
  }
  if (cond.verdict === 'falsa') {
    parts.push(`Cuidado: la veo <span class="bad">falsa</span> con un ${Math.round(cond.confidence * 100)}% de confianza.`);
  } else if (cond.verdict === 'sospechosa') {
    parts.push(`No me cuadra del todo: la marco como <span class="bad">sospechosa</span>, mírala con lupa.`);
  } else if (cond.verdict === 'danada' || cond.verdict === 'dañada') {
    parts.push(`Está <span class="bad">dañada</span>, se nota el desgaste.`);
  } else if (cond.verdict) {
    parts.push(`La veo <span class="good">auténtica</span> (${Math.round(cond.confidence * 100)}% de confianza).`);
  }
  if (g.psa != null) {
    parts.push(`De calificación le pongo un <span class="hl">PSA ${Number.isInteger(g.psa) ? g.psa : g.psa.toFixed(1)}</span>` +
      (g.limiting_factor ? `, la limitan ${g.limiting_factor === 'centrado' ? 'el centrado' : 'l' + (g.limiting_factor === 'superficie' ? 'a superficie' : 'os ' + g.limiting_factor)}` : '') + '.');
    if (g.worth_grading === true) parts.push(`Graduarla <span class="good">compensa</span>: dejaría unos €${g.net_gain_eur} netos.`);
    else if (g.worth_grading === false) parts.push(`Graduarla <span class="bad">no compensa</span> a este precio.`);
  }
  if (f) {
    const pct = f.change_pct_180d;
    parts.push(pct > 2 ? `Y va <span class="good">al alza</span>: +${pct}% a 180 días.`
      : pct < -2 ? `Ojo, va <span class="bad">a la baja</span>: ${pct}% a 180 días.`
      : `Su precio está <b>plano</b> de aquí a 180 días.`);
  }
  return parts.join(' ');
}

let SAY_TIMER = null;
function speak(d) {
  const el = $('#say'), dlg = $('#dialog'), data = $('#result .after-dialog');
  if (!el) return;
  const html = buildMessage(d);
  const finish = () => {
    clearInterval(SAY_TIMER);
    el.innerHTML = html;
    dlg.classList.add('done');
    $('#dnext').hidden = false;
    data.classList.add('in');          // la ficha entra y el mensaje queda fijo arriba
  };
  if (document.body.classList.contains('calm')) { finish(); return; }

  // escribe el texto respetando las etiquetas HTML (no se parte un <span> por la mitad)
  const tokens = html.match(/<[^>]+>|&[a-z]+;|[\s\S]/g) || [];
  let i = 0, out = '';
  clearInterval(SAY_TIMER);
  el.innerHTML = '<span class="caret"></span>';
  SAY_TIMER = setInterval(() => {
    if (i >= tokens.length) return finish();
    // en cada tic avanza 2 caracteres: legible pero sin hacerse eterno
    for (let k = 0; k < 2 && i < tokens.length; k++) out += tokens[i++];
    el.innerHTML = out + '<span class="caret"></span>';
  }, 18);
  dlg.onclick = finish;               // tocar la caja salta el texto, como en el juego
}

/* ------------------------------------------------- calificación tipo PSA */
function gradeBlock(g, eur) {
  if (!g || g.psa == null) return '';
  const psa = g.psa;
  const tone = psa >= 9.5 ? 'gem' : psa >= 8.5 ? 'high' : psa >= 7 ? 'mid' : 'low';
  const sub = g.subgrades || {};
  const worth = g.worth_grading;
  return `
    <div class="psa" data-tone="${tone}" style="margin-top:20px">
      <div class="psa-head">
        <div class="psa-slab">
          <span class="psa-brand">PSA</span>
          <span class="psa-num">${Number.isInteger(psa) ? psa : psa.toFixed(1)}</span>
        </div>
        <div>
          <span class="label">Calificación estimada</span>
          <h3 class="psa-label">${g.label || ''}</h3>
          <small class="dim">${g.note || ''}</small>
        </div>
      </div>
      <div class="psa-sub">
        ${['centrado', 'esquinas', 'bordes', 'superficie'].map(k => {
          const v = sub[k];
          if (v == null) return '';
          const pct = Math.max(0, Math.min(1, (v - 1) / 9));
          const lim = g.limiting_factor === k;
          return `<div class="sg${lim ? ' lim' : ''}">
            <span class="label">${k}${lim ? ' ·' : ''}</span>
            <b>${Number(v).toFixed(1)}</b>
            <span class="track"><span class="fill" data-v="${pct}"></span></span>
          </div>`;
        }).join('')}
      </div>
      ${g.centering_pct ? `<p class="dim psa-meta">Centrado medido <b>${g.centering_pct}</b>${g.detail ? ' · ' + g.detail : ''}</p>` : ''}
      ${g.value_if_graded ? `
        <div class="psa-value">
          <div class="stat"><span class="label">En bruto</span><b>${fmt(eur)}</b></div>
          <div class="stat"><span class="label">PSA 10</span><b class="lime">${fmt(g.value_if_graded.psa10)}</b></div>
          <div class="stat"><span class="label">PSA 9</span><b>${fmt(g.value_if_graded.psa9)}</b></div>
          <div class="stat"><span class="label">A tu grado</span><b>${fmt(g.value_at_estimate)}</b></div>
        </div>
        <p class="psa-verdict ${worth ? 'yes' : 'no'}">
          ${worth ? '✓ Compensa graduarla' : '✕ No compensa graduarla'}
          <span class="dim">· neto ${g.net_gain_eur > 0 ? '+' : ''}${fmt(g.net_gain_eur)} tras ${fmt(g.grading_cost_eur)} de servicio</span>
        </p>` : ''}
      <small class="dim" style="display:block;margin-top:8px;font-size:.72rem">
        Pre-grading orientativo · ${g.fuente || ''}
      </small>
    </div>`;
}

/* brillo holográfico que sigue al dedo/puntero */
function holoTilt(el) {
  if (!el || document.body.classList.contains('calm')) return;
  const move = (x, y) => {
    const r = el.getBoundingClientRect();
    const px = (x - r.left) / r.width, py = (y - r.top) / r.height;
    el.style.transform = `rotateY(${(px - .5) * 18}deg) rotateX(${-(py - .5) * 18}deg) scale(1.02)`;
    el.style.setProperty('--ha', (215 + (px - .5) * 160) + 'deg');   // foil arcoiris
    el.style.setProperty('--mx', (px * 100) + '%');
    el.style.setProperty('--my', (py * 100) + '%');
    el.style.setProperty('--ang', (px * 360) + 'deg');
  };
  el.addEventListener('pointermove', e => move(e.clientX, e.clientY));
  el.addEventListener('touchmove', e => {
    const t = e.touches[0]; if (t) move(t.clientX, t.clientY);
  }, { passive: true });
  const reset = () => { el.style.transform = ''; };
  el.addEventListener('pointerleave', reset);
  el.addEventListener('touchend', reset);
}

/* ------------------------------------------------------------- colección */
async function addToCollection(id, cond) {
  const r = await fetch('/api/collection', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ card_id: id, qty: 1, condition: cond || 'autentica' })
  });
  const d = await r.json();
  toast('Guardada · colección €' + d.total_eur);
}
async function loadCollection() {
  const d = await (await fetch('/api/collection')).json();
  tween($('#col-total'), d.total_eur || 0, '€', 2);
  $('#col-cop').textContent = d.total_cop ? d.total_cop.toLocaleString('es-CO') + ' COP' : '—';
  const n = (d.items || []).reduce((a, b) => a + (b.qty || 1), 0);
  $('#col-count').textContent = n + (n === 1 ? ' carta' : ' cartas');
  $('#col-list').innerHTML = (d.items || []).length ? d.items.map(i => `
    <div class="row">
      <img src="${i.image}" alt="" loading="lazy">
      <div><b>${i.name}</b><small>${i.set_name || ''} · ${i.condition || ''} · x${i.qty}</small></div>
      <div class="val">${fmt(i.eur)}</div>
    </div>`).join('')
    : '<div class="empty">Colección vacía. Escanea una carta y pulsa «Guardar».</div>';
}

/* ---------------------------------------------------------------- mercado */
let searchT;
$('#q').addEventListener('input', e => {
  clearTimeout(searchT);
  const q = e.target.value.trim();
  if (q.length < 2) { $('#results').innerHTML = ''; return; }
  searchT = setTimeout(async () => {
    const d = await (await fetch('/api/search?q=' + encodeURIComponent(q))).json();
    $('#results').innerHTML = (d.items || []).length ? d.items.map(i => `
      <button class="row" data-id="${i.id}" style="text-align:left;width:100%">
        <img src="${i.image}" alt="" loading="lazy">
        <div><b>${i.name}</b><small>${i.set_name || ''} · ${i.rarity || ''}</small></div>
        <div class="val">${fmt(i.eur)}</div>
      </button>`).join('') : '<div class="empty">Sin resultados.</div>';
    $$('#results .row').forEach(b => b.addEventListener('click', () => openCard(b.dataset.id)));
  }, 260);
});

async function openCard(id) {
  const d = await (await fetch('/api/card/' + encodeURIComponent(id))).json();
  const p = d.price || {}, f = d.forecast;
  $('#market-detail').hidden = false;
  $('#md-name').textContent = d.card.name + ' · ' + (d.card.set_name || '');
  tween($('#md-price'), p.eur || p.trend || 0, '€', 2);
  $('#md-alt').textContent = (d.card.rarity && d.card.rarity !== 'None' ? d.card.rarity + ' · ' : '') + '#' + (d.card.local_id || '?');
  const dl = $('#md-delta');
  if (f) {
    const up = f.change_pct_180d > 2, down = f.change_pct_180d < -2;
    dl.className = 'delta ' + (up ? 'up' : down ? 'down' : 'flat');
    dl.textContent = (up ? '▲ ' : down ? '▼ ' : '● ') +
      (f.change_pct_180d > 0 ? '+' : '') + f.change_pct_180d + '% a 180 días · confianza ' +
      Math.round(f.confidence * 100) + '%';
  } else { dl.className = 'delta flat'; dl.textContent = 'sin predicción'; }

  const hist = [];
  if (p.avg30) hist.push({ x: -30, y: p.avg30 });
  if (p.avg7) hist.push({ x: -7, y: p.avg7 });
  hist.push({ x: 0, y: p.eur || p.trend || p.avg7 || 0 });
  const fut = f ? f.horizon_days.map((h, i) => ({
    x: h, y: f.eur[i], lo: f.low_band[i], hi: f.high_band[i]
  })) : [];
  PriceChart.draw($('#chart'), hist, fut, {});

  $('#md-stats').innerHTML = `
    <div class="stat"><span class="label">Mínimo</span><b>${fmt(p.low)}</b></div>
    <div class="stat"><span class="label">Media 7d</span><b>${fmt(p.avg7)}</b></div>
    <div class="stat"><span class="label">Media 30d</span><b>${fmt(p.avg30)}</b></div>
    <div class="stat"><span class="label">${f ? 'A 180 días' : 'Tendencia'}</span><b>${f ? fmt(f.eur[2]) : fmt(p.trend)}</b></div>`;
  $('#market-detail').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/* ----------------------------------------------------------------- modelos */
async function loadMetrics() {
  const h = await (await fetch('/api/health')).json();
  const m = h.metrics || {};
  const box = v => `<div class="stat"><span class="label">${v[0]}</span><b>${v[1]}</b></div>`;
  let html = '';
  if (m.embedder) {
    html += `<h3 style="margin-top:4px">Identificación de carta</h3>
      <p class="dim" style="font-size:.82rem;margin:4px 0 10px">MobileNetV3-Small + aprendizaje contrastivo (NT-Xent) sobre fotos simuladas.</p>
      <div class="price-grid">${[['recall@1', (m.embedder['recall@1'] || '—')],
        ['recall@5', (m.embedder['recall@5'] || '—')],
        ['imágenes', (m.embedder.images || '—')],
        ['épocas', (m.embedder.epochs || '—')]].map(box).join('')}</div>`;
  }
  if (m.condition) {
    const pc = m.condition.per_class || {};
    html += `<h3 style="margin-top:18px">Autenticidad y estado</h3>
      <p class="dim" style="font-size:.82rem;margin:4px 0 10px">MobileNetV3-Small, 3 clases. Split por carta: ninguna carta de test se vio en entrenamiento.</p>
      <div class="price-grid">${[['exactitud', (m.condition.test_accuracy * 100).toFixed(1) + '%'],
        ['F1 auténtica', (pc.autentica ? pc.autentica.f1 : '—')],
        ['F1 falsa', (pc.falsa ? pc.falsa.f1 : '—')],
        ['F1 dañada', (pc.danada ? pc.danada.f1 : '—')]].map(box).join('')}</div>`;
  }
  if (m.grade) {
    const eje = m.grade.mae_por_eje || {}, cor = m.grade.correlacion_por_eje || {};
    html += `<h3 style="margin-top:18px">Calificación PSA</h3>
      <p class="dim" style="font-size:.82rem;margin:4px 0 10px">Desgaste sintético de severidad conocida (etiqueta = 10 − 9·severidad). Split por carta.</p>
      <div class="price-grid">${[['MAE', m.grade.test_mae_grades + ' grados'],
        ['dentro de ±1', (m.grade.within_1_grade * 100).toFixed(1) + '%'],
        ['baseline MAE', m.grade.baseline_predecir_media_mae],
        ['cartas test', m.grade.cartas_test]].map(box).join('')}</div>
      <div class="price-grid" style="margin-top:8px">${Object.keys(eje).map(k =>
        box([k, (eje[k] ?? '—') + (cor[k] != null ? ' · r=' + cor[k] : '')])).join('')}</div>`;
  }
  if (m.price) {
    html += `<h3 style="margin-top:18px">Predicción de valor</h3>
      <p class="dim" style="font-size:.82rem;margin:4px 0 10px">${m.price.objetivo || ''} · ${m.price.fuente || ''}</p>
      <div class="price-grid">${[['acierto dirección', (m.price.acierto_direccion * 100).toFixed(1) + '%'],
        ['MAE', m.price.mae], ['R²', m.price.r2],
        ['baseline MAE', m.price.baseline_cero_mae]].map(box).join('')}</div>
      <p class="dim" style="font-size:.78rem">${m.price.gana_a_baselines ? 'El modelo supera a los baselines de predecir cero y predecir la media.' : 'Atención: el modelo NO supera a los baselines.'}</p>`;
  }
  $('#metrics').innerHTML = html || '<div class="empty">Todavía no hay modelos entrenados. Ejecuta los scripts de entrenamiento.</div>';
}

/* ------------------------------------------------------------------ salud */
async function health() {
  try {
    const h = await (await fetch('/api/health')).json();
    $('#ncards').textContent = (h.index_cards || h.catalog_cards || 0).toLocaleString('es-CO');
    const el = $('#health'), t = $('#healthtxt');
    if (h.demo) { el.classList.add('warn'); t.textContent = 'MODO DEMO'; }
    else { el.classList.remove('warn'); t.textContent = 'MODELOS ACTIVOS' + (h.temp_c ? ' · ' + h.temp_c + '°C' : ''); }
  } catch (e) { $('#healthtxt').textContent = 'sin conexión'; }
}

moveGlider();
health();
setInterval(health, 20000);
