"""v5.4 — شمارنده‌های ماندگار داشبورد ادمین.

چرا لازم بود: آمار «فعال ۲۴ساعت» و «درخواست‌های ۲۴ ساعت» قبلاً فقط در حافظه بود و با هر
ری‌استارت/دیپلوی صفر می‌شد؛ «دیروز» و «میانگین ۷ روز» هم اصلاً قابل محاسبه نبود.

دو منبع داده (هر دو به وقت تهران):
  • daily_active(day, user_id, ts) — هر کاربر روزی یک ردیف (زمان اولین فعالیت آن روز).
    مجموعهٔ کاربرانِ دیده‌شدهٔ امروز در حافظه است تا برای هر پیام یک INSERT نزنیم.
  • stat_counters(bucket='YYYY-MM-DD HH', key, value) — شمارنده‌های ساعتی:
    req (پیام/دکمهٔ ربات)، err (خطاها)، boot (استارت پروسه)، memrestart (ری‌استارت حافظه‌ای).

نوشتن‌ها دسته‌ای است: flush() هر ۶۰ ثانیه از ترد server_stats صدا زده می‌شود؛ در بدترین
حالت (کرش ناگهانی) فقط آمار حداکثر یک دقیقه از دست می‌رود.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

import settings
from services import db
from services.common import TEHRAN

log = logging.getLogger("metrics")

_lock = threading.Lock()
_day: str | None = None
_seen: set[int] = set()
_pending: list[tuple[str, int, int]] = []
_counts: dict[tuple[str, str], int] = {}
_MAX_PENDING = 50_000  # سقف حافظه اگر دیتابیس مدتی در دسترس نباشد

RETAIN_DAYS = 40


def tehran_now() -> datetime:
    return datetime.now(TEHRAN)


def day_key(dt: datetime | None = None) -> str:
    return (dt or tehran_now()).astimezone(TEHRAN).strftime("%Y-%m-%d")


def hour_key(dt: datetime | None = None) -> str:
    return (dt or tehran_now()).astimezone(TEHRAN).strftime("%Y-%m-%d %H")


def hit(user_id: int | None, count_request: bool = True) -> None:
    """ثبت فعالیت کاربر (برای DAU) + در صورت نیاز یک «درخواست». بسیار ارزان — فقط حافظه."""
    t = tehran_now()
    d = t.strftime("%Y-%m-%d")
    global _day
    with _lock:
        if d != _day:
            _day = d
            _seen.clear()
        if user_id:
            uid = int(user_id)
            if uid not in _seen:
                _seen.add(uid)
                if len(_pending) < _MAX_PENDING:
                    _pending.append((d, uid, int(time.time())))
        if count_request:
            k = (t.strftime("%Y-%m-%d %H"), "req")
            _counts[k] = _counts.get(k, 0) + 1


def bump(key: str, n: int = 1) -> None:
    """افزایش یک شمارندهٔ ساعتی (err/boot/memrestart/...)."""
    k = (hour_key(), key)
    with _lock:
        _counts[k] = _counts.get(k, 0) + int(n)


def flush() -> None:
    """نوشتن دسته‌ای در دیتابیس. نکته: لاگ خطا بیرون از قفل تا با شمارندهٔ خطا بن‌بست نشود."""
    with _lock:
        pend = _pending[:]
        cnts = dict(_counts)
        _pending.clear()
        _counts.clear()
    if not pend and not cnts:
        return
    try:
        with db.tx() as c:
            if pend:
                c.executemany("INSERT OR IGNORE INTO daily_active(day, user_id, ts) VALUES(?,?,?)", pend)
            for (bucket, key), val in cnts.items():
                c.execute(
                    "INSERT INTO stat_counters(bucket, key, value) VALUES(?,?,?) "
                    "ON CONFLICT(bucket, key) DO UPDATE SET value = value + excluded.value",
                    (bucket, key, val))
    except Exception as exc:
        with _lock:  # برگرداندن به صف تا دور بعد دوباره تلاش شود
            room = max(0, _MAX_PENDING - len(_pending))
            _pending[:0] = pend[:room]
            for k, v in cnts.items():
                _counts[k] = _counts.get(k, 0) + v
        log.warning("metrics flush failed: %s", exc)


def seed_today() -> None:
    """در استارت: کاربرانی که امروز (قبل از این پروسه) فعال بوده‌اند را از ستون‌های موجود
    (last_streak_date ربات / last_seen مینی‌اپ) وارد daily_active می‌کند تا آمار امروزِ
    روز دیپلوی/ری‌استارت ناقص نباشد."""
    t = tehran_now()
    d = t.strftime("%Y-%m-%d")
    # شروع روز تهران به UTC (قالب iso ستون last_seen مینی‌اپ)
    start_iso = (t.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=3, minutes=30)).strftime(
        "%Y-%m-%dT%H:%M:%S")
    now_ts = int(time.time())
    try:
        with db.tx() as c:
            c.execute(
                "INSERT OR IGNORE INTO daily_active(day, user_id, ts) "
                "SELECT ?, user_id, ? FROM users WHERE user_id<>? AND (last_streak_date=? "
                "OR (last_seen IS NOT NULL AND last_seen>=?) OR last_active_date=?)",
                (d, now_ts, settings.ADMIN_ID or 0, d, start_iso, d))
    except Exception as exc:
        log.warning("seed_today failed: %s", exc)


def prune() -> None:
    """پاک‌سازی داده‌های قدیمی‌تر از RETAIN_DAYS روز."""
    cut = (tehran_now() - timedelta(days=RETAIN_DAYS)).strftime("%Y-%m-%d")
    try:
        with db.tx() as c:
            c.execute("DELETE FROM daily_active WHERE day < ?", (cut,))
            c.execute("DELETE FROM stat_counters WHERE bucket < ?", (cut,))
    except Exception as exc:
        log.warning("metrics prune failed: %s", exc)


# ---------------- خواندن ----------------
def dau(day: str, until_ts: int | None = None) -> int:
    if until_ts is None:
        return int(db.scalar("SELECT COUNT(*) FROM daily_active WHERE day=?", (day,), 0))
    return int(db.scalar("SELECT COUNT(*) FROM daily_active WHERE day=? AND ts<=?", (day, until_ts), 0))


def dau_by_day(first_day: str, last_day: str) -> dict[str, int]:
    return {r["day"]: int(r["n"]) for r in db.rows(
        "SELECT day, COUNT(*) AS n FROM daily_active WHERE day>=? AND day<=? GROUP BY day", (first_day, last_day))}


def distinct_active(first_day: str, last_day: str) -> int:
    return int(db.scalar(
        "SELECT COUNT(DISTINCT user_id) FROM daily_active WHERE day>=? AND day<=?", (first_day, last_day), 0))


def returning_today(day: str) -> int:
    """فعال‌های امروز که قبل از امروز هم در daily_active دیده شده‌اند."""
    return int(db.scalar(
        "SELECT COUNT(*) FROM daily_active a WHERE a.day=? AND EXISTS "
        "(SELECT 1 FROM daily_active b WHERE b.user_id=a.user_id AND b.day<?)", (day, day), 0))


def first_day() -> str | None:
    return db.scalar("SELECT MIN(day) FROM daily_active", (), None)


def counter_by_day(key: str, first_day_: str, last_day: str) -> dict[str, int]:
    """جمع شمارندهٔ ساعتی به تفکیک روز."""
    return {r["d"]: int(r["n"]) for r in db.rows(
        "SELECT substr(bucket,1,10) AS d, SUM(value) AS n FROM stat_counters "
        "WHERE key=? AND bucket>=? AND bucket<? GROUP BY d", (key, first_day_, last_day + "~"))}


def counter_range(key: str, start_bucket: str, end_bucket_incl: str) -> int:
    return int(db.scalar(
        "SELECT COALESCE(SUM(value),0) FROM stat_counters WHERE key=? AND bucket>=? AND bucket<=?",
        (key, start_bucket, end_bucket_incl), 0))


def counter_first_day(key: str) -> str | None:
    b = db.scalar("SELECT MIN(bucket) FROM stat_counters WHERE key=?", (key,), None)
    return b[:10] if b else None
