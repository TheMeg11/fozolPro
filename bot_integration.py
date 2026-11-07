"""اتصال ربات فعلی بله (main.py / pyTelegramBotAPI) به مینی‌اپ و لایهٔ سرویس.

از main.py صدا زده می‌شود (patch در PATCH_main_py.md):
    from bot_integration import webapp_markup, webapp_reply_keyboard, handle_start_payload, register_handlers, setup_menu_button
"""
from __future__ import annotations

import logging

import settings
from services import bale_api, support, users, vip
from services.common import AppError

log = logging.getLogger("bot_integration")
WEBAPP_BUTTON_TEXT = "📱 باز کردن مینی‌اپ"   # طبق راهنمای بله حداکثر ۲۰ کاراکتر


def webapp_url(start: str | None = None) -> str:
    if not settings.WEBAPP_URL:
        return ""
    return settings.WEBAPP_URL + "/" + (f"?startapp={start}" if start else "")


def webapp_markup(start: str | None = None):
    """دکمهٔ شیشه‌ای web_app زیر پیام (/start و منوی اصلی)."""
    from telebot import types

    kb = types.InlineKeyboardMarkup()
    if settings.WEBAPP_URL:
        kb.add(types.InlineKeyboardButton(WEBAPP_BUTTON_TEXT, web_app=types.WebAppInfo(webapp_url(start))))
    return kb


def append_webapp_button(markup) -> bool:
    """افزودن دکمهٔ شیشه‌ای web_app به یک InlineKeyboardMarkup موجود (منوی ربات)."""
    if not settings.WEBAPP_URL:
        return False
    try:
        from telebot import types
        markup.add(types.InlineKeyboardButton(WEBAPP_BUTTON_TEXT, web_app=types.WebAppInfo(webapp_url())))
        return True
    except Exception:
        return False


def webapp_reply_keyboard(extra_rows: list[list[str]] | None = None):
    """صفحه‌کلید ریپلای با دکمهٔ web_app در ردیف اول + ردیف‌های فعلی منوی ربات."""
    from telebot import types

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if settings.WEBAPP_URL:
        kb.row(types.KeyboardButton(WEBAPP_BUTTON_TEXT, web_app=types.WebAppInfo(webapp_url())))
    for row in extra_rows or []:
        kb.row(*[types.KeyboardButton(t) for t in row])
    return kb


def setup_menu_button() -> bool:
    """Menu Button مینی‌اپ. اگر Bot API بله setChatMenuButton را پشتیبانی نکند، از BotFather بله تنظیم کنید."""
    if not settings.WEBAPP_URL:
        return False
    try:
        bale_api.call("setChatMenuButton", menu_button={"type": "web_app", "text": "مینی‌اپ", "web_app": {"url": webapp_url()}})
        log.info("menu button set to %s", settings.WEBAPP_URL)
        return True
    except AppError as exc:
        log.info("setChatMenuButton not available (%s) — configure via BotFather in Bale", exc.code)
        return False


def handle_start_payload(bot, message, payload: str) -> bool:
    """پارامترهای deep link در /start. True یعنی پردازش شد و هندلر فعلی /start ادامه ندهد."""
    u = message.from_user
    user = {"id": u.id, "first_name": u.first_name, "last_name": getattr(u, "last_name", None), "username": getattr(u, "username", None)}
    users.ensure_user(user)
    # نکتهٔ fozol-pro: کدهای تله و لینک‌های فضول‌یابی مستقیماً توسط هندلر اصلی
    # ربات (main.py) پردازش می‌شوند؛ اینجا فقط deep linkهای مینی‌اپ هندل می‌شوند.
    if payload == "support":
        bot.send_message(message.chat.id, "📎 عکس، ویدیو یا فایل خود را همین‌جا بفرستید تا به پشتیبانی برسد.")
        return True
    if payload == "restore" and settings.is_admin(u.id):
        bot.send_message(message.chat.id, "🗄 برای بازیابی، دستور /restore را بزنید و سپس فایل بکاپ را ارسال کنید.")
        return True
    if payload == "broadcast" and settings.is_admin(u.id):
        bot.send_message(message.chat.id, "📣 برای پخش مدیا، از مسیر پخش همگانی فعلی ربات استفاده کنید.")
        return True
    # v4.3: باز کردن هویت فضول از مینی‌اپ (پرداخت در چت ربات) — payload: reveal_<clicker_id>
    if payload.startswith("reveal_"):
        _reveal_invoice(bot, message.chat.id, u.id, payload[len("reveal_"):])
        return True
    return False


