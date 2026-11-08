"""bot_helpers.py — ابزارهای خالص ربات (استخراج‌شده از main.py — v4.7).

اعداد فارسی/تاریخ شمسی/موتور قیمت VIP/فرار مارک‌داون/کدگذاری base62 —
توابع بدون وابستگی به دیتابیس یا اشیاء ربات.
"""
from __future__ import annotations

import datetime
import re
import string

import logging

try:
    import jdatetime
except ImportError:  # pragma: no cover
    jdatetime = None

logger = logging.getLogger("bot_helpers")
JDATE_OK = jdatetime is not None


PERSIAN_DIGITS = '۰۱۲۳۴۵۶۷۸۹'

def to_persian_digits(text):
    """تبدیل ارقام انگلیسی به فارسی در یک رشته."""
    if text is None:
        return ""
    s = str(text)
    for i, d in enumerate('0123456789'):
        s = s.replace(d, PERSIAN_DIGITS[i])
    return s

def to_persian_int(n):
    """تبدیل عدد به رشته فارسی با جداکنندهٔ هزارگان."""
    try:
        return to_persian_digits(f"{int(n):,}")
    except (ValueError, TypeError):
        return to_persian_digits(str(n))

def shamsi_date(dt=None, with_time=False):
    """تاریخ شمسی. اگر dt نبود، الان."""
    if not JDATE_OK:
        # Fallback: میلادی
        if dt is None: dt = datetime.datetime.now()
        if with_time:
            return dt.strftime("%Y/%m/%d - %H:%M")
        return dt.strftime("%Y/%m/%d")
    if dt is None:
        dt = datetime.datetime.now()
    try:
        if isinstance(dt, str):
            return dt  # از قبل تبدیل شده
        g_date = jdatetime.date.fromgregorian(date=dt.date() if hasattr(dt, 'date') else dt)
        if with_time and hasattr(dt, 'strftime'):
            return to_persian_digits(f"{g_date.strftime('%Y/%m/%d')} - {dt.strftime('%H:%M')}")
        return to_persian_digits(g_date.strftime('%Y/%m/%d'))
    except Exception as e:
        logger.error(f"shamsi_date error: {e}")
        return dt.strftime("%Y/%m/%d") if hasattr(dt, 'strftime') else str(dt)

def shamsi_today_str():
    """تاریخ شمسی امروز به صورت رشته (برای گزارش روزانه)."""
    if not JDATE_OK:
        return datetime.date.today().isoformat()
    g_today = datetime.date.today()
    j_today = jdatetime.date.fromgregorian(date=g_today)
    return to_persian_digits(j_today.strftime('%Y/%m/%d'))

def fmt_amount_rial(amount):
    """فرمت مبالغ به ریال فارسی."""
    return to_persian_int(amount) + " ریال"

