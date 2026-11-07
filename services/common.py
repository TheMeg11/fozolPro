"""ابزارهای مشترک لایهٔ سرویس: خطای یکپارچه، زمان، تاریخ شمسی."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

TEHRAN = timezone(timedelta(hours=3, minutes=30))  # ایران از ۱۴۰۱ ساعت تابستانی ندارد


class AppError(Exception):
    """خطای کسب‌وکار؛ هم در API (JSON) و هم در ربات (متن پیام) قابل استفاده."""

    def __init__(self, code: str, message: str, status: int = 400, details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details or {}


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or now()).astimezone(timezone.utc).isoformat(timespec="seconds")


def parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def tehran_day_start(days_ago: int = 0) -> datetime:
    t = now().astimezone(TEHRAN)
    start = t.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
    return start.astimezone(timezone.utc)


def jalali(value: str | datetime | None, with_time: bool = False) -> str:
    """نمایش تاریخ شمسی برای پیام‌های ربات (jdatetime از وابستگی‌های فعلی پروژه است)."""
    dt = parse(value) if isinstance(value, str) or value is None else value
    if not dt:
        return "—"
    local = dt.astimezone(TEHRAN)
    try:
        import jdatetime

        j = jdatetime.datetime.fromgregorian(datetime=local.replace(tzinfo=None))
        return j.strftime("%Y/%m/%d %H:%M" if with_time else "%Y/%m/%d")
    except Exception:  # pragma: no cover
        return local.strftime("%Y-%m-%d %H:%M" if with_time else "%Y-%m-%d")


def mask_name(name: str) -> str:
    return " ".join((w[0] + "***") for w in (name or "؟").split() if w) or "؟***"


def display_name(u: dict) -> str:
    return (f"{u.get('first_name') or ''} {u.get('last_name') or ''}").strip() or (u.get("username") or "کاربر")
