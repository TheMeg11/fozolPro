# -*- coding: utf-8 -*-
"""
bot_sender.py — v5.0: ماژول ارسال متمرکز بله (گیت سراسری + مدیریت 429 + آمار)
================================================================================
طبق اعلان رسمی بله (ble.ir/botnews — محدودیت تعاملی):
  • نرخ پایهٔ ارسال هر ربات: ۳ پیام/ثانیه (بدون نیاز به تعامل کاربران).
  • نرخ بالاتر فقط با «ظرفیت تعاملی» مجاز است: پیام/کلیک دریافتی از کاربران
    در پنجرهٔ چندثانیه‌ای، نرخ مجاز را بالا می‌برد.
پخش همگانی با ۱۰ نخ موازی و لیمیتر ۲۵/ثانیه، حلقه‌های اعلان بدون وقفه
(۲۰ پیام/ثانیه) و پردازش موازی وب‌هوک این سقف را می‌شکست ← ارور ظرفیت تعاملی.

این ماژول «یک نقطهٔ کنترل» برای همهٔ ارسال‌های خروجی است و از دو مسیر عبور می‌کند:
  ۱) patch موجود apihelper._make_request در main.py → کل مسیر telebot
     (ربات اصلی، پخش همگانی، حلقه‌های پس‌زمینه، بکاپ، چرخ شانس، ...)
  ۲) services/bale_api.call → ارسال‌های API مینی‌اپ (فاکتور، پیام، فایل)

امکانات:
  • گیت سراسری توکن-باکت برای «پیام‌ساز» ها: پیش‌فرض ۲.۵/ثانیه + burst=۳
    (زیر سقف رسمی ۳/ثانیه؛ توصیهٔ بله برای پخش همگانی: ارسال در طول زمان)
  • گیت سبک برای ادیت/حذف/تایپینگ (۱۰/ثانیه) — پیام جدید نمی‌سازند و در
    ظرفیت تعاملی حساب نمی‌شوند
  • فاصلهٔ حداقلی بین دو «ارسال پیام» به یک چت (۰.۷۵ ثانیه)
  • مدیریت 429 در همهٔ فراخوانی‌ها: خواندن retry_after از پاسخ بله،
    تلاش مجدد تا ۵ بار + سردکردن تطبیقی نرخ سراسری (نصف شدن تا ۱۲۰ ثانیه)
  • آمار لحظه‌ای (ارسال/ادیت/429/انتظار) + لاک دوره‌ای هر ۵ دقیقه
  • متدهای خواندنی (getUpdates، getChat، answerCallbackQuery، ...) از گیت
    عبور می‌کنند تا تجربهٔ کاربر و polling کند نشود — فقط retry 429 دارند

همهٔ مقادیر با متغیر محیطی قابل تنظیم‌اند؛ پیش‌فرض‌ها امن‌اند و نیازی به تغییر
تنظیمات Railway نیست:
  SEND_GATE_RATE_PER_SEC (2.5)   SEND_GATE_BURST (3)
  SEND_GATE_EDIT_RATE_PER_SEC (10)  SEND_GATE_EDIT_BURST (10)
  SEND_GATE_PER_CHAT_SEC (0.75)  SEND_429_MAX_RETRIES (5)
  SEND_429_DEFAULT_WAIT (3)      SEND_GATE_429_COOLDOWN (120)  SEND_GATE_429_FACTOR (0.5)
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque

log = logging.getLogger("sender")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, "") or default))
    except (TypeError, ValueError):
        return default


# ─── تنظیمات (پیش‌فرض = زیر سقف رسمی بله) ───
RATE_PER_SEC = max(0.5, _env_float("SEND_GATE_RATE_PER_SEC", 2.5))          # پیام/ثانیه
BURST = max(1, _env_int("SEND_GATE_BURST", 3))                              # ظرف لحظه‌ای
EDIT_RATE_PER_SEC = max(1.0, _env_float("SEND_GATE_EDIT_RATE_PER_SEC", 10.0))
EDIT_BURST = max(1, _env_int("SEND_GATE_EDIT_BURST", 10))
PER_CHAT_SEC = max(0.0, _env_float("SEND_GATE_PER_CHAT_SEC", 0.75))         # فاصلهٔ هر چت
MAX_429_RETRIES = max(0, _env_int("SEND_429_MAX_RETRIES", 5))
DEFAULT_429_WAIT = max(0.5, _env_float("SEND_429_DEFAULT_WAIT", 3.0))
COOLDOWN_SEC = max(5.0, _env_float("SEND_GATE_429_COOLDOWN", 120.0))
COOLDOWN_FACTOR = min(1.0, max(0.1, _env_float("SEND_GATE_429_FACTOR", 0.5)))
STATS_LOG_SEC = max(30.0, _env_float("SEND_STATS_LOG_SEC", 300.0))

# متدهایی که «پیام جدید» می‌سازند → گیت کامل (این‌ها در ظرفیت تعاملی بله حساب می‌شوند)
_SEND_METHODS = {
    "sendMessage", "sendPhoto", "sendVideo", "sendAnimation", "sendAudio",
    "sendVoice", "sendVideoNote", "sendDocument", "sendSticker", "sendLocation",
    "sendVenue", "sendContact", "sendPoll", "sendDice", "sendMediaGroup",
    "sendInvoice", "copyMessage", "forwardMessage",
}
# متدهای سبک: پیام جدید نمی‌سازند (ادیت/حذف/تایپینگ) → گیت بازتر
_LIGHT_METHODS = {
    "editMessageText", "editMessageCaption", "editMessageReplyMarkup",
    "editMessageLiveLocation", "stopMessageLiveLocation", "deleteMessage",
    "sendChatAction", "setChatTitle", "pinChatMessage", "unpinChatMessage",
}


class RateLimited(Exception):
    """نشانگر 429 برای مسیرهای خارج از telebot (services/bale_api).
    پس از اتمام تلاش‌ها هم همین خطا بالا می‌رود تا caller آن را به خطای
    خودش تبدیل کند."""

    def __init__(self, retry_after: float | None = None, description: str = ""):
        self.retry_after = retry_after
        self.description = description
        super().__init__(f"bale rate limited (retry_after={retry_after}) {description}"[:200])


def _is_rate_limit(exc: BaseException) -> bool:
    if isinstance(exc, RateLimited):
        return True
    if getattr(exc, "error_code", None) == 429:
        return True
    resp = getattr(exc, "response", None)
    if getattr(resp, "status_code", None) == 429:
        return True
    return False


def _retry_after_of(exc: BaseException) -> float | None:
    """استخراج retry_after از پاسخ بله (اگر ارسال شده باشد)."""
    v = getattr(exc, "retry_after", None)
    if v is not None:
        try:
            return max(0.5, float(v))
        except (TypeError, ValueError):
            pass
    rj = getattr(exc, "result_json", None)
    if isinstance(rj, dict):
        try:
            ra = (rj.get("parameters") or {}).get("retry_after")
            if ra is not None:
                return max(0.5, float(ra))
        except (TypeError, ValueError):
            pass
    return None


class _TokenBucket:
    """توکن-باکت thread-safe با نرخ تطبیقی: پس از هر 429 تا پایان دورهٔ
    سردی، نرخ موقتاً در COOLDOWN_FACTOR ضرب می‌شود (کف ۰.۵/ثانیه)."""

    def __init__(self, rate: float, burst: int):
        self._base_rate = float(rate)
        self._burst = float(burst)
        self._tokens = float(burst)
        self._ts = time.monotonic()
        self._cooldown_until = 0.0
        self._cond = threading.Condition()

    def _rate(self) -> float:
        if time.monotonic() < self._cooldown_until:
            return max(0.5, self._base_rate * COOLDOWN_FACTOR)
        return self._base_rate

    def acquire(self, tokens: float = 1.0) -> None:
        with self._cond:
            while True:
                now = time.monotonic()
                rate = self._rate()
                self._tokens = min(self._burst, self._tokens + (now - self._ts) * rate)
                self._ts = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                wait = (tokens - self._tokens) / max(rate, 0.1) + 0.002
                self._cond.wait(timeout=min(wait, 5.0))

    def trigger_cooldown(self, seconds: float | None = None) -> None:
        with self._cond:
            self._cooldown_until = max(
                self._cooldown_until, time.monotonic() + (seconds or COOLDOWN_SEC)
            )
            self._cond.notify_all()


_bucket = _TokenBucket(RATE_PER_SEC, BURST)
_light_bucket = _TokenBucket(EDIT_RATE_PER_SEC, EDIT_BURST)


class _ChatPacer:
    """حداقل فاصلهٔ بین دو «ارسال پیام جدید» به یک چت — ضد اسپم یک کاربر."""

    def __init__(self, min_interval: float):
        self._min = float(min_interval)
        self._lock = threading.Lock()
        self._last: dict[str, float] = {}

    def wait(self, chat_id) -> None:
        if not self._min or chat_id is None:
            return
        key = str(chat_id)
        while True:
            with self._lock:
                now = time.monotonic()
                last = self._last.get(key, 0.0)
                if now - last >= self._min:
                    self._last[key] = now
                    if len(self._last) > 8192:  # هرس گاه‌به‌گاه (حافظهٔ سالم)
                        cutoff = now - 3600.0
                        self._last = {k: v for k, v in self._last.items() if v > cutoff}
                    return
                need = self._min - (now - last)
            time.sleep(min(need, 5.0))


_chat_pacer = _ChatPacer(PER_CHAT_SEC)


def _chat_of(params: dict | None):
    """chat_id را از پارامترهای درخواست برمی‌دارد (int/str هر دو ممکن‌اند)."""
    if not isinstance(params, dict):
        return None
    v = params.get("chat_id")
    if v is None:
        return None
    if isinstance(v, (int, str)):
        s = str(v).strip()
        if s:
            return s
    return None


# ─── آمار ───
class _Stats:
    def __init__(self):
        self._lock = threading.Lock()
        self.sent = 0
        self.edits = 0
        self.hits_429 = 0
        self.errors = 0
        self.wait_total = 0.0
        self.wait_max = 0.0
        self.send_ts: deque = deque()  # مهر زمانی ارسال‌های موفق (پنجرهٔ ۶۰ثانیه)

    def note_wait(self, waited: float) -> None:
        with self._lock:
            self.wait_total += waited
            if waited > self.wait_max:
                self.wait_max = waited

    def note_ok(self, is_send: bool) -> None:
        with self._lock:
            if is_send:
                self.sent += 1
                self.send_ts.append(time.monotonic())
            else:
                self.edits += 1

    def note_429(self) -> None:
        with self._lock:
            self.hits_429 += 1

    def note_error(self) -> None:
        with self._lock:
            self.errors += 1

    def snapshot(self) -> dict:
        with self._lock:
            now = time.monotonic()
            while self.send_ts and self.send_ts[0] < now - 60.0:
                self.send_ts.popleft()
            return {
                "sent": self.sent, "edits": self.edits, "429": self.hits_429,
                "errors": self.errors, "wait_avg": self.wait_total / max(1, self.sent + self.edits),
                "wait_max": self.wait_max, "rate60": len(self.send_ts),
            }


_stats = _Stats()


def stats_text() -> str:
    """خلاصهٔ آمار sender — برای /usage ادمین."""
    s = _stats.snapshot()
    return (
        f"📨 ارسال: {s['sent']} | ادیت: {s['edits']} | 429: {s['429']} | خطا: {s['errors']}\n"
        f"⏱️ انتظار گیت: میانگین {s['wait_avg']:.2f}s | بیشینه {s['wait_max']:.2f}s | "
        f"نرخ ۶۰ثانیهٔ اخیر: {s['rate60']} پیام/دقیقه"
    )


def _stats_logger() -> None:
    while True:
        time.sleep(STATS_LOG_SEC)
        s = _stats.snapshot()
        if s["sent"] or s["edits"] or s["429"]:
            log.info(
                "[sender] sent=%d edits=%d 429=%d errors=%d wait_avg=%.2fs wait_max=%.2fs rate60=%d/min "
                "(gate=%.1f/s burst=%d)",
                s["sent"], s["edits"], s["429"], s["errors"], s["wait_avg"], s["wait_max"],
                s["rate60"], RATE_PER_SEC, BURST,
            )


threading.Thread(target=_stats_logger, daemon=True, name="sender-stats").start()


def normalize_method(method) -> str:
    """«sendMessage» از آدرس‌های هم شکل (مثل bot<token>/sendMessage) جدا می‌کند."""
    if not method:
        return ""
    return str(method).rstrip("/").split("/")[-1]


def gated(do_call, method, params: dict | None = None):
    """قلب ماژول — همهٔ فراخوانی‌های API بله باید از اینجا عبور کنند:

    ۱) طبقه‌بندی متد (پیام‌ساز / سبک / خواندنی)
    ۲) گیت مربوطه (توکن-باکت سراسری + فاصلهٔ چت برای پیام‌سازها)
    ۳) اجرا؛ در 429: خواندن retry_after، سرد کردن گیت، صبر و تلاش مجدد
    ۴) پس از اتمام تلاش‌ها همان خطای اصلی بالا می‌رود تا رفتار caller
       عیناً مثل قبل بماند (مثلاً تشخیص 403=بلاک در پخش همگانی).

    do_call: تابع بدون آرگومان که درخواست واقعی را می‌زند.
    """
    m = normalize_method(method)
    is_send = m in _SEND_METHODS
    is_light = m in _LIGHT_METHODS

    attempt = 0
    while True:
        t0 = time.monotonic()
        if is_send:
            _chat_pacer.wait(_chat_of(params))
            _bucket.acquire()
        elif is_light:
            _light_bucket.acquire()
        _stats.note_wait(time.monotonic() - t0)
        try:
            result = do_call()
            _stats.note_ok(is_send)
            return result
        except Exception as exc:
            if not _is_rate_limit(exc):
                _stats.note_error()
                raise
            attempt += 1
            _stats.note_429()
            if is_send or is_light:
                # 429 یعنی حتی نرخ فعلی هم زیاد بوده → سرد کردن تطبیقی گیت
                _bucket.trigger_cooldown()
                _light_bucket.trigger_cooldown()
            ra = _retry_after_of(exc)
            wait = ra if ra is not None else min(DEFAULT_429_WAIT * (2 ** (attempt - 1)), 60.0)
            if attempt <= MAX_429_RETRIES:
                log.warning(
                    "[sender] 429 روی %s (تلاش %d از %d) — %.1fs صبر و تکرار",
                    m, attempt, MAX_429_RETRIES, wait,
                )
                time.sleep(wait)
                continue
            log.error("[sender] 429 روی %s حتی پس از %d تلاش — خطا به caller واگذار شد", m, attempt)
            raise