def _reveal_invoice(bot, chat_id: int, user_id: int, cid_raw: str) -> None:
    """فاکتور «باز کردن هویت» — همان جریان دکمهٔ reveal_buy_ در ربات (payload یکسان).
    منبع داده: همان DB ربات (جدول‌های settings/reveals/clicks) از طریق services.db."""
    try:
        from telebot import types
        from services import bot_settings, db as sdb
        try:
            cid = int(str(cid_raw).strip())
        except (TypeError, ValueError):
            bot.send_message(chat_id, "⛔ درخواست نامعتبر است.")
            return
        if vip.is_active(user_id):
            bot.send_message(chat_id, "🏅 تو VIP هستی — هویت فضول‌ها برایت رایگان و کامل نمایش داده می‌شود!")
            return
        if sdb.row("SELECT 1 FROM reveals WHERE owner_id=? AND clicker_id=?", (user_id, cid)):
            bot.send_message(chat_id, "✅ این هویت قبلاً باز شده — از «اطلاعات فضول» ببین.")
            return
        if not sdb.row("SELECT 1 FROM clicks WHERE owner_id=? AND clicker_id=? LIMIT 1", (user_id, cid)):
            bot.send_message(chat_id, "⛔ این کاربر فضول تلهٔ تو نیست.")
            return
        price_rial = bot_settings.get_int("reveal_price", 30000)
        payload_full = f"reveal_{user_id}_{cid}"
        try:
            bot.send_invoice(chat_id,
                             title="🔓 باز کردن هویت فضول",
                             description="مشاهدهٔ شناسه و آیدی کامل این فضول — برای همیشه",
                             invoice_payload=payload_full, provider_token=settings.PROVIDER_TOKEN, currency="IRT",
                             prices=[types.LabeledPrice(label="باز کردن هویت", amount=price_rial)],
                             need_name=False, need_phone_number=False, need_email=False, is_flexible=False)
        except Exception as exc:
            log.error("reveal invoice error (miniapp deep link): %s", exc)
            bot.send_message(chat_id, "❌ خطا در ایجاد فاکتور. درگاه پرداخت ممکن است فعال نباشد.")
    except Exception:
        log.exception("reveal deep-link failed")
        try:
            bot.send_message(chat_id, "❌ خطای غیرمنتظره؛ دوباره تلاش کنید.")
        except Exception:
            pass


def register_handlers(bot) -> None:
    """هندلرهای پرداخت و مدیای پشتیبانی که با لایهٔ سرویس کار می‌کنند.
    اگر main.py هندلر پرداخت دارد، بدنهٔ آن را با همین توابع جایگزین کنید (نه هر دو)."""

    @bot.pre_checkout_query_handler(func=lambda q: str(q.invoice_payload).startswith("vip:"))
    def _pre_checkout(q):
        valid = vip.validate_pre_checkout(q.invoice_payload, q.from_user.id, getattr(q, "total_amount", None))
        bot.answer_pre_checkout_query(q.id, ok=valid, error_message=None if valid else "این فاکتور معتبر نیست؛ از مینی‌اپ دوباره اقدام کنید.")

    @bot.message_handler(content_types=["successful_payment"], func=lambda m: str(m.successful_payment.invoice_payload).startswith("vip:"))
    def _paid(m):
        sp = m.successful_payment
        st = vip.handle_successful_payment(m.from_user.id, sp.invoice_payload, getattr(sp, "provider_payment_charge_id", None))
        if st:
            bot.send_message(m.chat.id, st["message"], reply_markup=webapp_markup("vip"))

    @bot.message_handler(commands=["app"])
    def _app(m):
        bot.send_message(m.chat.id, "مینی‌اپ فضول‌یاب 👇", reply_markup=webapp_markup())


def save_support_media(message) -> None:
    """از هندلر فعلی پشتیبانی برای مدیا صدا بزنید تا در صندوق مینی‌اپ هم دیده شود."""
    ct = message.content_type
    file_id = None
    if ct == "photo":
        file_id = message.photo[-1].file_id
    elif ct in ("video", "document", "voice", "audio"):
        file_id = getattr(message, ct).file_id
    support.add_user_message(message.from_user.id, message.caption or "", media_type=ct, file_id=file_id, notify=False)
