"""فضول‌یابی — پل‌شده به جداول واقعی ربات (traps / clicks / nicknames).

جریان: کاربر لینک `ble.ir/<bot>?start=<code>` را منتشر می‌کند (code = کد تله یا
کد base62 شناسه) → بازدیدکننده در بله /start می‌زند → هندلر اصلی ربات کلیک را در
`clicks` ثبت و به مالک اطلاع می‌دهد → مینی‌اپ همان دیتا را می‌خواند.
VIP: هویت کامل فضول‌ها؛ عادی: ماسک‌شده.
"""
from __future__ import annotations

from datetime import timedelta

import settings
from services import avatars, bale_api, db, legacy_bridge, vip
from services.common import AppError, iso, now, tehran_day_start

DEFAULT_TRAP_TITLE = "لینک اصلی من"


def link(code: str) -> str:
    return f"{settings.BALE_DEEPLINK_BASE}{bale_api.bot_username()}?start={code}"


def ensure_default_trap(owner_id: int) -> dict:
    """تلهٔ پیش‌فرض ربات مجازی است (کد base62 شناسه) — رکورد جدول ندارد."""
    code = legacy_bridge.default_trap_code(owner_id)
    u = db.row("SELECT created_at FROM users WHERE user_id=?", (owner_id,)) or {}
    return {"id": code, "code": code, "title": DEFAULT_TRAP_TITLE, "bait": "",
            "is_default": 1, "created_at": u.get("created_at") or "", "link": link(code)}


def limits(owner_id: int) -> dict:
    is_vip = vip.is_active(owner_id)
    custom = db.scalar("SELECT COUNT(*) FROM traps WHERE owner_id=?", (owner_id,), 0)
    # v4.7 (همگام‌سازی با پنل شیشه‌ای): سقف تله از همان تنظیم زندهٔ ربات
    # (vip_max_traps — پیش‌فرض ۳ مثل ربات)؛ تلهٔ اختصاصی فقط برای VIP.
    from services import bot_settings
    max_traps = bot_settings.get_int("vip_max_traps", 3) if is_vip else 0
    return {"max_traps": max_traps,
            "custom_traps": custom, "reveal": is_vip, "vip_required": not is_vip}


def create_trap(owner_id: int, title: str, bait: str = "") -> dict:
    title, bait = (title or "").strip(), (bait or "").strip()
    if not 2 <= len(title) <= 40:
        raise AppError("VALIDATION_ERROR", "عنوان تله باید بین ۲ تا ۴۰ کاراکتر باشد.", 422)
    lim = limits(owner_id)
    # v4.7 (همگام‌سازی با پنل شیشه‌ای): ساخت تلهٔ اختصاصی فقط برای VIP —
    # در ربات هم add_trap برای غیر VIP با MY_TRAPS_VIP_ONLY رد می‌شود.
    if not lim["reveal"]:
        raise AppError("VIP_REQUIRED", "ساخت تلهٔ اختصاصی فقط برای اعضای VIP است.", 403)
    if lim["custom_traps"] >= lim["max_traps"]:
        msg = f"به سقف {lim['max_traps']} تله رسیده‌اید."
        raise AppError("LIMIT_REACHED", msg, 403)
    code = legacy_bridge.new_trap_code(owner_id)
    db.execute("INSERT INTO traps(trap_code, owner_id, label) VALUES(?,?,?)", (code, owner_id, title[:40]))
    t = db.row("SELECT * FROM traps WHERE trap_code=?", (code,)) or {}
    return _trap_view(t, owner_id)


def delete_trap(owner_id: int, code: str) -> None:
    t = db.row("SELECT trap_code FROM traps WHERE trap_code=? AND owner_id=?", (code, owner_id))
    if not t:
        raise AppError("NOT_FOUND", "تله پیدا نشد.", 404)
    db.execute("DELETE FROM traps WHERE trap_code=? AND owner_id=?", (code, owner_id))


def _trap_view(t: dict, owner_id: int) -> dict:
    code = t.get("trap_code") or t.get("code") or ""
    visits = db.scalar("SELECT COUNT(*) FROM clicks WHERE owner_id=? AND trap_code=?", (owner_id, code), 0)
    return {"id": code, "code": code, "title": t.get("label") or "تله", "bait": t.get("bait") or "",
            "is_default": 0, "created_at": t.get("created_at") or "", "link": link(code), "visits": int(visits or 0)}


def trap_title(code: str | None) -> str:
    if not code:
        return DEFAULT_TRAP_TITLE
    r = db.row("SELECT label FROM traps WHERE trap_code=?", (code,))
    return (r.get("label") if r else None) or "تله"


