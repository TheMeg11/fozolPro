"""پنل سوپر ادمین: آمار، کاربران، پخش همگانی، بکاپ. مجوز در لایهٔ API/ربات با settings.is_admin چک می‌شود."""
from __future__ import annotations

import logging
import os
import secrets
import sqlite3
import tempfile
import threading
import time
from datetime import timedelta

import settings
from services import avatars, bale_api, bot_settings, db, legacy_bridge, snoop, support, users, vip
from services.common import AppError, TEHRAN, display_name, iso, jalali, now, tehran_day_start

log = logging.getLogger("admin")
_bc_lock = threading.Lock()


def stats() -> dict:
    """آمار پنل ادمین — از جداول واقعی ربات (users/clicks/vip) + پرداخت‌های مینی‌اپ."""
    ts = iso()
    day_fmt = "%Y-%m-%d %H:%M:%S"  # ستون‌های TIMESTAMP ربات UTC هستند
    today_s = tehran_day_start(0).strftime(day_fmt)
    week_s = tehran_day_start(6).strftime(day_fmt)
    today_local = now().astimezone(TEHRAN).date().isoformat()
    tday_iso = legacy_bridge.today_tehran().isoformat()
    month = iso(now() - timedelta(days=30))
    chart = []
    for d in range(13, -1, -1):
        s, e = tehran_day_start(d), tehran_day_start(d) + timedelta(days=1)
        s_local = now().astimezone(TEHRAN) - timedelta(days=d)
        chart.append({"date": iso(s), "new_users": db.scalar("SELECT COUNT(*) FROM users WHERE created_at>=? AND created_at<?", (s.strftime(day_fmt), e.strftime(day_fmt)), 0),
                      "snoops": db.scalar("SELECT COUNT(*) FROM clicks WHERE clicked_at>=? AND clicked_at<?", (s.strftime(day_fmt), e.strftime(day_fmt)), 0),
                      "anon": db.scalar("SELECT COUNT(*) FROM anon_logs WHERE timestamp>=? AND timestamp<?", (s.strftime(day_fmt), e.strftime(day_fmt)), 0),
                      "day_local": s_local.date().isoformat()})
    return {
        "users_total": db.scalar("SELECT COUNT(*) FROM users"),
        "users_today": db.scalar("SELECT COUNT(*) FROM users WHERE created_at>=?", (today_s,)),
        "users_active_today": db.scalar(
            "SELECT COUNT(*) FROM users WHERE (last_active_date=?) OR (last_seen IS NOT NULL AND last_seen>=?)",
            (today_local, iso(tehran_day_start(0)))),
        "users_week": db.scalar("SELECT COUNT(*) FROM users WHERE created_at>=?", (week_s,)),
        "vip_active": db.scalar(
            "SELECT COUNT(*) FROM users u LEFT JOIN vip v ON v.user_id=u.user_id "
            "WHERE (u.vip_until IS NOT NULL AND u.vip_until>?) OR (v.expire_date IS NOT NULL AND v.expire_date>=?)",
            (ts, legacy_bridge.today_tehran().isoformat())),
        "revenue_month": db.scalar("SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='paid' AND paid_at>=?", (month,)),
        "snoops_today": db.scalar("SELECT COUNT(*) FROM clicks WHERE clicked_at>=?", (today_s,)),
        "anon_today": db.scalar("SELECT COUNT(*) FROM anon_logs WHERE date(timestamp)=date('now')", (), 0),
        "open_tickets": support.open_count(),
        "banned": db.scalar("SELECT COUNT(*) FROM users WHERE COALESCE(is_banned,0)=1 OR COALESCE(blocked_by_admin,0)=1"),
        "chart": chart,
        # ---- v4.3: آمار تفصیلی (هم‌ارز «آمار کاربران / آمار VIP» پنل شیشه‌ای) ----
        "users_month": db.scalar("SELECT COUNT(*) FROM users WHERE created_at>=?", (iso(now() - timedelta(days=30)),)),
        "users_week_active": db.scalar("SELECT COUNT(*) FROM users WHERE last_seen IS NOT NULL AND last_seen>=?", (week_s,)),
        "vip_expiring_7d": db.scalar(
            "SELECT COUNT(*) FROM users u LEFT JOIN vip v ON v.user_id=u.user_id WHERE "
            "(u.vip_until IS NOT NULL AND u.vip_until>? AND u.vip_until<=?) OR (v.expire_date IS NOT NULL AND v.expire_date>=? AND v.expire_date<=?)",
            (ts, iso(now() + timedelta(days=7)), tday_iso, (now().astimezone(TEHRAN).date() + timedelta(days=7)).isoformat())),
        "vip_revenue_total": db.scalar("SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='paid'"),
        "vip_ever": db.scalar("SELECT COUNT(DISTINCT user_id) FROM transactions WHERE type IN ('vip','purchase')"),
        "traps_total": db.scalar("SELECT COUNT(*) FROM traps"),
        "anon_total": db.scalar("SELECT COUNT(*) FROM anon_logs", (), 0),
        "spins_total": db.scalar("SELECT COUNT(*) FROM wheel_spins", (), 0),
        "challenge_status": challenge_view(),
    }


