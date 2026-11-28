"""REST API مینی‌اپ بله + سرو فرانت‌اند (همان پروسس ربات).

قرارداد پاسخ: موفق {"ok": true, "data": ...} | خطا {"ok": false, "error": {"code", "message", "details"}}
احراز هویت: هدر X-Bale-Init-Data (initData خام بله) → اعتبارسنجی HMAC روی سرور. مجوز ادمین فقط با ADMIN_ID سمت سرور.
"""
from __future__ import annotations

import hmac
import html
import ipaddress
import json
import logging
import os
import re
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.gzip import GZipMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

import settings
from auth import InitDataError, validate_init_data
from services import admin as admin_svc
from services import anon as anon_svc
from services import avatars, bale_api, bot_settings, channels, db, missions, rewards, snoop, support, users, vip, wheel
from services import profile as profile_svc
from services.common import AppError

log = logging.getLogger("api")
DEFAULT_SDK_SRC = "https://tapi.bale.ai/miniapp.js?1"


def ok(data: Any) -> dict:
    return {"ok": True, "data": data}


def err_response(code: str, message: str, status: int, details: dict | None = None) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": code, "message": message, "details": details or {}}}, status_code=status,
                        headers={"Cache-Control": "no-store"})


# ---------------- Rate limit (پنجرهٔ لغزان در حافظه؛ کافی برای یک instance) ----------------
class RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()
        self._last_prune = time.monotonic()

    def check(self, key: str) -> None:
        if self.per_minute <= 0:
            return
        t = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and t - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                raise AppError("RATE_LIMITED", "تعداد درخواست‌ها زیاد است؛ چند ثانیه صبر کنید.", 429)
            q.append(t)
            # v5.3 (رفع باگ): هرس قبلی هیچ‌وقت کار نمی‌کرد — deque کلیدهای قدیمی فقط وقتی
            # خالی می‌شد که همان کلید دوباره درخواست بدهد؛ پس دیکشنری بی‌نهایت رشد می‌کرد و
            # بعد از ۲۰هزار کلید، هر درخواست کل دیکشنری را پیمایش می‌کرد. حالا هر ۶۰ ثانیه
            # کلیدهایی که آخرین درخواستشان قدیمی‌تر از ۶۰ ثانیه است حذف می‌شوند.
            if t - self._last_prune > 60:
                self._last_prune = t
                for k in [k for k, v in self.hits.items() if not v or t - v[-1] > 60]:
                    self.hits.pop(k, None)


limiter = RateLimiter(settings.RATE_LIMIT_PER_MIN)


def _is_private(host: str) -> bool:
    try:
        a = ipaddress.ip_address(host)
        return a.is_private or a.is_loopback or a.is_link_local or a in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        return False


def client_ip(request: Request) -> str:
    """v5.3: IP واقعی کلاینت برای rate-limit.

    uvicorn با forwarded_allow_ips="*" «چپ‌ترین» مقدار X-Forwarded-For را برمی‌دارد که
    خود کلاینت می‌تواند جعل کند (دور زدن محدودیت IP با یک هدر). پراکسی Railway IP واقعی
    را به «انتهای» لیست اضافه می‌کند؛ پس از راست به چپ اولین IP عمومی را برمی‌داریم."""
    raw = request.headers.get("x-forwarded-for") or ""
    for part in reversed([p.strip() for p in raw.split(",") if p.strip()]):
        host = part.rsplit(":", 1)[0] if part.count(":") == 1 else part.strip("[]")
        if not _is_private(host):
            return host
    return request.client.host if request.client else "?"


# ---------------- Dependencies ----------------
def current_user(request: Request) -> dict:
    ip = client_ip(request)
    limiter.check(f"ip:{ip}")
    try:
        data = validate_init_data(request.headers.get(settings.INITDATA_HEADER), settings.BOT_TOKEN,
                                  settings.INITDATA_MAX_AGE, settings.INITDATA_HMAC_KEY)
    except InitDataError as exc:
        raise AppError(exc.code, exc.message, 401) from None
    u = data["user"]
    limiter.check(f"u:{u['id']}")
    row = users.ensure_user(u)
    if row.get("is_banned"):
        raise AppError("BANNED", "حساب شما مسدود شده است. با پشتیبانی تماس بگیرید.", 403)
    return row


