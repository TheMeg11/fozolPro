"""آواتار (عکس پروفایل) کاربران بله — پروکسی امضادار با کش دیسک.

چرا پروکسی؟
- تگ <img> نمی‌تواند هدر X-Bale-Init-Data بفرستد → URL امضادار (HMAC + انقضا) می‌سازیم.
- CSP مینی‌اپ img-src 'self' است → عکس باید از همین سرویس سرو شود.
- هر عکس یک‌بار دانلود و روی Volume کش می‌شود (۷ روز) → مصرف پهنای‌باند Railway حداقل.

جریان: getChat → photo.small_file_id → getFile → دانلود از BALE_FILE_BASE →
بهینه‌سازی با Pillow (۱۶۰px، JPEG) → کش در settings.AVATAR_DIR.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading
import time
from pathlib import Path

import requests

import settings
from services import bale_api

log = logging.getLogger("avatars")
_session = requests.Session()
_lock = threading.Lock()
TTL_DAYS = 7
SIZE_PX = 160


def _secret() -> str:
    return settings.BOT_TOKEN or "fozol-avatar-fallback"


def _sig(uid: int, exp: int) -> str:
    return hmac.new(_secret().encode(), f"{uid}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]


def url_for(uid: int) -> str:
    """URL امضادار برای <img src>. ۲۴ ساعت اعتبار."""
    exp = int(time.time()) + 86400
    return f"/api/avatar/{int(uid)}.jpg?e={exp}&s={_sig(uid, exp)}"


def check_sig(uid: int, exp: str, sig: str) -> bool:
    try:
        e = int(exp)
    except (TypeError, ValueError):
        return False
    if e < int(time.time()):
        return False
    return hmac.compare_digest(_sig(uid, e), str(sig or ""))


def _cache_path(uid: int) -> Path:
    return Path(settings.AVATAR_DIR) / f"{int(uid)}.jpg"


def _download(uid: int) -> bytes | None:
    """دانلود عکس پروفایل از بله؛ None = عکس ندارد یا خطا."""
    try:
        chat = bale_api.call("getChat", chat_id=int(uid), timeout=10) or {}
        photo = (chat.get("photo") or {})
        file_id = photo.get("small_file_id") or photo.get("big_file_id")
        if not file_id:
            return None
        f = bale_api.call("getFile", file_id=file_id, timeout=15) or {}
        fp = f.get("file_path")
        if not fp:
            return None
        url = f"{settings.BALE_FILE_BASE}/bot{settings.BOT_TOKEN}/{fp}"
        resp = _session.get(url, timeout=20)
        if resp.status_code != 200 or not resp.content:
            return None
        return _optimize(resp.content)
    except Exception as exc:
        log.debug("avatar download %s failed: %s", uid, exc.__class__.__name__)
        return None


def _optimize(raw: bytes) -> bytes:
    try:
        import io

        from PIL import Image

        im = Image.open(io.BytesIO(raw)).convert("RGB")
        im.thumbnail((SIZE_PX, SIZE_PX))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82, optimize=True)
        return buf.getvalue()
    except Exception:
        return raw


def _cached(p: Path) -> bytes | None:
    """خواندن از کش — فایل خالی = نشانگر معتبرِ «بدون عکس» (کش منفی).
    v5.0.2 (رفع باگ): قبلاً برای فایل خالی None برمی‌گشت و get_avatar آن را
    «کش‌میس» تفسیر می‌کرد → برای هر بازدید از صفحهٔ فضول‌یاب، برای کاربرانِ
    بدون عکس یا بلاک‌کرده، دوباره getChat زده می‌شد (ده‌ها هزار خطای
    «Forbidden: bot was blocked» + اتلاف پهنای‌باند + سریال‌شدن روی قفل).
    حالا b"" (که falsy است ولی None نیست) به‌عنوان hit گزارش می‌شود."""
    try:
        if p.exists() and time.time() - p.stat().st_mtime < TTL_DAYS * 86400:
            return p.read_bytes()  # ممکن است b"" باشد = کش منفی معتبر
    except OSError:
        pass
    return None


def get_avatar(uid: int) -> bytes | None:
    """بایت‌های JPEG از کش/شبکه. None = عکسی وجود ندارد (کلاینت به حرف اول نام برمی‌گردد).
    v5.0.2: کش منفی (فایل خالی) هم hit حساب می‌شود — بدون تماس با API بله."""
    uid = int(uid)
    p = _cache_path(uid)
    hit = _cached(p)
    if hit is not None:  # b"" = «بدون عکس» کش‌شده — دیگر getChat تکراری نیست
        return hit or None
    with _lock:
        hit = _cached(p)  # دوباره زیر قفل — شاید ترد دیگری همین حالا نوشته باشد
        if hit is not None:
            return hit or None
        data = _download(uid)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(data or b"")  # b'' = نشانگر «بدون عکس» تا getChat تکراری نشود
            os.replace(tmp, p)
        except OSError as exc:
            log.warning("avatar cache write failed: %s", exc)
        return data


# ── v5.0.2: هرس دوره‌ای کش دیسک — فایل‌های منقضی (TTL_DAYS) حذف می‌شوند تا
# سهمیهٔ Volume (۵۰۰MB) پر نشود؛ قبلاً فایل‌های آواتار برای همیشه می‌ماندند. ──
def _purge_expired() -> None:
    try:
        root = Path(settings.AVATAR_DIR)
        if not root.is_dir():
            return
        cutoff = time.time() - TTL_DAYS * 86400
        removed = 0
        for f in root.glob("*.jpg"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except OSError:
                pass
        if removed:
            log.info("avatar cache purge: %d expired file(s) removed", removed)
    except Exception:
        pass


def _purge_loop() -> None:
    while True:
        time.sleep(6 * 3600)
        _purge_expired()


try:
    threading.Thread(target=_purge_loop, name="avatar-purge", daemon=True).start()
except Exception:
    pass
