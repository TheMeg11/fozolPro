"""پاداش‌ها — جایزه روزانه، کد هدیه و استریک روزانه برای مینی‌اپ.

منطق دقیقاً هم‌ارز منوی «🎁 پاداش‌ها» پنل شیشه‌ای ربات (main.py):
- جایزه روزانه: همهٔ کاربران، ریست ۰۰:۰۰ به وقت تهران؛ قرعه‌کشی با همان
  وزن‌های DAILY_PRIZES؛ پاداش استریک ‎+۱۰٪‎ به ازای هر روز پیوسته تا سقف ۱۰۰٪؛
  جایزهٔ VIP نقاط عطف استریک (۱۰/۲۰/۳۰/۴۰+).
- کد هدیه: کدهای معتبر (ظرفیت آزاد + استفاده‌نشده توسط کاربر) + فعال‌سازی اتمیک.
- touch_daily: همگام‌سازی استریک/XP ورود روزانه وقتی کاربر فقط از مینی‌اپ می‌آید.
"""
from __future__ import annotations

import secrets
from datetime import date, timedelta

from services import db, users, vip
from services.common import TEHRAN, AppError, now
from services.common import now as _now

log = __import__("logging").getLogger("rewards")

# ====== جوایز جایزه روزانه — همان DAILY_PRIZES ربات ======
DAILY_PRIZES = [
    {"type": "xp", "value": 30, "weight": 30, "label": "۳۰ XP"},
    {"type": "xp", "value": 60, "weight": 24, "label": "۶۰ XP"},
    {"type": "xp", "value": 100, "weight": 18, "label": "۱۰۰ XP"},
    {"type": "xp", "value": 200, "weight": 12, "label": "۲۰۰ XP"},
    {"type": "xp", "value": 500, "weight": 6, "label": "۵۰۰ XP"},
    {"type": "xp", "value": 1000, "weight": 2, "label": "۱٬۰۰۰ XP"},
    {"type": "vip", "value": 1, "weight": 3, "label": "۱ روز VIP (جک‌پات!)"},
]
DAILY_STREAK_BONUS_STEP = 10   # درصد پاداش استریک به‌ازای هر روز پیوسته
DAILY_STREAK_BONUS_CAP = 100   # سقف پاداش استریک (درصد)

# ====== جوایز VIP نقاط عطف استریک — همان streak_vip_reward ربات ======
def streak_vip_reward(streak: int) -> int:
    s = int(streak or 0)
    if s == 10:
        return 1
    if s == 20:
        return 2
    if s == 30:
        return 3
    if s >= 40 and s % 10 == 0:
        return 5
    return 0


def _today_tehran() -> str:
    return now().astimezone(TEHRAN).date().isoformat()


def _yesterday_tehran() -> str:
    return (now().astimezone(TEHRAN).date() - timedelta(days=1)).isoformat()


def _utc_today() -> str:
    return date.today().isoformat()


def _lottery(prizes: list[dict]) -> dict:
    """قرعه‌کشی وزن‌دار با RNG رمنگ — همان random.choices ربات."""
    return secrets.SystemRandom().choices(prizes, weights=[p["weight"] for p in prizes], k=1)[0]


# ---------------- جایزه روزانه ----------------
def daily_state(user_id: int) -> dict:
    """وضعیت جایزه روزانه — همان render_daily_bonus ربات."""
    r = db.row("SELECT last_claim, streak, total_claims FROM daily_bonus WHERE user_id=?", (user_id,)) or {}
    raw_streak = int(r.get("streak") or 0)
    last_claim = r.get("last_claim")
    today, yesterday = _today_tehran(), _yesterday_tehran()
    streak = raw_streak if last_claim in (today, yesterday) else 0
    done = last_claim == today
    bonus_pct = min(max(streak, 0) * DAILY_STREAK_BONUS_STEP, DAILY_STREAK_BONUS_CAP)
    return {
        "done": done, "streak": streak, "bonus_pct": bonus_pct,
        "total_claims": int(r.get("total_claims") or 0),
        "prizes": [{"label": p["label"], "type": p["type"], "value": p["value"]} for p in DAILY_PRIZES],
    }


