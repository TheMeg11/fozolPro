"""چت ناشناس مینی‌اپ — هم‌ساز با پیام‌های ناشناس ربات (جدول anon_logs).

قواعد (عیناً مثل ربات):
- ارسال فقط به «فضول‌های تلهٔ خودم» یا «طرفِ گفتگوی ناشناس موجود» (ضد تماس سرد).
- محدودیت: VIP = ۱۰ پیام در دقیقه؛ کاربر عادی = ۱ پیام در ۲۴ ساعت (rolling).
- بلاک ناشناس (blocked_anon) رعایت می‌شود.
- فیلتر لینک خارجی + واژه‌های نامناسب (نسخهٔ سبک همان فیلتر ربات).

حریم خصوصی (مهم):
- اگر طرف مقابل «فضولِ من» بوده (در clicks با owner=من) → نامش طبق قانون VIP نمایش
  داده می‌شود (VIP: کامل + عکس؛ عادی: ماسک‌شده).
- در غیر این صورت (او شروع‌کنندهٔ گفتگو بوده) → «کاربر ناشناس» با شمارهٔ ثابت گفتگو.
- شناسهٔ عددی/یوزرنیم طرف مقابل هرگز به کلاینت نمی‌رود — فقط یک token داخلی.
- آمار/آرشیو کامل فقط برای ادمین (همان چیزی که قبلاً به PV ادمین می‌رفت).
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from collections import defaultdict, deque

import settings
from services import avatars, bale_api, db, legacy_bridge, users, vip
from services.common import AppError, display_name, iso, mask_name, now, parse

log = logging.getLogger("anon")

# ---- فیلتر محتوا (سبک؛ هم‌راستا با ربات) ----
_LINK_RE = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/|telegram\.dog/|ble\.ir/)", re.I)
_MENTION_RE = re.compile(r"@[\w_]{5,}")
PROFANITY_WORDS = (
    "کسده کصده کیر کون جنده کونی خارکسه بی‌عفت بی عفت احمق ابله عوضی گوه گایده شلفت "
    "ممه بی‌شرف بی شرف fuck shit bitch asshole dick pussy cunt "
    "خارکصده خواهرکصده مادرکصده ناموس لاشی دیوث دایوث کونده ساکزن جکشه جاکش کسکش حرومزاده حرامی "
    "تخم سگ پدرسگ دودول بیضه خایه ساک پورن سکسی جلق بگایی گاییدم میگام اسکل اوسکل پلشت لاشخور "
    "بیشعور بی شعور نفهم وحشی الاغ"
).split()


def _content_error(text: str) -> str | None:
    if _LINK_RE.search(text) or _MENTION_RE.search(text):
        return "لینک یا آیدی خارجی"
    low = re.sub(r"\s+", " ", text.lower()).strip()
    for w in PROFANITY_WORDS:
        if w in low:
            return "محتوای نامناسب"
    return None


# ---- rate limit در حافظه (VIP) ----
_vip_rate: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=20))
_rl_lock = threading.Lock()


def _vip_can_send(sender: int, receiver: int) -> bool:
    now_t = time.time()
    key = (sender, receiver)
    with _rl_lock:
        q = _vip_rate[key]
        while q and q[0] < now_t - 60:
            q.popleft()
        return len(q) < 10


def _vip_reg(sender: int, receiver: int) -> None:
    with _rl_lock:
        _vip_rate[(sender, receiver)].append(time.time())


def _normal_can_send(sender: int) -> bool:
    last = db.scalar("SELECT timestamp FROM anon_logs WHERE sender_id=? ORDER BY id DESC LIMIT 1", (sender,), None)
    if not last:
        return True
    ts = parse(str(last))
    return (not ts) or (now() - ts).total_seconds() >= 86400


# ---- رابطه‌ها ----
def _is_my_snoop(owner: int, clicker: int) -> bool:
    return bool(db.row("SELECT 1 FROM clicks WHERE owner_id=? AND clicker_id=? LIMIT 1", (owner, clicker)))


def _has_thread(a: int, b: int) -> bool:
    return bool(db.row("SELECT 1 FROM anon_logs WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?) LIMIT 1", (a, b, b, a)))


def _can_contact(sender: int, target: int) -> bool:
    if sender == target:
        return False
    return _is_my_snoop(sender, target) or _has_thread(sender, target)


def _anon_blocked(blocker: int, blocked: int) -> bool:
    return bool(db.row("SELECT 1 FROM blocked_anon WHERE blocker_id=? AND blocked_id=?", (blocker, blocked)))


# ---- برچسب طرف گفتگو (با حریم خصوصی) ----
def _partner_view(me_id: int, partner_id: int, seq: int) -> dict:
    """طرف گفتگو از نگاه من. فقط اگر «فضولِ من» باشد نامش دیده می‌شود (طبق قانون VIP)."""
    if _is_my_snoop(me_id, partner_id):
        if vip.is_active(me_id):
            r = db.row("SELECT first_name, last_name, username FROM users WHERE user_id=?", (partner_id,)) or {}
            name = display_name(r) if (r.get("first_name") or r.get("last_name")) else None
            if not name:  # در جدول users نیست — از clicks بخوان
                c = db.row("SELECT clicker_name FROM clicks WHERE owner_id=? AND clicker_id=? ORDER BY id DESC LIMIT 1", (me_id, partner_id)) or {}
                name = c.get("clicker_name") or None
            return {"known": True, "masked": False, "name": name or "کاربر بله", "avatar": avatars.url_for(partner_id), "token": _token(me_id, partner_id)}
        c = db.row("SELECT clicker_name FROM clicks WHERE owner_id=? AND clicker_id=? ORDER BY id DESC LIMIT 1", (me_id, partner_id)) or {}
        raw = c.get("clicker_name") or "کاربر بله"
        return {"known": True, "masked": True, "name": mask_name(raw), "avatar": None, "token": _token(me_id, partner_id)}
    return {"known": False, "masked": True, "name": f"کاربر ناشناس {seq or 1}", "avatar": None, "token": _token(me_id, partner_id)}


def _token(me_id: int, partner_id: int) -> str:
    """توکن غیرقابل‌گم‌شدن برای کلاینت (بدون افشای شناسهٔ عددی طرف)."""
    return hashlib.sha256(f"anon:{settings.BOT_TOKEN or 'fozol-anon'}:{me_id}:{partner_id}".encode()).hexdigest()[:16]


def _partner_by_token(me_id: int, token: str) -> int | None:
    """برگرداندن شناسهٔ طرف گفتگو از توکن — فقط اگر واقعاً گفتگو/رابطه وجود داشته باشد."""
    r = db.rows("""SELECT DISTINCT CASE WHEN sender_id=? THEN receiver_id ELSE sender_id END AS p
                   FROM anon_logs WHERE sender_id=? OR receiver_id=? LIMIT 200""", (me_id, me_id, me_id))
    for row in r + [{"p": x} for x in _snoop_ids(me_id)]:
        p = row["p"]
        if p and _token(me_id, p) == token:
            return p
    return None


def _snoop_ids(me_id: int) -> list[int]:
    return [r["clicker_id"] for r in db.rows("SELECT DISTINCT clicker_id FROM clicks WHERE owner_id=?", (me_id,))]


# ---- لیست گفتگوها ----
def conversations(me_id: int) -> list[dict]:
    rs = db.rows("""SELECT CASE WHEN sender_id=? THEN receiver_id ELSE sender_id END AS partner_id,
                          sender_id, receiver_id, text, timestamp
                   FROM anon_logs WHERE sender_id=? OR receiver_id=?
                   ORDER BY id DESC""", (me_id, me_id, me_id))
    seen: dict[int, dict] = {}
    for r in rs:
        p = r["partner_id"]
        if p in seen:
            if r["sender_id"] == me_id:
                seen[p]["out"] += 1
            else:
                seen[p]["inn"] += 1
            continue
        seen[p] = {"partner_id": p, "last_text": r["text"] or "", "last_at": r["timestamp"],
                   "last_from_me": r["sender_id"] == me_id, "out": 1 if r["sender_id"] == me_id else 0, "inn": 0 if r["sender_id"] == me_id else 1}
    items = sorted(seen.values(), key=lambda x: str(x["last_at"] or ""), reverse=True)
    out = []
    for i, it in enumerate(items, 1):
        pv = _partner_view(me_id, it["partner_id"], i)
        out.append({
            "token": pv["token"], "known": pv["known"], "masked": pv["masked"], "name": pv["name"], "avatar": pv["avatar"],
            "last_text": (it["last_text"] or "")[:90], "last_at": it["last_at"], "last_from_me": it["last_from_me"],
            "count_in": it["inn"], "count_out": it["out"],
        })
    return out


def thread(me_id: int, token: str) -> dict:
    partner = _partner_by_token(me_id, token)
    if partner is None:
        raise AppError("NOT_FOUND", "این گفتگو پیدا نشد.", 404)
    pv = _partner_view(me_id, partner, 0)
    seq = _conv_seq(me_id, partner)
    pv["name"] = pv["name"] if pv["known"] else f"کاربر ناشناس {seq}"
    rs = db.rows("""SELECT sender_id, receiver_id, text, timestamp FROM anon_logs
                    WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)
                    ORDER BY id ASC LIMIT 300""", (me_id, partner, partner, me_id))
    msgs = [{"mine": r["sender_id"] == me_id, "text": r["text"] or "", "created_at": r["timestamp"]} for r in rs]
    # v4.4: کلاینت برای غیر-VIP کامپوزر را می‌بندد و بنر VIP می‌گذارد
    return {"partner": pv, "messages": msgs, "can_send": _can_contact(me_id, partner) and vip.is_active(me_id),
            "vip_required": not vip.is_active(me_id)}


def _conv_seq(me_id: int, partner_id: int) -> int:
    convs = conversations(me_id)
    for i, c in enumerate(convs, 1):
        if c["token"] == _token(me_id, partner_id):
            return i
    return 1


def token_for_snoop(me_id: int, clicker_id: int) -> str:
    """برای شروع گفتگو با یکی از فضول‌ها (از جزئیات فضول در مینی‌اپ)."""
    if not _is_my_snoop(me_id, clicker_id):
        raise AppError("FORBIDDEN", "فقط می‌توانید به فضول‌های خودتان پیام ناشناس بدهید.", 403)
    return _token(me_id, clicker_id)


# ---- ارسال ----
def send(me_id: int, token: str, text: str) -> dict:
    # v4.4: ارسال پیام ناشناس فقط برای VIP — درخواست کاربر ادمین
    if not vip.is_active(me_id):
        raise AppError("FORBIDDEN", "ارسال پیام ناشناس فقط برای اعضای VIP است. با VIP گفتگوهای ناشناس نامحدود شو!", 403)
    partner = _partner_by_token(me_id, token)
    if partner is None:
        raise AppError("NOT_FOUND", "این گفتگو پیدا نشد.", 404)
    text = (text or "").strip()
    if not text:
        raise AppError("VALIDATION_ERROR", "متن پیام خالی است.", 422)
    if len(text) > 1000:
        raise AppError("VALIDATION_ERROR", "متن پیام حداکثر ۱۰۰۰ کاراکتر است.", 422)
    bad = _content_error(text)
    if bad:
        raise AppError("VALIDATION_ERROR", f"پیام شما شامل {bad} است و ارسال نشد.", 422)
    if not _can_contact(me_id, partner):
        raise AppError("FORBIDDEN", "فقط می‌توانید به فضول‌های خودتان یا طرفِ گفتگوی فعلی پیام بدهید.", 403)
    if _anon_blocked(partner, me_id):
        raise AppError("FORBIDDEN", "این کاربر شما را بلاک کرده است. پیام ارسال نشد.", 403)
    is_vip = vip.is_active(me_id)
    if is_vip:
        if not _vip_can_send(me_id, partner):
            raise AppError("RATE_LIMITED", "محدودیت پیام ناشناس! کمی صبر کن.", 429)
    else:
        if not _normal_can_send(me_id):
            raise AppError("RATE_LIMITED", "کاربران عادی روزی یک پیام ناشناس می‌فرستند. با VIP نامحدود شو!", 429)

    # نقاب VIP (مثل ربات)
    mask = None
    if is_vip:
        m = db.row("SELECT emoji, mask_text FROM user_mask WHERE user_id=?", (me_id,))
        if m and (m.get("emoji") or m.get("mask_text")):
            mask = f"{m.get('emoji') or ''} {m.get('mask_text') or ''}".strip()

    # تحویل به طرف مقابل با همان فرمت/دکمه‌های ربات تا تجربه یکپارچه باشد
    def esc(s: str) -> str:
        return s.replace("*", "\\*").replace("_", "\\_").replace("[", "\\[")
    is_reply = _has_thread(partner, me_id)
    body = f"🎭 *{esc(mask)}* نجوا کرد:\n{esc(text)}" if mask else (
        ("📩 *پاسخ ناشناس:*\n" if is_reply else "📩 *پیام ناشناس:*\n") + esc(text))
    reply_markup = {"inline_keyboard": [[
        {"text": "🔄 پاسخ ناشناس", "callback_data": f"anon_reply_{me_id}"},
    ], [
        {"text": "🚫 بلاک", "callback_data": f"block_{me_id}"},
        {"text": "⚠️ گزارش تخلف", "callback_data": f"report_{me_id}"},
    ]]}
    bale_api.send_message(partner, body, reply_markup=reply_markup)
    if is_vip:
        _vip_reg(me_id, partner)
    ts = iso()
    with db.tx() as c:
        c.execute("INSERT INTO anon_logs (sender_id, receiver_id, text, timestamp) VALUES(?,?,?,?)", (me_id, partner, text, ts))
    return {"sent": True, "created_at": ts}


# ---- آرشیو ادمین (به‌جای ارسال به PV ادمین) ----
def admin_archive(page: int = 1, per: int = 20, q: str = "") -> dict:
    page = max(1, page)
    per = max(5, min(50, per))
    where, params = "1=1", []
    q = (q or "").strip().lstrip("@")
    if q:
        if q.isdigit():
            where = "(l.sender_id=? OR l.receiver_id=?)"
            params = [int(q), int(q)]
        else:
            where = "(su.first_name LIKE ? OR su.last_name LIKE ? OR su.username LIKE ? OR ru.first_name LIKE ? OR ru.last_name LIKE ? OR ru.username LIKE ? OR l.text LIKE ?)"
            params = [f"%{q}%"] * 7
    total = db.scalar(f"SELECT COUNT(*) FROM anon_logs l WHERE {where}", params, 0)
    rs = db.rows(f"""SELECT l.*, su.first_name AS s_fn, su.last_name AS s_ln, su.username AS s_un,
                            ru.first_name AS r_fn, ru.last_name AS r_ln, ru.username AS r_un
                     FROM anon_logs l
                     LEFT JOIN users su ON su.user_id=l.sender_id
                     LEFT JOIN users ru ON ru.user_id=l.receiver_id
                     WHERE {where} ORDER BY l.id DESC LIMIT ? OFFSET ?""",
                 params + [per, (page - 1) * per])
    items = [{
        "sender": {"id": r["sender_id"], "name": display_name({"first_name": r["s_fn"], "last_name": r["s_ln"], "username": r["s_un"]}),
                   "username": r["s_un"], "avatar": avatars.url_for(r["sender_id"])},
        "receiver": {"id": r["receiver_id"], "name": display_name({"first_name": r["r_fn"], "last_name": r["r_ln"], "username": r["r_un"]}),
                     "username": r["r_un"], "avatar": avatars.url_for(r["receiver_id"])},
        "text": (r["text"] or "")[:200], "created_at": r["timestamp"],
    } for r in rs]
    stats = {
        "total": total,
        "today": db.scalar("SELECT COUNT(*) FROM anon_logs WHERE date(timestamp)=date('now')", (), 0),
        "last_24h": db.scalar("SELECT COUNT(*) FROM anon_logs WHERE julianday('now') - julianday(timestamp) <= 1", (), 0),
    }
    return {"items": items, "total": total, "page": page, "pages": max(1, -(-total // per)), "stats": stats}
