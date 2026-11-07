"""کلاینت حداقلی Bot API بله (فقط آدرس‌های پایهٔ بله از settings).

API مینی‌اپ برای ارسال پیام/فاکتور/فایل از این ماژول استفاده می‌کند تا به نمونهٔ telebot وابسته نباشد.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

import requests

import settings
from services.common import AppError

log = logging.getLogger("bale_api")
_session = requests.Session()
_me_lock = threading.Lock()
_me_cache: dict[str, Any] = {}


class BaleApiError(AppError):
    pass


def _url(method: str) -> str:
    return f"{settings.BALE_API_BASE}/bot{settings.BOT_TOKEN}/{method}"


def call(method: str, timeout: float = 20, files: dict | None = None, **params: Any) -> Any:
    if not settings.BOT_TOKEN:
        raise BaleApiError("BOT_NOT_CONFIGURED", "توکن ربات تنظیم نشده است.", 503)
    try:
        if files:
            resp = _session.post(_url(method), data={k: v for k, v in params.items() if v is not None}, files=files, timeout=timeout)
        else:
            resp = _session.post(_url(method), json={k: v for k, v in params.items() if v is not None}, timeout=timeout)
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("bale api %s failed: %s", method, exc.__class__.__name__)
        raise BaleApiError("BALE_UNAVAILABLE", "ارتباط با سرور بله برقرار نشد.", 502) from None
    if not data.get("ok"):
        desc = str(data.get("description", ""))[:200]
        log.warning("bale api %s error: %s", method, desc)
        raise BaleApiError("BALE_API_ERROR", "سرور بله درخواست را نپذیرفت.", 502, {"description": desc})
    return data.get("result")


def get_me() -> dict:
    with _me_lock:
        if not _me_cache:
            _me_cache.update(call("getMe") or {})
        return dict(_me_cache)


def bot_username() -> str:
    if settings.BOT_USERNAME:
        return settings.BOT_USERNAME
    try:
        return (get_me().get("username") or "").lstrip("@")
    except AppError:
        return ""


def send_message(chat_id: int, text: str, reply_markup: dict | None = None) -> Any:
    return call("sendMessage", chat_id=chat_id, text=text[:4096], reply_markup=reply_markup)


def send_invoice(chat_id: int, title: str, description: str, payload: str, amount_rial: int, label: str) -> Any:
    """همان الگوی sendInvoice ربات فعلی؛ مبلغ به ریال، provider_token = PROVIDER_TOKEN (WALLET-...)."""
    if not settings.PROVIDER_TOKEN:
        raise BaleApiError("PAYMENT_NOT_CONFIGURED", "درگاه پرداخت تنظیم نشده است.", 503)
    return call(
        "sendInvoice",
        chat_id=chat_id, title=title, description=description, payload=payload,
        provider_token=settings.PROVIDER_TOKEN, currency="IRR",
        prices=[{"label": label, "amount": int(amount_rial)}],
    )


def send_document(chat_id: int, path: str, filename: str, caption: str = "") -> Any:
    with open(path, "rb") as fh:
        return call("sendDocument", timeout=120, files={"document": (filename, fh)}, chat_id=str(chat_id), caption=caption[:1024])


def get_chat_member(chat_id: str | int, user_id: int) -> dict:
    return call("getChatMember", chat_id=chat_id, user_id=user_id) or {}


def get_chat(chat_id: str | int) -> dict:
    return call("getChat", chat_id=chat_id) or {}


def set_webhook(url: str) -> Any:
    return call("setWebhook", url=url)


def delete_webhook() -> Any:
    return call("deleteWebhook")
