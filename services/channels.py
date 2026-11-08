"""عضویت اجباری در کانال‌ها — منبع واحد: جدول `forced_channels` ربات (+ env اختیاری).

v4.7 (باگ «اد اجباری کار نمی‌کند»):
- **fail-closed** مثل ربات: اگر نتوان عضویت را بررسی کرد (ربات ادمین کانال نیست،
  شناسهٔ کانال اشتباه است و…) کاربر «عضو نیست» فرض می‌شود و گیت باز نمی‌شود —
  قبلاً fail-open بود و همه بدون عضویت رد می‌شدند.
- نرمال‌سازی شناسهٔ کانال: شناسه‌های متنی مثل `fzxinfo` برای API به `@fzxinfo`
  تبدیل می‌شوند و دکمهٔ عضویت به `ble.ir/fzxinfo` می‌رود (قبلاً بدون @ صدا زده
  می‌شد و همیشه خطا → همیشه fail-open).
- خطای «user not found» = کاربر عضو نیست (رفتار عادی بله برای غیرعضو).
- کش ۹۰ ثانیه‌ای + اطلاع یک‌بارهٔ خطای پیکربندی به ادمین (مثل ربات).
"""
from __future__ import annotations

import logging
import threading
import time

import settings
from services import bale_api, db
from services.common import AppError

log = logging.getLogger("channels")
_cache: dict[int, tuple[float, dict]] = {}
_info: dict[str, dict] = {}
_lock = threading.Lock()
_notified_broken: set[str] = set()
TTL = 90
OK_STATUSES = {"member", "administrator", "creator", "owner"}


def force_join_enabled() -> bool:
    try:
        import config as _legacy
        return bool(getattr(_legacy, "FORCE_JOIN_ENABLED", True))
    except Exception:
        return True


def _api_chat_id(cid: str) -> str:
    """شناسهٔ قابل استفاده برای getChatMember بله: عددی یا @username."""
    cid = (cid or "").strip()
    if cid.startswith("@") or (cid.startswith("-") and cid[1:].isdigit()):
        return cid
    if cid.isdigit():
        return cid
    return "@" + cid  # شناسهٔ متنی بدون @ (فرمت ذخیرهٔ قدیمی پنل مینی‌اپ)


def _channel_url(cid: str, invite_link: str | None, username: str | None) -> str:
    if (invite_link or "").strip():
        return invite_link.strip()
    uname = (username or "").strip().lstrip("@")
    if uname:
        return f"{settings.BALE_DEEPLINK_BASE}{uname}"
    return settings.BALE_DEEPLINK_BASE


def _required_channels() -> list[dict]:
    """کانال‌های اجباری از جدول ربات + متغیر محیطی اختیاری (بدون تکرار)."""
    out, seen = [], set()
    try:
        rows = db.rows("SELECT channel_id, channel_name, invite_link FROM forced_channels ORDER BY added_at")
    except Exception:
        rows = []
    for r in rows:
        cid = str(r.get("channel_id") or "").strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        username = cid.lstrip("@") if not (cid.startswith("-") and cid[1:].isdigit()) and not cid.isdigit() else None
        out.append({"id": cid, "title": (r.get("channel_name") or cid), "username": username,
                    "url": _channel_url(cid, r.get("invite_link"), username)})
    for ch in settings.REQUIRED_CHANNELS:
        if ch in seen:
            continue
        seen.add(ch)
        username = ch.lstrip("@") if ch.startswith("@") else None
        out.append({"id": ch, "title": ch, "username": username,
                    "url": _channel_url(ch, None, username)})
    return out


def _channel_info(ch: dict) -> dict:
    cid = ch["id"]
    if cid not in _info:
        info = dict(ch)
        try:
            chat = bale_api.get_chat(_api_chat_id(cid))
            if chat:
                info["title"] = chat.get("title") or info["title"]
                link = chat.get("invite_link")
                if link:
                    info["url"] = link
                uname = (chat.get("username") or "").lstrip("@")
                if uname and not info.get("url"):
                    info["url"] = f"{settings.BALE_DEEPLINK_BASE}{uname}"
        except AppError:
            pass  # عنوان/لینک همان مقدار جدول می‌ماند
        _info[cid] = info
    return dict(_info[cid])


def _notify_admin_broken(cid: str, why: str) -> None:
    """اطلاع یک‌باره به ادمین مثل ربات — تا خطای پیکربندی بی‌صدا نماند."""
    if cid in _notified_broken:
        return
    _notified_broken.add(cid)
    try:
        if settings.ADMIN_ID:
            bale_api.send_message(
                settings.ADMIN_ID,
                f"⚠️ ربات نمی‌تواند اعضای کانال {cid} را بررسی کند ({why}).\n"
                "ربات باید در کانال **ادمین** باشد. تا زمان رفع مشکل، عضویت در این کانال اجباری است.")
    except Exception:
        pass


def _check_one(ch: dict, user_id: int) -> bool:
    """بررسی عضویت یک کاربر در یک کانال — fail-closed (مثل is_subscribed ربات)."""
    try:
        status = (bale_api.get_chat_member(_api_chat_id(ch["id"]), user_id) or {}).get("status")
        return status in OK_STATUSES
    except AppError as exc:
        desc = str((exc.details or {}).get("description") or "")
        if "user not found" in desc.lower():
            return False  # کاربر عضو کانال نیست — حالت عادی
        # ربات ادمین نیست / کانال پیدا نشد / خطای بله → عضو نیست + خبر به ادمین
        why = exc.code
        if desc:
            why += f": {desc[:80]}"
        log.warning("membership check failed for %s: %s (fail-closed)", ch["id"], why)
        _notify_admin_broken(ch["id"], why)
        return False


def check(user_id: int, force: bool = False) -> dict:
    channels = _required_channels()
    if not channels or not force_join_enabled() or settings.is_admin(user_id):
        return {"joined": True, "channels": []}
    with _lock:
        hit = _cache.get(user_id)
    if hit and not force and time.time() - hit[0] < TTL:
        return hit[1]
    result_ch, joined_all = [], True
    for ch in channels:
        info = _channel_info(ch)
        ok = _check_one(ch, user_id)
        info["joined"] = ok
        joined_all = joined_all and ok
        result_ch.append(info)
    result = {"joined": joined_all, "channels": result_ch}
    with _lock:
        _cache[user_id] = (time.time(), result)
    return result


def require(user_id: int) -> None:
    res = check(user_id)
    if not res["joined"]:
        raise AppError("CHANNEL_JOIN_REQUIRED", "برای ادامه ابتدا عضو کانال شوید.", 403,
                       {"channels": [c for c in res["channels"] if not c["joined"]]})


def invalidate_cache(user_id: int | None = None) -> None:
    """پاک‌کردن کش عضویت (بعد از افزودن/حذف کانال یا «بررسی عضویت»)."""
    with _lock:
        if user_id:
            _cache.pop(user_id, None)
        else:
            _cache.clear()
