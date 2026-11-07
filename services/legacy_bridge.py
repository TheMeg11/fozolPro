"""پل بین لایهٔ سرویس مینی‌اپ (fozol-pro) و دیتابیس/منطق ربات legacy (main.py).

ربات موجود برای VIP از جدول `vip(user_id, expire_date)` و برای فضول‌یابی از
جدول‌های `traps` / `clicks` / `nicknames` استفاده می‌کند. این ماژول خواندن/نوشتن
هر دو جهان را یکسان می‌کند تا ربات و مینی‌اپ همیشه یک دیتای واحد ببینند:

- VIP مؤثر = بزرگ‌ترین مقدار بین `vip.expire_date` (ربات) و `users.vip_until` (مینی‌اپ).
- هر نوشتن VIP در هر دو جدول انجام و کش VIP ربات باطل می‌شود.
- کد تلهٔ پیش‌فرض هر کاربر همان `encode_id(user_id)` ربات است (base62).
"""
from __future__ import annotations

import datetime
import logging
import secrets
import string
from typing import Optional

from services import db
from services.common import TEHRAN, iso, now, parse

log = logging.getLogger("legacy_bridge")

# دقیقاً همان الفبای ربات (main.py: BASE62_CHARS)
BASE62 = string.digits + string.ascii_uppercase + string.ascii_lowercase


# ---------------- کدگذاری شناسه (همان encode_id ربات) ----------------
def encode_id(uid: int) -> str:
    uid = int(uid)
    if uid <= 0:
        return "0"
    res = []
    while uid > 0:
        uid, rem = divmod(uid, 62)
        res.append(BASE62[rem])
    return "".join(reversed(res))


# ---------------- VIP: خواندن یکپارچه ----------------
def bot_vip_date(user_id: int) -> Optional[datetime.date]:
    """تاریخ انقضای VIP از جدول ربات (YYYY-MM-DD) یا None."""
    r = db.row("SELECT expire_date FROM vip WHERE user_id=?", (user_id,))
    if not r or not r.get("expire_date"):
        return None
    try:
        return datetime.date.fromisoformat(str(r["expire_date"])[:10])
    except ValueError:
        return None


def _end_of_day(d: datetime.date) -> datetime.datetime:
    """VIP ربات تا پایان روز انقضا معتبر است (هم‌سمان is_vip ربات)."""
    return datetime.datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=TEHRAN)


def effective_vip_expiry(user_id: int) -> Optional[datetime.datetime]:
    """انقضای مؤثر VIP = max(جدول vip ربات، users.vip_until مینی‌اپ)."""
    exps = []
    bd = bot_vip_date(user_id)
    if bd:
        exps.append(_end_of_day(bd))
    mu = parse(db.scalar("SELECT vip_until FROM users WHERE user_id=?", (user_id,), None))
    if mu:
        exps.append(mu)
    return max(exps) if exps else None


def active_vip_date(user_id: int) -> Optional[datetime.date]:
    """تاریخ انقضای VIP مؤثر (فقط اگر هنوز فعال) به‌صورت date تهران."""
    exp = effective_vip_expiry(user_id)
    if not exp or exp <= now():
        return None
    return exp.astimezone(TEHRAN).date()


def is_vip(user_id: int) -> bool:
    return active_vip_date(user_id) is not None


def today_tehran() -> datetime.date:
    return now().astimezone(TEHRAN).date()


def today_utc_str() -> str:
    """شروع امروز تهران به‌صورت 'YYYY-MM-DD HH:MM:SS' UTC — برای مقایسه با
    ستون‌های TIMESTAMP دیتابیس ربات (clicked_at و created_at)."""
    s = now().astimezone(TEHRAN).replace(hour=0, minute=0, second=0, microsecond=0)
    return s.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ---------------- VIP: نوشتن یکپارچه ----------------
def vip_write(user_id: int, new_date: datetime.date, plan_id: Optional[str] = None) -> None:
    """نوشتن هم‌زمان در جدول `vip` ربات و ستون‌های `users` مینی‌اپ + باطل‌کردن کش ربات."""
    day = new_date.isoformat()
    with db.tx() as c:
        c.execute(
            "INSERT INTO vip(user_id, expire_date) VALUES(?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET expire_date=excluded.expire_date",
            (user_id, day),
        )
        c.execute("UPDATE users SET vip_until=?, vip_plan=? WHERE user_id=?",
                  (iso(_end_of_day(new_date)), plan_id, user_id))
    invalidate_bot_vip_cache(user_id)


def vip_clear(user_id: int) -> None:
    with db.tx() as c:
        c.execute("DELETE FROM vip WHERE user_id=?", (user_id,))
        c.execute("UPDATE users SET vip_until=NULL, vip_plan=NULL WHERE user_id=?", (user_id,))
    invalidate_bot_vip_cache(user_id)


def invalidate_bot_vip_cache(user_id: int) -> None:
    """کش VIP ربات (Database._vip_cache) را برای این کاربر باطل می‌کند تا
    تغییر VIP از مینی‌اپ بلافاصله در ربات هم دیده شود."""
    try:
        import main as legacy_main  # در اجرای واقعی main از قبل لود شده است

        dbi = getattr(legacy_main, "db", None)
        if dbi is None:
            return
        cls = type(dbi)
        cache = getattr(cls, "_vip_cache", None)
        if cache is None:
            return
        lock = getattr(cls, "_vip_cache_lock", None)
        if lock is not None:
            with lock:
                cache.pop(user_id, None)
        else:
            cache.pop(user_id, None)
    except Exception as exc:  # noqa: BLE001 — پل اختیاری است
        log.debug("vip cache invalidation skipped: %s", exc.__class__.__name__)


# ---------------- فضول‌یابی: تله‌ها ----------------
def default_trap_code(owner_id: int) -> str:
    """تلهٔ پیش‌فرض ربات = کد base62 شناسه کاربر (لینک ?start=<code>)."""
    return encode_id(owner_id)


def new_trap_code(owner_id: int) -> str:
    """کد تلهٔ اختصاصی در همان قالب ربات: 't' + ۵ کاراکتر [a-z0-9] یکتا."""
    alpha = string.ascii_lowercase + string.digits
    for _ in range(30):
        code = "t" + "".join(secrets.choice(alpha) for _ in range(5))
        if not db.row("SELECT 1 FROM traps WHERE trap_code=?", (code,)):
            return code
    return "t" + "".join(secrets.choice(alpha) for _ in range(8))
