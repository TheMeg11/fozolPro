"""تنظیمات مشترک ربات/مینی‌اپ — منبع واحد: جدول `settings` ربات (منوی شیشه‌ای).

پنل ادمین مینی‌اپ و منوی شیشه‌ای ربات هر دو همین جدول را می‌خوانند/می‌نویسند؛
چون ربات get_setting_int را در هر استفاده زنده از DB می‌خواند، تغییر از مینی‌اپ
بلافاصله در رفتار ربات هم اعمال می‌شود (بدون ری‌استارت).
"""
from __future__ import annotations

import logging

import settings

from services import db
from services.common import AppError

log = logging.getLogger("bot_settings")

# ---- تنظیمات قابل‌ویرایش از پنل ادمین مینی‌اپ (whitelist) ----
# type: bool | int | price  (price = تومان، در جدول ریال ذخیره می‌شود مثل ربات)
EDITABLE = {
    "leaderboard_size":      {"label": "تعداد ردیف‌های جدول برترین‌ها", "type": "int", "min": 5, "max": 50, "default": 20, "hint": "چند نفر اول در مینی‌اپ نمایش داده شوند"},
    "wheel_enabled":         {"label": "گردونه شانس", "type": "bool", "default": 1},
    "maintenance_mode":      {"label": "حالت نگهداری (فقط ادمین)", "type": "bool", "default": 0},
    "smart_reminder_enabled": {"label": "یادآور هوشمند", "type": "bool", "default": 1},
    "weekly_report_enabled": {"label": "گزارش هفتگی ادمین", "type": "bool", "default": 1},
    "weekly_report_day":     {"label": "روز گزارش هفتگی", "type": "int", "min": 0, "max": 6, "default": 6, "hint": "۰=شنبه … ۶=جمعه"},
    "weekly_report_hour":    {"label": "ساعت گزارش هفتگی", "type": "int", "min": 0, "max": 23, "default": 21},
    "trial_days":            {"label": "هدیهٔ ورود (روز VIP)", "type": "int", "min": 0, "max": 30, "default": 3},
    "auto_backup_enabled":   {"label": "بکاپ خودکار شبانه", "type": "bool", "default": 1},
    "vip_price_30":          {"label": "قیمت VIP یک‌ماهه", "type": "price", "default": 49000},
    "vip_price_90":          {"label": "قیمت VIP سه‌ماهه", "type": "price", "default": 132250},
    "vip_price_365":         {"label": "قیمت VIP یک‌ساله", "type": "price", "default": 411500},
    "reveal_price":          {"label": "قیمت باز کردن هویت فضول (تک‌نفره)", "type": "price", "default": 3000,
                              "hint": "برای کاربران غیر-VIP؛ پرداخت در چت ربات انجام می‌شود"},
    "saveface_price":        {"label": "قیمت «حفظ آبرو» در تله", "type": "price", "default": 4500,
                              "hint": "مبلغی که بازدیدکنندهٔ تله برای فاش‌نشدن هویتش می‌پردازد (۳ دقیقه فرصت)"},
}

WEEKDAY_FA = {0: "شنبه", 1: "یک‌شنبه", 2: "دو‌شنبه", 3: "سه‌شنبه", 4: "چهار‌شنبه", 5: "پنج‌شنبه", 6: "جمعه"}


def get(key: str, default: str | None = None) -> str | None:
    try:
        r = db.row("SELECT value FROM settings WHERE key=?", (key,))
        return r["value"] if r else default
    except Exception:
        return default


def get_int(key: str, default: int = 0) -> int:
    try:
        return int(get(key, str(default)) or default)
    except (TypeError, ValueError):
        return default


def set_value(key: str, value) -> None:
    db.execute("INSERT INTO settings (key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, str(value)))


def leaderboard_size() -> int:
    n = get_int("leaderboard_size", 20)
    return max(3, min(50, n))


def wheel_enabled() -> bool:
    return get_int("wheel_enabled", 1) == 1


def vip_prices_toman() -> dict[int, int]:
    """قیمت‌های VIP از جدول settings ربات (ریال) → تومان (فقط کلیدهای تنظیم‌شده).
    خالی → از env استفاده می‌شود."""
    out = {}
    for days in (30, 90, 365):
        v = get(f"vip_price_{days}")
        if v is None:
            continue
        try:
            out[days] = int(v) // 10  # ریال → تومان
        except (TypeError, ValueError):
            continue
    return out


def monthly_price_toman() -> int:
    """قیمت واقعی VIP ماهانه (تومان) — جدول settings ربات (ریال) در اولویت.
    اگر ادمین هنوز تنظیم نکرده باشد، پیش‌فرض ۴٬۹۰۰ تومان (۴۹٬۰۰۰ ریال) —
    هم‌سو با قیمت واقعی فعلی ربات و پیش‌فرض پنل ادمین."""
    v = get("vip_price_30")
    if v is not None:
        try:
            return max(1, int(v) // 10)
        except (TypeError, ValueError):
            pass
    return 4900


def price_comparison() -> dict | None:
    """v4.4: مقایسهٔ قیمت هوشمند — «۵ هویتِ تکی در برابر VIP کامل ماه».
    همهٔ مبالغ از تنظیمات زندهٔ ادمین خوانده می‌شوند (بدون هاردکد).
    خروجی بر حسب تومان؛ None یعنی دادهٔ کافی نیست."""
    single = get_int("reveal_price", 30000) // 10
    month = monthly_price_toman()
    if single <= 0 or month <= 0:
        return None
    singles = 5
    singles_total = single * singles
    save_pct = int(round(max(0.0, (singles_total - month) / singles_total * 100))) if singles_total else 0
    return {"singles": singles, "single_price": single, "singles_total": singles_total,
            "month_price": month, "save_pct": save_pct}


def admin_view() -> list[dict]:
    """نمای پنل ادمین: مقدار فعلی هر تنظیم + متادیتا."""
    out = []
    for key, meta in EDITABLE.items():
        val = get(key)
        if val is None:
            val = str(meta["default"])
        item = {"key": key, "label": meta["label"], "type": meta["type"], "value": val}
        if meta["type"] == "int":
            item["value"] = str(get_int(key, int(meta["default"])))
            if key == "weekly_report_day":
                item["value_fa"] = WEEKDAY_FA.get(get_int(key, 6), "جمعه")
        if meta.get("hint"):
            item["hint"] = meta["hint"]
        out.append(item)
    return out


def admin_set(key: str, value) -> None:
    meta = EDITABLE.get(key)
    if not meta:
        raise AppError("VALIDATION_ERROR", "این تنظیم قابل تغییر نیست.", 422)
    t = meta["type"]
    try:
        if t == "bool":
            v = 1 if str(value).strip() in ("1", "true", "True", "on") else 0
        elif t == "int":
            v = int(str(value).strip())
            if not (int(meta.get("min", 0)) <= v <= int(meta.get("max", 10 ** 9))):
                raise ValueError
        elif t == "price":
            v = int(str(value).strip())
            if not (1000 <= v <= 100_000_000):
                raise ValueError
            v = v * 10  # تومان → ریال (فرمت ذخیرهٔ ربات)
        else:  # pragma: no cover
            raise ValueError
    except (TypeError, ValueError):
        raise AppError("VALIDATION_ERROR", "مقدار واردشده معتبر نیست.", 422) from None
    set_value(key, v)
    log.info("setting %s = %s (from miniapp admin)", key, v)
