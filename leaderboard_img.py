# -*- coding: utf-8 -*-
"""
leaderboard_img — تولید تصویر «تالار شکارچیان» (v3.10.0)
v3.10: موتور نام‌ها با anyascii (ترنسلیتریشن کامل) + جهت پایهٔ نام
چیدمان ۲ منتخب ادمین: سکوی ۲-۱-۳ + فهرست رتبه‌های ۴ تا ۱۰
سبک: «نئون سایبر HUD × پاستل رویایی» (پایه تیره) + بوردر ردیف عادی‌ها
اصلاحات نهایی ادمین: عدد رتبه دقیقاً وسط کادر + نشان VIP در راستِ شکار

v3.9.3 — موتور نام‌های چندفونتی (فارسی/انگلیسی/فانتزی/ایموجی/ترکیبی):
  ۱) نرمال‌سازی NFKC: حروف ریاضی فانتزی → حروف ساده (𝓕𝓪𝓽𝓮𝓶𝓮𝓱 → Fatemeh)
  ۲) فیلتر گلیف-به-گلیف با cmap واقعی فونت‌ها (بدون tofu و بدون فاصله‌های رازده)
  ۳) فونت ایموجی تک‌رنگ NotoEmoji برای 👑✨🎀☁️… (هم‌رنگ نام، هماهنگ با استایل)
  ۴) ترسیم ران‌به-ران (هر ران با فونت خودش و bidi صحیح داخل ران)

خودکفا: Pillow + fontTools + فونت‌های وزیرمتن/NotoEmoji در fonts/
در نبود هر وابستگی → AVAILABLE=False / خروجی None → ربات به حالت متنی برمی‌گردد.
"""
import os
import io
import re
import math
import unicodedata

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops
    AVAILABLE = True
except Exception:
    AVAILABLE = False

try:
    from fontTools.ttLib import TTFont
    _FONTTOOLS = True
except Exception:
    _FONTTOOLS = False

