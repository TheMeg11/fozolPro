"""VIP و پرداخت — یکپارچه با جدول `vip` ربات legacy.

ربات موجود VIP را در جدول `vip(user_id, expire_date — تاریخ ISO)` نگه می‌دارد و
مینی‌اپ در ستون‌های `users.vip_until/vip_plan`. هر دو از طریق services.legacy_bridge
هم‌گام نگه داشته می‌شوند؛ «انقضای مؤثر» = بزرگ‌ترین مقدار بین این دو.

پرداخت داخل مینی‌اپ پردازش نمی‌شود: create_invoice فاکتور را با sendInvoice در
چت بلهٔ کاربر می‌فرستد (payload با پیشوند `vip:` — بدون تداخل با فاکتورهای
ربات که از `_` استفاده می‌کنند)؛ ربات در pre_checkout/successful_payment همین
ماژول را صدا می‌زند تا VIP فعال شود.
"""
from __future__ import annotations

import math
import secrets
from datetime import timedelta

import settings
from services import bale_api, bot_settings, db, legacy_bridge
from services.common import AppError, iso, jalali, now, parse


def _live_plans() -> list[dict]:
    """قیمت‌ها از جدول settings ربات (تنظیم‌شده در منوی شیشه‌ای/پنل مینی‌اپ).
    اگر تنظیم نشده بود → پیش‌فرض‌های env. منبع واحد برای چت ربات و مینی‌اپ."""
    base = [dict(p) for p in settings.VIP_PLANS]
    prices = bot_settings.vip_prices_toman()
    if prices:
        for p in base:
            if p["days"] in prices:
                p["price"] = prices[p["days"]]
    return base


def plans() -> list[dict]:
    return _live_plans()


def plan(plan_id: str) -> dict:
    for p in _live_plans():
        if p["id"] == plan_id:
            return dict(p)
    raise AppError("VALIDATION_ERROR", "پلن انتخاب‌شده معتبر نیست.", 422)


def until_active(vip_until: str | None) -> bool:
    """سازگاری قدیمی — فقط مقدار ستون مینی‌اپ."""
    dt = parse(vip_until)
    return bool(dt and dt > now())


def is_active(user_id: int) -> bool:
    return legacy_bridge.is_vip(user_id)


def status(user_id: int) -> dict:
    exp = legacy_bridge.effective_vip_expiry(user_id)
    active = bool(exp and exp > now())
    r = db.row("SELECT vip_plan FROM users WHERE user_id=?", (user_id,)) or {}
    p = next((x for x in _live_plans() if x["id"] == r.get("vip_plan")), None)
    return {
        "active": active,
        "plan_title": (p["title"] if p else "VIP") if active else None,
        "expires_at": iso(exp) if active else None,
        "days_left": max(0, math.ceil((exp - now()).total_seconds() / 86400)) if active else 0,
    }


def extend(user_id: int, days: int, plan_id: str | None = None) -> dict:
    if not 0 < days <= 3650:
        raise AppError("VALIDATION_ERROR", "تعداد روز باید بین ۱ تا ۳۶۵۰ باشد.", 422)
    cur = legacy_bridge.active_vip_date(user_id)
    base = cur if cur else legacy_bridge.today_tehran()  # همان منطق add_vip ربات
    new = base + timedelta(days=days)
    legacy_bridge.vip_write(user_id, new, plan_id)
    return status(user_id)


def reduce(user_id: int, days: int) -> dict:
    if not 0 < days <= 3650:
        raise AppError("VALIDATION_ERROR", "تعداد روز نامعتبر است.", 422)
    cur = legacy_bridge.active_vip_date(user_id)
    if not cur:
        raise AppError("VALIDATION_ERROR", "این کاربر VIP فعال ندارد.", 422)
    new = cur - timedelta(days=days)
    if new <= legacy_bridge.today_tehran():
        legacy_bridge.vip_clear(user_id)
    else:
        legacy_bridge.vip_write(user_id, new)
    return status(user_id)


def cancel(user_id: int) -> dict:
    legacy_bridge.vip_clear(user_id)
    return status(user_id)


