/* Particulas y luz de arena: canvas fijo detras de la interfaz.
   Es lo que hace POKEMON en sus menus: chispas doradas que suben lento y
   se apagan, sin cubrir nada. Vanilla, un solo canvas, ~50 particulas,
   se pausa cuando la pestana no se ve y se apaga con MOVIMIENTO reducido. */
'use strict';
(() => {
  const cv = document.createElement('canvas');
  cv.id = 'sparkles';
  cv.setAttribute('aria-hidden', 'true');
  const st = document.createElement('style');
  st.textContent =
    '#sparkles{position:fixed;inset:0;z-index:-2;pointer-events:none;width:100%;height:100%}';
  document.head.appendChild(st);
  document.body.appendChild(cv);
  const ctx = cv.getContext('2d');
  let W, H, P = [], running = true, last = 0;

  const palette = () => {
    const cs = getComputedStyle(document.documentElement);
    const dark = document.documentElement.dataset.theme !== 'light';
    return {
      dark,
      colors: dark ? ['#ffd873', '#bfe900', '#8477fb', '#fff'] : ['#e8b400', '#7f9c00', '#6a5bf0', '#123']
    };
  };

  function make() {
    return {
      x: Math.random() * W,
      y: H + Math.random() * 40,
      s: 1.2 + Math.random() * 3.4,            // tamano
      v: 8 + Math.random() * 26,                // velocidad de subida (px/s)
      dr: (Math.random() - .5) * 22,            // deriva lateral
      tw: Math.random() * Math.PI * 2,          // fase de titileo
      life: 0,
      ttl: 5 + Math.random() * 7,
      c: 0
    };
  }
  function fit() {
    W = cv.width = devicePixelRatio > 1 ? innerWidth * Math.min(devicePixelRatio, 2) : innerWidth;
    H = cv.height = devicePixelRatio > 1 ? innerHeight * Math.min(devicePixelRatio, 2) : innerHeight;
  }
  fit();
  addEventListener('resize', fit, { passive: true });

  const N = Math.min(60, Math.max(28, Math.round(innerWidth / 26)));
  for (let i = 0; i < N; i++) { const p = make(); p.y = Math.random() * H; P.push(p); }

  function tick(t) {
    requestAnimationFrame(tick);
    if (!running) return;
    const dt = Math.min(.05, (t - last) / 1000 || .016); last = t;
    const { colors, dark } = palette();
    ctx.clearRect(0, 0, W, H);
    for (const p of P) {
      p.life += dt;
      if (p.life > p.ttl || p.y < -12) { Object.assign(p, make()); }
      p.y -= p.v * dt;
      p.x += Math.sin(p.tw + p.life * 2.2) * p.dr * dt;
      // titileo: curva suave, nunca invisible mas de un momento
      const tw = .35 + .65 * Math.abs(Math.sin(p.life * 2.6 + p.tw));
      const fadeIn = Math.min(1, p.life * 1.8);
      const fadeOut = Math.min(1, Math.max(0, (p.ttl - p.life) / 1.4));
      const a = tw * fadeIn * fadeOut * (dark ? .95 : .55);
      const c = colors[p.c || (p.c = Math.floor(Math.random() * colors.length))];
      ctx.globalAlpha = a;
      // cruz de luz (estrella de 4 puntas), lo que usa el juego en las rarezas
      const r = p.s;
      ctx.fillStyle = c;
      ctx.beginPath();
      ctx.moveTo(p.x, p.y - r * 2.2); ctx.quadraticCurveTo(p.x, p.y, p.x + r * 2.2, p.y);
      ctx.quadraticCurveTo(p.x, p.y, p.x, p.y + r * 2.2); ctx.quadraticCurveTo(p.x, p.y, p.x - r * 2.2, p.y);
      ctx.quadraticCurveTo(p.x, p.y, p.x, p.y - r * 2.2);
      ctx.fill();
      if (p.s > 2.6) {                    // nucleo brillante en las grandes
        ctx.globalAlpha = a * .9;
        ctx.beginPath(); ctx.arc(p.x, p.y, r * .55, 0, 7); ctx.fillStyle = dark ? '#fff' : '#fff8e0';
        ctx.fill();
      }
    }
    ctx.globalAlpha = 1;
  }
  requestAnimationFrame(tick);

  // pausa cuando no se ve: en el kiosco siempre se ve, pero ahorra bateria en laptop
  document.addEventListener('visibilitychange', () => { running = !document.hidden && !document.body.classList.contains('calm'); });
  const _obs = new MutationObserver(() => { running = !document.body.classList.contains('calm'); });
  _obs.observe(document.body, { attributes: true, attributeFilter: ['class'] });
})();
