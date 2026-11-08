"""ماموریت‌ها (تسک‌های ۲۰۰تایی) برای مینی‌اپ — دقیقاً همان منطق پنل شیشه‌ای ربات.

منبع داده: `tasks.py` (فایل خالص ربات — بدون وابستگی به main.py). توابع `check`
هر تسک روی شیء db ربات نوشته شده‌اند؛ اینجا با `_TaskDB` همان متدها روی
`services.db` پیاده می‌شوند تا بدون import ربات هم کار کند.

انتخاب ۳ ماموریت ویژهٔ روز: seed = f"{user_id}:{today_iso}:{page}" — همان
فرمول show_tasks_page در main.py؛ در نتیجه مینی‌اپ همیشه همان ماموریت‌هایی را
نشان می‌دهد که پنل شیشه‌ای برای همان روز نشان می‌دهد.
"""
from __future__ import annotations

import random

import tasks as tasks_module
from services import db, users
from services.common import TEHRAN

log = __import__("logging").getLogger("missions")

# دسته‌بندی و ترتیب نمایش — همان cat_order ربات
CATEGORY_ORDER = {"easy": 0, "medium": 1, "hard": 2}
CATEGORY_INFO = {
    "easy": {"emoji": "🟢", "title": "آسان"},
    "medium": {"emoji": "🟡", "title": "متوسط"},
    "hard": {"emoji": "🔴", "title": "سخت"},
}


# ---------------- پل دیتابیس برای توابع check ربات ----------------
class _Conn:
    """شبیه‌سازی db.conn ربات برای لامبداهای tasks.py که SQL مستقیم می‌زنند."""

    @staticmethod
    def execute(sql, params=()):
        return db.conn().execute(sql, params)


class _TaskDB:
    """متدهایی از Database ربات که توابع check تسک‌ها صدا می‌زنند — روی services.db."""

    conn = _Conn()

    # --- شمارنده‌ها ---
    @staticmethod
    def get_clicks_count(owner_id):
        return int(db.scalar("SELECT COUNT(*) FROM clicks WHERE owner_id=?", (owner_id,), 0))

    @staticmethod
    def get_distinct_snoop_count(user_id):
        return int(db.scalar("SELECT COUNT(DISTINCT clicker_id) FROM clicks WHERE owner_id=?", (user_id,), 0))

    @staticmethod
    def get_user_purchase_count(user_id):
        return int(db.scalar("SELECT COUNT(*) FROM transactions WHERE user_id=? AND type='vip'", (user_id,), 0))

    @staticmethod
    def get_user_gift_count(user_id):
        return int(db.scalar("SELECT COUNT(*) FROM transactions WHERE user_id=? AND type='gift_vip'", (user_id,), 0))

    # --- تنظیمات VIP (ستون‌های users) ---
    @staticmethod
    def get_welcome_text(user_id):
        return db.scalar("SELECT welcome_text FROM users WHERE user_id=?", (user_id,), None)

    @staticmethod
    def get_welcome_photo(user_id):
        return db.scalar("SELECT welcome_photo FROM users WHERE user_id=?", (user_id,), None)

    @staticmethod
    def get_user_mask(user_id):
        return db.row("SELECT emoji, mask_text FROM user_mask WHERE user_id=?", (user_id,))

    # --- پاداش‌های یکباره ---
    @staticmethod
    def has_bonus(user_id, bonus_type):
        return db.row("SELECT 1 FROM xp_bonuses WHERE user_id=? AND bonus_type=?", (user_id, bonus_type)) is not None


_BRIDGE = _TaskDB()


# ---------------- منطق مشترک با show_tasks_page ربات ----------------
def _task_done(user_id: int, task: dict) -> bool:
    if _BRIDGE.has_bonus(user_id, f"task_{task['id']}"):
        return True
    try:
        return bool(task["check"](_BRIDGE, user_id))
    except Exception as exc:  # جدول نبود/خطای گذرا — مثل ربات: انجام‌نشده
        log.debug("task check %s failed: %s", task["id"], exc)
        return False