def search_users(q: str = "", flt: str = "all", sort: str = "recent", limit: int = 50) -> dict:
    where, params = ["1=1"], []
    q = (q or "").strip().lstrip("@")
    if q:
        if q.isdigit():
            where.append("(CAST(users.user_id AS TEXT) LIKE ?)")  # users. — چون JOIN vip هم user_id دارد
            params.append(f"{q}%")
        else:
            where.append("(first_name LIKE ? OR last_name LIKE ? OR username LIKE ? OR (first_name || ' ' || COALESCE(last_name,'')) LIKE ?)")
            params += [f"%{q}%"] * 4
    if flt == "vip":
        where.append("(users.vip_until > ? OR v.expire_date >= ?)")
        params.append(iso())
        params.append(legacy_bridge.today_tehran().isoformat())
    elif flt == "banned":
        where.append("(COALESCE(users.is_banned,0)=1 OR COALESCE(users.blocked_by_admin,0)=1)")
    w = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) FROM users LEFT JOIN vip v ON v.user_id=users.user_id WHERE {w}", params)
    # v4.3: مرتب‌سازی بر اساس معیارهای مختلف (پنل ادمین مینی‌اپ)
    ts = iso()
    tday = legacy_bridge.today_tehran().isoformat()
    vip_expr = f"(CASE WHEN (users.vip_until > '{ts}' OR v.expire_date >= '{tday}') THEN 1 ELSE 0 END)"
    order = {
        "recent": "COALESCE(users.last_seen, users.created_at) DESC",
        "joined": "COALESCE(users.joined_at, users.created_at) DESC",
        "level":  "COALESCE(users.xp, 0) DESC",
        "vip":    f"{vip_expr} DESC, COALESCE(users.vip_until, '') DESC",
        "name":   "(first_name || ' ' || COALESCE(last_name,'')) COLLATE NOCASE ASC",
        "snoops": "(SELECT COUNT(*) FROM clicks c WHERE c.owner_id=users.user_id) DESC, COALESCE(users.last_seen, users.created_at) DESC",
        "traps":  "(SELECT COUNT(*) FROM traps t WHERE t.owner_id=users.user_id) DESC, COALESCE(users.last_seen, users.created_at) DESC",
    }.get(sort, "COALESCE(users.last_seen, users.created_at) DESC")
    rs = db.rows(f"""SELECT users.*, v.expire_date AS bot_vip_date FROM users
                     LEFT JOIN vip v ON v.user_id=users.user_id WHERE {w}
                     ORDER BY {order} LIMIT ?""", params + [limit])
    return {"total": total, "sort": sort, "items": [{"id": r["user_id"], "name": display_name(r), "username": r.get("username"), "is_vip": _row_is_vip(r), "avatar": avatars.url_for(r["user_id"]),
                                       "banned": bool(r.get("is_banned") or r.get("blocked_by_admin")), "level": users.level_info(r.get("xp") or 0)["level"], "xp": r.get("xp") or 0, "joined_at": r.get("joined_at") or r.get("created_at")} for r in rs]}


