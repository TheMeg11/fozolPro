"""پشتیبانی دوطرفه. پیام‌های متنی از مینی‌اپ و چت در یک جدول ذخیره می‌شوند؛
مدیا از چت ربات ثبت می‌شود (add_user_message با media_type/file_id از هندلر ربات)."""
from __future__ import annotations

import logging

import settings
from services import avatars, bale_api, db, users
from services.common import AppError, display_name, iso

log = logging.getLogger("support")


def _touch(c, user_id: int, status: str = "open") -> None:
    c.execute("INSERT INTO support_tickets(user_id, status, updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at",
              (user_id, status, iso()))


def _clean(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise AppError("VALIDATION_ERROR", "متن پیام خالی است.", 422)
    if len(text) > 2000:
        raise AppError("VALIDATION_ERROR", "متن پیام حداکثر ۲۰۰۰ کاراکتر است.", 422)
    return text


def add_user_message(user_id: int, text: str, media_type: str | None = None, file_id: str | None = None, notify: bool = True) -> dict:
    text = (text or "").strip() if media_type else _clean(text)
    ts = iso()
    with db.tx() as c:
        mid = c.execute("INSERT INTO support_messages(user_id, sender, text, media_type, file_id, created_at) VALUES(?, 'user', ?, ?, ?, ?)",
                        (user_id, text, media_type, file_id, ts)).lastrowid
        _touch(c, user_id, "open")
    if notify and settings.SUPPORT_NOTIFY_ADMIN and settings.ADMIN_ID:
        try:
            u = users.get(user_id)
            # v4.4: پشتیبانی اولویت‌دار — پیام کاربر VIP با برچسب ⚡️ برای ادمین
            prio = " ⚡️ VIP" if legacy_vip(user_id) else ""
            bale_api.send_message(settings.ADMIN_ID, f"📩 پیام پشتیبانی{prio} از {display_name(u)} (#{user_id}):\n\n{text or '[مدیا]'}")
        except AppError as exc:
            log.warning("admin notify failed: %s", exc.code)
    return {"id": mid, "from": "user", "text": text, "media_type": media_type, "created_at": ts}


def add_admin_reply(user_id: int, text: str, deliver: bool = True) -> dict:
    text = _clean(text)
    users.get(user_id)
    if deliver:
        bale_api.send_message(user_id, f"💬 پاسخ پشتیبانی:\n\n{text}")
    ts = iso()
    with db.tx() as c:
        mid = c.execute("INSERT INTO support_messages(user_id, sender, text, read_by_admin, created_at) VALUES(?, 'admin', ?, 1, ?)", (user_id, text, ts)).lastrowid
        _touch(c, user_id, "open")
    return {"id": mid, "from": "admin", "text": text, "created_at": ts}


def messages(user_id: int, mark_read: bool = False, limit: int = 200) -> list[dict]:
    if mark_read:
        db.execute("UPDATE support_messages SET read_by_admin=1 WHERE user_id=? AND sender='user' AND read_by_admin=0", (user_id,))
    rs = db.rows("SELECT * FROM (SELECT * FROM support_messages WHERE user_id=? ORDER BY id DESC LIMIT ?) ORDER BY id", (user_id, limit))
    return [{"id": r["id"], "from": r["sender"], "text": r["text"] or "", "media_type": r["media_type"], "created_at": r["created_at"]} for r in rs]


def ticket_status(user_id: int) -> str:
    return db.scalar("SELECT status FROM support_tickets WHERE user_id=?", (user_id,), "open")


def close(user_id: int) -> None:
    with db.tx() as c:
        _touch(c, user_id, "closed")


def legacy_vip(user_id: int) -> bool:
    """وضعیت VIP مؤثر (جدول ربات + مینی‌اپ) — برای اولویت پشتیبانی و برچسب‌ها."""
    try:
        from services import legacy_bridge
        return legacy_bridge.is_vip(user_id)
    except Exception:
        return False


def tickets(limit: int = 100) -> list[dict]:
    # v4.4: ترتیب اولویت — تیکت‌های VIP بالاتر از بقیه نمایش داده می‌شوند
    rs = db.rows("""SELECT t.user_id, t.status, t.updated_at, u.first_name, u.last_name, u.username,
                    (SELECT COUNT(*) FROM support_messages m WHERE m.user_id=t.user_id AND m.sender='user' AND m.read_by_admin=0) AS unread,
                    (SELECT text FROM support_messages m WHERE m.user_id=t.user_id ORDER BY id DESC LIMIT 1) AS last_text,
                    (SELECT media_type FROM support_messages m WHERE m.user_id=t.user_id ORDER BY id DESC LIMIT 1) AS last_media,
                    (SELECT sender FROM support_messages m WHERE m.user_id=t.user_id ORDER BY id DESC LIMIT 1) AS last_from
                    FROM support_tickets t LEFT JOIN users u ON u.user_id=t.user_id
                    ORDER BY (t.status='open') DESC,
                             (COALESCE(u.vip_until,'') > ? OR EXISTS (SELECT 1 FROM vip v WHERE v.user_id=t.user_id AND v.expire_date >= date('now'))) DESC,
                             t.updated_at DESC LIMIT ?""", (iso(), limit))
    return [{"user_id": r["user_id"], "name": display_name(r), "status": r["status"], "unread": r["unread"], "avatar": avatars.url_for(r["user_id"]),
             "is_vip": legacy_vip(r["user_id"]),
             "last_text": ("📷 مدیا" if r["last_media"] else (r["last_text"] or "")), "last_at": r["updated_at"], "last_from": r["last_from"]} for r in rs]


def open_count() -> int:
    return int(db.scalar("SELECT COUNT(*) FROM support_tickets WHERE status='open'", (), 0))
