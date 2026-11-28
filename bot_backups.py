"""bot_backups.py — بکاپ شبانه (استخراج‌شده از main.py — v4.7).

زنجیرهٔ بکاپ شبانه + snapshot. (v5.4: گزارش روزانهٔ ادمین حذف شد.)
اشیاء ربات از طریق _bind(globals()) تزریق می‌شوند."""
from __future__ import annotations

import datetime
import io
import logging
import threading
import time

import gzip
import os
import tempfile

logger = logging.getLogger("bot_backups")
# ─── اشیاء تزریق‌شده از main.py در زمان import (الگوی bind — کد منتقل‌شده دست‌نخورده) ───
_BIND_KEYS = ['bot', 'db', 'texts', 'types', 'logger', 'ADMIN_ID', 'TEHRAN_TZ', 'to_persian_digits', 'to_persian_int', 'shamsi_date', 'jdatetime', 'BASE_DIR', 'DB_PATH', 'Path', 'sqlite3']


def _bind(ns: dict) -> None:
    """تزریق اشیاء runtime از globals() ربات (bot, db, texts, WHEEL_PRIZES, ...)."""
    for _k in _BIND_KEYS:
        if _k in ns:
            globals()[_k] = ns[_k]


# v5.4: «گزارش روزانهٔ ساعت ۲۳» به درخواست ادمین حذف شد — همهٔ آمار در داشبورد (services/dashboard.py).

# ====== بکاپ شبانه دیتابیس (هر شب ساعت ۰۳:۳۰ بامداد به وقت ایران — خلوت‌ترین ساعت) ======
def _make_db_backup_snapshot(dest_path):
    """ایجاد یک اسنپ‌شات کامل و سازگار از دیتابیس (شامل WAL) با استفاده از sqlite3 backup API.
    فایل اصلی هرگز دست‌نخورده می‌ماند؛ فقط یک کپی یکپارچه در dest_path ساخته می‌شود."""
    src = sqlite3.connect(str(DB_PATH))
    dst = sqlite3.connect(str(dest_path))
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()

# ── v3.23: کمکی‌های بکاپ — فشرده‌سازی، تلاش مجدد، زمان ۰۳:۳۰، VACUUM هفتگی ──
def _fmt_size(nbytes):
    """نمایش خوانا برای ادمین."""
    try:
        kb = float(nbytes) / 1024.0
        if kb >= 1024:
            return "%.1f مگابایت" % (kb / 1024.0)
        return "%d کیلوبایت" % int(kb)
    except Exception:
        return "؟"

def _gzip_db_file(src_path):
    """فشرده‌سازی فایل اسنپ‌شات دیتابیس (رفع ارور تایم‌اوت آپلود — حجم معمولاً ۵ تا ۱۰ برابر کم می‌شود).
    خروجی: (مسیر .gz، حجم خام، حجم فشرده) بایت."""
    import gzip as _gzip
    gz_path = str(src_path) + ".gz"
    with open(src_path, 'rb') as f_in, _gzip.open(gz_path, 'wb', compresslevel=6) as f_out:
        while True:
            chunk = f_in.read(512 * 1024)
            if not chunk:
                break
            f_out.write(chunk)
    return gz_path, os.path.getsize(str(src_path)), os.path.getsize(gz_path)

def _send_document_with_retry(bot_obj, chat_id, path, caption, tries=3, base_delay=3.0):
    """ارسال فایل با تلاش مجدد نمایی — رفع قطعی ارور «write operation timed out».
    خروجی: (موفق؟، آخرین خطا)."""
    last_err = None
    for attempt in range(1, tries + 1):
        try:
            with open(path, 'rb') as f:
                # v3.24.8: آپلود فایل حجیم timeout جدا می‌گیرد چون READ_TIMEOUT سراسری به ۳۰ رسید
                bot_obj.send_document(chat_id, f, caption=caption, timeout=90)
            return True, None
        except Exception as e:
            last_err = e
            logger.error("backup send attempt %s/%s failed: %s", attempt, tries, e)
            if attempt < tries:
                time.sleep(base_delay * attempt)
    return False, last_err

def _next_backup_target(now_t):
    """v3.23: بعدی زمان بکاپ خودکار — ۰۳:۳۰ بامداد تهران (خلوت‌ترین ساعت ربات).
    اگر الان از ۰۳:۳۰ گذشته باشیم، فردا ۰۳:۳۰."""
    target = now_t.replace(hour=3, minute=30, second=0, microsecond=0)
    if target <= now_t:
        target += datetime.timedelta(days=1)
    return target

VACUUM_INTERVAL_DAYS = 7

def _vacuum_due(today_iso):
    """هفتگی یک‌بار (یا اولین اجرا) VACUUM لازم است — صفحات آزاد انباشته جمع می‌شوند."""
    try:
        last = db.get_setting("last_vacuum_date")
    except Exception:
        last = None
    if not last:
        return True
    try:
        delta = datetime.date.fromisoformat(today_iso) - datetime.date.fromisoformat(str(last))
        return delta.days >= VACUUM_INTERVAL_DAYS
    except Exception:
        return True

