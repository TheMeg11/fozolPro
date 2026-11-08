"""bot_wheel_media.py — رسانهٔ چرخ شانس (MP4/GIF) + ساسپنس تایپ‌رایتر (v4.7).

زنجیرهٔ ارسال جایزهٔ چرخ: file_id هاردکد config → کش → رندر MP4 → GIF → متن.
اشیاء ربات از طریق _bind(globals()) تزریق می‌شوند."""
from __future__ import annotations

import datetime
import io
import logging
import threading
import time

import config
import wheel_gif
import wheel_video

logger = logging.getLogger("bot_wheel_media")
# ─── اشیاء تزریق‌شده از main.py در زمان import (الگوی bind — کد منتقل‌شده دست‌نخورده) ───
_BIND_KEYS = ['bot', 'db', 'texts', 'types', 'logger', 'WHEEL_PRIZES', 'to_persian_digits', 'to_persian_int', 'safe_edit_text']


def _bind(ns: dict) -> None:
    """تزریق اشیاء runtime از globals() ربات (bot, db, texts, WHEEL_PRIZES, ...)."""
    for _k in _BIND_KEYS:
        if _k in ns:
            globals()[_k] = ns[_k]


_wheel_fid_cache = {}      # کش درون-پردازه‌ای file_id MP4 (فقط برای رندرهای جدید)
_wheel_gif_fid_cache = {}  # کش درون-پردازه‌ای file_id GIF فالبک

# ====== v3.13.1: فایل آی‌دی‌های هاردکد config — ثابت و جاودان، بدون رندر/آپلود ======
# با تغییر موتور رندر چرخ، WHEEL_ENGINE_VERSION را بالا ببرید و file_idهای جدید
# را در config.py (WHEEL_MEDIA_VERSION همان عدد) به‌روز کنید.
WHEEL_ENGINE_VERSION = "3.13.1"
_cfg_wver = str(getattr(config, "WHEEL_MEDIA_VERSION", "") or "")
if _cfg_wver == WHEEL_ENGINE_VERSION:
    WHEEL_MP4_FILE_IDS = {int(k): v for k, v in dict(
        getattr(config, "WHEEL_MP4_FILE_IDS", {}) or {}).items()}
    WHEEL_GIF_FILE_IDS = {int(k): v for k, v in dict(
        getattr(config, "WHEEL_GIF_FILE_IDS", {}) or {}).items()}
    print("🎡 WHEEL MEDIA: %d MP4 + %d GIF file_id از config (نسخهٔ %s) بارگذاری شد" % (
        len(WHEEL_MP4_FILE_IDS), len(WHEEL_GIF_FILE_IDS), _cfg_wver), flush=True)
else:
    WHEEL_MP4_FILE_IDS = {}
    WHEEL_GIF_FILE_IDS = {}
    print("🎡 WHEEL MEDIA: هاردکد config معتبر نیست (نسخهٔ %r ≠ %s) — رندر در استارت" % (
        _cfg_wver, WHEEL_ENGINE_VERSION), flush=True)


def _wheel_prewarm_job():
    """v3.13.1: با file_idهای هاردکد config هیچ رندر/آپلودی لازم نیست؛
    فقط ایندکس‌های فاقد file_id در استارت رندر می‌شوند."""
    try:
        _n = len(WHEEL_PRIZES)
        if len(WHEEL_MP4_FILE_IDS) >= _n and len(WHEEL_GIF_FILE_IDS) >= _n:
            print("🎡 WHEEL SELFTEST: prewarm=CONFIG %d/%d (0ms) — بدون رندر/آپلود" % (_n, _n),
                  flush=True)
            return
        if wheel_video and wheel_gif and wheel_gif.AVAILABLE and wheel_video.MP4_AVAILABLE():
            _t0 = time.time()
            _missing = [i for i in range(_n) if i not in WHEEL_MP4_FILE_IDS]
            for _i in _missing:
                try:
                    wheel_video.get_spin_mp4(WHEEL_PRIZES, _i)
                except Exception:
                    pass
            print("🎡 WHEEL SELFTEST: prewarm=MP4 %d/%d (%dms) [بدون config: %s]" % (
                _n - len(_missing), _n, int((time.time() - _t0) * 1000), _missing), flush=True)
            return
        print("🎡 WHEEL SELFTEST: MP4 در دسترس نیست — چرخ با GIF", flush=True)
        if wheel_gif and wheel_gif.AVAILABLE:
            _t1 = time.time()
            _okg = wheel_gif.prewarm(WHEEL_PRIZES)
            print("🎡 WHEEL SELFTEST: prewarm=GIF %d/%d (%dms)" % (
                _okg, _n, int((time.time() - _t1) * 1000)), flush=True)
        else:
            print("🎡 WHEEL SELFTEST: wheel_gif در دسترس نیست (Pillow نیست)", flush=True)
    except Exception as _wp_err:
        print("🎡 WHEEL SELFTEST FAILED: %s" % _wp_err, flush=True)


# ====== v3.14: ساسپنس چرخ — تایپ‌رایتر کاراکتربه‌کاراکتر + مکث دراماتیک + برد ======
_wheel_type_locks = {}
_wheel_type_locks_guard = threading.Lock()

def _wheel_type_lock(chat_id):
    """هر چت حداکثر یک تایپ‌رایتر فعال — جلوگیری از تداخل ادیت‌های هم‌زمان."""
    with _wheel_type_locks_guard:
        if chat_id not in _wheel_type_locks:
            _wheel_type_locks[chat_id] = threading.Lock()
        return _wheel_type_locks[chat_id]

