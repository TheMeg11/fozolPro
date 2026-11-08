"""پروفایل کاربر در مینی‌اپ — نام نمایشی، لقب کارآگاهی و ویترین نشان‌ها.

v4.4: «لقب‌ها و نشان‌ها» از ربات به مینی‌اپ می‌آیند:
- لقب‌ها (LEVEL_NAMES ربات) با پیشرفت سطح باز می‌شوند و کاربر یکی را به‌عنوان
  لقب فعال برای نمایش به همه انتخاب می‌کند.
- نام نمایشی (users.display_name — همان ستون منوی شیشه‌ای ربات) آزادانه قابل
  تغییر است؛ در گزارش فضول‌گیری، لیدربورد ربات و مینی‌اپ نمایش داده می‌شود.
- نشان‌ها از دادهٔ واقعی کاربر محاسبه می‌شوند (بدون جدول اضافه).
"""
from __future__ import annotations

from services import db, vip
from services.common import AppError, display_name

# دقیقاً همان جدول لقب‌های ربات (main.py: texts.LEVEL_NAMES)
try:
    import texts as _bot_texts
    LEVEL_NAMES: dict[int, tuple[str, str]] = dict(_bot_texts.LEVEL_NAMES)
except Exception:  # pragma: no cover — اجرای مستقل
    LEVEL_NAMES = {
        1: ("فضول تازه‌وارد", "🐣"), 3: ("کنجکاو سیری‌ناپذیر", "👀"),
        10: ("فضول حرفه‌ای", "🎩"), 25: ("سرفضول", "🎖️"),
        50: ("استاد فضول‌ها", "🎓"), 100: ("پادشاه فضول‌ها", "👑"),
    }

_NAME_MIN, _NAME_MAX = 2, 32


def _level_of(uid: int) -> int:
    xp = db.scalar("SELECT COALESCE(xp,0) FROM users WHERE user_id=?", (uid,), 0)
    lvl = 1
    while 100 * (lvl + 1) * (lvl + 2) // 2 <= xp:
        lvl += 1
    return lvl


def _content_error(text: str) -> str | None:
    """همان فیلتر سبک محتوای چت ناشناس (لینک/آیدی خارجی + واژه‌های نامناسب)."""
    try:
        from services import anon as _anon
        return _anon._content_error(text)
    except Exception:
        return None


def _auto_title_key(lvl: int) -> int:
    """نزدیک‌ترین لقب بازِ پایین‌تر — دقیقاً منطق get_level_title ربات."""
    chosen = min(LEVEL_NAMES.keys())
    for k in sorted(LEVEL_NAMES.keys()):
        if k <= lvl:
            chosen = k
        else:
            break
    return chosen


def titles_view(uid: int) -> list[dict]:
    """همهٔ لقب‌ها با وضعیت باز/قفل — لقب فعلی (خودکار یا انتخابی) مشخص است."""
    lvl = _level_of(uid)
    active = db.scalar("SELECT active_title FROM users WHERE user_id=?", (uid,), None)
    custom_key = active if (active is not None and active in LEVEL_NAMES and lvl >= active) else None
    auto_key = _auto_title_key(lvl)
    out = []
    for key in sorted(LEVEL_NAMES.keys()):
        title, emoji = LEVEL_NAMES[key]
        out.append({
            "key": key, "title": title, "emoji": emoji,
            "unlocked": lvl >= key,
            "active": (key == custom_key) if custom_key is not None else (key == auto_key),
        })
    return out


def current_title(uid: int) -> dict:
    """لقب نمایشی فعلی: انتخاب کاربر (اگر باز باشد) وگرنه لقب خودکار سطح."""
    lvl = _level_of(uid)
    active = db.scalar("SELECT active_title FROM users WHERE user_id=?", (uid,), None)
    if active is not None and active in LEVEL_NAMES and lvl >= active:
        title, emoji = LEVEL_NAMES[active]
        return {"key": active, "title": title, "emoji": emoji, "custom": True}
    key = _auto_title_key(lvl)
    title, emoji = LEVEL_NAMES[key]
    return {"key": key, "title": title, "emoji": emoji, "custom": False}


