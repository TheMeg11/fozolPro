"""کاربران، XP، سطح‌بندی و لیدربورد — هم‌سمان فرمول سطح ربات legacy.

فرمول ربات (main.py): XP لازم برای رسیدن به سطح L = 100×L×(L+1)/2 (سطح ۱ از صفر،
سطح ۲ از ۳۰۰، سطح ۳ از ۶۰۰ و…) با سقف config.MAX_LEVEL=100. ستون `level_cached`
نیز هم‌زمان به‌روز می‌شود تا UI ربات دچار تأخیر نشود.
"""
from __future__ import annotations

import math
from datetime import datetime

from services import avatars, bot_settings, db, legacy_bridge, vip
from services.common import AppError, display_name, iso, now, parse

try:  # سقف سطح از config ربات
    import config as _legacy_cfg
    MAX_LEVEL = int(getattr(_legacy_cfg, "MAX_LEVEL", 100))
except Exception:  # pragma: no cover
    MAX_LEVEL = 100


def xp_for_level(level: int) -> int:
    """XP تجمعی لازم برای رسیدن به سطح level — دقیقاً مثل ربات."""
    return 100 * level * (level + 1) // 2


def level_from_xp(xp: int) -> int:
    if xp < 100:
        return 1
    lvl = int((-1 + math.sqrt(1 + 8 * xp / 100)) / 2)
    if lvl < 1:
        lvl = 1
    if lvl > MAX_LEVEL:
        lvl = MAX_LEVEL
    return lvl


def level_info(xp: int) -> dict:
    xp = max(0, int(xp or 0))
    lvl = level_from_xp(xp)
    cur = 0 if lvl == 1 else xp_for_level(lvl)
    nxt = xp_for_level(lvl + 1) if lvl < MAX_LEVEL else xp_for_level(lvl) + 1
    progress = round((xp - cur) / (nxt - cur), 4) if nxt > cur else 1.0
    return {"xp": xp, "level": lvl, "level_xp": xp - cur, "next_level_xp": nxt - cur, "progress": progress}


def week_key(dt: datetime | None = None) -> str:
    y, w, _ = (dt or now()).isocalendar()
    return f"{y}-W{w:02d}"


def ensure_user(u: dict) -> dict:
    """ثبت/به‌روزرسانی کاربر از دادهٔ امضاشدهٔ بله یا آپدیت ربات.

    v4.0.1: اگر نام‌ها تغییری نکرده و last_seen تازه باشد، نوشتن انجام نمی‌شود —
    چون این تابع روی «هر» درخواست مینی‌اپ صدا زده می‌شود، حذف نوشتن‌های تکراری
    رقابت قفل SQLite (database is locked) را عملاً از بین می‌برد.
    """
    uid = int(u["id"])
    fn, ln, un = u.get("first_name"), u.get("last_name"), u.get("username")
    row = db.row("SELECT user_id, first_name, last_name, username, last_seen FROM users WHERE user_id=?", (uid,))
    ts = iso()
    if row:
        same = ((row.get("first_name") or None) == (fn or None)
                and (row.get("last_name") or None) == (ln or None)
                and (row.get("username") or None) == (un or None))
        ls = parse(row.get("last_seen")) if row.get("last_seen") else None
        if same and ls and (now() - ls).total_seconds() < 120:
            return get(uid)  # بدون نوشتن — رکورد تازه است
    with db.tx() as c:
        c.execute(
            """INSERT INTO users(user_id, first_name, last_name, username, joined_at, last_seen, xp, week_xp, is_banned)
               VALUES(?,?,?,?,?,?,COALESCE((SELECT xp FROM users WHERE user_id=?),0),0,0)
               ON CONFLICT(user_id) DO UPDATE SET first_name=excluded.first_name, last_name=excluded.last_name,
               username=excluded.username, last_seen=excluded.last_seen,
               joined_at=COALESCE(users.joined_at, excluded.joined_at)""",
            (uid, fn, ln, un, ts, ts, uid),
        )
    return get(uid)


def get(user_id: int) -> dict:
    r = db.row("SELECT * FROM users WHERE user_id=?", (user_id,))
    if not r:
        raise AppError("NOT_FOUND", "کاربر پیدا نشد.", 404)
    return r


def is_banned(user_id: int) -> bool:
    """مسدود از هر دو مسیر: مینی‌اپ (is_banned) یا ربات (blocked_by_admin/blocked)."""
    r = db.row("SELECT is_banned, blocked_by_admin FROM users WHERE user_id=?", (user_id,))
    if not r:
        return False
    return bool(r.get("is_banned") or r.get("blocked_by_admin"))