def member_user(user: dict = Depends(current_user)) -> dict:
    """کاربر عضو کانال‌های اجباری (برای همهٔ اندپوینت‌ها به‌جز /me و /channels/check)."""
    channels.require(user["user_id"])
    return user


def admin_user(user: dict = Depends(current_user)) -> dict:
    if not settings.is_admin(user["user_id"]):
        log.warning("forbidden admin access by %s", user["user_id"])
        raise AppError("FORBIDDEN", "به این بخش دسترسی ندارید.", 403)
    return user


# ---------------- Bodies ----------------
class TrapIn(BaseModel):
    title: str = Field(min_length=2, max_length=40)
    bait: str = Field(default="", max_length=200)


class PurchaseIn(BaseModel):
    plan_id: str = Field(min_length=1, max_length=32)


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class VipChangeIn(BaseModel):
    action: Literal["add", "reduce", "cancel"]
    days: int = Field(default=0, ge=0, le=3650)


class BanIn(BaseModel):
    banned: bool


class BroadcastIn(BaseModel):
    text: str = Field(min_length=3, max_length=4000)
    target: Literal["all", "vip", "free"] = "all"


class ChatSendIn(BaseModel):
    token: str = Field(min_length=4, max_length=64)
    text: str = Field(min_length=1, max_length=1000)


class SettingIn(BaseModel):
    key: str = Field(min_length=2, max_length=64)
    value: str | int | bool


class GiftIn(BaseModel):
    days: int = Field(ge=1, le=3650)
    max_uses: int = Field(ge=1, le=10000)
    code: str | None = Field(default=None, max_length=24)


class RedeemIn(BaseModel):
    code: str = Field(min_length=2, max_length=24)


# ---- v5.3: مدل‌های ورودی برای اندپوینت‌هایی که قبلاً body: dict خام می‌گرفتند ----
class ProfileEditIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=64)
    active_title: int | str | None = None
    reset_name: bool = False
    reset_title: bool = False


class WelcomeIn(BaseModel):
    text: str | None = Field(default=None, max_length=1000)


class MaskIn(BaseModel):
    clear: bool = False
    emoji: str | None = Field(default=None, max_length=32)
    text: str | None = Field(default=None, max_length=64)


class VisibilityIn(BaseModel):
    period: Literal["week", "all"] = "week"
    hidden: bool = False


class ChallengeIn(BaseModel):
    action: Literal["start", "cancel"]
    # None هم پذیرفته می‌شود (parseInt نامعتبر در JS → null) — مثل رفتار قبلی، پیش‌فرض اعمال می‌شود
    hours: int | None = Field(default=24, ge=1, le=24 * 60)
    reward_days: int | None = Field(default=3, ge=0, le=3650)
    reward_type: str = Field(default="vip", max_length=16)
    reward_amount: int | None = Field(default=0, ge=0, le=10 ** 9)
    announce_text: str = Field(default="", max_length=3000)


class ForcedChannelIn(BaseModel):
    channel_id: str = Field(min_length=2, max_length=128)
    title: str = Field(default="", max_length=128)
    target: int | None = Field(default=0, ge=0, le=10 ** 8)


class AdBroadcastIn(BaseModel):
    url: str = Field(default="", max_length=512)
    stage: Literal["preview", "send"] = "preview"


# ---- v5.3: سقف حجم بدنهٔ درخواست (ASGI) — جلوی بدنه‌های چند مگابایتی/حمله حافظه را می‌گیرد ----
MAX_BODY_API = 64 * 1024
MAX_BODY_WEBHOOK = 2 * 1024 * 1024


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        limit = MAX_BODY_WEBHOOK if scope.get("path", "").startswith("/bale/webhook/") else MAX_BODY_API
        for k, v in scope.get("headers") or []:
            if k == b"content-length":
                try:
                    if int(v) > limit:
                        return await _send_413(send)
                except ValueError:
                    return await _send_413(send)
        seen = 0

        async def limited_receive():
            nonlocal seen
            msg = await receive()
            if msg.get("type") == "http.request":
                seen += len(msg.get("body") or b"")
                if seen > limit:
                    raise AppError("PAYLOAD_TOO_LARGE", "حجم درخواست بیش از حد مجاز است.", 413)
            return msg

        return await self.app(scope, limited_receive, send)


