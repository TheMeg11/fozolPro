"""v5.3 — توکن مات برای دکمه‌های پیام ناشناس (رفع نشت حریم خصوصی).

قبلاً دکمه‌های زیر هر پیام ناشناس شناسهٔ عددی واقعی فرستنده را حمل می‌کردند
(anon_reply_<id> / block_<id> / report_<id>). کلاینت بله callback_data را نشان
نمی‌دهد، ولی هر کسی با بازرسی پیام (نسخهٔ وب/ابزار توسعه) می‌توانست هویت فرستنده را کشف کند.

حالا برای هر جفت (owner, target) یک توکن HMAC قطعی ساخته می‌شود:
  - owner  = کسی که دکمه را می‌زند (گیرندهٔ پیام)
  - target = طرف دیگر گفتگو (فرستندهٔ ناشناس)
فقط owner همان توکن می‌تواند آن را resolve کند؛ برای هر کس دیگری بی‌اثر است.
توکن قطعی است ← یک سطر برای هر جفت (رشد جدول به ازای هر پیام نیست).

قالب‌های جدید callback (همه زیر سقف ۶۴ بایت):
  axr_<tok>         پاسخ ناشناس
  axb_<tok>         بلاک
  axu_<tok>         آنبلاک
  axp_<tok>         گزارش تخلف
  axq_<tok>_<code>  دلیل گزارش
  axk_<tok>_<k>[_<suffix>]  دکمه‌های مربوط به یک فضول (لقب/پیام/اطلاعات/هدیه/بی‌صدا/خرید هویت)
                            — قبلاً شناسهٔ عددی فضول حتی برای صاحب تلهٔ غیرVIP در دکمه بود و
                            خرید «باز کردن هویت» با بازرسی callback_data دور زده می‌شد.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import threading

import settings
from services import db
from services.common import iso

log = logging.getLogger("anon_refs")

PREFIXES = ("axr_", "axb_", "axu_", "axp_", "axq_", "axk_")
# کد یک‌حرفی ← پیشوند callback قدیمی ربات (فقط همین‌ها مجازند)
SNOOP_KINDS = {"n": "nick_", "a": "anon_", "d": "snoopdetail_", "g": "giftvip_", "m": "mute_",
               "u": "unmute_", "r": "reveal_buy_", "c": "confirmgift_"}
_KIND_OF = {v: k for k, v in SNOOP_KINDS.items()}


def snoop_cb(prefix: str, owner_id: int, target_id: int, suffix: str = "") -> str:
    """callback_data مات برای دکمه‌ای که در قالب قدیم f"{prefix}{target_id}{_suffix}" بود."""
    k = _KIND_OF[prefix]
    tail = f"_{suffix}" if suffix != "" else ""
    return f"axk_{make(owner_id, target_id)}_{k}{tail}"
_known: set[str] = set()
_known_lock = threading.Lock()


def _key() -> bytes:
    return hashlib.sha256(f"anon-refs:{settings.BOT_TOKEN or 'fozol'}".encode()).digest()


def token(owner_id: int, target_id: int) -> str:
    """توکن قطعی جفت — بدون ذخیره."""
    return hmac.new(_key(), f"{int(owner_id)}:{int(target_id)}".encode(), hashlib.sha256).hexdigest()[:16]


def make(owner_id: int, target_id: int) -> str:
    """ساخت توکن + ثبت نگاشت (فقط بار اول)."""
    tok = token(owner_id, target_id)
    with _known_lock:
        if tok in _known:
            return tok
    try:
        db.execute("INSERT OR IGNORE INTO anon_refs(token, owner_id, target_id, created_at) VALUES(?,?,?,?)",
                   (tok, int(owner_id), int(target_id), iso()))
        with _known_lock:
            if len(_known) > 20000:
                _known.clear()
            _known.add(tok)
    except Exception as exc:  # ذخیرهٔ توکن هرگز نباید ارسال را بشکند
        log.warning("anon_refs.make failed: %s", exc)
    return tok


def resolve(owner_id: int, tok: str) -> int | None:
    """شناسهٔ target فقط اگر توکن متعلق به همین owner باشد."""
    tok = (tok or "").strip()
    if not (8 <= len(tok) <= 32) or not all(c in "0123456789abcdef" for c in tok):
        return None
    try:
        r = db.row("SELECT target_id FROM anon_refs WHERE token=? AND owner_id=?", (tok, int(owner_id)))
    except Exception:
        return None
    return int(r["target_id"]) if r else None


def buttons(owner_id: int, target_id: int, blocked: bool = False) -> dict:
    """کیبورد استاندارد پیام ناشناس (فرم JSON بات‌API)."""
    tok = make(owner_id, target_id)
    if blocked:
        return {"inline_keyboard": [[{"text": "🔄 پاسخ ناشناس", "callback_data": f"axr_{tok}"},
                                     {"text": "✅ آنبلاک", "callback_data": f"axu_{tok}"}]]}
    return {"inline_keyboard": [
        [{"text": "🔄 پاسخ ناشناس", "callback_data": f"axr_{tok}"}],
        [{"text": "🚫 بلاک", "callback_data": f"axb_{tok}"},
         {"text": "⚠️ گزارش تخلف", "callback_data": f"axp_{tok}"}],
    ]}


def translate(owner_id: int, data: str) -> str | None:
    """تبدیل callback قالب جدید به قالب داخلی قدیمی ربات (فقط سمت سرور).

    خروجی: رشتهٔ قدیمی (مثلاً anon_reply_<id>) یا None برای توکن نامعتبر/متعلق به دیگری.
    دادهٔ غیرِ قالب جدید بدون تغییر برمی‌گردد.
    """
    if not data or not data.startswith(PREFIXES):
        return data
    kind, rest = data[:3], data[4:]
    code = None
    if kind in ("axq", "axk"):
        tok, _, code = rest.partition("_")
    else:
        tok = rest
    target = resolve(owner_id, tok)
    if target is None:
        return None
    if kind == "axk":
        k, _, suffix = (code or "").partition("_")
        prefix = SNOOP_KINDS.get(k)
        if not prefix:
            return None
        return f"{prefix}{target}" + (f"_{suffix}" if suffix else "")
    return {
        "axr": f"anon_reply_{target}",
        "axb": f"block_{target}",
        "axu": f"unblock_{target}",
        "axp": f"report_{target}",
        "axq": f"reportreason_{target}_{code or '0'}",
    }[kind]
