# -*- coding: utf-8 -*-
"""
bot_sender.py — v5.1: کنترل نرخ ارسال بله با «اولویت» + توقف سراسری هوشمند
================================================================================
طبق اعلان رسمی بله (ble.ir/botnews — محدودیت تعاملی):
  • نرخ پایهٔ ارسال هر ربات: ۳ پیام/ثانیه (بدون نیاز به تعامل کاربران).
  • نرخ بالاتر فقط با «ظرفیت تعاملی» مجاز است: پیام/کلیک دریافتی از کاربران
    در پنجرهٔ چندثانیه‌ای، نرخ مجاز را بالا می‌برد.

── چرا v5.0 کافی نبود (بر اساس لاگ واقعی Railway) ──
لاگ نشان می‌داد با گیت ۲.۵/ثانیه هم ربات در طوفان ۴۲۹ غرق می‌شود:
  • ۲۸۸ هشدار «۴۲۹ … صبر و تکرار» (retry_after از ۶ تا ۵۳ ثانیه)
  • throughput واقعی فقط ~۶ پیام در دقیقه (در برابر ۱۵۰ پیام/دقیقهٔ اسمی)
  • ۴۶ خطای «query is too old» = کالبک‌ها بعد از ۳۰ ثانیه جواب می‌گرفتند
سه ریشهٔ اصلی:
  ۱) هر ۴۲۹ انتظارِ retry_after را **درجا داخل نخ هندلر** می‌خوابانید؛ با ۴ نخ
     هندلر، کل ربات (getUpdates) قفل می‌شد → «پیام دریافت نمی‌کند».
  ۲) هیچ «توقف سراسری» نبود؛ ۴-۵ نخ هم‌زمان تلاش مجدد می‌کردند (thundering
     herd) و جریمهٔ بله را دوباره و دوباره تمدید می‌کردند.
  ۳) گیت هیچ اولویتی نداشت؛ پخش همگانی و حلقه‌های پس‌زمینه همان سطل پاسخ‌های
     تعاملی کاربر را می‌خوردند → «پاسخ‌ها دیر می‌آید».

── مدل v5.1 ──
  • سه سطح اولویت: high (پاسخ به کاربر) > normal (اعلان‌ها) > bulk (پخش همگانی)
    - bulk هرگز توکن نمی‌گیرد اگر حتی یک درخواست high/normal در صف باشد.
    - bulk سقف نرخ جداگانه دارد (پیش‌فرض ۱/ثانیه) تا ظرفیت پاسخ‌دهی آزاد بماند.
  • توقف سراسری (global flood pause): هر ۴۲۹ با retry_after، همهٔ مسیرها را
    (به‌جز خواندنی‌ها) تا پایان پنجره متوقف می‌کند؛ هیچ تلاش موازی‌ای در آن
    پنجره انجام نمی‌شود → جریمه تمدید نمی‌شود.
  • بودجهٔ انتظار محدود (inline budget):
    - high/normal: ۱۰ ثانیه (پیش‌فرض) — بیشتر از این، سریع شکست می‌خورد تا
      نخ هندلر آزاد بماند و ربات از دسترس خارج نشود.
    - bulk: ۱۰ دقیقه — پخش همگانی می‌تواند صبر کند (چون نخ هندلر نیست).
  • سردشدن تطبیقی با بازیابی تدریجی: هر پنجرهٔ سردی نرخ را ۲۵٪ کم می‌کند
    (کف ۵۰٪) و بعد از پایان پنجره، هر ۳۰ ثانیه ۱۰٪ به نرخ اضافه می‌شود.
    (v5.0 هر ۴۲۹ را «now+120s» می‌کرد و نرخ هیچ‌وقت برنمی‌گشت.)
  • متدهای خواندنی (getUpdates/getChat/answerCallbackQuery/…) گیت نرخ ندارند؛
    فقط ۴۲۹ آن‌ها با بودجهٔ کوتاه مدیریت می‌شود تا polling کند نشود.
  • ۴۰۳ (کاربر ربات را بلاک کرده) و ۴۰۰ هرگز تلاش مجدد نمی‌شوند.

تنظیمات (همهٔ متغیرهای محیطی؛ پیش‌فرض‌ها زیر سقف رسمی بله‌اند):
  SEND_GATE_RATE_PER_SEC=2.0      نرخ کل پیام‌سازها (پاسخ تعاملی + اعلان + پخش)
  SEND_GATE_BURST=3               ظرف لحظه‌ای
  SEND_BULK_RATE_PER_SEC=1.0      سقف نرخ لِین پخش همگانی (زیر نرخ پایهٔ بله)
  SEND_GATE_EDIT_RATE_PER_SEC=4   نرخ ادیت/حذف/تایپینگ
  SEND_GATE_PER_CHAT_SEC=1.0      حداقل فاصلهٔ دو پیام جدید به یک چت
  SEND_INLINE_MAX_WAIT=10         بودجهٔ انتظار پاسخ تعاملی (ثانیه)
  SEND_BULK_MAX_WAIT=600          بودجهٔ انتظار لِین پخش (ثانیه)
  SEND_429_MAX_RETRIES=4          سقف تلاش مجدد هر فراخوانی
  SEND_429_MAX_PAUSE=120          سقف توقف سراسری به‌خاطر یک 429 (ثانیه)
  SEND_GATE_429_COOLDOWN=60       طول پنجرهٔ سردی (ثانیه)
"""
from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
from collections import deque

