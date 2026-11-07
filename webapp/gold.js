/* =========================================================
   fozol-pro — ذرات طلایی پریمیوم VIP (نسخهٔ ۳ — Luxe)
   هدف: حس «بسیار پرومیوم و حرفه‌ای» با کمترین مصرف CPU/GPU.

   معماری چهار لایه با عمق میدان و پالت شامپاین-طلایی-کهربایی:
     • لایهٔ ۰ (دور)  : هاله‌های aurora بسیار نرم و بزرگ — حرکت بسیار کند
     • لایهٔ ۱ (میانی): بوکه‌های طلایی با حلقهٔ لبهٔ ظریف — شناور با باد
     • لایهٔ ۲ (نزدیک): جرقه‌های کریستالی با برق چهارپر + گیلینت‌های تصادفی
     • لایهٔ ۳ (ریز)  : غبار طلایی ریز درخشان — حس فضا
   + شهاب طلایی مورب و «جاروی نور» افقی هر چند ثانیه
   + میدان جریان باد (flow field سینوسی) برای حرکت ارگانیک
   پرفورمنس: همهٔ ذرات اسپرایت پیش‌رندر هستند؛ تعداد متناسب با مساحت؛
   dpr سقف ۲؛ در تب مخفی متوقف؛ prefers-reduced-motion → یک فریم ثابت.
   فعال‌سازی: window.FzVip.apply(me) — از app.js صدا زده می‌شود.
   ========================================================= */
