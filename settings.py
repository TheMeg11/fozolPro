"""تنظیمات مینی‌اپ بله — همه‌چیز از متغیرهای محیطی.

ترتیب اولویت: env  ←  مقدار هم‌نام در config.py فعلی پروژه  ←  پیش‌فرض.
به این ترتیب config.py موجود دست نمی‌خورد و فقط مقادیرش ری‌یوز می‌شود.
هر چیزِ مخصوص بله (آدرس SDK، نام آبجکت SDK، کلید HMAC) قابل‌تنظیم است و باید با docs.bale.ai تطبیق داده شود.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

try:  # config.py فعلی ربات (در صورت وجود)
    import config as _legacy  # type: ignore
except Exception:  # pragma: no cover - در تست‌ها و اجرای مستقل وجود ندارد
    _legacy = None


def _get(name: str, default: str = "") -> str:
    val = os.getenv(name)
    if val not in (None, ""):
        return str(val)
    if _legacy is not None:
        legacy_val = getattr(_legacy, name, None)
        if legacy_val not in (None, ""):
            return str(legacy_val)
    return default


def _int(name: str, default: int) -> int:
    try:
        return int(_get(name, str(default)))
    except ValueError:
        return default


BASE_DIR = Path(__file__).resolve().parent

# --- هسته (متغیرهای فعلی پروژه) ---
BOT_TOKEN: str = _get("BOT_TOKEN")
ADMIN_ID: int = _int("ADMIN_ID", 0)
PROVIDER_TOKEN: str = _get("PROVIDER_TOKEN")          # درگاه پرداخت بله (WALLET-...)
DB_PATH: str = _get("DB_PATH", "/data/bot_data.db")

# --- وب و دیپلوی ---
PORT: int = _int("PORT", 8080)
RAILWAY_PUBLIC_DOMAIN: str = _get("RAILWAY_PUBLIC_DOMAIN")
WEBAPP_URL: str = (_get("WEBAPP_URL") or (f"https://{RAILWAY_PUBLIC_DOMAIN}" if RAILWAY_PUBLIC_DOMAIN else "")).rstrip("/")
WEBHOOK_URL: str = _get("WEBHOOK_URL").rstrip("/")      # خالی = polling
WEBHOOK_SECRET: str = _get("WEBHOOK_SECRET")
INITDATA_MAX_AGE: int = _int("INITDATA_MAX_AGE", 86400)  # ثانیه

# --- آدرس‌های پایهٔ بله (هیچ فراخوانی به سرویس دیگری انجام نمی‌شود) ---
BALE_API_BASE: str = _get("BALE_API_BASE", "https://tapi.bale.ai").rstrip("/")
BALE_FILE_BASE: str = _get("BALE_FILE_BASE", f"{BALE_API_BASE}/file").rstrip("/")
BALE_DEEPLINK_BASE: str = _get("BALE_DEEPLINK_BASE", "https://ble.ir/").rstrip("/") + "/"
BALE_SDK_URL: str = _get("BALE_SDK_URL", "https://tapi.bale.ai/miniapp.js?1")
BALE_SDK_GLOBAL: str = _get("BALE_SDK_GLOBAL", "Bale")            # window.Bale.WebApp
INITDATA_HMAC_KEY: str = _get("INITDATA_HMAC_KEY", "WebAppData")  # کلید ثابت HMAC طبق مستند بله
INITDATA_HEADER: str = _get("INITDATA_HEADER", "X-Bale-Init-Data")

# --- اختیاری‌ها (پیش‌فرض معقول دارند) ---
BOT_USERNAME: str = _get("BOT_USERNAME").lstrip("@")   # خالی = خودکار از getMe
REQUIRED_CHANNELS: list[str] = [c.strip() for c in _get("REQUIRED_CHANNELS").split(",") if c.strip()]
FORCE_JOIN_ENABLED: bool = _get("FORCE_JOIN_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
MINIAPP_DEMO: str = _get("MINIAPP_DEMO", "off")         # auto|on|off — در production خاموش
RATE_LIMIT_PER_MIN: int = _int("RATE_LIMIT_PER_MIN", 120)
WEBAPP_DIR: Path = Path(_get("WEBAPP_DIR", str(BASE_DIR / "webapp")))
# کش عکس‌های پروفایل (پروکسی آواتار) — روی Volume تا مصرف پهنای‌باند حداقل شود
AVATAR_DIR: Path = Path(_get("AVATAR_DIR", "/data/avatars"))
CSP: str = _get(
    "CSP",
    "frame-ancestors 'self' https://*.bale.ai https://bale.ai; frame-src https://*.bale.ai; "
    "default-src 'self'; script-src 'self' https://tapi.bale.ai https://*.bale.ai; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'",
)
SUPPORT_NOTIFY_ADMIN: bool = _get("SUPPORT_NOTIFY_ADMIN", "1") == "1"
BROADCAST_DELAY_SEC: float = float(_get("BROADCAST_DELAY_SEC", "0.06"))
XP_PER_SNOOP: int = _int("XP_PER_SNOOP", 5)
FREE_MAX_TRAPS: int = _int("FREE_MAX_TRAPS", 1)
VIP_MAX_TRAPS: int = _int("VIP_MAX_TRAPS", 10)

# v4.4: پیش‌فرض‌ها هم‌سو با قیمت واقعی ربات (ماهانه ۴٬۹۰۰ تومان — موتور قیمت‌گذاری config)
_DEFAULT_PLANS = [
    {"id": "monthly", "title": "VIP یک‌ماهه", "days": 30, "price": 4900, "old_price": None, "badge": None},
    {"id": "quarterly", "title": "VIP سه‌ماهه", "days": 90, "price": 13225, "old_price": 14700, "badge": "محبوب‌ترین"},
    {"id": "yearly", "title": "VIP یک‌ساله", "days": 365, "price": 41150, "old_price": 58800, "badge": "بهترین ارزش"},
]
try:
    VIP_PLANS: list[dict] = json.loads(_get("VIP_PLANS")) if _get("VIP_PLANS") else _DEFAULT_PLANS
except json.JSONDecodeError:
    VIP_PLANS = _DEFAULT_PLANS
# قیمت‌ها به تومان نمایش داده می‌شوند؛ مبلغ فاکتور بله به ریال است.
TOMAN_TO_RIAL: int = _int("TOMAN_TO_RIAL", 10)

VIP_FEATURES = [
    "نمایش نام و یوزرنیم کامل فضول‌ها",
    "ساخت تله‌های اختصاصی چندگانه (تا سقف تنظیم‌شدهٔ ربات)",
    "امتیاز XP دوبرابر در همه فعالیت‌ها",
    "یک چرخش اضافه گردونه در روز",
    "🛡️ سپر استریک — با غیبت یک‌روزه زنجیره‌ات نمی‌سوزد",
    "🎁 به ازای هر فضولِ جدید در تله، ۱ روز VIP رایگان",
    "⚡️ پشتیبانی اولویت‌دار + دسترسی زودهنگام به قابلیت‌های جدید",
    "پیام ناشناس نامحدود به فضول‌ها",
    "نشان طلایی در جدول برترین‌ها",
    "✨ ذرات طلایی متحرک در پس‌زمینهٔ مینی‌اپ",
    "نشان و قاب طلایی VIP در تمام صفحات",
]


def is_admin(user_id: int | None) -> bool:
    return bool(ADMIN_ID) and user_id == ADMIN_ID