def expire_due() -> list[int]:
    """برای tasks.py: کاربرانی که VIP مینی‌اپشان (vip_until) تمام شده را برمی‌گرداند و پاک می‌کند.
    انقضای VIP سمت ربات را خودِ ربات (tasks/حلقه‌های legacy) مدیریت می‌کند."""
    ts = iso()
    ids = [r["user_id"] for r in db.rows(
        "SELECT user_id FROM users WHERE vip_until IS NOT NULL AND vip_until <= ?", (ts,))]
    if ids:
        for uid in ids:
            # اگر VIP ربات هنوز فعال است، vip_until را هم‌گام نگه دار — پاک نکن
            if legacy_bridge.bot_vip_date(uid) and legacy_bridge.bot_vip_date(uid) >= legacy_bridge.today_tehran():
                d = legacy_bridge.bot_vip_date(uid)
                legacy_bridge.vip_write(uid, d)
            else:
                db.execute("UPDATE users SET vip_until=NULL WHERE user_id=?", (uid,))
    return ids


# ---------------- پرداخت ----------------
def create_invoice(user_id: int, plan_id: str) -> dict:
    p = plan(plan_id)
    if not settings.PROVIDER_TOKEN:
        raise AppError("PAYMENT_NOT_CONFIGURED", "درگاه پرداخت هنوز فعال نشده؛ لطفاً بعداً تلاش کنید یا با پشتیبانی تماس بگیرید.", 503)
    recent = db.scalar("SELECT COUNT(*) FROM payments WHERE user_id=? AND status='pending' AND created_at > ?",
                       (user_id, iso(now() - timedelta(minutes=2))), 0)
    if recent >= 3:
        raise AppError("RATE_LIMITED", "چند فاکتور پیاپی ساخته‌اید؛ کمی صبر کنید.", 429)
    payload = f"vip:{p['id']}:{user_id}:{secrets.token_hex(6)}"
    amount_rial = int(p["price"]) * settings.TOMAN_TO_RIAL
    db.execute("INSERT INTO payments(user_id, plan_id, amount, payload, status, created_at) VALUES(?,?,?,?, 'pending', ?)",
               (user_id, p["id"], int(p["price"]), payload, iso()))
    bale_api.send_invoice(
        chat_id=user_id, title=f"خرید {p['title']}", description=f"اشتراک {p['days']} روزهٔ فضول‌یاب — پس از پرداخت خودکار فعال می‌شود.",
        payload=payload, amount_rial=amount_rial, label=p["title"],
    )
    return {"invoice_sent": True, "plan": p, "chat_url": settings.BALE_DEEPLINK_BASE + bale_api.bot_username()}


def validate_pre_checkout(payload: str, user_id: int, total_amount_rial: int | None = None) -> bool:
    r = db.row("SELECT * FROM payments WHERE payload=?", (payload,))
    if not r or r["user_id"] != user_id or r["status"] != "pending":
        return False
    return total_amount_rial is None or int(total_amount_rial) == int(r["amount"]) * settings.TOMAN_TO_RIAL


def handle_successful_payment(user_id: int, payload: str, charge_id: str | None = None) -> dict | None:
    """idempotent: پرداخت تکراری دوباره VIP اضافه نمی‌کند."""
    with db.tx() as c:
        r = c.execute("SELECT * FROM payments WHERE payload=?", (payload,)).fetchone()
        if not r or r["user_id"] != user_id or r["status"] == "paid":
            return None
        c.execute("UPDATE payments SET status='paid', charge_id=?, paid_at=? WHERE id=?", (charge_id, iso(), r["id"]))
    p = plan(r["plan_id"])
    st = extend(user_id, int(p["days"]), p["id"])
    st["message"] = f"✅ {p['title']} فعال شد.\nتاریخ انقضا: {jalali(st['expires_at'])}"
    return st


