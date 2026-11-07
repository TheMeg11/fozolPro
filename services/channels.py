"""عضویت اجباری در کانال‌ها — منبع واحد: جدول `forced_channels` ربات (+ env اختیاری).

ربات کانال‌های اجباری را در پنل ادمین به جدول `forced_channels` اضافه/حذف می‌کند؛
مینی‌اپ همان لیست را زنده می‌خواند. اگر بله خطا بدهد (مثلاً ربات ادمین کانال نیست)
fail-open می‌کنیم و لاگ می‌نویسیم تا خطای پیکربندی همهٔ کاربران را قفل نکند.
نتیجهٔ چک هر کاربر ۹۰ ثانیه کش می‌شود.
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
TTL = 90
OK_STATUSES = {"member", "administrator", "creator", "owner"}


def force_join_enabled() -> bool:
    try:
        import config as _legacy
        return bool(getattr(_legacy, "FORCE_JOIN_ENABLED", True))
    except Exception:
        return True


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
        username = cid.lstrip("@") if cid.startswith("@") else None
        url = (r.get("invite_link") or "").strip() or (f"{settings.BALE_DEEPLINK_BASE}{username}" if username else settings.BALE_DEEPLINK_BASE)
        out.append({"id": cid, "title": (r.get("channel_name") or cid), "username": username, "url": url})
    for ch in settings.REQUIRED_CHANNELS:
        if ch in seen:
            continue
        seen.add(ch)
        username = ch.lstrip("@") if ch.startswith("@") else None
        out.append({"id": ch, "title": ch, "username": username,
                    "url": f"{settings.BALE_DEEPLINK_BASE}{username}" if username else settings.BALE_DEEPLINK_BASE})
    return out


def _channel_info(ch: dict) -> dict:
    cid = ch["id"]
    if cid not in _info:
        info = dict(ch)
        try:
            if not (ch.get("invite_link") or ch.get("url")):
                chat = bale_api.get_chat(cid)
                info["title"] = chat.get("title") or info["title"]
        except AppError:
            pass
        _info[cid] = info
    return dict(_info[cid])


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
        try:
            status = (bale_api.get_chat_member(ch["id"], user_id) or {}).get("status")
            ok = status in OK_STATUSES
        except AppError as exc:
            log.warning("membership check failed for %s: %s (fail-open)", ch["id"], exc.code)
            ok = True
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
        raise AppError("CHANNEL_JOIN_REQUIRED", "برای ادامه ابتدا عضو کانال شوید.", 403, {"channels": [c for c in res["channels"] if not c["joined"]]})
