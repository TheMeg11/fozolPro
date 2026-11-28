# -*- coding: utf-8 -*-
"""memguard.py — گارد حافظه برای کانتینر کوچک Railway (پیش‌فرض ۵۱۲MB)
================================================================================
مشاهدهٔ واقعی روی Railway: `rss_max` از ۱۲۹MB به ۱۴۶MB در ۳۰ دقیقه رسید و
سرویس با OOM ری‌استارت می‌شد («پر می‌شود و هنگ می‌کند»). سه کار انجام می‌دهد:

۱) **پایش واقعی RSS** (نه فقط peak): هر MEM_CHECK_SEC مقدار VmRSS را از
   /proc/self/status می‌خواند و در لاگ می‌نویسد؛ در صورت فعال بودن
   MEM_TRACE=1، ۵ منبع بزرگِ tracemalloc را هم چاپ می‌کند.
۲) **بهداشت نرم**: عبور از MEM_SOFT_MB (پیش‌فرض ۳۲۰MB) → پاک‌سازی کش‌های
   ثبت‌شده (pruner ها) + gc.collect + malloc_trim(0). این کار صفحات آزادشدهٔ
   allocator را به سیستم‌عامل برمی‌گرداند (مشکل کلاسیک fragmentation در
   پروسهٔ چندنخی Python با Pillow و ده‌ها اتصال TLS).
۳) **ری‌استارت محترمانه**: عبور پی‌درپی از MEM_HARD_MB (پیش‌فرض ۴۴۰MB)
   → SIGTERM به خود پروسه تا uvicorn/polling تمیز بسته شوند و Railway
   کانتینر تازه بالا بیاورد؛ به‌جای OOM-kill وسط نوشتن دیتابیس.

متغیرهای محیطی:
  MEM_CHECK_SEC=120      بازهٔ پایش (ثانیه)
  MEM_SOFT_MB=320        آستانهٔ بهداشت نرم
  MEM_HARD_MB=440        آستانهٔ ری‌استارت محترمانه (۰ = خاموش)
  MEM_TRACE=0            چاپ ۵ منبع بزرگ حافظه در هر گزارش
"""
from __future__ import annotations

import gc
import logging
import os
import signal
import threading
import time

log = logging.getLogger("mem")

CHECK_SEC = max(30.0, float(os.environ.get("MEM_CHECK_SEC") or 120))
SOFT_MB = float(os.environ.get("MEM_SOFT_MB") or 320)
HARD_MB = float(os.environ.get("MEM_HARD_MB") or 440)
TRACE = os.environ.get("MEM_TRACE", "0").strip() in ("1", "true", "yes", "on")

# v5.2: پرچم «خروج به‌خاطر حافظه» — run.py بعد از بستن تمیز DB، با این پرچم
# با کد خروج 1 خارج می‌شود تا Railway حتی با restartPolicy=ON_FAILURE هم
# سرویس را دوباره بالا بیاورد (با exit 0 هرگز ری‌استارت نمی‌شود).
SELF_TERMINATED = False

_pruners: list = []
_lock = threading.Lock()


def register_pruner(fn) -> None:
    """کش‌های ماژول‌ها پاک‌سازی خودشان را اینجا ثبت می‌کنند."""
    with _lock:
        if fn not in _pruners:
            _pruners.append(fn)


def rss_mb() -> float:
    """RSS جاری پروسه به مگابایت (Linux: /proc/self/status)."""
    try:
        with open("/proc/self/status", "r", encoding="ascii", errors="ignore") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except Exception:
        pass
    try:
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    except Exception:
        return 0.0


def _malloc_trim() -> None:
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def trim(prune: bool = True) -> None:
    """بهداشت حافظه: پاک‌سازی کش‌ها + GC + بازگرداندن صفحات آزاد به OS."""
    if prune:
        with _lock:
            hooks = list(_pruners)
        for fn in hooks:
            try:
                fn()
            except Exception:
                log.debug("pruner %r failed", fn, exc_info=True)
    try:
        gc.collect()
    except Exception:
        pass
    _malloc_trim()


def _trace_top() -> str:
    try:
        import tracemalloc

        if not tracemalloc.is_tracing():
            tracemalloc.start(10)
            return "tracemalloc started"
        snap = tracemalloc.take_snapshot()
        top = snap.statistics("lineno")[:5]
        return " | ".join(f"{str(s.traceback)[:70]}={s.size / 1048576.0:.1f}MB" for s in top)
    except Exception as exc:  # pragma: no cover
        return f"trace failed: {exc}"


def _loop() -> None:
    over_hard = 0
    time.sleep(min(30.0, CHECK_SEC))
    while True:
        try:
            # v5.3: بستن کانکشن‌های SQLite ترد‌های مرده (پول anyio) در هر دور — ارزان است
            try:
                from services import db as _db

                _db.prune_dead_connections()
            except Exception:
                pass
            mb = rss_mb()
            peak = 0.0
            try:
                import resource

                peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
            except Exception:
                pass
            log.info("🧠 mem: rss=%.0fMB peak=%.0fMB soft=%.0f hard=%.0f", mb, peak, SOFT_MB, HARD_MB)
            if TRACE:
                log.info("🧠 top: %s", _trace_top())
            if SOFT_MB and mb >= SOFT_MB:
                log.warning("🧠 RSS %.0fMB ≥ %.0fMB — پاک‌سازی کش‌ها + malloc_trim", mb, SOFT_MB)
                trim()
            if HARD_MB and mb >= HARD_MB:
                over_hard += 1
                log.error("🧠 RSS %.0fMB ≥ %.0fMB (نوبت %d)", mb, HARD_MB, over_hard)
                if over_hard >= 2:
                    global SELF_TERMINATED
                    SELF_TERMINATED = True
                    # v5.4: ثبت ماندگار «ری‌استارت حافظه‌ای» برای داشبورد (قبل از خاموشی)
                    try:
                        from services import metrics as _mx

                        _mx.bump("memrestart")
                        _mx.flush()
                    except Exception:
                        pass
                    log.error("🧠 ری‌استارت محترمانه به‌خاطر حافظه — SIGTERM به خود پروسه")
                    try:
                        os.kill(os.getpid(), signal.SIGTERM)
                    except Exception:
                        os._exit(1)
                    return
            else:
                over_hard = 0
        except Exception:
            log.exception("memguard loop error")
        time.sleep(CHECK_SEC)


def start() -> None:
    threading.Thread(target=_loop, name="memguard", daemon=True).start()
