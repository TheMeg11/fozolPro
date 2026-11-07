"""گردونه شانس روزانه (VIP: فاصلهٔ ۱۲ ساعته = یک چرخش اضافه در روز).
v4.3: پاداش XP برای VIP دوبرابر می‌شود — نتیجه شفاف گزارش می‌شود تا کاربر گیج نشود."""
from __future__ import annotations

import secrets
from datetime import timedelta

from services import bot_settings, db, users, vip
from services.common import AppError, iso, now, parse

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

SEGMENTS = [
    {"label": "۲۰ XP", "color": "#10b981", "type": "xp", "amount": 20, "weight": 22},
    {"label": "پوچ", "color": "#64748b", "type": "none", "amount": 0, "weight": 16},
    {"label": "۵۰ XP", "color": "#3b82f6", "type": "xp", "amount": 50, "weight": 14},
    {"label": "۱ روز VIP", "color": "#e09b12", "type": "vip", "amount": 1, "weight": 4},
    {"label": "۱۰ XP", "color": "#8b5cf6", "type": "xp", "amount": 10, "weight": 22},
    {"label": "پوچ", "color": "#475569", "type": "none", "amount": 0, "weight": 14},
    {"label": "۱۰۰ XP", "color": "#ec4899", "type": "xp", "amount": 100, "weight": 6},
    {"label": "۳ روز VIP", "color": "#f97316", "type": "vip", "amount": 3, "weight": 2},
]
_rng = secrets.SystemRandom()


def _cooldown(user_id: int) -> timedelta:
    return timedelta(hours=12) if vip.is_active(user_id) else timedelta(hours=24)


def state(user_id: int) -> dict:
    if not bot_settings.wheel_enabled():
        return {"can_spin": False, "next_spin_at": None, "disabled": True,
                "segments": [{"label": s["label"], "color": s["color"]} for s in SEGMENTS]}
    last = parse(db.scalar("SELECT last_spin_at FROM users WHERE user_id=?", (user_id,), None))
    nxt = last + _cooldown(user_id) if last else None
    return {"can_spin": not nxt or nxt <= now(), "next_spin_at": iso(nxt) if nxt and nxt > now() else None,
            "segments": [{"label": s["label"], "color": s["color"]} for s in SEGMENTS]}


def spin(user_id: int) -> dict:
    cd = _cooldown(user_id)
    with db.tx() as c:  # چک و ثبت اتمیک تا دوبار چرخاندن هم‌زمان ممکن نباشد
        last = parse(c.execute("SELECT last_spin_at FROM users WHERE user_id=?", (user_id,)).fetchone()[0])
        if last and last + cd > now():
            raise AppError("COOLDOWN", "امروز گردونه را چرخانده‌اید. بعداً دوباره سر بزنید!", 429, {"next_spin_at": iso(last + cd)})
        c.execute("UPDATE users SET last_spin_at=? WHERE user_id=?", (iso(), user_id))
    idx = _rng.choices(range(len(SEGMENTS)), weights=[s["weight"] for s in SEGMENTS])[0]
    seg = SEGMENTS[idx]
    label = "پوچ! شانس دفعهٔ بعد 😅"
    doubled = False
    if seg["type"] == "xp":
        base = seg["amount"]
        before = users.get(user_id).get("xp") or 0
        info = users.add_xp(user_id, base)  # add_xp برای VIP دوبرابر اعمال می‌کند
        gained = info["xp"] - before
        doubled = gained > base
        if doubled:
            label = f"{str(gained).translate(_FA_DIGITS)} امتیاز XP — پاداش دوبرابر VIP 👑 (۲×{str(base).translate(_FA_DIGITS)})"
        else:
            label = f"{str(gained).translate(_FA_DIGITS)} امتیاز XP"
    elif seg["type"] == "vip":
        vip.extend(user_id, seg["amount"])
        label = f"{str(seg['amount']).translate(_FA_DIGITS)} روز اشتراک VIP"
    db.execute("INSERT INTO wheel_spins(user_id, prize_type, amount, created_at) VALUES(?,?,?,?)", (user_id, seg["type"], seg["amount"], iso()))
    return {"index": idx, "prize": {"type": seg["type"], "amount": seg["amount"], "label": label,
                                    "vip_doubled": doubled},
            "next_spin_at": iso(now() + _cooldown(user_id)), "xp": users.level_info(users.get(user_id).get("xp") or 0)}
