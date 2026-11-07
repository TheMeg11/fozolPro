"""دسترسی به SQLite — مشترک بین ترد ربات و API.

- هر ترد اتصال خودش را دارد (thread-local)؛ اتصال‌ها autocommit هستند.
- نوشتن‌ها از طریق tx() با قفل سراسری + BEGIN IMMEDIATE سریال می‌شوند (جلوگیری از database is locked).
- WAL + busy_timeout برای خواندن هم‌زمان.
- مهاجرت فقط افزایشی: CREATE TABLE IF NOT EXISTS و ALTER TABLE ADD COLUMN پس از چک وجود ستون.
"""
from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import threading
import time
from typing import Any, Iterator

import settings

log = logging.getLogger("db")
_local = threading.local()
_write_lock = threading.RLock()
_all_conns: list[sqlite3.Connection] = []
_all_lock = threading.Lock()
_generation = 0  # v4.6.2: با هر close_all زیاد می‌شود تا کانکشن‌های thread-local باطل شوند (بعد از /restore)


def _open(path: str) -> sqlite3.Connection:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    with _all_lock:
        _all_conns.append(conn)
    return conn


def conn() -> sqlite3.Connection:
    path = settings.DB_PATH
    c = getattr(_local, "conn", None)
    # v4.6.2: چک _generation — اگر close_all() (مثلاً بعد از /restore) اجرا شده باشد،
    # کانکشن‌های thread-localِ بقیهٔ ترد‌ها به فایل قدیمی/بسته اشاره می‌کنند و باید باز شوند.
    if (c is None or getattr(_local, "gen", -1) != _generation
            or getattr(_local, "path", None) != path):
        c = _open(path)
        _local.conn, _local.path, _local.gen = c, path, _generation
    return c


@contextlib.contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    """تراکنش نوشتنی سریال‌شده + تلاش مجدد روی قفل گذرا (database is locked).

    اگر اتصال دیگری (مثلاً اتصال ربات legacy) لحظاتی قفل نوشتن را نگه دارد،
    به‌جای خطای 500 به کاربر، چند بار با فاصله تلاش می‌کنیم؛ busy_timeout خود
    SQLite هم ۳۰ ثانیه منتظر می‌ماند. ترکیب این دو، خطای قفل را در عمل حذف می‌کند."""
    with _write_lock:
        c = conn()
        for attempt in range(5):
            try:
                c.execute("BEGIN IMMEDIATE")
                break
            except sqlite3.OperationalError as exc:
                if attempt == 4 or "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                    raise
                time.sleep(0.4 * (attempt + 1))
        try:
            yield c
            c.execute("COMMIT")
        except BaseException:
            try:
                c.execute("ROLLBACK")
            except sqlite3.Error:  # حتی اگر rollback هم خطا داد، خطای اصلی را گم نکن
                pass
            raise


def rows(sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn().execute(sql, params).fetchall()]