log = logging.getLogger("sender")

HIGH, NORMAL, BULK = "high", "normal", "bulk"


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
RATE_PER_SEC = max(0.5, _env_float("SEND_GATE_RATE_PER_SEC", 2.0))            # پیام/ثانیه (کل)
BURST = max(1, _env_int("SEND_GATE_BURST", 3))
BULK_RATE_PER_SEC = max(0.2, _env_float("SEND_BULK_RATE_PER_SEC", 1.0))
EDIT_RATE_PER_SEC = max(1.0, _env_float("SEND_GATE_EDIT_RATE_PER_SEC", 4.0))
EDIT_BURST = max(1, _env_int("SEND_GATE_EDIT_BURST", 4))
PER_CHAT_SEC = max(0.0, _env_float("SEND_GATE_PER_CHAT_SEC", 1.0))            # فاصلهٔ هر چت
MAX_429_RETRIES = max(0, _env_int("SEND_429_MAX_RETRIES", 4))
DEFAULT_429_WAIT = max(0.5, _env_float("SEND_429_DEFAULT_WAIT", 3.0))
MAX_429_PAUSE = max(5.0, _env_float("SEND_429_MAX_PAUSE", 120.0))
COOLDOWN_SEC = max(5.0, _env_float("SEND_GATE_429_COOLDOWN", 60.0))
COOLDOWN_FACTOR = min(1.0, max(0.2, _env_float("SEND_GATE_429_FACTOR", 0.75)))  # ضریب هر پنجره
MIN_FACTOR = min(1.0, max(0.1, _env_float("SEND_GATE_MIN_FACTOR", 0.5)))       # کف (۵۰٪ نرخ پایه)
RECOVERY_STEP_SEC = max(10.0, _env_float("SEND_GATE_RECOVERY_SEC", 30.0))
RECOVERY_STEP = min(1.0, max(0.01, _env_float("SEND_GATE_RECOVERY_STEP", 0.1)))
INLINE_BUDGET = max(1.0, _env_float("SEND_INLINE_MAX_WAIT", 10.0))            # پاسخ تعاملی
BULK_BUDGET = max(30.0, _env_float("SEND_BULK_MAX_WAIT", 600.0))              # لِین پخش
READ_BUDGET = max(1.0, _env_float("SEND_READ_MAX_WAIT", 6.0))                 # خواندنی‌ها
STATS_LOG_SEC = max(60.0, _env_float("SEND_STATS_LOG_SEC", 300.0))

# متدهایی که «پیام جدید» می‌سازند → گیت کامل (در ظرفیت تعاملی بله حساب می‌شوند)
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
    """۴۲۹ بله (یا اتمام بودجهٔ انتظار) برای مسیرهایی که از telebot نمی‌آیند.

    caller این خطا را به خطای خودش تبدیل می‌کند؛ متنش کوتاه است تا در لاگ نیاید.
    """

    def __init__(self, retry_after: float | None = None, description: str = ""):
        self.retry_after = retry_after
        self.description = description
        super().__init__(f"bale rate limited (retry_after={retry_after}) {description}"[:200])