if AVAILABLE:

    FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
    FA_MAP = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
    RTL = dict(direction="rtl", language="fa")
    RUN_GAP = 2  # فاصلهٔ بین ران‌ها (متن/ایموجی)

    W_FIX, H_FIX = 1080, 1400
    TITLE = "تالار شکارچیان"
    # v3.19: برند از config — ربات اصلی @fzxbot است (pentesterbot فقط تست است)
    try:
        import config as _lb_cfg
        _brand = str(getattr(_lb_cfg, "BRAND_USERNAME", "fzxbot") or "fzxbot")
    except Exception:
        _brand = "fzxbot"
    FOOTER = "فضول‌گیر — ‎@" + _brand

    POD = [(2, 80, 280, 225), (1, 390, 300, 265), (3, 720, 280, 225)]
    BASE = 540
    ROW_Y0, ROW_H = 596, 86

    # ── پالت سبک 🅰️ (HUD × پاستل — پایه تیره) ──
    PGOLD = (245, 205, 120)   # طلایی پاستلی (VIP)
    PCYAN = (130, 220, 235)   # فیروزه‌ای پاستلی (براکت‌های HUD)
    PLAV = (170, 178, 215)    # لوشه
    MINT = (140, 225, 175)    # ستارهٔ «شما»

    _fcache = {}

    def F(size, weight="Bold"):
        key = (size, weight)
        if key not in _fcache:
            if weight == "Emoji":
                _fcache[key] = ImageFont.truetype(
                    os.path.join(FONT_DIR, "NotoEmoji.ttf"), size)
            else:
                _fcache[key] = ImageFont.truetype(
                    os.path.join(FONT_DIR, "Vazirmatn-%s.ttf" % weight), size)
        return _fcache[key]

    def fa(n):
        return str(n).translate(FA_MAP)

    # ══════════ v3.10.0: موتور نام‌ها — ترنسلیتریشن کامل + جهت پایه ══════════
    # v3.9.3 دو باگ داشت که روی پروداکشن تأیید شد:
    #   A) نویسه‌های بدون گلیف حذف می‌شدند: «🅐🅥🅘🅝»→«بی‌نام»، «ꪑꪮꪊsꫀ»→«s»
    #   B) ران‌ها همیشه راست‌به‌چپ چیده می‌شدند: «Mo🤍on»→«on♡Mo»
    # راه‌حل: anyascii (ترنسلیتریشن همهٔ یونیکد به ASCII) + تشخیص جهت پایهٔ نام.
    try:
        from anyascii import anyascii as _anyascii
        _ANYASCII = True
    except Exception:
        _ANYASCII = False

    _cmaps = {}

    def _cmap_for(path):
        """مجموعهٔ کدپوینت‌های پشتیبانی‌شدهٔ یک فونت (کش می‌شود)."""
        if path not in _cmaps:
            try:
                tt = TTFont(path, fontNumber=0, lazy=True)
                _cmaps[path] = set(tt.getBestCmap().keys())
                tt.close()
            except Exception:
                _cmaps[path] = set()
        return _cmaps[path]

    _VAZIR_PATH = os.path.join(FONT_DIR, "Vazirmatn-Medium.ttf")
    _EMOJI_PATH = os.path.join(FONT_DIR, "NotoEmoji.ttf")
    VAZIR_CMAP = _cmap_for(_VAZIR_PATH) if _FONTTOOLS else None
    EMOJI_CMAP = _cmap_for(_EMOJI_PATH) if (_FONTTOOLS and os.path.exists(_EMOJI_PATH)) else set()
    EMOJI_OK = bool(EMOJI_CMAP)

    _STRIP_CP = (0xFE0E, 0xFE0F, 0x200D)  # انتخاب‌گرهای ظاهر + ZWJ

    # فقط حرکات رایج فارسی/عربی مجاز به ماندن‌اند؛ بقیهٔ Mn (نشانه‌های قرآنی،
    # ویراما/تون‌مارک‌های تزئینی فانتزی) حذف می‌شوند.
    _ARABIC_MN = set(range(0x064B, 0x0660)) | {0x0670}

    # بلوک‌های عتیق/تزئینی که ترنسلیتریشن‌شان به کدهای زباله می‌شود (D13/A306) → حذف
    _DROP_BLOCKS = ((0x10000, 0x1013F),   # Linear B / Aegean
                    (0x10280, 0x102FF),   # Lycian / Carian / OldItalic-adjacent
                    (0x10300, 0x1032F),   # Old Italic
                    (0x10330, 0x1034F),   # Gothic
                    (0x10800, 0x1083F),   # Cypriot Syllabary
                    (0x10600, 0x1077F),   # Linear A / linear-adjacent
                    (0x11A00, 0x11ABF),   # Zanabazar/Soyombo
                    (0x13000, 0x1342F),   # Egyptian Hieroglyphs (𓂃 𓆩 𓆪)
                    (0x1E800, 0x1E8FF))   # Mende Kikakui

    def _in_drop_blocks(cp):
        for a, b in _DROP_BLOCKS:
            if a <= cp <= b:
                return True
        return False

    # نویسه‌های تزئینی پرکاربرد جامعهٔ «نام فانتزی» که یونیکد عادی‌شان معلوم است
    # (تن‌حرف‌های تای‌لِ که به‌جای حروف لاتین مصرف می‌شوند؛
    #  نویسه‌های Mn مثل ꪲꪳ نباید ترنسلیت شوند — فیلتر Mn حذف‌شان می‌کند)
    _ABUSE_MAP = {0x1972: "a", 0x1971: "e", 0x1970: "o", 0x1973: "i",
                  0x1952: "n", 0x1957: "t", 0x1950: "k"}

    # ── v3.19: وایت‌لیست نام لیدربورد (درخواست ادمین) ──
    # فقط اعداد + حروف انگلیسی + حروف فارسی/عربی + نیم‌فاصله + فاصله می‌مانند؛
    # جداکننده‌ها (_ - .) به فاصله تبدیل و تزئینی‌ها/ایموجی‌ها (* @ ⅍ ⭐ …) حذف می‌شوند.
    _NAME_SEP_RE = re.compile(r"[_\-.~=+|/\\]+")
    _NAME_KEEP_RE = re.compile(r"[^0-9A-Za-z\u0600-\u06FF\u200c ]+")

    def nfkc_clean(name):
        """نرمال‌سازی: حروف فانتزی یونیکد → حروف ساده + حذف نویسه‌های کنترلی
        + وایت‌لیست v3.19 (فقط فارسی/انگلیسی/عدد)."""
        s = unicodedata.normalize("NFKC", str(name or ""))
        s = "".join(ch for ch in s if ord(ch) not in _STRIP_CP)
        # نگاشت دستی نویسه‌های «فانتزی‌ساز» — تن‌حرف‌های تای‌لِ که به‌جای صدادار مصرف می‌شوند
        s = s.translate(_ABUSE_MAP)
        # v3.19: جداکننده → فاصله، بقیهٔ نویسه‌های خاص/ایموجی → حذف کامل
        s = _NAME_SEP_RE.sub(" ", s)
        s = _NAME_KEEP_RE.sub("", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _kind(ch):
        """نوع نویسه برای موتور رندر — None یعنی خارج از پوشش دو فونت اصلی."""
        cp = ord(ch)
        if VAZIR_CMAP is not None and cp in VAZIR_CMAP:
            return "text"
        if EMOJI_OK and cp in EMOJI_CMAP:
            return "emoji"
        return None

    def _expand_char(ch):
        """نویسهٔ خارج از پوشش → لیست نویسه‌های جایگزین قابل‌رندر (یا حذف)."""
        cp = ord(ch)
        if unicodedata.category(ch) == "Mn":
            return [ch] if cp in _ARABIC_MN else []
        if _in_drop_blocks(cp):
            return []
        if _ANYASCII:
            try:
                t = _anyascii(ch)
            except Exception:
                t = ""
            if t:
                return [c for c in t]
        return []

    def to_runs(s):
        """رشتهٔ پاک‌شده → ران‌های هم‌فونت [(text, kind)].
        نویسه‌های بدون گلیف: اول ترنسلیتریشن (anyascii)، اگر نشد حذف تمیز."""
        flat = []  # [(ch, kind)]
        for ch in s:
            # علامت ترکیبی خارج از اعراب مجاز → حذف، حتی اگر وزیرمتن گلیف داشته باشد
            # (نویسه‌های تزئینی فانتزی مثل ۫/᜔/᮫ به‌صورت یتیم و رازده دیده می‌شوند)
            if unicodedata.category(ch) == "Mn" and ord(ch) not in _ARABIC_MN:
                continue
            k = _kind(ch)
            if k:
                flat.append((ch, k))
            else:
                for c2 in _expand_char(ch):
                    flat.append((c2, "text"))
        runs = []
        for ch, k in flat:
            if runs and runs[-1][1] == k:
                runs[-1][0] += ch
            else:
                runs.append([ch, k])
        out = []
        for txt, k in runs:
            t = txt.strip()
            if not t:
                continue
            if out:
                out[-1][0] = out[-1][0].rstrip()
            out.append([t, k])
        return [tuple(r) for r in out] or [(u"بی‌نام", "text")]

    def _has_rtl(txt):
        for c in txt:
            o = ord(c)
            if 0x0590 <= o <= 0x08FF or 0xFB1D <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF:
                return True
        return False

    def _base_dir(runs):
        """جهت پایهٔ نام بر اساس اولین نویسهٔ قوی (UAX#9 قاعدهٔ P2) —
        پیش‌فرض rtl (ربات فارسی‌زبان). رفع باگ وارونگی نام‌های لاتین."""
        for txt, k in runs:
            if k != "text":
                continue
            for ch in txt:
                b = unicodedata.bidirectional(ch)
                if b in ("R", "AL"):
                    return "rtl"
                if b == "L":
                    return "ltr"
        return "rtl"

    def runs_width(d, runs, tf, ef):
        w = 0.0
        for i, (txt, k) in enumerate(runs):
            f = tf if k == "text" else ef
            if k == "text" and _has_rtl(txt):
                w += d.textlength(txt, font=f, **RTL)
            else:
                w += d.textlength(txt, font=f)
            if i:
                w += RUN_GAP
        return w

    def sanitize_fit(d, name, maxw, tf, ef):
        """پاک‌سازی + ترنسلیتریشن + برش با «…» — خروجی: ران‌های آمادهٔ ترسیم."""
        s = nfkc_clean(name)
        if not s:
            return [(u"بی‌نام", "text")]
        if runs_width(d, to_runs(s), tf, ef) <= maxw:
            return to_runs(s)
        # برش تدریجی + نشانگر «…» تا خواننده بفهمد نام کامل نمایش داده نشده
        while s:
            s = s[:-1].rstrip()
            if not s:
                break
            cand = to_runs(s + "…")
            if runs_width(d, cand, tf, ef) <= maxw:
                return cand
        return [(u"…", "text")]

    def _draw_runs(d, runs, x_edge, y, tf, ef, fill):
        """ترسیم ران‌ها مطابق جهت پایهٔ نام:
        rtl → از لبهٔ راست به چپ (اولین ران منطقی = راست‌ترین)
        ltr → از لبهٔ چپ به راست (رفع باگ «Mo🤍on» → «on♡Mo»)"""
        if _base_dir(runs) == "rtl":
            x = x_edge
            for txt, k in runs:
                f = tf if k == "text" else ef
                if k == "text" and _has_rtl(txt):
                    w = d.textlength(txt, font=f, **RTL)
                    d.text((x, y), txt, font=f, fill=fill, anchor="rm", **RTL)
                else:
                    w = d.textlength(txt, font=f)
                    d.text((x, y), txt, font=f, fill=fill, anchor="rm")
                x -= w + RUN_GAP
        else:
            x = x_edge - runs_width(d, runs, tf, ef)
            for txt, k in runs:
                f = tf if k == "text" else ef
                if k == "text" and _has_rtl(txt):
                    w = d.textlength(txt, font=f, **RTL)
                    d.text((x + w, y), txt, font=f, fill=fill, anchor="rm", **RTL)
                else:
                    w = d.textlength(txt, font=f)
                    d.text((x, y), txt, font=f, fill=fill, anchor="lm")
                x += w + RUN_GAP

    def draw_name_right(d, runs, x_right, y, tf, ef, fill):
        _draw_runs(d, runs, x_right, y, tf, ef, fill)

    def draw_name_center(d, runs, cx, y, tf, ef, fill):
        total = runs_width(d, runs, tf, ef)
        if _base_dir(runs) == "rtl":
            _draw_runs(d, runs, cx + total / 2.0, y, tf, ef, fill)
        else:
            _draw_runs(d, runs, cx + total / 2.0, y, tf, ef, fill)
    # ══════════ پایان موتور نام‌ها ══════════

    # ---------- افکت‌ها (الگوی اثبات‌شده panel_lib) ----------
    def with_glow(img, painter, blur=12):
        gl = Image.new("RGB", img.size, (0, 0, 0))
        painter(ImageDraw.Draw(gl))
        gl = gl.filter(ImageFilter.GaussianBlur(blur))
        return ImageChops.lighter(img, gl)

    def radial_glow(img, cx, cy, r, color, blur=50, gain=1.0):
        gl = Image.new("RGB", img.size, (0, 0, 0))
        c = tuple(min(255, int(v * gain)) for v in color)
        ImageDraw.Draw(gl).ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
        gl = gl.filter(ImageFilter.GaussianBlur(blur))
        return ImageChops.lighter(img, gl)

    def v_gradient(size, top, bottom):
        w, h = size
        g = Image.new("RGB", (1, h))
        for yy in range(h):
            t = yy / max(1, h - 1)
            g.putpixel((0, yy), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
        return g.resize((w, h))

    # ---------- آیکون‌های برداری (Railway-safe — بدون فونت ایموجی) ----------
    def icon_crown(d, cx, cy, s, color):
        h = s * 0.62
        pts = [(cx - s / 2, cy + h / 2), (cx - s / 2, cy - h * 0.05), (cx - s * 0.25, cy + h * 0.1),
               (cx, cy - h / 2), (cx + s * 0.25, cy + h * 0.1), (cx + s / 2, cy - h * 0.05),
               (cx + s / 2, cy + h / 2)]
        d.polygon(pts, fill=color)
        d.rectangle([cx - s / 2, cy + h / 2, cx + s / 2, cy + h / 2 + h * 0.14], fill=color)
        for dx in (-s * 0.42, 0, s * 0.42):
            r = s * 0.08
            d.ellipse([cx + dx - r, cy - h / 2 - r, cx + dx + r, cy - h / 2 + r], fill=color)

    def icon_star(d, cx, cy, s, color):
        pts = []
        for i in range(10):
            a = math.radians(-90 + i * 36)
            r = s / 2 if i % 2 == 0 else s * 0.21
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        d.polygon(pts, fill=color)

    def diamond(d, cx, cy, r, fill):
        d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=fill)

    def _render(users, subtitle):
        users = list(users)[:10]
        if len(users) < 3:
            return None
        # ارتفاع پویا: با کمتر از ۱۰ کاربر، بوم کوتاه‌تر (بدون فضای خالی)
        n_rows = max(len(users) - 3, 0)
        H = ROW_Y0 + max(n_rows, 1) * ROW_H + 42 + 160
        W = W_FIX

        # ── پس‌زمینه: سرمه‌ای + گرادیان + هاله‌های پاستلی + شبکه ──
        img = Image.new("RGB", (W, H), (8, 12, 26))
        img = ImageChops.lighter(
            img, v_gradient((W, H), (10, 16, 34), (7, 10, 22)).point(lambda p: int(p * 0.95)))
        img = radial_glow(img, 180, 130, 360, (80, 75, 135), blur=100, gain=0.9)
        img = radial_glow(img, W - 150, 380, 300, (45, 105, 125), blur=100, gain=0.8)
        img = radial_glow(img, W / 2, H - 180, 400, (70, 60, 115), blur=110, gain=0.7)
        d = ImageDraw.Draw(img)
        for x in range(0, W, 72):
            d.line([(x, 0), (x, H)], fill=(18, 26, 44), width=1)
        for y in range(0, H, 72):
            d.line([(0, y), (W, y)], fill=(18, 26, 44), width=1)
        # ── قاب HUD: مستطیل نازک + براکت‌های فیروزه‌ای ۴ گوشه ──
        d.rectangle([34, 34, W - 34, H - 34], outline=(105, 105, 155), width=2)
        BL = 46
        for (x, y, dx, dy) in [(44, 44, 1, 1), (W - 44, 44, -1, 1),
                               (44, H - 44, 1, -1), (W - 44, H - 44, -1, -1)]:
            d.line([(x, y), (x + dx * BL, y)], fill=PCYAN, width=4)
            d.line([(x, y), (x, y + dy * BL)], fill=PCYAN, width=4)

        FONTS = dict(
            title=F(62, "Black"), sub=F(30, "Medium"), pod_name=F(32, "Bold"),
            pod_name_e=F(30, "Emoji"), pod_clicks=F(26, "Medium"),
            rank=F(34, "Bold"), name=F(34, "Medium"), name_v=F(34, "Bold"),
            name_e=F(32, "Emoji"), kills=F(30, "Bold"), foot=F(24, "Medium"), chip=F(24, "Bold"),
        )

        # ── سرصفحه + گلو فیروزه‌ای ──
        img = with_glow(img, lambda g: g.text((W / 2, 118), TITLE, font=FONTS["title"],
                                              fill=(70, 145, 165), anchor="mm", **RTL), blur=14)
        d = ImageDraw.Draw(img)
        d.text((W / 2, 118), TITLE, font=FONTS["title"], fill=(230, 245, 250), anchor="mm", **RTL)
        d.text((W / 2, 190), subtitle, font=FONTS["sub"], fill=PLAV, anchor="mm", **RTL)
        diamond(d, W / 2 - 245, 118, 7, (150, 200, 220))
        diamond(d, W / 2 + 245, 118, 7, (150, 200, 220))

        # ── سکوی قهرمانان (۲ — ۱ — ۳) ──
        for rank, px, pw, ph in POD:
            name, cnt, vip, me = users[rank - 1]
            py = BASE - ph
            accent = {1: PGOLD, 2: (180, 185, 215), 3: (235, 165, 120)}[rank]
            # گلو + سایه + کارت
            img = with_glow(img, lambda g, px=px, py=py, pw=pw, ph=ph, a=accent:
                            g.rounded_rectangle([px, py, px + pw, py + ph], radius=24,
                                                outline=a, width=5 if rank == 1 else 3), blur=8)
            d = ImageDraw.Draw(img)
            d.rounded_rectangle([px, py, px + pw, py + ph], radius=24, fill=(16, 24, 44),
                                outline=accent, width=4 if rank == 1 else 2)
            # مدال رتبه در لبهٔ بالا
            cx = px + pw // 2
            d.ellipse([cx - 26, py - 26, cx + 26, py + 26], fill=accent,
                      outline=(8, 12, 26), width=4)
            d.text((cx, py), fa(rank), font=FONTS["rank"], fill=(30, 26, 12), anchor="mm")
            if rank == 1:
                icon_crown(d, cx, py + 64, 44, accent)
            runs_pn = sanitize_fit(d, name, pw - 44, FONTS["pod_name"], FONTS["pod_name_e"])
            ny = py + 108
            draw_name_center(d, runs_pn, cx, ny, FONTS["pod_name"], FONTS["pod_name_e"],
                             (250, 220, 140) if vip else (210, 220, 240))
            if vip:
                d.rounded_rectangle([cx - 29, ny + 30, cx + 29, ny + 62], radius=10,
                                    fill=PGOLD)
                d.text((cx, ny + 45), "VIP", font=FONTS["chip"], fill=(60, 45, 10), anchor="mm")
            d.text((cx, BASE - 30), "%s شکار" % fa(cnt), font=FONTS["pod_clicks"],
                   fill=(140, 150, 180), anchor="mm", **RTL)

        # ── جداکننده ──
        d.line([(70, ROW_Y0 - 26), (W - 70, ROW_Y0 - 26)], fill=(60, 75, 105), width=2)

        # ── فهرست رتبه‌های ۴ به بالا ──
        y = ROW_Y0
        for i in range(4, len(users) + 1):
            name, cnt, vip, me = users[i - 1]
            cy = y + 42
            # پس‌زمینهٔ ردیف: VIP طلایی تیره / عادی بوردر لوشه-بنفش
            if vip:
                d.rounded_rectangle([70, y + 6, W - 70, y + 80], radius=12,
                                    fill=(52, 44, 22))
            else:
                d.rounded_rectangle([70, y + 6, W - 70, y + 80], radius=12,
                                    fill=(13, 19, 36), outline=(66, 80, 115), width=2)
            # رتبه (راست) — دقیقاً وسط کادر: فاصلهٔ مساوی از بالا و پایین
            rank_s = fa(i)
            rw = d.textlength(rank_s, font=FONTS["rank"])
            rx = W - 90
            bb = d.textbbox((0, 0), rank_s, font=FONTS["rank"], anchor="ra")
            gy = (y + 6 + y + 80) / 2 - (bb[1] + bb[3]) / 2
            d.text((rx, gy), rank_s, font=FONTS["rank"],
                   fill=PGOLD if vip else (120, 135, 165), anchor="ra")
            # نام (بعد از رتبه) — موتور چندفونتی + برش نام‌های بلند
            nx = rx - rw - 26
            kills_s = "%s شکار" % fa(cnt)
            kw = d.textlength(kills_s, font=FONTS["kills"], **RTL)
            left_bound = 100 + kw + (80 if vip else 0) + 18
            tfont = FONTS["name_v"] if vip else FONTS["name"]
            maxw_name = max(120, nx - left_bound) - (34 if vip else 0)
            runs_n = sanitize_fit(d, name, maxw_name, tfont, FONTS["name_e"])
            if vip:
                icon_crown(d, nx - 4, cy - 16, 28, PGOLD)
                nx -= 34
            draw_name_right(d, runs_n, nx, cy, tfont, FONTS["name_e"],
                            (250, 220, 140) if vip else (208, 218, 238))
            # چپ: شکار + نشان VIP در «راستِ» شکار
            lx = 100
            d.text((lx, cy), kills_s, font=FONTS["kills"],
                   fill=(150, 220, 240) if vip else (140, 155, 185), anchor="lm", **RTL)
            if vip:
                px_ = lx + kw + 14
                d.rounded_rectangle([px_, cy - 16, px_ + 54, cy + 16], radius=9, fill=PGOLD)
                d.text((px_ + 27, cy), "VIP", font=FONTS["chip"],
                       fill=(60, 45, 10), anchor="mm")
            y += ROW_H
            if i < len(users):
                d.line([(70, y), (W - 70, y)], fill=(30, 40, 62), width=1)

        # ── پانویس (نزدیک آخرین ردیف — بوم هم‌قد محتوا) ──
        d.text((W / 2, ROW_Y0 + max(n_rows, 1) * ROW_H + 42), FOOTER,
               font=FONTS["foot"], fill=(140, 150, 175), anchor="mm", **RTL)

        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()


def render_leaderboard_image(users, subtitle="۱۰ شکارچی برتر هفته"):
    """users = [(name, cnt, is_vip, is_me), ...] حداقل ۳ نفر → بایت‌های PNG یا None"""
    if not AVAILABLE:
        return None
    try:
        return _render(users, subtitle)
    except Exception:
        return None