def fmt_amount_toman(amount):
    """فرمت مبالغ به تومان فارسی."""
    return to_persian_int(amount // 10) + " تومان"

def pct_change(new, old):
    """محاسبهٔ درصد تغییر (new نسبت به old). برمی‌گرداند (علامت, عدد)."""
    if old == 0:
        # رفع باگ: استایل یکسان با بقیه موارد — استفاده از ایموجی
        return ('📈', '∞') if new > 0 else ('📉', '0')
    change = int(round((new - old) / old * 100))
    sign = '📈' if change >= 0 else '📉'
    return sign, to_persian_digits(abs(change))


# ====== v3.22: موتور قیمت‌گذاری خودکار VIP ======
# ادمین فقط قیمت ماهانه را وارد می‌کند؛ بقیهٔ پلن‌ها از فرمول چیده می‌شوند:
#   هفتگی = ماهانه × ۱.۱ ÷ ۴ | سه‌ماهه = ×۲.۷ | شش‌ماهه = ×۴.۸ | یک‌ساله = ×۸.۴
VIP_PLAN_LABELS = {7: "هفتگی", 30: "ماهانه", 90: "سه‌ماهه", 180: "شش‌ماهه", 365: "یک‌ساله"}

def vip_plan_label(days):
    """نام فارسی پلن بر اساس روز (هفتگی/ماهانه/...) — ناشناخته‌ها «N روزه»."""
    try:
        return VIP_PLAN_LABELS.get(int(days), f"{to_persian_digits(int(days))} روزه")
    except (TypeError, ValueError):
        return f"{to_persian_digits(days)} روزه"

def _round_price_250(x):
    """گردکردن قیمت به نزدیک‌ترین ۲۵۰ ریال (حفظ دقیق مثال کاربر: ۵۰۰٬۰۰۰ → هفتگی ۱۳۷٬۵۰۰)."""
    return max(250, int(round(x / 250.0)) * 250)

def compute_vip_prices(monthly_rial):
    """v3.22: چیدن خودکار همهٔ پلن‌ها از روی قیمت ماهانه (ورودی/خروجی به ریال).
    خروجی: دیکشنری {روز: قیمت} به همان ترتیب رسمی منو (هفتگی، ماهانه، سه‌ماهه، شش‌ماهه، یک‌ساله)."""
    m = float(monthly_rial)
    return {
        7:   _round_price_250(m * 1.10 / 4.0),
        30:  _round_price_250(m),
        90:  _round_price_250(m * 3 * 0.90),
        180: _round_price_250(m * 6 * 0.80),
        365: _round_price_250(m * 12 * 0.70),
    }

# ارقام عربی (٠-٩) علاوه بر فارسی (۰-۹)
_ARABIC_DIGITS = '٠١٢٣٤٥٦٧٨٩'
_MIN_MONTHLY_RIAL = 100_000        # ۱۰٬۰۰۰ تومان — حداقل منطقی ضد خطای تایپی
_MAX_MONTHLY_RIAL = 10_000_000_000 # ۱ میلیارد تومان — سقف ضد ورودی عجیب

def parse_price_input(text):
    """v3.22: پارس امن ورودی قیمت.
    «50000» یا «50,000 تومان» یا «۵۰٬۰۰۰» → تومان (×۱۰ = ریال)
    «500000 ریال» → ریال
    خروجی: (مقدار_ریال, واحد) یا (None, None) اگر قابل پارس نباشد."""
    if text is None:
        return (None, None)
    t = str(text).strip().lower()
    for ch in (',', '،', '٬'):          # جداکنندهٔ هزارگان لاتین/فارسی/عربی
        t = t.replace(ch, '')
    for i, d in enumerate(PERSIAN_DIGITS):
        t = t.replace(d, str(i))
    for i, d in enumerate(_ARABIC_DIGITS):
        t = t.replace(d, str(i))
    is_rial = 'ریال' in t
    if is_rial:
        t = t.replace('ریال', ' ')
    t = t.replace('تومان', ' ').replace('ت', ' ')   # پسوند «ت» هم تومان است
    t = t.strip()
    if not t or not t.isdigit():
        return (None, None)
    n = int(t)
    if is_rial:
        return (n, 'rial')
    return (n * 10, 'toman')

def validate_monthly_rial(n):
    """بازهٔ مجاز قیمت ماهانه — ضد خطای تایپی و ضد مقدارهای عجیب."""
    return n is not None and _MIN_MONTHLY_RIAL <= n <= _MAX_MONTHLY_RIAL

def build_vip_price_lines(prices):
    """ساخت خط‌های نمایش قیمت‌ها (تومان) با برچسب فارسی پلن + درصد تخفیف."""
    discounts = {7: '', 30: '', 90: ' (۱۰٪ تخفیف)', 180: ' (۲۰٪ تخفیف)', 365: ' (۳۰٪ تخفیف)'}
    lines = []
    for days in sorted(prices.keys()):
        amount = prices[days]
        lines.append(f"• {vip_plan_label(days)} ({to_persian_digits(days)} روز): {fmt_amount_toman(amount)}{discounts.get(days, '')}")
    return "\n".join(lines)



# ====== ابزار فرار از مارک‌داون ======
# parse_mode="Markdown" فعال است؛ escape_md کاراکترهای خطرناک را می‌پوشاند
# تا نام کاربران (با _ یا *) باعث خطای parse و حذف عکس‌ها نشود.
def escape_md(text: str) -> str:
    """Escape کاراکترهای مارک‌داون legacy (MarkdownV1) — جلوگیری از شکستن parse
    و در نتیجه حذف شدن عکس‌ها/کپشن‌ها وقتی نام کاربر شامل _ یا * باشد."""
    if text is None:
        return text
    s = str(text)
    return s.replace("\\", "\\\\").replace("*", "\\*").replace("_", "\\_").replace("`", "\\`")

# ====== کوتاه‌سازی شناسه (Base62) ======
BASE62_CHARS = string.digits + string.ascii_uppercase + string.ascii_lowercase
def rank_emoji_display(rank: int) -> str:
    if rank == 1: return "🥇"
    if rank == 2: return "🥈"
    if rank == 3: return "🥉"
    return "".join(f"{d}️⃣" for d in str(rank))

def generate_ghost_bar(cnt: int) -> str:
    # نوار پیشرفت ساده با کاراکترهای نوآر
    if cnt <= 30:
        return "🔍" * cnt
    return "🔍" * 20 + f" ... {to_persian_digits(cnt)}"
def encode_id(uid: int) -> str:
    if uid < 0:
        raise ValueError("شناسه منفی معتبر نیست")
    if uid == 0:
        return '0'
    res = []
    while uid > 0:
        uid, rem = divmod(uid, 62)
        res.append(BASE62_CHARS[rem])
    return ''.join(reversed(res))

def decode_id(code: str) -> int:
    code = code.strip()
    if not code:
        raise ValueError("کد خالی معتبر نیست")
    uid = 0
    for char in code:
        if char not in BASE62_CHARS:
            raise ValueError("کد نامعتبر")
        uid = uid * 62 + BASE62_CHARS.index(char)
    return uid

def sanitize_name(text: str) -> str:
    """v3.19: فقط اعداد + حروف فارسی + حروف انگلیسی (حذف * _ - @ ایموجی و نویسه‌های فانتزی)."""
    if re.search(r'(@|https?://|ble\.ir/|t\.me/)', text or '', flags=re.IGNORECASE):
        return "بی‌نام"
    try:
        import unicodedata as _ud
        s = _ud.normalize("NFKC", str(text or ""))
    except Exception:
        s = str(text or "")
    # دو‌tier: جداکننده‌ها (_ - . و نظیر) → فاصله؛ تزئینی/ایموجی/نماد → حذف کامل
    s = re.sub(r'[_\-.~=+|/\\]+', ' ', s)
    s = re.sub(r'[^0-9A-Za-z\u0600-\u06FF\u200c ]+', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s if s else "بی‌نام"

def crown_name(name, is_vip):
    """v3.6: نشان VIP — تاج دو طرف نام در رتبه‌بندی‌ها."""
    return f"👑 {name} 👑" if is_vip else name

def fa_to_en_digits(s):
    """تبدیل ارقام فارسی/عربی به لاتین برای پارس ورودی عددی."""
    if s is None:
        return ""
    s = str(s)
    return s.translate(str.maketrans(PERSIAN_DIGITS + "٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))