(function () {
  'use strict';

  var canvas = null, ctx = null, raf = null, running = false, active = false;
  var particles = [];
  var dpr = Math.min(window.devicePixelRatio || 1, 2);
  var W = 0, H = 0, last = 0, T = 0;
  var sprites = null;
  var reduceMotion = false;
  try { reduceMotion = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches); } catch (e) { /* noop */ }
  var rand = Math.random;

  /* ---------- اسپرایت‌های پیش‌رندر ---------- */
  function mkCanvas(size) { var c = document.createElement('canvas'); c.width = c.height = size; return { c: c, g: c.getContext('2d'), s: size }; }

  function buildSprites() {
    if (sprites) return;

    // ۰) aurora — هالهٔ محو خیلی بزرگ (لایهٔ دور)
    var aur = mkCanvas(160);
    (function (g, s) {
      var gr = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
      gr.addColorStop(0, 'rgba(255,226,150,0.34)');
      gr.addColorStop(0.5, 'rgba(244,192,84,0.12)');
      gr.addColorStop(1, 'rgba(244,192,84,0)');
      g.fillStyle = gr; g.fillRect(0, 0, s, s);
    })(aur.g, aur.s);

    // ۱) بوکهٔ طلایی — هستهٔ نرم + حلقهٔ لبه (دو تُن: شامپاین / کهربایی)
    function bokeh(core, mid, rim) {
      var k = mkCanvas(128);
      var g = k.g, s = k.s;
      var gr = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
      gr.addColorStop(0, core);
      gr.addColorStop(0.34, mid);
      gr.addColorStop(0.68, rim);
      gr.addColorStop(1, 'rgba(233,168,32,0)');
      g.fillStyle = gr; g.fillRect(0, 0, s, s);
      // حلقهٔ لبهٔ ظریف (بوکهٔ لنز واقعی)
      g.strokeStyle = rim; g.lineWidth = 1.6;
      g.beginPath(); g.arc(s / 2, s / 2, s * 0.31, 0, Math.PI * 2); g.stroke();
      return k.c;
    }
    var bokChampagne = bokeh('rgba(255,240,196,0.95)', 'rgba(250,214,110,0.55)', 'rgba(255,224,140,0.16)');
    var bokAmber = bokeh('rgba(255,232,160,0.95)', 'rgba(244,186,74,0.52)', 'rgba(236,164,52,0.15)');

    // ۲) جرقهٔ کریستالی — هستهٔ روشن + برق چهارپر (دو چرخش ±۲۲°)
    function spark() {
      var sp = mkCanvas(96), g = sp.g, s = sp.s, c = s / 2;
      function line(x1, y1, x2, y2, w) {
        var lg = g.createLinearGradient(x1, y1, x2, y2);
        lg.addColorStop(0, 'rgba(255,236,170,0)');
        lg.addColorStop(0.5, 'rgba(255,240,190,0.9)');
        lg.addColorStop(1, 'rgba(255,236,170,0)');
        g.strokeStyle = lg; g.lineCap = 'round'; g.lineWidth = w;
        g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke();
      }
      line(2, c, s - 2, c, 2.4); line(c, 2, c, s - 2, 2.4);            // صلیب اصلی
      var d = s * 0.19;                                                  // پرهای مورب ظریف‌تر
      line(c - d, c - d, c + d, c + d, 1.1); line(c + d, c - d, c - d, c + d, 1.1);
      var gr = g.createRadialGradient(c, c, 0, c, c, s / 2);
      gr.addColorStop(0, 'rgba(255,252,235,1)');
      gr.addColorStop(0.12, 'rgba(255,232,150,0.95)');
      gr.addColorStop(0.3, 'rgba(244,192,84,0.30)');
      gr.addColorStop(1, 'rgba(244,192,84,0)');
      g.fillStyle = gr; g.beginPath(); g.arc(c, c, s / 2, 0, Math.PI * 2); g.fill();
      return sp.c;
    }
    var sparkA = spark();
    var sparkB = mkCanvas(96);
    (function (g, s) { g.translate(s / 2, s / 2); g.rotate(0.4); g.translate(-s / 2, -s / 2); g.drawImage(sparkA, 0, 0); })(sparkB.g, sparkB.s);

    // ۳) غبار ریز — نقطهٔ درخشان کوچک
    var du = mkCanvas(32);
    (function (g, s) {
      var gr = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
      gr.addColorStop(0, 'rgba(255,244,214,0.95)');
      gr.addColorStop(0.4, 'rgba(250,214,110,0.4)');
      gr.addColorStop(1, 'rgba(250,214,110,0)');
      g.fillStyle = gr; g.fillRect(0, 0, s, s);
    })(du.g, du.s);

    sprites = { aurora: aur.c, bokeh: [bokChampagne, bokAmber], spark: [sparkA, sparkB.c], dust: du.c };
  }

  /* ---------- ذرات ---------- */
  function spawn(p, initial) {
    p = p || {};
    p.x = rand() * W;
    p.y = initial ? rand() * H : H + 30 + rand() * 90;
    p.ph = rand() * Math.PI * 2;
    return p;
  }

  function makeFar(initial) {
    var p = spawn({}, initial);
    p.layer = 0;
    p.r = 30 + rand() * 46;
    p.vy = 2 + rand() * 3.4;
    p.vx = (rand() - 0.5) * 1.6;
    p.a = 0.30 + rand() * 0.26;
    p.twV = 0.07 + rand() * 0.08;
    return p;
  }
  function makeMid(initial) {
    var p = spawn({}, initial);
    p.layer = 1;
    p.r = 4.5 + rand() * 10;
    p.vy = 6 + rand() * 9;
    p.sway = rand() * Math.PI * 2;
    p.swayV = 0.22 + rand() * 0.4;
    p.swayA = 4 + rand() * 8;
    p.a = 0.24 + rand() * 0.32;
    p.twV = 0.3 + rand() * 0.45;
    p.k = rand() < 0.55 ? 0 : 1; // تن شامپاین/کهربایی
    return p;
  }
  function makeSpark(initial) {
    var p = spawn({}, initial);
    p.layer = 2;
    p.r = 1.4 + rand() * 2.2;
    p.vy = 11 + rand() * 15;
    p.sway = rand() * Math.PI * 2;
    p.swayV = 0.45 + rand() * 0.8;
    p.swayA = 3 + rand() * 7;
    p.a = 0.4 + rand() * 0.38;
    p.twV = 0.8 + rand() * 1.3;
    p.k = rand() < 0.5 ? 0 : 1; // چرخش صلیب
    p.glintAt = T + 3 + rand() * 12;
    return p;
  }
  function makeDust(initial) {
    var p = spawn({}, initial);
    p.layer = 3;
    p.r = 0.7 + rand() * 1.1;
    p.vy = 4 + rand() * 7;
    p.sway = rand() * Math.PI * 2;
    p.swayV = 0.6 + rand() * 1.1;
    p.swayA = 2 + rand() * 5;
    p.a = 0.3 + rand() * 0.35;
    p.twV = 1.2 + rand() * 1.8;
    return p;
  }

  /* ---------- رویدادهای نوری ویژه ---------- */
  var shoot = null, sweep = null, nextShootAt = 6, nextSweepAt = 11;
  function startShoot() {
    var going = rand() > 0.5 ? 1 : -1;
    shoot = { x0: W * (0.15 + rand() * 0.7), y0: H * (0.04 + rand() * 0.3), dx: going * (140 + rand() * 120), dy: 90 + rand() * 90, dur: 0.8 + rand() * 0.4, t0: T };
    nextShootAt = T + 8 + rand() * 10;
  }
  function startSweep() {
    sweep = { y: H * (0.12 + rand() * 0.7), dir: rand() > 0.5 ? 1 : -1, dur: 1.15 + rand() * 0.5, t0: T };
    nextSweepAt = T + 12 + rand() * 12;
  }
  function drawShoot() {
    if (!shoot) return;
    var pr = (T - shoot.t0) / shoot.dur;
    if (pr >= 1) { shoot = null; return; }
    var fade = Math.sin(pr * Math.PI);
    var x1 = shoot.x0 + shoot.dx * pr, y1 = shoot.y0 + shoot.dy * pr;
    var x0 = shoot.x0 + shoot.dx * Math.max(0, pr - 0.34), y0 = shoot.y0 + shoot.dy * Math.max(0, pr - 0.34);
    var lg = ctx.createLinearGradient(x0, y0, x1, y1);
    lg.addColorStop(0, 'rgba(255,226,150,0)');
    lg.addColorStop(0.8, 'rgba(255,226,150,' + (0.3 * fade).toFixed(3) + ')');
    lg.addColorStop(1, 'rgba(255,248,220,' + (0.9 * fade).toFixed(3) + ')');
    ctx.strokeStyle = lg; ctx.lineCap = 'round'; ctx.lineWidth = 1.7;
    ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
    var d = 12 * fade;
    if (d > 0.5) ctx.drawImage(sprites.spark[0], x1 - d / 2, y1 - d / 2, d, d);
  }
  function drawSweep() {
    if (!sweep) return;
    var pr = (T - sweep.t0) / sweep.dur;
    if (pr >= 1) { sweep = null; return; }
    var fade = Math.sin(pr * Math.PI) * 0.16;
    var cx = sweep.dir > 0 ? pr * (W + 340) - 170 : W - pr * (W + 340) + 170;
    var gr = ctx.createRadialGradient(cx, sweep.y, 0, cx, sweep.y, 240);
    gr.addColorStop(0, 'rgba(255,240,190,' + fade.toFixed(3) + ')');
    gr.addColorStop(1, 'rgba(255,240,190,0)');
    ctx.fillStyle = gr;
    ctx.fillRect(cx - 240, sweep.y - 60, 480, 120);
  }

  /* ---------- حلقهٔ رندر ---------- */
  function counts() {
    var area = W * H;
    return [
      Math.max(3, Math.min(8, Math.round(area / 90000))),
      Math.max(8, Math.min(22, Math.round(area / 30000))),
      Math.max(10, Math.min(24, Math.round(area / 24000))),
      Math.max(14, Math.min(36, Math.round(area / 16000)))
    ];
  }
  var MAKERS = [makeFar, makeMid, makeSpark, makeDust];

  function step(now) {
    if (!running || !ctx) return;
    var dt = Math.min(0.05, last ? (now - last) / 1000 : 0.016);
    last = now; T += dt;
    ctx.clearRect(0, 0, W, H);

    var want = counts(), byLayer = [0, 0, 0, 0], i, p, L;
    for (i = 0; i < particles.length; i++) byLayer[particles[i].layer]++;
    for (L = 0; L < 4; L++) {
      while (byLayer[L] < want[L]) { particles.push(MAKERS[L](false)); byLayer[L]++; }
      if (byLayer[L] > want[L]) {
        for (i = particles.length - 1; i >= 0 && byLayer[L] > want[L]; i--) {
          if (particles[i].layer === L) { particles.splice(i, 1); byLayer[L]--; }
        }
      }
    }

    // میدان باد: رانش افقی ملایم و ارگانیک (سینوسی در ارتفاع و زمان)
    var wind = Math.sin(T * 0.13) * 7 + Math.sin(T * 0.043) * 4;

    for (i = 0; i < particles.length; i++) {
      p = particles[i];
      p.y -= p.vy * dt;
      if (p.layer === 0) {
        p.x += (p.vx + wind * 0.25) * dt;
        var twf = 0.62 + 0.38 * Math.sin(T * p.twV * 2 * Math.PI + p.ph);
        ctx.globalAlpha = Math.max(0.04, p.a * twf);
        var df = p.r * 2;
        ctx.drawImage(sprites.aurora, p.x - df / 2, p.y - df / 2, df, df);
      } else {
        p.sway += p.swayV * dt * 2;
        p.x += (Math.sin(p.sway) * p.swayA + (p.layer === 1 ? wind * 0.6 : wind * 0.4)) * dt;
        var tw = 0.58 + 0.42 * Math.sin(T * p.twV * 2 * Math.PI + p.ph);
        var alpha = p.a * tw, d;
        if (p.layer === 1) {
          d = p.r * 2;
          ctx.globalAlpha = Math.max(0.05, alpha);
          ctx.drawImage(sprites.bokeh[p.k], p.x - d / 2, p.y - d / 2, d, d);
        } else if (p.layer === 2) {
          var boost = 0;
          if (T >= p.glintAt) {
            var gp = (T - p.glintAt) / 0.6;
            if (gp >= 1) { p.glintAt = T + 6 + rand() * 14; }
            else boost = Math.sin(gp * Math.PI);
          }
          alpha = Math.min(1, alpha + boost * 0.6);
          var flare = 1 + boost * 2.1;
          d = p.r * 7 * flare;
          ctx.globalAlpha = Math.max(0.08, alpha);
          ctx.drawImage(sprites.spark[p.k], p.x - d / 2, p.y - d / 2, d, d);
        } else { // غبار ریز
          d = p.r * 6;
          ctx.globalAlpha = Math.max(0.06, alpha * 0.8);
          ctx.drawImage(sprites.dust, p.x - d / 2, p.y - d / 2, d, d);
        }
      }
      if (p.y < -80) spawn(p, false);
      else if (p.x < -100) p.x = W + 96;
      else if (p.x > W + 100) p.x = -96;
    }

    if (!reduceMotion) {
      if (T >= nextShootAt && !shoot) startShoot();
      if (T >= nextSweepAt && !sweep) startSweep();
      drawShoot();
      drawSweep();
    }
    ctx.globalAlpha = 1;
    raf = requestAnimationFrame(step);
  }

  function renderStatic() {
    /* یک فریم ثابت برای prefers-reduced-motion */
    buildSprites();
    resize();
    for (var L = 0; L < 4; L++) {
      var n = Math.ceil(counts()[L] / 2);
      for (var i = 0; i < n; i++) particles.push(MAKERS[L](true));
    }
    for (i = 0; i < particles.length; i++) {
      var p = particles[i], d = (p.r || 4) * 2;
      ctx.globalAlpha = p.a || 0.3;
      var img = p.layer === 0 ? sprites.aurora : p.layer === 1 ? sprites.bokeh[p.k] : p.layer === 2 ? sprites.spark[p.k] : sprites.dust;
      ctx.drawImage(img, p.x - d / 2, p.y - d / 2, d, d);
    }
    ctx.globalAlpha = 1;
  }

  function resize() {
    if (!canvas) return;
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function start() {
    if (running) return;
    if (reduceMotion) { renderStatic(); running = false; return; }
    buildSprites();
    resize();
    last = 0; T = 0;
    running = true;
    raf = requestAnimationFrame(step);
  }

  function stop() {
    running = false;
    if (raf) { cancelAnimationFrame(raf); raf = null; }
    if (ctx && canvas) ctx.clearRect(0, 0, W, H);
    particles = []; shoot = null; sweep = null;
  }

  function ensure() {
    if (canvas) return canvas;
    buildSprites();
    canvas = document.createElement('canvas');
    canvas.id = 'gold-canvas';
    canvas.setAttribute('aria-hidden', 'true');
    document.body.appendChild(canvas);
    ctx = canvas.getContext('2d');
    window.addEventListener('resize', function () { resize(); if (reduceMotion && active) renderStatic(); });
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) { if (raf) { cancelAnimationFrame(raf); raf = null; } }
      else if (running) { last = 0; raf = requestAnimationFrame(step); }
    });
    // همگام با تغییر تم روشن/تیره
    try {
      var mo = new MutationObserver(function () {
        if (!canvas) return;
        var light = document.documentElement.getAttribute('data-theme') !== 'dark';
        canvas.classList.toggle('gold-canvas--light', light);
      });
      mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    } catch (e) { /* noop */ }
    return canvas;
  }

  /* ---------- API عمومی ---------- */
  window.FzVip = {
    apply: function (me) {
      active = !!(me && me.vip && me.vip.active);
      if (!document.body) return;
      document.body.classList.toggle('is-vip', active);
      if (!document.body.classList.contains('vip-booted')) {
        document.body.classList.add('vip-booted');
        ensure();
      }
      if (canvas) {
        var light = document.documentElement.getAttribute('data-theme') !== 'dark';
        canvas.classList.toggle('gold-canvas--light', light);
      }
      if (active) start();
      else stop();
    }
  };
})();
