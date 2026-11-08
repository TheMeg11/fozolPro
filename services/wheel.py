"""گردونه شانس روزانه — v4.7: هم‌گام کامل با پنل شیشه‌ای ربات.

- فقط برای اعضای VIP (مثل wheel_spin ربات که «⛔ فقط برای اعضای VIP!» می‌دهد).
- جوایز و وزن‌ها دقیقاً همان WHEEL_PRIZES ربات (۲۰/۵۰/۱۰۰/۲۵۰/۵۰۰/۱۰۰۰ XP + ۱/۳ روز VIP).
- یک چرخش در روز، رزرو اتمیک روی همان ستون last_wheel_date ربات (به وقت تهران) —
  قبلاً مینی‌اپ ستون جداگانهٔ last_spin_at با کول‌داون متفاوت داشت و کاربر VIP
  می‌توانست همان روز هم در ربات و هم در مینی‌اپ بچرخاند.
- اعطای XP بدون دوبرابر شدن VIP — همان award_xp_with_level_up_notify ربات.
"""
from __future__ import annotations

import secrets
from datetime import timedelta

from services import bot_settings, db, users, vip
from services.common import AppError, TEHRAN, iso, now

# ====== جوایز — همان WHEEL_PRIZES ربات ======
SEGMENTS = [
    {"label": "۲۰ XP", "color": "#10b981", "type": "xp", "amount": 20, "weight": 28},
    {"label": "۵۰ XP", "color": "#3b82f6", "type": "xp", "amount": 50, "weight": 24},
    {"label": "۱۰۰ XP", "color": "#ec4899", "type": "xp", "amount": 100, "weight": 19},
    {"label": "۲۵۰ XP", "color": "#8b5cf6", "type": "xp", "amount": 250, "weight": 13},
    {"label": "۵۰۰ XP", "color": "#f97316", "type": "xp", "amount": 500, "weight": 8},
    {"label": "۱٬۰۰۰ XP", "color": "#eab308", "type": "xp", "amount": 1000, "weight": 4},
    {"label": "۱ روز VIP", "color": "#e09b12", "type": "vip", "amount": 1, "weight": 3},
    {"label": "۳ روز VIP", "color": "#ef4444", "type": "vip", "amount": 3, "weight": 1},
]
_rng = secrets.SystemRandom()


def _today_tehran() -> str:
    return now().astimezone(TEHRAN).date().isoformat()


def state(user_id: int) -> dict:
    vip_active = vip.is_active(user_id)
    segments = [{"label": s["label"], "color": s["color"]} for s in SEGMENTS]
    if not bot_settings.wheel_enabled():
        return {"can_spin": False, "next_spin_at": None, "disabled": True, "vip_required": False,
                "segments": segments}
    # v4.7: همان شاخص روزانهٔ ربات (last_wheel_date به وقت تهران)
    last = db.scalar("SELECT last_wheel_date FROM users WHERE user_id=?", (user_id,), None)
    done = bool(last and str(last)[:10] == _today_tehran())
    # فردا ۰۰:۰۰ تهران = لحظهٔ باز شدن چرخش بعدی
    t = now().astimezone(TEHRAN)
    nxt = (t.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))
    return {"can_spin": (not done) and vip_active, "next_spin_at": iso(nxt) if done else None,
            "done_today": done, "vip_required": not vip_active, "disabled": False,
            "segments": segments}


def spin(user_id: int) -> dict:
    if not bot_settings.wheel_enabled():
        raise AppError("FORBIDDEN", "گردونه شانس فعلاً غیرفعال است.", 403)
    # v4.7: چرخ شانس ویژهٔ VIP — همان gate ربات
    if not vip.is_active(user_id):
        raise AppError("VIP_REQUIRED", "چرخ شانس فقط برای اعضای VIP است!", 403,
                       {"upsell": True})
    today = _today_tehran()
    with db.tx() as c:  # رزرو اتمیک — همان claim_wheel_date_atomic ربات
        row = c.execute("SELECT last_wheel_date FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row and str(row[0] or "")[:10] == today:
            raise AppError("COOLDOWN", "فرصت امروزت تمام شده — فردا بیا!", 429)
        if row:
            c.execute("UPDATE users SET last_wheel_date=? WHERE user_id=?", (today, user_id))
        else:
            c.execute("INSERT INTO users (user_id, last_wheel_date) VALUES (?,?) "
                      "ON CONFLICT(user_id) DO UPDATE SET last_wheel_date=excluded.last_wheel_date",
                      (user_id, today))
    idx = _rng.choices(range(len(SEGMENTS)), weights=[s["weight"] for s in SEGMENTS])[0]
    seg = SEGMENTS[idx]
    label = ""
    if seg["type"] == "xp":
        # همان ربات: مقدار ثابت جایزه (بدون دوبرابر شدن VIP)
        users.add_xp(user_id, seg["amount"], vip_double=False)
        label = f"{seg['amount']} امتیاز XP"
    elif seg["type"] == "vip":
        vip.extend(user_id, seg["amount"])
        label = f"{seg['amount']} روز اشتراک VIP"
    db.execute("INSERT INTO wheel_spins(user_id, prize_type, amount, created_at) VALUES(?,?,?,?)",
               (user_id, seg["type"], seg["amount"], iso()))
    t = now().astimezone(TEHRAN)
    nxt = (t.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))
    return {"index": idx, "prize": {"type": seg["type"], "amount": seg["amount"], "label": label,
                                    "vip_doubled": False},
            "next_spin_at": iso(nxt),
            "xp": users.level_info(users.get(user_id).get("xp") or 0)}