async def _send_413(send) -> None:
    body = json.dumps({"ok": False, "error": {"code": "PAYLOAD_TOO_LARGE", "message": "حجم درخواست بیش از حد مجاز است.",
                                              "details": {}}}, ensure_ascii=False).encode()
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class SelectiveGZip:
    """v5.3: فشرده‌سازی gzip برای JSON/JS/CSS/HTML — به‌جز مسیرهای از قبل فشرده (عکس/فونت)."""
    _SKIP = ("/api/avatar/", "/img/", "/fonts/", "/bale/webhook/")

    def __init__(self, app):
        self.app = app
        self.gz = GZipMiddleware(app, minimum_size=800, compresslevel=5)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not scope.get("path", "").startswith(self._SKIP):
            return await self.gz(scope, receive, send)
        return await self.app(scope, receive, send)


_ACCESS_LOG_ALL = (os.environ.get("ACCESS_LOG") or "").strip().lower() in ("1", "true", "yes", "on")
_SLOW_MS = 1500.0


def _safe_path(path: str) -> str:
    """v5.3: سکرت وبهوک هرگز در لاگ چاپ نشود."""
    if path.startswith("/bale/webhook/"):
        return "/bale/webhook/***"
    return path


class WarnIn(BaseModel):
    reason: str = Field(default="", max_length=200)


