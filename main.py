import telebot
from telebot import apihelper, types
import os, io, sqlite3, datetime, time, threading, re, string, requests, random, logging, sys, shutil, tempfile, hashlib
from collections import defaultdict, deque
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# اضافه کردن مسیر site-packages کاربر برای دسترسی به jdatetime
try:
    sys.path.insert(0, '/home/z/.local/lib/python3.13/site-packages')
    import jdatetime
    JDATE_OK = True
except ImportError:
    JDATE_OK = False
    print("⚠️ jdatetime نصب نیست — تاریخ‌ها میلادی نمایش داده می‌شوند.")
import texts
import tasks as tasks_module
import config
from telebot.apihelper import ApiTelegramException

# ====== v3.9: ماژول لیدربورد تصویری (Pillow) — در نبودش، حالت متنی ======
try:
    import leaderboard_img
except Exception as _lbi_err:
    leaderboard_img = None
    print("⚠️ leaderboard_img بارگذاری نشد — لیدربورد متنی می‌ماند:", _lbi_err)

# ====== v3.9.4: ماژول انیمیشن GIF چرخ شانس — در نبودش، نتیجهٔ فوری متنی ======
try:
    import wheel_gif
except Exception as _wg_err:
    wheel_gif = None
    print("⚠️ wheel_gif بارگذاری نشد — چرخ شانس بدون انیمیشن GIF:", _wg_err)

# ====== v3.13: ماژول ویدیوی MP4 چرخ (روش A نهایی‌شده) — در نبود ffmpeg → GIF ======
try:
    import wheel_video
except Exception as _wv_err:
    wheel_video = None
    print("⚠️ wheel_video بارگذاری نشد — چرخ شانس با GIF قبلی:", _wv_err)

# ====== لاگ‌گیری پایه ======
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ====== v3.21: شمارندهٔ خطاها — «مشکلات ربات» در آمار کل ======
# هر لاگ ERROR/CRITICAL (خطاهای هندلرها، API، دیتابیس و...) شمرده می‌شود؛
# دامنه: از شروع پروسه (هم‌خوان با «آپ‌تایم») + متن آخرین خطا برای دیباگ سریع.
class _ErrorCounter(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self._lock = threading.Lock()
        self.count = 0
        self.last = ""
        self.last_at = None

    def emit(self, record):
        with self._lock:
            self.count += 1
            try:
                self.last = str(record.getMessage())[:150]
            except Exception:
                self.last = ""
            # v4.0 (fozol-pro): TEHRAN_TZ ممکن است در خطاهای زودهنگام import هنوز تعریف نشده باشد
            try:
                self.last_at = datetime.datetime.now(TEHRAN_TZ).strftime('%H:%M')
            except Exception:
                self.last_at = None

    def snapshot(self):
        with self._lock:
            return self.count, self.last

ERROR_COUNTER = _ErrorCounter()
logging.getLogger().addHandler(ERROR_COUNTER)

# ====== مسیرها ======
BASE_DIR = Path(__file__).parent
# Railway: مسیر دیتابیس از Environment Variable (DB_PATH) خوانده می‌شود
# تا روی Volume دائمی ذخیره شود و با هر deploy از بین نرود.
# v4.6.1 (رفع باگ دیپلوی از ریپو): پیش‌فرض هم‌سو با settings.py → /data/bot_data.db
# (قبلاً بدون DB_PATH، ربات به BASE_DIR/bot_data.db می‌رفت و مینی‌اپ به /data/bot_data.db
#  — یعنی دو دیتابیس جدا و از دست رفتن داده‌ها هنگام redeploy!)
DB_PATH = Path(os.environ.get("DB_PATH", "").strip() or "/data/bot_data.db")
try:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

# ====== بارگذاری تنظیمات از config.py ======
TOKEN = config.BOT_TOKEN
ADMIN_ID = config.ADMIN_ID
PROVIDER_TOKEN = config.PROVIDER_TOKEN
VIP_PRICES = dict(config.VIP_PRICES_DEFAULT)  # کپی برای امکان تغییر در runtime

# فایل آی‌دی‌ها از config.py
LEADERBOARD_PHOTO_ID = config.LEADERBOARD_PHOTO_ID
SCARY_PHOTO_ID = config.SCARY_PHOTO_ID
PROMO_WELCOME_NEW_PHOTO_ID = config.PROMO_WELCOME_NEW_PHOTO_ID
PROMO_WELCOME_OLD_PHOTO_ID = config.PROMO_WELCOME_OLD_PHOTO_ID
REVIEW_PHOTO_ID = config.REVIEW_PHOTO_ID
VIP_MAIN_PHOTO_ID = config.VIP_MAIN_PHOTO_ID
BUY_VIP_PHOTO_ID = config.BUY_VIP_PHOTO_ID
LEVEL_UP_PHOTO_ID = config.LEVEL_UP_PHOTO_ID
CHALLENGE_PHOTO_ID = config.CHALLENGE_PHOTO_ID  # v3.24.0: عکس منوی فضول‌گیر برتر
LINK_TUTORIAL_VIDEO_ID = config.LINK_TUTORIAL_VIDEO_ID

# تنظیمات پخش همگانی
BROADCAST_WORKERS = config.BROADCAST_WORKERS
BROADCAST_BATCH_SIZE = config.BROADCAST_BATCH_SIZE
BROADCAST_BATCH_DELAY = config.BROADCAST_BATCH_DELAY
BROADCAST_TIMEOUT = config.BROADCAST_TIMEOUT

# تنظیمات XP
XP_BONUS_ONE_TIME = config.XP_BONUS_ONE_TIME
XP_RECURRING = config.XP_RECURRING

if not TOKEN or TOKEN == "TOKEN_ROBAT_RA_INJA_BENAVISID":
    print("❌ توکن نامعتبر. متغیر محیطی BOT_TOKEN را در تنظیمات (Railway → Variables) تعریف کنید.")
    exit(1)

if not ADMIN_ID:
    print("⚠️ ADMIN_ID ست نشده — حالت تست فعال می‌شود. اولین کاربر که /start بزنه خودکار ادمین می‌شود.")

apihelper.API_URL = "https://tapi.bale.ai/bot{0}/{1}"
# ====== v3.23: timeout و retry سراسری — پایداری شبکه در مقیاس ۵۰۰۰+ کاربر ======
# ریشهٔ ارور «write operation timed out» در آپلود بکاپ حجیم، timeout پیش‌فرض کتابخانه بود.
# v3.24.8 (بر اساس گزارش /usage): دُم کند ۱۵–۳۰ ثانیه‌ای — ریشه: یک پکت گمشده
# با CONNECT=20 × MAX_RETRIES=15 کتابخانه می‌توانست هندلر را دقایقی نگه دارد.
# حالا: شکستِ سریعِ اتصال (۸ث) + حداکثر ۳ تلاش؛ آپلود بکاپ حجیم timeout=۹۰ جدا می‌گیرد.
apihelper.CONNECT_TIMEOUT = 8       # اتصال TCP — شکست سریع به‌جای معطلی ۲۰ثانیه‌ای
apihelper.READ_TIMEOUT = 30         # خواندن پاسخ (پیش‌فرض کتابخانه) — بکاپ با timeout=۹۰ در send_document
apihelper.LONG_POLLING_TIMEOUT = 30
apihelper.RETRY_ON_ERROR = True     # خطاهای شبکهٔ پرشی خودکار تلاش مجدد می‌شوند
apihelper.RETRY_TIMEOUT = 2
apihelper.MAX_RETRIES = 3           # v3.24.8: سقف ۳ تلاش (پیش‌فرض کتابخانه ۱۵ بود)
# رفع باگ 404 در /restore: دانلود فایل هم باید از سرور بله انجام شود نه api.telegram.org
try:
    apihelper.FILE_URL = "https://tapi.bale.ai/file/bot{0}/{1}"
except Exception:
    pass
bot = telebot.TeleBot(TOKEN, parse_mode="Markdown",
                      num_threads=int(os.environ.get("BOT_WORKER_THREADS", "8")))
bot_info = bot.get_me()
BOT_USERNAME = bot_info.username

# ====== سازگاری با Bale: حذف reply_parameters از همه درخواست‌ها ======
# Bale API از پارامتر reply_parameters (معرفی‌شده در Telegram Bot API 7.0) پشتیبانی نمی‌کند.
# نسخه‌های جدید pyTelegramBotAPI (4.x+) به‌صورت پیش‌فرض از reply_parameters استفاده می‌کنند
# (حتی اگه reply_to_message_id پاس بدی، بازم به reply_parameters تبدیلش می‌کنه).
# این باعث خطای 404 "no such group or user" در Bale می‌شود.
# این patch همه درخواست‌ها رو intercept می‌کنه و reply_parameters رو به reply_to_message_id تبدیل می‌کنه.
import json as _json_module
_original_make_request = apihelper._make_request

# ====== v3.24.0: رفع باگ «HTTP 414 Request-URI Too Large» — باز نشدن آمار کل و آرشیو روزانه ======
# pyTelegramBotAPI کل payload (متن + دکمه‌ها) را به‌صورت Query String در URL ارسال می‌کند.
# متن‌های فارسیِ بلند بعد از انکود (هر حرف ≈ ۶ بایت) از سقف URI در nginx بله (≈۸KB) رد می‌شوند.
# تست زنده روی API بله (۱۴۰۴/۰۶/۱۴): JSON Body ← 400 «chat id is empty» (پشتیبانی نمی‌شود!)
#                                   form-urlencoded body ← 200 OK ✅
# راه‌حل نهایی: اگر طول URI تخمینی از حد آستانه گذشت، همان payload با «فرم‌بادی» ارسال
# می‌شود (همان انکود Query String ولی در بدنهٔ درخواست — بدون محدودیت URI).
# بقیه درخواست‌ها عیناً مسیر قبلی را می‌روند (صفر ریسک رگرسیون).
_BALE_JSON_BODY_MIN = 2500  # حد آستانه طول URI انکودشده (کاراکتر)

def _bale_estimate_uri_len(params):
    """تخمین طول URI در حالت Query String — همان انکودی که requests انجام می‌دهد."""
    try:
        from urllib.parse import urlencode
        return len(urlencode(params, doseq=True))
    except Exception:
        try:
            return len(str(params)) * 3
        except Exception:
            return 0

def _bale_post_body(token, method_name, params):
    """ارسال POST با form-urlencoded body — مسیر امن برای payload های بزرگ.
    (تست زنده: بله JSON Body را parse نمی‌کند ولی فرم‌بادی استاندارد را کامل قبول می‌کند.)
    رفتار timeout/exception عیناً مثل _make_request اصلی شبیه‌سازی شده است."""
    import requests as _rq
    from urllib.parse import urlencode as _urlencode
    request_url = apihelper.API_URL.format(token, method_name)
    p = dict(params)
    read_timeout = apihelper.READ_TIMEOUT
    connect_timeout = apihelper.CONNECT_TIMEOUT
    if 'timeout' in p:
        try:
            read_timeout = p.pop('timeout')
            connect_timeout = read_timeout
        except Exception:
            pass
    if 'long_polling_timeout' in p:
        try:
            lpt = p.pop('long_polling_timeout')
            p['timeout'] = lpt
            read_timeout = max(lpt + 5, read_timeout)
        except Exception:
            pass
    body = _urlencode(p, doseq=True)
    result = _rq.post(request_url, data=body.encode('utf-8'),
                      headers={'Content-Type': 'application/x-www-form-urlencoded'},
                      timeout=(connect_timeout, read_timeout),
                      proxies=getattr(apihelper, 'proxy', None))
    json_result = apihelper._check_result(method_name, result)
    if json_result:
        return json_result['result']
    return None

def _bale_make_request(token, method_url, params=None, method='post', files=None, **kw):
    """Patch برای سازگاری با Bale: reply_parameters → reply_to_message_id در همه درخواست‌ها.
    v3.24.0: payload های بزرگ (URI بلند) به‌جای Query String با فرم‌بادی ارسال می‌شوند."""
    if params and 'reply_parameters' in params:
        try:
            rp = params['reply_parameters']
            if isinstance(rp, str):
                rp_dict = _json_module.loads(rp)
            elif hasattr(rp, 'to_json'):
                rp_dict = _json_module.loads(rp.to_json())
            elif isinstance(rp, dict):
                rp_dict = {}
            else:
                rp_dict = {}
            # فقط message_id رو بردار و به‌عنوان reply_to_message_id اضافه کن
            if 'message_id' in rp_dict and 'reply_to_message_id' not in params:
                params['reply_to_message_id'] = rp_dict['message_id']
            params.pop('reply_parameters', None)
        except Exception:
            # اگه پارس نشد، فقط حذفش کن تا Bale به مشکل نخوره
            params.pop('reply_parameters', None)
    # v3.24.0: مسیر فرم‌بادی فقط برای POST بدون فایل و payload بزرگ
    if params and method == 'post' and not files:
        try:
            if _bale_estimate_uri_len(params) >= _BALE_JSON_BODY_MIN:
                return _bale_post_body(token, method_url, params)
        except Exception:
            pass  # هر مشکلی در تخمین/مسیر فرم‌بادی → رفتار عادی قبلی
    return _original_make_request(token, method_url, params=params, method=method, files=files)
apihelper._make_request = _bale_make_request

# ====== v3.19: ادیت امن پیام پنل — رفع باگ «دکمه‌های زیر پیام عکس‌دار کار نمی‌کند» ======
# در Bale پیامِ حاوی عکس/ویدیو با edit_message_text ادیت نمی‌شود → دکمه‌ها مرده به‌نظر می‌رسند.
# راه‌حل: تلاش برای ادیت؛ در شکست → ارسال پیام جدید و سپس حذف پیام قدیمی.
_bot_edit_message_text = bot.edit_message_text

def safe_edit_text(text, chat_id, message_id, reply_markup=None, **kw):
    """ادیت متن پیام؛ اگر پیام رسانه‌ای باشد (ادیت ممکن نیست) پیام جدید می‌فرستد
    و پیام قبلی را حذف می‌کند. امضای آرگومان‌ها با bot.edit_message_text یکسان است."""
    if message_id:
        try:
            _bot_edit_message_text(text, chat_id, message_id, reply_markup=reply_markup, **kw)
            return
        except Exception:
            pass
    # مسیر فالبک: اول پیام جدید تا پنل هیچ‌وقت گم نشود، بعد حذف قدیمی
    try:
        bot.send_message(chat_id, text, reply_markup=reply_markup, **kw)
    except Exception:
        return
    if message_id:
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass

# ====== ابزارهای اعداد فارسی و تاریخ شمسی ======
from bot_helpers import (  # noqa: F401 — v4.7 استخراج از main.py
    PERSIAN_DIGITS, to_persian_digits, to_persian_int, shamsi_date, shamsi_today_str,
    fmt_amount_rial, fmt_amount_toman, pct_change, vip_plan_label, _round_price_250,
    compute_vip_prices, parse_price_input, validate_monthly_rial, build_vip_price_lines,
    _MIN_MONTHLY_RIAL, _MAX_MONTHLY_RIAL, escape_md, BASE62_CHARS, rank_emoji_display,
    generate_ghost_bar, encode_id, decode_id, sanitize_name, crown_name, fa_to_en_digits,
)
# ====== v3.22: حالت نگهداری ======
_maint_cache = {"val": None, "ts": 0.0}


def maintenance_active():
    """آیا حالت نگهداری فعال است؟ (کش ۵ ثانیه‌ای برای جلوگیری از کوئری در هر پیام)"""
    now = time.time()
    if _maint_cache["val"] is None or now - _maint_cache["ts"] > 5.0:
        try:
            _maint_cache["val"] = 1 if db.get_setting_int("maintenance_mode", 0) == 1 else 0
        except Exception:
            pass
        _maint_cache["ts"] = now
    return _maint_cache["val"] == 1

def maintenance_gate(user_id):
    """v3.22: True = این کاربر در زمان نگهداری مسدود است (هر کس جز سوپرادمین)."""
    if user_id == ADMIN_ID:
        return False
    return maintenance_active()

def fetch_channel_info(channel_identifier):
    """اطلاعات کانال را از API دریافت می‌کند و شناسهٔ مناسب برای get_chat_member را برمی‌گرداند."""
    url = f"https://tapi.bale.ai/bot{TOKEN}/getChat"
    try:
        resp = requests.post(url, json={"chat_id": channel_identifier}, timeout=5)
        data = resp.json()
        if data.get("ok"):
            chat = data["result"]
            name = chat.get("title", str(channel_identifier))
            link = chat.get("invite_link", None)
            raw_id = chat.get("id")
            # تبدیل شناسه به فرمت صحیح منفی
            api_id = str(raw_id) if raw_id is not None else str(channel_identifier)
            return {"name": name, "link": link, "api_id": api_id}
    except Exception as e:
        logger.warning(f"fetch_channel_info error: {e}")
    return {"name": str(channel_identifier), "link": None, "api_id": channel_identifier}

# ====== پایگاه داده ======
from bot_db import Database, _SharedWriteLock, TEHRAN_TZ  # noqa: F401 — v4.7 استخراج از main.py
db = Database(str(DB_PATH))

# ====== Auto-Admin (TEST MODE) ======
# وقتی ADMIN_ID از env ست نشده (==0)، اولین کاربری که /start بزنه به‌صورت خودکار ادمین میشه.
# این فقط برای تست/دیباگ هست و در محیط production حتماً باید ADMIN_ID در env ست شده باشه.
def _try_load_auto_admin():
    """اگه ADMIN_ID == 0، تلاش می‌کنه auto_admin_id رو از دیتابیس بخونه و ADMIN_ID رو آپدیت کنه."""
    global ADMIN_ID
    if ADMIN_ID != 0:
        return
    try:
        row = db.conn.execute("SELECT value FROM settings WHERE key='auto_admin_id'").fetchone()
        if row and row['value']:
            ADMIN_ID = int(row['value'])
            logger.info(f"🧪 TEST MODE: Auto-admin loaded from DB: {ADMIN_ID}")
    except Exception as e:
        logger.error(f"Auto-admin load error: {e}")

def _set_auto_admin(uid):
    """در TEST MODE، اولین کاربر به‌عنوان ادمین خودکار در DB ذخیره میشه و ADMIN_ID آپدیت میشه."""
    global ADMIN_ID
    if ADMIN_ID != 0:
        return False
    try:
        with db._lock:
            existing = db.conn.execute("SELECT value FROM settings WHERE key='auto_admin_id'").fetchone()
            if existing and existing['value']:
                return False  # از قبل ست شده
            db.conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                            ("auto_admin_id", str(uid)))
            db.conn.commit()
        ADMIN_ID = int(uid)
        logger.info(f"🧪 TEST MODE: Auto-admin set to {ADMIN_ID}")
        return True
    except Exception as e:
        logger.error(f"Auto-admin set error: {e}")
        return False

_try_load_auto_admin()

# ====== بارگذاری قیمت‌های VIP از دیتابیس (اگر ادمین قبلاً تغییر داده) ======
for _days in VIP_PRICES.keys():
    saved = db.get_vip_price(_days)
    if saved and saved > 0:
        VIP_PRICES[_days] = saved

# ====== بارگذاری کانال‌های اجباری از دیتابیس ======
CHANNELS = []
channel_info = {}
broken_channels = set()  # کانال‌هایی که ربات نمی‌تواند اعضایشان را بررسی کند (v4.7 — قبل از load)
# v4.7: تزریق به bot_db برای گزارش روزانه (get_full_daily_report_data)
import bot_db as _bot_db_mod
_bot_db_mod.broken_channels = broken_channels

# کلید خاموش/روشن عضویت اجباری — از Environment Variable
# FORCE_JOIN_ENABLED=0 یا false → عضویت اجباری کاملاً غیرفعال
FORCE_JOIN_ENABLED = os.environ.get("FORCE_JOIN_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")

def _api_ch_id(ch_id):
    """v4.7 (باگ اد اجباری): نرمال‌سازی شناسهٔ کانال برای API بله.

    رکوردهای قدیمی پنل مینی‌اپ شناسهٔ متنی بدون @ (مثل «fzxinfo») دارند؛
    getChatMember با آن خطای 404 «no such group» می‌دهد. شناسهٔ عددی و
    @username بدون تغییر برمی‌گردند؛ متنی بدون @ → «@fzxinfo»."""
    ch_id = (ch_id or "").strip()
    if not ch_id:
        return ch_id
    if ch_id.startswith("@") or (ch_id.startswith("-") and ch_id[1:].isdigit()):
        return ch_id
    if ch_id.isdigit():
        return ch_id
    return "@" + ch_id


def load_channels_from_db():
    """v4.7 (باگ «اد اجباری کار نمی‌کند»): کانال‌ها دیگر به‌خاطر خطای بررسی حذف نمی‌شوند.

    قبلاً اگر get_chat_member روی یک کانال خطا می‌داد (ربات ادمین نبود / شناسهٔ
    اشتباه)، کانال بی‌صدا از CHANNELS حذف می‌شد و اد اجباری کلاً خاموش می‌شد.
    حالا کانال در لیست می‌ماند؛ خطا فقط به سوپرادمین اطلاع داده می‌شود و
    is_subscribed همان‌طور مثل قبل fail-closed رفتار می‌کند (کاربر باید عضو شود)."""
    global CHANNELS, channel_info
    CHANNELS.clear()
    channel_info.clear()
    if not FORCE_JOIN_ENABLED:
        print("⛔ عضویت اجباری خاموش است (FORCE_JOIN_ENABLED=0) — کانال‌ها بارگذاری نشدند.", flush=True)
        return
    for fc in db.get_all_forced_channels():
        ch_id = fc['channel_id']
        name = fc['channel_name'] if fc['channel_name'] else ch_id
        link = fc['invite_link'] if fc['invite_link'] else None
        channel_info[ch_id] = {"name": name, "link": link}
        broken_channels.discard(ch_id)
        # تست سریع دسترسی — کانال حتی در صورت خطا هم در چک اجباری می‌ماند (v4.7)
        try:
            bot.get_chat_member(_api_ch_id(ch_id), ADMIN_ID)
        except Exception as e:
            broken_channels.add(ch_id)
            logger.error(f"⚠️ Cannot verify admin in channel {ch_id}: {e}")
            print(f"⚠️ کانال {ch_id}: ربات نمی‌تواند اعضا را بررسی کند — کانال در اد اجباری می‌ماند (fail-closed).", flush=True)
        CHANNELS.append(ch_id)

load_channels_from_db()

print(f"✅ ربات @{BOT_USERNAME} v{getattr(config, 'BOT_VERSION', '3.14.0')} | ادمین: {ADMIN_ID} | پرداخت: {'فعال' if PROVIDER_TOKEN else 'غیرفعال'} | عضویت اجباری: {'فعال' if FORCE_JOIN_ENABLED else 'خاموش'} | کانال‌های اجباری: {CHANNELS}", flush=True)

# ====== ثابت‌ها و توابع کمکی ======
# توجه: نام سطح‌ها در texts.LEVEL_NAMES تعریف شده‌اند (v3.17)

# ========== عکس‌ها و فایل‌ها =============
# همه فایل آی‌دی‌ها در config.py تعریف شده‌اند

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

# ====== فیلتر لینک‌های خارجی و فحاشی ======
# لیست کلمات ممنوعه (فحاشی و توهین)
PROFANITY_WORDS = [
    # --- لیست اولیه شما ---
    'کسده', 'کصده', 'کس ننه', 'کص ننه', 'کیر', 'کون', 'جنده', 'کونی', 'خارکسه',
    'بی‌عفت', 'بی عفت', 'احمق', 'ابله', 'مغز فلگ', 'چاقال', 'خنگ', 'کر',
    'عوضی', 'رو سیاه', 'روسیاه', 'گوه', 'گاید', 'گایده', 'شلفت', 'ننه کص',
    'کصشر', 'کسشر', 'ممه', 'کله کیری', 'بی‌شرف', 'بی شرف', 'دزد', 'لقmac',
    'fuck', 'shit', 'bitch', 'asshole', 'dick', 'pussy', 'cunt',

    # --- فحش‌های ناموسی و رکیک شدید (اضافه شده) ---
    'خارکصده', 'خارکسده', 'خواهرکصده', 'خواهرکسده', 'مادرکصده', 'مادرکسده',
    'ناموس', 'بی‌ناموس', 'بیناموس', 'لاشی', 'دیوث', 'دایوث', 'کیرم', 'کیرت',
    'کونده', 'کونته', 'کونی', 'ساکزن', 'جکشه', 'جاکش', 'باجناق', 'خوارکسه',
    'کسکش', 'کصکش', 'حرومزاده', 'حرامی', 'تخم سگ', 'تخمسگ', 'پدرسگ', 'پدر سگ',

    # --- کلمات و اصطلاحات جنسی و اندام‌ها (با املای مختلف) ---
    'کص', 'کس', 'دودول', 'بیضه', 'خایه', 'خایه‌مال', 'خایه مال', 'ساک', 'پستون',
    'ارضا', 'جلق', 'جق', 'جقی', 'حشری', 'سکسی', 'پورن', 'صیغه', 'همجنس‌باز',

    # --- مشتقات فعل گاییدن (بسیار رایج در توهین‌ها) ---
    'بگایی', 'بگام', 'بگات', 'بگاد', 'بگایید', 'بگاین', 'گاییدم', 'گاییدت', 'گاییدش',
    'میگام', 'میگات', 'میگاد', 'کون گشاد', 'کون لق',

    # --- توهین‌های عامیانه، تحقیرآمیز و کلمات سبک‌تر ---
    'عن', 'عنتر', 'شاش', 'شاشی', 'پفیوز', 'اسکل', 'اوسکل', 'اسکول', 'پلشت',
    'لاشخور', 'پفیوز', 'بیشعور', 'بی شعور', 'نفهم', 'وحشی', 'گاو', 'الاغ', 'خر',
    'دیوونه', 'دیوانه', 'روانی', 'عقده‌ای', 'جیره خور', 'خایه خور', 'مفت خور'
]

# الگوی تشخیص لینک‌های خارجی (هر چیزی که شبیه URL باشه)
URL_PATTERN = re.compile(
    r'(https?://[^\s]+|www\.[^\s]+|t\.me/[^\s]+|telegram\.me/[^\s]+|'
    r'telegram\.dog/[^\s]+|ble\.ir/[^\s]+|@[\w_]{5,})',
    re.IGNORECASE
)

def contains_external_link(text: str) -> bool:
    """بررسی آیا متن شامل لینک خارجی یا یوزرنیم تلگرام/بله هست."""
    if not text:
        return False
    # لینک‌های http/https/www
    if re.search(r'(https?://|www\.)', text, re.IGNORECASE):
        return True
    # لینک‌های تلگرام و بله
    if re.search(r'(t\.me/|telegram\.me/|telegram\.dog/|ble\.ir/)', text, re.IGNORECASE):
        return True
    # @username (۵ کاراکتر یا بیشتر — برای جلوگیری از false positive با ایموجی‌ها)
    if re.search(r'@[\w_]{5,}', text):
        return True
    return False

def contains_profanity(text: str) -> bool:
    """بررسی آیا متن شامل فحاشی یا توهین هست."""
    if not text:
        return False
    text_lower = text.lower()
    # نرمال‌سازی (حذف فاصله‌های اضافی)
    text_normalized = re.sub(r'\s+', ' ', text_lower).strip()
    for word in PROFANITY_WORDS:
        if word in text_normalized:
            return True
    return False

def is_inappropriate_content(text: str) -> tuple:
    """بررسی محتوای نامناسب.
    برمی‌گرداند: (is_inappropriate: bool, reason: str)"""
    if contains_external_link(text):
        return True, "لینک خارجی"
    if contains_profanity(text):
        return True, "محتوای نامناسب"
    return False, ""

# ====== دریافت عکس پروفایل با requests ======
def get_user_photo_file_id(user_id):
    try:
        url = f"https://tapi.bale.ai/bot{TOKEN}/getChat"
        resp = requests.post(url, json={"chat_id": user_id}, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok") and "photo" in data.get("result", {}):
                return data["result"]["photo"]["big_file_id"]
    except:
        pass
    return None

# ====== محدودیت‌ها ======
# برای کاربر عادی: یک دیکشنری جدا برای ردیابی روزانه
# برای VIP: همان deque مبتنی بر دقیقه
anon_rate_vip = defaultdict(lambda: deque(maxlen=200))  # VIP: per-minute tracking
anon_daily_normal = defaultdict(lambda: deque(maxlen=10))  # Normal: per-day tracking
click_rate = defaultdict(lambda: deque(maxlen=10))
gift_attempt_rate = defaultdict(lambda: deque(maxlen=5))

def can_send_anon(sender, receiver):
    """بررسی آیا کاربر می‌تواند پیام ناشناس بفرستد.
    - کاربر VIP: ۱۰ پیام در دقیقه (عملا نامحدود)
    - کاربر عادی: ۱ پیام در روز
    """
    now = time.time()
    if db.is_vip(sender):
        # VIP: 10 per minute
        key = (sender, receiver)
        while anon_rate_vip[key] and anon_rate_vip[key][0] < now - 60:
            anon_rate_vip[key].popleft()
        return len(anon_rate_vip[key]) < 10
    else:
        # Normal: 1 per day (86400 seconds)
        # ردیابی بر اساس sender فقط (نه per receiver)
        day_start = now - 86400
        while anon_daily_normal[sender] and anon_daily_normal[sender][0] < day_start:
            anon_daily_normal[sender].popleft()
        return len(anon_daily_normal[sender]) < 1

def reg_anon(sender, receiver):
    """ثبت یک ارسال پیام ناشناس."""
    now = time.time()
    if db.is_vip(sender):
        anon_rate_vip[(sender, receiver)].append(now)
    else:
        anon_daily_normal[sender].append(now)

def can_anon_contact(sender_id, target_id):
    """v3.22 امنیتی: ضد تماس سرد — مخاطب ناشناس فقط باید
    فضولِ تلهٔ فرستنده یا طرفِ گفتگوی ناشناسِ قبلی (در هر دو جهت) باشد.
    بدون این چک، با کال‌بک فورج‌شده (anon_ / anon_reply_) می‌شد به هر کاربری پیام ناشناس اسپم داد."""
    if sender_id == target_id:
        return False
    try:
        for s in db.get_snoops(sender_id):
            if s['clicker_id'] == target_id:
                return True
        # زنجیرهٔ پاسخ: قبلاً بین این دو پیام ناشناس ردوبدل شده است
        # توجه: get_last_anon_log وقتی لاگی نیست «رشتهٔ خالی» برمی‌گرداند نه None — پس truthy چک می‌کنیم
        if db.get_last_anon_log(target_id, sender_id):
            return True
        if db.get_last_anon_log(sender_id, target_id):
            return True
    except Exception as e:
        logger.error(f"can_anon_contact error: {e}")
        return False
    return False

def can_click(user_id):
    now = time.time()
    while click_rate[user_id] and click_rate[user_id][0] < now - 60:
        click_rate[user_id].popleft()
    return len(click_rate[user_id]) < 3

def reg_click(user_id):
    click_rate[user_id].append(time.time())


def anon_vip_gate(user_id):
    """v4.4: پیام ناشناس فقط برای VIP — درخواست کاربر ادمین.
    خروجی None یعنی مجاز؛ در غیر این صورت (متن, مارک‌آپ) برای رد و آپ‌سل."""
    if db.is_vip(user_id):
        return None
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("👑 فعال‌سازی کارت طلایی", callback_data="buy_vip_menu"))
    markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
    return ("✉️ ارسال پیام ناشناس فقط مخصوص اعضای کارت طلایی است.\n"
            "👑 با VIP می‌توانی به همهٔ فضول‌هایت پیام ناشناس نامحدود بدهی!", markup)

# ====== حالت‌ها (با Lock کامل) ======
awaiting = {}
state_lock = threading.Lock()
def clear_user_state(chat_id):
    with state_lock:
        awaiting.pop(chat_id, None)

def set_user_state(chat_id, state):
    with state_lock:
        awaiting[chat_id] = state

def get_user_state(chat_id):
    with state_lock:
        return awaiting.get(chat_id)

support_sessions = set()
support_partners = {}
admin_reply = {}

# ====== شمارندهٔ پیام‌های ۲۴ ساعت ======
msg_times = deque()
msg_lock = threading.Lock()

# ====== v3.21: درخواست‌ها — شمارندهٔ ماه شمسی + کاربرانِ دارای حداقل یک درخواست ======
def _g2j_fallback(gy, gm, gd):
    """میلادی → شمسی (الگوریتم کلاسیک) — فقط وقتی jdatetime در دسترس نیست."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd

def _j2g_fallback(jy, jm, jd):
    """شمسی → میلادی (الگوریتم کلاسیک) — فقط وقتی jdatetime در دسترس نیست."""
    jy += 1595
    days = (-355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4)
            + jd + ((jm - 1) * 31 if jm < 7 else ((jm - 7) * 30) + 186))
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)
    months = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 12
    for i in range(1, 13):
        if gd <= months[i]:
            gm = i
            break
        gd -= months[i]
    return gy, gm, gd

def _current_jalali_month_key():
    """کلید ماه شمسی جاری به شکل 'YYYY-MM' (مثلاً '1404-07')."""
    try:
        j_now = jdatetime.date.fromgregorian(date=datetime.date.today())
        return "%04d-%02d" % (j_now.year, j_now.month)
    except Exception:
        t = datetime.date.today()
        jy, jm, _ = _g2j_fallback(t.year, t.month, t.day)
        return "%04d-%02d" % (jy, jm)

class _MonthRequestCounter:
    """شمارندهٔ درخواست‌های «ماه شمسی» جاری — در حافظه شمرده می‌شود و هر ۵ دقیقه
    (و در ماه‌عوضی فوری) در جدول settings ذخیره می‌شود. با ری‌استارت حداکثر ۵ دقیقه
    از شمارش از دست می‌رود. کلیدها: req_month_key / req_month_count."""
    def __init__(self):
        self._lock = threading.Lock()
        self._key = None
        self._count = 0
        self._dirty = False
        self._load()

    def _load(self):
        try:
            self._key = db.get_setting("req_month_key") or None
            self._count = int(db.get_setting("req_month_count") or 0)
        except Exception:
            self._key, self._count = None, 0
        cur = _current_jalali_month_key()
        if self._key != cur:  # ری‌استارت در ماه جدید → شمارش از صفر
            self._key, self._count, self._dirty = cur, 0, False

    def increment(self):
        with self._lock:
            cur = _current_jalali_month_key()
            if cur != self._key:  # ماه عوض شد → ریست فوری
                self._key, self._count = cur, 0
            self._count += 1
            self._dirty = True

    def current(self):
        with self._lock:
            if _current_jalali_month_key() != self._key:
                self._key, self._count, self._dirty = _current_jalali_month_key(), 0, False
            return self._count

    def flush(self):
        """ذخیره در settings — توسط janitor هر ۵ دقیقه صدا زده می‌شود."""
        with self._lock:
            if not self._dirty:
                return
            try:
                db.set_setting("req_month_key", self._key)
                db.set_setting("req_month_count", str(self._count))
                self._dirty = False
            except Exception:
                pass

_month_requests = None  # بلافاصله بعد از ساخت db مقداردهی می‌شود
try:
    _month_requests = _MonthRequestCounter()
except Exception:
    _month_requests = None

# کاربرانِ دارای حداقل یک درخواست — در حافظه نگه‌داری + فلاش دوره‌ای به users.requested
_requested_users = set()
_requested_lock = threading.Lock()
_requested_dirty = set()

def load_requested_users():
    """هنگام استارت: مجموعهٔ کاربرانِ با requested=1 را از دیتابیس می‌خواند."""
    try:
        with db.conn:
            rows = db.conn.execute("SELECT user_id FROM users WHERE requested=1").fetchall()
        with _requested_lock:
            _requested_users.update(int(r['user_id']) for r in rows)
        logger.info("[v3.21] requested users loaded: %d", len(_requested_users))
    except Exception as e:
        logger.error("load_requested_users failed: %s", e)

def track_request_user(user_id):
    """ثبت اینکه این کاربر حداقل یک درخواست (پیام/دکمه) به ربات فرستاده است."""
    if not user_id:
        return
    with _requested_lock:
        if user_id in _requested_users:
            return
        _requested_users.add(user_id)
        _requested_dirty.add(user_id)

def flush_persisted_stats():
    """هر ۵ دقیقه: فلاش شمارندهٔ ماه + کاربرانِ درخواست‌دهنده به دیتابیس."""
    try:
        if _month_requests:
            _month_requests.flush()
    except Exception:
        pass
    try:
        with _requested_lock:
            dirty = list(_requested_dirty)
            _requested_dirty.clear()
        if dirty:
            with db._lock:
                db.conn.executemany(
                    "UPDATE users SET requested=1 WHERE user_id=?", [(u,) for u in dirty])
                db.conn.commit()
    except Exception as e:
        logger.error("flush_requested_users error: %s", e)

# v3.6: کاربران تازه‌فعال (برای اسکنر ماموریت‌های زمان واقعی) — user_id -> timestamp
_recently_active = {}
_recently_active_lock = threading.Lock()

def mark_recently_active(user_id):
    now = time.time()
    with _recently_active_lock:
        _recently_active[user_id] = now
        # هر از گاهی پاک‌سازی ورودی‌های قدیمی‌تر از ۱۰ دقیقه
        if len(_recently_active) > 500:
            cutoff = now - 600
            for k in [k for k, v in _recently_active.items() if v < cutoff]:
                _recently_active.pop(k, None)

def get_recently_active_users(seconds=300):
    cutoff = time.time() - seconds
    with _recently_active_lock:
        return [uid for uid, ts in _recently_active.items() if ts >= cutoff]

STREAK_MILESTONES = {3: 100, 7: 250, 14: 500, 30: 1200}

# ====== v3.6: چرخ شانس روزانه (VIP) ======
WHEEL_PRIZES = [
    {"type": "xp", "value": 20, "weight": 28, "label": "۲۰ XP"},
    {"type": "xp", "value": 50, "weight": 24, "label": "۵۰ XP"},
    {"type": "xp", "value": 100, "weight": 19, "label": "۱۰۰ XP"},
    {"type": "xp", "value": 250, "weight": 13, "label": "۲۵۰ XP"},
    {"type": "xp", "value": 500, "weight": 8, "label": "۵۰۰ XP"},
    {"type": "xp", "value": 1000, "weight": 4, "label": "۱٬۰۰۰ XP"},
    {"type": "vip", "value": 1, "weight": 3, "label": "۱ روز VIP (نادر!)"},
    {"type": "vip", "value": 3, "weight": 1, "label": "۳ روز VIP (جک‌پات!)"},
]
WHEEL_CELLS = "🟨🟦🟩🟪🟧🟥⬛🟩"  # (قدیمی — دیگر استفاده نمی‌شود؛ برای سازگاری مانده)

# ====== v3.17: جوایز جایزه روزانه (همهٔ کاربران — ریست ۰۰:۰۰ ایران) ======
DAILY_PRIZES = [
    {"type": "xp", "value": 30,   "weight": 30, "label": "۳۰ XP"},
    {"type": "xp", "value": 60,   "weight": 24, "label": "۶۰ XP"},
    {"type": "xp", "value": 100,  "weight": 18, "label": "۱۰۰ XP"},
    {"type": "xp", "value": 200,  "weight": 12, "label": "۲۰۰ XP"},
    {"type": "xp", "value": 500,  "weight": 6,  "label": "۵۰۰ XP"},
    {"type": "xp", "value": 1000, "weight": 2,  "label": "۱٬۰۰۰ XP"},
    {"type": "vip", "value": 1,   "weight": 3,  "label": "۱ روز VIP (جک‌پات!)"},
]
DAILY_STREAK_BONUS_STEP = 10   # درصد پاداش استریک به‌ازای هر روز پیوسته
DAILY_STREAK_BONUS_CAP = 100   # سقف پاداش استریک (درصد)

# ====== v3.19: جوایز VIP نقاط عطف استریک جایزه روزانه (درخواست ادمین) ======
# روز ۱۰: ۱ روز | روز ۲۰: ۲ روز | روز ۳۰: ۳ روز | روز ۴۰: ۵ روز |
# روز ۵۰ به بعد: هر ۱۰ روز ۵ روز VIP (۵۰/۶۰/۷۰/...)
def streak_vip_reward(streak):
    """پاداش VIP مخصوص رسیدن استریک به نقاط عطف — ۰ یعنی بدون پاداش."""
    s = int(streak or 0)
    if s == 10:
        return 1
    if s == 20:
        return 2
    if s == 30:
        return 3
    if s >= 40 and s % 10 == 0:
        return 5
    return 0

import bot_wheel_media as _bot_wheel_media  # v4.7 استخراج از main.py — ماژول bot_wheel_media
_bot_wheel_media._bind(globals())  # تزریق اشیاء ربات (bot/db/texts/...)
from bot_wheel_media import (  # noqa: F401 — نام‌های منتقل‌شده به ماژول
    _wheel_fid_cache, _wheel_gif_fid_cache, WHEEL_ENGINE_VERSION, _cfg_wver,
    _wheel_prewarm_job, _wheel_type_locks, _wheel_type_locks_guard, _wheel_type_lock,
    _wheel_send_prize_media, _wheel_suspense_send
)
def _update_streak_and_notify(user_id):
    """استریک روزانه — در اولین فعالیت هر روز به‌روزرسانی + پاداش XP در نقاط عطف.
    v4.4: سپر استریک VIP (غیبت یک‌روزه زنجیره را نمی‌سوزاند) +
    جایزهٔ هفتگی دوئولینگو-استایل — هر ۷ روز پیاپی، ۱ روز VIP رایگان."""
    streak, is_new_day, shield_used = db.update_streak(user_id)
    if not is_new_day:
        return
    # v4.4: سپر استریک — اطلاع‌رسانی که زنجیره نجات یافت
    if shield_used:
        try:
            bot.send_message(user_id, texts.STREAK_SHIELD_SAVED.format(streak=to_persian_digits(streak)))
        except Exception:
            pass
    # v4.4: جایزهٔ هفتگی — هر ۷ روز (خارج از نقاط عطف XP تا دوباره‌کاری نشود)
    if streak >= 7 and streak % 7 == 0 and streak not in STREAK_MILESTONES:
        try:
            db.add_vip(user_id, 1)
            db.add_transaction(user_id, "streak_week_bonus", 0, 1)
            try:
                bot.send_message(user_id, texts.STREAK_WEEKLY_VIP.format(streak=to_persian_digits(streak)))
            except Exception:
                pass
        except Exception as e:
            logger.error(f"streak weekly vip bonus error: {e}")
    if streak in STREAK_MILESTONES:
        try:
            u = db.get_user_basic(user_id)
            name = (u['first_name'] if u and u['first_name'] else "کارآگاه")
            bot.send_message(user_id, texts.STREAK_MILESTONE.format(
                streak=to_persian_digits(streak), name=escape_md(name),
                xp=to_persian_int(STREAK_MILESTONES[streak])))
        except Exception:
            pass
        try:
            award_xp_with_level_up_notify(user_id, STREAK_MILESTONES[streak], chat_id=user_id)
        except Exception:
            pass

def record_message(user_id: int = None):
    if user_id == ADMIN_ID:
        return
    try:
        _update_streak_and_notify(user_id)
    except Exception:
        pass
    mark_recently_active(user_id)
    # v3.21: درخواست‌سنجی — پیام کاربر = یک درخواست (شمارندهٔ ماه شمسی + مجموعهٔ کاربران)
    try:
        track_request_user(user_id)
    except Exception:
        pass
    try:
        if _month_requests:
            _month_requests.increment()
    except Exception:
        pass
    now = time.time()
    with msg_lock:
        msg_times.append(now)

def get_messages_24h():
    now = time.time()
    with msg_lock:
        while msg_times and msg_times[0] < now - 86400:
            msg_times.popleft()
        return len(msg_times)

# ====== v3.21: نام نمایشی دکمه‌ها (برای «پرکلیک‌ترین دکمه» در آمار کل) ======
CALLBACK_LABELS = {
    "my_link_show": "تله من", "my_info": "اطلاعات من", "leaderboard": "ستاره‌ها",
    "snooplist": "لیست فضول‌ها", "tasks": "ماموریت‌ها", "rewards_menu": "پاداش‌ها",
    "daily_bonus": "جایزه روزانه", "daily_claim": "دریافت جایزه روزانه",
    "wheel": "چرخ شانس", "wheel_spin": "چرخاندن چرخ", "gift_code": "کد هدیه",
    "vip_info": "کارت طلایی", "buy_vip_menu": "فعال‌سازی کارت طلایی",
    "vip_buy": "خرید کارت طلایی", "anon": "پیام ناشناس", "anon_menu": "پیام ناشناس",
    "support": "پشتیبانی", "help": "راهنما", "main_menu": "خانه",
    "challenge_info": "چالش فضول‌گیر برتر", "profile_reveal": "باز کردن پروفایل",
    "settings": "تنظیمات", "mask": "نقاب", "nickname": "لقب",
    "admin_panel": "پنل ادمین", "admin_userlist": "لیست کاربران (ادمین)",
    "admin_daily": "آمار کل (ادمین)", "admin_broadcast": "پیام همگانی",
    "admin_ad_mode": "حالت تبلیغ",
    "check_join": "بررسی عضویت", "copy_raw_link": "کپی لینک خام",
    "hide_me": "مخفیکردن نام", "lb_name": "تغییر نام نمایشی",
    "admin_price_monthly": "تغییر قیمت VIP", "admin_price_monthly_go": "تأیید قیمت‌های VIP",
    "admin_maint_toggle": "حالت نگهداری",
    "back_to_menu": "بازگشت به خانه", "home": "خانه",
}

def _button_display_name(callback_data):
    """برگرداندن نام نمایشی فارسی دکمه از روی callback_data؛ ناشناخته‌ها تمیز و کوتاه می‌شوند."""
    if not callback_data:
        return "نامشخص"
    cb = str(callback_data).strip()
    if cb in CALLBACK_LABELS:
        return CALLBACK_LABELS[cb]
    for prefix, label in CALLBACK_LABELS.items():
        if cb.startswith(prefix + "_") or cb.startswith(prefix + "-"):
            return label
    # پترن‌های پارامتری رایج
    for prefix, label in (("snooplist_page", "لیست فضول‌ها"), ("tasks_page", "ماموریت‌ها"),
                          ("admin_userlist", "لیست کاربران (ادمین)"),
                          ("admin_daily_archive", "آرشیو روزانه (ادمین)"),
                          ("leaderboard_page", "ستاره‌ها"), ("chal_glass", "چالش فضول‌گیر برتر"),
                          ("user_detail", "پروفایل کاربر"),
                          ("buy_vip", "خرید کارت طلایی"), ("confirmgift", "هدیه VIP"),
                          ("admin_edit_price", "تغییر قیمت VIP")):
        if cb.startswith(prefix):
            return label
    return cb.replace("_", " ")[:24]

import bot_backups as _bot_backups  # v4.7 استخراج از main.py — ماژول bot_backups
_bot_backups._bind(globals())  # تزریق اشیاء ربات (bot/db/texts/...)
from bot_backups import (  # noqa: F401 — نام‌های منتقل‌شده به ماژول
    build_daily_report_text, daily_report_loop, _make_db_backup_snapshot, _fmt_size,
    _gzip_db_file, _send_document_with_retry, _next_backup_target, VACUUM_INTERVAL_DAYS,
    _vacuum_due, _maintenance_before_backup, _snapshot_health_and_users, nightly_backup_loop,
    _restore_pending_lock, _restore_pending
)
def _set_restore_pending(val):
    """v3.11: تنظیم امن فلگ انتظار بازیابی (از /restore و پنل ادمین)."""
    global _restore_pending
    with _restore_pending_lock:
        _restore_pending = val

def _validate_sqlite_file(path):
    """بررسی اینکه فایل یک SQLite معتبر با جدول users باشد. خروجی: (ok, n_users یا پیام خطا)."""
    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        if not cur.fetchone():
            conn.close()
            return False, "جدول users یافت نشد — این فایل دیتابیس این ربات نیست."
        n_users = cur.execute("SELECT COUNT(*) AS c FROM users").fetchone()['c']
        conn.close()
        return True, n_users
    except Exception as e:
        return False, str(e)

def _swap_database_with_file(new_db_path):
    """جایگزینی امن دیتابیس فعال با فایل جدید + بازسازی اتصال و کش‌ها.
    رفع باگ Errno 18: rename بین فایل‌سیستم‌های متفاوت (Volume و کانتینر) مجاز نیست —
    از shutil.move استفاده می‌کنیم که cross-device را هندل می‌کند."""
    global db
    old_db = db
    with db._lock:
        # v4.6.2: واتچ‌داگ نمونهٔ قدیمی را متوقف کن تا بعد از بستن conn حلقهٔ خطا نزند
        try:
            old_db._shutdown_watchdog = True
        except Exception:
            pass
        db.conn.close()
        tmp_old = BASE_DIR / "bot_data_old.db"
        try: tmp_old.unlink()
        except Exception: pass
        # پاک کردن WAL/SHM قدیمی قبل از جایگزینی
        try: Path(str(DB_PATH) + "-wal").unlink()
        except Exception: pass
        try: Path(str(DB_PATH) + "-shm").unlink()
        except Exception: pass
        if DB_PATH.exists():
            shutil.move(str(DB_PATH), str(tmp_old))
        shutil.move(str(new_db_path), str(DB_PATH))
        db = Database(str(DB_PATH))
    # ── v4.6.2 (رفع باگ «خطای داخلی سرور» و رتبهٔ غلط مینی‌اپ بعد از /restore):
    # لایهٔ دیتابیس مینی‌اپ (services.db) هنوز کانکشن‌های thread-local به فایل قدیمی
    # (rename شده) داشت و دیتابیس بازیابی‌شده ستون‌های نسخهٔ جدید (مثل last_name،
    # xp و…) را نداشت. بستن همهٔ کانکشن‌ها + اجرای مهاجرت افزایشی روی فایل جدید: ──
    try:
        from services import db as _api_db
        _api_db.close_all()
        _api_db.migrate()
        logger.info("restore: miniapp DB layer resynced (connections reopened + migrate) after swap")
    except Exception:
        logger.error("restore: miniapp DB resync failed", exc_info=True)
    # بارگذاری مجدد تنظیمات وابسته به دیتابیس
    for _days in VIP_PRICES.keys():
        saved = db.get_vip_price(_days)
        if saved and saved > 0:
            VIP_PRICES[_days] = saved
    load_channels_from_db()
    try:
        with _subscription_cache_lock:
            _subscription_cache.clear()
    except Exception:
        pass
    try: tmp_old.unlink()
    except Exception: pass

@bot.message_handler(commands=['restore'])
def restore_cmd(message):
    """فعال‌سازی حالت انتظار برای دریافت فایل bot_data.db — فقط سوپر ادمین."""
    global _restore_pending
    chat_id = message.chat.id
    if int(chat_id) != int(ADMIN_ID):
        # نکتهٔ حیاتی: عملیات بازیابی فقط برای سوپر ادمین مجاز است.
        try:
            bot.reply_to(message, "⛔ این دستور فقط برای سوپر ادمین مجاز است.")
        except Exception:
            pass
        return
    with _restore_pending_lock:
        _restore_pending = True
    try:
        bot.reply_to(message,
            "📤 لطفاً فایل bot_data.db (یا فایل فشردهٔ .gz بکاپ) را همین‌جا ارسال کنید.\n"
            "⏳ منتظر دریافت فایل هستم... (برای لغو: /cancel)")
    except Exception as e:
        logger.error(f"restore_cmd reply error: {e}")

@bot.message_handler(commands=['cancel'], func=lambda m: m.chat.id == ADMIN_ID and _restore_pending)
def restore_cancel_cmd(message):
    """لغو حالت انتظار بازیابی."""
    global _restore_pending
    with _restore_pending_lock:
        _restore_pending = False
    try:
        bot.reply_to(message, "✅ عملیات بازیابی لغو شد.")
    except Exception:
        pass

@bot.message_handler(content_types=['document'], func=lambda m: _restore_pending and m.chat.id == ADMIN_ID)
def restore_receive_document(message):
    """دریافت فایل دیتابیس از سوپر ادمین، اعتبارسنجی و جایگزینی.
    توجه: این هندلر فقط وقتی فعال است که ادمین /restore زده باشد؛ در حالت عادی
    رفتار document ها مثل قبل توسط هندلر پشتیبانی مدیریت می‌شود."""
    global _restore_pending
    chat_id = message.chat.id
    document = message.document
    max_size = 50 * 1024 * 1024  # سقف ۵۰ مگابایت
    if document.file_size and document.file_size > max_size:
        with _restore_pending_lock:
            _restore_pending = False
        try: bot.reply_to(message, "❌ حجم فایل بیش از حد مجاز است (حداکثر ۵۰MB).")
        except Exception: pass
        return
    try:
        status = bot.reply_to(message, "⏳ در حال دریافت و بررسی فایل...")
    except Exception:
        status = None
    try:
        file_info = bot.get_file(document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        # ── v3.23: پشتیبانی از فایل فشردهٔ .gz خروجی بکاپ‌ها ──
        fname = (getattr(document, 'file_name', '') or '').lower()
        if fname.endswith('.gz') or (len(downloaded) > 2 and downloaded[0] == 0x1F and downloaded[1] == 0x8B):
            import gzip as _gzip
            try:
                downloaded = _gzip.decompress(downloaded)
                logger.info("restore: gz file decompressed (%s bytes).", len(downloaded))
            except Exception as _gz_err:
                with _restore_pending_lock:
                    _restore_pending = False
                try: bot.reply_to(message, "❌ فایل فشرده قابل بازکردن نیست (%s)." % _gz_err)
                except Exception: pass
                return
        incoming = BASE_DIR / "restore_incoming.db"
        with open(incoming, 'wb') as f:
            f.write(downloaded)
        ok, info = _validate_sqlite_file(incoming)
        if not ok:
            with _restore_pending_lock:
                _restore_pending = False
            try: incoming.unlink()
            except Exception: pass
            try: bot.reply_to(message, f"❌ فایل نامعتبر است: {info}\nعملیات لغو شد. برای تلاش مجدد /restore را بزنید.", reply_to_message_id=status.message_id if status else None)
            except Exception: pass
            return
        _swap_database_with_file(incoming)
        with _restore_pending_lock:
            _restore_pending = False
        try:
            total_users = to_persian_int(info)
            bot.reply_to(message,
                f"✅ دیتابیس با موفقیت جایگزین شد!\n"
                f"👤 تعداد کاربران بازیابی‌شده: {total_users}\n"
                f"🚀 ربات با اطلاعات قبلی فعال است.",
                reply_to_message_id=status.message_id if status else None)
        except Exception as e:
            logger.error(f"restore success msg error: {e}")
    except Exception as e:
        with _restore_pending_lock:
            _restore_pending = False
        logger.error(f"restore receive error: {e}")
        try: bot.reply_to(message, f"❌ خطا در بازیابی دیتابیس: {e}", reply_to_message_id=status.message_id if status else None)
        except Exception: pass

# ====== وضعیت پخش همگانی (با Lock) ======
broadcast_lock = threading.Lock()
broadcast_mode = False
broadcast_admin_chat = None
broadcast_preview_msg = None
broadcast_started_at = None
broadcast_confirm_deadline = None   # v3.19: ددلاین تأیید پیش‌نمایش (۵ دقیقه)
# دکمه‌های اینلاین اختیاری برای پخش همگانی (None = بدون دکمه)
broadcast_inline_markup = None
# وقتی True است، ادمین در حال وارد کردن تعریف دکمه‌هاست
broadcast_awaiting_buttons = False
# شناسه پیام پیش‌نمایش ارسال‌شده به ادمین — برای پاک‌سازی بعد از تصمیم نهایی
broadcast_preview_sent_msg_id = None
# NOTE: BROADCAST_TIMEOUT از config.py بارگذاری می‌شود؛ اینجا override نکنید

# Flag توقف پخش همگانی — ادمین می‌تواند وسط ارسال آن را متوقف کند
broadcast_stop_flag = threading.Event()

# ====== حالت تبلیغ (Ad Mode) — پیام فضول‌گیری با دکمه‌های تبلیغاتی ======
# سوپرادمین لینک می‌دهد؛ ربات همان قالب پیام «یه فضول روی لینک شما کلیک کرد!» را
# برای همه کاربران می‌فرستد با این تفاوت که تمام دکمه‌ها به لینک تبلیغ اشاره می‌کنند.
broadcast_ad_awaiting_link = False   # در انتظار دریافت لینک از سوپرادمین
broadcast_ad_link = None             # لینک تبلیغ تأییدشده (برای لاگ/نمایش)
broadcast_ad_started_at = None       # زمان ورود به حالت — برای تایم‌اوت انتظار لینک
# پارسر ارسال پخش؛ فقط حالت تبلیغ «Markdown» است (قالب فضول‌گیری بولد دارد)
broadcast_parse_mode = None

def set_broadcast_mode(val, chat=None, msg=None, started=None):
    """تنظیم حالت پخش همگانی.
    هنگام خاموش کردن (val=False)، تمام متغیرهای وابسته از جمله دکمه‌ها و حالت تبلیغ ریست می‌شوند."""
    global broadcast_mode, broadcast_admin_chat, broadcast_preview_msg, broadcast_started_at
    global broadcast_confirm_deadline, broadcast_inline_markup, broadcast_awaiting_buttons
    global broadcast_preview_sent_msg_id
    global broadcast_parse_mode, broadcast_ad_awaiting_link, broadcast_ad_link, broadcast_ad_started_at
    with broadcast_lock:
        broadcast_mode = val
        broadcast_admin_chat = chat
        broadcast_preview_msg = msg
        broadcast_started_at = started
        if not val:
            broadcast_confirm_deadline = None
            broadcast_inline_markup = None
            broadcast_awaiting_buttons = False
            broadcast_preview_sent_msg_id = None
            broadcast_parse_mode = None
            broadcast_ad_awaiting_link = False
            broadcast_ad_link = None
            broadcast_ad_started_at = None

def set_broadcast_inline_markup(markup):
    """تنظیم دکمه‌های اینلاین برای پیام پخش همگانی."""
    global broadcast_inline_markup
    with broadcast_lock:
        broadcast_inline_markup = markup

def set_broadcast_awaiting_buttons(val):
    """تنظیم حالت انتظار برای دریافت تعریف دکمه‌ها از ادمین."""
    global broadcast_awaiting_buttons
    with broadcast_lock:
        broadcast_awaiting_buttons = val

def get_broadcast_inline_markup():
    """گرفتن کپی امن از دکمه‌های اینلاین فعلی پخش همگانی (یا None)."""
    with broadcast_lock:
        return broadcast_inline_markup

def set_broadcast_preview_sent_msg_id(msg_id):
    """ذخیره شناسه پیام پیش‌نمایش برای پاک‌سازی بعدی."""
    global broadcast_preview_sent_msg_id
    with broadcast_lock:
        broadcast_preview_sent_msg_id = msg_id

def get_broadcast_preview_sent_msg_id():
    """گرفتن شناسه پیام پیش‌نمایش."""
    with broadcast_lock:
        return broadcast_preview_sent_msg_id

def set_broadcast_ad_awaiting_link(val):
    """حالت انتظار لینک تبلیغ (Ad Mode) را تنظیم می‌کند."""
    global broadcast_ad_awaiting_link
    with broadcast_lock:
        broadcast_ad_awaiting_link = bool(val)

def get_broadcast_ad_awaiting_link():
    with broadcast_lock:
        return broadcast_ad_awaiting_link

def set_broadcast_ad_started_at(ts):
    """زمان ورود به حالت تبلیغ — برای تایم‌اوت انتظار لینک."""
    global broadcast_ad_started_at
    with broadcast_lock:
        broadcast_ad_started_at = ts

def set_broadcast_ad_link(url):
    global broadcast_ad_link
    with broadcast_lock:
        broadcast_ad_link = url

def get_broadcast_ad_link():
    with broadcast_lock:
        return broadcast_ad_link

def set_broadcast_parse_mode(pm):
    """پارسر ارسال پخش — فقط حالت تبلیغ Markdown نیاز دارد (قالب فضول‌گیری بولد دارد)."""
    global broadcast_parse_mode
    with broadcast_lock:
        broadcast_parse_mode = pm

def get_broadcast_parse_mode():
    with broadcast_lock:
        return broadcast_parse_mode

def parse_button_definitions(text):
    """تبدیل متن تعریف دکمه‌ها به InlineKeyboardMarkup.
    فرمت هر خط:  text|url
    چند خط = چند دکمه (هر کدام در یک ردیف جدا).
    برمی‌گرداند: (True, InlineKeyboardMarkup) یا (False, error_message)
    """
    lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
    if not lines:
        return (False, "❌ هیچ خطی پیدا نشد.\n\nفرمت صحیح:\n`متن دکمه|https://example.com`\n`متن دکمه ۲|https://example2.com`")

    buttons = []
    for i, line in enumerate(lines, 1):
        if '|' not in line:
            return (False, f"❌ خط {to_persian_digits(i)}: جداکننده `|` پیدا نشد.\n\nفرمت: `متن دکمه|https://example.com`")
        parts = line.split('|', 1)
        btn_text = parts[0].strip()
        btn_url = parts[1].strip()
        if not btn_text:
            return (False, f"❌ خط {to_persian_digits(i)}: متن دکمه خالی است.")
        if not btn_url:
            return (False, f"❌ خط {to_persian_digits(i)}: URL دکمه خالی است.")
        if not (btn_url.startswith('http://') or btn_url.startswith('https://')):
            return (False, f"❌ خط {to_persian_digits(i)}: URL باید با `http://` یا `https://` شروع شود.\nدریافت شد: `{escape_md(btn_url)}`")
        buttons.append(types.InlineKeyboardButton(btn_text, url=btn_url))

    if not buttons:
        return (False, "❌ هیچ دکمه معتبری ساخته نشد.")

    # هر دکمه در یک ردیف جدا (row_width=1)
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(*buttons)
    return (True, markup)

def broadcast_preview_keyboard(total_users):
    """کیبورد معمولی پیش‌نمایش پخش همگانی با دکمه‌های کنترلی.
    شامل: مشاهده پیش‌نمایش / افزودن دکمه اینلاین / حذف دکمه‌ها / لغو."""
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True, one_time_keyboard=True)
    markup.add(
        types.KeyboardButton("👁 مشاهده پیش‌نمایش"),
        types.KeyboardButton("➕ افزودن دکمه اینلاین"),
    )
    with broadcast_lock:
        has_buttons = broadcast_inline_markup is not None
    if has_buttons:
        markup.add(types.KeyboardButton("🗑 حذف دکمه‌ها"))
    markup.add(types.KeyboardButton("❌ لغو"))
    return markup

def send_preview_to_admin(chat_id, preview_msg, inline_markup=None):
    """ارسال پیش‌نمایش پیام پخش همگانی به ادمین.
    استراتژی هوشمندانه (همان broadcast):
    - اگه پیام متنی است و دکمه دارد: send_message با reply_markup (one-shot)
    - اگه رسانه است یا بدون دکمه: copy_message + editMessageReplyMarkup

    یک دکمه «✅ تأیید و ارسال به همه» نیز به انتهای دکمه‌ها اضافه می‌شود.
    برمی‌گرداند: message_id پیام پیش‌نمایش یا None در صورت خطا."""
    try:
        # ساختن کیبورد نهایی: دکمه‌های اینلاین تعریف‌شده + دکمه تأیید
        final_markup = types.InlineKeyboardMarkup(row_width=1)
        if inline_markup is not None and inline_markup.keyboard:
            for row in inline_markup.keyboard:
                for btn in row:
                    final_markup.add(btn)
        final_markup.add(types.InlineKeyboardButton(
            "✅ تأیید و ارسال به همه",
            callback_data="broadcast_confirm_send_all"
        ))

        # تشخیص نوع پیام
        is_text = hasattr(preview_msg, 'content_type') and preview_msg.content_type == 'text'
        text_content = preview_msg.text if is_text else None

        # استراتژی 1: پیام متنی با دکمه → one-shot send_message
        if is_text and text_content is not None and inline_markup is not None:
            try:
                sent = bot.send_message(chat_id, text_content, reply_markup=final_markup)
                return sent.message_id if sent and hasattr(sent, 'message_id') else None
            except Exception as e:
                logger.error(f"Preview (text one-shot) error: {e}")
                # fallback به copy_message

        # استراتژی 2: رسانه یا بدون دکمه → copy_message + editMessageReplyMarkup
        sent = bot.copy_message(chat_id, from_chat_id=preview_msg.chat.id,
                                message_id=preview_msg.message_id)
        if not sent or not hasattr(sent, 'message_id'):
            logger.error("Preview: copy_message returned no message_id")
            return None
        preview_msg_id = sent.message_id

        # الصاق دکمه‌ها با editMessageReplyMarkup
        try:
            bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=preview_msg_id,
                reply_markup=final_markup,
            )
        except Exception as e:
            logger.error(f"Preview: editMessageReplyMarkup failed: {e}")

        return preview_msg_id
    except Exception as e:
        logger.error(f"send_preview_to_admin error: {e}")
        return None

def delete_preview_message(chat_id):
    """حذف پیام پیش‌نمایش قبلی ادمین (اگه وجود داره)."""
    msg_id = get_broadcast_preview_sent_msg_id()
    if msg_id:
        try:
            bot.delete_message(chat_id, msg_id)
        except Exception:
            pass
        set_broadcast_preview_sent_msg_id(None)

# ====== حالت تبلیغ (Ad Mode) — broadcast پیام فضول‌گیری با دکمه‌های تبلیغاتی ======

def _build_ad_message(url):
    """ساخت متن و دکمه‌های پیام تبلیغ — دقیقاً در قالب پیام فضول‌گیری اصلی
    («یه فضول روی لینک شما کلیک کرد!») با این تفاوت که تمام دکمه‌ها
    به‌جای کارهای خودشان، لینک تبلیغ را باز می‌کنند."""
    t = datetime.datetime.now().strftime("%Y/%m/%d - %H:%M")
    msg = (f"🔔 *یه فضول روی لینک شما کلیک کرد!*\n"
           f"🕒 {t}\n"
           f"👤 🕵️ فضول ناشناس\n"
           f"🆔 مخفی 🔒\n"
           f"📎 مخفی 🔒")
    # همان خط کنجکاوی پیام اصلی (هویت فضول قفله!)
    try:
        msg += "\n\n" + texts.REVEAL_TEASE
    except Exception:
        pass
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🏷️ لقب دادن", url=url),
        types.InlineKeyboardButton("✉️ پیام ناشناس", url=url),
        types.InlineKeyboardButton("📊 اطلاعات فضول", url=url),
        types.InlineKeyboardButton("🎁 هدیه به فضول", url=url),
        types.InlineKeyboardButton("📋 لیست فضول‌ها", url=url),
        types.InlineKeyboardButton("🏠 خانه", url=url),
    )
    markup.add(types.InlineKeyboardButton("🔓 ببین کیه!", url=url))
    return msg, markup

def _start_ad_broadcast(chat_id, url):
    """نمونهٔ پیام تبلیغ را برای سوپرادمین می‌فرستد و state پیش‌نمایش/تأیید را آماده می‌کند.
    بعد از این تابع، جریان تأیید همان مسیر استاندارد پخش همگانی است
    (دکمهٔ «✅ تأیید و ارسال به همه» روی خود پیام نمونه).
    نکته: parse_mode=Markdown ست می‌شود چون قالب فضول‌گیری بولد دارد و
    broadcast_bot (برخلاف bot اصلی) پارسر پیش‌فرض ندارد."""
    try:
        total_users = len(db.get_broadcast_targets())
        msg_text, ad_markup = _build_ad_message(url)
        set_broadcast_ad_link(url)
        set_broadcast_parse_mode("Markdown")
        # پاک‌سازی پیش‌نمایش قبلی (اگه از جلسهٔ قبل مانده)
        delete_preview_message(chat_id)

        # کیبورد نهایی = دکمه‌های تبلیغ + دکمهٔ تأیید (مثل send_preview_to_admin)
        final_markup = types.InlineKeyboardMarkup(row_width=1)
        for row in ad_markup.keyboard:
            for btn in row:
                final_markup.add(btn)
        final_markup.add(types.InlineKeyboardButton(
            "✅ تأیید و ارسال به همه",
            callback_data="broadcast_confirm_send_all"
        ))

        # ارسال نمونه — خودِ پیام پیش‌نمایش، دقیقاً همان چیزی است که به کاربران می‌رسد
        sent = bot.send_message(chat_id, msg_text, reply_markup=final_markup)
        sent_msg_id = sent.message_id if sent and hasattr(sent, 'message_id') else None

        # آماده‌سازی state استاندارد پخش همگانی (پیش‌نمایش = پیام نمونه)
        set_broadcast_mode(True, chat_id, sent, time.time())
        global broadcast_confirm_deadline
        with broadcast_lock:
            broadcast_confirm_deadline = time.time() + BROADCAST_TIMEOUT
        set_broadcast_inline_markup(ad_markup)
        if sent_msg_id:
            set_broadcast_preview_sent_msg_id(sent_msg_id)

        try:
            bot.send_message(chat_id,
                f"📣 *حالت تبلیغ فعال شد*\n\n"
                f"👆 پیام بالا، نمونهٔ دقیق پیامی است که برای همه ارسال می‌شود.\n"
                f"👥 گیرندگان: {to_persian_digits(total_users)} کاربر\n"
                f"🔗 تمام دکمه‌ها به این لینک اشاره می‌کنند:\n{escape_md(url)}\n\n"
                f"✅ اگر اوکیه، روی «تأیید و ارسال به همه» زیر همان پیام بزنید.\n"
                f"❌ برای لغو، دکمهٔ «لغو» را بزنید.\n"
                f"⏳ اگر تا {BROADCAST_TIMEOUT//60} دقیقه تأیید نکنید، خودکار لغو می‌شود.",
                reply_markup=types.ReplyKeyboardMarkup(
                    row_width=1, resize_keyboard=True, one_time_keyboard=True
                ).add(types.KeyboardButton("❌ لغو")),
                parse_mode="Markdown")
        except Exception as e:
            logger.error(f"ad mode instructions error: {e}")
    except Exception as e:
        logger.error(f"ad broadcast start error: {e}")
        set_broadcast_mode(False)
        try:
            bot.send_message(chat_id, "❌ خطا در ساخت پیام تبلیغ. دوباره تلاش کنید.",
                             reply_markup=admin_panel_back_markup())
        except Exception:
            pass

# ====== پخش همگانی (نسخه بهینه‌شده — Parallel + Smart Routing) ======

def broadcast_safe_edit_text(text, chat_id, message_id, reply_markup=None, **kw):
    """ادیت امن پیام پیشرفت پخش همگانی.
    برخلاف safe_edit_text، در صورت شکست ادیت پیام جدید نمی‌فرستد — چون گزارش پیشرفت
    هر ۵ ثانیه آپدیت می‌شود و ارسال پیام جدید در هر بار، موج پیام اضافی برای ادمین می‌سازد.
    فقط لاگ می‌کند تا thread پخش با خطای ادیت متوقف نشود."""
    if not message_id:
        return
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup, **kw)
    except Exception as e:
        # «message is not modified» بی‌اهمیت است (متن تغییری نکرده)؛ بقیه فقط لاگ
        if 'message is not modified' not in str(e).lower():
            logger.debug(f"broadcast_safe_edit_text: {e}")

# Rate limiter سراسری برای جلوگیری از 429
_broadcast_rate_lock = threading.Lock()
_broadcast_last_send_times = deque()  # زمان‌های ارسال اخیر برای rate limiting

def _rate_limit_wait(max_per_second=25):
    """Rate limiting adaptive: اگه در آخر 1 ثانیه بیش از max_per_second ارسال شده، صبر کن."""
    now = time.time()
    with _broadcast_rate_lock:
        # پاک‌سازی زمان‌های قدیمی‌تر از 1 ثانیه
        while _broadcast_last_send_times and _broadcast_last_send_times[0] < now - 1.0:
            _broadcast_last_send_times.popleft()
        # اگه در آخر 1 ثانیه بیش از حد مجاز ارسال شده، صبر کن
        if len(_broadcast_last_send_times) >= max_per_second:
            wait_time = 1.0 - (now - _broadcast_last_send_times[0])
            if wait_time > 0:
                time.sleep(wait_time)
                now = time.time()
        _broadcast_last_send_times.append(now)

# ====== پخش همگانی (نسخه بهینه‌شده — Parallel + Smart Routing) ======

def _send_broadcast_single(broadcast_bot, uid, from_chat_id, message_id,
                            reply_markup=None, is_text=False, text_content=None,
                            parse_mode=None):
    """ارسال یک پیام broadcast به یک کاربر.

    استراتژی هوشمندانه:
    - اگه پیام متنی است و دکمه دارد: از send_message با reply_markup استفاده می‌کند (one-shot، سریع‌تر)
    - اگه پیام رسانه‌ای است و دکمه دارد: copy_message + editMessageReplyMarkup (دو مرحله، لازم)
    - اگه دکمه ندارد: فقط copy_message (یک مرحله)

    برمی‌گرداند: ('ok' | 'blocked' | 'failed')
    """
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            # Rate limiting
            _rate_limit_wait(max_per_second=25)

            # استراتژی 1: پیام متنی با دکمه → one-shot send_message
            if is_text and text_content is not None and reply_markup is not None:
                try:
                    broadcast_bot.send_message(
                        uid, text_content,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                    )
                    return 'ok'
                except ApiTelegramException as e:
                    if e.error_code == 403:
                        return 'blocked'
                    if e.error_code == 429 and attempt < max_retries:
                        time.sleep(2 ** attempt)  # exponential backoff: 1s, 2s
                        continue
                    raise

            # استراتژی 2: رسانه با دکمه → copy_message + editMessageReplyMarkup
            # استراتژی 3: بدون دکمه → فقط copy_message
            sent = broadcast_bot.copy_message(
                uid,
                from_chat_id=from_chat_id,
                message_id=message_id,
            )

            # الصاق دکمه‌ها با editMessageReplyMarkup (فقط برای رسانه با دکمه)
            if reply_markup is not None and sent and hasattr(sent, 'message_id'):
                try:
                    # هر API call باید rate-limit شود (رسانه+دکمه = ۲ call در هر کاربر)
                    _rate_limit_wait(max_per_second=25)
                    broadcast_bot.edit_message_reply_markup(
                        chat_id=uid,
                        message_id=sent.message_id,
                        reply_markup=reply_markup,
                    )
                except ApiTelegramException as e:
                    # اگه edit ناموفق بود، پیام اصلی هنوز ارسال شده
                    if e.error_code == 429:
                        time.sleep(1)
                        try:
                            broadcast_bot.edit_message_reply_markup(
                                chat_id=uid,
                                message_id=sent.message_id,
                                reply_markup=reply_markup,
                            )
                        except Exception:
                            pass
                    # سایر خطاها غیربحرانی هستند
                except Exception:
                    pass

            return 'ok'

        except ApiTelegramException as e:
            if e.error_code == 403:
                return 'blocked'
            if e.error_code == 429 and attempt < max_retries:
                # Rate limited — exponential backoff
                time.sleep(2 ** attempt)
                continue
            return 'failed'
        except Exception:
            if attempt < max_retries:
                time.sleep(0.5)
                continue
            return 'failed'
    return 'failed'

# ── v3.23: ادامهٔ پخش همگانی بعد از قطع/ری‌استارت (resume) ──
BC_STATE_KEY = "broadcast_resume_state"

def _bc_state_write(admin_chat_id, progress_msg_id, src_chat_id, src_msg_id, total, done, sent, blocked, failed):
    """ثبت وضعیت لحظه‌ای پخش در دیتابیس — بعد از کرش/ری‌استارت قابل ادامه است.
    هر ~۱۰ ثانیه (هم‌زمان با گزارش پیشرفت) و هر ۲۰۰ پیام نوشته می‌شود."""
    try:
        import json as _j
        st = {"active": 1, "admin_chat": int(admin_chat_id or 0), "progress_msg": int(progress_msg_id or 0),
              "src_chat": int(src_chat_id or 0), "src_msg": int(src_msg_id or 0),
              "total": int(total or 0), "done": int(done or 0), "sent": int(sent or 0),
              "blocked": int(blocked or 0), "failed": int(failed or 0)}
        db.set_setting(BC_STATE_KEY, _j.dumps(st))
    except Exception as e:
        logger.error("bc state write error: %s", e)

def _bc_state_clear():
    try:
        db.set_setting(BC_STATE_KEY, "")
    except Exception:
        pass

def _bc_state_read():
    """خواندن وضعیت پخش نیمه‌کاره — فقط اگر active باشد."""
    try:
        raw = db.get_setting(BC_STATE_KEY)
        if not raw:
            return None
        import json as _j
        st = _j.loads(raw)
        if isinstance(st, dict) and st.get("active") == 1:
            return st
    except Exception:
        pass
    return None

def _run_broadcast_async(admin_chat_id, preview_msg, resume_state=None, parse_mode_arg=None):
    """اجرای پخش همگانی در thread جداگانه.
    - نمونه مستقل TeleBot (جدا از ربات اصلی)
    - ارسال موازی با ThreadPoolExecutor + rate limiter (۲۵ پیام/ثانیه)
    - گزارش زنده هر ۵ ثانیه
    - هندلینگ 429 و 403
    - v3.23: resume_state — ادامهٔ پخش نیمه‌کاره بعد از قطع/ری‌استارت
    - fix: در فراخوانی از callback «broadcast_confirm_send_all»، آرگومان سوم می‌تواند
      InlineKeyboardMarkup باشد (نه دیکشنری resume) — چون set_broadcast_mode(False)
      دکمه‌ها را پاک می‌کند، markup قبل از پاک‌شدن گرفته شده و باید همین‌جا منتقل شود.
      اینجا تشخیص داده می‌شود: دیکشنری = state واقعی resume، غیردیکشنری = markup پخش تازه.
    - حالت تبلیغ: parse_mode_arg («Markdown») برای رندر بولد قالب فضول‌گیری منتقل می‌شود."""
    # سازگاری فراخوانی‌ها: تفکیک markup از state واقعی resume
    markup_arg = None
    if resume_state is not None and not isinstance(resume_state, dict):
        markup_arg = resume_state
        resume_state = None
    # رفع باگ: try/except در سطح topLevel تا thread در صورت خطا سایلنت نشود
    try:
        _run_broadcast_async_impl(admin_chat_id, preview_msg, resume_state, markup_arg, parse_mode_arg)
    except Exception as e:
        logger.error(f"Broadcast async fatal error: {e}")
        try:
            broadcast_bot = telebot.TeleBot(TOKEN)
            broadcast_bot.send_message(admin_chat_id,
                f"❌ خطای بحرانی در پخش همگانی: {e}",
                reply_markup=admin_panel_back_markup())
        except Exception:
            pass

def _run_broadcast_async_impl(admin_chat_id, preview_msg, resume_state=None, markup_arg=None, parse_mode_arg=None):
    """پیاده‌سازی واقعی پخش همگانی — v3.23: پشتیبانی ادامه از محل قطع.
    نسخه بهینه‌شده: ThreadPoolExecutor موازی، smart routing برای متن/رسانه.
    markup_arg: دکمه‌های اینلاین منتقل‌شده از callback تأیید (قبل از پاک‌شدن state)."""
    global broadcast_stop_flag
    broadcast_stop_flag.clear()

    # پارسر ارسال — فقط حالت تبلیغ «Markdown» است (قالب فضول‌گیری بولد دارد)
    bc_parse_mode = parse_mode_arg or None

    # ساخت نمونه مستقل TeleBot برای پخش همگانی
    try:
        broadcast_bot = telebot.TeleBot(TOKEN)
    except Exception as e:
        logger.error(f"Cannot create broadcast_bot: {e}")
        return

    # ── v3.23: حالت ادامه (resume) یا شروع تازه ──
    if resume_state:
        try:
            done0 = max(0, int(resume_state.get('done', 0) or 0))
            from_chat_id = int(resume_state.get('src_chat') or admin_chat_id)
            message_id = int(resume_state.get('src_msg') or 0)
            pre_sent = int(resume_state.get('sent', 0) or 0)
            pre_blocked = int(resume_state.get('blocked', 0) or 0)
            pre_failed = int(resume_state.get('failed', 0) or 0)
        except Exception:
            done0, from_chat_id, message_id, pre_sent, pre_blocked, pre_failed = 0, admin_chat_id, 0, 0, 0, 0
        users = db.get_broadcast_targets_offset(done0)
        is_resume = True
        # در حالت resume، اطلاعات dکمه‌ها رو از preview_msg نمی‌گیریم (چون None است)
        # اما برای حفظ رفتار، در resume از دکمه‌ها استفاده نمی‌کنیم (resume معمولاً برای پیام‌های بدون دکمه است)
        current_markup = None
        use_one_shot = False
        text_content = None
    else:
        done0 = 0
        from_chat_id = None
        message_id = None
        pre_sent = pre_blocked = pre_failed = 0
        users = db.get_broadcast_targets()
        is_resume = False
        # تشخیص نوع پیام برای smart routing
        current_markup = get_broadcast_inline_markup()
        if current_markup is None and markup_arg is not None:
            # markup از callback تأیید آمده (قبل از پاک‌شدن state گرفته شده بود)
            current_markup = markup_arg
        is_text = hasattr(preview_msg, 'content_type') and preview_msg.content_type == 'text'
        text_content = preview_msg.text if is_text else None
        use_one_shot = is_text and current_markup is not None and text_content is not None

    if use_one_shot:
        logger.info("Broadcast: using ONE-SHOT send_message strategy (text + buttons)")
    elif current_markup is not None:
        logger.info("Broadcast: using TWO-STEP strategy (copy_message + editMessageReplyMarkup) for media with buttons")
    else:
        logger.info("Broadcast: using copy_message strategy (no buttons)")

    total = done0 + len(users)
    if len(users) == 0:
        _bc_state_clear()
        try:
            broadcast_bot.send_message(admin_chat_id,
                "✅ چیزی از پخش نیمه‌کاره برای ادامه نمانده بود." if is_resume
                else "❌ هیچ کاربر فعالی برای ارسال وجود ندارد.",
                reply_markup=admin_panel_back_markup())
        except: pass
        return

    # منبع کپی — شروع تازه: پیام پیش‌نمایش | ادامه: اطلاعات ذخیره‌شده در دیتابیس
    if not is_resume:
        from_chat_id = preview_msg.chat.id
        message_id = preview_msg.message_id
    if not message_id:
        _bc_state_clear()
        try:
            broadcast_bot.send_message(admin_chat_id, "⚠️ پیام منبع پخش نیمه‌کاره قابل بازیابی نیست — پخش لغو شد.",
                             reply_markup=admin_panel_back_markup())
        except: pass
        return

    # ارسال پیام پیشرفت
    head = "♻️ *ادامهٔ پخش همگانی از محل قطع*" if is_resume else "📢 *شروع پخش همگانی*"
    try:
        progress_msg = broadcast_bot.send_message(admin_chat_id,
            f"{head}\n"
            f"👥 کل گیرنده‌ها: {to_persian_digits(total)}\n"
            f"✅ ارسال موفق: {to_persian_digits(pre_sent)}\n"
            f"📊 پیشرفت: {to_persian_digits(int(done0 * 100 / total) if total else 0)}٪\n"
            f"⏱️ در حال ارسال...",
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("⏹️ توقف ارسال", callback_data="broadcast_stop")
            )
        )
        progress_msg_id = progress_msg.message_id
    except Exception as e:
        logger.error(f"Cannot send progress msg: {e}")
        progress_msg_id = None

    sent_cnt = pre_sent
    blocked_cnt = pre_blocked
    failed_cnt = pre_failed
    start_time = time.time()
    last_update = 0
    processed_this_run = 0
    skipped_cnt = 0

    # آمار شمارش thread-safe
    stats_lock = threading.Lock()
    counters = {'sent': sent_cnt, 'blocked': blocked_cnt, 'failed': failed_cnt, 'processed': 0}

    # v3.23: ثبت وضعیت اولیه برای resume
    _bc_state_write(admin_chat_id, progress_msg_id, from_chat_id, message_id, total, done0, sent_cnt, blocked_cnt, failed_cnt)

    def send_to_user(uid):
        """تابع worker برای ارسال به یک کاربر."""
        if broadcast_stop_flag.is_set():
            return ('skipped', uid)

        result = _send_broadcast_single(
            broadcast_bot, uid, from_chat_id, message_id,
            reply_markup=current_markup,
            is_text=use_one_shot,
            text_content=text_content,
            parse_mode=bc_parse_mode,
        )

        with stats_lock:
            counters['processed'] += 1
            if result == 'ok':
                counters['sent'] += 1
            elif result == 'blocked':
                counters['blocked'] += 1
                try:
                    db.mark_user_blocked_bot(uid)
                except: pass
            else:
                counters['failed'] += 1

        return (result, uid)

    # ارسال موازی با ThreadPoolExecutor
    workers = min(BROADCAST_WORKERS, 16)  # cap at 16 workers

    with ThreadPoolExecutor(max_workers=workers) as executor:
        # Submit all tasks
        futures = {executor.submit(send_to_user, uid): uid for uid in users}

        for future in as_completed(futures):
            if broadcast_stop_flag.is_set():
                # لغو بقیه task ها
                for f in futures:
                    f.cancel()
                skipped_cnt = sum(1 for f in futures if not f.done())
                break

            try:
                result, uid = future.result()
                if result == 'skipped':
                    skipped_cnt += 1
            except Exception as e:
                logger.error(f"Broadcast worker error for uid={futures[future]}: {e}")
                with stats_lock:
                    counters['failed'] += 1
                    counters['processed'] += 1

            processed_this_run += 1
            done_now = done0 + processed_this_run

            # به‌روزرسانی پیام پیشرفت هر ۵ ثانیه + ثبت وضعیت resume
            now = time.time()
            if progress_msg_id and (now - last_update) > 5:
                last_update = now
                with stats_lock:
                    sent_cnt = counters['sent']
                    blocked_cnt = counters['blocked']
                    failed_cnt = counters['failed']
                    processed = done0 + counters['processed']
                pct = int(processed * 100 / total) if total else 100
                elapsed = now - start_time
                speed = (processed - done0) / elapsed if elapsed > 0 else 0
                remaining = (total - processed) / speed if speed > 0 else 0
                try:
                    broadcast_safe_edit_text(
                        f"📢 *پخش همگانی در حال اجرا...*\n"
                        f"👥 کل گیرنده‌ها: {to_persian_digits(total)}\n"
                        f"✅ ارسال موفق: {to_persian_digits(sent_cnt)}\n"
                        f"🚫 بلاک‌شده: {to_persian_digits(blocked_cnt)}\n"
                        f"⚠️ خطا: {to_persian_digits(failed_cnt)}\n"
                        f"📊 پیشرفت: {to_persian_digits(pct)}٪\n"
                        f"⚡️ سرعت: {to_persian_digits(int(speed))} پیام/ثانیه\n"
                        f"⏱️ زمان باقی‌مانده: ~{to_persian_digits(int(remaining))} ثانیه",
                        admin_chat_id, progress_msg_id,
                        reply_markup=types.InlineKeyboardMarkup().add(
                            types.InlineKeyboardButton("⏹️ توقف ارسال", callback_data="broadcast_stop")
                        )
                    )
                except: pass
                # v3.23: ثبت پیشرفت هم‌زمان با گزارش
                _bc_state_write(admin_chat_id, progress_msg_id, from_chat_id, message_id, total, done_now, sent_cnt, blocked_cnt, failed_cnt)
            elif (processed_this_run % 200) == 0:
                # v3.23: ثبت پیشرفت هر ۲۰۰ پیام
                with stats_lock:
                    sent_cnt = counters['sent']
                    blocked_cnt = counters['blocked']
                    failed_cnt = counters['failed']
                _bc_state_write(admin_chat_id, progress_msg_id, from_chat_id, message_id, total, done_now, sent_cnt, blocked_cnt, failed_cnt)

    # اگه توقف نشده، آمار نهایی رو از counters بگیر
    with stats_lock:
        sent_cnt = counters['sent']
        blocked_cnt = counters['blocked']
        failed_cnt = counters['failed']

    elapsed_total = time.time() - start_time
    was_stopped = broadcast_stop_flag.is_set()
    broadcast_stop_flag.clear()
    # v3.23: پایان/توقف پخش — وضعیت resume پاک می‌شود (توقف دستی = تصمیم ادمین)
    _bc_state_clear()

    # حذف پیام پیشرفت
    if progress_msg_id:
        try:
            broadcast_bot.delete_message(admin_chat_id, progress_msg_id)
        except: pass

    # ذخیره آمار در دیتابیس
    success_rate = int(sent_cnt * 100 / total) if total else 0
    try:
        with db._lock:
            db.conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                ("last_broadcast_stats", f"{sent_cnt}/{total} ({success_rate}%)")
            )
            db.conn.commit()
    except: pass
    # v3.23: کش آمار کهنه شده (آخرین پخش) بی‌اعتبار شود
    try:
        db.invalidate_stats_cache()
    except Exception:
        pass

    # گزارش نهایی به ادمین
    summary = (
        f"{'⏹️ پخش همگانی متوقف شد' if was_stopped else '✅ پخش همگانی پایان یافت'}\n"
        f"{'♻️ (از محل قطع قبلی ادامه یافت)' if is_resume else ''}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 کل گیرنده‌ها: {to_persian_digits(total)}\n"
        f"✅ ارسال موفق: {to_persian_digits(sent_cnt)}\n"
        f"🚫 بلاک‌کننده‌ها (کاربرانی که ربات را بلاک کرده‌اند): {to_persian_digits(blocked_cnt)}\n"
        f"⚠️ خطاهای دیگر: {to_persian_digits(failed_cnt)}\n"
        f"⏭️ رد‌شده (به‌خاطر توقف): {to_persian_digits(skipped_cnt)}\n"
        f"📊 نرخ موفقیت: {to_persian_digits(success_rate)}٪\n"
        f"⏱️ زمان کل: {to_persian_digits(int(elapsed_total))} ثانیه\n"
        f"⚡️ سرعت میانگین: {to_persian_digits(int((total - done0) / elapsed_total if elapsed_total > 0 else 0))} پیام/ثانیه\n"
        f"🔧 روش ارسال: {'one-shot (متن)' if use_one_shot else 'copy_message' + (' + edit' if current_markup else '')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 کاربران بلاک‌کننده به‌صورت خودکار از پخش‌های بعدی حذف می‌شوند."
    )
    try:
        broadcast_bot.send_message(admin_chat_id, summary, reply_markup=admin_panel_back_markup())
    except: pass

# ====== سیستم سطح‌بندی XP ======
# XP لازم برای رفتن از سطح (L-1) به L = 100 × L
# XP تجمعی تا سطح L = 100 × L × (L+1) / 2
# پاداش‌ها در config.py تعریف شده‌اند (XP_BONUS_ONE_TIME, XP_RECURRING)

def get_level_title(level):
    """v3.17: نام سطح با ارث‌بری — اگر سطح نام‌دار نبود، نام نزدیک‌ترین سطح نام‌دارِ پایین‌تر
    برگردانده می‌شود (مثلاً سطح ۸۸ → نام سطح ۸۰). خروجی: (title, emoji)"""
    if level is None or level < 1:
        level = 1
    chosen = min(texts.LEVEL_NAMES.keys())
    for k in sorted(texts.LEVEL_NAMES.keys()):
        if k <= level:
            chosen = k
        else:
            break
    return texts.LEVEL_NAMES[chosen]

def get_next_named_level(level):
    """v3.17: اولین سطح نام‌دارِ بالاتر از سطح فعلی (یا None اگر به سقف رسیده)."""
    for k in sorted(texts.LEVEL_NAMES.keys()):
        if k > level:
            return k
    return None

def get_rank_tier(level):
    """برگرداندن (title, emoji) برای یک سطح مشخص — سازگار با فراخوانی‌های قدیمی."""
    return get_level_title(level)

def get_user_display(user_id, name=None):
    """نام نمایشی کاربر با نشان رتبهٔ فعلی.
    v4.4: اگر کاربر نام نمایشی دلخواه (users.display_name) انتخاب کرده باشد،
    همان برای همه نمایش داده می‌شود (گزارش فضول‌گیری، لیدربورد و…)."""
    try:
        _custom = db.get_display_name(user_id)
        if _custom:
            name = sanitize_name(_custom)
    except Exception:
        pass
    if name is None:
        try:
            u = db.get_user_basic(user_id)
            name = u['first_name'] if u and u['first_name'] else "بی‌نام"
        except: name = "بی‌نام"
    level = db.get_user_level_cached(user_id)
    _, emoji = get_rank_tier(level)
    return f"{emoji} {name}" if emoji else name

def get_user_rank_emoji(user_id):
    """فقط ایموجی رتبه برای نمایش کنار نام."""
    level = db.get_user_level_cached(user_id)
    _, emoji = get_rank_tier(level)
    return emoji

def award_xp_with_level_up_notify(user_id, amount, recurring_type=None, bonus_type=None, bonus_amount=None, chat_id=None):
    """
    اعطای XP به کاربر با مدیریت خودکار ارتقای سطح.
    - اگر سطح بالا برود: پیام تبریک با عکس (LEVEL_UP_PHOTO_ID) ارسال می‌کند.
    - بررسی ماموریت‌ها: اگر ماموریتی تکمیل شده باشد، فقط از طریق answer_callback_query
      به‌صورت toast به کاربر اطلاع می‌دهد (برای جلوگیری از شلوغ شدن چت).

    recurring_type: کلید در XP_RECURRING (مثل 'new_distinct_snoop')
    bonus_type: کلید در XP_BONUS_ONE_TIME (مثل 'first_snoop')
    """
    total_xp = 0
    level_old = db.get_user_level_cached(user_id)

    # اعطای XP تکرارشونده
    if recurring_type and recurring_type in XP_RECURRING:
        total_xp += XP_RECURRING[recurring_type]

    # اعطای XP یکباره (فقط اولین بار)
    if bonus_type and bonus_type in XP_BONUS_ONE_TIME:
        awarded, _, _, _ = db.award_bonus_xp(user_id, bonus_type, XP_BONUS_ONE_TIME[bonus_type])
        if awarded:
            total_xp += XP_BONUS_ONE_TIME[bonus_type]

    if total_xp > 0:
        _, level_new, level_old = db.add_xp(user_id, total_xp)
        # بررسی ارتقا — فقط برای ارتقا پیام جداگانه با عکس می‌فرستیم
        if level_new > level_old:
            title, emoji = get_rank_tier(level_new)
            xp_next = db.xp_for_next_level(level_new)
            xp_current = db.get_user_xp(user_id)
            try:
                msg = texts.LEVEL_UP_MESSAGE.format(
                    level=to_persian_digits(level_new),
                    title=title,
                    emoji=emoji,
                    xp_current=to_persian_int(xp_current),
                    xp_next=to_persian_int(xp_next) if xp_next else "نهایتی"
                )
                target_chat = chat_id if chat_id else user_id
                try:
                    # ارسال با عکس (اگر LEVEL_UP_PHOTO_ID تنظیم شده باشد)
                    if LEVEL_UP_PHOTO_ID:
                        try:
                            bot.send_photo(target_chat, LEVEL_UP_PHOTO_ID, caption=msg)
                        except:
                            bot.send_message(target_chat, msg)
                    else:
                        bot.send_message(target_chat, msg)
                except Exception as e:
                    logger.error(f"Level-up notify error: {e}")
            except Exception as e:
                logger.error(f"Level-up message build error: {e}")

    # نکته: _check_and_award_tasks_xp فقط در show_tasks_page و show_task_detail_popup صدا زده می‌شه
    # (نه روی هر اکشن) برای جلوگیری از اسکن ۲۰۰ تسک در هر کلیک


def _check_and_award_tasks_xp(user_id, notify=True):
    """بررسی تمام تسک‌ها — اگر تسکی تکمیل شده:
    1. XP آن را به کاربر اضافه می‌کند.
    2. اگر سطح بالا برود، پیام تبریک با عکس می‌فرستد.
    3. اگر notify=True (اسکنر زمان واقعی): یک پیام خلاصهٔ تکمیل در لحظهٔ انجام ارسال می‌شود.
       اگر notify=False (همگام‌سازی/بازکردن صفحه): بی‌صدا فقط XP اعطا می‌شود (بدون اسپم)."""
    newly_completed = []  # لیست تسک‌های تازه تکمیل‌شده

    for task in tasks_module.TASKS:
        task_id = task["id"]
        # اگر قبلاً این تسک پاداش گرفته، رد کن
        if db.has_bonus(user_id, f"task_{task_id}"):
            continue
        try:
            # بررسی آیا تسک انجام شده
            with db._lock:
                is_done = bool(task["check"](db, user_id))
            if is_done:
                # اعطای XP تسک به‌صورت bonus (یکباره)
                # level_old رو قبل از award ذخیره می‌کنیم تا بعداً چک کنیم
                level_before = db.get_user_level_cached(user_id)
                awarded, xp_new, level_new, _ = db.award_bonus_xp(user_id, f"task_{task_id}", task["xp"])
                if awarded:
                    # v3.24.7: تسک‌های چالش VIP — علاوه بر XP، روز VIP هم هدیه داده می‌شود
                    if task.get("vip_reward"):
                        try:
                            db.add_vip(user_id, int(task["vip_reward"]))
                            db.add_transaction(user_id, "challenge_vip", 0, int(task["vip_reward"]))
                        except Exception as e:
                            logger.error("VIP challenge grant error %s: %s", task_id, e)
                    newly_completed.append(task)
                    # اگر سطح بالا رفت، پیام ارتقا بفرست
                    # v3.11: فقط در حالت زنده (اسکنر) — در حالت بی‌صدا (sync/بازکردن صفحه)
                    # ارسال نمی‌شود تا بعد از هر ری‌استارت سیل پیام ارتقا به همه شروع نشود.
                    if level_new > level_before and notify:
                        try:
                            title, emoji = get_rank_tier(level_new)
                            xp_next = db.xp_for_next_level(level_new)
                            msg = texts.LEVEL_UP_MESSAGE.format(
                                level=to_persian_digits(level_new),
                                title=title,
                                emoji=emoji,
                                xp_current=to_persian_int(xp_new),
                                xp_next=to_persian_int(xp_next) if xp_next else "نهایتی"
                            )
                            try:
                                if LEVEL_UP_PHOTO_ID:
                                    try:
                                        bot.send_photo(user_id, LEVEL_UP_PHOTO_ID, caption=msg)
                                    except:
                                        bot.send_message(user_id, msg)
                                else:
                                    bot.send_message(user_id, msg)
                            except Exception as e:
                                logger.error(f"Level-up notify error: {e}")
                        except Exception as e:
                            logger.error(f"Level-up msg build error: {e}")
        except Exception as e:
            logger.error(f"Task check error for {task_id}: {e}")

    # v3.6: اعلان در لحظهٔ انجام — یک پیام خلاصه (نه رگباری) فقط در حالت notify
    if newly_completed and notify:
        try:
            total_xp = sum(t["xp"] for t in newly_completed)
            # v3.24.7: چالش‌های VIP تکمیل‌شده — اعلان جداگانه و برجسته
            vip_wins = [t for t in newly_completed if t.get("vip_reward")]
            for vt in vip_wins:
                try:
                    bot.send_message(user_id,
                        f"🏆 *چالش VIP تکمیل شد!*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🎯 {vt['name']}\n"
                        f"👑 جایزه: *{to_persian_digits(vt['vip_reward'])} روز VIP* (فعال شد)\n"
                        f"💎 +{to_persian_int(vt['xp'])} XP")
                except Exception as e:
                    logger.error("VIP challenge notify error: %s", e)
            if len(newly_completed) == 1:
                t = newly_completed[0]
                notif = (
                    f"🎉 *ماموریت تکمیل شد!*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📋 {t['name']}\n"
                    f"🎁 پاداش: +{to_persian_int(t['xp'])} XP"
                )
            else:
                notif = (
                    f"🎉 *{to_persian_digits(len(newly_completed))} ماموریت تکمیل شد!*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                )
                for t in newly_completed[:10]:
                    notif += f"✅ {t['name']} (+{to_persian_int(t['xp'])} XP)\n"
                if len(newly_completed) > 10:
                    notif += f"• و {to_persian_digits(len(newly_completed) - 10)} ماموریت دیگر...\n"
                notif += f"\n💎 مجموع پاداش: +{to_persian_int(total_xp)} XP"
            bot.send_message(user_id, notif)
        except Exception as e:
            logger.error(f"Task instant notify error: {e}")
    # صف برای سازگاری — دیگر جایی مصرف نمی‌شود (اعلان همان‌جا ارسال شد)
    if newly_completed:
        try:
            _append_pending_task_notifications(user_id, newly_completed)
        except Exception as e:
            logger.error(f"Append task notifications error: {e}")


# ====== صف نوتیفیکیشن‌های تسک (به‌جای ارسال فوری) ======
_pending_task_notifications = {}  # user_id -> list of task dicts
_pending_task_lock = threading.Lock()

def _append_pending_task_notifications(user_id, tasks_list):
    """v3.6: فقط صف — اعلان فوری در _check_and_award_tasks_xp انجام می‌شود (یک پیام خلاصه)."""
    with _pending_task_lock:
        if user_id not in _pending_task_notifications:
            _pending_task_notifications[user_id] = []
        _pending_task_notifications[user_id].extend(tasks_list)

def _get_and_clear_pending_task_notifications(user_id):
    """گرفتن و پاک کردن نوتیفیکیشن‌های در انتظار کاربر."""
    with _pending_task_lock:
        notifs = _pending_task_notifications.get(user_id, [])
        _pending_task_notifications[user_id] = []
        return notifs

def maybe_daily_login_xp(user_id, chat_id=None):
    """اگر اولین فعالیت روزانه است، XP روزانه می‌دهد."""
    if db.touch_daily_active(user_id):
        award_xp_with_level_up_notify(user_id, 0, recurring_type='daily_login', chat_id=chat_id)

# ====== توابع کمکی ======
def fmt_id(uid, vip, owner_id=None):
    """نمایش شناسه — VIP یا باز شدهٔ تکی (reveal)."""
    if vip:
        return f"*{uid}*"
    if owner_id is not None and db.is_revealed(owner_id, uid):
        return f"*{uid}* 🔓"
    return "🔒 (فقط VIP)"

def fmt_uname(uname, vip, owner_id=None, uid=None):
    if vip:
        return f"@{uname}" if uname else "ندارد"
    if owner_id is not None and uid is not None and db.is_revealed(owner_id, uid):
        return f"@{uname}" if uname else "ندارد"
    return "🔒 (فقط VIP)"

def _add_reveal_button(markup, owner_id, clicker_id, vip_owner):
    """افزودن دکمهٔ «باز کردن هویت» برای غیر-VIP (پرداخت در لحظهٔ اوج)."""
    try:
        if vip_owner:
            return markup
        price_toman = db.get_setting_int("reveal_price", 30000) // 10
        markup.add(
            types.InlineKeyboardButton(f"🔓 باز کردن هویت ({to_persian_digits(price_toman)} تومان)", callback_data=f"reveal_buy_{clicker_id}"),
            types.InlineKeyboardButton("🏅 VIP", callback_data="vip_info"))
    except Exception:
        pass
    return markup

def user_link(uid): return f"ble.ir/{BOT_USERNAME}?start={encode_id(uid)}"


# ====== پشتیبانی و پاسخ ادمین (Thread-Safe) ======
support_lock = threading.Lock()
support_sessions = set()
support_partners = {}
admin_reply = {}

def add_support_session(user_id: int):
    with support_lock:
        support_sessions.add(user_id)

def remove_support_session(user_id: int):
    with support_lock:
        support_sessions.discard(user_id)

def clear_support_session(user_id: int):
    with support_lock:
        support_sessions.discard(user_id)
        support_partners.pop(user_id, None)

def is_support_session(user_id: int) -> bool:
    with support_lock:
        return user_id in support_sessions

def set_support_partner(user_id: int, partner_id: int):
    with support_lock:
        support_partners[user_id] = partner_id

def get_support_partner(user_id: int):
    with support_lock:
        return support_partners.get(user_id)

def pop_support_partner(user_id: int):
    with support_lock:
        return support_partners.pop(user_id, None)

def set_admin_reply(user_id: int, target_id: int):
    with support_lock:
        admin_reply[user_id] = target_id

def get_admin_reply(user_id: int):
    with support_lock:
        return admin_reply.get(user_id)

def pop_admin_reply(user_id: int):
    with support_lock:
        return admin_reply.pop(user_id, None)
    
def get_support_sessions_list():
    """برگرداندن یک کپی از لیست جلسات پشتیبانی (امن برای پیمایش)"""
    with support_lock:
        return list(support_sessions)
    
def is_support_sessions_empty():
    with support_lock:
        return not support_sessions

# ====== توابع اد اجباری ======
# ====== کش عضویت کانال اجباری (۵ دقیقه) ======
_subscription_cache = {}  # user_id -> (is_subscribed: bool, timestamp: float)
_subscription_cache_lock = threading.Lock()
SUBSCRIPTION_CACHE_TTL = 300  # ۵ دقیقه

def _on_channel_target_reached(ch_id, notify=True):
    """v3.21: کانال به هدف جذب رسید — از لیست جوین اجباری حذف + خبر به سوپرادمین.
    (حذف خودش اتمیک داخل record_channel_join انجام شده؛ اینجا فقط پاک‌سازی حافظه و اعلان است)"""
    try:
        if ch_id in CHANNELS:
            CHANNELS.remove(ch_id)
    except Exception:
        pass
    ch_name = channel_info.pop(ch_id, {}).get("name", ch_id)
    broken_channels.discard(ch_id)
    clear_subscription_cache()
    if notify:
        try:
            count = db.get_channel_join_count(ch_id)
            bot.send_message(
                ADMIN_ID,
                "🎯 *هدف جذب تکمیل شد!*\n\n"
                f"📢 کانال: {escape_md(str(ch_name))}\n"
                f"👥 اعضای جذب‌شده: {to_persian_digits(count)}\n\n"
                "✅ این کانال به‌صورت خودکار از لیست جوین اجباری حذف شد و دیگر به کاربران نمایش داده نمی‌شود.",
            )
        except Exception as e:
            logger.error("notify channel target reached failed: %s", e)

def is_subscribed(user_id):
    if not CHANNELS:
        return True

    # بررسی کش
    now = time.time()
    with _subscription_cache_lock:
        cached = _subscription_cache.get(user_id)
        if cached:
            is_sub, ts = cached
            if now - ts < SUBSCRIPTION_CACHE_TTL:
                return is_sub

    # چک واقعی — روی کپی پیمایش می‌کنیم چون در صورت تکمیل هدف، کانال از لیست حذف می‌شود
    for ch_id in list(CHANNELS):
        try:
            member = bot.get_chat_member(_api_ch_id(ch_id), user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                # کش کردن نتیجه (غیرعضو)
                with _subscription_cache_lock:
                    _subscription_cache[user_id] = (False, now)
                return False
            # v3.21: اگر کانال با همین عضویت به هدف جذبش رسید، خودکار حذف می‌شود
            try:
                _done = db.record_channel_join(user_id, ch_id)
            except Exception:
                _done = None
            if _done:
                _on_channel_target_reached(ch_id)
                continue

        except ApiTelegramException as e:
            # کاربر در کانال عضو نیست (عادی)
            if e.error_code == 400 and 'user not found' in str(e).lower():
                with _subscription_cache_lock:
                    _subscription_cache[user_id] = (False, now)
                return False

            # ربات به اعضا دسترسی ندارد (ادمین نیست)
            if e.error_code == 403:
                # فقط یک بار به ادمین اطلاع بده
                if ch_id not in broken_channels:
                    broken_channels.add(ch_id)
                    try:
                        bot.send_message(
                            ADMIN_ID,
                            f"⚠️ ربات نمی‌تواند اعضای کانال {ch_id} را بررسی کند (خطای 403).\n"
                            "ربات باید در کانال **ادمین** باشد.\n"
                            "تا زمان رفع مشکل، عضویت در این کانال اجباری است."
                        )
                    except:
                        pass
                # کاربر را غیرعضو فرض کن
                with _subscription_cache_lock:
                    _subscription_cache[user_id] = (False, now)
                return False

            # رفع باگ: سایر خطاهای API → غیرعضو، اما کش نکنیم (ممکن است transient باشد)
            logger.error(f"API error checking channel {ch_id}: {e}")
            return False

        except Exception as e:
            # رفع باگ: خطای شبکه و ... → غیرعضو، اما کش نکنیم تا در تلاش بعدی دوباره چک شود
            logger.error(f"General error checking channel {ch_id}: {e}")
            return False

    # همه چک‌ها موفق بود → عضو است
    with _subscription_cache_lock:
        _subscription_cache[user_id] = (True, now)
    return True

def clear_subscription_cache(user_id=None):
    """پاک کردن کش عضویت (برای وقتی کاربر روی «بررسی عضویت» می‌زنه)."""
    with _subscription_cache_lock:
        if user_id:
            _subscription_cache.pop(user_id, None)
        else:
            _subscription_cache.clear()

def build_channel_keyboard(original_callback, user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    any_unjoined = False
    for ch_id in list(CHANNELS):  # v3.21: کپی — ممکن است کانالی حین چک حذف شود
        is_member = False
        try:
            member = bot.get_chat_member(_api_ch_id(ch_id), user_id)
            if member.status in ['member', 'administrator', 'creator']:
                # v3.21: اگر کانال با همین عضویت به هدف جذبش رسید، خودکار حذف می‌شود
                try:
                    _done = db.record_channel_join(user_id, ch_id)
                except Exception:
                    _done = None
                if _done:
                    _on_channel_target_reached(ch_id)
                is_member = True
        except:
            pass    # اگر خطا داد، فرض می‌کنیم عضو نیست و کانال را نشان می‌دهیم

        if is_member:
            continue    # عضو است – نمایش نده

        any_unjoined = True
        info = channel_info.get(ch_id, {})
        ch_name = info.get("name", ch_id)
        ch_link = info.get("link")
        if not ch_link:
            # v4.7 (باگ اد اجباری): شناسهٔ متنی (با یا بدون @) → لینک عمومی
            # ble.ir/<username>؛ فقط شناسهٔ عددی به joinchat می‌رود.
            _aid = _api_ch_id(ch_id)
            if _aid.startswith("@"):
                ch_link = f"https://ble.ir/{_aid[1:]}"
            elif _aid.startswith("-") and _aid[1:].isdigit():
                ch_link = f"https://ble.ir/joinchat/{ch_id}"
            else:
                ch_link = f"https://ble.ir/{ch_id}"
        markup.add(types.InlineKeyboardButton(f"📢 {ch_name}", url=ch_link))

    if any_unjoined:
        markup.add(types.InlineKeyboardButton(texts.FORCE_JOIN_BUTTON_CHECK, callback_data=f"checkjoin_{original_callback}"))
        return markup
    return None


def vip_info_text():
    prices_lines = "\n".join(
        f"• {vip_plan_label(days)} ({to_persian_digits(days)} روز): {fmt_amount_toman(amount)}"
        for days, amount in VIP_PRICES.items()
    )
    return (
        "🏅 *اشتراک VIP کارآگاهی*\n\n"
        "قابلیت‌های ویژه:\n"
        "• 🆔 دیدن شناسه و آیدی فضول‌ها\n"
        "• ✉️ پیام ناشناس نامحدود (کاربران عادی فقط ۱ پیام در روز)\n"
        "• 🎭 نقاب کارآگاهی هنگام ارسال پیام ناشناس\n"
        "• 📝 تنظیم متن و عکس خوش‌آمدگویی برای فضول‌ها\n"
        "• 🎰 چرخ شانس روزانه با جوایز واقعی\n"
        "• 📊 آنالیز حرفه‌ای تله (ساعات اوج، رشد، رتبه)\n"
        "• 🕳️ تله‌های چندگانه (چند لینک همزمان)\n"
        "• 🎁 هدیه‌دادن روزهای VIP به دوستان\n"
        "• 👑 تاج طلایی کنار نام در تالار شکارچیان\n\n"
        f"💰 قیمت اشتراک:\n{prices_lines}\n\n"
        "🔍 یکی از کارآگاهان ویژه شو!"
    )

def _vip_gold_features():
    """v3.7: خطوط امتیازهای کارت طلایی (مشترک بین دو حالت)."""
    return (
        "✦ شناسه و آیدی فضول‌ها 🆔\n"
        "✦ پیام ناشناس نامحدود ✉️\n"
        "✦ نقاب کارآگاهی اختصاصی 🎭\n"
        "✦ خوش‌آمدگویی اختصاصی 📝\n"
        "✦ تله‌های چندگانه 🕳️\n"
        "✦ آنالیز حرفه‌ای تله 📊\n"
        "✦ چرخ شانس روزانه 🎰\n"
        "✦ هدیه‌دادن روزهای VIP 🎁\n"
        "✦ تاج طلایی در تالار شکارچیان 👑"
    )

def _price_comparison_line():
    """v4.4: خط مقایسهٔ قیمت هوشمند — «۵ هویت تکی = X تومان؛ VIP کامل ماه = Y تومان».
    همهٔ مبالغ از تنظیمات زندهٔ ادمین (بدون هاردکد)."""
    try:
        from services import bot_settings as _bs
        _cmp = _bs.price_comparison()
        if not _cmp:
            return ""
        return ("\n💡 *مقایسهٔ هوشمند:* "
                f"{to_persian_digits(_cmp['singles'])} هویتِ تکی = {fmt_amount_toman(_cmp['singles_total'] * 10)}؛\n"
                f"👑 VIP کامل ماه فقط {fmt_amount_toman(_cmp['month_price'] * 10)} — {to_persian_digits(_cmp['save_pct'])}٪ ارزان‌تر!\n")
    except Exception:
        return ""


def build_vip_gold_menu(user_id):
    """v3.7: منوی «کارت طلایی» — ظاهر لوکس و کاملاً متمایز از منوی عادی.
    خروجی: (متن, کیبورد, فعال؟)"""
    prices_lines = "\n".join(
        f"🔹 {vip_plan_label(days)} ({to_persian_digits(days)} روز) — {fmt_amount_toman(amount)}"
        for days, amount in VIP_PRICES.items()
    )
    header = (
        "👑 ━━━━━━━━━━━━━━ 👑\n"
        "🏅 *کارت طلایی کارآگاهی*\n"
        "👑 ━━━━━━━━━━━━━━ 👑"
    )
    features = _vip_gold_features()
    is_active = db.is_vip(user_id)
    if is_active:
        days = db.get_vip_days_left(user_id)
        if days == 0:
            status_block = (
                "✅ کارت طلایی تو فعال است\n"
                "⏳ ⚠️ امروز آخرین روز اعتبار کارت توست!"
            )
        else:
            exp_date = db.get_vip_expire_date(user_id)
            exp_str = shamsi_date(exp_date) if exp_date else ""
            exp_line = f"\n📅 اعتبار تا: {exp_str}" if exp_str else ""
            status_block = (
                "✅ کارت طلایی تو فعال است\n"
                f"⏳ اعتبار: {to_persian_digits(days)} روز باقی‌مانده"
                + exp_line
            )
        # وضعیت چرخ شانس امروز (اگر ادمین روشن کرده باشد)
        wheel_line = ""
        wheel_on = True
        try:
            wheel_on = db.get_setting_int("wheel_enabled", 1) == 1
            if wheel_on:
                today_t = datetime.datetime.now(TEHRAN_TZ).date().isoformat()
                if db.get_last_wheel_date(user_id) == today_t:
                    wheel_line = "\n🎰 چرخ شانس: امروز چرخیدی — فردا بیا!"
                else:
                    wheel_line = "\n🎰 چرخ شانس: جایزهٔ امروزت منتظر توست!"
        except Exception:
            wheel_line = ""
        text = (
            f"{header}\n\n"
            f"{status_block}{wheel_line}\n\n"
            "✨ امتیازهای اختصاصی تو:\n"
            f"{features}\n\n"
            "🛒 کارتت را قبل از پایان تمدید کن تا تاجت نخوابد!"
        )
        m = types.InlineKeyboardMarkup(row_width=2)
        if wheel_on:
            m.add(types.InlineKeyboardButton("🎁 پاداش‌ها", callback_data="rewards_menu"))
        m.add(types.InlineKeyboardButton("✨ قابلیت‌های ویژه", callback_data="vip_features"),
              types.InlineKeyboardButton("📊 آنالیز تله", callback_data="trap_analytics"))
        m.add(types.InlineKeyboardButton("🕳️ تله‌های من", callback_data="my_traps"),
              types.InlineKeyboardButton("🎁 هدیهٔ روزهای VIP", callback_data="gvip_menu"))
        m.add(types.InlineKeyboardButton("🛒 تمدید کارت", callback_data="buy_vip_menu"),
              types.InlineKeyboardButton("👑 تالار شکارچیان", callback_data="leaderboard"))
        m.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
        return text, m, True
    # حالت غیر-VIP: نمایش فروش‌محور
    text = (
        f"{header}\n\n"
        "⚠️ کارت طلایی تو غیرفعال است\n\n"
        "با کارت طلایی باز می‌شود:\n"
        f"{features}\n\n"
        "💰 پلن‌های کارت طلایی:\n"
        f"{prices_lines}\n"
        f"{_price_comparison_line()}\n"
        "✨ کارآگاه ویژه شو و همه‌چیز را باز کن!"
    )
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("💠 فعال‌سازی کارت طلایی", callback_data="buy_vip_menu"))
    m.add(types.InlineKeyboardButton("✨ قابلیت‌های ویژه", callback_data="vip_features"),
          types.InlineKeyboardButton("👑 تالار شکارچیان", callback_data="leaderboard"))
    m.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
    return text, m, False

def vip_status_display(user_id):
    if not db.is_vip(user_id):
        return False, "غیرفعال"
    days = db.get_vip_days_left(user_id)
    if days == 0:
        return True, "فعال 🏅 (امروز آخرین روز)"
    else:
        return True, f"فعال 🏅 ({to_persian_digits(days)} روز اعتبار باقی‌مانده)"

def main_menu(user_id=None):
    # v3.8: دو چیدمان مجزا — VIPها: «میزکار کارآگاه» | عادی‌ها: «ویترین کارت طلایی»
    m = types.InlineKeyboardMarkup(row_width=2)
    # وضعیت VIP کاربر
    is_vip_user = False
    try:
        is_vip_user = bool(user_id) and db.is_vip(user_id)
    except Exception:
        is_vip_user = False
    if is_vip_user:
        # ── چیدمان VIP (طرح ۲ کاربر) ──
        # سطر ۱: دکمهٔ شیشه‌ای — تنها (کالبک: نمایش روز و ساعت باقی‌مانده)
        m.add(types.InlineKeyboardButton("⚜️VIP⚜️", callback_data="vip_time_left"))
        # سطر ۲: قهرمان تمام‌عرض — ابزار اصلی شکار
        m.add(types.InlineKeyboardButton("🔍 تلهٔ من", callback_data="my_link_show"))
        # سطر ۳: شکار و رتبه
        m.add(
            types.InlineKeyboardButton("📋 لیست فضول‌ها", callback_data="snooplist_page_1"),
            types.InlineKeyboardButton("⭐ ستاره‌ها", callback_data="leaderboard"),
        )
        # سطر ۴: پیشرفت و پاداش — همهٔ جوایز زیر یک دکمه (v3.17)
        m.add(
            types.InlineKeyboardButton("🎯 ماموریت‌ها", callback_data="tasks_page_1"),
            types.InlineKeyboardButton("🎁 پاداش‌ها", callback_data="rewards_menu"),
        )
        # سطر ۵: کارت طلایی و اطلاعات
        m.add(
            types.InlineKeyboardButton("👑 کارت طلایی", callback_data="vip_info"),
            types.InlineKeyboardButton("ℹ️ اطلاعات من", callback_data="my_info"),
        )
        # سطر ۶: اطلاع‌رسانی
        m.add(
            types.InlineKeyboardButton("📖 راهنما", callback_data="help"),
            types.InlineKeyboardButton("📞 پشتیبانی", callback_data="support"),
        )
    else:
        # ── چیدمان عادی (گزینهٔ ۲ کاربر — فروش‌محور) ──
        # سطر ۱: CTA تمام‌عرض
        m.add(types.InlineKeyboardButton("💎 فعال‌سازی کارت طلایی", callback_data="buy_vip_menu"))
        # سطر ۲: شکار
        m.add(
            types.InlineKeyboardButton("🔍 تلهٔ من", callback_data="my_link_show"),
            types.InlineKeyboardButton("📋 لیست فضول‌ها", callback_data="snooplist_page_1"),
        )
        # سطر ۳: پیشرفت
        m.add(
            types.InlineKeyboardButton("🎯 ماموریت‌ها", callback_data="tasks_page_1"),
            types.InlineKeyboardButton("⭐ ستاره‌ها", callback_data="leaderboard"),
        )
        # سطر ۴: پاداش و اطلاعات — همهٔ جوایز زیر یک دکمه (v3.17)
        m.add(
            types.InlineKeyboardButton("🎁 پاداش‌ها", callback_data="rewards_menu"),
            types.InlineKeyboardButton("ℹ️ اطلاعات من", callback_data="my_info"),
        )
        # سطر ۵: کمک
        m.add(
            types.InlineKeyboardButton("📖 راهنما", callback_data="help"),
            types.InlineKeyboardButton("📞 پشتیبانی", callback_data="support"),
        )
    # دکمهٔ چالش فضول‌گیر برتر — فقط وقتی ادمین فعال کرده باشد (زمان‌بندی‌شده یا در جریان) (v3.18)
    try:
        ch_status = db.get_setting("challenge_status", "") or ""
    except Exception:
        ch_status = ""
    if ch_status in ("scheduled", "active"):
        m.add(types.InlineKeyboardButton("🏆 فضول‌گیر برتر", callback_data="challenge_info"))
    if user_id == ADMIN_ID:
        m.add(types.InlineKeyboardButton("🔐 پنل ادمین", callback_data="admin_panel"))
    # v4.0 (fozol-pro): دکمهٔ شیشه‌ای مینی‌اپ — آخرین سطر منوی اصلی
    try:
        from bot_integration import append_webapp_button
        append_webapp_button(m)
    except Exception:
        pass
    return m

def home_markup():
    return types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))

def cancel_markup():
    return types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("❌ انصراف", callback_data="cancel_state"))

def admin_panel_back_markup():
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(types.InlineKeyboardButton("🔐 پنل ادمین", callback_data="admin_panel"))
    m.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
    return m

def vip_menu_button():
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(types.InlineKeyboardButton("👑 بازگشت به کارت طلایی", callback_data="vip_info"))
    m.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
    return m

VIP_EXPIRED_MSG = (
    "⛔ اشتراک VIP شما به پایان رسیده، بنابراین این قابلیت در حال حاضر غیرفعال است.\n"
    "👑 تنظیمات قبلی شما (در صورت وجود) حذف نشده‌اند و به‌محض فعال شدن دوباره‌ی VIP، خودکار فعال می‌شوند."
)

def _build_home_text_inner(user_id):
    """ساخت متن پویای خانه بر اساس وضعیت کاربر.
    اولویت: VIP > returning user > recent clicks > no clicks > new user."""
    try:
        u = db.get_user_basic(user_id)
        name = u['first_name'] if u and u['first_name'] else "دوست"
    except:
        name = "دوست"

    # اگه کاربر جدید (سطح ۱ و XP=0 و بدون کلیک) → حالت ۱
    level = db.get_user_level_cached(user_id)
    xp = db.get_user_xp(user_id)
    total_clicks = db.get_clicks_count(user_id)
    snoop_count = db.get_distinct_snoop_count(user_id)
    today_clicks = db.get_today_clicks_count(user_id)
    is_vip = db.is_vip(user_id)
    vip_days = db.get_vip_days_left(user_id) if is_vip else 0

    # محاسبه روزهای گذشته از آخرین فعالیت
    try:
        last_active = db.conn.execute(
            "SELECT last_active_date FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        days_ago = None
        if last_active and last_active['last_active_date']:
            from datetime import date as dt_date
            last_date = dt_date.fromisoformat(last_active['last_active_date'])
            today = dt_date.today()
            days_ago = (today - last_date).days
    except:
        days_ago = None

    # محاسبه کلیک‌های جدید از آخرین فعالیت
    new_clicks = 0
    if days_ago and days_ago > 0:
        try:
            # کلیک‌های دریافتی در days_ago روز گذشته
            row = db.conn.execute(
                "SELECT COUNT(*) as c FROM clicks WHERE owner_id=? AND date(clicked_at) >= date('now', ?)",
                (user_id, f'-{days_ago} days')
            ).fetchone()
            new_clicks = row['c'] if row else 0
        except:
            new_clicks = 0

    title, emoji = get_rank_tier(level)

    if is_vip:
        # v3.8: حالت ۴ — VIP: متن «درگاه کارآگاه ویژه» (روز آخر اعتبار هم پوشش داده می‌شود)
        if vip_days > 0:
            days_str = to_persian_digits(vip_days) + " روز"
        else:
            days_str = "امروز آخرین روز!"
        try:
            _streak = db.get_streak(user_id) or 0
        except Exception:
            _streak = 0
        if _streak >= 2:
            streak_line = "🔥 استریک روزانه: " + to_persian_digits(_streak) + " روز — امروز هم بیا تا نشکنه!\n"
        else:
            streak_line = ""
        return texts.HOME_VIP_GOLD.format(
            name=escape_md(name),
            level=to_persian_digits(level),
            title=title,
            snoop_count=to_persian_int(snoop_count),
            total_clicks=to_persian_int(total_clicks),
            days=days_str,
            streak_line=streak_line
        )
    elif days_ago and days_ago >= 7 and new_clicks > 0:
        # حالت ۵: کاربر قدیمی برگشته
        return texts.HOME_RETURNING_USER.format(
            name=escape_md(name),
            days_ago=to_persian_digits(days_ago),
            level=to_persian_digits(level),
            title=title,
            snoop_count=to_persian_int(snoop_count),
            total_clicks=to_persian_int(total_clicks),
            vip_status=f"فعال ({to_persian_digits(vip_days)} روز)" if is_vip else "غیرفعال",
            new_clicks=to_persian_int(new_clicks)
        )
    elif today_clicks > 0:
        # حالت ۳: کلیک‌های اخیر
        vip_status = f"فعال ({to_persian_digits(vip_days)} روز)" if is_vip else "غیرفعال"
        return texts.HOME_WITH_RECENT_CLICKS.format(
            name=escape_md(name),
            level=to_persian_digits(level),
            title=title,
            snoop_count=to_persian_int(snoop_count),
            today_clicks=to_persian_int(today_clicks),
            total_clicks=to_persian_int(total_clicks),
            vip_status=vip_status
        )
    elif total_clicks == 0 and level == 1 and xp == 0:
        # حالت ۱: کاربر جدید
        return texts.HOME_NEW_USER.format(name=escape_md(name))
    else:
        # حالت ۲: تله فعال ولی بدون کلیک اخیر
        vip_status = f"فعال ({to_persian_digits(vip_days)} روز)" if is_vip else "غیرفعال"
        return texts.HOME_NO_CLICKS.format(
            name=escape_md(name),
            level=to_persian_digits(level),
            title=title,
            vip_status=vip_status
        )


def build_dynamic_home_text(user_id):
    """متن خانه + خط استریک روزانه."""
    text = _build_home_text_inner(user_id)
    try:
        streak = db.get_streak(user_id)
        if streak >= 2:
            text += "\n\n🔥 استریک روزانه: " + to_persian_digits(streak) + " روز پیاپی — امروز هم بیا تا نشکنه!"
    except Exception:
        pass
    # v4.4: شمارندهٔ زندهٔ فضول‌های قفل‌شده — فقط برای کاربر عادی؛ هیچ اطلاعات هویتی
    # (نام/کد/زمان) فاش نمی‌شود، فقط عدد واقعی فضول‌های یکتا.
    try:
        if not db.is_vip(user_id):
            locked = db.get_distinct_snoop_count(user_id) or 0
            if locked > 0:
                text += ("\n\n🔒 همین الان " + to_persian_int(locked) + " فضولِ قفل‌شده داری — "
                         "با کارت طلایی همه باز می‌شوند!")
    except Exception:
        pass
    # v3.8: تبلیغ کارت طلایی — فقط برای کاربران عادی (انتخاب کاربر: گزینهٔ ۲)
    try:
        if not db.is_vip(user_id):
            text += "\n\n✨ می‌دونستی با «کارت طلایی» هر روز چرخ شانس، تلهٔ چندگانه و آنالیز حرفه‌ای داری؟\n——————————————"
    except Exception:
        pass
    return text


def show_main_menu_for_callback(call, chat_id, user_id):
    home_text = build_dynamic_home_text(user_id)
    # اگه پیام عکس یا ویدیو باشه، edit_text خراب می‌شه — باید delete+resend کنیم
    if call.message.content_type in ('photo', 'video', 'document', 'animation'):
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        bot.send_message(chat_id, home_text, reply_markup=main_menu(user_id))
    else:
        try:
            safe_edit_text(home_text, chat_id, call.message.message_id, reply_markup=main_menu(user_id))
        except Exception:
            bot.send_message(chat_id, home_text, reply_markup=main_menu(user_id))

# ایموجی‌های نقاب کارآگاهی (تم نوآر)
MASK_EMOJIS = ["🎭", "🔍", "🕯️", "🌙", "📂", "🔦", "🕵️", "👁️", "🗒️", "📇", "🧥", "🎖️", "🏅", "📰", "☕", "🚬"]

# ====== توابع دستیار ادمین ======
def admin_panel_markup():
    """منوی اصلی ادمین — دسته‌بندی‌شده (v3.4)."""
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        types.InlineKeyboardButton("👥 کاربران", callback_data="admin_cat_users"),
        types.InlineKeyboardButton("👑 VIP و مالی", callback_data="admin_cat_vip"),
        types.InlineKeyboardButton("🎁 هدیه و پاداش", callback_data="admin_cat_gift"),
        types.InlineKeyboardButton("📢 اطلاع‌رسانی", callback_data="admin_cat_broadcast"),
        types.InlineKeyboardButton("🏆 رویدادها و آمار", callback_data="admin_cat_events"),
        types.InlineKeyboardButton("⚙️ یادآورها و تنظیمات", callback_data="admin_cat_reminders"),
        types.InlineKeyboardButton("🗄 دیتابیس", callback_data="admin_cat_db"),
    )
    m.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
    return m

def _admin_back_panel():
    return types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel"))

def admin_cat_users_markup():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        types.InlineKeyboardButton("🔍 جستجوی کاربر", callback_data="admin_search_user"),
        types.InlineKeyboardButton("👥 لیست کاربران", callback_data="admin_userlist_invites_1"),
    )
    m.add(types.InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel"))
    return m

def admin_cat_vip_markup():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        types.InlineKeyboardButton("💰 تراکنش‌ها", callback_data="admin_transactions_page_1"),
        types.InlineKeyboardButton("📊 آمار VIP", callback_data="admin_vip_stats"),
        types.InlineKeyboardButton("💵 تغییر قیمت VIP", callback_data="admin_vip_prices"),
        types.InlineKeyboardButton("⚙️ مدیریت VIP", callback_data="admin_vip"),
        types.InlineKeyboardButton("🔓 قیمت باز کردن پروفایل", callback_data="admin_set_reveal_price"),
        types.InlineKeyboardButton("🤫 قیمت حفظ آبرو تله", callback_data="admin_set_saveface_price"),
    )
    m.add(types.InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel"))
    return m

def admin_cat_gift_markup():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        types.InlineKeyboardButton("🎁 کدهای هدیه", callback_data="admin_gift_list"),
        types.InlineKeyboardButton("➕ کد هدیه جدید", callback_data="admin_new_gift"),
        types.InlineKeyboardButton("🚪 هدیهٔ ورود (روزها)", callback_data="admin_set_trial"),
    )
    try:
        wheel_on = (db.get_setting_int("wheel_enabled", 1) == 1)
        m.add(types.InlineKeyboardButton(f"🎰 چرخ شانس: {'روشن ✅' if wheel_on else 'خاموش ❌'}", callback_data="admin_wheel_toggle"))
    except Exception:
        pass
    m.add(types.InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel"))
    return m

def admin_cat_broadcast_markup():
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(types.InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast"))
    m.add(types.InlineKeyboardButton("📣 حالت تبلیغ", callback_data="admin_ad_mode"))
    m.add(types.InlineKeyboardButton("📢 اد اجباری", callback_data="admin_forced_ads"))
    m.add(types.InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel"))
    return m

def admin_cat_events_markup():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        types.InlineKeyboardButton("🏆 چالش فضول‌گیر برتر", callback_data="admin_challenge_menu"),
        types.InlineKeyboardButton("📊 آمار کل", callback_data="admin_daily"),
        types.InlineKeyboardButton("📊 آرشیو روزانه", callback_data="admin_daily_archive"),
        types.InlineKeyboardButton("👥 آمار کاربران", callback_data="admin_user_stats"),
        types.InlineKeyboardButton("📬 لاگ ناشناس", callback_data="admin_anonlog_page_1"),
    )
    m.add(types.InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel"))
    return m

def admin_cat_reminders_markup():
    reminder_on = db.get_setting_int("smart_reminder_enabled", 1) == 1
    weekly_on = db.get_setting_int("weekly_report_enabled", 1) == 1
    ch_status = get_challenge_status()
    maint_on = db.get_setting_int("maintenance_mode", 0) == 1
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(types.InlineKeyboardButton(f"🚧 حالت نگهداری: {'روشن ✅' if maint_on else 'خاموش'}", callback_data="admin_maint_toggle"))
    m.add(types.InlineKeyboardButton(f"🔧 یادآور هوشمند: {'روشن' if reminder_on else 'خاموش'}", callback_data="admin_toggle_reminder"))
    m.add(types.InlineKeyboardButton(f"📊 گزارش هفتگی: {'روشن' if weekly_on else 'خاموش'}", callback_data="admin_toggle_weekly"))
    m.add(types.InlineKeyboardButton("📅 روز گزارش هفتگی", callback_data="admin_set_weekly_day"))
    m.add(types.InlineKeyboardButton("⏰ ساعت گزارش هفتگی", callback_data="admin_set_weekly_hour"))
    m.add(types.InlineKeyboardButton(f"🚪 هدیهٔ ورود: {to_persian_digits(db.get_setting_int('trial_days', 3))} روز", callback_data="admin_set_trial"))
    m.add(types.InlineKeyboardButton("⚙️ نمای کلی تنظیمات", callback_data="admin_settings_overview"))
    m.add(types.InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel"))
    return m

def admin_cat_db_markup():
    """v3.11: بخش دیتابیس — بکاپ فوری، بازیابی از فایل، بکاپ خودکار نیمه‌شب."""
    auto_on = db.get_setting_int("auto_backup_enabled", 1) == 1
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(types.InlineKeyboardButton("💾 بکاپ فوری دیتابیس", callback_data="admin_backup_now"))
    m.add(types.InlineKeyboardButton("♻️ بازیابی دیتابیس از فایل", callback_data="admin_restore_start"))
    m.add(types.InlineKeyboardButton(
        "⏰ بکاپ خودکار (۰۳:۳۰ بامداد): " + ("روشن ✅" if auto_on else "خاموش ❌"),
        callback_data="admin_autoback_toggle"))
    m.add(types.InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel"))
    return m


def _admin_backup_now_job(chat_id):
    """v3.11: اسنپ‌شات امن SQLite (بدون قطع اتصال اصلی) → فشرده‌سازی gzip → ارسال فایل به ادمین.
    v3.23: رفع ارور «write operation timed out» — فایل فشرده (۵~۱۰ برابر کوچک‌تر) +
    timeout سراسری ۹۰ ثانیه + تلاش مجدد ۳ باره + گزارش سلامت و حجم."""
    backup_path = None
    gz_path = None
    try:
        stamp = datetime.datetime.now(TEHRAN_TZ).strftime('%Y%m%d_%H%M')
        backup_path = BASE_DIR / ("bot_data_manual_%s.db" % stamp)
        _make_db_backup_snapshot(backup_path)
        health_str, n_users = _snapshot_health_and_users(backup_path)
        gz_path, raw_b, gz_b = _gzip_db_file(backup_path)
        try: backup_path.unlink()
        except Exception: pass
        backup_path = None  # از این به بعد فقط gz لازم است
        caption = (
            "💾 بکاپ دستی دیتابیس\n"
            "📅 %s\n"
            "👤 کاربران: %s\n"
            "📦 حجم: %s → %s (فشرده)\n"
            "🩺 سلامت: %s\n"
            "♻️ بازیابی: همین فایل را در /restore ارسال کنید (از gz پشتیبانی می‌شود)." % (
                shamsi_date(datetime.datetime.now(TEHRAN_TZ), with_time=True),
                to_persian_int(n_users), _fmt_size(raw_b), _fmt_size(gz_b), health_str))
        ok_sent, send_err = _send_document_with_retry(bot, chat_id, gz_path, caption)
        if ok_sent:
            logger.info("🗄️ Manual DB backup sent to admin (gz, %s → %s).", _fmt_size(raw_b), _fmt_size(gz_b))
        else:
            raise send_err if send_err else RuntimeError("send failed")
    except Exception as e:
        logger.error("manual backup error: %s", e)
        try:
            bot.send_message(chat_id, "❌ خطا در بکاپ دستی دیتابیس: %s" % e)
        except Exception:
            pass
    finally:
        for _p in (backup_path, gz_path):
            if _p:
                try:
                    Path(_p).unlink()
                except Exception:
                    pass


def admin_vip_submenu_markup():
    """زیرمنوی VIP — طبق درخواست: تراکنش‌ها، تغییر قیمت، آمار VIP، مدیریت VIP."""
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        types.InlineKeyboardButton("💰 تراکنش‌ها", callback_data="admin_transactions_page_1"),
        types.InlineKeyboardButton("💵 تغییر قیمت VIP", callback_data="admin_vip_prices"),
        types.InlineKeyboardButton("📊 آمار VIP", callback_data="admin_vip_stats"),
        types.InlineKeyboardButton("⚙️ مدیریت VIP", callback_data="admin_vip"),
    )
    m.add(types.InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel"))
    return m

def process_admin_addvip(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        # رفع باگ: بررسی تعداد آرگومان‌ها
        parts = message.text.split()
        if len(parts) != 2:
            bot.reply_to(message, "❌ فرمت اشتباه. مثال درست:\n123456789 30", reply_markup=admin_panel_back_markup())
            return
        uid, days = int(parts[0]), int(parts[1])
        if days <= 0 or days > 3650:
            bot.reply_to(message, "❌ تعداد روز باید بین ۱ و ۳۶۵۰ باشد.", reply_markup=admin_panel_back_markup())
            return
        db.add_vip(uid, days)
        bot.reply_to(message, f"✅ کاربر {uid} برای {days} روز VIP شد.", reply_markup=admin_panel_back_markup())
    except Exception:
        bot.reply_to(message, "❌ فرمت اشتباه. مثال درست:\n123456789 30", reply_markup=admin_panel_back_markup())

def process_admin_quick_vip(message, target_id):
    if message.from_user.id != ADMIN_ID: return
    try:
        days = int(message.text.strip())
        # رفع باگ: اعتبارسنجی بازه روز
        if days <= 0 or days > 3650:
            bot.reply_to(message, "❌ تعداد روز باید بین ۱ و ۳۶۵۰ باشد.", reply_markup=admin_panel_back_markup())
            return
        db.add_vip(target_id, days)
        days_left = db.get_vip_days_left(target_id)
        bot.reply_to(message,
                     f"✅ کاربر {target_id} برای {to_persian_digits(days)} روز VIP شد.\n👑 مجموع باقی‌مانده: {to_persian_digits(days_left)} روز",
                     reply_markup=admin_panel_back_markup())
    except Exception:
        bot.reply_to(message, "❌ تعداد روز نامعتبر.", reply_markup=admin_panel_back_markup())

def process_admin_quick_vip_minus(message, target_id):
    """v3.16: کاهش روزهای VIP کاربر توسط سوپر ادمین."""
    if message.from_user.id != ADMIN_ID: return
    try:
        days = int(message.text.strip())
        if days <= 0 or days > 3650:
            bot.reply_to(message, "❌ تعداد روز باید بین ۱ و ۳۶۵۰ باشد.", reply_markup=admin_panel_back_markup())
            return
        new_exp = db.remove_vip_days(target_id, days)
        if new_exp is None:
            bot.reply_to(message, f"⚠️ کاربر {target_id} اصلاً VIP ندارد.", reply_markup=admin_panel_back_markup())
            return
        days_left = db.get_vip_days_left(target_id)
        if days_left > 0:
            bot.reply_to(message,
                         f"✅ {to_persian_digits(days)} روز از VIP کاربر {target_id} کم شد.\n📅 انقضای جدید: {new_exp.isoformat()}\n👑 باقی‌مانده: {to_persian_digits(days_left)} روز",
                         reply_markup=admin_panel_back_markup())
        else:
            bot.reply_to(message,
                         f"✅ {to_persian_digits(days)} روز از VIP کاربر {target_id} کم شد.\n📅 انقضای جدید: {new_exp.isoformat()}\n⛔ VIP این کاربر دیگر فعال نیست.",
                         reply_markup=admin_panel_back_markup())
    except Exception:
        bot.reply_to(message, "❌ تعداد روز نامعتبر.", reply_markup=admin_panel_back_markup())

def process_admin_search(message):
    if message.from_user.id != ADMIN_ID: return
    query = message.text.strip()
    results = db.search_users(query)
    markup = types.InlineKeyboardMarkup(row_width=1)
    if not results:
        markup.add(types.InlineKeyboardButton("🔐 پنل ادمین", callback_data="admin_panel"))
        markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
        bot.reply_to(message, "❌ هیچ کاربری یافت نشد.", reply_markup=markup)
    else:
        lines = [f"🔍 نتایج جستجو برای '{query}':"]
        for u in results[:10]: lines.append(f"• {u['first_name'] or 'بی‌نام'} (ID: {u['user_id']})")
        for u in results[:10]:
            markup.add(types.InlineKeyboardButton(f"{u['first_name'] or u['user_id']}", callback_data=f"user_detail_{u['user_id']}"))
        markup.add(types.InlineKeyboardButton("🔐 پنل ادمین", callback_data="admin_panel"))
        bot.reply_to(message, "\n".join(lines), reply_markup=markup)

ARCHIVE_DAYS_PER_PAGE = 20

def _archive_day_line(date_display, cnt, avg):
    """v3.24.7: یک خط آرشیو — خوانا و کوتاه با نوار بصری نسبت به میانگین:
    «۱۴۰۵/۰۶/۱۶  ▇▇▇▇▇▇▇▇  ۸۳+»  (تعداد نسبی نوار = سهم روز از بیشینهٔ صفحه)
    میانگین فقط یک‌بار در سرصفحه گفته می‌شود، نه تکرار در هر سطر."""
    return "%s  %s  %s" % (date_display, _archive_bar, to_persian_digits(cnt))

def _archive_bar(cnt, max_cnt):
    """نوار بصری ۱۰ خانهای نسبت به پرکارترین روز همین صفحه."""
    if max_cnt <= 0:
        return "▁"
    filled = max(1, round(cnt / max_cnt * 10))
    return "▇" * filled

def _send_daily_archive(chat_id, message_id, growth_data, page=0):
    """v3.20: آرشیو روزانه — لیستی به فرمت درخواستی:
    «تاریخ شمسی : n کاربر جدید | c تا بیشتر/کمتر از میانگین (میانگین: X)»
    میانگین روی «تمام روزهای شمرده‌شدهٔ» دیتابیس (از اولین روز تا امروز) حساب می‌شود.
    صفحه‌بندی ۳۰ روزه + همیشه پیام جدید (بدون edit) — مقاوم به خطا و قابل رصد در لاگ."""
    logger.info("[ADMIN] daily archive render page=%s", page)
    counts = {}
    for d, c in growth_data:
        try:
            counts[str(d)] = int(c or 0)
        except (TypeError, ValueError):
            pass
    today = datetime.date.today()
    if counts:
        try:
            first_day = datetime.date.fromisoformat(min(counts.keys()))
        except Exception:
            first_day = today
    else:
        first_day = today
    if first_day > today:
        first_day = today
    # تمام روزهای تقویمی از اولین روز تا امروز (روزهای بدون کاربر = صفر)
    all_days = []
    _d = first_day
    while _d.isoformat() <= today.isoformat():
        all_days.append(_d)
        _d += datetime.timedelta(days=1)
    total_all = sum(counts.values())
    n_all = len(all_days)
    avg = (total_all / n_all) if n_all else 0.0
    # صفحه‌بندی: صفحهٔ ۰ = ۳۰ روز اخیر (از جدید به قدیم)
    per = ARCHIVE_DAYS_PER_PAGE
    pages = max(1, (len(all_days) + per - 1) // per)
    page = max(0, min(page, pages - 1))
    end_idx = len(all_days) - page * per
    start_idx = max(0, end_idx - per)
    window = list(reversed(all_days[start_idx:end_idx]))
    lines = [
        "📊 *آرشیو روزانه — کاربران جدید*",
        "🗓 میانگین کل: %s نفر در روز (%s روز)" % (
            to_persian_digits(int(round(avg))), to_persian_digits(n_all)),
        "",
    ]
    # v3.24.7: بیشینهٔ همین صفحه برای مقیاس نوارهای بصری
    _page_counts = [counts.get(g.isoformat(), 0) for g in window]
    _page_max = max(_page_counts) if _page_counts else 0
    for g_date in window:
        cnt = counts.get(g_date.isoformat(), 0)
        try:
            j_date = jdatetime.date.fromgregorian(date=g_date)
            date_display = to_persian_digits(j_date.strftime("%y/%m/%d"))
        except Exception:
            date_display = to_persian_digits(g_date.isoformat())
        lines.append("%s  %s  %s" % (date_display, _archive_bar(cnt, _page_max), to_persian_digits(cnt)))
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("صفحهٔ %s از %s" % (to_persian_digits(page + 1), to_persian_digits(pages)))
    markup = types.InlineKeyboardMarkup(row_width=2)
    nav = []
    if page < pages - 1:
        nav.append(types.InlineKeyboardButton("📅 روزهای قدیمی‌تر ⬅️", callback_data="admin_daily_archive_p%d" % (page + 1)))
    if page > 0:
        nav.append(types.InlineKeyboardButton("➡️ روزهای جدیدتر", callback_data="admin_daily_archive_p%d" % (page - 1)))
    if nav:
        markup.add(*nav)
    markup.add(types.InlineKeyboardButton("🔙 بازگشت به آمار", callback_data="admin_daily"))
    bot.send_message(chat_id, "\n".join(lines), reply_markup=markup)
    logger.info("[ADMIN] daily archive OK page=%s", page)
    if message_id:
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass

# v3.24.0: رفع باگ «لیست کاربران باز نمیشود» — این ثابت در نسخه‌های قبل تعریف نشده بود
ADMIN_USERLIST_PAGE_SIZE = 10

def show_admin_userlist(chat_id, page, message_id, sort="invites"):
    """v3.20: لیست کاربران ادمین — دو مرتب‌سازی (بیشترین دعوت / جدیدترین) + صفحه‌بندی
    ۱۰تایی با دکمه‌های شیشه‌ای. رفع قطعی «باز نشدن»: هیچ‌وقت edit نمی‌کنیم؛ همیشه
    پیامِ جدید می‌فرستیم (هر کلاینتی پیام جدید را نشان می‌دهد) و بعد پیام قدیمی را
    حذف می‌کنیم. همهٔ مراحل لاگ می‌شوند تا در Railway قابل رصد باشد."""
    logger.info("[ADMIN] userlist render start page=%s sort=%s", page, sort)
    # v3.24.0: رفع باگ «لیست کاربران باز نمیشود» — متغیر قبل‌تر تعریف نشده بود (NameError)
    limit = ADMIN_USERLIST_PAGE_SIZE
    offset = (max(1, page) - 1) * limit
    users = db.get_admin_userlist(sort, offset, limit)
    total = db.count_all_users()
    total_pages = max(1, (total + limit - 1) // limit)
    page = max(1, min(page, total_pages))
    sort_label = "بیشترین دعوت" if sort == "invites" else "جدیدترین"
    lines = [
        "👥 لیست کاربران — مرتب‌سازی: " + sort_label,
        "صفحهٔ %s از %s | مجموع: %s کاربر" % (to_persian_digits(page), to_persian_digits(total_pages), to_persian_int(total)),
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    base_rank = (page - 1) * limit
    for i, u in enumerate(users):
        snoop_cnt = u.get('snoop_count', 0) or 0
        nm = (u.get('first_name') or 'بی‌نام')[:30]
        lines.append("%s. %s — %s دعوت" % (to_persian_digits(base_rank + i + 1), nm, to_persian_digits(snoop_cnt)))
    if not users:
        lines.append("کاربری در این صفحه نیست.")
    # دکمه‌های شیشه‌ای — ۱۰ کاربر در صفحه (۲ ستون)
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for u in users:
        snoop_cnt = u.get('snoop_count', 0) or 0
        lbl = (u.get('first_name') or str(u.get('user_id')))[:20]
        if snoop_cnt:
            lbl = "%s (%s)" % (lbl, to_persian_digits(snoop_cnt))
        buttons.append(types.InlineKeyboardButton(lbl, callback_data="user_detail_%s" % u['user_id']))
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.add(buttons[i], buttons[i + 1])
        else:
            markup.add(buttons[i])
    # سوییچ مرتب‌سازی — نشان ✅ روی حالت فعال
    if sort == "invites":
        markup.add(
            types.InlineKeyboardButton("✅ بیشترین دعوت", callback_data="admin_userlist_invites_%d" % page),
            types.InlineKeyboardButton("جدیدترین 🆕", callback_data="admin_userlist_new_%d" % page),
        )
    else:
        markup.add(
            types.InlineKeyboardButton("بیشترین دعوت 🔝", callback_data="admin_userlist_invites_%d" % page),
            types.InlineKeyboardButton("✅ جدیدترین", callback_data="admin_userlist_new_%d" % page),
        )
    # ناوبری صفحات
    nav = []
    if page > 1:
        nav.append(types.InlineKeyboardButton("⬅️ قبلی", callback_data="admin_userlist_%s_%d" % (sort, page - 1)))
    if page < total_pages:
        nav.append(types.InlineKeyboardButton("بعدی ➡️", callback_data="admin_userlist_%s_%d" % (sort, page + 1)))
    if nav:
        markup.add(*nav)
    markup.add(types.InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel"))
    # همیشه پیام جدید — اول بفرست، بعد قدیمی را حذف کن (پنل هیچ‌وقت گم نمی‌شود)
    bot.send_message(chat_id, "\n".join(lines), reply_markup=markup)
    logger.info("[ADMIN] userlist render OK page=%s sort=%s", page, sort)
    if message_id:
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass

# ====== v3.21: پنل «آمار کاربران» + برترین‌های روز/هفته/ماه ======
ADMIN_TOP_PAGE_SIZE = 10
_TOP_WINDOW_LABELS = {"day": "امروز", "week": "۷ روز اخیر", "month": "ماه شمسی جاری"}

def _top_window_start_iso(window):
    """شروع بازهٔ برترین‌ها به UTC (فرمت clicked_at) — روز = ۰۰:۰۰ تهران، ماه = ۱ ماه شمسی."""
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    if window == "day":
        dt = datetime.datetime.now(TEHRAN_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if window == "week":
        return (now_utc - datetime.timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    if window == "month":
        try:
            tehran_today = datetime.datetime.now(TEHRAN_TZ).date()
            try:
                j_today = jdatetime.date.fromgregorian(date=tehran_today)
                jy, jm = j_today.year, j_today.month
            except Exception:
                jy, jm, _ = _g2j_fallback(tehran_today.year, tehran_today.month, tehran_today.day)
            try:
                g_start = jdatetime.date(jy, jm, 1).togregorian()
            except Exception:
                gy, gm, gd = _j2g_fallback(jy, jm, 1)
                g_start = datetime.date(gy, gm, gd)
            dt = datetime.datetime(g_start.year, g_start.month, g_start.day, 0, 0, 0,
                                   tzinfo=TEHRAN_TZ)
            return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return (now_utc - datetime.timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    return "1970-01-01 00:00:00"

def show_admin_user_stats(chat_id, message_id):
    """v3.21: پنل «آمار کاربران» — خلاصه + سه دکمهٔ جدا برای لیست‌های برترین (جلوگیری از مشکل).
    همان الگوی امن لیست کاربران: پیام جدید، بعد حذف پیام قدیمی."""
    logger.info("[ADMIN] user-stats render start")
    st, _st_ts = db.get_user_stats_summary_cached()  # v3.23: کش ۶۰ ثانیه‌ای
    lines = [
        "👥 آمار کاربران",
        "━━━━━━━━━━━━━━━━━━━━",
        "🔹 کل: %s نفر | 📨 قابل پیام: %s نفر" % (
            to_persian_int(st['total']), to_persian_digits(st['messageable'])),
        "(قابل پیام = ربات را بلاک نکرده و مسدود نشده)",
        "🆕 جدید امروز: +%s نفر" % to_persian_digits(st['new_today']),
        "🧑‍💻 با حداقل یک درخواست به ربات: %s نفر" % to_persian_digits(st['requested']),
        "━━━━━━━━━━━━━━━━━━━━",
        "برترین‌ها بر اساس فضول‌های جدید گرفته‌شده:",
    ]
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("☀️ برترین‌های روز", callback_data="admin_top_day_p1"),
        types.InlineKeyboardButton("📅 برترین‌های هفته", callback_data="admin_top_week_p1"),
        types.InlineKeyboardButton("🗓 برترین‌های ماه", callback_data="admin_top_month_p1"),
    )
    markup.add(types.InlineKeyboardButton("🔄 بروزرسانی", callback_data="admin_user_stats"))
    markup.add(types.InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel"))
    bot.send_message(chat_id, "\n".join(lines), reply_markup=markup)
    logger.info("[ADMIN] user-stats render OK")
    if message_id:
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass

def show_top_users_list(chat_id, page, message_id, window="day"):
    """v3.21: لیست برترین‌های روز/هفته/ماه — صفحه‌بندی ۱۰تایی با دکمه‌های شیشه‌ای."""
    logger.info("[ADMIN] top-users render start window=%s page=%s", window, page)
    if window not in _TOP_WINDOW_LABELS:
        window = "day"
    limit = ADMIN_TOP_PAGE_SIZE
    page = max(1, page)
    offset = (page - 1) * limit
    start_iso = _top_window_start_iso(window)
    try:
        rows, total = db.get_top_users_window(start_iso, offset, limit)
    except Exception as e:
        logger.error("top-users query error: %s", e)
        rows, total = [], 0
    total_pages = max(1, (total + limit - 1) // limit)
    page = min(page, total_pages)
    lines = [
        "🏆 برترین‌های %s" % _TOP_WINDOW_LABELS[window],
        "صفحهٔ %s از %s | تعداد در لیست: %s نفر" % (
            to_persian_digits(page), to_persian_digits(total_pages), to_persian_digits(total)),
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    base_rank = (page - 1) * limit
    rank_icons = ['🥇', '🥈', '🥉']
    for i, r in enumerate(rows):
        rank = base_rank + i + 1
        icon = rank_icons[rank - 1] if rank <= 3 else "%s." % to_persian_digits(rank)
        nm = sanitize_name((r.get('first_name') or 'بی‌نام'))
        try:
            nm = escape_md(crown_name(nm, db.is_vip(r['owner_id'])))
        except Exception:
            nm = escape_md(nm)
        lines.append("%s %s — %s فضول" % (icon, nm, to_persian_digits(r['cnt'])))
    if not rows:
        lines.append("هنوز کسی در این بازه امتیازی نگرفته است.")
    # دکمه‌های شیشه‌ای — ۱۰ کاربر در صفحه (۲ ستون)
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for r in rows:
        lbl = (r.get('first_name') or str(r.get('owner_id')))[:20]
        lbl = "%s (%s)" % (lbl, to_persian_digits(r['cnt']))
        buttons.append(types.InlineKeyboardButton(lbl, callback_data="user_detail_%s" % r['owner_id']))
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.add(buttons[i], buttons[i + 1])
        else:
            markup.add(buttons[i])
    nav = []
    if page > 1:
        nav.append(types.InlineKeyboardButton("⬅️ قبلی", callback_data="admin_top_%s_p%d" % (window, page - 1)))
    if page < total_pages:
        nav.append(types.InlineKeyboardButton("بعدی ➡️", callback_data="admin_top_%s_p%d" % (window, page + 1)))
    if nav:
        markup.add(*nav)
    markup.add(
        types.InlineKeyboardButton("☀️ روز", callback_data="admin_top_day_p1"),
        types.InlineKeyboardButton("📅 هفته", callback_data="admin_top_week_p1"),
        types.InlineKeyboardButton("🗓 ماه", callback_data="admin_top_month_p1"),
    )
    markup.add(types.InlineKeyboardButton("🔙 بازگشت به آمار کاربران", callback_data="admin_user_stats"))
    bot.send_message(chat_id, "\n".join(lines), reply_markup=markup)
    logger.info("[ADMIN] top-users render OK window=%s page=%s", window, page)
    if message_id:
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass

def show_user_detail(chat_id, target_id, message_id, info):
    user = info['user']
    vip_status = info['vip_status']
    if info['vip_expire'] and vip_status == "فعال":
        vip_status += f" (تا {info['vip_expire']})"
    warnings = db.get_user_warning_count(target_id)
    is_hidden = db.is_hide_leaderboard(target_id)
    leaderboard_status = "مخفی" if is_hidden else "عمومی"

    text = texts.ADMIN_USER_DETAIL.format(
        user_id=target_id, name=escape_md(user['first_name'] or 'ندارد'),
        username=escape_md(user['username'] or 'ندارد'),
        blocked="مسدود" if user['blocked'] else "فعال",
        vip_status=vip_status,
        vip_sources=info.get('vip_sources') or "—",
        total_clicks=info['total_clicks'],
        snoop_count=info['snoop_count'],
        join_date="نامشخص",
        warnings=warnings,
        leaderboard_status=leaderboard_status
    )

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🚫 مسدود", callback_data=f"admin_action_block_{target_id}"),
        types.InlineKeyboardButton("✅ رفع مسدود", callback_data=f"admin_action_unblock_{target_id}")
    )
    # v3.16: کنترل کامل VIP — افزودن / کاهش / لغو کامل
    markup.add(
        types.InlineKeyboardButton("➕ افزودن VIP", callback_data=f"admin_action_vip_{target_id}"),
        types.InlineKeyboardButton("➖ کاهش VIP", callback_data=f"admin_action_vipminus_{target_id}")
    )
    markup.add(
        types.InlineKeyboardButton("❌ لغو کامل VIP", callback_data=f"admin_action_viprevoke_{target_id}"),
        types.InlineKeyboardButton("✉️ پیام", callback_data=f"admin_action_message_{target_id}")
    )
    # v4.7 (اخطار به کاربر): همان جریان اخطار ربات — اخطار سوم خودکار مسدود می‌کند
    markup.add(
        types.InlineKeyboardButton("⚠️ اخطار به کاربر", callback_data=f"admin_warn_{target_id}"),
        types.InlineKeyboardButton("🔄 بازنشانی اخطارها", callback_data=f"admin_resetwarns_{target_id}")
    )
    markup.add(types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="admin_userlist_page_1"))
    markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
    safe_edit_text(text, chat_id, message_id, reply_markup=markup)

def show_admin_transactions(chat_id, page, message_id):
    limit = 10; offset = (page-1)*limit
    txns = db.get_transactions_paginated(offset, limit)
    total = db.count_transactions(); total_pages = max(1, (total + limit - 1) // limit)
    lines = [texts.ADMIN_TRANSACTION_LIST.format(page=page)]
    for t in txns: lines.append(f"👤 {t['user_id']} | {t['type']} | {t['amount']:,} ریال | {t['timestamp'][:16]}")
    markup = types.InlineKeyboardMarkup()
    row = []
    if page > 1: row.append(types.InlineKeyboardButton("⬅️", callback_data=f"admin_transactions_page_{page-1}"))
    if page < total_pages: row.append(types.InlineKeyboardButton("➡️", callback_data=f"admin_transactions_page_{page+1}"))
    if row: markup.row(*row)
    markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel"))
    safe_edit_text("\n".join(lines), chat_id, message_id, reply_markup=markup)

def show_admin_anon_logs(chat_id, page, message_id):
    limit = 5; offset = (page-1)*limit
    logs = db.get_anon_logs_paginated(offset, limit)
    total = db.count_anon_logs(); total_pages = max(1, (total + limit - 1) // limit)
    lines = [texts.ADMIN_ANON_LOG_HEADER]
    for l in logs: lines.append(texts.ADMIN_ANON_LOG_ENTRY.format(sender=l['sender_id'], receiver=l['receiver_id'], text=l['text'][:100]))
    markup = types.InlineKeyboardMarkup(row_width=2)
    for l in logs:
        markup.add(
            types.InlineKeyboardButton("✉️ پیام", callback_data=f"anonlog_action_msg_{l['sender_id']}"),
            types.InlineKeyboardButton("🚫 بلاک", callback_data=f"anonlog_action_block_{l['sender_id']}"))
    row = []
    if page > 1: row.append(types.InlineKeyboardButton("⬅️", callback_data=f"admin_anonlog_page_{page-1}"))
    if page < total_pages: row.append(types.InlineKeyboardButton("➡️", callback_data=f"admin_anonlog_page_{page+1}"))
    if row: markup.row(*row)
    markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel"))
    safe_edit_text("\n".join(lines), chat_id, message_id, reply_markup=markup)

# ====== ویزارد کاربر جدید ======
def _grant_first_entry_gift(user_id):
    """هدیهٔ ورود (چند روز VIP) — فقط اولین ورود؛ تعداد روزها از پنل ادمین."""
    try:
        if db.is_trial_given(user_id):
            return 0
        days = db.get_setting_int("trial_days", 3)
        if days <= 0:
            return 0
        db.add_vip(user_id, days)
        db.set_trial_given(user_id)
        try:
            db.add_transaction(user_id, "trial_vip", 0, days)
        except Exception:
            pass
        return days
    except Exception as e:
        logger.error(f"first entry gift error: {e}")
        return 0


def _start_new_user_wizard(chat_id, name, tone="warm"):
    """شروع ویزارد کاربر جدید — مرحله ۱: پیام خوش‌آمد (گرم برای welcome/organic، تله‌ای برای referral)."""
    trial_days = db.get_setting_int("trial_days", 3)
    try:
        # مرحله ۱: پیام خوش‌آمد بسته به مسیر ورود
        if tone == "scary":
            bot.send_message(chat_id, texts.TRAP_WIZARD_INTRO.format(name=escape_md(name), days=to_persian_digits(trial_days)))
        else:
            bot.send_message(chat_id, texts.WIZARD_WELCOME.format(name=escape_md(name), days=to_persian_digits(trial_days)))
        # مرحله ۲: ویدیو + متن + دکمه‌ها (بدون تأخیر)
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("🔍 ساخت تله", callback_data="wizard_make_trap"))
        markup.add(types.InlineKeyboardButton("➡️ ادامه", callback_data="wizard_skip"))
        if LINK_TUTORIAL_VIDEO_ID:
            try:
                bot.send_video(chat_id, LINK_TUTORIAL_VIDEO_ID, caption=texts.WIZARD_TUTORIAL, reply_markup=markup)
            except:
                bot.send_message(chat_id, texts.WIZARD_TUTORIAL_NO_VIDEO, reply_markup=markup)
        else:
            bot.send_message(chat_id, texts.WIZARD_TUTORIAL_NO_VIDEO, reply_markup=markup)
    except Exception as e:
        logger.error(f"Wizard error: {e}")

# ====== /panel — نمایش منوی خانه ======
@bot.message_handler(commands=['panel'])
def panel_cmd(message):
    chat_id = message.chat.id
    if db.is_blocked(chat_id):
        return
    # نمایش منوی خانه (مثل وقتی که پیام نامفهوم ارسال می‌شه)
    home_text = build_dynamic_home_text(chat_id)
    # رفع باگ: wrap در try/except
    try:
        bot.reply_to(message, home_text, reply_markup=main_menu(chat_id))
    except ApiTelegramException as e:
        if e.error_code == 403:
            try: db.mark_user_blocked_bot(chat_id)
            except Exception: pass
        else:
            logger.error(f"panel_cmd send error: {e}")
    except Exception as e:
        logger.error(f"panel_cmd send error: {e}")

# ====== v3.10.0: ابزارهای عیب‌یابی ادمین ======
@bot.message_handler(commands=['usage'])
def usage_cmd(message):
    """v3.24.4: گزارش تلمتری استفاده — ساعت پیک، پرمصرف‌ها، مسیرهای کند. فقط سوپرادمین."""
    if message.from_user.id != ADMIN_ID:
        return
    try:
        hourly = db.usage_hourly_report(24)
        top = db.usage_top_labels(24, 12)
        slow = db.usage_slow_paths(24, 2000, 10)
        errs = db.usage_error_counts(24)

        lines = ["📊 *گزارش استفاده ۲۴ ساعت اخیر*", ""]
        # ساعت پیک — جمع رویدادها در هر ساعت
        per_hour = {}
        for r in hourly:
            per_hour[r['hour']] = per_hour.get(r['hour'], 0) + r['n']
        if per_hour:
            lines.append("🕐 *بار هر ساعت:*")
            peak = max(per_hour.values()) if per_hour else 0
            for h, n in sorted(per_hour.items()):
                bar = "▇" * max(1, round(n / max(peak, 1) * 10))
                lines.append(f"  {h} — {to_persian_int(n)} {bar}")
            peak_hours = [h for h, n in per_hour.items() if n == peak]
            lines.append(f"🔥 ساعت پیک: {', '.join(peak_hours)} با {to_persian_int(peak)} رویداد")
            lines.append("")
        if top:
            lines.append("👆 *پرمصرف‌ترین مسیرها:*")
            for r in top[:12]:
                lines.append(f"  [{r['kind']}] {r['label']} — {to_persian_int(r['n'])} بار | میانگین {to_persian_int(r['avg_ms'])}ms | بیشینه {to_persian_int(r['max_ms'])}ms")
            lines.append("")
        if slow:
            lines.append("🐌 *مسیرهای کند (بالای ۲ ثانیه):*")
            for r in slow:
                lines.append(f"  [{r['kind']}] {r['label']} — {to_persian_int(r['n'])} بار | میانگین {to_persian_int(r['avg_ms'])}ms | بیشینه {to_persian_int(r['max_ms'])}ms")
            lines.append("")
        if errs:
            lines.append("🧯 *خطاها به تفکیک ساعت:*")
            for r in errs:
                lines.append(f"  {r['hour']} — {to_persian_int(r['n'])} خطا")
        else:
            lines.append("🧯 خطایی در ۲۴ ساعت اخیر ثبت نشده ✅")
        bot.send_message(message.chat.id, "\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"usage report error: {e}")
        try:
            bot.send_message(message.chat.id, f"⚠️ خطا در گزارش: {e}")
        except Exception:
            pass

@bot.message_handler(commands=['lbdebug'])
def lbdebug_cmd(message):
    """v3.12: وضعیت کش پلکانی + هر دو تابلو (کل/هفته) با کوئری‌های show_leaderboard."""
    if message.from_user.id != ADMIN_ID:
        return
    try:
        lines = ["🔬 LB DEBUG — کش پلکانی تنبل " + LB_RENDER_VERSION,
                 "⏱ سقف کهنگی تصویر: سوپر ادمین ۱۰ دقیقه | کاربر عادی ۲ ساعت"]
        for _cmode in ("all", "week"):
            _cfid, _cts = lb_cache_get(_cmode)
            if _cfid and _cts:
                _cage = int(time.time()) - int(_cts)
                lines.append("🖼 کش[%s]: سن %s ثانیه (~%s دقیقه) → تازه برای ادمین: %s | برای کاربر: %s" % (
                    _cmode, to_persian_digits(_cage), to_persian_digits(max(1, _cage // 60)),
                    "✅" if _cage < LB_TTL_ADMIN else "❌ کهنه",
                    "✅" if _cage < LB_TTL_USER else "❌ کهنه"))
            else:
                lines.append("🖼 کش[%s]: خالی — نخستین درخواست رندر تازه می‌سازد" % _cmode)
        for _mode in ("all", "week"):
            rows = (db.get_leaderboard_top(10) if _mode == "all"
                    else db.get_leaderboard_top_week(10))
            sub = "همه‌زمان" if _mode == "all" else "هفته"
            lines.append("")
            lines.append("🏆 تابلو %s — %s ردیف:" % (sub, to_persian_digits(len(rows))))
            for i, r in enumerate(rows):
                try:
                    _v = db.is_vip(r['owner_id'])
                except Exception:
                    _v = False
                lines.append("%s. %s — %s شکار%s" % (
                    to_persian_digits(i + 1),
                    sanitize_name(r['first_name'] or "بی‌نام")[:32],
                    to_persian_digits(r['cnt']), " 👑" if _v else ""))
        bot.reply_to(message, "\n".join(lines))
    except Exception as _e:
        try:
            bot.reply_to(message, "⚠️ lbdebug: %s" % _e)
        except Exception:
            pass


@bot.message_handler(commands=['wheelshow'])
def wheelshow_cmd(message):
    """پیش‌نمایش ویدیوی MP4 چرخ (جک‌پات) + زمان تولید — v3.13 روش A؛ فالبک GIF."""
    if message.from_user.id != ADMIN_ID:
        return
    try:
        _vid = None
        if wheel_video and wheel_gif and wheel_gif.AVAILABLE and wheel_video.MP4_AVAILABLE():
            t0 = time.time()
            _vid = wheel_video.get_spin_mp4(WHEEL_PRIZES, len(WHEEL_PRIZES) - 1)
            dt = int((time.time() - t0) * 1000)
        if _vid:
            bio = io.BytesIO(_vid)
            bio.name = "wheel.mp4"
            bot.send_animation(message.chat.id, bio,
                               caption="🎡 پیش‌نمایش چرخ v3.14 — MP4 جک‌پات\n⏱ %dms | 📦 %dKB" % (
                                   dt, len(_vid) // 1024))
            return
        # فالبک: GIF قبلی
        t0 = time.time()
        _gif = wheel_gif.get_spin_gif(WHEEL_PRIZES, len(WHEEL_PRIZES) - 1) if (wheel_gif and wheel_gif.AVAILABLE) else None
        dt = int((time.time() - t0) * 1000)
        if _gif:
            bio = io.BytesIO(_gif)
            bio.name = "wheel.gif"
            bot.send_animation(message.chat.id, bio,
                               caption="🎡 پیش‌نمایش چرخ (GIF فالبک) — جک‌پات\n⏱ %dms | 📦 %dKB" % (
                                   dt, len(_gif) // 1024))
        else:
            bot.reply_to(message, "⚠️ تولید MP4/GIF ناموفق — لاگ را ببین")
    except Exception as _e:
        try:
            bot.reply_to(message, "⚠️ wheelshow: %s" % _e)
        except Exception:
            pass


# ====== v4.4: مرحلهٔ «حفظ آبرو / لو رفتن» تله ======
# زمان‌بندی: ۶۰ ثانیه فرصت فشردن هر دکمه → ۳ دقیقه فرصت پرداخت (در صورت انتخاب حفظ آبرو)
TRAP_PENDING_SECONDS = 60
TRAP_SAVEFACE_SECONDS = 180
# قیمت پیش‌فرض «حفظ آبرو» به ریال — از پنل ادمین (کلید settings: saveface_price) قابل تغییر است
TRAP_SAVEFACE_PRICE_DEFAULT = 45000


def _saveface_price_rial():
    try:
        v = db.get_setting_int("saveface_price", TRAP_SAVEFACE_PRICE_DEFAULT)
        if v < 10000 or v > 100_000_000:
            return TRAP_SAVEFACE_PRICE_DEFAULT
        return v
    except Exception:
        return TRAP_SAVEFACE_PRICE_DEFAULT


def _trap_send_decision_message(decision):
    """ارسال/یادآوری پیام «حفظ آبرو یا لو رفتن» به بازدیدکنندهٔ تله."""
    price_toman = _saveface_price_rial() // 10
    visitor_id = decision['visitor_id']
    try:
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton(
            texts.TRAP_BTN_SAVEFACE.format(price=to_persian_digits(price_toman)),
            callback_data=f"trapdec_save_{decision['id']}"))
        markup.add(types.InlineKeyboardButton(
            texts.TRAP_BTN_EXPOSE_ME, callback_data=f"trapdec_expose_{decision['id']}"))
        bot.send_message(visitor_id,
                         texts.TRAP_CHANCE.format(price=to_persian_digits(price_toman)),
                         reply_markup=markup)
    except Exception as e:
        logger.error(f"trap decision message error (dec={decision.get('id')}): {e}")


def _trap_owner_report(decision):
    """گزارش فضول‌گیری به صاحب لینک — کد دقیقاً از جریان قبلی منتقل شده (v4.4:
    فقط بعد از نهایی‌شدن تصمیم بازدیدکننده فراخوانی می‌شود، نه در لحظهٔ کلیک)."""
    owner_id = decision['owner_id']
    clicker_id = decision['visitor_id']
    repeat = decision.get('repeat_count') or 1
    trap_code = decision.get('trap_code')
    clicker_username = decision.get('clicker_username')
    display_name = decision.get('display_name') or "بی‌نام"
    photo_file_id = decision.get('photo_file_id')
    vip_owner = db.is_vip(owner_id)
    t = datetime.datetime.now().strftime("%Y/%m/%d - %H:%M")

    if is_subscribed(owner_id):
        # v4.7 (فقط نام برای غیر VIP): کاربر عادی فقط نام فضول را می‌بیند —
        # نه شناسه، نه یوزرنیم و نه عکس پروفایل (عکس هویت را لو می‌دهد).
        if vip_owner:
            msg = (f"🔔 *یه فضول روی لینک شما کلیک کرد!*\n"
                   f"🕒 {t}\n👤 {escape_md(display_name)}\n"
                   f"🆔 {fmt_id(clicker_id, vip_owner, owner_id=owner_id)}\n📎 {fmt_uname(clicker_username, vip_owner, owner_id=owner_id, uid=clicker_id)}")
        else:
            msg = (f"🔔 *یه فضول روی لینک شما کلیک کرد!*\n"
                   f"🕒 {t}\n👤 {escape_md(display_name)}")
            msg += "\n\n" + texts.REVEAL_TEASE
        if repeat == 1:
            msg += "\n\n🆕 *فضول جدید!* این اولین کلیکشه."
        if repeat > 3:
            msg += "\n🔥 *فضول حرفه‌ای شناسایی شد!*"
            msg += "\n\nاین فضول هی داره روی لینکت کلیک میکنه اگه اذیتت میکنه با دکمه بی‌صدا دهنشو ببند!"
        if trap_code:
            try:
                _tlabel = db.get_trap_label(trap_code)
                if _tlabel:
                    msg += f"\n🕳️ از تله: {escape_md(_tlabel)}"
            except Exception:
                pass

        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🏷️ لقب دادن", callback_data=f"nick_{clicker_id}"),
            types.InlineKeyboardButton("✉️ پیام ناشناس", callback_data=f"anon_{clicker_id}"),
            types.InlineKeyboardButton("📊 اطلاعات فضول", callback_data=f"snoopdetail_{clicker_id}"),
            types.InlineKeyboardButton("🎁 هدیه به فضول", callback_data=f"giftvip_{clicker_id}"),
            types.InlineKeyboardButton("📋 لیست فضول‌ها", callback_data="snooplist_page_1"),
            types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu")
        )
        _add_reveal_button(markup, owner_id, clicker_id, vip_owner)
        if repeat > 3:
            markup.add(types.InlineKeyboardButton("🔕 بی‌صدا", callback_data=f"mute_{clicker_id}"))

        if photo_file_id and vip_owner:
            try: bot.send_photo(owner_id, photo_file_id, caption=msg, reply_markup=markup)
            except:
                try: bot.send_message(owner_id, msg, reply_markup=markup)
                except: pass
        else:
            try: bot.send_message(owner_id, msg, reply_markup=markup)
            except: pass
    else:
        db.save_pending_snoop(owner_id, clicker_id, display_name, t, vip_owner,
                              clicker_username, repeat, False, photo_file_id)
        markup = build_channel_keyboard("show_pending_snoop", owner_id)
        # اگر owner ربات را بلاک کرده، خطا نده — جریان بازدیدکننده قطع نشود
        try:
            bot.send_message(owner_id, texts.SNOOP_CAUGHT_UNSUBSCRIBED, reply_markup=markup)
        except ApiTelegramException as e:
            if e.error_code == 403:
                try:
                    db.mark_user_blocked_bot(owner_id)
                except Exception:
                    pass
        except Exception:
            pass


def _trap_visitor_aftermath(decision, first_name=None):
    """پیام‌های بعدی برای بازدیدکننده — دقیقاً مانند جریان قبلی ربات:
    پیام scary + (ویزارد اگر تازه‌وارد) + پیام خوش‌آمد اختصاصی صاحب لینک VIP."""
    clicker_id = decision['visitor_id']
    owner_id = decision['owner_id']
    is_new = bool(decision.get('is_new'))
    trial_days = db.get_setting_int("trial_days", 3)

    scary_markup = types.InlineKeyboardMarkup(row_width=1)
    scary_markup.add(types.InlineKeyboardButton("🔍 تلهٔ من", callback_data="my_link_show"))
    scary_markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
    _gift_line = texts.SCARY_GIFT_LINE.format(days=to_persian_digits(trial_days)) if (is_new and trial_days > 0) else ""
    try:
        if SCARY_PHOTO_ID:
            bot.send_photo(clicker_id, SCARY_PHOTO_ID, caption=texts.SCARY_TIMEOUT.format(link=user_link(clicker_id), gift_line=_gift_line), reply_markup=scary_markup)
        else:
            bot.send_message(clicker_id, texts.SCARY_TIMEOUT.format(link=user_link(clicker_id), gift_line=_gift_line), reply_markup=scary_markup)
    except: pass

    if is_new:
        try:
            _start_new_user_wizard(clicker_id, first_name or "رفیق", tone="scary")
        except Exception as e:
            logger.error(f"Wizard start error: {e}")

    # پیام خوش‌آمد اختصاصی صاحب لینک VIP (مثل جریان قبلی — حتی برای بازدیدکنندهٔ نجات‌یافته)
    try:
        if db.is_vip(owner_id):
            welcome_photo = db.get_welcome_photo(owner_id); welcome_text = db.get_welcome_text(owner_id)
            if welcome_photo:
                try: bot.send_photo(clicker_id, welcome_photo, caption=welcome_text or "")
                except:
                    if welcome_text:
                        try: bot.send_message(clicker_id, welcome_text)
                        except: pass
            elif welcome_text:
                try: bot.send_message(clicker_id, welcome_text)
                except: pass
    except Exception as e:
        logger.error(f"trap welcome error: {e}")


def _trap_expose_visitor(decision, reason="expose"):
    """لو رفتن بازدیدکننده — گزارش صاحب لینک + پیام‌های بعدی. بدون هیچ راه فراری:
    حتی اگر بازدیدکننده ربات را بلاک کرده باشد، گزارش صاحب لینک ارسال می‌شود."""
    visitor_id = decision['visitor_id']
    try:
        _trap_owner_report(decision)
    except Exception as e:
        logger.error(f"trap owner report error (dec={decision.get('id')}): {e}")
    try:
        text = (texts.TRAP_EXPIRED_UNPAID if reason == "unpaid"
                else texts.TRAP_EXPIRED_NO_ACTION if reason == "timeout"
                else texts.TRAP_EXPOSED_VISITOR)
        bot.send_message(visitor_id, text)
    except Exception:
        pass
    _trap_visitor_aftermath(decision)


def trap_decision_loop():
    """v4.4: حلقهٔ داوری تله — هر ۳ ثانیه تصمیم‌های رسیده به ضرب‌الاجل را نهایی می‌کند.
    تصمیم‌ها در دیتابیس ذخیره می‌شوند؛ ری‌استارت ربات هم هیچ راه فراری باز نمی‌کند."""
    while True:
        try:
            for dec in db.expire_due_trap_decisions(time.time()):
                reason = "unpaid" if dec.get('status') == 'saveface' else "timeout"
                try:
                    _trap_expose_visitor(dec, reason=reason)
                except Exception as e:
                    logger.error(f"trap expose error (dec={dec['id']}): {e}")
        except Exception as e:
            logger.error(f"trap decision loop error: {e}")
        time.sleep(3)


# ====== /start ======
@bot.message_handler(commands=['start'])
def start_cmd(message):
    global _restore_pending
    _t0 = time.time()  # v3.24.4: تلمتری — /start (مسیر ورود کاربر)
    try:
        _start_cmd_impl(message)
    finally:
        try:
            db.log_usage_event("cmd", "/start", (time.time() - _t0) * 1000)
        except Exception:
            pass

def _start_cmd_impl(message):
    global _restore_pending
    chat_id = message.chat.id
    # v3.22: دروازهٔ حالت نگهداری — فقط سوپرادمین عبور می‌کند
    if maintenance_gate(message.from_user.id):
        try:
            bot.reply_to(message, texts.MAINTENANCE_NOTICE)
        except Exception:
            pass
        return
    # در حالت تست (ADMIN_ID == 0) شناسه کاربر رو لاگ کن
    if ADMIN_ID == 0:
        logger.info(f"🧪 TEST MODE: /start received from chat_id={chat_id}, user_id={message.from_user.id}, username={message.from_user.username}")
    clear_user_state(chat_id)
    remove_support_session(chat_id)
    pop_support_partner(chat_id)
    pop_admin_reply(chat_id)

    # در TEST MODE، اولین کاربر به‌صورت خودکار ادمین میشه
    if ADMIN_ID == 0:
        was_set = _set_auto_admin(chat_id)
        if was_set:
            try:
                bot.reply_to(message,
                    f"🧪 *حالت تست — ادمین خودکار*\n\n"
                    f"شما به‌عنوان اولین کاربر، ادمین این ربات شدید!\n"
                    f"🆔 شناسه چت شما: `{chat_id}`\n\n"
                    f"برای دسترسی به پنل ادمین، روی /panel بزنید.",
                    parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Auto-admin notify error: {e}")

    if db.is_blocked(message.from_user.id):
        # رفع باگ: wrap در try/except
        try:
            bot.reply_to(message, "⛔ حساب شما مسدود شده است.")
        except Exception:
            pass
        return

    # مهم: باید is_new_user رو قبل از sync_user_profile چک کنیم
    # چون sync_user_profile کاربر رو در DB ثبت می‌کنه و بعدش is_new_user همیشه False برمی‌گرده
    user_id = message.from_user.id
    is_new = db.is_new_user(user_id)
    # v3.24.6: sync پروفایل → پس‌زمینه برای کاربر موجود (مثل مسیر text) —
    # کاربر جدید سنکرون می‌ماند تا ثبت اولیه و source attribution قطعی باشد
    if is_new:
        db.sync_user_profile(chat_id, message.from_user.first_name, message.from_user.username)
    else:
        threading.Thread(target=db.sync_user_profile,
                         args=(chat_id, message.from_user.first_name, message.from_user.username),
                         daemon=True).start()
    # v3.6: استارت هم فعالیت است — استریک + آمار ۲۴h + اسکنر ماموریت
    record_message(user_id)
    args = message.text.split(' ', 1)
    trial_days = db.get_setting_int("trial_days", 3)

    # ====== هوشمندی: چک سلامت دیتابیس هنگام start سوپر ادمین ======
    # اگر دیتابیس کمتر از حداقل کاربران داشت → درخواست فایل بکاپ از ادمین
    if int(user_id) == int(ADMIN_ID) and not _restore_pending:
        try:
            total_users = db.conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()['c']
        except Exception:
            total_users = 0
        if total_users < 100:
            with _restore_pending_lock:
                _restore_pending = True
            try:
                bot.send_message(ADMIN_ID,
                    f"⚠️ *هشدار بازیابی دیتابیس*\n\n"
                    f"دیتابیس فعلی فقط {to_persian_int(total_users)} کاربر دارد.\n"
                    f"به نظر می‌رسد بکاپ اصلی بارگذاری نشده است.\n\n"
                    f"📤 لطفاً فایل bot_data.db را همین‌جا ارسال کنید.\n"
                    f"(برای لغو: /cancel)", parse_mode="Markdown")
                print(f"⚠️ DB has only {total_users} users — restore requested from admin", flush=True)
            except Exception as e:
                logger.error(f"auto-restore request error: {e}")

    if len(args) > 1 and args[1].strip():
        param = args[1].strip()  # رفع باگ: strip کردن پارامتر برای جلوگیری از مشکل فاصله‌های اضافی
        if param == "welcome":
            name = message.from_user.first_name or "رفیق"
            if is_new:
                # کاربر جدید — ثبت با source=welcome و شروع ویزارد
                db.upsert_user_basic(user_id, name, message.from_user.username, source="welcome")
                _grant_first_entry_gift(user_id)
                _start_new_user_wizard(chat_id, name, tone="warm")
            else:
                # کاربر قدیمی — پیام کوتاه
                caption = texts.ALREADY_MEMBER
                photo_id = PROMO_WELCOME_OLD_PHOTO_ID
                welcome_markup = types.InlineKeyboardMarkup(row_width=2)
                welcome_markup.add(
                    types.InlineKeyboardButton("🔍 تلهٔ من", callback_data="my_link_show"),
                    types.InlineKeyboardButton("ℹ️ اطلاعات من", callback_data="my_info"),
                    types.InlineKeyboardButton("📖 راهنما", callback_data="help"),
                    types.InlineKeyboardButton("🏅 VIP", callback_data="vip_info"),
                    types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu")
                )
                if photo_id:
                    try:
                        bot.send_photo(user_id, photo_id, caption=caption, reply_markup=welcome_markup)
                    except:
                        bot.reply_to(message, caption, reply_markup=welcome_markup)
                else:
                    bot.reply_to(message, caption, reply_markup=welcome_markup)
            return
        # ── v4.4: خرید تک‌نفرهٔ هویت از مینی‌اپ — param: reveal_<base62> ──
        # (رفع باگ: این پارامتر قبلاً هیچ هندلری نداشت و «لینک نامعتبر» می‌داد)
        if param.startswith("reveal_"):
            try:
                rid = decode_id(param[len("reveal_"):])
            except Exception:
                bot.reply_to(message, "🔴 لینک نامعتبر.", reply_markup=main_menu(message.from_user.id)); return
            if rid <= 0 or rid == user_id:
                bot.reply_to(message, "🔴 لینک نامعتبر.", reply_markup=main_menu(message.from_user.id)); return
            if db.is_vip(user_id):
                bot.reply_to(message, "🏅 تو VIP هستی — هویت همهٔ فضول‌ها برایت رایگان است!", reply_markup=main_menu(user_id)); return
            if db.is_revealed(user_id, rid):
                bot.reply_to(message, "✅ این هویت قبلاً باز شده — از «اطلاعات فضول» ببین.", reply_markup=main_menu(user_id)); return
            # امنیتی: فقط فضولِ واقعی تلهٔ خودت قابل بازکردن است — ضد فورج پارامتر
            _rv_snoops = db.get_snoops(user_id)
            if not any(s['clicker_id'] == rid for s in _rv_snoops):
                bot.reply_to(message, "⛔ این کاربر فضول تلهٔ تو نیست.", reply_markup=main_menu(user_id)); return
            price_rial = db.get_setting_int("reveal_price", 30000)
            try:
                bot.send_invoice(chat_id,
                    title="🔓 باز کردن هویت فضول",
                    description="مشاهدهٔ شناسه و آیدی کامل این فضول — برای همیشه",
                    invoice_payload=f"reveal_{user_id}_{rid}", provider_token=PROVIDER_TOKEN, currency="IRT",
                    prices=[types.LabeledPrice(label="باز کردن هویت", amount=price_rial)],
                    need_name=False, need_phone_number=False, need_email=False, is_flexible=False)
                bot.reply_to(message, "🧾 فاکتور در همین چت ارسال شد — روی «پرداخت» بزن.")
            except Exception as e:
                logger.error(f"Miniapp reveal invoice error: {e}")
                bot.reply_to(message, "❌ خطا در ایجاد فاکتور. بعداً تلاش کن.", reply_markup=main_menu(user_id))
            return
        # v3.6: اول چک کن پارامتر کد تلهٔ چندگانه است
        trap_code = None
        trap_row = db.get_trap_by_code(param)
        if trap_row:
            owner_id = trap_row['owner_id']
            trap_code = param
        elif not param.isdigit():
            try: owner_id = decode_id(param)
            except:
                bot.reply_to(message, "🔴 لینک نامعتبر.", reply_markup=main_menu(message.from_user.id)); return
        else: owner_id = int(param)
        clicker = message.from_user; clicker_id = clicker.id
        if clicker_id == owner_id:
            bot.reply_to(message, "🤨 روی لینک خودت نزن میفهمم😉", reply_markup=main_menu(message.from_user.id)); return
        if not can_click(clicker_id):
            bot.reply_to(message, "⏳ *کمی صبر کن و دوباره تلاش کن...*", reply_markup=main_menu(message.from_user.id)); return
        reg_click(clicker_id)
        clicker_name = clicker.first_name or "بی‌نام"; clicker_username = clicker.username
        # is_new از قبل محاسبه شده (clicker_id == user_id)
        if is_new:
            db.upsert_user_basic(clicker_id, clicker_name, clicker_username, source="referral")
            _grant_first_entry_gift(clicker_id)
            # شروع ویزارد برای کاربر جدید (بعد از ثبت کلیک)
            # ولی اول باید پیام‌های مربوط به کلیک رو بفرستیم
        photo_file_id = get_user_photo_file_id(clicker_id)
        try:
            chat_info = bot.get_chat(clicker_id)
            clicker_name = chat_info.first_name or clicker_name
            clicker_username = chat_info.username or clicker_username
        except: pass
        # v4.4: نام نمایشی دلخواه — اگر کاربر در پروفایل نامی برای خودش انتخاب کرده،
        # همان در گزارش فضول‌گیری صاحب لینک نمایش داده می‌شود
        try:
            _custom_disp = db.get_display_name(clicker_id)
            if _custom_disp:
                clicker_name = _custom_disp
        except Exception:
            pass
        repeat = db.add_click(owner_id, clicker_id, clicker_name, clicker_username, is_new, trap_code=trap_code)
        vip_owner = db.is_vip(owner_id)
        t = datetime.datetime.now().strftime("%Y/%m/%d - %H:%M")
        display_name = get_user_display(clicker_id, clicker_name)

        # v4.4: پاداش VIP صاحب تله — به ازای هر فضول جدید، ۱ روز VIP رایگان
        # (فقط تا وقتی VIP فعال دارد؛ جایگزین پاداش حذف‌شدهٔ v3.24.7 با درخواست ادمین)
        gift_vip_given = False
        if repeat == 1 and db.is_vip(owner_id):
            try:
                db.add_vip(owner_id, 1)
                db.add_transaction(owner_id, "trap_vip_bonus", 0, 1)
                gift_vip_given = True
                try:
                    bot.send_message(owner_id, texts.VIP_PIPE_DAY_BONUS)
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"trap vip bonus error: {e}")

        # ----- اعطای XP به صاحب لینک -----
        # اگر این کلیک از یک فضول یکتاست (یعنی این clicker_id قبلاً روی این لینک کلیک نکرده)،
        # XP فضول جدید می‌گیره. همچنین اگر کاربر جدید بود، XP دعوت موفق.
        if repeat == 1:
            # اولین کلیک این clicker_id → فضول یکتای جدید
            bonus = 'first_snoop' if db.get_distinct_snoop_count(owner_id) == 1 else None
            award_xp_with_level_up_notify(
                owner_id, 0,
                recurring_type='new_distinct_snoop',
                bonus_type=bonus,
                chat_id=owner_id
            )
        if is_new:
            # دعوت موفق (کاربر جدید از لینک این شخص)
            bonus = 'first_invite' if db.get_user_invite_count(owner_id) == 1 else None
            award_xp_with_level_up_notify(
                owner_id, 0,
                recurring_type='successful_invite',
                bonus_type=bonus,
                chat_id=owner_id
            )
        # ----- اعطای XP روزانه به کلیک‌کننده -----
        maybe_daily_login_xp(clicker_id, chat_id=clicker_id)

        if db.is_snoop_muted(owner_id, clicker_id):
            scary_markup = types.InlineKeyboardMarkup(row_width=1)
            scary_markup.add(types.InlineKeyboardButton("🔍 ساخت تلهٔ من", callback_data="my_link_show"))
            scary_markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
            # v3.19: خط هدیهٔ ورود فقط برای کاربر جدید (اولین ورود) — نه کلیک‌های بعدی
            _gift_line = texts.SCARY_GIFT_LINE.format(days=to_persian_digits(trial_days)) if (is_new and trial_days > 0) else ""
            try:
                if SCARY_PHOTO_ID:
                    bot.send_photo(clicker_id, SCARY_PHOTO_ID, caption=texts.SCARY_TIMEOUT.format(link=user_link(clicker_id), gift_line=_gift_line), reply_markup=scary_markup)
                else:
                    bot.send_message(clicker_id, texts.SCARY_TIMEOUT.format(link=user_link(clicker_id), gift_line=_gift_line), reply_markup=scary_markup)
            except: pass
            # کاربر بی‌صدا شده گزارشی برای صاحب لینک ندارد (مثل جریان قبلی — بدون ویزارد)
            return

        # ── v4.4: مرحلهٔ تصمیم «حفظ آبرو / لو رفتن» — قبل از هر گزارش و پیام دیگری ──
        # اگر تصمیمِ بازِ همین تله وجود دارد (کلیک مجدد)، فقط یادآوری کن — گزارش هنوز ارسال نشده.
        open_dec = db.get_open_trap_decision(clicker_id, owner_id)
        if open_dec:
            _trap_send_decision_message(open_dec)
            return
        # ثبت تصمیم باز: ۱ دقیقه فرصت فشردن دکمه؛ تایمر پس‌زمینه هر راه فراری را می‌بندد.
        decision_id = db.create_trap_decision(
            clicker_id, owner_id, trap_code, is_new, repeat,
            display_name, clicker_username, photo_file_id,
            deadline=time.time() + TRAP_PENDING_SECONDS)
        _trap_send_decision_message(db.get_trap_decision(decision_id))
        return
    else:
        # استارت بدون پارامتر — از is_new که در ابتدای تابع محاسبه شده استفاده می‌کنیم
        # رفع باگ: پارامتر باید strip شود تا فاصله‌های اضافی مشکلی نسازند
        name = message.from_user.first_name or "رفیق"

        if is_new:
            # کاربر جدید بدون پارامتر (از سرچ بله) — شروع ویزارد
            db.upsert_user_basic(user_id, name, message.from_user.username, source="organic")
            _grant_first_entry_gift(user_id)
            _start_new_user_wizard(chat_id, name, tone="warm")
            return

        if not is_subscribed(user_id):
            markup = build_channel_keyboard("main_menu", user_id)
            bot.reply_to(message, texts.FORCE_JOIN_PROMPT, reply_markup=markup if markup else main_menu(user_id))
        else:
            if db.is_vip(user_id):
                days_left = db.get_vip_days_left(user_id)   # بدون +1
                if days_left == 0:
                    days_str = "امروز آخرین روز"
                else:
                    days_str = f"{days_left} روز"
                bot.reply_to(message, texts.VIP_WELCOME.format(name=escape_md(name), days=days_str), reply_markup=main_menu(user_id))
            else:
                bot.reply_to(message, texts.WELCOME.format(link=user_link(user_id)), reply_markup=main_menu(user_id))

# ====== پخش همگانی (با استفاده از lock + کیبورد معمولی) ======
# همه نوع محتوا پشتیبانی می‌شود: متن، عکس، ویدیو، صدا، ویس، گیف، استیکر، فایل، موقعیت، تماس و غیر
# نکته: اگه در حالت انتظار دکمه‌ها (broadcast_awaiting_buttons) باشیم، این هندلر پیام‌های متنی
# را نمی‌گیرد تا به‌جای محتوای پخش، به‌عنوان تعریف دکمه پردازش شوند.
@bot.message_handler(
    func=lambda msg: broadcast_mode
                     and msg.chat.id == broadcast_admin_chat
                     and not broadcast_awaiting_buttons
                     and not (msg.text and (
                         msg.text == '👁 مشاهده پیش‌نمایش'
                         or msg.text == '❌ لغو'
                         or msg.text == '➕ افزودن دکمه اینلاین'
                         or msg.text == '🗑 حذف دکمه‌ها'
                     )),
    content_types=['text', 'photo', 'video', 'document', 'audio', 'voice',
                   'animation', 'video_note', 'sticker', 'contact', 'location', 'venue']
)
def broadcast_handler(message):
    global broadcast_preview_msg, broadcast_inline_markup, broadcast_preview_sent_msg_id
    with broadcast_lock:
        if not broadcast_mode:
            return
        if broadcast_started_at and (time.time() - broadcast_started_at > BROADCAST_TIMEOUT):
            set_broadcast_mode(False)
            # رفع باگ: wrap در try/except
            try:
                bot.reply_to(message, "⏱️ زمان حالت پخش همگانی قبلاً به پایان رسیده بود و خودکار لغو شد.")
            except Exception as e:
                logger.error(f"broadcast timeout notify error: {e}")
            return

        # اگه پیام پیش‌نمایش قبلی وجود داره، پاکش کن
        old_preview_id = broadcast_preview_sent_msg_id
        broadcast_preview_msg = message
        # هر بار پیام جدید، دکمه‌های قبلی رو پاک کن
        broadcast_inline_markup = None
        broadcast_preview_sent_msg_id = None
        # v3.19: ددلاین ۵ دقیقه‌ای برای مرحلهٔ تأیید — اگر ادمین تأیید نکند،
        # watcher خودکار لغو می‌کند و کیبورد تأیید جمع می‌شود (جلوگیری از هنگ/کرش)
        global broadcast_confirm_deadline
        broadcast_confirm_deadline = time.time() + BROADCAST_TIMEOUT
        total_users = len(db.get_broadcast_targets())

    # حذف پیام پیش‌نمایش قبلی (اگه بود)
    if old_preview_id:
        try:
            bot.delete_message(message.chat.id, old_preview_id)
        except Exception:
            pass

    # ارسال پیش‌نمایش به ادمین (با دکمه‌های فعلی — در اینجا هیچ‌چیز الصاق نمی‌شه چون inline_markup=None شد)
    preview_msg_id = send_preview_to_admin(message.chat.id, message, inline_markup=None)

    if preview_msg_id:
        set_broadcast_preview_sent_msg_id(preview_msg_id)
        preview_status_line = "👁 پیش‌نمایش بالا برای شما ارسال شد."
    else:
        preview_status_line = "⚠️ ارسال پیش‌نمایش ناموفق بود — ولی پیام ذخیره شد."

    # کیبورد معمولی با گزینه‌های مشاهده پیش‌نمایش / افزودن دکمه / لغو
    markup = broadcast_preview_keyboard(total_users)
    # رفع باگ: wrap در try/except
    try:
        bot.reply_to(message,
            f"📢 *پیام پخش همگانی دریافت شد*\n\n"
            f"{preview_status_line}\n\n"
            f"👥 این پیام برای {to_persian_digits(total_users)} کاربر ارسال خواهد شد.\n\n"
            f"🔘 برای افزودن دکمه اینلاین به پیام، گزینه «➕ افزودن دکمه اینلاین» را بزنید.\n"
            f"👁 برای مشاهده دوباره پیش‌نمایش، «مشاهده پیش‌نمایش» را بزنید.\n"
            f"⏳ اگر تا {BROADCAST_TIMEOUT//60} دقیقه تأیید نکنی، ارسال خودکار لغو می‌شود.",
            reply_markup=markup)
    except Exception as e:
        logger.error(f"broadcast preview reply error: {e}")

def _send_anon_report_to_admin(sender_id, receiver_id, text, is_reply=False):
    # v4.2 (fozol-pro): منسوخ — آرشیو پیام‌های ناشناس به‌جای PV ادمین، در پنل ادمین مینی‌اپ است.
    return None

# ====== مدیریت پیام‌های متنی ======
@bot.message_handler(func=lambda msg: msg.text and not msg.text.startswith('/'), content_types=['text'])
def text_handler(message):
    # v3.24.4: تلمتری — کل پردازش پیام متنی با زمان‌سنج؛ فراخوانی هندلر واقعی
    _t0 = time.time()
    try:
        _label = (message.text or "text").strip()[:40] if message.text else "text"
    except Exception:
        _label = "text"
    try:
        _text_handler_inner(message)
    finally:
        try:
            db.log_usage_event("msg", _label, (time.time() - _t0) * 1000)
        except Exception:
            pass

def _text_handler_inner(message):
    chat_id = message.chat.id
    # v3.22: دروازهٔ حالت نگهداری — فقط سوپرادمین عبور می‌کند
    if maintenance_gate(message.from_user.id):
        try:
            bot.reply_to(message, texts.MAINTENANCE_NOTICE)
        except Exception:
            pass
        return
    record_message(message.from_user.id)
    if db.is_blocked(chat_id):
        # رفع باگ: wrap در try/except
        try:
            bot.reply_to(message, "⛔ حساب شما مسدود شده است.")
        except Exception:
            pass
        return
    # v3.24.3: sync پروفایل → پس‌زمینه (commit روی قفل تک-کانکشن مسیر پیام را کند می‌کرد)
    threading.Thread(target=db.sync_user_profile,
                     args=(chat_id, message.from_user.first_name, message.from_user.username),
                     daemon=True).start()
    text = message.text.strip()

    # ====== حالت تبلیغ: دریافت لینک تبلیغ از سوپرادمین ======
    # (این حالت قبل از شروع broadcast_mode است — لینک باید متن خالص باشد)
    if chat_id == ADMIN_ID and get_broadcast_ad_awaiting_link():
        if text == "❌ لغو":
            set_broadcast_ad_awaiting_link(False)
            set_broadcast_ad_started_at(None)
            set_broadcast_ad_link(None)
            try:
                bot.send_message(chat_id, "❌ حالت تبلیغ لغو شد.", reply_markup=types.ReplyKeyboardRemove())
            except Exception:
                pass
            return
        url = text
        if not (url.startswith('http://') or url.startswith('https://')):
            try:
                bot.send_message(chat_id,
                    "❌ لینک نامعتبر است! لینک باید با `http://` یا `https://` شروع شود.\n\n"
                    "دوباره لینک را بفرستید یا «❌ لغو» را بزنید.",
                    reply_markup=types.ReplyKeyboardMarkup(
                        row_width=1, resize_keyboard=True, one_time_keyboard=False
                    ).add(types.KeyboardButton("❌ لغو")),
                    parse_mode="Markdown")
            except Exception:
                pass
            return
        # لینک معتبر — بستن حالت انتظار و ساخت/ارسال نمونه
        set_broadcast_ad_awaiting_link(False)
        set_broadcast_ad_started_at(None)
        _start_ad_broadcast(chat_id, url)
        return

    # ====== هندلینگ کیبورد معمولی پخش همگانی (مشاهده پیش‌نمایش / افزودن دکمه / حذف دکمه / لغو) ======
    if chat_id == ADMIN_ID and broadcast_mode and broadcast_preview_msg:
        # ----- حالت انتظار دکمه‌ها: متن دریافتی به‌عنوان تعریف دکمه‌ها پردازش می‌شود -----
        if broadcast_awaiting_buttons:
            # در حالت انتظار دکمه، تنها «❌ لغو» اتمام‌دهنده است
            if text == "❌ لغو":
                set_broadcast_awaiting_buttons(False)
                total_users = len(db.get_broadcast_targets())
                markup = broadcast_preview_keyboard(total_users)
                bot.send_message(chat_id,
                    "❌ افزودن دکمه‌ها لغو شد.\n"
                    "می‌توانید دوباره دکمه‌ها را اضافه کنید یا پیش‌نمایش را ببینید.",
                    reply_markup=markup)
                return
            # پردازش تعریف دکمه‌ها
            success, result = parse_button_definitions(text)
            if not success:
                # خطا — دوباره از ادمین بخواه
                bot.send_message(chat_id,
                    result + "\n\nلطفاً دوباره دکمه‌ها را به‌فرمت صحیح بفرستید یا روی «❌ لغو» بزنید.",
                    reply_markup=types.ReplyKeyboardMarkup(
                        row_width=1, resize_keyboard=True, one_time_keyboard=True
                    ).add(types.KeyboardButton("❌ لغو")))
                return
            # دکمه‌ها با موفقیت ساخته شد
            set_broadcast_inline_markup(result)
            set_broadcast_awaiting_buttons(False)
            total_users = len(db.get_broadcast_targets())
            markup = broadcast_preview_keyboard(total_users)

            # حذف پیش‌نمایش قبلی
            delete_preview_message(chat_id)

            # ارسال پیش‌نمایش جدید با دکمه‌های اینلاین (با editMessageReplyMarkup)
            preview_msg_id = send_preview_to_admin(chat_id, broadcast_preview_msg, inline_markup=result)
            if preview_msg_id:
                set_broadcast_preview_sent_msg_id(preview_msg_id)
                preview_status = "👁 پیش‌نمایش بالا با دکمه‌های اینلاین الصاق‌شده ارسال شد."
            else:
                preview_status = "⚠️ ارسال پیش‌نمایش ناموفق بود، اما دکمه‌ها ذخیره شدند."

            bot.send_message(chat_id,
                f"✅ {to_persian_digits(len(result.keyboard))} دکمه اینلاین به پیام الصاق شد.\n\n"
                f"{preview_status}\n\n"
                f"اگر همه چیز درست است، روی دکمه «✅ تأیید و ارسال به همه» زیر پیام بزنید.",
                reply_markup=markup)
            return

        # ----- دکمه‌های کنترلی کیبورد معمولی -----
        if text == "👁 مشاهده پیش‌نمایش":
            # حذف پیش‌نمایش قبلی
            delete_preview_message(chat_id)

            # ارسال پیش‌نمایش جدید
            current_markup = get_broadcast_inline_markup()
            preview_msg_id = send_preview_to_admin(chat_id, broadcast_preview_msg, inline_markup=current_markup)
            if preview_msg_id:
                set_broadcast_preview_sent_msg_id(preview_msg_id)
                bot.send_message(chat_id,
                    "👁 پیش‌نمایش بالا برای شما ارسال شد.\n"
                    "اگر همه چیز درست است، روی دکمه «✅ تأیید و ارسال به همه» زیر پیام بزنید.",
                    reply_markup=broadcast_preview_keyboard(len(db.get_broadcast_targets())))
            else:
                bot.send_message(chat_id,
                    "⚠️ ارسال پیش‌نمایش ناموفق بود. دوباره تلاش کنید.")
            return
        elif text == "❌ لغو":
            # حذف پیش‌نمایش قبلی
            delete_preview_message(chat_id)
            set_broadcast_mode(False)
            bot.send_message(chat_id, "❌ ارسال همگانی لغو شد.", reply_markup=types.ReplyKeyboardRemove())
            return
        elif text == "➕ افزودن دکمه اینلاین":
            # ورود به حالت انتظار تعریف دکمه‌ها
            set_broadcast_awaiting_buttons(True)
            instructions = (
                "🔘 *افزودن دکمه اینلاین*\n\n"
                "دکمه‌ها را با فرمت زیر بفرستید — هر خط یک دکمه:\n\n"
                "`متن دکمه ۱|https://example.com`\n"
                "`متن دکمه ۲|https://example2.com`\n\n"
                "• جداکننده: کاراکتر `|`\n"
                "• URL باید با `http://` یا `https://` شروع شود\n"
                "• هر خط یک دکمه (هر کدام در یک ردیف جدا نمایش داده می‌شود)\n\n"
                "مثال:\n"
                "`سایت ما|https://example.com`\n"
                "`کانال ما|https://t.me/mychannel`\n"
                "`گروه ما|https://t.me/mygroup`"
            )
            bot.send_message(chat_id, instructions,
                reply_markup=types.ReplyKeyboardMarkup(
                    row_width=1, resize_keyboard=True, one_time_keyboard=False
                ).add(types.KeyboardButton("❌ لغو")),
                parse_mode="Markdown")
            return
        elif text == "🗑 حذف دکمه‌ها":
            set_broadcast_inline_markup(None)
            total_users = len(db.get_broadcast_targets())
            markup = broadcast_preview_keyboard(total_users)
            # حذف پیش‌نمایش قبلی
            delete_preview_message(chat_id)
            # ارسال پیش‌نمایش جدید بدون دکمه
            preview_msg_id = send_preview_to_admin(chat_id, broadcast_preview_msg, inline_markup=None)
            if preview_msg_id:
                set_broadcast_preview_sent_msg_id(preview_msg_id)
                preview_status = "👁 پیش‌نمایش بدون دکمه ارسال شد."
            else:
                preview_status = "⚠️ ارسال پیش‌نمایش ناموفق بود."
            bot.send_message(chat_id,
                f"🗑 دکمه‌های اینلاین حذف شدند.\n{preview_status}",
                reply_markup=markup)
            return

    state = get_user_state(chat_id)
    if state is not None:
        if state[0] == 'gift_code':
            clear_user_state(chat_id)
            now = time.time()
            # حذف تلاش‌های قدیمی (بیشتر از ۱ ساعت)
            while gift_attempt_rate[chat_id] and gift_attempt_rate[chat_id][0] < now - 3600:
                gift_attempt_rate[chat_id].popleft()

            if len(gift_attempt_rate[chat_id]) >= 5:
                bot.reply_to(message, "⏳ تعداد تلاش‌های شما برای کد هدیه به پایان رسید. یک ساعت صبر کنید.",
                             reply_markup=home_markup())
                return

            # ثبت این تلاش
            gift_attempt_rate[chat_id].append(now)

            result, gift_data = db.redeem_gift(text, chat_id)
            if result:
                bot.reply_to(message, f"🎉 کد با موفقیت فعال شد! {gift_data} روز VIP به حساب شما اضافه شد.",
                             reply_markup=home_markup())
            else:
                bot.reply_to(message, f"❌ {gift_data}", reply_markup=home_markup())
            return

        elif state[0] == 'anon_reply':
            target_id = state[1]; clear_user_state(chat_id)
            # v4.4: پیام ناشناس فقط برای VIP (لایهٔ دوم — ضد فورج کال‌بک/حالت)
            _vg = anon_vip_gate(chat_id)
            if _vg:
                bot.reply_to(message, _vg[0], reply_markup=_vg[1])
                return
            if not is_subscribed(chat_id):
                markup = build_channel_keyboard(f"anon_reply_{target_id}", chat_id)
                if markup:
                    bot.reply_to(message, texts.FORCE_JOIN_PROMPT, reply_markup=markup)
                return
            # فیلتر محتوای نامناسب
            is_bad, reason = is_inappropriate_content(text)
            if is_bad:
                bot.reply_to(message,
                    f"❌ پیام شما شامل {reason} است و ارسال نشد.\n"
                    "لطفاً متن مناسبی وارد کنید.",
                    reply_markup=home_markup())
                return
            # اصلاح: افزودن rate limit
            # v3.22 امنیتی: ضد تماس سرد — فقط طرفِ گفتگوی ناشناسِ موجود
            if not can_anon_contact(chat_id, target_id):
                bot.reply_to(message, "⛔ فقط می‌توانی به فضول‌های تلهٔ خودت یا طرفِ گفتگوی ناشناس فعلی پیام بدهی.", reply_markup=home_markup()); return
            if not can_send_anon(chat_id, target_id):
                bot.reply_to(message, "⏳ محدودیت پیام ناشناس! کمی صبر کن.", reply_markup=home_markup()); return
            # رفع باگ: بررسی block قبل از reg_anon — وگرنه rate limit بیهوده مصرف می‌شود
            if db.is_anon_blocked(target_id, chat_id):
                bot.reply_to(message, "⛔ این کاربر شما را بلاک کرده است. پاسخ ارسال نشد.", reply_markup=home_markup()); return
            reg_anon(chat_id, target_id)
            # رفع باگ: اعمال نقاب VIP برای پاسخ ناشناس هم (مثل anon_msg)
            mask = None
            if db.is_vip(chat_id):
                mask_data = db.get_user_mask(chat_id)
                if mask_data:
                    emoji, mask_text = mask_data
                    mask = f"{emoji} {escape_md(mask_text)}" if mask_text else emoji
            msg_text = f"🎭 *{mask}* نجوا کرد:\n{escape_md(text)}" if mask else f"📩 *پاسخ ناشناس:*\n{escape_md(text)}"
            reply_markup = types.InlineKeyboardMarkup()
            reply_markup.add(types.InlineKeyboardButton("🔄 پاسخ ناشناس", callback_data=f"anon_reply_{chat_id}"))
            # رفع باگ: حذف dead code — چون در این نقطه target مطمئناً sender را بلاک نکرده
            reply_markup.add(types.InlineKeyboardButton("🚫 بلاک", callback_data=f"block_{chat_id}"),
                             types.InlineKeyboardButton("⚠️ گزارش تخلف", callback_data=f"report_{chat_id}"))
            try:
                bot.send_message(target_id, msg_text, reply_markup=reply_markup)
                db.add_anon_log(chat_id, target_id, text)
                bot.reply_to(message, "📨 پاسخ ناشناس ارسال شد...", reply_markup=home_markup())
                # v4.2: گزارش به PV ادمین حذف شد — آرشیو کامل در پنل ادمین مینی‌اپ (آرشیو پیام‌های ناشناس)
            except Exception as e:
                logger.error(f"Anon reply send error: {e}")
                bot.reply_to(message, "❌ ارسال ناموفق بود. لطفاً دوباره تلاش کن.", reply_markup=home_markup())
            return

        elif state[0] == 'anon_msg':
            target_id = state[1]; clear_user_state(chat_id)
            # v4.4: پیام ناشناس فقط برای VIP (لایهٔ دوم — ضد فورج کال‌بک/حالت)
            _vg = anon_vip_gate(chat_id)
            if _vg:
                bot.reply_to(message, _vg[0], reply_markup=_vg[1])
                return
            if not is_subscribed(chat_id):
                markup = build_channel_keyboard(f"anon_{target_id}", chat_id)
                if markup:
                    bot.reply_to(message, texts.FORCE_JOIN_PROMPT, reply_markup=markup)
                return
            # فیلتر محتوای نامناسب
            is_bad, reason = is_inappropriate_content(text)
            if is_bad:
                bot.reply_to(message,
                    f"❌ پیام شما شامل {reason} است و ارسال نشد.\n"
                    "لطفاً متن مناسبی وارد کنید.",
                    reply_markup=home_markup())
                return
            # v3.22 امنیتی: ضد تماس سرد — فقط فضول‌های تلهٔ خودت یا طرف گفتگوی قبلی
            if not can_anon_contact(chat_id, target_id):
                bot.reply_to(message, "⛔ فقط می‌توانی به فضول‌های تلهٔ خودت یا طرفِ گفتگوی ناشناس فعلی پیام بدهی.", reply_markup=home_markup()); return
            if not can_send_anon(chat_id, target_id):
                bot.reply_to(message, "⏳ محدودیت پیام ناشناس! کمی صبر کن.", reply_markup=home_markup()); return
            if db.is_anon_blocked(target_id, chat_id):
                bot.reply_to(message, "⛔ این کاربر شما را بلاک کرده است. پیام ارسال نشد.", reply_markup=home_markup()); return
            reg_anon(chat_id, target_id)
            mask = None
            if db.is_vip(chat_id):
                mask_data = db.get_user_mask(chat_id)
                if mask_data:
                    emoji, mask_text = mask_data
                    mask = f"{emoji} {escape_md(mask_text)}" if mask_text else emoji
            msg_text = f"🎭 *{mask}* نجوا کرد:\n{escape_md(text)}" if mask else f"📩 *پیام ناشناس:*\n{escape_md(text)}"
            reply_markup = types.InlineKeyboardMarkup()
            reply_markup.add(types.InlineKeyboardButton("🔄 پاسخ ناشناس", callback_data=f"anon_reply_{chat_id}"))
            # رفع باگ: حذف dead code — چون در این نقطه target مطمئناً sender را بلاک نکرده
            reply_markup.add(types.InlineKeyboardButton("🚫 بلاک", callback_data=f"block_{chat_id}"),
                             types.InlineKeyboardButton("⚠️ گزارش تخلف", callback_data=f"report_{chat_id}"))
            try:
                bot.send_message(target_id, msg_text, reply_markup=reply_markup)
                db.add_anon_log(chat_id, target_id, text)
                bot.reply_to(message, "📨 پیام ناشناس ارسال شد...", reply_markup=home_markup())
                # v4.2: گزارش به PV ادمین حذف شد — آرشیو کامل در پنل ادمین مینی‌اپ (آرشیو پیام‌های ناشناس)
            except Exception as e:
                logger.error(f"Anon send error: {e}")
                bot.reply_to(message, "❌ ارسال ناموفق بود. لطفاً دوباره تلاش کن.", reply_markup=home_markup())
            return

        elif state[0] == 'nickname':
            cid = state[1]; clear_user_state(chat_id)
            # فیلتر محتوای نامناسب
            is_bad, reason = is_inappropriate_content(text)
            if is_bad:
                bot.reply_to(message,
                    f"❌ لقب شما شامل {reason} است.\n"
                    "لطفاً لقب دیگری وارد کنید.",
                    reply_markup=home_markup())
                return
            db.set_nickname(chat_id, cid, text)
            bot.reply_to(message, f"📜 لقب «{escape_md(text)}» در کتاب سایه‌ها ثبت شد.", reply_markup=home_markup())
            return

        elif state[0] == 'link_text':
            # v4.7 (باگ بیو): بایو بله حداکثر ۷۰ کاراکتر است؛ هایپرلینک خالی
            # [](لینک) به‌ازای هر لینک (طول لینک + ۴) کاراکتر می‌گیرد؛ برای لینک
            # اصلی ۲۵کاراکتری = ۲۹ → متن حداکثر ۴۱ کاراکتر. بلندتر → پیام کوتاه.
            _link = user_link(chat_id)
            _bio_limit = 70 - (len(_link) + 4)
            if len(text) > _bio_limit:
                set_user_state(chat_id, ('link_text',))
                bot.reply_to(message, "❗ *توی بیو جا نمیشه! کوتاه تر بنویس*\n\n"
                             f"حداکثر {_bio_limit} کاراکتر — متن فعلی {to_persian_digits(len(text))} کاراکتر است.",
                             reply_markup=cancel_markup())
                return
            clear_user_state(chat_id)
            full_link = f"[{escape_md(text)}]({_link})"
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(types.InlineKeyboardButton("📋 کپی لینک", callback_data="copy_dummy",
                                                  copy_text=types.CopyTextButton(full_link)))
            markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
            final_text = (
                f"🎭 *هایپرلینک تو ساخته شد:*\n{full_link}\n\n"
                f"💡 اونو کپی کن و توی بیوگرافیت بذار تا فضول‌ها رو شکار کنی..."
            )
            bot.reply_to(message, final_text, reply_markup=markup)
            return

        elif state[0] == 'add_trap_label':
            clear_user_state(chat_id)
            if not db.is_vip(chat_id):
                bot.reply_to(message, texts.MY_TRAPS_VIP_ONLY, reply_markup=vip_menu_button()); return
            label = text[:30].strip() or "تله"
            code = db.create_trap(chat_id, label)
            tlink = f"ble.ir/{BOT_USERNAME}?start={code}"
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(types.InlineKeyboardButton("📋 کپی لینک تله", callback_data=f"copy_trap_{code}",
                                                  copy_text=types.CopyTextButton(tlink)))
            markup.add(types.InlineKeyboardButton("🕳️ تله‌های من", callback_data="my_traps"))
            markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
            bot.reply_to(message, texts.TRAP_ADDED.format(label=escape_md(label), link=tlink), reply_markup=markup)
            return

        elif state[0] == 'gvip_id':
            clear_user_state(chat_id)
            if not db.is_vip(chat_id):
                bot.reply_to(message, texts.GVIP_NOT_VIP, reply_markup=vip_menu_button()); return
            raw = fa_to_en_digits(text).strip()
            if not raw.isdigit():
                set_user_state(chat_id, ('gvip_id',))
                bot.reply_to(message, "❌ لطفاً شناسهٔ عددی بفرست (مثلاً: ۱۲۳۴۵۶۷۸۹).", reply_markup=cancel_markup())
                return
            rid = int(raw)
            if rid == chat_id:
                set_user_state(chat_id, ('gvip_id',))
                bot.reply_to(message, texts.GVIP_SELF, reply_markup=cancel_markup())
                return
            target = db.get_user_basic(rid)
            if not target:
                set_user_state(chat_id, ('gvip_id',))
                bot.reply_to(message, texts.GVIP_NOT_FOUND, reply_markup=cancel_markup())
                return
            today_t = datetime.datetime.now(TEHRAN_TZ).date().isoformat()
            if db.get_last_giftvip_date(chat_id) == today_t:
                bot.reply_to(message, texts.GVIP_LIMIT_DAILY, reply_markup=home_markup())
                return
            rname = sanitize_name(target['first_name'] or str(rid))
            set_user_state(chat_id, ('gvip_days', rid))
            bot.reply_to(message, texts.GVIP_ASK_DAYS.format(rname=escape_md(rname)), reply_markup=cancel_markup())
            return

        elif state[0] == 'gvip_days':
            clear_user_state(chat_id)
            rid = state[1] if len(state) > 1 else None
            if rid is None:
                bot.reply_to(message, "⛔ خطا — دوباره از منوی VIP شروع کن.", reply_markup=vip_menu_button()); return
            raw = fa_to_en_digits(text).strip()
            if not raw.isdigit() or not (1 <= int(raw) <= 30):
                set_user_state(chat_id, ('gvip_days', rid))
                bot.reply_to(message, texts.GVIP_INVALID_DAYS, reply_markup=cancel_markup())
                return
            days = int(raw)
            if not db.is_vip(chat_id):
                bot.reply_to(message, texts.GVIP_NOT_VIP, reply_markup=vip_menu_button()); return
            days_left = db.get_vip_days_left(chat_id)
            if days_left <= days:
                set_user_state(chat_id, ('gvip_days', rid))
                bot.reply_to(message, texts.GVIP_NOT_ENOUGH, reply_markup=cancel_markup())
                return
            target = db.get_user_basic(rid)
            if not target:
                bot.reply_to(message, texts.GVIP_NOT_FOUND, reply_markup=home_markup())
                return
            rname = sanitize_name(target['first_name'] or str(rid))
            set_user_state(chat_id, ('gvip_confirm', rid, days))
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(types.InlineKeyboardButton(f"✅ تأیید هدیهٔ {to_persian_digits(days)} روزه", callback_data=f"gvip_go_{rid}_{days}"))
            markup.add(types.InlineKeyboardButton("❌ انصراف", callback_data="cancel_state"))
            bot.reply_to(message, texts.GVIP_CONFIRM.format(rname=escape_md(rname), days=to_persian_digits(days)), reply_markup=markup)
            return

        elif state[0] == 'welcome_text':
            clear_user_state(chat_id)
            if not db.is_vip(chat_id):
                bot.reply_to(message, VIP_EXPIRED_MSG, reply_markup=vip_menu_button()); return
            # فیلتر محتوای نامناسب
            is_bad, reason = is_inappropriate_content(text)
            if is_bad:
                bot.reply_to(message,
                    f"❌ متن شما شامل {reason} است.\n"
                    "لطفاً متن دیگری وارد کنید.",
                    reply_markup=vip_menu_button())
                return
            db.set_welcome_text(chat_id, text)
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(types.InlineKeyboardButton("🖼️ تنظیم عکس خوش‌آمدگویی", callback_data="set_welcome_photo"))
            markup.add(types.InlineKeyboardButton("👑 بازگشت به کارت طلایی", callback_data="vip_info"))
            markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
            bot.reply_to(message,
                "📜 متن خوش‌آمدگویی ثبت شد.\n"
                "🖼️ می‌تونی یه عکس هم بهش اضافه کنی تا کامل‌تر بشه.\n"
                "دکمهٔ زیر رو بزن یا بعداً از منوی VIP اقدام کن.",
                reply_markup=markup)
            return

        elif state[0] == 'mask_emoji':
            clear_user_state(chat_id); emoji = text.strip()
            if not db.is_vip(chat_id):
                bot.reply_to(message, VIP_EXPIRED_MSG, reply_markup=vip_menu_button()); return
            set_user_state(chat_id, ('mask_text', emoji))
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(types.InlineKeyboardButton("بدون لقب", callback_data="mask_skip_text"),
                       types.InlineKeyboardButton("❌ انصراف", callback_data="cancel_state"))
            bot.reply_to(message, "🎭 حالا لقب (متن) نقاب را بفرست، یا یکی از دکمه‌های زیر را بزن.", reply_markup=markup)
            return

        elif state[0] == 'mask_text':
            emoji = state[1]; clear_user_state(chat_id); mask_text = text.strip()
            if not db.is_vip(chat_id):
                bot.reply_to(message, VIP_EXPIRED_MSG, reply_markup=vip_menu_button()); return
            # فیلتر محتوای نامناسب
            is_bad, reason = is_inappropriate_content(mask_text)
            if is_bad:
                bot.reply_to(message,
                    f"❌ لقب نقاب شما شامل {reason} است.\n"
                    "لطفاً لقب دیگری وارد کنید.",
                    reply_markup=vip_menu_button())
                return
            db.set_user_mask(chat_id, emoji, mask_text)
            bot.reply_to(message, f"🎭 نقاب کارآگاهی تو: {emoji} {mask_text}", reply_markup=vip_menu_button())
            return

        elif state[0] == 'new_gift_days':
            days = int(text) if text.isdigit() else 0
            if days <= 0:
                clear_user_state(chat_id)
                bot.reply_to(message, "❌ تعداد روز نامعتبر.", reply_markup=admin_panel_back_markup()); return
            set_user_state(chat_id, ('new_gift_uses', days))
            bot.reply_to(message, "حالا تعداد استفاده (ظرفیت) کد را وارد کنید:", reply_markup=cancel_markup())
            return

        elif state[0] == 'new_gift_uses':
            days = state[1]; clear_user_state(chat_id)
            uses = int(text) if text.isdigit() else 0
            if uses <= 0:
                bot.reply_to(message, "❌ ظرفیت نامعتبر.", reply_markup=admin_panel_back_markup()); return
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            db.create_gift_code(code, days, uses)
            bot.reply_to(message, f"🎁 کد هدیه ساخته شد:\n{code}\nروز: {days} | ظرفیت: {uses}", reply_markup=admin_panel_back_markup())
            return

        elif state[0] == 'set_lb_name':
            # v3.20: نام نمایشی لیدربورد — فقط حروف انگلیسی، فارسی و اعداد مجاز است
            clear_user_state(chat_id)
            _cleaned = re.sub(r' +', ' ', text).strip()
            if (2 <= len(_cleaned) <= 32
                    and re.search(r'[0-9A-Za-z\u0600-\u06FF]', _cleaned)
                    and re.fullmatch(r'[0-9A-Za-z\u0600-\u06FF\u200c ]+', _cleaned)):
                db.set_display_name(chat_id, _cleaned)
                try:
                    bot.reply_to(message, texts.LB_NAME_OK.format(name=_cleaned), reply_markup=home_markup())
                except Exception:
                    pass
                try:
                    show_leaderboard(chat_id, chat_id)
                except Exception as _lbn_err:
                    logger.error("set_lb_name re-render error: %s", _lbn_err)
            else:
                try:
                    bot.reply_to(message, texts.LB_NAME_INVALID, reply_markup=home_markup())
                except Exception:
                    pass
            return

        elif state[0] == 'admin_search_user':
            clear_user_state(chat_id)
            process_admin_search(message)
            return

        elif state[0] == 'admin_addvip':
            clear_user_state(chat_id)
            process_admin_addvip(message)
            return

        elif state[0] == 'admin_edit_price':
            days = state[1]; clear_user_state(chat_id)
            # حذف کاراکترهای اضافی مثل کاما یا تومان
            cleaned = text.replace(',', '').replace('ریال', '').replace('تومان', '').strip()
            # تبدیل اعداد فارسی به انگلیسی برای پردازش
            for i, d in enumerate(PERSIAN_DIGITS):
                cleaned = cleaned.replace(d, str(i))
            try:
                new_price = int(cleaned)
                if new_price <= 0:
                    raise ValueError()
                # اگر به تومان وارد شده (عدد کوچک)، به ریال تبدیل کن
                # اگر عدد کمتر از ۱۰۰۰۰ هست احتمالا تومان وارد شده
                if new_price < 1000:
                    new_price = new_price * 10  # تبدیل تومان به ریال
                VIP_PRICES[days] = new_price
                db.set_vip_price(days, new_price)
                bot.reply_to(message,
                    f"✅ قیمت {to_persian_digits(days)} روزه با موفقیت به‌روزرسانی شد.\n"
                    f"💵 قیمت جدید: {fmt_amount_rial(new_price)} ({fmt_amount_toman(new_price)})",
                    reply_markup=admin_panel_back_markup())
            except (ValueError, TypeError):
                bot.reply_to(message,
                    "❌ عدد نامعتبر. لطفاً فقط عدد (به ریال یا تومان) وارد کنید.",
                    reply_markup=admin_panel_back_markup())
            return

        elif state[0] == 'admin_challenge_hours':
            # v3.18: مدت چالش به ساعت (۱ تا ۷۲۰)
            clear_user_state(chat_id)
            cleaned = text.strip()
            for i, d in enumerate(PERSIAN_DIGITS):
                cleaned = cleaned.replace(d, str(i))
            if not cleaned.isdigit() or not (1 <= int(cleaned) <= 720):
                bot.reply_to(message, "❌ عدد نامعتبر (۱ تا ۷۲۰ ساعت). دوباره بفرست:", reply_markup=cancel_markup())
                set_user_state(chat_id, ('admin_challenge_hours', None))
                return
            hours_val = int(cleaned)
            set_user_state(chat_id, ('admin_challenge_prize', hours_val))
            bot.reply_to(message, texts.ADMIN_CHALLENGE_ASK_PRIZE, reply_markup=cancel_markup())
            return

        elif state[0] == 'admin_challenge_prize':
            # v3.18: جایزهٔ نفر اول به روز VIP (۱ تا ۳۶۵) → نمایش خلاصه و درخواست تأیید
            clear_user_state(chat_id)
            hours_val = state[1]
            cleaned = text.strip()
            for i, d in enumerate(PERSIAN_DIGITS):
                cleaned = cleaned.replace(d, str(i))
            if not cleaned.isdigit() or not (1 <= int(cleaned) <= 365):
                bot.reply_to(message, "❌ عدد نامعتبر (۱ تا ۳۶۵ روز). دوباره بفرست:", reply_markup=cancel_markup())
                set_user_state(chat_id, ('admin_challenge_prize', hours_val))
                return
            prize_val = int(cleaned)
            # پیش‌نمایش پنجرهٔ شمارش: از ۰۰:۰۰ فردا تهران
            preview = _challenge_start_challenge_preview(hours_val, prize_val)
            set_user_state(chat_id, ('admin_challenge_confirm', (hours_val, prize_val)))
            conf_markup = types.InlineKeyboardMarkup(row_width=1)
            conf_markup.add(types.InlineKeyboardButton("✅ بله، شروع کن و به همه اطلاع بده", callback_data="admin_challenge_go"))
            conf_markup.add(types.InlineKeyboardButton("❌ انصراف", callback_data="cancel_state"))
            bot.reply_to(message, texts.ADMIN_CHALLENGE_CONFIRM.format(
                hours=to_persian_digits(hours_val),
                **_challenge_prize_dict(prize_val),
                count_start=preview[2],
                end_time=preview[3]), reply_markup=conf_markup)
            return

        elif state[0] == 'admin_set_trial':
            clear_user_state(chat_id)
            cleaned = text.strip()
            for i, d in enumerate(PERSIAN_DIGITS):
                cleaned = cleaned.replace(d, str(i))
            if not cleaned.isdigit() or not (0 <= int(cleaned) <= 365):
                bot.reply_to(message, "❌ عدد نامعتبر (۰ تا ۳۶۵؛ صفر = غیرفعال).", reply_markup=admin_panel_back_markup())
                return
            val = int(cleaned)
            db.set_setting("trial_days", val)
            bot.reply_to(message, texts.ADMIN_SET_TRIAL_OK.format(value=to_persian_digits(val)), reply_markup=admin_panel_back_markup())
            return

        elif state[0] == 'admin_set_reveal_price':
            clear_user_state(chat_id)
            cleaned = text.replace(',', '').replace('ریال', '').replace('تومان', '').strip()
            for i, d in enumerate(PERSIAN_DIGITS):
                cleaned = cleaned.replace(d, str(i))
            try:
                val = int(cleaned)
                if val <= 0:
                    raise ValueError()
                if val < 10000:      # تومان → ریال
                    val = val * 10
                db.set_setting("reveal_price", val)
                bot.reply_to(message, texts.ADMIN_SET_REVEAL_OK.format(value=to_persian_int(val // 10)), reply_markup=admin_panel_back_markup())
            except (ValueError, TypeError):
                bot.reply_to(message, "❌ عدد نامعتبر (تومان یا ریال).", reply_markup=admin_panel_back_markup())
            return

        elif state[0] == 'admin_set_saveface_price':
            # v4.4: قیمت «حفظ آبرو» تله — تومان یا ریال، سقف ۱۰ میلیون ریال
            clear_user_state(chat_id)
            cleaned = text.replace(',', '').replace('ریال', '').replace('تومان', '').strip()
            for i, d in enumerate(PERSIAN_DIGITS):
                cleaned = cleaned.replace(d, str(i))
            try:
                val = int(cleaned)
                if val <= 0:
                    raise ValueError()
                if val < 10000:      # تومان → ریال
                    val = val * 10
                if val > 100_000_000:
                    raise ValueError()
                db.set_setting("saveface_price", val)
                bot.reply_to(message, f"✅ قیمت «حفظ آبرو» روی {to_persian_int(val // 10)} تومان تنظیم شد.", reply_markup=admin_panel_back_markup())
            except (ValueError, TypeError):
                bot.reply_to(message, "❌ عدد نامعتبر (تومان یا ریال).", reply_markup=admin_panel_back_markup())
            return

        elif state[0] == 'admin_set_weekly_day':
            clear_user_state(chat_id)
            cleaned = text.strip()
            for i, d in enumerate(PERSIAN_DIGITS):
                cleaned = cleaned.replace(d, str(i))
            if not cleaned.isdigit() or not (0 <= int(cleaned) <= 6):
                bot.reply_to(message, "❌ عدد نامعتبر (۰ تا ۶).", reply_markup=admin_panel_back_markup())
                return
            db.set_setting("weekly_report_day", int(cleaned))
            wd = _FA_WEEKDAY.get(int(cleaned), ("جمعه", 4))[0]
            bot.reply_to(message, f"✅ روز گزارش هفتگی: {wd}", reply_markup=admin_panel_back_markup())
            return

        elif state[0] == 'admin_set_weekly_hour':
            clear_user_state(chat_id)
            cleaned = text.strip()
            for i, d in enumerate(PERSIAN_DIGITS):
                cleaned = cleaned.replace(d, str(i))
            if not cleaned.isdigit() or not (0 <= int(cleaned) <= 23):
                bot.reply_to(message, "❌ عدد نامعتبر (۰ تا ۲۳).", reply_markup=admin_panel_back_markup())
                return
            db.set_setting("weekly_report_hour", int(cleaned))
            bot.reply_to(message, f"✅ ساعت گزارش هفتگی: {to_persian_digits(int(cleaned))}:۰۰ (تهران)", reply_markup=admin_panel_back_markup())
            return

        elif state[0] == 'admin_price_monthly':
            # v3.22: فقط قیمت ماهانه گرفته می‌شود؛ بقیهٔ پلن‌ها خودکار محاسبه و پیش‌نمایش داده می‌شوند
            val_rial, unit = parse_price_input(text)
            if val_rial is None:
                bot.reply_to(message, texts.ADMIN_PRICE_INVALID, reply_markup=cancel_markup())
                return
            if not validate_monthly_rial(val_rial):
                bot.reply_to(message,
                    texts.ADMIN_PRICE_RANGE.format(
                        min=to_persian_int(_MIN_MONTHLY_RIAL // 10),
                        max=to_persian_int(_MAX_MONTHLY_RIAL // 10)),
                    reply_markup=cancel_markup())
                return
            computed = compute_vip_prices(val_rial)
            set_user_state(chat_id, ('admin_price_monthly_confirm', computed))
            conf_markup = types.InlineKeyboardMarkup(row_width=1)
            conf_markup.add(types.InlineKeyboardButton("✅ ذخیره و اعمال", callback_data="admin_price_monthly_go"))
            conf_markup.add(types.InlineKeyboardButton("❌ انصراف", callback_data="cancel_state"))
            monthly_disp = fmt_amount_toman(val_rial) if unit == 'toman' else fmt_amount_rial(val_rial)
            bot.reply_to(message,
                texts.ADMIN_PRICE_PREVIEW.format(
                    monthly=monthly_disp,
                    lines=build_vip_price_lines(computed)),
                reply_markup=conf_markup)
            return

        elif state[0] == 'admin_quick_vip':
            target_id = state[1]; clear_user_state(chat_id)
            process_admin_quick_vip(message, target_id)
            return

        elif state[0] == 'admin_quick_vip_minus':
            # v3.16: کاهش روزهای VIP
            target_id = state[1]; clear_user_state(chat_id)
            process_admin_quick_vip_minus(message, target_id)
            return

        elif state[0] == 'admin_new_channel':
            clear_user_state(chat_id)
            ch_input = text.strip()
            info = fetch_channel_info(ch_input)
            if not info or info.get("name") == str(ch_input):
                bot.send_message(chat_id, "❌ نتوانستم اطلاعات کانال را دریافت کنم. مطمئن شوید ربات عضو است.", reply_markup=admin_panel_back_markup())
                return

            name = info["name"]
            link = info["link"]
            # اگر کانال عمومی است (با @ شروع می‌شود)، تست با همان @username
            test_id = info["api_id"]   # همیشه شناسهٔ عددی استاندارد (با -100)

            bot_id = bot.user.id
            try:
                member = bot.get_chat_member(test_id, bot_id)
                if member.status not in ['administrator', 'creator']:
                    bot.send_message(
                        chat_id,
                        "❌ ربات باید **ادمین کانال** باشد تا بتواند عضویت کاربران را بررسی کند.\n"
                        "لطفاً ربات را در کانال ادمین کنید و دوباره امتحان کنید.",
                        reply_markup=admin_panel_back_markup()
                    )
                    return
            except ApiTelegramException as e:
                err_msg = str(e).lower()
                if 'no such group' in err_msg or 'chat not found' in err_msg:
                    bot.send_message(chat_id, "❌ کانال مورد نظر یافت نشد. مطمئن شوید شناسه درست است و ربات عضو کانال باشد.", reply_markup=admin_panel_back_markup())
                elif 'user not found' in err_msg:
                    bot.send_message(chat_id, "❌ ربات نمی‌تواند وضعیت خود را بررسی کند. احتمالاً در کانال عضو نیست.", reply_markup=admin_panel_back_markup())
                else:
                    bot.send_message(chat_id, f"❌ خطای API: {e}", reply_markup=admin_panel_back_markup())
                return
            except Exception as e:
                logger.error(f"Test get_chat_member failed: {e}")
                bot.send_message(chat_id, f"❌ خطای ناشناخته: {e}", reply_markup=admin_panel_back_markup())
                return

            # v3.21: ابتدا هدف جذب پرسیده می‌شود — کانال هنوز ذخیره نشده است
            set_user_state(chat_id, ('admin_new_channel_target', test_id, name, link))
            bot.send_message(
                chat_id,
                f"✅ کانال «{name}» تأیید شد (ربات ادمین است).\n\n"
                "🎯 حالا *هدف جذب* را بفرست — چند کاربر باید از این کانال جذب شود؟\n"
                "• یک عدد بفرست (مثلاً ‎100)\n"
                "• ‎0 یعنی بدون محدودیت (حذف خودکار نداشته باشد)\n\n"
                "پس از رسیدن به هدف، کانال به‌صورت خودکار از جوین اجباری حذف می‌شود و به سوپرادمین خبر داده می‌شود.",
                reply_markup=cancel_markup())
            return

        elif state[0] == 'admin_new_channel_target':
            # v3.21: دریافت عدد هدف جذب و ثبت نهایی کانال
            raw = fa_to_en_digits(text.strip())
            try:
                target = int(raw)
            except ValueError:
                bot.send_message(chat_id,
                    "⚠️ لطفاً فقط یک عدد بفرست (مثلاً ‎100) یا ‎0 برای بدون محدودیت.\n"
                    "دوباره هدف جذب را بفرست:", reply_markup=cancel_markup())
                return
            if target < 0:
                bot.send_message(chat_id,
                    "⚠️ عدد نمی‌تواند منفی باشد. دوباره بفرست (‎0 = بدون محدودیت):",
                    reply_markup=cancel_markup())
                return
            ch_id, ch_name, ch_link = state[1], state[2], state[3]
            clear_user_state(chat_id)
            db.add_forced_channel(ch_id, ch_name, ch_link, target=target)
            if ch_id not in CHANNELS:
                CHANNELS.append(ch_id)
            channel_info[ch_id] = {"name": ch_name, "link": ch_link}
            broken_channels.discard(ch_id)
            if target > 0:
                done_msg = (f"✅ کانال «{ch_name}» با شناسهٔ {ch_id} اضافه شد.\n"
                            f"🎯 هدف جذب: {to_persian_digits(target)} کاربر — پس از رسیدن به هدف، "
                            "کانال خودکار از جوین اجباری حذف و به سوپرادمین خبر داده می‌شود.")
            else:
                done_msg = (f"✅ کانال «{ch_name}» با شناسهٔ {ch_id} اضافه شد.\n"
                            "♾ هدف جذب: بدون محدودیت")
            bot.send_message(chat_id, done_msg, reply_markup=admin_panel_back_markup())
            return

    target_id = pop_admin_reply(chat_id)
    if target_id is not None:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📞 پاسخ", callback_data=f"support_reply_{ADMIN_ID}"),
                   types.InlineKeyboardButton("🚪 خروج از پشتیبانی", callback_data="support_exit"))
        # رفع باگ: اگر کاربر ربات را بلاک کرده، ارسال خطا می‌دهد
        try:
            # v3.16: escape متن ادمین — جلوگیری از شکستن Markdown با _ و * و ارسال ناموفق
            bot.send_message(target_id, f"📩 *پاسخ مدیر:*\n{escape_md(text)}", reply_markup=markup)
            bot.reply_to(message, "📨 پاسخ ارسال شد.", reply_markup=admin_panel_back_markup())
        except ApiTelegramException as e:
            if e.error_code == 403:
                try:
                    db.mark_user_blocked_bot(target_id)
                except Exception:
                    pass
                bot.reply_to(message, "⚠️ این کاربر ربات را بلاک کرده است. پیام ارسال نشد.", reply_markup=admin_panel_back_markup())
            else:
                logger.error(f"Admin reply to {target_id} error: {e}")
                bot.reply_to(message, "❌ خطا در ارسال پیام.", reply_markup=admin_panel_back_markup())
        except Exception as e:
            logger.error(f"Admin reply to {target_id} error: {e}")
            bot.reply_to(message, "❌ خطا در ارسال پیام.", reply_markup=admin_panel_back_markup())
        return

    if is_support_session(chat_id):
        u = db.get_user_basic(chat_id)
        name = u['first_name'] if u and u['first_name'] else "بی‌نام"
        username = u['username'] if u and u['username'] else None
        total_clicks = db.get_clicks_count(chat_id); distinct_snoops = db.get_distinct_snoop_count(chat_id)
        is_active_vip = db.is_vip(chat_id)
        vip_status = "فعال" if is_active_vip else "غیرفعال"
        # رفع باگ: +1 حذف شد — get_vip_days_left روزهای باقی‌مانده واقعی را برمی‌گرداند
        days_left = db.get_vip_days_left(chat_id)
        vip_str = f"👑 {to_persian_digits(days_left)} روز" if vip_status == "فعال" else vip_status
        admin_msg = (f"📩 *پیام پشتیبانی*\n"
                     f"👤 {escape_md(name)}\n🆔 {chat_id}\n📎 @{escape_md(username) if username else 'ندارد'}\n"
                     f"👑 فضول: {distinct_snoops}\n🖱️ کلیک: {total_clicks}\n🏅 VIP: {vip_str}\n\n"
                     f"💬 متن: {escape_md(text)}")
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("📞 پاسخ", callback_data=f"support_reply_{chat_id}"))
        bot.send_message(ADMIN_ID, admin_msg, reply_markup=markup)
        markup_user = types.InlineKeyboardMarkup(row_width=2)
        markup_user.add(types.InlineKeyboardButton("🚪 خروج از پشتیبانی", callback_data="support_exit"),
                        types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
        set_support_partner(chat_id, ADMIN_ID)    
        set_support_partner(ADMIN_ID, chat_id)    
        # رفع باگ: wrap در try/except
        try:
            bot.reply_to(message, "📞 پیامت به مدیر رسید.", reply_markup=markup_user)
        except ApiTelegramException as e:
            if e.error_code == 403:
                try: db.mark_user_blocked_bot(chat_id)
                except Exception: pass
            else:
                logger.error(f"Support reply notify error: {e}")
        except Exception as e:
            logger.error(f"Support reply notify error: {e}")
        return

    # ====== fallback: اگه کاربر در هیچ حالتی نبود و پیامش هم به هیچ هندلری نخورد، منوی خانه رو بفرست ======
    # این بخش فقط برای پیام‌های متنی که هیچ state ای ندارن اجرا می‌شه
    home_text = build_dynamic_home_text(chat_id)
    # رفع باگ: wrap در try/except — اگه کاربر ربات رو بلاک کرده، کل polling thread کرش نکنه
    try:
        bot.reply_to(message, home_text, reply_markup=main_menu(chat_id))
    except ApiTelegramException as e:
        if e.error_code == 403:
            try: db.mark_user_blocked_bot(chat_id)
            except Exception: pass
        else:
            logger.error(f"text_handler fallback send error: {e}")
    except Exception as e:
        logger.error(f"text_handler fallback send error: {e}")

# ====== دریافت عکس خوش‌آمد ======
@bot.message_handler(content_types=['photo'])
def photo_handler(message):
    chat_id = message.chat.id
    # v3.22: دروازهٔ حالت نگهداری — فقط سوپرادمین عبور می‌کند
    if maintenance_gate(message.from_user.id):
        try:
            bot.reply_to(message, texts.MAINTENANCE_NOTICE)
        except Exception:
            pass
        return
    # رفع باگ: ثبت پیام برای آمار 24 ساعته
    record_message(message.from_user.id)

    # اگه در حالت پخش همگانی هستیم و فرستنده ادمین است، این هندلر نباید کاری کنه
    # (broadcast_handler باید این پیام رو بگیره — ولی اگه اینجا رسیدیم یعنی اون نگرفته)
    with broadcast_lock:
        if broadcast_mode and chat_id == broadcast_admin_chat and not broadcast_awaiting_buttons:
            logger.warning("photo_handler: broadcast_mode is active but broadcast_handler didn't catch this photo — delegating manually")
            try:
                broadcast_handler(message)
            except Exception as e:
                logger.error(f"photo_handler → broadcast_handler delegation error: {e}")
            return

    if db.is_blocked(chat_id):
        return
    db.sync_user_profile(chat_id, message.from_user.first_name, message.from_user.username)
    state = get_user_state(chat_id)
    if state and state[0] == 'welcome_photo':
        clear_user_state(chat_id)
        if not db.is_vip(chat_id):
            # رفع باگ: wrap در try/except
            try:
                bot.reply_to(message, VIP_EXPIRED_MSG, reply_markup=vip_menu_button())
            except Exception:
                pass
            return
        file_id = message.photo[-1].file_id
        db.set_welcome_photo(chat_id, file_id)
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("📝 تنظیم متن خوش‌آمدگویی", callback_data="set_welcome"))
        markup.add(types.InlineKeyboardButton("👑 بازگشت به کارت طلایی", callback_data="vip_info"))
        markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
        # رفع باگ: wrap در try/except
        try:
            bot.reply_to(message,
                "🖼️ عکس خوش‌آمدگویی ثبت شد.\n"
                "📝 حالا می‌تونی یه متن هم بهش اضافه کنی تا پیامت کامل‌تر بشه!\n"
                "دکمهٔ زیر رو بزن یا بعداً از منوی VIP اقدام کن.",
                reply_markup=markup)
        except Exception as e:
            logger.error(f"photo_handler welcome_photo reply error: {e}")
        return

    # اگر در حالت پشتیبانی هسته، عکس رو هم به ادمین فوروارد کن
    # v3.16: پاسخ مدیایی سوپر ادمین به کاربر (حالت admin_reply) — قبل از چک پشتیبانی
    if chat_id == ADMIN_ID:
        _adm_target = pop_admin_reply(chat_id)
        if _adm_target is not None:
            _admin_media_reply(message, _adm_target)
            return

    if is_support_session(chat_id):
        _forward_support_message_to_admin(message)
        # v4.0 (fozol-pro): ثبت در صندوق پشتیبانی مینی‌اپ
        try:
            from bot_integration import save_support_media
            save_support_media(message)
        except Exception:
            pass
        return

    # fallback: اگه کاربر در هیچ حالتی نبود و عکس فرستاد، منوی خانه رو بفرست
    home_text = build_dynamic_home_text(chat_id)
    # رفع باگ: wrap در try/except — جلوگیری از کرش polling
    try:
        bot.reply_to(message, home_text, reply_markup=main_menu(chat_id))
    except ApiTelegramException as e:
        if e.error_code == 403:
            try: db.mark_user_blocked_bot(chat_id)
            except Exception: pass
        else:
            logger.error(f"photo_handler fallback send error: {e}")
    except Exception as e:
        logger.error(f"photo_handler fallback send error: {e}")

# ====== هندلر همه انواع فایل برای پشتیبانی ======
# این هندلر فقط زمانی فعال می‌شود که کاربر در حالت پشتیبانی باشد
@bot.message_handler(content_types=['video', 'document', 'audio', 'voice', 'video_note', 'animation', 'sticker', 'contact', 'location'])
def file_handler_support(message):
    """هندلر همه انواع فایل — فقط در حالت پشتیبانی فعال است."""
    chat_id = message.chat.id
    # v3.22: دروازهٔ حالت نگهداری — فقط سوپرادمین عبور می‌کند
    if maintenance_gate(message.from_user.id):
        try:
            bot.reply_to(message, texts.MAINTENANCE_NOTICE)
        except Exception:
            pass
        return
    # رفع باگ: ثبت پیام برای آمار 24 ساعته
    record_message(message.from_user.id)

    # اگه در حالت پخش همگانی هستیم و فرستنده ادمین است، این هندلر نباید کاری کنه
    with broadcast_lock:
        if broadcast_mode and chat_id == broadcast_admin_chat and not broadcast_awaiting_buttons:
            logger.warning(f"file_handler_support: broadcast_mode is active but broadcast_handler didn't catch this {message.content_type} — delegating manually")
            try:
                broadcast_handler(message)
            except Exception as e:
                logger.error(f"file_handler_support → broadcast_handler delegation error: {e}")
            return

    if db.is_blocked(chat_id):
        return
    # v3.5: آنبلاک خودکار — هر تعاملی (حتی استیکر/ویدئو) کاربر را از لیست بلاک‌ربات خارج می‌کند
    db.sync_user_profile(chat_id, message.from_user.first_name, message.from_user.username)
    # v3.16: پاسخ مدیایی سوپر ادمین به کاربر (حالت admin_reply) — قبل از چک پشتیبانی
    if chat_id == ADMIN_ID:
        _adm_target = pop_admin_reply(chat_id)
        if _adm_target is not None:
            _admin_media_reply(message, _adm_target)
            return
    # فقط در حالت پشتیبانی فعال باشد
    if not is_support_session(chat_id):
        # اگه کاربر در حالت پشتیبانی نیست و فایل فرستاد، منوی خانه رو بفرست
        home_text = build_dynamic_home_text(chat_id)
        # رفع باگ: wrap در try/except
        try:
            bot.reply_to(message, home_text, reply_markup=main_menu(chat_id))
        except ApiTelegramException as e:
            if e.error_code == 403:
                try: db.mark_user_blocked_bot(chat_id)
                except Exception: pass
            else:
                logger.error(f"file_handler fallback send error: {e}")
        except Exception as e:
            logger.error(f"file_handler fallback send error: {e}")
        return
    _forward_support_message_to_admin(message)

def _admin_media_reply(message, target_id):
    """v3.16: ارسال پاسخ مدیایی سوپر ادمین به کاربر (عکس/ویدیو/انیمیشن/فایل/ویدئونوت/ویس/آهنگ/استیکر/لوکیشن/مخاطب).
    مدیا با file_id دوباره ارسال می‌شود (کاملاً سازگار با بله، بدون هدر «فورواردشده»)
    + برچسب «پاسخ مدیر» و دکمه‌های پاسخ/خروج برای کاربر."""
    chat_id = message.chat.id
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📞 پاسخ", callback_data=f"support_reply_{ADMIN_ID}"),
               types.InlineKeyboardButton("🚪 خروج از پشتیبانی", callback_data="support_exit"))
    caption = message.caption or ""
    footer = "📩 *پاسخ مدیر*"
    new_caption = None
    footer_separate = True
    if caption:
        cand = escape_md(caption) + "\n\n" + footer
        if len(cand) <= 1024:
            new_caption = cand
            footer_separate = False
        else:
            esc_only = escape_md(caption)
            if len(esc_only) <= 1024:
                new_caption = esc_only
    try:
        if message.photo:
            bot.send_photo(target_id, message.photo[-1].file_id, caption=new_caption, reply_markup=markup)
        elif message.video:
            bot.send_video(target_id, message.video.file_id, caption=new_caption, reply_markup=markup)
        elif message.animation:
            bot.send_animation(target_id, message.animation.file_id, caption=new_caption, reply_markup=markup)
        elif message.audio:
            bot.send_audio(target_id, message.audio.file_id, caption=new_caption, reply_markup=markup)
        elif message.voice:
            bot.send_voice(target_id, message.voice.file_id, caption=new_caption, reply_markup=markup)
        elif message.document:
            bot.send_document(target_id, message.document.file_id, caption=new_caption, reply_markup=markup)
        elif message.video_note:
            bot.send_video_note(target_id, message.video_note.file_id, reply_markup=markup)
        elif message.sticker:
            bot.send_sticker(target_id, message.sticker.file_id, reply_markup=markup)
        elif message.location:
            bot.send_location(target_id, message.location.latitude, message.location.longitude, reply_markup=markup)
        elif message.contact:
            bot.send_contact(target_id, message.contact.phone_number, message.contact.first_name,
                             message.contact.last_name, reply_markup=markup)
        else:
            # نوع پشتیبانی‌نشده — فوروارد مستقیم به‌عنوان آخرین راه
            bot.forward_message(target_id, from_chat_id=chat_id, message_id=message.message_id)
        if footer_separate:
            bot.send_message(target_id, footer, reply_markup=markup)
        try:
            bot.reply_to(message, "📨 پاسخ ارسال شد.", reply_markup=admin_panel_back_markup())
        except Exception:
            pass
    except ApiTelegramException as e:
        if e.error_code == 403:
            try: db.mark_user_blocked_bot(target_id)
            except Exception: pass
            try: bot.reply_to(message, "⚠️ این کاربر ربات را بلاک کرده است. ارسال انجام نشد.", reply_markup=admin_panel_back_markup())
            except Exception: pass
        else:
            logger.error(f"Admin media reply to {target_id} error: {e}")
            try: bot.reply_to(message, "❌ خطا در ارسال مدیا.", reply_markup=admin_panel_back_markup())
            except Exception: pass
    except Exception as e:
        logger.error(f"Admin media reply to {target_id} error: {e}")
        try: bot.reply_to(message, "❌ خطا در ارسال مدیا.", reply_markup=admin_panel_back_markup())
        except Exception: pass

def _forward_support_message_to_admin(message):
    """فوروارد یک پیام (هر نوعی) از کاربر به ادمین در حالت پشتیبانی.
    پیام به‌صورت یک‌تکه (forward) ارسال می‌شود تا چندتکه نشود."""
    chat_id = message.chat.id
    try:
        # فوروارد مستقیم پیام به ادمین — همیشه یک‌تکه
        bot.forward_message(ADMIN_ID, from_chat_id=chat_id, message_id=message.message_id)

        # ارسال متادیتای کاربر به‌عنوان پیام جداگانه (کوتاه)
        u = db.get_user_basic(chat_id)
        name = u['first_name'] if u and u['first_name'] else "بی‌نام"
        username = u['username'] if u and u['username'] else None
        total_clicks = db.get_clicks_count(chat_id)
        distinct_snoops = db.get_distinct_snoop_count(chat_id)
        is_active_vip = db.is_vip(chat_id)
        vip_status = "فعال" if is_active_vip else "غیرفعال"
        # رفع باگ: +1 حذف شد — get_vip_days_left روزهای باقی‌مانده واقعی را برمی‌گرداند
        days_left = db.get_vip_days_left(chat_id)
        vip_str = f"👑 {to_persian_digits(days_left)} روز" if vip_status == "فعال" else vip_status

        # v4.4: پشتیبانی اولویت‌دار VIP — برچسب ⚡️ روی پیام‌های کاربر VIP
        prio_line = "\n⚡️ *اولویت VIP*" if is_active_vip else ""
        admin_meta = (f"📩 *پیام پشتیبانی*{prio_line}\n"
                      f"👤 {escape_md(name)}\n🆔 {to_persian_digits(chat_id)}\n📎 @{escape_md(username) if username else 'ندارد'}\n"
                      f"👑 فضول: {to_persian_int(distinct_snoops)}\n🖱️ کلیک: {to_persian_int(total_clicks)}\n🏅 VIP: {vip_str}")
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("📞 پاسخ", callback_data=f"support_reply_{chat_id}"))
        bot.send_message(ADMIN_ID, admin_meta, reply_markup=markup)

        # تأیید به کاربر
        markup_user = types.InlineKeyboardMarkup(row_width=2)
        markup_user.add(types.InlineKeyboardButton("🚪 خروج از پشتیبانی", callback_data="support_exit"),
                        types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
        set_support_partner(chat_id, ADMIN_ID)
        set_support_partner(ADMIN_ID, chat_id)
        bot.reply_to(message, "📞 پیامت به مدیر رسید.", reply_markup=markup_user)
    except Exception as e:
        logger.error(f"Support forward error: {e}")
        # رفع باگ: wrap در try/except
        try:
            bot.reply_to(message, "❌ خطا در ارسال پیام. لطفاً دوباره تلاش کنید.")
        except Exception:
            pass

# ====== لیست فضول‌ها ======
def show_snoop_list(chat_id, page=1, message_id=None):
    snoops = db.get_snoops(chat_id)
    if not snoops:
        text = "📁 هنوز هیچ فضولی در دامت نیفتاده..."
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🏠 بازگشت به منو", callback_data="main_menu"))
        if message_id:
            try:
                safe_edit_text(text, chat_id, message_id, reply_markup=markup)
                return
            except Exception:
                pass
        bot.send_message(chat_id, text, reply_markup=markup)
        return

    per_page = 20; total_pages = max(1, (len(snoops)+per_page-1)//per_page)
    page = max(1, min(page, total_pages))
    start = (page-1)*per_page; end = start+per_page
    page_items = snoops[start:end]
    buttons = []
    for s in page_items:
        disp = s.get('nickname') or s['name']
        emoji = get_user_rank_emoji(s['clicker_id'])
        btn_text = f"{emoji} {disp}" if emoji else disp
        buttons.append(types.InlineKeyboardButton(btn_text, callback_data=f"snoopdetail_{s['clicker_id']}"))
    markup = types.InlineKeyboardMarkup(row_width=2)
    for i in range(0, len(buttons), 2):
        if i+1 < len(buttons): markup.add(buttons[i], buttons[i+1])
        else: markup.add(buttons[i])
    nav = []
    if page > 1: nav.append(types.InlineKeyboardButton("⬅️ قبلی", callback_data=f"snooplist_page_{page-1}"))
    if page < total_pages: nav.append(types.InlineKeyboardButton("بعدی ➡️", callback_data=f"snooplist_page_{page+1}"))
    if nav: markup.row(*nav)
    markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))

    text = f"📋 *لیست فضول‌ها (صفحه {page} از {total_pages})*"
    if message_id:
        try:
            safe_edit_text(text, chat_id, message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)


# ====== v3.17: مقدار فعلی متریک هر گروه ماموریت — برای نوار پیشرفت زنده ======
def _task_progress_value(user_id, task):
    """مقدار فعلی پیشرفت کاربر برای ماموریت‌های عددی (group/threshold) یا None."""
    grp = task.get("group")
    if not grp or "threshold" not in task:
        return None
    try:
        if grp == "click_count":
            return db.get_clicks_count(user_id)
        if grp == "snoop_count":
            return db.get_distinct_snoop_count(user_id)
        if grp == "nickname_count":
            with db._lock:
                return db.conn.execute("SELECT COUNT(*) FROM nicknames WHERE owner_id=?", (user_id,)).fetchone()[0]
        if grp == "anon_sent":
            with db._lock:
                return db.conn.execute("SELECT COUNT(*) FROM anon_logs WHERE sender_id=?", (user_id,)).fetchone()[0]
        if grp == "anon_received":
            with db._lock:
                return db.conn.execute("SELECT COUNT(*) FROM anon_logs WHERE receiver_id=?", (user_id,)).fetchone()[0]
        if grp == "mute_count":
            with db._lock:
                return db.conn.execute("SELECT COUNT(*) FROM muted_snoops WHERE owner_id=?", (user_id,)).fetchone()[0]
        if grp == "block_count":
            with db._lock:
                return db.conn.execute("SELECT COUNT(*) FROM blocked_anon WHERE blocker_id=?", (user_id,)).fetchone()[0]
        if grp == "gift_used":
            with db._lock:
                return db.conn.execute("SELECT COUNT(*) FROM gift_usage WHERE user_id=?", (user_id,)).fetchone()[0]
        if grp == "vip_purchase":
            with db._lock:
                return db.conn.execute("SELECT COUNT(*) FROM transactions WHERE user_id=? AND type='vip'", (user_id,)).fetchone()[0]
        if grp == "vip_gift":
            return db.get_user_gift_count(user_id)
        if grp == "days_active":
            with db._lock:
                row = db.conn.execute("SELECT COALESCE(julianday('now') - julianday(created_at), 0) FROM users WHERE user_id=?", (user_id,)).fetchone()
                return int(row[0] or 0) if row else 0
        # ---- v4.8: گروه‌های ماموریت‌های رشد (هم‌گام با services/missions.py) ----
        if grp == "invite_count":
            with db._lock:
                return db.conn.execute("SELECT COUNT(DISTINCT clicker_id) FROM clicks WHERE owner_id=? AND is_new_user=1", (user_id,)).fetchone()[0]
        if grp == "streak":
            with db._lock:
                row = db.conn.execute("SELECT COALESCE(streak_count,0) FROM users WHERE user_id=?", (user_id,)).fetchone()
                return int(row[0] or 0) if row else 0
        if grp == "daily_claims":
            with db._lock:
                row = db.conn.execute("SELECT COALESCE(total_claims,0) FROM daily_bonus WHERE user_id=?", (user_id,)).fetchone()
                return int(row[0] or 0) if row else 0
        if grp == "wheel_spins":
            with db._lock:
                return db.conn.execute("SELECT COUNT(*) FROM wheel_spins WHERE user_id=?", (user_id,)).fetchone()[0]
        if grp == "trap_count":
            with db._lock:
                return db.conn.execute("SELECT COUNT(*) FROM traps WHERE owner_id=?", (user_id,)).fetchone()[0]
        if grp == "xp_total":
            with db._lock:
                row = db.conn.execute("SELECT COALESCE(xp,0) FROM users WHERE user_id=?", (user_id,)).fetchone()
                return int(row[0] or 0) if row else 0
    except Exception:
        return None
    return None


# ====== ماموریت‌ها — v3.17: ۳ ماموریت ویژهٔ روز ======
def show_tasks_page(chat_id, user_id, page, call):
    """نمایش ماموریت‌ها — ری‌دیزاین v3.17:
    - به‌جای لیست بلند ۲۰۰تایی، فقط ۳ ماموریت ویژه نمایش داده می‌شود.
    - صفحهٔ ۱: انتخاب قطعی بر اساس روز (seed = کاربر + تاریخ ایران) — هر روز ست جدید.
    - دکمهٔ «ماموریت‌های دیگر» ست متفاوتی نشان می‌دهد.
    - ماموریت‌های تکمیل‌شده خودکار و بی‌صدا XP می‌گیرند (اسکنر زمان واقعی)."""
    all_tasks = tasks_module.TASKS
    total = len(all_tasks)

    # ابتدا _check_and_award_tasks_xp رو صدا بزن تا تسک‌های تازه تکمیل‌شده رو پردازش کنه
    # و نوتیفیکیشن‌های در انتظار رو هم در نظر بگیر
    try:
        # v3.6: بی‌صدا — اعلان‌ها توسط اسکنر زمان واقعی ارسال می‌شوند (نه هنگام بازکردن صفحه)
        _check_and_award_tasks_xp(user_id, notify=False)
    except Exception as e:
        logger.error(f"Tasks check on page view: {e}")

    # محاسبه وضعیت هر تسک (done یا نه)
    task_status = {}  # task_id -> bool (done?)
    done_count = 0
    for t in all_tasks:
        is_done = db.has_bonus(user_id, f"task_{t['id']}")
        if not is_done:
            try:
                with db._lock:
                    is_done = bool(t["check"](db, user_id))
                # اگر تازه انجام شده، XP رو نمی‌دیم چون _check_and_award_tasks_xp قبلاً داده
            except Exception as e:
                logger.error(f"Task check error {t['id']}: {e}")
                is_done = False
        task_status[t["id"]] = is_done
        if is_done:
            done_count += 1

    # فیلتر کردن تسک‌های نمایش‌داده‌شده:
    # 1. تسک‌های انجام‌شده حذف می‌شوند
    # 2. از هر گروه milestone فقط کمترین threshold که هنوز انجام نشده می‌ماند
    remaining_tasks = []
    groups_done_threshold = {}  # group -> max threshold done
    groups_added = set()  # گروه‌هایی که قبلاً تسک فعالشون اضافه شده

    # اول pass اول: محاسبه max threshold done برای هر گروه
    for t in all_tasks:
        if "group" in t and t["group"]:
            grp = t["group"]
            if task_status.get(t["id"], False):
                thr = t.get("threshold", 0)
                if grp not in groups_done_threshold or thr > groups_done_threshold[grp]:
                    groups_done_threshold[grp] = thr

    # pass دوم: انتخاب تسک‌های نمایش
    for t in all_tasks:
        if task_status.get(t["id"], False):
            # تسک انجام شده — رد کن
            continue
        if "group" in t and t["group"]:
            grp = t["group"]
            thr = t.get("threshold", 0)
            # اگر threshold این تسک کمتر یا مساوی max done باشه، یعنی قبلاً انجام شده
            # (البته اگه done_count برای این تسک true نباشه، ولی threshold کمتر باشه، یعنی باید done می‌بود)
            # این حالت نباید رخ بده چون check() باید true برمی‌گرداند
            # اما برای اطمینان، فقط اولین تسک با threshold > max_done رو می‌گیریم
            max_done = groups_done_threshold.get(grp, 0)
            if thr <= max_done:
                # این تسک باید done می‌بود ولی نشده — مشکلی هست، ردش کن
                continue
            if grp in groups_added:
                # قبلاً تسک فعال این گروه اضافه شده
                continue
            groups_added.add(grp)
            remaining_tasks.append(t)
        else:
            # تسک بدون group — همیشه نمایش (اگه done نباشه)
            remaining_tasks.append(t)

    # حالا remaining_tasks لیست تسک‌های قابل نمایشه — v3.17: از بین آن‌ها فقط ۳ عدد انتخاب می‌شود
    total_remaining = len(remaining_tasks)
    today_iso = datetime.datetime.now(TEHRAN_TZ).date().isoformat()
    rng = random.Random(f"{user_id}:{today_iso}:{page}")
    if total_remaining <= 3:
        page_tasks = list(remaining_tasks)
    else:
        page_tasks = rng.sample(remaining_tasks, 3)
        # مرتب‌سازی از آسان به سخت برای حس پیشرفت بهتر
        cat_order = {"easy": 0, "medium": 1, "hard": 2}
        page_tasks.sort(key=lambda t: (cat_order.get(t["category"], 9), t.get("threshold", 0), t["xp"]))

    # progress bar کلی
    pct = int(done_count * 100 / total) if total else 0
    bar_len = 20
    filled = int(pct * bar_len / 100)
    bar = '█' * filled + '░' * (bar_len - filled)

    # ====== متن جذاب — ۳ ماموریت ویژهٔ امروز ======
    lines = [
        f"🎯 *ماموریت‌های ویژهٔ امروز*",
        f"━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📈 پیشرفت کل: {to_persian_digits(done_count)} از {to_persian_digits(total)} ({to_persian_digits(pct)}٪)",
        f"{bar}",
        f"",
    ]
    if total_remaining == 0:
        lines.append("🏆 *باورنکردنیه! همهٔ ۲۰۰ ماموریت رو کامل کردی!*")
        lines.append("👑 تو دیگه افسانهٔ فضول‌یابی — اسمت برای همیشه می‌درخشه!")
    else:
        lines.append(f"🔥 امروز {to_persian_digits(len(page_tasks))} ماموریت ویژه داری!")
        lines.append("🌙 هر شب ساعت ۰۰:۰۰ ست جدید باز می‌شه — از دستش نده!")
        lines.append("")
        idx_emoji = ["1️⃣", "2️⃣", "3️⃣"]
        for i, t in enumerate(page_tasks):
            cinfo = tasks_module.CATEGORY_INFO.get(t["category"], {"emoji": "🎯"})
            idx = idx_emoji[i] if i < 3 else "🔸"
            lines.append(f"{idx} {cinfo.get('emoji', '🎯')} *{t['name']}*  +{to_persian_digits(t['xp'])} XP")
            # نوار پیشرفت زنده برای ماموریت‌های عددی
            prog = _task_progress_value(user_id, t)
            if prog is not None:
                thr = max(1, t.get("threshold", 1))
                pf = max(0, min(int(prog * 10 / thr), 10))
                pbar = "▰" * pf + "▱" * (10 - pf)
                lines.append(f"　　{pbar} {to_persian_digits(min(prog, thr))} از {to_persian_digits(thr)}")
        lines.append("")
        lines.append("⚡ پاداش هر ماموریت فقط یک‌بار می‌ده؛ بقیه هم خودکار شمرده می‌شن!")

    # کیبورد — ۳ ماموریت ویژه (تپ = جزئیات و پاداش)
    markup = types.InlineKeyboardMarkup(row_width=1)
    for t in page_tasks:
        btn = types.InlineKeyboardButton(
            f"🎯 {t['name']} (+{to_persian_digits(t['xp'])} XP)",
            callback_data=f"task_detail_{t['id']}"
        )
        markup.add(btn)

    # دکمه‌های ناوبری — ست متفاوت + خانه
    if total_remaining > 3:
        markup.add(types.InlineKeyboardButton("🔄 ماموریت‌های دیگر", callback_data=f"tasks_page_{page + 1 if page > 1 else 2}"))
    markup.add(types.InlineKeyboardButton("🔙 اطلاعات من", callback_data="my_info"))
    markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))

    # ارسال/ویرایش پیام
    if call.message.content_type == 'photo':
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except: pass
        bot.send_message(chat_id, "\n".join(lines), reply_markup=markup)
    else:
        try:
            safe_edit_text("\n".join(lines), chat_id, call.message.message_id, reply_markup=markup)
        except:
            bot.send_message(chat_id, "\n".join(lines), reply_markup=markup)

    # v3.6: اعلان تکمیل ماموریت‌ها به‌صورت زمان واقعی توسط task_scanner_loop ارسال می‌شود
    # (رفع باگ: بازکردن صفحهٔ ماموریت‌ها باعث رگبار پیام‌های تکمیل می‌شد)

    # نکته: answer_callback_query قبلاً در callback_handler زده شده (loading toast)
    # پس اینجا دیگه نمی‌زنیم


def show_task_detail_popup(call, user_id, task_id):
    """نمایش جزئیات یک تسک به‌صورت popup (answer_callback_query) — برای جلوگیری از شلوغ شدن چت."""
    task = tasks_module.get_task_by_id(task_id)
    if not task:
        bot.answer_callback_query(call.id, "❌ تسک یافت نشد.", show_alert=True)
        return

    is_done = db.has_bonus(user_id, f"task_{task['id']}")
    if not is_done:
        # بررسی مجدد آیا الان انجام شده
        try:
            with db._lock:
                is_done = bool(task["check"](db, user_id))
            if is_done:
                # تسک الان تکمیل شد — XP رو بده
                level_before = db.get_user_level_cached(user_id)
                awarded, xp_new, level_new, _ = db.award_bonus_xp(user_id, f"task_{task['id']}", task["xp"])
                if awarded:
                    # اگر سطح بالا رفت، پیام ارتقا بفرست
                    if level_new > level_before:
                        try:
                            title, emoji = get_rank_tier(level_new)
                            xp_next = db.xp_for_next_level(level_new)
                            msg = texts.LEVEL_UP_MESSAGE.format(
                                level=to_persian_digits(level_new),
                                title=title,
                                emoji=emoji,
                                xp_current=to_persian_int(xp_new),
                                xp_next=to_persian_int(xp_next) if xp_next else "نهایتی"
                            )
                            try:
                                if LEVEL_UP_PHOTO_ID:
                                    try:
                                        bot.send_photo(user_id, LEVEL_UP_PHOTO_ID, caption=msg)
                                    except:
                                        bot.send_message(user_id, msg)
                                else:
                                    bot.send_message(user_id, msg)
                            except Exception as e:
                                logger.error(f"Level-up notify error: {e}")
                        except Exception as e:
                            logger.error(f"Level-up msg build error: {e}")

                    # toast به کاربر
                    bot.answer_callback_query(call.id,
                        f"🎉 ماموریت تکمیل شد!\n{task['name']}\n+{to_persian_digits(task['xp'])} XP",
                        show_alert=True)
                    return
        except Exception as e:
            logger.error(f"Task detail check error: {e}")

    status = "✅ انجام شده" if is_done else "⬜ در انتظار انجام"
    popup_text = texts.TASKS_DETAIL_POPUP.format(
        name=task["name"],
        xp=to_persian_digits(task["xp"]),
        desc=task["desc"],
        status=status
    )

    # اضافه‌کردن پیشنهاد ماموریت بعدی (در همون group)
    if is_done and task.get("group"):
        group = task["group"]
        # پیدا کردن ماموریت بعدی در همون group (با threshold بالاتر)
        group_tasks = sorted(
            [t for t in tasks_module.TASKS if t.get("group") == group],
            key=lambda x: x.get("threshold", 0)
        )
        # پیدا کردن اولین ماموریت انجام‌نشده بعد از این
        current_threshold = task.get("threshold", 0)
        next_task = None
        for t in group_tasks:
            if t.get("threshold", 0) > current_threshold:
                is_next_done = db.has_bonus(user_id, f"task_{t['id']}")
                if not is_next_done:
                    next_task = t
                    break
        if next_task:
            popup_text += texts.NEXT_TASK_HINT.format(
                name=next_task["name"],
                xp=to_persian_digits(next_task["xp"])
            )

    bot.answer_callback_query(call.id, popup_text, show_alert=True)


# ====== v3.12: کش پلکانیِ تنبلِ لیدربورد (مشخصات ادمین) ======
#   • تنبل: تا وقتی کسی تابلو را درخواست نکند، هیچ تصویری تولید یا آپلود نمی‌شود.
#   • درخواست سوپر ادمین (ADMIN_ID): تصویرِ کش‌شده نباید قدیمی‌تر از ۱۰ دقیقه باشد.
#   • درخواست کاربر عادی: تصویرِ کش‌شده نباید قدیمی‌تر از ۲ ساعت باشد.
#   • هر پنجرهٔ تابلو (همه‌زمان/هفته) جایگاه کش مستقل خودش را دارد.
# اگر تصویرِ کش از سقفِ کهنگیِ همان درخواست‌دهنده کهنه‌تر باشد یا file_id مردود
# شود → رندر تازه از همان ردیف‌هایی که همین لحظه از دیتابیس خوانده شده‌اند.
LB_RENDER_VERSION = "3.14.0"  # v3.14: حذف نمای هفته + حذف شیشه‌ای از مسیر عادی (فالبک تصویری)
LB_TTL_ADMIN = 600    # سقف کهنگی برای سوپر ادمین — ۱۰ دقیقه
LB_TTL_USER = 7200    # سقف کهنگی برای کاربر عادی — ۲ ساعت

_lb_render_lock = threading.Lock()


def lb_cache_get(board="all"):
    """(file_id, unix_ts) جایگاه کش این پنجره — یا ('', 0)"""
    try:
        fid = db.get_setting("lb_cache_fileid_" + board, "")
        ts = db.get_setting_int("lb_cache_ts_" + board, 0)
        if fid and ts:
            return fid, int(ts)
    except Exception:
        pass
    return "", 0


def lb_cache_set(board, fid, ts):
    try:
        db.set_setting("lb_cache_fileid_" + board, fid)
        db.set_setting("lb_cache_ts_" + board, str(int(ts)))
    except Exception:
        pass


def lb_ttl_for(user_id):
    """سقف کهنگی مجاز برای این درخواست‌دهنده: سوپر ادمین ۱۰ دقیقه، بقیه ۲ ساعت"""
    try:
        return LB_TTL_ADMIN if int(user_id or 0) == int(ADMIN_ID) else LB_TTL_USER
    except Exception:
        return LB_TTL_USER


def lb_is_fresh(ts, user_id):
    """آیا تصویرِ رندرشده در زمان ts برای این درخواست‌دهنده هنوز تازه است؟"""
    try:
        return (time.time() - int(ts)) < lb_ttl_for(user_id)
    except Exception:
        return False


def lb_send_image(chat_id, users, sub, cap, markup, board="all", user_id=0):
    """v3.12: ارسال تصویر تالار با کش پلکانی تنبل —
      ۱) مسیر سریع: اگر تصویرِ کش این پنجره از سقفِ کهنگیِ این درخواست‌دهنده
         جوان‌تر باشد (ادمین ۱۰ دقیقه، کاربر ۲ ساعت) → همان file_id ارسال
         می‌شود؛ بدون رندر و بدون آپلود (رفتار تنبل).
      ۲) در غیر این صورت (کش خالی/کهنه/file_id مردود) → رندر تازه از همان
         ردیف‌هایی که همین لحظه از دیتابیس خوانده شده‌اند + ذخیرهٔ file_id تازه.
    True یعنی عکس ارسال شد."""
    ttl = lb_ttl_for(user_id)
    fid, ts = lb_cache_get(board)
    if fid and ts and lb_is_fresh(ts, user_id):
        try:
            bot.send_photo(chat_id, fid, caption=cap, reply_markup=markup)
            print("🖼 LB[%s]: cache HIT (age=%ds<ttl=%ds) — no render/upload" % (
                board, int(time.time()) - int(ts), ttl), flush=True)
            return True
        except Exception as fid_err:
            logger.warning("lb cached file_id rejected: %s", fid_err)
    age = (int(time.time()) - int(ts)) if ts else -1
    if not _lb_render_lock.acquire(timeout=30):
        logger.warning("lb render lock timeout — skip to fallback")
        return False
    try:
        png = leaderboard_img.render_leaderboard_image(users, subtitle=sub)
        if not png:
            return False
        tmp = tempfile.NamedTemporaryFile(prefix="lb_", suffix=".png", delete=False)
        try:
            tmp.write(png)
            tmp.close()
            with open(tmp.name, "rb") as f:
                msg = bot.send_photo(chat_id, f, caption=cap, reply_markup=markup)
            try:
                _nfid = ""
                if msg and getattr(msg, "photo", None):
                    _nfid = msg.photo[-1].file_id
                if _nfid:
                    lb_cache_set(board, _nfid, time.time())
            except Exception:
                pass
            print("🖼 LB[%s]: FRESH render (%s; ttl=%ds) — new file_id cached" % (
                board, ("stale age=%ds" % age) if age >= 0 else "cache empty", ttl),
                flush=True)
            return True
        finally:
            try:
                os.remove(tmp.name)
            except Exception:
                pass
    except Exception as send_err:
        logger.warning("leaderboard photo send failed: %s", send_err)
        return False
    finally:
        _lb_render_lock.release()


def _lb_live_probe():
    """v3.11: پروب زندهٔ تابلو در استارت — هر دو پنجره (کل و هفته) با همان
    کوئری‌های show_leaderboard در لاگ چاپ می‌شوند؛ PNG نمای «کل» در
    /tmp/lb_probe.png ذخیره می‌شود تا با تصویر واقعی مقایسه شود."""
    try:
        for _mode in ("all", "week"):
            rows = (db.get_leaderboard_top(10) if _mode == "all"
                    else db.get_leaderboard_top_week(10))
            users = []
            for r in rows:
                try:
                    _v = db.is_vip(r['owner_id'])
                except Exception:
                    _v = False
                users.append((sanitize_name(r['first_name'] or "بی‌نام"), r['cnt'], _v, False))
            print("📊 LB PROBE[%s]: rows=%d" % (_mode, len(users)), flush=True)
            for i, u in enumerate(users):
                print("📊 LB PROBE[%s] row%02d: %s | %s | cnt=%d vip=%s" % (
                    _mode, i + 1, rows[i]['owner_id'], u[0][:44], u[1], u[2]), flush=True)
            if _mode == "all" and users:
                png = leaderboard_img.render_leaderboard_image(users, subtitle="۱۰ شکارچی برتر")
                if png:
                    try:
                        with open("/tmp/lb_probe.png", "wb") as f:
                            f.write(png)
                        print("📊 LB PROBE render=OK(%dKB) -> /tmp/lb_probe.png" % (len(png) // 1024), flush=True)
                        # v3.19: فایل موقت — بعد از لاگ حذف می‌شود (مدیریت حافظه Railway)
                        try:
                            os.remove("/tmp/lb_probe.png")
                        except Exception:
                            pass
                    except Exception:
                        print("📊 LB PROBE render=OK(%dKB)" % (len(png) // 1024), flush=True)
                else:
                    print("📊 LB PROBE render=FAILED", flush=True)
    except Exception as _probe_err:
        print("📊 LB PROBE FAILED: %s" % _probe_err, flush=True)


def show_leaderboard(chat_id, user_id, board="all"):
    """v3.11: board="all" → تابلوی همه‌زمان (پیش‌فرض؛ کاربران واقعی همیشگی) یا
    "week" → نمای هفتگی. هر دو همیشه رندر تازه از دیتابیس زنده."""
    top = db.get_leaderboard_top(5)
    user_distinct = db.get_distinct_snoop_count(user_id)
    user_rank = db.get_user_rank_by_distinct(user_id)
    total_sharers = db.count_all_users()

    lines = [texts.LEADERBOARD_HEADER]

    # ۵ نفر برتر — فرمت جدید:
    # 🥇 🌿 با ۸۲ فضول یکتا:
    #          𓆩♡𓆪 strawberry 𓆩♡𓆪
    for i, row in enumerate(top):
        rank = i + 1
        # ایموجی سطح کاربر
        level_emoji = get_user_rank_emoji(row['owner_id'])
        # مدال رتبه
        medal = rank_emoji_display(rank)
        name = sanitize_name(row['first_name'] or "بی‌نام")
        if row['owner_id'] == user_id:
            name = f"⭐ {name}"
        name_escaped = name
        cnt = row['cnt']

        lines.append(
            f"{medal} {level_emoji} با {to_persian_digits(cnt)} فضول:"
        )
        # v3.6: نشان VIP — تاج دو طرف نام
        try:
            _row_vip = db.is_vip(row['owner_id'])
        except Exception:
            _row_vip = False
        if _row_vip:
            lines.append(f"    𓆩👑𓆪 {name_escaped} 𓆩👑𓆪")
        else:
            lines.append(f"    𓆩♡𓆪 {name_escaped} 𓆩♡𓆪")

    user_hidden = db.is_hide_leaderboard(user_id)
    # v3.14: رتبهٔ None (بدون هیچ شکار یکتا) — پیام دوستانه به‌جای «None»
    if user_rank is None:
        rank_text = "🎯 هنوز در تالار رتبه‌ای نداری — اولین دامت رو بساز و شکار کن!"
    else:
        rank_text = texts.LEADERBOARD_MY_RANK.format(rank=to_persian_digits(user_rank), total=to_persian_digits(total_sharers))
    if user_hidden:
        rank_text += " (مخفی)"
    # فاصله قبل از بخش رتبه
    lines.append("")
    lines.append(rank_text)

    if not user_hidden and any(row['owner_id'] == user_id for row in top):
        for idx, row in enumerate(top):
            if row['owner_id'] == user_id:
                user_idx = idx
                break
        if user_idx == 0:
            lines.append("")
            lines.append(texts.LEADERBOARD_TOP1)
        else:
            gap = top[user_idx-1]['cnt'] - user_distinct
            lines.append("")
            lines.append(texts.LEADERBOARD_GAP_NEXT.format(gap=to_persian_digits(gap)))
    else:
        if top:
            last_cnt = top[-1]['cnt']
            gap = last_cnt - user_distinct
            if gap > 0:
                lines.append("")
                lines.append(texts.LEADERBOARD_GAP_TOP10.format(gap=to_persian_digits(gap)))
            else:
                lines.append("")
                lines.append("📊 تو به تالار راه یافته‌ای اما نامت مخفی است.")
        else:
            lines.append("")
            lines.append("📁 هنوز هیچ کارآگاهی در تالار نیست...")

    # فاصله قبل از motto
    lines.append("")
    lines.append(texts.LEADERBOARD_MOTTO)
    caption = "\n".join(lines)

    markup = types.InlineKeyboardMarkup(row_width=2)
    # v3.12: دکمه‌های کاربردی بعد از تابلوی شیشه‌ای ۱۰ نفر برتر اضافه می‌شوند

    # ── v3.9.2: کپشن کوتاه — همه‌چیز در تصویر است؛ متن فقط این چند خط ──
    cap_parts = [rank_text]
    try:
        _nvip = db.count_active_vips()
        if _nvip:
            if _nvip == 1:
                cap_parts.append("⚜️ یک نفر VIP دارد")
            else:
                cap_parts.append("⚜️ %s نفر VIP دارند" % to_persian_digits(_nvip))
    except Exception:
        pass
    # ── v3.14: نمای «هفته» حذف شد — تابلو همیشه همه‌زمان است ──
    rows_board = None
    board_is_week = False
    try:
        rows_board = db.get_leaderboard_top(10)
        if len(rows_board) < 3:
            rows_board = None
    except Exception:
        rows_board = None

    try:
        if rows_board:
            _ids = [r['owner_id'] for r in rows_board]
            if user_id in _ids:
                _i = _ids.index(user_id)
                if _i == 0:
                    cap_parts.append(texts.LEADERBOARD_TOP1)
                else:
                    _gap = rows_board[_i - 1]['cnt'] - rows_board[_i]['cnt']
                    if _gap > 0:
                        cap_parts.append(texts.LEADERBOARD_GAP_NEXT.format(gap=to_persian_digits(_gap)))
            else:
                # v3.9.4: فاصله با همان سنجهٔ تابلو (هفتگی↔هفتگی، کل↔کل) — نه مخلوط
                _my_cnt = db.get_week_distinct_snoop_count(user_id) if board_is_week else user_distinct
                _gap = rows_board[-1]['cnt'] - _my_cnt
                if _gap > 0:
                    cap_parts.append(texts.LEADERBOARD_GAP_TOP10.format(gap=to_persian_digits(_gap)))
    except Exception:
        pass
    cap_parts.append(texts.LEADERBOARD_MOTTO)
    cap_short = "\n\n".join(cap_parts)

    # v3.11: دکمهٔ سوییچ پنجرهٔ تابلو — v3.14 حذف شد (نمای هفته کنار گذاشته شد)

    # ── v3.14: دکمه‌های شیشه‌ای از مسیر عادی حذف شدند — تابلو فقط تصویر + کپشن؛
    # شیشه‌ای‌ها فقط در فالبکِ پایین (وقتی نمایش تصویری به مشکل بخورد) برمی‌گردند. ──

    # v3.12: دکمه‌های کاربردی — بعد از تابلو
    toggle_text = "👁️ مخفی کردن نام" if not user_hidden else "👁️ نمایش نام"
    markup.add(types.InlineKeyboardButton(toggle_text, callback_data="toggle_leaderboard_hide"))
    # v3.20: تغییر نام نمایشی تابلو
    markup.add(types.InlineKeyboardButton(texts.LB_NAME_BTN, callback_data="set_lb_name"))
    markup.add(
        types.InlineKeyboardButton("🔍 دریافت تله", callback_data="my_link_show"),
        types.InlineKeyboardButton("🏅 VIP", callback_data="vip_info"),
        types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu")
    )

    # ── v3.14: لیدربورد تصویری با کش پلکانی تنبل (ادمین ۱۰دقیقه / کاربر ۲ساعت) ──
    _img_ok = False
    if leaderboard_img and leaderboard_img.AVAILABLE and rows_board:
        sub = "۱۰ شکارچی برتر"
        users = None
        try:
            users = []
            for r in rows_board:
                try:
                    _v = db.is_vip(r['owner_id'])
                except Exception:
                    _v = False
                # تصویر برای همهٔ کاربران مشترک است (کش پلکانی)؛ ستارهٔ «شما»
                # در تصویر نیست — رتبهٔ اختصاصی هر کاربر در کپشن می‌آید.
                users.append((sanitize_name(r['first_name'] or "بی‌نام"),
                              r['cnt'], _v, False))
        except Exception as lb_err:
            logger.warning("leaderboard image render failed: %s", lb_err)
            users = None
        if users:
            _img_ok = lb_send_image(chat_id, users, sub, cap_short, markup,
                                    board="all", user_id=user_id)
    if _img_ok:
        return

    # ── فالبک ۱: عکس ثابت لیدربورد — با همان کپشن کوتاه ──
    if LEADERBOARD_PHOTO_ID:
        try:
            bot.send_photo(chat_id, LEADERBOARD_PHOTO_ID, caption=cap_short, reply_markup=markup)
            return
        except Exception:
            pass

    # ── v3.14 فالبک ۲: فقط وقتی «نمایش تصویری» به مشکل خورد (رندر زنده + عکس ثابت
    # هر دو شکست خوردند) دکمه‌های شیشه‌ای ۱۰ نفر برتر برمی‌گردند تا فهرست واقعی
    # دیتابیسِ زنده از دست نرود: [نام] [🎫VIP یا 💳عادی] [تعداد شکار — فقط عدد] ──
    try:
        if rows_board:
            for _gi, _gr in enumerate(rows_board):
                try:
                    _gv = db.is_vip(_gr['owner_id'])
                except Exception:
                    _gv = False
                _gn = sanitize_name(_gr['first_name'] or "بی‌نام")
                if len(_gn) > 20:
                    _gn = _gn[:19] + "…"
                _gbadge = "🎫VIP" if _gv else "💳عادی"
                _gcb = "lbwho:a:%s" % (_gr['owner_id'],)
                markup.row(
                    types.InlineKeyboardButton(_gn, callback_data=_gcb),
                    types.InlineKeyboardButton(_gbadge, callback_data=_gcb),
                    types.InlineKeyboardButton(to_persian_digits(_gr['cnt']), callback_data=_gcb),
                )
    except Exception as _glb_err:
        logger.warning("lb glass buttons (fallback) failed: %s", _glb_err)
    bot.send_message(chat_id, cap_short, reply_markup=markup)
def handle_original_callback(callback_data, chat_id, user_id, message_id=None):
    """اجرای کالبک اصلی بعد از تأیید عضویت، بدون answer_callback_query اضافه."""
    if callback_data == "main_menu":
        show_main_menu(chat_id, user_id, message_id)
    elif callback_data.startswith("snooplist_page_"):
        page = int(callback_data.split("_")[-1])
        show_snoop_list(chat_id, page, message_id)
    elif callback_data == "my_link_show":
        link = user_link(user_id)
        samples = [
            f"[جرات داری روم کلیک کن 👁️]({link})",
            f"[میخوای آشنا شیم؟ 🤭]({link})",
        ]
        text = (
            f"🔍 *تلهٔ اختصاصی تو:*\n{link}\n\n"
            f"🎭 این لینک خام رو که نمی‌تونی توی بیو بذاری...\n"
            f"باید پشت یه متن قایمش کنی — این میشه *هایپرلینک*.\n"
            f"یه جملهٔ جذاب که هرکی روش بزنه، مستقیم می‌افته توی دامت.\n\n"
            f"📋 چند نمونهٔ آماده با کد خودت:\n"
            f"1. {samples[0]}\n"
            f"2. {samples[1]}\n\n"
            f"💡 هرکدوم رو دوست داشتی *کپی* کن و بچسبون توی بیوگرافیت.\n"
            f"یا خودت یه متن دلخواه بساز..."
        )
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn1 = types.InlineKeyboardButton("📋 کپی 1", callback_data="copy_sample_1",
                                          copy_text=types.CopyTextButton(samples[0]))
        btn2 = types.InlineKeyboardButton("📋 کپی 2", callback_data="copy_sample_2",
                                          copy_text=types.CopyTextButton(samples[1]))
        markup.add(btn1, btn2)
        markup.add(types.InlineKeyboardButton("✍️ ساخت هایپرلینک با متن دلخواه", callback_data="get_hyperlink"))
        markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
        send_or_edit_message(chat_id, text, markup, message_id)
    elif callback_data == "help":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(types.InlineKeyboardButton("📝 متن خوش‌آمد", callback_data="help_welcome"),
                   types.InlineKeyboardButton("🖼️ عکس خوش‌آمد", callback_data="help_welcome_photo"),
                   types.InlineKeyboardButton("🎭 نقاب کارآگاهی", callback_data="help_mask"),
                   types.InlineKeyboardButton("🎁 کد هدیه", callback_data="help_gift"),
                   types.InlineKeyboardButton("ℹ️ اطلاعات من", callback_data="help_myinfo"),
                   types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
        send_or_edit_message(chat_id, texts.HELP_MENU_PROMPT, markup, message_id)
    elif callback_data == "vip_info":
        text, markup, _gold_active = build_vip_gold_menu(user_id)
        send_or_edit_message(chat_id, text, markup, message_id)
    elif callback_data == "my_info":
        u = bot.get_chat(user_id)
        total_clicks = db.get_clicks_count(user_id)
        snoop_count = db.get_distinct_snoop_count(user_id)
        today_clicks = db.get_today_clicks_count(user_id)
        is_active_vip, vip_status_str = vip_status_display(user_id)
        emoji = get_user_rank_emoji(user_id)
        level = db.get_user_level_cached(user_id)
        xp = db.get_user_xp(user_id)
        title, _ = get_rank_tier(level)
        xp_next = db.xp_for_next_level(level)
        display_name = f"{emoji} {escape_md(u.first_name or 'بی‌نام')}" if emoji else escape_md(u.first_name or 'بی‌نام')

        # محاسبه progress bar برای سطح
        # نکته مهم: سطح ۱ از XP=0 شروع می‌شود (نه از xp_for_level(1)=100)
        # سطح L (L≥2) از xp_for_level(L) شروع می‌شود
        if xp_next:
            if level == 1:
                xp_this_level_start = 0
            else:
                xp_this_level_start = db.xp_for_level(level)
            xp_in_level = xp - xp_this_level_start
            xp_needed_this_level = xp_next - xp_this_level_start
            progress_pct = int(xp_in_level * 100 / xp_needed_this_level) if xp_needed_this_level > 0 else 0
            progress_pct = max(0, min(100, progress_pct))
            bar_len = 10
            filled = int(progress_pct * bar_len / 100)
            level_bar = '█' * filled + '░' * (bar_len - filled)
            xp_to_next = xp_next - xp
            level_section = (
                f"📊 سطح: {to_persian_digits(level)} — {emoji} {title}\n"
                f"✨ {to_persian_int(xp)} از {to_persian_int(xp_next)} دریافت شده\n"
                f"{level_bar} {to_persian_digits(progress_pct)}٪\n"
                f"🎯 تا سطح بعد: {to_persian_int(xp_to_next)} XP"
            )
        else:
            level_section = (
                f"📊 سطح: {to_persian_digits(level)} — {emoji} {title}\n"
                f"✨ XP: {to_persian_int(xp)}\n"
                f"🏆 به حداکثر سطح رسیده‌اید!"
            )

        text = (
            f"📋 *اطلاعات من*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {display_name}\n"
            f"🆔 {to_persian_digits(user_id)}\n"
            f"📎 @{u.username or 'ندارد'}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📈 *آمار*\n"
            f"👑 فضول: {to_persian_int(snoop_count)}\n"
            f"🖱️ کلیک: {to_persian_int(total_clicks)}\n"
            f"🖱️ کلیک امروز: {to_persian_int(today_clicks)}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *پیشرفت*\n"
            f"{level_section}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏅 *اشتراک*\n"
            f"وضعیت VIP: {vip_status_str}\n\n"
            f"🔗 *تلهٔ شما*\n"
            f"{user_link(user_id)}\n"
        )

        # بخش آخرین فعالیت‌ها
        activities = db.get_recent_activities(user_id, limit=4)
        if activities:
            text += f"\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
            text += f"🕐 *آخرین فعالیت‌ها*\n"
            for act in activities:
                # فرمت کردن زمان (شمسی)
                try:
                    ts = act.get('timestamp', '')
                    if ts:
                        # تبدیل به تاریخ شمسی
                        try:
                            g_date = datetime.datetime.strptime(ts[:10], "%Y-%m-%d").date()
                            j_date = jdatetime.date.fromgregorian(date=g_date)
                            time_str = to_persian_digits(j_date.strftime("%Y/%m/%d"))
                        except:
                            time_str = to_persian_digits(ts[:10])
                    else:
                        time_str = 'نامشخص'
                except:
                    time_str = 'نامشخص'

                if act['type'] == 'click':
                    name = escape_md(act.get('name', 'ناشناس'))
                    text += f"• {time_str}: {name} تله‌ات رو کلیک کرد\n"
                elif act['type'] == 'vip':
                    days = to_persian_digits(act.get('days', 0))
                    text += f"• {time_str}: VIP خریدی ({days} روز)\n"
                elif act['type'] == 'gift':
                    days = to_persian_digits(act.get('days', 0))
                    text += f"• {time_str}: VIP هدیه دادی ({days} روز)\n"
                elif act['type'] == 'task':
                    task_name = escape_md(act.get('task_name', 'ماموریت'))
                    text += f"• {time_str}: ماموریت «{task_name}» رو تکمیل کردی\n"

        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("🎯 ماموریت‌ها", callback_data="tasks_page_1"),
                   types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
        send_or_edit_message(chat_id, text, markup, message_id)
    elif callback_data == "leaderboard":
        show_leaderboard(chat_id, user_id)   # تابع show_leaderboard خودش پیام جدید می‌سازد
    # می‌توانید کالبک‌های دیگر را هم در اینجا اضافه کنید...
    else:
        # اگر کالبک ناشناخته بود، منوی اصلی را نشان بده
        show_main_menu(chat_id, user_id, message_id)

def render_wheel_info(chat_id, user_id):
    """v3.6: نمایش وضعیت چرخ شانس روزانه."""
    today_t = datetime.datetime.now(TEHRAN_TZ).date().isoformat()
    done = db.get_last_wheel_date(user_id) == today_t
    status_line = texts.WHEEL_DONE if done else texts.WHEEL_READY
    prize_lines = "\n".join(f"• {p['label']}" for p in WHEEL_PRIZES)
    text = texts.WHEEL_INFO.format(status_line=status_line, prize_lines=prize_lines)
    m = types.InlineKeyboardMarkup(row_width=1)
    if not done:
        m.add(types.InlineKeyboardButton(texts.WHEEL_SPIN_BTN, callback_data="wheel_spin"))
    m.add(types.InlineKeyboardButton("🎁 بازگشت به پاداش‌ها", callback_data="rewards_menu"))
    m.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
    bot.send_message(chat_id, text, reply_markup=m)

def render_daily_bonus(chat_id, user_id, delete_message_id=None):
    """v3.17: پنل جایزه روزانه — همهٔ کاربران؛ هر روز ساعت ۰۰:۰۰ ایران ریست می‌شود.
    چرخ شانس ویژهٔ VIP است ولی جایزه روزانه برای همه باز است."""
    if delete_message_id:
        try: bot.delete_message(chat_id, delete_message_id)
        except Exception: pass
    today_t = datetime.datetime.now(TEHRAN_TZ).date().isoformat()
    info = db.get_daily_bonus(user_id)
    raw_streak = info.get("streak") or 0
    last_claim = info.get("last_claim")
    # v3.19: استریک مؤثر — اگر دیروز/امروز نگرفته باشد، استریک عملاً ریست شده (نمایش ۰)
    yesterday_t = (datetime.datetime.now(TEHRAN_TZ).date() - datetime.timedelta(days=1)).isoformat()
    streak = raw_streak if last_claim in (today_t, yesterday_t) else 0
    done = last_claim == today_t
    # نمایش پاداش استریک فعلی (برای روز بعدی اگر امشب بگیرد)
    bonus_pct = min(max(streak, 0) * DAILY_STREAK_BONUS_STEP, DAILY_STREAK_BONUS_CAP)
    status_line = texts.DAILY_BONUS_DONE if done else texts.DAILY_BONUS_READY
    prize_lines = "\n".join(f"• {p['label']}" for p in DAILY_PRIZES)
    text = texts.DAILY_BONUS_INFO.format(
        streak=to_persian_digits(streak),
        bonus_pct=to_persian_digits(bonus_pct),
        status_line=status_line,
        prize_lines=prize_lines,
        vip_roadmap=texts.DAILY_VIP_ROADMAP,
    )
    m = types.InlineKeyboardMarkup(row_width=1)
    if not done:
        m.add(types.InlineKeyboardButton(texts.DAILY_BONUS_CLAIM_BTN, callback_data="daily_claim"))
    m.add(types.InlineKeyboardButton("🎡 چرخ شانس (ویژه)", callback_data="wheel_info"))
    m.add(types.InlineKeyboardButton("🎁 بازگشت به پاداش‌ها", callback_data="rewards_menu"))
    m.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
    bot.send_message(chat_id, text, reply_markup=m)

def render_my_traps(chat_id, user_id, delete_message_id=None):
    """v3.6: نمایش لیست تله‌های چندگانه کاربر VIP."""
    if delete_message_id:
        try: bot.delete_message(chat_id, delete_message_id)
        except Exception: pass
    max_traps = db.get_setting_int("vip_max_traps", 3)
    traps = db.get_traps_of(user_id)
    counts = db.get_trap_click_counts(user_id)
    main_c = counts.get('main', {'clicks': 0, 'snoops': 0})
    rows = [texts.MY_TRAPS_MAIN.format(icon="🏠", clicks=to_persian_int(main_c['clicks']), snoops=to_persian_int(main_c['snoops']))]
    markup = types.InlineKeyboardMarkup(row_width=1)
    for tr in traps:
        c = counts.get(tr['trap_code'], {'clicks': 0, 'snoops': 0})
        lbl = tr['label'] or 'تله'
        rows.append(texts.MY_TRAPS_ROW.format(icon="🕳", label=escape_md(lbl), clicks=to_persian_int(c['clicks']), snoops=to_persian_int(c['snoops'])))
        tlink = f"ble.ir/{BOT_USERNAME}?start={tr['trap_code']}"
        markup.add(types.InlineKeyboardButton(f"📋 کپی لینک «{lbl}»", callback_data=f"copy_trap_{tr['trap_code']}", copy_text=types.CopyTextButton(tlink)))
        markup.add(types.InlineKeyboardButton(f"🗑 حذف «{lbl}»", callback_data=f"del_trap_{tr['trap_code']}"))
    rows_text = "\n".join(rows)
    text = texts.MY_TRAPS_HEADER.format(rows=rows_text)
    if not traps:
        text += "\n" + texts.MY_TRAPS_EMPTY_EXTRA
    if 1 + len(traps) < max_traps:
        markup.add(types.InlineKeyboardButton("➕ تلهٔ جدید", callback_data="add_trap_start"))
    else:
        text += "\n\n" + texts.MY_TRAPS_LIMIT.format(max_traps=to_persian_digits(max_traps))
    markup.add(types.InlineKeyboardButton("🔙 تلهٔ من", callback_data="my_link_show"))
    markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
    bot.send_message(chat_id, text, reply_markup=markup)

def render_trap_analytics(chat_id, user_id, delete_message_id=None):
    """v3.6: آنالیز حرفه‌ای تله (VIP)."""
    if delete_message_id:
        try: bot.delete_message(chat_id, delete_message_id)
        except Exception: pass
    total = db.get_clicks_count(user_id)
    snoops = db.get_distinct_snoop_count(user_id)
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(types.InlineKeyboardButton("🔙 تلهٔ من", callback_data="my_link_show"))
    m.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
    if total == 0:
        bot.send_message(chat_id, texts.ANALYTICS_EMPTY, reply_markup=m)
        return
    today_c = db.get_today_clicks_count(user_id)
    c7 = db.get_owner_clicks_window(user_id, 7)
    c30 = db.get_owner_clicks_window(user_id, 30)
    avg7 = c7 / 7.0
    this_w, last_w = db.get_owner_weekly_compare(user_id)
    if last_w > 0:
        diff = int((this_w - last_w) * 100 / last_w)
        week_cmp = f"{('🟢 +' if diff >= 0 else '🔴 ')}{to_persian_digits(abs(diff))}٪ نسبت به هفتهٔ قبل"
    elif this_w > 0:
        week_cmp = "🟢 شروع رشد!"
    else:
        week_cmp = "⚪️ بدون تغییر"
    hours = db.get_clicks_by_hour(user_id, 30)
    top_hours = sorted(hours.items(), key=lambda kv: -kv[1])[:3]
    if top_hours:
        peak_str = "، ".join(f"{to_persian_digits(h)}:۰۰" for h, _ in top_hours)
    else:
        peak_str = texts.ANALYTICS_PEAK_NONE
    best_d, best_c = db.get_best_click_day(user_id)
    if best_d:
        try:
            j_best = jdatetime.date.fromgregorian(date=datetime.date.fromisoformat(best_d))
            best_str = f"{to_persian_digits(j_best.strftime('%Y/%m/%d'))} با {to_persian_digits(best_c)} کلیک"
        except Exception:
            best_str = f"{to_persian_digits(best_d)} با {to_persian_digits(best_c)} کلیک"
    else:
        best_str = "—"
    rank = db.get_user_rank_by_distinct(user_id)
    rank_str = to_persian_digits(rank) if rank else "—"
    lines = [
        texts.ANALYTICS_HEADER,
        f"🖱️ کلیک کل: {to_persian_int(total)}",
        f"👑 فضول یکتا: {to_persian_int(snoops)}",
        f"📅 امروز: {to_persian_int(today_c)} | ۷ روز: {to_persian_int(c7)} | ۳۰ روز: {to_persian_int(c30)}",
        f"📊 میانگین هفته: {to_persian_digits(int(round(avg7)))} کلیک/روز",
        f"📈 روند: {week_cmp}",
        f"⏰ ساعات اوج شکار: {peak_str}",
        f"🏅 بهترین روز: {best_str}",
        f"🏆 رتبهٔ تو بین شکارچی‌ها: {rank_str}",
    ]
    # تفکیک تله‌ها
    traps = db.get_traps_of(user_id)
    if traps:
        counts = db.get_trap_click_counts(user_id)
        lines.append("")
        lines.append("🕳 *عملکرد تله‌ها:*")
        main_c = counts.get('main', {'clicks': 0, 'snoops': 0})
        lines.append(f"• تلهٔ اصلی: {to_persian_int(main_c['clicks'])} کلیک ({to_persian_int(main_c['snoops'])} فضول)")
        for tr in traps:
            c = counts.get(tr['trap_code'], {'clicks': 0, 'snoops': 0})
            lines.append(f"• {escape_md(tr['label'] or 'تله')}: {to_persian_int(c['clicks'])} کلیک ({to_persian_int(c['snoops'])} فضول)")
    bot.send_message(chat_id, "\n".join(lines), reply_markup=m)

def show_main_menu(chat_id, user_id, message_id=None):
    """نمایش منوی اصلی بدون answer_callback_query اضافی."""
    text = build_dynamic_home_text(user_id)
    markup = main_menu(user_id)
    send_or_edit_message(chat_id, text, markup, message_id)

def send_or_edit_message(chat_id, text, markup, message_id):
    """در صورت وجود message_id ویرایش می‌کند، در غیر این صورت پیام جدید می‌فرستد."""
    if message_id:
        try:
            safe_edit_text(text, chat_id, message_id, reply_markup=markup)
        except Exception:
            bot.send_message(chat_id, text, reply_markup=markup)
    else:
        bot.send_message(chat_id, text, reply_markup=markup)
_pending_forcejoin_msgs = {}  # v3.9.2: user_id -> message_id پیام عضویت اجباری (برای پاک‌سازی بعدی)

# ====== کیبورد شیشه‌ای (یکپارچه) ======
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    # v3.24.4: تلمتری — wrap کامل؛ همهٔ خروجی‌ها (returnهای داخلی) پوشش داده می‌شوند
    _t0 = time.time()
    try:
        _callback_handler_impl(call)
    finally:
        try:
            db.log_usage_event("cb", call.data[:120], (time.time() - _t0) * 1000)
        except Exception:
            pass

def _callback_handler_impl(call):
    global broadcast_mode, broadcast_admin_chat, broadcast_preview_msg, broadcast_started_at
    _t0 = time.time()  # v4.7: رفع NameError تله‌متری در مسیر خطا
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    data = call.data
    # v3.22: دروازهٔ حالت نگهداری — فقط سوپرادمین عبور می‌کند (قبل از هر ثبت آماری)
    if maintenance_gate(user_id):
        try:
            bot.answer_callback_query(call.id, texts.MAINTENANCE_CB_SHORT, show_alert=True)
        except Exception:
            pass
        return
    record_message(call.from_user.id)
    # v3.24.3: ثبت آمار کلیک و sync پروفایل → پس‌زمینه (قبل از این، دو commit سریالی
    # روی قفل تک-کانکشن جلوی پاسخ‌دهی را می‌گرفت؛ آمار لازم نیست سریال باشد)
    def _cb_stats_bg():
        try:
            db.log_callback_click(data)
        except Exception:
            pass
        try:
            db.sync_user_profile(user_id, call.from_user.first_name, call.from_user.username)
        except Exception:
            pass
    threading.Thread(target=_cb_stats_bg, daemon=True).start()
    while True:
        try:
            if db.is_blocked(user_id):
                bot.answer_callback_query(call.id, "⛔ حساب شما مسدود شده است.", show_alert=True)
                return


            force_check_exceptions = ["main_menu", "cancel_state"]
            is_admin = data.startswith("admin_") or data in [
                "admin_panel", "admin_search_user", "admin_vip_stats",
                "admin_most_active", "admin_gift_list", "admin_new_gift",
                "admin_vip", "admin_addvip", "admin_daily", "admin_broadcast",
                "admin_support_list", "admin_forced_ads"
            ]
            is_checkjoin = data.startswith("checkjoin_")

            # ----- بررسی اولیهٔ عضویت برای تمام callbackهای غیرمجاز -----
            if not (is_admin or is_checkjoin or any(data.startswith(ex) for ex in force_check_exceptions)):
                if not is_subscribed(user_id):
                    markup = build_channel_keyboard(data, user_id)
                    if markup:
                        bot.answer_callback_query(call.id, "⚡️ برای استفاده از قدرت‌های تاریک، ابتدا در کانال‌های زیر عضو شوید.")
                        if call.message.content_type == 'photo':
                            try:
                                bot.delete_message(chat_id, call.message.message_id)
                            except:
                                pass
                            _pj = bot.send_message(chat_id, texts.FORCE_JOIN_PROMPT, reply_markup=markup)
                            _pending_forcejoin_msgs[user_id] = _pj.message_id
                        else:
                            try:
                                safe_edit_text(texts.FORCE_JOIN_PROMPT, chat_id, call.message.message_id, reply_markup=markup)
                            except:
                                _pj = bot.send_message(chat_id, texts.FORCE_JOIN_PROMPT, reply_markup=markup)
                                _pending_forcejoin_msgs[user_id] = _pj.message_id
                    else:
                        bot.answer_callback_query(call.id, "⏳ در حال حاضر امکان بررسی عضویت وجود ندارد. لطفاً لحظاتی دیگر تلاش کنید.", show_alert=True)
                    return

            # v3.9.2: پاک‌سازی پیام عضویت اجباریِ باقی‌مانده از تعامل قبلی
            _pj_old = _pending_forcejoin_msgs.pop(user_id, None)
            if _pj_old:
                try: bot.delete_message(chat_id, _pj_old)
                except: pass

            # ----- مدیریت checkjoin (جلوگیری از Recursion) -----
            if is_checkjoin:
                original_callback = data[len("checkjoin_"):]
                # پاک کردن کش عضویت قبل از چک مجدد
                clear_subscription_cache(user_id)
                if is_subscribed(user_id):
                    bot.answer_callback_query(call.id, "✅ عضویت تأیید شد.", show_alert=True)
                    _pending_forcejoin_msgs.pop(user_id, None)
                    try:
                        bot.delete_message(chat_id, call.message.message_id)
                    except:
                        pass

                    # --- مستقیماً کالبک اصلی را اجرا کن ---
                    if original_callback == "show_pending_snoop":
                        info = db.get_pending_snoop(user_id)
                        if info:
                            # v4.7 (فقط نام برای غیر VIP): بدون شناسه/یوزرنیم/عکس
                            if info['vip_owner']:
                                msg = (f"🔔 *یه فضول روی لینک شما کلیک کرد!*\n"
                                    f"🕒 {info['t']}\n👤 {escape_md(info['display_name'])}\n"
                                    f"🆔 {fmt_id(info['clicker_id'], info['vip_owner'], owner_id=info['owner_id'])}\n"
                                    f"📎 {fmt_uname(info['clicker_username'], info['vip_owner'], owner_id=info['owner_id'], uid=info['clicker_id'])}")
                            else:
                                msg = (f"🔔 *یه فضول روی لینک شما کلیک کرد!*\n"
                                    f"🕒 {info['t']}\n👤 {escape_md(info['display_name'])}")
                                msg += "\n\n" + texts.REVEAL_TEASE
                            if info['repeat'] == 1:
                                msg += "\n\n🆕 *فضول جدید!* این اولین کلیکشه."
                            if info['repeat'] > 3:
                                msg += "\n🔥 *فضول حرفه‌ای شناسایی شد!*"
                            if info['gift_vip_given']:
                                msg += "\n\n🎁 *هدیه:* ۱ روز VIP به خاطر شکار یک کاربر جدید!"
                            markup = types.InlineKeyboardMarkup(row_width=2)
                            markup.add(
                                types.InlineKeyboardButton("🏷️ لقب دادن", callback_data=f"nick_{info['clicker_id']}"),
                                types.InlineKeyboardButton("✉️ پیام ناشناس", callback_data=f"anon_{info['clicker_id']}"),
                                types.InlineKeyboardButton("📊 اطلاعات فضول", callback_data=f"snoopdetail_{info['clicker_id']}"),
                                types.InlineKeyboardButton("🎁 هدیه به فضول", callback_data=f"giftvip_{info['clicker_id']}"),
                                types.InlineKeyboardButton("📋 لیست فضول‌ها", callback_data="snooplist_page_1"),
                                types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu")
                            )
                            _add_reveal_button(markup, info['owner_id'], info['clicker_id'], info['vip_owner'])
                            if info['repeat'] > 3:
                                markup.add(types.InlineKeyboardButton("🔕 بی‌صدا", callback_data=f"mute_{info['clicker_id']}"))
                            if info['photo_file_id'] and info['vip_owner']:
                                try:
                                    bot.send_photo(user_id, info['photo_file_id'], caption=msg, reply_markup=markup)
                                except:
                                    bot.send_message(user_id, msg, reply_markup=markup)
                            else:
                                bot.send_message(user_id, msg, reply_markup=markup)
                        else:
                            bot.send_message(user_id, "⏳ اطلاعات فضول منقضی شده یا در دسترس نیست.")
                        return

                    # برای بقیهٔ کالبک‌ها: data رو به original_callback تغییر بده و continue بزن
                    # تا callback_handler خودش همه چیز رو هندل کنه
                    data = original_callback
                    continue

                else:
                    # هنوز عضو نیست
                    markup = build_channel_keyboard(original_callback, user_id)
                    if markup:
                        bot.answer_callback_query(call.id, "⏳ هنوز در کانال‌های زیر عضو نیستی.", show_alert=True)
                        try:
                            safe_edit_text(texts.FORCE_JOIN_PROMPT, chat_id, call.message.message_id, reply_markup=markup)
                        except:
                            pass
                    return

            # ============================================================
            # از اینجا به بعد، تمام بخش‌های اصلی callback_handler قرار دارند
            # هر جا قبلاً return callback_handler(call) داشتیم،
            # به data = new_callback; continue تغییر یافته است.
            # ============================================================

            # ----- show_pending_snoop (مستقیم، بدون عضویت) -----
            if data == "show_pending_snoop":
                if is_subscribed(user_id):
                    info = db.get_pending_snoop(user_id)
                    if info:
                        # v4.7 (فقط نام برای غیر VIP): بدون شناسه/یوزرنیم/عکس
                        if info['vip_owner']:
                            msg = (f"🔔 *یه فضول روی لینک شما کلیک کرد!*\n"
                                   f"🕒 {info['t']}\n👤 {escape_md(info['display_name'])}\n"
                                   f"🆔 {fmt_id(info['clicker_id'], info['vip_owner'], owner_id=info['owner_id'])}\n📎 {fmt_uname(info['clicker_username'], info['vip_owner'], owner_id=info['owner_id'], uid=info['clicker_id'])}")
                        else:
                            msg = (f"🔔 *یه فضول روی لینک شما کلیک کرد!*\n"
                                   f"🕒 {info['t']}\n👤 {escape_md(info['display_name'])}")
                            msg += "\n\n" + texts.REVEAL_TEASE
                        if info['repeat'] == 1:
                            msg += "\n\n🆕 *فضول جدید!* این اولین کلیکشه."
                        if info['repeat'] > 3:
                            msg += "\n🔥 *فضول حرفه‌ای شناسایی شد!*"
                        if info['gift_vip_given']:
                            msg += "\n\n🎁 *هدیه:* ۱ روز VIP به خاطر شکار یک کاربر جدید!"
                        markup = types.InlineKeyboardMarkup(row_width=2)
                        markup.add(
                            types.InlineKeyboardButton("🏷️ لقب دادن", callback_data=f"nick_{info['clicker_id']}"),
                            types.InlineKeyboardButton("✉️ پیام ناشناس", callback_data=f"anon_{info['clicker_id']}"),
                            types.InlineKeyboardButton("📊 اطلاعات فضول", callback_data=f"snoopdetail_{info['clicker_id']}"),
                            types.InlineKeyboardButton("🎁 هدیه به فضول", callback_data=f"giftvip_{info['clicker_id']}"),
                            types.InlineKeyboardButton("📋 لیست فضول‌ها", callback_data="snooplist_page_1"),
                            types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu")
                        )
                        _add_reveal_button(markup, info['owner_id'], info['clicker_id'], info['vip_owner'])
                        if info['repeat'] > 3:
                            markup.add(types.InlineKeyboardButton("🔕 بی‌صدا", callback_data=f"mute_{info['clicker_id']}"))
                        if info['photo_file_id'] and info['vip_owner']:
                            try:
                                bot.send_photo(user_id, info['photo_file_id'], caption=msg, reply_markup=markup)
                            except:
                                bot.send_message(user_id, msg, reply_markup=markup)
                        else:
                            bot.send_message(user_id, msg, reply_markup=markup)
                        bot.answer_callback_query(call.id, "✅ اطلاعات فضول نمایش داده شد.")
                    else:
                        bot.answer_callback_query(call.id, "اطلاعات قبلاً نمایش داده شده یا وجود ندارد.")
                else:
                    markup = build_channel_keyboard("show_pending_snoop", user_id)
                    if markup:
                        bot.answer_callback_query(call.id, texts.FORCE_JOIN_STILL_NOT)
                        try:
                            safe_edit_text(texts.SNOOP_CAUGHT_UNSUBSCRIBED, chat_id, call.message.message_id, reply_markup=markup)
                        except:
                            bot.send_message(chat_id, texts.SNOOP_CAUGHT_UNSUBSCRIBED, reply_markup=markup)
                return

            # ----- مشاهیر تاریکی -----
            if data == "leaderboard":
                clear_user_state(chat_id)
                bot.answer_callback_query(call.id)
                show_leaderboard(chat_id, user_id)
                return

            # ----- v3.11: سوییچ پنجرهٔ لیدربورد (کل ↔ هفته) -----
            if data in ("lbboard_all", "lbboard_week"):
                clear_user_state(chat_id)
                bot.answer_callback_query(call.id)
                show_leaderboard(chat_id, user_id,
                                 board="all" if data == "lbboard_all" else "week")
                return

            # ----- v3.12: جزئیات شکارچی از دکمه‌های شیشه‌ای تابلو -----
            if data.startswith("lbwho:"):
                try:
                    _lw = data.split(":")
                    _gbd = _lw[1] if len(_lw) > 1 else "a"
                    _target = int(_lw[2])
                    if _gbd == "w":
                        _rows = db.get_leaderboard_top_week(10)
                        _cnt = db.get_week_distinct_snoop_count(_target)
                        _rk = db.get_week_rank_by_distinct(_target)
                        _tt = db.count_week_board_owners()
                        _bl = "هفته"
                    else:
                        _rows = db.get_leaderboard_top(10)
                        _cnt = db.get_distinct_snoop_count(_target)
                        _rk = db.get_user_rank_by_distinct(_target)
                        _tt = db.count_all_users()
                        _bl = "همه‌زمان"
                    _nm = ""
                    for _r in _rows:
                        if _r['owner_id'] == _target:
                            _nm = sanitize_name(_r['first_name'] or "بی‌نام")
                            break
                    if not _nm:
                        try:
                            _row = db.conn.execute(
                                "SELECT COALESCE(NULLIF(display_name,''), first_name) FROM users WHERE user_id=?",
                                (_target,)).fetchone()
                            _nm = sanitize_name((_row[0] if _row else "") or "کاربر")
                        except Exception:
                            _nm = "کاربر"
                    try:
                        _gvip = db.is_vip(_target)
                    except Exception:
                        _gvip = False
                    _medal = rank_emoji_display(_rk) if (_rk and 1 <= _rk <= 3) else "🏅"
                    _rk_str = to_persian_digits(_rk) if _rk else "—"
                    _lwmsg = "%s رتبهٔ %s از %s (تابلوی %s)\n👤 %s\n🎯 %s شکار%s" % (
                        _medal, _rk_str, to_persian_digits(_tt), _bl,
                        _nm, to_persian_digits(_cnt),
                        ("\n👑 عضویت VIP فعال دارد ✨" if _gvip else ""))
                    bot.answer_callback_query(call.id, _lwmsg, show_alert=True)
                except Exception as _lw_err:
                    try:
                        bot.answer_callback_query(call.id, "⚠️ %s" % _lw_err)
                    except Exception:
                        pass
                return

            if data == "toggle_leaderboard_hide":
                current_hide = db.is_hide_leaderboard(user_id)
                db.set_hide_leaderboard(user_id, not current_hide)
                bot.answer_callback_query(call.id, "وضعیت نمایش تغییر کرد.")
                show_leaderboard(chat_id, user_id)
                return

            # ----- v3.20: نام نمایشی لیدربورد -----
            if data == "set_lb_name":
                clear_user_state(chat_id)
                set_user_state(chat_id, ('set_lb_name',))
                bot.answer_callback_query(call.id)
                try:
                    _cur = db.get_display_name(user_id)
                    _cur_line = ("نام فعلی تابلو: %s" % _cur) if _cur else "الان نام اکانتت نمایش داده می‌شود."
                    _mk = types.InlineKeyboardMarkup(row_width=1)
                    _mk.add(types.InlineKeyboardButton("🔄 بازگشت به نام اکانت", callback_data="reset_lb_name"))
                    _mk.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                    bot.send_message(chat_id, texts.LB_NAME_PROMPT.format(current=_cur_line), reply_markup=_mk)
                except Exception as e:
                    logger.error("set_lb_name prompt error: %s", e)
                return

            if data == "reset_lb_name":
                clear_user_state(chat_id)
                db.set_display_name(user_id, None)
                bot.answer_callback_query(call.id, texts.LB_NAME_RESET_OK)
                show_leaderboard(chat_id, user_id)
                return

            # ----- mute / unmute (toggle پویا) -----
            if data.startswith("mute_"):
                target_id = int(data.split("_")[1])
                db.mute_snoop(user_id, target_id)
                # آپدیت دکمه: تبدیل به «با صدا»
                try:
                    # ساخت کیبورد جدید با دکمه «با صدا»
                    new_markup = types.InlineKeyboardMarkup(row_width=2)
                    new_markup.add(
                        types.InlineKeyboardButton("✉️ پیام ناشناس", callback_data=f"anon_{target_id}"),
                        types.InlineKeyboardButton("🏷️ لقب", callback_data=f"nick_{target_id}"),
                        types.InlineKeyboardButton("🎁 هدیه VIP", callback_data=f"giftvip_{target_id}"),
                        types.InlineKeyboardButton("🔙 لیست", callback_data="snooplist_page_1"))
                    new_markup.add(types.InlineKeyboardButton("🔔 با صدا", callback_data=f"unmute_{target_id}"))
                    new_markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=new_markup)
                except: pass
                bot.answer_callback_query(call.id, "🔕 این فضول بی‌صدا شد.")
                return
            if data.startswith("unmute_"):
                target_id = int(data.split("_")[1])
                db.unmute_snoop(user_id, target_id)
                # آپدیت دکمه: تبدیل به «بی‌صدا»
                try:
                    new_markup = types.InlineKeyboardMarkup(row_width=2)
                    new_markup.add(
                        types.InlineKeyboardButton("✉️ پیام ناشناس", callback_data=f"anon_{target_id}"),
                        types.InlineKeyboardButton("🏷️ لقب", callback_data=f"nick_{target_id}"),
                        types.InlineKeyboardButton("🎁 هدیه VIP", callback_data=f"giftvip_{target_id}"),
                        types.InlineKeyboardButton("🔙 لیست", callback_data="snooplist_page_1"))
                    new_markup.add(types.InlineKeyboardButton("🔕 بی‌صدا", callback_data=f"mute_{target_id}"))
                    new_markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=new_markup)
                except: pass
                bot.answer_callback_query(call.id, "🔔 این فضول با صدا شد.")
                return

            # ----- پشتیبانی -----
            if data == "support_exit":
                remove_support_session(chat_id)
                pop_support_partner(chat_id)
                clear_user_state(chat_id)
                bot.answer_callback_query(call.id, "از پشتیبانی خارج شدید.")
                show_main_menu_for_callback(call, chat_id, user_id)
                return

            # ----- کد هدیه -----
            if data == "gift_code":
                clear_user_state(chat_id)
                # دریافت کدهای هدیه فعال برای این کاربر
                # کد valid = ظرفیت پر نشده + حذف نشده + کاربر قبلاً استفاده نکرده
                all_codes = db.get_all_gift_codes()
                valid_codes = []
                for c in all_codes:
                    # اگر ظرفیت پر شده، رد کن
                    if c['used_count'] >= c['max_uses']:
                        continue
                    # اگر کاربر قبلاً استفاده کرده، رد کن
                    already_used = db.conn.execute(
                        "SELECT 1 FROM gift_usage WHERE code=? AND user_id=?",
                        (c['code'], user_id)
                    ).fetchone()
                    if already_used:
                        continue
                    valid_codes.append(c)

                if not valid_codes:
                    bot.answer_callback_query(call.id)
                    bot.send_message(chat_id,
                        "🎁 *کد هدیه*\n\n"
                        "در حال حاضر کد هدیهٔ فعالی برای شما موجود نیست.\n"
                        "اگر کد هدیه‌ای دارید، می‌توانید آن را مستقیماً ارسال کنید.",
                        reply_markup=home_markup())
                    return

                # نمایش کدهای فعال به‌صورت دکمه شیشه‌ای
                lines = ["🎁 *کدهای هدیهٔ فعال*\n"]
                for c in valid_codes:
                    days = c['days']
                    remaining = c['max_uses'] - c['used_count']
                    lines.append(f"• {to_persian_digits(days)} روز VIP — ظرفیت باقی‌مانده: {to_persian_digits(remaining)}")
                lines.append("\n💡 برای فعال‌سازی، روی یکی از دکمه‌های زیر بزنید:")

                markup = types.InlineKeyboardMarkup(row_width=1)
                for c in valid_codes:
                    days = c['days']
                    remaining = c['max_uses'] - c['used_count']
                    btn = types.InlineKeyboardButton(
                        f"🎁 {to_persian_digits(days)} روز VIP (ظرفیت: {to_persian_digits(remaining)})",
                        callback_data=f"redeem_gift_{c['code']}"
                    )
                    markup.add(btn)
                markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))

                bot.answer_callback_query(call.id)
                # ارسال به‌صورت پیام جدید (حذف پیام قبلی)
                try:
                    bot.delete_message(chat_id, call.message.message_id)
                except: pass
                bot.send_message(chat_id, "\n".join(lines), reply_markup=markup)
                return

            # فعال‌سازی کد هدیه با دکمه شیشه‌ای
            if data.startswith("redeem_gift_"):
                code = data[len("redeem_gift_"):]
                # بررسی مجدد اعتبار کد
                row = db.conn.execute("SELECT * FROM gift_codes WHERE code=?", (code,)).fetchone()
                if not row:
                    bot.answer_callback_query(call.id, "❌ این کد دیگر موجود نیست.", show_alert=True)
                    return
                if row['used_count'] >= row['max_uses']:
                    bot.answer_callback_query(call.id, "❌ ظرفیت این کد به پایان رسیده.", show_alert=True)
                    return
                already = db.conn.execute(
                    "SELECT 1 FROM gift_usage WHERE code=? AND user_id=?",
                    (code, user_id)
                ).fetchone()
                if already:
                    bot.answer_callback_query(call.id, "❌ شما قبلاً این کد را استفاده کرده‌اید.", show_alert=True)
                    return
                # فعال‌سازی کد
                result, gift_data = db.redeem_gift(code, user_id)
                if result:
                    bot.answer_callback_query(call.id,
                        f"🎉 کد با موفقیت فعال شد!\n{to_persian_digits(gift_data)} روز VIP به حساب شما اضافه شد.",
                        show_alert=True)
                    # به‌روزرسانی پیام
                    try:
                        safe_edit_text(
                            f"✅ کد {code} با موفقیت فعال شد!\n{to_persian_digits(gift_data)} روز VIP به حساب شما اضافه شد.",
                            chat_id, call.message.message_id,
                            reply_markup=home_markup()
                        )
                    except: pass
                else:
                    bot.answer_callback_query(call.id, f"❌ {gift_data}", show_alert=True)
                return

            # ----- پاسخ ناشناس -----
            if data.startswith("anon_reply_"):
                # v4.4: پیام ناشناس فقط برای VIP — درخواست کاربر ادمین
                _vg = anon_vip_gate(user_id)
                if _vg:
                    bot.answer_callback_query(call.id, "✉️ فقط VIP!", show_alert=True)
                    try:
                        bot.send_message(chat_id, _vg[0], reply_markup=_vg[1])
                    except Exception:
                        pass
                    return
                target_id = int(data.split("_")[-1])
                if db.is_anon_blocked(target_id, user_id):
                    bot.answer_callback_query(call.id, "⛔ بلاک شده‌اید.", show_alert=True)
                    return
                clear_user_state(chat_id)
                set_user_state(chat_id, ('anon_reply', target_id))
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, texts.ANON_REPLY_PROMPT, reply_markup=cancel_markup())
                return

            # ----- پشتیبانی پاسخ -----
            if data.startswith("support_reply_"):
                target_id = int(data.split("_")[-1])
                if user_id == ADMIN_ID:
                    remove_support_session(ADMIN_ID)
                    set_admin_reply(user_id, target_id)
                    bot.answer_callback_query(call.id)
                    bot.send_message(chat_id, "✍️ پاسخ:", reply_markup=cancel_markup())
                else:
                    add_support_session(user_id)
                    set_support_partner(user_id, ADMIN_ID)
                    bot.answer_callback_query(call.id)
                    bot.send_message(chat_id, "✉️ پیام:", reply_markup=cancel_markup())
                return

            # ----- بلاک / آنبلاک ناشناس -----
            if data.startswith("block_"):
                target_id = int(data.split("_")[1])
                db.block_anon(user_id, target_id)
                new_markup = types.InlineKeyboardMarkup()
                new_markup.add(types.InlineKeyboardButton("🔄 پاسخ ناشناس", callback_data=f"anon_reply_{user_id}"),
                               types.InlineKeyboardButton("✅ آنبلاک", callback_data=f"unblock_{target_id}"))
                try:
                    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=new_markup)
                except:
                    pass
                bot.answer_callback_query(call.id, "🚫 کاربر بلاک شد.")
                bot.send_message(ADMIN_ID, f"🚫 کاربر {user_id} کاربر {target_id} را بلاک کرد.")
                return
            if data.startswith("unblock_"):
                target_id = int(data.split("_")[1])
                db.unblock_anon(user_id, target_id)
                new_markup = types.InlineKeyboardMarkup()
                new_markup.add(types.InlineKeyboardButton("🔄 پاسخ ناشناس", callback_data=f"anon_reply_{user_id}"),
                               types.InlineKeyboardButton("🚫 بلاک", callback_data=f"block_{target_id}"))
                try:
                    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=new_markup)
                except:
                    pass
                bot.answer_callback_query(call.id, "✅ کاربر آزاد شد.")
                bot.send_message(ADMIN_ID, f"✅ کاربر {user_id} کاربر {target_id} را آنبلاک کرد.")
                return

            # ----- گزارش تخلف -----
            if data.startswith("report_") and not data.startswith("reportreason_"):
                target_id = int(data.split("_")[1])
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(
                    types.InlineKeyboardButton("😖 مزاحمت", callback_data=f"reportreason_{target_id}_1"),
                    types.InlineKeyboardButton("🤬 توهین", callback_data=f"reportreason_{target_id}_2"),
                    types.InlineKeyboardButton("🚯 اسپم", callback_data=f"reportreason_{target_id}_3"),
                    types.InlineKeyboardButton("❌ انصراف", callback_data="cancel_state"),
                )
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, "⚠️ دلیل گزارش را انتخاب کنید:", reply_markup=markup)
                return

            if data.startswith("reportreason_"):
                parts = data.split("_")
                target_id = int(parts[1])
                reason_code = parts[2]
                reasons = {"1": "مزاحمت", "2": "توهین", "3": "اسپم"}
                reason = reasons.get(reason_code, "نامشخص")

                reporter = db.get_user_basic(user_id)
                reporter_name = reporter['first_name'] if reporter and reporter['first_name'] else "بی‌نام"
                reporter_username = reporter['username'] if reporter and reporter['username'] else "ندارد"

                culprit = db.get_user_basic(target_id)
                culprit_name = culprit['first_name'] if culprit and culprit['first_name'] else "بی‌نام"
                culprit_username = culprit['username'] if culprit and culprit['username'] else "ندارد"

                message_text = db.get_last_anon_log(target_id, user_id)
                if not message_text:
                    message_text = "متن پیام در دسترس نیست"

                admin_text = texts.ADMIN_REPORT_MESSAGE.format(
                    complainant_name=escape_md(reporter_name),
                    complainant_id=user_id,
                    complainant_username=reporter_username,
                    culprit_name=escape_md(culprit_name),
                    culprit_id=target_id,
                    culprit_username=culprit_username,
                    message_text=escape_md(message_text[:500]),
                    reason=reason
                )

                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(
                    types.InlineKeyboardButton("🚫 بلاک خاطی", callback_data=f"admin_block_{target_id}"),
                    types.InlineKeyboardButton("✉️ پیام به خاطی", callback_data=f"admin_msg_{target_id}"),
                    types.InlineKeyboardButton("✅ بررسی شد", callback_data=f"admin_review_{target_id}_{user_id}_{reason_code}"),
                    types.InlineKeyboardButton("❌ رد گزارش", callback_data=f"admin_rejectreport_{user_id}")
                )

                bot.send_message(ADMIN_ID, admin_text, reply_markup=markup)
                bot.answer_callback_query(call.id, "گزارش شما به تاریکی ارسال شد.")
                try:
                    safe_edit_text("📨 گزارش شما به مدیر ارسال شد. با متخلف برخورد خواهد شد.", chat_id, call.message.message_id, reply_markup=home_markup())
                except:
                    pass
                return

            # ----- پنل ادمین -----
            if data == "admin_panel":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                clear_user_state(chat_id)
                safe_edit_text(texts.ADMIN_PANEL, chat_id, call.message.message_id, reply_markup=admin_panel_markup())
                bot.answer_callback_query(call.id)
                return

            # ----- v3.4: دسته‌های منوی ادمین -----
            if data == "admin_cat_users":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                safe_edit_text(texts.ADMIN_CAT_USERS, chat_id, call.message.message_id, reply_markup=admin_cat_users_markup())
                bot.answer_callback_query(call.id)
                return
            if data == "admin_cat_vip":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                safe_edit_text(texts.ADMIN_CAT_VIP, chat_id, call.message.message_id, reply_markup=admin_cat_vip_markup())
                bot.answer_callback_query(call.id)
                return
            if data == "admin_cat_gift":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                safe_edit_text(texts.ADMIN_CAT_GIFT, chat_id, call.message.message_id, reply_markup=admin_cat_gift_markup())
                bot.answer_callback_query(call.id)
                return
            if data == "admin_cat_broadcast":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                safe_edit_text(texts.ADMIN_CAT_BROADCAST, chat_id, call.message.message_id, reply_markup=admin_cat_broadcast_markup())
                bot.answer_callback_query(call.id)
                return
            if data == "admin_cat_events":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                safe_edit_text(texts.ADMIN_CAT_EVENTS, chat_id, call.message.message_id, reply_markup=admin_cat_events_markup())
                bot.answer_callback_query(call.id)
                return
            if data == "admin_cat_reminders":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                safe_edit_text(texts.ADMIN_CAT_REMINDERS, chat_id, call.message.message_id, reply_markup=admin_cat_reminders_markup())
                bot.answer_callback_query(call.id)
                return

            # ----- v3.11: بخش دیتابیس (بکاپ فوری / بازیابی / بکاپ خودکار) -----
            if data == "admin_cat_db":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                safe_edit_text(texts.ADMIN_CAT_DB, chat_id, call.message.message_id, reply_markup=admin_cat_db_markup())
                bot.answer_callback_query(call.id)
                return
            if data == "admin_backup_now":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                bot.answer_callback_query(call.id, "⏳ در حال آماده‌سازی بکاپ...")
                threading.Thread(target=_admin_backup_now_job, args=(chat_id,), daemon=True).start()
                return
            if data == "admin_restore_start":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                _set_restore_pending(True)
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id,
                                 "📤 لطفاً فایل bot_data.db را همین‌جا ارسال کنید.\n"
                                 "⏳ منتظر دریافت فایل هستم... (برای لغو: /cancel)")
                return
            if data == "admin_autoback_toggle":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                new_val = 0 if db.get_setting_int("auto_backup_enabled", 1) == 1 else 1
                db.set_setting("auto_backup_enabled", new_val)
                bot.answer_callback_query(call.id)
                try:
                    safe_edit_text(texts.ADMIN_CAT_DB, chat_id, call.message.message_id, reply_markup=admin_cat_db_markup())
                except Exception:
                    pass
                return

            # ----- v3.18: چالش فضول‌گیر برتر (ادمین) -----
            if data == "admin_challenge_menu":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                status = get_challenge_status()
                if status in ("scheduled", "active"):
                    status_fa = "زمان‌بندی‌شده (شمارش از ۰۰:۰۰ فردا)" if status == "scheduled" else "در جریان (شمارش فعال است)"
                    win = _challenge_window()
                    start_fa = _challenge_utc_to_tehran_str(win[0]) if win else to_persian_digits(db.get_setting("challenge_date", "") or "نامشخص")
                    end_fa = _challenge_utc_to_tehran_str(win[1]) if win else "نامشخص"
                    text = texts.ADMIN_CHALLENGE_MENU_ACTIVE.format(
                        status=status_fa,
                        count_start=start_fa,
                        end_time=end_fa,
                        remaining=("تا شروع شمارش: " if status == "scheduled" else "تا پایان شمارش: ") + _challenge_remaining_str(),
                        **_challenge_prize_dict(db.get_setting_int("challenge_reward_days", 3)),
                        top_preview=_challenge_standings_text(3, with_count=True))
                    markup = types.InlineKeyboardMarkup(row_width=1)
                    markup.add(types.InlineKeyboardButton("🏆 جدول برترین‌ها (۱۰ نفر)", callback_data="admin_challenge_top"))
                    markup.add(types.InlineKeyboardButton("🔄 بروزرسانی", callback_data="admin_challenge_menu"))
                    markup.add(types.InlineKeyboardButton("❌ لغو فوری چالش", callback_data="admin_challenge_cancel"))
                    markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_cat_events"))
                else:
                    text = texts.ADMIN_CHALLENGE_MENU_IDLE
                    markup = types.InlineKeyboardMarkup(row_width=1)
                    markup.add(types.InlineKeyboardButton("▶️ استارت چالش", callback_data="admin_challenge_start"))
                    markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_cat_events"))
                try:
                    safe_edit_text(text, chat_id, call.message.message_id, reply_markup=markup)
                except Exception:
                    bot.send_message(chat_id, text, reply_markup=markup)
                bot.answer_callback_query(call.id)
                return
            if data == "admin_challenge_top":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                text = texts.ADMIN_CHALLENGE_TOP.format(
                    remaining=("تا شروع شمارش: " if get_challenge_status() == "scheduled" else "تا پایان شمارش: ") + _challenge_remaining_str(),
                    top_list=_challenge_standings_text(10, with_count=True))
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(types.InlineKeyboardButton("🔄 بروزرسانی", callback_data="admin_challenge_top"))
                markup.add(types.InlineKeyboardButton("🔙 بازگشت به مدیریت چالش", callback_data="admin_challenge_menu"))
                try:
                    safe_edit_text(text, chat_id, call.message.message_id, reply_markup=markup)
                except Exception:
                    bot.send_message(chat_id, text, reply_markup=markup)
                bot.answer_callback_query(call.id)
                return
            if data == "admin_challenge_start":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                status = get_challenge_status()
                if status in ("scheduled", "active"):
                    bot.answer_callback_query(call.id, "⚠️ یک چالش فعال وجود دارد — اول لغوش کن.", show_alert=True)
                    return
                clear_user_state(chat_id)
                set_user_state(chat_id, ('admin_challenge_hours', None))
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, texts.ADMIN_CHALLENGE_ASK_HOURS, reply_markup=cancel_markup())
                return
            if data == "admin_challenge_go":
                # v3.18: تأیید نهایی استارت — تنظیم پنجره + اعلام به همه
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                st = get_user_state(chat_id)
                if not st or st[0] != 'admin_challenge_confirm':
                    bot.answer_callback_query(call.id, "⏱️ زمان تأیید منقضی شد — دوباره استارت کن.", show_alert=True)
                    return
                hours_val, prize_val = st[1]
                if get_challenge_status() in ("scheduled", "active"):
                    clear_user_state(chat_id)
                    bot.answer_callback_query(call.id, "⚠️ چالش دیگری فعال است.", show_alert=True)
                    return
                clear_user_state(chat_id)
                _s, _e, count_start_fa, end_fa = _challenge_start_challenge(hours_val, prize_val)
                announce = texts.CHALLENGE_ANNOUNCE.format(
                    **_challenge_prize_dict(prize_val),
                    duration_hours=to_persian_digits(hours_val))
                # ارسال اعلام در پس‌زمینه (بدون بلاک شدن هندلر)
                threading.Thread(target=_broadcast_to_all_users, args=(announce,), daemon=True).start()
                bot.answer_callback_query(call.id, "✅ چالش شروع شد")
                bot.send_message(chat_id,
                    texts.ADMIN_CHALLENGE_STARTED.format(
                        hours=to_persian_digits(hours_val),
                        **_challenge_prize_dict(prize_val),
                        count_start=count_start_fa,
                        end_time=end_fa) + "\n\n📨 پیام اعلام در پس‌زمینه برای همهٔ کاربران ارسال می‌شود.",
                    reply_markup=_admin_back_panel())
                return
            if data == "admin_challenge_cancel":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                status = get_challenge_status()
                if status not in ("scheduled", "active"):
                    bot.answer_callback_query(call.id, "چالش فعالی وجود ندارد.")
                    return
                confirm_markup = types.InlineKeyboardMarkup(row_width=1)
                confirm_markup.add(types.InlineKeyboardButton("✅ بله، لغو کن", callback_data="admin_challenge_cancel_ok"))
                confirm_markup.add(types.InlineKeyboardButton("🔙 انصراف", callback_data="admin_challenge_menu"))
                bot.answer_callback_query(call.id)
                try:
                    safe_edit_text(texts.ADMIN_CHALLENGE_CANCEL_CONFIRM, chat_id, call.message.message_id, reply_markup=confirm_markup)
                except Exception:
                    bot.send_message(chat_id, texts.ADMIN_CHALLENGE_CANCEL_CONFIRM, reply_markup=confirm_markup)
                return
            if data == "admin_challenge_cancel_ok":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                db.set_setting("challenge_status", "cancelled")
                bot.answer_callback_query(call.id, "✅ لغو شد")
                bot.send_message(chat_id, texts.ADMIN_CHALLENGE_CANCELLED, reply_markup=_admin_back_panel())
                return

            # ----- v3.4: تنظیمات (هدیهٔ ورود، reveal، یادآورها، گزارش هفتگی) -----
            if data == "admin_set_trial":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                cur = db.get_setting_int("trial_days", 3)
                clear_user_state(chat_id)
                set_user_state(chat_id, ('admin_set_trial', None))
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, texts.ADMIN_ASK_TRIAL_DAYS.format(current=to_persian_digits(cur)), reply_markup=cancel_markup())
                return
            if data == "admin_set_reveal_price":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                cur = db.get_setting_int("reveal_price", 30000) // 10
                clear_user_state(chat_id)
                set_user_state(chat_id, ('admin_set_reveal_price', None))
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, texts.ADMIN_ASK_REVEAL_PRICE.format(current=to_persian_int(cur)), reply_markup=cancel_markup())
                return
            if data == "admin_set_saveface_price":
                # v4.4: تنظیم قیمت «حفظ آبرو» تله از پنل ادمین
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                cur = _saveface_price_rial() // 10
                clear_user_state(chat_id)
                set_user_state(chat_id, ('admin_set_saveface_price', None))
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, f"🤫 قیمت «حفظ آبرو» تله را وارد کن (تومان یا ریال). فعلی: {to_persian_int(cur)} تومان", reply_markup=cancel_markup())
                return
            if data == "admin_toggle_reminder":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                new_val = 0 if db.get_setting_int("smart_reminder_enabled", 1) == 1 else 1
                db.set_setting("smart_reminder_enabled", new_val)
                bot.answer_callback_query(call.id)
                safe_edit_text(texts.ADMIN_CAT_REMINDERS, chat_id, call.message.message_id, reply_markup=admin_cat_reminders_markup())
                return
            if data == "admin_toggle_weekly":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                new_val = 0 if db.get_setting_int("weekly_report_enabled", 1) == 1 else 1
                db.set_setting("weekly_report_enabled", new_val)
                bot.answer_callback_query(call.id)
                safe_edit_text(texts.ADMIN_CAT_REMINDERS, chat_id, call.message.message_id, reply_markup=admin_cat_reminders_markup())
                return
            # ----- v3.22: حالت نگهداری -----
            if data == "admin_maint_toggle":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                new_val = 0 if db.get_setting_int("maintenance_mode", 0) == 1 else 1
                db.set_setting("maintenance_mode", new_val)
                # بی‌اعتبارکردن فوری کش تا بدون تأخیر اعمال شود
                _maint_cache["val"] = new_val
                _maint_cache["ts"] = time.time()
                logger.info(f"[ADMIN] maintenance mode -> {new_val}")
                bot.answer_callback_query(call.id)
                safe_edit_text(texts.ADMIN_MAINT_ON if new_val else texts.ADMIN_MAINT_OFF,
                               chat_id, call.message.message_id, reply_markup=admin_cat_reminders_markup())
                return
            if data == "admin_set_weekly_day":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                cur = db.get_setting_int("weekly_report_day", 6)
                clear_user_state(chat_id)
                set_user_state(chat_id, ('admin_set_weekly_day', None))
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, texts.ADMIN_ASK_WEEKLY_DAY.format(current=to_persian_digits(cur)), reply_markup=cancel_markup())
                return
            if data == "admin_set_weekly_hour":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                cur = db.get_setting_int("weekly_report_hour", 21)
                clear_user_state(chat_id)
                set_user_state(chat_id, ('admin_set_weekly_hour', None))
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, texts.ADMIN_ASK_WEEKLY_HOUR.format(current=to_persian_digits(cur)), reply_markup=cancel_markup())
                return
            if data == "admin_settings_overview":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                reminder_on = "روشن" if db.get_setting_int("smart_reminder_enabled", 1) == 1 else "خاموش"
                weekly_on = "روشن" if db.get_setting_int("weekly_report_enabled", 1) == 1 else "خاموش"
                maint_on = "روشن ✅" if db.get_setting_int("maintenance_mode", 0) == 1 else "خاموش"
                ch_status = get_challenge_status()
                ch_fa = {"scheduled": "زمان‌بندی‌شده", "active": "در جریان"}.get(ch_status, "غیرفعال")
                wd = _FA_WEEKDAY.get(db.get_setting_int("weekly_report_day", 6), ("جمعه", 4))[0]
                text = texts.ADMIN_SETTINGS_OVERVIEW.format(
                    trial_days=to_persian_digits(db.get_setting_int("trial_days", 3)),
                    reveal_price=to_persian_int(db.get_setting_int("reveal_price", 30000) // 10),
                    reminder_status=reminder_on, weekly_status=weekly_on,
                    weekly_day=wd, weekly_hour=to_persian_digits(db.get_setting_int("weekly_report_hour", 21)),
                    challenge_status=ch_fa, maintenance_status=maint_on)
                try:
                    safe_edit_text(text, chat_id, call.message.message_id, reply_markup=admin_cat_reminders_markup())
                except Exception:
                    bot.send_message(chat_id, text, reply_markup=admin_cat_reminders_markup())
                bot.answer_callback_query(call.id)
                return

            # ----- v3.18: چالش فضول‌گیر برتر (کاربر) -----
            if data == "challenge_info":
                status = get_challenge_status()
                reward_days = db.get_setting_int("challenge_reward_days", 3)
                if status == "scheduled":
                    text = texts.CHALLENGE_PENDING.format(
                        hours=_challenge_remaining_str(),
                        **_challenge_prize_dict(reward_days))
                elif status == "active":
                    text = texts.CHALLENGE_LIVE_HEADER.format(
                        remaining=_challenge_remaining_str(),
                        **_challenge_prize_dict(reward_days),
                        standings=_challenge_standings_text(),
                        motivation=_challenge_motivation_text(user_id))
                else:
                    text = texts.CHALLENGE_NONE
                markup = types.InlineKeyboardMarkup(row_width=2)
                if status == "active":
                    # v3.24.1: دو دکمه در یک ردیف — [نام کاربر][تعداد فضول‌ها]
                    # دکمهٔ نام → جزئیات زندهٔ بازیکن | دکمهٔ امتیاز → نمایشی (غیرکلیک)
                    win = _challenge_window()
                    if win:
                        _chal_icons = ['🥇', '🥈', '🥉']
                        _top_rows = _challenge_cached(("top", win[0], win[1], 3),
                                                      lambda: db.get_top_hunters_window(win[0], win[1], 3),
                                                      ttl=_CHALLENGE_CACHE_TTL_BOARD)
                        for _i, _r in enumerate(_top_rows):
                            _name = sanitize_name(_r['first_name'] or 'بی‌نام')
                            try:
                                _r_vip = db.is_vip(_r['owner_id'])
                            except Exception:
                                _r_vip = False
                            _icon = _chal_icons[_i] if _i < len(_chal_icons) else '•'
                            _cnt = f"🪤 {to_persian_digits(_r['snoops'])}"
                            markup.add(
                                types.InlineKeyboardButton(
                                    f"{_icon} {crown_name(_name, _r_vip)}",
                                    callback_data=f"chal_glass_{_r['owner_id']}"),
                                types.InlineKeyboardButton(_cnt, callback_data="chal_noop"))
                if status in ("scheduled", "active"):
                    # v3.24.2: چینش جدید — [بروزرسانی][تلهٔ من] در یک ردیف، [خانه] زیرش
                    markup.add(
                        types.InlineKeyboardButton("🔄 بروزرسانی", callback_data="challenge_info"),
                        types.InlineKeyboardButton("🔍 تلهٔ من", callback_data="my_link_show"))
                markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                # v3.24.0: منوی فضول‌گیر برتر مثل «کارت طلایی» عکس‌دار شد.
                # پیامِ عکس‌دار در بله قابل ادیت نیست → همیشه: حذف پیام قبلی ← ارسال عکس
                # با caption و دکمه‌ها؛ اگر عکس مردود بود، متن ساده (فالبک مثل vip_info).
                try:
                    bot.delete_message(chat_id, call.message.message_id)
                except Exception:
                    pass
                if CHALLENGE_PHOTO_ID:
                    try:
                        bot.send_photo(chat_id, CHALLENGE_PHOTO_ID, caption=text, reply_markup=markup)
                    except Exception:
                        bot.send_message(chat_id, text, reply_markup=markup)
                else:
                    bot.send_message(chat_id, text, reply_markup=markup)
                bot.answer_callback_query(call.id)
                return
            # ----- v3.24.1: دکمهٔ نمایشی امتیاز (تعداد فضول‌ها) — بدون اکشن -----
            if data == "chal_noop":
                bot.answer_callback_query(call.id, "🪤 تعداد فضول‌های شکارشده در این چالش")
                return
            # ----- v3.24.1: جزئیات بازیکن چالش — پاپ‌آپ alert (بدون پیام جدید) -----
            if data.startswith("chal_glass_"):
                status = get_challenge_status()
                win = _challenge_window()
                if status != "active" or not win:
                    bot.answer_callback_query(call.id, "⏳ چالش فعالی در جریان نیست.", show_alert=True)
                    return
                try:
                    target_uid = int(data.rsplit("_", 1)[1])
                except Exception:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                urow = db.get_user_basic(target_uid)
                _g_name = sanitize_name((urow['first_name'] if urow and urow['first_name'] else 'بی‌نام'))
                _g_score = db.get_challenge_score(target_uid, win[0], win[1])
                _g_rank = db.get_challenge_rank(target_uid, win[0], win[1])
                _g_icons = ['🥇', '🥈', '🥉', '🎖️']
                _g_icon = _g_icons[_g_rank - 1] if isinstance(_g_rank, int) and 1 <= _g_rank <= 4 else "🎖️"
                _g_rank_fa = to_persian_digits(_g_rank) if isinstance(_g_rank, int) else "بدون رتبه"
                # v3.24.1: فقط پاپ‌آپ alert — پیام جداگانه/ادیت ارسال نمی‌شود
                alert_text = f"{_g_icon} {_g_name}\n\n⚡ امتیاز فعلی: {to_persian_digits(_g_score)} فضول جدید\n🏅 رتبهٔ فعلی: {_g_rank_fa}"
                bot.answer_callback_query(call.id, alert_text, show_alert=True)
                return

            # ----- جستجوی کاربر -----
            if data == "admin_search_user":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                clear_user_state(chat_id)
                set_user_state(chat_id, ('admin_search_user',))
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, texts.ADMIN_USER_SEARCH_PROMPT, reply_markup=cancel_markup())
                return

            # ----- لیست کاربران -----
            # ----- v3.21: آمار کاربران + برترین‌های روز/هفته/ماه -----
            if data == "admin_user_stats":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                bot.answer_callback_query(call.id)
                try:
                    show_admin_user_stats(chat_id, call.message.message_id)
                except Exception as e:
                    logger.error("admin user-stats render error: %s", e)
                    try:
                        bot.send_message(chat_id, "⚠️ خطا در نمایش آمار کاربران. دوباره تلاش کن.")
                    except Exception:
                        pass
                return

            if data.startswith("admin_top_"):
                # admin_top_<window>_p<page> — window: day | week | month
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                _win, _tp = "day", 1
                try:
                    _body = data[len("admin_top_"):]
                    _win, _tp = _body.rsplit("_p", 1)
                    _tp = max(1, int(_tp))
                except Exception:
                    _win, _tp = "day", 1
                if _win not in ("day", "week", "month"):
                    _win = "day"
                bot.answer_callback_query(call.id)
                try:
                    show_top_users_list(chat_id, _tp, call.message.message_id, window=_win)
                except Exception as e:
                    logger.error("admin top-users render error: %s", e)
                    try:
                        bot.send_message(chat_id, "⚠️ خطا در نمایش لیست برترین‌ها. دوباره تلاش کن.")
                    except Exception:
                        pass
                return

            if data.startswith("admin_userlist_"):
                # v3.20: admin_userlist_<sort>_<page> | قدیمی: admin_userlist_page_<n> → invites
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                try:
                    _parts = data.split("_")
                    if len(_parts) >= 4 and _parts[2] in ("invites", "new"):
                        _sort, _page = _parts[2], int(_parts[3])
                    else:
                        _sort, _page = "invites", int(_parts[-1])
                except Exception:
                    _sort, _page = "invites", 1
                # اول answer تا دکمه فوری آزاد شود — رندر همیشه پیام جدید است
                bot.answer_callback_query(call.id)
                try:
                    show_admin_userlist(chat_id, _page, call.message.message_id, sort=_sort)
                except Exception as e:
                    logger.error("admin userlist render error: %s", e)
                    try:
                        bot.send_message(chat_id, "⚠️ خطا در نمایش لیست. دوباره تلاش کن.")
                    except Exception:
                        pass
                return

            if data.startswith("admin_resetwarns_"):
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                target_id = int(data.split("_")[-1])
                db.reset_warnings(target_id)
                bot.answer_callback_query(call.id, f"اخطارهای کاربر {target_id} بازنشانی و در صورت نیاز مسدودیتش لغو شد.")
                info = db.get_user_detail(target_id)
                if info:
                    show_user_detail(chat_id, target_id, call.message.message_id, info)
                return

            # v4.7 (اخطار به کاربر): افزایش شمارنده + پیام به کاربر + مسدودیت خودکار در اخطار سوم
            if data.startswith("admin_warn_"):
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                target_id = int(data.split("_")[-1])
                if target_id == ADMIN_ID:
                    bot.answer_callback_query(call.id, "نمی‌توانید به خودتان اخطار بدهید.", show_alert=True)
                    return
                current_warnings = db.increment_warning(target_id)
                if current_warnings >= 3:
                    db.block_user(target_id, by_admin=True)
                    try:
                        bot.send_message(target_id, texts.BAN_MESSAGE)
                    except ApiTelegramException as e:
                        if e.error_code == 403:
                            try: db.mark_user_blocked_bot(target_id)
                            except Exception: pass
                    except Exception:
                        pass
                    bot.answer_callback_query(call.id, f"⚠️ اخطار ۳ از ۳ ثبت شد — کاربر {target_id} مسدود شد.", show_alert=True)
                else:
                    try:
                        bot.send_message(target_id, texts.WARNING_MESSAGE.format(
                            current=current_warnings, reason="اخطار مستقیم از طرف مدیر ربات"))
                    except ApiTelegramException as e:
                        if e.error_code == 403:
                            try: db.mark_user_blocked_bot(target_id)
                            except Exception: pass
                    except Exception:
                        pass
                    bot.answer_callback_query(call.id, f"⚠️ اخطار {to_persian_digits(current_warnings)} از ۳ ثبت و به کاربر اعلام شد.")
                info = db.get_user_detail(target_id)
                if info:
                    show_user_detail(chat_id, target_id, call.message.message_id, info)
                return

            if data.startswith("user_detail_"):
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                target_id = int(data.split("_")[-1])
                info = db.get_user_detail(target_id)
                if not info:
                    bot.answer_callback_query(call.id, "کاربر یافت نشد.", show_alert=True)
                    return
                show_user_detail(chat_id, target_id, call.message.message_id, info)
                bot.answer_callback_query(call.id)
                return

            if data.startswith("admin_viprevoke_ok_"):
                # v3.16: تأیید نهایی لغو کامل VIP
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                target_id = int(data.split("_")[-1])
                ok = db.revoke_vip(target_id)
                if ok:
                    try:
                        safe_edit_text(
                            f"❌ VIP کاربر {target_id} به‌طور کامل لغو شد.\n(برای اعطای مجدد از دکمهٔ «➕ افزودن VIP» استفاده کن.)",
                            chat_id, call.message.message_id)
                    except Exception:
                        pass
                    bot.answer_callback_query(call.id, "VIP کاربر لغو شد.")
                    info = db.get_user_detail(target_id)
                    if info:
                        show_user_detail(chat_id, target_id, call.message.message_id, info)
                else:
                    bot.answer_callback_query(call.id, "این کاربر اصلاً VIP ندارد.", show_alert=True)
                    try:
                        safe_edit_text(f"⚠️ کاربر {target_id} اصلاً VIP نداشت.", chat_id, call.message.message_id)
                    except Exception:
                        pass
                return

            if data.startswith("admin_action_"):
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                parts = data.split("_")
                action = parts[2]
                target_id = int(parts[3])
                if action == "block":
                    db.block_user(target_id, by_admin=True)
                    bot.answer_callback_query(call.id, f"کاربر {target_id} مسدود شد.")
                elif action == "unblock":
                    db.unblock_user(target_id)
                    bot.answer_callback_query(call.id, f"کاربر {target_id} رفع مسدودیت شد.")
                elif action == "vip":
                    clear_user_state(chat_id)
                    set_user_state(chat_id, ('admin_quick_vip', target_id))
                    bot.answer_callback_query(call.id)
                    bot.send_message(chat_id, f"تعداد روز VIP برای کاربر {target_id}:", reply_markup=cancel_markup())
                    return
                elif action == "vipminus":
                    # v3.16: کاهش روزهای VIP
                    days_left = db.get_vip_days_left(target_id)
                    clear_user_state(chat_id)
                    set_user_state(chat_id, ('admin_quick_vip_minus', target_id))
                    bot.answer_callback_query(call.id)
                    bot.send_message(chat_id,
                                     f"➖ تعداد روز کاهش VIP برای کاربر {target_id}:\n(باقی‌ماندهٔ فعلی: {to_persian_digits(days_left)} روز)",
                                     reply_markup=cancel_markup())
                    return
                elif action == "viprevoke":
                    # v3.16: لغو کامل VIP — ابتدا تأییده
                    has_vip = db.get_vip_expire_date(target_id) is not None
                    if not has_vip:
                        bot.answer_callback_query(call.id, "این کاربر اصلاً VIP ندارد.", show_alert=True)
                        return
                    bot.answer_callback_query(call.id)
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("✅ بله، لغو کن", callback_data=f"admin_viprevoke_ok_{target_id}"))
                    markup.add(types.InlineKeyboardButton("🔙 انصراف", callback_data=f"user_detail_{target_id}"))
                    bot.send_message(chat_id,
                                     f"⚠️ مطمئنی می‌خوای VIP کاربر {target_id} به‌طور *کامل* لغو بشه؟\nاین عملیات قابل بازگشت نیست (برای بازگرداندن باید دوباره VIP اضافه کنی).",
                                     reply_markup=markup)
                    return
                elif action == "message":
                    set_admin_reply(user_id, target_id)
                    bot.answer_callback_query(call.id)
                    bot.send_message(chat_id, "✍️ پیام خود را بنویسید:", reply_markup=cancel_markup())
                    return
                return

            if data.startswith("admin_transactions_page_"):
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                page = int(data.split("_")[-1])
                show_admin_transactions(chat_id, page, call.message.message_id)
                bot.answer_callback_query(call.id)
                return

            # ----- فعال‌ترین‌ها -----
            if data == "admin_most_active":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                top = db.get_most_active_owners_by_unique(10)
                lines = ["🔥 *فعال‌ترین تله‌ها (بیشترین فضول)*"]
                for i, row in enumerate(top):
                    name = get_user_display(row['owner_id'], row['first_name'])
                    lines.append(f"{i+1}. {name} – {row['cnt']} فضول")
                markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel"))
                safe_edit_text("\n".join(lines), chat_id, call.message.message_id, reply_markup=markup)
                bot.answer_callback_query(call.id)
                return

            if data == "admin_vip_stats":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                active, expired = db.get_vip_stats()
                text = texts.ADMIN_VIP_STATS.format(active=active, expired=expired)
                markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙", callback_data="admin_panel"))
                safe_edit_text(text, chat_id, call.message.message_id, reply_markup=markup)
                bot.answer_callback_query(call.id)
                return

            if data.startswith("admin_anonlog_page_"):
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                page = int(data.split("_")[-1])
                show_admin_anon_logs(chat_id, page, call.message.message_id)
                bot.answer_callback_query(call.id)
                return
            if data.startswith("anonlog_action_"):
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                parts = data.split("_")
                action = parts[2]
                target_id = int(parts[3])
                if action == "msg":
                    set_admin_reply(user_id, target_id)
                    bot.answer_callback_query(call.id)
                    bot.send_message(chat_id, "✍️ پیام (از طرف پشتیبانی):", reply_markup=cancel_markup())
                elif action == "block":
                    db.block_user(target_id)
                    bot.answer_callback_query(call.id, f"کاربر {target_id} مسدود شد.")
                return

            if data.startswith("admin_review_"):
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                parts = data.split("_")
                culprit_id = int(parts[2])
                reporter_id = int(parts[3])
                reason_code = parts[4]
                reasons = {"1": "مزاحمت", "2": "توهین", "3": "اسپم"}
                reason = reasons.get(reason_code, "نامشخص")

                current_warnings = db.increment_warning(culprit_id)

                if current_warnings >= 3:
                    db.block_user(culprit_id, by_admin=True)
                    try:
                        bot.send_message(culprit_id, texts.BAN_MESSAGE)
                    except ApiTelegramException as e:
                        if e.error_code == 403:
                            try: db.mark_user_blocked_bot(culprit_id)
                            except Exception: pass
                    except: pass
                else:
                    try:
                        bot.send_message(culprit_id, texts.WARNING_MESSAGE.format(current=current_warnings, reason=reason))
                    except ApiTelegramException as e:
                        if e.error_code == 403:
                            try: db.mark_user_blocked_bot(culprit_id)
                            except Exception: pass
                    except: pass

                try:
                    if REVIEW_PHOTO_ID:
                        bot.send_photo(reporter_id, REVIEW_PHOTO_ID, caption=texts.REVIEWED_FEEDBACK)
                    else:
                        bot.send_message(reporter_id, texts.REVIEWED_FEEDBACK)
                except ApiTelegramException as e:
                    if e.error_code == 403:
                        try: db.mark_user_blocked_bot(reporter_id)
                        except Exception: pass
                except: pass

                bot.answer_callback_query(call.id, "اخطار ثبت و اطلاع‌رسانی انجام شد.")
                try:
                    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
                except:
                    pass
                return

            if data.startswith("admin_rejectreport_"):
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                reporter_id = int(data.split("_")[-1])
                # رفع باگ: mark blocked users
                try:
                    bot.send_message(reporter_id, texts.REJECTED_FEEDBACK)
                except ApiTelegramException as e:
                    if e.error_code == 403:
                        try: db.mark_user_blocked_bot(reporter_id)
                        except Exception: pass
                except: pass
                bot.answer_callback_query(call.id, "گزارش رد شد.")
                try:
                    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
                except:
                    pass
                return

            # ----- کدهای هدیه -----
            if data == "admin_gift_list":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                codes = db.get_all_gift_codes()
                lines = ["🎁 *لیست کدهای هدیه*\n"]
                if not codes:
                    lines.append("هیچ کد هدیه‌ای ساخته نشده.")
                for c in codes:
                    lines.append(f"• {c['code']} | {to_persian_digits(c['days'])} روز | استفاده: {to_persian_digits(c['used_count'])}/{to_persian_digits(c['max_uses'])}")
                markup = types.InlineKeyboardMarkup(row_width=1)
                # دکمه حذف برای هر کد (در صورت وجود)
                for c in codes:
                    markup.add(types.InlineKeyboardButton(f"🗑️ حذف {c['code']}", callback_data=f"admin_delete_gift_{c['code']}"))
                markup.add(types.InlineKeyboardButton("➕ کد هدیه جدید", callback_data="admin_new_gift"))
                markup.add(types.InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_panel"))
                safe_edit_text("\n".join(lines), chat_id, call.message.message_id, reply_markup=markup)
                bot.answer_callback_query(call.id)
                return

            if data.startswith("admin_delete_gift_"):
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                code = data[len("admin_delete_gift_"):]
                # تأیید حذف
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(
                    types.InlineKeyboardButton("✅ بله، حذف کن", callback_data=f"admin_confirm_delete_gift_{code}"),
                    types.InlineKeyboardButton("❌ انصراف", callback_data="admin_gift_list")
                )
                safe_edit_text(
                    f"⚠️ *تأیید حذف کد هدیه*\n\n"
                    f"آیا از حذف کد {code} مطمئن هستی؟\n"
                    f"⚠️ این عمل قابل بازگشت نیست.",
                    chat_id, call.message.message_id, reply_markup=markup,
                    parse_mode="Markdown"
                )
                bot.answer_callback_query(call.id)
                return

            if data.startswith("admin_confirm_delete_gift_"):
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                code = data[len("admin_confirm_delete_gift_"):]
                db.delete_gift_code(code)
                bot.answer_callback_query(call.id, f"✅ کد {code} حذف شد.")
                # برگشت به لیست کدها
                data = "admin_gift_list"
                continue

            if data == "admin_new_gift":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                clear_user_state(chat_id)
                set_user_state(chat_id, ('new_gift_days',))
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, "تعداد روز VIP کد هدیه را وارد کنید:", reply_markup=cancel_markup())
                return

            # ----- مدیریت VIP (صفحه‌بندی‌شده، فقط فعال‌ها) -----
            if data == "admin_vip" or data.startswith("admin_vip_page_"):
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                # تشخیص صفحه
                if data == "admin_vip":
                    page = 1
                else:
                    try:
                        page = int(data.split("_")[-1])
                    except:
                        page = 1

                limit = 20
                offset = (page - 1) * limit
                vips = db.get_active_vips_paginated(offset, limit)
                total = db.count_active_vips()
                total_pages = max(1, (total + limit - 1) // limit)

                lines = [f"👑 *مدیریت VIP* (صفحهٔ {to_persian_digits(page)} از {to_persian_digits(total_pages)})"]
                lines.append(f"فعال: {to_persian_digits(total)} نفر\n")
                if not vips:
                    lines.append("هیچ VIP فعالی وجود ندارد.")
                else:
                    for v in vips:
                        name = v.get('first_name') or "بی‌نام"
                        # تبدیل تاریخ میلادی به شمسی
                        try:
                            g_date = datetime.datetime.strptime(v['expire_date'], "%Y-%m-%d").date()
                            j_date = jdatetime.date.fromgregorian(date=g_date)
                            date_display = to_persian_digits(j_date.strftime("%Y/%m/%d"))
                        except:
                            date_display = to_persian_digits(v['expire_date'])
                        lines.append(f"• {escape_md(name)} (id:{to_persian_digits(v['user_id'])}) — تا {date_display}")

                markup = types.InlineKeyboardMarkup(row_width=2)
                # دکمه‌های ناوبری
                nav = []
                if page > 1:
                    nav.append(types.InlineKeyboardButton("⬅️ قبلی", callback_data=f"admin_vip_page_{page-1}"))
                if page < total_pages:
                    nav.append(types.InlineKeyboardButton("بعدی ➡️", callback_data=f"admin_vip_page_{page+1}"))
                if nav:
                    markup.add(*nav)
                markup.add(types.InlineKeyboardButton("➕ افزودن VIP", callback_data="admin_addvip"))
                markup.add(types.InlineKeyboardButton("🔙 بازگشت به VIP", callback_data="admin_vip_submenu"))
                safe_edit_text("\n".join(lines), chat_id, call.message.message_id, reply_markup=markup)
                bot.answer_callback_query(call.id)
                return
            if data == "admin_addvip":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                clear_user_state(chat_id)
                set_user_state(chat_id, ('admin_addvip',))
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, "فرمت: id days", reply_markup=cancel_markup())
                return

            # ----- مدیریت قیمت‌های VIP (v3.22: ورودی فقط قیمت ماهانه، بقیه خودکار) -----
            if data == "admin_vip_prices":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                lines = ["💵 *قیمت‌های فعلی VIP*\n"]
                m = types.InlineKeyboardMarkup(row_width=1)
                for days, amount in VIP_PRICES.items():
                    lines.append(f"• {vip_plan_label(days)} ({to_persian_digits(days)} روز): {fmt_amount_rial(amount)} ({fmt_amount_toman(amount)})")
                m.add(types.InlineKeyboardButton("✏️ تغییر قیمت‌ها (ورودی: قیمت ماهانه)", callback_data="admin_price_monthly"))
                m.add(types.InlineKeyboardButton("🔙 بازگشت به VIP", callback_data="admin_vip_submenu"))
                safe_edit_text("\n".join(lines), chat_id, call.message.message_id, reply_markup=m)
                bot.answer_callback_query(call.id)
                return

            # v3.22: شروع تغییر قیمت — فقط قیمت ماهانه پرسیده می‌شود
            if data == "admin_price_monthly":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                clear_user_state(chat_id)
                set_user_state(chat_id, ('admin_price_monthly',))
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id,
                    texts.ADMIN_PRICE_MONTHLY_ASK.format(
                        current=fmt_amount_toman(VIP_PRICES.get(30, 0))),
                    reply_markup=cancel_markup())
                return

            # v3.22: تأیید و ذخیرهٔ قیمت‌های محاسبه‌شده (دکمهٔ شیشه‌ای پیش‌نمایش)
            if data == "admin_price_monthly_go":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                st = get_user_state(chat_id)
                if not st or st[0] != 'admin_price_monthly_confirm' or not isinstance(st[1], dict):
                    bot.answer_callback_query(call.id, "⏳ پیش‌نمایشی برای تأیید نیست — دوباره شروع کن.", show_alert=True)
                    return
                computed = st[1]
                clear_user_state(chat_id)
                for d, p in computed.items():
                    VIP_PRICES[d] = p
                    db.set_vip_price(d, p)
                logger.info(f"[ADMIN] VIP prices updated from monthly base: {computed}")
                lines = build_vip_price_lines(computed)
                m = types.InlineKeyboardMarkup(row_width=1)
                m.add(types.InlineKeyboardButton("🔙 بازگشت به VIP", callback_data="admin_vip_submenu"))
                m.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                bot.answer_callback_query(call.id, "✅ ذخیره شد")
                bot.send_message(chat_id, texts.ADMIN_PRICE_SAVED.format(lines=lines), reply_markup=m)
                return

            # ویرایش تکی قیمت (قدیمی — هنوز کار می‌کنه اگر کسی مستقیم بزنه)
            if data.startswith("admin_edit_price_"):
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                days = int(data.split("_")[-1])
                clear_user_state(chat_id)
                set_user_state(chat_id, ('admin_edit_price', days))
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id,
                    f"💵 قیمت جدید برای {to_persian_digits(days)} روزه رو به ریال وارد کنید.\n"
                    f"📌 قیمت فعلی: {to_persian_int(VIP_PRICES.get(days, 0))} ریال",
                    reply_markup=cancel_markup())
                return
            if data == "admin_daily":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                try:
                    expiring_vip_count = len(db.get_expiring_vips(0)) + len(db.get_expiring_vips(1))
                except Exception:
                    expiring_vip_count = 0
                # v3.23: آمار سنگین با کش ۶۰ ثانیه‌ای — پنل روی ۵۰۰۰+ کاربر دیگر دیتابیس را قفل نمی‌کند
                s, s_ts = db.get_daily_stats_cached()

                all_codes = db.get_all_gift_codes()
                active_codes_count = len([c for c in all_codes if c['used_count'] < c['max_uses']])
                broken_list = ', '.join(broken_channels) if broken_channels else 'ندارد'

                # محاسبهٔ کاربران جدید فعال‌شده امروز (کاربرانی که امروز کلیک داده‌اند و ایجادشده امروز هستند)
                # این برای نمایش "کاربران جدیدِ فعال‌شده امروز"
                # ساده‌سازی: تعداد کاربرانی که امروز created_at دارند و در clicks امروز حضور دارند
                # اما چون پیاده‌سازی کامل‌اش سنگین است، همان new_today استفاده می‌کنیم (تقریبی)

                # ۵ تلهٔ برتر امروز (بر اساس فضول — مخفی اگر صفر) — v3.23: با کش
                today = datetime.date.today().isoformat()
                def _q_top_traps_today():
                    try:
                        return db.conn.execute(
                            "SELECT c.owner_id, u.first_name, COUNT(DISTINCT c.clicker_id) as c FROM clicks c "
                            "JOIN users u ON c.owner_id=u.user_id WHERE date(c.clicked_at)=? "
                            "GROUP BY c.owner_id ORDER BY c DESC LIMIT 5", (today,)).fetchall()
                    except Exception:
                        return []
                top_distinct_rows, _tt_ts = db._cached_stat("top_traps_today", 60.0, _q_top_traps_today)
                top_rank_icons = ['🥇', '🥈', '🥉', '🏅', '🎖️']

                # محاسبه آخرین پخش همگانی
                last_bc = db.conn.execute(
                    "SELECT value FROM settings WHERE key='last_broadcast_stats'").fetchone()
                last_bc_str = last_bc['value'] if last_bc else "ندارد"

                # بخش ۵ تلهٔ برتر — فقط اگر حداقل یک فضول امروز ثبت شده باشد
                top_section = ""
                if top_distinct_rows:
                    top_section = (
                        f"🏆 ۵ تلهٔ برتر امروز (بر اساس فضول):\n"
                        + "\n".join(
                            f"{top_rank_icons[i]} {escape_md(crown_name(sanitize_name(r['first_name'] or 'بی‌نام'), db.is_vip(r['owner_id'])))} (id{to_persian_digits(r['owner_id'])}) — {to_persian_digits(r['c'])} فضول"
                            for i, r in enumerate(top_distinct_rows)
                        )
                        + f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    )

                # v3.5: وضعیت چالش (خط شرطی) — v3.18: نام جدید — v4.6: جایزهٔ vip یا پاکت
                _ch_st = get_challenge_status()
                if _ch_st == "scheduled":
                    _ch_prizes = _challenge_prize_dict(db.get_setting_int("challenge_reward_days", 3))
                    challenge_line = (
                        f"🏆 چالش فضول‌گیری: فردا از ساعت ۰۰:۰۰ اجرا می‌شه\n"
                        f" (جوایز: 🥇 {_ch_prizes['first_prize']} | 🥈 {_ch_prizes['second_prize']} | 🥉 {_ch_prizes['third_prize']})\n"
                    )
                elif _ch_st == "active":
                    challenge_line = f"🏆 چالش فضول‌گیری: در جریان — تا پایان شمارش: {_challenge_remaining_str()}\n"
                else:
                    challenge_line = ""

                # ── v3.21: داده‌های جدید داشبورد ──
                joins_today = db.get_channel_joins_today()
                err_count, err_last = ERROR_COUNTER.snapshot()
                if err_count:
                    err_line = f"🧯 مشکلات ربات: {to_persian_digits(err_count)} خطا (آخرین: {escape_md(err_last[:60])})\n"
                else:
                    err_line = "🧯 مشکلات ربات: ندارد ✅\n"
                month_reqs = 0
                try:
                    if _month_requests:
                        month_reqs = _month_requests.current()
                except Exception:
                    month_reqs = 0
                with _requested_lock:
                    requested_total = len(_requested_users)
                try:
                    _top_cb = db.get_callback_stats(limit=1)
                    top_cb_line = ""
                    if _top_cb:
                        top_cb_line = (
                            f"🖱️ پرکلیک‌ترین دکمه: «{_button_display_name(_top_cb[0]['callback_data'])}» "
                            f"({to_persian_int(_top_cb[0]['click_count'])} کلیک)\n"
                        )
                except Exception:
                    top_cb_line = ""
                try:
                    (_st_active, _st_best), _ = db.get_bonus_streak_stats_cached()
                except Exception:
                    _st_active, _st_best = 0, 0

                text = (
                    f"📊 داشبورد ربات فضول‌گیر\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"🎯 شکار و تله‌ها\n"
                    f"🔹 کلیک امروز: {to_persian_digits(s['clicks_today'])} | کل: {to_persian_int(s['total_clicks'])}\n"
                    f"👑 فضول: {to_persian_int(s['distinct_clickers'])} | صاحبان تله: {to_persian_int(s['trap_owners'])}\n"
                    f"📊 میانگین ۷ روز: {to_persian_digits(s['avg_7'])} کلیک/روز\n"
                    + challenge_line
                    + "\n"
                    + top_section
                    + f"🏅 VIP و درآمد\n"
                    f"🔹 فعال: {to_persian_digits(s['active_vip'])} | ⏳ در شرف انقضا: {to_persian_digits(expiring_vip_count)}\n"
                    f"💰 امروز: {fmt_amount_rial(s['revenue_today'])} ({to_persian_digits(s['tx_today'])} تراکنش)\n"
                    f"💰 کل: {fmt_amount_rial(s['total_revenue'])} ({to_persian_digits(s['tx_total'])} تراکنش)\n"
                    f"🔓 پروفایل بازشده: {to_persian_digits(s['reveals_total'])} بار | درآمد: {fmt_amount_rial(s['reveal_revenue'])}\n\n"
                    f"🎁 کد هدیه: ساخته {to_persian_digits(s['gift_created'])} | استفاده {to_persian_digits(s['gift_used'])} | فعال {to_persian_digits(active_codes_count)}\n"
                    f"💬 پیام ناشناس: {to_persian_int(s['anon_total'])}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"⚙️ سیستم و عملکرد\n"
                    f"📢 جوین اجباری: {to_persian_digits(s['channels_count'])} عدد | عضویت: {to_persian_int(s['total_joins'])} | امروز: {to_persian_digits(joins_today)}\n"
                    f"⚠️ مشکل‌دار: {escape_md(broken_list)}\n"
                    f"🛡️ مسدود ادمین: {to_persian_digits(s['total_banned'])} | بلاک‌کردن ربات: {to_persian_digits(s['blocked_bot_count'])}\n"
                    f"⏱️ آپ‌تایم: {uptime_str()}\n"
                    f"📨 درخواست‌های ۲۴ ساعت پیش: {to_persian_digits(get_messages_24h())}\n"
                    f"🗓 درخواست‌های این ماه (شمسی): {to_persian_digits(month_reqs)}\n"
                    + top_cb_line
                    + f"🧑‍💻 کاربران با حداقل یک درخواست: {to_persian_digits(requested_total)} نفر\n"
                    f"📢 آخرین پخش همگانی: {escape_md(last_bc_str)}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"👥 کاربران و رشد\n"
                    f"🔹 کل: {to_persian_int(s['total_users'])}\n"
                    f"🆕 جدید امروز: +{to_persian_digits(s['new_today'])} | دیروز: +{to_persian_digits(s['new_yesterday'])}\n"
                    f"🔹 فعال ۲۴ساعت: {to_persian_digits(s['active_today'])} | نرخ بازگشت: {to_persian_digits(s['return_rate'])}\n"
                    f"✨ جدیدِ فعال‌شدهٔ امروز: {to_persian_digits(s['new_activated_today'])} نفر\n"
                    f"🔥 استریک فعال: {to_persian_digits(_st_active)} نفر | رکورد: {to_persian_digits(_st_best)} روز\n"
                    f"📥 ورود کاربران — بدون پارامتر: {to_persian_int(s['organic'])} | خوش‌آمد: {to_persian_int(s['welcome'])} | تله: {to_persian_int(s['referral'])}\n"
                    + err_line +
                    f"\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔄 بروزرسانی آمار: {shamsi_date(datetime.datetime.fromtimestamp(s_ts, TEHRAN_TZ), with_time=True)} (کش ۶۰ ثانیه‌ای)"
                )

                markup = types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("🔄 بروزرسانی", callback_data="admin_daily"),
                    types.InlineKeyboardButton("📊 آرشیو روزانه", callback_data="admin_daily_archive"),
                    types.InlineKeyboardButton("🌙 گزارش روزانه", callback_data="admin_test_daily_report"),
                    types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")
                )
                safe_edit_text(text, chat_id, call.message.message_id, reply_markup=markup)
                bot.answer_callback_query(call.id)
                return

            # دکمه تست گزارش روزانه (برای ادمین)
            if data == "admin_test_daily_report":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                try:
                    text = build_daily_report_text()
                    bot.send_message(chat_id, text)
                except Exception as e:
                    bot.send_message(chat_id, f"❌ خطا در ساخت گزارش: {e}")
                bot.answer_callback_query(call.id)
                return

            # ----- آرشیو روزانه — کاربران جدید در هر روز (v3.5: نمودار + خلاصه) -----
            if data == "admin_daily_archive" or data.startswith("admin_daily_archive_p"):
                # v3.20: صفحه‌بندی ۳۰ روزه + میانگین کل روزهای شمرده‌شده
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                _page = 0
                if data.startswith("admin_daily_archive_p"):
                    try:
                        _page = max(0, int(data.rsplit("p", 1)[-1]))
                    except Exception:
                        _page = 0
                try:
                    growth_data = db.get_daily_user_growth(days=3650)
                except Exception as e:
                    logger.error("daily archive query error: %s", e)
                    growth_data = []
                if not growth_data:
                    bot.answer_callback_query(call.id, "هنوز داده‌ای موجود نیست.", show_alert=True)
                    return
                bot.answer_callback_query(call.id)
                try:
                    _send_daily_archive(chat_id, call.message.message_id, growth_data, page=_page)
                except Exception as e:
                    logger.error("daily archive error: %s", e)
                    try:
                        bot.send_message(chat_id, "⚠️ خطا در ساخت آرشیو. دوباره تلاش کن.")
                    except Exception:
                        pass
                return

            if data == "admin_broadcast":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                set_broadcast_mode(True, chat_id, None, time.time())
                bot.answer_callback_query(call.id)
                markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("❌ لغو حالت پخش همگانی", callback_data="broadcast_mode_cancel"))
                bot.send_message(chat_id,
                    "📢 *حالت پخش همگانی فعال شد!*\n\n"
                    f"⏳ اگر تا {BROADCAST_TIMEOUT//60} دقیقه دیگر پیامی نفرستید، این حالت خودکار لغو خواهد شد.\n\n"
                    "برای لغو فوری همین حالا، دکمهٔ زیر را بزنید.",
                    reply_markup=markup)
                return

            # ----- حالت تبلیغ: سوپرادمین لینک می‌دهد؛ پیام فضول‌گیری با دکمه‌های تبلیغاتی برای همه می‌رود -----
            if data == "admin_ad_mode":
                if user_id != ADMIN_ID:
                    try: bot.answer_callback_query(call.id, "⛔")
                    except Exception: pass
                    return
                with broadcast_lock:
                    busy = broadcast_mode
                if busy:
                    try: bot.answer_callback_query(call.id, "اول پخش همگانی فعلی را لغو/تأیید کنید.", show_alert=True)
                    except Exception: pass
                    return
                # پاک‌سازی کامل state قبلی (شامل متغیرهای تبلیغ) و ورود به حالت دریافت لینک
                set_broadcast_mode(False)
                set_broadcast_ad_awaiting_link(True)
                set_broadcast_ad_started_at(time.time())
                try: bot.answer_callback_query(call.id)
                except Exception: pass
                ad_prompt = (
                    "📣 *حالت تبلیغ*\n\n"
                    "لینک تبلیغ خود را ارسال کنید — مثلاً:\n"
                    "`https://github.com/TheMeg11/`\n\n"
                    "• لینک باید با `http://` یا `https://` شروع شود\n"
                    "• پیام فضول‌گیری («یه فضول روی لینک شما کلیک کرد!») در همان قالب اصلی برای همه ارسال می‌شود\n"
                    "• تمام دکمه‌های پیام به لینک شما اشاره می‌کنند\n"
                    "• اول یک نمونه برای خودتان ارسال می‌شود تا تأیید کنید\n\n"
                    "برای لغو، «❌ لغو» را بزنید."
                )
                try:
                    bot.send_message(chat_id, ad_prompt,
                        reply_markup=types.ReplyKeyboardMarkup(
                            row_width=1, resize_keyboard=True, one_time_keyboard=False
                        ).add(types.KeyboardButton("❌ لغو")),
                        parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"ad mode prompt error: {e}")
                return

            if data == "admin_support_list":
                # حذف شد — طبق درخواست، دکمه پشتیبانی‌ها از منوی ادمین حذف شده.
                # اما برای backward-compatibility کالبک رو نگه می‌داریم.
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                bot.answer_callback_query(call.id, "این بخش حذف شده است.", show_alert=True)
                return

            # ----- زیرمنوی VIP -----
            if data == "admin_vip_submenu":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                text = (
                    "👑 *مدیریت VIP*\n\n"
                    "یکی از گزینه‌های زیر را انتخاب کنید:\n\n"
                    "💰 تراکنش‌ها — لیست پرداخت‌ها\n"
                    "💵 تغییر قیمت VIP — ویرایش قیمت همه پلن‌ها\n"
                    "📊 آمار VIP — تعداد فعال و منقضی\n"
                    "⚙️ مدیریت VIP — افزودن VIP دستی و لیست VIPها"
                )
                safe_edit_text(text, chat_id, call.message.message_id, reply_markup=admin_vip_submenu_markup())
                bot.answer_callback_query(call.id)
                return

            # ----- اد اجباری -----
            if data == "admin_forced_ads":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                channels = db.get_all_forced_channels()
                lines = ["📢 *مدیریت کانال‌های اجباری*"]
                markup = types.InlineKeyboardMarkup(row_width=1)
                if channels:
                    for ch in channels:
                        ch_id = ch['channel_id']
                        ch_name = channel_info.get(ch_id, {}).get("name", ch_id)
                        count = db.get_channel_join_count(ch_id)
                        # v3.21: نمایش هدف جذب (۰ = بدون محدودیت)
                        tgt = (ch.get('target', 0) or 0) if hasattr(ch, 'get') else 0
                        if tgt > 0:
                            pct = int(count * 100 / tgt) if tgt else 0
                            pct = min(100, max(0, pct))
                            tgt_txt = "%s/%s عضو (%s٪)" % (
                                to_persian_digits(count), to_persian_digits(tgt), to_persian_digits(pct))
                        else:
                            tgt_txt = "%s عضو (بدون محدودیت)" % to_persian_digits(count)
                        lines.append(f"• {ch_name} — {tgt_txt}")
                        markup.add(types.InlineKeyboardButton(f"❌ حذف {ch_name}", callback_data=f"admin_remove_channel_{ch_id}"))
                else:
                    lines.append("هیچ کانالی تعریف نشده است.")
                markup.add(types.InlineKeyboardButton("➕ افزودن کانال", callback_data="admin_add_channel"))
                markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel"))
                safe_edit_text("\n".join(lines), chat_id, call.message.message_id, reply_markup=markup)
                bot.answer_callback_query(call.id)
                return

            if data == "admin_add_channel":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                clear_user_state(chat_id)
                set_user_state(chat_id, ('admin_new_channel',))
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, "شناسه کانال (مثلاً @username یا شناسه عددی) را بفرستید:", reply_markup=cancel_markup())
                return

            # ----- حذف کانال (اصلاح‌شده با ادامهٔ حلقه) -----
            if data.startswith("admin_remove_channel_"):
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                ch_id = data[len("admin_remove_channel_"):]
                db.remove_forced_channel(ch_id)
                if ch_id in CHANNELS:
                    CHANNELS.remove(ch_id)
                channel_info.pop(ch_id, None)
                broken_channels.discard(ch_id)            # <-- این خط اضافه شود
                bot.answer_callback_query(call.id, "✅ کانال حذف شد.")
                data = "admin_forced_ads"
                continue

            # ----- پخش همگانی -----
            # broadcast_confirm و broadcast_cancel حذف شدند — با کیبورد معمولی هندل می‌شن
            if data == "broadcast_mode_cancel":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                set_broadcast_mode(False)
                bot.answer_callback_query(call.id, "لغو شد.")
                safe_edit_text("❌ حالت پخش همگانی لغو شد.", chat_id, call.message.message_id, reply_markup=admin_panel_back_markup())
                return

            if data == "broadcast_stop":
                if user_id != ADMIN_ID:
                    try: bot.answer_callback_query(call.id, "⛔")
                    except Exception: pass
                    return
                broadcast_stop_flag.set()
                # مقاوم‌سازی: callback منقضی/تکراری نباید جریان توقف را بشکند
                try: bot.answer_callback_query(call.id, "⏹️ درخواست توقف ارسال شد. چند ثانیه طول می‌کشد...")
                except Exception: pass
                return

            # ----- تأیید ارسال به همه (از روی پیام پیش‌نمایش) -----
            if data == "broadcast_confirm_send_all":
                if user_id != ADMIN_ID:
                    try: bot.answer_callback_query(call.id, "⛔")
                    except Exception: pass
                    return
                # چک اینکه پیام پیش‌نمایش هنوز معتبره
                preview_msg = None
                current_markup = None
                bc_parse_mode = None
                with broadcast_lock:
                    if not broadcast_mode or not broadcast_preview_msg:
                        try: bot.answer_callback_query(call.id, "❌ حالت پخش همگانی فعال نیست.", show_alert=True)
                        except Exception: pass
                        return
                    preview_msg = broadcast_preview_msg
                    current_markup = broadcast_inline_markup
                    bc_parse_mode = broadcast_parse_mode

                # شروع ارسال
                set_broadcast_mode(False, None, preview_msg, None)

                # حذف کیبورد معمولی
                try:
                    bot.send_message(chat_id, "🚀 شروع ارسال همگانی...", reply_markup=types.ReplyKeyboardRemove())
                except Exception:
                    pass

                # جلوگیری از کلیک دوبار روی دکمه (القاء loading روی callback)
                # مقاوم‌سازی: callback منقضی/تکراری نباید استارت thread پخش را بشکند —
                # (بدون این try/except، خطای ۴۰۰ قبل از Thread.start() جریان را سایلنت خراب می‌کند)
                try:
                    bot.answer_callback_query(call.id, "🚀 شروع ارسال...")
                except Exception:
                    pass

                # شروع ارسال در thread جداگانه با نمونه مستقل TeleBot
                # (bc_parse_mode: فقط حالت تبلیغ Markdown است — قبل از پاک‌شدن state گرفته شد)
                threading.Thread(
                    target=_run_broadcast_async,
                    args=(chat_id, preview_msg, current_markup, bc_parse_mode),
                    daemon=True
                ).start()
                return

            # ----- v3.23: ادامه/لغو پخش همگانی نیمه‌کاره (بعد از ری‌استارت) -----
            if data == "bc_resume_go":
                if user_id != ADMIN_ID:
                    try: bot.answer_callback_query(call.id, "⛔")
                    except Exception: pass
                    return
                st = _bc_state_read()
                if not st:
                    try: bot.answer_callback_query(call.id, "پخش نیمه‌کاره‌ای برای ادامه نیست.")
                    except Exception: pass
                    return
                # مقاوم‌سازی: callback منقضی نباید استارت resume را بشکند
                try: bot.answer_callback_query(call.id, "▶️ ادامهٔ پخش از محل قطع...")
                except Exception: pass
                try:
                    bot.edit_message_text("▶️ ادامهٔ پخش همگانی آغاز شد...", chat_id, call.message.message_id)
                except Exception:
                    pass
                threading.Thread(target=_run_broadcast_async, args=(ADMIN_ID, None, st), daemon=True).start()
                return
            if data == "bc_resume_cancel":
                if user_id != ADMIN_ID:
                    try: bot.answer_callback_query(call.id, "⛔")
                    except Exception: pass
                    return
                _bc_state_clear()
                try: bot.answer_callback_query(call.id, "لغو شد.")
                except Exception: pass
                try:
                    bot.edit_message_text("🗑 پخش نیمه‌کاره لغو شد.", chat_id, call.message.message_id)
                except Exception:
                    pass
                return

            # ----- دکمه‌های عمومی -----
            if data == "my_link_show":
                clear_user_state(chat_id)
                link = user_link(user_id)
                samples = [
                    f"[جرات داری روم کلیک کن 👁️]({link})",
                    f"[میخوای آشنا شیم؟ 🤭]({link})",
                ]
                text = (
                    f"🔍 *تلهٔ اختصاصی تو:*\n{link}\n\n"
                    f"🎭 این لینک خام رو که نمی‌تونی توی بیو بذاری...\n"
                    f"باید پشت یه متن قایمش کنی — این میشه *هایپرلینک*.\n"
                    f"یه جملهٔ جذاب که هرکی روش بزنه، مستقیم می‌افته توی دامت.\n\n"
                    f"📋 چند نمونهٔ آماده با کد خودت:\n"
                    f"1. {samples[0]}\n"
                    f"2. {samples[1]}\n\n"
                    f"💡 هرکدوم رو دوست داشتی *کپی* کن و بچسبون توی بیوگرافیت.\n"
                    f"یا خودت یه متن دلخواه بساز..."
                )
                markup = types.InlineKeyboardMarkup(row_width=2)
                # v3.17: کپی مستقیم لینک خام — تمام‌عرض، اول از همه
                btn_raw = types.InlineKeyboardButton("🔗 کپی لینک خام", callback_data="copy_raw_link",
                                                     copy_text=types.CopyTextButton(link))
                markup.add(btn_raw)
                btn1 = types.InlineKeyboardButton("📋 کپی 1", callback_data=f"copy_sample_1", copy_text=types.CopyTextButton(samples[0]))
                btn2 = types.InlineKeyboardButton("📋 کپی 2", callback_data=f"copy_sample_2", copy_text=types.CopyTextButton(samples[1]))
                markup.add(btn1, btn2)
                markup.add(types.InlineKeyboardButton("✍️ ساخت هایپرلینک با متن دلخواه", callback_data="get_hyperlink"))
                markup.add(types.InlineKeyboardButton("📊 آنالیز تله", callback_data="trap_analytics"),
                           types.InlineKeyboardButton("🕳️ تله‌های من", callback_data="my_traps"))
                markup.add(types.InlineKeyboardButton("🎬 نحوه قرار دادن لینک", callback_data="help_link_tutorial"))
                markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))

                if call.message.content_type == 'photo':
                    try:
                        bot.delete_message(chat_id, call.message.message_id)
                    except:
                        pass
                    bot.send_message(chat_id, text, reply_markup=markup)
                else:
                    safe_edit_text(text, chat_id, call.message.message_id, reply_markup=markup)
                bot.answer_callback_query(call.id)
                return

            if data == "get_hyperlink":
                clear_user_state(chat_id)
                set_user_state(chat_id, ('link_text',))
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, "✍️ متنی که میخوای هایپرلینک شه رو وارد کن:", reply_markup=cancel_markup())
                return

            # ----- اطلاعات من + آمار من -----
            if data == "my_info":
                clear_user_state(chat_id)
                # ابتدا چک کن تسک‌های تازه تکمیل‌شده رو (برای به‌روزرسانی سطح و XP)
                # نکته: _check_and_award_tasks_xp فقط در tasks page صدا زده می‌شه (نه در my_info)

                u = call.from_user
                total_clicks = db.get_clicks_count(user_id)
                snoop_count = db.get_distinct_snoop_count(user_id)
                # v3.17: فضول امروز — فقط کاربران جدیدِ امروز (نه کل کلیک‌ها)
                today_fools = db.get_today_new_snoop_count(user_id)
                is_active_vip, vip_status_str = vip_status_display(user_id)
                emoji = get_user_rank_emoji(user_id)
                level = db.get_user_level_cached(user_id)
                xp = db.get_user_xp(user_id)
                title, _ = get_rank_tier(level)
                xp_next = db.xp_for_next_level(level)

                # محاسبه progress bar برای سطح
                # نکته: سطح ۱ از XP=0 شروع می‌شود، سطح L≥2 از xp_for_level(L)
                # v3.17: سقف سطح از ۵۰ به ۱۰۰ (config.MAX_LEVEL)
                if xp_next:
                    if level == 1:
                        xp_this_level_start = 0
                    else:
                        xp_this_level_start = db.xp_for_level(level)
                    xp_in_level = xp - xp_this_level_start
                    xp_needed_this_level = xp_next - xp_this_level_start
                    progress_pct = int(xp_in_level * 100 / xp_needed_this_level) if xp_needed_this_level > 0 else 0
                    progress_pct = max(0, min(100, progress_pct))
                    bar_len = 10
                    filled = int(progress_pct * bar_len / 100)
                    level_bar = '█' * filled + '░' * (bar_len - filled)
                    xp_to_next = xp_next - xp
                    level_section = (
                        f"📊 سطح: {to_persian_digits(level)} — {emoji} {title}\n"
                        f"✨ {to_persian_int(xp)} از {to_persian_int(xp_next)} دریافت شده\n"
                        f"{level_bar} {to_persian_digits(progress_pct)}٪\n"
                        f"🎯 تا سطح بعد: {to_persian_int(xp_to_next)} XP"
                    )
                else:
                    level_section = (
                        f"📊 سطح: {to_persian_digits(level)} — {emoji} {title}\n"
                        f"✨ XP: {to_persian_int(xp)}\n"
                        f"🏆 به حداکثر سطح رسیده‌اید!"
                    )

                display_name = f"{emoji} {escape_md(u.first_name or 'بی‌نام')}" if emoji else escape_md(u.first_name or 'بی‌نام')

                # قالب جدید بدون باکس/جعبه — سبک و خوانا
                text = (
                    f"📋 *اطلاعات من*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"👤 {display_name}\n"
                    f"🆔 {to_persian_digits(user_id)}\n"
                    f"📎 @{u.username or 'ندارد'}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📈 *آمار*\n"
                    f"👑 فضول: {to_persian_int(snoop_count)}\n"
                    f"🖱️ کلیک: {to_persian_int(total_clicks)}\n"
                    f"🆕 فضول امروز: {to_persian_int(today_fools)} نفر\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 *پیشرفت*\n"
                    f"{level_section}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🏅 *اشتراک*\n"
                    f"وضعیت VIP: {vip_status_str}\n\n"
                    f"🔗 *تلهٔ شما*\n"
                    f"{user_link(user_id)}\n"
                )

                # بخش آخرین فعالیت‌ها
                activities = db.get_recent_activities(user_id, limit=4)
                if activities:
                    text += f"\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    text += f"🕐 *آخرین فعالیت‌ها*\n"
                    for act in activities:
                        try:
                            ts = act.get('timestamp', '')
                            if ts:
                                # تبدیل به تاریخ شمسی
                                try:
                                    g_date = datetime.datetime.strptime(ts[:10], "%Y-%m-%d").date()
                                    j_date = jdatetime.date.fromgregorian(date=g_date)
                                    time_str = to_persian_digits(j_date.strftime("%Y/%m/%d"))
                                except:
                                    time_str = to_persian_digits(ts[:10])
                            else:
                                time_str = 'نامشخص'
                        except:
                            time_str = 'نامشخص'

                        if act['type'] == 'click':
                            name = escape_md(act.get('name', 'ناشناس'))
                            text += f"• {time_str}: {name} تله‌ات رو کلیک کرد\n"
                        elif act['type'] == 'vip':
                            days = to_persian_digits(act.get('days', 0))
                            text += f"• {time_str}: VIP خریدی ({days} روز)\n"
                        elif act['type'] == 'gift':
                            days = to_persian_digits(act.get('days', 0))
                            text += f"• {time_str}: VIP هدیه دادی ({days} روز)\n"
                        elif act['type'] == 'task':
                            task_name = escape_md(act.get('task_name', 'ماموریت'))
                            text += f"• {time_str}: ماموریت «{task_name}» رو تکمیل کردی\n"

                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(types.InlineKeyboardButton("🎯 ماموریت‌ها", callback_data="tasks_page_1"),
                           types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                bot.answer_callback_query(call.id)
                if call.message.content_type == 'photo':
                    try:
                        bot.delete_message(chat_id, call.message.message_id)
                    except:
                        pass
                    bot.send_message(chat_id, text, reply_markup=markup)
                else:
                    safe_edit_text(text, chat_id, call.message.message_id, reply_markup=markup)
                return

            if data == "my_stats":
                today_clicks = db.get_today_clicks_count(user_id)
                top_snoops = db.get_snoops(user_id)[:3]
                lines = ["📊 *آمار شکارچی*\n"]
                lines.append(f"🖱️ کلیک امروز: {today_clicks}")
                if top_snoops:
                    lines.append("\n🕵️ *۳ فضول برتر:*")
                    for i, s in enumerate(top_snoops):
                        name = s.get('nickname') or s['name']
                        lines.append(f"{i+1}. {escape_md(name)} – {s['count']} بار")
                else:
                    lines.append("\n🕵️ هنوز هیچ فضولی ثبت نشده.")
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(types.InlineKeyboardButton("🔙 اطلاعات من", callback_data="my_info"))
                markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                bot.answer_callback_query(call.id)
                if call.message.content_type == 'photo':
                    try:
                        bot.delete_message(chat_id, call.message.message_id)
                    except:
                        pass
                    bot.send_message(chat_id, "\n".join(lines), reply_markup=markup)
                else:
                    safe_edit_text("\n".join(lines), chat_id, call.message.message_id, reply_markup=markup)
                return

            # ====== ماموریت‌ها ======
            if data.startswith("tasks_page_"):
                page = int(data.split("_")[-1])
                # loading toast برای پردازش ۲۰۰ تسک
                try:
                    bot.answer_callback_query(call.id, "⏳ در حال بارگذاری...")
                except: pass
                show_tasks_page(chat_id, user_id, page, call)
                return

            if data.startswith("task_detail_"):
                task_id = data[len("task_detail_"):]
                show_task_detail_popup(call, user_id, task_id)
                return

            if data == "achievements" or data == "my_progress":
                # نمایش پیشرفت سطح کاربر (جایگزین تالار افتخارات حذف‌شده)
                level = db.get_user_level_cached(user_id)
                xp = db.get_user_xp(user_id)
                xp_next = db.xp_for_next_level(level)
                title, emoji = get_rank_tier(level)
                # محاسبهٔ XP لازم برای این سطح و سطح بعدی
                xp_this_level_start = db.xp_for_level(level - 1) if level > 1 else 0
                xp_in_level = xp - xp_this_level_start
                xp_needed_this_level = (100 * level) if level < config.MAX_LEVEL else 0
                # v3.17: سطح نام‌دار بعدی
                next_named = get_next_named_level(level)
                lines = [f"📈 *پیشرفت کارآگاهی شما*\n"]
                lines.append(f"{emoji} *رتبه:* {title}")
                lines.append(f"📊 *سطح:* {to_persian_digits(level)} از {to_persian_digits(config.MAX_LEVEL)}")
                lines.append(f"✨ *XP کل:* {to_persian_int(xp)}")
                if xp_next:
                    lines.append(f"🎯 XP تا سطح بعد: {to_persian_int(xp_next - xp)}")
                else:
                    lines.append("🏆 به حداکثر سطح رسیده‌اید!")
                if xp_needed_this_level and level < config.MAX_LEVEL:
                    progress_pct = int(xp_in_level * 100 / xp_needed_this_level) if xp_needed_this_level else 0
                    progress_pct = max(0, min(100, progress_pct))
                    bar_len = 10
                    filled = int(progress_pct / 10)
                    bar = '█' * filled + '░' * (bar_len - filled)
                    lines.append(f"\n{bar} {to_persian_digits(progress_pct)}٪")
                if next_named:
                    nt_title, nt_emoji = texts.LEVEL_NAMES[next_named]
                    levels_to_next = next_named - level
                    lines.append(f"\n🔮 رتبهٔ بعد: {nt_emoji} {nt_title}")
                    lines.append(f"📋 {to_persian_digits(levels_to_next)} سطح تا رتبهٔ بعدی")
                lines.append("\n💡 *راه‌های کسب XP:*")
                lines.append(f"👑 هر فضول جدید: +{to_persian_digits(XP_RECURRING['new_distinct_snoop'])}")
                lines.append(f"🕸️ هر تله‌گذاری موفق (عضو شدن کسی از لینکت): +{to_persian_digits(XP_RECURRING['successful_invite'])}")
                lines.append(f"📅 ورود روزانه: +{to_persian_digits(XP_RECURRING['daily_login'])}")
                lines.append(f"👑 خرید اشتراک ویژه: +{to_persian_digits(XP_RECURRING['buy_vip'])}")
                lines.append(f"🎁 هدیه اشتراک ویژه: +{to_persian_digits(XP_RECURRING['gift_vip'])}")
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(types.InlineKeyboardButton("🔙 اطلاعات من", callback_data="my_info"))
                markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                bot.answer_callback_query(call.id)
                if call.message.content_type == 'photo':
                    try:
                        bot.delete_message(chat_id, call.message.message_id)
                    except:
                        pass
                    bot.send_message(chat_id, "\n".join(lines), reply_markup=markup)
                else:
                    safe_edit_text("\n".join(lines), chat_id, call.message.message_id, reply_markup=markup)
                return

            # ----- لیست فضول‌ها -----
            if data.startswith("snooplist_page_"):
                page = int(data.split("_")[-1])
                clear_user_state(chat_id)
                if call.message.content_type == 'photo':
                    try:
                        bot.delete_message(chat_id, call.message.message_id)
                    except:
                        pass
                    show_snoop_list(chat_id, page)
                else:
                    show_snoop_list(chat_id, page, message_id=call.message.message_id)
                bot.answer_callback_query(call.id)
                return

            if data.startswith("snoopdetail_"):
                cid = int(data.split("_")[1])
                snoops = db.get_snoops(user_id)
                info = next((s for s in snoops if s['clicker_id'] == cid), None)
                if not info:
                    bot.answer_callback_query(call.id, "خطا!")
                    return
                vip = db.is_vip(user_id)
                name_disp = info.get('nickname') or info['name']
                # v4.4 حریم خصوصی: کاربر عادی هیچ اطلاعاتی از فضول نمی‌بیند — فقط نام (ماسک‌شده)
                if vip:
                    detail = f"👤 {escape_md(name_disp)}\n🔢 {info['count']} بار\n🆔 {fmt_id(cid, vip, owner_id=user_id)}\n📎 {fmt_uname(info.get('username'), vip, owner_id=user_id, uid=cid)}"
                else:
                    detail = f"👤 {escape_md(name_disp)}"
                if not vip:
                    detail += "\n\n" + texts.REVEAL_TEASE
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(
                    types.InlineKeyboardButton("✉️ پیام ناشناس", callback_data=f"anon_{cid}"),
                    types.InlineKeyboardButton("🏷️ لقب", callback_data=f"nick_{cid}"),
                    types.InlineKeyboardButton("🎁 هدیه VIP", callback_data=f"giftvip_{cid}"),
                    types.InlineKeyboardButton("🔙 لیست", callback_data="snooplist_page_1"))
                if not vip and not db.is_revealed(user_id, cid):
                    price_toman = db.get_setting_int("reveal_price", 30000) // 10
                    markup.add(types.InlineKeyboardButton(f"🔓 باز کردن هویت ({to_persian_digits(price_toman)} تومان)", callback_data=f"reveal_buy_{cid}"))
                if db.is_snoop_muted(user_id, cid):
                    markup.add(types.InlineKeyboardButton("🔔 با صدا", callback_data=f"unmute_{cid}"))
                else:
                    markup.add(types.InlineKeyboardButton("🔕 بی‌صدا", callback_data=f"mute_{cid}"))
                markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                bot.answer_callback_query(call.id)
                if call.message.content_type == 'photo':
                    try:
                        bot.delete_message(chat_id, call.message.message_id)
                    except:
                        pass
                    bot.send_message(chat_id, detail, reply_markup=markup)
                else:
                    safe_edit_text(detail, chat_id, call.message.message_id, reply_markup=markup)
                return

            if data.startswith("nick_"):
                cid = int(data.split("_")[1])
                clear_user_state(chat_id)
                set_user_state(chat_id, ('nickname', cid))
                bot.answer_callback_query(call.id)
                if call.message.content_type == 'photo':
                    try:
                        bot.delete_message(chat_id, call.message.message_id)
                    except:
                        pass
                    bot.send_message(chat_id, "🏷️ لقب:", reply_markup=cancel_markup())
                else:
                    safe_edit_text("🏷️ لقب:", chat_id, call.message.message_id, reply_markup=cancel_markup())
                return

            if data.startswith("anon_") and not data.startswith("anon_reply_"):
                # v4.4: پیام ناشناس فقط برای VIP — درخواست کاربر ادمین
                _vg = anon_vip_gate(user_id)
                if _vg:
                    bot.answer_callback_query(call.id, "✉️ فقط VIP!", show_alert=True)
                    try:
                        bot.send_message(chat_id, _vg[0], reply_markup=_vg[1])
                    except Exception:
                        pass
                    return
                cid = int(data.split("_")[1])
                clear_user_state(chat_id)
                set_user_state(chat_id, ('anon_msg', cid))
                bot.answer_callback_query(call.id)
                if call.message.content_type == 'photo':
                    try:
                        bot.delete_message(chat_id, call.message.message_id)
                    except:
                        pass
                    bot.send_message(chat_id, "✉️ پیام ناشناس:", reply_markup=cancel_markup())
                else:
                    safe_edit_text("✉️ پیام ناشناس:", chat_id, call.message.message_id, reply_markup=cancel_markup())
                return

            if data.startswith("giftvip_"):
                target_id = int(data.split("_")[1])
                markup = types.InlineKeyboardMarkup(row_width=1)
                for days, amount in VIP_PRICES.items():
                    markup.add(types.InlineKeyboardButton(f"🎁 {vip_plan_label(days)} ({to_persian_digits(days)} روز) – {fmt_amount_toman(amount)}", callback_data=f"confirmgift_{target_id}_{days}"))
                markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"snoopdetail_{target_id}"))
                markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                bot.answer_callback_query(call.id)
                if call.message.content_type == 'photo':
                    try:
                        bot.delete_message(chat_id, call.message.message_id)
                    except:
                        pass
                    bot.send_message(chat_id, f"🎁 *هدیه VIP*", reply_markup=markup)
                else:
                    safe_edit_text(f"🎁 *هدیه VIP*", chat_id, call.message.message_id, reply_markup=markup)
                return

            # ── v4.4: مرحلهٔ «حفظ آبرو» — ارسال فاکتور پرداخت (۳ دقیقه فرصت) ──
            if data.startswith("trapdec_save_"):
                try:
                    dec_id = int(data.split("_")[2])
                except (ValueError, IndexError):
                    bot.answer_callback_query(call.id, "درخواست نامعتبر است.", show_alert=True)
                    return
                dec = db.get_trap_decision(dec_id)
                # ضد فورج کال‌بک: فقط بازدیدکنندهٔ خودِ تصمیم می‌تواند بزند
                if not dec or dec['visitor_id'] != user_id:
                    bot.answer_callback_query(call.id, "⛔ این تصمیم مال تو نیست.", show_alert=True)
                    return
                if dec['status'] == 'pending':
                    # رزرو وضعیت به‌صورت اتمیک — اگر تایمر همین لحظه لو داده باشد، رد می‌شود
                    if not db.set_trap_decision_status(dec_id, 'saveface', deadline=time.time() + TRAP_SAVEFACE_SECONDS):
                        bot.answer_callback_query(call.id, "⌛ این فرصت تمام شده است!", show_alert=True)
                        return
                elif dec['status'] != 'saveface':
                    bot.answer_callback_query(call.id, "⌛ این فرصت تمام شده است!", show_alert=True)
                    return
                price_rial = _saveface_price_rial()
                payload = f"saveface_{user_id}_{dec_id}_{int(time.time())}"
                try:
                    bot.send_invoice(chat_id,
                        title="🤫 حفظ آبرو",
                        description="هویتت هرگز به صاحب لینک فاش نمی‌شود — گزارش فضول‌گیری ارسال نمی‌شود",
                        invoice_payload=payload, provider_token=PROVIDER_TOKEN, currency="IRT",
                        prices=[types.LabeledPrice(label="حفظ آبرو", amount=price_rial)],
                        need_name=False, need_phone_number=False, need_email=False, is_flexible=False)
                    bot.answer_callback_query(call.id, "🧾 فاکتور ارسال شد — ۳ دقیقه فرصت داری!")
                    try:
                        bot.send_message(chat_id, texts.TRAP_PAY_REQUEST)
                    except Exception:
                        pass
                except Exception as e:
                    logger.error(f"saveface invoice error (dec={dec_id}): {e}")
                    # درگاه در دسترس نیست — راه فرار نیست: تایمر ۳ دقیقه‌ای همچنان فعال است
                    bot.answer_callback_query(call.id,
                        "❌ درگاه پرداخت در دسترس نیست! تا ۳ دقیقه فرصت داری دوباره تلاش کنی؛ وگرنه لو می‌روی.",
                        show_alert=True)
                return

            # ── v4.4: «لو برو» — گزارش فوراً برای صاحب لینک ارسال می‌شود ──
            if data.startswith("trapdec_expose_"):
                try:
                    dec_id = int(data.split("_")[2])
                except (ValueError, IndexError):
                    bot.answer_callback_query(call.id, "درخواست نامعتبر است.", show_alert=True)
                    return
                dec = db.get_trap_decision(dec_id)
                if not dec or dec['visitor_id'] != user_id:
                    bot.answer_callback_query(call.id, "⛔ این تصمیم مال تو نیست.", show_alert=True)
                    return
                # اتمیک: فقط یک بار نهایی می‌شود (دوبار فشردن یا مسابقه با تایمر امن است)
                if not db.set_trap_decision_status(dec_id, 'exposed'):
                    bot.answer_callback_query(call.id, "این تصمیم قبلاً نهایی شده است.", show_alert=True)
                    return
                bot.answer_callback_query(call.id, "💀 گزارش ارسال شد.")
                _trap_expose_visitor(dec, reason="expose")
                return

            if data.startswith("reveal_buy_"):
                cid = int(data.split("_")[2])
                if db.is_vip(user_id):
                    bot.answer_callback_query(call.id, "🏅 تو VIP هستی — هویت برایت رایگان است!", show_alert=True)
                    return
                if db.is_revealed(user_id, cid):
                    bot.answer_callback_query(call.id, "✅ این هویت قبلاً باز شده — از «اطلاعات فضول» ببین.", show_alert=True)
                    return
                # v3.22 امنیتی: فقط فضولِ تلهٔ خودت قابل بازکردن است — ضد فورج کال‌بک
                _rv_snoops = db.get_snoops(user_id)
                if not any(s['clicker_id'] == cid for s in _rv_snoops):
                    bot.answer_callback_query(call.id, "⛔ این کاربر فضول تلهٔ تو نیست.", show_alert=True)
                    return
                price_rial = db.get_setting_int("reveal_price", 30000)
                payload = f"reveal_{user_id}_{cid}"
                try:
                    bot.send_invoice(chat_id,
                        title="🔓 باز کردن هویت فضول",
                        description="مشاهدهٔ شناسه و آیدی کامل این فضول — برای همیشه",
                        invoice_payload=payload, provider_token=PROVIDER_TOKEN, currency="IRT",
                        prices=[types.LabeledPrice(label="باز کردن هویت", amount=price_rial)],
                        need_name=False, need_phone_number=False, need_email=False, is_flexible=False)
                    bot.answer_callback_query(call.id, "فاکتور ارسال شد.")
                except Exception as e:
                    logger.error(f"Reveal invoice error: {e}")
                    bot.answer_callback_query(call.id, "❌ خطا در ایجاد فاکتور.", show_alert=True)
                return

            if data.startswith("confirmgift_"):
                parts = data.split("_")
                target_id = int(parts[1])
                days = int(parts[2])
                # رفع باگ: بررسی اعتبار پلن قبل از ارسال فاکتور
                amount = VIP_PRICES.get(days)
                if amount is None:
                    bot.answer_callback_query(call.id, "❌ طرح انتخابی نامعتبر است.", show_alert=True)
                    return
                payload = f"giftvip_{user_id}_{target_id}_{days}_{int(time.time())}"
                try:
                    bot.send_invoice(chat_id, title="🎁 هدیه VIP", description=f"هدیهٔ کارت طلایی {vip_plan_label(days)} ({to_persian_digits(days)} روز) برای کاربر دیگر",
                                     invoice_payload=payload, provider_token=PROVIDER_TOKEN, currency="IRT",
                                     prices=[types.LabeledPrice(label=f"کارت طلایی {vip_plan_label(days)}", amount=amount)],
                                     need_name=False, need_phone_number=False, need_email=False, is_flexible=False)
                    bot.answer_callback_query(call.id, "فاکتور هدیه ارسال شد.")
                except Exception as e:
                    logger.error(f"Gift invoice error: {e}")
                    bot.answer_callback_query(call.id, "❌ خطا در ایجاد فاکتور.", show_alert=True)
                return

            if data == "support":
                clear_user_state(chat_id)
                add_support_session(chat_id)
                markup = types.InlineKeyboardMarkup(row_width=1)
                # v4.7 (بخش ارتباط): دکمهٔ کانال اطلاع‌رسانی @fzxinfo — هدایت مستقیم به کانال
                markup.add(types.InlineKeyboardButton("📢 کانال اطلاع‌رسانی", url="https://ble.ir/fzxinfo"))
                markup.add(types.InlineKeyboardButton("خروج از پشتیبانی", callback_data="support_exit"))
                markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, "📞 پیامت رو بنویس...", reply_markup=markup)
                return

            # ----- v3.7: منوی «کارت طلایی» VIP (ظاهر لوکس، متمایز از منوی عادی) -----
            if data == "vip_info":
                clear_user_state(chat_id)
                gold_text, gold_markup, gold_active = build_vip_gold_menu(user_id)
                # همیشه پیام قبلی رو پاک کن و پیام جدید بفرست (مثل لیدربورد)
                # چون اگه پیام قبلی عکس داشته باشه، edit_text خراب می‌شه
                try:
                    bot.delete_message(chat_id, call.message.message_id)
                except: pass
                if VIP_MAIN_PHOTO_ID:
                    try:
                        bot.send_photo(chat_id, VIP_MAIN_PHOTO_ID, caption=gold_text, reply_markup=gold_markup)
                    except:
                        bot.send_message(chat_id, gold_text, reply_markup=gold_markup)
                else:
                    bot.send_message(chat_id, gold_text, reply_markup=gold_markup)
                if gold_active:
                    bot.answer_callback_query(call.id, "👑 درود، کارآگاه ویژه!")
                else:
                    bot.answer_callback_query(call.id)
                return

            # v3.7: دکمهٔ شیشه‌ای VIP — نمایش روز و ساعت باقی‌مانده
            if data == "vip_time_left":
                if not db.is_vip(user_id):
                    bot.answer_callback_query(call.id, "⛔ کارت طلایی فعال نداری.", show_alert=True)
                    return
                days = db.get_vip_days_left(user_id)
                now = datetime.datetime.now(TEHRAN_TZ)
                nxt = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                hours = max(0, int((nxt - now).total_seconds() // 3600))
                if hours == 0:
                    minutes = max(1, int((nxt - now).total_seconds() // 60))
                    msg = f"شما تا {to_persian_digits(minutes)} دقیقه دیگر کاربر VIP ربات هستید 🙇"
                elif days > 0:
                    msg = f"شما تا {to_persian_digits(days)} روز و {to_persian_digits(hours)} ساعت دیگر کاربر VIP ربات هستید 🙇"
                else:
                    msg = f"شما تا {to_persian_digits(hours)} ساعت دیگر کاربر VIP ربات هستید 🙇"
                bot.answer_callback_query(call.id, msg, show_alert=True)
                return

            # منوی قابلیت‌های VIP (هم‌تم با کارت طلایی)
            if data == "vip_features":
                clear_user_state(chat_id)
                m = types.InlineKeyboardMarkup(row_width=1)
                m.add(types.InlineKeyboardButton("📝 متن خوش‌آمدگویی", callback_data="set_welcome"))
                m.add(types.InlineKeyboardButton("🖼️ عکس خوش‌آمدگویی", callback_data="set_welcome_photo"))
                m.add(types.InlineKeyboardButton("🎭 نقاب کارآگاهی", callback_data="set_mask"))
                m.add(types.InlineKeyboardButton("📜 پیش‌نمایش پیام خوش‌آمد", callback_data="preview_welcome"))
                m.add(types.InlineKeyboardButton("🎰 چرخ شانس روزانه", callback_data="wheel_info"))
                m.add(types.InlineKeyboardButton("📊 آنالیز حرفه‌ای تله", callback_data="trap_analytics"))
                m.add(types.InlineKeyboardButton("🕳️ تله‌های چندگانه", callback_data="my_traps"))
                m.add(types.InlineKeyboardButton("🎁 هدیه‌دادن روزهای VIP", callback_data="gvip_menu"))
                m.add(types.InlineKeyboardButton("👑 بازگشت به کارت طلایی", callback_data="vip_info"))
                m.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                # delete+resend چون پیام قبلی ممکن است عکس‌دار باشد
                try:
                    bot.delete_message(chat_id, call.message.message_id)
                except: pass
                bot.send_message(chat_id,
                    "✨ ━━━━━━━━━━━━━━ ✨\n"
                    "🛠 *کارگاه کارآگاه ویژه*\n"
                    "✨ ━━━━━━━━━━━━━━ ✨\n\n"
                    "ابزارهای اختصاصی کارت طلایی را اینجا تنظیم کن:",
                    reply_markup=m)
                bot.answer_callback_query(call.id)
                return

            if data == "buy_vip_menu":
                m = types.InlineKeyboardMarkup(row_width=1)
                for days, amount in VIP_PRICES.items():
                    m.add(types.InlineKeyboardButton(f"💎 {vip_plan_label(days)} ({to_persian_digits(days)} روز) — {fmt_amount_toman(amount)}", callback_data=f"buy_vip_{days}"))
                m.add(types.InlineKeyboardButton("👑 بازگشت به کارت طلایی", callback_data="vip_info"))
                # delete+resend چون پیام قبلی ممکن است عکس‌دار باشد
                try:
                    bot.delete_message(chat_id, call.message.message_id)
                except: pass
                buy_text = (
                    "🛒 ━━━━━━━━━━━━━━ 🛒\n"
                    "💎 *پلن‌های کارت طلایی*\n"
                    "🛒 ━━━━━━━━━━━━━━ 🛒\n\n"
                    "پلن دلخواهت را انتخاب کن:"
                )
                if BUY_VIP_PHOTO_ID:
                    try:
                        bot.send_photo(chat_id, BUY_VIP_PHOTO_ID, caption=buy_text, reply_markup=m)
                    except:
                        bot.send_message(chat_id, buy_text, reply_markup=m)
                else:
                    bot.send_message(chat_id, buy_text, reply_markup=m)
                bot.answer_callback_query(call.id)
                return

            if data.startswith("buy_vip_"):
                days = int(data.split("_")[2])
                # رفع باگ: بررسی اعتبار پلن قبل از ارسال فاکتور
                amount = VIP_PRICES.get(days)
                if amount is None:
                    bot.answer_callback_query(call.id, "❌ طرح انتخابی نامعتبر است.", show_alert=True)
                    return
                payload = f"vip_{user_id}_{days}_{int(time.time())}"
                try:
                    bot.send_invoice(chat_id, title="اشتراک VIP فضول‌یاب",
                                     description=f"کارت طلایی {vip_plan_label(days)} — {to_persian_digits(days)} روز",
                                     invoice_payload=payload, provider_token=PROVIDER_TOKEN, currency="IRT",
                                     prices=[types.LabeledPrice(label=f"کارت طلایی {vip_plan_label(days)}", amount=amount)],
                                     need_name=False, need_phone_number=False, need_email=False, is_flexible=False)
                    bot.answer_callback_query(call.id, "✅ فاکتور ارسال شد.")
                except Exception as e:
                    logger.error(f"VIP invoice error: {e}")
                    bot.answer_callback_query(call.id, "❌ خطا در ایجاد فاکتور.", show_alert=True)
                return

            # ====== v3.6: توگل چرخ شانس (ادمین) ======
            if data == "admin_wheel_toggle":
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                new_val = 0 if db.get_setting_int("wheel_enabled", 1) == 1 else 1
                db.set_setting("wheel_enabled", str(new_val))
                bot.answer_callback_query(call.id, f"🎰 چرخ شانس {'روشن' if new_val else 'خاموش'} شد.")
                try:
                    safe_edit_text(texts.ADMIN_CAT_GIFT, chat_id, call.message.message_id, reply_markup=admin_cat_gift_markup())
                except Exception:
                    bot.send_message(chat_id, texts.ADMIN_CAT_GIFT, reply_markup=admin_cat_gift_markup())
                return

            # ====== v3.6: چرخ شانس روزانه (VIP) ======
            if data == "wheel_info":
                clear_user_state(chat_id)
                bot.answer_callback_query(call.id)
                if db.get_setting_int("wheel_enabled", 1) != 1:
                    m = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                    bot.send_message(chat_id, texts.WHEEL_DISABLED, reply_markup=m)
                    return
                if not db.is_vip(user_id):
                    m = types.InlineKeyboardMarkup(row_width=1)
                    m.add(types.InlineKeyboardButton("🛒 خرید کارت طلایی", callback_data="buy_vip_menu"))
                    m.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                    bot.send_message(chat_id, texts.WHEEL_VIP_ONLY, reply_markup=m)
                    return
                render_wheel_info(chat_id, user_id)
                return

            # ====== v3.17: مرکز پاداش‌ها (چرخ شانس + کد هدیه + جایزه روزانه) ======
            if data == "rewards_menu":
                clear_user_state(chat_id)
                bot.answer_callback_query(call.id)
                m = types.InlineKeyboardMarkup(row_width=1)
                m.add(types.InlineKeyboardButton("🎂 جایزه روزانه", callback_data="daily_bonus"))
                m.add(types.InlineKeyboardButton("🎡 چرخ شانس", callback_data="wheel_info"))
                m.add(types.InlineKeyboardButton("🎟️ کد هدیه", callback_data="gift_code"))
                m.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                try:
                    safe_edit_text(texts.REWARDS_HEADER, chat_id, call.message.message_id, reply_markup=m)
                except Exception:
                    bot.send_message(chat_id, texts.REWARDS_HEADER, reply_markup=m)
                return

            # ====== v3.17: جایزه روزانه (همهٔ کاربران — ریست ۰۰:۰۰ ایران) ======
            if data == "daily_bonus":
                clear_user_state(chat_id)
                bot.answer_callback_query(call.id)
                render_daily_bonus(chat_id, user_id, delete_message_id=call.message.message_id)
                return

            if data == "daily_claim":
                today_t = datetime.datetime.now(TEHRAN_TZ).date().isoformat()
                yesterday_t = (datetime.datetime.now(TEHRAN_TZ).date() - datetime.timedelta(days=1)).isoformat()
                # v3.18.1: دریافت اتمیک — دابل‌کلیک موازی فقط یک‌بار جایزه می‌گیرد؛
                # استریک هم داخل همان UPSERT گارددار محاسبه می‌شود
                won, streak = db.claim_daily_bonus_atomic(user_id, today_t, yesterday_t)
                if not won:
                    bot.answer_callback_query(call.id, texts.DAILY_BONUS_ALREADY_TOAST, show_alert=True)
                    return
                bot.answer_callback_query(call.id)
                # قرعه‌کشی جایزهٔ رندوم
                prize = random.choices(DAILY_PRIZES, weights=[p["weight"] for p in DAILY_PRIZES], k=1)[0]
                if prize["type"] == "xp":
                    # پاداش استریک: هر روز پیوسته ‎+۱۰٪‎ تا سقف ۱۰۰٪
                    bonus_pct = min((streak - 1) * DAILY_STREAK_BONUS_STEP, DAILY_STREAK_BONUS_CAP)
                    final_xp = int(prize["value"] * (100 + bonus_pct) / 100)
                    try:
                        award_xp_with_level_up_notify(user_id, final_xp, chat_id=user_id)
                    except Exception:
                        pass
                    bonus_note = texts.DAILY_BONUS_NOTE.format(pct=to_persian_digits(bonus_pct)) if bonus_pct > 0 else ""
                    prize_line = texts.DAILY_RESULT_XP.format(xp=to_persian_digits(final_xp), bonus_note=bonus_note)
                else:
                    try:
                        db.add_vip(user_id, prize["value"])
                    except Exception:
                        pass
                    prize_line = texts.DAILY_RESULT_VIP.format(days=to_persian_digits(prize["value"]))
                # v3.19: جایزهٔ VIP نقاط عطف استریک (۱۰=۱ | ۲۰=۲ | ۳۰=۳ | ۴۰+=هر ۱۰ روز ۵ روز)
                milestone_line = ""
                _mvip = streak_vip_reward(streak)
                if _mvip > 0:
                    try:
                        db.add_vip(user_id, _mvip)
                        db.add_transaction(user_id, "streak_vip", 0, _mvip)
                    except Exception:
                        pass
                    milestone_line = "\n" + texts.DAILY_RESULT_STREAK_VIP.format(
                        streak=to_persian_digits(streak), days=to_persian_digits(_mvip))
                text = texts.DAILY_RESULT_HEADER.format(prize_line=prize_line, streak=to_persian_digits(streak))
                if milestone_line:
                    text += milestone_line
                m = types.InlineKeyboardMarkup(row_width=2)
                m.add(types.InlineKeyboardButton("🎡 چرخ شانس", callback_data="wheel_info"),
                      types.InlineKeyboardButton("🎁 پاداش‌ها", callback_data="rewards_menu"))
                m.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                try:
                    bot.delete_message(chat_id, call.message.message_id)
                except Exception:
                    pass
                bot.send_message(chat_id, text, reply_markup=m)
                return

            if data == "wheel_spin":
                if db.get_setting_int("wheel_enabled", 1) != 1:
                    bot.answer_callback_query(call.id, texts.WHEEL_DISABLED, show_alert=True)
                    return
                if not db.is_vip(user_id):
                    bot.answer_callback_query(call.id, "⛔ فقط برای اعضای VIP!", show_alert=True)
                    return
                today_t = datetime.datetime.now(TEHRAN_TZ).date().isoformat()
                # v3.18.1: رزرو اتمیک اسپین — دابل‌کلیک فقط یک‌بار می‌چرخد
                if not db.claim_wheel_date_atomic(user_id, today_t):
                    bot.answer_callback_query(call.id, "⏳ فرصت امروزت تمام شده — فردا بیا!", show_alert=True)
                    return
                bot.answer_callback_query(call.id)
                # قرعه‌کشی
                prize = random.choices(WHEEL_PRIZES, weights=[p["weight"] for p in WHEEL_PRIZES], k=1)[0]
                # اعطای جایزه
                if prize["type"] == "xp":
                    try:
                        award_xp_with_level_up_notify(user_id, prize["value"], chat_id=user_id)
                    except Exception:
                        pass
                    result_text = texts.WHEEL_RESULT_XP.format(xp=to_persian_digits(prize["value"]))
                else:
                    try:
                        db.add_vip(user_id, prize["value"])
                    except Exception:
                        pass
                    result_text = texts.WHEEL_RESULT_VIP.format(days=to_persian_digits(prize["value"]))
                # ── v4.8: ثبت چرخش در wheel_spins — همانند مینی‌اپ (services/wheel.py) تا
                # ماموریت‌های گردونه (g14/g15/g26) از هر دو مسیر ربات و مینی‌اپ شمرده شوند ──
                try:
                    with db._lock:
                        db.conn.execute(
                            "INSERT INTO wheel_spins(user_id, prize_type, amount, created_at) VALUES(?,?,?,?)",
                            (user_id, prize["type"], prize["value"],
                             datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")))
                except Exception as _ws_err:
                    logger.error(f"wheel_spins log error {user_id}: {_ws_err}")
                # ── v3.14: نمایش سینمایی — تایپ‌رایتر + مکث + برد + MP4/GIF،
                # همه در نخ پس‌زمینه؛ هندلر فوراً آزاد می‌شود تا polling برای
                # هزاران کاربر هم‌زمان بلاک نشود ──
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(types.InlineKeyboardButton("🎡 چرخ مجدد فردا", callback_data="wheel_info"),
                           types.InlineKeyboardButton("🎁 پاداش‌ها", callback_data="rewards_menu"))
                markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                widx = WHEEL_PRIZES.index(prize)
                threading.Thread(target=_wheel_suspense_send,
                                 args=(chat_id, widx, result_text, prize["type"], markup),
                                 daemon=True).start()
                return

            # ====== v3.6: تله‌های چندگانه (VIP) ======
            if data == "my_traps":
                clear_user_state(chat_id)
                bot.answer_callback_query(call.id)
                if not db.is_vip(user_id):
                    m = types.InlineKeyboardMarkup(row_width=1)
                    m.add(types.InlineKeyboardButton("🛒 خرید کارت طلایی", callback_data="buy_vip_menu"))
                    m.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                    bot.send_message(chat_id, texts.MY_TRAPS_VIP_ONLY, reply_markup=m)
                    return
                render_my_traps(chat_id, user_id, delete_message_id=call.message.message_id)
                return

            if data == "add_trap_start":
                if not db.is_vip(user_id):
                    bot.answer_callback_query(call.id, "⛔ فقط برای اعضای VIP!", show_alert=True)
                    return
                max_traps = db.get_setting_int("vip_max_traps", 3)
                if 1 + db.count_traps(user_id) >= max_traps:
                    bot.answer_callback_query(call.id, texts.MY_TRAPS_LIMIT.format(max_traps=to_persian_digits(max_traps)), show_alert=True)
                    return
                clear_user_state(chat_id)
                set_user_state(chat_id, ('add_trap_label',))
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, texts.TRAP_ASK_LABEL, reply_markup=cancel_markup())
                return

            if data.startswith("del_trap_"):
                code = data[len("del_trap_"):]
                db.delete_trap(code, user_id)
                bot.answer_callback_query(call.id, texts.TRAP_DELETED)
                render_my_traps(chat_id, user_id, delete_message_id=call.message.message_id)
                return

            if data.startswith("copy_trap_"):
                bot.answer_callback_query(call.id, "📋 لینک کپی شد!")
                return

            # ====== v3.6: آنالیز حرفه‌ای تله (VIP) ======
            if data == "trap_analytics":
                clear_user_state(chat_id)
                bot.answer_callback_query(call.id)
                if not db.is_vip(user_id):
                    m = types.InlineKeyboardMarkup(row_width=1)
                    m.add(types.InlineKeyboardButton("🛒 خرید کارت طلایی", callback_data="buy_vip_menu"))
                    m.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                    bot.send_message(chat_id, texts.ANALYTICS_VIP_ONLY, reply_markup=m)
                    return
                render_trap_analytics(chat_id, user_id, delete_message_id=call.message.message_id)
                return

            # ====== v3.6: هدیه‌دادن روزهای VIP ======
            if data == "gvip_menu":
                clear_user_state(chat_id)
                if not db.is_vip(user_id):
                    bot.answer_callback_query(call.id, texts.GVIP_NOT_VIP, show_alert=True)
                    return
                today_t = datetime.datetime.now(TEHRAN_TZ).date().isoformat()
                if db.get_last_giftvip_date(user_id) == today_t:
                    bot.answer_callback_query(call.id, texts.GVIP_LIMIT_DAILY, show_alert=True)
                    return
                set_user_state(chat_id, ('gvip_id',))
                bot.answer_callback_query(call.id)
                days_left = db.get_vip_days_left(user_id)
                try:
                    bot.delete_message(chat_id, call.message.message_id)
                except Exception:
                    pass
                bot.send_message(chat_id, texts.GVIP_INTRO.format(days_left=to_persian_digits(days_left)), reply_markup=cancel_markup())
                return

            if data.startswith("gvip_go_"):
                parts = data.split("_")
                if len(parts) != 4:
                    bot.answer_callback_query(call.id, "❌ خطا.", show_alert=True)
                    return
                try:
                    rid, days = int(parts[2]), int(parts[3])
                except Exception:
                    bot.answer_callback_query(call.id, "❌ خطا.", show_alert=True)
                    return
                # v3.22 امنیتی: ضد کلیک فریب‌کارانه — باید تأییدِ در جریانِ خود کاربر و با همان گیرنده/روزها باشد
                _gv_st = get_user_state(chat_id)
                if not _gv_st or _gv_st[0] != 'gvip_confirm' or len(_gv_st) < 3 or _gv_st[1] != rid or _gv_st[2] != days:
                    bot.answer_callback_query(call.id, "⏳ درخواست هدیه‌ای در جریان نیست.", show_alert=True)
                    return
                clear_user_state(chat_id)
                if not db.is_vip(user_id):
                    bot.answer_callback_query(call.id, texts.GVIP_NOT_VIP, show_alert=True)
                    return
                today_t = datetime.datetime.now(TEHRAN_TZ).date().isoformat()
                if db.get_last_giftvip_date(user_id) == today_t:
                    bot.answer_callback_query(call.id, texts.GVIP_LIMIT_DAILY, show_alert=True)
                    return
                ok, res = db.transfer_vip_days(user_id, rid, days)
                if not ok:
                    emap = {"no_vip": texts.GVIP_NOT_VIP, "not_enough": texts.GVIP_NOT_ENOUGH}
                    bot.answer_callback_query(call.id, emap.get(res, "❌ خطا در انتقال."), show_alert=True)
                    return
                db.set_last_giftvip_date(user_id, today_t)
                try:
                    db.add_transaction(user_id, "vip_transfer_out", 0, 0)
                    db.add_transaction(rid, "vip_transfer_in", 0, 0)
                except Exception:
                    pass
                gleft = db.get_vip_days_left(user_id)
                me = db.get_user_basic(user_id)
                tgt = db.get_user_basic(rid)
                rname = sanitize_name((tgt['first_name'] if tgt and tgt['first_name'] else str(rid)))
                sname = sanitize_name((me['first_name'] if me and me['first_name'] else "یک کارآگاه"))
                bot.answer_callback_query(call.id, "✅ هدیه ارسال شد!")
                bot.send_message(chat_id, texts.GVIP_DONE_OWNER.format(
                    rname=escape_md(rname), days=to_persian_digits(days), days_left=to_persian_digits(gleft)))
                try:
                    rleft = db.get_vip_days_left(rid)
                    bot.send_message(rid, texts.GVIP_DONE_RECEIVER.format(
                        sname=escape_md(sname), days=to_persian_digits(days), days_left=to_persian_digits(rleft)))
                except Exception:
                    pass
                return

            if data == "set_welcome":
                if not db.is_vip(user_id):
                    bot.answer_callback_query(call.id, "⛔ این قابلیت فقط برای کاربران VIP فعال است.", show_alert=True)
                    return
                clear_user_state(chat_id)
                set_user_state(chat_id, ('welcome_text',))
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, "✍️ متن:", reply_markup=cancel_markup())
                return

            if data == "set_welcome_photo":
                if not db.is_vip(user_id):
                    bot.answer_callback_query(call.id, "⛔ این قابلیت فقط برای کاربران VIP فعال است.", show_alert=True)
                    return
                clear_user_state(chat_id)
                set_user_state(chat_id, ('welcome_photo',))
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, "🖼️ عکس خوش‌آمدگویی را ارسال کنید:", reply_markup=cancel_markup())
                return

            if data == "set_mask":
                if not db.is_vip(user_id):
                    bot.answer_callback_query(call.id, "⛔ این قابلیت فقط برای کاربران VIP فعال است.", show_alert=True)
                    return
                clear_user_state(chat_id)
                markup = types.InlineKeyboardMarkup(row_width=4)
                btns = [types.InlineKeyboardButton(em, callback_data=f"mask_emoji_{em}") for em in MASK_EMOJIS]
                for i in range(0, len(btns), 4):
                    markup.add(*btns[i:i+4])
                markup.add(types.InlineKeyboardButton("❌ انصراف", callback_data="cancel_state"))
                safe_edit_text("🎭 یک ایموجی برای نقاب انتخاب کن یا خودت تایپ کن:", chat_id, call.message.message_id, reply_markup=markup)
                set_user_state(chat_id, ('mask_emoji',))
                bot.answer_callback_query(call.id)
                return

            if data.startswith("mask_emoji_"):
                if not db.is_vip(user_id):
                    bot.answer_callback_query(call.id, "⛔ اشتراک VIP شما فعال نیست.", show_alert=True)
                    return
                emoji = data.split("_", 2)[2]
                clear_user_state(chat_id)
                set_user_state(chat_id, ('mask_text', emoji))
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(types.InlineKeyboardButton("بدون لقب", callback_data="mask_skip_text"),
                           types.InlineKeyboardButton("❌ انصراف", callback_data="cancel_state"))
                safe_edit_text(f"🎭 ایموجی: {emoji}\nحالا لقب (متن) نقاب را بفرست، یا دکمه «بدون لقب» را بزن.", chat_id, call.message.message_id, reply_markup=markup)
                bot.answer_callback_query(call.id)
                return

            if data == "mask_skip_text":
                state = get_user_state(chat_id)
                if state and state[0] == 'mask_text':
                    emoji = state[1]
                    clear_user_state(chat_id)
                    if not db.is_vip(chat_id):
                        safe_edit_text(VIP_EXPIRED_MSG, chat_id, call.message.message_id, reply_markup=vip_menu_button())
                        bot.answer_callback_query(call.id)
                        return
                    db.set_user_mask(chat_id, emoji, "")
                    safe_edit_text(f"🎭 نقاب کارآگاهی تو: {emoji}", chat_id, call.message.message_id, reply_markup=vip_menu_button())
                else:
                    bot.answer_callback_query(call.id, "خطا.")
                bot.answer_callback_query(call.id)
                return

            # ----- راهنما -----
            if data == "help":
                clear_user_state(chat_id)
                markup = types.InlineKeyboardMarkup(row_width=2)
                # دکمه‌های راهنمای جدید — طبق texts.HELP_MAIN_BUTTONS
                for label, callback in texts.HELP_MAIN_BUTTONS:
                    markup.add(types.InlineKeyboardButton(label, callback_data=callback))
                markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                safe_edit_text(texts.HELP_MAIN_PROMPT, chat_id, call.message.message_id, reply_markup=markup)
                bot.answer_callback_query(call.id)
                return

            # ----- زیردکمه‌های راهنما -----
            if data in ("help_link", "help_vip", "help_anon", "help_gift",
                        "help_tasks", "help_xp", "help_myinfo", "help_link_tutorial"):
                mapping = {
                    "help_link": texts.HELP_LINK,
                    "help_vip": texts.HELP_VIP,
                    "help_anon": texts.HELP_ANON,
                    "help_gift": texts.HELP_GIFT,
                    "help_tasks": texts.HELP_TASKS,
                    "help_xp": texts.HELP_XP,
                    "help_myinfo": texts.HELP_MYINFO_NEW,
                }
                # برای help_link_tutorial فقط دکمه خانه (بدون بازگشت به راهنما)
                if data == "help_link_tutorial":
                    markup = types.InlineKeyboardMarkup(row_width=1)
                    markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                else:
                    markup = types.InlineKeyboardMarkup(row_width=1)
                    markup.add(types.InlineKeyboardButton("🔙 راهنما", callback_data="help"))
                    markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))

                # برای help_link_tutorial یک ویدیو ارسال می‌کنیم
                if data == "help_link_tutorial":
                    # پاک کردن پیام قبلی و ارسال ویدیو + متن
                    try:
                        bot.delete_message(chat_id, call.message.message_id)
                    except: pass
                    if LINK_TUTORIAL_VIDEO_ID:
                        try:
                            bot.send_video(chat_id, LINK_TUTORIAL_VIDEO_ID, caption=texts.LINK_TUTORIAL_TEXT, reply_markup=markup)
                        except:
                            bot.send_message(chat_id, texts.LINK_TUTORIAL_TEXT, reply_markup=markup)
                    else:
                        bot.send_message(chat_id, texts.LINK_TUTORIAL_TEXT + "\n\n⚠️ ویدیوی آموزشی به‌زودی اضافه می‌شود.", reply_markup=markup)
                    bot.answer_callback_query(call.id)
                    return

                safe_edit_text(mapping[data], chat_id, call.message.message_id, reply_markup=markup)
                bot.answer_callback_query(call.id)
                return

            # ----- backward compatibility برای دکمه‌های قدیمی -----
            if data in ("help_welcome", "help_welcome_photo", "help_mask", "help_myinfo"):
                mapping = {
                    "help_welcome": texts.HELP_WELCOME,
                    "help_welcome_photo": texts.HELP_WELCOME_PHOTO,
                    "help_mask": texts.HELP_MASK,
                    "help_myinfo": texts.HELP_MYINFO_NEW
                }
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(types.InlineKeyboardButton("🔙 راهنما", callback_data="help"))
                markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                safe_edit_text(mapping[data], chat_id, call.message.message_id, reply_markup=markup)
                bot.answer_callback_query(call.id)
                return

            if data == "preview_welcome":
                clear_user_state(chat_id)
                welcome_text = db.get_welcome_text(user_id)
                welcome_photo = db.get_welcome_photo(user_id)
                if not welcome_text and not welcome_photo:
                    bot.answer_callback_query(call.id, "⛔ هیچ پیام خوش‌آمدی تنظیم نکردی.", show_alert=True)
                    return
                note = "" if db.is_vip(user_id) else "\n\n⚠️ توجه: چون اشتراک VIP شما در حال حاضر غیرفعال است، این پیام به فضول‌ها نمایش داده نمی‌شود."
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(types.InlineKeyboardButton("👑 بازگشت به کارت طلایی", callback_data="vip_info"))
                markup.add(types.InlineKeyboardButton("🏠 خانه", callback_data="main_menu"))
                if welcome_photo:
                    try:
                        bot.send_photo(chat_id, welcome_photo, caption=(welcome_text or "👋") + note, reply_markup=markup)
                    except:
                        bot.send_message(chat_id, (welcome_text or "👋") + note, reply_markup=markup)
                else:
                    bot.send_message(chat_id, (welcome_text or "👋") + note, reply_markup=markup)
                bot.answer_callback_query(call.id)
                return

            if data == "main_menu":
                clear_user_state(chat_id)
                bot.answer_callback_query(call.id)
                show_main_menu_for_callback(call, chat_id, user_id)
                return

            # ====== کالبک‌های ویزارد کاربر جدید ======
            if data == "wizard_make_trap":
                # کاربر تله ساخت — اول پیام تله رو نشون بده، بعد منوی اصلی
                bot.answer_callback_query(call.id)
                # حذف پیام ویزارد
                try:
                    bot.delete_message(chat_id, call.message.message_id)
                except: pass
                # نمایش تله (مثل my_link_show)
                link = user_link(user_id)
                samples = [
                    f"[جرات داری روم کلیک کن 👁️]({link})",
                    f"[میخوای آشنا شیم؟ 🤭]({link})",
                ]
                trap_text = (
                    f"🔍 *تلهٔ اختصاصی تو:*\n{link}\n\n"
                    f"📋 این لینک خام رو که نمی‌تونی توی بیو بذاری...\n"
                    f"باید پشت یه متن قایمش کنی — این میشه *هایپرلینک*.\n"
                    f"یه جملهٔ جذاب که هرکی روش بزنه، مستقیم می‌افته توی دامت.\n\n"
                    f"📋 چند نمونهٔ آماده با کد خودت:\n"
                    f"۱. {samples[0]}\n"
                    f"۲. {samples[1]}\n\n"
                    f"💡 هرکدوم رو دوست داشتی *کپی* کن و بچسبون توی بیوگرافیت.\n"
                    f"یا خودت یه متن دلخواه بساز..."
                )
                trap_markup = types.InlineKeyboardMarkup(row_width=2)
                btn1 = types.InlineKeyboardButton("📋 کپی ۱", callback_data="copy_sample_1", copy_text=types.CopyTextButton(samples[0]))
                btn2 = types.InlineKeyboardButton("📋 کپی ۲", callback_data="copy_sample_2", copy_text=types.CopyTextButton(samples[1]))
                trap_markup.add(btn1, btn2)
                trap_markup.add(types.InlineKeyboardButton("✍️ ساخت هایپرلینک با متن دلخواه", callback_data="get_hyperlink"))
                trap_markup.add(types.InlineKeyboardButton("🎬 نحوه قرار دادن لینک", callback_data="help_link_tutorial"))
                # دکمه ادامه به منوی اصلی
                trap_markup.add(types.InlineKeyboardButton("➡️ ادامه به منوی اصلی", callback_data="wizard_go_home"))
                bot.send_message(chat_id, trap_text, reply_markup=trap_markup)
                return

            if data == "wizard_skip":
                # کاربر رد کرد — پیام کوتاه + منوی اصلی
                bot.answer_callback_query(call.id)
                try:
                    bot.delete_message(chat_id, call.message.message_id)
                except: pass
                bot.send_message(chat_id, texts.WIZARD_AFTER_TUTORIAL_SKIP)
                # ارسال منوی اصلی
                show_main_menu_for_callback(call, chat_id, user_id)
                return

            if data == "wizard_go_home":
                # بعد از ساخت تله، به منوی اصلی بره
                bot.answer_callback_query(call.id)
                show_main_menu_for_callback(call, chat_id, user_id)
                return

            if data.startswith("copy_sample_"):
                bot.answer_callback_query(call.id, "📋 لینک کپی شد!")
                return
            if data == "copy_raw_link":
                bot.answer_callback_query(call.id, "🔗 لینک خام کپی شد! بذارش هرجا خواستی.")
                return
            if data == "copy_dummy":
                bot.answer_callback_query(call.id)
                return

            if data.startswith("admin_block_"):
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                target = int(data.split("_")[2])
                db.block_user(target, by_admin=True)
                bot.answer_callback_query(call.id, f"کاربر {target} مسدود شد.")
                return
            if data.startswith("admin_msg_"):
                if user_id != ADMIN_ID:
                    bot.answer_callback_query(call.id, "⛔")
                    return
                target = int(data.split("_")[2])
                set_admin_reply(user_id, target)
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, "✍️ پیام خود را برای کاربر بنویسید:", reply_markup=cancel_markup())
                return

            if data == "cancel_state":
                clear_user_state(chat_id)
                remove_support_session(chat_id)
                pop_support_partner(chat_id)
                pop_admin_reply(chat_id)
                bot.answer_callback_query(call.id, "❌ لغو شد.")
                show_main_menu_for_callback(call, chat_id, user_id)
                return

            # اگر به اینجا رسیدیم، یعنی callback نهایی پردازش شده و باید خارج شویم
            bot.answer_callback_query(call.id)
            return

        except Exception as e:
            logger.error(f"Callback error: {e}")
            db.log_usage_event("error", f"cb:{(data or '?').split('_')[0]}:{type(e).__name__}", (time.time() - _t0) * 1000)
            try:
                bot.answer_callback_query(call.id, "⚠️ خطای غیرمنتظره! لطفاً دوباره تلاش کن.")
            except:
                pass
            return
        
# ====== هندلرهای پرداخت ======
@bot.pre_checkout_query_handler(func=lambda query: True)
def pre_checkout(query):
    """رفع باگ: اعتبارسنجی payload قبل از تأیید پرداخت.
    بدون این اعتبارسنجی، کاربر می‌تواند با payload دستی پرداخت کند و VIP بگیرد."""
    try:
        # v4.0 (fozol-pro): فاکتورهای مینی‌اپ (vip:...) را هندلر اختصاصی مینی‌اپ تأیید می‌کند
        if str(query.invoice_payload).startswith("vip:"):
            return
        # v3.22: در نگهداری، پرداخت جدید غیرادمین بسته است (پول کسی برنمی‌گردد چون تأیید نمی‌شود)
        if maintenance_gate(query.from_user.id):
            bot.answer_pre_checkout_query(query.id, ok=False,
                error_message="🚧 ربات در حالت نگهداری است — لطفاً بعد از رفع نگهداری دوباره تلاش کن.")
            return
        parts = query.invoice_payload.split("_")
        if not parts or parts[0] not in ("vip", "giftvip", "reveal", "saveface"):
            bot.answer_pre_checkout_query(query.id, ok=False,
                error_message="فاکتور نامعتبر است.")
            return

        if parts[0] == "saveface":
            # v4.4: payload: saveface_{visitor_id}_{decision_id}_{time}
            # پرداخت فقط تا وقتی معتبر است که تصمیم هنوز در وضعیت saveface باشد
            # (اگر تایمر ۳ دقیقه‌ای لو داده باشد، پرداخت تأیید نمی‌شود و پول برداشته نمی‌شود)
            if len(parts) < 3:
                bot.answer_pre_checkout_query(query.id, ok=False,
                    error_message="اطلاعات فاکتور ناقص است.")
                return
            buyer_id = int(parts[1])
            dec_id = int(parts[2])
            if buyer_id != query.from_user.id:
                bot.answer_pre_checkout_query(query.id, ok=False,
                    error_message="این فاکتور برای کاربر دیگری است.")
                return
            dec = db.get_trap_decision(dec_id)
            if not dec or dec['visitor_id'] != buyer_id or dec['status'] != 'saveface':
                bot.answer_pre_checkout_query(query.id, ok=False,
                    error_message="⌛ فرصت حفظ آبرو تمام شده است — پرداخت انجام نمی‌شود.")
                return
            expected_amount = _saveface_price_rial()
        elif parts[0] == "vip":
            # payload: vip_{user_id}_{days}_{time}
            if len(parts) < 4:
                bot.answer_pre_checkout_query(query.id, ok=False,
                    error_message="اطلاعات فاکتور ناقص است.")
                return
            buyer_id = int(parts[1])
            days = int(parts[2])
            # فقط خریدار می‌تواند پرداخت کند
            if buyer_id != query.from_user.id:
                bot.answer_pre_checkout_query(query.id, ok=False,
                    error_message="این فاکتور برای کاربر دیگری است.")
                return
            expected_amount = VIP_PRICES.get(days)
        elif parts[0] == "giftvip":
            # payload: giftvip_{buyer_id}_{target_id}_{days}_{time}
            if len(parts) < 5:
                bot.answer_pre_checkout_query(query.id, ok=False,
                    error_message="اطلاعات فاکتور هدیه ناقص است.")
                return
            buyer_id = int(parts[1])
            days = int(parts[3])
            if buyer_id != query.from_user.id:
                bot.answer_pre_checkout_query(query.id, ok=False,
                    error_message="این فاکتور برای کاربر دیگری است.")
                return
            expected_amount = VIP_PRICES.get(days)
        else:  # reveal — payload: reveal_{user_id}_{cid}
            # رفع باگ قدیمی: فاکتورهای reveal به‌اشتباه داخل شاخهٔ giftvip رد می‌شدند
            if len(parts) < 3:
                bot.answer_pre_checkout_query(query.id, ok=False,
                    error_message="اطلاعات فاکتور ناقص است.")
                return
            buyer_id = int(parts[1])
            if buyer_id != query.from_user.id:
                bot.answer_pre_checkout_query(query.id, ok=False,
                    error_message="این فاکتور برای کاربر دیگری است.")
                return
            expected_amount = db.get_setting_int("reveal_price", 30000)

        if expected_amount is None:
            bot.answer_pre_checkout_query(query.id, ok=False,
                error_message="طرح انتخابی نامعتبر است.")
            return

        bot.answer_pre_checkout_query(query.id, ok=True)
    except (ValueError, IndexError):
        bot.answer_pre_checkout_query(query.id, ok=False,
            error_message="خطا در پردازش فاکتور.")
    except Exception as e:
        logger.error(f"Pre-checkout error: {e}")
        bot.answer_pre_checkout_query(query.id, ok=False,
            error_message="خطا در پردازش فاکتور.")

@bot.message_handler(content_types=['successful_payment'])
def successful_payment(message):
    payment = message.successful_payment
    payload = payment.invoice_payload
    # v4.0 (fozol-pro): پرداخت‌های مینی‌اپ (vip:...) توسط هندلر اختصاصی مینی‌اپ پردازش می‌شوند
    if payload.startswith("vip:"):
        return
    try:
        parts = payload.split("_")
        if parts[0] == "vip":
            buyer_id = int(parts[1])
            # اصلاح بحرانی ۳: تطابق خریدار با کاربر واقعی
            if buyer_id != message.from_user.id:
                bot.send_message(message.chat.id, "❌ خرید نامعتبر است.", reply_markup=home_markup())
                return
            days = int(parts[2])
            expected_amount = VIP_PRICES.get(days)
            if expected_amount is None:
                bot.send_message(message.chat.id, "❌ طرح خرید نامعتبر است. لطفاً با پشتیبانی تماس بگیرید.",
                                 reply_markup=home_markup())
                return
            if payment.total_amount != expected_amount:
                bot.send_message(message.chat.id,
                                 f"❌ مبلغ پرداختی ({to_persian_int(payment.total_amount)} ریال) با مبلغ مورد انتظار ({to_persian_int(expected_amount)} ریال) مغایرت دارد. "
                                 "لطفاً با پشتیبانی تماس بگیرید.",
                                 reply_markup=home_markup())
                return
            db.add_transaction(buyer_id, "vip", expected_amount, days)
            db.add_vip(buyer_id, days)
            # ----- اعطای XP خرید VIP -----
            purchase_count = db.get_user_purchase_count(buyer_id)
            bonus = 'first_buy_vip' if purchase_count == 1 else None
            award_xp_with_level_up_notify(
                buyer_id, 0,
                recurring_type='buy_vip',
                bonus_type=bonus,
                chat_id=buyer_id
            )
            bot.send_message(buyer_id,
                             f"🏅 اشتراک VIP شما به مدت {to_persian_digits(days)} روز فعال شد! خوش آمدی به تیم کارآگاهان ویژه.",
                             reply_markup=home_markup())

        elif parts[0] == "giftvip":
            buyer_id = int(parts[1])
            if buyer_id != message.from_user.id:
                bot.send_message(message.chat.id, "❌ خرید نامعتبر است.", reply_markup=home_markup())
                return
            target_id = int(parts[2])
            days = int(parts[3])
            expected_amount = VIP_PRICES.get(days)
            if expected_amount is None:
                bot.send_message(message.chat.id, "❌ طرح هدیه نامعتبر است. لطفاً با پشتیبانی تماس بگیرید.",
                                 reply_markup=home_markup())
                return
            if payment.total_amount != expected_amount:
                bot.send_message(message.chat.id,
                                 f"❌ مبلغ پرداختی ({to_persian_int(payment.total_amount)} ریال) با مبلغ مورد انتظار ({to_persian_int(expected_amount)} ریال) مغایرت دارد. "
                                 "لطفاً با پشتیبانی تماس بگیرید.",
                                 reply_markup=home_markup())
                return
            db.add_transaction(buyer_id, "gift_vip", expected_amount, days)
            db.add_vip(target_id, days)
            buyer_name = get_user_display(buyer_id)
            # ----- اعطای XP هدیه VIP به خریدار -----
            gift_count = db.get_user_gift_count(buyer_id)
            bonus = 'first_gift_vip' if gift_count == 1 else None
            award_xp_with_level_up_notify(
                buyer_id, 0,
                recurring_type='gift_vip',
                bonus_type=bonus,
                chat_id=buyer_id
            )
            bot.send_message(buyer_id,
                             f"🎁 هدیهٔ تو ({to_persian_digits(days)} روز VIP) به کاربر مورد نظر رسید.",
                             reply_markup=home_markup())
            # رفع باگ: اگر target ربات را بلاک کرده، ارسال پیام خطا می‌دهد
            try:
                bot.send_message(target_id,
                                 f"🎁 *{escape_md(buyer_name)}* به تو {to_persian_digits(days)} روز VIP هدیه داد!\n🏅 حالا از قابلیت‌های ویژه برخوردار شدی.",
                                 reply_markup=home_markup())
            except ApiTelegramException as e:
                if e.error_code == 403:
                    logger.info(f"Target {target_id} has blocked the bot; gift VIP still applied.")
                    try:
                        db.mark_user_blocked_bot(target_id)
                    except Exception:
                        pass
                else:
                    logger.error(f"Gift notify target {target_id} error: {e}")
            except Exception as e:
                logger.error(f"Gift notify target {target_id} error: {e}")

        elif parts[0] == "reveal":
            buyer_id = int(parts[1])
            if buyer_id != message.from_user.id:
                bot.send_message(message.chat.id, "❌ خرید نامعتبر است.", reply_markup=home_markup())
                return
            clicker_id = int(parts[2])
            expected = db.get_setting_int("reveal_price", 30000)
            if payment.total_amount != expected:
                bot.send_message(message.chat.id,
                                 f"❌ مبلغ پرداختی ({to_persian_int(payment.total_amount)} ریال) با مبلغ مورد انتظار ({to_persian_int(expected)} ریال) مغایرت دارد.",
                                 reply_markup=home_markup())
                return
            # v3.22 امنیتی: لایهٔ دوم — فضولِ تله نبودن خریدار یعنی فعال‌سازی ممنوع (لایگ لایهٔ فاکتور)
            _rv2_snoops = db.get_snoops(buyer_id)
            if not any(s['clicker_id'] == clicker_id for s in _rv2_snoops):
                logger.error(f"[SECURITY] reveal paid for non-snoop {clicker_id} by {buyer_id} — rejected")
                bot.send_message(message.chat.id,
                                 "❌ این کاربر فضول تلهٔ تو نیست؛ فعال‌سازی انجام نشد. برای بازگشت مبلغ با پشتیبانی تماس بگیر.",
                                 reply_markup=home_markup())
                try:
                    bot.send_message(ADMIN_ID, f"⚠️ [SECURITY] تلاش reveal غیرمجاز: خریدار {buyer_id} برای {clicker_id} — مبلغ پرداخت شده ولی فعال نشد.")
                except Exception:
                    pass
                return
            db.add_reveal(buyer_id, clicker_id)
            db.add_transaction(buyer_id, "reveal", expected, 0)
            snoops = db.get_snoops(buyer_id)
            info = next((s for s in snoops if s['clicker_id'] == clicker_id), None)
            r_name = info['name'] if info else "فضول"
            r_uname = info.get('username') if info else None
            bot.send_message(buyer_id,
                texts.REVEAL_SUCCESS.format(name=escape_md(r_name), uid=clicker_id,
                                            uname=f"@{r_uname}" if r_uname else "ندارد"),
                reply_markup=home_markup())

        elif parts[0] == "saveface":
            # v4.4: پرداخت «حفظ آبرو» — payload: saveface_{visitor_id}_{decision_id}_{time}
            buyer_id = int(parts[1])
            dec_id = int(parts[2])
            if buyer_id != message.from_user.id:
                bot.send_message(message.chat.id, "❌ خرید نامعتبر است.", reply_markup=home_markup())
                return
            expected = _saveface_price_rial()
            if payment.total_amount != expected:
                bot.send_message(message.chat.id,
                                 f"❌ مبلغ پرداختی ({to_persian_int(payment.total_amount)} ریال) با مبلغ مورد انتظار ({to_persian_int(expected)} ریال) مغایرت دارد.",
                                 reply_markup=home_markup())
                return
            # اتمیک: فقط از وضعیت saveface → paid. اگر تایمر ۳ دقیقه‌ای همزمان لو داده باشد،
            # پرداخت قبول نمی‌شود و برای بازگشت دستی به ادمین اطلاع داده می‌شود.
            if not db.set_trap_decision_status(dec_id, 'paid', paid_amount=expected):
                bot.send_message(buyer_id,
                    "⚠️ پرداخت رسید ولی فرصت حفظ آبرو همین لحظه تمام شده بود. "
                    "مبلغ شما دستی بررسی و بازگشت داده می‌شود — با پشتیبانی تماس بگیر.",
                    reply_markup=home_markup())
                try:
                    bot.send_message(ADMIN_ID,
                        f"⚠️ [saveface] پرداخت بعد از انقضا: کاربر {buyer_id}، تصمیم {dec_id}، مبلغ {to_persian_int(expected)} ریال — بازگشت وجه لازم است.")
                except Exception:
                    pass
                return
            db.set_trap_decision_status(dec_id, 'saved')
            db.add_transaction(buyer_id, "saveface", expected, 0)
            dec = db.get_trap_decision(dec_id)
            bot.send_message(buyer_id, texts.TRAP_SAVED, reply_markup=home_markup())
            # اطلاع بی‌نام به صاحب لینک — بدون هیچ اطلاعات هویتی
            if dec:
                try:
                    if is_subscribed(dec['owner_id']):
                        bot.send_message(dec['owner_id'], texts.TRAP_SAVED_OWNER_ANON)
                except Exception:
                    pass
                _trap_visitor_aftermath(dec)

        else:
            bot.send_message(message.chat.id, "✅ پرداخت شما دریافت شد.", reply_markup=home_markup())

    except Exception as e:
        logger.error(f"Payment error: {e}")
        bot.send_message(message.chat.id, "❌ خطا در پردازش پرداخت. لطفاً با پشتیبانی تماس بگیرید.",
                         reply_markup=home_markup())

import bot_challenge as _bot_challenge  # v4.7 استخراج از main.py — ماژول bot_challenge
_bot_challenge._bind(globals())  # تزریق اشیاء ربات (bot/db/texts/...)
from bot_challenge import (  # noqa: F401 — نام‌های منتقل‌شده به ماژول
    _challenge_now_tehran, get_challenge_status, _broadcast_to_all_users,
    _challenge_utcnow, _CHAL_FMT, _challenge_window,
    _challenge_utc_to_tehran_str, _challenge_remaining_str, _challenge_standings_text,
    _challenge_cache_lock, _challenge_cache, _CHALLENGE_CACHE_TTL,
    _CHALLENGE_CACHE_TTL_BOARD, _challenge_cached, _challenge_motivation_text,
    _challenge_start_challenge_preview, _challenge_start_challenge, _challenge_prize_for_rank,
    _challenge_reward_type, _challenge_envelope_for_rank, _challenge_money_fa,
    _challenge_prize_block_text, _challenge_prize_dict, _challenge_finish_and_settle,
    _challenge_tick, challenge_loop
)
# ====== v3.4: گزارش هفتگی شخصی ======
# نگاشت ۰=شنبه … ۶=جمعه به weekday پایتون (دوشنبه=۰)
_FA_WEEKDAY = {0: ("شنبه", 5), 1: ("یکشنبه", 6), 2: ("دوشنبه", 0), 3: ("سه‌شنبه", 1),
               4: ("چهارشنبه", 2), 5: ("پنجشنبه", 3), 6: ("جمعه", 4)}

def _delta_str(cur, prev):
    d = cur - prev
    if d > 0:
        return "▲ +" + to_persian_digits(d)
    if d < 0:
        return "▼ " + to_persian_digits(d)
    return "بدون تغییر"

def _build_weekly_report_text(user_id):
    now_t = _challenge_now_tehran()
    today = now_t.date()
    this_start = (today - datetime.timedelta(days=7)).isoformat()
    prev_start = (today - datetime.timedelta(days=14)).isoformat()
    t_iso = today.isoformat()
    clicks_this = db.conn.execute("SELECT COUNT(*) FROM clicks WHERE owner_id=? AND date(clicked_at) >= ? AND date(clicked_at) < ?", (user_id, this_start, t_iso)).fetchone()[0]
    clicks_prev = db.conn.execute("SELECT COUNT(*) FROM clicks WHERE owner_id=? AND date(clicked_at) >= ? AND date(clicked_at) < ?", (user_id, prev_start, this_start)).fetchone()[0]
    snoops_this = db.conn.execute("SELECT COUNT(DISTINCT clicker_id) FROM clicks WHERE owner_id=? AND date(clicked_at) >= ? AND date(clicked_at) < ?", (user_id, this_start, t_iso)).fetchone()[0]
    snoops_prev = db.conn.execute("SELECT COUNT(DISTINCT clicker_id) FROM clicks WHERE owner_id=? AND date(clicked_at) >= ? AND date(clicked_at) < ?", (user_id, prev_start, this_start)).fetchone()[0]
    xp = db.get_user_xp(user_id)
    level = db.get_user_level_cached(user_id)
    streak = db.get_streak(user_id)
    rank = db.get_user_rank_by_distinct(user_id)
    rank_str = f"#{to_persian_digits(rank)}" if rank else "بدون رتبه"
    if snoops_this > 0:
        tip = "🚀 ادامه بده! هر هفته بهتر از هفتهٔ قبل."
    else:
        tip = "💡 تله‌ات رو این هفته پخش کن — متن جذاب‌تر = شکار بیشتر!"
    return texts.WEEKLY_REPORT_PERSONAL.format(
        clicks_this=to_persian_digits(clicks_this), delta=_delta_str(clicks_this, clicks_prev),
        snoops_this=to_persian_digits(snoops_this), delta_s=_delta_str(snoops_this, snoops_prev),
        xp=to_persian_int(xp), level=to_persian_digits(level),
        streak=to_persian_digits(streak), rank=rank_str, tip=tip)

def weekly_report_loop():
    """گزارش هفتگی شخصی — روز و ساعت قابل تنظیم از پنل ادمین (به وقت تهران)."""
    while True:
        try:
            enabled = db.get_setting_int("weekly_report_enabled", 1)
            if not enabled:
                time.sleep(600)
                continue
            now_t = _challenge_now_tehran()
            conf_day = db.get_setting_int("weekly_report_day", 6)     # ۰=شنبه … ۶=جمعه
            conf_hour = db.get_setting_int("weekly_report_hour", 21)  # ساعت تهران
            py_wd = _FA_WEEKDAY.get(conf_day, (None, 4))[1]
            # اگر همین الان زمان ارسال است؟
            last_sent = db.get_setting("weekly_report_last_date", "")
            if now_t.weekday() == py_wd and now_t.hour == conf_hour and last_sent != now_t.date().isoformat():
                targets = db.get_users_active_since(14)
                for uid in targets:
                    try:
                        bot.send_message(uid, _build_weekly_report_text(uid))
                    except ApiTelegramException as e:
                        if e.error_code == 403:
                            try:
                                db.mark_user_blocked_bot(uid)
                            except Exception:
                                pass
                    except Exception:
                        pass
                    time.sleep(0.05)
                db.set_setting("weekly_report_last_date", now_t.date().isoformat())
                print("📊 گزارش هفتگی ارسال شد", flush=True)
                continue
            time.sleep(60)
        except Exception as e:
            logger.error(f"weekly report loop error: {e}")
            time.sleep(120)

def fozol_week_loop():
    """v4.4: اعلان رقابتی «فضول هفته» — شنبه‌ها ساعت ۱۲:۰۰ تهران.
    قهرمان هفتهٔ گذشته (بیشترین فضول یکتای جدید) به همهٔ کاربران اعلام می‌شود:
    «علی این هفته ۱۲ فضول شکار کرد — تو چندتا؟»
    حریم خصوصی: اگر قهرمان نامش را در تابلو مخفی کرده باشد، نفر بعدی معرفی می‌شود."""
    while True:
        try:
            now_t = _challenge_now_tehran()
            last = db.get_setting("fozol_week_last", "")
            # شنبه = weekday() == 5 در پایتون؛ ساعت ۱۲ ظهر تهران
            if now_t.weekday() == 5 and now_t.hour == 12 and last != now_t.date().isoformat():
                try:
                    champ = None
                    for row in db.get_leaderboard_top_week(10):
                        # ردیف کاربران مخفی از کوئری حذف شده؛ دوباره چک می‌کنیم (حالت لبه)
                        if db.is_hide_leaderboard(row['owner_id']):
                            continue
                        champ = row
                        break
                    if champ:
                        name = sanitize_name(champ['first_name'] or "کارآگاه")
                        markup = types.InlineKeyboardMarkup(row_width=1)
                        markup.add(types.InlineKeyboardButton("👑 تالار شکارچیان", callback_data="leaderboard"))
                        markup.add(types.InlineKeyboardButton("🕳️ تلهٔ من", callback_data="my_link_show"))
                        sent = _broadcast_to_all_users(
                            texts.FOZOL_WEEK_ANNOUNCE.format(
                                name=escape_md(name), count=to_persian_digits(champ['cnt'])),
                            markup=markup)
                        print(f"🏆 Fozol-of-the-week announced: {name} ({champ['cnt']}) → {sent} users", flush=True)
                except Exception as e:
                    logger.error(f"fozol week announce error: {e}")
                db.set_setting("fozol_week_last", now_t.date().isoformat())
            time.sleep(600)
        except Exception as e:
            logger.error(f"fozol week loop error: {e}")
            time.sleep(300)


def streak_guard_loop():
    """v3.5: هشدار استریک در خطر — هر روز ساعت ۲۰:۳۰ تهران.
    به کاربرانی که دیروز فعال بودند ولی امروز فعالیتی ندارند تذکر می‌دهد
    تا استریک‌شان نیمه‌شب نشکند. هر کاربر حداکثر یک‌بار در روز."""
    while True:
        try:
            now_t = datetime.datetime.now(TEHRAN_TZ)
            last_sent = db.get_setting("streak_guard_last_date", "")
            if now_t.hour >= 20 and now_t.minute >= 30 and last_sent != now_t.date().isoformat():
                try:
                    rows = db.get_streak_at_risk_users()
                except Exception as e:
                    logger.error(f"streak guard query error: {e}")
                    rows = []
                sent = 0
                for r in rows:
                    uid = r['user_id']
                    if uid == ADMIN_ID:
                        db.set_streak_notified_date(uid)
                        continue
                    try:
                        name = sanitize_name(r['first_name'] or "کارآگاه")
                        bot.send_message(uid, texts.STREAK_AT_RISK.format(
                            name=name, streak=to_persian_digits(r['streak_count'] or 1)))
                        sent += 1
                    except ApiTelegramException as e:
                        if e.error_code == 403:
                            try:
                                db.mark_user_blocked_bot(uid)
                            except Exception:
                                pass
                    except Exception:
                        pass
                    finally:
                        try:
                            db.set_streak_notified_date(uid)
                        except Exception:
                            pass
                    time.sleep(0.05)
                db.set_setting("streak_guard_last_date", now_t.date().isoformat())
                print(f"🔥 Streak-at-risk notices sent to {sent} users", flush=True)
            time.sleep(60)
        except Exception as e:
            logger.error(f"streak guard loop error: {e}")
            time.sleep(120)

def _task_scanner_silent_sync():
    """یک‌بار در کل عمر ربات: همهٔ ماموریت‌های عقب‌افتادهٔ همهٔ کاربران بی‌صدا اعطا می‌شوند
    تا اعلان‌های جدید فقط برای تکمیل‌های واقعاً جدید ارسال شوند."""
    if db.get_setting("task_scanner_sync_done", "") == "1":
        return
    try:
        # v3.11: پرچم «قبل از پیمایش» ثبت می‌شود — اگر پروسه وسط راه مرد، استارت
        # بعدی دوباره سیل ارتقا را شروع نمی‌کند؛ کاربران عقب‌مانده هنگام بازکردن
        # صفحهٔ ماموریت‌ها به‌صورت بی‌صدا جبران می‌شوند.
        db.set_setting("task_scanner_sync_done", "1")
        with db._lock:
            uids = [r['user_id'] for r in db.conn.execute("SELECT user_id FROM users").fetchall()]
        for uid in uids:
            try:
                _check_and_award_tasks_xp(uid, notify=False)
            except Exception:
                pass
        print(f"✅ Silent task sync done for {len(uids)} users", flush=True)
    except Exception as e:
        logger.error(f"task silent sync error: {e}")

def task_scanner_loop():
    """v3.6: اعلان ماموریت در لحظهٔ انجام — هر ۶۰ ثانیه کاربران تازه‌فعال (۵ دقیقهٔ اخیر)
    بررسی می‌شوند و ماموریت‌های تازه‌تکمیل‌شده فوراً اعلام می‌شوند."""
    _task_scanner_silent_sync()
    while True:
        try:
            time.sleep(60)
            for uid in get_recently_active_users(300):
                if uid == ADMIN_ID:
                    continue
                try:
                    _check_and_award_tasks_xp(uid, notify=True)
                except Exception as e:
                    logger.error(f"task scanner user error {uid}: {e}")
        except Exception as e:
            logger.error(f"task scanner loop error: {e}")
            time.sleep(120)

# ====== وظایف دوره‌ای ======
def clean_logs_periodically():
    while True:
        time.sleep(86400)
        try: db.clean_old_anon_logs(30)
        except Exception as e: logger.error(f"Log clean error: {e}")
        # ── v3.23: بازهٔ نگهداری جداول بی‌رویه رشدکننده ──
        try: db.clean_old_callback_stats(120)   # دکمه‌های ۱۲۰ روز لمس‌نشده
        except Exception as e: logger.error(f"callback_stats clean error: {e}")
        try: db.clean_old_channel_joins(365)    # عضویت‌های قدیم‌تر از یک سال
        except Exception as e: logger.error(f"channel_joins clean error: {e}")
        try: db.usage_prune(7)                  # v3.24.4: تلمتری — نگهداری ۷ روز
        except Exception as e: logger.error(f"usage prune error: {e}")

def remind_vip_expiry():
    while True:
        time.sleep(86400)
        try:
            # --- v3.4: هشدار تمدید ۲ روز مانده (با دکمهٔ خرید) ---
            for uid in db.get_expiring_vips(days_left=2):
                try:
                    m = types.InlineKeyboardMarkup()
                    m.add(types.InlineKeyboardButton("👑 تمدید کارت طلایی", callback_data="buy_vip_menu"))
                    bot.send_message(uid, texts.RENEWAL_WARNING_2D, reply_markup=m)
                except ApiTelegramException as e:
                    if e.error_code == 403:
                        try:
                            db.mark_user_blocked_bot(uid)
                        except Exception:
                            pass
                except Exception:
                    pass
            # --- یادآوری ۱ روز مانده (موجود) ---
            expiring = db.get_expiring_vips(days_left=1)
            for uid in expiring:
                try:
                    bot.send_message(uid, texts.VIP_EXPIRY_REMINDER)
                except ApiTelegramException as e:
                    # رفع باگ: اگر کاربر ربات را بلاک کرده (403)، علامت‌گذاری کن تا دوباره ارسال نشود
                    if e.error_code == 403:
                        try:
                            db.mark_user_blocked_bot(uid)
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"VIP reminder error: {e}")

def remind_inactive_users():
    """یادآوری روزانه به کاربرانی که ۳+ روز نیستی سر زدن و کلیک جدید دارن."""
    while True:
        # هر ۲۴ ساعت یک‌بار
        time.sleep(86400)
        try:
            # پیدا کردن کاربران فعال (بلاک نشده) که ۳+ روز از آخرین فعالیتشون گذشته
            with db._lock:
                rows = db.conn.execute(
                    "SELECT user_id, last_active_date FROM users "
                    "WHERE (blocked=0 OR blocked IS NULL) AND last_active_date IS NOT NULL "
                    "AND julianday('now') - julianday(last_active_date) >= 3 "
                    "AND julianday('now') - julianday(last_active_date) <= 30"
                ).fetchall()

            for row in rows:
                uid = row['user_id']
                last_active = row['last_active_date']
                try:
                    # محاسبه کلیک‌های جدید از آخرین فعالیت
                    from datetime import date as dt_date
                    last_date = dt_date.fromisoformat(last_active)
                    today = dt_date.today()
                    days_ago = (today - last_date).days

                    click_row = db.conn.execute(
                        "SELECT COUNT(*) as c FROM clicks WHERE owner_id=? AND date(clicked_at) >= date('now', ?)",
                        (uid, f'-{days_ago} days')
                    ).fetchone()
                    new_clicks = click_row['c'] if click_row else 0

                    distinct_row = db.conn.execute(
                        "SELECT COUNT(DISTINCT clicker_id) as c FROM clicks WHERE owner_id=? AND date(clicked_at) >= date('now', ?)",
                        (uid, f'-{days_ago} days')
                    ).fetchone()
                    new_snoops = distinct_row['c'] if distinct_row else 0

                    # فقط اگه کلیک جدید داره پیام بفرست
                    if new_clicks > 0:
                        u = db.get_user_basic(uid)
                        name = u['first_name'] if u and u['first_name'] else "دوست"
                        msg = texts.INACTIVE_REMINDER.format(
                            name=escape_md(name),
                            new_clicks=to_persian_int(new_clicks),
                            new_snoops=to_persian_int(new_snoops)
                        )
                        try:
                            bot.send_message(uid, msg)
                        except ApiTelegramException as e:
                            # رفع باگ: اگر کاربر ربات را بلاک کرده (403)، علامت‌گذاری کن
                            if e.error_code == 403:
                                try:
                                    db.mark_user_blocked_bot(uid)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                except Exception as e:
                    logger.error(f"Inactive reminder error for {uid}: {e}")

            # --- v4.4: یادآور هوشمند شخصی‌سازی‌شده — بر اساس رفتار واقعی هر کاربر ---
            # (به‌جای پیام عمومی: بهترین قالب برای هر کاربر انتخاب می‌شود)
            try:
                if db.get_setting_int("smart_reminder_enabled", 1):
                    with db._lock:
                        rows2 = db.conn.execute(
                            "SELECT user_id FROM users "
                            "WHERE (blocked=0 OR blocked IS NULL) AND last_active_date IS NOT NULL "
                            "AND julianday('now') - julianday(last_active_date) >= 2 "
                            "AND julianday('now') - julianday(last_active_date) <= 14 "
                            "AND (last_remind_date IS NULL OR julianday('now') - julianday(last_remind_date) >= 3)"
                        ).fetchall()
                    for row2 in rows2:
                        uid2 = row2['user_id']
                        try:
                            u2 = db.get_user_basic(uid2)
                            name2 = escape_md(u2['first_name'] if u2 and u2['first_name'] else "دوست")
                            _is_vip2 = db.is_vip(uid2)
                            total_clicks2 = db.get_clicks_count(uid2)
                            distinct2 = db.get_distinct_snoop_count(uid2)
                            streak2 = db.get_streak(uid2) or 0
                            msg2 = None
                            markup2 = None
                            if distinct2 >= 3 and not _is_vip2:
                                # رفتار ۱: فضول‌های قفل‌شده دارد و VIP نیست → آپ‌سل هویت (فقط عدد — بدون هویت)
                                msg2 = texts.REMINDER_NEW_LOCKED.format(name=name2, count=to_persian_int(distinct2))
                                markup2 = types.InlineKeyboardMarkup()
                                markup2.add(types.InlineKeyboardButton("👑 باز کردن همه با کارت طلایی", callback_data="buy_vip_menu"))
                            elif total_clicks2 == 0:
                                # رفتار ۲: هنوز هیچ کلیکی نگرفته → آموزش پخش لینک
                                msg2 = texts.REMINDER_NEVER_SHARED.format(name=name2, link=user_link(uid2))
                            elif streak2 >= 2:
                                # رفتار ۳: استریک فعال → چرخ شانس + حفظ زنجیره
                                msg2 = texts.REMINDER_WHEEL_READY.format(name=name2, streak=to_persian_digits(streak2))
                                markup2 = types.InlineKeyboardMarkup()
                                markup2.add(types.InlineKeyboardButton("🎰 چرخاندن چرخ شانس", callback_data="wheel_info"))
                            else:
                                # فالبک: تلهٔ بی‌شکار (قالب قبلی)
                                msg2 = texts.SMART_REMINDER_NOCATCH.format(link=user_link(uid2))
                            try:
                                bot.send_message(uid2, msg2, reply_markup=markup2)
                                db.set_last_remind_date(uid2)
                            except ApiTelegramException as e:
                                if e.error_code == 403:
                                    try:
                                        db.mark_user_blocked_bot(uid2)
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                        except Exception as e:
                            logger.error(f"smart reminder error for {uid2}: {e}")
            except Exception as e:
                logger.error(f"smart reminder block error: {e}")
        except Exception as e:
            logger.error(f"Inactive reminder loop error: {e}")

def broadcast_timeout_watcher():
    global broadcast_mode, broadcast_admin_chat, broadcast_preview_msg, broadcast_started_at, broadcast_confirm_deadline
    global broadcast_inline_markup, broadcast_awaiting_buttons, broadcast_preview_sent_msg_id
    global broadcast_parse_mode, broadcast_ad_awaiting_link, broadcast_ad_link, broadcast_ad_started_at
    while True:
        time.sleep(15)
        try:
            # ── v3.19: تایم‌اوت مرحلهٔ تأیید (پیش‌نمایش داده شده ولی تأیید نشده) ──
            notify_chat = None
            with broadcast_lock:
                if (broadcast_mode and broadcast_preview_msg and broadcast_confirm_deadline
                        and time.time() > broadcast_confirm_deadline):
                    broadcast_mode = False
                    broadcast_admin_chat, notify_chat = None, broadcast_admin_chat
                    broadcast_preview_msg = None
                    broadcast_started_at = None
                    broadcast_confirm_deadline = None
                    # reset متغیرهای جدید broadcast — هم‌راستا با set_broadcast_mode(False)
                    broadcast_inline_markup = None
                    broadcast_awaiting_buttons = False
                    broadcast_preview_sent_msg_id = None
                    broadcast_parse_mode = None
            if notify_chat:
                try:
                    # جمع‌کردن کیبورد تأیید + اطلاع‌رسانی
                    bot.send_message(notify_chat, texts.BROADCAST_CONFIRM_EXPIRED,
                                     reply_markup=types.ReplyKeyboardRemove())
                except Exception:
                    pass
            # ── تایم‌اوت حالت انتظار پیام (هیچ پیش‌نمایشی ساخته نشده) ──
            with broadcast_lock:
                if broadcast_mode and broadcast_started_at and (time.time() - broadcast_started_at > BROADCAST_TIMEOUT):
                    chat_to_notify = broadcast_admin_chat
                    set_broadcast_mode(False)
                    if chat_to_notify:
                        try:
                            bot.send_message(chat_to_notify, "⏱️ حالت پخش همگانی به دلیل عدم استفاده، به‌صورت خودکار لغو شد.")
                        except:
                            pass
            # ── تایم‌اوت حالت تبلیغ (انتظار لینک از سوپرادمین) ──
            ad_notify = None
            with broadcast_lock:
                if (broadcast_ad_awaiting_link and broadcast_ad_started_at
                        and time.time() - broadcast_ad_started_at > BROADCAST_TIMEOUT):
                    broadcast_ad_awaiting_link = False
                    broadcast_ad_link = None
                    broadcast_ad_started_at = None
                    ad_notify = ADMIN_ID
            if ad_notify:
                try:
                    bot.send_message(ad_notify, "⏱️ حالت تبلیغ به دلیل ارسال نکردن لینک، خودکار لغو شد.",
                                     reply_markup=types.ReplyKeyboardRemove())
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Broadcast watcher error: {e}")

def periodic_cleanup():
    while True:
        time.sleep(300)
        now = time.time()
        # v4.7: بارگذاری مجدد کانال‌های اجباری از دیتابیس — کانال‌هایی که ادمین
        # از پنل مینی‌اپ اضافه/حذف کرده بدون ری‌استارت در اد اجباری ربات فعال شوند.
        try:
            load_channels_from_db()
        except Exception as _ch_err:
            logger.error("channels reload failed: %s", _ch_err)
        # پاک‌سازی anon_rate_vip (VIP)
        for key in list(anon_rate_vip.keys()):
            while anon_rate_vip[key] and anon_rate_vip[key][0] < now - 120:
                anon_rate_vip[key].popleft()
            if not anon_rate_vip[key]:
                del anon_rate_vip[key]
        # پاک‌سازی anon_daily_normal (کاربران عادی — نگه‌داری ۲۵ ساعت)
        for uid in list(anon_daily_normal.keys()):
            while anon_daily_normal[uid] and anon_daily_normal[uid][0] < now - 90000:
                anon_daily_normal[uid].popleft()
            if not anon_daily_normal[uid]:
                del anon_daily_normal[uid]
        for uid in list(click_rate.keys()):
            while click_rate[uid] and click_rate[uid][0] < now - 120:
                click_rate[uid].popleft()
            if not click_rate[uid]:
                del click_rate[uid]
        # پاک‌سازی gift_attempt_rate – حذف تلاش‌های قدیمی‌تر از ۲ ساعت
        for uid in list(gift_attempt_rate.keys()):
            while gift_attempt_rate[uid] and gift_attempt_rate[uid][0] < now - 7200:
                gift_attempt_rate[uid].popleft()
            if not gift_attempt_rate[uid]:
                del gift_attempt_rate[uid]
        # ── v3.19: janitor فایل‌های موقت — هیچ فایل اضافه‌ای در کانتینر/حجم Railway نماند ──
        try:
            import glob as _glob
            _cutoff = now - 3600
            _patterns = [
                str(BASE_DIR / "lb_*.png"),
                str(BASE_DIR / "restore_incoming.db"),
                str(BASE_DIR / "bot_data_old.db"),
                # v3.23: بقایای بکاپ‌ها هم هرگز روی دیسک نمی‌مانند
                str(BASE_DIR / "bot_data_backup_*.db"),
                str(BASE_DIR / "bot_data_backup_*.db.gz"),
                str(BASE_DIR / "bot_data_manual_*.db"),
                str(BASE_DIR / "bot_data_manual_*.db.gz"),
                "/tmp/lb_*.png", "/tmp/wheel*.mp4", "/tmp/wheel*.gif", "/tmp/tmp*.mp4",
            ]
            for _pat in _patterns:
                for _fp in _glob.glob(_pat):
                    try:
                        if os.path.getmtime(_fp) < _cutoff:
                            os.remove(_fp)
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"file janitor error: {e}")
        # ── v3.21: فلاش آمار ماندگار (شمارندهٔ ماه شمسی + کاربرانِ درخواست‌دهنده) ──
        try:
            flush_persisted_stats()
        except Exception as e:
            logger.error(f"stats flush error: {e}")
        # ── v3.19: گزارش حافظه (RSS) هر ~۳۰ دقیقه برای پایش Railway ──
        try:
            if int(now) % 1800 < 300:
                try:
                    import resource as _res
                    _rss = _res.getrusage(_res.RUSAGE_SELF).ru_maxrss
                except Exception:
                    _rss = 0
                print("🧠 MEMORY: rss_max=%dKB" % _rss, flush=True)
        except Exception:
            pass

threading.Thread(target=periodic_cleanup, daemon=True).start()
threading.Thread(target=clean_logs_periodically, daemon=True).start()
threading.Thread(target=remind_vip_expiry, daemon=True).start()
threading.Thread(target=broadcast_timeout_watcher, daemon=True).start()
threading.Thread(target=daily_report_loop, daemon=True).start()
threading.Thread(target=remind_inactive_users, daemon=True).start()
threading.Thread(target=nightly_backup_loop, daemon=True).start()
threading.Thread(target=challenge_loop, daemon=True).start()
threading.Thread(target=weekly_report_loop, daemon=True).start()
threading.Thread(target=streak_guard_loop, daemon=True).start()
threading.Thread(target=task_scanner_loop, daemon=True).start()
# v4.4: داوری تله — تصمیم‌های «حفظ آبرو / لو رفتن» را در ضرب‌الاجل نهایی می‌کند (بدون راه فرار)
threading.Thread(target=trap_decision_loop, daemon=True).start()
# v4.4: اعلان رقابتی «فضول هفته» — شنبه‌ها ۱۲:۰۰ تهران
threading.Thread(target=fozol_week_loop, daemon=True).start()

# BOT_START_TIME در ابتدای اجرای main تعریف می‌شود؛ اینجا fallback می‌گذاریم تا uptime_str خراب نشود
BOT_START_TIME = time.time()
def uptime_str():
    seconds = int(time.time() - BOT_START_TIME)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    return f"{to_persian_digits(days)} روز و {to_persian_digits(hours)} ساعت و {to_persian_digits(minutes)} دقیقه"
def print_startup_metrics():
    """خلاصهٔ تحلیلی استارتاپ — چاپ در لاگ برای پایش رشد/نگهداشت/درآمد."""
    try:
        import json as _json
        q = lambda sql, p=(): db.conn.execute(sql, p).fetchone()[0]
        m = {}
        # --- رشد ---
        m["users_total"] = q("SELECT COUNT(*) FROM users")
        m["users_blocked"] = q("SELECT COUNT(*) FROM users WHERE blocked=1")
        for lbl, d in (("24h",1),("7d",7),("30d",30)):
            m[f"new_{lbl}"] = q("SELECT COUNT(*) FROM users WHERE created_at >= datetime('now', ?)", (f"-{d} days",))
        # --- فعالیت (درگیر در کلیک: مالک یا کلیک‌کننده) ---
        for lbl, d in (("24h",1),("7d",7),("30d",30)):
            m[f"active_{lbl}"] = q("SELECT COUNT(*) FROM (SELECT clicker_id uid FROM clicks WHERE clicked_at >= datetime('now', ?) UNION SELECT owner_id FROM clicks WHERE clicked_at >= datetime('now', ?))", (f"-{d} days", f"-{d} days"))
        # --- سطل‌های ریزش بر اساس آخرین فعالیت ---
        m["last_act_1d"] = q("SELECT COUNT(*) FROM (SELECT clicker_id uid, MAX(clicked_at) mx FROM clicks GROUP BY clicker_id) WHERE mx >= datetime('now','-1 day')")
        m["last_act_7d"] = q("SELECT COUNT(*) FROM (SELECT clicker_id uid, MAX(clicked_at) mx FROM clicks GROUP BY clicker_id) WHERE mx >= datetime('now','-7 day')")
        m["last_act_30d"] = q("SELECT COUNT(*) FROM (SELECT clicker_id uid, MAX(clicked_at) mx FROM clicks GROUP BY clicker_id) WHERE mx >= datetime('now','-30 day')")
        m["last_act_older"] = q("SELECT COUNT(*) FROM (SELECT clicker_id uid, MAX(clicked_at) mx FROM clicks GROUP BY clicker_id) WHERE mx < datetime('now','-30 day')")
        m["never_clicked"] = q("SELECT COUNT(*) FROM users WHERE user_id NOT IN (SELECT DISTINCT clicker_id FROM clicks)")
        # --- قیف تله‌گذاری ---
        m["trap_owners_with_clicks"] = q("SELECT COUNT(DISTINCT owner_id) FROM clicks")
        m["distinct_clickers"] = q("SELECT COUNT(DISTINCT clicker_id) FROM clicks")
        m["total_clicks"] = q("SELECT COUNT(*) FROM clicks")
        for s in ("organic","welcome","referral"):
            m[f"src_{s}"] = q("SELECT COUNT(*) FROM users WHERE source=?", (s,))
        # --- نگهداشت همگنی: کاربران کلیک‌کنندهٔ جدید، بازگشت در ۷ روز بعد ---
        m["d1_return"] = q("SELECT COUNT(*) FROM (SELECT clicker_id uid, MIN(date(clicked_at)) fd FROM clicks GROUP BY clicker_id) c WHERE EXISTS (SELECT 1 FROM clicks c2 WHERE c2.clicker_id=c.uid AND date(c2.clicked_at) > c.fd AND date(c2.clicked_at) <= date(c.fd, '+1 day'))")
        m["d7_return"] = q("SELECT COUNT(*) FROM (SELECT clicker_id uid, MIN(date(clicked_at)) fd FROM clicks GROUP BY clicker_id) c WHERE EXISTS (SELECT 1 FROM clicks c2 WHERE c2.clicker_id=c.uid AND date(c2.clicked_at) > c.fd AND date(c2.clicked_at) <= date(c.fd, '+7 day'))")
        m["clickers_total"] = q("SELECT COUNT(*) FROM (SELECT DISTINCT clicker_id FROM clicks)")
        # --- درآمد ---
        m["tx_vip_total"] = q("SELECT COUNT(*) FROM transactions WHERE type='vip'")
        m["vip_buyers"] = q("SELECT COUNT(DISTINCT user_id) FROM transactions WHERE type='vip'")
        m["vip_repeat_buyers"] = q("SELECT COUNT(*) FROM (SELECT user_id FROM transactions WHERE type='vip' GROUP BY user_id HAVING COUNT(*) > 1)")
        m["revenue_total_rial"] = q("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type IN ('vip','gift_vip')")
        m["tx_gift_vip"] = q("SELECT COUNT(*) FROM transactions WHERE type='gift_vip'")
        for d_, amt in db.conn.execute("SELECT days, COUNT(*), COALESCE(SUM(amount),0) FROM transactions WHERE type='vip' GROUP BY days").fetchall():
            m[f"plan_{d_}d"] = f"{amt[1]}x {amt[2]}"
        # میانگین فاصلهٔ ثبت‌نام تا اولین خرید
        m["avg_days_to_first_buy"] = q("SELECT COALESCE(ROUND(AVG(julianday(t.ts) - julianday(u.created_at)),1),0) FROM (SELECT user_id, MIN(timestamp) ts FROM transactions WHERE type='vip' GROUP BY user_id) t JOIN users u ON u.user_id=t.user_id")
        m["active_vip_now"] = q("SELECT COUNT(*) FROM vip WHERE expire_date >= date('now')")
        # --- تعامل ---
        m["anon_msgs"] = q("SELECT COUNT(*) FROM anon_logs")
        m["nicknames_set"] = q("SELECT COUNT(*) FROM nicknames")
        m["gift_codes_used"] = q("SELECT COALESCE(SUM(used_count),0) FROM gift_codes")
        m["welcome_texts_set"] = q("SELECT COUNT(*) FROM users WHERE welcome_text IS NOT NULL")
        # --- v3.23: حجم فایل‌های دیتابیس — پایش رشد دیسک روی Railway ---
        try:
            m["db_size_mb"] = round(os.path.getsize(str(DB_PATH)) / 1048576.0, 2)
        except Exception:
            pass
        for _suf in ("-wal", "-shm"):
            try:
                _p = str(DB_PATH) + _suf
                if os.path.exists(_p):
                    m["db" + _suf.replace("-", "_") + "_mb"] = round(os.path.getsize(_p) / 1048576.0, 2)
            except Exception:
                pass
        # --- روند کلیک ۱۴ روز ---
        trend = db.conn.execute("SELECT date(clicked_at), COUNT(*) FROM clicks WHERE clicked_at >= datetime('now','-14 day') GROUP BY date(clicked_at) ORDER BY 1").fetchall()
        m["clicks_trend_14d"] = {r[0]: r[1] for r in trend}
        print("📊 STARTUP_METRICS " + _json.dumps(m, ensure_ascii=False), flush=True)
    except Exception as e:
        print(f"⚠️ startup metrics failed: {e}", flush=True)

# ====== v4.0 (fozol-pro): نقطهٔ ورود سرویس یکپارچه — run.py این تابع را صدا می‌زند ======
def start_background_tasks(bot=None):
    """همهٔ آماده‌سازی‌های استارتاپ ربات بدون polling/webhook.
    (polling یا webhook را run.py مدیریت می‌کند؛ حلقه‌های پس‌زمینهٔ سنگین مثل
    بکاپ شبانه و پاک‌سازی، در سطح ماژول main.py راه‌اندازی شده‌اند.)"""
    global BOT_START_TIME
    print(f"🚀 ربات @{BOT_USERNAME} راه‌اندازی شد (fozol-pro).", flush=True)
    BOT_START_TIME = time.time()
    print_startup_metrics()

    # ── بارگذاری کاربرانِ دارای درخواست ──
    try:
        load_requested_users()
    except Exception as _e:
        logger.error("load_requested_users error: %s", _e)

    # ── v3.24.7: اصلاح یک‌باره — کسر ۱۴ روز VIP بدون منشا (فقط بار اول) ──
    try:
        if db.get_setting("vip_correction_16339634_done", "") != "1":
            _adj = db.remove_vip_days(16339634, 14)
            db.set_setting("vip_correction_16339634_done", "1")
            db.add_transaction(16339634, "admin_vip_remove", 0, -14)
            print(f"⚖️ VIP correction: -14 days from 16339634 (result: {_adj})", flush=True)
    except Exception as _e:
        logger.error("vip correction error: %s", _e)

    # ── v3.23: تشخیص پخش همگانی نیمه‌کاره بعد از ری‌استارت/کرش ──
    try:
        _bc_st = _bc_state_read()
        if _bc_st:
            _mk_resume = types.InlineKeyboardMarkup(row_width=1)
            _mk_resume.add(
                types.InlineKeyboardButton("▶️ ادامه از محل قطع", callback_data="bc_resume_go"),
                types.InlineKeyboardButton("🗑 لغو پخش نیمه‌کاره", callback_data="bc_resume_cancel"),
            )
            bot.send_message(ADMIN_ID,
                "📢 پخش همگانی نیمه‌کاره پیدا شد (به‌خاطر ری‌استارت ربات):\n"
                f"✅ ارسال‌شده: {to_persian_digits(_bc_st.get('sent', 0) or 0)} از {to_persian_digits(_bc_st.get('total', 0) or 0)}\n"
                "می‌خواهید از همان‌جا ادامه دهید؟",
                reply_markup=_mk_resume)
            logger.info("[v3.23] unfinished broadcast detected (done=%s/%s)",
                        _bc_st.get('done', 0), _bc_st.get('total', 0))
    except Exception as _bc_err:
        logger.error("broadcast resume detect error: %s", _bc_err)

    # ── v3.11: پاک‌سازی کلیدهای کش کهنهٔ لیدربورد ──
    try:
        db.set_setting("lb_cache_sig", "")
        db.set_setting("lb_cache_fileid", "")
        print("🧹 LB: stale cache keys cleared.", flush=True)
    except Exception:
        pass

    # ── v3.9.2: خودآزمایی رندر لیدربورد ──
    try:
        if leaderboard_img and leaderboard_img.AVAILABLE:
            from PIL import features as _pilfeat
            _rq = str(_pilfeat.check("raqm"))
            _png_t = leaderboard_img._render(
                [("𓆩👑𓆪 .✧･ﾟ: ✧ 𝑀𝒶𝒽𝓉𝒶𝒷 ✧:･ﾟ✧ 𓆩👑𓆪", 10, True, False),
                 ("𝓕𝓪𝓽𝓮𝓶𝓮𝓱 🎀", 8, False, False), ("سارا محمدی", 6, False, False)],
                "خودآزمایی")
            print("🧪 LB SELFTEST: raqm=%s render=%s" % (
                _rq, "OK(%d bytes)" % len(_png_t) if _png_t else "FAILED"), flush=True)
        else:
            print("🧪 LB SELFTEST: leaderboard_img در دسترس نیست (import Pillow شکست خورده)", flush=True)
    except Exception:
        import traceback as _tb
        print("🧪 LB SELFTEST FAILED: " + _tb.format_exc(), flush=True)

    # ── v3.9.4: پیش‌تولید انیمیشن‌های چرخ شانس (نخ پس‌زمینه) ──
    threading.Thread(target=_wheel_prewarm_job, daemon=True).start()

    # ── v3.10.0: پروب زندهٔ تابلو در پس‌زمینه ──
    threading.Thread(target=_lb_live_probe, daemon=True).start()


# ====== اجرا ======
if __name__ == "__main__":
    print(f"🚀 ربات @{BOT_USERNAME} راه‌اندازی شد.", flush=True)
    BOT_START_TIME = time.time()
    print_startup_metrics()

    # ── v3.21: بارگذاری کاربرانِ دارای درخواست + لاگ شمارندهٔ ماه شمسی ──
    load_requested_users()
    # ── v3.24.7: اصلاح یک‌باره — کسر ۱۴ روز VIP بدون منشا از حساب ۱۶۳۳۹۶۳۴ ──
    # (ممیزی ۲۰۲۶-۰۹-۰۷: ۱۴ روز فراتر از فضول+تریال بدون رد پای دیتابیسی)
    try:
        if db.get_setting("vip_correction_16339634_done", "") != "1":
            _adj = db.remove_vip_days(16339634, 14)
            db.set_setting("vip_correction_16339634_done", "1")
            db.add_transaction(16339634, "admin_vip_remove", 0, -14)
            print(f"⚖️ VIP correction: -14 days from 16339634 (result: {_adj})", flush=True)
    except Exception as _e:
        logger.error("vip correction error: %s", _e)
    try:
        logger.info("[v3.21] requests this month (jalali %s): %s",
                    _current_jalali_month_key(),
                    _month_requests.current() if _month_requests else 0)
    except Exception:
        pass

    # ── v3.23: تشخیص پخش همگانی نیمه‌کاره بعد از ری‌استارت/کرش ──
    try:
        _bc_st = _bc_state_read()
        if _bc_st:
            _mk_resume = types.InlineKeyboardMarkup(row_width=1)
            _mk_resume.add(
                types.InlineKeyboardButton("▶️ ادامه از محل قطع", callback_data="bc_resume_go"),
                types.InlineKeyboardButton("🗑 لغو پخش نیمه‌کاره", callback_data="bc_resume_cancel"),
            )
            bot.send_message(ADMIN_ID,
                "📢 پخش همگانی نیمه‌کاره پیدا شد (به‌خاطر ری‌استارت ربات):\n"
                f"✅ ارسال‌شده: {to_persian_digits(_bc_st.get('sent', 0) or 0)} از {to_persian_digits(_bc_st.get('total', 0) or 0)}\n"
                "می‌خواهید از همان‌جا ادامه دهید؟",
                reply_markup=_mk_resume)
            logger.info("[v3.23] unfinished broadcast detected (done=%s/%s)",
                        _bc_st.get('done', 0), _bc_st.get('total', 0))
    except Exception as _bc_err:
        logger.error("broadcast resume detect error: %s", _bc_err)

    # ── v3.11: کش لیدربورد کاملاً حذف شد — پاک‌سازی کلیدهای کهنه از settings ──
    try:
        db.set_setting("lb_cache_sig", "")
        db.set_setting("lb_cache_fileid", "")
        print("🧹 LB: stale cache keys cleared.", flush=True)
    except Exception:
        pass

    # ── v3.9.2: خودآزمایی رندر لیدربورد (تشخیص فوری مشکل raqm/fribidi/فونت در لاگ) ──
    try:
        if leaderboard_img and leaderboard_img.AVAILABLE:
            from PIL import features as _pilfeat
            _rq = str(_pilfeat.check("raqm"))
            _png_t = leaderboard_img._render(
                [("𓆩👑𓆪 .✧･ﾟ: ✧ 𝑀𝒶𝒽𝓉𝒶𝒷 ✧:･ﾟ✧ 𓆩👑𓆪", 10, True, False),
                 ("𝓕𝓪𝓽𝓮𝓶𝓮𝓱 🎀", 8, False, False), ("سارا محمدی", 6, False, False)],
                "خودآزمایی")
            print("🧪 LB SELFTEST: raqm=%s render=%s" % (
                _rq, "OK(%d bytes)" % len(_png_t) if _png_t else "FAILED"), flush=True)
        else:
            print("🧪 LB SELFTEST: leaderboard_img در دسترس نیست (import Pillow شکست خورده)", flush=True)
    except Exception:
        import traceback as _tb
        print("🧪 LB SELFTEST FAILED: " + _tb.format_exc(), flush=True)

    # ── v3.9.4: پیش‌تولید انیمیشن‌های چرخ شانس (نخ پس‌زمینه) ──
    threading.Thread(target=_wheel_prewarm_job, daemon=True).start()

    # ── v3.10.0: پروب زندهٔ تابلو در پس‌زمینه (لاگ دادهٔ واقعی + PNG پروب) ──
    threading.Thread(target=_lb_live_probe, daemon=True).start()

    # ====== حالت Webhook (پیش‌فرض روی Railway) ======
    # اگر متغیر WEBHOOK_URL ست شده باشد → webhook؛ وگرنه polling محلی
    _webhook_url = os.environ.get("WEBHOOK_URL", "").strip()

    if _webhook_url:
        # --- حالت WEBHOOK ---
        # v3.23: استخر نخ محدود + وب‌سرور چندنخی — زیر بار انفجاری ۵۰۰۰+ کاربر،
        # به ازای هر آپدیت Thread نامحدود ساخته نمی‌شود؛ حافظه و قفل دیتابیس کنترل می‌شود.
        from concurrent.futures import ThreadPoolExecutor
        try:
            from http.server import ThreadingHTTPServer as _THServer
            from http.server import BaseHTTPRequestHandler  # v4.7: رفق NameError
        except ImportError:  # پایتون خیلی قدیمی
            from http.server import HTTPServer as _THServer
            from http.server import BaseHTTPRequestHandler
        pool_workers = max(4, int(os.environ.get("WEBHOOK_WORKERS", "16")))
        wh_pool = ThreadPoolExecutor(max_workers=pool_workers, thread_name_prefix="wh")
        print(f"🧵 webhook worker pool: {pool_workers} threads", flush=True)

        secret = os.environ.get("WEBHOOK_SECRET", "").strip()
        bot.remove_webhook()
        if secret:
            ok_wh = bot.set_webhook(url=_webhook_url, secret_token=secret,
                                    allowed_updates=["message", "callback_query", "pre_checkout_query"])
        else:
            # بدون secret — بله هدر secret نمی‌فرستد
            ok_wh = bot.set_webhook(url=_webhook_url,
                                    allowed_updates=["message", "callback_query", "pre_checkout_query"])
        print(f"🔗 webhook set → {_webhook_url} : {ok_wh}", flush=True)

        class WHHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get('Content-Length', 0))
                raw = self.rfile.read(length)
                try:
                    update = types.Update.de_json(_json_module.loads(raw.decode()))
                    hdr = (self.headers.get('X-Telegram-Bot-Api-Secret-Token') or
                           self.headers.get('X-Bale-Secret-Token') or "")
                    # اگر secret تنظیم شده باشد چک می‌شود؛ بدون secret همه قبول
                    if (not secret) or hdr == secret:
                        try:
                            wh_pool.submit(bot.process_new_updates, [update])
                        except Exception:
                            # فالبک: اگر استخر مشکل خورد، نخ عادی
                            threading.Thread(target=bot.process_new_updates,
                                             args=([update],), daemon=True).start()
                    else:
                        logger.warning(f"webhook: bad secret token")
                    self.send_response(200)
                except Exception as e:
                    logger.error(f"Webhook error: {e}")
                    try: self.send_response(200)
                    except Exception: pass
                finally:
                    try: self.end_headers()
                    except Exception: pass

            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                try:
                    self.wfile.write(b"bot is running")
                except Exception:
                    pass

            def log_message(self, fmt, *args):
                pass

        port = int(os.environ.get("PORT", "8080"))
        print(f"🌐 webhook server on :{port}", flush=True)
        _THServer(("0.0.0.0", port), WHHandler).serve_forever()
    else:
        # --- حالت POLLING (اجرای محلی) ---
        offset = None
        while True:
            try:
                updates = bot.get_updates(offset=offset, timeout=30,
                                          allowed_updates=["message", "callback_query", "pre_checkout_query"])
                for upd in updates:
                    try:
                        bot.process_new_updates([upd])
                    except Exception as e:
                        logger.error(f"Update processing error: {e}")
                    # رفع باگ: upd ممکن است آبجکت Update یا dict باشد
                    try:
                        if isinstance(upd, dict):
                            _uid = upd.get("update_id")
                        else:
                            _uid = getattr(upd, "update_id", None)
                        if _uid is not None:
                            offset = _uid + 1
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"Polling error, retrying in 5s: {e}")
                time.sleep(5)