def _wheel_send_prize_media(chat_id, widx, result_text, markup):
    """v3.14: زنجیرهٔ ارسال رسانهٔ چرخ — استخراج‌شده از هندلر:
    ۱) MP4 هاردکد config  ۲) کش درون‌پردازه‌ای  ۳) رندر MP4  ۴) GIF هاردکد/کش/رندر  ۵) متن"""
    sent = False
    try:
        # اولویت ۱: file_id هاردکد config (ثابت و جاودان — صفر رندر/آپلود) یا کش
        _fid = WHEEL_MP4_FILE_IDS.get(widx) or _wheel_fid_cache.get(widx)
        if _fid:
            try:
                bot.send_animation(chat_id, _fid, caption=result_text, reply_markup=markup)
                return
            except Exception as _wf_err:
                logger.warning("wheel mp4 file_id stale: %s", _wf_err)
        # اولویت ۲: رندر و آپلود MP4 (فقط وقتی file_id نداشتیم)
        if (not sent and wheel_video and wheel_gif
                and wheel_gif.AVAILABLE and wheel_video.MP4_AVAILABLE()):
            _vid = wheel_video.get_spin_mp4(WHEEL_PRIZES, widx)
            if _vid:
                _bio = io.BytesIO(_vid)
                _bio.name = "wheel.mp4"
                _msg_w = bot.send_animation(chat_id, _bio, caption=result_text, reply_markup=markup)
                sent = True
                try:
                    _wheel_fid_cache[widx] = _msg_w.animation.file_id
                except Exception:
                    pass
                return
        # اولویت ۳: فالبک GIF — config → کش → رندر
        if not sent and wheel_gif and wheel_gif.AVAILABLE:
            _gfid = WHEEL_GIF_FILE_IDS.get(widx) or _wheel_gif_fid_cache.get(widx)
            if _gfid:
                try:
                    bot.send_animation(chat_id, _gfid, caption=result_text, reply_markup=markup)
                    return
                except Exception as _wg_err:
                    logger.warning("wheel gif file_id stale: %s", _wg_err)
            _gif = wheel_gif.get_spin_gif(WHEEL_PRIZES, widx)
            if _gif:
                _bio = io.BytesIO(_gif)
                _bio.name = "wheel.gif"
                _msg_w = bot.send_animation(chat_id, _bio, caption=result_text, reply_markup=markup)
                sent = True
                try:
                    _wheel_gif_fid_cache[widx] = _msg_w.animation.file_id
                except Exception:
                    pass
                return
    except Exception as _w_err:
        logger.warning("wheel animation failed: %s", _w_err)
    if not sent:
        # فالبک: نتیجهٔ فوری و تمیز (بدون انیمیشن)
        try:
            bot.send_message(chat_id, "🎡 " + result_text, reply_markup=markup)
        except Exception as _tx_err:
            logger.warning("wheel text fallback failed: %s", _tx_err)

def _wheel_suspense_send(chat_id, widx, result_text, prize_type, markup):
    """v3.14: نمایش سینمایی چرخ — همه‌چیز در نخ پس‌زمینه تا هندلر بلاک نشود:
    (۱) پیام تایپ‌شوندهٔ کاراکتربه‌کاراکتر (۲) مکث دراماتیک (۳) اعلام برد
    (۴) ارسال MP4/GIF جایزه + توضیحات."""
    lk = _wheel_type_lock(chat_id)
    if not lk.acquire(timeout=0.5):
        # تایپ‌رایتر قبلی هنوز فعال — بدون ساسپنس، مستقیم نتیجه
        _wheel_send_prize_media(chat_id, widx, result_text, markup)
        return
    try:
        full = texts.WHEEL_SUSPENSE
        msg_id = None
        shown = 0
        step = 9        # کاراکتر در هر ادیت
        delay = 0.30    # ثانیه بین ادیت‌ها (~۳ ادیت/ثانیه — امن برای rate-limit)
        # ── فاز ۱: تایپ کاراکتربه‌کاراکتر ──
        while shown < len(full):
            shown = min(len(full), shown + step)
            piece = full[:shown]
            try:
                if msg_id is None:
                    msg_id = bot.send_message(chat_id, piece).message_id
                else:
                    safe_edit_text(piece, chat_id, msg_id)
            except Exception as _te:
                if msg_id is None:
                    break  # حتی ارسال اول هم نشد — مستقیم نتیجه
                time.sleep(0.9)  # flood — مکث و یک تلاش مجدد
                try:
                    safe_edit_text(piece, chat_id, msg_id)
                except Exception:
                    pass
            time.sleep(delay)
        # ── فاز ۲: مکث دراماتیک قبل از اعلام برد ──
        time.sleep(1.0)
        # ── فاز ۳: اعلام برد ──
        reveal = texts.WHEEL_REVEAL_JACKPOT if prize_type == "vip" else texts.WHEEL_REVEAL
        try:
            if msg_id is not None:
                safe_edit_text(full + "\n\n" + reveal, chat_id, msg_id)
            else:
                msg_id = bot.send_message(chat_id, full + "\n\n" + reveal).message_id
        except Exception:
            pass
        time.sleep(0.45)
        # ── فاز ۴: رسانهٔ جایزه + توضیحات ──
        _wheel_send_prize_media(chat_id, widx, result_text, markup)
    finally:
        try:
            lk.release()
        except Exception:
            pass



__all__ = ['_wheel_fid_cache', '_wheel_gif_fid_cache', 'WHEEL_ENGINE_VERSION', '_cfg_wver', '_wheel_prewarm_job', '_wheel_type_locks', '_wheel_type_locks_guard', '_wheel_type_lock', '_wheel_send_prize_media', '_wheel_suspense_send']