def create_app(bot: Any = None) -> FastAPI:
    app = FastAPI(title="Fozoolyab Bale Mini App", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.bot = bot

    # ---------- خطاها ----------
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return err_response(exc.code, exc.message, exc.status, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        fields = [".".join(str(p) for p in e.get("loc", [])[1:]) for e in exc.errors()]
        return err_response("VALIDATION_ERROR", "اطلاعات واردشده معتبر نیست.", 422, {"fields": fields})

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, f"HTTP_{exc.status_code}")
        return err_response(code, "مسیر پیدا نشد." if exc.status_code == 404 else "درخواست نامعتبر است.", exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return err_response("SERVER_ERROR", "خطای داخلی سرور؛ لطفاً کمی بعد تلاش کنید.", 500)

    # ---------- هدرها + لاگ ----------
    @app.middleware("http")
    async def _headers(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = settings.CSP   # بدون X-Frame-Options (نسخهٔ وب بله با iframe باز می‌کند)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # v5.3: HSTS + بستن APIهای حساس مرورگر که مینی‌اپ لازم ندارد
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Permissions-Policy"] = ("camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
                                                  "accelerometer=(), gyroscope=(), magnetometer=(), interest-cohort=()")
        path = request.url.path
        if path.startswith("/api/avatar/"):
            response.headers["Cache-Control"] = "public, max-age=86400, stale-while-revalidate=604800"
        elif path.startswith("/api/") or path.startswith("/bale/"):
            response.headers["Cache-Control"] = "no-store"
        elif path.startswith("/fonts/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif request.query_params.get("v") and response.status_code == 200 and path != "/":
            # v5.3: فایل‌های نسخه‌دار (?v=mtime) هرگز تغییر نمی‌کنند — کش یک‌ساله؛ با هر دیپلوی
            # نسخهٔ جدید در index.html (که no-cache است) لینک تازه می‌سازد.
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path != "/health":
            response.headers.setdefault("Cache-Control", "no-cache")
        # v5.3: لاگ هر درخواست حذف شد (هزاران خط/ساعت = CPU + سهمیهٔ لاگ Railway).
        # فقط خطاها و درخواست‌های کند؛ ACCESS_LOG=1 لاگ کامل را برمی‌گرداند.
        if path != "/health" and not path.startswith("/api/avatar/"):
            ms = (time.perf_counter() - start) * 1000
            code = response.status_code
            if _ACCESS_LOG_ALL or code >= 500 or ms >= _SLOW_MS:
                log.info("%s %s %s %.0fms", request.method, _safe_path(path), code, ms)
            elif code >= 400 and code not in (401, 404, 429):
                log.info("%s %s %s %.0fms", request.method, _safe_path(path), code, ms)
        return response

    # ---------- سلامت ----------
    @app.get("/health")
    def health():
        try:
            db.scalar("SELECT 1")
            db_ok = True
        except Exception:
            db_ok = False
        mode = "webhook" if settings.WEBHOOK_URL else "polling"
        body = {"ok": db_ok, "db": db_ok, "bot": bool(app.state.bot), "mode": mode}
        return JSONResponse(body, status_code=200 if db_ok else 503)

    # ---------- کاربر ----------
    @app.get("/api/me")
    def me(user: dict = Depends(current_user)):
        uid = user["user_id"]
        # v4.7: همگام‌سازی استریک/XP ورود روزانه — کاربری که فقط مینی‌اپ را باز می‌کند
        # هم مثل پنل شیشه‌ای زنجیرهٔ روزانه‌اش ادامه می‌یابد (سپر VIP هم اعمال می‌شود).
        try:
            rewards.touch_daily(uid)
        except Exception:
            pass
        ch = channels.check(uid)
        rec = snoop.visitors(uid, size=3)["items"]
        vip_st = vip.status(uid)
        streak_count = db.scalar("SELECT COALESCE(streak_count,0) FROM users WHERE user_id=?", (uid,), 0)
        return ok({
            "user": users.public_profile(user), "is_admin": settings.is_admin(uid),
            "vip": vip_st, "xp": users.level_info(user.get("xp") or 0), "rank": users.rank(uid),
            "snoop": snoop.quick_stats(uid), "wheel": {k: v for k, v in wheel.state(uid).items() if k != "segments"},
            "channels": {"joined": ch["joined"], "required": [c for c in ch["channels"] if not c["joined"]]},
            "recent": rec,
            # v4.4: استریک + سپر VIP + روزهای باقی‌مانده تا جایزهٔ هفتگی
            "streak": {"count": streak_count, "shield": bool(vip_st["active"]),
                       "days_to_weekly": (7 - (streak_count % 7)) if streak_count else 7},
            "settings": {"reveal_price_toman": bot_settings.get_int("reveal_price", 30000) // 10},
        })

    @app.get("/api/channels/check")
    def channels_check(user: dict = Depends(current_user)):
        return ok(channels.check(user["user_id"], force=True))

    # ---------- فضول‌یابی ----------
    @app.get("/api/snoop/summary")
    def snoop_summary(user: dict = Depends(member_user)):
        return ok(snoop.summary(user["user_id"]))

    @app.get("/api/snoop/visitors")
    def snoop_visitors(trap_code: str | None = Query(None, max_length=16), cursor: int = Query(0, ge=0, le=1000000), user: dict = Depends(member_user)):
        return ok(snoop.visitors(user["user_id"], trap_code, cursor))

    @app.get("/api/snoop/radar")
    def snoop_radar(user: dict = Depends(member_user)):
        """v4.4: رادار فضول‌ها — ساعات پربازدید، بهترین تله، مقایسه با میانگین."""
        return ok(snoop.radar(user["user_id"]))

    # ---------- پروفایل: لقب‌ها، نشان‌ها، ویرایش نام (v4.4) ----------
    @app.get("/api/profile")
    def profile_view(user: dict = Depends(member_user)):
        return ok(profile_svc.view(user["user_id"]))

    @app.post("/api/profile/edit")
    def profile_edit(body: ProfileEditIn, user: dict = Depends(member_user)):
        raw_title = body.active_title
        try:
            active_title = int(raw_title) if raw_title not in (None, "") else None
        except (TypeError, ValueError):
            raise AppError("VALIDATION_ERROR", "لقب انتخابی نامعتبر است.", 422) from None
        return ok(profile_svc.update(
            user["user_id"],
            display_name_str=body.display_name if "display_name" in body.model_fields_set else None,
            active_title=active_title,
            reset_name=body.reset_name,
            reset_title=body.reset_title,
        ))

    @app.post("/api/snoop/traps")
    def snoop_create(body: TrapIn, user: dict = Depends(member_user)):
        return ok(snoop.create_trap(user["user_id"], body.title, body.bait))

    @app.delete("/api/snoop/traps/{trap_code}")
    def snoop_delete(trap_code: str, user: dict = Depends(member_user)):
        if not 2 <= len(trap_code) <= 16:
            raise AppError("VALIDATION_ERROR", "کد تله نامعتبر است.", 422)
        snoop.delete_trap(user["user_id"], trap_code)
        return ok({"deleted": True})

    # ---------- VIP / پرداخت ----------
    @app.get("/api/vip/plans")
    def vip_plans(user: dict = Depends(member_user)):
        uid = user["user_id"]
        comparison = None
        try:
            comparison = bot_settings.price_comparison()
        except Exception:
            comparison = None
        return ok({"status": vip.status(uid), "plans": vip.plans(), "features": settings.VIP_FEATURES,
                   "payments": vip.payments_of(uid), "comparison": comparison})

    @app.post("/api/vip/purchase")
    def vip_purchase(body: PurchaseIn, user: dict = Depends(member_user)):
        return ok(vip.create_invoice(user["user_id"], body.plan_id))

    # ---------- v4.9: تنظیمات ویژهٔ VIP (متن خوش‌آمدگویی + نقاب) ----------
    @app.get("/api/vip/settings")
    def vip_settings_view(user: dict = Depends(member_user)):
        return ok(vip.settings_view(user["user_id"]))

    @app.post("/api/vip/settings/welcome")
    def vip_settings_welcome(body: WelcomeIn, user: dict = Depends(member_user)):
        return ok(vip.set_welcome_text(user["user_id"], body.text))

    @app.post("/api/vip/settings/mask")
    def vip_settings_mask(body: MaskIn, user: dict = Depends(member_user)):
        if body.clear:
            return ok(vip.clear_mask(user["user_id"]))
        if not body.emoji:
            raise AppError("VALIDATION_ERROR", "ایموجی نقاب را انتخاب کن.", 422)
        return ok(vip.set_mask(user["user_id"], body.emoji, body.text or ""))

    # ---------- XP / لیدربورد / گردونه ----------
    @app.get("/api/leaderboard")
    def leaderboard(period: Literal["week", "all"] = "week", user: dict = Depends(member_user)):
        return ok(users.leaderboard(period, user["user_id"]))

    @app.post("/api/leaderboard/visibility")
    def leaderboard_visibility(body: VisibilityIn, user: dict = Depends(member_user)):
        """v4.4: کلید روشن/خاموش نمایش نام من در برترین‌ها — جداگانه برای هفتگی و کل."""
        users.set_hidden(body.period, user["user_id"], body.hidden)
        return ok({"period": body.period, "hidden": body.hidden})

    @app.get("/api/wheel")
    def wheel_state(user: dict = Depends(member_user)):
        return ok(wheel.state(user["user_id"]))

    @app.post("/api/wheel/spin")
    def wheel_spin(user: dict = Depends(member_user)):
        return ok(wheel.spin(user["user_id"]))

    # ---------- v4.7: ماموریت‌ها (همان ماموریت‌های پنل شیشه‌ای) ----------
    @app.get("/api/missions")
    def missions_page(page: int = Query(1, ge=1, le=1000), user: dict = Depends(member_user)):
        return ok(missions.page(user["user_id"], page))

    @app.get("/api/missions/{task_id}")
    def missions_detail(task_id: str, user: dict = Depends(member_user)):
        t = missions.detail(user["user_id"], task_id)
        if not t:
            raise AppError("NOT_FOUND", "ماموریت پیدا نشد.", 404)
        return ok(t)

    # ---------- v4.7: پاداش‌ها (جایزه روزانه + کد هدیه — هم‌ارز منوی 🎁 ربات) ----------
    @app.get("/api/rewards")
    def rewards_state(user: dict = Depends(member_user)):
        uid = user["user_id"]
        return ok({"daily": rewards.daily_state(uid), "gift_codes": rewards.gift_codes(uid),
                   "wheel": {k: v for k, v in wheel.state(uid).items() if k != "segments"}})

    @app.post("/api/rewards/claim")
    def rewards_claim(user: dict = Depends(member_user)):
        return ok(rewards.claim_daily(user["user_id"]))

    @app.post("/api/gifts/redeem")
    def gifts_redeem(body: RedeemIn, user: dict = Depends(member_user)):
        return ok(rewards.redeem_gift(user["user_id"], body.code))

    # ---------- پشتیبانی ----------
    @app.get("/api/support/messages")
    def support_list(user: dict = Depends(current_user)):
        uid = user["user_id"]
        return ok({"ticket": {"status": support.ticket_status(uid)}, "messages": support.messages(uid)})

    @app.post("/api/support/messages")
    def support_send(body: TextIn, user: dict = Depends(current_user)):
        return ok(support.add_user_message(user["user_id"], body.text))

    # ---------- چت ناشناس (تب «چت») ----------
    @app.get("/api/chat/conversations")
    def chat_conversations(user: dict = Depends(member_user)):
        return ok({"items": anon_svc.conversations(user["user_id"])})

    @app.get("/api/chat/thread/{token}")
    def chat_thread(token: str, user: dict = Depends(member_user)):
        return ok(anon_svc.thread(user["user_id"], token))

    @app.post("/api/chat/send")
    def chat_send(body: ChatSendIn, user: dict = Depends(member_user)):
        return ok(anon_svc.send(user["user_id"], body.token, body.text))

    @app.post("/api/snoop/visitors/{user_id}/anon-token")
    def snoop_anon_token(user_id: int, user: dict = Depends(member_user)):
        """شروع گفتگوی ناشناس با یکی از فضول‌ها (از جزئیات فضول)."""
        if not vip.is_active(user["user_id"]):
            raise AppError("FORBIDDEN", "برای پیام ناشناس به فضول‌ها ابتدا VIP فعال کنید.", 403)
        return ok({"token": anon_svc.token_for_snoop(user["user_id"], user_id)})

    # ---------- ادمین (همه با admin_user) ----------
    @app.get("/api/admin/stats")
    def a_stats(_: dict = Depends(admin_user)):
        return ok(admin_svc.stats())

    # ---- v4.3: هم‌ارزهای پنل شیشه‌ای ----
    @app.get("/api/admin/challenge")
    def a_challenge(_: dict = Depends(admin_user)):
        return ok(admin_svc.challenge_view())

    @app.post("/api/admin/challenge")
    def a_challenge_op(body: ChallengeIn, _: dict = Depends(admin_user)):
        if body.action == "start":
            # v4.6: نوع جایزه (vip | envelope)، مبلغ پاکت و متن اعلان شروع قابل ویرایش
            return ok(admin_svc.challenge_start(
                body.hours or 24, body.reward_days or 3, body.reward_type or "vip",
                body.reward_amount or 0, body.announce_text or ""))
        return ok(admin_svc.challenge_cancel())

    @app.get("/api/admin/forced-channels")
    def a_channels(_: dict = Depends(admin_user)):
        return ok(admin_svc.forced_channels())

    @app.post("/api/admin/forced-channels")
    def a_channel_add(body: ForcedChannelIn, _: dict = Depends(admin_user)):
        return ok(admin_svc.add_forced_channel(body.channel_id, body.title, body.target or 0))

    @app.delete("/api/admin/forced-channels/{channel_id}")
    def a_channel_del(channel_id: str, _: dict = Depends(admin_user)):
        return ok(admin_svc.remove_forced_channel(channel_id))

    @app.post("/api/admin/ad-broadcast")
    def a_ad_broadcast(body: AdBroadcastIn, _: dict = Depends(admin_user)):
        return ok(admin_svc.ad_broadcast(body.url, body.stage))

    @app.get("/api/admin/settings")
    def a_settings_view(_: dict = Depends(admin_user)):
        return ok({"items": bot_settings.admin_view()})

    @app.post("/api/admin/settings")
    def a_settings_set(body: SettingIn, _: dict = Depends(admin_user)):
        bot_settings.admin_set(body.key, body.value)
        return ok({"key": body.key, "items": bot_settings.admin_view()})

    @app.get("/api/admin/anon-logs")
    def a_anon_logs(page: int = Query(1, ge=1, le=1000), q: str = Query("", max_length=64), _: dict = Depends(admin_user)):
        return ok(anon_svc.admin_archive(page, 20, q))

    @app.get("/api/admin/gifts")
    def a_gifts(_: dict = Depends(admin_user)):
        return ok({"items": admin_svc.gifts()})

    @app.post("/api/admin/gifts")
    def a_gift_create(body: GiftIn, _: dict = Depends(admin_user)):
        return ok(admin_svc.create_gift(body.days, body.max_uses, body.code))

    @app.get("/api/admin/transactions")
    def a_transactions(page: int = Query(1, ge=1, le=1000), _: dict = Depends(admin_user)):
        return ok(admin_svc.transactions(page))

    @app.get("/api/admin/users")
    def a_users(q: str = Query("", max_length=64), filter: Literal["all", "vip", "banned"] = "all",
                sort: Literal["recent", "joined", "level", "snoops", "traps", "vip", "name"] = "recent",
                _: dict = Depends(admin_user)):
        return ok(admin_svc.search_users(q, filter, sort))

    @app.get("/api/admin/users/{user_id}")
    def a_user(user_id: int, _: dict = Depends(admin_user)):
        return ok(admin_svc.user_detail(user_id))

    @app.post("/api/admin/users/{user_id}/vip")
    def a_vip(user_id: int, body: VipChangeIn, _: dict = Depends(admin_user)):
        return ok(admin_svc.change_vip(user_id, body.action, body.days))

    @app.post("/api/admin/users/{user_id}/ban")
    def a_ban(user_id: int, body: BanIn, me_: dict = Depends(admin_user)):
        return ok(admin_svc.set_ban(me_["user_id"], user_id, body.banned))

    # v4.7: اخطار به کاربر + بازنشانی اخطارها (هم‌ارز پنل شیشه‌ای)
    @app.post("/api/admin/users/{user_id}/warn")
    def a_warn(user_id: int, body: WarnIn, me_: dict = Depends(admin_user)):
        if user_id == me_["user_id"]:
            raise AppError("VALIDATION_ERROR", "نمی‌توانید به خودتان اخطار بدهید.", 422)
        return ok(admin_svc.warn_user(user_id, body.reason or "اخطار از طرف مدیر"))

    @app.post("/api/admin/users/{user_id}/reset-warnings")
    def a_reset_warns(user_id: int, _: dict = Depends(admin_user)):
        return ok(admin_svc.reset_warnings(user_id))

    @app.post("/api/admin/users/{user_id}/message")
    def a_msg(user_id: int, body: TextIn, _: dict = Depends(admin_user)):
        return ok(admin_svc.direct_message(user_id, body.text))

    @app.get("/api/admin/broadcast/meta")
    def a_bmeta(_: dict = Depends(admin_user)):
        return ok(admin_svc.broadcast_meta())

    @app.post("/api/admin/broadcast")
    def a_broadcast(body: BroadcastIn, _: dict = Depends(admin_user)):
        return ok(admin_svc.start_broadcast(body.text, body.target))

    @app.get("/api/admin/broadcast/{job_id}")
    def a_bstatus(job_id: str, _: dict = Depends(admin_user)):
        return ok(admin_svc.broadcast_status(job_id))

    @app.get("/api/admin/tickets")
    def a_tickets(_: dict = Depends(admin_user)):
        return ok({"items": support.tickets()})

    @app.get("/api/admin/tickets/{user_id}")
    def a_ticket(user_id: int, _: dict = Depends(admin_user)):
        u = users.get(user_id)
        from services.common import display_name
        return ok({"user_id": user_id, "name": display_name(u), "status": support.ticket_status(user_id), "messages": support.messages(user_id, mark_read=True)})

    @app.post("/api/admin/tickets/{user_id}/reply")
    def a_reply(user_id: int, body: TextIn, _: dict = Depends(admin_user)):
        return ok(support.add_admin_reply(user_id, body.text))

    @app.post("/api/admin/tickets/{user_id}/close")
    def a_close(user_id: int, _: dict = Depends(admin_user)):
        support.close(user_id)
        return ok({"status": "closed"})

    @app.get("/api/admin/backup")
    def a_backup_info(_: dict = Depends(admin_user)):
        return ok(admin_svc.backup_info())

    @app.post("/api/admin/backup")
    def a_backup(_: dict = Depends(admin_user)):
        return ok(admin_svc.backup_now())

    # ---------- وب‌هوک بله ----------
    if settings.WEBHOOK_URL and settings.WEBHOOK_SECRET:
        # v5.0: به‌جای یک نخ مجزا برای هر آپدیت (burst ارسال زیر بار)،
        # صف داخلی با ۲-۴ worker — هم‌زمانی کنترل‌شده + گیت سراسری bot_sender.
        wh_pool = ThreadPoolExecutor(max_workers=settings.WEBHOOK_WORKERS,
                                     thread_name_prefix="bale-wh")
        # v5.1: حذف آپدیت تکراری — بله در نبود پاسخ ۲۰۰ همان آپدیت را دوباره
        # می‌فرستد؛ بدون dedupe، هر پیام کاربر دو-سه بار پردازش و دوبار ارسال می‌شد.
        _seen_ids: deque = deque(maxlen=4000)
        _seen_set: set = set()
        _seen_lock = threading.Lock()

        def _seen_before(update_id) -> bool:
            if update_id is None:
                return False
            with _seen_lock:
                if update_id in _seen_set:
                    return True
                _seen_set.add(update_id)
                _seen_ids.append(update_id)
                while len(_seen_set) > 4000 and _seen_ids:
                    _seen_set.discard(_seen_ids[0])
                    _seen_ids.popleft()
                return False

        @app.post("/bale/webhook/{secret}")
        async def webhook(secret: str, request: Request):
            if not hmac.compare_digest(secret, settings.WEBHOOK_SECRET):
                raise AppError("FORBIDDEN", "forbidden", 403)
            payload = await request.body()
            if app.state.bot is not None and payload:
                import telebot  # pyTelegramBotAPI (سازگار با Bot API بله)

                try:
                    update = telebot.types.Update.de_json(payload.decode("utf-8"))
                except Exception:
                    log.warning("webhook: invalid update payload (%d bytes)", len(payload))
                    return {"ok": True}
                if update is not None and not _seen_before(getattr(update, "update_id", None)):
                    try:
                        wh_pool.submit(app.state.bot.process_new_updates, [update])
                    except Exception:
                        # فالبک: اگر استخر مشکل خورد (shutdown/صف پر)، نخ عادی
                        threading.Thread(target=app.state.bot.process_new_updates,
                                         args=([update],), daemon=True).start()
            # پاسخ فوری: بله منتظر ۲۰۰ می‌ماند؛ تأخیر در پاسخ = ارسال دوبارهٔ آپدیت
            return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})

    # ---------- آواتار (پروکسی عکس پروفایل با امضا؛ بدون هدر initData چون تگ <img> است) ----------
    @app.get("/api/avatar/{uid}.jpg")
    def avatar(uid: int, e: str = Query(""), s: str = Query("")):
        if not avatars.check_sig(uid, e, s):
            raise AppError("FORBIDDEN", "لینک عکس معتبر نیست.", 403)
        data = avatars.get_avatar(uid)
        if not data:
            raise AppError("NOT_FOUND", "این کاربر عکس پروفایل ندارد.", 404)
        return Response(data, media_type="image/jpeg")

    # ---------- فرانت‌اند ----------
    index_cache: dict[str, str] = {}

    def asset_version() -> str:
        """نسخهٔ فایل‌های فرانت برای شکستن کش وب‌ویو (mtime آخرین تغییر)."""
        try:
            v = 0
            for name in ("app.css", "app.js", "gold.js", "img/logo.png", "img/logo-sm.png"):
                p = settings.WEBAPP_DIR / name
                if p.exists():
                    v = max(v, int(p.stat().st_mtime))
            return str(v)
        except Exception:
            return "1"

    @app.get("/", response_class=HTMLResponse)
    def index():
        if "html" not in index_cache:
            raw = (settings.WEBAPP_DIR / "index.html").read_text(encoding="utf-8")
            raw = raw.replace(DEFAULT_SDK_SRC, html.escape(settings.BALE_SDK_URL, quote=True))
            raw = re.sub(r"(?<![\w/$.-])(app\.css|app\.js|gold\.js|img/logo(?:-sm)?\.png)",
                         lambda m: m.group(1) + "?v=" + asset_version(), raw)
            index_cache["html"] = raw
        return HTMLResponse(index_cache["html"], headers={"Cache-Control": "no-cache"})

    @app.get("/config.js")
    def config_js():
        cfg = {"apiBase": "/api", "sdkGlobal": settings.BALE_SDK_GLOBAL, "botUsername": bale_api.bot_username() or "bot",
               "deepLinkBase": settings.BALE_DEEPLINK_BASE, "demo": settings.MINIAPP_DEMO}
        return Response("window.APP_CONFIG = " + json.dumps(cfg, ensure_ascii=False) + ";", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})

    if settings.WEBAPP_DIR.exists():
        app.mount("/", StaticFiles(directory=str(settings.WEBAPP_DIR), html=False), name="webapp")

    # v5.3: gzip (کاهش ۶۰-۸۰٪ پهنای‌باند JS/CSS/JSON) + سقف حجم بدنه — بیرونی‌ترین لایه‌ها
    app.add_middleware(SelectiveGZip)
    app.add_middleware(BodyLimitMiddleware)
    return app