def badges_view(uid: int) -> list[dict]:
    """ویترین نشان‌ها — همه از دادهٔ واقعی کاربر محاسبه می‌شود."""
    snoops = db.scalar("SELECT COUNT(DISTINCT clicker_id) FROM clicks WHERE owner_id=?", (uid,), 0)
    invites = db.scalar("SELECT COUNT(DISTINCT clicker_id) FROM clicks WHERE owner_id=? AND is_new_user=1", (uid,), 0)
    spins = db.scalar("SELECT COUNT(*) FROM wheel_spins WHERE user_id=?", (uid,), 0)
    streak = db.scalar("SELECT COALESCE(streak_count,0) FROM users WHERE user_id=?", (uid,), 0)
    has_mask = bool(db.row("SELECT 1 FROM user_mask WHERE user_id=? AND (emoji IS NOT NULL OR mask_text IS NOT NULL)", (uid,)))
    is_vip = vip.is_active(uid)

    def badge(key, emoji, title, desc, got, goal=None):
        d = {"key": key, "emoji": emoji, "title": title, "desc": desc, "earned": bool(got)}
        if goal is not None and not got:
            d["goal"] = goal
        return d

    return [
        badge("first_snoop", "🔍", "اولین شکار", "اولین فضولی که در دامت افتاد", snoops >= 1),
        badge("snoop_25", "🎯", "شکارچی ۲۵", "۲۵ فضول یکتا در تله‌هایت", snoops >= 25, goal=25),
        badge("snoop_100", "🏹", "شکارچی ۱۰۰", "۱۰۰ فضول یکتا — افسانهٔ فضول‌یابی", snoops >= 100, goal=100),
        badge("inviter", "🤝", "دعوت‌کننده", "حداقل یک کاربر جدید با لینک تو وارد ربات شد", invites >= 1),
        badge("streak_7", "🔥", "زنجیرهٔ آتشین", "استریک ۷ روزهٔ پیاپی", streak >= 7, goal=7),
        badge("spinner", "🎰", "چرخان", "۱۰ بار چرخ شانس", spins >= 10, goal=10),
        badge("masked", "🎭", "نقاب‌دار", "نقاب کارآگاهی اختصاصی ساخت", has_mask),
        badge("vip", "👑", "کارت طلایی", "عضو حلقهٔ ویژهٔ کارآگاهان", is_vip),
    ]


def view(uid: int) -> dict:
    u = db.row("SELECT * FROM users WHERE user_id=?", (uid,)) or {}
    return {
        "display_name": u.get("display_name") or None,
        "account_name": display_name(u),
        "title": current_title(uid),
        "titles": titles_view(uid),
        "badges": badges_view(uid),
    }


def update(uid: int, display_name_str: str | None = None, active_title: int | None = None,
           reset_name: bool = False, reset_title: bool = False) -> dict:
    """ویرایش آزاد نام نمایشی + انتخاب لقب (فقط از لقب‌های بازشده)."""
    if reset_name:
        db.execute("UPDATE users SET display_name=NULL WHERE user_id=?", (uid,))
    elif display_name_str is not None:
        name = display_name_str.strip()
        if not (_NAME_MIN <= len(name) <= _NAME_MAX):
            raise AppError("VALIDATION_ERROR", f"نام باید بین {_NAME_MIN} تا {_NAME_MAX} کاراکتر باشد.", 422)
        bad = _content_error(name)
        if bad:
            raise AppError("VALIDATION_ERROR", f"این نام قابل قبول نیست ({bad}).", 422)
        db.execute("UPDATE users SET display_name=? WHERE user_id=?", (name, uid))

    if reset_title:
        db.execute("UPDATE users SET active_title=NULL WHERE user_id=?", (uid,))
    elif active_title is not None:
        if active_title not in LEVEL_NAMES:
            raise AppError("VALIDATION_ERROR", "این لقب وجود ندارد.", 422)
        lvl = _level_of(uid)
        if lvl < active_title:
            title, _ = LEVEL_NAMES[active_title]
            raise AppError("VALIDATION_ERROR", f"لقب «{title}» هنوز قفل است — با سطح {active_title} باز می‌شود.", 403)
        db.execute("UPDATE users SET active_title=? WHERE user_id=?", (active_title, uid))

    return view(uid)