def set_banned(user_id: int, banned: bool) -> None:
    get(user_id)
    flag = 1 if banned else 0
    db.execute("UPDATE users SET is_banned=?, blocked_by_admin=? WHERE user_id=?", (flag, flag, user_id))


def add_xp(user_id: int, amount: int, vip_double: bool = True) -> dict:
    """افزودن XP + به‌روزرسانی level_cached.

    vip_double=False → همان رفتار award_bonus_xp ربات (بدون دوبرابر شدن VIP)؛
    برای پاداش‌های ماموریت/جایزه روزانه که خودشان عدد نهایی را حساب می‌کنند."""
    if vip_double and legacy_bridge.is_vip(user_id):
        amount *= 2  # XP دوبرابر VIP
    wk = week_key()
    with db.tx() as c:
        row = c.execute("SELECT xp, week_key, week_xp FROM users WHERE user_id=?", (user_id,)).fetchone()
        xp_old = row[0] if row and row[0] is not None else 0
        xp_new = xp_old + amount
        if row and row[1] == wk:
            week_new = (row[2] or 0) + amount
        else:
            week_new = amount
        lvl = level_from_xp(xp_new)
        c.execute(
            """UPDATE users SET xp=?, week_xp=?, week_key=?, level_cached=? WHERE user_id=?""",
            (xp_new, week_new, wk, lvl, user_id),
        )
    return level_info(xp_new)


def rank(user_id: int) -> int:
    xp = db.scalar("SELECT COALESCE(xp,0) FROM users WHERE user_id=?", (user_id,), 0)
    return int(db.scalar(
        "SELECT COUNT(*) FROM users WHERE COALESCE(xp,0) > ? AND COALESCE(is_banned,0)=0 AND COALESCE(blocked_by_admin,0)=0",
        (xp,), 0)) + 1


def _row_is_vip(r: dict) -> bool:
    """VIP سطر لیدربورد: ستون مینی‌اپ یا جدول vip ربات.
    v4.2: رفع باگ «برترین‌ها نمایش داده نمی‌شود» — until_active قبلاً بدون import بود و
    هر فراخوانی لیدربورد NameError/500 می‌داد."""
    if vip.until_active(r.get("vip_until")):
        return True
    bd = r.get("bot_vip_date")
    return bool(bd and str(bd) >= legacy_bridge.today_tehran().isoformat())


def set_hidden(period: str, me_id: int, hidden: bool) -> None:
    """v4.4: مخفی/نمایش نام من در برترین‌ها — جداگانه برای هفتگی و کل دوران."""
    col = "hide_leaderboard_week" if period == "week" else "hide_leaderboard"
    if col not in ("hide_leaderboard_week", "hide_leaderboard"):
        raise AppError("VALIDATION_ERROR", "بازهٔ نامعتبر است.", 422)
    db.execute(f"UPDATE users SET {col}=? WHERE user_id=?", (1 if hidden else 0, me_id))


def is_hidden(period: str, me_id: int) -> bool:
    col = "hide_leaderboard_week" if period == "week" else "hide_leaderboard"
    return bool(db.scalar(f"SELECT COALESCE({col},0) FROM users WHERE user_id=?", (me_id,), 0))


