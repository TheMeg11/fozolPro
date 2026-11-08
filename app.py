"""REST API مینی‌اپ بله + سرو فرانت‌اند (همان پروسس ربات).

قرارداد پاسخ: موفق {"ok": true, "data": ...} | خطا {"ok": false, "error": {"code", "message", "details"}}
احراز هویت: هدر X-Bale-Init-Data (initData خام بله) → اعتبارسنجی HMAC روی سرور. مجوز ادمین فقط با ADMIN_ID سمت سرور.
"""
from __future__ import annotations

import hmac
import html
import json
import logging
import re
import threading
import time
from collections import defaultdict, deque
from typing import Any, Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
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
            if len(self.hits) > 20000:  # جلوگیری از رشد بی‌رویه
                for k in [k for k, v in self.hits.items() if not v][:5000]:
                    self.hits.pop(k, None)


limiter = RateLimiter(settings.RATE_LIMIT_PER_MIN)


# ---------------- Dependencies ----------------
def current_user(request: Request) -> dict:
    ip = request.client.host if request.client else "?"
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
        path = request.url.path
        if path.startswith("/api/avatar/"):
            response.headers["Cache-Control"] = "public, max-age=86400, stale-while-revalidate=604800"
        elif path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        elif path.startswith("/fonts/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path != "/health":
            response.headers.setdefault("Cache-Control", "no-cache")
        if path != "/health" and not path.startswith("/api/avatar/"):
            log.info("%s %s %s %.0fms", request.method, path, response.status_code, (time.perf_counter() - start) * 1000)
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
    def profile_edit(body: dict, user: dict = Depends(member_user)):
        raw_title = body.get("active_title")
        try:
            active_title = int(raw_title) if raw_title is not None else None
        except (TypeError, ValueError):
            raise AppError("VALIDATION_ERROR", "لقب انتخابی نامعتبر است.", 422) from None
        return ok(profile_svc.update(
            user["user_id"],
            display_name_str=body.get("display_name") if "display_name" in body else None,
            active_title=active_title,
            reset_name=bool(body.get("reset_name")),
            reset_title=bool(body.get("reset_title")),
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

    # ---------- XP / لیدربورد / گردونه ----------
    @app.get("/api/leaderboard")
    def leaderboard(period: Literal["week", "all"] = "week", user: dict = Depends(member_user)):
        return ok(users.leaderboard(period, user["user_id"]))

    @app.post("/api/leaderboard/visibility")
    def leaderboard_visibility(body: dict, user: dict = Depends(member_user)):
        """v4.4: کلید روشن/خاموش نمایش نام من در برترین‌ها — جداگانه برای هفتگی و کل."""
        period = str(body.get("period") or "week")
        if period not in ("week", "all"):
            raise AppError("VALIDATION_ERROR", "بازهٔ نامعتبر است.", 422)
        users.set_hidden(period, user["user_id"], bool(body.get("hidden")))
        return ok({"period": period, "hidden": bool(body.get("hidden"))})

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
    def a_challenge_op(body: dict, _: dict = Depends(admin_user)):
        action = str(body.get("action") or "")
        if action == "start":
            # v4.6: نوع جایزه (vip | envelope)، مبلغ پاکت و متن اعلان شروع قابل ویرایش
            return ok(admin_svc.challenge_start(
                int(body.get("hours") or 24), int(body.get("reward_days") or 3),
                str(body.get("reward_type") or "vip"), int(body.get("reward_amount") or 0),
                str(body.get("announce_text") or "")))
        if action == "cancel":
            return ok(admin_svc.challenge_cancel())
        raise AppError("VALIDATION_ERROR", "action نامعتبر است.", 422)

    @app.get("/api/admin/forced-channels")
    def a_channels(_: dict = Depends(admin_user)):
        return ok(admin_svc.forced_channels())

    @app.post("/api/admin/forced-channels")
    def a_channel_add(body: dict, _: dict = Depends(admin_user)):
        return ok(admin_svc.add_forced_channel(str(body.get("channel_id") or ""), str(body.get("title") or ""), int(body.get("target") or 0)))

    @app.delete("/api/admin/forced-channels/{channel_id}")
    def a_channel_del(channel_id: str, _: dict = Depends(admin_user)):
        return ok(admin_svc.remove_forced_channel(channel_id))

    @app.post("/api/admin/ad-broadcast")
    def a_ad_broadcast(body: dict, _: dict = Depends(admin_user)):
        return ok(admin_svc.ad_broadcast(str(body.get("url") or ""), str(body.get("stage") or "preview")))

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

    # ---------- وب‌هوک بله (اختیاری) ----------
    if settings.WEBHOOK_URL and settings.WEBHOOK_SECRET:
        @app.post("/bale/webhook/{secret}")
        async def webhook(secret: str, request: Request):
            if not hmac.compare_digest(secret, settings.WEBHOOK_SECRET):
                raise AppError("FORBIDDEN", "forbidden", 403)
            payload = await request.body()
            if app.state.bot is not None:
                import telebot  # pyTelegramBotAPI (سازگار با Bot API بله)

                update = telebot.types.Update.de_json(payload.decode("utf-8"))
                threading.Thread(target=app.state.bot.process_new_updates, args=([update],), daemon=True).start()
            return {"ok": True}

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

    return app