def _row_is_vip(r: dict) -> bool:
    if vip.until_active(r.get("vip_until")):
        return True
    bd = r.get("bot_vip_date")
    return bool(bd and str(bd) >= legacy_bridge.today_tehran().isoformat())


def user_detail(user_id: int) -> dict:
    u = users.get(user_id)
    return {
        "user": {"id": u["user_id"], "name": display_name(u), "username": u.get("username"), "joined_at": u.get("joined_at"), "last_seen": u.get("last_seen"), "avatar": avatars.url_for(user_id)},
        "banned": bool(u.get("is_banned")), "vip": vip.status(user_id), "xp": users.level_info(u.get("xp") or 0),
        "stats": {"snoops": db.scalar("SELECT COUNT(*) FROM clicks WHERE owner_id=?", (user_id,)),
                  "traps": db.scalar("SELECT COUNT(*) FROM traps WHERE owner_id=?", (user_id,)),
                  "spins": db.scalar("SELECT COUNT(*) FROM wheel_spins WHERE user_id=?", (user_id,))},
        "payments": vip.payments_of(user_id),
    }


def change_vip(user_id: int, action: str, days: int = 0) -> dict:
    users.get(user_id)
    if action == "add":
        st = vip.extend(user_id, days)
        note = f"🎁 {days} روز به اشتراک VIP شما اضافه شد.\nانقضا: {jalali(st['expires_at'])}"
    elif action == "reduce":
        st = vip.reduce(user_id, days)
        note = f"ℹ️ اشتراک VIP شما {days} روز کاهش یافت." + (f"\nانقضا: {jalali(st['expires_at'])}" if st["active"] else "")
    elif action == "cancel":
        vip.cancel(user_id)
        note = "ℹ️ اشتراک VIP شما توسط مدیریت لغو شد."
    else:
        raise AppError("VALIDATION_ERROR", "عملیات نامعتبر است.", 422)
    try:
        bale_api.send_message(user_id, note)
    except AppError:
        pass
    return user_detail(user_id)


def set_ban(admin_id: int, user_id: int, banned: bool) -> dict:
    if user_id == admin_id:
        raise AppError("VALIDATION_ERROR", "نمی‌توانید خودتان را مسدود کنید.", 422)
    users.set_banned(user_id, banned)
    return user_detail(user_id)