def _visits_where(owner_id: int, code: str | None) -> tuple[str, list]:
    where, params = "c.owner_id=?", [owner_id]
    if code:
        where += " AND c.trap_code=?"
        params.append(code)
    # بدون code → همهٔ بازدیدها (لینک اصلی + همهٔ تله‌ها) — فیلتر «همه» مینی‌اپ
    return where, params


def visitors(owner_id: int, trap_code: str | None = None, cursor: int = 0, size: int = 20) -> dict:
    reveal = vip.is_active(owner_id)
    where, params = _visits_where(owner_id, trap_code)
    total = db.scalar(f"SELECT COUNT(*) FROM (SELECT c.clicker_id, c.trap_code FROM clicks c WHERE {where} GROUP BY c.clicker_id, c.trap_code)", params, 0)
    rs = db.rows(
        f"""SELECT c.clicker_id, c.trap_code,
                   MAX(COALESCE(n.nickname, c.clicker_name)) AS visitor_name,
                   MAX(c.clicker_username) AS visitor_username,
                   COUNT(*) AS count,
                   MIN(c.clicked_at) AS first_at,
                   MAX(c.clicked_at) AS last_at
            FROM clicks c
            LEFT JOIN nicknames n ON n.owner_id=c.owner_id AND n.clicker_id=c.clicker_id
            WHERE {where}
            GROUP BY c.clicker_id, c.trap_code
            ORDER BY last_at DESC LIMIT ? OFFSET ?""",
        params + [size, cursor],
    )
    traps_map = {t["trap_code"]: t["label"] for t in db.rows("SELECT trap_code, label FROM traps WHERE owner_id=?", (owner_id,))}
    items = []
    for i, r in enumerate(rs):
        name = r["visitor_name"] or "کاربر بله"
        code = r["trap_code"] or ""
        if reveal:
            base = {"id": f"{r['clicker_id']}", "trap_id": code, "trap_title": traps_map.get(code) or DEFAULT_TRAP_TITLE,
                    "count": r["count"], "visited_at": r["last_at"], "first_at": r["first_at"]}
            items.append({**base, "masked": False, "name": name, "username": r["visitor_username"], "user_id": r["clicker_id"], "avatar": avatars.url_for(r["clicker_id"])})
        else:
            # v4.7 (باگ «کل فضول‌ها»): کاربر عادی فقط نام فضول را می‌بیند (بدون ماسک —
            # هم‌سو با پنل شیشه‌ای ربات)؛ نه تعداد مراجعه، نه کدام تله، نه زمان؛
            # و هرگز شناسهٔ عددی واقعی. reveal_code = کد base62 فقط برای خرید تک‌نفره.
            items.append({"id": f"v{i + 1}", "masked": True, "name": name,
                          "reveal_code": legacy_bridge.encode_id(r["clicker_id"])})
    nxt = cursor + size
    return {"items": items, "next_cursor": str(nxt) if nxt < total else None, "total": total}


def _day_counts(owner_id: int, days: int) -> list[dict]:
    chart = []
    for d in range(days - 1, -1, -1):
        # tehran_day_start خروجی UTC می‌دهد؛ ستون clicked_at ربات هم UTC است
        start, end = tehran_day_start(d), tehran_day_start(d) + timedelta(days=1)
        s = start.strftime("%Y-%m-%d %H:%M:%S")
        e = end.strftime("%Y-%m-%d %H:%M:%S")
        cnt = db.scalar("SELECT COUNT(*) FROM clicks WHERE owner_id=? AND clicked_at>=? AND clicked_at<?",
                        (owner_id, s, e), 0)
        chart.append({"date": iso(start), "count": cnt})
    return chart


def summary(owner_id: int) -> dict:
    default = ensure_default_trap(owner_id)
    traps = [default]
    for t in db.rows("SELECT * FROM traps WHERE owner_id=? ORDER BY created_at ASC", (owner_id,)):
        traps.append(_trap_view(t, owner_id))
    default_visits = db.scalar("SELECT COUNT(*) FROM clicks WHERE owner_id=? AND trap_code IS NULL", (owner_id,), 0)
    traps[0]["visits"] = int(default_visits)
    chart = _day_counts(owner_id, 7)
    # v4.7 (باگ «کل فضول‌ها»): «کل» = تعداد فضول‌های یکتا (COUNT DISTINCT) — نه کل کلیک‌ها.
    # نمودار «فعالیت ۷ روز اخیر» همچنان کلیک است (برچسبش بازدید/فعالیت است).
    total = db.scalar("SELECT COUNT(DISTINCT clicker_id) FROM clicks WHERE owner_id=?", (owner_id,), 0)
    return {"link": default["link"], "traps": traps,
            "stats": {"today": chart[-1]["count"], "week": sum(x["count"] for x in chart),
                      "total": total, "chart": chart},
            "limits": limits(owner_id)}


