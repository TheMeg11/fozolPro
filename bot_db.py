"""bot_db.py — لایهٔ دیتابیس ربات (استخراج‌شده از main.py — v4.7).

کلاس Database + _SharedWriteLock؛ فقط به logger/config/TEHRAN_TZ وابسته است.
main.py می‌نویسد: `db = Database(DB_PATH)` — همهٔ ارجاع‌های db.* دست‌نخورده‌اند.
"""
from __future__ import annotations

import datetime
import logging
import sqlite3
import threading
import time
from pathlib import Path

import config
import tasks as tasks_module

logger = logging.getLogger("bot_db")
TEHRAN_TZ = datetime.timezone(datetime.timedelta(hours=3, minutes=30))


class _SharedWriteLock:
    """قفل ترکیبی نوشتن: قفل ربات + قفل لایهٔ مینی‌اپ (services.db._write_lock).

    ربات (main.py) و مینی‌اپ (services/*.py) دو استخر اتصال جدا به همان فایل
    SQLite دارند. بدون این قفل مشترک، نوشتن هر دو لایه می‌تواند هم‌زمان درخواست
    قفل SQLite را بدهد و «database is locked» بدهد. با این قفل، همهٔ نوشتن‌ها
    در کل پروسس سریال می‌شوند و ترتیب گرفتن قفل همیشه یکسان است (بدون deadlock).
    """

    def __init__(self, primary: threading.RLock):
        self._primary = primary
        self._shared = None
        try:  # در حالت API-only (بدون import شدن main) هم کار می‌کند
            from services import db as _svc_db
            self._shared = _svc_db._write_lock
        except Exception:
            self._shared = None

    def __enter__(self):
        self._primary.acquire()
        if self._shared is not None:
            self._shared.acquire()

    def __exit__(self, *exc):
        if self._shared is not None:
            self._shared.release()
        self._primary.release()