class _BudgetExhausted(RateLimited):
    """بودجهٔ انتظار تمام شد — عمداً سریع شکست می‌خوریم تا نخ هندلر آزاد بماند."""


# ─── اولویت هر نخ (high برای هندلرها، bulk برای پخش همگانی) ───
_tls = threading.local()


def set_priority(level: str | None) -> None:
    _tls.priority = level


def get_priority() -> str:
    lvl = getattr(_tls, "priority", None)
    return lvl if lvl in (HIGH, NORMAL, BULK) else NORMAL


@contextlib.contextmanager
def priority(level: str):
    """`with bot_sender.priority(bot_sender.BULK): ...` — همهٔ ارسال‌های این نخ."""
    old = getattr(_tls, "priority", None)
    _tls.priority = level
    try:
        yield
    finally:
        _tls.priority = old


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


def _is_retryable(exc: BaseException) -> bool:
    """فقط 429 (و خطای شبکه که خود telebot مدیریت می‌کند) مستحق تلاش مجدد است.

    ۴۰۳ «bot was blocked by the user» و ۴۰۰ «query is too old» تکرارپذیر نیستند؛
    v5.0 آن‌ها را هم دوباره تلاش می‌کرد و فقط صف را شلوغ می‌کرد.
    """
    return _is_rate_limit(exc)


# ─── گیت ───
class _Gate:
    """توکن-باکت thread-safe با اولویت، توقف سراسری و نرخ تطبیقی خودبازیاب."""

    def __init__(self, rate: float, burst: int, bulk_rate: float | None = None):
        self._base_rate = float(rate)
        self._burst = float(burst)
        self._tokens = float(burst)
        self._ts = time.monotonic()
        self._bulk_base = float(bulk_rate or rate)
        self._bulk_tokens = 1.0
        self._factor = 1.0
        self._cooldown_until = 0.0
        self._recover_at = 0.0
        self._pause_until = 0.0
        self._waiting = {HIGH: 0, NORMAL: 0, BULK: 0}
        self._cond = threading.Condition()

    # --- داخلی (فقط با قفل گرفته‌شده) ---
    def _rate(self, now: float) -> float:
        if now < self._cooldown_until:
            return max(0.5, self._base_rate * self._factor)
        # بازیابی تدریجی پس از پایان پنجرهٔ سردی
        if self._factor < 1.0 and now >= self._recover_at:
            self._factor = min(1.0, self._factor + RECOVERY_STEP)
            self._recover_at = now + RECOVERY_STEP_SEC
        return max(0.5, self._base_rate * self._factor)

    def acquire(self, deadline: float, level: str = NORMAL, tokens: float = 1.0) -> None:
        """توکن می‌گیرد یا _BudgetExhausted می‌دهد (هرگز بیشتر از بودجه نمی‌خوابد)."""
        is_bulk = level == BULK
        with self._cond:
            self._waiting[level] += 1
            try:
                while True:
                    now = time.monotonic()
                    # ۱) توقف سراسری ۴۲۹
                    if now < self._pause_until:
                        left = self._pause_until - now
                        if now + left > deadline:
                            raise _BudgetExhausted(left, "global flood pause")
                        self._cond.wait(timeout=min(left, 1.0))
                        continue
                    # ۲) شارژ
                    prev_ts = self._ts
                    rate = self._rate(now)
                    self._tokens = min(self._burst, self._tokens + max(0.0, now - prev_ts) * rate)
                    self._ts = now
                    self._bulk_tokens = min(
                        float(BURST), self._bulk_tokens + max(0.0, now - prev_ts) * min(self._bulk_base, rate)
                    )
                    # ۳) اولویت: high > normal > bulk
                    if is_bulk:
                        blocked = self._waiting[HIGH] or self._waiting[NORMAL]
                        if not blocked and self._bulk_tokens >= tokens and self._tokens >= tokens:
                            self._bulk_tokens -= tokens
                            self._tokens -= tokens
                            return
                    else:
                        if (level == HIGH or not self._waiting[HIGH]) and self._tokens >= tokens:
                            self._tokens -= tokens
                            return
                    # ۴) انتظار
                    if now >= deadline:
                        raise _BudgetExhausted(None, "gate budget exhausted")
                    if is_bulk:
                        need = max(0.0, (tokens - self._bulk_tokens) / max(self._bulk_base, 0.1))
                    else:
                        need = (tokens - self._tokens) / max(self._rate(now), 0.1)
                    self._cond.wait(timeout=max(0.05, min(need + 0.005, max(0.05, deadline - now), 5.0)))
            finally:
                self._waiting[level] -= 1

    def note_429(self, retry_after: float | None) -> float:
        """توقف سراسری + سردکردن تطبیقی. مقدار توقف (ثانیه) را برمی‌گرداند."""
        with self._cond:
            now = time.monotonic()
            pause = min(MAX_429_PAUSE, max(1.0, float(retry_after or DEFAULT_429_WAIT)))
            if now >= self._cooldown_until:
                self._factor = max(MIN_FACTOR, self._factor * COOLDOWN_FACTOR)
            self._cooldown_until = max(self._cooldown_until, now + COOLDOWN_SEC)
            self._recover_at = self._cooldown_until
            self._pause_until = max(self._pause_until, now + pause)
            self._tokens = 0.0
            self._bulk_tokens = 0.0
            self._ts = now
            self._cond.notify_all()
            return pause

    def pause_left(self) -> float:
        with self._cond:
            return max(0.0, self._pause_until - time.monotonic())

    def snapshot(self) -> dict:
        with self._cond:
            return {
                "tokens": round(self._tokens, 2), "factor": round(self._factor, 2),
                "pause_left": round(max(0.0, self._pause_until - time.monotonic()), 1),
                "waiting": dict(self._waiting),
            }


