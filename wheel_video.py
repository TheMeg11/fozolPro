# -*- coding: utf-8 -*-
"""
wheel_video — خروجی MP4 چرخ شانس (v3.13.0 — روش «A» نهایی‌شده توسط ادمین)
──────────────────────────────────────────────────────────────────────────
ادمین از میان ۴ نمونهٔ ارسالی (A: MP4 / B: GIF HQ / C: APNG / D: WEBP)
روش A را نهایی کرد. این ماژول دقیقاً همان نمونهٔ تأییدشده را تولید می‌کند:

  • همان موتور سینمایی wheel_gif (دی‌سک ابرنمونه، ریم متالیک، گلاس، ذرات)
  • تایم‌لاین ۴۹ فریمی: انتیسپیش → ease-out درجهٔ ۵ (۳۶ فریم) → overshoot → جشن برد
  • خروجی MP4 رنگ کامل (بدون کوانتیزهٔ ۱۲۸ رنگیِ GIF):
    H.264 / yuv420p / crf 18 / preset medium / +faststart / 30fps ثابت
    (هر فریمِ مدت-متغیر تا پایان مدتش در 30fps تکرار می‌شود — دقیقاً مثل نمونهٔ A)

کدگذار با ffmpeg انجام می‌شود؛ جست‌وجو: PATH → imageio-ffmpeg (باندلِ pip).
اگر ffmpeg نبود، render None برمی‌گرداند و main.py به‌طور خودکار سراغ GIF قبلی
(wheel_gif) می‌رود — یعنی رفتار فعلی هرگز خراب نمی‌شود.

API: MP4_AVAILABLE() / render_spin_mp4 / get_spin_mp4 / prewarm_mp4
"""
import math
import os
import shutil
import subprocess
import tempfile
import threading

import wheel_gif

try:
    from PIL import Image  # noqa: F401  (فقط برای چک در دسترس بودن)
    _PIL_OK = True
except Exception:
    _PIL_OK = False

MP4_FPS = 30              # همان نمونهٔ A
CELEBRATE_HOLD_MS = 2600  # نگه‌داشت فریم آخر جشن — همان نمونهٔ A
MAX_MP4_BYTES = 10 * 1024 * 1024  # محافظ: خروجی غیرعادی → None

_ffmpeg_exe = None
_ffmpeg_probed = False
_mp4_cache = {}
_mp4_lock = threading.Lock()


def ffmpeg_exe():
    """مسیر ffmpeg: اول PATH، بعد باندل imageio-ffmpeg؛ نبود → None (یک‌بار پروب)."""
    global _ffmpeg_exe, _ffmpeg_probed
    if _ffmpeg_probed:
        return _ffmpeg_exe
    _ffmpeg_probed = True
    try:
        _exe = shutil.which("ffmpeg")
        if _exe:
            _ffmpeg_exe = _exe
            return _exe
    except Exception:
        pass
    try:
        import imageio_ffmpeg
        _ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        _ffmpeg_exe = None
    return _ffmpeg_exe


def MP4_AVAILABLE():
    return bool(_PIL_OK) and wheel_gif.AVAILABLE and ffmpeg_exe() is not None