class Database:
    def __init__(self, path):
        # v3.24.9: اگر پوشهٔ مقصد (مثلاً Volume در Railway) هنوز ساخته نشده باشد،
        # sqlite3.connect با خطای "unable to open database file" کرش می‌کند.
        # این‌جا مسیر پدر را از قبل می‌سازیم تا از این کرش‌لوپ جلوگیری شود.
        try:
            _parent = Path(path).parent
            _parent.mkdir(parents=True, exist_ok=True)
        except Exception as _mkdir_err:
            logger.error("DB parent dir mkdir failed for %s: %s", path, _mkdir_err)
        # v4.2 (fozol-pro): رفع قطعی/«database is locked» — اتصال در حالت autocommit.
        # قبلاً isolation_level پیش‌فرض (implicit transaction) بود: اگر بین execute و commit
        # استثنا رخ می‌داد، تراکنشِ باز می‌ماند و قفل نوشتن SQLite تا مداخلهٔ watchdog (۶۰ ثانیه)
        # نگه داشته می‌شد؛ در آن بازه ربات هنگ می‌کرد و مینی‌اپ خطای database is locked می‌گرفت.
        # با autocommit هر statement بلافاصله commit می‌شود (همان رفتاری که کد قدیمی با commit()
        # بعد از هر execute دنبالش بود) و commit()های موجود no-op بی‌ضرر می‌شوند.
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=30, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        # v4.0.1 (fozol-pro): قفل نوشتن مشترک با لایهٔ مینی‌اپ + timeout طولانی‌تر
        self._lock = _SharedWriteLock(threading.RLock())
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        # ── v3.23: تیون عملکرد SQLite برای مقیاس ۵۰۰۰+ کاربر ──
        self.conn.execute("PRAGMA synchronous=NORMAL")   # در WAL ایمن است؛ نوشتن چند برابر سریع‌تر از FULL
        self.conn.execute("PRAGMA cache_size=-16000")    # کش ۱۶ مگابایتی صفحات (پیش‌فرض ~۲MB)
        self.conn.execute("PRAGMA temp_store=MEMORY")    # جدول‌های موقت در RAM نه دیسک
        self.conn.execute("PRAGMA mmap_size=134217728")  # mmap ۱۲۸MB — خواندن سریع‌تر
        # ── v3.23: کش TTL آمارهای سنگین پنل ادمین ──
        self._stats_cache = {}
        self._migrate()
        # v4.0.1 (fozol-pro): واتچ‌داگ تراکنش گیرکرده — اگر بین execute و commit
        # استثنا رخ دهد، تراکنش باز می‌ماند و قفل نوشتن دیتابیس «برای همیشه» گیر
        # می‌کند (مینی‌اپ خطای database is locked می‌دهد). واتچ‌داگ بعد از ۶۰ ثانیه
        # آن را rollback می‌کند تا سیستم خودش ترمیم شود.
        # ── v4.6.2: فلگ توقف واتچ‌داگ — بعد از /restore که conn بسته و نمونه جایگزین می‌شود،
        # واتچ‌داگ نمونهٔ قدیمی نباید تا ابد روی کانکشن بسته خطا بدهد ──
        self._shutdown_watchdog = False
        self._txn_watch = threading.Thread(target=self._txn_watchdog, name="db-txn-watchdog", daemon=True)
        self._txn_watch.start()

    def _txn_watchdog(self):
        stuck_since = None
        while True:
            time.sleep(5)
            if getattr(self, "_shutdown_watchdog", False):
                break  # v4.6.2: نمونهٔ قدیمی بازنشسته شده — پایان حلقه
            try:
                if self.conn.in_transaction:
                    if stuck_since is None:
                        stuck_since = time.time()
                    elif time.time() - stuck_since > 60:
                        with self._lock:
                            if self.conn.in_transaction:
                                logger.error("DB watchdog: write transaction open >60s — rolling back stuck transaction (self-heal)")
                                try:
                                    self.conn.rollback()
                                except sqlite3.Error as rb_err:
                                    logger.error("DB watchdog rollback failed: %s", rb_err)
                        stuck_since = None
                else:
                    stuck_since = None
            except Exception as exc:
                logger.warning("DB watchdog error: %s", exc)
                stuck_since = None

    def sync_user_profile(self, user_id, first_name, username):
        with self._lock:
            now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.conn.execute(
                "INSERT OR IGNORE INTO users (user_id, first_name, username, created_at) VALUES (?,?,?,?)",
                (user_id, first_name or "بی‌نام", username or "", now)
            )
            self.conn.execute(
                "UPDATE users SET first_name=?, username=? WHERE user_id=?",
                (first_name or "بی‌نام", username or "", user_id)
            )
            # اگه کاربر قبلاً ربات رو بلاک کرده بود (blocked_bot=1) ولی حالا پیام فرستاده،
            # یعنی آنبلاک کرده — پس فلگ رو پاک کن تا دوباره به صف پخش برگرده
            self.conn.execute(
                "UPDATE users SET blocked_bot=0 WHERE user_id=? AND blocked_bot=1",
                (user_id,)
            )
            self.conn.commit()

    def _migrate(self):
        with self._lock:
            self.conn.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    blocked INTEGER DEFAULT 0,
                    welcome_text TEXT,
                    welcome_photo TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    source TEXT
                );
                CREATE TABLE IF NOT EXISTS clicks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER NOT NULL,
                    clicker_id INTEGER NOT NULL,
                    clicker_name TEXT,
                    clicker_username TEXT,
                    clicked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_new_user INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS nicknames (
                    owner_id INTEGER NOT NULL,
                    clicker_id INTEGER NOT NULL,
                    nickname TEXT,
                    PRIMARY KEY (owner_id, clicker_id)
                );
                CREATE TABLE IF NOT EXISTS vip (
                    user_id INTEGER PRIMARY KEY,
                    expire_date TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS blocked_anon (
                    blocker_id INTEGER NOT NULL,
                    blocked_id INTEGER NOT NULL,
                    PRIMARY KEY (blocker_id, blocked_id)
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    days INTEGER DEFAULT 0,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS anon_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_id INTEGER NOT NULL,
                    receiver_id INTEGER NOT NULL,
                    text TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS gift_codes (
                    code TEXT PRIMARY KEY,
                    days INTEGER NOT NULL,
                    max_uses INTEGER NOT NULL,
                    used_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS gift_usage (
                    code TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (code, user_id)
                );
                CREATE TABLE IF NOT EXISTS user_mask (
                    user_id INTEGER PRIMARY KEY,
                    emoji TEXT,
                    mask_text TEXT
                );
                CREATE TABLE IF NOT EXISTS muted_snoops (
                    owner_id INTEGER NOT NULL,
                    clicker_id INTEGER NOT NULL,
                    PRIMARY KEY (owner_id, clicker_id)
                );
                CREATE TABLE IF NOT EXISTS channel_joins (
                    user_id INTEGER NOT NULL,
                    channel_username TEXT NOT NULL,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, channel_username)
                );
                CREATE TABLE IF NOT EXISTS pending_snoops (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER NOT NULL,
                    clicker_id INTEGER NOT NULL,
                    display_name TEXT,
                    t TEXT,
                    vip_owner INTEGER DEFAULT 0,
                    clicker_username TEXT,
                    repeat INTEGER DEFAULT 1,
                    gift_vip_given INTEGER DEFAULT 0,
                    photo_file_id TEXT
                );
                CREATE TABLE IF NOT EXISTS forced_channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT UNIQUE NOT NULL,
                    channel_name TEXT,
                    invite_link TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS daily_report_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_report_date TEXT
                );
                INSERT OR IGNORE INTO daily_report_state (id, last_report_date) VALUES (1, NULL);
                CREATE TABLE IF NOT EXISTS callback_stats (
                    callback_data TEXT PRIMARY KEY,
                    click_count INTEGER DEFAULT 0,
                    last_clicked TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            ''')
            # v3.24.4: جدول تلمتری استفاده — ساعت پیک / مسیرهای کند / پرمصرف‌ها
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    kind TEXT NOT NULL,          -- cb | msg | cmd | error | slow
                    label TEXT,
                    duration_ms INTEGER DEFAULT 0
                );
            ''')
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_events(ts)")
            self.conn.commit()
            self._ensure_columns()
            self._create_indexes()

    def reset_warnings(self, user_id):
        with self._lock:
            self.conn.execute("UPDATE users SET warning_count = 0 WHERE user_id=?", (user_id,))
            row = self.conn.execute("SELECT blocked, blocked_by_admin FROM users WHERE user_id=?", (user_id,)).fetchone()
            if row and row['blocked'] and row['blocked_by_admin']:
                self.conn.execute("UPDATE users SET blocked=0, blocked_by_admin=0 WHERE user_id=?", (user_id,))
            self.conn.commit()

    def _ensure_columns(self):
        # موارد کاملاً بی‌خطر
        try: self.conn.execute("SELECT username FROM users LIMIT 1")
        except sqlite3.OperationalError: self.conn.execute("ALTER TABLE users ADD COLUMN username TEXT"); self.conn.commit()
        try: self.conn.execute("SELECT first_name FROM users LIMIT 1")
        except sqlite3.OperationalError: self.conn.execute("ALTER TABLE users ADD COLUMN first_name TEXT"); self.conn.commit()
        try: self.conn.execute("SELECT blocked FROM users LIMIT 1")
        except sqlite3.OperationalError: self.conn.execute("ALTER TABLE users ADD COLUMN blocked INTEGER DEFAULT 0"); self.conn.commit()
        try: self.conn.execute("SELECT welcome_text FROM users LIMIT 1")
        except sqlite3.OperationalError: self.conn.execute("ALTER TABLE users ADD COLUMN welcome_text TEXT"); self.conn.commit()
        try: self.conn.execute("SELECT welcome_photo FROM users LIMIT 1")
        except sqlite3.OperationalError: self.conn.execute("ALTER TABLE users ADD COLUMN welcome_photo TEXT"); self.conn.commit()
        try: self.conn.execute("SELECT is_new_user FROM clicks LIMIT 1")
        except sqlite3.OperationalError: self.conn.execute("ALTER TABLE clicks ADD COLUMN is_new_user INTEGER DEFAULT 0"); self.conn.commit()
        # --- v3.4: مهاجرت ستون‌های جدید users ---
        for _col, _def in (("streak_count", "INTEGER DEFAULT 0"), ("last_streak_date", "TEXT"),
                           ("trial_given", "INTEGER DEFAULT 0"), ("last_remind_date", "TEXT"),
                           ("streak_notified_date", "TEXT"),
                           ("last_wheel_date", "TEXT"), ("last_giftvip_date", "TEXT")):
            try: self.conn.execute(f"SELECT {_col} FROM users LIMIT 1")
            except sqlite3.OperationalError:
                self.conn.execute(f"ALTER TABLE users ADD COLUMN {_col} {_def}"); self.conn.commit()
        # --- v3.6: جدول تله‌های چندگانه ---
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS traps (
                trap_code TEXT PRIMARY KEY,
                owner_id INTEGER NOT NULL,
                label TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        try: self.conn.execute("SELECT trap_code FROM clicks LIMIT 1")
        except sqlite3.OperationalError: self.conn.execute("ALTER TABLE clicks ADD COLUMN trap_code TEXT"); self.conn.commit()
        # --- v3.4: جدول باز کردن تکی پروفایل (reveal) ---
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS reveals (
                owner_id INTEGER NOT NULL,
                clicker_id INTEGER NOT NULL,
                revealed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (owner_id, clicker_id)
            )
        ''')
        # --- v3.17: جدول جایزه روزانه (همهٔ کاربران — ریست ساعت ۰۰:۰۰ ایران) ---
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS daily_bonus (
                user_id INTEGER PRIMARY KEY,
                last_claim TEXT,
                streak INTEGER DEFAULT 0,
                total_claims INTEGER DEFAULT 0
            )
        ''')
        # --- v4.4: تصمیم «حفظ آبرو / لو رفتن» بازدیدکنندهٔ تله ---
        # status: pending (۱ دقیقه فرصت انتخاب) | saveface (۳ دقیقه فرصت پرداخت)
        #         | saved (پرداخت شد) | exposed (لو رفت — گزارش ارسال شد)
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS trap_decisions (
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
            )
        ''')
        try:
            self.conn.execute("CREATE INDEX IF NOT EXISTS ix_trapdec_deadline ON trap_decisions(status, deadline)")
        except sqlite3.OperationalError:
            pass
        # --- v4.4: مخفی‌سازی جداگانهٔ هفتگی لیدربورد (hide_leaderboard = کل دوران) ---
        try: self.conn.execute("SELECT hide_leaderboard_week FROM users LIMIT 1")
        except sqlite3.OperationalError: self.conn.execute("ALTER TABLE users ADD COLUMN hide_leaderboard_week INTEGER DEFAULT 0"); self.conn.commit()
        # --- v4.4: لقب فعال انتخابی کاربر (کلید LEVEL_NAMES؛ NULL = لقب خودکار سطح) ---
        try: self.conn.execute("SELECT active_title FROM users LIMIT 1")
        except sqlite3.OperationalError: self.conn.execute("ALTER TABLE users ADD COLUMN active_title INTEGER"); self.conn.commit()
        self.conn.commit()
        try: self.conn.execute("SELECT created_at FROM users LIMIT 1")
        except sqlite3.OperationalError:
            self.conn.execute("ALTER TABLE users ADD COLUMN created_at TEXT")
            self.conn.commit()
        try: self.conn.execute("SELECT source FROM users LIMIT 1")
        except sqlite3.OperationalError:
            self.conn.execute("ALTER TABLE users ADD COLUMN source TEXT")
            self.conn.commit()
        # حذف: بخش خطرناک vip کاملاً پاک شده است (DROP TABLE آنجا انجام نمی‌شود)
        try: self.conn.execute("SELECT blocked_by_admin FROM users LIMIT 1")
        except sqlite3.OperationalError:
            self.conn.execute("ALTER TABLE users ADD COLUMN blocked_by_admin INTEGER DEFAULT 0")
            self.conn.commit()
        try: self.conn.execute("SELECT warning_count FROM users LIMIT 1")
        except sqlite3.OperationalError: self.conn.execute("ALTER TABLE users ADD COLUMN warning_count INTEGER DEFAULT 0"); self.conn.commit()
        try: self.conn.execute("SELECT hide_leaderboard FROM users LIMIT 1")
        except sqlite3.OperationalError: self.conn.execute("ALTER TABLE users ADD COLUMN hide_leaderboard INTEGER DEFAULT 0"); self.conn.commit()
        # v3.20: نام نمایشی دلخواه برای لیدربورد (NULL = نام اکانت)
        try: self.conn.execute("SELECT display_name FROM users LIMIT 1")
        except sqlite3.OperationalError: self.conn.execute("ALTER TABLE users ADD COLUMN display_name TEXT"); self.conn.commit()
        # v3.21: آیا کاربر حداقل یک درخواست (پیام/دکمه) به ربات فرستاده است
        try: self.conn.execute("SELECT requested FROM users LIMIT 1")
        except sqlite3.OperationalError: self.conn.execute("ALTER TABLE users ADD COLUMN requested INTEGER DEFAULT 0"); self.conn.commit()
        # v3.21: هدف جذب کانال اجباری (0 = بدون محدودیت)
        try: self.conn.execute("SELECT target FROM forced_channels LIMIT 1")
        except sqlite3.OperationalError: self.conn.execute("ALTER TABLE forced_channels ADD COLUMN target INTEGER DEFAULT 0"); self.conn.commit()
        # ستون‌های سیستم XP و سطح‌بندی
        try: self.conn.execute("SELECT xp FROM users LIMIT 1")
        except sqlite3.OperationalError: self.conn.execute("ALTER TABLE users ADD COLUMN xp INTEGER DEFAULT 0"); self.conn.commit()
        try: self.conn.execute("SELECT level_cached FROM users LIMIT 1")
        except sqlite3.OperationalError: self.conn.execute("ALTER TABLE users ADD COLUMN level_cached INTEGER DEFAULT 1"); self.conn.commit()
        try: self.conn.execute("SELECT last_active_date FROM users LIMIT 1")
        except sqlite3.OperationalError: self.conn.execute("ALTER TABLE users ADD COLUMN last_active_date TEXT"); self.conn.commit()
        # جدول ردیابی XP یکباره‌ها (جلوگیری از اعطای دوباره)
        try: self.conn.execute("SELECT user_id FROM xp_bonuses LIMIT 1")
        except sqlite3.OperationalError:
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS xp_bonuses (
                    user_id INTEGER NOT NULL,
                    bonus_type TEXT NOT NULL,
                    awarded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, bonus_type)
                )
            ''')
            self.conn.commit()
        # ستون last_broadcast_blocked — کاربرانی که ربات رو بلاک کرده‌اند (برای حذف از پخش همگانی)
        try: self.conn.execute("SELECT blocked_bot FROM users LIMIT 1")
        except sqlite3.OperationalError: self.conn.execute("ALTER TABLE users ADD COLUMN blocked_bot INTEGER DEFAULT 0"); self.conn.commit()

    def increment_warning(self, user_id):
        with self._lock:
            self.conn.execute("UPDATE users SET warning_count = COALESCE(warning_count, 0) + 1 WHERE user_id=?", (user_id,))
            self.conn.commit()
            return self.conn.execute("SELECT warning_count FROM users WHERE user_id=?", (user_id,)).fetchone()['warning_count']

    def get_last_anon_log(self, sender_id, receiver_id):
        with self._lock:
            row = self.conn.execute(
                "SELECT text FROM anon_logs WHERE sender_id=? AND receiver_id=? ORDER BY timestamp DESC LIMIT 1",
                (sender_id, receiver_id)
            ).fetchone()
            return row['text'] if row else ""

    def get_user_warning_count(self, user_id):
        with self._lock:
            row = self.conn.execute("SELECT warning_count FROM users WHERE user_id=?", (user_id,)).fetchone()
            return row['warning_count'] if row else 0

    def set_hide_leaderboard(self, user_id, hide):
        with self._lock:
            self.conn.execute("UPDATE users SET hide_leaderboard=? WHERE user_id=?", (1 if hide else 0, user_id))
            self.conn.commit()

    def is_hide_leaderboard(self, user_id):
        with self._lock:
            row = self.conn.execute("SELECT hide_leaderboard FROM users WHERE user_id=?", (user_id,)).fetchone()
            return row and row['hide_leaderboard'] == 1

    def set_display_name(self, user_id, name):
        """v3.20: نام نمایشی دلخواه برای لیدربورد؛ نام خالی/None = بازگشت به نام اکانت."""
        with self._lock:
            self.conn.execute("UPDATE users SET display_name=? WHERE user_id=?", ((name or '').strip() or None, user_id))
            self.conn.commit()

    def get_display_name(self, user_id):
        with self._lock:
            try:
                row = self.conn.execute("SELECT display_name FROM users WHERE user_id=?", (user_id,)).fetchone()
                return (row['display_name'] if row else None) or None
            except sqlite3.OperationalError:
                return None


    def _create_indexes(self):
        with self._lock:
            # رفع باگ: اگر ستون‌های کلیدی وجود نداشته باشند (مثلاً بعد از /restore با
            # فایل قدیمی)، ایندکس‌ها کرش می‌کنند. ابتدا ستون‌ها تضمین می‌شوند.
            try: self.conn.execute("SELECT username FROM users LIMIT 1")
            except sqlite3.OperationalError: self.conn.execute("ALTER TABLE users ADD COLUMN username TEXT"); self.conn.commit()
            try: self.conn.execute("SELECT clicked_at FROM clicks LIMIT 1")
            except sqlite3.OperationalError: self.conn.execute("ALTER TABLE clicks ADD COLUMN clicked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"); self.conn.commit()
            self.conn.executescript('''
                CREATE INDEX IF NOT EXISTS idx_clicks_owner ON clicks(owner_id);
                CREATE INDEX IF NOT EXISTS idx_clicks_clicker ON clicks(clicker_id);
                CREATE INDEX IF NOT EXISTS idx_clicks_owner_clicker ON clicks(owner_id, clicker_id);
                CREATE INDEX IF NOT EXISTS idx_clicks_date ON clicks(clicked_at);
                CREATE INDEX IF NOT EXISTS idx_clicks_new_time ON clicks(is_new_user, clicked_at);
                CREATE INDEX IF NOT EXISTS idx_vip_expire ON vip(expire_date);
                CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
            ''')
            self.conn.commit()
            # ── v3.23: ایندکس‌های داغ مقیاس بالا — جداگانه تا نبود ستون قدیمی بقیه را نیندازد ──
            _hot_indexes = [
                ("idx_users_created_at",    "CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at)"),
                ("idx_users_created_date",  "CREATE INDEX IF NOT EXISTS idx_users_created_date ON users(date(created_at))"),
                ("idx_users_last_active",   "CREATE INDEX IF NOT EXISTS idx_users_last_active ON users(last_active_date)"),
                ("idx_users_source",        "CREATE INDEX IF NOT EXISTS idx_users_source ON users(source)"),
                ("idx_users_blocked",       "CREATE INDEX IF NOT EXISTS idx_users_blocked ON users(blocked)"),
                ("idx_users_blocked_bot",   "CREATE INDEX IF NOT EXISTS idx_users_blocked_bot ON users(blocked_bot)"),
                ("idx_users_streak_date",   "CREATE INDEX IF NOT EXISTS idx_users_streak_date ON users(last_streak_date, streak_count)"),
                ("idx_users_requested",     "CREATE INDEX IF NOT EXISTS idx_users_requested ON users(requested)"),
                ("idx_anon_timestamp",      "CREATE INDEX IF NOT EXISTS idx_anon_timestamp ON anon_logs(timestamp)"),
                ("idx_anon_pair",           "CREATE INDEX IF NOT EXISTS idx_anon_pair ON anon_logs(sender_id, receiver_id)"),
                ("idx_tx_timestamp",        "CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON transactions(timestamp)"),
                ("idx_tx_type",             "CREATE INDEX IF NOT EXISTS idx_tx_type ON transactions(type)"),
                ("idx_cb_clicks",           "CREATE INDEX IF NOT EXISTS idx_cb_clicks ON callback_stats(click_count)"),
                ("idx_cb_last",             "CREATE INDEX IF NOT EXISTS idx_cb_last ON callback_stats(last_clicked)"),
                ("idx_cj_joined",           "CREATE INDEX IF NOT EXISTS idx_cj_joined ON channel_joins(joined_at)"),
                ("idx_db_last_claim",       "CREATE INDEX IF NOT EXISTS idx_db_last_claim ON daily_bonus(last_claim)"),
            ]
            for _iname, _isql in _hot_indexes:
                try:
                    self.conn.execute(_isql)
                except sqlite3.OperationalError as _ie:
                    # ستون ممکن است در دیتابیس قدیمیِ restore‌شده وجود نداشته باشد — غیرمهلک
                    print(f"⚠️ index {_iname} skipped: {_ie}", flush=True)
            self.conn.commit()

    # ---------- متدهای اصلی ----------
    def add_click(self, owner_id, clicker_id, name, username, is_new=False, trap_code=None):
        with self._lock:
            now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.conn.execute(
                "INSERT OR IGNORE INTO users (user_id, first_name, username, created_at) VALUES (?,?,?,?)",
                (owner_id, "", "", now))
            self.conn.execute(
                "INSERT OR IGNORE INTO users (user_id, first_name, username, created_at) VALUES (?,?,?,?)",
                (clicker_id, name, username, now))
            self.conn.execute(
                "UPDATE users SET first_name=?, username=? WHERE user_id=?",
                (name, username, clicker_id))
            self.conn.execute(
                "INSERT INTO clicks (owner_id, clicker_id, clicker_name, clicker_username, is_new_user, trap_code) VALUES (?,?,?,?,?,?)",
                (owner_id, clicker_id, name, username, 1 if is_new else 0, trap_code))
            self.conn.commit()
            # v3.24.3: با هر کلیک جدید، کش نتایج چالش باطل می‌شود تا اعداد زنده بمانند
            try:
                with _challenge_cache_lock:
                    _challenge_cache.clear()
            except NameError:
                pass
            return self.conn.execute(
                "SELECT COUNT(*) as cnt FROM clicks WHERE owner_id=? AND clicker_id=?",
                (owner_id, clicker_id)).fetchone()['cnt']

    def get_clicks_count(self, owner_id):
        with self._lock:
            row = self.conn.execute("SELECT COUNT(*) as cnt FROM clicks WHERE owner_id=?", (owner_id,)).fetchone()
            return row['cnt'] if row else 0

    def get_today_clicks_count(self, owner_id):
        with self._lock:
            today = datetime.date.today().isoformat()
            row = self.conn.execute("SELECT COUNT(*) as cnt FROM clicks WHERE owner_id=? AND date(clicked_at)=?", (owner_id, today)).fetchone()
            return row['cnt'] if row else 0

    def get_today_new_snoop_count(self, owner_id):
        """v3.17: فضول امروز — فقط کاربران جدید (اولین‌بار وارد ربات‌شده از لینک صاحب تله)
        شمرده می‌شوند؛ روز هم به وقت ایران (UTC+3:30) محاسبه می‌شود."""
        with self._lock:
            today_t = datetime.datetime.now(TEHRAN_TZ).date().isoformat()
            row = self.conn.execute(
                "SELECT COUNT(DISTINCT clicker_id) as cnt FROM clicks "
                "WHERE owner_id=? AND is_new_user=1 AND date(clicked_at, '+3 hours', '+30 minutes')=?",
                (owner_id, today_t)).fetchone()
            return row['cnt'] if row else 0

    def get_snoops(self, owner_id):
        with self._lock:
            q = '''SELECT c.clicker_id, c.clicker_name as name, c.clicker_username as username,
                         COUNT(*) as count, n.nickname
                  FROM clicks c LEFT JOIN nicknames n ON c.owner_id=n.owner_id AND c.clicker_id=n.clicker_id
                  WHERE c.owner_id=? GROUP BY c.clicker_id ORDER BY count DESC'''
            return [dict(r) for r in self.conn.execute(q, (owner_id,)).fetchall()]

    def set_nickname(self, owner_id, clicker_id, nick):
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO nicknames (owner_id, clicker_id, nickname) VALUES (?,?,?)", (owner_id, clicker_id, nick))
            self.conn.commit()

    # v3.24.4: کش کوتاه وضعیت VIP — در یک مسیر /start تا ۳ بار is_vip صدا زده می‌شود
    # (main_menu + home inner + home tail)؛ کش ۶۰ ثانیه‌ای سه قفل را به یکی تبدیل می‌کند.
    _vip_cache = {}
    _vip_cache_lock = threading.Lock()
    _VIP_CACHE_TTL = 60.0

    def is_vip(self, user_id):
        now = time.time()
        with Database._vip_cache_lock:
            hit = Database._vip_cache.get(user_id)
            if hit and now - hit[1] < Database._VIP_CACHE_TTL:
                return hit[0]
        result = self._is_vip_db(user_id)
        with Database._vip_cache_lock:
            Database._vip_cache[user_id] = (result, now)
            if len(Database._vip_cache) > 5000:  # جلوگیری از رشد بی‌رویه
                Database._vip_cache = {k: v for k, v in list(Database._vip_cache.items())
                                       if now - v[1] < Database._VIP_CACHE_TTL}
        return result

    def _is_vip_db(self, user_id):
        with self._lock:
            row = self.conn.execute("SELECT expire_date FROM vip WHERE user_id=?", (user_id,)).fetchone()
            if not row:
                return False
            try:
                exp = datetime.datetime.strptime(row['expire_date'], "%Y-%m-%d").date()
                if exp >= datetime.date.today():
                    return True
                # رفع باگ: رکورد VIP منقضی‌شده را حذف نکنیم — باعث می‌شود آمار (get_vip_stats) دقیق باشد
                # و admin بتواند تاریخچه VIPهای منقضی‌شده را ببیند. فقط False برمی‌گردانیم.
                return False
            except (ValueError, TypeError):
                return False

    def add_vip(self, user_id, days):
        with self._lock:
            row = self.conn.execute("SELECT expire_date FROM vip WHERE user_id=?", (user_id,)).fetchone()
            if row:
                try:
                    current_exp = datetime.datetime.strptime(row['expire_date'], "%Y-%m-%d").date()
                    if current_exp >= datetime.date.today(): new_exp = current_exp + datetime.timedelta(days=days)
                    else: new_exp = datetime.date.today() + datetime.timedelta(days=days)
                except: new_exp = datetime.date.today() + datetime.timedelta(days=days)
                self.conn.execute("UPDATE vip SET expire_date=? WHERE user_id=?", (new_exp.isoformat(), user_id))
            else:
                new_exp = datetime.date.today() + datetime.timedelta(days=days)
                self.conn.execute("INSERT INTO vip (user_id, expire_date) VALUES (?,?)", (user_id, new_exp.isoformat()))
            self.conn.commit()
        # v3.24.4: باطل‌سازی کش VIP بعد از تغییر
        try:
            with Database._vip_cache_lock:
                Database._vip_cache.pop(user_id, None)
        except Exception:
            pass

    def remove_vip_days(self, user_id, days):
        """v3.16: کاهش روزهای VIP ادمین — تعداد روز از تاریخ انقضا کم می‌شود.
        اگر کاربر VIP نداشته باشد None برمی‌گرداند؛ در غیر این صورت تاریخ انقضای جدید."""
        with self._lock:
            row = self.conn.execute("SELECT expire_date FROM vip WHERE user_id=?", (user_id,)).fetchone()
            if not row:
                return None
            try:
                current_exp = datetime.datetime.strptime(row['expire_date'], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return None
            new_exp = current_exp - datetime.timedelta(days=days)
            self.conn.execute("UPDATE vip SET expire_date=? WHERE user_id=?", (new_exp.isoformat(), user_id))
            self.conn.commit()
        # v3.24.4: باطل‌سازی کش VIP بعد از تغییر
        try:
            with Database._vip_cache_lock:
                Database._vip_cache.pop(user_id, None)
        except Exception:
            pass
        return new_exp

    def revoke_vip(self, user_id):
        """v3.16: لغو کامل VIP ادمین — تاریخ انقضا به دیروز تنظیم می‌شود.
        به این ترتیب is_vip فوراً False می‌شود ولی سابقهٔ VIP در آمار (get_vip_stats) حفظ می‌ماند.
        اگر کاربر اصلاً VIP نداشته باشد False برمی‌گرداند."""
        with self._lock:
            row = self.conn.execute("SELECT expire_date FROM vip WHERE user_id=?", (user_id,)).fetchone()
            if not row:
                return False
            yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
            self.conn.execute("UPDATE vip SET expire_date=? WHERE user_id=?", (yesterday, user_id))
            self.conn.commit()
        # v3.24.4: باطل‌سازی کش VIP بعد از تغییر
        try:
            with Database._vip_cache_lock:
                Database._vip_cache.pop(user_id, None)
        except Exception:
            pass
        return True

    def get_vip_days_left(self, user_id):
        with self._lock:
            row = self.conn.execute("SELECT expire_date FROM vip WHERE user_id=?", (user_id,)).fetchone()
            if not row: return 0
            try:
                exp = datetime.datetime.strptime(row['expire_date'], "%Y-%m-%d").date()
                return max(0, (exp - datetime.date.today()).days)
            except (ValueError, TypeError):
                return 0

    def get_vip_expire_date(self, user_id):
        """v3.7: تاریخ انقضای VIP به صورت datetime.date (یا None)."""
        with self._lock:
            row = self.conn.execute("SELECT expire_date FROM vip WHERE user_id=?", (user_id,)).fetchone()
            if not row: return None
            try:
                return datetime.datetime.strptime(row['expire_date'], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return None

    def get_expiring_vips(self, days_left=1):
        with self._lock:
            target = (datetime.date.today() + datetime.timedelta(days=days_left)).isoformat()
            rows = self.conn.execute("SELECT user_id FROM vip WHERE expire_date = ?", (target,)).fetchall()
            return [r['user_id'] for r in rows]

    def block_user(self, user_id, by_admin=False):
        with self._lock:
            if by_admin:
                self.conn.execute("UPDATE users SET blocked=1, blocked_by_admin=1 WHERE user_id=?", (user_id,))
            else:
                self.conn.execute("UPDATE users SET blocked=1 WHERE user_id=?", (user_id,))
            self.conn.commit()

    def unblock_user(self, user_id):
        with self._lock:
            self.conn.execute("UPDATE users SET blocked=0, blocked_by_admin=0 WHERE user_id=?", (user_id,))
            self.conn.commit()

    def is_blocked(self, user_id):
        with self._lock:
            row = self.conn.execute("SELECT blocked FROM users WHERE user_id=?", (user_id,)).fetchone()
            return row and row['blocked'] == 1

    def mark_user_blocked_bot(self, user_id):
        """کاربری که ربات را بلاک کرده (خطای 403 در ارسال) را علامت‌گذاری می‌کند."""
        with self._lock:
            self.conn.execute("UPDATE users SET blocked_bot=1 WHERE user_id=?", (user_id,))
            self.conn.commit()

    def unmark_user_blocked_bot(self, user_id):
        """کاربری که ربات را آنبلاک کرده را به صف پخش برمی‌گرداند.
        وقتی کاربر پیامی به ربات می‌فرستد، این متد صدا زده می‌شود."""
        with self._lock:
            self.conn.execute("UPDATE users SET blocked_bot=0 WHERE user_id=?", (user_id,))
            self.conn.commit()

    def get_broadcast_targets(self):
        """کاربرانی که واجد شرایط دریافت پخش همگانی هستند (بلاک نشده، حسابشان فعال است).
        v3.23: ترتیب پایدار با user_id — پیش‌نیاز resume دقیق پخش همگانی."""
        with self._lock:
            return [r['user_id'] for r in self.conn.execute(
                "SELECT user_id FROM users WHERE (blocked=0 OR blocked IS NULL) AND (blocked_bot=0 OR blocked_bot IS NULL) "
                "ORDER BY user_id ASC"
            ).fetchall()]

    def get_broadcast_targets_offset(self, offset):
        """v3.23: ادامهٔ پخش همگانی از محل قطع — همان شرط و ترتیب پایدار با پرش offset."""
        with self._lock:
            return [r['user_id'] for r in self.conn.execute(
                "SELECT user_id FROM users WHERE (blocked=0 OR blocked IS NULL) AND (blocked_bot=0 OR blocked_bot IS NULL) "
                "ORDER BY user_id ASC LIMIT -1 OFFSET ?", (max(0, int(offset)),)).fetchall()]

    def set_welcome_text(self, user_id, text):
        with self._lock:
            self.conn.execute("UPDATE users SET welcome_text=? WHERE user_id=?", (text, user_id))
            self.conn.commit()

    def get_welcome_text(self, user_id):
        with self._lock:
            row = self.conn.execute("SELECT welcome_text FROM users WHERE user_id=?", (user_id,)).fetchone()
            return row['welcome_text'] if row else None

    def set_welcome_photo(self, user_id, file_id):
        with self._lock:
            self.conn.execute("UPDATE users SET welcome_photo=? WHERE user_id=?", (file_id, user_id))
            self.conn.commit()

    def get_welcome_photo(self, user_id):
        with self._lock:
            row = self.conn.execute("SELECT welcome_photo FROM users WHERE user_id=?", (user_id,)).fetchone()
            return row['welcome_photo'] if row else None

    def block_anon(self, blocker_id, blocked_id):
        with self._lock:
            self.conn.execute("INSERT OR IGNORE INTO blocked_anon (blocker_id, blocked_id) VALUES (?,?)", (blocker_id, blocked_id))
            self.conn.commit()

    def unblock_anon(self, blocker_id, blocked_id):
        with self._lock:
            self.conn.execute("DELETE FROM blocked_anon WHERE blocker_id=? AND blocked_id=?", (blocker_id, blocked_id))
            self.conn.commit()

    def is_anon_blocked(self, blocker_id, blocked_id):
        with self._lock:
            row = self.conn.execute("SELECT 1 FROM blocked_anon WHERE blocker_id=? AND blocked_id=?", (blocker_id, blocked_id)).fetchone()
            return row is not None

    def search_users(self, query):
        with self._lock:
            if query.isdigit(): row = self.conn.execute("SELECT * FROM users WHERE user_id=?", (int(query),)).fetchone(); return [dict(row)] if row else []
            like = f"%{query}%"
            return [dict(r) for r in self.conn.execute("SELECT * FROM users WHERE first_name LIKE ? OR username LIKE ?", (like, like)).fetchall()]

    def get_active_users(self, include_blocked=False):
        with self._lock:
            if include_blocked:
                return [dict(r) for r in self.conn.execute("SELECT user_id FROM users").fetchall()]
            return [dict(r) for r in self.conn.execute("SELECT user_id FROM users WHERE blocked=0 OR blocked IS NULL").fetchall()]

    def get_user_detail(self, user_id):
        with self._lock:
            user = self.conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
            if not user: return None
            total_clicks = self.conn.execute("SELECT COUNT(*) as cnt FROM clicks WHERE owner_id=?", (user_id,)).fetchone()['cnt']
            snoop_count = self.conn.execute("SELECT COUNT(DISTINCT clicker_id) as cnt FROM clicks WHERE owner_id=?", (user_id,)).fetchone()['cnt']
            vip_row = self.conn.execute("SELECT expire_date FROM vip WHERE user_id=?", (user_id,)).fetchone()
            vip_status = "غیرفعال"
            if vip_row:
                try:
                    if datetime.datetime.strptime(vip_row['expire_date'], "%Y-%m-%d").date() >= datetime.date.today():
                        vip_status = "فعال"
                except (ValueError, TypeError):
                    pass
            # v3.24.7: منشا VIP — خلاصهٔ یک‌سطری از ردپاهای دیتابیس
            vip_sources = []
            try:
                _s = self.conn.execute(
                    "SELECT type, SUM(days) sd FROM transactions WHERE user_id=? AND days>0 GROUP BY type ORDER BY sd DESC",
                    (user_id,)).fetchall()
                _src_fa = {"vip": "خرید", "gift_vip": "هدیه", "trial_vip": "هدیهٔ ورود",
                           "challenge_vip": "چالش", "admin_vip": "ادمین", "admin_vip_remove": "کسر ادمین"}
                for _r in _s:
                    vip_sources.append(f"{_src_fa.get(_r['type'], _r['type'])} {_r['sd']}")
                _sc = self.conn.execute("SELECT COUNT(*) c FROM clicks WHERE owner_id=? AND is_new_user=1", (user_id,)).fetchone()['c']
                if _sc:
                    vip_sources.append(f"دعوت {_sc}")
            except Exception:
                pass
            return {'user': dict(user), 'total_clicks': total_clicks, 'snoop_count': snoop_count,
                    'vip_status': vip_status, 'vip_expire': vip_row['expire_date'] if vip_row else None,
                    'vip_sources': " + ".join(vip_sources)}

    _ADMIN_USERLIST_BASE = (
        "SELECT u.*, COALESCE(sc.cnt, 0) as snoop_count "
        "FROM users u LEFT JOIN ("
        "SELECT owner_id, COUNT(DISTINCT clicker_id) AS cnt FROM clicks GROUP BY owner_id"
        ") sc ON sc.owner_id = u.user_id "
    )

    def get_admin_userlist(self, sort="invites", offset=0, limit=10):
        """v3.20: لیست کاربران پنل ادمین با دو مرتب‌سازی:
        invites = بیشترین فضول یکتا (نزولی) | new = جدیدترین کاربر (نزولی).
        هر دو با یک GROUP BY یک‌مرحله‌ای + ایندکس مرکب (هزینه O(clicks)) — بدون فریز."""
        with self._lock:
            if sort == "new":
                q = (self._ADMIN_USERLIST_BASE +
                     "ORDER BY (u.created_at IS NULL) ASC, u.created_at DESC, "
                     "u.user_id DESC LIMIT ? OFFSET ?")
            else:
                q = (self._ADMIN_USERLIST_BASE +
                     "ORDER BY COALESCE(sc.cnt, 0) DESC, u.user_id ASC LIMIT ? OFFSET ?")
            return [dict(r) for r in self.conn.execute(q, (limit, offset)).fetchall()]

    def get_all_users_paginated(self, offset=0, limit=20):
        """سازگاری قدیمی — معادل get_admin_userlist(sort='invites')."""
        return self.get_admin_userlist("invites", offset, limit)

    def count_all_users(self):
        with self._lock:
            return self.conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()['cnt']

    def add_transaction(self, user_id, ttype, amount, days=0):
        with self._lock:
            self.conn.execute("INSERT INTO transactions (user_id, type, amount, days) VALUES (?,?,?,?)", (user_id, ttype, amount, days))
            self.conn.commit()

    def get_transactions_paginated(self, offset=0, limit=10):
        with self._lock:
            return [dict(r) for r in self.conn.execute("SELECT * FROM transactions ORDER BY timestamp DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()]

    def count_transactions(self):
        with self._lock:
            return self.conn.execute("SELECT COUNT(*) as cnt FROM transactions").fetchone()['cnt']

    def get_most_active_owners_by_unique(self, limit=10):
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT c.owner_id, u.first_name, COUNT(DISTINCT c.clicker_id) as cnt FROM clicks c JOIN users u ON c.owner_id=u.user_id GROUP BY c.owner_id ORDER BY cnt DESC LIMIT ?", (limit,)).fetchall()]

    _LB_NAME = "COALESCE(NULLIF(u.display_name, ''), u.first_name)"

    def get_leaderboard_top(self, limit=10):
        """v3.20: نام نمایشی دلخواه (display_name) در صورت تعیین، وگرنه نام اکانت."""
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                f"SELECT c.owner_id, {self._LB_NAME} AS first_name, COUNT(DISTINCT c.clicker_id) as cnt "
                "FROM clicks c JOIN users u ON c.owner_id=u.user_id "
                "WHERE u.hide_leaderboard = 0 AND u.blocked = 0 "
                "GROUP BY c.owner_id ORDER BY cnt DESC LIMIT ?", (limit,)).fetchall()]

    def get_leaderboard_top_week(self, limit=10):
        """v3.9: برترین‌های ۷ روز اخیر (فضول یکتا) — v3.20: با نام نمایشی"""
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                f"SELECT c.owner_id, {self._LB_NAME} AS first_name, COUNT(DISTINCT c.clicker_id) as cnt "
                "FROM clicks c JOIN users u ON c.owner_id=u.user_id "
                "WHERE u.hide_leaderboard = 0 AND u.blocked = 0 "
                "AND c.clicked_at >= datetime('now', '-7 days') "
                "GROUP BY c.owner_id ORDER BY cnt DESC LIMIT ?", (limit,)).fetchall()]

    def get_user_rank_by_distinct(self, user_id):
        with self._lock:
            user_cnt = self.get_distinct_snoop_count(user_id)
            row = self.conn.execute(
                "SELECT COUNT(*) as higher FROM ("
                "SELECT owner_id, COUNT(DISTINCT clicker_id) as cnt FROM clicks GROUP BY owner_id"
                ") WHERE cnt > ?", (user_cnt,)).fetchone()
            return row['higher'] + 1

    def get_vip_stats(self):
        with self._lock:
            active = self.conn.execute("SELECT COUNT(*) as cnt FROM vip WHERE expire_date >= date('now')").fetchone()['cnt']
            expired = self.conn.execute("SELECT COUNT(*) as cnt FROM vip WHERE expire_date < date('now')").fetchone()['cnt']
            return active, expired

    def add_anon_log(self, sender, receiver, text):
        with self._lock:
            self.conn.execute("INSERT INTO anon_logs (sender_id, receiver_id, text) VALUES (?,?,?)", (sender, receiver, text))
            self.conn.commit()

    def get_anon_logs_paginated(self, offset=0, limit=10):
        with self._lock:
            return [dict(r) for r in self.conn.execute("SELECT * FROM anon_logs ORDER BY timestamp DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()]

    def count_anon_logs(self):
        with self._lock:
            return self.conn.execute("SELECT COUNT(*) as cnt FROM anon_logs").fetchone()['cnt']

    def create_gift_code(self, code, days, max_uses):
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO gift_codes (code, days, max_uses, used_count) VALUES (?, ?, ?, 0)", (code, days, max_uses))
            self.conn.commit()

    # اصلاح بحرانی ۲: redeem_gift اتمی بدون commit اضافی در add_vip
    def redeem_gift(self, code, user_id):
        with self._lock:
            row = self.conn.execute("SELECT * FROM gift_codes WHERE code=?", (code,)).fetchone()
            if not row: return False, "کد نامعتبر است."
            if row['used_count'] >= row['max_uses']: return False, "ظرفیت استفاده از این کد به پایان رسیده."
            usage = self.conn.execute("SELECT 1 FROM gift_usage WHERE code=? AND user_id=?", (code, user_id)).fetchone()
            if usage: return False, "شما قبلاً این کد را استفاده کرده‌اید."
            # افزایش مصرف
            self.conn.execute("UPDATE gift_codes SET used_count = used_count + 1 WHERE code=?", (code,))
            # ثبت استفاده
            self.conn.execute("INSERT INTO gift_usage (code, user_id) VALUES (?,?)", (code, user_id))
            # اعمال مستقیم VIP (بدون add_vip که commit جداگانه دارد)
            days = row['days']
            current = self.conn.execute("SELECT expire_date FROM vip WHERE user_id=?", (user_id,)).fetchone()
            if current:
                try:
                    cur_exp = datetime.datetime.strptime(current['expire_date'], "%Y-%m-%d").date()
                    if cur_exp >= datetime.date.today():
                        new_exp = cur_exp + datetime.timedelta(days=days)
                    else:
                        new_exp = datetime.date.today() + datetime.timedelta(days=days)
                except:
                    new_exp = datetime.date.today() + datetime.timedelta(days=days)
                self.conn.execute("UPDATE vip SET expire_date=? WHERE user_id=?", (new_exp.isoformat(), user_id))
            else:
                new_exp = datetime.date.today() + datetime.timedelta(days=days)
                self.conn.execute("INSERT INTO vip (user_id, expire_date) VALUES (?,?)", (user_id, new_exp.isoformat()))
            self.conn.commit()
            return True, days

    def get_all_gift_codes(self):
        with self._lock:
            return [dict(r) for r in self.conn.execute("SELECT * FROM gift_codes ORDER BY created_at DESC").fetchall()]

    def delete_gift_code(self, code):
        """حذف یک کد هدیه (و استفاده‌های مربوط به آن)."""
        with self._lock:
            self.conn.execute("DELETE FROM gift_usage WHERE code=?", (code,))
            self.conn.execute("DELETE FROM gift_codes WHERE code=?", (code,))
            self.conn.commit()

    def is_new_user(self, user_id):
        with self._lock:
            return self.conn.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone() is None

    def set_user_source(self, user_id, source):
        with self._lock:
            self.conn.execute("UPDATE users SET source=? WHERE user_id=?", (source, user_id))
            self.conn.commit()

    def upsert_user_basic(self, user_id, first_name, username, source=None):
        """ثبت/به‌روزرسانی کاربر. مهم: source همیشه UPDATE می‌شه (حتی اگه کاربر از قبل وجود داشته باشه)."""
        with self._lock:
            now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if source:
                # اول INSERT (اگه کاربر جدید باشه)
                self.conn.execute(
                    "INSERT OR IGNORE INTO users (user_id, first_name, username, source, created_at) VALUES (?,?,?,?,?)",
                    (user_id, first_name, username, source, now))
                # بعد UPDATE صریح source (برای کاربرانی که از قبل ثبت شدن ولی source خالی دارن)
                self.conn.execute(
                    "UPDATE users SET source=? WHERE user_id=? AND (source IS NULL OR source='' OR source='organic')",
                    (source, user_id))
            else:
                self.conn.execute(
                    "INSERT OR IGNORE INTO users (user_id, first_name, username, created_at) VALUES (?,?,?,?)",
                    (user_id, first_name, username, now))
            self.conn.commit()

    def get_user_basic(self, user_id):
        with self._lock:
            row = self.conn.execute("SELECT first_name, username FROM users WHERE user_id=?", (user_id,)).fetchone()
            return dict(row) if row else None

    def get_all_vips(self):
        with self._lock:
            return [dict(r) for r in self.conn.execute("SELECT user_id, expire_date FROM vip ORDER BY expire_date").fetchall()]

    def get_active_vips_paginated(self, offset=0, limit=20):
        """گرفتن VIPهای فعال (expire_date >= today) با صفحه‌بندی + نام کاربر."""
        with self._lock:
            q = '''SELECT v.user_id, v.expire_date, u.first_name
                   FROM vip v
                   LEFT JOIN users u ON v.user_id = u.user_id
                   WHERE v.expire_date >= date('now')
                   ORDER BY v.expire_date DESC
                   LIMIT ? OFFSET ?'''
            return [dict(r) for r in self.conn.execute(q, (limit, offset)).fetchall()]

    def count_active_vips(self):
        with self._lock:
            return self.conn.execute("SELECT COUNT(*) as c FROM vip WHERE expire_date >= date('now')").fetchone()['c']

    def log_callback_click(self, callback_data):
        """ثبت آمار کلیک روی یک دکمه اینلاین."""
        try:
            with self._lock:
                self.conn.execute(
                    "INSERT INTO callback_stats (callback_data, click_count, last_clicked) VALUES (?, 1, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(callback_data) DO UPDATE SET click_count = click_count + 1, last_clicked = CURRENT_TIMESTAMP",
                    (callback_data,)
                )
                self.conn.commit()
        except: pass

    # ====== v3.24.4: تلمتری استفاده — نمودار ساعت پیک، مسیرهای کند، پرمصرف‌ها ======
    def log_usage_event(self, kind, label, duration_ms=0):
        """ثبت یک رویداد استفاده (دکمه/پیام/دستور) با مدت پردازش.
        سبک: یک INSERT + commit هر ۵۰ رویداد (فلاش دسته‌ای) — فشار روی قفل حداقلی."""
        try:
            with self._lock:
                self.conn.execute(
                    "INSERT INTO usage_events (kind, label, duration_ms) VALUES (?,?,?)",
                    (kind, label[:120], int(duration_ms)))
                # فلاش دسته‌ای: شمارندهٔ داخلی هر ۵۰ رویداد یکبار commit می‌کند
                self._usage_pending = getattr(self, "_usage_pending", 0) + 1
                if self._usage_pending >= 50:
                    self.conn.commit()
                    self._usage_pending = 0
        except Exception:
            pass

    def usage_hourly_report(self, hours=24):
        """گزارش ساعتی استفاده — بار هر ساعت به تفکیک نوع رویداد (برای یافتن ساعت پیک)."""
        with self._lock:
            try:
                return [dict(r) for r in self.conn.execute(
                    "SELECT strftime('%m-%d %H', ts) AS hour, kind, COUNT(*) AS n, "
                    "CAST(AVG(duration_ms) AS INTEGER) AS avg_ms, MAX(duration_ms) AS max_ms "
                    "FROM usage_events WHERE ts >= datetime('now', ?) "
                    "GROUP BY hour, kind ORDER BY hour", (f'-{int(hours)} hours',)).fetchall()]
            except Exception:
                return []

    def usage_top_labels(self, hours=24, limit=15):
        """پرمصرف‌ترین مسیرها (دکمه‌ها/دستورها) در بازه — با میانگین و بیشینهٔ زمان پاسخ."""
        with self._lock:
            try:
                return [dict(r) for r in self.conn.execute(
                    "SELECT kind, label, COUNT(*) AS n, "
                    "CAST(AVG(duration_ms) AS INTEGER) AS avg_ms, MAX(duration_ms) AS max_ms "
                    "FROM usage_events WHERE ts >= datetime('now', ?) "
                    "GROUP BY kind, label ORDER BY n DESC LIMIT ?",
                    (f'-{int(hours)} hours', int(limit))).fetchall()]
            except Exception:
                return []

    def usage_slow_paths(self, hours=24, min_ms=2000, limit=15):
        """کندترین مسیرهای پردازش — میانگین بالای min_ms یا تک‌رویدادهای خیلی کند."""
        with self._lock:
            try:
                return [dict(r) for r in self.conn.execute(
                    "SELECT kind, label, COUNT(*) AS n, "
                    "CAST(AVG(duration_ms) AS INTEGER) AS avg_ms, MAX(duration_ms) AS max_ms "
                    "FROM usage_events WHERE ts >= datetime('now', ?) AND duration_ms >= ? "
                    "GROUP BY kind, label ORDER BY max_ms DESC LIMIT ?",
                    (f'-{int(hours)} hours', int(min_ms), int(limit))).fetchall()]
            except Exception:
                return []

    def usage_error_counts(self, hours=24):
        """شمارش خطاها در بازه (برای مقایسهٔ نرخ خطا بین ساعات پیک و عادی)."""
        with self._lock:
            try:
                return [dict(r) for r in self.conn.execute(
                    "SELECT strftime('%m-%d %H', ts) AS hour, COUNT(*) AS n "
                    "FROM usage_events WHERE ts >= datetime('now', ?) AND kind='error' "
                    "GROUP BY hour ORDER BY hour", (f'-{int(hours)} hours',)).fetchall()]
            except Exception:
                return []

    def usage_prune(self, days=7):
        """حذف رویدادهای قدیمی‌تر از N روز — جدول هرگز بی‌رویه رشد نمی‌کند."""
        try:
            with self._lock:
                self.conn.execute("DELETE FROM usage_events WHERE ts < datetime('now', ?)",
                                  (f'-{int(days)} days',))
                self.conn.commit()
        except Exception:
            pass

    def get_callback_stats(self, limit=20):
        """گرفتن پراستفاده‌ترین دکمه‌ها."""
        with self._lock:
            try:
                return [dict(r) for r in self.conn.execute(
                    "SELECT callback_data, click_count, last_clicked FROM callback_stats "
                    "ORDER BY click_count DESC LIMIT ?", (limit,)
                ).fetchall()]
            except:
                return []

    def get_recent_activities(self, user_id, limit=5):
        """گرفتن آخرین فعالیت‌های کاربر از داده‌های موجود (بدون جدول جدید).
        منابع: clicks (دریافتی), transactions (vip/gift_vip), xp_bonuses (تسک‌ها)."""
        activities = []
        with self._lock:
            # آخرین کلیک‌های دریافتی (max 2)
            rows = self.conn.execute(
                "SELECT clicker_name, clicked_at FROM clicks WHERE owner_id=? "
                "ORDER BY clicked_at DESC LIMIT 2", (user_id,)
            ).fetchall()
            for r in rows:
                name = r['clicker_name'] or 'ناشناس'
                activities.append({
                    'type': 'click',
                    'name': name,
                    'timestamp': r['clicked_at']
                })

            # آخرین خرید VIP (max 1)
            rows = self.conn.execute(
                "SELECT days, timestamp FROM transactions WHERE user_id=? AND type='vip' "
                "ORDER BY timestamp DESC LIMIT 1", (user_id,)
            ).fetchall()
            for r in rows:
                activities.append({
                    'type': 'vip',
                    'days': r['days'],
                    'timestamp': r['timestamp']
                })

            # آخرین هدیه VIP (max 1)
            rows = self.conn.execute(
                "SELECT days, timestamp FROM transactions WHERE user_id=? AND type='gift_vip' "
                "ORDER BY timestamp DESC LIMIT 1", (user_id,)
            ).fetchall()
            for r in rows:
                activities.append({
                    'type': 'gift',
                    'days': r['days'],
                    'timestamp': r['timestamp']
                })

            # آخرین تسک‌های تکمیل‌شده (max 1)
            rows = self.conn.execute(
                "SELECT bonus_type, awarded_at FROM xp_bonuses WHERE user_id=? AND bonus_type LIKE 'task_%' "
                "ORDER BY awarded_at DESC LIMIT 1", (user_id,)
            ).fetchall()
            for r in rows:
                task_id = r['bonus_type'].replace('task_', '')
                task = tasks_module.get_task_by_id(task_id)
                if task:
                    activities.append({
                        'type': 'task',
                        'task_name': task['name'],
                        'timestamp': r['awarded_at']
                    })

        # مرتب‌سازی بر اساس timestamp (نزولی)
        activities.sort(key=lambda x: x['timestamp'] or '', reverse=True)
        return activities[:limit]

    def mute_snoop(self, owner_id, clicker_id):
        with self._lock:
            self.conn.execute("INSERT OR IGNORE INTO muted_snoops (owner_id, clicker_id) VALUES (?,?)", (owner_id, clicker_id))
            self.conn.commit()

    def unmute_snoop(self, owner_id, clicker_id):
        with self._lock:
            self.conn.execute("DELETE FROM muted_snoops WHERE owner_id=? AND clicker_id=?", (owner_id, clicker_id))
            self.conn.commit()

    def is_snoop_muted(self, owner_id, clicker_id):
        with self._lock:
            row = self.conn.execute("SELECT 1 FROM muted_snoops WHERE owner_id=? AND clicker_id=?", (owner_id, clicker_id)).fetchone()
            return row is not None

    def get_user_invite_count(self, user_id):
        with self._lock:
            return self.conn.execute("SELECT COUNT(*) as cnt FROM clicks WHERE owner_id=? AND is_new_user=1", (user_id,)).fetchone()['cnt']

    def get_user_purchase_count(self, user_id):
        with self._lock:
            return self.conn.execute("SELECT COUNT(*) as cnt FROM transactions WHERE user_id=? AND type='vip'", (user_id,)).fetchone()['cnt']

    def get_user_gift_count(self, user_id):
        with self._lock:
            return self.conn.execute("SELECT COUNT(*) as cnt FROM transactions WHERE user_id=? AND type='gift_vip'", (user_id,)).fetchone()['cnt']

    def get_distinct_snoop_count(self, user_id):
        with self._lock:
            return self.conn.execute("SELECT COUNT(DISTINCT clicker_id) as cnt FROM clicks WHERE owner_id=?", (user_id,)).fetchone()['cnt']

    def get_week_distinct_snoop_count(self, user_id):
        """v3.9.4: فضول یکتای ۷ روز اخیر کاربر — هم‌پنجرهٔ get_leaderboard_top_week."""
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(DISTINCT clicker_id) as cnt FROM clicks "
                "WHERE owner_id=? AND clicked_at >= datetime('now', '-7 days')",
                (user_id,)).fetchone()
            return row['cnt'] if row else 0

    def get_week_rank_by_distinct(self, user_id):
        """v3.11: رتبهٔ کاربر در پنجرهٔ ۷روزه — هم‌سنجهٔ تابلوی هفتگی."""
        with self._lock:
            row_u = self.conn.execute(
                "SELECT COUNT(DISTINCT clicker_id) as cnt FROM clicks "
                "WHERE owner_id=? AND clicked_at >= datetime('now', '-7 days')",
                (user_id,)).fetchone()
            user_cnt = row_u['cnt'] if row_u else 0
            row = self.conn.execute(
                "SELECT COUNT(*) as higher FROM ("
                "SELECT owner_id, COUNT(DISTINCT clicker_id) as cnt FROM clicks "
                "WHERE clicked_at >= datetime('now', '-7 days') GROUP BY owner_id"
                ") WHERE cnt > ?", (user_cnt,)).fetchone()
            return (row['higher'] + 1) if row else 1

    def count_week_board_owners(self):
        """v3.11: تعداد صاحبان تلهٔ فعال در پنجرهٔ ۷روزه."""
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*) as c FROM (SELECT owner_id FROM clicks "
                "WHERE clicked_at >= datetime('now', '-7 days') GROUP BY owner_id)").fetchone()
            return row['c'] if row else 0

    def clean_old_anon_logs(self, days=30):
        with self._lock:
            self.conn.execute("DELETE FROM anon_logs WHERE julianday('now') - julianday(timestamp) > ?", (days,))
            self.conn.commit()

    def clean_old_callback_stats(self, days=120):
        """v3.23: پاکسازی دکمه‌های لمس‌نشده — جلوگیری از رشد بی‌رویهٔ callback_stats."""
        with self._lock:
            self.conn.execute("DELETE FROM callback_stats WHERE julianday('now') - julianday(last_clicked) > ?", (days,))
            self.conn.commit()

    def clean_old_channel_joins(self, days=365):
        """v3.23: پاکسازی عضویت‌های خیلی قدیم (آمار «کل عضویت» روی یک سال اخیر می‌ماند)."""
        with self._lock:
            self.conn.execute("DELETE FROM channel_joins WHERE julianday('now') - julianday(joined_at) > ?", (days,))
            self.conn.commit()

    def get_daily_stats(self):
        with self._lock:
            today = datetime.date.today().isoformat()
            yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

            # --- کاربران ---
            total_users = self.conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()['cnt']
            new_today = self.conn.execute("SELECT COUNT(*) as cnt FROM users WHERE date(created_at)=?", (today,)).fetchone()['cnt']
            new_yesterday = self.conn.execute("SELECT COUNT(*) as cnt FROM users WHERE date(created_at)=?", (yesterday,)).fetchone()['cnt']
            active_today = self.conn.execute("SELECT COUNT(DISTINCT clicker_id) as cnt FROM clicks WHERE date(clicked_at)=?", (today,)).fetchone()['cnt']

            # نرخ بازگشت: کاربران فعال امروز که حداقل یک بار قبل از امروز هم کلیک کرده‌اند
            returning_today = self.conn.execute(
                "SELECT COUNT(DISTINCT clicker_id) as cnt FROM clicks WHERE date(clicked_at)=? AND clicker_id IN (SELECT DISTINCT clicker_id FROM clicks WHERE date(clicked_at) < ?)",
                (today, today)
            ).fetchone()['cnt']
            return_rate = f"{int((returning_today / active_today * 100) if active_today else 0)}%"

            # --- منابع ورود (جدید) ---
            organic = self.conn.execute("SELECT COUNT(*) as cnt FROM users WHERE source='organic'").fetchone()['cnt']
            welcome = self.conn.execute("SELECT COUNT(*) as cnt FROM users WHERE source='welcome'").fetchone()['cnt']
            referral = self.conn.execute("SELECT COUNT(*) as cnt FROM users WHERE source='referral'").fetchone()['cnt']

            # --- کلیک‌ها ---
            total_clicks = self.conn.execute("SELECT COUNT(*) as cnt FROM clicks").fetchone()['cnt']
            distinct_clickers = self.conn.execute("SELECT COUNT(DISTINCT clicker_id) as cnt FROM clicks").fetchone()['cnt']
            trap_owners = self.conn.execute("SELECT COUNT(DISTINCT owner_id) as cnt FROM clicks").fetchone()['cnt']
            # میانگین کلیک ۷ روز
            avg_7 = self.conn.execute(
                "SELECT ROUND(COUNT(*) / 7.0, 1) as cnt FROM clicks WHERE clicked_at >= date('now','-7 days')"
            ).fetchone()['cnt']

            # --- VIP و درآمد ---
            active_vip = self.conn.execute("SELECT COUNT(*) as cnt FROM vip WHERE expire_date >= date('now')").fetchone()['cnt']
            total_revenue = self.conn.execute("SELECT COALESCE(SUM(amount),0) as cnt FROM transactions WHERE type IN ('vip','gift_vip')").fetchone()['cnt']
            revenue_today = self.conn.execute("SELECT COALESCE(SUM(amount),0) as cnt FROM transactions WHERE date(timestamp)=? AND type IN ('vip','gift_vip')", (today,)).fetchone()['cnt']
            tx_today = self.conn.execute("SELECT COUNT(*) as cnt FROM transactions WHERE date(timestamp)=? AND type IN ('vip','gift_vip')", (today,)).fetchone()['cnt']
            tx_total = self.conn.execute("SELECT COUNT(*) as cnt FROM transactions WHERE type IN ('vip','gift_vip')").fetchone()['cnt']

            # --- کدهای هدیه ---
            gift_created = self.conn.execute("SELECT COUNT(*) as cnt FROM gift_codes").fetchone()['cnt']
            gift_used = self.conn.execute("SELECT COALESCE(SUM(used_count),0) as cnt FROM gift_codes").fetchone()['cnt']

            # --- پیام‌های ناشناس ---
            anon_total = self.conn.execute("SELECT COUNT(*) as cnt FROM anon_logs").fetchone()['cnt']

            # --- بلاک‌شده‌ها ---
            total_banned = self.conn.execute("SELECT COUNT(*) as cnt FROM users WHERE blocked=1").fetchone()['cnt']
            blocked_bot_count = self.conn.execute("SELECT COUNT(*) as cnt FROM users WHERE blocked_bot=1").fetchone()['cnt']

            # --- v3.5: کلیک امروز ---
            clicks_today = self.conn.execute("SELECT COUNT(*) as cnt FROM clicks WHERE date(clicked_at)=?", (today,)).fetchone()['cnt']

            # --- v3.5: باز کردن پروفایل (reveal) ---
            reveals_total = 0
            reveal_revenue = 0
            try:
                reveals_total = self.conn.execute("SELECT COUNT(*) as cnt FROM reveals").fetchone()['cnt']
                reveal_revenue = self.conn.execute(
                    "SELECT COALESCE(SUM(amount),0) as cnt FROM transactions WHERE type='reveal'").fetchone()['cnt']
            except sqlite3.OperationalError:
                pass

            # --- v3.5: استریک فعال امروز (استریک ≥۲ که امروز زنده نگه داشته شده) ---
            streak_active = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM users WHERE streak_count >= 2 AND last_streak_date=?", (today,)
            ).fetchone()['cnt']

            # --- v3.5: کاربران جدیدِ امروز که همین امروز فعال شدند (حداقل یک کلیک) ---
            new_activated_today = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM users u WHERE date(u.created_at)=? "
                "AND EXISTS (SELECT 1 FROM clicks c WHERE c.clicker_id=u.user_id AND date(c.clicked_at)=?)",
                (today, today)
            ).fetchone()['cnt']

            # --- کانال‌های اجباری (تعداد و مجموع عضویت) ---
            channels = self.get_all_forced_channels()
            channels_count = len(channels)
            total_joins = sum(self.get_channel_join_count(ch['channel_id']) for ch in channels)

            return {
                'total_users': total_users,
                'new_today': new_today,
                'new_yesterday': new_yesterday,
                'active_today': active_today,
                'return_rate': return_rate,
                'organic': organic,
                'welcome': welcome,
                'referral': referral,
                'total_clicks': total_clicks,
                'distinct_clickers': distinct_clickers,
                'trap_owners': trap_owners,
                'avg_7': avg_7,
                'active_vip': active_vip,
                'total_revenue': total_revenue,
                'revenue_today': revenue_today,
                'tx_today': tx_today,
                'tx_total': tx_total,
                'gift_created': gift_created,
                'gift_used': gift_used,
                'anon_total': anon_total,
                'total_banned': total_banned,
                'blocked_bot_count': blocked_bot_count,
                'channels_count': channels_count,
                'total_joins': total_joins,
                'clicks_today': clicks_today,
                'reveals_total': reveals_total,
                'reveal_revenue': reveal_revenue,
                'streak_active': streak_active,
                'new_activated_today': new_activated_today,
            }

    # ---------- v3.23: کش TTL آمارهای سنگین پنل ادمین ----------
    def _cached_stat(self, key, ttl, fn):
        """کش کوتاه‌مدت (پیش‌فرض ۶۰ ثانیه) برای کوئری‌های سنگین — در مقیاس ۵۰۰۰+ کاربر
        باز کردن پنل نباید ده‌ها COUNT/GROUP BY روی کل جدول‌ها بزند (قفل دیتابیس).
        خروجی: (value, computed_at_epoch) — زمان محاسبه برای نمایش صادقانهٔ «بروزرسانی»."""
        now = time.time()
        try:
            ent = self._stats_cache.get(key)
            if ent and (now - ent[0]) < ttl:
                return ent[1], ent[0]
        except Exception:
            pass
        val = fn()
        computed_at = time.time()
        try:
            self._stats_cache[key] = (computed_at, val)
        except Exception:
            pass
        return val, computed_at

    def invalidate_stats_cache(self):
        """بی‌اعتبارسازی کش آمار بعد از تغییرات مهم (پخش، تراکنش، بلاک و...)."""
        try:
            self._stats_cache.clear()
        except Exception:
            pass

    def get_daily_stats_cached(self, ttl=60.0):
        return self._cached_stat("daily_stats", ttl, self.get_daily_stats)

    def get_user_stats_summary_cached(self, ttl=60.0):
        return self._cached_stat("user_stats_summary", ttl, self.get_user_stats_summary)

    def get_bonus_streak_stats_cached(self, ttl=60.0):
        return self._cached_stat("bonus_streak", ttl, self.get_bonus_streak_stats)

    def set_user_mask(self, user_id, emoji, mask_text):
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO user_mask (user_id, emoji, mask_text) VALUES (?,?,?)", (user_id, emoji, mask_text))
            self.conn.commit()

    # ----- سیستم XP و سطح‌بندی -----
    # فرمول: XP لازم برای رفتن از سطح (L-1) به L = 100 × L
    # XP تجمعی تا سطح L = 100 × L × (L+1) / 2
    def get_user_xp(self, user_id):
        with self._lock:
            row = self.conn.execute("SELECT xp FROM users WHERE user_id=?", (user_id,)).fetchone()
            return row['xp'] if row and row['xp'] is not None else 0

    def get_user_level_cached(self, user_id):
        with self._lock:
            row = self.conn.execute("SELECT level_cached FROM users WHERE user_id=?", (user_id,)).fetchone()
            return row['level_cached'] if row and row['level_cached'] is not None else 1

    @staticmethod
    def level_from_xp(xp):
        """محاسبهٔ سطح از روی XP تجمعی."""
        if xp < 100:
            return 1
        # حل: 100×L×(L+1)/2 = xp → L² + L - 2*xp/100 = 0 → L = (-1 + √(1 + 8*xp/100)) / 2
        import math
        L = int((-1 + math.sqrt(1 + 8 * xp / 100)) / 2)
        if L < 1: L = 1
        if L > config.MAX_LEVEL: L = config.MAX_LEVEL
        return L

    @staticmethod
    def xp_for_level(level):
        """XP تجمعی لازم برای رسیدن به سطح level."""
        return 100 * level * (level + 1) // 2

    @staticmethod
    def xp_for_next_level(current_level):
        """XP کل لازم برای رسیدن از سطح فعلی به سطح بعدی."""
        if current_level >= config.MAX_LEVEL:
            return None
        return Database.xp_for_level(current_level + 1)

    def add_xp(self, user_id, amount):
        """افزودن XP به کاربر و به‌روزرسانی level_cached. برمی‌گرداند (xp_new, level_new, level_old)."""
        with self._lock:
            row = self.conn.execute("SELECT xp, level_cached FROM users WHERE user_id=?", (user_id,)).fetchone()
            if not row:
                return 0, 1, 1
            xp_old = row['xp'] if row['xp'] is not None else 0
            level_old = row['level_cached'] if row['level_cached'] is not None else 1
            xp_new = xp_old + amount
            level_new = self.level_from_xp(xp_new)
            self.conn.execute("UPDATE users SET xp=?, level_cached=? WHERE user_id=?", (xp_new, level_new, user_id))
            self.conn.commit()
            return xp_new, level_new, level_old

    def has_bonus(self, user_id, bonus_type):
        with self._lock:
            row = self.conn.execute("SELECT 1 FROM xp_bonuses WHERE user_id=? AND bonus_type=?", (user_id, bonus_type)).fetchone()
            return row is not None

    def award_bonus_xp(self, user_id, bonus_type, amount):
        """اعطای XP یکباره (فقط اولین بار). برمی‌گرداند (awarded: bool, xp_new: int, level_new: int, level_old: int)."""
        with self._lock:
            existing = self.conn.execute("SELECT 1 FROM xp_bonuses WHERE user_id=? AND bonus_type=?", (user_id, bonus_type)).fetchone()
            if existing:
                row = self.conn.execute("SELECT xp, level_cached FROM users WHERE user_id=?", (user_id,)).fetchone()
                return False, (row['xp'] if row else 0), (row['level_cached'] if row else 1), (row['level_cached'] if row else 1)
            self.conn.execute("INSERT OR IGNORE INTO xp_bonuses (user_id, bonus_type) VALUES (?,?)", (user_id, bonus_type))
            xp_old_row = self.conn.execute("SELECT xp, level_cached FROM users WHERE user_id=?", (user_id,)).fetchone()
            xp_old = xp_old_row['xp'] if xp_old_row and xp_old_row['xp'] else 0
            level_old = xp_old_row['level_cached'] if xp_old_row and xp_old_row['level_cached'] else 1
            xp_new = xp_old + amount
            level_new = self.level_from_xp(xp_new)
            self.conn.execute("UPDATE users SET xp=?, level_cached=? WHERE user_id=?", (xp_new, level_new, user_id))
            self.conn.commit()
            return True, xp_new, level_new, level_old

    def touch_daily_active(self, user_id):
        """اگر اولین فعالیت روزانه است، XP روزانه می‌دهد. برمی‌گرداند (got_xp: bool)."""
        with self._lock:
            today = datetime.date.today().isoformat()
            row = self.conn.execute("SELECT last_active_date FROM users WHERE user_id=?", (user_id,)).fetchone()
            if not row:
                return False
            if row['last_active_date'] == today:
                return False
            self.conn.execute("UPDATE users SET last_active_date=? WHERE user_id=?", (today, user_id))
            self.conn.commit()
            return True

    # ====== v3.4: تنظیمات عمومی (settings) ======
    def get_setting(self, key, default=None):
        with self._lock:
            try:
                row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
                return row['value'] if row else default
            except sqlite3.OperationalError:
                return default

    def set_setting(self, key, value):
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
            self.conn.commit()

    def get_setting_int(self, key, default=0):
        try:
            return int(self.get_setting(key, default))
        except (TypeError, ValueError):
            return default

    # ====== v3.4: هدیهٔ ورود (تریال) ======
    def is_trial_given(self, user_id):
        with self._lock:
            row = self.conn.execute("SELECT trial_given FROM users WHERE user_id=?", (user_id,)).fetchone()
            return bool(row and row['trial_given'])

    def set_trial_given(self, user_id):
        with self._lock:
            self.conn.execute("UPDATE users SET trial_given=1 WHERE user_id=?", (user_id,))
            self.conn.commit()

    # ====== v3.4: استریک روزانه ======
    def update_streak(self, user_id):
        """به‌روزرسانی استریک در اولین فعالیت هر روز.
        برمی‌گرداند (streak_new, is_new_day, shield_used).
        v4.4: سپر استریک VIP — اگر فقط یک روز غیبت کرده باشد (last == پریروز)
        و VIP فعال داشته باشد، زنجیره نمی‌شکند و ادامه می‌یابد."""
        # وضعیت VIP بیرون از قفل خوانده می‌شود (جلوگیری از تو در تویی قفل)
        try:
            _vip_now = self.is_vip(user_id)
        except Exception:
            _vip_now = False
        with self._lock:
            today = datetime.date.today()
            yesterday = (today - datetime.timedelta(days=1)).isoformat()
            two_ago = (today - datetime.timedelta(days=2)).isoformat()
            t_iso = today.isoformat()
            row = self.conn.execute("SELECT last_streak_date, streak_count FROM users WHERE user_id=?", (user_id,)).fetchone()
            if not row:
                return 0, False, False
            last = row['last_streak_date']
            cur = row['streak_count'] or 0
            if last == t_iso:
                return cur, False, False  # امروز ثبت شده
            shield_used = False
            if last == yesterday:
                new_streak = cur + 1
            elif last == two_ago and _vip_now:
                # v4.4: سپر استریک VIP — غیبت یک‌روزه زنجیره را نمی‌سوزاند
                new_streak = cur + 1
                shield_used = True
            else:
                new_streak = 1
            self.conn.execute("UPDATE users SET streak_count=?, last_streak_date=? WHERE user_id=?", (new_streak, t_iso, user_id))
            self.conn.commit()
            return new_streak, True, bool(shield_used)

    def get_streak(self, user_id):
        with self._lock:
            row = self.conn.execute("SELECT streak_count, last_streak_date FROM users WHERE user_id=?", (user_id,)).fetchone()
            if not row or not row['last_streak_date']:
                return 0
            # اگر بیش از یک روز فعالیت نداشته، استریک عملاً شکسته ولی عدد را نگه می‌داریم تا با ورود مجدد ریست شود
            return row['streak_count'] or 0

    # ====== v3.4: باز کردن تکی پروفایل ======
    def add_reveal(self, owner_id, clicker_id):
        with self._lock:
            self.conn.execute("INSERT OR IGNORE INTO reveals (owner_id, clicker_id) VALUES (?,?)", (owner_id, clicker_id))
            self.conn.commit()

    def is_revealed(self, owner_id, clicker_id):
        with self._lock:
            row = self.conn.execute("SELECT 1 FROM reveals WHERE owner_id=? AND clicker_id=?", (owner_id, clicker_id)).fetchone()
            return bool(row)

    def count_reveals(self, owner_id):
        with self._lock:
            return self.conn.execute("SELECT COUNT(*) FROM reveals WHERE owner_id=?", (owner_id,)).fetchone()[0]

    def set_last_remind_date(self, user_id):
        with self._lock:
            self.conn.execute("UPDATE users SET last_remind_date=? WHERE user_id=?", (datetime.date.today().isoformat(), user_id))
            self.conn.commit()

    # ====== v3.5: استریک در خطر ======
    def get_streak_at_risk_users(self):
        """کاربرانی که دیروز (مبنای ثبت استریک) فعال بودند ولی امروز هنوز فعالیتی ندارند
        و اگر تا پایان روز کاری نکنند استریک‌شان می‌شکند. امروز تذکر داده نشده باشند."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT user_id, streak_count, first_name FROM users "
                "WHERE (blocked=0 OR blocked IS NULL) AND (blocked_bot=0 OR blocked_bot IS NULL) "
                "AND streak_count >= 1 "
                "AND last_streak_date = date('now', '-1 day') "
                "AND (streak_notified_date IS NULL OR streak_notified_date != date('now'))"
            ).fetchall()
            return [dict(r) for r in rows]

    def set_streak_notified_date(self, user_id):
        with self._lock:
            self.conn.execute("UPDATE users SET streak_notified_date=? WHERE user_id=?",
                              (datetime.date.today().isoformat(), user_id))
            self.conn.commit()

    # ====== v3.6: تله‌های چندگانه ======
    def create_trap(self, owner_id, label):
        """ساخت تلهٔ جدید با کد یکتا — خروجی: trap_code"""
        import random, string as _string
        with self._lock:
            for _ in range(20):
                code = "t" + "".join(random.choice(_string.ascii_lowercase + _string.digits) for _ in range(5))
                if not self.conn.execute("SELECT 1 FROM traps WHERE trap_code=?", (code,)).fetchone():
                    break
            self.conn.execute("INSERT INTO traps (trap_code, owner_id, label) VALUES (?,?,?)",
                              (code, owner_id, label or "تله"))
            self.conn.commit()
            return code

    def get_traps_of(self, owner_id):
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT trap_code, label, created_at FROM traps WHERE owner_id=? ORDER BY created_at ASC", (owner_id,)).fetchall()]

    def get_trap_by_code(self, code):
        with self._lock:
            row = self.conn.execute("SELECT trap_code, owner_id, label FROM traps WHERE trap_code=?", (code,)).fetchone()
            return dict(row) if row else None

    def count_traps(self, owner_id):
        with self._lock:
            return self.conn.execute("SELECT COUNT(*) FROM traps WHERE owner_id=?", (owner_id,)).fetchone()[0]

    def delete_trap(self, trap_code, owner_id):
        with self._lock:
            self.conn.execute("DELETE FROM traps WHERE trap_code=? AND owner_id=?", (trap_code, owner_id))
            self.conn.commit()

    def get_trap_click_counts(self, owner_id):
        """تعداد کلیک و فضول یکتا برای هر trap_code یک صاحب."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT COALESCE(trap_code,'') as trap_code, COUNT(*) as clicks, COUNT(DISTINCT clicker_id) as snoops "
                "FROM clicks WHERE owner_id=? GROUP BY COALESCE(trap_code,'')", (owner_id,)).fetchall()
            return {r['trap_code'] or 'main': {'clicks': r['clicks'], 'snoops': r['snoops']} for r in rows}

    def get_trap_label(self, trap_code):
        if not trap_code:
            return None
        with self._lock:
            row = self.conn.execute("SELECT label FROM traps WHERE trap_code=?", (trap_code,)).fetchone()
            return row['label'] if row else None

    # ====== v4.4: تصمیم «حفظ آبرو / لو رفتن» بازدیدکنندهٔ تله ======
    def create_trap_decision(self, visitor_id, owner_id, trap_code, is_new, repeat_count,
                             display_name, clicker_username, photo_file_id, deadline):
        """ثبت یک تصمیم باز — در بازگشت، id رکورد را می‌دهد."""
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO trap_decisions (visitor_id, owner_id, trap_code, is_new, repeat_count, "
                "display_name, clicker_username, photo_file_id, status, deadline, created_at) "
                "VALUES (?,?,?,?,?,?,?,?, 'pending', ?, ?)",
                (visitor_id, owner_id, trap_code, 1 if is_new else 0, repeat_count,
                 display_name, clicker_username, photo_file_id, deadline,
                 datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")))
            self.conn.commit()
            return cur.lastrowid

    def get_trap_decision(self, decision_id):
        with self._lock:
            row = self.conn.execute("SELECT * FROM trap_decisions WHERE id=?", (decision_id,)).fetchone()
            return dict(row) if row else None

    def get_open_trap_decision(self, visitor_id, owner_id):
        """آخرین تصمیمِ باز (pending/saveface) برای این جفت — ضد دوباره‌سازی هنگام کلیک مجدد."""
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM trap_decisions WHERE visitor_id=? AND owner_id=? AND status IN ('pending','saveface') "
                "ORDER BY id DESC LIMIT 1", (visitor_id, owner_id)).fetchone()
            return dict(row) if row else None

    def count_open_trap_decisions(self, visitor_id):
        """تعداد کل تصمیم‌های بازِ یک بازدیدکننده (هر صاحبی) — برای جلوگیری از موازی‌سازی."""
        with self._lock:
            return self.conn.execute(
                "SELECT COUNT(*) FROM trap_decisions WHERE visitor_id=? AND status IN ('pending','saveface')",
                (visitor_id,)).fetchone()[0]

    def set_trap_decision_status(self, decision_id, status, deadline=None, paid_amount=0):
        """تغییر وضعیت فقط از وضعیتِ پیش‌بینی‌شده — خروجی True یعنی این فراخوانی برندهٔ تغییر شد (اتمیک).
        pending → saveface | saveface → paid | pending/saveface → exposed | * → saved(فقط از paid مسیر پرداخت)"""
        with self._lock:
            row = self.conn.execute("SELECT status FROM trap_decisions WHERE id=?", (decision_id,)).fetchone()
            if not row:
                return False
            cur = row['status']
            allowed = {
                'pending':   {'saveface', 'exposed'},
                'saveface':  {'paid', 'exposed'},
                'paid':      {'saved'},
            }
            if status not in allowed.get(cur, set()):
                return False
            if deadline is not None:
                self.conn.execute("UPDATE trap_decisions SET status=?, deadline=?, resolved_at=NULL WHERE id=?",
                                  (status, deadline, decision_id))
            else:
                self.conn.execute(
                    "UPDATE trap_decisions SET status=?, resolved_at=CASE WHEN ? IN ('saved','exposed') THEN ? ELSE resolved_at END, "
                    "paid_amount=CASE WHEN ?='paid' THEN ? ELSE paid_amount END WHERE id=?",
                    (status, status, datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                     status, paid_amount, decision_id))
            self.conn.commit()
            return True

    def expire_due_trap_decisions(self, now_ts, limit=25):
        """واکشی تصمیم‌های رسیده به ضرب‌الاجل (pending بعد از ۱ دقیقه، saveface بعد از ۳ دقیقه).
        فقط ردیف‌های باز را به exposed تغییر می‌دهد — خروجی: لیست رکوردهای expose‌شده."""
        out = []
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM trap_decisions WHERE status IN ('pending','saveface') AND deadline IS NOT NULL AND deadline<=? "
                "ORDER BY id ASC LIMIT ?", (now_ts, limit)).fetchall()
            for r in rows:
                cur = self.conn.execute(
                    "UPDATE trap_decisions SET status='exposed', resolved_at=? WHERE id=? AND status IN ('pending','saveface')",
                    (datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), r['id']))
                if cur.rowcount == 1:
                    out.append(dict(r))
            if out:
                self.conn.commit()
        return out

    # ====== v3.6: آنالیز حرفه‌ای تله ======
    def get_owner_clicks_window(self, owner_id, days):
        return self.conn.execute(
            "SELECT COUNT(*) as c FROM clicks WHERE owner_id=? AND clicked_at >= date('now', ?)",
            (owner_id, f'-{days} days')).fetchone()['c']

    def get_clicks_by_hour(self, owner_id, days=30):
        with self._lock:
            rows = self.conn.execute(
                "SELECT CAST(strftime('%H', clicked_at) AS INTEGER) as h, COUNT(*) as c "
                "FROM clicks WHERE owner_id=? AND clicked_at >= date('now', ?) GROUP BY h", (owner_id, f'-{days} days')).fetchall()
            return {r['h']: r['c'] for r in rows}

    def get_best_click_day(self, owner_id):
        with self._lock:
            row = self.conn.execute(
                "SELECT date(clicked_at) as d, COUNT(*) as c FROM clicks WHERE owner_id=? GROUP BY d ORDER BY c DESC LIMIT 1",
                (owner_id,)).fetchone()
            return (row['d'], row['c']) if row else (None, 0)

    def get_owner_weekly_compare(self, owner_id):
        """کلیک هفتهٔ جاری (۷ روز اخیر) در برابر هفتهٔ قبل (۷ تا ۱۴ روز پیش)."""
        with self._lock:
            this_w = self.conn.execute(
                "SELECT COUNT(*) as c FROM clicks WHERE owner_id=? AND clicked_at >= date('now','-7 days')",
                (owner_id,)).fetchone()['c']
            last_w = self.conn.execute(
                "SELECT COUNT(*) as c FROM clicks WHERE owner_id=? AND clicked_at >= date('now','-14 days') "
                "AND clicked_at < date('now','-7 days')", (owner_id,)).fetchone()['c']
            return this_w, last_w

    # ====== v3.6: چرخ شانس و هدیهٔ VIP ======
    def set_last_wheel_date(self, user_id, date_iso):
        with self._lock:
            self.conn.execute("UPDATE users SET last_wheel_date=? WHERE user_id=?", (date_iso, user_id))
            self.conn.commit()

    def get_last_wheel_date(self, user_id):
        with self._lock:
            row = self.conn.execute("SELECT last_wheel_date FROM users WHERE user_id=?", (user_id,)).fetchone()
            return row['last_wheel_date'] if row else None

    # ====== v3.17: جایزه روزانه (همهٔ کاربران) ======
    def get_daily_bonus(self, user_id):
        with self._lock:
            row = self.conn.execute("SELECT last_claim, streak, total_claims FROM daily_bonus WHERE user_id=?", (user_id,)).fetchone()
            if not row:
                return {"last_claim": None, "streak": 0, "total_claims": 0}
            return {"last_claim": row['last_claim'],
                    "streak": row['streak'] or 0,
                    "total_claims": row['total_claims'] or 0}

    def set_daily_bonus_claim(self, user_id, date_iso, streak):
        with self._lock:
            self.conn.execute(
                "INSERT INTO daily_bonus (user_id, last_claim, streak, total_claims) VALUES (?,?,?,1) "
                "ON CONFLICT(user_id) DO UPDATE SET last_claim=excluded.last_claim, streak=excluded.streak, total_claims=total_claims+1",
                (user_id, date_iso, streak))
            self.conn.commit()

    def claim_daily_bonus_atomic(self, user_id, today_iso, yesterday_iso):
        """v3.18.1: دریافت اتمیک جایزهٔ روزانه — در برابر دابل‌کلیک/نخ‌های موازی ایمن.
        فقط نخِ اولی که گارد WHERE را پاس کند برنده است (UPSERT گارددار).
        برمی‌گرداند (won, streak_new)."""
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO daily_bonus (user_id, last_claim, streak, total_claims) VALUES (?,?,1,1) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "last_claim=excluded.last_claim, "
                "streak=CASE WHEN daily_bonus.last_claim=? THEN daily_bonus.streak+1 ELSE 1 END, "
                "total_claims=daily_bonus.total_claims+1 "
                "WHERE daily_bonus.last_claim IS NOT ?",
                (user_id, today_iso, yesterday_iso, today_iso))
            if not cur.rowcount:
                return (False, 0)
            row = self.conn.execute("SELECT streak FROM daily_bonus WHERE user_id=?", (user_id,)).fetchone()
            self.conn.commit()
            return (True, ((row['streak'] if row else 1) or 1))

    def claim_wheel_date_atomic(self, user_id, date_iso):
        """v3.18.1: رزرو اتمیک اسپین چرخ — فقط اولین کلیکِ روز برنده است (UPSERT گارددار).
        برمی‌گرداند True اگر این نخ اسپین را از آنِ خود کرد."""
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO users (user_id, last_wheel_date) VALUES (?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET last_wheel_date=excluded.last_wheel_date "
                "WHERE users.last_wheel_date IS NOT ?",
                (user_id, date_iso, date_iso))
            self.conn.commit()
            return cur.rowcount > 0

    def set_last_giftvip_date(self, user_id, date_iso):
        with self._lock:
            self.conn.execute("UPDATE users SET last_giftvip_date=? WHERE user_id=?", (date_iso, user_id))
            self.conn.commit()

    def get_last_giftvip_date(self, user_id):
        with self._lock:
            row = self.conn.execute("SELECT last_giftvip_date FROM users WHERE user_id=?", (user_id,)).fetchone()
            return row['last_giftvip_date'] if row else None

    def transfer_vip_days(self, giver_id, receiver_id, days):
        """انتقال روزهای VIP از giver به receiver.
        شرط: بعد از انتقال حداقل ۱ روز برای giver بماند.
        خروجی: (ok, giver_days_left یا پیام خطا)"""
        with self._lock:
            grow = self.conn.execute("SELECT expire_date FROM vip WHERE user_id=?", (giver_id,)).fetchone()
            if not grow:
                return False, "no_vip"
            try:
                g_exp = datetime.datetime.strptime(grow['expire_date'], "%Y-%m-%d").date()
            except Exception:
                return False, "no_vip"
            today = datetime.date.today()
            if g_exp < today:
                return False, "no_vip"
            remaining = (g_exp - today).days
            if remaining <= days:  # بعد از هدیه باید >= 1 روز بماند
                return False, "not_enough"
            new_exp = g_exp - datetime.timedelta(days=days)
            self.conn.execute("UPDATE vip SET expire_date=? WHERE user_id=?", (new_exp.isoformat(), giver_id))
            # گیرنده
            rrow = self.conn.execute("SELECT expire_date FROM vip WHERE user_id=?", (receiver_id,)).fetchone()
            if rrow:
                try:
                    r_exp = datetime.datetime.strptime(rrow['expire_date'], "%Y-%m-%d").date()
                    if r_exp >= today:
                        r_new = r_exp + datetime.timedelta(days=days)
                    else:
                        r_new = today + datetime.timedelta(days=days)
                except Exception:
                    r_new = today + datetime.timedelta(days=days)
                self.conn.execute("UPDATE vip SET expire_date=? WHERE user_id=?", (r_new.isoformat(), receiver_id))
            else:
                r_new = today + datetime.timedelta(days=days)
                self.conn.execute("INSERT INTO vip (user_id, expire_date) VALUES (?,?)", (receiver_id, r_new.isoformat()))
            self.conn.commit()
            return True, (new_exp - today).days

    # ====== v3.4: چالش شکارچی روز ======
    def get_top_hunters_day(self, date_iso, limit=10):
        """برترین شکارچیان یک روز مشخص — بر اساس تعداد فضول (کلیک‌کنندهٔ یکتا)."""
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT c.owner_id, u.first_name, COUNT(DISTINCT c.clicker_id) as snoops "
                "FROM clicks c JOIN users u ON c.owner_id=u.user_id "
                "WHERE date(c.clicked_at)=? AND (u.blocked=0 OR u.blocked IS NULL) "
                "GROUP BY c.owner_id ORDER BY snoops DESC LIMIT ?", (date_iso, limit)).fetchall()]

    # ====== v3.18: چالش فضول‌گیر برتر — شمارش در بازهٔ زمانی (فقط فضول‌های جدید) ======
    def get_top_hunters_window(self, start_utc, end_utc, limit=10):
        """برترین‌های چالش در بازهٔ [start_utc, end_utc) — فقط فضول‌های جدید (is_new_user=1).
        هر کاربرِ جدید فقط یک‌بار (برای اولین صاحب تله‌ای که گرفته) شمرده می‌شود.
        مرتب‌سازی ثانویه: زودتر که اولین فضولش را گرفته بالا می‌آید (پایداری نمایش)."""
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT c.owner_id, u.first_name, COUNT(DISTINCT c.clicker_id) as snoops, "
                "MIN(c.clicked_at) as first_at "
                "FROM clicks c JOIN users u ON c.owner_id=u.user_id "
                "WHERE c.is_new_user=1 AND c.clicked_at>=? AND c.clicked_at<? "
                "AND (u.blocked=0 OR u.blocked IS NULL) "
                "GROUP BY c.owner_id ORDER BY snoops DESC, first_at ASC LIMIT ?",
                (start_utc, end_utc, limit)).fetchall()]

    def get_challenge_score(self, user_id, start_utc, end_utc):
        """امتیاز زندهٔ یک کاربر در بازهٔ چالش (تعداد فضول‌های جدید گرفته‌شده)."""
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(DISTINCT clicker_id) as cnt FROM clicks "
                "WHERE owner_id=? AND is_new_user=1 AND clicked_at>=? AND clicked_at<?",
                (user_id, start_utc, end_utc)).fetchone()
            return row['cnt'] if row else 0

    # ----- v3.21: آمار کاربران + برترین‌های روز/هفته/ماه -----
    def get_top_users_window(self, start_iso, offset=0, limit=10):
        """برترین کاربران از <start_iso> تا الان — بر اساس فضول یکتای جدید (is_new_user=1).
        با نام نمایشی (COALESCE display_name) و حذف مخفی‌ها/مسدودها؛ به‌همراه تعداد کل
        برای صفحه‌بندی. دقیقاً همان متریک چالش/لیدربورد هفته است."""
        with self._lock:
            base = ("FROM clicks c JOIN users u ON c.owner_id=u.user_id "
                    "WHERE c.is_new_user=1 AND c.clicked_at>=? "
                    "AND u.hide_leaderboard=0 AND (u.blocked=0 OR u.blocked IS NULL)")
            rows = self.conn.execute(
                f"SELECT c.owner_id, {self._LB_NAME} AS first_name, "
                f"COUNT(DISTINCT c.clicker_id) AS cnt {base} "
                f"GROUP BY c.owner_id ORDER BY cnt DESC, c.owner_id ASC LIMIT ? OFFSET ?",
                (start_iso, limit, offset)).fetchall()
            total = self.conn.execute(
                f"SELECT COUNT(*) AS cnt FROM (SELECT c.owner_id {base} GROUP BY c.owner_id)",
                (start_iso,)).fetchone()['cnt']
            return [dict(r) for r in rows], total

    def get_user_stats_summary(self):
        """v3.21: خلاصهٔ پنل «آمار کاربران» — کل | قابل‌ارسال | جدید امروز | با حداقل یک درخواست."""
        with self._lock:
            total = self.conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()['cnt']
            try:
                messageable = self.conn.execute(
                    "SELECT COUNT(*) as cnt FROM users WHERE (blocked_bot=0 OR blocked_bot IS NULL) "
                    "AND (blocked=0 OR blocked IS NULL)").fetchone()['cnt']
            except sqlite3.OperationalError:
                messageable = total
            new_today = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM users WHERE date(created_at)=?",
                (datetime.date.today().isoformat(),)).fetchone()['cnt']
            try:
                requested = self.conn.execute(
                    "SELECT COUNT(*) as cnt FROM users WHERE requested=1").fetchone()['cnt']
            except sqlite3.OperationalError:
                requested = 0
            return {'total': total, 'messageable': messageable,
                    'new_today': new_today, 'requested': requested}

    def get_bonus_streak_stats(self):
        """v3.21: استریک جایزهٔ روزانه — تعداد زنده (دیروز/امروز دریافت کرده) | رکورد (طولانی‌ترین)."""
        with self._lock:
            y = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
            try:
                active = self.conn.execute(
                    "SELECT COUNT(*) as cnt FROM daily_bonus WHERE last_claim>=?", (y,)).fetchone()['cnt']
                best = self.conn.execute(
                    "SELECT COALESCE(MAX(streak),0) as cnt FROM daily_bonus").fetchone()['cnt']
            except sqlite3.OperationalError:
                active, best = 0, 0
            return active, best

    def get_challenge_rank(self, user_id, start_utc, end_utc):
        """رتبهٔ زندهٔ کاربر در چالش (۱ = نفر اول)؛ None اگر امتیازی ندارد."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT c.owner_id, COUNT(DISTINCT c.clicker_id) as s "
                "FROM clicks c JOIN users u ON c.owner_id=u.user_id "
                "WHERE c.is_new_user=1 AND c.clicked_at>=? AND c.clicked_at<? "
                "AND (u.blocked=0 OR u.blocked IS NULL) "
                "GROUP BY c.owner_id ORDER BY s DESC, MIN(c.clicked_at) ASC",
                (start_utc, end_utc)).fetchall()
        for i, r in enumerate(rows, 1):
            if r['owner_id'] == user_id:
                return i
        return None

    def get_user_rank_by_distinct(self, user_id):
        """رتبهٔ کاربر بین صاحبان تله بر اساس فضول.
        v3.9.4: فقط نام‌های قابل نمایش — مخفی‌کننده‌ها و بلاک‌شده‌ها شمرده نمی‌شوند
        تا «رتبهٔ تو» دقیقاً با تابلوی واقعی بخواند."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT c.owner_id, COUNT(DISTINCT c.clicker_id) as s "
                "FROM clicks c JOIN users u ON c.owner_id=u.user_id "
                "WHERE u.hide_leaderboard=0 AND (u.blocked=0 OR u.blocked IS NULL) "
                "GROUP BY c.owner_id ORDER BY s DESC"
            ).fetchall()
            for i, r in enumerate(rows, 1):
                if r['owner_id'] == user_id:
                    return i
            return None

    def get_users_active_since(self, days=14):
        """کاربران بلاک‌نشده که در N روز اخیر فعالیتی داشته‌اند (برای گزارش هفتگی)."""
        with self._lock:
            return [r['user_id'] for r in self.conn.execute(
                "SELECT user_id FROM users WHERE (blocked=0 OR blocked IS NULL) "
                "AND (blocked_bot=0 OR blocked_bot IS NULL) "
                "AND last_active_date IS NOT NULL "
                "AND julianday('now') - julianday(last_active_date) <= ?", (days,)).fetchall()]

    def get_top_users_by_xp(self, limit=10):
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT user_id, first_name, xp, level_cached FROM users "
                "WHERE hide_leaderboard=0 AND (blocked=0 OR blocked IS NULL) "
                "ORDER BY xp DESC LIMIT ?", (limit,)).fetchall()]

    # ----- مدیریت قیمت VIP -----
    def set_vip_price(self, days, amount):
        """تغییر قیمت VIP در دیتابیس برای حفظ پایداری."""
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (f"vip_price_{days}", str(amount))
            )
            self.conn.commit()

    def get_vip_price(self, days):
        with self._lock:
            try:
                row = self.conn.execute("SELECT value FROM settings WHERE key=?", (f"vip_price_{days}",)).fetchone()
                return int(row['value']) if row else None
            except sqlite3.OperationalError:
                return None

    def get_user_mask(self, user_id):
        with self._lock:
            row = self.conn.execute("SELECT emoji, mask_text FROM user_mask WHERE user_id=?", (user_id,)).fetchone()
            if row and (row['emoji'] or row['mask_text']): return (row['emoji'], row['mask_text'])
            return None

    # ----- متدهای جدید اد اجباری -----
    def record_channel_join(self, user_id, channel_username):
        """v3.21: ثبت عضویت + بررسی هدف جذب. اگر تعداد اعضای جذب‌شده به هدف برسد
        (target>0)، کانال به‌صورت اتمیک از لیست جوین اجباری حذف و شناسه‌اش برگردانده
        می‌شود تا فراخواننده به سوپرادمین خبر بدهد. فقط یک نخ برنده می‌شود (DELETE گارددار)."""
        completed = None
        with self._lock:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO channel_joins (user_id, channel_username) VALUES (?,?)",
                (user_id, channel_username)
            )
            if cur.rowcount:
                try:
                    row = self.conn.execute(
                        "SELECT target FROM forced_channels WHERE channel_id=?", (channel_username,)
                    ).fetchone()
                    tgt = (row['target'] if row else 0) or 0
                    if tgt > 0:
                        cnt = self.conn.execute(
                            "SELECT COUNT(*) as cnt FROM channel_joins WHERE channel_username=?",
                            (channel_username,)
                        ).fetchone()['cnt']
                        if cnt >= tgt:
                            d = self.conn.execute(
                                "DELETE FROM forced_channels WHERE channel_id=? AND target>0",
                                (channel_username,)
                            )
                            if d.rowcount:
                                completed = channel_username
                except sqlite3.OperationalError:
                    pass  # ستون target هنوز موجود نیست (دیتابیس قدیمی)
            self.conn.commit()
        return completed

    def get_channel_join_count(self, channel_username):
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM channel_joins WHERE channel_username=?",
                (channel_username,)
            ).fetchone()
            return row['cnt'] if row else 0

    def get_channel_joins_today(self):
        """v3.21: تعداد عضویت‌های ثبت‌شدهٔ امروز (همهٔ کانال‌ها) به وقت تهران."""
        with self._lock:
            try:
                today_tehran = datetime.datetime.now(TEHRAN_TZ).date().isoformat()
                row = self.conn.execute(
                    "SELECT COUNT(*) as cnt FROM channel_joins WHERE date(joined_at, '+3 hours', '+30 minutes')=?",
                    (today_tehran,)
                ).fetchone()
                return row['cnt'] if row else 0
            except sqlite3.OperationalError:
                return 0

    # ----- مدیریت کانال‌های اجباری -----
    def add_forced_channel(self, channel_id, channel_name, invite_link, target=0):
        with self._lock:
            self.conn.execute(
                "INSERT INTO forced_channels (channel_id, channel_name, invite_link, target) VALUES (?,?,?,?) "
                "ON CONFLICT(channel_id) DO UPDATE SET channel_name=excluded.channel_name, "
                "invite_link=excluded.invite_link, target=excluded.target",
                (channel_id, channel_name, invite_link, int(target or 0))
            )
            self.conn.commit()

    def remove_forced_channel(self, channel_id):
        with self._lock:
            self.conn.execute("DELETE FROM forced_channels WHERE channel_id=?", (channel_id,))
            self.conn.commit()

    def get_all_forced_channels(self):
        with self._lock:
            return [dict(r) for r in self.conn.execute("SELECT * FROM forced_channels ORDER BY added_at").fetchall()]

    # ----- pending snoops -----
    def save_pending_snoop(self, owner_id, clicker_id, display_name, t, vip_owner, clicker_username, repeat, gift_vip_given, photo_file_id):
        with self._lock:
            self.conn.execute("DELETE FROM pending_snoops WHERE owner_id=?", (owner_id,))
            self.conn.execute(
                "INSERT INTO pending_snoops (owner_id, clicker_id, display_name, t, vip_owner, clicker_username, repeat, gift_vip_given, photo_file_id) VALUES (?,?,?,?,?,?,?,?,?)",
                (owner_id, clicker_id, display_name, t, vip_owner, clicker_username, repeat, gift_vip_given, photo_file_id)
            )
            self.conn.commit()

    def get_pending_snoop(self, owner_id):
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM pending_snoops WHERE owner_id=? ORDER BY id DESC LIMIT 1", (owner_id,)
            ).fetchone()
            if row:
                self.conn.execute("DELETE FROM pending_snoops WHERE owner_id=?", (owner_id,))
                self.conn.commit()
                return dict(row)
            return None

    def get_last_daily_report_date(self):
        with self._lock:
            try:
                row = self.conn.execute("SELECT last_report_date FROM daily_report_state WHERE id=1").fetchone()
                return row['last_report_date'] if row else None
            except sqlite3.OperationalError:
                return None

    def set_last_daily_report_date(self, date_str):
        with self._lock:
            try:
                self.conn.execute("UPDATE daily_report_state SET last_report_date=? WHERE id=1", (date_str,))
                self.conn.commit()
            except sqlite3.OperationalError:
                pass

    def get_daily_user_growth(self, days=30):
        """گرفتن تعداد کاربران جدید در هر روز برای N روز گذشته.
        برمی‌گرداند: لیست از (date_iso, count) — فقط روزهایی که حداقل ۱ کاربر جدید داشته‌اند.
        از قدیمی‌ترین به جدیدترین مرتب می‌شود."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT date(created_at) as d, COUNT(*) as c "
                "FROM users WHERE date(created_at) >= date('now', ?) "
                "GROUP BY date(created_at) ORDER BY d ASC",
                (f'-{days} days',)
            ).fetchall()
            return [(r['d'], r['c']) for r in rows]

    def get_full_daily_report_data(self):
        """داده‌های کامل برای گزارش روزانه ساعت ۲۳."""
        with self._lock:
            today = datetime.date.today().isoformat()
            yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

            # کاربران
            new_today = self.conn.execute("SELECT COUNT(*) as c FROM users WHERE date(created_at)=?", (today,)).fetchone()['c']
            new_yesterday = self.conn.execute("SELECT COUNT(*) as c FROM users WHERE date(created_at)=?", (yesterday,)).fetchone()['c']
            active_today = self.conn.execute("SELECT COUNT(DISTINCT clicker_id) as c FROM clicks WHERE date(clicked_at)=?", (today,)).fetchone()['c']
            active_yesterday = self.conn.execute("SELECT COUNT(DISTINCT clicker_id) as c FROM clicks WHERE date(clicked_at)=?", (yesterday,)).fetchone()['c']

            # کلیک‌ها
            clicks_today = self.conn.execute("SELECT COUNT(*) as c FROM clicks WHERE date(clicked_at)=?", (today,)).fetchone()['c']
            clicks_yesterday = self.conn.execute("SELECT COUNT(*) as c FROM clicks WHERE date(clicked_at)=?", (yesterday,)).fetchone()['c']
            distinct_today = self.conn.execute("SELECT COUNT(DISTINCT clicker_id) as c FROM clicks WHERE date(clicked_at)=?", (today,)).fetchone()['c']

            # صاحبان تلهٔ جدید امروز (اولین کلیک دریافتی)
            new_trap_owners = self.conn.execute(
                "SELECT COUNT(*) as c FROM (SELECT owner_id, MIN(date(clicked_at)) as first_click FROM clicks GROUP BY owner_id HAVING first_click=?)",
                (today,)).fetchone()['c']

            # پیام‌های ناشناس امروز
            anon_today = self.conn.execute("SELECT COUNT(*) as c FROM anon_logs WHERE date(timestamp)=?", (today,)).fetchone()['c']

            # گزارش‌های تخلف امروز (تقریبی: اخطارهای امروز)
            reports_today = 0  # پیاده‌سازی ساده؛ اخطارها در جدول users به‌صورت count هست

            # درآمد امروز و دیروز
            revenue_today = self.conn.execute(
                "SELECT COALESCE(SUM(amount),0) as c FROM transactions WHERE date(timestamp)=? AND type IN ('vip','gift_vip')",
                (today,)).fetchone()['c']
            revenue_yesterday = self.conn.execute(
                "SELECT COALESCE(SUM(amount),0) as c FROM transactions WHERE date(timestamp)=? AND type IN ('vip','gift_vip')",
                (yesterday,)).fetchone()['c']
            tx_today = self.conn.execute(
                "SELECT COUNT(*) as c FROM transactions WHERE date(timestamp)=? AND type IN ('vip','gift_vip')",
                (today,)).fetchone()['c']

            # VIP
            active_vip = self.conn.execute("SELECT COUNT(*) as c FROM vip WHERE expire_date >= date('now')").fetchone()['c']
            expiring_vips = self.conn.execute(
                "SELECT user_id FROM vip WHERE expire_date IN (?, ?)",
                (today, yesterday)).fetchall()
            # VIPهای جدید امروز (کسانی که امروز تراکنش vip داشته‌اند)
            new_vip_today_rows = self.conn.execute(
                "SELECT DISTINCT user_id FROM transactions WHERE date(timestamp)=? AND type='vip'", (today,)).fetchall()
            new_vip_today = [r['user_id'] for r in new_vip_today_rows]

            # کدهای هدیه استفاده‌شده امروز
            gift_used_today = self.conn.execute(
                "SELECT COUNT(*) as c FROM gift_usage WHERE date(used_at)=?", (today,)).fetchone()['c']
            active_gift_codes = self.conn.execute(
                "SELECT COUNT(*) as c FROM gift_codes WHERE used_count < max_uses").fetchone()['c']

            # کاربران مسدودشده امروز
            # (ستون updated_at نداریم؛ تقریبی: کل مسدودشده‌ها)
            total_banned = self.conn.execute("SELECT COUNT(*) as c FROM users WHERE blocked=1").fetchone()['c']
            # کاربرانی که ربات را بلاک کرده‌اند (از خطای 403)
            blocked_bot_count = self.conn.execute("SELECT COUNT(*) as c FROM users WHERE blocked_bot=1").fetchone()['c']

            # برترین شکارچیان امروز
            top_today = self.conn.execute(
                "SELECT c.owner_id, u.first_name, COUNT(DISTINCT c.clicker_id) as c FROM clicks c "
                "JOIN users u ON c.owner_id=u.user_id WHERE date(c.clicked_at)=? "
                "GROUP BY c.owner_id ORDER BY c DESC LIMIT 5", (today,)).fetchall()

            # کانال‌های اجباری مشکل‌دار
            broken = list(broken_channels) if 'broken_channels' in globals() else []

            # آخرین پخش همگانی
            last_broadcast_info = self.conn.execute(
                "SELECT value FROM settings WHERE key='last_broadcast_stats'").fetchone()
            last_broadcast = last_broadcast_info['value'] if last_broadcast_info else None

            return {
                'new_today': new_today,
                'new_yesterday': new_yesterday,
                'active_today': active_today,
                'active_yesterday': active_yesterday,
                'clicks_today': clicks_today,
                'clicks_yesterday': clicks_yesterday,
                'distinct_today': distinct_today,
                'new_trap_owners': new_trap_owners,
                'anon_today': anon_today,
                'revenue_today': revenue_today,
                'revenue_yesterday': revenue_yesterday,
                'tx_today': tx_today,
                'active_vip': active_vip,
                'expiring_vips': [r['user_id'] for r in expiring_vips],
                'new_vip_today': new_vip_today,
                'gift_used_today': gift_used_today,
                'active_gift_codes': active_gift_codes,
                'total_banned': total_banned,
                'blocked_bot_count': blocked_bot_count,
                'top_today': [dict(r) for r in top_today],
                'broken_channels': broken,
                'last_broadcast': last_broadcast,
            }