def _remaining_tasks(user_id: int) -> tuple[list[dict], int, int]:
    """تسک‌های قابل نمایش + تعداد انجام‌شده — همان الگوریتم milestone ربات."""
    all_tasks = tasks_module.TASKS
    total = len(all_tasks)
    task_status: dict[str, bool] = {}
    done_count = 0
    for t in all_tasks:
        is_done = _task_done(user_id, t)
        task_status[t["id"]] = is_done
        if is_done:
            done_count += 1

    groups_done_threshold: dict[str, int] = {}
    for t in all_tasks:
        grp = t.get("group")
        if grp and task_status.get(t["id"]):
            thr = int(t.get("threshold") or 0)
            if thr > groups_done_threshold.get(grp, 0):
                groups_done_threshold[grp] = thr

    remaining, groups_added = [], set()
    for t in all_tasks:
        if task_status.get(t["id"]):
            continue
        grp = t.get("group")
        if grp:
            thr = int(t.get("threshold") or 0)
            if thr <= groups_done_threshold.get(grp, 0):
                continue
            if grp in groups_added:
                continue
            groups_added.add(grp)
        remaining.append(t)
    return remaining, done_count, total


def progress_value(user_id: int, task: dict) -> int | None:
    """مقدار فعلی متریک گروه — همان نگاشت _task_progress_value ربات."""
    grp = task.get("group")
    if not grp or "threshold" not in task:
        return None
    try:
        if grp == "click_count":
            return _BRIDGE.get_clicks_count(user_id)
        if grp == "snoop_count":
            return _BRIDGE.get_distinct_snoop_count(user_id)
        if grp == "nickname_count":
            return int(db.scalar("SELECT COUNT(*) FROM nicknames WHERE owner_id=?", (user_id,), 0))
        if grp == "anon_sent":
            return int(db.scalar("SELECT COUNT(*) FROM anon_logs WHERE sender_id=?", (user_id,), 0))
        if grp == "anon_received":
            return int(db.scalar("SELECT COUNT(*) FROM anon_logs WHERE receiver_id=?", (user_id,), 0))
        if grp == "mute_count":
            return int(db.scalar("SELECT COUNT(*) FROM muted_snoops WHERE owner_id=?", (user_id,), 0))
        if grp == "block_count":
            return int(db.scalar("SELECT COUNT(*) FROM blocked_anon WHERE blocker_id=?", (user_id,), 0))
        if grp == "gift_used":
            return int(db.scalar("SELECT COUNT(*) FROM gift_usage WHERE user_id=?", (user_id,), 0))
        if grp == "vip_purchase":
            return int(db.scalar("SELECT COUNT(*) FROM transactions WHERE user_id=? AND type='vip'", (user_id,), 0))
        if grp == "vip_gift":
            return _BRIDGE.get_user_gift_count(user_id)
        if grp == "days_active":
            return int(db.scalar(
                "SELECT COALESCE(julianday('now') - julianday(created_at), 0) FROM users WHERE user_id=?",
                (user_id,), 0))
    except Exception:
        return None
    return None


def _task_view(user_id: int, task: dict) -> dict:
    prog = progress_value(user_id, task)
    thr = task.get("threshold")
    return {
        "id": task["id"], "name": task["name"], "desc": task.get("desc") or "",
        "xp": task["xp"], "category": task["category"],
        "category_info": CATEGORY_INFO.get(task["category"], {"emoji": "🎯", "title": "ماموریت"}),
        "progress": (None if prog is None or not thr else
                     {"value": min(int(prog), int(thr)), "threshold": int(thr),
                      "pct": min(100, round(int(prog) * 100 / max(1, int(thr))))}),
    }


def page(user_id: int, page_num: int = 1) -> dict:
    """صفحهٔ ماموریت‌های ویژهٔ امروز — همان انتخاب رندم seeded ربات."""
    page_num = max(1, int(page_num or 1))
    award_pending(user_id, notify=False)  # همگام‌سازی بی‌صنا مثل بازکردن صفحه در ربات
    remaining, done_count, total = _remaining_tasks(user_id)
    today_iso = _now_tehran().isoformat()
    rng = random.Random(f"{user_id}:{today_iso}:{page_num}")
    if len(remaining) <= 3:
        page_tasks = list(remaining)
    else:
        page_tasks = rng.sample(remaining, 3)
        page_tasks.sort(key=lambda t: (CATEGORY_ORDER.get(t["category"], 9), t.get("threshold", 0), t["xp"]))
    pct = int(done_count * 100 / total) if total else 0
    return {
        "page": page_num,
        "tasks": [_task_view(user_id, t) for t in page_tasks],
        "total_remaining": len(remaining),
        "progress": {"done": done_count, "total": total, "pct": pct},
    }