def _maintenance_before_backup():
    """v3.23: پیش از بکاپ شبانه — VACUUM هفتگی + checkpoint فایل WAL.
    دیتابیس جمع‌وجور ← بکاپ کوچک‌تر و سریع‌تر + کوئری‌های روز بعد سریع‌تر."""
    today_iso = datetime.datetime.now(TEHRAN_TZ).date().isoformat()
    if _vacuum_due(today_iso):
        try:
            with db._lock:
                db.conn.execute("VACUUM")
            try:
                db.set_setting("last_vacuum_date", today_iso)
            except Exception:
                pass
            logger.info("🧹 VACUUM completed (weekly maintenance).")
        except Exception as e:
            logger.error("VACUUM error: %s", e)
    try:
        with db._lock:
            db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception as e:
        logger.error("wal_checkpoint error: %s", e)

def _snapshot_health_and_users(snapshot_path):
    """v3.23: گزارش سلامت روی خود اسنپ‌شات (بدون قفل دیتابیس زنده) — (متن سلامت، تعداد کاربر)."""
    try:
        _c = sqlite3.connect(str(snapshot_path))
        _ic = str(_c.execute("PRAGMA integrity_check").fetchone()[0])
        _n = _c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        _c.close()
        return ("سالم ✅" if _ic.lower() == "ok" else ("⚠️ " + _ic[:40])), _n
    except Exception as _e:
        logger.error("snapshot health check error: %s", _e)
        return "نامشخص", 0

def nightly_backup_loop():
    """Thread که هر شب ساعت ۰۳:۳۰ بامداد به وقت ایران (خلوت‌ترین ساعت ربات) جدیدترین نسخهٔ
    دیتابیس را فشرده‌شده (gzip) به‌صورت فایل به پی‌وی سوپر ادمین (ADMIN_ID) ارسال می‌کند.
    نکتهٔ حیاتی: این فایل فقط و فقط به سوپر ادمین ارسال می‌شود."""
    while True:
        try:
            now_t = datetime.datetime.now(TEHRAN_TZ)
            # v3.23: محاسبهٔ زمان بعدی ۰۳:۳۰ تهران
            target = _next_backup_target(now_t)
            wait_s = (target - now_t).total_seconds()
            time.sleep(max(wait_s, 1))

            # v3.11: احترام به کلید روشن/خاموش بکاپ خودکار (پنل ادمین ← دیتابیس)
            try:
                if db.get_setting_int("auto_backup_enabled", 1) != 1:
                    continue
            except Exception:
                pass

            # v3.23: نگهداری هفتگی قبل از اسنپ‌شات
            _maintenance_before_backup()

            backup_path = BASE_DIR / f"bot_data_backup_{datetime.datetime.now(TEHRAN_TZ).strftime('%Y%m%d')}.db"
            _make_db_backup_snapshot(backup_path)
            health_str, n_users = _snapshot_health_and_users(backup_path)
            gz_path, raw_b, gz_b = _gzip_db_file(backup_path)
            try: backup_path.unlink()
            except Exception: pass
            try:
                caption = (
                    f"🗄️ بکاپ شبانهٔ دیتابیس — {shamsi_date(datetime.datetime.now(TEHRAN_TZ), with_time=True)}\n"
                    f"👤 کاربران: {to_persian_int(n_users)}\n"
                    f"📦 حجم: {_fmt_size(raw_b)} → {_fmt_size(gz_b)} (فشرده)\n"
                    f"🩺 سلامت: {health_str}"
                )
                ok_sent, send_err = _send_document_with_retry(bot, ADMIN_ID, gz_path, caption)
                if ok_sent:
                    logger.info("🗄️ Nightly DB backup sent to admin (gz, %s → %s).", _fmt_size(raw_b), _fmt_size(gz_b))
                else:
                    logger.error("Nightly backup send failed after %s retries: %s", 3, send_err)
            except Exception as e:
                logger.error(f"Nightly backup send error: {e}")
            finally:
                try: Path(gz_path).unlink()
                except Exception: pass
        except Exception as e:
            logger.error(f"Nightly backup loop error: {e}")
            time.sleep(60)

# ====== بازیابی دیتابیس از طریق /restore (فقط سوپر ادمین) ======
# جریان کار: ادمین /restore را می‌زند → ربات منتظر دریافت فایل bot_data.db می‌ماند
# → فایل دریافتی اعتبارسنجی می‌شود → جایگزین دیتابیس فعلی می‌شود → ربات با اطلاعات کاربران فعال می‌ماند.
_restore_pending_lock = threading.Lock()
_restore_pending = False




__all__ = ['_make_db_backup_snapshot', '_fmt_size', '_gzip_db_file', '_send_document_with_retry', '_next_backup_target', 'VACUUM_INTERVAL_DAYS', '_vacuum_due', '_maintenance_before_backup', '_snapshot_health_and_users', 'nightly_backup_loop', '_restore_pending_lock', '_restore_pending']