def row(sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
    r = conn().execute(sql, params).fetchone()
    return dict(r) if r else None


def scalar(sql: str, params: tuple | list = (), default: Any = 0) -> Any:
    r = conn().execute(sql, params).fetchone()
    return r[0] if r and r[0] is not None else default


def execute(sql: str, params: tuple | list = ()) -> int:
    with tx() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid or cur.rowcount


def column_exists(c: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r[1] == column for r in c.execute(f"PRAGMA table_info({table})").fetchall())


SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        first_name TEXT, last_name TEXT, username TEXT,
        joined_at TEXT, last_seen TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS snoop_traps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL, title TEXT NOT NULL, bait TEXT DEFAULT '',
        code TEXT NOT NULL UNIQUE, is_default INTEGER DEFAULT 0, active INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_traps_owner ON snoop_traps(owner_id)",
    """CREATE TABLE IF NOT EXISTS snoop_visits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trap_id INTEGER NOT NULL, owner_id INTEGER NOT NULL, visitor_id INTEGER NOT NULL,
        visitor_name TEXT, visitor_username TEXT, count INTEGER DEFAULT 1,
        first_at TEXT NOT NULL, last_at TEXT NOT NULL,
        UNIQUE(trap_id, visitor_id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_visits_owner ON snoop_visits(owner_id, last_at)",
    """CREATE TABLE IF NOT EXISTS snoop_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trap_id INTEGER NOT NULL, owner_id INTEGER NOT NULL, visitor_id INTEGER NOT NULL, created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_events_owner ON snoop_events(owner_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_events_time ON snoop_events(created_at)",
    """CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL, plan_id TEXT NOT NULL, amount INTEGER NOT NULL,
        payload TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'pending',
        charge_id TEXT, created_at TEXT NOT NULL, paid_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS ix_payments_user ON payments(user_id, created_at)",
    """CREATE TABLE IF NOT EXISTS support_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL, sender TEXT NOT NULL, text TEXT DEFAULT '',
        media_type TEXT, file_id TEXT, read_by_admin INTEGER DEFAULT 0, created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_support_user ON support_messages(user_id, id)",
    """CREATE TABLE IF NOT EXISTS support_tickets (
        user_id INTEGER PRIMARY KEY, status TEXT NOT NULL DEFAULT 'open', updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS broadcast_jobs (
        id TEXT PRIMARY KEY, target TEXT NOT NULL, text TEXT NOT NULL, status TEXT NOT NULL,
        total INTEGER DEFAULT 0, sent INTEGER DEFAULT 0, failed INTEGER DEFAULT 0,
        created_at TEXT NOT NULL, finished_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS wheel_spins (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        prize_type TEXT NOT NULL, amount INTEGER DEFAULT 0, created_at TEXT NOT NULL
    )""",
    "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)",
    # --- v4.0 (fozol-pro): جدول‌های هستهٔ ربات legacy — همان اسکیمای main.py؛
    # اگر ربات بعداً import شود CREATE TABLE IF NOT EXISTS آن no-op است ---
    """CREATE TABLE IF NOT EXISTS vip (
        user_id INTEGER PRIMARY KEY,
        expire_date TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS traps (
        trap_code TEXT PRIMARY KEY,
        owner_id INTEGER NOT NULL,
        label TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS clicks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL,
        clicker_id INTEGER NOT NULL,
        clicker_name TEXT,
        clicker_username TEXT,
        clicked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_new_user INTEGER DEFAULT 0,
        trap_code TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS ix_clicks_owner ON clicks(owner_id, clicked_at)",
    "CREATE INDEX IF NOT EXISTS ix_clicks_trap ON clicks(trap_code)",
    """CREATE TABLE IF NOT EXISTS nicknames (
        owner_id INTEGER NOT NULL,
        clicker_id INTEGER NOT NULL,
        nickname TEXT,
        PRIMARY KEY (owner_id, clicker_id)
    )""",
    """CREATE TABLE IF NOT EXISTS forced_channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id TEXT UNIQUE NOT NULL,
        channel_name TEXT,
        invite_link TEXT,
        target INTEGER DEFAULT 0,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    # --- v4.1 (fozol-pro): جداول ربات که سرویس‌های جدید مینی‌اپ لازم دارند؛
    # در production ربات هم همین‌ها را می‌سازد و CREATE IF NOT EXISTS جمع می‌شود ---
    """CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS anon_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        text TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    "CREATE INDEX IF NOT EXISTS idx_anon_pair ON anon_logs(sender_id, receiver_id)",
    "CREATE INDEX IF NOT EXISTS idx_anon_timestamp ON anon_logs(timestamp)",
    """CREATE TABLE IF NOT EXISTS blocked_anon (
        blocker_id INTEGER NOT NULL,
        blocked_id INTEGER NOT NULL,
        PRIMARY KEY (blocker_id, blocked_id)
    )""",
    """CREATE TABLE IF NOT EXISTS user_mask (
        user_id INTEGER PRIMARY KEY,
        emoji TEXT,
        mask_text TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        amount INTEGER NOT NULL,
        days INTEGER DEFAULT 0,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS gift_codes (
        code TEXT PRIMARY KEY,
        days INTEGER NOT NULL,
        max_uses INTEGER NOT NULL,
        used_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS gift_usage (
        code TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (code, user_id)
    )""",
    # --- v4.4: تصمیم «حفظ آبرو / لو رفتن» بازدیدکنندهٔ تله (مشترک با ربات) ---
    """CREATE TABLE IF NOT EXISTS trap_decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        visitor_id INTEGER NOT NULL,
        owner_id INTEGER NOT NULL,
        trap_code TEXT,
        is_new INTEGER DEFAULT 0,
        repeat_count INTEGER DEFAULT 1,
        display_name TEXT,
        clicker_username TEXT,
        photo_file_id TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        deadline REAL,
        created_at TEXT NOT NULL,
        resolved_at TEXT,
        paid_amount INTEGER DEFAULT 0
    )""",
    "CREATE INDEX IF NOT EXISTS ix_trapdec_deadline ON trap_decisions(status, deadline)",
]

# ستون‌هایی که ممکن است در جدول users فعلی main.py نباشند (افزایشی و امن)
# v4.0 (fozol-pro): ستون‌های ربات (blocked/blocked_by_admin/level_cached/created_at/source) هم
# اینجا تضمین می‌شوند تا حالت API-only هم بدون import ربات کار کند — هم‌سکیمای main.py.
USER_COLUMNS = {
    "first_name": "TEXT", "last_name": "TEXT", "username": "TEXT",
    "joined_at": "TEXT", "last_seen": "TEXT",
    "xp": "INTEGER DEFAULT 0", "week_xp": "INTEGER DEFAULT 0", "week_key": "TEXT",
    "vip_until": "TEXT", "vip_plan": "TEXT", "is_banned": "INTEGER DEFAULT 0", "last_spin_at": "TEXT",
    "blocked": "INTEGER DEFAULT 0", "blocked_by_admin": "INTEGER DEFAULT 0",
    "level_cached": "INTEGER DEFAULT 1", "created_at": "TEXT", "source": "TEXT",
    "last_active_date": "TEXT",  # شمارندهٔ «کاربران فعال امروز» ربات
    "hide_leaderboard_week": "INTEGER DEFAULT 0",  # v4.4: مخفی‌سازی جداگانهٔ هفتگی برترین‌ها
    "active_title": "INTEGER",  # v4.4: لقب فعال انتخابی (کلید LEVEL_NAMES)
    # v4.4: ستون‌های ربات که سرویس‌های مینی‌اپ هم می‌خوانند (در حالت API-only تضمین شوند)
    "display_name": "TEXT",
    "hide_leaderboard": "INTEGER DEFAULT 0",
    "streak_count": "INTEGER DEFAULT 0",
    "last_streak_date": "TEXT",
}


def migrate() -> None:
    with tx() as c:
        for stmt in SCHEMA:
            c.execute(stmt)
        for col, decl in USER_COLUMNS.items():
            if not column_exists(c, "users", col):
                c.execute(f"ALTER TABLE users ADD COLUMN {col} {decl}")
                log.info("migration: users.%s added", col)
        # v4.3: هم‌سکما کردن forced_channels با ربات (ستون target برای هدف جذب)
        if not column_exists(c, "forced_channels", "target"):
            c.execute("ALTER TABLE forced_channels ADD COLUMN target INTEGER DEFAULT 0")
            log.info("migration: forced_channels.target added")
        c.execute("CREATE INDEX IF NOT EXISTS ix_users_xp ON users(xp)")
    log.info("database ready at %s (WAL)", settings.DB_PATH)


def kv_get(key: str, default: str | None = None) -> str | None:
    r = row("SELECT value FROM kv WHERE key=?", (key,))
    return r["value"] if r else default


def kv_set(key: str, value: str) -> None:
    execute("INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def close_all() -> None:
    global _generation
    with _all_lock:
        for c in _all_conns:
            with contextlib.suppress(Exception):
                c.close()
        _all_conns.clear()
    _generation += 1  # v4.6.2: کانکشن‌های کش‌شدهٔ همهٔ ترد‌ها را باطل کن
    _local.__dict__.clear()