_gate = _Gate(RATE_PER_SEC, BURST, BULK_RATE_PER_SEC)
_light_gate = _Gate(EDIT_RATE_PER_SEC, EDIT_BURST, BULK_RATE_PER_SEC)


class _ChatPacer:
    """حداقل فاصلهٔ بین دو «ارسال پیام جدید» به یک چت — ضد اسپم یک کاربر."""

    def __init__(self, min_interval: float):
        self._min = float(min_interval)
        self._lock = threading.Lock()
        self._last: dict[str, float] = {}

    def wait(self, chat_id, deadline: float | None = None) -> None:
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
            if deadline is not None and time.monotonic() + need > deadline:
                raise _BudgetExhausted(need, "chat pacer")
            time.sleep(min(need, 1.0))


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
        self.fast_fails = 0
        self.wait_total = 0.0
        self.wait_max = 0.0
        self.last_pause = 0.0
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

    def note_429(self, pause: float = 0.0) -> None:
        with self._lock:
            self.hits_429 += 1
            if pause:
                self.last_pause = pause

    def note_error(self) -> None:
        with self._lock:
            self.errors += 1

    def note_fast_fail(self) -> None:
        with self._lock:
            self.fast_fails += 1

    def snapshot(self) -> dict:
        with self._lock:
            now = time.monotonic()
            while self.send_ts and self.send_ts[0] < now - 60.0:
                self.send_ts.popleft()
            total = max(1, self.sent + self.edits)
            return {
                "sent": self.sent, "edits": self.edits, "429": self.hits_429,
                "errors": self.errors, "fast_fails": self.fast_fails,
                "wait_avg": self.wait_total / total, "wait_max": self.wait_max,
                "rate60": len(self.send_ts), "last_pause": self.last_pause,
            }


_stats = _Stats()


def stats_text() -> str:
    """خلاصهٔ آمار sender — برای /usage ادمین."""
    s = _stats.snapshot()
    g = _gate.snapshot()
    return (
        f"📨 ارسال: {s['sent']} | ادیت: {s['edits']} | 429: {s['429']} | خطا: {s['errors']}"
        f" | رد سریع: {s['fast_fails']}\n"
        f"⏱️ انتظار گیت: میانگین {s['wait_avg']:.2f}s | بیشینه {s['wait_max']:.2f}s | "
        f"نرخ ۶۰ثانیهٔ اخیر: {s['rate60']} پیام/دقیقه\n"
        f"🚦 گیت: نرخ {RATE_PER_SEC:.1f}/s (ضریب {g['factor']:.2f}) | توقف باقی‌مانده "
        f"{g['pause_left']:.1f}s | صف: {g['waiting']}"
    )