def quick_stats(owner_id: int) -> dict:
    default = ensure_default_trap(owner_id)
    today_start = legacy_bridge.today_utc_str()
    # v4.7 (باگ «کل فضول‌ها»): «کل فضول‌ها» و «فضول امروز» = فضول یکتا (COUNT DISTINCT clicker_id)
    # — قبلاً COUNT(*) کلیک‌ها بود و عدد تکراریها را هم می‌شمرد.
    today = db.scalar("SELECT COUNT(DISTINCT clicker_id) FROM clicks WHERE owner_id=? AND clicked_at>=?",
                      (owner_id, today_start), 0)
    total = db.scalar("SELECT COUNT(DISTINCT clicker_id) FROM clicks WHERE owner_id=?", (owner_id,), 0)
    distinct = total
    return {"today": today, "total": total, "distinct": distinct, "link": default["link"]}


def radar(owner_id: int) -> dict:
    """v4.4: رادار فضول‌ها — همهٔ داده‌ها از جدول clicks موجود خوانده می‌شود.

    - ساعات پربازدید: توزیع ۲۴ ساعتهٔ کلیک‌های ۱۴ روز اخیر به وقت تهران
    - بهترین تله (کانال انتشار): تله‌ای که بیشترین فضول یکتا را در ۱۴ روز اخیر آورده
    - مقایسه با میانگین: کلیک ۷ روز اخیر من در برابر میانگین هر صاحب‌لینک فعال کل ربات
    """
    from services.common import TEHRAN, parse  # محلی — جلوگیری از چرخهٔ ایمپورت

    def _utc_str(days_ago: int) -> str:
        return (now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")

    since14, since7 = _utc_str(14), _utc_str(7)

    hour_counts = [0] * 24
    for r in db.rows("SELECT clicked_at FROM clicks WHERE owner_id=? AND clicked_at>=?", (owner_id, since14)):
        dt = parse(r.get("clicked_at"))
        if not dt:
            continue
        try:
            hour_counts[dt.astimezone(TEHRAN).hour] += 1
        except Exception:
            continue

    best_hours = sorted(range(24), key=lambda h: hour_counts[h], reverse=True)[:3]
    best_hours = [h for h in best_hours if hour_counts[h] > 0]

    trap_rows = db.rows(
        """SELECT COALESCE(trap_code,'') AS code, COUNT(*) AS clicks, COUNT(DISTINCT clicker_id) AS snoops
           FROM clicks WHERE owner_id=? AND clicked_at>=? GROUP BY COALESCE(trap_code,'')
           ORDER BY snoops DESC, clicks DESC LIMIT 1""", (owner_id, since14))
    best_trap = None
    if trap_rows and (trap_rows[0]["snoops"] or trap_rows[0]["clicks"]):
        tr = trap_rows[0]
        title = trap_title(tr["code"] or None)
        if not tr["code"]:
            title = DEFAULT_TRAP_TITLE
        best_trap = {"code": tr["code"] or "", "title": title, "snoops": int(tr["snoops"] or 0),
                     "clicks": int(tr["clicks"] or 0)}

    me_week = db.scalar("SELECT COUNT(*) FROM clicks WHERE owner_id=? AND clicked_at>=?", (owner_id, since7), 0)
    total_week = db.scalar("SELECT COUNT(*) FROM clicks WHERE clicked_at>=?", (since7,), 0)
    owners_week = db.scalar("SELECT COUNT(DISTINCT owner_id) FROM clicks WHERE clicked_at>=?", (since7,), 0)
    avg_week = round(total_week / owners_week, 1) if owners_week else 0.0
    diff_pct = None
    if avg_week > 0:
        diff_pct = int(round((me_week - avg_week) / avg_week * 100))

    return {
        "hour_chart": [{"hour": h, "count": hour_counts[h]} for h in range(24)],
        "best_hours": [{"hour": h, "count": hour_counts[h]} for h in sorted(best_hours)],
        "best_trap": best_trap,
        "me_last_week": me_week,
        "avg_last_week": avg_week,
        "diff_pct": diff_pct,
    }


def record_visit(code: str, visitor: dict) -> dict | None:
    """ثبت بازدید خودکار توسط هندلر /start ربات انجام می‌شود (جداول clicks).
    این تابع فقط برای سازگاری نگه داشته شده و دیگر استفاده نمی‌شود."""
    return None
