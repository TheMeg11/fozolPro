"""bot_challenge.py — سیستم «چالش فضول‌گیر برتر» (استخراج‌شده از main.py — v4.7).

همهٔ توابع چالش: وضعیت، پنجرهٔ زمانی، جدول برترین‌ها، جایزه، تسویه و حلقه.
اشیاء ربات از طریق _bind(globals()) تزریق می‌شوند."""
from __future__ import annotations

import datetime
import io
import logging
import threading
import time

import jdatetime

logger = logging.getLogger("bot_challenge")
# ─── اشیاء تزریق‌شده از main.py در زمان import (الگوی bind — کد منتقل‌شده دست‌نخورده) ───
_BIND_KEYS = ['bot', 'db', 'texts', 'types', 'logger', 'ADMIN_ID', 'TEHRAN_TZ', 'to_persian_digits', 'to_persian_int', 'escape_md', 'fmt_amount_toman', '_broadcast_to_all_users', 'get_user_display', 'ApiTelegramException', 'sanitize_name', 'crown_name']


def _bind(ns: dict) -> None:
    """تزریق اشیاء runtime از globals() ربات (bot, db, texts, WHEEL_PRIZES, ...)."""
    for _k in _BIND_KEYS:
        if _k in ns:
            globals()[_k] = ns[_k]


# ====== v3.18: چالش فضول‌گیر برتر ======
def _challenge_now_tehran():
    return datetime.datetime.now(TEHRAN_TZ)

def get_challenge_status():
    return db.get_setting("challenge_status", "") or ""

def _broadcast_to_all_users(text, markup=None):
    """ارسال پیام به همهٔ کاربران واجد شرایط (سازگار با 403)."""
    sent = 0
    for uid in db.get_broadcast_targets():
        try:
            bot.send_message(uid, text, reply_markup=markup)
            sent += 1
        except ApiTelegramException as e:
            if e.error_code == 403:
                try:
                    db.mark_user_blocked_bot(uid)
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(0.05)
    return sent

