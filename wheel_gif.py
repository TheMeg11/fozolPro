# -*- coding: utf-8 -*-
"""
wheel_gif — انیمیشن GIF چرخ شانس روزانه (v3.10.0 — بازطراحی سینمایی)
──────────────────────────────────────────────────────────────────────
نسخهٔ جدید نسبت به v3.9.4:
  • دیسکِ master با ابرنمونه‌برداری ×۲ (لبه‌های دقیق و نرم پس از کوچک‌سازی)
  • گرادیان رادیال دو-تُنِ هر سگمنت (روشن کنار ریم → عمیق کنار توپ)
  • ریم متالیک طلایی با بندبندی زاویه‌ای + خطوط دورِ تیره/روشن
  • انتیسپیشن (عقب‌کشیدن کوتاه) + ease-out درجهٔ ۵ + فرورفتن و آرام‌گرفتن (overshoot)
  • جشن برد: تیره‌شدن بقیهٔ سگمنت‌ها، روشن‌شدن سگمنت برنده، سه حلقهٔ پالس،
    باران ذرات (ستاره و دایره با فیزیک سادهٔ سقوط) و توپ 🎉
  • گلاسِ استاتیک روی دیسک (نور بالای صفحه نمی‌چرخد — حس شیشه)
  • تیکِ نشانگر: هنگام عبور مرز سگمنت‌ها، نشانگر می‌پرد و قوسِ نور می‌گیرد
برچسب‌ها همیشه قابت و همراه سگمنت‌ها مدار می‌زنند؛ کوانتیزه با پالت مشترک.
API بدون تغییر: get_spin_gif / prewarm / selftest / AVAILABLE
"""
import io
import math
import os
import threading

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops
    AVAILABLE = True
except Exception:
    AVAILABLE = False

