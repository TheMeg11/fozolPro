"""v5.4 — داشبورد یکپارچهٔ ادمین (ربات + مینی‌اپ) با چیدمان «روند و مقایسه».

هر شاخص روزانه سه عدد دارد: امروز (تا این لحظه)، دیروز (کامل) و میانگین ۷ روز کامل قبل؛
درصد تغییر نسبت به «دیروز تا همین ساعت» است — مقایسهٔ امروزِ نیمه‌کاره با کل دیروز گمراه‌کننده بود.

اصلاحات داده نسبت به داشبورد قبلی (v5.3):
  • همهٔ «امروز»ها به تقویم تهران — قبلاً کلیک/درآمد/تلهٔ برتر با تاریخ UTC شمرده می‌شد
    (ستون‌های CURRENT_TIMESTAMP به UTC هستند ولی date.today() کانتینر تهران است).
  • درآمد = تراکنش‌های ربات (vip/gift_vip/reveal/saveface — ریال) + پرداخت‌های مینی‌اپ
    (جدول payments — تومان). قبلاً مینی‌اپ و «حفظ آبرو» کلاً حساب نمی‌شد.
  • «فعال» و «درخواست» ماندگار (services.metrics) — دیگر با ری‌استارت صفر نمی‌شود.
  • «پیام ناشناس» با برچسب درست «۳۰ روز اخیر» (لاگ‌های قدیمی‌تر پاک می‌شوند).
  • «میانگین ۷ روز» دقیقاً ۷ روز کامل (قبلاً ۷ روز + امروزِ نیمه‌کاره تقسیم بر ۷).
  • منبع ورود با ردیف «مینی‌اپ/نامشخص» — جمع‌شان حالا برابر کل کاربران است.

ستون‌های زمانی: users.created_at به وقت محلی کانتینر (TZ=Asia/Tehran) نوشته می‌شود؛
clicks/transactions/anon_logs/gift_usage/channel_joins/wheel_spins به UTC (برخی با قالب iso).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

import settings
from services import db, metrics, server_stats
from services.common import TEHRAN, display_name

log = logging.getLogger("dashboard")

_cache: dict = {"at": 0.0, "data": None}
_cache_lock = threading.Lock()
_runtime_fn = None

REVENUE_TX_TYPES = ("vip", "gift_vip", "reveal", "saveface")
_UTC_FMT = "%Y-%m-%d %H:%M:%S"


def set_runtime(fn) -> None:
    """main.py (ربات) تابعی ثبت می‌کند که داده‌های زمان‌اجرای ربات را برمی‌گرداند
    (خطاها، کانال‌های مشکل‌دار، پرکلیک‌ترین دکمه، شمارندهٔ ماه شمسی، ...)."""
    global _runtime_fn
    _runtime_fn = fn


def invalidate() -> None:
    with _cache_lock:
        _cache["at"] = 0.0


# ---------------- ابزار زمان ----------------
def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(_UTC_FMT)


def _local(dt: datetime) -> str:
    """قالب ستون users.created_at (ساعت محلی تهران، بدون منطقه)."""
    return dt.astimezone(TEHRAN).strftime(_UTC_FMT)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception as exc:  # یک کوئری خراب نباید کل داشبورد را از کار بیندازد
        log.warning("dashboard query failed: %s", exc)
        return default


# ---------------- محاسبهٔ روند ----------------
def _trend(key: str, icon: str, label: str, per_day: dict, days: list[str], y_same=None,
           first_day: str | None = None, kind: str = "int") -> dict:
    """per_day: {day: value}؛ days[0]=امروز ... days[7]=۷ روز قبل.
    first_day: اولین روزی که این شاخص داده دارد (برای شاخص‌های جدید) — روزهای قبلش در میانگین نمی‌آیند."""
    today = per_day.get(days[0], 0) or 0
    past = [d for d in days[1:8] if not first_day or d >= first_day]
    # روز اولِ داده معمولاً ناقص است (از لحظهٔ دیپلوی) — اگر روزهای کامل دیگری هست، کنار گذاشته می‌شود
    if first_day and first_day in past and len(past) > 1:
        past.remove(first_day)
    yesterday = per_day.get(days[1], 0) if (not first_day or days[1] >= first_day) else None
    if yesterday is None:
        y_same = None  # دادهٔ دیروز وجود ندارد — درصد تغییر بی‌معناست
    avg7 = (sum(per_day.get(d, 0) or 0 for d in past) / len(past)) if past else None
    return {"key": key, "icon": icon, "label": label, "today": today, "yesterday": yesterday,
            "y_same": y_same, "avg7": avg7, "avg_days": len(past), "kind": kind}


def _per_day_sql(sql: str, params: tuple) -> dict:
    return {r["d"]: (r["n"] or 0) for r in db.rows(sql, params) if r.get("d")}


def _compute() -> dict:
    t = datetime.now(TEHRAN)
    d0 = t.replace(hour=0, minute=0, second=0, microsecond=0)
    starts = [d0 - timedelta(days=i) for i in range(9)]
    days = [s.strftime("%Y-%m-%d") for s in starts]
    y_cut = t - timedelta(days=1)  # «دیروز تا همین ساعت»
    s7 = starts[7]
    tx_types = ",".join("?" * len(REVENUE_TX_TYPES))
    ratio = max(1, int(getattr(settings, "TOMAN_TO_RIAL", 10) or 10))
    try:
        metrics.flush()  # آمار لحظه‌ای: صف حافظه قبل از خواندن نوشته شود
    except Exception:
        pass

    trends = []
    # ۱) کاربر جدید — created_at محلی تهران
    nu = _safe(lambda: _per_day_sql(
        "SELECT substr(created_at,1,10) AS d, COUNT(*) AS n FROM users WHERE created_at>=? GROUP BY d",
        (_local(s7),)), {})
    nu_y = _safe(lambda: db.scalar("SELECT COUNT(*) FROM users WHERE created_at>=? AND created_at<?",
                                   (_local(starts[1]), _local(y_cut)), 0), 0)
    trends.append(_trend("new_users", "🆕", "کاربر جدید", nu, days, nu_y))

    # ۲) کاربر فعال (DAU) — ماندگار
    dau_first = _safe(metrics.first_day)
    dau = _safe(lambda: metrics.dau_by_day(days[7], days[0]), {})
    dau_y = _safe(lambda: metrics.dau(days[1], int(y_cut.timestamp())), 0)
    trends.append(_trend("active", "🔥", "کاربر فعال", dau, days, dau_y, dau_first))

    # ۳) درخواست (پیام + دکمهٔ ربات) — شمارندهٔ ساعتی
    req_first = _safe(lambda: metrics.counter_first_day("req"))
    req = _safe(lambda: metrics.counter_by_day("req", days[7], days[0]), {})
    req_y = _safe(lambda: metrics.counter_range("req", days[1] + " 00", y_cut.strftime("%Y-%m-%d %H")), 0)
    trends.append(_trend("requests", "📨", "درخواست به ربات", req, days, req_y, req_first))

    # ۴) کلیک تله — clicked_at به UTC (یکدست؛ ایندکس‌دار)
    ck = _safe(lambda: _per_day_sql(
        "SELECT strftime('%Y-%m-%d', clicked_at, '+210 minutes') AS d, COUNT(*) AS n FROM clicks "
        "WHERE clicked_at>=? GROUP BY d", (_utc(s7),)), {})
    ck_y = _safe(lambda: db.scalar("SELECT COUNT(*) FROM clicks WHERE clicked_at>=? AND clicked_at<?",
                                   (_utc(starts[1]), _utc(y_cut)), 0), 0)
    trends.append(_trend("clicks", "🎯", "کلیک روی تله", ck, days, ck_y))

    # ۵) پیام ناشناس — قالب زمان مختلط (ربات/مینی‌اپ) → datetime() یکدستش می‌کند
    an = _safe(lambda: _per_day_sql(
        "SELECT strftime('%Y-%m-%d', datetime(timestamp), '+210 minutes') AS d, COUNT(*) AS n FROM anon_logs "
        "WHERE datetime(timestamp)>=? GROUP BY d", (_utc(s7),)), {})
    an_y = _safe(lambda: db.scalar("SELECT COUNT(*) FROM anon_logs WHERE datetime(timestamp)>=? AND datetime(timestamp)<?",
                                   (_utc(starts[1]), _utc(y_cut)), 0), 0)
    trends.append(_trend("anon", "💬", "پیام ناشناس", an, days, an_y))

    # ۶ و ۷) خرید و درآمد — ربات (ریال) + مینی‌اپ (تومان) → تومان
    def _rev_days():
        amt, cnt = {}, {}
        for r in db.rows(
                "SELECT strftime('%Y-%m-%d', datetime(timestamp), '+210 minutes') AS d, SUM(amount) AS s, COUNT(*) AS n "
                f"FROM transactions WHERE type IN ({tx_types}) AND amount>0 AND datetime(timestamp)>=? GROUP BY d",
                (*REVENUE_TX_TYPES, _utc(s7))):
            amt[r["d"]] = amt.get(r["d"], 0) + (r["s"] or 0) // ratio
            cnt[r["d"]] = cnt.get(r["d"], 0) + (r["n"] or 0)
        for r in db.rows(
                "SELECT strftime('%Y-%m-%d', paid_at, '+210 minutes') AS d, SUM(amount) AS s, COUNT(*) AS n "
                "FROM payments WHERE status='paid' AND paid_at>=? GROUP BY d", (_iso(s7),)):
            amt[r["d"]] = amt.get(r["d"], 0) + (r["s"] or 0)
            cnt[r["d"]] = cnt.get(r["d"], 0) + (r["n"] or 0)
        return amt, cnt

    def _rev_same():
        a = db.row(f"SELECT COALESCE(SUM(amount),0) AS s, COUNT(*) AS n FROM transactions WHERE type IN ({tx_types}) "
                   "AND amount>0 AND datetime(timestamp)>=? AND datetime(timestamp)<?",
                   (*REVENUE_TX_TYPES, _utc(starts[1]), _utc(y_cut)))
        b = db.row("SELECT COALESCE(SUM(amount),0) AS s, COUNT(*) AS n FROM payments WHERE status='paid' "
                   "AND paid_at>=? AND paid_at<?", (_iso(starts[1]), _iso(y_cut)))
        return (a["s"] // ratio + b["s"]), (a["n"] + b["n"])

    rv_amt, rv_cnt = _safe(_rev_days, ({}, {}))
    rv_ys, rv_yn = _safe(_rev_same, (0, 0))
    trends.append(_trend("purchases", "🛒", "خرید", rv_cnt, days, rv_yn))
    trends.append(_trend("revenue", "💰", "درآمد (تومان)", rv_amt, days, rv_ys, kind="money"))

    # ۸) عضویت کانال اجباری — joined_at به UTC
    jn = _safe(lambda: _per_day_sql(
        "SELECT strftime('%Y-%m-%d', joined_at, '+210 minutes') AS d, COUNT(*) AS n FROM channel_joins "
        "WHERE joined_at>=? GROUP BY d", (_utc(s7),)), {})
    jn_y = _safe(lambda: db.scalar("SELECT COUNT(*) FROM channel_joins WHERE joined_at>=? AND joined_at<?",
                                   (_utc(starts[1]), _utc(y_cut)), 0), 0)
    trends.append(_trend("joins", "📢", "عضویت کانال اجباری", jn, days, jn_y))

    # ۹) استفاده از کد هدیه — used_at به UTC
    gu = _safe(lambda: _per_day_sql(
        "SELECT strftime('%Y-%m-%d', used_at, '+210 minutes') AS d, COUNT(*) AS n FROM gift_usage "
        "WHERE used_at>=? GROUP BY d", (_utc(s7),)), {})
    gu_y = _safe(lambda: db.scalar("SELECT COUNT(*) FROM gift_usage WHERE used_at>=? AND used_at<?",
                                   (_utc(starts[1]), _utc(y_cut)), 0), 0)
    trends.append(_trend("gift_uses", "🎁", "استفاده از کد هدیه", gu, days, gu_y))

    # ۱۰ و ۱۱) خطا و ری‌استارت — شمارنده‌های ساعتی ماندگار
    y_hour = y_cut.strftime("%Y-%m-%d %H")
    # اولین استارتِ ثبت‌شده = شروع شمارش خطا/ری‌استارت (روزهای قبلش داده ندارند، نه «صفر»)
    er_first = _safe(lambda: metrics.counter_first_day("boot")) or days[0]
    er = _safe(lambda: metrics.counter_by_day("err", days[7], days[0]), {})
    er_y = _safe(lambda: metrics.counter_range("err", days[1] + " 00", y_hour), 0)
    trends.append(_trend("errors", "🧯", "خطای ربات", er, days, er_y, er_first))
    bt = _safe(lambda: metrics.counter_by_day("boot", days[7], days[0]), {})
    bt_y = _safe(lambda: metrics.counter_range("boot", days[1] + " 00", y_hour), 0)
    trends.append(_trend("boots", "🔁", "ری‌استارت سرور", bt, days, bt_y, er_first))

    # ۱۲ و ۱۳) رم و هزینهٔ سرور به تفکیک روز (نمونه‌های داخلی)
    sd = _safe(lambda: server_stats.daily_local(days[7], days[0]), {})
    disk = _safe(server_stats.disk_gb, 0.0) or 0.0
    s_first = min(sd) if sd else None
    ram_day = {d: v["mem"] for d, v in sd.items()}
    cost_day = {d: server_stats.cost_24h(v["mem"] / 1024.0, v["cpu"], disk)["total"] for d, v in sd.items()}
    trends.append(_trend("ram", "🧠", "میانگین رم (MB)", ram_day, days, None, s_first or days[0], kind="mb"))
    trends.append(_trend("cost", "💵", "هزینهٔ سرور", cost_day, days, None, s_first or days[0], kind="usd"))

    # ---------------- کل‌ها ----------------
    today_s, tomorrow_s = days[0], (d0 + timedelta(days=1)).strftime("%Y-%m-%d")
    week_end = (d0 + timedelta(days=7)).strftime("%Y-%m-%d")
    now_iso = _iso(t)

    def _users_block():
        u = db.row(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN source='referral' THEN 1 ELSE 0 END) AS src_ref, "
            "SUM(CASE WHEN source='welcome' THEN 1 ELSE 0 END) AS src_wel, "
            "SUM(CASE WHEN source='organic' THEN 1 ELSE 0 END) AS src_org, "
            "SUM(CASE WHEN COALESCE(blocked,0)=1 OR COALESCE(is_banned,0)=1 THEN 1 ELSE 0 END) AS banned, "
            "SUM(CASE WHEN COALESCE(blocked_by_admin,0)=1 THEN 1 ELSE 0 END) AS banned_admin, "
            "SUM(CASE WHEN COALESCE(blocked_bot,0)=1 THEN 1 ELSE 0 END) AS blocked_bot, "
            "SUM(CASE WHEN COALESCE(requested,0)=1 THEN 1 ELSE 0 END) AS requested, "
            "SUM(CASE WHEN streak_count>=2 AND last_streak_date=? THEN 1 ELSE 0 END) AS streak_active "
            "FROM users", (today_s,)) or {}
        out = {k: int(u.get(k) or 0) for k in ("total", "src_ref", "src_wel", "src_org", "banned",
                                               "banned_admin", "blocked_bot", "requested", "streak_active")}
        out["src_other"] = max(0, out["total"] - out["src_ref"] - out["src_wel"] - out["src_org"])
        return out

    users_b = _safe(_users_block, {}) or {}
    act_today = dau.get(days[0], 0)
    users_b["returning_today"] = _safe(lambda: int(db.scalar(
        "SELECT COUNT(*) FROM daily_active a JOIN users u ON u.user_id=a.user_id "
        "WHERE a.day=? AND u.created_at<?", (days[0], _local(d0)), 0)), 0)
    users_b["return_rate"] = round(users_b["returning_today"] * 100 / act_today) if act_today else None
    users_b["wau"] = _safe(lambda: metrics.distinct_active(days[6], days[0]), 0)
    users_b["mau"] = _safe(lambda: metrics.distinct_active((d0 - timedelta(days=29)).strftime("%Y-%m-%d"), days[0]), 0)
    users_b["active_data_days"] = ((d0.date() - datetime.strptime(dau_first, "%Y-%m-%d").date()).days + 1) if dau_first else 0
    users_b["new_activated_today"] = _safe(lambda: int(db.scalar(
        "SELECT COUNT(DISTINCT c.clicker_id) FROM clicks c JOIN users u ON u.user_id=c.clicker_id "
        "WHERE c.clicked_at>=? AND u.created_at>=?", (_utc(d0), _local(d0)), 0)), 0)

    def _bonus():
        y = days[1]
        return {"bonus_streak_alive": int(db.scalar("SELECT COUNT(*) FROM daily_bonus WHERE last_claim>=?", (y,), 0)),
                "bonus_streak_best": int(db.scalar("SELECT COALESCE(MAX(streak),0) FROM daily_bonus", (), 0))}
    users_b.update(_safe(_bonus, {"bonus_streak_alive": 0, "bonus_streak_best": 0}))

    def _vip_block():
        active = int(db.scalar(
            "SELECT COUNT(*) FROM (SELECT user_id FROM vip WHERE expire_date>=? "
            "UNION SELECT user_id FROM users WHERE vip_until IS NOT NULL AND vip_until>?)", (today_s, now_iso), 0))
        exp_2d = int(db.scalar("SELECT COUNT(*) FROM vip WHERE expire_date IN (?,?)", (today_s, tomorrow_s), 0))
        exp_7d = int(db.scalar("SELECT COUNT(*) FROM vip WHERE expire_date>=? AND expire_date<=?", (today_s, week_end), 0))
        bot_rial = db.row(f"SELECT COALESCE(SUM(amount),0) AS s, COUNT(*) AS n FROM transactions "
                          f"WHERE type IN ({tx_types}) AND amount>0", REVENUE_TX_TYPES)
        app_t = db.row("SELECT COALESCE(SUM(amount),0) AS s, COUNT(*) AS n FROM payments WHERE status='paid'")
        m30 = t - timedelta(days=30)
        bot30 = db.row(f"SELECT COALESCE(SUM(amount),0) AS s, COUNT(*) AS n FROM transactions WHERE type IN ({tx_types}) "
                       "AND amount>0 AND datetime(timestamp)>=?", (*REVENUE_TX_TYPES, _utc(m30)))
        app30 = db.row("SELECT COALESCE(SUM(amount),0) AS s, COUNT(*) AS n FROM payments WHERE status='paid' AND paid_at>=?",
                       (_iso(m30),))
        by_type = {r["type"]: (int(r["s"] or 0) // ratio, int(r["n"] or 0)) for r in db.rows(
            "SELECT type, SUM(amount) AS s, COUNT(*) AS n FROM transactions WHERE type IN ('reveal','saveface') "
            "AND amount>0 GROUP BY type")}
        buyers = int(db.scalar(
            f"SELECT COUNT(*) FROM (SELECT user_id FROM transactions WHERE type IN ({tx_types}) AND amount>0 "
            "UNION SELECT user_id FROM payments WHERE status='paid')", REVENUE_TX_TYPES, 0))
        reveals = int(db.scalar("SELECT COUNT(*) FROM reveals", (), 0))
        gifts = db.row("SELECT COUNT(*) AS codes, COALESCE(SUM(used_count),0) AS used, "
                       "SUM(CASE WHEN used_count<max_uses THEN 1 ELSE 0 END) AS active FROM gift_codes") or {}
        return {"active": active, "expiring_2d": exp_2d, "expiring_7d": exp_7d,
                "revenue_total": int(bot_rial["s"]) // ratio + int(app_t["s"]),
                "revenue_bot": int(bot_rial["s"]) // ratio, "revenue_app": int(app_t["s"]),
                "purchases_total": int(bot_rial["n"]) + int(app_t["n"]),
                "revenue_30d": int(bot30["s"]) // ratio + int(app30["s"]),
                "purchases_30d": int(bot30["n"]) + int(app30["n"]),
                "reveal_revenue": by_type.get("reveal", (0, 0))[0], "reveal_paid": by_type.get("reveal", (0, 0))[1],
                "reveals_total": reveals,
                "saveface_revenue": by_type.get("saveface", (0, 0))[0], "saveface_paid": by_type.get("saveface", (0, 0))[1],
                "buyers": buyers,
                "gift_codes": int(gifts.get("codes") or 0), "gift_used": int(gifts.get("used") or 0),
                "gift_active": int(gifts.get("active") or 0)}

    vip_b = _safe(_vip_block, {}) or {}
    if vip_b and users_b.get("total"):
        vip_b["conversion"] = round(vip_b["buyers"] * 100 / users_b["total"], 1)

    def _traps_block():
        r = db.row("SELECT COUNT(*) AS clicks, COUNT(DISTINCT clicker_id) AS snoopers, "
                   "COUNT(DISTINCT owner_id) AS owners FROM clicks") or {}
        return {"clicks_total": int(r.get("clicks") or 0), "snoopers_total": int(r.get("snoopers") or 0),
                "owners_total": int(r.get("owners") or 0),
                "snoopers_today": int(db.scalar("SELECT COUNT(DISTINCT clicker_id) FROM clicks WHERE clicked_at>=?",
                                                (_utc(d0),), 0)),
                "traps_total": int(db.scalar("SELECT COUNT(*) FROM traps", (), 0)),
                "spins_total": int(db.scalar("SELECT COUNT(*) FROM wheel_spins", (), 0)),
                "spins_today": int(db.scalar("SELECT COUNT(*) FROM wheel_spins WHERE datetime(created_at)>=?",
                                             (_utc(d0),), 0)),
                "anon_30d": int(db.scalar("SELECT COUNT(*) FROM anon_logs", (), 0))}

    traps_b = _safe(_traps_block, {}) or {}

    def _top_today():
        rs = db.rows(
            "SELECT c.owner_id, u.first_name, u.last_name, u.username, COUNT(DISTINCT c.clicker_id) AS n, "
            "EXISTS(SELECT 1 FROM vip v WHERE v.user_id=c.owner_id AND v.expire_date>=?) AS is_vip "
            "FROM clicks c JOIN users u ON u.user_id=c.owner_id WHERE c.clicked_at>=? "
            "GROUP BY c.owner_id ORDER BY n DESC LIMIT 5", (today_s, _utc(d0)))
        return [{"id": r["owner_id"], "name": display_name(r), "snoops": int(r["n"]), "vip": bool(r["is_vip"])}
                for r in rs]

    top = _safe(_top_today, []) or []

    def _system_block():
        out = {"channels": int(db.scalar("SELECT COUNT(*) FROM forced_channels", (), 0)),
               "channel_joins_total": int(db.scalar(
                   "SELECT COUNT(*) FROM channel_joins WHERE channel_username IN (SELECT channel_id FROM forced_channels)",
                   (), 0)),
               "open_tickets": int(db.scalar("SELECT COUNT(*) FROM support_tickets WHERE status='open'", (), 0))}
        # آخرین پخش همگانی: پنل ربات (settings) یا مینی‌اپ (broadcast_jobs) — هر کدام جدیدتر
        bc = db.row("SELECT value FROM settings WHERE key='last_broadcast_stats'")
        bc_at = db.row("SELECT value FROM settings WHERE key='last_broadcast_at'")
        last = None
        if bc:
            try:
                at = float(bc_at["value"]) if bc_at else None
            except (TypeError, ValueError):
                at = None
            last = {"text": bc["value"], "at": at, "via": "ربات"}
        job = db.row("SELECT sent, total, finished_at FROM broadcast_jobs WHERE status='done' AND finished_at IS NOT NULL "
                     "ORDER BY finished_at DESC LIMIT 1")
        if job:
            try:
                j_at = datetime.fromisoformat(job["finished_at"]).timestamp()
            except (TypeError, ValueError):
                j_at = None
            if j_at and (not last or not last.get("at") or j_at > last["at"]):
                pct = int(job["sent"] * 100 / job["total"]) if job["total"] else 0
                last = {"text": f"{job['sent']}/{job['total']} ({pct}%)", "at": j_at, "via": "مینی‌اپ"}
        out["last_broadcast"] = last
        return out

    system_b = _safe(_system_block, {}) or {}

    def _challenge():
        from services import admin as _adm  # import دیرهنگام — admin هم dashboard را import می‌کند
        st = _adm._chal_get("challenge_status") or "idle"
        if st not in ("scheduled", "active"):
            return None
        win = _adm._chal_window()
        rem = None
        if win:
            ref = win[0] if st == "scheduled" else win[1]
            try:
                end = datetime.strptime(ref, _adm._CHAL_FMT).replace(tzinfo=timezone.utc)
                rem = max(0, int((end - datetime.now(timezone.utc)).total_seconds()))
            except ValueError:
                rem = None
        return {"status": st, "remaining_sec": rem}

    challenge = _safe(_challenge, None)
    runtime = {}
    if _runtime_fn:
        runtime = _safe(_runtime_fn, {}) or {}

    server = _safe(server_stats.snapshot, {}) or {}
    server["boots_today"] = bt.get(days[0], 0) if isinstance(bt, dict) else 0
    server["boots_yesterday"] = bt.get(days[1], 0) if isinstance(bt, dict) else 0
    mr = _safe(lambda: metrics.counter_by_day("memrestart", days[1], days[0]), {}) or {}
    server["memrestarts_today"] = mr.get(days[0], 0)

    return {"generated_at": time.time(), "today": days[0], "now_hm": t.strftime("%H:%M"),
            "trends": trends, "users": users_b, "vip": vip_b, "traps": traps_b, "top_today": top,
            "system": system_b, "challenge": challenge, "runtime": runtime, "server": server}


def collect(max_age: float = 60.0) -> dict:
    """داده‌های داشبورد با کش کوتاه (پیش‌فرض ۶۰ ثانیه) — یک محاسبه در هر لحظه."""
    with _cache_lock:
        if _cache["data"] is not None and time.time() - _cache["at"] < max_age:
            return _cache["data"]
        data = _compute()
        _cache.update({"at": time.time(), "data": data})
        return data


# ======================= قالب متنی ربات (preset «روند و مقایسه») =======================
_FA = str.maketrans("0123456789.", "۰۱۲۳۴۵۶۷۸۹٫")


def fa(x) -> str:
    return str(x).translate(_FA)


def num(x) -> str:
    try:
        return fa(f"{int(round(float(x))):,}".replace(",", "٬"))
    except (TypeError, ValueError):
        return "—"


def usd(x) -> str:
    if x is None:
        return "—"
    x = float(x)
    if 0 < x < 0.01:
        return "<" + fa("0.01") + "$"
    return fa(f"{x:.2f}" if x >= 0.1 else f"{x:.3f}") + "$"


def _val(v, kind: str, avg: bool = False) -> str:
    if v is None:
        return "—"
    if kind == "usd":
        return usd(v)
    if avg and kind == "int" and 0 < float(v) < 10:
        return fa(f"{float(v):.1f}")  # میانگین‌های کوچک (مثلاً ۰٫۳ خرید در روز) صفر نشوند
    return num(v)


def _delta(today, y_same) -> str:
    if y_same is None:
        return ""
    today, y_same = float(today or 0), float(y_same or 0)
    if y_same == 0:
        return " ▲" if today > 0 else ""
    p = round((today - y_same) * 100 / y_same)
    if p == 0:
        return " ±۰٪"
    return (" ▲" if p > 0 else " ▼") + fa(abs(p)) + "٪"


def _dur(sec) -> str:
    sec = int(sec or 0)
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if d:
        return f"{fa(d)} روز و {fa(h)} ساعت"
    if h:
        return f"{fa(h)} ساعت و {fa(m)} دقیقه"
    return f"{fa(m)} دقیقه"


def _bar(pct: float, width: int = 10) -> str:
    full = max(0, min(width, int(round(pct / 100 * width))))
    return "▓" * full + "░" * (width - full)


def _shamsi(ts: float | None, with_time: bool = True) -> str:
    if not ts:
        return ""
    dt = datetime.fromtimestamp(ts, TEHRAN)
    try:
        import jdatetime

        j = jdatetime.date.fromgregorian(date=dt.date()).strftime("%Y/%m/%d")
    except Exception:
        j = dt.strftime("%Y/%m/%d")
    return fa(j + (" " + dt.strftime("%H:%M") if with_time else ""))


def _md(s) -> str:
    from services.bale_api import escape_md

    return escape_md(s)


def bot_text(d: dict) -> str:
    L = []
    L.append(f"📊 *داشبورد فضول‌یاب* — {_shamsi(d['generated_at'], False)} · ساعت {fa(d['now_hm'])}")
    L.append("روند: *امروز تا این لحظه* · دیروز · م۷ = میانگین ۷ روز کامل")
    L.append("▲▼ = تغییر نسبت به دیروز تا همین ساعت")
    L.append("━━━━━━━━━━━━━━")
    L.append("📈 *روند امروز*")
    for tr in d["trends"]:
        kind = tr["kind"]
        delta = "" if kind in ("mb", "usd") else _delta(tr["today"], tr["y_same"])
        avg = _val(tr["avg7"], kind, avg=True)
        if tr["avg7"] is not None and tr["avg_days"] and tr["avg_days"] < 7:
            avg += f"({fa(tr['avg_days'])}ر)"
        L.append(f"{tr['icon']} {tr['label']}: *{_val(tr['today'], kind)}*{delta} · دیروز {_val(tr['yesterday'], kind)} · م۷ {avg}")

    u, v, tp, sy, sv, rt = d["users"], d["vip"], d["traps"], d["system"], d["server"], d["runtime"]
    if u:
        L.append("━━━━━━━━━━━━━━")
        L.append("👥 *کاربران*")
        wau = f"فعال ۷ روز: {num(u.get('wau'))} · ۳۰ روز: {num(u.get('mau'))}"
        if u.get("active_data_days", 0) < 30:
            wau += f" (از {fa(u.get('active_data_days', 0))} روز داده)"
        L.append(f"👥 کل: *{num(u.get('total'))}* · {wau}")
        rr = f"{fa(u['return_rate'])}٪" if u.get("return_rate") is not None else "—"
        L.append(f"🔁 بازگشتی امروز: {rr} از فعال‌ها (عضو قبل از امروز) · ✨ جدیدهای فضول‌شده: {num(u.get('new_activated_today'))}")
        L.append(f"📥 منبع ورود: تله {num(u.get('src_ref'))} · خوش‌آمد {num(u.get('src_wel'))} · "
                 f"مستقیم {num(u.get('src_org'))} · مینی‌اپ/نامشخص {num(u.get('src_other'))}")
        L.append(f"🔥 استریک ورود فعال (۲+ روز): {num(u.get('streak_active'))} · استریک جایزه: {num(u.get('bonus_streak_alive'))} "
                 f"زنده · رکورد {num(u.get('bonus_streak_best'))} روز")
        L.append(f"🧑‍💻 حداقل یک درخواست به ربات: {num(rt.get('requested_total') or u.get('requested'))} نفر")
        L.append(f"🛡 مسدود: {num(u.get('banned'))} (توسط ادمین {num(u.get('banned_admin'))}) · "
                 f"🚫 ربات را بلاک کرده: {num(u.get('blocked_bot'))}")
    if v:
        L.append("━━━━━━━━━━━━━━")
        L.append("👑 *VIP و درآمد* (تومان)")
        L.append(f"👑 VIP فعال: *{num(v.get('active'))}* · انقضا امروز/فردا: {num(v.get('expiring_2d'))} · تا ۷ روز: {num(v.get('expiring_7d'))}")
        L.append(f"💰 ۳۰ روز اخیر: *{num(v.get('revenue_30d'))}* ({num(v.get('purchases_30d'))} خرید)")
        L.append(f"💰 کل: {num(v.get('revenue_total'))} ({num(v.get('purchases_total'))} خرید) — "
                 f"ربات {num(v.get('revenue_bot'))} · مینی‌اپ {num(v.get('revenue_app'))}")
        L.append(f"🔓 بازکردن پروفایل: {num(v.get('reveals_total'))} بار ({num(v.get('reveal_paid'))} پولی · {num(v.get('reveal_revenue'))}) · "
                 f"😶 حفظ آبرو: {num(v.get('saveface_paid'))} ({num(v.get('saveface_revenue'))})")
        conv = f"{fa(v['conversion'])}٪" if v.get("conversion") is not None else "—"
        L.append(f"🛍 خریدار یکتا: {num(v.get('buyers'))} · نرخ تبدیل: {conv}")
        L.append(f"🎁 کد هدیه: {num(v.get('gift_active'))} فعال از {num(v.get('gift_codes'))} کد · {num(v.get('gift_used'))} بار استفاده")
    if tp:
        L.append("━━━━━━━━━━━━━━")
        L.append("🎯 *تله‌ها و فضول‌ها*")
        L.append(f"🎯 کلیک کل: {num(tp.get('clicks_total'))} · فضول یکتا: {num(tp.get('snoopers_total'))} "
                 f"(امروز {num(tp.get('snoopers_today'))}) · صاحب تله: {num(tp.get('owners_total'))}")
        L.append(f"🪤 تلهٔ ساخته‌شده: {num(tp.get('traps_total'))} · 🎡 گردونه: {num(tp.get('spins_total'))} "
                 f"(امروز {num(tp.get('spins_today'))}) · 💬 ناشناس ۳۰ روز: {num(tp.get('anon_30d'))}")
        ch = d.get("challenge")
        if ch:
            rem = _dur(ch.get("remaining_sec")) if ch.get("remaining_sec") is not None else "—"
            L.append(f"🏆 چالش: {'در جریان' if ch['status'] == 'active' else 'زمان‌بندی‌شده'} — "
                     f"{'تا پایان' if ch['status'] == 'active' else 'تا شروع'} {rem}")
        if d.get("top_today"):
            L.append("🏆 تله‌های برتر امروز (فضول یکتا):")
            medals = ["🥇", "🥈", "🥉", "🏅", "🎖"]
            for i, r in enumerate(d["top_today"]):
                crown = " 👑" if r.get("vip") else ""
                L.append(f"  {medals[i]} {_md(r['name'][:24])}{crown} — {num(r['snoops'])}")
    if sv:
        L.append("━━━━━━━━━━━━━━")
        L.append("🖥 *سرور Railway*")
        lim = sv.get("mem_limit_mb") or 512
        pct = sv.get("mem_now_mb", 0) * 100 / lim if lim else 0
        L.append(f"🧠 رم الان: *{num(sv.get('mem_now_mb'))}MB* از {num(lim)} {_bar(pct)} {fa(round(pct))}٪")
        cov = sv.get("covered_h") or 0
        cov_s = f" (پوشش {fa(round(cov))} ساعت)" if cov < 23 else ""
        L.append(f"📈 ۲۴ ساعت: کمینه {num(sv.get('mem_min_mb'))} · میانگین {num(sv.get('mem_avg_mb'))} · "
                 f"بیشینه {num(sv.get('mem_max_mb'))} MB{cov_s}")
        cpu_a, cpu_m = float(sv.get("cpu_avg") or 0), float(sv.get("cpu_max") or 0)
        L.append(f"⚙️ CPU: میانگین {fa(format(cpu_a, '.3f'))} · بیشینه {fa(format(cpu_m, '.2f'))} vCPU")
        c = sv.get("cost") or {}
        eg = usd(c.get("egress")) if c.get("egress") is not None else "نامعلوم"
        L.append(f"💵 پیش‌بینی ۲۴ ساعت: *{usd(c.get('total'))}* (رم {usd(c.get('ram'))} · CPU {usd(c.get('cpu'))} · "
                 f"دیسک {usd(c.get('disk'))} · ترافیک {eg})")
        month = f"📅 پیش‌بینی ماه (۳۰ روز): ≈ {usd(sv.get('cost_month'))}"
        if sv.get("plan_credit"):
            month += f" از {usd(sv['plan_credit'])} اعتبار پلن"
        L.append(month)
        L.append(f"💾 دیتابیس: {num(sv.get('db_mb'))}MB · دیسک: {fa(format(float(sv.get('disk_gb') or 0), '.2f'))}GB · "
                 f"🛡 گارد حافظه: {num(sv.get('soft_mb'))}/{num(sv.get('hard_mb'))}MB")
        mr = f" (حافظه‌ای {fa(sv['memrestarts_today'])})" if sv.get("memrestarts_today") else ""
        L.append(f"⏱ آپ‌تایم: {_dur(sv.get('uptime_sec'))} · ری‌استارت امروز: {fa(sv.get('boots_today', 0))}{mr}")
        if sv.get("source") == "railway":
            L.append(f"📡 منبع ۲۴ساعت/هزینه: API رسمی Railway ✅ ({_dur(sv.get('railway_age_sec'))} پیش)")
        elif sv.get("railway_configured") and sv.get("railway_error"):
            L.append(f"📡 API Railway خطا داد ({_md(sv['railway_error'][:50])}) — اندازه‌گیری داخلی")
        else:
            L.append("📡 منبع: اندازه‌گیری داخلی · برای عدد دقیق Railway متغیر RAILWAY\\_API\\_TOKEN را ست کنید")
    L.append("━━━━━━━━━━━━━━")
    L.append("⚙️ *سیستم*")
    broken = rt.get("broken_channels") or []
    L.append(f"📢 جوین اجباری: {num(sy.get('channels'))} کانال · عضویت کل {num(sy.get('channel_joins_total'))} · "
             f"مشکل‌دار: {_md(', '.join(broken)) if broken else 'ندارد ✅'}")
    if rt.get("err_total"):
        L.append(f"🧯 خطاها از آخرین ری‌استارت: {num(rt['err_total'])} — آخرین: {_md((rt.get('err_last') or '')[:60])}")
    else:
        L.append("🧯 خطاها از آخرین ری‌استارت: ندارد ✅")
    if rt.get("top_button"):
        tb = rt["top_button"]
        L.append(f"🖱 پرکلیک‌ترین دکمه: «{_md(tb.get('label'))}» ({num(tb.get('count'))} کلیک)")
    if rt.get("month_requests") is not None:
        L.append(f"🗓 درخواست‌های این ماه (شمسی): {num(rt['month_requests'])}")
    lb = sy.get("last_broadcast")
    if lb:
        when = f" — {_shamsi(lb['at'])}" if lb.get("at") else ""
        L.append(f"📣 آخرین پخش همگانی ({lb.get('via')}): {fa(_md(lb['text'])).replace('%', '٪')}{when}")
    else:
        L.append("📣 آخرین پخش همگانی: ندارد")
    L.append(f"🎫 تیکت باز پشتیبانی: {num(sy.get('open_tickets'))}")
    L.append("━━━━━━━━━━━━━━")
    L.append(f"🔄 بروزرسانی: {_shamsi(d['generated_at'])} (کش ۶۰ ثانیه)")
    text = "\n".join(L)
    if len(text) > 4000:  # سقف پیام بله — ابتدا لیست تله‌های برتر کوتاه می‌شود
        text = text[:3990] + "\n…"
    return text


def api_view(d: dict) -> dict:
    """نسخهٔ JSON برای مینی‌اپ (همان داده‌ها)."""
    return d