def _stats_logger() -> None:
    while True:
        time.sleep(STATS_LOG_SEC)
        s = _stats.snapshot()
        if s["sent"] or s["edits"] or s["429"]:
            g = _gate.snapshot()
            log.info(
                "[sender] sent=%d edits=%d 429=%d errors=%d fast_fail=%d wait_avg=%.2fs "
                "wait_max=%.2fs rate60=%d/min gate=%.1f/s factor=%.2f pause=%.1fs queue=%s",
                s["sent"], s["edits"], s["429"], s["errors"], s["fast_fails"],
                s["wait_avg"], s["wait_max"], s["rate60"], RATE_PER_SEC,
                g["factor"], g["pause_left"], g["waiting"],
            )


threading.Thread(target=_stats_logger, daemon=True, name="sender-stats").start()


def normalize_method(method) -> str:
    """«sendMessage» از آدرس‌های هم شکل (مثل bot<token>/sendMessage) جدا می‌کند."""
    if not method:
        return ""
    return str(method).rstrip("/").split("/")[-1]


def _budget_for(level: str) -> float:
    if level == BULK:
        return BULK_BUDGET
    return INLINE_BUDGET


def gated(do_call, method, params: dict | None = None, level: str | None = None):
    """قلب ماژول — همهٔ فراخوانی‌های API بله باید از اینجا عبور کنند:

    ۱) طبقه‌بندی متد (پیام‌ساز / سبک / خواندنی) + اولویت نخ
    ۲) گرفتن توکن با اولویت (high > normal > bulk) — bulk هرگز جلوی کاربر را نمی‌گیرد
    ۳) اجرا؛ در ۴۲۹: توقف سراسری + تلاش مجدد **داخل بودجهٔ زمانی**
    ۴) خروج از بودجه = خطای سریع (نه خوابِ دقیقه‌ای در نخ هندلر)

    do_call: تابع بدون آرگومان که درخواست واقعی را می‌زند.
    level:   high | normal | bulk (پیش‌فرض: سطح نخ جاری)
    """
    m = normalize_method(method)
    is_send = m in _SEND_METHODS
    is_light = m in _LIGHT_METHODS
    lvl = level or get_priority()
    if lvl not in (HIGH, NORMAL, BULK):
        lvl = NORMAL

    # ── متدهای خواندنی: گیت نرخ ندارند (polling و پاسخ کالبک هرگز صف نمی‌شوند) ──
    if not (is_send or is_light):
        deadline = time.monotonic() + min(READ_BUDGET, MAX_429_PAUSE)
        attempt = 0
        while True:
            try:
                return do_call()
            except Exception as exc:
                if not _is_retryable(exc):
                    raise
                attempt += 1
                _stats.note_429()
                pause = _gate.note_429(_retry_after_of(exc))
                _light_gate.note_429(pause)
                if attempt > min(2, MAX_429_RETRIES) or time.monotonic() + pause > deadline:
                    raise
                time.sleep(min(pause, max(0.0, deadline - time.monotonic())))

    deadline = time.monotonic() + _budget_for(lvl)
    chat_key = _chat_of(params) if is_send else None
    attempt = 0
    while True:
        t0 = time.monotonic()
        try:
            if is_send:
                _chat_pacer.wait(chat_key, deadline)
                _gate.acquire(deadline, lvl)
            else:
                _light_gate.acquire(deadline, lvl)
        except _BudgetExhausted as exc:
            _stats.note_fast_fail()
            raise RateLimited(exc.retry_after, f"budget exhausted on {m}") from None
        _stats.note_wait(time.monotonic() - t0)
        try:
            result = do_call()
            _stats.note_ok(is_send)
            return result
        except Exception as exc:
            if not _is_retryable(exc):
                _stats.note_error()
                raise
            attempt += 1
            ra = _retry_after_of(exc)
            pause = _gate.note_429(ra)
            _light_gate.note_429(pause)
            _stats.note_429(pause)
            left = deadline - time.monotonic()
            if attempt > MAX_429_RETRIES or left <= 0.5 or pause > left:
                _stats.note_fast_fail()
                log.warning(
                    "[sender] 429 روی %s — توقف %.0fs از بودجهٔ %.0fs بیشتر است؛ رد سریع (نخ آزاد می‌ماند)",
                    m, pause, _budget_for(lvl),
                )
                raise
            log.warning(
                "[sender] 429 روی %s (تلاش %d از %d) — توقف سراسری %.1fs",
                m, attempt, MAX_429_RETRIES, pause,
            )
            time.sleep(min(pause, left))