def _challenge_utcnow():
    """اکنون به UTC — بدون timezone (سازگار با فرمت clicked_at دیتابیس)."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

_CHAL_FMT = "%Y-%m-%d %H:%M:%S"

def _challenge_window():
    """v3.18: خواندن پنجرهٔ شمارش چالش از تنظیمات.
    خروجی: (start_utc_str, end_utc_str) یا None"""
    s = db.get_setting("challenge_start_utc", "") or ""
    e = db.get_setting("challenge_end_utc", "") or ""
    if not s or not e:
        return None
    try:
        datetime.datetime.strptime(s, _CHAL_FMT)
        datetime.datetime.strptime(e, _CHAL_FMT)
        return s, e
    except Exception:
        return None

def _challenge_utc_to_tehran_str(utc_str):
    """نمایش زمان UTC ذخیره‌شده به‌صورت تاریخ/ساعت تهران (فارسی)."""
    try:
        dt = datetime.datetime.strptime(utc_str, _CHAL_FMT)
        tehran = dt + datetime.timedelta(hours=3, minutes=30)  # ایران: UTC+3:30 ثابت
        return to_persian_digits(tehran.strftime("%Y-%m-%d ساعت %H:%M"))
    except Exception:
        return to_persian_digits(utc_str or "نامشخص")

def _challenge_remaining_str():
    """v3.18: زمان باقی‌مانده — scheduled: تا شروع شمارش | active: تا پایان چالش."""
    status = get_challenge_status()
    now_utc = _challenge_utcnow()
    target = None
    if status == "scheduled":
        s = db.get_setting("challenge_start_utc", "") or ""
        try: target = datetime.datetime.strptime(s, _CHAL_FMT)
        except Exception: return "زمان نامشخص"
    elif status == "active":
        e = db.get_setting("challenge_end_utc", "") or ""
        try: target = datetime.datetime.strptime(e, _CHAL_FMT)
        except Exception: return "زمان نامشخص"
    else:
        return "زمان نامشخص"
    total = max(0, int((target - now_utc).total_seconds()))
    h, m = total // 3600, (total % 3600) // 60
    if h > 0:
        return f"{to_persian_digits(h)} ساعت و {to_persian_digits(m)} دقیقه"
    return f"{to_persian_digits(m)} دقیقه"

def _challenge_standings_text(top=3, with_count=False):
    """v3.24.1: جدول زندهٔ برترین‌های چالش جاری (فقط فضول‌های جدید، در بازهٔ شمارش).
    v3.18 → v3.24.1: پیش‌فرض ۳ نفر برتر.
    with_count=False (کاربر): فقط مدال + نام — تعداد در دکمه‌های شیشه‌ای هست
    و سطر فارسی/انگلیسی + عدد ناخوانا می‌شد.
    with_count=True (ادمین): سطر با تعداد فضول.
    v3.24.6: کوئری برترین‌ها از کش ۳۰ ثانیه‌ای (لایهٔ عمومی)."""
    win = _challenge_window()
    if not win:
        return "هنوز شکاری ثبت نشده — اولین نفر باش! 🏁"
    rows = _challenge_cached(("top", win[0], win[1], top),
                             lambda: db.get_top_hunters_window(win[0], win[1], top),
                             ttl=_CHALLENGE_CACHE_TTL_BOARD)
    if not rows:
        return "هنوز هیچ فضولی شکار نشده — اولین نفر باش! 🏁"
    icons = ['🥇', '🥈', '🥉', '🎖️']
    lines = []
    for i, r in enumerate(rows):
        try:
            _r_vip = db.is_vip(r['owner_id'])
        except Exception:
            _r_vip = False
        _row_tmpl = texts.CHALLENGE_STANDINGS_ROW_COUNT if with_count else texts.CHALLENGE_STANDINGS_ROW
        lines.append(_row_tmpl.format(
            icon=icons[i] if i < len(icons) else "•",
            name=crown_name(sanitize_name(r['first_name'] or 'بی‌نام'), _r_vip),
            snoops=to_persian_digits(r['snoops'])))
    return "\n".join(lines)


# ── v3.24.3: کش کوتاه‌مدت نتایج چالش — کوئری رتبه/برترین‌ها هر بار full-scan گروهی
# روی clicks است؛ هر باز شدن منو = چند کوئری سنگین. کش ۵ ثانیه‌ای هم پاسخ‌دهی را
# سریع می‌کند هم قفل دیتابیس را آزادتر نگه می‌دارد.
# v3.24.6: TTL دو-لایه — جدول/پودیوم عمومی ۳۰ ثانیه (کم‌تغییر)، رتبه/امتیاز شخصی
# همان ۵ ثانیه (زنده‌بودن ادراک کاربر). در پیک شب فشار قفل DB نصف می‌شود.
_challenge_cache_lock = threading.Lock()
_challenge_cache = {}  # key -> (timestamp, value)
_CHALLENGE_CACHE_TTL = 5.0
_CHALLENGE_CACHE_TTL_BOARD = 30.0

def _challenge_cached(key, fn, ttl=None):
    _ttl = ttl or _CHALLENGE_CACHE_TTL
    now = time.time()
    with _challenge_cache_lock:
        hit = _challenge_cache.get(key)
        if hit and now - hit[0] < _ttl:
            return hit[1]
    val = fn()
    with _challenge_cache_lock:
        _challenge_cache[key] = (now, val)
        if len(_challenge_cache) > 500:  # پاک‌سازی منقضی‌ها
            expired = [k for k, (t, _) in _challenge_cache.items() if now - t >= _ttl]
            for k in expired:
                _challenge_cache.pop(k, None)
    return val

def _challenge_motivation_text(user_id):
    """v3.24.1: پیام انگیزشی شخصی بر اساس فاصله تا رتبهٔ ۳ (سکوی برنز).
    روی سکو → تشویقِ ماندن | نزدیک سکو → فاصلهٔ دقیق | بدون امتیاز → دعوت به شروع.
    v3.24.6: رتبه/امتیاز از کش ۵ ثانیه‌ای، پودیوم از لایهٔ ۳۰ ثانیه‌ای."""
    win = _challenge_window()
    if not win:
        return ""
    try:
        rank = _challenge_cached(("rank", user_id, win[0], win[1]),
                                 lambda: db.get_challenge_rank(user_id, win[0], win[1]))
        score = _challenge_cached(("score", user_id, win[0], win[1]),
                                  lambda: db.get_challenge_score(user_id, win[0], win[1]))
        if rank and rank <= 3:
            return texts.CHALLENGE_ON_PODIUM
        if not score:
            return texts.CHALLENGE_NO_SCORE_YET
        podium_rows = _challenge_cached(("top3", win[0], win[1]),
                                        lambda: db.get_top_hunters_window(win[0], win[1], 3),
                                        ttl=_CHALLENGE_CACHE_TTL_BOARD)
        if podium_rows and len(podium_rows) >= 3:
            third_score = podium_rows[2]['snoops']
            gap = (third_score or 0) - (score or 0) + 1  # +1: باید از نفر سوم جلو بزند
            if gap <= 3:
                return texts.CHALLENGE_GAP_TO_PODIUM.format(gap=to_persian_digits(gap))
        return ""  # فاصله زیاد — پیام نمی‌دهیم تا ناامید نشود
    except Exception as e:
        logger.error("challenge motivation error: %s", e)
        return ""

def _challenge_start_challenge_preview(hours, prize_days):
    """v3.18: محاسبهٔ پنجرهٔ شمارش بدون ذخیره (برای مرحلهٔ تأیید ادمین).
    خروجی: (start_utc_str, end_utc_str, count_start_fa, end_fa)"""
    now_t = _challenge_now_tehran()
    start_teh = now_t.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
    end_teh = start_teh + datetime.timedelta(hours=int(hours))
    start_utc = start_teh.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    end_utc = end_teh.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    count_start_fa = "فردا ساعت ۰۰:۰۰"
    end_fa = to_persian_digits(end_teh.strftime("%Y-%m-%d ساعت %H:%M"))
    return start_utc.strftime(_CHAL_FMT), end_utc.strftime(_CHAL_FMT), count_start_fa, end_fa

def _challenge_start_challenge(hours, prize_days):
    """v3.18: راه‌اندازی چالش — اعلانِ شروع را جداگانه ارسال می‌کنیم.
    شمارش از ۰۰:۰۰ فردا (تهران) و پایان = شروع + hours ساعت.
    خروجی: (start_utc_str, end_utc_str, count_start_fa, end_fa)"""
    now_t = _challenge_now_tehran()
    start_teh = now_t.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
    end_teh = start_teh + datetime.timedelta(hours=int(hours))
    start_utc = start_teh.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    end_utc = end_teh.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    start_s, end_s = start_utc.strftime(_CHAL_FMT), end_utc.strftime(_CHAL_FMT)
    db.set_setting("challenge_start_utc", start_s)
    db.set_setting("challenge_end_utc", end_s)
    db.set_setting("challenge_hours", int(hours))
    db.set_setting("challenge_reward_days", int(prize_days))
    # v4.6: چالشِ ساخته‌شده از جریان ربات همیشه جایزهٔ VIP دارد — نوع/مبلغ پاکت و متن اعلان قبلی پاک می‌شود
    db.set_setting("challenge_reward_type", "vip")
    db.set_setting("challenge_reward_amount", 0)
    db.set_setting("challenge_announce_text", "")
    db.set_setting("challenge_announce_pending", "0")
    db.set_setting("challenge_date", start_teh.date().isoformat())
    db.set_setting("challenge_status", "scheduled")
    count_start_fa = "فردا ساعت ۰۰:۰۰"
    end_fa = to_persian_digits(end_teh.strftime("%Y-%m-%d ساعت %H:%M"))
    return start_s, end_s, count_start_fa, end_fa

def _challenge_prize_for_rank(rank, reward_days):
    """v3.24.2: جایزهٔ هر رتبه — اول کامل، دوم ۶۰٪، سوم ۳۰٪ (گرد به پایین، حداقل ۱ روز)."""
    if rank == 1:
        return int(reward_days)
    if rank == 2:
        return max(1, int(reward_days * 60 // 100))
    if rank == 3:
        return max(1, int(reward_days * 30 // 100))
    return 0

# ── v4.6: جایزهٔ پاکت (توزیع دستی ادمین پس از پایان چالش) ──
def _challenge_reward_type() -> str:
    """نوع جایزهٔ چالش جاری — «vip» (پیش‌فرض) یا «envelope» (پاکت نقدی)."""
    return (db.get_setting("challenge_reward_type", "") or "vip").strip() or "vip"

def _challenge_envelope_for_rank(rank, amount):
    """سهم پاکت هر رتبه به تومان — اول کامل، دوم ۶۰٪، سوم ۳۰٪ (گرد به پایین)."""
    if rank == 1:
        return int(amount)
    if rank == 2:
        return int(amount * 60 // 100)
    if rank == 3:
        return int(amount * 30 // 100)
    return 0

def _challenge_money_fa(amount):
    """نمایش مبلغ با جداکنندهٔ هزارگان و ارقام فارسی — ۵۰۰٬۰۰۰."""
    return to_persian_digits(f"{int(amount):,}".replace(",", "٬"))

def _challenge_prize_block_text():
    """v4.6: بلوک سه‌خطی «پاداش ها» برای همهٔ اعلان‌ها — vip: روز | envelope: پاکت تومانی.
    مرجع واحد نمایش جوایز؛ هر متنی که جوایز را نشان می‌دهد باید از همین استفاده کند."""
    if _challenge_reward_type() == "envelope":
        a = db.get_setting_int("challenge_reward_amount", 0)
        if a > 0:
            return (" 🥇 پاکت " + _challenge_money_fa(a) + " تومان\n"
                    " 🥈 پاکت " + _challenge_money_fa(_challenge_envelope_for_rank(2, a)) + " تومان\n"
                    " 🥉 پاکت " + _challenge_money_fa(_challenge_envelope_for_rank(3, a)) + " تومان")
        return (" 🥇 پاکت نقدی\n"
                " 🥈 پاکت نقدی\n"
                " 🥉 پاکت نقدی (مبلغ توسط ادمین تعیین می‌شود)")
    rd = db.get_setting_int("challenge_reward_days", 3)
    return (" 🥇 " + to_persian_digits(rd) + " روز VIP\n"
            " 🥈 " + to_persian_digits(_challenge_prize_for_rank(2, rd)) + " روز VIP\n"
            " 🥉 " + to_persian_digits(_challenge_prize_for_rank(3, rd)) + " روز VIP")

def _challenge_prize_dict(reward_days):
    """v3.24.2 → v4.6: دیکشنری جوایز سه رتبه برای format متن‌های ادمین/اعلان — مرجع واحد درصد ۱۰۰/۶۰/۳۰.
    prize_block = بلوک سه‌خطی آماده (vip یا پاکت)؛ first/second/third_prize = نمایش تک‌خطی هر رتبه.
    هر متن جدیدی که جوایز را نمایش می‌دهد باید از همین استفاده کند تا محاسبه همیشه یکجا باشد."""
    rd = int(reward_days)
    if _challenge_reward_type() == "envelope":
        a = db.get_setting_int("challenge_reward_amount", 0)
        if a > 0:
            first = "پاکت " + _challenge_money_fa(a) + " تومان"
            second = "پاکت " + _challenge_money_fa(_challenge_envelope_for_rank(2, a)) + " تومان"
            third = "پاکت " + _challenge_money_fa(_challenge_envelope_for_rank(3, a)) + " تومان"
        else:
            first = second = third = "پاکت نقدی"
    else:
        first = to_persian_digits(rd) + " روز VIP"
        second = to_persian_digits(_challenge_prize_for_rank(2, rd)) + " روز VIP"
        third = to_persian_digits(_challenge_prize_for_rank(3, rd)) + " روز VIP"
    return {
        "reward_days": to_persian_digits(rd),
        "second_days": to_persian_digits(_challenge_prize_for_rank(2, rd)),
        "third_days": to_persian_digits(_challenge_prize_for_rank(3, rd)),
        "first_prize": first,
        "second_prize": second,
        "third_prize": third,
        "prize_block": _challenge_prize_block_text(),
    }

def _challenge_finish_and_settle():
    """v3.18 → v3.24.2 → v4.6: پایان چالش + تسویه.
    جایزهٔ VIP: رتبهٔ ۱ کامل، رتبهٔ ۲ ۶۰٪، رتبهٔ ۳ ۳۰٪ — هم‌امتیازها جایزهٔ همان رتبه را می‌گیرند.
    جایزهٔ پاکت (envelope): هیچ VIP فعال نمی‌شود؛ برندگان اعلام و لیست توزیع دستی برای ادمین فرستاده می‌شود.
    امتیاز صفر جایزه ندارد. خروجی: متن اعلام نتایج (برای اطلاع ادمین)."""
    win = _challenge_window()
    rtype = _challenge_reward_type()
    reward_days = db.get_setting_int("challenge_reward_days", 3)
    reward_amount = db.get_setting_int("challenge_reward_amount", 0)
    if win:
        rows = db.get_top_hunters_window(win[0], win[1], 100)
    else:
        rows = []
    if rows and rows[0]['snoops'] >= 1:
        # رتبه‌گذاری با هم‌امتیاز: هر گروه هم‌امتیاز، رتبهٔ بالاترین عضو گروه را می‌گیرد
        ranked = []  # (rank, row)
        rank = 1
        prev_score = None
        for i, r in enumerate(rows[:25]):  # سقف محاسبه: ۲۵ نفر اول
            score = r['snoops']
            if score < 1:
                break
            if score != prev_score:
                rank = i + 1
                prev_score = score
            if rank > 3:
                break
            ranked.append((rank, r))
        top_score = rows[0]['snoops']
        if rtype == "envelope":
            # ── v4.6: جایزهٔ پاکت — بدون فعال‌سازی خودکار VIP؛ توزیع دستی توسط ادمین ──
            payout = {1: [], 2: [], 3: []}  # (name, user_id, amount)
            for rank, r in ranked:
                amt = _challenge_envelope_for_rank(rank, reward_amount)
                if amt > 0:
                    payout[rank].append((sanitize_name(r['first_name'] or 'بی‌نام'), r['owner_id'], amt))
            names = "، ".join(n for n, _, _ in payout[1]) or "—"
            second_line = ""
            if payout[2]:
                second_line = "\n🥈 نفر دوم: " + "، ".join(n for n, _, _ in payout[2]) + f" — پاکت {_challenge_money_fa(payout[2][0][2])} تومان\n"
            third_line = ""
            if payout[3]:
                third_line = "\n🥉 نفر سوم: " + "، ".join(n for n, _, _ in payout[3]) + f" — پاکت {_challenge_money_fa(payout[3][0][2])} تومان\n"
            announce = texts.CHALLENGE_RESULT_ENVELOPE.format(
                names=names,
                snoops=to_persian_digits(top_score),
                first_prize=("پاکت " + _challenge_money_fa(_challenge_envelope_for_rank(1, reward_amount)) + " تومان"),
                second_line=second_line + ("\n" if second_line else ""),
                third_line=third_line + ("\n" if third_line else ""))
            # پیام تسویهٔ دستی برای ادمین: لیست برندگان با شناسه و مبلغ
            try:
                winner_lines = "\n".join(
                    ("🥇 " if rk == 1 else "🥈 " if rk == 2 else "🥉 ") + f"{nm} (id{to_persian_digits(uid)}) — پاکت {_challenge_money_fa(am)} تومان"
                    for rk, rows_by in payout.items() for (nm, uid, am) in rows_by)
                bot.send_message(ADMIN_ID, texts.ADMIN_CHALLENGE_ENVELOPE_SETTLE.format(winner_lines=winner_lines or "—"))
            except Exception as e:
                logger.error(f"challenge envelope settle DM error: {e}")
        else:
            # اعطای جوایز VIP
            payout_names = {1: [], 2: [], 3: []}
            for rank, r in ranked:
                days = _challenge_prize_for_rank(rank, reward_days)
                if days > 0:
                    try:
                        db.add_vip(r['owner_id'], days)
                    except Exception:
                        pass
                    payout_names[rank].append(sanitize_name(r['first_name'] or 'بی‌نام'))
            names = "، ".join(payout_names[1]) or "—"
            # خطوط جایزهٔ دوم/سوم — فقط وقتی برندهٔ آن رتبه وجود دارد؛ اعداد = همان گردشدهٔ واقعی
            second_line = ""
            if payout_names[2]:
                second_line = "\n🥈 نفر دوم: " + "، ".join(payout_names[2]) + f" — {to_persian_digits(_challenge_prize_for_rank(2, reward_days))} روز VIP\n"
            third_line = ""
            if payout_names[3]:
                third_line = "\n🥉 نفر سوم: " + "، ".join(payout_names[3]) + f" — {to_persian_digits(_challenge_prize_for_rank(3, reward_days))} روز VIP\n"
            announce = texts.CHALLENGE_RESULT.format(
                names=names,
                snoops=to_persian_digits(top_score),
                reward_days=to_persian_digits(reward_days),
                second_line=second_line + ("\n" if second_line else ""),
                third_line=third_line + ("\n" if third_line else ""))
    else:
        announce = texts.CHALLENGE_NO_WINNER
    try:
        _broadcast_to_all_users(announce)
    except Exception as e:
        logger.error(f"challenge result broadcast error: {e}")
    db.set_setting("challenge_status", "finished")
    return announce

def _challenge_tick():
    """v3.18 → v4.6: یک پالس از چرخهٔ حیات چالش:
    اعلان شروع در انتظار → پخش فوری (چالش ساخته‌شده از مینی‌اپ)
    scheduled → (رسیدن به ۰۰:۰۰ فردا) → active + اعلان «شمارش آغاز شد»
    active → (رسیدن به پایان) → finished + تسویهٔ خودکار جایزه + اعلام نتایج."""
    status = get_challenge_status()
    now_s = _challenge_utcnow().strftime(_CHAL_FMT)
    # ── v4.6: اعلان شروعِ در انتظار — چالش‌های ساخته‌شده از پنل مینی‌اپ بلافاصله (در اولین پالس) به همه اعلام می‌شوند ──
    if db.get_setting("challenge_announce_pending", "") == "1":
        db.set_setting("challenge_announce_pending", "0")  # اول پرچم برداشته شود تا در خطا دوباره پخش نشود
        if status == "scheduled":
            custom = (db.get_setting("challenge_announce_text", "") or "").strip()
            if custom:
                announce = custom  # متن ویرایش‌شدهٔ ادمین — عیناً همان ارسال می‌شود
            else:
                announce = texts.CHALLENGE_ANNOUNCE.format(
                    **_challenge_prize_dict(db.get_setting_int("challenge_reward_days", 3)),
                    duration_hours=to_persian_digits(db.get_setting_int("challenge_hours", 24)))
            try:
                threading.Thread(target=_broadcast_to_all_users, args=(announce,), daemon=True).start()
            except Exception as e:
                logger.error(f"challenge start announce error: {e}")
            print("🏆 چالش فضول‌گیر برتر: اعلان شروع برای همه ارسال شد", flush=True)
    if status == "scheduled":
        s = db.get_setting("challenge_start_utc", "") or ""
        if s and now_s >= s:
            db.set_setting("challenge_status", "active")
            reward_days = db.get_setting_int("challenge_reward_days", 3)
            hours = db.get_setting_int("challenge_hours", 24)
            announce = texts.CHALLENGE_COUNT_START.format(
                **_challenge_prize_dict(reward_days),
                duration_hours=to_persian_digits(hours))
            try:
                threading.Thread(target=_broadcast_to_all_users, args=(announce,), daemon=True).start()
            except Exception as e:
                logger.error(f"challenge count-start announce error: {e}")
            print("🏆 چالش فضول‌گیر برتر: شمارش آغاز شد", flush=True)
    elif status == "active":
        e = db.get_setting("challenge_end_utc", "") or ""
        if e and now_s >= e:
            announce = _challenge_finish_and_settle()
            print(f"🏆 چالش فضول‌گیر برتر: پایان یافت ({announce[:40]}...)", flush=True)

def challenge_loop():
    """حلقهٔ چالش — هر ۶۰ ثانیه یک پالس."""
    while True:
        try:
            _challenge_tick()
        except Exception as e:
            logger.error(f"challenge loop error: {e}")
        time.sleep(60)



__all__ = ['_challenge_now_tehran', 'get_challenge_status', '_broadcast_to_all_users', '_challenge_utcnow', '_CHAL_FMT', '_challenge_window', '_challenge_utc_to_tehran_str', '_challenge_remaining_str', '_challenge_standings_text', '_challenge_cache_lock', '_challenge_cache', '_CHALLENGE_CACHE_TTL', '_CHALLENGE_CACHE_TTL_BOARD', '_challenge_cached', '_challenge_motivation_text', '_challenge_start_challenge_preview', '_challenge_start_challenge', '_challenge_prize_for_rank', '_challenge_reward_type', '_challenge_envelope_for_rank', '_challenge_money_fa', '_challenge_prize_block_text', '_challenge_prize_dict', '_challenge_finish_and_settle', '_challenge_tick', 'challenge_loop']
