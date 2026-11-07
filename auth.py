"""اعتبارسنجی initData مینی‌اپ بله (فقط سمت سرور).

الگوریتم (طبق docs.bale.ai/miniapp — «اعتبارسنجی داده‌های دریافت‌شده از طریق مینی‌اپ»):
  data_check_string = همهٔ جفت‌های key=value به‌جز hash، مرتب‌شده بر اساس کلید، جداشده با '\\n'
  secret_key        = HMAC_SHA256(key=INITDATA_HMAC_KEY ("WebAppData"), msg=bot_token)
  hash              = hex(HMAC_SHA256(key=secret_key, msg=data_check_string))
مقایسه با hmac.compare_digest و بررسی auth_date. به user_id ارسالی کلاینت هرگز اعتماد نمی‌شود؛
هویت فقط از فیلد user داخل initData امضاشده خوانده می‌شود.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode

MAX_INITDATA_LEN = 8192
FUTURE_SKEW_SEC = 120


class InitDataError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _secret(bot_token: str, hmac_key: str) -> bytes:
    return hmac.new(hmac_key.encode(), bot_token.encode(), hashlib.sha256).digest()


def _check_string(fields: dict[str, str]) -> str:
    return "\n".join(f"{k}={fields[k]}" for k in sorted(fields))


def compute_hash(fields: dict[str, str], bot_token: str, hmac_key: str = "WebAppData") -> str:
    clean = {k: v for k, v in fields.items() if k != "hash"}
    return hmac.new(_secret(bot_token, hmac_key), _check_string(clean).encode(), hashlib.sha256).hexdigest()


def sign_init_data(fields: dict[str, Any], bot_token: str, hmac_key: str = "WebAppData") -> str:
    """ساخت initData امضاشده (برای تست و ابزار توسعه)."""
    str_fields = {k: (json.dumps(v, ensure_ascii=False, separators=(",", ":")) if isinstance(v, (dict, list)) else str(v)) for k, v in fields.items()}
    str_fields["hash"] = compute_hash(str_fields, bot_token, hmac_key)
    return urlencode(str_fields)


def validate_init_data(
    init_data: str | None,
    bot_token: str,
    max_age: int = 86400,
    hmac_key: str = "WebAppData",
    now: int | None = None,
) -> dict[str, Any]:
    if not init_data:
        raise InitDataError("AUTH_REQUIRED", "برای استفاده، مینی‌اپ را از داخل بله باز کنید.")
    if not bot_token:
        raise InitDataError("AUTH_INVALID", "توکن ربات روی سرور تنظیم نشده است.")
    if len(init_data) > MAX_INITDATA_LEN:
        raise InitDataError("AUTH_INVALID", "دادهٔ نشست نامعتبر است.")
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        raise InitDataError("AUTH_INVALID", "دادهٔ نشست قابل خواندن نیست.") from None

    fields: dict[str, str] = {}
    for key, value in pairs:
        if key in fields:  # کلید تکراری = تلاش برای دست‌کاری
            raise InitDataError("AUTH_INVALID", "دادهٔ نشست نامعتبر است.")
        fields[key] = value

    received = fields.pop("hash", "")
    if not received:
        raise InitDataError("AUTH_INVALID", "امضای نشست وجود ندارد.")
    expected = hmac.new(_secret(bot_token, hmac_key), _check_string(fields).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received.lower()):
        raise InitDataError("AUTH_INVALID", "اعتبار نشست تأیید نشد. مینی‌اپ را دوباره از بله باز کنید.")

    try:
        auth_date = int(fields.get("auth_date", ""))
    except ValueError:
        raise InitDataError("AUTH_INVALID", "زمان نشست نامعتبر است.") from None
    now = int(time.time()) if now is None else now
    if auth_date > now + FUTURE_SKEW_SEC:
        raise InitDataError("AUTH_INVALID", "زمان نشست نامعتبر است.")
    if max_age > 0 and now - auth_date > max_age:
        raise InitDataError("AUTH_EXPIRED", "نشست شما منقضی شده؛ مینی‌اپ را ببندید و دوباره باز کنید.")

    try:
        user = json.loads(fields.get("user") or "null")
    except json.JSONDecodeError:
        raise InitDataError("AUTH_INVALID", "اطلاعات کاربر نامعتبر است.") from None
    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        raise InitDataError("AUTH_INVALID", "اطلاعات کاربر در نشست وجود ندارد.")

    return {
        "user": user,
        "auth_date": auth_date,
        "query_id": fields.get("query_id"),
        "start_param": fields.get("start_param"),
        "raw": fields,
    }
