"""نقطهٔ ورود سرویس Railway: ربات بله + API مینی‌اپ در یک پروسس.

- uvicorn روی 0.0.0.0:$PORT؛ SIGTERM/SIGINT توسط uvicorn مدیریت می‌شود و پس از آن polling متوقف و DB بسته می‌شود.
- دریافت آپدیت: webhook (پیش‌فرض وقتی WEBHOOK_URL + WEBHOOK_SECRET ست باشد) یا polling.
  v5.1: در حالت webhook، ست‌کردن وبهوک **بعد از بالا آمدن پورت** انجام می‌شود؛
  قبلاً قبل از listen ست می‌شد و در پنجرهٔ کوتاه اولیه بله ۴۰۴ می‌گرفت.
- گارد حافظه (memguard) برای پلن ۵۱۲MB: RSS واقعی + بهداشت + ری‌استارت محترمانه.
- فقط یک instance (numReplicas=1) به‌خاطر SQLite و polling.
"""
from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time

import uvicorn

import settings


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    # لاگ‌های پرحجمِ کتابخانه که فقط نویز تولید می‌کنند (مصرف CPU/حافظه در پلن کوچک)
    logging.getLogger("telebot").setLevel(logging.WARNING)


def configure_telebot_for_bale() -> None:
    """pyTelegramBotAPI فقط به‌خاطر سازگاری API استفاده می‌شود؛ همهٔ درخواست‌ها به سرور بله می‌رود."""
    from telebot import apihelper

    apihelper.API_URL = settings.BALE_API_BASE + "/bot{0}/{1}"
    apihelper.FILE_URL = settings.BALE_FILE_BASE + "/bot{0}/{1}"


def load_bot():
    """ربات فعلی را از main.py بارگذاری می‌کند (main.py نباید هنگام import، polling را شروع کند)."""
    log = logging.getLogger("run")
    if not settings.BOT_TOKEN:
        log.warning("BOT_TOKEN not set — running API only")
        return None, None
    configure_telebot_for_bale()
    try:
        import main as legacy  # ربات موجود
    except Exception:
        log.exception("could not import main.py — running API only")
        return None, None
    bot = getattr(legacy, "bot", None)
    if bot is None:
        log.error("main.py has no `bot` object — running API only")
        return None, legacy
    from bot_integration import register_handlers, setup_menu_button

    if not getattr(legacy, "MINIAPP_HANDLERS_REGISTERED", False):
        register_handlers(bot)
    setup_menu_button()
    return bot, legacy


def start_polling(bot) -> threading.Thread:
    from services import bale_api

    try:
        bale_api.delete_webhook()
    except Exception:
        pass

    def _run():
        bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20, logger_level=logging.WARNING)

    t = threading.Thread(target=_run, name="bale-polling", daemon=True)
    t.start()
    return t


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=0.5):
            return True
    except OSError:
        return False


def set_webhook_when_listening(url: str, timeout: float = 90.0) -> None:
    """v5.1: وبهوک فقط وقتی ست می‌شود که خود سرویس در حال listen باشد.

    اگر setWebhook قبل از آمادگی پورت اجرا شود، بله ممکن است آپدیت‌ها را در
    همان پنجره به سرویسِ در حال ری‌استارت بفرستد و گم شوند.
    """
    log = logging.getLogger("webhook")
    from services import bale_api

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_open(settings.PORT):
            break
        time.sleep(0.5)
    else:
        log.warning("port %s did not open in %.0fs — setting webhook anyway", settings.PORT, timeout)

    for attempt in range(1, 6):
        try:
            # فقط url — بله پارامترهای اضافی تلگرامی را در برخی نسخه‌ها رد می‌کند
            bale_api.call("setWebhook", url=url)
            log.info("✅ webhook set → %s", url)
            try:
                info = bale_api.call("getWebhookInfo") or {}
                log.info("webhook info: url=%s pending=%s last_error=%s",
                         info.get("url"), info.get("pending_update_count"), info.get("last_error_message"))
            except Exception:
                pass
            return
        except Exception as exc:
            wait = min(30, 2 ** attempt)
            log.warning("setWebhook attempt %d failed (%s) — retry in %ss", attempt, exc.__class__.__name__, wait)
            time.sleep(wait)
    log.error("❌ could not set webhook — سرویس در حالت بدون آپدیت می‌ماند؛ WEBHOOK_URL را بررسی کنید")