if AVAILABLE:

    FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
    FA_MAP = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
    RTL = dict(direction="rtl", language="fa")

    _LANCZOS = getattr(Image, "LANCZOS", None) or getattr(Image, "BICUBIC")
    _BICUBIC = getattr(Image, "BICUBIC", None) or Image.LANCZOS

    # ── هندسه ──
    SIZE = 560
    CX = CY = SIZE // 2
    R_RIM = 218          # شعاع بیرونی سگمنت‌ها
    R_RIM_RING = 234     # شعاع میانی ریم متالیک
    HUB_R = 62           # توپی مرکز
    SPINS = 3.0
    SS = 2               # ضریب ابرنمونه‌برداری دیسک

    # ── پالت (هم‌سبک تالار شکارچیان: سرمه‌ای HUD × پاستل) ──
    BG = (8, 12, 26)
    PGOLD = (245, 205, 120)
    ACCENTS = [
        (245, 205, 120),  # طلایی پاستلی
        (130, 220, 235),  # فیروزه‌ای
        (140, 225, 175),  # نعنایی
        (170, 178, 215),  # لوشه
        (235, 165, 120),  # هلویی
        (235, 150, 175),  # صورتی
        (200, 160, 230),  # یاسی
        (150, 190, 240),  # آبی آسمانی
    ]
    _CONFETTI = [(245, 205, 120), (130, 220, 235), (140, 225, 175),
                 (235, 150, 175), (200, 160, 230), (255, 255, 255)]

    XP_ICONS = ["⭐", "🍀", "🎯", "⚡", "💎", "🎁"]

    _fcache = {}
    _gif_cache = {}
    _cache_lock = threading.Lock()

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

    def blend(c1, c2, t):
        """t=1 → c1، t=0 → c2"""
        return tuple(int(round(c1[k] * t + c2[k] * (1 - t))) for k in range(3))

    def _icon_for(prize, i):
        if prize.get("type") == "vip":
            return "🏆" if int(prize.get("value", 0)) >= 3 else "👑"
        return XP_ICONS[i % len(XP_ICONS)]

    def _label_for(prize):
        if prize.get("type") == "vip":
            return "VIP " + fa(prize["value"])
        return fa(prize["value"])

    # ══════════ پس‌زمینهٔ ثابت HUD ══════════
    _bg_cache = None

    def _make_bg():
        global _bg_cache
        if _bg_cache is not None:
            return _bg_cache
        base = Image.new("RGB", (SIZE, SIZE), BG)
        ov = Image.new("RGB", (SIZE, SIZE), BG)
        d = ImageDraw.Draw(ov)
        d.ellipse([CX - 215, CY - 215, CX + 215, CY + 215], fill=(17, 23, 46))
        d.ellipse([40, 20, 220, 200], fill=(15, 19, 40))
        d.ellipse([SIZE - 225, SIZE - 245, SIZE - 45, SIZE - 65], fill=(14, 21, 42))
        ov = ov.filter(ImageFilter.GaussianBlur(60))
        base = ImageChops.lighter(base, ov)
        d = ImageDraw.Draw(base)
        for x in range(0, SIZE, 56):
            d.line([(x, 0), (x, SIZE)], fill=(15, 21, 38), width=1)
        for y in range(0, SIZE, 56):
            d.line([(0, y), (SIZE, y)], fill=(15, 21, 38), width=1)
        # براکت‌های HUD گوشه‌ها — امضای بصری ربات
        BL = 44
        for (x, y, dx, dy) in [(20, 20, 1, 1), (SIZE - 20, 20, -1, 1),
                               (20, SIZE - 20, 1, -1), (SIZE - 20, SIZE - 20, -1, -1)]:
            d.line([(x, y), (x + dx * BL, y)], fill=(90, 190, 210), width=4)
            d.line([(x, y), (x, y + dy * BL)], fill=(90, 190, 210), width=4)
        _bg_cache = base
        return base

    # ══════════ دیسکِ master (یک‌بار ساخته می‌شود — ابرنمونه ×۲) ══════════
    _master_cache = {}
    _master_small = {}

    def _make_master(n_seg):
        """دیسک چرخ با گرادیان رادیال سگمنت‌ها + ریم متالیک — RGBA در ابعاد ×SS.
        زاویه‌ها هم‌قراردادِ pieslice (صفر = ساعت ۳، جهت مثبت = ساعت‌گرد) تا
        با مدارِ برچسب‌ها و محاسبهٔ land یکی باشد.
        ترتیب لایه‌ها: ریم متالیک (حلقهٔ بیرونی) → سگمنت‌ها داخل ریم → جداکننده → سایه‌ها."""
        if n_seg in _master_cache:
            return _master_cache[n_seg]
        M = SIZE * SS
        mcx = mcy = M // 2
        r_rim = R_RIM * SS            # لبهٔ بیرونی سگمنت‌ها = لبهٔ داخلی ریم
        r_ring_o = R_RIM_RING * SS    # لبهٔ بیرونی ریم متالیک
        hub = HUB_R * SS
        seg = 360.0 / n_seg

        img = Image.new("RGBA", (M, M), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        # ── ۱) ریم متالیک طلایی (بندبندی زاویه‌ای — نور از بالا-چپ) ──
        for k in range(48):
            a0 = k * 7.5 - 90
            a1 = a0 + 7.5
            t = 0.5 - 0.5 * math.cos(math.radians(a0 + 45))  # ۰..۱
            c = blend(blend((255, 244, 214), PGOLD, t), (120, 90, 40), 0.22)
            d.pieslice([mcx - r_ring_o, mcy - r_ring_o, mcx + r_ring_o, mcy + r_ring_o],
                       a0, a1, fill=c + (255,))
        # سوراخ داخلی ریم — فقط داخل R_RIM خالی می‌شود تا حلقهٔ ریم بماند
        d.ellipse([mcx - r_rim, mcy - r_rim, mcx + r_rim, mcy + r_rim],
                  fill=(0, 0, 0, 0))
        # خطوط لبهٔ ریم
        d.ellipse([mcx - r_rim, mcy - r_rim, mcx + r_rim, mcy + r_rim],
                  outline=(250, 230, 170, 255), width=2 * SS)
        d.ellipse([mcx - r_ring_o, mcy - r_ring_o, mcx + r_ring_o, mcy + r_ring_o],
                  outline=(15, 20, 40, 255), width=2 * SS)

        # ── ۲) سگمنت‌ها داخل ریم: آهنگ دو-تُن شعاعی (۱۲ بند) ──
        for i in range(n_seg):
            acc = ACCENTS[i % len(ACCENTS)]
            light = blend(acc, (255, 255, 255), 0.34)
            dark = blend(acc, (10, 14, 30), 0.62)
            mask = Image.new("L", (M, M), 0)
            md = ImageDraw.Draw(mask)
            md.pieslice([mcx - r_rim, mcy - r_rim, mcx + r_rim, mcy + r_rim],
                        i * seg, (i + 1) * seg, fill=255)
            band = Image.new("RGB", (M, M), dark)
            bd = ImageDraw.Draw(band)
            for k in range(12):
                t1 = (k + 1) / 12.0
                c = blend(light, dark, 1.0 - t1)
                bd.pieslice([mcx - r_rim * t1, mcy - r_rim * t1,
                             mcx + r_rim * t1, mcy + r_rim * t1],
                            0, 360, fill=c)
            img.paste(band, (0, 0), mask)

        # ── ۳) جداکننده‌های تیره بین سگمنت‌ها ──
        d = ImageDraw.Draw(img)
        for i in range(n_seg):
            a = math.radians(i * seg)
            d.line([(mcx, mcy),
                    (mcx + r_rim * math.cos(a), mcy + r_rim * math.sin(a))],
                   fill=(10, 14, 30, 255), width=3 * SS)

        # ── ۴) سایهٔ حلقه‌ای کنار ریم + سایهٔ توپ (عمق) ──
        sh = Image.new("RGBA", (M, M), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        sd.ellipse([mcx - r_rim, mcy - r_rim, mcx + r_rim, mcy + r_rim],
                   outline=(0, 0, 0, 90), width=6 * SS)
        sh = sh.filter(ImageFilter.GaussianBlur(3 * SS))
        img = Image.alpha_composite(img, sh)

        sh2 = Image.new("RGBA", (M, M), (0, 0, 0, 0))
        s2 = ImageDraw.Draw(sh2)
        s2.ellipse([mcx - hub - 26 * SS, mcy - hub - 26 * SS,
                    mcx + hub + 26 * SS, mcy + hub + 26 * SS],
                   fill=(0, 0, 0, 70))
        sh2 = sh2.filter(ImageFilter.GaussianBlur(8 * SS))
        img = Image.alpha_composite(img, sh2)

        # نسخهٔ کوچک‌شدهٔ از-پیش-آماده برای چرخش سریع در فریم‌ها (بدون افت محسوس)
        _master_cache[n_seg] = img
        _master_small[n_seg] = img.resize((SIZE, SIZE), _LANCZOS)
        return img

    def _master_for_spin(n_seg):
        """نسخهٔ آمادهٔ چرخش — کوچک‌شده به ابعاد خروجی (چرخش ارزان)."""
        if n_seg not in _master_small:
            _make_master(n_seg)
        return _master_small[n_seg]

    # گلاسِ استاتیک (نورِ بالای قاب — بعد از چرخش دیسک می‌نشیند)
    _gloss_cache = None

    def _make_gloss():
        global _gloss_cache
        if _gloss_cache is not None:
            return _gloss_cache
        g = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        gd = ImageDraw.Draw(g)
        for k in range(10):
            t0 = k / 10.0
            a = int(26 * (1.0 - t0))
            y0 = (CY - R_RIM) + (2 * R_RIM) * t0 * 0.55
            y1 = (CY - R_RIM) + (2 * R_RIM) * ((k + 1) / 10.0) * 0.55
            gd.rectangle([CX - R_RIM, y0, CX + R_RIM, y1], fill=(255, 255, 255, a))
        # برش دایره‌ای
        mask = Image.new("L", (SIZE, SIZE), 0)
        ImageDraw.Draw(mask).ellipse([CX - R_RIM, CY - R_RIM, CX + R_RIM, CY + R_RIM],
                                     fill=255)
        g.putalpha(Image.composite(g.split()[3], Image.new("L", (SIZE, SIZE), 0), mask))
        _gloss_cache = g
        return g

    # ══════════ برچسب‌ها و آیکون‌ها ══════════
    def _text_tile(txt, font, fill, pad=10):
        tmp = Image.new("RGBA", (8, 8))
        td = ImageDraw.Draw(tmp)
        try:
            bb = td.textbbox((0, 0), txt, font=font, **RTL)
        except Exception:
            bb = td.textbbox((0, 0), txt, font=font)
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        tile = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
        d = ImageDraw.Draw(tile)
        try:
            d.text((pad - bb[0] + 2, pad - bb[1] + 2), txt, font=font, fill=(5, 8, 18), **RTL)
            d.text((pad - bb[0], pad - bb[1]), txt, font=font, fill=fill, **RTL)
        except Exception:
            d.text((pad - bb[0] + 2, pad - bb[1] + 2), txt, font=font, fill=(5, 8, 18))
            d.text((pad - bb[0], pad - bb[1]), txt, font=font, fill=fill)
        return tile

    def _build_tiles(prizes):
        tiles = []
        for i, p in enumerate(prizes):
            acc = ACCENTS[i % len(ACCENTS)]
            if p.get("type") == "vip":
                lt = _text_tile(_label_for(p), F(26, "Black"), blend(acc, (255, 255, 255), 0.18))
            else:
                lt = _text_tile(_label_for(p), F(36, "Black"), blend(acc, (255, 255, 255), 0.18))
            it = _text_tile(_icon_for(p, i), F(38, "Emoji"), blend(acc, (255, 255, 255), 0.22), pad=6)
            tiles.append((lt, it))
        hub = _text_tile("🎡", F(56, "Emoji"), (235, 240, 250), pad=6)
        hub_win = _text_tile("🎉", F(56, "Emoji"), (235, 240, 250), pad=6)
        return tiles, hub, hub_win

    # ══════════ ذرات جشن برد ══════════
    def _make_particles(seed_n=46):
        import random
        rnd = random.Random(20250901)
        parts = []
        for i in range(seed_n):
            ang = rnd.uniform(0, 2 * math.pi)
            speed = rnd.uniform(2.2, 7.5)
            parts.append({
                "x": float(CX), "y": float(CY - 10),
                "vx": math.cos(ang) * speed,
                "vy": math.sin(ang) * speed - 2.2,
                "c": _CONFETTI[rnd.randrange(len(_CONFETTI))],
                "s": rnd.uniform(2.0, 4.6),
                "star": rnd.random() < 0.4,
                "rot": rnd.uniform(0, math.pi),
            })
        return parts

    def _draw_particle(d, p, t):
        x = p["x"] + p["vx"] * t
        y = p["y"] + p["vy"] * t + 26.0 * t * t  # گرانش
        fade = max(0.0, 1.0 - t / 2.6)
        if fade <= 0.02 or x < 6 or x > SIZE - 6 or y > SIZE - 6:
            return
        col = blend(p["c"], BG, 1.0 - fade)
        s = p["s"]
        if p["star"]:
            a = p["rot"] + t * 2.2
            pts = []
            for i in range(8):
                aa = a + i * math.pi / 4
                rr = s * (1.9 if i % 2 == 0 else 0.75)
                pts.append((x + rr * math.cos(aa), y + rr * math.sin(aa)))
            d.polygon(pts, fill=col)
        else:
            d.ellipse([x - s, y - s, x + s, y + s], fill=col)

    # ══════════ رندر یک فریم ══════════
    def _frame(theta, bg, tiles, hub_tile, prizes_n, winner_idx=None,
               pulse=0.0, particles=None, pt=0.0, tick=False):
        img = bg.convert("RGBA")
        seg = 360.0 / prizes_n

        # دیسک: چرخش نسخهٔ کوچک‌شدهٔ master (ارزان و نرم) → ترکیب با پس‌زمینه
        master = _master_for_spin(prizes_n)
        rot = master.rotate(-theta, resample=_BICUBIC)
        img = Image.alpha_composite(img, rot)

        # گلاس استاتیک
        img = Image.alpha_composite(img, _make_gloss())

        d = ImageDraw.Draw(img)

        # حالت برد: تیره‌کردن بقیه + روشن‌کردن سگمنت برنده
        if winner_idx is not None:
            ov = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
            od = ImageDraw.Draw(ov)
            for i in range(prizes_n):
                if i == winner_idx:
                    continue
                od.pieslice([CX - R_RIM, CY - R_RIM, CX + R_RIM, CY + R_RIM],
                            i * seg + theta, (i + 1) * seg + theta,
                            fill=(6, 8, 20, 120))
            img = Image.alpha_composite(img, ov)
            d = ImageDraw.Draw(img)
            wd = ImageDraw.Draw(img)
            wd.pieslice([CX - R_RIM, CY - R_RIM, CX + R_RIM, CY + R_RIM],
                        winner_idx * seg + theta, (winner_idx + 1) * seg + theta,
                        fill=(255, 255, 255, 36))

        # برچسب + آیکون هر سگمنت (قائم، مدارِ هم‌زمان با چرخش)
        for i in range(prizes_n):
            a = math.radians((i + 0.5) * seg + theta)
            lt, it = tiles[i]
            r_lab = 112 if i % 2 == 0 else 148
            lx = CX + r_lab * math.cos(a)
            ly = CY + r_lab * math.sin(a)
            img.paste(lt, (int(lx - lt.width / 2), int(ly - lt.height / 2)), lt)
            ix = CX + 191 * math.cos(a)
            iy = CY + 191 * math.sin(a)
            img.paste(it, (int(ix - it.width / 2), int(iy - it.height / 2)), it)

        d = ImageDraw.Draw(img)

        # حلقه‌های پالس برد
        if winner_idx is not None and pulse > 0:
            acc = ACCENTS[winner_idx % len(ACCENTS)]
            for j in range(3):
                pr = R_RIM_RING + 8 + j * 16 + 26 * pulse
                wdt = max(1, int(5 * (1 - pulse)) + 1)
                d.ellipse([CX - pr, CY - pr, CX + pr, CY + pr],
                          outline=blend(acc, (255, 255, 255), 0.3), width=wdt)

        # توپی مرکزی متالیک
        d.ellipse([CX - HUB_R - 8, CY - HUB_R - 8, CX + HUB_R + 8, CY + HUB_R + 8],
                  fill=(30, 26, 16), outline=(90, 74, 40), width=2)
        d.ellipse([CX - HUB_R, CY - HUB_R, CX + HUB_R, CY + HUB_R],
                  fill=(16, 22, 44), outline=(210, 180, 110), width=3)
        img.paste(hub_tile, (int(CX - hub_tile.width / 2), int(CY - hub_tile.height / 2)),
                  hub_tile)

        # ذرات جشن
        if particles is not None and pt > 0:
            pd = ImageDraw.Draw(img)
            for p in particles:
                _draw_particle(pd, p, pt)

        # نشانگر طلایی با تیکِ عبور از مرز سگمنت
        _pointer(ImageDraw.Draw(img), tick)
        return img

    def _pointer(d, tick=False):
        dy = 6 if tick else 0
        col = (255, 235, 170) if tick else PGOLD
        d.polygon([(CX - 19, 14 + dy), (CX + 19, 14 + dy), (CX, 56 + dy)],
                  fill=col, outline=(6, 9, 20))
        d.line([(CX - 19, 14 + dy), (CX, 56 + dy)], fill=(255, 245, 215), width=2)

    # ══════════ خروجی GIF ══════════
    def render_spin_gif(prizes, winner_idx, spins=SPINS):
        """چرخ می‌سازد که دقیقاً روی prizes[winner_idx] می‌ایستد → بایت‌های GIF یا None"""
        if not AVAILABLE:
            return None
        n = len(prizes)
        if n < 2 or winner_idx < 0 or winner_idx >= n:
            return None
        seg = 360.0 / n
        land = (270.0 - (winner_idx + 0.5) * seg) % 360.0   # نوک نشانگر بالای چرخ
        theta_final = 360.0 * spins + land

        bg = _make_bg()
        tiles, hub, hub_win = _build_tiles(prizes)

        frames = []
        durs = []

        def _boundaries_passed(a, b):
            """تعداد مرز سگمنتی که بین زاویهٔ a و b (a<b، ساعت‌گرد) از زیر نشانگر (۲۷۰°) رد شده"""
            import math as _m
            fa_ = _m.floor((a - 270.0) / seg)
            fb_ = _m.floor((b - 270.0) / seg)
            return int(fb_ - fa_)

        # ── فاز ۱: انتیسپیشن (عقب‌کشیدن کوتاه) ──
        for theta, du in [(-7.5, 95), (-11.0, 95), (-6.0, 85), (0.0, 80)]:
            frames.append(_frame(theta, bg, tiles, hub, n))
            durs.append(du)

        # ── فاز ۲: چرخش ease-out درجه ۵ ──
        NF = 30
        prev = 0.0
        for k in range(NF):
            t = (k + 1) / float(NF)
            e = 1.0 - pow(1.0 - t, 5.0)
            theta = theta_final * e
            tick = _boundaries_passed(prev, theta) > 0
            frames.append(_frame(theta, bg, tiles, hub, n, tick=tick))
            if k < 12:
                durs.append(50)
            elif k < 20:
                durs.append(75)
            elif k < 27:
                durs.append(110)
            else:
                durs.append(150)
            prev = theta

        # ── فاز ۳: فرورفتن و آرام‌گرفتن (overshoot → نقطهٔ دقیق) ──
        for theta, du in [(theta_final + 3.2, 130), (theta_final + 1.2, 120),
                          (theta_final, 150)]:
            frames.append(_frame(theta, bg, tiles, hub, n))
            durs.append(du)

        # ── فاز ۴: جشن برد (تیره/روشن + پالس + ذرات + 🎉) ──
        particles = _make_particles()
        for pt, pulse, du in [(0.10, 0.0, 90), (0.45, 0.35, 150), (0.85, 0.65, 210),
                              (1.30, 0.90, 280), (1.85, 1.0, 360), (2.40, 1.0, 5400)]:
            f = _frame(theta_final, bg, tiles, hub_win, n,
                       winner_idx=winner_idx, pulse=pulse,
                       particles=particles, pt=pt)
            frames.append(f)
            durs.append(du)

        # کوانتیزه با پالت مشترک (بدون سوسو)
        rgb = [f.convert("RGB") for f in frames]
        try:
            pal = rgb[len(rgb) // 2].quantize(colors=128, method=Image.MEDIANCUT)
        except Exception:
            pal = rgb[len(rgb) // 2].quantize(colors=128)
        try:
            qs = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in rgb]
        except Exception:
            qs = [f.quantize(palette=pal) for f in rgb]

        buf = io.BytesIO()
        qs[0].save(buf, format="GIF", save_all=True, append_images=qs[1:],
                   duration=durs, loop=0, optimize=False, disposal=1)
        return buf.getvalue()

    def get_spin_gif(prizes, winner_idx):
        """نسخهٔ کش‌شدهٔ GIF برای ایندکس جایزه — thread-safe
        v3.24.8: اولین رندر در پروسهٔ فرعی (بدون اشغال GIL ربات)؛ شکست → رندر داخلی."""
        with _cache_lock:
            if winner_idx not in _gif_cache:
                data = _render_in_subprocess(prizes, winner_idx, "gif")
                if not data:
                    data = render_spin_gif(prizes, winner_idx)
                _gif_cache[winner_idx] = data
            return _gif_cache[winner_idx]

    def prewarm(prizes):
        """تولید همهٔ GIFها در استارت — تعداد موفق را برمی‌گرداند"""
        ok = 0
        for i in range(len(prizes)):
            try:
                if get_spin_gif(prizes, i):
                    ok += 1
            except Exception:
                pass
        return ok

    def selftest(prizes):
        """برای لاگ استارت — «OK(n KB)» یا «FAILED»"""
        try:
            b = render_spin_gif(prizes, min(2, len(prizes) - 1))
            return "OK(%dKB)" % (len(b) // 1024) if b else "FAILED"
        except Exception:
            return "FAILED"

# ====== v3.24.8: رندر در پروسهٔ فرعی — دور نگه‌داشتن GIL از ربات ======
# ریشهٔ دُم کند ۱۵–۳۰ ثانیه‌ای در گزارش /usage: رندر PIL (فریم‌سازی خالص پایتونی)
# GIL را برای ثانیه‌ها اشغال می‌کند و همهٔ هندلرهای وب‌هوک همان بازه معطل می‌مانند.
# راه‌حل: اولین رندر هر ایندکس در پروسهٔ فرعی جدا (python -c — اصلی را دوباره import نمی‌کند)؛
# خروجی به والد برمی‌گردد و مثل قبل کش می‌شود. شکست → fallback به رندر داخلی (رفتار قبلی).
def _render_in_subprocess(prizes, winner_idx, kind="gif", timeout_s=120):
    """رندر GIF/MP4 در پروسهٔ فرعی. خروجی: بایت‌ها یا None.
    prizes باید JSON-serializable باشد (WHEEL_PRIZES هست)."""
    import json, subprocess, sys, tempfile
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        payload = json.dumps({"p": prizes, "i": int(winner_idx)}, ensure_ascii=False)
    except Exception:
        return None
    in_path = out_path = None
    try:
        fd, in_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        out_path = in_path + ".out"
        if kind == "mp4":
            body = "import wheel_video as w;r=w.render_spin_mp4(d['p'],d['i'])"
        else:
            body = "import wheel_gif as w;r=w.render_spin_gif(d['p'],d['i'])"
        code = (
            "import json,sys;"
            f"sys.path.insert(0,{here!r});"
            "d=json.load(open(sys.argv[1],encoding='utf-8'));"
            f"{body};"
            "open(sys.argv[2],'wb').write(r or b'')"
        )
        subprocess.run(
            [sys.executable, "-c", code, in_path, out_path],
            cwd=here, timeout=timeout_s,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False)
        if os.path.exists(out_path):
            with open(out_path, "rb") as fh:
                data = fh.read()
            return data or None
        return None
    except Exception:
        return None
    finally:
        for _pth in (in_path, out_path):
            try:
                if _pth and os.path.exists(_pth):
                    os.remove(_pth)
            except Exception:
                pass