def build_timeline(prizes, winner_idx, spins=None, spin_frames=36):
    """تایم‌لاین دقیق نمونهٔ A تأییدشده → (frames[RGBA], durss]) — فرود دقیق روی جایزه.
    v3.16 رفع باگ: wheel_gif.SPINS داخل کلاس تعریف شده بود و در سطح ماژول وجود نداشت
    → import کل ماژول crash می‌شد. حالا با getattr امن خوانده می‌شود."""
    if spins is None:
        spins = getattr(wheel_gif, "SPINS", 3.0)
    n = len(prizes)
    seg = 360.0 / n
    land = (270.0 - (winner_idx + 0.5) * seg) % 360.0
    theta_final = 360.0 * spins + land

    bg = wheel_gif._make_bg()
    tiles, hub, hub_win = wheel_gif._build_tiles(prizes)

    frames, durs = [], []

    def frame(theta, hub_tile=hub, **kw):
        return wheel_gif._frame(theta, bg, tiles, hub_tile, n, **kw)

    def boundaries(a, b):
        return int(math.floor((b - 270.0) / seg) - math.floor((a - 270.0) / seg))

    # فاز ۱: انتیسپیشن
    for theta, du in [(-7.5, 95), (-11.0, 95), (-6.0, 85), (0.0, 80)]:
        frames.append(frame(theta))
        durs.append(du)

    # فاز ۲: چرخش نرم ease-out درجهٔ ۵ (۳۶ فریم — نرم‌تر از GIF)
    prev = 0.0
    for k in range(spin_frames):
        t = (k + 1) / float(spin_frames)
        e = 1.0 - pow(1.0 - t, 5.0)
        theta = theta_final * e
        tick = boundaries(prev, theta) > 0
        frames.append(frame(theta, tick=tick))
        durs.append(60 if k < spin_frames * 0.55 else (85 if k < spin_frames * 0.8 else 120))
        prev = theta

    # فاز ۳: overshoot → فرود دقیق
    for theta, du in [(theta_final + 3.2, 130), (theta_final + 1.2, 120), (theta_final, 150)]:
        frames.append(frame(theta))
        durs.append(du)

    # فاز ۴: جشن برد (ذرات + پالس + نورافکن + 🎉)
    particles = wheel_gif._make_particles()
    for pt, pulse, du in [(0.10, 0.0, 90), (0.45, 0.35, 130), (0.85, 0.65, 170),
                          (1.30, 0.90, 220), (1.85, 1.0, 300), (2.40, 1.0, CELEBRATE_HOLD_MS)]:
        frames.append(frame(theta_final, hub_tile=hub_win, winner_idx=winner_idx,
                            pulse=pulse, particles=particles, pt=pt))
        durs.append(du)

    return frames, durs


def encode_mp4_bytes(frames, durs, fps=MP4_FPS):
    """تایم‌لاین مدت-متغیر → MP4 (H.264 رنگ کامل) → بایت‌ها؛ هرگونه خطا → None."""
    exe = ffmpeg_exe()
    if not exe or not frames:
        return None
    try:
        rgb = [f.convert("RGB") for f in frames]
        w, h = rgb[0].size
        if w % 2 or h % 2:  # yuv420p الزام زوج بودن — در عمل 560×560 زوج است
            rgb = [f.crop((0, 0, w - (w % 2), h - (h % 2))) for f in rgb]
            w, h = rgb[0].size
        out_frames = []
        for f, du in zip(rgb, durs):
            out_frames.extend([f] * max(1, int(round(du / 1000.0 * fps))))

        fd, tmp_out = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        try:
            cmd = [exe, "-y", "-loglevel", "error",
                   "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (w, h),
                   "-r", str(fps), "-i", "-",
                   "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                   "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                   "-f", "mp4", tmp_out]
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for f in out_frames:
                    p.stdin.write(f.tobytes())
                p.stdin.close()
                p.wait(timeout=180)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
                return None
            if p.returncode != 0:
                return None
            with open(tmp_out, "rb") as fh:
                data = fh.read()
        finally:
            try:
                os.remove(tmp_out)
            except Exception:
                pass
        if not data or len(data) > MAX_MP4_BYTES or data[4:8] != b"ftyp":
            return None
        return data
    except Exception:
        return None


def render_spin_mp4(prizes, winner_idx):
    """چرخ می‌سازد که دقیقاً روی prizes[winner_idx] فرود می‌آید → بایت‌های MP4 یا None."""
    if not MP4_AVAILABLE():
        return None
    n = len(prizes)
    if n < 2 or winner_idx < 0 or winner_idx >= n:
        return None
    try:
        frames, durs = build_timeline(prizes, winner_idx)
        return encode_mp4_bytes(frames, durs)
    except Exception:
        return None


def get_spin_mp4(prizes, winner_idx):
    """نسخهٔ کش‌شدهٔ MP4 برای ایندکس جایزه — thread-safe (مثل get_spin_gif).
    v3.24.8: اولین رندر در پروسهٔ فرعی (بدون اشغال GIL ربات)؛ شکست → رندر داخلی."""
    with _mp4_lock:
        if winner_idx not in _mp4_cache:
            data = wheel_gif._render_in_subprocess(prizes, winner_idx, "mp4")
            if not data:
                data = render_spin_mp4(prizes, winner_idx)
            _mp4_cache[winner_idx] = data
        return _mp4_cache[winner_idx]


def prewarm_mp4(prizes):
    """تولید همهٔ MP4ها در استارت — تعداد موفق را برمی‌گرداند."""
    ok = 0
    for i in range(len(prizes)):
        try:
            if get_spin_mp4(prizes, i):
                ok += 1
        except Exception:
            pass
    return ok