def payments_of(user_id: int, limit: int = 20) -> list[dict]:
    titles = {p["id"]: p["title"] for p in _live_plans()}
    db.execute("UPDATE payments SET status='failed' WHERE user_id=? AND status='pending' AND created_at < ?", (user_id, iso(now() - timedelta(days=1))))
    return [{"id": f"INV-{r['id']}", "plan_title": titles.get(r["plan_id"], r["plan_id"]), "amount": r["amount"], "status": r["status"], "created_at": r["created_at"]}
            for r in db.rows("SELECT * FROM payments WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))]


# ---------------- v4.9: تنظیمات ویژهٔ VIP (کارگاه کارآگاه ویژه) ----------------
# همان سه تنظیم منوی «کارگاه کارآگاه ویژه» پنل شیشه‌ای، این‌بار از مینی‌اپ:
# متن خوش‌آمدگویی، عکس خوش‌آمدگویی (رویت وضعیت — آپلود عکس در چت ربات) و نقاب کارآگاهی.
MASK_EMOJIS = ["🎭", "🔍", "🕯️", "🌙", "📂", "🔦", "🕵️", "👁️", "🗒️", "📇", "🧥", "🎖️", "🏅", "📰", "☕", "🚬"]
WELCOME_MAX = 500    # حداکثر طول متن خوش‌آمدگویی
MASK_EMOJI_MAX = 16  # یک ایموجی (یا ترکیب کوتاه)
MASK_TEXT_MAX = 32   # لقب نقاب — همان مقیاس لقب‌های لیدربورد


def _require_active(user_id: int) -> None:
    if not is_active(user_id):
        raise AppError("VIP_REQUIRED", "این تنظیم فقط برای اعضای VIP فعال است.", 403)


def _content_error(text: str) -> str | None:
    """همان فیلتر محتوای ربات (لینک خارجی + واژه‌های نامناسب) — مشترک با پروفایل."""
    try:
        from services import anon as _anon
        return _anon._content_error(text)
    except Exception:
        return None


def settings_view(user_id: int) -> dict:
    active = is_active(user_id)
    u = db.row("SELECT welcome_text, welcome_photo FROM users WHERE user_id=?", (user_id,)) or {}
    m = db.row("SELECT emoji, mask_text FROM user_mask WHERE user_id=?", (user_id,)) or {}
    return {
        "active": active,
        "welcome": {"text": u.get("welcome_text") or None, "photo_set": bool(u.get("welcome_photo"))},
        "mask": {"emoji": m.get("emoji") or None, "text": m.get("mask_text") or None},
        "mask_emojis": list(MASK_EMOJIS),
        "limits": {"welcome_max": WELCOME_MAX, "mask_emoji_max": MASK_EMOJI_MAX, "mask_text_max": MASK_TEXT_MAX},
    }


def set_welcome_text(user_id: int, text: str | None) -> dict:
    """ثبت/پاک کردن متن خوش‌آمدگویی — همان ستون users.welcome_text ربات."""
    _require_active(user_id)
    if text is None or not str(text).strip():
        db.execute("UPDATE users SET welcome_text=NULL WHERE user_id=?", (user_id,))
        return settings_view(user_id)
    t = str(text).strip()
    if len(t) > WELCOME_MAX:
        raise AppError("VALIDATION_ERROR", f"متن خوش‌آمدگویی حداکثر {WELCOME_MAX} کاراکتر است.", 422)
    bad = _content_error(t)
    if bad:
        raise AppError("VALIDATION_ERROR", f"این متن قابل قبول نیست ({bad}).", 422)
    db.execute("UPDATE users SET welcome_text=? WHERE user_id=?", (t, user_id))
    return settings_view(user_id)


def set_mask(user_id: int, emoji: str, mask_text: str) -> dict:
    """ثبت نقاب کارآگاهی — همان جدول user_mask ربات (INSERT OR REPLACE)."""
    _require_active(user_id)
    e = str(emoji or "").strip()
    t = str(mask_text or "").strip()
    if not e:
        raise AppError("VALIDATION_ERROR", "ایموجی نقاب را انتخاب کن یا خودت تایپ کن.", 422)
    if len(e) > MASK_EMOJI_MAX:
        raise AppError("VALIDATION_ERROR", "ایموجی نقاب نامعتبر است.", 422)
    if len(t) > MASK_TEXT_MAX:
        raise AppError("VALIDATION_ERROR", f"لقب نقاب حداکثر {MASK_TEXT_MAX} کاراکتر است.", 422)
    if t:
        bad = _content_error(t)
        if bad:
            raise AppError("VALIDATION_ERROR", f"این لقب قابل قبول نیست ({bad}).", 422)
    db.execute("INSERT OR REPLACE INTO user_mask (user_id, emoji, mask_text) VALUES (?,?,?)", (user_id, e, t))
    return settings_view(user_id)


def clear_mask(user_id: int) -> dict:
    _require_active(user_id)
    db.execute("DELETE FROM user_mask WHERE user_id=?", (user_id,))
    return settings_view(user_id)