def log_effective_config() -> None:
    """خلاصهٔ تنظیمات مؤثر در استارتاپ — برای دیباگ سریع از روی لاگ Railway."""
    import bot_sender

    log = logging.getLogger("run")
    mode = "webhook" if (settings.WEBHOOK_URL and settings.WEBHOOK_SECRET) else "polling"
    log.info(
        "config: mode=%s port=%s webapp=%s | send-gate=%.1f/s burst=%d bulk=%.1f/s edit=%.1f/s "
        "per_chat=%.1fs inline_budget=%.0fs | webhook_workers=%d",
        mode, settings.PORT, settings.WEBAPP_URL or "-",
        bot_sender.RATE_PER_SEC, bot_sender.BURST, bot_sender.BULK_RATE_PER_SEC,
        bot_sender.EDIT_RATE_PER_SEC, bot_sender.PER_CHAT_SEC, bot_sender.INLINE_BUDGET,
        settings.WEBHOOK_WORKERS,
    )


def main() -> None:
    setup_logging()
    log = logging.getLogger("run")
    from services import admin, db

    db.migrate()
    admin.recover_jobs()
    log_effective_config()

    import memguard

    memguard.start()

    bot, legacy = load_bot()
    webhook_url = f"{settings.WEBHOOK_URL}/bale/webhook/{settings.WEBHOOK_SECRET}" if (
        settings.WEBHOOK_URL and settings.WEBHOOK_SECRET) else ""

    if bot is not None:
        if webhook_url:
            threading.Thread(target=set_webhook_when_listening, args=(webhook_url,),
                             name="webhook-setup", daemon=True).start()
            log.info("mode: webhook (set after port is ready)")
        elif settings.WEBHOOK_URL and not settings.WEBHOOK_SECRET:
            log.warning("WEBHOOK_URL ست شده ولی WEBHOOK_SECRET خالی است — به polling برمی‌گردیم")
            start_polling(bot)
        else:
            start_polling(bot)
            log.info("mode: polling")
        starter = getattr(legacy, "start_background_tasks", None)  # tasks.py: بکاپ شبانه و انقضای VIP
        if callable(starter):
            starter(bot)

    from app import create_app

    server = uvicorn.Server(uvicorn.Config(create_app(bot), host="0.0.0.0", port=settings.PORT, log_config=None,
                                           proxy_headers=True, forwarded_allow_ips="*", timeout_graceful_shutdown=10))
    log.info("listening on 0.0.0.0:%s (webapp: %s)", settings.PORT, settings.WEBAPP_URL or "not set")
    try:
        server.run()  # تا SIGTERM بلاک می‌شود
    finally:
        if bot is not None:
            try:
                bot.stop_polling()
            except Exception:
                pass
        try:
            db.close_all()
        except Exception:
            pass
        log.info("shutdown complete")
        # v5.2: اگر خاموشی به‌خاطر گارد حافظه بود، با کد 1 خارج شو تا Railway
        # سرویس را ری‌استارت کند. با exit 0 و restartPolicy=ON_FAILURE سرویس
        # برای همیشه خاموش می‌ماند (علت اصلی قطعی ۲۶ نوامبر).
        if memguard.SELF_TERMINATED:
            log.warning("exit(1) به‌خاطر ری‌استارت حافظه‌ای — درخواست بالا آمدن دوباره به Railway")
            os._exit(1)


if __name__ == "__main__":
    main()