def detail(user_id: int, task_id: str) -> dict | None:
    task = tasks_module.get_task_by_id(task_id)
    if not task:
        return None
    award_pending(user_id, notify=False)
    view = _task_view(user_id, task)
    view["done"] = _task_done(user_id, task)
    return view


def _now_tehran():
    from services.common import now
    return now().astimezone(TEHRAN).date()


# ---------------- اعطای XP تسک‌های تازه تکمیل‌شده (همان _check_and_award_tasks_xp) ----------------
def award_pending(user_id: int, notify: bool = False) -> list[dict]:
    """تسک‌های تازه انجام‌شده را بی‌صدا XP می‌دهد (مثل ربات). برمی‌گرداند لیست تسک‌های تازه.

    notify=True → پیام خلاصهٔ تکمیل از طریق بله برای کاربر ارسال می‌شود
    (معادل اسکنر زمان واقعی ربات؛ از مینی‌اپ استفاده نمی‌شود تا اسپم نشود)."""
    from services import vip as vip_svc

    newly: list[dict] = []
    for task in tasks_module.TASKS:
        task_id = task["id"]
        if _BRIDGE.has_bonus(user_id, f"task_{task_id}"):
            continue
        try:
            if not bool(task["check"](_BRIDGE, user_id)):
                continue
        except Exception:
            continue
        # اعطای اتمیک یکباره — همان award_bonus_xp ربات (بدون دوبرابر شدن VIP)
        with db.tx() as c:
            existing = c.execute("SELECT 1 FROM xp_bonuses WHERE user_id=? AND bonus_type=?",
                                 (user_id, f"task_{task_id}")).fetchone()
            if existing:
                continue  # قبلاً توسط ربات ثبت شده
            c.execute("INSERT INTO xp_bonuses (user_id, bonus_type) VALUES (?,?)",
                      (user_id, f"task_{task_id}"))
        info = users.add_xp(user_id, int(task["xp"]), vip_double=False)
        if task.get("vip_reward"):
            try:
                vip_svc.extend(user_id, int(task["vip_reward"]))
                db.execute("INSERT INTO transactions(user_id, type, amount, days, timestamp) VALUES(?,?,?,?,?)",
                           (user_id, "challenge_vip", 0, int(task["vip_reward"]), _utc_now_str()))
            except Exception as exc:
                log.error("vip challenge grant %s: %s", task_id, exc)
        newly.append({**_task_view(user_id, task), "xp": task["xp"], "level": info.get("level")})
    if notify and newly:
        _notify_completion(user_id, newly)
    return newly


def _utc_now_str() -> str:
    from services.common import now
    return now().strftime("%Y-%m-%d %H:%M:%S")


def _notify_completion(user_id: int, newly: list[dict]) -> None:
    """اعلان تکمیل ماموریت در چت بله — متن همان اسکنر ربات."""
    try:
        from services import bale_api

        if len(newly) == 1:
            t = newly[0]
            text = ("🎉 *ماموریت تکمیل شد!*\n\n"
                    f"🎯 *{t['name']}*\n"
                    f"⭐ +{t['xp']} XP")
        else:
            lines = [f"🎉 *{len(newly)} ماموریت تکمیل شد!*\n"]
            for t in newly[:10]:
                lines.append(f"• {t['name']} (+{t['xp']} XP)")
            if len(newly) > 10:
                lines.append(f"• و {len(newly) - 10} ماموریت دیگر...")
            text = "\n".join(lines)
        bale_api.send_message(user_id, text)
    except Exception as exc:
        log.debug("task completion notify skipped: %s", exc)