def direct_message(user_id: int, text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise AppError("VALIDATION_ERROR", "متن پیام خالی است.", 422)
    users.get(user_id)
    bale_api.send_message(user_id, text)
    return {"sent": True}


# ---------------- پخش همگانی ----------------
def _targets(target: str) -> list[int]:
    ts = iso()
    sql = {"all": "SELECT user_id FROM users WHERE COALESCE(is_banned,0)=0 AND COALESCE(blocked_by_admin,0)=0",
           "vip": ("SELECT u.user_id FROM users u LEFT JOIN vip v ON v.user_id=u.user_id "
                   "WHERE COALESCE(u.is_banned,0)=0 AND COALESCE(u.blocked_by_admin,0)=0 AND "
                   "(u.vip_until>? OR v.expire_date>=?)"),
           "free": ("SELECT u.user_id FROM users u LEFT JOIN vip v ON v.user_id=u.user_id "
                    "WHERE COALESCE(u.is_banned,0)=0 AND COALESCE(u.blocked_by_admin,0)=0 AND "
                    "(u.vip_until IS NULL OR u.vip_until<=?) AND (v.expire_date IS NULL OR v.expire_date<?)")}.get(target)
    if not sql:
        raise AppError("VALIDATION_ERROR", "گروه مخاطبان نامعتبر است.", 422)
    if target == "all":
        return [r["user_id"] for r in db.rows(sql)]
    tday = legacy_bridge.today_tehran().isoformat()
    return [r["user_id"] for r in db.rows(sql, (ts, tday) if target == "vip" else (ts, tday))]


def broadcast_meta() -> dict:
    ts = iso()
    allc = db.scalar("SELECT COUNT(*) FROM users WHERE COALESCE(is_banned,0)=0 AND COALESCE(blocked_by_admin,0)=0")
    vipc = db.scalar(
        "SELECT COUNT(*) FROM users u LEFT JOIN vip v ON v.user_id=u.user_id "
        "WHERE COALESCE(u.is_banned,0)=0 AND COALESCE(u.blocked_by_admin,0)=0 AND "
        "(u.vip_until>? OR v.expire_date>=?)", (ts, legacy_bridge.today_tehran().isoformat()))
    jobs = db.rows("SELECT * FROM broadcast_jobs ORDER BY created_at DESC LIMIT 5")
    return {"counts": {"all": allc, "vip": vipc, "free": allc - vipc}, "jobs": [_job_view(j) for j in jobs]}


def _job_view(j: dict) -> dict:
    return {"id": j["id"], "target": j["target"], "text_preview": j["text"][:80], "status": j["status"], "total": j["total"], "sent": j["sent"], "failed": j["failed"], "created_at": j["created_at"]}


def start_broadcast(text: str, target: str, sender=None) -> dict:
    text = (text or "").strip()
    if len(text) < 3:
        raise AppError("VALIDATION_ERROR", "متن پیام خیلی کوتاه است.", 422)
    with _bc_lock:
        if db.scalar("SELECT COUNT(*) FROM broadcast_jobs WHERE status='running'"):
            raise AppError("BUSY", "یک پخش همگانی در حال اجراست؛ صبر کنید تا تمام شود.", 409)
        ids = _targets(target)
        job_id = f"b-{int(time.time())}-{secrets.token_hex(2)}"
        db.execute("INSERT INTO broadcast_jobs(id, target, text, status, total, created_at) VALUES(?,?,?, 'running', ?, ?)", (job_id, target, text, len(ids), iso()))
    send = sender or (lambda uid: bale_api.send_message(uid, text))
    threading.Thread(target=_run_broadcast, args=(job_id, ids, send), name=f"broadcast-{job_id}", daemon=True).start()
    return {"job_id": job_id, "total": len(ids)}


def _run_broadcast(job_id: str, ids: list[int], send) -> None:
    sent = failed = 0
    for i, uid in enumerate(ids, 1):
        try:
            send(uid)
            sent += 1
        except Exception:
            failed += 1
        if i % 25 == 0 or i == len(ids):
            db.execute("UPDATE broadcast_jobs SET sent=?, failed=? WHERE id=?", (sent, failed, job_id))
        time.sleep(settings.BROADCAST_DELAY_SEC)
    db.execute("UPDATE broadcast_jobs SET status='done', sent=?, failed=?, finished_at=? WHERE id=?", (sent, failed, iso(), job_id))
    log.info("broadcast %s done: sent=%s failed=%s", job_id, sent, failed)


def broadcast_status(job_id: str) -> dict:
    j = db.row("SELECT * FROM broadcast_jobs WHERE id=?", (job_id,))
    if not j:
        raise AppError("NOT_FOUND", "پخش پیدا نشد.", 404)
    return _job_view(j)


def recover_jobs() -> None:
    """پس از ری‌استارت، jobهای نیمه‌کاره را «interrupted» علامت می‌زند."""
    db.execute("UPDATE broadcast_jobs SET status='interrupted', finished_at=? WHERE status='running'", (iso(),))


# ---------------- بکاپ ----------------
def backup_info() -> dict:
    size = os.path.getsize(settings.DB_PATH) if os.path.exists(settings.DB_PATH) else 0
    return {"last_backup_at": db.kv_get("last_backup_at"), "db_size_bytes": size, "schedule": "هر شب ساعت ۰۳:۰۰ (به وقت تهران)",
            "users": db.scalar("SELECT COUNT(*) FROM users"), "path": settings.DB_PATH}


def backup_now(send: bool = True) -> dict:
    """کپی سازگار با WAL از طریق sqlite backup API و ارسال به چت ادمین در بله (همان مسیر بکاپ شبانه)."""
    name = f"backup-{now().strftime('%Y%m%d-%H%M%S')}.db"
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        dst = sqlite3.connect(tmp)
        try:
            db.conn().backup(dst)
        finally:
            dst.close()
        size = os.path.getsize(tmp)
        if send:
            if not settings.ADMIN_ID:
                raise AppError("ADMIN_NOT_CONFIGURED", "ADMIN_ID تنظیم نشده است.", 503)
            bale_api.send_document(settings.ADMIN_ID, tmp, name, caption=f"🗄 بکاپ دیتابیس — {jalali(iso(), True)}")
        db.kv_set("last_backup_at", iso())
        return {"sent": send, "filename": name, "size_bytes": size}
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ---------------- هدیه‌ها و تراکنش‌ها (هم‌سکیمای ربات) ----------------
def gifts() -> list[dict]:
    rs = db.rows("SELECT * FROM gift_codes ORDER BY created_at DESC LIMIT 100")
    return [{"code": r["code"], "days": r["days"], "max_uses": r["max_uses"], "used_count": r["used_count"],
             "created_at": r["created_at"], "status": "done" if r["used_count"] >= r["max_uses"] else "open"} for r in rs]


def create_gift(days: int, max_uses: int, code: str | None = None) -> dict:
    if not 1 <= days <= 3650:
        raise AppError("VALIDATION_ERROR", "تعداد روز باید بین ۱ و ۳۶۵۰ باشد.", 422)
    if not 1 <= max_uses <= 10000:
        raise AppError("VALIDATION_ERROR", "سقف استفاده باید بین ۱ و ۱۰۰۰۰ باشد.", 422)
    import secrets as _secrets
    import string as _string
    code = (code or "").strip().upper() or ("GIFT" + "".join(_secrets.choice(_string.digits) for _ in range(6)))
    if not 4 <= len(code) <= 24 or not all(c in _string.ascii_letters + _string.digits + "-_" for c in code):
        raise AppError("VALIDATION_ERROR", "کد هدیه فقط حروف/رقم انگلیسی (۴ تا ۲۴ کاراکتر) باشد.", 422)
    if db.row("SELECT 1 FROM gift_codes WHERE code=?", (code,)):
        raise AppError("VALIDATION_ERROR", "این کد قبلاً ساخته شده است.", 422)
    db.execute("INSERT INTO gift_codes (code, days, max_uses) VALUES(?,?,?)", (code, days, max_uses))
    return {"code": code, "days": days, "max_uses": max_uses}


def transactions(page: int = 1, per: int = 30) -> dict:
    page = max(1, page)
    total = db.scalar("SELECT COUNT(*) FROM transactions", (), 0)
    rs = db.rows("""SELECT t.*, u.first_name, u.last_name, u.username FROM transactions t
                    LEFT JOIN users u ON u.user_id=t.user_id
                    ORDER BY t.id DESC LIMIT ? OFFSET ?""", (per, (page - 1) * per))
    TYPE_FA = {"purchase": "خرید VIP", "gift": "کد هدیه", "admin_vip_add": "افزودن توسط ادمین",
               "admin_vip_remove": "کاهش توسط ادمین", "wheel": "گردونه شانس", "trial": "هدیهٔ ورود"}
    items = [{"id": r["id"], "user": {"id": r["user_id"], "name": display_name(r) if (r.get("first_name") or r.get("last_name") or r.get("username")) else str(r["user_id"]),
                                        "username": r.get("username"), "avatar": avatars.url_for(r["user_id"])},
              "type": r["type"], "type_fa": TYPE_FA.get(r["type"], r["type"]), "amount": r["amount"],
              "days": r.get("days") or 0, "created_at": r["timestamp"]} for r in rs]
    return {"items": items, "total": total, "page": page, "pages": max(1, -(-total // per))}


def snoop_overview(user_id: int) -> dict:  # برای ری‌یوز در پیام‌های ادمین ربات
    return snoop.quick_stats(user_id)


# ---------------- v4.3: چالش فضول‌گیر برتر (هم‌کلید با منوی شیشه‌ای ربات) ----------------
# وضعیت/شمارش از همان کلیدهای settings ربات (challenge_status/challenge_start_utc/...)
# خوانده می‌شود؛ حلقهٔ challenge_loop ربات هر ۶۰ ثانیه پالس می‌زند و «شروع شمارش»،
# «پایان + تسویهٔ جوایز» را خودش انجام می‌دهد. مینی‌اپ فقط وضعیت را می‌سازد/می‌خواند.
_CHAL_FMT = "%Y-%m-%d %H:%M:%S"  # UTC naive — دقیقاً مثل ربات


def _chal_get(key: str, default: str = "") -> str:
    v = bot_settings.get(key)
    return v if v is not None else default


def _chal_get_int(key: str, default: int) -> int:
    return bot_settings.get_int(key, default)


def _chal_window() -> tuple[str, str] | None:
    s, e = _chal_get("challenge_start_utc"), _chal_get("challenge_end_utc")
    if not s or not e:
        return None
    try:
        from datetime import datetime as _dt
        _dt.strptime(s, _CHAL_FMT), _dt.strptime(e, _CHAL_FMT)
        return s, e
    except ValueError:
        return None


def challenge_view() -> dict:
    status = _chal_get("challenge_status")
    win = _chal_window()
    from datetime import datetime as _dt, timezone as _tz
    out = {"status": status or "idle", "hours": _chal_get_int("challenge_hours", 24),
           "reward_days": _chal_get_int("challenge_reward_days", 3), "top": [],
           # v4.6: نوع جایزه (vip | envelope) + مبلغ پاکت + متن اعلان شروع ذخیره‌شده
           "reward_type": (_chal_get("challenge_reward_type", "") or "vip").strip(),
           "reward_amount": _chal_get_int("challenge_reward_amount", 0),
           "announce_text": _chal_get("challenge_announce_text", "")}
    if win:
        out["start_utc"], out["end_utc"] = win
        try:
            st = _dt.strptime(win[0], _CHAL_FMT).replace(tzinfo=_tz.utc)
            en = _dt.strptime(win[1], _CHAL_FMT).replace(tzinfo=_tz.utc)
            out["start_at"], out["end_at"] = st.isoformat(), en.isoformat()
            if status == "scheduled":
                out["remaining_sec"] = max(0, int((st - now()).total_seconds()))
            elif status == "active":
                out["remaining_sec"] = max(0, int((en - now()).total_seconds()))
        except ValueError:
            pass
    if status in ("scheduled", "active") and win:
        out["top"] = _challenge_standings(win[0], win[1], 10)
    return out


def _challenge_standings(start_utc: str, end_utc: str, limit: int = 10) -> list[dict]:
    """همان منطق ربات: فقط فضول‌های جدید (is_new_user=1)، هر کاربر جدید یک‌بار برای اولین صاحب تله."""
    rs = db.rows(
        "SELECT c.owner_id, u.first_name, u.last_name, u.username, "
        "COUNT(DISTINCT c.clicker_id) AS snoops, MIN(c.clicked_at) AS first_at "
        "FROM clicks c JOIN users u ON c.owner_id=u.user_id "
        "WHERE c.is_new_user=1 AND c.clicked_at>=? AND c.clicked_at<? "
        "AND (COALESCE(u.is_banned,0)=0) "
        "GROUP BY c.owner_id ORDER BY snoops DESC, first_at ASC LIMIT ?",
        (start_utc, end_utc, limit))
    return [{"id": r["owner_id"], "name": display_name(r), "username": r.get("username"),
             "avatar": avatars.url_for(r["owner_id"]), "snoops": r["snoops"]} for r in rs]


def challenge_start(hours: int, reward_days: int, reward_type: str = "vip",
                    reward_amount: int = 0, announce_text: str = "") -> dict:
    """ساخت وضعیت «scheduled» با کلیدهای ربات — شمارش از ۰۰:۰۰ فردا به وقت تهران.
    v4.6: جایزه یا «vip» (روز) است یا «envelope» (پاکت — توزیع دستی ادمین پس از پایان)؛
    متن اعلان شروع هم قابل ویرایش است (خالی = متن پیش‌فرض ربات). اعلان بلافاصله توسط
    حلقهٔ چالش ربات (حداکثر ۶۰ ثانیه بعد) برای همهٔ کاربران پخش می‌شود."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    if not (1 <= int(hours) <= 168):
        raise AppError("VALIDATION_ERROR", "مدت چالش باید بین ۱ تا ۱۶۸ ساعت باشد.", 422)
    rtype = "envelope" if str(reward_type or "").strip().lower() == "envelope" else "vip"
    amount = 0
    if rtype == "vip":
        if not (1 <= int(reward_days) <= 365):
            raise AppError("VALIDATION_ERROR", "جایزهٔ رتبهٔ اول باید بین ۱ تا ۳۶۵ روز باشد.", 422)
    else:
        amount = int(reward_amount or 0)
        if not (0 <= amount <= 2_000_000_000):
            raise AppError("VALIDATION_ERROR", "مبلغ پاکت نامعتبر است.", 422)
    announce = str(announce_text or "").strip()
    if len(announce) > 3000:
        raise AppError("VALIDATION_ERROR", "متن اعلان حداکثر ۳۰۰۰ کاراکتر است.", 422)
    status = _chal_get("challenge_status")
    if status in ("scheduled", "active"):
        raise AppError("BUSY", "یک چالش در جریان است؛ اول آن را لغو کنید.", 409)
    tehran_now = now().astimezone(TEHRAN)
    start_teh = tehran_now.replace(hour=0, minute=0, second=0, microsecond=0) + _td(days=1)
    end_teh = start_teh + _td(hours=int(hours))
    start_utc = start_teh.astimezone(_tz.utc).replace(tzinfo=None)
    end_utc = end_teh.astimezone(_tz.utc).replace(tzinfo=None)
    bot_settings.set_value("challenge_start_utc", start_utc.strftime(_CHAL_FMT))
    bot_settings.set_value("challenge_end_utc", end_utc.strftime(_CHAL_FMT))
    bot_settings.set_value("challenge_hours", int(hours))
    bot_settings.set_value("challenge_reward_days", int(reward_days) if rtype == "vip" else 0)
    bot_settings.set_value("challenge_reward_type", rtype)
    bot_settings.set_value("challenge_reward_amount", amount)
    bot_settings.set_value("challenge_announce_text", announce)
    bot_settings.set_value("challenge_date", start_teh.date().isoformat())
    bot_settings.set_value("challenge_status", "scheduled")
    bot_settings.set_value("challenge_announce_pending", "1")  # ربات در اولین پالس اعلان شروع را پخش می‌کند
    log.info("challenge scheduled from miniapp admin: %s .. %s (%sh, reward %s)", start_utc, end_utc, hours,
             ("%sd" % reward_days) if rtype == "vip" else ("envelope %s" % amount))
    return challenge_view()


def challenge_cancel() -> dict:
    bot_settings.set_value("challenge_status", "cancelled")
    bot_settings.set_value("challenge_announce_pending", "0")  # اعلان چالشِ لغوشده پخش نشود
    log.info("challenge cancelled from miniapp admin")
    return challenge_view()


# ---------------- v4.3: کانال‌های اجباری (جدول forced_channels ربات) ----------------
def forced_channels() -> dict:
    try:
        rows = db.rows("SELECT channel_id, channel_name, invite_link, target, added_at FROM forced_channels ORDER BY added_at")
    except Exception:
        rows = []
    items = []
    for r in rows:
        cid = str(r.get("channel_id") or "")
        try:
            joins = db.scalar("SELECT COUNT(*) FROM channel_joins WHERE channel_username=?", (cid,), 0)
        except Exception:
            joins = 0  # جدول شمارش عضویت ربات ممکن است هنوز ساخته نشده باشد
        tgt = int(r.get("target") or 0)
        items.append({"id": cid, "title": r.get("channel_name") or cid,
                      "url": (r.get("invite_link") or "").strip(), "target": tgt,
                      "joins": joins, "added_at": r.get("added_at"),
                      "percent": (min(100, round(joins * 100 / tgt)) if tgt > 0 else None)})
    enabled = True
    try:
        import config as _legacy
        enabled = bool(getattr(_legacy, "FORCE_JOIN_ENABLED", True))
    except Exception:
        pass
    return {"enabled": enabled, "items": items}


def add_forced_channel(channel_id: str, title: str, target: int = 0) -> dict:
    channel_id = (channel_id or "").strip()
    title = (title or "").strip()
    if not channel_id:
        raise AppError("VALIDATION_ERROR", "شناسهٔ کانال را وارد کنید (@username یا شناسهٔ عددی).", 422)
    if channel_id.startswith("@"):
        channel_id = channel_id.lstrip("@")
    if len(channel_id) < 3:
        raise AppError("VALIDATION_ERROR", "شناسهٔ کانال معتبر نیست.", 422)
    target = max(0, int(target or 0))
    if db.row("SELECT 1 FROM forced_channels WHERE channel_id=?", (channel_id,)):
        raise AppError("VALIDATION_ERROR", "این کانال قبلاً اضافه شده است.", 422)
    db.execute("INSERT INTO forced_channels (channel_id, channel_name, invite_link, target, added_at) VALUES(?,?,?,?,?)",
               (channel_id, title or channel_id, "", target, iso()))
    log.info("forced channel added from miniapp: %s (target=%s)", channel_id, target)
    return forced_channels()


def remove_forced_channel(channel_id: str) -> dict:
    db.execute("DELETE FROM forced_channels WHERE channel_id=?", ((channel_id or "").strip(),))
    log.info("forced channel removed from miniapp: %s", channel_id)
    return forced_channels()


# ---------------- v4.3: حالت تبلیغ (پیام همگانی با دکمه‌های لینک تبلیغ) ----------------
_AD_TEMPLATE = ("🔔 <b>یه فضول روی لینک شما کلیک کرد!</b>\n"
                "🕒 {t}\n"
                "👤 🕵️ فضول ناشناس\n"
                "🆔 مخفی 🔒\n"
                "📎 مخفی 🔒\n\n"
                "🔍 دوست داری بدونی کی بود؟ هویت فضول‌ها فقط با VIP لو می‌ره! 👑")


def ad_broadcast(url: str, stage: str) -> dict:
    url = (url or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise AppError("VALIDATION_ERROR", "لینک باید با http:// یا https:// شروع شود.", 422)
    if len(url) > 512:
        raise AppError("VALIDATION_ERROR", "لینک خیلی طولانی است.", 422)
    text = _AD_TEMPLATE.format(t=now().astimezone(TEHRAN).strftime("%Y/%m/%d - %H:%M"))
    buttons = [[{"text": "🏷️ لقب دادن", "url": url}, {"text": "✉️ پیام ناشناس", "url": url}],
               [{"text": "📊 اطلاعات فضول", "url": url}, {"text": "🎁 هدیه به فضول", "url": url}],
               [{"text": "📋 لیست فضول‌ها", "url": url}, {"text": "🏠 خانه", "url": url}]]
    markup = {"inline_keyboard": buttons}
    if stage == "preview":
        if not settings.ADMIN_ID:
            raise AppError("ADMIN_NOT_CONFIGURED", "ADMIN_ID تنظیم نشده است.", 503)
        bale_api.send_message(settings.ADMIN_ID, text + "\n\n<i>👁 نمونهٔ پیام تبلیغ — این متن با دکمه‌های بالا به همه ارسال می‌شود.</i>",
                              reply_markup=markup)
        return {"preview": True, "targets": _ad_targets_count()}
    if stage == "send":
        with _bc_lock:
            if db.scalar("SELECT COUNT(*) FROM broadcast_jobs WHERE status='running'"):
                raise AppError("BUSY", "یک پخش همگانی در حال اجراست؛ صبر کنید تا تمام شود.", 409)
            ids = _targets("all")
            job_id = f"ad-{int(time.time())}-{secrets.token_hex(2)}"
            db.execute("INSERT INTO broadcast_jobs(id, target, text, status, total, created_at) VALUES(?,?,?, 'running', ?, ?)",
                       (job_id, "ad", text, len(ids), iso()))
        send = lambda uid: bale_api.send_message(uid, text, reply_markup=markup)  # noqa: E731
        threading.Thread(target=_run_broadcast, args=(job_id, ids, send), name=f"adbc-{job_id}", daemon=True).start()
        return {"job_id": job_id, "total": len(ids)}
    raise AppError("VALIDATION_ERROR", "مرحلهٔ نامعتبر است.", 422)


def _ad_targets_count() -> int:
    return db.scalar("SELECT COUNT(*) FROM users WHERE COALESCE(is_banned,0)=0 AND COALESCE(blocked_by_admin,0)=0")