def claim_daily(user_id: int) -> dict:
    """دریافت جایزه روزانه — همان daily_claim ربات (اتمیک ضد دابل‌کلیک)."""
    today, yesterday = _today_tehran(), _yesterday_tehran()
    with db.tx() as c:
        row = c.execute("SELECT last_claim FROM daily_bonus WHERE user_id=?", (user_id,)).fetchone()
        if row and row[0] == today:
            raise AppError("ALREADY_CLAIMED", "جایزهٔ امروز را قبلاً گرفته‌ای؛ فردا دوباره بیا!", 429)
        c.execute(
            """INSERT INTO daily_bonus (user_id, last_claim, streak, total_claims) VALUES(?,?,1,1)
               ON CONFLICT(user_id) DO UPDATE SET
               last_claim=excluded.last_claim,
               streak=CASE WHEN daily_bonus.last_claim=? THEN daily_bonus.streak+1 ELSE 1 END,
               total_claims=daily_bonus.total_claims+1
               WHERE daily_bonus.last_claim IS NOT ?""",
            (user_id, today, yesterday, today))
        row2 = c.execute("SELECT streak FROM daily_bonus WHERE user_id=?", (user_id,)).fetchone()
        streak = int(row2[0] or 1) if row2 else 1

    # قرعه‌کشی جایزه
    prize = _lottery(DAILY_PRIZES)
    if prize["type"] == "xp":
        bonus_pct = min((streak - 1) * DAILY_STREAK_BONUS_STEP, DAILY_STREAK_BONUS_CAP)
        final_xp = int(prize["value"] * (100 + bonus_pct) / 100)
        users.add_xp(user_id, final_xp, vip_double=False)  # همان ربات: بدون دوبرابر VIP
        result = {"type": "xp", "amount": final_xp, "label": f"{final_xp} XP",
                  "bonus_pct": bonus_pct}
    else:
        vip.extend(user_id, int(prize["value"]))
        result = {"type": "vip", "amount": int(prize["value"]), "label": f"{prize['value']} روز VIP"}

    # جایزهٔ VIP نقاط عطف استریک
    milestone = streak_vip_reward(streak)
    milestone_days = 0
    if milestone > 0:
        try:
            vip.extend(user_id, milestone)
            db.execute("INSERT INTO transactions(user_id, type, amount, days, timestamp) VALUES(?,?,?,?,datetime('now'))",
                       (user_id, "streak_vip", 0, milestone))
            milestone_days = milestone
        except Exception as exc:
            log.error("streak milestone vip error: %s", exc)

    return {"prize": result, "streak": streak, "milestone_vip_days": milestone_days,
            "state": daily_state(user_id), "xp": users.level_info(users.get(user_id).get("xp") or 0)}


# ---------------- کد هدیه ----------------
def gift_codes(user_id: int) -> list[dict]:
    """کدهای هدیهٔ فعال برای این کاربر — همان فیلتر منوی «🎟️ کد هدیه» ربات."""
    out = []
    for r in db.rows("SELECT code, days, max_uses, used_count FROM gift_codes ORDER BY created_at DESC"):
        if int(r["used_count"] or 0) >= int(r["max_uses"] or 0):
            continue
        if db.row("SELECT 1 FROM gift_usage WHERE code=? AND user_id=?", (r["code"], user_id)):
            continue
        out.append({"code": r["code"], "days": int(r["days"] or 0),
                    "remaining": int(r["max_uses"]) - int(r["used_count"] or 0)})
    return out


def redeem_gift(user_id: int, code: str) -> dict:
    """فعال‌سازی کد هدیه — همان redeem_gift ربات (اتمیک، یک‌بار برای هر کاربر)."""
    code = (code or "").strip()
    if not 2 <= len(code) <= 24:
        raise AppError("VALIDATION_ERROR", "کد هدیه معتبر نیست.", 422)
    with db.tx() as c:
        row = c.execute("SELECT * FROM gift_codes WHERE code=?", (code,)).fetchone()
        if not row:
            raise AppError("GIFT_INVALID", "کد نامعتبر است.", 404)
        if row["used_count"] >= row["max_uses"]:
            raise AppError("GIFT_EXHAUSTED", "ظرفیت استفاده از این کد به پایان رسیده.", 409)
        if c.execute("SELECT 1 FROM gift_usage WHERE code=? AND user_id=?", (code, user_id)).fetchone():
            raise AppError("GIFT_ALREADY_USED", "شما قبلاً این کد را استفاده کرده‌اید.", 409)
        c.execute("UPDATE gift_codes SET used_count = used_count + 1 WHERE code=?", (code,))
        c.execute("INSERT INTO gift_usage (code, user_id) VALUES (?,?)", (code, user_id))
        days = int(row["days"] or 0)
    st = vip.extend(user_id, days)
    try:
        db.execute("INSERT INTO transactions(user_id, type, amount, days, timestamp) VALUES(?,?,?,?,datetime('now'))",
                   (user_id, "gift_code", 0, days))
    except Exception:
        pass
    return {"days": days, "vip": st}


# ---------------- استریک / ورود روزانه (همگام‌سازی با ربات) ----------------
def touch_daily(user_id: int) -> dict:
    """اولین فعالیت امروز (UTC مثل ربات): استریک روزانه + XP ورود روزانه.

    وقتی کاربر فقط مینی‌اپ را باز کند هم زنجیرهٔ او مثل پنل شیشه‌ای ادامه می‌یابد."""
    # ۱) استریک — همان update_streak ربات (سپر VIP برای غیبت یک‌روزه)
    today = _utc_today()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    two_ago = (date.today() - timedelta(days=2)).isoformat()
    vip_now = vip.is_active(user_id)
    streak, is_new_day, shield_used = 0, False, False
    with db.tx() as c:
        row = c.execute("SELECT last_streak_date, streak_count FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row:
            last, cur = row[0], int(row[1] or 0)
            if last != today:
                if last == yesterday:
                    streak = cur + 1
                elif last == two_ago and vip_now:
                    streak = cur + 1
                    shield_used = True
                else:
                    streak = 1
                c.execute("UPDATE users SET streak_count=?, last_streak_date=? WHERE user_id=?",
                          (streak, today, user_id))
                is_new_day = True
            else:
                streak = cur
    # ۲) XP ورود روزانه — همان maybe_daily_login_xp ربات (۲ XP)
    login_xp = 0
    with db.tx() as c:
        row = c.execute("SELECT last_active_date FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row and row[0] != today:
            c.execute("UPDATE users SET last_active_date=? WHERE user_id=?", (today, user_id))
            login_xp = 2
    if login_xp:
        users.add_xp(user_id, login_xp, vip_double=False)
    return {"streak": streak, "is_new_day": is_new_day, "shield_used": shield_used, "login_xp": login_xp}
