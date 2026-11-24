/* Gráfica de precios en canvas 2D puro. Sin librerías: la Pi no baja CDNs. */
(function (global) {
  'use strict';

  function dpr(canvas) {
    const d = Math.min(global.devicePixelRatio || 1, 2);
    const r = canvas.getBoundingClientRect();
    canvas.width = Math.max(320, r.width * d);
    canvas.height = Math.max(160, r.height * d);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(d, 0, 0, d, 0, 0);
    return { ctx, w: canvas.width / d, h: canvas.height / d };
  }

  const easeOut = t => 1 - Math.pow(1 - t, 3);

  /**
   * hist: [{x: -30, y: 3.8}, ...] puntos reales (días negativos = pasado)
   * fut : [{x: 30, y: 4.1, lo: 3.6, hi: 4.5}, ...] predicción
   */
  function drawPrice(canvas, hist, fut, opts) {
    opts = opts || {};
    const { ctx, w, h } = dpr(canvas);
    const pad = { l: 44, r: 14, t: 16, b: 26 };
    const all = hist.concat(fut);
    if (!all.length) return;
    const xs = all.map(p => p.x);
    const ys = all.map(p => p.y)
      .concat(fut.map(p => p.lo)).concat(fut.map(p => p.hi))
      .filter(v => typeof v === 'number');
    let x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
    let y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    const padY = (y1 - y0) * 0.18 || Math.max(0.1, y1 * 0.1);
    y0 -= padY; y1 += padY;
    if (x1 === x0) x1 = x0 + 1;

    const X = v => pad.l + (v - x0) / (x1 - x0) * (w - pad.l - pad.r);
    const Y = v => h - pad.b - (v - y0) / (y1 - y0) * (h - pad.t - pad.b);

    const start = performance.now();
    const dur = opts.animate === false ? 0 : 850;

    function frame(now) {
      const t = dur ? easeOut(Math.min(1, (now - start) / dur)) : 1;
      ctx.clearRect(0, 0, w, h);

      // rejilla
      ctx.strokeStyle = 'rgba(255,255,255,.08)';
      ctx.lineWidth = 1;
      ctx.font = '600 10px Saira, system-ui';
      ctx.fillStyle = 'rgba(249,255,250,.38)';
      for (let i = 0; i <= 4; i++) {
        const v = y0 + (y1 - y0) * i / 4, y = Y(v);
        ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
        ctx.fillText('€' + v.toFixed(v < 10 ? 2 : 0), 6, y + 3);
      }
      // hoy
      const xh = X(0);
      ctx.save();
      ctx.setLineDash([4, 5]);
      ctx.strokeStyle = 'rgba(255,255,255,.3)';
      ctx.beginPath(); ctx.moveTo(xh, pad.t); ctx.lineTo(xh, h - pad.b); ctx.stroke();
      ctx.restore();
      ctx.fillStyle = 'rgba(249,255,250,.55)';
      ctx.fillText('HOY', xh - 11, h - 9);
      if (fut.length) ctx.fillText('+' + fut[fut.length - 1].x + 'd', X(fut[fut.length - 1].x) - 16, h - 9);
      if (hist.length) ctx.fillText(hist[0].x + 'd', X(hist[0].x) - 8, h - 9);

      // banda de incertidumbre
      const fv = fut.filter(p => typeof p.lo === 'number');
      if (fv.length) {
        const last = hist[hist.length - 1] || fv[0];
        ctx.beginPath();
        ctx.moveTo(X(last.x), Y(last.y));
        fv.forEach(p => ctx.lineTo(X(p.x * t), Y(p.hi)));
        for (let i = fv.length - 1; i >= 0; i--) ctx.lineTo(X(fv[i].x * t), Y(fv[i].lo));
        ctx.closePath();
        ctx.fillStyle = 'rgba(191,233,0,.14)';
        ctx.fill();
      }

      // histórico
      function line(pts, color, width, glow, prog) {
        if (!pts.length) return;
        ctx.save();
        ctx.beginPath();
        pts.forEach((p, i) => {
          const px = X(prog ? p.x * prog : p.x), py = Y(p.y);
          i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
        });
        ctx.strokeStyle = color; ctx.lineWidth = width;
        ctx.lineJoin = 'round'; ctx.lineCap = 'round';
        if (glow) { ctx.shadowColor = color; ctx.shadowBlur = 14; }
        ctx.stroke();
        ctx.restore();
      }
      const hvis = hist.slice(0, Math.max(2, Math.ceil(hist.length * Math.min(1, t * 1.6))));
      line(hvis, '#0a95f6', 2.5, true);
      const bridge = hist.length ? [hist[hist.length - 1]].concat(fut) : fut;
      line(bridge, '#bfe900', 2.5, true, t);

      // puntos de predicción
      fut.forEach(p => {
        const px = X(p.x * t), py = Y(p.y);
        ctx.beginPath(); ctx.arc(px, py, 4, 0, 6.3);
        ctx.fillStyle = '#bfe900'; ctx.fill();
        ctx.strokeStyle = '#010636'; ctx.lineWidth = 2; ctx.stroke();
      });

      if (t < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  global.PriceChart = { draw: drawPrice };
})(window);
