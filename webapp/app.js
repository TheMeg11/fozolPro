/* =========================================================
   فضول‌یاب — مینی‌اپ بله | app.js
   بدون بیلد، بدون CDN. لایه‌ها:
   Config → Utils → Icons → Platform(SDK بله) → API/Demo → Store/Cache
   → UI Kit (h, Sheet, Modal, Toast, Skeleton) → Router(in-memory) → Pages → Boot
   ========================================================= */
(function () {
  'use strict';
  if (window.__FZ_BOOTED__) return;
  window.__FZ_BOOTED__ = true;

  /* ===================== Config ===================== */
  var CFG = Object.assign({
    appName: 'فضول‌یاب',
    version: '4.7.0',
    apiBase: '/api',
    sdkGlobal: 'Bale',            // window.Bale.WebApp
    sdkFallbackGlobal: '',        // فقط برای توسعه؛ در محصول خالی بماند
    sdkUrl: '',                   // در صورت عدم تزریق در index.html، به‌صورت پویا لود می‌شود
    botUsername: 'fozoolyab_bot',
    deepLinkBase: 'https://ble.ir/',
    useNativeMainButton: true,
    demo: 'auto',                 // auto | on | off
    requestTimeoutMs: 15000
  }, window.APP_CONFIG || {});

  /* ===================== Utils ===================== */
  var nf; try { nf = new Intl.NumberFormat('fa-IR'); } catch (e) { nf = null; }
  function fa(n) { if (n === null || n === undefined || n === '') return ''; return nf ? nf.format(n) : faDigits(n); }
  function faDigits(s) { return String(s).replace(/\d/g, function (d) { return '۰۱۲۳۴۵۶۷۸۹'[d]; }); }
  function toman(n) { return fa(n) + ' تومان'; }
  function mkFmt(opts) { try { return new Intl.DateTimeFormat('fa-IR-u-ca-persian', opts); } catch (e) { return null; } }
  var F_DATE = mkFmt({ year: 'numeric', month: 'long', day: 'numeric' });
  var F_SHORT = mkFmt({ month: 'long', day: 'numeric' });
  var F_TIME = mkFmt({ hour: '2-digit', minute: '2-digit', hour12: false });
  var F_DAY = mkFmt({ day: 'numeric' });
  var F_WD = mkFmt({ weekday: 'narrow' });
  function jdate(v, withTime) {
    if (!v) return '—';
    var d = new Date(v); if (isNaN(d)) return '—';
    var s = F_DATE ? F_DATE.format(d) : d.toLocaleDateString();
    return withTime ? s + '، ساعت ' + jtime(d) : s;
  }
  function jshort(v) { var d = new Date(v); return F_SHORT ? F_SHORT.format(d) : d.toLocaleDateString(); }
  function jtime(v) { var d = new Date(v); return F_TIME ? F_TIME.format(d) : d.toLocaleTimeString(); }
  function ago(v) {
    var s = (Date.now() - new Date(v).getTime()) / 1000;
    if (s < 60) return 'همین الان';
    if (s < 3600) return fa(Math.floor(s / 60)) + ' دقیقه پیش';
    if (s < 86400) return fa(Math.floor(s / 3600)) + ' ساعت پیش';
    if (s < 86400 * 7) return fa(Math.floor(s / 86400)) + ' روز پیش';
    return jdate(v);
  }
  function until(v) {
    var s = (new Date(v).getTime() - Date.now()) / 1000;
    if (s <= 60) return 'کمتر از یک دقیقه';
    if (s < 3600) return fa(Math.ceil(s / 60)) + ' دقیقه دیگر';
    if (s < 86400) return fa(Math.floor(s / 3600)) + ' ساعت و ' + fa(Math.floor(s % 3600 / 60)) + ' دقیقه دیگر';
    return fa(Math.ceil(s / 86400)) + ' روز دیگر';
  }
  function hashStr(s) { var h = 0; for (var i = 0; i < s.length; i++) { h = ((h << 5) - h + s.charCodeAt(i)) | 0; } return Math.abs(h); }
  var PALETTE = ['#f97316', '#8b5cf6', '#06b6d4', '#ec4899', '#10b981', '#3b82f6', '#eab308', '#ef4444', '#14b8a6', '#a855f7'];
  function colorFor(id) { return PALETTE[hashStr(String(id)) % PALETTE.length]; }
  function initials(name) {
    var parts = String(name || '؟').trim().split(/\s+/).slice(0, 2);
    return parts.map(function (w) { return w.charAt(0); }).join('\u200c');
  }
  function debounce(fn, ms) { var t; return function () { var a = arguments, self = this; clearTimeout(t); t = setTimeout(function () { fn.apply(self, a); }, ms); }; }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function clone(o) { return o === undefined ? o : JSON.parse(JSON.stringify(o)); }
  var LS = {
    get: function (k, d) { try { var v = localStorage.getItem('fz.' + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem('fz.' + k, JSON.stringify(v)); } catch (e) { /* storage unavailable */ } }
  };
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return legacyCopy(text); });
    }
    return Promise.resolve(legacyCopy(text));
  }
  function legacyCopy(text) {
    var ta = document.createElement('textarea'); ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select(); var ok = false; try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    ta.remove(); return ok;
  }

  /* ===================== DOM helper ===================== */
  function h(tag, props) {
    var el = document.createElement(tag);
    if (props) {
      for (var k in props) {
        var v = props[k];
        if (v === null || v === undefined || v === false) continue;
        if (k === 'class') el.className = v;
        else if (k === 'style') { if (typeof v === 'string') el.style.cssText = v; else Object.assign(el.style, v); }
        else if (k.slice(0, 2) === 'on' && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
        else if (k === 'html') el.innerHTML = v; // فقط برای SVGهای ثابت داخلی
        else if (k in el && k !== 'list' && k !== 'form') { try { el[k] = v; } catch (e) { el.setAttribute(k, v); } }
        else el.setAttribute(k, v === true ? '' : v);
      }
    }
    for (var i = 2; i < arguments.length; i++) add(el, arguments[i]);
    return el;
  }
  function add(el, c) {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) { c.forEach(function (x) { add(el, x); }); return; }
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }

  /* ===================== Icons (inline SVG) ===================== */
  var P = {
    home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V9.5"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    crown: '<path d="M3 7l4.5 4L12 4l4.5 7L21 7l-2 12H5L3 7Z"/>',
    edit: '<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    radar: '<path d="M12 12 19 5M12 21a9 9 0 1 1 9-9"/><circle cx="12" cy="12" r="4"/><path d="M12 12v.01"/>',
    coins: '<circle cx="9" cy="9" r="5.5"/><path d="M15.2 6.6a5.5 5.5 0 1 1-7.6 7.6"/><path d="M7.5 9h3M9 7.5v3"/>',
    message: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3Z"/><path d="m9 12 2 2 4-4"/>',
    copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
    share: '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    minus: '<path d="M5 12h14"/>',
    trash: '<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/>',
    chevL: '<path d="m15 18-6-6 6-6"/>',
    back: '<path d="M5 12h14M13 5l7 7-7 7"/>',
    trophy: '<path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0V4Z"/><path d="M17 5h3v2a3 3 0 0 1-3 3M7 5H4v2a3 3 0 0 0 3 3"/>',
    gift: '<rect x="3" y="8" width="18" height="4" rx="1"/><path d="M12 8v13M5 12v9h14v-9"/><path d="M12 8S10.5 3 8 3.5 7 8 12 8Zm0 0s1.5-5 4-4.5S17 8 12 8Z"/>',
    bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    check: '<path d="m5 12 5 5L20 7"/>',
    checks: '<path d="m2 12 5 5L17 7M12 16l1 1L23 7"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    send: '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4 20-7Z"/>',
    clip: '<path d="m21 11-8.5 8.5a5 5 0 0 1-7-7L14 4a3.5 3.5 0 0 1 5 5l-8.6 8.6a2 2 0 0 1-2.8-2.8L15 7.5"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    users: '<circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0"/><path d="M16 4a4 4 0 0 1 0 8M22 21a7 7 0 0 0-4-6.3"/>',
    chart: '<path d="M3 3v18h18"/><path d="M7 15v2M11 10v7M15 12v5M19 7v10"/>',
    megaphone: '<path d="M3 11v2a1 1 0 0 0 1 1h3l6 4V6L7 10H4a1 1 0 0 0-1 1Z"/><path d="M17 8a5 5 0 0 1 0 8M20 5a9 9 0 0 1 0 14"/>',
    database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    unlock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.6-1.7"/>',
    ban: '<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
    external: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>',
    wifiOff: '<path d="M2 2l20 20M8.5 16.5a5 5 0 0 1 7 0M5 13a10 10 0 0 1 5.2-2.8M12 20h.01M16.7 11.3A10 10 0 0 1 19 13M2 8.8a15 15 0 0 1 4.2-2.7M10.7 5.1A15 15 0 0 1 22 8.8"/>',
    alert: '<path d="M12 3 2 20h20L12 3Z"/><path d="M12 10v4M12 17v.5"/>',
    star: '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9L12 3Z"/>',
    link: '<path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
    target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    image: '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/>',
    vibrate: '<rect x="8" y="3" width="8" height="18" rx="2"/><path d="M4 8v8M20 8v8"/>',
    palette: '<circle cx="12" cy="12" r="9"/><circle cx="8" cy="10" r="1"/><circle cx="12" cy="7.5" r="1"/><circle cx="16" cy="10" r="1"/><path d="M12 21a2 2 0 0 1 0-4h2a3 3 0 0 0 3-3"/>',
    bot: '<rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 8V4M9 13v1M15 13v1M9 17h6"/>',
    receipt: '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2V3Z"/><path d="M9 8h6M9 12h6"/>',
    inbox: '<path d="M3 13h5l1 3h6l1-3h5"/><path d="M5 5h14l2 8v6H3v-6l2-8Z"/>',
    upload: '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v4h16v-4"/>',
    sparkles: '<path d="M12 3l1.8 4.7 4.7 1.8-4.7 1.8L12 16l-1.8-4.7-4.7-1.8 4.7-1.8L12 3Z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15Z"/>',
    fire: '<path d="M12 22c4 0 7-2.7 7-7 0-4-3-6-4-9-1 2-2 3-3 3 0-2-1-4-3-6 0 4-4 6-4 12 0 4.3 3 7 7 7Z"/>',
    hash: '<path d="M4 9h16M4 15h16M10 3 8 21M16 3l-2 18"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>'
  };
  function icon(name, cls) {
    return h('span', { class: 'ic' + (cls ? ' ' + cls : ''), 'aria-hidden': 'true', html: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + (P[name] || P.info) + '</svg>' });
  }

  /* ===================== Platform (SDK بله) ===================== */
  var Platform = (function () {
    var wa = null;
    function detect() {
      var g = window[CFG.sdkGlobal];
      wa = (g && g.WebApp) || null;
      if (!wa && CFG.sdkFallbackGlobal) { var f = window[CFG.sdkFallbackGlobal]; wa = (f && f.WebApp) || null; }
      // اسکریپت SDK خارج از اپ بله هم لود می‌شود اما initData ندارد؛ در آن حالت «داخل بله» نیستیم
      if (wa && !wa.initData) wa = null;
      return wa;
    }
    function call(obj, fn) { try { if (obj && typeof obj[fn] === 'function') return obj[fn].apply(obj, [].slice.call(arguments, 2)); } catch (e) { /* unsupported */ } }
    function loadSdk() {
      if (detect() || !CFG.sdkUrl) return Promise.resolve(wa);
      return new Promise(function (resolve) {
        var s = document.createElement('script'); var done = false;
        var fin = function () { if (done) return; done = true; resolve(detect()); };
        s.src = CFG.sdkUrl; s.async = true; s.onload = fin; s.onerror = fin;
        document.head.appendChild(s); setTimeout(fin, 3500);
      });
    }
    var backCb = null;
    return {
      init: function () {
        return loadSdk().then(function () {
          if (wa) {
            call(wa, 'ready'); call(wa, 'expand');
            if (wa.BackButton) call(wa.BackButton, 'onClick', function () { if (backCb) backCb(); });
          }
          return wa;
        });
      },
      get wa() { return wa; },
      get initData() { return (wa && wa.initData) || ''; },
      get user() { return wa && wa.initDataUnsafe && wa.initDataUnsafe.user; },
      get hasNativeBack() { return !!(wa && wa.BackButton && typeof wa.BackButton.show === 'function'); },
      get hasMainButton() { return !!(CFG.useNativeMainButton && wa && wa.MainButton && typeof wa.MainButton.show === 'function' && typeof wa.MainButton.setText === 'function'); },
      colorScheme: function () { return wa && wa.colorScheme; },
      themeParams: function () { return (wa && wa.themeParams) || null; },
      onEvent: function (ev, cb) { call(wa, 'onEvent', ev, cb); },
      onBack: function (cb) { backCb = cb; },
      setBack: function (visible) { if (wa && wa.BackButton) call(wa.BackButton, visible ? 'show' : 'hide'); },
      main: {
        handler: null,
        show: function (text, cb) {
          var mb = wa.MainButton; if (this.handler) call(mb, 'offClick', this.handler);
          this.handler = cb; call(mb, 'setText', text); call(mb, 'onClick', cb); call(mb, 'enable'); call(mb, 'show');
        },
        progress: function (on) { call(wa.MainButton, on ? 'showProgress' : 'hideProgress'); },
        hide: function () { if (!wa || !wa.MainButton) return; if (this.handler) call(wa.MainButton, 'offClick', this.handler); this.handler = null; call(wa.MainButton, 'hide'); }
      },
      haptic: function (kind) {
        if (!LS.get('haptic', true)) return;
        var hf = wa && wa.HapticFeedback;
        if (hf) {
          if (kind === 'success' || kind === 'error' || kind === 'warning') call(hf, 'notificationOccurred', kind);
          else if (kind === 'select') call(hf, 'selectionChanged');
          else call(hf, 'impactOccurred', kind || 'light');
        } else if (navigator.vibrate) { try { navigator.vibrate(kind === 'error' ? [20, 40, 20] : kind === 'success' ? 18 : 8); } catch (e) { /* noop */ } }
      },
      openLink: function (url) {
        if (State.demo && !wa) { toast('در اپ بله باز می‌شود: ' + url.replace(/^https?:\/\//, ''), 'info'); return; }
        if (wa && typeof wa.openLink === 'function') { call(wa, 'openLink', url); return; }
        window.open(url, '_blank', 'noopener');
      },
      botLink: function (start) { return CFG.deepLinkBase + CFG.botUsername + (start ? '?start=' + encodeURIComponent(start) : ''); },
      openBot: function (start) {
        var url = this.botLink(start);
        if (wa && typeof wa.openBaleLink === 'function') { call(wa, 'openBaleLink', url); return; }
        this.openLink(url);
      },
      startParam: function () {
        var u = wa && wa.initDataUnsafe; if (u && u.start_param) return u.start_param;
        try {
          var q = new URLSearchParams(location.search); var hp = new URLSearchParams(location.hash.replace(/^#/, ''));
          return q.get('startapp') || q.get('tgWebAppStartParam') || hp.get('tgWebAppStartParam') || '';
        } catch (e) { return ''; }
      },
      share: function (text, url) {
        if (navigator.share) return navigator.share({ title: CFG.appName, text: text, url: url }).then(function () { return 'shared'; }, function () { return 'cancel'; });
        return copyText(text + '\n' + url).then(function () { return 'copied'; });
      }
    };
  })();

  /* ===================== State & Cache ===================== */
  var State = { me: null, demo: false, online: navigator.onLine };
  var Cache = {
    m: {},
    get: function (k) { return this.m[k]; },
    set: function (k, v) { this.m[k] = clone(v); },
    del: function (prefix) { for (var k in this.m) if (k.indexOf(prefix) === 0) delete this.m[k]; }
  };

  /* ===================== API ===================== */
  function ApiError(code, message, status, details) { this.code = code; this.message = message; this.status = status || 0; this.details = details || {}; }
  ApiError.prototype = Object.create(Error.prototype);
  var ERR_TEXT = {
    OFFLINE: 'اتصال اینترنت برقرار نیست. پس از اتصال دوباره تلاش کنید.',
    NETWORK: 'ارتباط با سرور برقرار نشد. کمی بعد دوباره تلاش کنید.',
    TIMEOUT: 'پاسخ سرور طول کشید. دوباره تلاش کنید.',
    AUTH_REQUIRED: 'برای استفاده، مینی‌اپ را از داخل بله باز کنید.',
    AUTH_INVALID: 'اعتبار نشست تأیید نشد. مینی‌اپ را ببندید و دوباره از بله باز کنید.',
    AUTH_EXPIRED: 'نشست شما منقضی شده؛ مینی‌اپ را ببندید و دوباره باز کنید.',
    RATE_LIMITED: 'تعداد درخواست‌ها زیاد است؛ چند ثانیه صبر کنید.',
    FORBIDDEN: 'به این بخش دسترسی ندارید.',
    NOT_FOUND: 'موردی پیدا نشد.',
    VALIDATION_ERROR: 'اطلاعات واردشده معتبر نیست.',
    CHANNEL_JOIN_REQUIRED: 'برای ادامه ابتدا عضو کانال شوید.',
    BANNED: 'حساب شما مسدود شده است. با پشتیبانی تماس بگیرید.',
    PAYMENT_NOT_CONFIGURED: 'درگاه پرداخت هنوز فعال نشده؛ لطفاً بعداً تلاش کنید یا با پشتیبانی تماس بگیرید.',
    /* v4.7: کدهای جدید ماموریت/پاداش/اخطار */
    VIP_REQUIRED: 'این قابلیت فقط برای اعضای VIP است.',
    ALREADY_CLAIMED: 'جایزهٔ امروز را قبلاً گرفته‌ای؛ فردا دوباره بیا!',
    GIFT_INVALID: 'کد نامعتبر است.',
    GIFT_EXHAUSTED: 'ظرفیت استفاده از این کد به پایان رسیده.',
    GIFT_ALREADY_USED: 'شما قبلاً این کد را استفاده کرده‌اید.',
    COOLDOWN: 'فرصت امروزت تمام شده — فردا بیا!',
    SERVER_ERROR: 'خطای داخلی سرور؛ لطفاً کمی بعد تلاش کنید.'
  };
  function errMsg(e) { return (e && e.message) || ERR_TEXT[e && e.code] || ERR_TEXT.SERVER_ERROR; }

  function api(path, opts) {
    opts = opts || {};
    var method = opts.method || 'GET';
    var p = State.demo ? Demo.handle(method, path, opts.body) : realFetch(method, path, opts.body);
    return p.catch(function (e) {
      if (!(e instanceof ApiError)) e = new ApiError('NETWORK', ERR_TEXT.NETWORK);
      if (e.code === 'CHANNEL_JOIN_REQUIRED') Gate.show((e.details && e.details.channels) || []);
      throw e;
    });
  }
  function realFetch(method, path, body, attempt) {
    attempt = attempt || 0;
    if (!navigator.onLine) return Promise.reject(new ApiError('OFFLINE', ERR_TEXT.OFFLINE));
    var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, CFG.requestTimeoutMs);
    // fozol-pro: خطاهای گذرا (5xx / قطعی لحظه‌ای شبکه / timeout) تا ۲ بار با فاصله دوباره تلاش
    // می‌شوند تا کاربر به‌خاطر یک اختلال لحظه‌ای صفحهٔ خطا نبیند.
    function retryable() { return attempt < 2; }
    function retry() { return sleep(800 * (attempt + 1)).then(function () { return realFetch(method, path, body, attempt + 1); }); }
    return fetch(CFG.apiBase + path, {
      method: method,
      headers: { 'Content-Type': 'application/json', 'X-Bale-Init-Data': Platform.initData },
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl ? ctrl.signal : undefined,
      credentials: 'same-origin'
    }).then(function (res) {
      clearTimeout(timer);
      return res.json().catch(function () { return null; }).then(function (data) {
        if (!res.ok || !data || data.ok === false) {
          var er = (data && data.error) || {};
          if (retryable() && (res.status >= 500 || res.status === 429)) return retry();
          throw new ApiError(er.code || (res.status >= 500 ? 'SERVER_ERROR' : 'HTTP_' + res.status), er.message || ERR_TEXT[er.code] || ERR_TEXT.SERVER_ERROR, res.status, er.details);
        }
        return data.data;
      });
    }, function (e) {
      clearTimeout(timer);
      var isAbort = e && e.name === 'AbortError';
      var safeMethod = method === 'GET' || method === 'DELETE';
      if (retryable() && (safeMethod || isAbort)) return retry();
      throw new ApiError(isAbort ? 'TIMEOUT' : 'NETWORK', isAbort ? ERR_TEXT.TIMEOUT : ERR_TEXT.NETWORK);
    });
  }

  /* ===================== Demo backend (داده‌های نمونه) ===================== */
  var Demo = (function () {
    var seed = 20240917;
    function rnd() { seed |= 0; seed = (seed + 0x6D2B79F5) | 0; var t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }
    function pick(a) { return a[Math.floor(rnd() * a.length)]; }
    var NOW = Date.now(), MIN = 60e3, HR = 3600e3, DAY = 86400e3;
    function iso(ms) { return new Date(ms).toISOString(); }
    var FIRST = ['سارا', 'علی', 'مهدی', 'نگار', 'امیرحسین', 'زهرا', 'پارسا', 'فاطمه', 'رضا', 'مریم', 'حسین', 'الهام', 'محمد', 'نازنین', 'کیان', 'ستاره', 'یاسین', 'هانیه', 'آرمان', 'مهسا', 'بهراد', 'شیرین', 'امید', 'ترانه'];
    var LAST = ['محمدی', 'رضایی', 'کریمی', 'احمدی', 'موسوی', 'حسینی', 'نوری', 'جعفری', 'قاسمی', 'صادقی', 'اکبری', 'کاظمی', 'طاهری', 'رحیمی', 'یزدانی', 'شریفی', 'فرهادی', 'مرادی'];
    var USERNAMES = ['sara_m', 'ali_rz', 'mahdi.k', 'negar_ahm', 'amirhosein', 'zahra_h', 'parsa_n', 'fateme_j', 'reza_gh', 'maryam_s', null, 'elham_k', 'mmd_tahe', null, 'kian_r', 'setare_y', null, 'hanie_sh', 'arman_f', 'mahsa_m'];
    function mask(name) { return name.split(' ').map(function (w) { return w.charAt(0) + '***'; }).join(' '); }

    var me = { id: 4815162342, first_name: 'آرش', last_name: 'کیانی', username: 'arash_kiani', joined_at: iso(NOW - 94 * DAY) };
    var db = {
      isAdmin: true, regularView: false, channelJoined: true, joinClicked: false,
      vip: { active: true, plan_id: 'quarterly', plan_title: 'VIP سه‌ماهه', started_at: iso(NOW - 67 * DAY), expires_at: iso(NOW + 23 * DAY + 5 * HR) },
      xp: 1840, weekXp: 420, lastSpin: null,
      traps: [
        { id: 1, title: 'لینک اصلی من', bait: '', code: 'k7Qp2', is_default: true, created_at: iso(NOW - 94 * DAY) },
        { id: 2, title: 'عکس جدیدم رو ببین 👀', bait: 'یه عکس از سفر شمال گذاشتم، فقط برای دوستای نزدیک 😍', code: 'x9Lm4', is_default: false, created_at: iso(NOW - 12 * DAY) },
        { id: 3, title: 'نظرسنجی ناشناس', bait: 'نظرت درباره من چیه؟ کاملاً ناشناس جواب بده 🤫', code: 'p2Rt8', is_default: false, created_at: iso(NOW - 4 * DAY) }
      ],
      visitors: [], payments: [], support: [], tickets: [], users: [], jobs: {}, nextId: 1000,
      challenge: { status: 'idle', hours: 24, reward_days: 3, top: [] },
      forcedChannels: [
        { id: 'mychannel', title: 'کانال رسمی فضول‌یاب', url: '', target: 5000, joins: 3821, added_at: iso(NOW - 60 * DAY), percent: 76 },
        { id: 'funbale', title: 'کانال سرگرمی بله', url: '', target: 0, joins: 1240, added_at: iso(NOW - 20 * DAY), percent: null }
      ]
    };
    // فضول‌ها
    var t = NOW - 7 * MIN;
    for (var i = 0; i < 28; i++) {
      var fn = pick(FIRST), ln = pick(LAST), uidx = Math.floor(rnd() * USERNAMES.length);
      db.visitors.push({ id: i + 1, trap_id: rnd() < 0.5 ? 1 : (rnd() < 0.6 ? 2 : 3), user_id: 600000000 + Math.floor(rnd() * 399999999), name: fn + ' ' + ln, username: USERNAMES[uidx], count: 1 + Math.floor(rnd() * rnd() * 6), first_at: iso(t - DAY * (1 + rnd() * 6)), visited_at: iso(t) });
      t -= (i < 6 ? 40 * MIN : 5 * HR) * (0.4 + rnd());
    }
    db.payments = [
      { id: 'INV-48213', plan_title: 'VIP سه‌ماهه', amount: 129000, status: 'paid', created_at: iso(NOW - 67 * DAY) },
      { id: 'INV-39120', plan_title: 'VIP یک‌ماهه', amount: 49000, status: 'paid', created_at: iso(NOW - 98 * DAY) },
      { id: 'INV-39002', plan_title: 'VIP یک‌ماهه', amount: 49000, status: 'failed', created_at: iso(NOW - 98 * DAY - 2 * HR) }
    ];
    db.support = [
      { id: 1, from: 'user', text: 'سلام، وقتتون بخیر. دوستم روی لینک فضول‌یابم زده ولی اسمش توی لیست نیومده 🤔', created_at: iso(NOW - 2 * DAY - 3 * HR) },
      { id: 2, from: 'admin', text: 'سلام آرش جان، وقت شما هم بخیر 🌹\nلینک باید داخل خود بله باز بشه تا ثبت بشه. اگر دوستت از مرورگر باز کرده باشه، ثبت نمی‌شه.', created_at: iso(NOW - 2 * DAY - 2 * HR) },
      { id: 3, from: 'user', text: 'آهان، درست شد. ممنون از پاسخ سریعتون 🙏', media_type: null, created_at: iso(NOW - 2 * DAY - 1 * HR) },
      { id: 4, from: 'user', text: 'اسکرین‌شات خطای پرداخت', media_type: 'photo', created_at: iso(NOW - 1 * DAY - 5 * HR) },
      { id: 5, from: 'admin', text: 'بررسی شد؛ مبلغ به کیف پول بله شما برگشت داده شده ✅', created_at: iso(NOW - 1 * DAY - 4 * HR) }
    ];
    // کاربران (پنل ادمین)
    for (var j = 0; j < 34; j++) {
      var nm = pick(FIRST) + ' ' + pick(LAST);
      var isVip = rnd() < 0.3;
      db.users.push({ id: 100000000 + Math.floor(rnd() * 899999999), name: nm, username: rnd() < 0.75 ? USERNAMES[j % USERNAMES.length] || ('user' + j) : null, is_vip: isVip, vip_expires_at: isVip ? iso(NOW + (3 + rnd() * 80) * DAY) : null, level: 1 + Math.floor(rnd() * 14), xp: Math.floor(rnd() * 9000), banned: rnd() < 0.06, joined_at: iso(NOW - rnd() * 300 * DAY), last_seen: iso(NOW - rnd() * 6 * DAY), snoops: Math.floor(rnd() * 400), traps: 1 + Math.floor(rnd() * 4) });
    }
    db.users.unshift({ id: me.id, name: me.first_name + ' ' + me.last_name, username: me.username, is_vip: true, vip_expires_at: db.vip.expires_at, level: 5, xp: db.xp, banned: false, joined_at: me.joined_at, last_seen: iso(NOW), snoops: 187, traps: 3 });
    var ticketTexts = ['پرداخت کردم ولی VIP فعال نشد', 'لینکم برای بعضیا باز نمیشه', 'چطور تله جدید بسازم؟', 'گردونه امروز کار نمی‌کنه', 'پیشنهاد: امکان حذف فضول‌ها از لیست', 'ممنون بابت ربات خوبتون 🌸'];
    for (var k = 0; k < 6; k++) {
      var u = db.users[k + 3];
      db.tickets.push({ user_id: u.id, name: u.name, status: k < 4 ? 'open' : 'closed', unread: k < 3 ? 1 + (k % 2) : 0, messages: [
        { id: 1, from: 'user', text: 'سلام', created_at: iso(NOW - (k + 1) * 3 * HR - 10 * MIN) },
        { id: 2, from: 'user', text: ticketTexts[k], media_type: k === 0 ? 'photo' : null, created_at: iso(NOW - (k + 1) * 3 * HR) }
      ].concat(k >= 4 ? [{ id: 3, from: 'admin', text: 'ممنون از پیامت 🙏 حتماً بررسی می‌کنیم.', created_at: iso(NOW - (k + 1) * 2 * HR) }] : []) });
    }
    var PLANS = [
      { id: 'monthly', title: 'VIP یک‌ماهه', days: 30, price: 49000, old_price: null, badge: null },
      { id: 'quarterly', title: 'VIP سه‌ماهه', days: 90, price: 129000, old_price: 147000, badge: 'محبوب‌ترین' },
      { id: 'yearly', title: 'VIP یک‌ساله', days: 365, price: 399000, old_price: 588000, badge: 'بهترین ارزش' }
    ];
    var FEATURES = ['نمایش نام و یوزرنیم کامل فضول‌ها', 'ساخت تا ۱۰ تله اختصاصی', 'امتیاز XP دوبرابر در همه فعالیت‌ها', 'یک چرخش اضافه گردونه در روز', 'نشان طلایی در جدول برترین‌ها'];
    var SEGMENTS = [
      { label: '۲۰ XP', color: '#10b981' }, { label: '۵۰ XP', color: '#3b82f6' }, { label: '۱۰۰ XP', color: '#ec4899' }, { label: '۲۵۰ XP', color: '#8b5cf6' },
      { label: '۵۰۰ XP', color: '#f97316' }, { label: '۱٬۰۰۰ XP', color: '#eab308' }, { label: '۱ روز VIP', color: '#e09b12' }, { label: '۳ روز VIP', color: '#ef4444' }
    ];
    var PRIZES = [{ type: 'xp', amount: 20 }, { type: 'xp', amount: 50 }, { type: 'xp', amount: 100 }, { type: 'xp', amount: 250 }, { type: 'xp', amount: 500 }, { type: 'xp', amount: 1000 }, { type: 'vip', amount: 1 }, { type: 'vip', amount: 3 }];
    /* v4.7: ماموریت‌های نمونه — همان ساختار /api/missions */
    var MISSIONS_POOL = [
      { id: 'e02', name: '۱۰ کلیک', desc: 'مجموعاً ۱۰ کلیک روی لینک شما انجام شود.', xp: 50, category: 'easy', category_info: { emoji: '🟢', title: 'آسان' }, progress: { value: 7, threshold: 10, pct: 70 } },
      { id: 'e13', name: 'تنظیم لقب', desc: 'برای یکی از فضول‌هایتان یک لقب تنظیم کنید.', xp: 50, category: 'easy', category_info: { emoji: '🟢', title: 'آسان' }, progress: null },
      { id: 'g01', name: 'اولین دعوت موفق', desc: 'یک کاربر جدید با لینک تو برای اولین‌بار وارد ربات شود.', xp: 60, category: 'easy', category_info: { emoji: '🟢', title: 'آسان' }, progress: { value: 0, threshold: 1, pct: 0 } },
      { id: 'g08', name: 'زنجیرهٔ ۷ روزه', desc: 'یک هفتهٔ کامل، هر روز سر بزن.', xp: 150, category: 'medium', category_info: { emoji: '🟡', title: 'متوسط' }, progress: { value: 4, threshold: 7, pct: 57 } },
      { id: 'g19', name: '۵۰۰ XP جمع کن', desc: 'مجموع XP حاصله از کلیک، فضول و ماموریت‌ها به ۵۰۰ برسد.', xp: 60, category: 'easy', category_info: { emoji: '🟢', title: 'آسان' }, progress: { value: 320, threshold: 500, pct: 64 } },
      { id: 'm07', name: '۵۰ فضول', desc: '۵۰ فضول یکتا در دام شما بیفتند.', xp: 250, category: 'medium', category_info: { emoji: '🟡', title: 'متوسط' }, progress: { value: 23, threshold: 50, pct: 46 } },
      { id: 'h02', name: '۵۰۰ کلیک', desc: 'مجموعاً ۵۰۰ کلیک روی لینک شما انجام شود.', xp: 600, category: 'hard', category_info: { emoji: '🔴', title: 'سخت' }, progress: { value: 187, threshold: 500, pct: 37 } },
      { id: 'm12', name: '۳ پیام ناشناس', desc: '۳ پیام ناشناس به فضول‌ها بفرستید.', xp: 150, category: 'medium', category_info: { emoji: '🟡', title: 'متوسط' }, progress: { value: 1, threshold: 3, pct: 33 } },
      { id: 'g16', name: 'اولین تلهٔ اختصاصی', desc: 'یک تلهٔ اختصاصی با نام دلخواه بساز (VIP).', xp: 80, category: 'easy', category_info: { emoji: '🟢', title: 'آسان' }, progress: { value: 0, threshold: 1, pct: 0 } },
      { id: 'g11', name: '۷ جایزهٔ روزانه', desc: '۷ بار جایزهٔ روزانه بگیر.', xp: 120, category: 'medium', category_info: { emoji: '🟡', title: 'متوسط' }, progress: { value: 5, threshold: 7, pct: 71 } }
    ];
    db.missionsPage = 1;

    function err(code, status, msg, details) { return new ApiError(code, msg || ERR_TEXT[code], status, details); }
    function vipActive() { return !db.regularView && db.vip.active && new Date(db.vip.expires_at) > new Date(); }
    function isAdmin() { return db.isAdmin && !db.regularView; }
    function levelOf(xp) { var lvl = 0; while (100 * (lvl + 1) * (lvl + 2) / 2 <= xp) lvl++; var cur = 100 * lvl * (lvl + 1) / 2, nxt = 100 * (lvl + 1) * (lvl + 2) / 2; return { xp: xp, level: lvl + 1, level_xp: xp - cur, next_level_xp: nxt - cur, progress: (xp - cur) / (nxt - cur) }; }
    function trapLink(code) { return CFG.deepLinkBase + CFG.botUsername + '?start=s_' + code; }
    function visitorView(v) {
      var trap = db.traps.filter(function (x) { return x.id === v.trap_id; })[0];
      var base = { id: v.id, trap_id: v.trap_id, trap_title: trap ? trap.title : '—', count: v.count, visited_at: v.visited_at, first_at: v.first_at };
      if (vipActive()) return Object.assign(base, { masked: false, name: v.name, username: v.username, user_id: v.user_id });
      /* v4.7: غیر VIP فقط نام واقعی را می‌بیند — هم‌سو با پنل شیشه‌ای ربات */
      return Object.assign(base, { masked: true, name: v.name, username: null, user_id: null });
    }
    function vipView() {
      var active = vipActive();
      var left = active ? Math.max(0, Math.ceil((new Date(db.vip.expires_at) - Date.now()) / DAY)) : 0;
      return { active: active, plan_title: active ? db.vip.plan_title : null, expires_at: active ? db.vip.expires_at : null, days_left: left };
    }
    function spinState() {
      /* v4.7: همان ربات — چرخ شانس VIP-only و یک بار در روز */
      var active = vipActive();
      var next = new Date(); next.setHours(24, 0, 0, 0);
      var done = !!db.lastSpin;
      return { can_spin: active && !done, next_spin_at: done ? iso(next.getTime()) : null, done_today: done, vip_required: !active };
    }
    function rankOf() { return 12; }
    function meView() {
      var today = db.visitors.filter(function (v) { return Date.now() - new Date(v.visited_at) < DAY; }).length;
      return {
        user: me, is_admin: isAdmin(), demo: true,
        vip: vipView(), xp: levelOf(db.xp), rank: rankOf(),
        streak: { count: db.streakCount || 4, shield: vipActive(), days_to_weekly: 3 },
        snoop: { today: 2, total: 96, distinct: 96, link: trapLink(db.traps[0].code) },
        wheel: spinState(),
        channels: { joined: db.channelJoined, required: db.channelJoined ? [] : channelList() },
        recent: db.visitors.slice(0, 3).map(visitorView),
        unread_support: 0
      };
    }
    function channelList() { return [{ id: -100123, title: 'کانال رسمی فضول‌یاب', username: 'fozoolyab_news', url: CFG.deepLinkBase + 'fozoolyab_news', joined: db.joinClicked }]; }
    function weekChart() {
      var out = [];
      for (var d = 6; d >= 0; d--) {
        var start = new Date(); start.setHours(0, 0, 0, 0); start = start.getTime() - d * DAY;
        var c = db.visitors.filter(function (v) { var x = new Date(v.visited_at).getTime(); return x >= start && x < start + DAY; }).length;
        out.push({ date: iso(start), count: c + [3, 5, 2, 7, 4, 6, 0][6 - d] });
      }
      return out;
    }
    function lb(period) {
      var rows = db.users.filter(function (u) { return u.id !== me.id; }).slice(0, 19).map(function (u) { return { name: u.name, level: u.level, xp: period === 'week' ? Math.floor(u.xp / 9) + 30 : u.xp, is_vip: u.is_vip }; });
      rows.sort(function (a, b) { return b.xp - a.xp; });
      var myRank = period === 'week' ? 7 : 12;
      var meRow = { name: me.first_name + ' ' + me.last_name, level: levelOf(db.xp).level, xp: period === 'week' ? db.weekXp : db.xp, is_vip: vipActive(), is_me: true };
      rows.splice(myRank - 1, 0, meRow);
      // اطمینان از ترتیب نزولی
      for (var i = 1; i < rows.length; i++) if (rows[i].xp > rows[i - 1].xp) rows[i].xp = Math.max(0, rows[i - 1].xp - Math.floor(3 + i * 2));
      rows.forEach(function (r, i) { r.rank = i + 1; });
      var top = rows[myRank - 2];
      return { period: period, items: rows, size: 20, participants: 134,
        me: { rank: myRank, xp: meRow.xp, name: meRow.name, level: meRow.level, gap: top ? top.xp - meRow.xp : null, is_vip: meRow.is_vip, hidden: !!(period === 'week' ? db.hideWeek : db.hideAll) } };
    }
    // ---- چت ناشناس (دمو) ----
    db.anon = [
      { token: 'd1', name: 'کاربر ناشناس ۱', known: false, masked: true, avatar: null, last_text: 'سلام! رباتت خیلی باحاله 😄', last_at: iso(NOW - 40 * MIN), last_from_me: false, count_in: 2, count_out: 0, messages: [
        { mine: false, text: 'سلام! رباتت خیلی باحاله 😄', created_at: iso(NOW - 2 * HR) },
        { mine: false, text: 'راستش نمی‌دونم کی هستم برات 😅', created_at: iso(NOW - 40 * MIN) }] },
      { token: 'd2', name: 'م*** ک***', known: true, masked: true, avatar: null, last_text: 'ممنون بابت راهنمایی', last_at: iso(NOW - 5 * HR), last_from_me: true, count_in: 1, count_out: 2, messages: [
        { mine: false, text: 'سلام، چطور تله بسازم؟', created_at: iso(NOW - 6 * HR) },
        { mine: true, text: 'از تب فضول‌یاب، دکمهٔ تله جدید 😉', created_at: iso(NOW - 5.5 * HR) },
        { mine: true, text: 'خوش آمدی!', created_at: iso(NOW - 5 * HR) }] }
    ];
    db.settingsDemo = {
      leaderboard_size: 20, wheel_enabled: 1, maintenance_mode: 0, smart_reminder_enabled: 1, weekly_report_enabled: 1,
      weekly_report_day: 6, weekly_report_hour: 21, trial_days: 3, auto_backup_enabled: 1,
      vip_price_30: 490000, vip_price_90: 1290000, vip_price_365: 3990000
    };
    db.gifts = [{ code: 'WELCOME10', days: 10, max_uses: 100, used_count: 34, created_at: iso(NOW - 12 * DAY), status: 'open' }];
    db.transactions = db.users.slice(0, 6).map(function (u, i) {
      return { id: i + 1, user: { id: u.id, name: u.name, username: u.username, avatar: null }, type: ['purchase', 'gift', 'admin_vip_add', 'wheel', 'trial', 'admin_vip_remove'][i], type_fa: ['خرید VIP', 'کد هدیه', 'افزودن توسط ادمین', 'گردونه شانس', 'هدیهٔ ورود', 'کاهش توسط ادمین'][i], amount: [49000, 0, 0, 0, 0, 0][i], days: [30, 7, 14, 1, 3, -5][i], created_at: iso(NOW - i * 2 * DAY) };
    });
    db.anonLogs = db.users.slice(0, 8).map(function (u, i) {
      return { sender: { id: u.id, name: u.name, username: u.username, avatar: null }, receiver: { id: db.users[(i + 3) % db.users.length].id, name: db.users[(i + 3) % db.users.length].name, username: null, avatar: null }, text: ['سلام، لینکت رو دیدم 👀', 'می‌خواستم ناشناس بگم که خیلی دوستت دارم 💛', 'کی هستی؟ 🤔', 'یه سؤال داشتم...', 'عالی بود مرسی', 'بیا هم بازی کنیم', 'دمت گرم', 'فال بده 😄'][i], created_at: iso(NOW - i * 3 * HR) };
    });
    function requireAdmin() { if (!isAdmin()) throw err('FORBIDDEN', 403); }
    function findUser(id) { var u = db.users.filter(function (x) { return String(x.id) === String(id); })[0]; if (!u) throw err('NOT_FOUND', 404, 'کاربر پیدا نشد.'); return u; }
    function adminUserView(u) {
      var vip = u.is_vip && new Date(u.vip_expires_at) > new Date();
      return { user: { id: u.id, name: u.name, username: u.username, joined_at: u.joined_at, last_seen: u.last_seen }, banned: u.banned, warnings: u.warns || 0, vip: { active: vip, expires_at: vip ? u.vip_expires_at : null, days_left: vip ? Math.ceil((new Date(u.vip_expires_at) - Date.now()) / DAY) : 0 }, xp: levelOf(u.xp), stats: { snoops: u.snoops, traps: u.traps, spins: Math.floor(u.xp / 120) }, payments: u.is_vip ? [{ id: 'INV-' + (u.id % 100000), plan_title: 'VIP یک‌ماهه', amount: 49000, status: 'paid', created_at: iso(Date.now() - 20 * DAY) }] : [] };
    }

    var R = [
      ['GET', /^\/me$/, function () { return meView(); }],
      ['GET', /^\/channels\/check$/, function () {
        if (db.joinClicked) db.channelJoined = true;
        return { joined: db.channelJoined, channels: channelList() };
      }],
      ['POST', /^\/demo\/join-click$/, function () { db.joinClicked = true; return { ok: true }; }],
      ['GET', /^\/snoop\/summary$/, function () {
        var counts = {}; db.visitors.forEach(function (v) { counts[v.trap_id] = (counts[v.trap_id] || 0) + v.count; });
        var week = weekChart();
        return {
          link: trapLink(db.traps[0].code),
          traps: db.traps.map(function (tr) { return Object.assign({}, tr, { link: trapLink(tr.code), visits: (counts[tr.id] || 0) + (tr.is_default ? 96 : 0) }); }),
          stats: { today: week[6].count, week: week.reduce(function (s, x) { return s + x.count; }, 0), total: 96, chart: week },
          limits: { max_traps: vipActive() ? 3 : 0, custom_traps: db.traps.filter(function (x) { return !x.is_default; }).length, reveal: vipActive(), vip_required: !vipActive() }
        };
      }],
      ['GET', /^\/snoop\/radar$/, function () {
        var hours = []; for (var h = 0; h < 24; h++) hours.push({ hour: h, count: Math.floor(rnd() * (h >= 20 && h <= 23 ? 14 : 5)) });
        return { hour_chart: hours, best_hours: [{ hour: 21, count: 13 }, { hour: 22, count: 11 }, { hour: 23, count: 9 }],
                 best_trap: { code: db.traps[0].code, title: db.traps[0].title, snoops: 34, clicks: 61 },
                 me_last_week: 42, avg_last_week: 18.5, diff_pct: 127 };
      }],
      ['GET', /^\/snoop\/visitors/, function (b, m, q) {
        var list = db.visitors; var tid = q.get('trap_id'); if (tid) list = list.filter(function (v) { return String(v.trap_id) === tid; });
        var cursor = parseInt(q.get('cursor') || '0', 10), size = 15;
        return { items: list.slice(cursor, cursor + size).map(visitorView), next_cursor: cursor + size < list.length ? String(cursor + size) : null, total: list.length };
      }],
      ['POST', /^\/snoop\/traps$/, function (b) {
        var title = String((b && b.title) || '').trim(), bait = String((b && b.bait) || '').trim();
        if (title.length < 2 || title.length > 40) throw err('VALIDATION_ERROR', 422, 'عنوان تله باید بین ۲ تا ۴۰ کاراکتر باشد.');
        /* v4.7: ساخت تله اختصاصی فقط برای VIP — هم‌سو با پنل شیشه‌ای */
        if (!vipActive()) throw err('VIP_REQUIRED', 403, 'ساخت تلهٔ اختصاصی فقط برای اعضای VIP است.');
        var custom = db.traps.filter(function (x) { return !x.is_default; }).length;
        if (custom >= 3) throw err('LIMIT_REACHED', 403, 'به سقف ۳ تله رسیده‌اید.');
        var code = Math.random().toString(36).slice(2, 7);
        var tr = { id: ++db.nextId, title: title, bait: bait.slice(0, 200), code: code, is_default: false, created_at: iso(Date.now()) };
        db.traps.push(tr); return Object.assign({}, tr, { link: trapLink(code), visits: 0 });
      }],
      ['DELETE', /^\/snoop\/traps\/(\d+)$/, function (b, m) {
        var id = parseInt(m[1], 10); var tr = db.traps.filter(function (x) { return x.id === id; })[0];
        if (!tr) throw err('NOT_FOUND', 404); if (tr.is_default) throw err('VALIDATION_ERROR', 422, 'لینک اصلی قابل حذف نیست.');
        db.traps = db.traps.filter(function (x) { return x.id !== id; }); return { deleted: true };
      }],
      ['GET', /^\/vip\/plans$/, function () { return { status: vipView(), plans: PLANS, features: FEATURES, payments: db.payments, comparison: { singles: 5, single_price: 3000, singles_total: 15000, month_price: 4900, save_pct: 67 } }; }],
      ['POST', /^\/vip\/purchase$/, function (b) {
        var plan = PLANS.filter(function (p) { return p.id === (b && b.plan_id); })[0]; if (!plan) throw err('VALIDATION_ERROR', 422, 'پلن نامعتبر است.');
        db.payments.unshift({ id: 'INV-' + Math.floor(50000 + Math.random() * 9999), plan_title: plan.title, amount: plan.price, status: 'pending', created_at: iso(Date.now()) });
        return { invoice_sent: true, plan: plan, chat_url: Platform.botLink() };
      }],
      ['GET', /^\/leaderboard/, function (b, m, q) { return lb(q.get('period') === 'week' ? 'week' : 'all'); }],
      ['POST', /^\/leaderboard\/visibility$/, function (b) {
        if ((b && b.period) === 'week') db.hideWeek = !!b.hidden; else db.hideAll = !!b.hidden;
        return { period: (b && b.period) || 'week', hidden: !!b.hidden };
      }],
      ['GET', /^\/profile$/, function () {
        var TITLES = [[1, 'فضول تازه‌وارد', '🐣'], [3, 'کنجکاو سیری‌ناپذیر', '👀'], [10, 'فضول حرفه‌ای', '🎩'], [25, 'سرفضول', '🎖️'], [50, 'استاد فضول‌ها', '🎓'], [100, 'پادشاه فضول‌ها', '👑']];
        var lvl = levelOf(db.xp).level;
        return {
          display_name: db.displayName || null, account_name: me.name,
          title: db.titleKey ? { key: db.titleKey, title: TITLES.filter(function (t) { return t[0] === db.titleKey; })[0][1], emoji: '🎩', custom: true } : { key: 1, title: 'فضول تازه‌وارد', emoji: '🐣', custom: false },
          titles: TITLES.map(function (t) { return { key: t[0], title: t[1], emoji: t[2], unlocked: lvl >= t[0], active: db.titleKey ? db.titleKey === t[0] : t[0] === 1 }; }),
          badges: [
            { key: 'first_snoop', emoji: '🔍', title: 'اولین شکار', desc: 'اولین فضولی که در دامت افتاد', earned: true },
            { key: 'snoop_25', emoji: '🎯', title: 'شکارچی ۲۵', desc: '۲۵ فضول یکتا در تله‌هایت', earned: db.visitors.length >= 25, goal: 25 },
            { key: 'inviter', emoji: '🤝', title: 'دعوت‌کننده', desc: 'حداقل یک کاربر جدید با لینک تو وارد ربات شد', earned: true },
            { key: 'streak_7', emoji: '🔥', title: 'زنجیرهٔ آتشین', desc: 'استریک ۷ روزهٔ پیاپی', earned: false, goal: 7 },
            { key: 'spinner', emoji: '🎰', title: 'چرخان', desc: '۱۰ بار چرخ شانس', earned: false, goal: 10 },
            { key: 'masked', emoji: '🎭', title: 'نقاب‌دار', desc: 'نقاب کارآگاهی اختصاصی ساخت', earned: false },
            { key: 'vip', emoji: '👑', title: 'کارت طلایی', desc: 'عضو حلقهٔ ویژهٔ کارآگاهان', earned: vipActive() }
          ]
        };
      }],
      ['POST', /^\/profile\/edit$/, function (b) {
        if (b && b.reset_name) db.displayName = null; else if (b && b.display_name) db.displayName = String(b.display_name);
        if (b && b.reset_title) db.titleKey = null; else if (b && b.active_title) db.titleKey = parseInt(b.active_title, 10);
        return { saved: true };
      }],
      ['GET', /^\/chat\/conversations$/, function () { return { items: db.anon }; }],
      ['GET', /^\/chat\/thread\/(\w+)$/, function (b, m) {
        var c = db.anon.filter(function (x) { return x.token === m[1]; })[0];
        if (!c) throw err('NOT_FOUND', 404, 'این گفتگو پیدا نشد.');
        return { partner: { token: c.token, known: c.known, masked: c.masked, name: c.name, avatar: c.avatar }, messages: c.messages, can_send: true };
      }],
      ['POST', /^\/chat\/send$/, function (b) {
        var c = db.anon.filter(function (x) { return x.token === (b && b.token); })[0];
        if (!c) throw err('NOT_FOUND', 404, 'این گفتگو پیدا نشد.');
        var text = String((b && b.text) || '').trim(); if (!text) throw err('VALIDATION_ERROR', 422, 'متن پیام خالی است.');
        var msg = { mine: true, text: text, created_at: iso(Date.now()) };
        c.messages.push(msg); c.last_text = text; c.last_at = msg.created_at; c.last_from_me = true; c.count_out++;
        return { sent: true, created_at: msg.created_at };
      }],
      ['POST', /^\/snoop\/visitors\/(\d+)\/anon-token$/, function (b, m) {
        if (!vipActive()) throw err('FORBIDDEN', 403, 'برای پیام ناشناس به فضول‌ها ابتدا VIP فعال کنید.');
        var uid = parseInt(m[1], 10);
        var t = 'v' + uid;
        if (!db.anon.filter(function (x) { return x.token === t; }).length) {
          var u = findUser(uid);
          db.anon.unshift({ token: t, name: mask(u.name), known: true, masked: true, avatar: null, last_text: '', last_at: iso(Date.now()), last_from_me: false, count_in: 0, count_out: 0, messages: [] });
        }
        return { token: t };
      }],
      ['GET', /^\/wheel$/, function () { var s = spinState(); return Object.assign(s, { segments: SEGMENTS }); }],
      ['POST', /^\/wheel\/spin$/, function () {
        /* v4.7: همان ربات — فقط VIP، بدون پاداش دوبرابر */
        if (!vipActive()) throw err('VIP_REQUIRED', 403, 'چرخ شانس فقط برای اعضای VIP است!');
        if (db.lastSpin) throw err('COOLDOWN', 429, 'فرصت امروزت تمام شده — فردا بیا!');
        var weights = [28, 24, 19, 13, 8, 4, 3, 1], total = weights.reduce(function (a, c) { return a + c; }, 0), r = Math.random() * total, idx = 0;
        for (; idx < weights.length; idx++) { r -= weights[idx]; if (r <= 0) break; }
        idx = Math.min(idx, 7);
        var pr = PRIZES[idx]; db.lastSpin = Date.now();
        if (pr.type === 'xp') { db.xp += pr.amount; db.weekXp += pr.amount; }
        if (pr.type === 'vip') { var base = vipActive() ? new Date(db.vip.expires_at).getTime() : Date.now(); db.vip.active = true; db.vip.expires_at = iso(base + pr.amount * DAY); }
        var label = pr.type === 'xp' ? fa(pr.amount) + ' امتیاز XP' : fa(pr.amount) + ' روز اشتراک VIP';
        var nxt = new Date(); nxt.setHours(24, 0, 0, 0);
        return { index: idx, prize: { type: pr.type, amount: pr.amount, label: label, vip_doubled: false }, next_spin_at: iso(nxt.getTime()), xp: levelOf(db.xp) };
      }],
      /* ---- v4.7: ماموریت‌ها (دمو) ---- */
      ['GET', /^\/missions$/, function (b, m, q) {
        var p = Math.max(1, parseInt(q.get('page') || '1', 10) || 1);
        var start = (p - 1) * 3 % MISSIONS_POOL.length;
        var tasks = MISSIONS_POOL.slice(start, start + 3);
        if (tasks.length < 3) tasks = tasks.concat(MISSIONS_POOL.slice(0, 3 - tasks.length));
        return { page: p, tasks: tasks, total_remaining: 204 - 34, progress: { done: 34, total: 204, pct: 17 } };
      }],
      ['GET', /^\/missions\/([a-z0-9]+)$/, function (b, m) {
        var t = MISSIONS_POOL.filter(function (x) { return x.id === m[1]; })[0];
        if (!t) throw err('NOT_FOUND', 404, 'ماموریت پیدا نشد.');
        return Object.assign({}, t, { done: false });
      }],
      /* ---- v4.7: پاداش‌ها (دمو) ---- */
      ['GET', /^\/rewards$/, function () {
        return {
          daily: { done: !!db.dailyClaimed, streak: db.dailyClaimed ? 5 : 4, bonus_pct: 40, total_claims: 23,
                   prizes: [{ label: '۳۰ XP', type: 'xp', value: 30 }, { label: '۶۰ XP', type: 'xp', value: 60 }, { label: '۱۰۰ XP', type: 'xp', value: 100 }, { label: '۲۰۰ XP', type: 'xp', value: 200 }, { label: '۵۰۰ XP', type: 'xp', value: 500 }, { label: '۱٬۰۰۰ XP', type: 'xp', value: 1000 }, { label: '۱ روز VIP', type: 'vip', value: 1 }] },
          gift_codes: [{ code: 'WELCOME10', days: 10, remaining: 66 }],
          wheel: spinState()
        };
      }],
      ['POST', /^\/rewards\/claim$/, function () {
        if (db.dailyClaimed) throw err('ALREADY_CLAIMED', 429, 'جایزهٔ امروز را قبلاً گرفته‌ای؛ فردا دوباره بیا!');
        db.dailyClaimed = true; db.xp += 42;
        return { prize: { type: 'xp', amount: 42, label: '۴۲ XP', bonus_pct: 40 }, streak: 5, milestone_vip_days: 0,
                 state: { done: true, streak: 5, bonus_pct: 50, total_claims: 24, prizes: [] }, xp: levelOf(db.xp) };
      }],
      ['POST', /^\/gifts\/redeem$/, function (b) {
        var code = String((b && b.code) || '').trim().toUpperCase();
        if (code !== 'WELCOME10') throw err('GIFT_INVALID', 404, 'کد نامعتبر است.');
        if (db.giftRedeemed) throw err('GIFT_ALREADY_USED', 409, 'شما قبلاً این کد را استفاده کرده‌اید.');
        db.giftRedeemed = true;
        return { days: 10, vip: vipView() };
      }],
      ['GET', /^\/support\/messages$/, function () { return { ticket: { status: 'open' }, messages: db.support }; }],
      ['POST', /^\/support\/messages$/, function (b) {
        var text = String((b && b.text) || '').trim(); if (!text) throw err('VALIDATION_ERROR', 422, 'متن پیام خالی است.');
        if (text.length > 2000) throw err('VALIDATION_ERROR', 422, 'متن پیام حداکثر ۲۰۰۰ کاراکتر است.');
        var msg = { id: ++db.nextId, from: 'user', text: text, created_at: iso(Date.now()) }; db.support.push(msg);
        setTimeout(function () { db.support.push({ id: ++db.nextId, from: 'admin', text: 'پیامت به دست تیم پشتیبانی رسید ✅\nبه‌زودی همین‌جا و در چت بله جواب می‌دیم.', created_at: iso(Date.now()) }); }, 3500);
        return msg;
      }],
      ['GET', /^\/admin\/stats$/, function () {
        requireAdmin(); var chart = [];
        for (var d = 13; d >= 0; d--) {
          var dl = new Date(Date.now() - d * DAY).toISOString().slice(0, 10);
          chart.push({ date: iso(Date.now() - d * DAY), day_local: dl, new_users: Math.floor(180 + Math.sin(d / 2) * 70 + (13 - d) * 9 + rnd() * 40), snoops: Math.floor(6000 + rnd() * 4000), anon: Math.floor(30 + rnd() * 40) });
        }
        return { users_total: 48210, users_today: 312, users_active_today: 1893, users_week: 2140, vip_active: 1873, revenue_month: 61450000, snoops_today: 9832, anon_today: 41, open_tickets: db.tickets.filter(function (x) { return x.status === 'open'; }).length, banned: 214, chart: chart,
          users_month: 5480, users_week_active: 9120, vip_expiring_7d: 128, vip_revenue_total: 412300000, vip_ever: 3120, traps_total: 8934, anon_total: 48120, spins_total: 31200,
          challenge_status: db.challenge };
      }],
      ['GET', /^\/admin\/challenge$/, function () { requireAdmin(); return clone(db.challenge); }],
      ['POST', /^\/admin\/challenge$/, function (b) {
        requireAdmin();
        if ((b.action || '') === 'start') {
          db.challenge = { status: 'scheduled', hours: b.hours || 24, reward_days: b.reward_days || 3,
            reward_type: b.reward_type || 'vip', reward_amount: b.reward_amount || 0,
            remaining_sec: 3600, start_at: iso(Date.now() + DAY), end_at: iso(Date.now() + DAY + (b.hours || 24) * 3600000), top: [] };
        } else if ((b.action || '') === 'cancel') {
          db.challenge = { status: 'cancelled', hours: 24, reward_days: 3, reward_type: 'vip', reward_amount: 0, top: [] };
        }
        return clone(db.challenge);
      }],
      ['GET', /^\/admin\/forced-channels$/, function () {
        requireAdmin(); return { enabled: true, items: db.forcedChannels };
      }],
      ['POST', /^\/admin\/forced-channels$/, function (b) {
        requireAdmin(); var cid = String((b.channel_id || '')).replace(/^@/, '').trim();
        if (cid.length < 3) throw err('VALIDATION_ERROR', 422, 'شناسهٔ کانال معتبر نیست.');
        if (db.forcedChannels.filter(function (c) { return c.id === cid; }).length) throw err('VALIDATION_ERROR', 422, 'این کانال قبلاً اضافه شده است.');
        db.forcedChannels.push({ id: cid, title: (b.title || cid), url: '', target: Math.max(0, parseInt(b.target || '0', 10)), joins: Math.floor(rnd() * 900), added_at: iso(Date.now()), percent: null });
        return { enabled: true, items: db.forcedChannels };
      }],
      ['DELETE', /^\/admin\/forced-channels\/(.+)$/, function (b, m) {
        requireAdmin(); var cid = decodeURIComponent(m[1]);
        db.forcedChannels = db.forcedChannels.filter(function (c) { return c.id !== cid; });
        return { enabled: true, items: db.forcedChannels };
      }],
      ['POST', /^\/admin\/ad-broadcast$/, function (b) {
        requireAdmin(); var u = String((b.url || '')).trim();
        if (!/^https?:\/\//i.test(u)) throw err('VALIDATION_ERROR', 422, 'لینک باید با http:// یا https:// شروع شود.');
        if ((b.stage || '') === 'preview') return { preview: true, targets: 48210 };
        var id = 'ad-' + Date.now();
        db.jobs[id] = { id: id, target: 'ad', text_preview: '📣 پیام تبلیغ با دکمه‌های لینک', status: 'running', total: 48210, sent: 0, failed: 0, created_at: iso(Date.now()) };
        return { job_id: id, total: 48210 };
      }],
      ['GET', /^\/admin\/anon-logs$/, function (b, m, q) {
        requireAdmin();
        var s = (q.get('q') || '').trim().toLowerCase();
        var list = s ? db.anonLogs.filter(function (x) { return (x.sender.name || '').indexOf(s) >= 0 || (x.text || '').indexOf(s) >= 0; }) : db.anonLogs;
        return { items: list.slice(0, 20), total: list.length, page: 1, pages: 1, stats: { total: list.length, today: 6, last_24h: 11 } };
      }],
      ['GET', /^\/admin\/settings$/, function () {
        requireAdmin();
        var META = { leaderboard_size: ['تعداد ردیف‌های جدول برترین‌ها', 'int'], wheel_enabled: ['گردونه شانس', 'bool'], maintenance_mode: ['حالت نگهداری (فقط ادمین)', 'bool'], smart_reminder_enabled: ['یادآور هوشمند', 'bool'], weekly_report_enabled: ['گزارش هفتگی ادمین', 'bool'], weekly_report_day: ['روز گزارش هفتگی', 'int'], weekly_report_hour: ['ساعت گزارش هفتگی', 'int'], trial_days: ['هدیهٔ ورود (روز VIP)', 'int'], auto_backup_enabled: ['بکاپ خودکار شبانه', 'bool'], vip_price_30: ['قیمت VIP یک‌ماهه', 'price'], vip_price_90: ['قیمت VIP سه‌ماهه', 'price'], vip_price_365: ['قیمت VIP یک‌ساله', 'price'] };
        return { items: Object.keys(META).map(function (k) { return { key: k, label: META[k][0], type: META[k][1], value: String(db.settingsDemo[k]) }; }) };
      }],
      ['POST', /^\/admin\/settings$/, function (b) {
        requireAdmin(); var k = b && b.key; if (!(k in db.settingsDemo)) throw err('VALIDATION_ERROR', 422, 'این تنظیم قابل تغییر نیست.');
        db.settingsDemo[k] = typeof b.value === 'boolean' ? (b.value ? 1 : 0) : (isNaN(parseInt(b.value, 10)) ? b.value : parseInt(b.value, 10));
        return { key: k };
      }],
      ['GET', /^\/admin\/gifts$/, function () { requireAdmin(); return { items: db.gifts }; }],
      ['POST', /^\/admin\/gifts$/, function (b) {
        requireAdmin(); var days = parseInt(b.days, 10), uses = parseInt(b.max_uses, 10);
        if (!(days > 0) || !(uses > 0)) throw err('VALIDATION_ERROR', 422, 'مقادیر معتبر وارد کنید.');
        var code = (b.code || '').trim().toUpperCase() || ('GIFT' + Math.floor(100000 + Math.random() * 899999));
        if (db.gifts.filter(function (g) { return g.code === code; }).length) throw err('VALIDATION_ERROR', 422, 'این کد قبلاً ساخته شده است.');
        var g = { code: code, days: days, max_uses: uses, used_count: 0, created_at: iso(Date.now()), status: 'open' };
        db.gifts.unshift(g); return g;
      }],
      ['GET', /^\/admin\/transactions$/, function () { requireAdmin(); return { items: db.transactions, total: db.transactions.length, page: 1, pages: 1 }; }],
      ['GET', /^\/admin\/users$/, function (b, m, q) {
        requireAdmin(); var s = (q.get('q') || '').trim().toLowerCase(), f = q.get('filter') || 'all', sort = q.get('sort') || 'recent';
        var list = db.users.filter(function (u) {
          if (f === 'vip' && !u.is_vip) return false; if (f === 'banned' && !u.banned) return false;
          if (!s) return true; return u.name.indexOf(s) >= 0 || String(u.id).indexOf(s) >= 0 || (u.username || '').toLowerCase().indexOf(s.replace('@', '')) >= 0;
        });
        var S = {
          recent: function (a, c) { return (c.last_seen || '').localeCompare(a.last_seen || ''); },
          joined: function (a, c) { return (c.joined_at || '').localeCompare(a.joined_at || ''); },
          level: function (a, c) { return (c.level || 0) - (a.level || 0) || (c.xp || 0) - (a.xp || 0); },
          snoops: function (a, c) { return (c.snoops || 0) - (a.snoops || 0); },
          traps: function (a, c) { return (c.traps || 0) - (a.traps || 0); },
          vip: function (a, c) { return (c.is_vip ? 1 : 0) - (a.is_vip ? 1 : 0); },
          name: function (a, c) { return (a.name || '').localeCompare(c.name || '', 'fa'); }
 };
        list = list.slice().sort(S[sort] || S.recent);
        return { sort: sort, items: list.slice(0, 50).map(function (u) { return { id: u.id, name: u.name, username: u.username, is_vip: u.is_vip, banned: u.banned, level: u.level, xp: u.xp || 0, joined_at: u.joined_at }; }), total: list.length };
      }],
      ['GET', /^\/admin\/users\/(\d+)$/, function (b, m) { requireAdmin(); return adminUserView(findUser(m[1])); }],
      ['POST', /^\/admin\/users\/(\d+)\/vip$/, function (b, m) {
        requireAdmin(); var u = findUser(m[1]); var days = parseInt((b && b.days) || 0, 10);
        var curExp = u.is_vip && new Date(u.vip_expires_at) > new Date() ? new Date(u.vip_expires_at).getTime() : Date.now();
        if (b.action === 'add') { if (!(days > 0 && days <= 3650)) throw err('VALIDATION_ERROR', 422, 'تعداد روز باید بین ۱ تا ۳۶۵۰ باشد.'); u.is_vip = true; u.vip_expires_at = iso(curExp + days * DAY); }
        else if (b.action === 'reduce') { if (!(days > 0)) throw err('VALIDATION_ERROR', 422, 'تعداد روز نامعتبر است.'); var ne = curExp - days * DAY; if (ne <= Date.now()) { u.is_vip = false; u.vip_expires_at = null; } else u.vip_expires_at = iso(ne); }
        else if (b.action === 'cancel') { u.is_vip = false; u.vip_expires_at = null; }
        else throw err('VALIDATION_ERROR', 422);
        if (u.id === me.id) { db.vip.active = u.is_vip; if (u.vip_expires_at) db.vip.expires_at = u.vip_expires_at; }
        return adminUserView(u);
      }],
      ['POST', /^\/admin\/users\/(\d+)\/ban$/, function (b, m) { requireAdmin(); var u = findUser(m[1]); if (u.id === me.id) throw err('VALIDATION_ERROR', 422, 'نمی‌توانید خودتان را مسدود کنید.'); u.banned = !!b.banned; return adminUserView(u); }],
      /* v4.7: اخطار به کاربر + بازنشانی اخطارها (دمو) */
      ['POST', /^\/admin\/users\/(\d+)\/warn$/, function (b, m) {
        requireAdmin(); var u = findUser(m[1]); if (u.id === me.id) throw err('VALIDATION_ERROR', 422, 'نمی‌توانید به خودتان اخطار بدهید.');
        u.warns = (u.warns || 0) + 1;
        var banned = false;
        if (u.warns >= 3) { u.banned = true; banned = true; }
        return Object.assign(adminUserView(u), { warn: { count: u.warns, banned: banned } });
      }],
      ['POST', /^\/admin\/users\/(\d+)\/reset-warnings$/, function (b, m) { requireAdmin(); var u = findUser(m[1]); u.warns = 0; return adminUserView(u); }],
      ['POST', /^\/admin\/users\/(\d+)\/message$/, function (b, m) { requireAdmin(); findUser(m[1]); if (!b || !String(b.text || '').trim()) throw err('VALIDATION_ERROR', 422, 'متن پیام خالی است.'); return { sent: true }; }],
      ['GET', /^\/admin\/broadcast\/meta$/, function () {
        requireAdmin(); var jobs = Object.keys(db.jobs).map(function (k) { return db.jobs[k]; }).reverse();
        return { counts: { all: 48210, vip: 1873, free: 46337 }, jobs: jobs.concat([{ id: 'b-1720', target: 'all', text_preview: '🎉 قابلیت تله‌های اختصاصی اضافه شد! همین حالا امتحانش کن.', status: 'done', total: 47880, sent: 47102, failed: 778, created_at: iso(NOW - 3 * DAY) }]) };
      }],
      ['POST', /^\/admin\/broadcast$/, function (b) {
        requireAdmin(); var text = String((b && b.text) || '').trim(); if (text.length < 3) throw err('VALIDATION_ERROR', 422, 'متن پیام خیلی کوتاه است.');
        var total = { all: 48210, vip: 1873, free: 46337 }[b.target] || 0; var id = 'b-' + Date.now();
        db.jobs[id] = { id: id, target: b.target, text_preview: text.slice(0, 80), status: 'running', total: total, sent: 0, failed: 0, created_at: iso(Date.now()) };
        return { job_id: id, total: total };
      }],
      ['GET', /^\/admin\/broadcast\/([\w-]+)$/, function (b, m) {
        requireAdmin(); var j = db.jobs[m[1]]; if (!j) throw err('NOT_FOUND', 404);
        if (j.status === 'running') { var step = Math.ceil(j.total / 5); var s = Math.min(j.total, j.sent + j.failed + step); j.failed = Math.floor(s * 0.014); j.sent = s - j.failed; if (s >= j.total) j.status = 'done'; }
        return j;
      }],
      ['GET', /^\/admin\/tickets$/, function () {
        requireAdmin();
        return { items: db.tickets.map(function (tk) { var last = tk.messages[tk.messages.length - 1]; return { user_id: tk.user_id, name: tk.name, status: tk.status, unread: tk.unread, last_text: last.media_type ? '📷 تصویر' : last.text, last_at: last.created_at, last_from: last.from }; }) };
      }],
      ['GET', /^\/admin\/tickets\/(\d+)$/, function (b, m) { requireAdmin(); var tk = db.tickets.filter(function (x) { return String(x.user_id) === m[1]; })[0]; if (!tk) throw err('NOT_FOUND', 404); tk.unread = 0; return { user_id: tk.user_id, name: tk.name, status: tk.status, messages: tk.messages }; }],
      ['POST', /^\/admin\/tickets\/(\d+)\/reply$/, function (b, m) {
        requireAdmin(); var tk = db.tickets.filter(function (x) { return String(x.user_id) === m[1]; })[0]; if (!tk) throw err('NOT_FOUND', 404);
        var text = String((b && b.text) || '').trim(); if (!text) throw err('VALIDATION_ERROR', 422, 'متن پاسخ خالی است.');
        var msg = { id: ++db.nextId, from: 'admin', text: text, created_at: iso(Date.now()) }; tk.messages.push(msg); tk.status = 'open'; return msg;
      }],
      ['POST', /^\/admin\/tickets\/(\d+)\/close$/, function (b, m) { requireAdmin(); var tk = db.tickets.filter(function (x) { return String(x.user_id) === m[1]; })[0]; if (!tk) throw err('NOT_FOUND', 404); tk.status = 'closed'; return { status: 'closed' }; }],
      ['GET', /^\/admin\/backup$/, function () { requireAdmin(); var d = new Date(); d.setHours(3, 0, 0, 0); if (d > new Date()) d = new Date(d.getTime() - DAY); return { last_backup_at: d.toISOString(), db_size_bytes: 19293184, schedule: 'هر شب ساعت ۰۳:۰۰ (به وقت تهران)', users: 48210, path: '/data/bot_data.db' }; }],
      ['POST', /^\/admin\/backup$/, function () { requireAdmin(); return { sent: true, filename: 'backup-' + new Date().toISOString().slice(0, 10) + '.db', size_bytes: 19293184 }; }]
    ];
    return {
      db: db,
      handle: function (method, fullPath, body) {
        var parts = fullPath.split('?'), path = parts[0], q = new URLSearchParams(parts[1] || '');
        return sleep(220 + Math.random() * 380).then(function () {
          if (!State.online) throw err('OFFLINE', 0);
          for (var i = 0; i < R.length; i++) {
            if (R[i][0] !== method) continue;
            var m = path.match(R[i][1]);
            if (m) return clone(R[i][2](body || {}, m, q));
          }
          throw err('NOT_FOUND', 404);
        });
      }
    };
  })();

  /* ===================== Theme ===================== */
  var Theme = {
    pref: LS.get('theme', 'auto'),
    init: function () {
      var self = this;
      this.apply();
      Platform.onEvent('themeChanged', function () { self.apply(); });
      if (window.matchMedia) { var mq = window.matchMedia('(prefers-color-scheme: dark)'); var cb = function () { self.apply(); }; if (mq.addEventListener) mq.addEventListener('change', cb); else if (mq.addListener) mq.addListener(cb); }
    },
    set: function (p) { this.pref = p; LS.set('theme', p); this.apply(); },
    resolved: function () {
      if (this.pref !== 'auto') return this.pref;
      var cs = Platform.colorScheme(); if (cs === 'dark' || cs === 'light') return cs;
      return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    },
    apply: function () {
      var root = document.documentElement, mode = this.resolved();
      root.setAttribute('data-theme', mode);
      var map = { bg_color: '--surface', secondary_bg_color: '--bg', text_color: '--text', hint_color: '--hint', link_color: '--link', button_color: '--accent', button_text_color: '--accent-text' };
      var tp = this.pref === 'auto' ? Platform.themeParams() : null;
      Object.keys(map).forEach(function (k) {
        var v = tp && tp[k];
        if (v && /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(v)) root.style.setProperty(map[k], v); else root.style.removeProperty(map[k]);
      });
      var meta = document.querySelector('meta[name="theme-color"]'); if (meta) meta.setAttribute('content', mode === 'dark' ? '#0e1319' : '#f2f4f7');
    }
  };

  /* ===================== Shell (layout) ===================== */
  var Shell = {
    root: null, pages: null, nav: null, toasts: null, mainEl: null, offline: null,
    TABS: [
      { id: 'home', label: 'خانه', icon: 'home' },
      { id: 'snoop', label: 'فضول‌یاب', icon: 'eye' },
      { id: 'vip', label: 'VIP', icon: 'crown' },
      { id: 'chat', label: 'چت', icon: 'message' },
      { id: 'profile', label: 'پروفایل', icon: 'user' },
      { id: 'admin', label: 'مدیریت', icon: 'shield', admin: true }
    ],
    mount: function () {
      var root = document.getElementById('app');
      if (!root) { root = document.createElement('div'); root.id = 'app'; document.body.appendChild(root); }
      root.innerHTML = '';
      this.root = root;
      this.pages = h('div', { class: 'pages' });
      this.nav = h('nav', { class: 'nav', role: 'tablist', 'aria-label': 'منوی اصلی' });
      this.toasts = h('div', { class: 'toast-wrap', 'aria-live': 'polite' });
      this.offline = h('div', { class: 'offline-bar' }, icon('wifiOff'), 'اتصال اینترنت قطع است؛ برخی بخش‌ها در دسترس نیستند');
      root.appendChild(this.pages); root.appendChild(this.nav); root.appendChild(this.toasts); root.appendChild(this.offline);
      var self = this;
      window.addEventListener('online', function () { State.online = true; self.offline.classList.remove('show'); toast('اتصال برقرار شد', 'success'); });
      window.addEventListener('offline', function () { State.online = false; self.offline.classList.add('show'); });
      if (!navigator.onLine) this.offline.classList.add('show');
    },
    renderNav: function () {
      var self = this; this.nav.innerHTML = '';
      this.TABS.filter(function (t) { return !t.admin || (State.me && State.me.is_admin); }).forEach(function (t) {
        var b = h('button', { class: 'nav-item', role: 'tab', 'data-tab': t.id, 'aria-label': t.label, onclick: function () { Platform.haptic('select'); Router.tab(t.id); } },
          h('span', { class: 'pill' }, icon(t.icon)), h('span', null, t.label));
        self.nav.appendChild(b);
      });
      this.setTab(Router.stack.length ? Router.stack[0].name : 'home');
    },
    setTab: function (id) { [].forEach.call(this.nav.children, function (b) { var on = b.getAttribute('data-tab') === id; b.classList.toggle('active', on); b.setAttribute('aria-selected', on ? 'true' : 'false'); }); },
    setBadge: function (id, n) {
      var b = this.nav.querySelector('[data-tab="' + id + '"]'); if (!b) return;
      var d = b.querySelector('.dot'); if (d) d.remove();
      if (n > 0) b.appendChild(h('span', { class: 'dot' }, fa(n)));
    },
    setNav: function (visible) { this.root.classList.toggle('no-nav', !visible); }
  };

  /* ===================== Back stack ===================== */
  var Back = {
    handlers: [],
    push: function (fn) { var self = this; this.handlers.push(fn); this.sync(); return function () { var i = self.handlers.indexOf(fn); if (i >= 0) self.handlers.splice(i, 1); self.sync(); }; },
    trigger: function () { if (this.handlers.length) { this.handlers[this.handlers.length - 1](); return true; } if (Router.canBack()) { Router.back(); return true; } return false; },
    sync: function () { Platform.setBack(this.handlers.length > 0 || Router.canBack()); }
  };

  /* ===================== Toast ===================== */
  function toast(text, type) {
    if (!Shell.toasts) return;
    var t = h('div', { class: 'toast ' + (type || '') }, icon(type === 'error' ? 'alert' : type === 'success' ? 'check' : 'info'), h('span', null, text));
    Shell.toasts.appendChild(t);
    if (type === 'error') Platform.haptic('error'); else if (type === 'success') Platform.haptic('success');
    while (Shell.toasts.children.length > 3) Shell.toasts.firstChild.remove();
    setTimeout(function () { t.classList.add('out'); setTimeout(function () { t.remove(); }, 260); }, 2600);
  }

  /* ===================== Sheet & Modal ===================== */
  function openSheet(o) {
    var overlay = h('div', { class: 'overlay-root' });
    var bd = h('div', { class: 'backdrop' });
    var sheet = h('div', { class: 'sheet', role: 'dialog', 'aria-modal': 'true' });
    var closed = false, unback;
    function close() {
      if (closed) return; closed = true; if (unback) unback();
      bd.classList.remove('show'); sheet.classList.remove('show'); sheet.style.transform = '';
      setTimeout(function () { overlay.remove(); }, 320);
      if (o.onClose) o.onClose();
    }
    var bodyEl = h('div', { class: 'sheet-body' });
    var head = h('div', { class: 'sheet-head' }, h('h3', null, o.title || ''), h('button', { class: 'icon-btn', 'aria-label': 'بستن', onclick: close }, icon('x')));
    var handle = h('div', { class: 'handle' });
    sheet.appendChild(handle); sheet.appendChild(head); sheet.appendChild(bodyEl);
    add(bodyEl, typeof o.body === 'function' ? o.body(close) : o.body);
    var api = { close: close, el: sheet, body: bodyEl, buttons: [] };
    if (o.actions && o.actions.length) {
      var act = h('div', { class: 'sheet-actions' });
      o.actions.forEach(function (a) {
        var b = h('button', { class: 'btn btn-' + (a.kind || 'primary'), onclick: function () { a.onClick ? a.onClick(close, b) : close(); } }, a.icon ? icon(a.icon) : null, a.text);
        api.buttons.push(b); act.appendChild(b);
      });
      sheet.appendChild(act);
    }
    // drag-to-close
    var startY = null, dy = 0;
    function ts(e) { startY = e.touches[0].clientY; dy = 0; sheet.style.transition = 'none'; }
    function tm(e) { if (startY === null) return; dy = Math.max(0, e.touches[0].clientY - startY); sheet.style.transform = 'translateY(' + dy + 'px)'; }
    function te() { if (startY === null) return; sheet.style.transition = ''; startY = null; if (dy > 90) close(); else sheet.style.transform = ''; }
    [handle, head].forEach(function (el) { el.addEventListener('touchstart', ts, { passive: true }); el.addEventListener('touchmove', tm, { passive: true }); el.addEventListener('touchend', te); });
    bd.addEventListener('click', close);
    overlay.appendChild(bd); overlay.appendChild(sheet); Shell.root.appendChild(overlay);
    requestAnimationFrame(function () { requestAnimationFrame(function () { bd.classList.add('show'); sheet.classList.add('show'); }); });
    unback = Back.push(close);
    Platform.haptic('light');
    return api;
  }
  function confirmDialog(o) {
    return new Promise(function (resolve) {
      var overlay = h('div', { class: 'overlay-root' }), bd = h('div', { class: 'backdrop' }), done = false, unback;
      function fin(v) { if (done) return; done = true; unback(); bd.classList.remove('show'); m.classList.remove('show'); setTimeout(function () { overlay.remove(); }, 230); resolve(v); }
      var m = h('div', { class: 'modal', role: 'alertdialog' },
        h('div', { class: 'm-icon' + (o.danger ? ' danger' : '') }, icon(o.icon || (o.danger ? 'alert' : 'info'))),
        h('h3', null, o.title), h('p', null, o.text || ''),
        h('div', { class: 'btn-row' },
          h('button', { class: 'btn btn-ghost', onclick: function () { fin(false); } }, o.cancel || 'انصراف'),
          h('button', { class: 'btn ' + (o.danger ? 'btn-danger' : 'btn-primary'), onclick: function () { fin(true); } }, o.ok || 'تأیید')));
      bd.addEventListener('click', function () { fin(false); });
      overlay.appendChild(bd); overlay.appendChild(m); Shell.root.appendChild(overlay);
      requestAnimationFrame(function () { requestAnimationFrame(function () { bd.classList.add('show'); m.classList.add('show'); }); });
      unback = Back.push(function () { fin(false); });
      Platform.haptic(o.danger ? 'warning' : 'light');
    });
  }

  /* ===================== Main action (MainButton یا دکمهٔ داخلی) ===================== */
  var MainAction = {
    el: null, btn: null,
    set: function (text, onClick, opts) {
      opts = opts || {};
      if (Platform.hasMainButton) { Platform.main.show(text, onClick); return; }
      if (!this.el) {
        this.btn = h('button', { class: 'btn btn-block btn-primary' });
        this.el = h('div', { class: 'main-action' }, this.btn);
        Shell.root.appendChild(this.el);
      }
      this.btn.className = 'btn btn-block ' + (opts.kind === 'gold' ? 'btn-gold' : 'btn-primary');
      this.btn.textContent = text; this.btn.disabled = !!opts.disabled; this.btn.onclick = onClick;
      if (Router.current) Router.current.ctx.body.classList.add('has-main');
    },
    loading: function (on) { if (Platform.hasMainButton) { Platform.main.progress(on); return; } if (this.btn) this.btn.classList.toggle('loading', on); },
    clear: function () { if (Platform.hasMainButton) Platform.main.hide(); if (this.el) { this.el.remove(); this.el = null; this.btn = null; } }
  };

  /* ===================== Reusable components ===================== */
  function iconBtn(name, onClick, label) { return h('button', { class: 'icon-btn', 'aria-label': label || '', onclick: onClick }, icon(name)); }
  function Avatar(name, id, opts) {
    opts = opts || {};
    var a = h('div', { class: 'avatar' + (opts.lg ? ' lg' : '') + (opts.masked ? ' masked' : '') + (opts.photo && !opts.masked ? ' has-photo' : ''), style: opts.masked ? null : { background: 'linear-gradient(135deg,' + colorFor(id || name) + ', ' + colorFor((id || name) + 'x') + ')' } },
      opts.masked ? icon('user') : initials(name));
    if (opts.masked) a.querySelector('.ic').style.cssText = 'width:20px;height:20px';
    // عکس پروفایل واقعی (پروکسی امضادار) — در صورت خطا به حروف اول نام برمی‌گردیم
    if (opts.photo && !opts.masked) {
      var img = h('img', { src: opts.photo, alt: '', loading: 'lazy', decoding: 'async', draggable: 'false' });
      img.addEventListener('error', function () { img.remove(); a.classList.remove('has-photo'); });
      a.appendChild(img);
    }
    if (opts.vip) a.appendChild(h('span', { class: 'vip-dot' }, icon('crown')));
    return a;
  }
  function ListItem(o) {
    var tag = o.onClick ? 'button' : 'div';
    return h(tag, { class: 'list-item', onclick: o.onClick ? function () { Platform.haptic('light'); o.onClick(); } : null },
      o.lead || (o.icon ? h('div', { class: 'li-icon ' + (o.tone || '') }, icon(o.icon)) : null),
      h('div', { class: 'li-body' }, h('div', { class: 'li-title ellipsis' }, o.title), o.sub ? h('div', { class: 'li-sub ellipsis' }, o.sub) : null),
      (o.end || o.onClick) ? h('div', { class: 'li-end' }, o.end || null, o.onClick && !o.noChev ? icon('chevL', 'chev') : null) : null);
  }
  function SectionTitle(text, actionText, onAction) { return h('div', { class: 'section-title' }, h('span', null, text), actionText ? h('button', { onclick: onAction }, actionText) : null); }
  function Empty(o) {
    return h('div', { class: 'empty' }, h('div', { class: 'e-icon' }, icon(o.icon || 'inbox')), h('h4', null, o.title), o.text ? h('p', null, o.text) : null,
      o.action ? h('button', { class: 'btn btn-secondary', onclick: o.action.onClick }, o.action.icon ? icon(o.action.icon) : null, o.action.text) : null);
  }
  function ErrorState(e, retry) {
    return Empty({ icon: e && e.code === 'OFFLINE' ? 'wifiOff' : (e && e.code === 'FORBIDDEN' ? 'lock' : 'alert'), title: e && e.code === 'OFFLINE' ? 'آفلاین هستید' : (e && e.code === 'FORBIDDEN' ? 'دسترسی محدود' : 'مشکلی پیش آمد'), text: errMsg(e), action: retry && (!e || e.code !== 'FORBIDDEN') ? { text: 'تلاش دوباره', icon: 'refresh', onClick: retry } : null });
  }
  var Skel = {
    line: function (w, hgt) { return h('div', { class: 'sk sk-line', style: { width: w || '100%', height: (hgt || 12) + 'px' } }); },
    block: function (hgt, r) { return h('div', { class: 'sk', style: { height: hgt + 'px', borderRadius: (r || 18) + 'px' } }); },
    list: function (n) {
      var l = h('div', { class: 'list' });
      for (var i = 0; i < (n || 5); i++) l.appendChild(h('div', { class: 'list-item' }, h('div', { class: 'sk sk-circle', style: { width: '42px', height: '42px', flexShrink: 0 } }), h('div', { class: 'li-body' }, Skel.line('55%', 13), Skel.line('35%', 10))));
      return l;
    },
    home: function () { return h('div', null, Skel.block(182, 22), h('div', { class: 'stat-grid' }, Skel.block(84, 16), Skel.block(84, 16), Skel.block(84, 16)), h('div', { style: 'height:20px' }), Skel.block(78, 18), h('div', { style: 'height:20px' }), Skel.list(3)); },
    cards: function () { return h('div', { class: 'stack' }, Skel.block(150), Skel.block(160), Skel.list(4)); },
    chat: function () { var w = h('div', { class: 'stack', style: 'padding:14px' }); ['60%', '45%', '70%', '40%'].forEach(function (x, i) { w.appendChild(h('div', { class: 'sk', style: { height: '46px', width: x, alignSelf: i % 2 ? 'flex-end' : 'flex-start', borderRadius: '18px' } })); }); return w; }
  };
  function Seg(options, value, onChange) {
    var el = h('div', { class: 'seg', role: 'tablist' });
    options.forEach(function (o) {
      el.appendChild(h('button', { class: o.id === value ? 'on' : '', onclick: function () { if (o.id === value) return; Platform.haptic('select'); onChange(o.id); } }, o.label));
    });
    return el;
  }
  function BarChart(points, opts) {
    opts = opts || {};
    var max = Math.max.apply(null, points.map(function (p) { return p.v; }).concat([1]));
    var el = h('div', { class: 'chart', style: opts.height ? { height: opts.height + 'px' } : null });
    points.forEach(function (p, i) {
      var bar = h('div', { class: 'bar' + (p.dim ? ' dim' : '') }, opts.values ? h('b', null, fa(p.v)) : null, h('i', { style: { height: '4px' } }), h('span', null, p.label));
      el.appendChild(bar);
      setTimeout(function () { bar.querySelector('i').style.height = Math.max(4, (p.v / max) * 100 * (opts.values ? 0.72 : 0.82)) + '%'; }, 60 + i * 30);
    });
    return el;
  }
  function vipChip(vip) { return vip && vip.active ? h('span', { class: 'chip gold' }, icon('crown'), 'VIP') : h('span', { class: 'chip' }, 'کاربر عادی'); }
  function statusChip(s) {
    var m = { paid: ['موفق', 'accent'], pending: ['در انتظار پرداخت', 'warn'], failed: ['ناموفق', 'danger'], open: ['باز', 'accent'], closed: ['بسته', ''], running: ['در حال ارسال', 'warn'], done: ['تکمیل شد', 'accent'] }[s] || [s, ''];
    return h('span', { class: 'chip ' + m[1] }, m[0]);
  }
  function withLoading(btn, promise) {
    btn.classList.add('loading'); btn.disabled = true;
    return promise.then(function (r) { btn.classList.remove('loading'); btn.disabled = false; return r; }, function (e) { btn.classList.remove('loading'); btn.disabled = false; throw e; });
  }
  function bytes(n) { return n > 1048576 ? fa((n / 1048576).toFixed(1)) + ' مگابایت' : fa(Math.round(n / 1024)) + ' کیلوبایت'; }

  /* ===================== Router (in-memory, بدون تغییر history) ===================== */
  var Router = {
    routes: {}, stack: [], current: null,
    def: function (name, cfg) { this.routes[name] = cfg; },
    canBack: function () { return this.stack.length > 1; },
    start: function (name, params) { this.stack = [{ name: name, params: params || {} }]; this.render('fade'); },
    tab: function (name) {
      if (this.stack.length === 1 && this.stack[0].name === name) { if (this.current) this.current.ctx.body.scrollTo({ top: 0, behavior: 'smooth' }); return; }
      this.stack = [{ name: name, params: {} }]; this.render('fade');
    },
    go: function (name, params) { this.stack.push({ name: name, params: params || {} }); this.render('push'); },
    back: function () { if (this.stack.length <= 1) return; this.stack.pop(); this.render('pop'); },
    refresh: function () { this.render('none'); },
    render: function (dir) {
      var entry = this.stack[this.stack.length - 1], route = this.routes[entry.name];
      if (!route) { entry = { name: 'home', params: {} }; this.stack = [entry]; route = this.routes.home; }
      if (route.admin && !(State.me && State.me.is_admin)) { this.stack = [{ name: 'home', params: {} }]; entry = this.stack[0]; route = this.routes.home; toast(ERR_TEXT.FORBIDDEN, 'error'); }
      Shell.setTab(this.stack[0].name);
      Shell.setNav(this.stack.length === 1);
      MainAction.clear();
      var old = this.current;
      if (old) { old.ctx.alive = false; old.ctx._cleanups.forEach(function (f) { try { f(); } catch (e) { /* noop */ } }); }
      var page = h('section', { class: 'page' });
      var headerEl = h('header', { class: 'page-header' });
      var body = h('div', { class: 'page-body' + (route.flush ? ' flush' : '') });
      page.appendChild(headerEl); page.appendChild(body);
      var ctx = {
        params: entry.params, page: page, body: body, alive: true, _cleanups: [], reload: function () { Router.refresh(); },
        onCleanup: function (fn) { this._cleanups.push(fn); },
        header: function (o) {
          headerEl.innerHTML = '';
          if (Router.canBack() && !Platform.hasNativeBack) headerEl.appendChild(iconBtn('back', function () { Router.back(); }, 'بازگشت'));
          else headerEl.appendChild(h('div', { style: 'width:4px' }));
          headerEl.appendChild(h('img', { class: 'brand-logo', src: 'img/logo-sm.png', alt: '' }));
          headerEl.appendChild(h('div', { class: 'title ellipsis' }, o.title, o.subtitle ? h('small', null, o.subtitle) : null));
          (o.actions || []).forEach(function (a) { headerEl.appendChild(a); });
        }
      };
      body.addEventListener('scroll', function () { headerEl.classList.toggle('scrolled', body.scrollTop > 4); }, { passive: true });
      this.current = { page: page, ctx: ctx, name: entry.name };
      try { route.render(ctx); } catch (e) { console.error(e); body.replaceChildren(ErrorState(new ApiError('SERVER_ERROR', 'خطا در نمایش صفحه'), function () { Router.refresh(); })); }
      // حذف صفحات قدیمی باقی‌مانده
      [].slice.call(Shell.pages.children).forEach(function (p) { if (!old || p !== old.page) p.remove(); });
      Shell.pages.appendChild(page);
      if (old && dir !== 'none') {
        page.classList.add('anim-' + dir + '-in'); old.page.classList.add('anim-' + dir + '-out');
        var op = old.page; setTimeout(function () { op.remove(); page.classList.remove('anim-' + dir + '-in'); }, 340);
      } else if (old) old.page.remove();
      else page.classList.add('anim-fade-in');
      Back.sync();
    }
  };

  /* داده با کش (stale-while-revalidate) */
  function useData(ctx, key, fetcher, render, skeleton) {
    var cached = Cache.get(key), last = cached !== undefined ? JSON.stringify(cached) : null;
    var sk = function () { return skeleton ? skeleton() : Skel.list(); };
    if (cached !== undefined) render(clone(cached)); else ctx.body.replaceChildren(sk());
    function run() {
      return fetcher().then(function (d) {
        Cache.set(key, d); if (!ctx.alive) return;
        var j = JSON.stringify(d); if (j !== last) { last = j; render(clone(d)); }
      }, function (e) {
        if (!ctx.alive) return;
        if (last === null) ctx.body.replaceChildren(ErrorState(e, function () { ctx.body.replaceChildren(sk()); run(); }));
        else toast(errMsg(e), 'error');
      });
    }
    ctx.reload = function () { return run(); };
    run();
    return run;
  }
  function refreshMe() { return api('/me').then(function (me) { State.me = me; Cache.set('me', me); if (window.FzVip) window.FzVip.apply(me); return me; }, function () { return State.me; }); }

  /* ===================== Shared sheets ===================== */
  function vipUpsell(reason) {
    var s = openSheet({
      title: '',
      body: h('div', { class: 'center' },
        h('div', { class: 'gate', style: 'position:static;padding:0;animation:none;background:transparent' }, h('div', { class: 'g-icon', style: 'background:linear-gradient(135deg,#f7c948,#e09b12);color:#fff' }, icon('crown'))),
        h('h3', { style: 'margin:0 0 6px;font-size:18px;font-weight:800' }, reason || 'هویت فضول‌ها رو ببین!'),
        h('p', { class: 'muted', style: 'margin:0 0 16px;font-size:13.5px' }, 'با اشتراک VIP نام و یوزرنیم کامل کسانی که لینکت را باز کرده‌اند نمایش داده می‌شود.'),
        h('ul', { class: 'features', style: 'text-align:right' }, ['نمایش هویت کامل فضول‌ها', 'تا ۱۰ تله اختصاصی', 'XP دوبرابر و گردونه اضافه'].map(function (f) { return h('li', null, icon('check'), f); }))),
      actions: [{ text: 'مشاهده پلن‌های VIP', kind: 'gold', icon: 'crown', onClick: function (close) { close(); Router.tab('vip'); } }]
    });
    return s;
  }
  function visitorSheet(v) {
    if (v.masked) {
      /* v4.3: برای فضول‌های قفل‌شده، علاوه بر آپ‌سل VIP، امکان خرید تک‌نفرهٔ هویت
         (همان reveal_price منوی شیشه‌ای) از طریق چت ربات فراهم است. */
      var price = (State.me && State.me.settings && State.me.settings.reveal_price_toman) || 3000;
      openSheet({
        title: 'هویت این فضول قفل است',
        body: h('div', { class: 'stack' },
          h('div', { class: 'alert warn' }, icon('lock'), h('div', null, 'دیدن نام و آیدی کامل همهٔ فضول‌ها با ', h('b', null, 'VIP'), ' امکان‌پذیر است.')),
          h('div', { class: 'card info-rows' },
            infoRow('گزینهٔ ۱ — اشتراک VIP', 'همهٔ فضول‌ها + امکانات ویژه'),
            infoRow('گزینهٔ ۲ — باز کردن همین یک نفر', 'پرداخت ' + fa(price) + ' تومان در چت ربات'))),
        actions: [
          { text: 'VIP می‌خواهم', icon: 'crown', onClick: function (close) { close(); Router.tab('vip'); } },
          { text: 'باز کردن همین نفر', icon: 'unlock', onClick: function (close) { close(); Platform.openBot('reveal_' + (v.reveal_code || v.id)); } }
        ]
      });
      return;
    }
    var acts = [];
    if (v.username) acts.push({ text: 'مشاهده پروفایل در بله', icon: 'external', onClick: function (close) { close(); Platform.openLink(CFG.deepLinkBase + v.username); } });
    if (v.user_id) acts.push({ text: 'ارسال پیام ناشناس', icon: 'send', onClick: function (close, btn) {
      withLoading(btn, api('/snoop/visitors/' + v.user_id + '/anon-token', { method: 'POST' })).then(function (r) {
        close(); Router.go('chat-thread', { token: r.token });
      }, function (e) { toast(errMsg(e), 'error'); });
    } });
    openSheet({
      title: 'جزئیات فضول',
      body: h('div', null,
        h('div', { class: 'center', style: 'margin-bottom:12px' }, h('div', { style: 'display:flex;justify-content:center;margin-bottom:8px' }, Avatar(v.name, v.user_id, { lg: true, photo: v.avatar })),
          h('div', { class: 'bold', style: 'font-size:17px' }, v.name), v.username ? h('div', { class: 'muted ltr' }, '@' + v.username) : h('div', { class: 'muted small' }, 'بدون یوزرنیم')),
        h('div', { class: 'card info-rows' },
          infoRow('شناسه کاربری', h('span', { class: 'ltr' }, String(v.user_id))),
          infoRow('از طریق', v.trap_title),
          infoRow('تعداد بازدید', fa(v.count) + ' بار'),
          infoRow('اولین بازدید', jdate(v.first_at, true)),
          infoRow('آخرین بازدید', jdate(v.visited_at, true)))),
      actions: acts
    });
  }
  function infoRow(k, v) { return h('div', { class: 'info-row' }, h('span', null, k), h('span', null, v)); }
  function VisitorItem(v) {
    return ListItem({
      lead: Avatar(v.name, v.user_id || v.id, { masked: v.masked, photo: v.avatar }),
      /* v4.7 (فقط نام برای غیر VIP): نام واقعی بدون بلور — بقیهٔ جزئیات قفل است */
      title: v.name,
      sub: v.masked ? 'هویت قفل است' : (v.trap_title + ' • ' + ago(v.visited_at)),
      end: [!v.masked && v.count > 1 ? h('span', { class: 'chip' }, '×' + fa(v.count)) : null, v.masked ? h('span', { class: 'chip gold' }, icon('lock')) : null],
      onClick: function () { visitorSheet(v); }
    });
  }
  function shareLink(link, text) {
    Platform.share(text || 'ببین کی بیشتر از همه سرک می‌کشه 👀', link).then(function (r) { if (r === 'copied') toast('لینک کپی شد', 'success'); });
  }
  function copyLink(link) { copyText(link).then(function (ok) { toast(ok ? 'لینک کپی شد' : 'کپی انجام نشد؛ لینک را دستی انتخاب کنید', ok ? 'success' : 'error'); }); }
  /* v4.3: کپی لینک به‌صورت هایپرلینک Markdown — [متن طعمه](لینک) + گزینهٔ لینک خالی
     v4.7 (باگ بیو): بایو بله حداکثر ۷۰ کاراکتر است؛ هایپرلینک خالی [](...) به‌ازای
     هر لینک (طول لینک + ۴) کاراکتر می‌گیرد؛ برای لینک ۲۵کاراکتری = ۲۹ → متن حداکثر ۴۱.
     از کاراکتر ۴۲م فقط پیام قرمزِ زیرخط‌دار زیر کادر نشان داده می‌شود — بدون هیچ
     توضیح اضافه؛ دکمه‌های کپی همچنان کار می‌کنند. */
  var BIO_MAX_CHARS = 70;
  function bioTextLimit(link) { return BIO_MAX_CHARS - (String(link || '').length + 4); }
  function hyperlinkSheet(link, defaultText, title) {
    var limit = bioTextLimit(link); // برای لینک اصلی (۲۵ کاراکتر) = ۴۱
    var inp = h('input', { class: 'input', maxLength: 200, placeholder: 'مثلاً: یه عکس باحال گذاشتم، ببین 👀', value: defaultText || '' });
    var preview = h('div', { class: 'md-preview ltr' }, '—');
    /* پیام قرمز و زیرخط‌دار — فقط وقتی متن از حد بیو بلندتر شود */
    var warn = h('div', { class: 'bio-warn', style: 'display:none' }, 'توی بیو جا نمیشه! کوتاه تر بنویس');
    function render() {
      var t = inp.value.trim();
      preview.textContent = t ? '[' + t + '](' + link + ')' : '[متن دلخواه](' + link + ')';
      warn.style.display = inp.value.length > limit ? '' : 'none';
    }
    inp.addEventListener('input', render); render();
    var sh = openSheet({
      title: title || 'کپی لینک با متن طعمه',
      body: h('div', { class: 'stack' },
        h('div', { class: 'field' }, h('label', null, 'متن دلخواه روی لینک'), inp, warn,
          h('div', { class: 'hint' }, h('span', null, 'لینک به‌صورت هایپرلینک (Markdown) کپی می‌شود — هر جا Markdown پشتیبانی شود، فقط متن دیده می‌شود'))),
        h('div', { class: 'field' }, h('label', null, 'پیش‌نمایش کپی'), preview),
        h('div', { class: 'field' }, h('label', null, 'لینک خام'), h('div', { class: 'link-box' }, h('span', { class: 'ltr' }, link)))),
      actions: [
        { text: 'کپی هایپرلینک', icon: 'copy', onClick: function (close) {
            var t = inp.value.trim();
            if (!t) { toast('اول متن لینک را وارد کنید یا «کپی لینک خالی» را بزنید', 'error'); inp.focus(); return; }
            copyText('[' + t + '](' + link + ')').then(function (ok) {
              close(); toast(ok ? 'هایپرلینک کپی شد ✅' : 'کپی انجام نشد', ok ? 'success' : 'error');
            });
          } },
        { text: 'کپی لینک خالی', kind: 'ghost', onClick: function (close) {
            copyText(link).then(function (ok) { close(); toast(ok ? 'لینک کپی شد' : 'کپی انجام نشد', ok ? 'success' : 'error'); });
          } }
      ]
    });
    setTimeout(function () { inp.focus(); }, 350);
    return sh;
  }

  /* ===================== Page: Home ===================== */
  Router.def('home', {
    render: function (ctx) {
      ctx.header({ title: CFG.appName, subtitle: State.demo ? 'حالت دمو • داده‌های نمونه' : 'مینی‌اپ رسمی در بله', actions: [iconBtn('refresh', function () { Platform.haptic('light'); ctx.reload(); }, 'به‌روزرسانی')] });
      useData(ctx, 'me', function () { return api('/me'); }, function (me) { State.me = me; if (window.FzVip) window.FzVip.apply(me); ctx.body.replaceChildren(HomeView(me)); }, Skel.home);
    }
  });
  function HomeView(me) {
    var name = me.user.first_name || 'دوست';
    var wrap = h('div', null);
    // v4.2: نشان VIP چانکی از روی اسم حذف شد (مربع طلایی زشت روی نام) — وضعیت VIP از
    // ذرات طلایی، کارت وضعیت و تم طلایی مشخص است.
    wrap.appendChild(h('div', { class: 'hero' },
      h('div', null, h('h2', null, 'سلام، ' + name + ' 👋'), h('p', null, me.snoop.today > 0 ? 'امروز ' + fa(me.snoop.today) + ' نفر به لینکت سرک کشیدن!' : 'امروز هنوز کسی سر نزده؛ لینکت رو پخش کن!')),
      h('div', { class: 'lvl' },
        h('div', { class: 'row between small', style: 'margin-bottom:6px;font-weight:700' }, h('span', null, '⭐ سطح ' + fa(me.xp.level)), h('span', null, fa(me.xp.level_xp) + ' / ' + fa(me.xp.next_level_xp) + ' XP')),
        h('div', { class: 'progress' }, h('i', { style: { width: Math.round(me.xp.progress * 100) + '%' } })))));
    wrap.appendChild(h('div', { class: 'stat-grid' },
      h('div', { class: 'stat' }, icon('fire'), h('div', { class: 'v' }, fa(me.snoop.today)), h('div', { class: 'k' }, 'فضول امروز')),
      h('div', { class: 'stat' }, icon('eye'), h('div', { class: 'v' }, fa(me.snoop.total)), h('div', { class: 'k' }, 'کل فضول‌ها')),
      h('div', { class: 'stat' }, icon('trophy'), h('div', { class: 'v' }, me.rank ? fa(me.rank) : '—'), h('div', { class: 'k' }, 'رتبه شما'))));
    /* v4.4: شمارندهٔ زندهٔ فضول‌های قفل‌شده — عدد واقعی، بدون هیچ اطلاعات هویتی */
    if (!me.vip.active && (me.snoop.distinct || 0) > 0) {
      wrap.appendChild(h('div', { class: 'gold-teaser', onclick: function () { Platform.haptic('light'); Router.tab('vip'); } }, icon('lock') || icon('crown'),
        h('div', { class: 'txt' }, h('b', null, '🔒 همین الان ' + fa(me.snoop.distinct) + ' فضولِ نیمه‌قفل داری'), h('span', null, 'نام‌ها را می‌بینی؛ آیدی و یوزرنیم کامل با VIP باز می‌شود.'))));
    }
    wrap.appendChild(SectionTitle('دسترسی سریع'));
    function q(ic, label, color, fn, badge) {
      return h('button', { onclick: function () { Platform.haptic('light'); fn(); } }, badge ? h('span', { class: 'badge-new' }, badge) : null, h('span', { class: 'qi', style: { color: color } }, icon(ic)), label);
    }
    /* v4.7 (باگ منوی دسترسی سریع): دکمهٔ VIP با «ماموریت‌ها» جایگزین شد —
       همان ماموریت‌های ویژهٔ روز پنل شیشه‌ای، با نوار پیشرفت (صفحهٔ missions).
       VIP همچنان از تب پایین و کارت‌های ارتقا در دسترس است. */
    wrap.appendChild(h('div', { class: 'card', style: 'padding:14px 8px' }, h('div', { class: 'quick' },
      q('link', 'کپی لینک', '#00a67e', function () { hyperlinkSheet(me.snoop.link); }),
      q('gift', 'گردونه', '#ec4899', function () { Router.go('wheel'); }, me.wheel.can_spin ? 'آماده' : null),
      q('trophy', 'برترین‌ها', '#e09b12', function () { Router.go('leaderboard'); }),
      q('target', 'ماموریت‌ها', '#8b5cf6', function () { Router.go('missions'); }, Missions.badge()))));
    if (!me.vip.active) {
      wrap.appendChild(h('div', { class: 'promo mt-12', onclick: function () { Router.tab('vip'); } }, icon('crown', 'big'),
        h('div', { class: 'grow' }, h('div', { class: 'bold' }, 'هویت فضول‌ها رو کشف کن!'), h('div', { class: 'small', style: 'opacity:.85' }, 'با ', h('b', null, 'VIP'), ' اسم و یوزرنیم کامل فضول‌ها را ببین.')),
        h('button', { class: 'btn btn-gold btn-sm' }, 'ارتقا')));
      /* fozol-pro: تیزر ذرات طلایی — مشتاق‌کردن کاربر عادی به VIP */
      wrap.appendChild(h('div', { class: 'gold-teaser', onclick: function () { Platform.haptic('light'); Router.tab('vip'); } }, icon('sparkles') || icon('crown'),
        h('div', { class: 'txt' }, h('b', null, '✨ پس‌زمینهٔ طلایی مخصوص VIP'), h('span', null, 'با فعال‌سازی VIP، مینی‌اپ برای تو با ذرات طلایی متحرک می‌درخشد.'))));
    } else {
      wrap.appendChild(h('div', { class: 'card mt-12 row', style: 'gap:12px' }, h('div', { class: 'li-icon gold' }, icon('crown')),
        h('div', { class: 'grow' }, h('div', { class: 'bold small' }, 'اشتراک VIP فعال است'), h('div', { class: 'small muted' }, fa(me.vip.days_left) + ' روز باقی‌مانده • تا ' + jdate(me.vip.expires_at))),
        h('button', { class: 'btn btn-secondary btn-sm', onclick: function () { Router.tab('vip'); } }, 'تمدید')));
    }
    wrap.appendChild(SectionTitle('آخرین فضول‌ها', me.recent.length ? 'مشاهده همه' : null, function () { Router.tab('snoop'); }));
    if (me.recent.length) wrap.appendChild(h('div', { class: 'list' }, me.recent.map(VisitorItem)));
    else wrap.appendChild(h('div', { class: 'card' }, Empty({ icon: 'eye', title: 'هنوز کسی سر نزده', text: 'لینک فضول‌یابت را در گروه‌ها و کانال‌های بله پخش کن.', action: { text: 'اشتراک‌گذاری لینک', icon: 'share', onClick: function () { shareLink(me.snoop.link); } } })));
    return wrap;
  }

  /* ===================== Page: Snoop ===================== */
  Router.def('snoop', {
    render: function (ctx) {
      var seg = ctx.params.seg || 'visitors', trapFilter = null, extra = [], nextCursor = null;
      ctx.header({ title: 'فضول‌یاب', subtitle: 'ببین کی سرک کشیده', actions: [iconBtn('refresh', function () { ctx.reload(); }, 'به‌روزرسانی')] });
      var fab = null;
      useData(ctx, 'snoop', function () {
        return Promise.all([api('/snoop/summary'), api('/snoop/visitors')]).then(function (r) { return { s: r[0], v: r[1] }; });
      }, function (d) { extra = []; nextCursor = d.v.next_cursor; draw(d); }, Skel.cards);

      /* v4.4: رادار فضول‌ها — ساعات پربازدید، بهترین تله، مقایسه با میانگین */
      function radarCard() {
        var card = h('div', { class: 'card mt-12' },
          h('div', { class: 'card-title' }, icon('radar') || icon('eye'), 'رادار فضول‌ها'),
          h('div', { class: 'small muted', style: 'margin-bottom:8px' }, 'تحلیل زنده از داده‌های واقعی تله‌های تو'),
          Skel.block(90, 12));
        api('/snoop/radar').then(function (r) {
          if (!ctx.alive) return;
          var inner = h('div', null);
          if (r.best_hours && r.best_hours.length) {
            inner.appendChild(h('div', { class: 'info-rows', style: 'margin-bottom:10px' },
              h('div', { class: 'info-row' }, h('span', null, '⏰ پربازدیدترین ساعت‌ها'), h('span', null, r.best_hours.map(function (x) { return fa(x.hour) + ':۰۰'; }).join('، '))),
              r.best_trap ? h('div', { class: 'info-row' }, h('span', null, '🎯 بهترین کانال انتشار'), h('span', { class: 'ellipsis', style: 'max-width:60%;display:inline-block' }, r.best_trap.title + ' (' + fa(r.best_trap.snoops) + ' فضول)')) : null,
              h('div', { class: 'info-row' }, h('span', null, '📊 کلیک ۷ روز اخیر تو'), h('span', null, fa(r.me_last_week) + ' در برابر میانگین ' + fa(Math.round(r.avg_last_week)) + (r.diff_pct !== null ? (r.diff_pct >= 0 ? ' (+' + fa(r.diff_pct) + '٪)' : ' (' + fa(r.diff_pct) + '٪)') : '')))));
            var chart = r.hour_chart.map(function (x) { return { v: x.count, label: x.hour % 6 === 0 ? fa(x.hour) : '' }; });
            inner.appendChild(BarChart(chart, { values: false }));
          } else {
            inner.appendChild(h('div', { class: 'small muted' }, 'هنوز داده کافی نیست — وقتی تله‌ات بازدید بگیرد، ساعات پربازدید و بهترین کانال انتشار همین‌جا تحلیل می‌شود.'));
          }
          var sk = card.querySelector('.sk'); if (sk) sk.remove();
          card.appendChild(inner);
        }, function () { var sk = card.querySelector('.sk'); if (sk) sk.remove(); card.appendChild(h('div', { class: 'small muted' }, 'رادار فعلاً در دسترس نیست.')); });
        return card;
      }

      function draw(d) {
        var s = d.s, w = h('div', null);
        w.appendChild(h('div', { class: 'card link-card' },
          h('div', { class: 'card-title' }, icon('link'), 'لینک فضول‌یاب شما'),
          h('div', { class: 'small muted' }, 'این لینک را هر جای بله منتشر کن؛ هر کس بازش کند در لیست فضول‌ها ثبت می‌شود.'),
          h('div', { class: 'link-box' }, h('span', { class: 'ltr' }, s.link), iconBtn('copy', function () { hyperlinkSheet(s.link); }, 'کپی')),
          h('div', { class: 'btn-row' }, h('button', { class: 'btn btn-primary', onclick: function () { shareLink(s.link); } }, icon('share'), 'اشتراک‌گذاری'), h('button', { class: 'btn btn-ghost', onclick: function () { hyperlinkSheet(s.link); } }, icon('copy'), 'کپی لینک'))));
        var chart = s.stats.chart.map(function (p, i) { return { v: p.count, label: F_WD ? F_WD.format(new Date(p.date)) : String(i + 1), dim: false }; });
        w.appendChild(h('div', { class: 'card' },
          h('div', { class: 'row between' }, h('div', { class: 'card-title', style: 'margin:0' }, icon('chart'), 'فعالیت ۷ روز اخیر'), h('span', { class: 'chip accent' }, fa(s.stats.week) + ' بازدید')),
          BarChart(chart, { values: true }),
          h('div', { class: 'stat-grid', style: 'margin-top:12px' },
            h('div', { class: 'stat', style: 'background:var(--surface-2);border:0' }, h('div', { class: 'v' }, fa(s.stats.today)), h('div', { class: 'k' }, 'امروز')),
            h('div', { class: 'stat', style: 'background:var(--surface-2);border:0' }, h('div', { class: 'v' }, fa(s.stats.week)), h('div', { class: 'k' }, 'این هفته')),
            h('div', { class: 'stat', style: 'background:var(--surface-2);border:0' }, h('div', { class: 'v' }, fa(s.stats.total)), h('div', { class: 'k' }, 'کل')))));
        /* v4.4: رادار فضول‌ها */
        w.appendChild(radarCard());
        w.appendChild(h('div', { class: 'mt-16' }, Seg([{ id: 'visitors', label: 'فضول‌ها' }, { id: 'traps', label: 'تله‌ها (' + fa(s.traps.length) + ')' }], seg, function (v) { seg = v; draw(d); })));
        if (seg === 'visitors') drawVisitors(w, d); else drawTraps(w, d);
        ctx.body.replaceChildren(w);
        if (fab) { fab.remove(); fab = null; }
        ctx.body.style.paddingBottom = seg === 'traps' ? '96px' : '';
        if (seg === 'traps') { fab = h('button', { class: 'fab', style: 'bottom:16px', onclick: function () { newTrap(s); } }, icon('plus'), 'تله جدید'); ctx.page.appendChild(fab); }
      }
      function drawVisitors(w, d) {
        var s = d.s;
        if (!s.limits.reveal) w.appendChild(h('div', { class: 'alert warn mt-12', onclick: function () { vipUpsell(); } }, icon('lock'), h('div', null, 'هویت فضول‌ها مخفی است. ', h('b', null, 'با VIP همه را ببین ←'))));
        /* v4.4 حریم خصوصی: فیلتر تله‌ها فقط برای VIP — فضولِ قفل‌شده هیچ جزئیاتی ندارد */
        if (s.limits.reveal) {
          var chips = h('div', { class: 'chips mt-12' });
          [{ id: null, title: 'همه' }].concat(s.traps).forEach(function (t) {
            chips.appendChild(h('button', { class: 'chip' + (trapFilter === t.id ? ' on' : ''), onclick: function () { trapFilter = t.id; Platform.haptic('select'); draw(d); } }, t.title));
          });
          w.appendChild(chips);
        } else { trapFilter = null; }
        var items = d.v.items.concat(extra).filter(function (v) { return trapFilter === null || v.trap_id === trapFilter; });
        if (!items.length) { w.appendChild(h('div', { class: 'card' }, Empty({ icon: 'eye', title: 'فضولی پیدا نشد', text: trapFilter ? 'هنوز کسی این تله را باز نکرده است.' : 'لینکت را به اشتراک بگذار تا فضول‌ها پیدا شوند.', action: { text: 'اشتراک‌گذاری لینک', icon: 'share', onClick: function () { shareLink(s.link); } } }))); return; }
        w.appendChild(h('div', { class: 'list' }, items.map(VisitorItem)));
        if (nextCursor) {
          var more = h('button', { class: 'btn btn-ghost btn-block mt-12', onclick: function () {
            withLoading(more, api('/snoop/visitors?cursor=' + encodeURIComponent(nextCursor))).then(function (r) { extra = extra.concat(r.items); nextCursor = r.next_cursor; draw(d); }, function (e) { toast(errMsg(e), 'error'); });
          } }, 'نمایش موارد بیشتر');
          w.appendChild(more);
        }
      }
      function drawTraps(w, d) {
        var s = d.s;
        /* v4.7 (همگام‌سازی با پنل شیشه‌ای): تلهٔ اختصاصی فقط برای VIP */
        w.appendChild(h('div', { class: 'alert mt-12' }, icon('info'), h('div', null, 'تله یک لینک اختصاصی با متن طعمه است. ', s.limits.reveal ? 'با VIP تا ' + fa(s.limits.max_traps) + ' تله می‌توانید بسازید.' : 'ساخت تلهٔ اختصاصی ویژهٔ اعضای VIP است.')));
        s.traps.forEach(function (t) {
          w.appendChild(h('div', { class: 'card trap-card mt-12' },
            h('div', { class: 'row between' }, h('div', { class: 'row grow' }, h('div', { class: 'li-icon' + (t.is_default ? '' : ' info') }, icon(t.is_default ? 'link' : 'target')), h('div', { class: 'grow' }, h('div', { class: 'bold ellipsis' }, t.title), h('div', { class: 'small muted' }, 'ساخته‌شده ' + jdate(t.created_at)))), h('span', { class: 'chip accent' }, icon('eye'), fa(t.visits))),
            t.bait ? h('div', { class: 'bait' }, t.bait) : null,
            /* v4.3: پیش‌نمایش لینک تله */
            h('div', { class: 'link-box', style: 'margin-top:10px' }, h('span', { class: 'ltr ellipsis' }, t.link), iconBtn('copy', function () { hyperlinkSheet(t.link, t.bait || t.title, 'کپی لینک تله با متن طعمه'); }, 'کپی')),
            h('div', { class: 'btn-row mt-8' },
              h('button', { class: 'btn btn-secondary btn-sm', onclick: function () { hyperlinkSheet(t.link, t.bait || t.title, 'کپی لینک تله با متن طعمه'); } }, icon('copy'), 'کپی با متن'),
              h('button', { class: 'btn btn-ghost btn-sm', onclick: function () { shareLink(t.link, t.bait || t.title); } }, icon('share'), 'ارسال'),
              t.is_default ? null : h('button', { class: 'btn btn-danger btn-sm', style: 'flex:0 0 44px;padding:0', 'aria-label': 'حذف', onclick: function () { delTrap(t); } }, icon('trash')))));
        });
      }
      function newTrap(s) {
        if (s.limits.custom_traps >= s.limits.max_traps) { if (!s.limits.reveal) vipUpsell('تله‌های بیشتر با VIP'); else toast('به سقف تعداد تله‌ها رسیده‌اید', 'error'); return; }
        var title = h('input', { class: 'input', maxLength: 40, placeholder: 'مثلاً: عکس جدیدم رو ببین 👀' });
        var bait = h('textarea', { class: 'textarea', maxLength: 200, placeholder: 'متنی که همراه لینک منتشر می‌شود (اختیاری)' });
        var cnt = h('span', null, '۰ / ۲۰۰');
        bait.addEventListener('input', function () { cnt.textContent = fa(bait.value.length) + ' / ۲۰۰'; });
        var sh = openSheet({
          title: 'ساخت تله جدید',
          body: h('div', { class: 'stack' }, h('div', { class: 'field' }, h('label', null, 'عنوان تله'), title), h('div', { class: 'field' }, h('label', null, 'متن طعمه'), bait, h('div', { class: 'hint' }, h('span', null, 'این متن فقط پیشنهاد است'), cnt))),
          actions: [{ text: 'ساخت تله', icon: 'plus', onClick: function (close, btn) {
            if (title.value.trim().length < 2) { toast('عنوان تله را وارد کنید', 'error'); title.focus(); return; }
            withLoading(btn, api('/snoop/traps', { method: 'POST', body: { title: title.value, bait: bait.value } })).then(function (t) {
              close(); toast('تله «' + t.title + '» ساخته شد', 'success'); Cache.del('snoop'); seg = 'traps'; ctx.reload();
            }, function (e) { if (e.code === 'LIMIT_REACHED' || e.code === 'VIP_REQUIRED') { close(); vipUpsell('تله‌های بیشتر با VIP'); } else toast(errMsg(e), 'error'); });
          } }]
        });
        setTimeout(function () { title.focus(); }, 350);
        return sh;
      }
      function delTrap(t) {
        confirmDialog({ title: 'حذف تله', text: 'تله «' + t.title + '» و آمار آن حذف می‌شود. لینک آن دیگر کار نخواهد کرد.', ok: 'حذف', danger: true, icon: 'trash' }).then(function (ok) {
          if (!ok) return;
          api('/snoop/traps/' + t.id, { method: 'DELETE' }).then(function () { toast('تله حذف شد', 'success'); Cache.del('snoop'); ctx.reload(); }, function (e) { toast(errMsg(e), 'error'); });
        });
      }
    }
  });

  /* ===================== Page: VIP ===================== */
  Router.def('vip', {
    render: function (ctx) {
      ctx.header({ title: 'اشتراک VIP', subtitle: 'پرداخت امن با درگاه بله' });
      var selected = null;
      useData(ctx, 'vip', function () { return api('/vip/plans'); }, draw, Skel.cards);
      function draw(d) {
        if (!selected) { var pop = d.plans.filter(function (p) { return p.badge; })[0]; selected = (pop || d.plans[0]).id; }
        var st = d.status, w = h('div', null);
        w.appendChild(h('div', { class: 'vip-card' + (st.active ? '' : ' off') }, icon('crown', 'crown'),
          h('div', { class: 'row between' }, h('h3', null, st.active ? 'VIP فعال است ✨' : 'هنوز VIP نیستی'), st.active ? h('span', { class: 'chip gold' }, st.plan_title || 'VIP') : null),
          h('div', { class: 'small', style: 'opacity:.85;margin-top:2px' }, st.active ? 'از همهٔ امکانات ویژه استفاده کن.' : 'با VIP هویت کامل فضول‌ها را ببین.'),
          st.active ? h('div', { class: 'exp' }, h('div', null, h('b', null, fa(st.days_left) + ' روز'), h('span', null, 'باقی‌مانده')), h('div', null, h('b', null, jshort(st.expires_at)), h('span', null, 'تاریخ انقضا'))) : null));
        w.appendChild(h('div', { class: 'card' }, h('div', { class: 'card-title' }, icon('sparkles'), 'امکانات VIP'), h('ul', { class: 'features' }, d.features.map(function (f) { return h('li', null, icon('check'), f); }))));
        /* v4.4: مقایسهٔ قیمت هوشمند — همهٔ مبالغ از تنظیمات زندهٔ ادمین */
        if (d.comparison && !st.active) {
          var cp = d.comparison;
          w.appendChild(h('div', { class: 'gold-teaser', onclick: function () { Platform.haptic('light'); } }, icon('coins') || icon('crown'),
            h('div', { class: 'txt' },
              h('b', null, '💡 مقایسهٔ هوشمند'),
              h('span', null, fa(cp.singles) + ' هویتِ تکی = ' + toman(cp.singles_total)),
              h('span', null, 'VIP کامل ماه فقط ' + toman(cp.month_price) + ' — ' + fa(cp.save_pct) + '٪ ارزان‌تر!'))));
        }
        w.appendChild(SectionTitle(st.active ? 'تمدید اشتراک' : 'انتخاب پلن'));
        var plans = h('div', { class: 'plans' });
        d.plans.forEach(function (p) {
          var perMonth = Math.round(p.price / (p.days / 30));
          plans.appendChild(h('button', { class: 'plan' + (p.id === selected ? ' on' : '') + (p.badge ? ' has-tag' : ''), onclick: function () { selected = p.id; Platform.haptic('select'); draw(d); } },
            p.badge ? h('span', { class: 'chip ' + (p.id === 'yearly' ? 'gold' : 'accent') + ' tag' }, p.badge) : null,
            h('span', { class: 'radio' }),
            h('div', { class: 'grow' }, h('div', { class: 'bold' }, p.title), h('div', { class: 'small muted' }, fa(p.days) + ' روز • ماهانه ' + toman(perMonth))),
            h('div', { class: 'price' }, p.old_price ? h('s', null, fa(p.old_price)) : null, h('b', null, fa(p.price)), h('span', { class: 'small muted' }, 'تومان'))));
        });
        w.appendChild(plans);
        w.appendChild(h('div', { class: 'alert mt-12' }, icon('info'), h('div', null, 'پرداخت داخل مینی‌اپ انجام نمی‌شود؛ فاکتور رسمی در چت بله برایتان ارسال می‌شود و پس از پرداخت، VIP خودکار فعال می‌شود.')));
        w.appendChild(SectionTitle('تاریخچه پرداخت'));
        if (d.payments.length) w.appendChild(h('div', { class: 'list' }, d.payments.map(function (p) {
          return ListItem({ icon: 'receipt', tone: p.status === 'failed' ? 'danger' : p.status === 'pending' ? 'warn' : '', title: p.plan_title, sub: jdate(p.created_at, true), end: h('div', { style: 'text-align:left' }, h('div', { class: 'bold', style: 'color:var(--text)' }, toman(p.amount)), statusChip(p.status)) });
        })));
        else w.appendChild(h('div', { class: 'card' }, Empty({ icon: 'receipt', title: 'پرداختی ثبت نشده', text: 'پس از اولین خرید، سوابق اینجا نمایش داده می‌شود.' })));
        ctx.body.replaceChildren(w);
        var plan = d.plans.filter(function (p) { return p.id === selected; })[0];
        MainAction.set((st.active ? 'تمدید • ' : 'خرید • ') + toman(plan.price), function () { buy(plan); }, { kind: 'gold' });
      }
      function buy(plan) {
        Platform.haptic('medium'); MainAction.loading(true);
        api('/vip/purchase', { method: 'POST', body: { plan_id: plan.id } }).then(function () {
          MainAction.loading(false); Cache.del('vip');
          openSheet({
            title: '',
            body: h('div', { class: 'center' },
              h('div', { class: 'g-icon', style: 'width:76px;height:76px;border-radius:26px;margin:0 auto 12px;display:flex;align-items:center;justify-content:center;background:var(--accent-soft);color:var(--accent)' }, icon('receipt')),
              h('h3', { style: 'margin:0 0 6px;font-weight:800' }, 'فاکتور در چت بله ارسال شد'),
              h('p', { class: 'muted small', style: 'margin:0 0 14px' }, plan.title + ' • ' + toman(plan.price)),
              h('div', { class: 'list', style: 'text-align:right' },
                ListItem({ icon: 'bot', title: '۱. به چت ربات در بله بروید', sub: 'فاکتور به‌صورت پیام برایتان آمده است' }),
                ListItem({ icon: 'receipt', title: '۲. روی «پرداخت» بزنید', sub: 'پرداخت از طریق درگاه رسمی بله' }),
                ListItem({ icon: 'crown', tone: 'gold', title: '۳. VIP خودکار فعال می‌شود', sub: 'نیازی به ارسال رسید نیست' })),
              State.demo ? h('div', { class: 'alert warn mt-12', style: 'text-align:right' }, icon('info'), h('div', null, 'در حالت دمو فاکتور واقعی ارسال نمی‌شود.')) : null),
            actions: [{ text: 'رفتن به چت ربات', icon: 'external', onClick: function (close) { close(); Platform.openBot(); } }, { text: 'باشه', kind: 'ghost' }],
            onClose: function () { if (ctx.alive) ctx.reload(); }
          });
        }, function (e) { MainAction.loading(false); toast(errMsg(e), 'error'); });
      }
    }
  });

  /* ===================== Chat view (shared: support & admin ticket) ===================== */
  function ChatView(ctx, o) {
    // o: {fetch(), send(text), mine: 'user'|'admin', empty: Node, attach: fn, pollMs, lockedBanner(meta), topNode: Node}
    var chat = h('div', { class: 'chat' });
    var ta = h('textarea', { rows: 1, placeholder: o.placeholder || 'پیام خود را بنویسید…', maxLength: 2000 });
    var sendBtn = h('button', { class: 'send', disabled: true, 'aria-label': 'ارسال' }, icon('send'));
    var composer = h('div', { class: 'composer' }, o.attach ? h('button', { class: 'attach', 'aria-label': 'پیوست', onclick: o.attach }, icon('clip')) : null, ta, sendBtn);
    var lastJson = null, firstLoad = true, lockedNode = null;
    /* v4.7: گرهٔ اختیاری بالای چت (مثلاً کارت کانال اطلاع‌رسانی در پشتیبانی) */
    var topNode = o.topNode || null;
    /* v4.4: قفل کامپوزر (مثلاً پیام ناشناس فقط VIP) — بنر جای کامپوزر می‌نشیند */
    function applyLock(meta) {
      var want = o.lockedBanner ? o.lockedBanner(meta) : null;
      if (want && !lockedNode) { lockedNode = want; if (composer.parentNode) composer.replaceWith(lockedNode); }
      else if (!want && lockedNode) { lockedNode.replaceWith(composer); lockedNode = null; }
    }
    ctx.body.replaceChildren(Skel.chat());
    ta.addEventListener('input', function () { ta.style.height = 'auto'; ta.style.height = Math.min(120, ta.scrollHeight) + 'px'; sendBtn.disabled = !ta.value.trim(); });
    ta.addEventListener('keydown', function (e) { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send(); });
    sendBtn.addEventListener('click', send);
    function bubble(m, pending) {
      var mine = m.from === o.mine;
      return h('div', { class: 'bubble ' + (mine ? 'me' : 'them') + (pending ? ' pending' : '') },
        m.media_type ? h('div', { class: 'media' }, icon('image'), m.media_type === 'photo' ? 'تصویر (در چت بله قابل مشاهده است)' : 'فایل پیوست (در چت بله)') : null,
        m.text, h('div', { class: 'meta' }, jtime(m.created_at), mine ? icon(pending ? 'clock' : 'checks') : null));
    }
    function paint(msgs) {
      var atBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
      chat.innerHTML = '';
      if (!msgs.length && o.empty) chat.appendChild(o.empty(function (t) { ta.value = t; ta.dispatchEvent(new Event('input')); ta.focus(); }));
      var lastDay = '';
      msgs.forEach(function (m) {
        var day = jdate(m.created_at); if (day !== lastDay) { chat.appendChild(h('div', { class: 'day-sep' }, day)); lastDay = day; }
        chat.appendChild(bubble(m));
      });
      if (firstLoad || atBottom) requestAnimationFrame(function () { chat.scrollTop = chat.scrollHeight; });
      firstLoad = false;
    }
    var messages = [];
    function load(silent) {
      return o.fetch().then(function (d) {
        if (!ctx.alive) return;
        applyLock(d.meta || d);
        if (ctx.body.firstChild !== chat) {
          if (topNode) ctx.body.replaceChildren(topNode, chat, lockedNode || composer);
          else ctx.body.replaceChildren(chat, lockedNode || composer);
        }
        if (o.onMeta) o.onMeta(d);
        var j = JSON.stringify(d.messages); if (j === lastJson) return; lastJson = j; messages = d.messages; paint(messages);
      }, function (e) {
        if (!ctx.alive) return;
        if (!silent || lastJson === null) ctx.body.replaceChildren(ErrorState(e, function () { ctx.body.replaceChildren(Skel.chat()); load(); }));
      });
    }
    function send() {
      var text = ta.value.trim(); if (!text) return;
      Platform.haptic('light');
      var temp = { from: o.mine, text: text, created_at: new Date().toISOString() };
      var b = bubble(temp, true); chat.appendChild(b); chat.scrollTop = chat.scrollHeight;
      ta.value = ''; ta.dispatchEvent(new Event('input'));
      o.send(text).then(function () { lastJson = null; load(true); }, function (e) { b.remove(); ta.value = text; ta.dispatchEvent(new Event('input')); toast(errMsg(e), 'error'); });
    }
    load();
    var timer = setInterval(function () { if (document.visibilityState === 'visible' && State.online) load(true); }, o.pollMs || 15000);
    ctx.onCleanup(function () { clearInterval(timer); });
    ctx.reload = function () { lastJson = null; return load(true); };
  }

  /* ===================== Page: Support ===================== */
  Router.def('support', {
    flush: true,
    render: function (ctx) {
      var chipEl = h('span', { class: 'chip accent' }, 'آنلاین');
      /* v4.4: پشتیبانی اولویت‌دار VIP — برچسب ⚡️ برای اعضای کارت طلایی */
      var isVipNow = !!(State.me && State.me.vip && State.me.vip.active);
      ctx.header({ title: 'پشتیبانی', subtitle: isVipNow ? '⚡️ اولویت VIP — پاسخ در اولویت ارسال می‌شود' : 'معمولاً در کمتر از ۲ ساعت پاسخ می‌دهیم', actions: [chipEl, h('div', { style: 'width:8px' })] });
      /* v4.7 (بخش ارتباط): کارت کانال اطلاع‌رسانی @fzxinfo — هدایت مستقیم به کانال */
      var infoCard = h('button', { class: 'card fzxinfo-card', onclick: function () {
        Platform.haptic('light'); Platform.openLink(CFG.deepLinkBase + 'fzxinfo');
      } },
        h('div', { class: 'li-icon', style: 'background:var(--accent-soft);color:var(--accent)' }, icon('megaphone')),
        h('div', { class: 'grow', style: 'text-align:right' },
          h('div', { class: 'bold' }, 'کانال اطلاع‌رسانی فضول‌یاب'),
          h('div', { class: 'small muted ltr' }, '@fzxinfo')),
        icon('external'));
      var topArea = h('div', { class: 'mb-12', style: 'margin-bottom:12px' }, infoCard);
      ChatView(ctx, {
        topNode: topArea,
        mine: 'user',
        fetch: function () { return api('/support/messages'); },
        send: function (text) { return api('/support/messages', { method: 'POST', body: { text: text } }); },
        onMeta: function (d) { var open = d.ticket && d.ticket.status !== 'closed'; chipEl.className = 'chip ' + (open ? 'accent' : ''); chipEl.textContent = open ? 'گفتگو باز' : 'بسته‌شده'; },
        pollMs: State.demo ? 4000 : 15000,
        attach: function () {
          openSheet({
            title: 'ارسال عکس، ویدیو یا فایل',
            body: h('div', { class: 'stack' }, h('div', { class: 'alert' }, icon('info'), h('div', null, 'برای حفظ کیفیت و امنیت، ارسال مدیا و فایل از داخل چت ربات در بله انجام می‌شود. پاسخ‌ها هم‌زمان اینجا و در چت نمایش داده می‌شوند.'))),
            actions: [{ text: 'ارسال از چت بله', icon: 'external', onClick: function (close) { close(); Platform.openBot('support'); } }]
          });
        },
        empty: function (fill) {
          return h('div', { class: 'card', style: 'margin:auto 0' }, Empty({ icon: 'message', title: 'سلام! چطور کمکت کنیم؟', text: 'سؤال یا مشکلت را بنویس؛ پاسخ هم اینجا و هم در چت بله می‌رسد.' }),
            h('div', { class: 'chips', style: 'justify-content:center;flex-wrap:wrap' }, ['مشکل در پرداخت', 'لینکم کار نمی‌کند', 'پیشنهاد دارم'].map(function (t) { return h('button', { class: 'chip', onclick: function () { fill(t + ': '); } }, t); })));
        }
      });
    }
  });

  /* ===================== Page: Chat (گفتگوهای ناشناس — تب اصلی) ===================== */
  Router.def('chat', {
    render: function (ctx) {
      ctx.header({ title: 'چت', subtitle: 'گفتگوهای ناشناس', actions: [iconBtn('refresh', function () { ctx.reload(); }, 'به‌روزرسانی')] });
      useData(ctx, 'chat', function () { return api('/chat/conversations'); }, draw, Skel.list);
      function draw(d) {
        if (!d.items.length) {
          ctx.body.replaceChildren(Empty({
            icon: 'message', title: 'هنوز گفتگویی نداری',
            text: 'وقتی کسی برات پیام ناشناس بفرسته یا از لیست فضول‌ها بهش ناشناس پیام بدی، گفتگوها همین‌جا جمع می‌شوند. هویت طرف مقابل همیشه محفوظ می‌ماند.',
            action: { text: 'رفتن به فضول‌یاب', icon: 'eye', onClick: function () { Router.tab('snoop'); } }
          }));
          return;
        }
        ctx.body.replaceChildren(h('div', { class: 'list' }, d.items.map(function (c) {
          return ListItem({
            lead: c.avatar && !c.masked ? Avatar(c.name, c.token, { photo: c.avatar }) : Avatar(c.name, c.token, { masked: true }),
            title: c.name,
            sub: (c.last_from_me ? 'شما: ' : '') + (c.last_text || '—'),
            end: h('div', { style: 'display:flex;flex-direction:column;align-items:flex-end;gap:4px' },
              h('span', { class: 'small muted' }, ago(c.last_at)),
              (c.count_in && !c.last_from_me) ? h('span', { class: 'chip accent' }, fa(c.count_in) + ' پیام') : null),
            onClick: function () { Router.go('chat-thread', { token: c.token, name: c.name }); }
          });
        })));
      }
    }
  });

  Router.def('chat-thread', {
    flush: true,
    render: function (ctx) {
      var token = ctx.params.token;
      ctx.header({ title: ctx.params.name || 'گفتگو', subtitle: 'گفتگوی ناشناس • هویت مخفی می‌ماند' });
      ChatView(ctx, {
        mine: 'me',
        placeholder: 'پیام ناشناس خود را بنویسید…',
        fetch: function () {
          return api('/chat/thread/' + encodeURIComponent(token)).then(function (d) {
            return { messages: d.messages.map(function (m) { return { from: m.mine ? 'me' : 'them', text: m.text, created_at: m.created_at }; }), meta: d };
          });
        },
        send: function (text) { return api('/chat/send', { method: 'POST', body: { token: token, text: text } }); },
        /* v4.4: پیام ناشناس فقط VIP — کامپوزر برای غیر-VIP بسته می‌شود */
        lockedBanner: function (meta) {
          return (meta && meta.vip_required) ? h('div', { class: 'alert warn', style: 'margin:0 12px 10px', onclick: function () { Platform.haptic('light'); Router.tab('vip'); } }, icon('lock'), h('div', null, 'ارسال پیام ناشناس فقط برای اعضای VIP است. ', h('b', null, 'فعال‌سازی VIP ←'))) : null;
        },
        onMeta: function (d) {
          if (d && d.partner) ctx.header({ title: d.partner.name || 'گفتگو', subtitle: 'گفتگوی ناشناس • هویت مخفی می‌ماند' });
        },
        pollMs: State.demo ? 5000 : 10000,
        empty: function (fill) {
          return h('div', { class: 'card', style: 'margin:auto 0' }, Empty({ icon: 'message', title: 'شروع گفتگوی ناشناس', text: 'اولین پیامت را بنویس؛ برای طرف مقابل کاملاً ناشناس می‌ماند.' }),
            h('div', { class: 'chips', style: 'justify-content:center;flex-wrap:wrap' }, ['سلام 👋', 'یه سؤال دارم', 'راستش رو بگو!'].map(function (t) { return h('button', { class: 'chip', onclick: function () { fill(t + ' '); } }, t); })));
        }
      });
    }
  });

  /* ===================== Page: Profile ===================== */
  Router.def('profile', {
    render: function (ctx) {
      ctx.header({ title: 'پروفایل' });
      useData(ctx, 'me', function () { return api('/me'); }, function (me) { State.me = me; if (window.FzVip) window.FzVip.apply(me); draw(me); }, Skel.cards);
      function draw(me) {
        var u = me.user, full = (u.first_name || '') + ' ' + (u.last_name || ''), w = h('div', null);
        w.appendChild(h('div', { class: 'card center', style: 'padding:22px 16px' },
          h('div', { style: 'display:flex;justify-content:center' }, Avatar(full, u.id, { lg: true, vip: me.vip.active, photo: u.avatar })),
          h('div', { class: 'bold mt-8', style: 'font-size:18px' }, full.trim()),
          u.username ? h('div', { class: 'muted ltr small' }, '@' + u.username) : null,
          h('div', { class: 'row', style: 'justify-content:center;margin-top:10px;flex-wrap:wrap' }, vipChip(me.vip), me.is_admin ? h('span', { class: 'chip accent' }, icon('shield'), 'ادمین') : null,
            h('button', { class: 'chip', onclick: function () { copyText(String(u.id)).then(function () { toast('شناسه کپی شد', 'success'); }); } }, icon('hash'), h('span', { class: 'ltr' }, String(u.id))))));
        w.appendChild(h('div', { class: 'stat-grid two' },
          h('div', { class: 'stat' }, icon('star'), h('div', { class: 'v' }, 'سطح ' + fa(me.xp.level)), h('div', { class: 'k' }, fa(me.xp.xp) + ' امتیاز XP')),
          h('div', { class: 'stat' }, icon('calendar'), h('div', { class: 'v', style: 'font-size:15px' }, jdate(u.joined_at)), h('div', { class: 'k' }, 'تاریخ عضویت'))));
        /* v4.4: ویترین کارآگاهی — لقب فعال + ویرایش نام/لقب + کارت هر نشان */
        var vit = h('div', null);
        w.appendChild(SectionTitle('ویترین کارآگاهی'));
        w.appendChild(vit);
        api('/profile').then(function (p) {
          if (!ctx.alive) return;
          vit.replaceChildren(
            h('div', { class: 'card', style: 'text-align:center;padding:16px 12px' },
              h('div', { class: 'small muted' }, 'لقب کارآگاهی فعال'),
              h('div', { class: 'title-row' }, p.title.emoji + ' ' + p.title.title, p.title.custom ? h('span', { class: 'chip gold', style: 'font-size:9px;padding:2px 8px' }, 'انتخاب تو') : null),
              p.display_name ? h('div', { class: 'small', style: 'margin-top:6px' }, 'نام نمایشی: ', h('b', null, p.display_name)) : h('div', { class: 'small muted', style: 'margin-top:6px' }, 'نام اکانت بله نمایش داده می‌شود'),
              h('button', { class: 'btn btn-secondary btn-sm', style: 'margin-top:10px', onclick: function () { profileEditSheet(p); } }, icon('edit') || icon('user'), 'ویرایش نام و لقب')),
            h('div', { class: 'badge-grid' }, p.badges.map(function (b) {
              return h('div', { class: 'badge-card' + (b.earned ? ' earned' : '') },
                h('div', { class: 'badge-emoji' }, b.emoji),
                h('div', { class: 'bold', style: 'font-size:13px' }, b.title),
                h('div', { class: 'muted' }, b.earned ? b.desc : (b.goal ? fa(b.goal) + ' — ' + b.desc : b.desc)),
                b.earned ? h('span', { class: 'chip gold' }, '✓ کسب شد') : null);
            })));
        }, function () { vit.replaceChildren(h('div', { class: 'card' }, Empty({ icon: 'star', title: 'ویترین در دسترس نیست', text: 'لحظه‌ای بعد دوباره امتحان کن.' }))); });
        w.appendChild(SectionTitle('فعالیت'));
        /* v4.4: کارت استریک روزانه + سپر VIP + جایزهٔ هفتگی */
        var stStreak = me.streak || { count: 0, shield: false, days_to_weekly: 7 };
        w.appendChild(h('div', { class: 'list' },
          ListItem({ icon: 'fire', tone: 'warn', title: 'استریک روزانه: ' + fa(stStreak.count) + ' روز',
            sub: stStreak.shield ? '🛡️ سپر VIP فعال — با غیبت یک‌روزه زنجیره‌ات نمی‌سوزد • ' + fa(stStreak.days_to_weekly) + ' روز تا جایزهٔ هفتگی (۱ روز VIP)' : (stStreak.count > 0 ? fa(stStreak.days_to_weekly) + ' روز تا جایزهٔ هفتگی • سپر VIP نداری' : 'هر روز بیا تا زنجیره‌ات بسازد'),
            onClick: function () { Router.go('wheel'); } }),
          ListItem({ icon: 'trophy', tone: 'warn', title: 'جدول برترین‌ها', sub: me.rank ? 'رتبهٔ شما: ' + fa(me.rank) : null, onClick: function () { Router.go('leaderboard'); } }),
          ListItem({ icon: 'gift', tone: 'danger', title: 'گردونه شانس', sub: me.wheel.can_spin ? 'چرخش امروزت آماده است 🎁' : 'چرخش بعدی: ' + until(me.wheel.next_spin_at), onClick: function () { Router.go('wheel'); } }),
          ListItem({ icon: 'receipt', title: 'تاریخچه پرداخت و VIP', onClick: function () { Router.tab('vip'); } })));
        w.appendChild(SectionTitle('تنظیمات'));
        var hapticSw = h('span', { class: 'switch' + (LS.get('haptic', true) ? ' on' : '') });
        var themeLabel = { auto: 'هماهنگ با بله', light: 'روشن', dark: 'تیره' };
        w.appendChild(h('div', { class: 'list' },
          ListItem({ icon: 'palette', tone: 'info', title: 'پوسته', end: themeLabel[Theme.pref], onClick: themeSheet }),
          ListItem({ icon: 'vibrate', tone: 'info', title: 'لرزش هنگام لمس', end: hapticSw, noChev: true, onClick: function () { var v = !LS.get('haptic', true); LS.set('haptic', v); hapticSw.classList.toggle('on', v); if (v) Platform.haptic('medium'); } })));
        if (me.is_admin) {
          w.appendChild(SectionTitle('مدیریت'));
          w.appendChild(h('div', { class: 'list' }, ListItem({ icon: 'shield', title: 'پنل سوپر ادمین', sub: 'آمار، کاربران، پخش همگانی، بکاپ', onClick: function () { Router.tab('admin'); } })));
        }
        w.appendChild(SectionTitle('ارتباط'));
        w.appendChild(h('div', { class: 'list' },
          ListItem({ icon: 'bot', title: 'باز کردن ربات در بله', sub: '@' + CFG.botUsername, onClick: function () { Platform.openBot(); } }),
          /* v4.7 (بخش ارتباط): کانال اطلاع‌رسانی @fzxinfo — هدایت مستقیم به کانال */
          ListItem({ icon: 'megaphone', tone: 'warn', title: 'کانال اطلاع‌رسانی', sub: '@fzxinfo — خبرها و آپدیت‌ها', onClick: function () { Platform.haptic('light'); Platform.openLink(CFG.deepLinkBase + 'fzxinfo'); } }),
          ListItem({ icon: 'message', tone: 'info', title: 'چت پشتیبانی', sub: 'پاسخ‌ها هم‌زمان در بله و اینجا', onClick: function () { Router.go('support'); } }),
          ListItem({ icon: 'info', title: 'درباره ' + CFG.appName, onClick: aboutSheet })));
        if (State.demo) {
          var regSw = h('span', { class: 'switch' + (Demo.db.regularView ? ' on' : '') });
          w.appendChild(SectionTitle('ابزار حالت دمو'));
          w.appendChild(h('div', { class: 'list' },
            ListItem({ icon: 'user', tone: 'warn', title: 'نمایش به‌عنوان کاربر عادی', sub: 'بدون VIP و بدون دسترسی ادمین', end: regSw, noChev: true, onClick: function () {
              Demo.db.regularView = !Demo.db.regularView; Cache.m = {}; refreshMe().then(function () { Shell.renderNav(); Router.refresh(); toast(Demo.db.regularView ? 'نمای کاربر عادی' : 'نمای ادمین VIP', 'success'); });
            } }),
            ListItem({ icon: 'lock', tone: 'warn', title: 'شبیه‌سازی عضویت اجباری کانال', onClick: function () { Demo.db.channelJoined = false; Demo.db.joinClicked = false; Cache.m = {}; refreshMe().then(function (m) { Gate.show(m.channels.required); }); } })));
        }
        w.appendChild(h('div', { class: 'center muted small', style: 'margin:22px 0 4px' }, CFG.appName + ' • نسخه ' + faDigits(CFG.version) + ' • مینی‌اپ بله'));
        ctx.body.replaceChildren(w);
      }
      function themeSheet() {
        var s = openSheet({
          title: 'پوسته',
          body: function (close) {
            return h('div', { class: 'list' }, [['auto', 'هماهنگ با بله', 'palette'], ['light', 'روشن', 'sun'], ['dark', 'تیره', 'moon']].map(function (o) {
              return ListItem({ icon: o[2], title: o[1], end: Theme.pref === o[0] ? h('span', { style: 'color:var(--accent);width:20px;height:20px;display:inline-flex' }, icon('check')) : null, noChev: true, onClick: function () { Theme.set(o[0]); close(); Router.refresh(); } });
            }));
          }
        });
        return s;
      }
      function aboutSheet() {
        openSheet({ title: 'درباره ' + CFG.appName, body: h('div', { class: 'stack' },
          h('p', { style: 'margin:0;font-size:14px;line-height:1.9' }, CFG.appName + ' به تو کمک می‌کند بفهمی چه کسانی به لینک‌هایت در بله سرک کشیده‌اند. لینک اختصاصی‌ات را منتشر کن، تله بساز، XP جمع کن و در جدول برترین‌ها بالا برو.'),
          h('div', { class: 'card info-rows' }, infoRow('نسخه', faDigits(CFG.version)), infoRow('پلتفرم', 'مینی‌اپ بله'), infoRow('ربات', h('span', { class: 'ltr' }, '@' + CFG.botUsername)))) });
      }
      /* v4.4: ویرایش آزاد نام نمایشی + انتخاب لقب کارآگاهی (از لقب‌های بازشده) */
      function profileEditSheet(p) {
        var nameInp = h('input', { class: 'input', maxLength: 32, placeholder: 'نامی که به همه نمایش داده می‌شود', value: p.display_name || '' });
        var selectedTitle = p.title.custom ? p.title.key : null; // null = خودکار
        function titleRows() {
          return p.titles.map(function (t) {
            var isActive = (selectedTitle === t.key) || (selectedTitle === null && t.active);
            return h('button', { class: 'lb-row', style: 'width:100%;text-align:right;border:1px solid ' + (isActive ? 'var(--gold-2)' : 'var(--border)'), onclick: function () {
              if (!t.unlocked) { toast('این لقب با سطح ' + fa(t.key) + ' باز می‌شود', 'error'); return; }
              if (selectedTitle === t.key) selectedTitle = null; else selectedTitle = t.key;
              Platform.haptic('select'); bodyWrap.replaceChildren(h('div', { class: 'stack' }, titleRows()));
            } },
              h('span', { style: 'font-size:20px;' }, t.unlocked ? t.emoji : '🔒'),
              h('div', { class: 'grow' }, h('div', { class: 'bold small' }, t.title), h('div', { class: 'small muted' }, t.unlocked ? (isActive ? 'فعال' : 'باز شده') : 'با سطح ' + fa(t.key) + ' باز می‌شود')),
              isActive ? h('span', { style: 'color:var(--gold-2);width:20px;height:20px;display:inline-flex;flex-shrink:0' }, icon('check')) : null);
          });
        }
        var bodyWrap = h('div', { class: 'stack' }, titleRows());
        openSheet({
          title: 'ویرایش پروفایل',
          body: h('div', { class: 'stack' },
            h('div', { class: 'field' }, h('label', null, 'نام نمایشی تو (برای همه)'), nameInp,
              h('div', { class: 'hint' }, h('span', null, 'خالی بگذاری، نام اکانت بله نمایش داده می‌شود'))),
            h('div', { class: 'field' }, h('label', null, 'لقب کارآگاهی (از لقب‌های بازشده انتخاب کن)'), bodyWrap)),
          actions: [
            { text: 'ذخیره', icon: 'check', onClick: function (close, btn) {
                var payload = {};
                if (nameInp.value.trim()) payload.display_name = nameInp.value.trim(); else payload.reset_name = true;
                if (selectedTitle !== null) payload.active_title = selectedTitle; else payload.reset_title = true;
                withLoading(btn, api('/profile/edit', { method: 'POST', body: payload })).then(function () {
                  close(); toast('پروفایل ذخیره شد ✅', 'success'); Cache.del('me'); if (ctx.alive) ctx.reload();
                }, function (e) { toast(errMsg(e), 'error'); });
              } },
            { text: 'انصراف', kind: 'ghost' }
          ]
        });
      }
    }
  });

  /* ===================== Page: Leaderboard (بازطراحی کامل — قالب leaderboard.zip) ===================== */
  var LB_SVG = {
    coin: '<svg viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="lbCoinG" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FFE9A8"/><stop offset=".55" stop-color="#FFC531"/><stop offset="1" stop-color="#E8930C"/></linearGradient></defs><circle cx="10" cy="10" r="9" fill="url(#lbCoinG)" stroke="#B96A00" stroke-width="1"/><circle cx="10" cy="10" r="6.2" fill="none" stroke="#FFF7D6" stroke-width="1.2" stroke-dasharray="2.5 2"/><path d="M10 6.2v1M10 12.8v1M12.4 8.2c-.5-.6-1.3-.9-2.4-.9-1.4 0-2.3.7-2.3 1.7 0 2.2 4.8 1.1 4.8 3.3 0 1-1 1.7-2.5 1.7-1.1 0-2-.3-2.5-1" stroke="#7A4A00" stroke-width="1.3" stroke-linecap="round" fill="none"/></svg>',
    crownCh: '<svg viewBox="0 0 48 36" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="lbChG" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFF3C4"/><stop offset=".35" stop-color="#FFD84D"/><stop offset=".7" stop-color="#F5A623"/><stop offset="1" stop-color="#C77400"/></linearGradient></defs><ellipse cx="24" cy="32.5" rx="16" ry="2.6" fill="#fff" opacity=".35"/><path d="M6 27.5 3.5 10.5c-.2-1.4 1.25-2.4 2.45-1.65L14 14.5 20.6 4.4c.7-1.1 2.3-1.1 3 0l6.6 10.1 8.05-5.65c1.2-.8 2.65.25 2.45 1.65L42 27.5H6Z" fill="url(#lbChG)" stroke="#8A4E00" stroke-width="1.2" stroke-linejoin="round"/><circle cx="9.5" cy="11.5" r="2.5" fill="#0B83D9" stroke="#fff" stroke-width="1.2"/><circle cx="24" cy="8.5" r="3" fill="#12B76A" stroke="#fff" stroke-width="1.4"/><circle cx="38.5" cy="11.5" r="2.5" fill="#0B83D9" stroke="#fff" stroke-width="1.2"/><circle cx="16.5" cy="20" r="1.6" fill="#fff"/><circle cx="24" cy="21.2" r="1.9" fill="#fff"/><circle cx="31.5" cy="20" r="1.6" fill="#fff"/><rect x="6" y="26" width="36" height="6" rx="3" fill="#062A63" stroke="#FFD84D" stroke-width="1.2"/><circle cx="24" cy="29" r="1.8" fill="#FFD84D"/></svg>',
    crownVip: '<svg viewBox="0 0 32 24" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="lbVipG" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFE9A8"/><stop offset=".38" stop-color="#FFD14D"/><stop offset=".75" stop-color="#F5A623"/><stop offset="1" stop-color="#D9820B"/></linearGradient></defs><path d="M3 18.5 1.6 7.2c-.15-1 .9-1.7 1.75-1.15L9 10l4.2-6.6c.5-.8 1.66-.8 2.16 0L19.6 10l5.65-3.95c.85-.55 1.9.15 1.75 1.15L25.6 18.5H3Z" fill="url(#lbVipG)" stroke="#B96A00" stroke-width="1" stroke-linejoin="round"/><circle cx="6.2" cy="8.2" r="1.7" fill="#0B83D9" stroke="#fff" stroke-width=".9"/><circle cx="16" cy="6.6" r="2" fill="#0AA884" stroke="#fff" stroke-width="1"/><circle cx="25.8" cy="8.2" r="1.7" fill="#0B83D9" stroke="#fff" stroke-width=".9"/><circle cx="11.2" cy="13.4" r="1.15" fill="#fff" opacity=".9"/><circle cx="16" cy="14.2" r="1.35" fill="#fff" opacity=".95"/><circle cx="20.8" cy="13.4" r="1.15" fill="#fff" opacity=".9"/><rect x="3" y="17.2" width="26" height="4.2" rx="2.1" fill="#0AA884" stroke="#fff" stroke-width="1"/></svg>',
    trophy: '<svg viewBox="0 0 24 24" fill="none"><path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0V4Z" stroke="#FFD84D" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="rgba(255,216,77,.35)"/><path d="M17 5h3v2a3 3 0 0 1-3 3M7 5H4v2a3 3 0 0 0 3 3" stroke="#FFD84D" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
  };
  function lbCoin(size) { return h('span', { class: 'lb-coin', style: { width: size + 'px', height: size + 'px' }, html: LB_SVG.coin, 'aria-hidden': 'true' }); }
  function lbVipTag() { return h('span', { class: 'lb-viptag' }, h('i', { html: LB_SVG.crownVip, 'aria-hidden': 'true' }), 'ویژه'); }

  Router.def('leaderboard', {
    render: function (ctx) {
      var period = 'week';
      ctx.header({ title: 'جدول برترین‌ها', subtitle: 'بر اساس امتیاز XP' });
      ctx.body.classList.add('lb-body'); // v4.6: بدون padding انتهایی تا نوار چسبان پایین کاملاً به لبه بچسبد
      function load() {
        useData(ctx, 'lb:' + period, function () { return api('/leaderboard?period=' + period); }, draw,
          function () { return h('div', { class: 'stack', style: 'padding:14px' }, Skel.block(230, 22), Skel.list(6)); });
      }
      function daysLeftOfWeek() {
        var day = new Date().getDay(); // 0=یک‌شنبه … 6=جمعه — هفتهٔ ما شنبه‌ تا جمعه
        return (5 - day + 7) % 7;
      }
      function draw(d) {
        var w = h('div', { class: 'lb' });
        // ---- v4.5: داک سربرگ — دقیقاً مطابق قالب مرجع کاربر (کارت مستقل: عنوان+چیپ، خط وضعیت، نوار آمار تاریک) ----
        var tabs = h('div', { class: 'lb-tabs lb-tabs--out', role: 'tablist' },
          h('button', { class: period === 'week' ? 'on' : '', role: 'tab', onclick: function () { if (period !== 'week') { period = 'week'; Platform.haptic('select'); load(); } } }, icon('calendar'), h('span', null, 'این هفته'), period !== 'week' ? h('em', null, 'زنده') : null),
          h('button', { class: period === 'all' ? 'on' : '', role: 'tab', onclick: function () { if (period !== 'all') { period = 'all'; Platform.haptic('select'); load(); } } }, icon('bolt'), h('span', null, 'کل دوران')));
        var stats = h('div', { class: 'lb-stats' },
          h('span', null, icon('users'), h('b', null, fa(d.participants)), ' شرکت‌کننده'),
          h('i', null),
          h('span', null, icon('trophy'), 'رتبهٔ شما: ', h('b', null, fa(d.me.rank))),
          h('i', null),
          period === 'week'
            ? h('span', null, icon('clock'), h('b', null, fa(daysLeftOfWeek())), ' روز تا پایان هفته')
            : h('span', null, icon('clock'), 'از ابتدای فعالیت'));
        w.appendChild(h('div', { class: 'lb-head' },
          h('div', { class: 'lb-head-row' },
            h('h2', null, h('span', { class: 'lb-trophy', html: LB_SVG.trophy, 'aria-hidden': 'true' }), 'جدول امتیازات'),
            h('div', { class: 'lb-size' }, fa(d.size), ' نفر اول')),
          h('div', { class: 'lb-live' }, h('i', null), period === 'week' ? 'صفحهٔ جاری • بازهٔ زمانی هفته' : 'صفحهٔ جاری • بازهٔ زمانی کل دوران'),
          stats));
        w.appendChild(tabs);
        /* v4.6: کلید نمایش نام به کارت اطلاعات شخص (نوار پایین) منتقل شد — کارت مستقل حذف شد */
        if (!d.items.length) {
          w.appendChild(h('div', { class: 'lb-sheet' }, h('div', { class: 'lb-sheet-grip' }),
            Empty({ icon: 'trophy', title: 'هنوز رتبه‌ای ثبت نشده', text: 'با جمع‌کردن XP از گردونه و فعالیت‌ها، خودت را بالای جدول بگذار!' })));
          ctx.body.replaceChildren(w);
          return;
        }
        // ---- سکوی سه‌نفر اول (فقط وقتی حداقل ۳ نفر هست) ----
        var top = d.items.slice(0, 3), rest;
        function pod(r, place) {
          var is1 = place === 1;
          var av = Avatar(r.name || '؟', 'lbp' + r.rank, { photo: r.avatar });
          return h('div', { class: 'lb-pod ' + (is1 ? 'first' : place === 2 ? 'second' : 'third') },
            h('div', { class: 'lb-pod-av' },
              is1 ? h('span', { class: 'lb-crown', html: LB_SVG.crownCh, 'aria-hidden': 'true' }) : null,
              av,
              h('span', { class: 'lb-rank-badge' + (is1 ? ' gold' : place === 3 ? ' bronze' : '') }, fa(place))),
            h('p', { class: 'lb-pod-name ellipsis' }, r.is_me ? 'شما' : (r.name || 'کاربر')),
            h('p', { class: 'lb-pod-sub' }, 'سطح ' + fa(r.level), r.is_vip && !is1 ? h('i', { class: 'lb-pod-vip', html: LB_SVG.crownVip, 'aria-hidden': 'true', title: 'VIP' }) : null),
            h('span', { class: 'lb-score-pill' + (is1 ? ' solid' : '') }, lbCoin(13), h('b', null, fa(r.xp))),
            h('div', { class: 'lb-stand' }, h('b', null, fa(place))));
        }
        if (d.items.length >= 3) {
          rest = d.items.slice(3);
          w.appendChild(h('div', { class: 'lb-head lb-head--podium' }, h('div', { class: 'lb-podium' }, pod(top[1], 2), pod(top[0], 1), pod(top[2], 3))));
        } else {
          rest = d.items.slice();
        }
        // ---- برگهٔ رتبه‌بندی ----
        var sheet = h('div', { class: 'lb-sheet' }, h('div', { class: 'lb-sheet-grip' }),
          h('div', { class: 'lb-sheet-head' },
            h('h3', null, 'رتبه‌بندی برتر', h('span', { class: 'lb-sheet-badge' }, period === 'week' ? 'هفتهٔ جاری' : 'همهٔ زمان‌ها'))));
        var rows = h('div', { class: 'lb-rows' });
        rest.forEach(function (r, i) {
          rows.appendChild(h('div', { class: 'lb-row' + (r.is_me ? ' me' : '') + (r.is_vip ? ' vip' : ''), style: { animationDelay: Math.min(i * 45, 400) + 'ms' } },
            h('span', { class: 'lb-rank' + (r.rank <= 3 ? ' top' : '') }, fa(r.rank)),
            Avatar(r.name || '؟', 'lbr' + r.rank, { photo: r.avatar, vip: r.is_vip }),
            h('div', { class: 'lb-row-body' },
              h('div', { class: 'lb-row-name' }, h('span', { class: 'ellipsis' }, r.is_me ? r.name + ' (شما)' : (r.name || 'کاربر')), r.is_vip ? lbVipTag() : null),
              h('div', { class: 'lb-row-sub' }, 'سطح ' + fa(r.level))),
            h('div', { class: 'lb-row-score' }, lbCoin(15), h('b', null, fa(r.xp)), h('span', null, 'امتیاز'))));
        });
        if (rest.length) sheet.appendChild(rows);
        sheet.appendChild(h('p', { class: 'lb-foot' }, period === 'week' ? 'رتبه‌های هفتگی با امتیاز XP همین هفته محاسبه می‌شوند' : 'مجموع امتیازها از ابتدای فعالیت محاسبه شده است'));
        w.appendChild(sheet);
        // ---- v4.6: کارت رتبهٔ من — نوار دوردیف چسبیده به لبهٔ پایین مثل ناوبار:
        //      ردیف ۱ = کلید نمایش نام (دقیقاً مطابق نمونهٔ مرجع: برچسب + سوییچ + آیکون مربعی گرد)
        //      ردیف ۲ = اطلاعات شخص (رتبه، نام، نوار پیشرفت، امتیاز) ----
        var pct = d.items[0] && d.items[0].xp ? Math.max(5, Math.min(100, Math.round(d.me.xp / d.items[0].xp * 100))) : 5;
        var shown = !d.me.hidden;
        var docSw = h('span', { class: 'switch' + (shown ? ' on' : '') });
        var docIc = h('span', { class: 'lb-me-doc-ic' + (shown ? '' : ' off') }, icon('eye'));
        w.appendChild(h('div', { class: 'lb-me' },
          h('div', { class: 'lb-me-in' },
            h('button', { type: 'button', class: 'lb-me-doc', 'aria-label': 'تغییر وضعیت نمایش نام', onclick: function () {
              var next = !docSw.classList.contains('on'); // true = نام نمایش داده شود
              Platform.haptic('medium');
              docSw.classList.toggle('on', next);
              docIc.classList.toggle('off', !next);
              api('/leaderboard/visibility', { method: 'POST', body: { period: period, hidden: !next } }).then(function () {
                var c = Cache.get('lb:' + period);
                if (c && c.me) { c.me.hidden = !next; Cache.set('lb:' + period, c); }
                toast(next ? 'نامت در جدول نمایش داده می‌شود' : 'نامت مخفی شد', 'success');
                if (ctx.alive) ctx.reload(); // بازخوانی فوری: سوییچ، ردیف جدول و رتبه هم‌زمان به‌روز می‌شوند
              }, function (e) { docSw.classList.toggle('on', !next); docIc.classList.toggle('off', next); toast(errMsg(e), 'error'); });
            } },
              h('span', { class: 'lb-me-doc-label' }, 'نمایش نام من در جدول'),
              docSw, docIc),
            h('div', { class: 'lb-me-row' },
              h('span', { class: 'lb-me-rank' }, h('b', null, fa(d.me.rank)), h('small', null, 'شما')),
              Avatar(d.me.name || 'شما', 'lbme', { photo: d.me.avatar, vip: d.me.is_vip }),
              h('div', { class: 'lb-me-body' },
                h('p', null, h('b', { class: 'ellipsis' }, d.me.name || 'شما'), h('span', { class: 'lb-me-tag' }, period === 'week' ? 'این هفته' : 'کل دوران')),
                h('div', { class: 'lb-me-bar' }, h('i', { style: { width: pct + '%' } })),
                d.me.gap ? h('span', { class: 'lb-me-gap' }, 'تا رتبهٔ قبلی ', h('b', null, fa(d.me.gap)), ' امتیاز') : null),
              h('div', { class: 'lb-me-score' }, lbCoin(15), h('b', null, fa(d.me.xp)), h('span', null, 'امتیاز'))))));
        ctx.body.replaceChildren(w);
      }
      load();
    }
  });

  /* =====================================================================
     ماموریت‌ها — نسخهٔ بازطراحی‌شده (الهام از Notcoin، دقیقاً با توکن‌های تم فضول‌یاب)
     جایگزین کامل بلوک «v4.7: Page: Missions» در webapp/app.js
     وابستگی‌ها: فقط توابع موجود خود app.js — h, icon, fa, api, useData, Router, State,
     LS, Platform, toast, openSheet, Skel, Empty, iconBtn, withLoading, errMsg, refreshMe,
     shareLink, hyperlinkSheet. هیچ API یا ساختار دادهٔ جدیدی لازم نیست:
       GET /api/missions?page=N  → { page, tasks[], total_remaining, progress{done,total,pct} }
       GET /api/missions/{id}    → همان task + done
     اصل یکپارچگی پاداش: کلاینت هرگز «ادعای تکمیل» ارسال نمی‌کند؛ وضعیت و XP فقط از
     پاسخ سرور (award_pending → xp_bonuses با کلید یکتای user_id+bonus_type) خوانده می‌شود.
     ===================================================================== */
  var Missions = (function () {
    var CAT = {
      easy: { title: 'آسان', hint: 'شروع سریع، پاداش کوچک' },
      medium: { title: 'متوسط', hint: 'کمی پشتکار می‌خواهد' },
      hard: { title: 'سخت', hint: 'مخصوص کارآگاه‌های حرفه‌ای' }
    };
    var CAT_ORDER = { easy: 0, medium: 1, hard: 2 };
    function tone(t) { return CAT[t.category] ? t.category : 'easy'; }
    function todayKey() {
      try { return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Tehran' }).format(new Date()); }
      catch (e) { var d = new Date(); return d.getFullYear() + '-' + (d.getMonth() + 1) + '-' + d.getDate(); }
    }
    function textOf(t) { return (t.name || '') + ' ' + (t.desc || ''); }
    /* آیکن متمایز هر ماموریت از روی متن آن — ترتیب قواعد مهم است (خاص → عام) */
    var ICON_RULES = [
      [/XP/, 'bolt'], [/تله/, 'target'], [/لقب/, 'edit'], [/بی‌صدا|بی صدا/, 'ban'], [/بلاک/, 'ban'], [/ناشناس/, 'message'],
      [/کد هدیه/, 'gift'], [/زنجیره|استریک/, 'fire'], [/جایزهٔ? ?روزانه|ورود روزانه/, 'calendar'],
      [/گردونه|چرخ/, 'sparkles'], [/خوش‌آمد|نقاب|پروفایل|نام نمایشی/, 'user'],
      [/هدیهٔ? ?VIP/, 'gift'], [/VIP/, 'crown'], [/دعوت|کاربر جدید|معرفی/, 'users'],
      [/کلیک/, 'link'], [/فضول/, 'eye'], [/روز/, 'clock']
    ];
    function iconFor(t) {
      var s = textOf(t);
      for (var i = 0; i < ICON_RULES.length; i++) if (ICON_RULES[i][0].test(s)) return ICON_RULES[i][1];
      return 'target';
    }
    /* اقدام پیشنهادی هر ماموریت — فقط ناوبری به قابلیت‌های موجود؛ هیچ تأییدی سمت کلاینت انجام نمی‌شود */
    function ctaFor(t) {
      var s = textOf(t), link = State.me && State.me.snoop && State.me.snoop.link;
      if (/لقب|بی‌صدا|بی صدا|تله/.test(s)) return { text: 'رفتن به فضول‌یاب', icon: 'eye', run: function () { Router.tab('snoop'); } };
      if (/ناشناس|بلاک/.test(s)) return { text: 'رفتن به چت ناشناس', icon: 'message', run: function () { Router.tab('chat'); } };
      if (/کد هدیه|جایزهٔ? ?روزانه|گردونه|چرخ/.test(s)) return { text: 'رفتن به پاداش‌ها', icon: 'gift', run: function () { Router.go('wheel'); } };
      if (/VIP|خوش‌آمد|نقاب/.test(s)) return { text: 'رفتن به بخش VIP', icon: 'crown', run: function () { Router.tab('vip'); } };
      if (/نام نمایشی|پروفایل/.test(s)) return { text: 'رفتن به پروفایل', icon: 'user', run: function () { Router.tab('profile'); } };
      if (/دعوت|کاربر جدید|کلیک|فضول|تله/.test(s) && link) {
        return { text: 'اشتراک‌گذاری لینک', icon: 'share', run: function () { shareLink(link); },
          alt: { text: 'کپی هایپرلینک برای بیو', icon: 'copy', run: function () { hyperlinkSheet(link); } } };
      }
      return null;
    }
    function cmp(a, b) {
      var ca = CAT_ORDER[a.category], cb = CAT_ORDER[b.category];
      ca = ca === undefined ? 9 : ca; cb = cb === undefined ? 9 : cb;
      if (ca !== cb) return ca - cb;
      var ta = (a.progress && a.progress.threshold) || 0, tb = (b.progress && b.progress.threshold) || 0;
      if (ta !== tb) return ta - tb;
      if ((a.xp || 0) !== (b.xp || 0)) return (a.xp || 0) - (b.xp || 0);
      return String(a.id).localeCompare(String(b.id));
    }
    function pct(p) { return Math.max(0, Math.min(100, Math.round(p && p.pct || 0))); }

    /* ---------- اجزای نمایشی ---------- */
    function xpPill(t, done) {
      return h('span', { class: 'mz-xp' + (done ? ' done' : '') }, icon(done ? 'check' : 'bolt'), done ? 'واریز شد' : h('span', { class: 'ltr' }, '+' + fa(t.xp) + ' XP'));
    }
    function progressRow(p) {
      if (!p) return null;
      var v = pct(p);
      return h('div', { class: 'mz-prog' },
        h('div', { class: 'progress', role: 'progressbar', 'aria-valuenow': v, 'aria-valuemin': 0, 'aria-valuemax': 100 }, h('i', { style: { width: v + '%' } })),
        h('span', null, fa(p.value) + ' از ' + fa(p.threshold)));
    }
    function card(t, done, fresh, idx, onOpen) {
      var c = tone(t);
      return h('button', {
        class: 'card mz-card tone-' + c + (done ? ' is-done' : '') + (fresh ? ' mz-in' : ''),
        style: fresh ? { animationDelay: Math.min(idx || 0, 8) * 45 + 'ms' } : null,
        'aria-label': t.name + (done ? '، انجام شده' : '، ' + fa(t.xp) + ' XP'),
        onclick: function () { Platform.haptic('light'); onOpen(t); }
      },
        h('div', { class: 'mz-ic' }, icon(done ? 'check' : iconFor(t))),
        h('div', { class: 'mz-body' },
          h('div', { class: 'mz-top' }, h('div', { class: 'mz-title' }, t.name), xpPill(t, done)),
          h('div', { class: 'mz-desc' }, done ? 'ماموریت کامل شد و پاداش به حسابت اضافه شد.' : (t.desc || CAT[c].hint)),
          done ? null : progressRow(t.progress)),
        done ? null : icon('chevL', 'chev'));
    }
    function stat(v, k) { return h('div', { class: 'mz-stat' }, h('b', null, v), h('span', null, k)); }
    function hero(s) {
      var p = s.progress, lvl = State.me && State.me.xp;
      return h('div', { class: 'card mz-hero' },
        h('div', { class: 'mz-head' },
          h('div', { class: 'mz-orb' }, icon('target')),
          h('div', { class: 'grow' },
            h('h3', null, 'پیشرفت کارآگاهی'),
            h('div', { class: 'mz-sub' }, fa(p.done) + ' از ' + fa(p.total) + ' ماموریت کامل شده')),
          h('span', { class: 'chip accent' }, fa(p.pct) + '٪')),
        h('div', { class: 'progress', role: 'progressbar', 'aria-valuenow': p.pct, 'aria-valuemin': 0, 'aria-valuemax': 100 }, h('i', { style: { width: p.pct + '%' } })),
        h('div', { class: 'mz-stats' },
          stat(fa(p.done), 'انجام‌شده'),
          stat(fa(s.total_remaining), 'باقی‌مانده'),
          stat(lvl ? fa(lvl.level) : '—', 'سطح شما')));
    }
    function skeleton() {
      var w = h('div', { class: 'stack' }, Skel.block(158, 18), Skel.line('40%', 12));
      for (var i = 0; i < 3; i++) w.appendChild(Skel.block(96, 18));
      return w;
    }

    /* ---------- صفحه ---------- */
    Router.def('missions', {
      render: function (ctx) {
        LS.set('missions_seen', todayKey());
        var tasks = {}, done = {}, seen = {}, summary = null, page = 1, misses = 0, exhausted = false;
        ctx.header({
          title: 'ماموریت‌ها', subtitle: 'انجام بده، XP بگیر، سطح بالا برو',
          actions: [iconBtn('refresh', function () { Platform.haptic('light'); ctx.reload(); }, 'به‌روزرسانی')]
        });
        useData(ctx, 'missions:1', function () { return api('/missions?page=1'); }, function (d) { absorb(d, true); }, skeleton);

        function ids() { return Object.keys(tasks); }
        function activeCount() { return ids().filter(function (id) { return !done[id]; }).length; }
        function normalize(d) {
          var p = d.progress || {};
          return { progress: { done: p.done || 0, total: p.total || 0, pct: Math.max(0, Math.min(100, p.pct || 0)) }, total_remaining: d.total_remaining || 0 };
        }
        function absorb(d, firstPage) {
          var prevDone = summary ? summary.progress.done : null, before = ids(), fresh = 0;
          if (firstPage) { page = 1; misses = 0; exhausted = false; }
          (d.tasks || []).forEach(function (t) { if (!tasks[t.id]) fresh++; tasks[t.id] = t; });
          summary = normalize(d);
          if (!firstPage) misses = fresh ? 0 : misses + 1;
          if (summary.total_remaining <= activeCount() || misses >= 2) exhausted = true;
          draw();
          /* تکمیل‌های تازه: شمارندهٔ سرور بالا رفته — کارت‌های غایب فقط پس از تأیید سرور «انجام‌شده» می‌شوند */
          if (prevDone !== null && summary.progress.done > prevDone) {
            Platform.haptic('success');
            toast('🎉 ' + fa(summary.progress.done - prevDone) + ' ماموریت کامل شد و پاداشش واریز شد', 'success');
            refreshMe().then(function () { if (ctx.alive) draw(); }, function () { /* noop */ });
            var present = {}; (d.tasks || []).forEach(function (t) { present[t.id] = true; });
            before.filter(function (id) { return !present[id] && !done[id]; }).forEach(verify);
          }
        }
        function verify(id) {
          api('/missions/' + encodeURIComponent(id)).then(function (t) {
            if (!ctx.alive) return;
            tasks[id] = t; if (t.done) done[id] = true; draw();
          }, function () { /* بی‌صدا — در به‌روزرسانی بعدی دوباره بررسی می‌شود */ });
        }
        function markDone(t) {
          if (done[t.id]) return;
          done[t.id] = true; tasks[t.id] = t;
          summary.progress.done += 1;
          summary.total_remaining = Math.max(0, summary.total_remaining - 1);
          summary.progress.pct = summary.progress.total ? Math.floor(summary.progress.done * 100 / summary.progress.total) : 0;
          Platform.haptic('success');
          toast('🎉 ماموریت «' + t.name + '» کامل شد! ' + fa(t.xp) + ' XP واریز شد', 'success');
          refreshMe().then(function () { if (ctx.alive) draw(); }, function () { /* noop */ });
          draw();
        }
        function moreButton() {
          var b = h('button', { class: 'btn btn-secondary btn-block mz-more', onclick: function () {
            Platform.haptic('light');
            withLoading(b, api('/missions?page=' + (page + 1))).then(function (d) { if (!ctx.alive) return; page += 1; absorb(d, false); }, function (e) { toast(errMsg(e), 'error'); });
          } }, icon('plus'), 'ماموریت‌های بیشتر');
          return b;
        }
        function draw() {
          var w = h('div', null);
          w.appendChild(hero(summary));
          var all = ids().map(function (id) { return tasks[id]; });
          var active = all.filter(function (t) { return !done[t.id]; }).sort(cmp);
          var finished = all.filter(function (t) { return done[t.id]; });
          if (!active.length && !finished.length) {
            w.appendChild(h('div', { class: 'card mt-12' }, Empty({ icon: 'trophy', title: 'همهٔ ماموریت‌ها کامل شد! 🏆', text: 'تو دیگه افسانهٔ فضول‌یابی — فردا سر بزن؛ شاید ماموریت تازه‌ای باز شده باشد.' })));
            ctx.body.replaceChildren(w); return;
          }
          w.appendChild(h('div', { class: 'mz-note' }, icon('fire'),
            h('span', null, 'امروز ', h('b', null, fa(active.length) + ' ماموریت'), ' فعال داری — هر شب ساعت ۰۰:۰۰ ست تازه‌ای باز می‌شود.')));
          var k = 0;
          ['easy', 'medium', 'hard'].forEach(function (c) {
            var items = active.filter(function (t) { return tone(t) === c; });
            if (!items.length) return;
            w.appendChild(h('div', { class: 'mz-sec' },
              h('span', null, h('i', { class: 'mz-dot ' + c }), CAT[c].title),
              h('span', { class: 'chip' }, fa(items.length) + ' ماموریت')));
            var ul = h('div', { class: 'mz-list' });
            items.forEach(function (t) { ul.appendChild(card(t, false, !seen[t.id], k++, openDetail)); });
            w.appendChild(ul);
          });
          if (finished.length) {
            w.appendChild(h('div', { class: 'mz-sec' }, h('span', null, h('i', { class: 'mz-dot easy' }), 'تکمیل‌شده'), h('span', { class: 'chip accent' }, fa(finished.length))));
            var dl = h('div', { class: 'mz-list' });
            finished.forEach(function (t) { dl.appendChild(card(t, true, false, 0, openDetail)); });
            w.appendChild(dl);
          }
          if (!exhausted) w.appendChild(moreButton());
          else if (active.length) w.appendChild(h('div', { class: 'small muted center mt-12' }, 'همهٔ ماموریت‌های باقی‌مانده را می‌بینی'));
          w.appendChild(h('div', { class: 'mz-note' }, icon('shield'),
            h('span', null, 'تأیید انجام هر ماموریت سمت سرور و از روی فعالیت واقعی توست؛ پاداش هر ماموریت فقط یک‌بار واریز می‌شود.')));
          ctx.body.replaceChildren(w);
          all.forEach(function (t) { seen[t.id] = true; });
        }
        function openDetail(t) {
          var isDone = !!done[t.id], cta = isDone ? null : ctaFor(t), c = tone(t), sh;
          var progWrap = h('div', null), statusWrap = h('div', null);
          var body = h('div', { class: 'stack' },
            h('div', { class: 'center' },
              h('div', { class: 'mz-sheet-ic tone-' + c + (isDone ? ' is-done' : '') }, icon(isDone ? 'check' : iconFor(t))),
              h('h3', { style: 'margin:0 0 6px;font-weight:800' }, t.name),
              h('div', { class: 'row', style: 'justify-content:center' }, h('span', { class: 'chip' }, h('i', { class: 'mz-dot ' + c }), CAT[c].title), xpPill(t, isDone))),
            h('p', { class: 'mz-sheet-desc' }, t.desc || CAT[c].hint),
            progWrap, statusWrap,
            cta && cta.alt ? h('div', { class: 'center' }, h('button', { class: 'btn btn-ghost btn-sm', onclick: function () { sh.close(); cta.alt.run(); } }, icon(cta.alt.icon), cta.alt.text)) : null);
          function paint(tt, ok) {
            progWrap.replaceChildren(); statusWrap.replaceChildren();
            if (!ok && tt.progress) {
              var p = tt.progress, left = Math.max(0, (p.threshold || 0) - (p.value || 0));
              progWrap.appendChild(h('div', { class: 'card mz-sheet-prog' },
                h('div', { class: 'row between small', style: 'margin-bottom:8px;font-weight:700' }, h('span', null, 'پیشرفت'), h('span', null, fa(p.value) + ' از ' + fa(p.threshold) + ' (' + fa(pct(p)) + '٪)')),
                h('div', { class: 'progress', style: 'height:10px' }, h('i', { style: { width: pct(p) + '%' } })),
                h('div', { class: 'small muted', style: 'margin-top:8px' }, left > 0 ? 'فقط ' + fa(left) + ' تای دیگر مانده!' : 'در آستانهٔ تکمیل — وضعیت را بررسی کن')));
            }
            statusWrap.appendChild(ok
              ? h('div', { class: 'alert mz-ok' }, icon('checks'), h('div', null, h('b', null, 'انجام شد! '), h('span', { class: 'ltr' }, '+' + fa(tt.xp) + ' XP'), ' به حسابت واریز شده است.'))
              : h('div', { class: 'alert' }, icon('shield'), h('div', null, 'با کامل‌شدن این ماموریت، ', h('b', { class: 'ltr' }, '+' + fa(tt.xp) + ' XP'), ' خودکار و فقط یک‌بار به حسابت اضافه می‌شود.')));
          }
          paint(t, isDone);
          var actions = [];
          if (cta) actions.push({ text: cta.text, icon: cta.icon, onClick: function (close) { close(); cta.run(); } });
          if (!isDone) actions.push({ text: 'بررسی وضعیت', icon: 'refresh', kind: cta ? 'secondary' : 'primary', onClick: function (close, btn) {
            withLoading(btn, api('/missions/' + encodeURIComponent(t.id))).then(function (fresh) {
              if (!ctx.alive) return;
              if (fresh.done) {
                paint(fresh, true); markDone(fresh);
                var act = sh.el.querySelector('.sheet-actions');
                if (act) act.replaceChildren(h('button', { class: 'btn btn-primary', onclick: close }, icon('check'), 'عالیه!'));
              } else {
                tasks[t.id] = fresh; paint(fresh, false); draw();
                var p = fresh.progress;
                toast(p ? 'هنوز کامل نشده — ' + fa(p.value) + ' از ' + fa(p.threshold) : 'هنوز انجام نشده؛ بعد از انجام دوباره بررسی کن', 'info');
              }
            }, function (e) { toast(errMsg(e), 'error'); });
          } });
          if (isDone) actions.push({ text: 'عالیه!', icon: 'check', onClick: function (close) { close(); } });
          sh = openSheet({ title: 'جزئیات ماموریت', body: body, actions: actions });
        }
      }
    });

    return {
      /* نشان «جدید» روی دکمهٔ دسترسی سریع تا اولین بازدید امروز (فقط حالت نمایشی محلی؛ ربطی به پاداش ندارد) */
      badge: function () { return LS.get('missions_seen') === todayKey() ? null : 'جدید'; }
    };
  })();

  /* ===================== Page: Wheel ===================== */
  Router.def('wheel', {
    render: function (ctx) {
      ctx.header({ title: 'پاداش‌ها', subtitle: 'گردونه شانس، جایزه روزانه و کد هدیه' });
      var rotation = 0, spinning = false;
      useData(ctx, 'wheel', function () { return api('/wheel'); }, draw, function () { return h('div', null, h('div', { class: 'sk sk-circle', style: 'width:min(84vw,320px);aspect-ratio:1;margin:12px auto 18px' }), Skel.block(52, 14)); });
      function wheelSvg(segs) {
        var n = segs.length, a = 360 / n, out = '<svg viewBox="0 0 300 300" class="wheel" xmlns="http://www.w3.org/2000/svg">';
        function pt(deg, r) { var rad = deg * Math.PI / 180; return (150 + r * Math.sin(rad)).toFixed(2) + ' ' + (150 - r * Math.cos(rad)).toFixed(2); }
        out += '<defs>'
          + '<linearGradient id="wz-ring" x1="0" y1="0" x2="1" y2="1">'
          + '<stop offset="0" stop-color="#ffe9a8"/><stop offset=".5" stop-color="#e09b12"/><stop offset="1" stop-color="#f7c948"/>'
          + '</linearGradient>'
          + '<radialGradient id="wz-vig" cx="50%" cy="50%" r="50%">'
          + '<stop offset="0" stop-color="rgba(0,0,0,0)"/><stop offset=".72" stop-color="rgba(0,0,0,0)"/><stop offset="1" stop-color="rgba(0,0,0,.28)"/>'
          + '</radialGradient>'
          + '</defs>';
        segs.forEach(function (s, i) {
          var a0 = i * a, a1 = (i + 1) * a, mid = a0 + a / 2;
          out += '<path d="M150 150 L' + pt(a0, 148) + ' A148 148 0 0 1 ' + pt(a1, 148) + ' Z" fill="' + s.color + '" stroke="rgba(10,14,20,.55)" stroke-width="1.4"/>';
          // فیکس خوانایی: لیبل نیمهٔ پایین گردونه ۱۸۰ درجه فلیپ می‌شود تا همیشه راست‌به‌چپِ درست و رو به بالا باشد
          var flip = mid > 90 && mid < 270;
          out += '<text x="150" y="' + (flip ? 248 : 52) + '" transform="rotate(' + (flip ? mid + 180 : mid) + ' 150 150)" text-anchor="middle" fill="#fff" font-size="13.5" font-weight="800" font-family="Vazirmatn, Tahoma, sans-serif">' + String(s.label).replace(/[<>&]/g, '') + '</text>';
        });
        out += '<circle cx="150" cy="150" r="148" fill="url(#wz-vig)"/>';
        out += '<path d="M' + pt(293, 122) + ' A122 122 0 0 1 ' + pt(337, 122) + '" fill="none" stroke="rgba(255,255,255,.22)" stroke-width="12" stroke-linecap="round"/>';
        out += '<circle cx="150" cy="150" r="146" fill="none" stroke="url(#wz-ring)" stroke-width="4.5"/>';
        return out + '<circle cx="150" cy="150" r="141" fill="none" stroke="rgba(255,214,110,.28)" stroke-width="1"/></svg>';
      }
      function draw(d) {
        if (spinning) return;
        var w = h('div', null);
        if (d.disabled) {
          ctx.body.replaceChildren(h('div', { class: 'card' }, Empty({ icon: 'lock', title: 'گردونه شانس فعلاً غیرفعال است', text: 'به‌زودی توسط مدیریت فعال می‌شود.' })));
          return;
        }
        /* v4.7 (همگام‌سازی با پنل شیشه‌ای): چرخ شانس فقط برای VIP — همان ربات */
        if (d.vip_required) {
          w.appendChild(h('div', { class: 'card center', style: 'padding:20px 16px' },
            h('div', { class: 'g-icon', style: 'margin:0 auto 10px;background:linear-gradient(135deg,#f7c948,#e09b12);color:#fff' }, icon('crown')),
            h('h3', { style: 'margin:0 0 6px;font-weight:800' }, 'چرخ شانس ویژهٔ VIP'),
            h('p', { class: 'muted small', style: 'margin:0 0 12px' }, 'جک‌پات ۱٬۰۰۰ XP و تا ۳ روز VIP — روزی یک چرخش رایگان برای اعضای کارت طلایی.'),
            h('button', { class: 'btn btn-gold', onclick: function () { Router.tab('vip'); } }, icon('crown'), 'فعال‌سازی VIP')));
        } else {
        var wrap = h('div', { class: 'wheel-wrap' }, h('div', { html: '<svg class="pointer" viewBox="0 0 34 42"><path d="M17 42 2 12A15 15 0 1 1 32 12Z" fill="#e5484d"/><circle cx="17" cy="15" r="6" fill="#fff"/></svg>' }), h('div', { class: 'hub' }, icon('gift')));
        var holder = h('div', { style: 'width:100%;height:100%', html: wheelSvg(d.segments) });
        wrap.insertBefore(holder, wrap.firstChild);
        var svg = holder.querySelector('svg'); svg.style.transform = 'rotate(' + rotation + 'deg)';
        w.appendChild(wrap);
        var btnArea = h('div', null);
        if (d.can_spin) {
          var btn = h('button', { class: 'btn btn-primary btn-block', style: 'height:52px;font-size:16px', onclick: function () { spin(d, svg, btn); } }, icon('sparkles'), 'بچرخون!');
          btnArea.appendChild(btn);
        } else {
          var cd = h('div', { class: 'countdown' }, '--:--:--');
          btnArea.appendChild(h('div', { class: 'card center' }, h('div', { class: 'muted small' }, 'چرخش بعدی تا'), cd, h('div', { class: 'small muted' }, 'هر روز ساعت ۰۰:۰۰ فرصت جدید باز می‌شود')));
          var tick = function () { var s = Math.max(0, Math.floor((new Date(d.next_spin_at) - Date.now()) / 1000)); if (s === 0) { Cache.del('wheel'); ctx.reload(); return; } cd.textContent = faDigits([Math.floor(s / 3600), Math.floor(s % 3600 / 60), s % 60].map(function (x) { return (x < 10 ? '0' : '') + x; }).join(':')); };
          tick(); var iv = setInterval(tick, 1000); ctx.onCleanup(function () { clearInterval(iv); });
        }
        w.appendChild(btnArea);
        w.appendChild(h('div', { class: 'card mt-12' }, h('div', { class: 'card-title' }, icon('gift'), 'جوایز ممکن'), h('div', { class: 'chips', style: 'flex-wrap:wrap' }, d.segments.map(function (s) { return h('span', { class: 'chip', style: { background: s.color, color: '#fff', borderColor: 'transparent' } }, s.label); }))));
        }
        /* v4.7 (هم‌ارز منوی 🎁 پاداش‌های ربات): جایزه روزانه + کد هدیه */
        w.appendChild(rewardsArea(ctx));
        ctx.body.replaceChildren(w);
      }
      function spin(d, svg, btn) {
        if (spinning) return; spinning = true; btn.disabled = true; Platform.haptic('medium');
        api('/wheel/spin', { method: 'POST' }).then(function (r) {
          var a = 360 / d.segments.length, jitter = (Math.random() - 0.5) * a * 0.6;
          var target = Math.ceil(rotation / 360) * 360 + 360 * 6 + (360 - (r.index * a + a / 2)) + jitter;
          rotation = target; svg.style.transform = 'rotate(' + target + 'deg)';
          var ticks = setInterval(function () { Platform.haptic('select'); }, 260);
          setTimeout(function () {
            clearInterval(ticks); spinning = false; Platform.haptic(r.prize.type === 'none' ? 'warning' : 'success');
            Cache.del('wheel'); Cache.del('me'); refreshMe();
            openSheet({ title: '', body: h('div', { class: 'center' }, h('div', { style: 'font-size:56px;line-height:1.2' }, r.prize.type === 'none' ? '😅' : r.prize.type === 'vip' ? '👑' : '🎉'),
              h('h3', { style: 'margin:6px 0;font-weight:800' }, r.prize.type === 'none' ? 'این بار پوچ شد!' : 'تبریک! برنده شدی'), h('p', { class: 'muted', style: 'margin:0 0 6px' }, r.prize.label)),
              actions: [{ text: 'عالی', onClick: function (close) { close(); } }], onClose: function () { if (ctx.alive) ctx.reload(); } });
          }, 5100);
        }, function (e) { spinning = false; btn.disabled = false; toast(errMsg(e), 'error'); if (e.code === 'COOLDOWN' || e.code === 'VIP_REQUIRED') { Cache.del('wheel'); ctx.reload(); } });
      }
    }
  });

  /* ===================== v4.7: Rewards (جایزه روزانه + کد هدیه — هم‌ارز منوی 🎁 ربات) ===================== */
  function rewardsArea(ctx) {
    var area = h('div', null);
    area.appendChild(SectionTitle('بقیهٔ پاداش‌ها'));
    var holder = h('div', null);
    area.appendChild(holder);
    api('/rewards').then(function (d) {
      if (!ctx.alive) return;
      holder.replaceChildren(dailyBonusCard(ctx, d.daily), giftCodeCard(ctx, d.gift_codes));
    }, function () { holder.replaceChildren(h('div', { class: 'small muted' }, 'پاداش‌ها فعلاً در دسترس نیست.')); });
    return area;
  }
  function dailyBonusCard(ctx, daily) {
    var card = h('div', { class: 'card mt-12 daily-card' });
    card.appendChild(h('div', { class: 'row between' },
      h('div', { class: 'card-title', style: 'margin:0' }, icon('calendar'), 'جایزه روزانه'),
      h('span', { class: 'chip accent' }, '🔥 استریک ' + fa(daily.streak || 0) + ' روز')));
    card.appendChild(h('div', { class: 'small muted', style: 'margin:6px 0 10px' },
      'هر روز ساعت ۰۰:۰۰ ریست می‌شود؛ هر روز پیوسته ‎+۱۰٪‎ پاداش اضافه تا سقف ۱۰۰٪.' +
      (daily.bonus_pct ? ' (پاداش فعلی: ' + fa(daily.bonus_pct) + '٪)' : '')));
    card.appendChild(h('div', { class: 'chips', style: 'flex-wrap:wrap;margin-bottom:10px' },
      (daily.prizes || []).map(function (p) { return h('span', { class: 'chip' + (p.type === 'vip' ? ' gold' : '') }, p.type === 'vip' ? icon('crown') : icon('bolt'), p.label); })));
    if (daily.done) {
      card.appendChild(h('div', { class: 'alert mt-8' }, icon('check'), h('div', null, 'جایزهٔ امروز گرفته شد ✅ — فردا دوباره بیا!')));
    } else {
      var btn = h('button', { class: 'btn btn-primary btn-block', onclick: function () {
        withLoading(btn, api('/rewards/claim', { method: 'POST' })).then(function (r) {
          Cache.del('me'); Cache.del('rewards'); refreshMe();
          openSheet({ title: '', body: h('div', { class: 'center' },
            h('div', { style: 'font-size:56px;line-height:1.2' }, r.prize.type === 'vip' ? '👑' : '🎉'),
            h('h3', { style: 'margin:6px 0;font-weight:800' }, 'جایزهٔ امروزت!'),
            h('p', { class: 'muted', style: 'margin:0 0 4px' }, r.prize.label),
            r.prize.bonus_pct ? h('p', { class: 'small muted', style: 'margin:0 0 4px' }, '🔥 پاداش استریک: +' + fa(r.prize.bonus_pct) + '٪') : null,
            r.milestone_vip_days ? h('p', { class: 'small', style: 'margin:4px 0 0;color:var(--gold)' }, '🎁 جایزهٔ استریک ' + fa(r.streak) + ' روزه: ' + fa(r.milestone_vip_days) + ' روز VIP رایگان!') : null,
            h('p', { class: 'small muted', style: 'margin:8px 0 0' }, 'زنجیرهٔ ' + fa(r.streak) + ' روزه ادامه دارد — فردا هم بیا!')),
            actions: [{ text: 'عالی', onClick: function (close) { close(); } }], onClose: function () { if (ctx.alive) ctx.reload(); } });
        }, function (e) { toast(errMsg(e), 'error'); if (e.code === 'ALREADY_CLAIMED') { Cache.del('rewards'); ctx.reload(); } });
      } }, icon('gift'), 'دریافت جایزه امروز');
      card.appendChild(btn);
    }
    return card;
  }
  function giftCodeCard(ctx, codes) {
    var card = h('div', { class: 'card mt-12' });
    card.appendChild(h('div', { class: 'row between' },
      h('div', { class: 'card-title', style: 'margin:0' }, icon('hash'), 'کد هدیه'),
      h('span', { class: 'chip' }, fa((codes || []).length) + ' کد فعال')));
    var list = h('div', { class: 'list mt-8' });
    (codes || []).forEach(function (g) {
      list.appendChild(ListItem({
        lead: h('div', { class: 'li-icon gold' }, icon('gift')),
        title: g.code, sub: fa(g.days) + ' روز VIP • ظرفیت باقی‌مانده: ' + fa(g.remaining),
        onClick: function () { redeemGift(g.code); }
      }));
    });
    if ((codes || []).length) card.appendChild(list);
    /* کد دستی — همان «اگر کد هدیه‌ای دارید مستقیم بفرستید» ربات */
    var inp = h('input', { class: 'input ltr', placeholder: 'مثلاً WELCOME10', maxLength: 24, style: 'text-align:left' });
    var btn = h('button', { class: 'btn btn-secondary btn-sm', onclick: function () {
      var code = inp.value.trim();
      if (code.length < 2) { toast('کد هدیه را وارد کن', 'error'); inp.focus(); return; }
      redeemGift(code);
    } }, icon('check'), 'فعال‌سازی');
    card.appendChild(h('div', { class: 'btn-row mt-8' }, inp, btn));
    function redeemGift(code) {
      withLoading(card, api('/gifts/redeem', { method: 'POST', body: { code: code } })).then(function (r) {
        Cache.del('me'); Cache.del('rewards'); refreshMe();
        toast('🎁 ' + fa(r.days) + ' روز VIP فعال شد!', 'success');
        if (ctx.alive) ctx.reload();
      }, function (e) { toast(errMsg(e), 'error'); });
    }
    return card;
  }

  /* ===================== Admin pages ===================== */
  Router.def('admin', {
    admin: true,
    render: function (ctx) {
      ctx.header({ title: 'پنل مدیریت', subtitle: 'دسترسی سوپر ادمین', actions: [iconBtn('refresh', function () { ctx.reload(); }, 'به‌روزرسانی')] });
      useData(ctx, 'admin:stats', function () { return api('/admin/stats'); }, function (s) {
        function kpi(ic, tone, v, k) { return h('div', { class: 'kpi' }, h('div', { class: 'top' }, h('div', { class: 'li-icon ' + tone }, icon(ic))), h('div', { class: 'v' }, v), h('div', { class: 'k' }, k)); }
        var w = h('div', null);
        w.appendChild(h('div', { class: 'kpi-grid' },
          kpi('users', '', fa(s.users_total), 'کل کاربران'),
          kpi('bolt', 'accent', fa(s.users_active_today), 'فعال امروز'),
          kpi('plus', 'info', '+' + fa(s.users_today), 'جدید امروز'),
          kpi('crown', 'gold', fa(s.vip_active), 'VIP فعال'),
          kpi('receipt', 'warn', fa(Math.round(s.revenue_month / 1e6 * 10) / 10) + ' م', 'درآمد ماه (تومان)'),
          kpi('eye', '', fa(s.snoops_today), 'فضولی امروز'),
          kpi('message', 'info', fa(s.anon_today), 'پیام ناشناس امروز'),
          kpi('inbox', 'danger', fa(s.open_tickets), 'تیکت باز')));
        var pts = s.chart.map(function (p) { return { v: p.new_users, label: F_DAY ? F_DAY.format(new Date(p.date)) : '' }; });
        w.appendChild(h('div', { class: 'card mt-12' }, h('div', { class: 'row between' }, h('div', { class: 'card-title', style: 'margin:0' }, icon('chart'), 'کاربران جدید (۱۴ روز)'), h('span', { class: 'chip accent' }, fa(s.users_week) + ' این هفته')), BarChart(pts, { height: 120 })));
        w.appendChild(SectionTitle('ابزارها'));
        w.appendChild(h('div', { class: 'list' },
          ListItem({ icon: 'users', title: 'مدیریت کاربران', sub: 'جستجو، جزئیات، VIP، مسدودسازی', onClick: function () { Router.go('admin-users'); } }),
          ListItem({ icon: 'megaphone', tone: 'warn', title: 'پخش همگانی', sub: 'ارسال پیام به همه یا گروه خاص', onClick: function () { Router.go('admin-broadcast'); } }),
          ListItem({ icon: 'inbox', tone: 'info', title: 'صندوق پشتیبانی', sub: fa(s.open_tickets) + ' گفتگوی باز', end: s.open_tickets ? h('span', { class: 'chip danger' }, fa(s.open_tickets)) : null, onClick: function () { Router.go('admin-tickets'); } }),
          ListItem({ icon: 'message', tone: 'gold', title: 'آرشیو پیام‌های ناشناس', sub: fa(s.anon_today) + ' پیام امروز • به‌جای ارسال به چت شما', onClick: function () { Router.go('admin-anonlog'); } }),
          ListItem({ icon: 'gift', tone: 'danger', title: 'کدهای هدیه', sub: 'ساخت و مدیریت کدهای VIP', onClick: function () { Router.go('admin-gifts'); } }),
          ListItem({ icon: 'receipt', title: 'تراکنش‌ها', sub: 'خریدها، هدیه‌ها و تغییرهای VIP', onClick: function () { Router.go('admin-transactions'); } }),
          ListItem({ icon: 'palette', tone: 'info', title: 'تنظیمات و قابلیت‌ها', sub: 'لیدربورد، گردونه، قیمت‌ها، حالت‌ها', onClick: function () { Router.go('admin-settings'); } }),
          ListItem({ icon: 'target', tone: 'warn', title: 'چالش فضول‌گیر برتر', sub: 'شروع، جدول برترین‌ها و جایزه — هم‌گام با ربات', onClick: function () { Router.go('admin-challenge'); } }),
          ListItem({ icon: 'users', tone: '', title: 'آمار تفصیلی', sub: 'کاربران، VIP و آرشیو روزانه', onClick: function () { Router.go('admin-stats'); } }),
          ListItem({ icon: 'megaphone', tone: 'info', title: 'کانال‌های اجباری', sub: 'مدیریت عضویت اجباری (اد اجباری)', onClick: function () { Router.go('admin-channels'); } }),
          ListItem({ icon: 'database', tone: 'danger', title: 'بکاپ و بازیابی', sub: 'بکاپ شبانه و دستی دیتابیس', onClick: function () { Router.go('admin-backup'); } })));
        ctx.body.replaceChildren(w);
        Shell.setBadge('admin', s.open_tickets);
      }, Skel.cards);
    }
  });

  Router.def('admin-users', {
    admin: true, tab: 'admin',
    render: function (ctx) {
      ctx.header({ title: 'مدیریت کاربران' });
      var q = '', filter = 'all', sort = 'recent', reqId = 0;
      var input = h('input', { class: 'input', type: 'search', placeholder: 'نام، یوزرنیم یا شناسه عددی', inputMode: 'search' });
      var listArea = h('div', { class: 'mt-12' });
      var chips = h('div', { class: 'chips mt-12' });
      var sortChips = h('div', { class: 'chips mt-8' });
      var SORTS = [
        ['recent', 'آخرین فعالیت'], ['joined', 'جدیدترین عضو'], ['level', 'بیشترین سطح'],
        ['snoops', 'بیشترین فضول'], ['traps', 'بیشترین تله'], ['vip', 'اشتراک VIP'], ['name', 'نام']
      ];
      function drawChips() {
        chips.innerHTML = '';
        [['all', 'همه'], ['vip', 'VIP'], ['banned', 'مسدود']].forEach(function (c) {
          chips.appendChild(h('button', { class: 'chip' + (filter === c[0] ? ' on' : ''), onclick: function () { filter = c[0]; drawChips(); load(); } }, c[1]));
        });
        sortChips.innerHTML = '';
        sortChips.appendChild(h('span', { class: 'small muted', style: 'align-self:center;margin:0 2px;white-space:nowrap;font-weight:700' }, 'مرتب‌سازی:'));
        SORTS.forEach(function (c) {
          sortChips.appendChild(h('button', { class: 'chip' + (sort === c[0] ? ' on' : ''), onclick: function () { sort = c[0]; drawChips(); load(); } }, c[1]));
        });
      }
      function load() {
        var my = ++reqId; listArea.replaceChildren(Skel.list(6));
        api('/admin/users?q=' + encodeURIComponent(q) + '&filter=' + filter + '&sort=' + sort).then(function (d) {
          if (my !== reqId || !ctx.alive) return;
          if (!d.items.length) { listArea.replaceChildren(Empty({ icon: 'search', title: 'کاربری پیدا نشد', text: 'عبارت جستجو یا معیار مرتب‌سازی را تغییر دهید.' })); return; }
          listArea.replaceChildren(h('div', { class: 'small muted', style: 'margin:0 4px 8px' }, fa(d.total) + ' نتیجه'), h('div', { class: 'list' }, d.items.map(function (u) {
            var sub = 'سطح ' + fa(u.level);
            if (sort === 'snoops' || sort === 'traps') sub += ' • ' + (sort === 'snoops' ? 'فضول' : 'تله');
            if (u.is_vip) sub += ' • VIP';
            return ListItem({ lead: Avatar(u.name, u.id, { vip: u.is_vip, photo: u.avatar }), title: u.name, sub: (u.username ? '@' + u.username + ' • ' : '') + sub, end: u.banned ? h('span', { class: 'chip danger' }, 'مسدود') : null, onClick: function () { Router.go('admin-user', { id: u.id }); } });
          })));
        }, function (e) { if (my === reqId && ctx.alive) listArea.replaceChildren(ErrorState(e, load)); });
      }
      input.addEventListener('input', debounce(function () { q = input.value.trim(); load(); }, 350));
      drawChips();
      ctx.body.replaceChildren(h('div', { class: 'search' }, icon('search'), input), chips, sortChips, listArea);
      load();
    }
  });

  Router.def('admin-user', {
    admin: true, tab: 'admin',
    render: function (ctx) {
      var id = ctx.params.id;
      ctx.header({ title: 'جزئیات کاربر' });
      var key = 'admin:user:' + id;
      useData(ctx, key, function () { return api('/admin/users/' + id); }, draw, Skel.cards);
      function update(p) { return p.then(function (d) { Cache.set(key, d); Cache.del('admin:stats'); draw(d); return d; }); }
      function draw(d) {
        var u = d.user, w = h('div', null);
        w.appendChild(h('div', { class: 'card center' }, h('div', { style: 'display:flex;justify-content:center' }, Avatar(u.name, u.id, { lg: true, vip: d.vip.active, photo: u.avatar })),
          h('div', { class: 'bold mt-8', style: 'font-size:17px' }, u.name), u.username ? h('div', { class: 'muted small ltr' }, '@' + u.username) : null,
          h('div', { class: 'row mt-8', style: 'justify-content:center' }, vipChip(d.vip), d.banned ? h('span', { class: 'chip danger' }, icon('ban'), 'مسدود') : null)));
        w.appendChild(h('div', { class: 'card info-rows' },
          infoRow('شناسه', h('span', { class: 'ltr' }, String(u.id))), infoRow('تاریخ عضویت', jdate(u.joined_at)), infoRow('آخرین فعالیت', ago(u.last_seen)),
          infoRow('سطح / XP', 'سطح ' + fa(d.xp.level) + ' • ' + fa(d.xp.xp) + ' XP'), infoRow('فضول‌های ثبت‌شده', fa(d.stats.snoops)), infoRow('تله‌ها', fa(d.stats.traps)),
          /* v4.7: اخطارها — همان پروندهٔ کاربر پنل شیشه‌ای */
          infoRow('اخطارها', (d.warnings || 0) >= 3 ? h('span', { class: 'chip danger' }, fa(d.warnings || 0) + ' — مسدود') : (d.warnings || 0) > 0 ? h('span', { class: 'chip warn' }, fa(d.warnings || 0) + ' از ۳') : fa(d.warnings || 0))));
        w.appendChild(SectionTitle('اشتراک VIP'));
        w.appendChild(h('div', { class: 'card' },
          h('div', { class: 'row between' }, h('div', null, h('div', { class: 'bold' }, d.vip.active ? 'فعال • ' + fa(d.vip.days_left) + ' روز' : 'غیرفعال'), d.vip.active ? h('div', { class: 'small muted' }, 'انقضا: ' + jdate(d.vip.expires_at)) : null), h('div', { class: 'li-icon gold' }, icon('crown'))),
          h('div', { class: 'btn-row mt-12' },
            h('button', { class: 'btn btn-secondary btn-sm', onclick: function () { vipDays('add'); } }, icon('plus'), 'افزودن'),
            h('button', { class: 'btn btn-ghost btn-sm', disabled: !d.vip.active, onclick: function () { vipDays('reduce'); } }, icon('minus'), 'کاهش'),
            h('button', { class: 'btn btn-danger btn-sm', disabled: !d.vip.active, onclick: cancelVip }, icon('x'), 'لغو'))));
        w.appendChild(SectionTitle('اقدامات'));
        w.appendChild(h('div', { class: 'list' },
          ListItem({ icon: 'send', tone: 'info', title: 'ارسال پیام مستقیم', sub: 'از طرف ربات در چت بله', onClick: sendMsg }),
          ListItem({ icon: 'inbox', title: 'گفتگوی پشتیبانی', onClick: function () { Router.go('admin-ticket', { user_id: u.id, name: u.name }); } }),
          /* v4.7: اخطار به کاربر — همان دکمهٔ پنل شیشه‌ای؛ اخطار سوم = مسدودیت خودکار */
          ListItem({ icon: 'alert', tone: 'warn', title: 'اخطار به کاربر', sub: (d.warnings || 0) + ' از ۳ — اخطار سوم مسدود می‌کند', onClick: warnUser }),
          d.warnings ? ListItem({ icon: 'refresh', tone: '', title: 'بازنشانی اخطارها', onClick: resetWarns }) : null,
          ListItem({ icon: 'ban', tone: 'danger', title: d.banned ? 'رفع مسدودی' : 'مسدود کردن کاربر', onClick: function () { toggleBan(d); } })));
        w.appendChild(SectionTitle('پرداخت‌ها'));
        w.appendChild(d.payments.length ? h('div', { class: 'list' }, d.payments.map(function (p) { return ListItem({ icon: 'receipt', title: p.plan_title, sub: jdate(p.created_at, true), end: h('div', { style: 'text-align:left' }, h('div', { class: 'bold', style: 'color:var(--text)' }, toman(p.amount)), statusChip(p.status)) }); }))
          : h('div', { class: 'card' }, Empty({ icon: 'receipt', title: 'پرداختی ثبت نشده' })));
        ctx.body.replaceChildren(w);
      }
      function vipDays(action) {
        var days = h('input', { class: 'input', type: 'number', inputMode: 'numeric', min: 1, max: 3650, placeholder: 'تعداد روز', value: '30' });
        var chips = h('div', { class: 'chips' }, [7, 30, 90, 365].map(function (n) { return h('button', { class: 'chip', onclick: function () { days.value = n; } }, fa(n) + ' روز'); }));
        openSheet({
          title: action === 'add' ? 'افزودن روز VIP' : 'کاهش روز VIP',
          body: h('div', { class: 'stack' }, chips, h('div', { class: 'field' }, h('label', null, 'تعداد روز'), days), h('div', { class: 'small muted' }, 'کاربر از طریق ربات در بله از تغییر مطلع می‌شود.')),
          actions: [{ text: action === 'add' ? 'افزودن' : 'کاهش', onClick: function (close, btn) {
            var n = parseInt(days.value, 10); if (!(n > 0)) { toast('تعداد روز معتبر وارد کنید', 'error'); return; }
            withLoading(btn, update(api('/admin/users/' + id + '/vip', { method: 'POST', body: { action: action, days: n } }))).then(function () { close(); toast('اشتراک به‌روزرسانی شد', 'success'); }, function (e) { toast(errMsg(e), 'error'); });
          } }]
        });
      }
      function cancelVip() {
        confirmDialog({ title: 'لغو VIP', text: 'اشتراک VIP این کاربر فوراً لغو می‌شود.', ok: 'لغو اشتراک', danger: true, icon: 'crown' }).then(function (ok) {
          if (ok) update(api('/admin/users/' + id + '/vip', { method: 'POST', body: { action: 'cancel' } })).then(function () { toast('VIP لغو شد', 'success'); }, function (e) { toast(errMsg(e), 'error'); });
        });
      }
      function toggleBan(d) {
        confirmDialog({ title: d.banned ? 'رفع مسدودی' : 'مسدود کردن', text: d.banned ? 'کاربر دوباره به ربات و مینی‌اپ دسترسی خواهد داشت.' : 'کاربر دیگر به ربات و مینی‌اپ دسترسی نخواهد داشت.', ok: d.banned ? 'رفع مسدودی' : 'مسدود کن', danger: !d.banned, icon: 'ban' }).then(function (ok) {
          if (ok) update(api('/admin/users/' + id + '/ban', { method: 'POST', body: { banned: !d.banned } })).then(function () { toast('انجام شد', 'success'); }, function (e) { toast(errMsg(e), 'error'); });
        });
      }
      function sendMsg() {
        var ta = h('textarea', { class: 'textarea', maxLength: 2000, placeholder: 'متن پیام…' });
        openSheet({ title: 'ارسال پیام مستقیم', body: h('div', { class: 'field' }, ta), actions: [{ text: 'ارسال', icon: 'send', onClick: function (close, btn) {
          if (!ta.value.trim()) { toast('متن پیام خالی است', 'error'); return; }
          withLoading(btn, api('/admin/users/' + id + '/message', { method: 'POST', body: { text: ta.value } })).then(function () { close(); toast('پیام ارسال شد', 'success'); }, function (e) { toast(errMsg(e), 'error'); });
        } }] });
        setTimeout(function () { ta.focus(); }, 350);
      }
      /* v4.7: اخطار به کاربر (با دلیل اختیاری) + بازنشانی اخطارها */
      function warnUser() {
        var reason = h('input', { class: 'input', maxLength: 200, placeholder: 'دلیل اخطار (اختیاری) — مثلاً: ارسال اسپم' });
        openSheet({
          title: 'اخطار به کاربر',
          body: h('div', { class: 'stack' },
            h('div', { class: 'alert warn' }, icon('alert'), h('div', null, 'پیام اخطار از طرف ربات برای کاربر ارسال می‌شود. اخطار سوم ', h('b', null, 'خودکار مسدود می‌کند'), '.')),
            h('div', { class: 'field' }, h('label', null, 'دلیل اخطار'), reason)),
          actions: [{ text: 'ثبت اخطار', icon: 'alert', onClick: function (close, btn) {
            withLoading(btn, update(api('/admin/users/' + id + '/warn', { method: 'POST', body: { reason: reason.value.trim() } }))).then(function (r) {
              close();
              if (r.warn && r.warn.banned) toast('اخطار ۳ از ۳ ثبت شد — کاربر مسدود شد', 'error');
              else toast('اخطار ثبت و به کاربر اعلام شد (' + fa(r.warn.count) + ' از ۳)', 'success');
            }, function (e) { toast(errMsg(e), 'error'); });
          } }]
        });
      }
      function resetWarns() {
        confirmDialog({ title: 'بازنشانی اخطارها', text: 'شمارندهٔ اخطارهای این کاربر صفر می‌شود.', ok: 'بازنشانی', icon: 'refresh' }).then(function (ok) {
          if (ok) update(api('/admin/users/' + id + '/reset-warnings', { method: 'POST' })).then(function () { toast('اخطارها بازنشانی شد', 'success'); }, function (e) { toast(errMsg(e), 'error'); });
        });
      }
    }
  });

  Router.def('admin-broadcast', {
    admin: true, tab: 'admin',
    render: function (ctx) {
      ctx.header({ title: 'پخش همگانی' });
      var target = 'all', text = '', job = null;
      useData(ctx, 'admin:bmeta', function () { return api('/admin/broadcast/meta'); }, draw, Skel.cards);
      var ta = h('textarea', { class: 'textarea', maxLength: 4000, placeholder: 'متن پیام همگانی… (Markdown ساده پشتیبانی می‌شود)', style: 'min-height:140px' });
      var counter = h('span', null, '۰ / ۴۰۰۰'), preview = h('div', { class: 'preview-bubble' }, 'پیش‌نمایش پیام اینجا نمایش داده می‌شود');
      var meta = null;
      ta.addEventListener('input', function () { text = ta.value; counter.textContent = fa(text.length) + ' / ۴۰۰۰'; preview.textContent = text || 'پیش‌نمایش پیام اینجا نمایش داده می‌شود'; setMain(); });
      function setMain() { if (!meta || job) return; MainAction.set('ارسال به ' + fa(meta.counts[target]) + ' کاربر', send, { disabled: text.trim().length < 3 }); }
      function draw(d) {
        meta = d;
        var w = h('div', null);
        w.appendChild(h('div', { class: 'card' }, h('div', { class: 'card-title' }, icon('users'), 'مخاطبان'),
          Seg([{ id: 'all', label: 'همه (' + fa(d.counts.all) + ')' }, { id: 'vip', label: 'VIP (' + fa(d.counts.vip) + ')' }, { id: 'free', label: 'عادی' }], target, function (v) { target = v; draw(d); })));
        w.appendChild(h('div', { class: 'card' }, h('div', { class: 'field' }, h('label', null, 'متن پیام'), ta, h('div', { class: 'hint' }, h('span', null, 'پیام از طرف ربات در چت بله ارسال می‌شود'), counter))));
        w.appendChild(h('div', { class: 'card' }, h('div', { class: 'card-title' }, icon('eye'), 'پیش‌نمایش'), preview));
        w.appendChild(h('div', { class: 'alert mt-12' }, icon('image'), h('div', null, 'پخش عکس، ویدیو یا فایل از داخل چت ربات انجام می‌شود. ', h('a', { href: '#', onclick: function (e) { e.preventDefault(); Platform.openBot('broadcast'); } }, 'باز کردن در بله ←'))));
        w.appendChild(adCard());
        if (job) w.appendChild(jobCard(job));
        if (d.jobs.length) {
          w.appendChild(SectionTitle('ارسال‌های اخیر'));
          w.appendChild(h('div', { class: 'list' }, d.jobs.slice(0, 5).map(function (j) { return ListItem({ icon: 'megaphone', tone: 'warn', title: j.text_preview, sub: jdate(j.created_at, true) + ' • ' + fa(j.sent) + ' موفق، ' + fa(j.failed) + ' ناموفق', end: statusChip(j.status) }); })));
        }
        ctx.body.replaceChildren(w); setMain();
      }
      function jobCard(j) {
        var pct = j.total ? Math.round((j.sent + j.failed) / j.total * 100) : 100;
        return h('div', { class: 'card mt-12', id: 'job-card' }, h('div', { class: 'row between' }, h('div', { class: 'card-title', style: 'margin:0' }, icon('send'), 'وضعیت ارسال'), statusChip(j.status)),
          h('div', { class: 'progress mt-12' }, h('i', { style: { width: pct + '%' } })),
          h('div', { class: 'row between small mt-8' }, h('span', null, '✅ ' + fa(j.sent) + ' موفق'), h('span', null, '⛔ ' + fa(j.failed) + ' ناموفق'), h('span', { class: 'bold' }, fa(pct) + '٪')));
      }
      /* v4.3: حالت تبلیغ — هم‌ارز «حالت تبلیغ» منوی شیشه‌ای: پیام قالب فضول‌گیری با دکمه‌هایی که به لینک تبلیغ می‌روند */
      function adCard() {
        var url = h('input', { class: 'input ltr', placeholder: 'https://example.com/your-ad', inputMode: 'url', dir: 'ltr' });
        function go(stage) {
          var u = url.value.trim();
          if (!/^https?:\/\//i.test(u)) { toast('لینک باید با http:// یا https:// شروع شود', 'error'); url.focus(); return; }
          if (stage === 'preview') {
            withLoading(url, api('/admin/ad-broadcast', { method: 'POST', body: { url: u, stage: 'preview' } })).then(function (r) {
              toast('نمونهٔ پیام به چت شما در بله ارسال شد 👁', 'success');
            }, function (e) { toast(errMsg(e), 'error'); });
            return;
          }
          confirmDialog({ title: 'ارسال تبلیغ به همه', text: 'پیام قالب فضول‌گیری با دکمه‌های لینک تبلیغ برای همهٔ کاربران ارسال می‌شود. این کار قابل لغو نیست.', ok: 'ارسال تبلیغ', icon: 'megaphone' }).then(function (ok) {
            if (!ok) return;
            withLoading(url, api('/admin/ad-broadcast', { method: 'POST', body: { url: u, stage: 'send' } })).then(function (r) {
              toast('ارسال تبلیغ آغاز شد (' + fa(r.total) + ' کاربر)', 'success'); url.value = '';
            }, function (e) { toast(errMsg(e), 'error'); });
          });
        }
        return h('div', { class: 'card mt-12' },
          h('div', { class: 'card-title' }, icon('megaphone'), 'حالت تبلیغ'),
          h('div', { class: 'small muted', style: 'margin-bottom:10px' }, 'قالب پیام «یه فضول روی لینک شما کلیک کرد!» برای همه ارسال می‌شود و تمام دکمه‌هایش لینک تبلیغ شما را باز می‌کنند.'),
          h('div', { class: 'field' }, h('label', null, 'لینک تبلیغ'), url),
          h('div', { class: 'btn-row mt-8' },
            h('button', { class: 'btn btn-ghost btn-sm', onclick: function () { go('preview'); } }, icon('eye'), 'نمونه به چت من'),
            h('button', { class: 'btn btn-primary btn-sm', onclick: function () { go('send'); } }, icon('send'), 'تأیید و ارسال به همه')));
      }
      function send() {
        confirmDialog({ title: 'ارسال پیام همگانی', text: 'پیام برای ' + fa(meta.counts[target]) + ' کاربر ارسال می‌شود. این کار قابل لغو نیست.', ok: 'ارسال کن', icon: 'megaphone' }).then(function (ok) {
          if (!ok) return; MainAction.loading(true);
          api('/admin/broadcast', { method: 'POST', body: { text: text, target: target } }).then(function (r) {
            MainAction.clear(); toast('ارسال آغاز شد', 'success');
            job = { id: r.job_id, status: 'running', total: r.total, sent: 0, failed: 0 }; ta.value = ''; text = ''; draw(meta);
            var iv = setInterval(function () {
              api('/admin/broadcast/' + r.job_id).then(function (j) {
                if (!ctx.alive) return; job = j; var c = ctx.body.querySelector('#job-card'); if (c) c.replaceWith(jobCard(j));
                if (j.status !== 'running') { clearInterval(iv); toast('پخش همگانی تکمیل شد', 'success'); Cache.del('admin:bmeta'); job = null; setTimeout(function () { if (ctx.alive) ctx.reload(); }, 1200); }
              }, function () { /* تلاش بعدی */ });
            }, 1500);
            ctx.onCleanup(function () { clearInterval(iv); });
          }, function (e) { MainAction.loading(false); toast(errMsg(e), 'error'); });
        });
      }
    }
  });

  Router.def('admin-tickets', {
    admin: true, tab: 'admin',
    render: function (ctx) {
      ctx.header({ title: 'صندوق پشتیبانی', actions: [iconBtn('refresh', function () { ctx.reload(); }, 'به‌روزرسانی')] });
      useData(ctx, 'admin:tickets', function () { return api('/admin/tickets'); }, function (d) {
        if (!d.items.length) { ctx.body.replaceChildren(Empty({ icon: 'inbox', title: 'صندوق خالی است', text: 'فعلاً پیام پشتیبانی جدیدی نیست.' })); return; }
        ctx.body.replaceChildren(h('div', { class: 'list' }, d.items.map(function (t) {
          return ListItem({ lead: Avatar(t.name, t.user_id, { photo: t.avatar, vip: t.is_vip }), title: t.name + (t.is_vip ? ' ⚡️' : ''), sub: (t.last_from === 'admin' ? 'شما: ' : '') + t.last_text, end: h('div', { style: 'display:flex;flex-direction:column;align-items:flex-end;gap:4px' }, h('span', null, ago(t.last_at)), t.unread ? h('span', { class: 'chip danger' }, fa(t.unread)) : statusChip(t.status)), noChev: true, onClick: function () { Router.go('admin-ticket', { user_id: t.user_id, name: t.name }); } });
        })));
      });
    }
  });

  Router.def('admin-ticket', {
    admin: true, tab: 'admin', flush: true,
    render: function (ctx) {
      var uid = ctx.params.user_id;
      var closeBtn = h('button', { class: 'btn btn-ghost btn-sm', onclick: function () {
        confirmDialog({ title: 'بستن گفتگو', text: 'گفتگو بسته می‌شود؛ با پیام جدید کاربر دوباره باز خواهد شد.', ok: 'بستن' }).then(function (ok) {
          if (ok) api('/admin/tickets/' + uid + '/close', { method: 'POST' }).then(function () { toast('گفتگو بسته شد', 'success'); Cache.del('admin:tickets'); ctx.reload(); }, function (e) { toast(errMsg(e), 'error'); });
        });
      } }, 'بستن');
      ctx.header({ title: ctx.params.name || 'گفتگو', subtitle: 'شناسه ' + faDigits(uid), actions: [closeBtn, iconBtn('user', function () { Router.go('admin-user', { id: uid }); }, 'پروفایل کاربر')] });
      ChatView(ctx, {
        mine: 'admin', placeholder: 'پاسخ به کاربر…',
        fetch: function () { return api('/admin/tickets/' + uid); },
        send: function (text) { Cache.del('admin:tickets'); return api('/admin/tickets/' + uid + '/reply', { method: 'POST', body: { text: text } }); },
        onMeta: function (d) { closeBtn.style.display = d.status === 'closed' ? 'none' : ''; },
        attach: function () { openSheet({ title: 'پاسخ با مدیا', body: h('div', { class: 'alert' }, icon('info'), h('div', null, 'برای ارسال عکس یا فایل به کاربر، از دستور پاسخ در چت ربات استفاده کنید.')), actions: [{ text: 'باز کردن ربات در بله', icon: 'external', onClick: function (c) { c(); Platform.openBot('reply_' + uid); } }] }); },
        pollMs: 12000
      });
    }
  });

  Router.def('admin-backup', {
    admin: true, tab: 'admin',
    render: function (ctx) {
      ctx.header({ title: 'بکاپ و بازیابی' });
      useData(ctx, 'admin:backup', function () { return api('/admin/backup'); }, function (d) {
        var btn = h('button', { class: 'btn btn-primary btn-block mt-12', onclick: function () {
          withLoading(btn, api('/admin/backup', { method: 'POST' })).then(function (r) { toast('بکاپ «' + r.filename + '» به چت ادمین در بله ارسال شد', 'success'); Cache.del('admin:backup'); }, function (e) { toast(errMsg(e), 'error'); });
        } }, icon('upload'), 'تهیه بکاپ فوری و ارسال به بله');
        ctx.body.replaceChildren(h('div', null,
          h('div', { class: 'card' }, h('div', { class: 'card-title' }, icon('database'), 'وضعیت دیتابیس'),
            h('div', { class: 'info-rows' }, infoRow('آخرین بکاپ', jdate(d.last_backup_at, true)), infoRow('حجم دیتابیس', bytes(d.db_size_bytes)), infoRow('زمان‌بندی', d.schedule), infoRow('تعداد کاربران', fa(d.users)), infoRow('مسیر', h('span', { class: 'ltr' }, d.path))), btn),
          h('div', { class: 'card' }, h('div', { class: 'card-title' }, icon('refresh'), 'بازیابی دیتابیس'),
            h('div', { class: 'alert danger' }, icon('alert'), h('div', null, 'بازیابی، دیتابیس فعلی را با فایل بکاپ جایگزین می‌کند. به‌دلیل نیاز به آپلود فایل، این کار فقط از چت ربات با دستور /restore انجام می‌شود.')),
            h('button', { class: 'btn btn-danger btn-block mt-12', onclick: function () { Platform.openBot('restore'); } }, icon('external'), 'رفتن به چت ربات برای /restore'))));
      }, Skel.cards);
    }
  });

  /* ===================== Admin: آرشیو پیام‌های ناشناس ===================== */
  Router.def('admin-anonlog', {
    admin: true, tab: 'admin',
    render: function (ctx) {
      ctx.header({ title: 'آرشیو پیام‌های ناشناس', subtitle: 'به‌جای ارسال به چت ادمین', actions: [iconBtn('refresh', function () { ctx.reload(); }, 'به‌روزرسانی')] });
      var page = 1, q = '';
      var input = h('input', { class: 'input', type: 'search', placeholder: 'جستجو: نام، یوزرنیم، شناسه یا متن پیام', inputMode: 'search' });
      var listArea = h('div', { class: 'mt-12' });
      var statsArea = h('div', { class: 'kpi-grid' });
      function load() {
        listArea.replaceChildren(Skel.list(6));
        api('/admin/anon-logs?page=' + page + (q ? '&q=' + encodeURIComponent(q) : '')).then(function (d) {
          if (!ctx.alive) return;
          statsArea.replaceChildren(
            h('div', { class: 'kpi' }, h('div', { class: 'top' }, h('div', { class: 'li-icon' }, icon('database'))), h('div', { class: 'v' }, fa(d.stats.total)), h('div', { class: 'k' }, 'کل پیام‌ها')),
            h('div', { class: 'kpi' }, h('div', { class: 'top' }, h('div', { class: 'li-icon info' }, icon('bolt'))), h('div', { class: 'v' }, fa(d.stats.last_24h)), h('div', { class: 'k' }, '۲۴ ساعت اخیر')),
            h('div', { class: 'kpi' }, h('div', { class: 'top' }, h('div', { class: 'li-icon gold' }, icon('message'))), h('div', { class: 'v' }, fa(d.stats.today)), h('div', { class: 'k' }, 'امروز')));
          if (!d.items.length) { listArea.replaceChildren(Empty({ icon: 'message', title: 'پیامی نیست', text: 'فعلاً پیام ناشناسی ثبت نشده است.' })); return; }
          var rows = h('div', { class: 'list' }, d.items.map(function (m) {
            return h('div', { class: 'list-item', onclick: function () { Router.go('admin-user', { id: m.sender.id }); } },
              Avatar(m.sender.name, m.sender.id, { photo: m.sender.avatar }),
              h('div', { class: 'li-body' },
                h('div', { class: 'li-title ellipsis' }, m.sender.name, h('span', { class: 'muted small', style: 'margin:0 4px' }, '←'), h('b', null, m.receiver.name)),
                h('div', { class: 'li-sub ellipsis' }, m.text || '—')),
              h('div', { class: 'li-end', style: 'display:flex;flex-direction:column;align-items:flex-end;gap:4px' },
                h('span', { class: 'small muted' }, ago(m.created_at)),
                h('span', { class: 'chip', style: 'direction:ltr' }, '#' + faDigits(String(m.sender.id)))));
          }));
          var pager = h('div', { class: 'chips mt-12', style: 'justify-content:center' });
          if (page > 1) pager.appendChild(h('button', { class: 'chip', onclick: function () { page--; load(); } }, 'صفحه قبل'));
          pager.appendChild(h('span', { class: 'chip on' }, 'صفحه ' + fa(d.page) + ' از ' + fa(d.pages)));
          if (page < d.pages) pager.appendChild(h('button', { class: 'chip', onclick: function () { page++; load(); } }, 'صفحه بعد'));
          listArea.replaceChildren(rows, pager);
        }, function (e) { if (ctx.alive) listArea.replaceChildren(ErrorState(e, load)); });
      }
      input.addEventListener('input', debounce(function () { q = input.value.trim(); page = 1; load(); }, 400));
      ctx.body.replaceChildren(h('div', { class: 'search' }, icon('search'), input), statsArea, listArea);
      load();
    }
  });

  /* ===================== v4.3: Admin: آمار تفصیلی (هم‌ارز آمار کاربران/VIP + آرشیو روزانه پنل شیشه‌ای) ===================== */
  Router.def('admin-stats', {
    admin: true, tab: 'admin',
    render: function (ctx) {
      ctx.header({ title: 'آمار تفصیلی', subtitle: 'هم‌ارز آمار کاربران و آمار VIP پنل شیشه‌ای', actions: [iconBtn('refresh', function () { ctx.reload(); }, 'به‌روزرسانی')] });
      useData(ctx, 'admin:stats', function () { return api('/admin/stats'); }, function (s) {
        function kpi(ic, tone, v, k) { return h('div', { class: 'kpi' }, h('div', { class: 'top' }, h('div', { class: 'li-icon ' + tone }, icon(ic))), h('div', { class: 'v' }, v), h('div', { class: 'k' }, k)); }
        var conv = s.users_total ? Math.round(s.vip_ever * 100 / s.users_total) : 0;
        var w = h('div', null);
        w.appendChild(h('div', { class: 'card' }, h('div', { class: 'card-title' }, icon('users'), 'کاربران'),
          h('div', { class: 'kpi-grid', style: 'margin-top:8px' },
            kpi('users', '', fa(s.users_total), 'کل کاربران'),
            kpi('plus', 'info', fa(s.users_month), '۳۰ روز اخیر'),
            kpi('bolt', 'accent', fa(s.users_active_today), 'فعال امروز'),
            kpi('clock', '', fa(s.users_week_active), 'فعال این هفته'),
            kpi('ban', 'danger', fa(s.banned), 'مسدود'),
            kpi('target', '', fa(s.traps_total), 'کل تله‌ها'))));
        w.appendChild(h('div', { class: 'card mt-12' }, h('div', { class: 'card-title' }, icon('crown'), 'VIP و مالی'),
          h('div', { class: 'kpi-grid', style: 'margin-top:8px' },
            kpi('crown', 'gold', fa(s.vip_active), 'VIP فعال'),
            kpi('clock', 'warn', fa(s.vip_expiring_7d), 'انقضا تا ۷ روز'),
            kpi('users', 'info', fa(s.vip_ever), 'خریدار (کل)'),
            kpi('chart', 'accent', fa(conv) + '٪', 'نرخ تبدیل'),
            kpi('receipt', 'gold', toman(s.revenue_month), 'درآمد ماه'),
            kpi('receipt', '', toman(s.vip_revenue_total), 'درآمد کل'))));
        w.appendChild(h('div', { class: 'card mt-12' }, h('div', { class: 'card-title' }, icon('message'), 'فعالیت'),
          h('div', { class: 'kpi-grid', style: 'margin-top:8px' },
            kpi('eye', '', fa(s.snoops_today), 'فضولی امروز'),
            kpi('eye', 'info', fa(s.snoops_total == null ? '—' : s.snoops_total), 'کل فضول‌ها'),
            kpi('message', 'gold', fa(s.anon_total), 'کل پیام ناشناس'),
            kpi('gift', 'warn', fa(s.spins_total), 'چرخش گردونه'))));
        w.appendChild(SectionTitle('آرشیو روزانه (۱۴ روز اخیر)'));
        var rows = [h('div', { class: 'info-row', style: 'font-weight:800' }, h('span', null, 'تاریخ'), h('span', { class: 'ltr' }, 'کاربر / فضول / ناشناس'))];
        s.chart.slice().reverse().forEach(function (p) {
          rows.push(h('div', { class: 'info-row' }, h('span', null, jdate(p.day_local || p.date)),
            h('span', { class: 'ltr' }, fa(p.new_users) + ' / ' + fa(p.snoops) + ' / ' + fa(p.anon || 0))));
        });
        w.appendChild(h('div', { class: 'card info-rows' }, rows));
        w.appendChild(h('div', { class: 'small muted mt-8', style: 'margin:0 4px 12px' }, 'هر ردیف: کاربران جدید، فضول‌های ثبت‌شده و پیام‌های ناشناس آن روز.'));
        if (s.challenge_status && s.challenge_status.status !== 'idle') {
          var cs = s.challenge_status;
          w.appendChild(h('div', { class: 'alert warn mt-12' }, icon('target'), h('div', null, 'چالش فضول‌گیر برتر در جریان است: ', h('b', null, CHALLENGE_FA[cs.status] || cs.status), ' — ', h('a', { href: '#', onclick: function (e) { e.preventDefault(); Router.go('admin-challenge'); } }, 'مدیریت چالش ←'))));
        }
        ctx.body.replaceChildren(w);
      }, Skel.cards);
    }
  });
  var CHALLENGE_FA = { idle: 'غیرفعال', scheduled: 'زمان‌بندی‌شده', active: 'در جریان', cancelled: 'لغو شده', finished: 'پایان‌یافته' };

  /* ===================== v4.3: Admin: چالش فضول‌گیر برتر ===================== */
  Router.def('admin-challenge', {
    admin: true, tab: 'admin',
    render: function (ctx) {
      ctx.header({ title: 'چالش فضول‌گیر برتر', subtitle: 'شمارش فضول‌های جدید در بازهٔ چالش', actions: [iconBtn('refresh', function () { ctx.reload(); }, 'به‌روزرسانی')] });
      useData(ctx, 'admin:challenge', function () { return api('/admin/challenge'); }, function (c) {
        var w = h('div', null);
        var stFa = CHALLENGE_FA[c.status] || c.status;
        var tone = c.status === 'active' ? 'accent' : c.status === 'scheduled' ? 'warn' : '';
        /* v4.6: خط پاداش — بر اساس نوع جایزه (vip یا پاکت) */
        var rewardLine;
        if ((c.reward_type || 'vip') === 'envelope') {
          var a0 = c.reward_amount || 0;
          rewardLine = '🧧 پاکت رتبهٔ اول: ' + (a0 > 0 ? fa(a0) + ' تومان' : 'نقدی (مبلغ بعداً تعیین می‌شود)')
            + ' • دوم ' + (a0 > 0 ? fa(Math.floor(a0 * 0.6)) + ' تومان' : '—')
            + ' • سوم ' + (a0 > 0 ? fa(Math.floor(a0 * 0.3)) + ' تومان' : '—')
            + ' — توزیع دستی توسط ادمین پس از پایان چالش';
        } else {
          rewardLine = 'پاداش رتبهٔ اول: ' + fa(c.reward_days) + ' روز VIP • دوم ' + fa(Math.max(1, Math.floor(c.reward_days * 60 / 100))) + ' روز • سوم ' + fa(Math.max(1, Math.floor(c.reward_days * 30 / 100))) + ' روز';
        }
        w.appendChild(h('div', { class: 'card center', style: 'padding:18px' },
          h('div', { class: 'li-icon ' + tone, style: 'width:52px;height:52px;border-radius:16px;margin:0 auto 10px;display:flex;align-items:center;justify-content:center' }, icon('target')),
          h('div', { class: 'bold', style: 'font-size:16px' }, 'وضعیت: ' + stFa),
          h('div', { class: 'small muted mt-4' }, c.status === 'active' || c.status === 'scheduled' ? rewardLine
            : 'چالش جدید با «شروع چالش» ساخته می‌شود؛ شمارش از ۰۰:۰۰ فردا آغاز و به‌صورت خودکار تسویه می‌شود.')));
        if (c.status === 'scheduled' || c.status === 'active') {
          var cd = h('div', { class: 'countdown', style: 'font-size:22px' }, '--:--:--');
          w.appendChild(h('div', { class: 'card center mt-12' },
            h('div', { class: 'muted small' }, c.status === 'scheduled' ? 'تا شروع شمارش' : 'تا پایان چالش'), cd,
            c.start_at ? h('div', { class: 'small muted mt-8' }, 'پایان: ' + jdate(c.end_at, true)) : null));
          var tick = function () {
            var s = c.remaining_sec != null ? c.remaining_sec + Math.max(0, Math.floor((Date.now() - fetchedAt) / 1000)) : 0;
            if (s <= 0) { Cache.del('admin:challenge'); ctx.reload(); return; }
            cd.textContent = faDigits([Math.floor(s / 3600), Math.floor(s % 3600 / 60), s % 60].map(function (x) { return (x < 10 ? '0' : '') + x; }).join(':'));
          };
          var fetchedAt = Date.now(); tick();
          var iv = setInterval(tick, 1000); ctx.onCleanup(function () { clearInterval(iv); });
          w.appendChild(h('div', { class: 'btn-row mt-12' }, h('button', { class: 'btn btn-danger btn-block', onclick: function () { cancelCh(); } }, icon('x'), 'لغو فوری چالش')));
        } else {
          w.appendChild(h('div', { class: 'btn-row mt-12' }, h('button', { class: 'btn btn-primary btn-block', onclick: function () { startSheet(); } }, icon('plus'), 'شروع چالش')));
        }
        w.appendChild(SectionTitle(c.top && c.top.length ? 'جدول برترین‌ها (۱۰ نفر)' : 'جدول برترین‌ها'));
        if (c.top && c.top.length) {
          w.appendChild(h('div', { class: 'list' }, c.top.map(function (r, i) {
            return ListItem({ lead: Avatar(r.name, r.id, { photo: r.avatar }), title: (i + 1) + '. ' + r.name, sub: r.username ? '@' + r.username : null, end: h('span', { class: 'chip' + (i === 0 ? ' gold' : '') }, icon('eye'), ' ' + fa(r.snoops) + ' فضول') });
          })));
        } else {
          w.appendChild(h('div', { class: 'card' }, Empty({ icon: 'trophy', title: 'هنوز رتبه‌ای ثبت نشده', text: c.status === 'active' ? 'با اولین فضولِ جدید، جدول شکل می‌گیرد.' : 'پس از شروع چالش، برترین‌ها اینجا دیده می‌شوند.' })));
        }
        w.appendChild(h('div', { class: 'alert mt-12' }, icon('info'), h('div', null, 'این بخش با منوی شیشه‌ای ربات هم‌گام است: اعلان شروع/پایان و تسویهٔ جوایز توسط خود ربات در بله انجام می‌شود.')));
        ctx.body.replaceChildren(w);
        function startSheet() {
          var hours = h('input', { class: 'input', type: 'number', inputMode: 'numeric', min: 1, max: 168, value: '24' });
          var days = h('input', { class: 'input', type: 'number', inputMode: 'numeric', min: 1, max: 365, value: '3' });
          var amount = h('input', { class: 'input', type: 'number', inputMode: 'numeric', min: 0, step: 1000, placeholder: 'مثلاً ۵۰۰۰۰۰ — خالی = فقط نوع پاکت' });
          var hChips = h('div', { class: 'chips' }, [24, 48, 72, 168].map(function (n) { return h('button', { class: 'chip', onclick: function () { hours.value = n; refreshAnnounce(); } }, fa(n) + ' ساعت'); }));
          /* v4.6: مرحلهٔ ۲ — نوع جایزه: روزهای VIP یا پاکت نقدی (توزیع دستی ادمین پس از پایان چالش) */
          var typeVal = 'vip';
          var fVip = h('div', { class: 'field' }, h('label', null, 'جایزهٔ رتبهٔ اول (روز VIP)'), days,
            h('div', { class: 'hint' }, h('span', null, 'رتبهٔ دوم ۶۰٪ و رتبهٔ سوم ۳۰٪ این مقدار — تسویهٔ خودکار ربات')));
          var fEnv = h('div', { class: 'field', style: 'display:none' }, h('label', null, 'مبلغ پاکت رتبهٔ اول (تومان)'), amount,
            h('div', { class: 'hint' }, h('span', null, 'پاکت دوم ۶۰٪ و سوم ۳۰٪ — پس از پایان چالش، خودت پاکت‌ها را بین برندگان توزیع می‌کنی')));
          var segVip = h('button', { type: 'button', class: 'on', onclick: function () { setType('vip'); } }, icon('crown'), h('span', null, 'روزهای VIP'));
          var segEnv = h('button', { type: 'button', onclick: function () { setType('envelope'); } }, icon('gift'), h('span', null, 'پاکت نقدی 🧧'));
          function setType(t) {
            typeVal = t;
            segVip.classList.toggle('on', t === 'vip');
            segEnv.classList.toggle('on', t === 'envelope');
            fVip.style.display = t === 'vip' ? '' : 'none';
            fEnv.style.display = t === 'envelope' ? '' : 'none';
            refreshAnnounce();
          }
          /* v4.6: مرحلهٔ ۳ — متن اعلان شروع: پیش‌فرضِ هوشمند با مقادیر فرم؛ قابل ویرایش کامل */
          var announce = h('textarea', { class: 'textarea', rows: 9, style: 'min-height:180px;font-size:12.5px;line-height:1.9' });
          var announceDirty = false;
          announce.addEventListener('input', function () { announceDirty = true; });
          function defaultAnnounce() {
            var hh = parseInt(hours.value, 10) || 24, block;
            if (typeVal === 'envelope') {
              var a = parseInt(amount.value, 10) || 0;
              block = a > 0
                ? ' 🥇 پاکت ' + fa(a) + ' تومان\n 🥈 پاکت ' + fa(Math.floor(a * 0.6)) + ' تومان\n 🥉 پاکت ' + fa(Math.floor(a * 0.3)) + ' تومان'
                : ' 🥇 پاکت نقدی\n 🥈 پاکت نقدی\n 🥉 پاکت نقدی';
            } else {
              var dd = parseInt(days.value, 10) || 3;
              block = ' 🥇 ' + fa(dd) + ' روز VIP\n 🥈 ' + fa(Math.max(1, Math.floor(dd * 0.6))) + ' روز VIP\n 🥉 ' + fa(Math.max(1, Math.floor(dd * 0.3))) + ' روز VIP';
            }
            return '🏆 *چالش «فضول‌گیر برتر» اعلام شد!*\n\n🎁 *پاداش ها:*\n' + block + '\n\n⏰ مدت چالش: *' + fa(hh) + ' ساعت* شمارش رسمی\n🕛 شروع شمارش: فردا ساعت ۰۰:۰۰ به وقت تهران\n\n⚙️ *قانون ساده:* هر فضول جدید (کسی که اولین‌بار وارد ربات می‌شه) که روی لینک تلهٔ تو کلیک کنه، یک امتیاز برای تو ثبت می‌شه. هرکی در پایان بیشترین فضول جدید رو گرفته باشه، برنده‌ست!\n\n💡 از همین حالا تله‌ات رو آماده کن و لینکت رو همه‌جا پخش کن!\n⬇️ جزئیات و جدول رقبا رو از دکمهٔ «🏆 فضول‌گیر برتر» در منو دنبال کن.';
          }
          function refreshAnnounce() { if (!announceDirty) announce.value = defaultAnnounce(); }
          hours.addEventListener('input', refreshAnnounce);
          days.addEventListener('input', refreshAnnounce);
          amount.addEventListener('input', refreshAnnounce);
          refreshAnnounce();
          openSheet({
            title: 'شروع چالش فضول‌گیر برتر',
            body: h('div', { class: 'stack' },
              h('div', { class: 'field' }, h('label', null, '۱) مدت شمارش (ساعت)'), hChips, hours),
              h('div', { class: 'field' }, h('label', null, '۲) نوع جایزه'), h('div', { class: 'seg' }, segVip, segEnv), fVip, fEnv),
              h('div', { class: 'field' },
                h('label', null, '۳) متن اعلان شروع (برای همهٔ کاربران — قابل ویرایش)'),
                h('div', { style: 'margin:0 0 8px' }, h('button', { class: 'chip', onclick: function () { announceDirty = false; refreshAnnounce(); toast('متن پیش‌فرض بازگردانی شد', 'success'); } }, '↺ بازگردانی پیش‌فرض')),
                announce,
                h('div', { class: 'hint' }, h('span', null, 'همین متن عیناً و بلافاصله برای همهٔ کاربران ارسال می‌شود'))),
              h('div', { class: 'small muted' }, 'اعلان شروع بلافاصله برای همه ارسال می‌شود؛ شمارش از ۰۰:۰۰ فردا آغاز و در پایان، خودکار تسویه می‌شود.')),
            actions: [{ text: 'شروع چالش', icon: 'target', onClick: function (close, btn) {
              withLoading(btn, api('/admin/challenge', { method: 'POST', body: {
                action: 'start',
                hours: parseInt(hours.value, 10),
                reward_days: parseInt(days.value, 10),
                reward_type: typeVal,
                reward_amount: parseInt(amount.value, 10) || 0,
                announce_text: (announce.value || '').trim()
              } })).then(function () {
                close(); Cache.del('admin:challenge'); Cache.del('admin:stats'); toast('چالش زمان‌بندی شد ✅', 'success'); ctx.reload();
              }, function (e) { toast(errMsg(e), 'error'); });
            } }]
          });
        }
        function cancelCh() {
          confirmDialog({ title: 'لغو فوری چالش', text: 'چالش لغو می‌شود و جایزه‌ای پرداخت نمی‌شود. این کار قابل بازگشت نیست.', ok: 'لغو چالش', danger: true, icon: 'target' }).then(function (ok) {
            if (ok) api('/admin/challenge', { method: 'POST', body: { action: 'cancel' } }).then(function () { Cache.del('admin:challenge'); Cache.del('admin:stats'); toast('چالش لغو شد', 'success'); ctx.reload(); }, function (e) { toast(errMsg(e), 'error'); });
          });
        }
      }, Skel.cards);
    }
  });

  /* ===================== v4.3: Admin: کانال‌های اجباری (اد اجباری پنل شیشه‌ای) ===================== */
  Router.def('admin-channels', {
    admin: true, tab: 'admin',
    render: function (ctx) {
      ctx.header({ title: 'کانال‌های اجباری', subtitle: 'عضویت اجباری پیش از استفاده از ربات', actions: [iconBtn('plus', function () { addSheet(); }, 'افزودن کانال')] });
      useData(ctx, 'admin:channels', function () { return api('/admin/forced-channels'); }, function (d) {
        var w = h('div', null);
        w.appendChild(h('div', { class: 'alert ' + (d.enabled ? '' : 'warn') + ' mt-0' }, icon(d.enabled ? 'check' : 'alert'),
          h('div', null, d.enabled ? 'عضویت اجباری فعال است: کاربران باید عضو کانال‌های زیر شوند.' : 'عضویت اجباری در تنظیمات ربات (env) غیرفعال است؛ لیست زیر ذخیره می‌شود اما اعمال نمی‌شود.')));
        if (!d.items.length) {
          w.appendChild(h('div', { class: 'card mt-12' }, Empty({ icon: 'megaphone', title: 'کانالی تعریف نشده', text: 'با افزودن کانال، کاربران جدید باید عضو شوند.', action: { text: 'افزودن کانال', icon: 'plus', onClick: addSheet } })));
        } else {
          w.appendChild(h('div', { class: 'list' }, d.items.map(function (c) {
            var end = h('div', { style: 'display:flex;flex-direction:column;align-items:flex-end;gap:4px' },
              h('span', { class: 'small muted' }, c.percent != null ? fa(c.percent) + '٪ • ' + fa(c.joins) + ' / ' + fa(c.target) + ' عضو' : fa(c.joins) + ' عضو'));
            return ListItem({ icon: 'megaphone', tone: 'info', title: c.title, sub: h('span', { class: 'ltr' }, '@' + c.id), end: end, noChev: true, onClick: function () {
              confirmDialog({ title: 'حذف کانال', text: '«' + c.title + '» از کانال‌های اجباری حذف می‌شود و شرط عضویت برای کاربران برداشته می‌شود.', ok: 'حذف', danger: true, icon: 'trash' }).then(function (ok) {
                if (ok) api('/admin/forced-channels/' + encodeURIComponent(c.id), { method: 'DELETE' }).then(function (r) { Cache.set('admin:channels', r); toast('کانال حذف شد', 'success'); ctx.reload(); }, function (e) { toast(errMsg(e), 'error'); });
              });
            } });
          })));
        }
        w.appendChild(h('div', { class: 'alert mt-12' }, icon('info'), h('div', null, 'هم‌گام با «اد اجباری» منوی شیشه‌ای ربات: تغییرات بلافاصله برای ربات و مینی‌اپ اعمال می‌شود.')));
        ctx.body.replaceChildren(w);
        function addSheet() {
          var cid = h('input', { class: 'input ltr', placeholder: '@mychannel یا شناسه عددی' });
          var title = h('input', { class: 'input', placeholder: 'نام نمایشی کانال', maxLength: 60 });
          var target = h('input', { class: 'input', type: 'number', inputMode: 'numeric', min: 0, placeholder: '۰ = بدون محدودیت' });
          openSheet({
            title: 'افزودن کانال اجباری',
            body: h('div', { class: 'stack' },
              h('div', { class: 'field' }, h('label', null, 'شناسهٔ کانال'), cid),
              h('div', { class: 'field' }, h('label', null, 'نام نمایشی'), title),
              h('div', { class: 'field' }, h('label', null, 'هدف جذب (اختیاری)'), target, h('div', { class: 'hint' }, h('span', null, 'تا رسیدن به این تعداد عضو، عضویت اجباری ادامه دارد'))),
              h('div', { class: 'small muted' }, 'ربات باید ادمین کانال باشد تا عضویت قابل بررسی باشد.')),
            actions: [{ text: 'افزودن', icon: 'plus', onClick: function (close, btn) {
              withLoading(btn, api('/admin/forced-channels', { method: 'POST', body: { channel_id: cid.value, title: title.value, target: parseInt(target.value || '0', 10) } })).then(function (r) {
                close(); Cache.set('admin:channels', r); toast('کانال اضافه شد', 'success'); ctx.reload();
              }, function (e) { toast(errMsg(e), 'error'); });
            } }]
          });
          setTimeout(function () { cid.focus(); }, 350);
        }
      }, Skel.cards);
    }
  });

  /* ===================== Admin: تنظیمات و قابلیت‌ها ===================== */
  Router.def('admin-settings', {
    admin: true, tab: 'admin',
    render: function (ctx) {
      ctx.header({ title: 'تنظیمات و قابلیت‌ها', subtitle: 'هم‌گام با منوی شیشه‌ای ربات' });
      function setVal(key, value, done) {
        api('/admin/settings', { method: 'POST', body: { key: key, value: value } }).then(function (r) {
          Cache.set('admin:settings', { items: r.items }); Cache.del('admin:stats'); Cache.del('lb:week'); Cache.del('lb:all'); Cache.del('vip'); Cache.del('wheel');
          toast('ذخیره شد', 'success'); if (done) done(r.items);
        }, function (e) { toast(errMsg(e), 'error'); });
      }
      useData(ctx, 'admin:settings', function () { return api('/admin/settings'); }, draw, Skel.cards);
      function draw(d) {
        var byKey = {};
        d.items.forEach(function (it) { byKey[it.key] = it; });
        var w = h('div', null);
        function switchRow(it) {
          var on = String(it.value) === '1';
          var sw = h('span', { class: 'switch' + (on ? ' on' : '') });
          return ListItem({ icon: it.key.indexOf('backup') >= 0 ? 'database' : it.key.indexOf('wheel') >= 0 ? 'gift' : it.key.indexOf('maint') >= 0 ? 'alert' : it.key.indexOf('report') >= 0 || it.key.indexOf('reminder') >= 0 ? 'clock' : 'bot', tone: on ? 'accent' : '', title: it.label, sub: it.hint, end: sw, noChev: true, onClick: function () {
            Platform.haptic('select');
            var nv = on ? 0 : 1; on = nv;
            sw.classList.toggle('on', !!nv);
            setVal(it.key, nv);
          } });
        }
        function numRow(it, opts) {
          opts = opts || {};
          var isPrice = it.type === 'price';
          var shown = isPrice ? Math.round(parseInt(it.value, 10) / 10) : parseInt(it.value, 10);
          var valEl = h('b', { style: 'font-size:15px' }, isPrice ? fa(shown) + ' تومان' : fa(shown) + (opts.unit || ''));
          function edit() {
            var inp = h('input', { class: 'input', type: 'number', inputMode: 'numeric', min: opts.min || 0, max: opts.max || 100000000, value: String(shown) });
            openSheet({
              title: it.label,
              body: h('div', { class: 'stack' },
                it.key === 'leaderboard_size' ? h('div', { class: 'chips' }, [10, 20, 30, 50].map(function (n) { return h('button', { class: 'chip', onclick: function () { inp.value = n; } }, fa(n) + ' نفر'); })) : null,
                h('div', { class: 'field' }, h('label', null, isPrice ? 'مقدار (تومان)' : 'مقدار'), inp),
                it.hint ? h('div', { class: 'small muted' }, it.hint) : null),
              actions: [{ text: 'ذخیره', icon: 'check', onClick: function (close, btn) {
                var v = parseInt(inp.value, 10);
                if (!(v >= (opts.min || 0))) { toast('مقدار معتبر وارد کنید', 'error'); return; }
                withLoading(btn, new Promise(function (res) { setVal(it.key, v, function (items) { close(); res(); }); }));
              } }]
            });
            setTimeout(function () { inp.focus(); }, 350);
          }
          return ListItem({ icon: it.key === 'leaderboard_size' ? 'trophy' : it.key.indexOf('price') >= 0 ? 'crown' : it.key.indexOf('day') >= 0 || it.key.indexOf('hour') >= 0 ? 'clock' : 'hash', tone: it.key.indexOf('price') >= 0 ? 'gold' : 'info', title: it.label, sub: it.hint || (it.key === 'weekly_report_day' ? '۰=شنبه … ۶=جمعه' : null), end: h('button', { class: 'chip', onclick: function (e) { e.stopPropagation(); Platform.haptic('light'); edit(); } }, valEl) });
        }
        w.appendChild(SectionTitle('نمایش'));
        w.appendChild(h('div', { class: 'list' }, numRow(byKey.leaderboard_size, { min: 3, max: 50, unit: ' نفر' })));
        w.appendChild(SectionTitle('قابلیت‌ها'));
        w.appendChild(h('div', { class: 'list' }, [byKey.wheel_enabled, byKey.maintenance_mode, byKey.smart_reminder_enabled, byKey.weekly_report_enabled, byKey.auto_backup_enabled].map(switchRow)));
        w.appendChild(SectionTitle('قیمت‌های VIP'));
        w.appendChild(h('div', { class: 'list' }, [byKey.vip_price_30, byKey.vip_price_90, byKey.vip_price_365].map(function (it) { return numRow(it, { min: 1000 }); })));
        w.appendChild(SectionTitle('زمان‌بندی و هدیه‌ها'));
        w.appendChild(h('div', { class: 'list' }, [numRow(byKey.weekly_report_day, { min: 0, max: 6 }), numRow(byKey.weekly_report_hour, { min: 0, max: 23, unit: ' ساعت' }), numRow(byKey.trial_days, { min: 0, max: 30, unit: ' روز' })]));
        w.appendChild(h('div', { class: 'alert mt-12' }, icon('info'), h('div', null, 'این تنظیمات همان منوی شیشه‌ای ربات هستند و بلافاصله روی ربات و مینی‌اپ اعمال می‌شوند.')));
        ctx.body.replaceChildren(w);
      }
    }
  });

  /* ===================== Admin: کدهای هدیه ===================== */
  Router.def('admin-gifts', {
    admin: true, tab: 'admin',
    render: function (ctx) {
      ctx.header({ title: 'کدهای هدیه', actions: [iconBtn('plus', function () { createSheet(); }, 'کد جدید')] });
      useData(ctx, 'admin:gifts', function () { return api('/admin/gifts'); }, draw, Skel.cards);
      function draw(d) {
        if (!d.items.length) { ctx.body.replaceChildren(Empty({ icon: 'gift', title: 'کدی نیست', text: 'با ساخت کد هدیه، کاربران با واردکردن آن در ربات VIP می‌شوند.', action: { text: 'ساخت اولین کد', icon: 'plus', onClick: createSheet } })); return; }
        ctx.body.replaceChildren(h('div', { class: 'list' }, d.items.map(function (g) {
          return ListItem({ icon: 'gift', tone: g.status === 'done' ? '' : 'gold', title: g.code, sub: fa(g.days) + ' روز VIP • ' + fa(g.used_count) + ' از ' + fa(g.max_uses) + ' استفاده', end: h('div', { style: 'display:flex;flex-direction:column;align-items:flex-end;gap:4px' }, statusChip(g.status), h('span', { class: 'small muted' }, jdate(g.created_at))), onClick: function () { copyText(g.code).then(function () { toast('کد «' + g.code + '» کپی شد', 'success'); }); } });
        })));
      }
      function createSheet() {
        var code = h('input', { class: 'input ltr', placeholder: 'خودکار', maxLength: 24 });
        var days = h('input', { class: 'input', type: 'number', inputMode: 'numeric', min: 1, max: 3650, value: '30' });
        var uses = h('input', { class: 'input', type: 'number', inputMode: 'numeric', min: 1, max: 10000, value: '10' });
        openSheet({
          title: 'کد هدیه جدید',
          body: h('div', { class: 'stack' },
            h('div', { class: 'field' }, h('label', null, 'کد (انگلیسی؛ خالی بگذارید تا خودکار ساخته شود)'), code),
            h('div', { class: 'field' }, h('label', null, 'روزهای VIP'), days),
            h('div', { class: 'field' }, h('label', null, 'سقف استفاده'), uses)),
          actions: [{ text: 'ساخت کد', icon: 'plus', onClick: function (close, btn) {
            var body = { days: parseInt(days.value, 10) || 0, max_uses: parseInt(uses.value, 10) || 0 };
            if (code.value.trim()) body.code = code.value.trim();
            withLoading(btn, api('/admin/gifts', { method: 'POST', body: body })).then(function (g) {
              close(); toast('کد «' + g.code + '» ساخته شد', 'success'); Cache.del('admin:gifts'); ctx.reload();
            }, function (e) { toast(errMsg(e), 'error'); });
          } }]
        });
      }
    }
  });

  /* ===================== Admin: تراکنش‌ها ===================== */
  Router.def('admin-transactions', {
    admin: true, tab: 'admin',
    render: function (ctx) {
      ctx.header({ title: 'تراکنش‌ها' });
      var page = 1;
      var listArea = h('div', { class: 'mt-12' });
      function load() {
        listArea.replaceChildren(Skel.list(6));
        api('/admin/transactions?page=' + page).then(function (d) {
          if (!ctx.alive) return;
          if (!d.items.length) { listArea.replaceChildren(Empty({ icon: 'receipt', title: 'تراکنشی ثبت نشده' })); return; }
          var rows = h('div', { class: 'list' }, d.items.map(function (t) {
            return ListItem({ lead: Avatar(t.user.name, t.user.id, { photo: t.user.avatar }), title: t.user.name, sub: t.type_fa + ' • ' + jdate(t.created_at, true), end: h('div', { style: 'text-align:left' }, h('div', { class: 'bold', style: 'color:var(--text)' }, t.days ? fa(t.days) + ' روز' : toman(t.amount))) });
          }));
          var pager = h('div', { class: 'chips mt-12', style: 'justify-content:center' });
          if (page > 1) pager.appendChild(h('button', { class: 'chip', onclick: function () { page--; load(); } }, 'صفحه قبل'));
          pager.appendChild(h('span', { class: 'chip on' }, 'صفحه ' + fa(d.page) + ' از ' + fa(d.pages)));
          if (page < d.pages) pager.appendChild(h('button', { class: 'chip', onclick: function () { page++; load(); } }, 'صفحه بعد'));
          listArea.replaceChildren(rows, pager);
        }, function (e) { if (ctx.alive) listArea.replaceChildren(ErrorState(e, load)); });
      }
      ctx.body.replaceChildren(listArea);
      load();
    }
  });

  /* ===================== Channel gate (عضویت اجباری) ===================== */
  var Gate = {
    el: null,
    show: function (channels) {
      if (this.el) this.el.remove();
      var self = this;
      var checkBtn = h('button', { class: 'btn btn-primary btn-block mt-16', onclick: function () {
        withLoading(checkBtn, api('/channels/check')).then(function (r) {
          if (r.joined) { self.hide(); toast('عضویت تأیید شد؛ خوش آمدید!', 'success'); Cache.m = {}; refreshMe().then(function () { Router.refresh(); }); }
          else toast('هنوز عضو همهٔ کانال‌ها نشده‌اید', 'error');
        }, function (e) { toast(errMsg(e), 'error'); });
      } }, icon('check'), 'عضو شدم، بررسی کن');
      this.el = h('div', { class: 'gate' },
        h('div', { class: 'g-icon' }, icon('megaphone')), h('h2', null, 'یک قدم تا شروع!'), h('p', null, 'برای استفاده از ' + CFG.appName + ' ابتدا عضو کانال زیر در بله شوید.'),
        h('div', { class: 'list' }, (channels || []).map(function (c) {
          return ListItem({ icon: 'megaphone', title: c.title, sub: c.username ? '@' + c.username : '', end: h('span', { class: 'btn btn-secondary btn-sm' }, 'عضویت'), noChev: true, onClick: function () { if (State.demo) api('/demo/join-click', { method: 'POST' }); Platform.openLink(c.url); } });
        })), checkBtn);
      Shell.root.appendChild(this.el);
    },
    hide: function () { if (this.el) { this.el.remove(); this.el = null; } }
  };

  /* ===================== Boot ===================== */
  function splash() {
    var s = h('div', { class: 'splash' },
      h('div', { class: 'logo' }, h('img', { src: 'img/logo.png', alt: '' })),
      h('h1', null, CFG.appName), h('div', { class: 'spinner' }));
    document.body.appendChild(s); return s;
  }
  function fatal(e, retry) {
    var el = h('div', { class: 'fatal' }, h('div', { class: 'card', style: 'width:100%;max-width:400px' }, ErrorState(e, retry),
      e.code && e.code.indexOf('AUTH') === 0 ? h('button', { class: 'btn btn-ghost btn-block', onclick: function () { Platform.openBot(); } }, icon('bot'), 'باز کردن ربات در بله') : null));
    document.body.appendChild(el); return el;
  }
  function decideDemo() {
    var q = ''; try { q = new URLSearchParams(location.search).get('demo') || ''; } catch (e) { q = ''; }
    if (q === '1' || CFG.demo === 'on') return true;
    if (q === '0' || CFG.demo === 'off') return false;
    return !Platform.initData;
  }
  function boot() {
    var sp = splash();
    Platform.init().then(function () {
      State.demo = decideDemo();
      Theme.init();
      Shell.mount();
      Platform.onBack(function () { Back.trigger(); });
      document.addEventListener('keydown', function (e) { if (e.key === 'Escape') Back.trigger(); });
      var fatalEl = null;
      function start() {
        if (fatalEl) { fatalEl.remove(); fatalEl = null; }
        api('/me').then(function (me) {
          State.me = me; Cache.set('me', me);
          if (window.FzVip) window.FzVip.apply(me);
          Shell.renderNav();
          var p = Platform.startParam(), tabs = ['home', 'snoop', 'vip', 'chat', 'support', 'profile', 'admin'];
          Router.start(tabs.indexOf(p) >= 0 && (p !== 'admin' || me.is_admin) ? p : 'home');
          if (p === 'wheel' || p === 'leaderboard' || p === 'missions') Router.go(p);
          if (me.channels && me.channels.joined === false) Gate.show(me.channels.required);
          if (me.is_admin) api('/admin/tickets').then(function (t) { Shell.setBadge('admin', t.items.filter(function (x) { return x.unread; }).length); }, function () { /* noop */ });
          sp.classList.add('hide'); setTimeout(function () { sp.remove(); }, 320);
        }, function (e) {
          sp.classList.add('hide');
          fatalEl = fatal(e, start);
        });
      }
      start();
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
