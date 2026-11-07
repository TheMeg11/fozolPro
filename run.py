"""نقطهٔ ورود سرویس Railway: ربات بله + API مینی‌اپ در یک پروسس.

- uvicorn روی 0.0.0.0:$PORT؛ SIGTERM/SIGINT توسط uvicorn مدیریت می‌شود و پس از آن polling متوقف و DB بسته می‌شود.
- دریافت آپدیت: polling (پیش‌فرض) یا webhook (WEBHOOK_URL + WEBHOOK_SECRET).
- فقط یک instance (numReplicas=1) به‌خاطر SQLite و polling.
"""
from __future__ import annotations

import logging
import sys
import threading

import uvicorn

import settings


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def configure_telebot_for_bale() -> None:
    """pyTelegramBotAPI فقط به‌خاطر سازگاری API استفاده می‌شود؛ همهٔ درخواست‌ها به سرور بله می‌رود."""
    from telebot import apihelper

    apihelper.API_URL = settings.BALE_API_BASE + "/bot{0}/{1}"
    apihelper.FILE_URL = settings.BALE_FILE_BASE + "/bot{0}/{1}"


def load_bot():
    """ربات فعلی را از main.py بارگذاری می‌کند (main.py نباید هنگام import، polling را شروع کند — patch را ببینید)."""
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


def main() -> None:
    setup_logging()
    log = logging.getLogger("run")
    from services import admin, db

    db.migrate()
    admin.recover_jobs()
    bot, legacy = load_bot()

    if bot is not None:
        if settings.WEBHOOK_URL and settings.WEBHOOK_SECRET:
            from services import bale_api

            bale_api.set_webhook(f"{settings.WEBHOOK_URL}/bale/webhook/{settings.WEBHOOK_SECRET}")
            log.info("webhook mode")
        else:
            start_polling(bot)
            log.info("polling mode")
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
        db.close_all()
        log.info("shutdown complete")


if __name__ == "__main__":
    main()