def leaderboard(period: str, me_id: int) -> dict:
    """جدول برترین‌ها — بازطراحی v4.1.

    حریم خصوصی: یوزرنیم/شناسهٔ عددی کاربران هرگز برنمی‌گردد (فقط نام، عکس، سطح، امتیاز، VIP).
    v4.4: هر کاربر می‌تواند نامش را جداگانه برای «هفتگی» و «کل دوران» مخفی کند
    (hide_leaderboard_week / hide_leaderboard) — ردیفش از هر دو جدول حذف می‌شود.
    """
    limit = bot_settings.leaderboard_size()
    wk = week_key()
    _JOIN = "LEFT JOIN vip v ON v.user_id=u.user_id"
    _BOT_VIP = "v.expire_date AS bot_vip_date"
    _HIDE = "COALESCE(u.hide_leaderboard,0)=0" if period != "week" else "COALESCE(u.hide_leaderboard_week,0)=0"
    _HIDE_N = _HIDE.replace("u.", "")  # برای کوئری‌های بدون alias
    if period == "week":
        rs = db.rows(f"""SELECT u.user_id, u.first_name, u.last_name, u.xp, u.week_xp AS score,
                        u.vip_until, u.display_name, {_BOT_VIP} FROM users u {_JOIN}
                        WHERE u.week_key=? AND {_HIDE} AND COALESCE(u.is_banned,0)=0 AND COALESCE(u.blocked_by_admin,0)=0 AND u.week_xp>0
                        ORDER BY u.week_xp DESC LIMIT ?""", (wk, limit))
        my_score = db.scalar("SELECT CASE WHEN week_key=? THEN week_xp ELSE 0 END FROM users WHERE user_id=?", (wk, me_id), 0)
        my_rank = int(db.scalar(f"""SELECT COUNT(*) FROM users u {_JOIN} WHERE u.week_key=? AND u.week_xp>?
                                    AND {_HIDE} AND COALESCE(u.is_banned,0)=0 AND COALESCE(u.blocked_by_admin,0)=0""",
                                (wk, my_score), 0)) + 1
        participants = db.scalar("SELECT COUNT(*) FROM users WHERE week_key=? AND week_xp>0 "
                                 f"AND {_HIDE_N} AND COALESCE(is_banned,0)=0 AND COALESCE(blocked_by_admin,0)=0", (wk,), 0)
        next_score = db.scalar(f"SELECT MIN(week_xp) FROM users WHERE week_key=? AND week_xp>? "
                               f"AND {_HIDE_N} AND COALESCE(is_banned,0)=0 AND COALESCE(blocked_by_admin,0)=0", (wk, my_score), None)
    else:
        rs = db.rows(f"""SELECT u.user_id, u.first_name, u.last_name, u.xp, u.xp AS score,
                        u.vip_until, u.display_name, {_BOT_VIP} FROM users u {_JOIN}
                        WHERE {_HIDE} AND COALESCE(u.is_banned,0)=0 AND COALESCE(u.blocked_by_admin,0)=0 AND COALESCE(u.xp,0)>0
                        ORDER BY u.xp DESC LIMIT ?""", (limit,))
        my_score = db.scalar("SELECT COALESCE(xp,0) FROM users WHERE user_id=?", (me_id,), 0)
        my_rank = int(db.scalar(f"""SELECT COUNT(*) FROM users u {_JOIN} WHERE u.xp>?
                                    AND {_HIDE} AND COALESCE(u.is_banned,0)=0 AND COALESCE(u.blocked_by_admin,0)=0""",
                                (my_score,), 0)) + 1
        participants = db.scalar(f"SELECT COUNT(*) FROM users WHERE COALESCE(xp,0)>0 "
                                 f"AND {_HIDE_N} AND COALESCE(is_banned,0)=0 AND COALESCE(blocked_by_admin,0)=0", (), 0)
        next_score = db.scalar(f"SELECT MIN(xp) FROM users WHERE COALESCE(xp,0)>? "
                               f"AND {_HIDE_N} AND COALESCE(is_banned,0)=0 AND COALESCE(blocked_by_admin,0)=0", (my_score,), None)
    items = [{
        "rank": i + 1,
        # v4.4: نام نمایشی دلخواه کاربر در اولویت (هم‌سو با لیدربورد ربات)
        "name": (r.get("display_name") or "").strip() or display_name(r),
        "level": level_info(r["xp"] or 0)["level"],
        "xp": int(r["score"] or 0), "is_vip": _row_is_vip(r), "is_me": r["user_id"] == me_id,
        "avatar": avatars.url_for(r["user_id"]),
    } for i, r in enumerate(rs)]
    me_u = db.row("SELECT first_name, last_name, xp FROM users WHERE user_id=?", (me_id,)) or {}
    gap = int(next_score - my_score) if next_score is not None else None
    return {
        "period": period, "items": items, "size": limit,
        "participants": int(participants or 0),
        "me": {"rank": my_rank, "xp": int(my_score or 0), "name": display_name(me_u),
               "level": level_info(me_u.get("xp") or 0)["level"], "avatar": avatars.url_for(me_id),
               "gap": gap if (gap is not None and gap > 0) else None,
               "hidden": is_hidden(period, me_id),
               "is_vip": _row_is_vip({"vip_until": db.scalar("SELECT vip_until FROM users WHERE user_id=?", (me_id,), None),
                                      "bot_vip_date": legacy_bridge.bot_vip_date(me_id).isoformat() if legacy_bridge.bot_vip_date(me_id) else None})},
    }


def public_profile(u: dict) -> dict:
    return {"id": u["user_id"], "first_name": u.get("first_name") or "", "last_name": u.get("last_name") or "",
            "username": u.get("username"), "joined_at": u.get("joined_at") or u.get("created_at"),
            "avatar": avatars.url_for(u["user_id"])}


def last_seen_dt(u: dict) -> datetime | None:
    return parse(u.get("last_seen"))
