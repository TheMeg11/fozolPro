"""v5.4 — آمار سرور برای داشبورد ادمین: رم، CPU، دیسک و پیش‌بینی هزینهٔ Railway.

دو منبع (هر دو با هم کار می‌کنند):
  ۱) اندازه‌گیری داخلی (همیشه فعال، بدون تنظیم): هر SAMPLE_SEC ثانیه رمِ کانتینر
     (cgroup: memory.current منهای inactive_file — همان «working set» که پلتفرم‌ها گزارش
     می‌کنند؛ در نبود cgroup، RSS پروسه) و مصرف CPU خوانده و در server_samples ذخیره می‌شود.
     کمینه/میانگین/بیشینهٔ ۲۴ ساعت با ری‌استارت پاک نمی‌شود. هزینه با نرخ‌های عمومی Railway
     تخمین زده می‌شود (ترافیک خروجی را نمی‌بیند).
  ۲) API رسمی Railway (اگر RAILWAY_API_TOKEN یا RAILWAY_PROJECT_TOKEN ست شده باشد): هر
     RAILWAY_REFRESH_SEC ثانیه کوئری metrics/usage روی backboard.railway.com — اعداد دقیق
     خود Railway (همان نمودار داشبوردش) + ترافیک خروجی. شناسه‌های پروژه/سرویس/محیط را
     Railway خودش با RAILWAY_PROJECT_ID / RAILWAY_SERVICE_ID / RAILWAY_ENVIRONMENT_ID تزریق می‌کند.

نرخ‌ها (قابل تغییر با env؛ پیش‌فرض = نرخ عمومی Railway، صورت‌حساب ثانیه‌ای، ماه = ۳۰ روز):
  RAILWAY_PRICE_RAM_GB_MONTH=10   RAILWAY_PRICE_CPU_MONTH=20
  RAILWAY_PRICE_VOLUME_GB_MONTH=0.15   RAILWAY_PRICE_EGRESS_GB=0.05
  RAILWAY_PLAN_CREDIT_USD (اختیاری؛ مثلاً 5 برای Hobby — برای نمایش «از اعتبار ماهانه»)
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone

from services import db, metrics

log = logging.getLogger("server_stats")

SAMPLE_SEC = max(30, int(os.environ.get("SERVER_SAMPLE_SEC") or 60))
RETAIN_DAYS = 8
RAILWAY_GQL = os.environ.get("RAILWAY_GQL_URL") or "https://backboard.railway.com/graphql/v2"
RAILWAY_REFRESH_SEC = max(120, int(os.environ.get("RAILWAY_REFRESH_SEC") or 300))
_MONTH_SEC = 30 * 86400


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


PRICE_RAM_GB_MONTH = _f("RAILWAY_PRICE_RAM_GB_MONTH", 10.0)
PRICE_CPU_MONTH = _f("RAILWAY_PRICE_CPU_MONTH", 20.0)
PRICE_VOLUME_GB_MONTH = _f("RAILWAY_PRICE_VOLUME_GB_MONTH", 0.15)
PRICE_EGRESS_GB = _f("RAILWAY_PRICE_EGRESS_GB", 0.05)
PLAN_CREDIT_USD = _f("RAILWAY_PLAN_CREDIT_USD", 0.0)

_START = time.time()
_lock = threading.Lock()
_prev_cpu: tuple[float, float] | None = None  # (wall, cpu_seconds)
_last: dict = {}
_rw: dict = {"at": 0.0, "ok_at": 0.0, "data": None, "error": None}
_started = False
_MAX_SANE_BYTES = 64 * 1024 ** 3  # بزرگ‌تر از این = عدد میزبان، نه کانتینر


# ---------------- خواندن منابع ----------------
def _read(path: str) -> str | None:
    try:
        with open(path, "r", encoding="ascii", errors="ignore") as fh:
            return fh.read().strip()
    except Exception:
        return None


def _stat_value(path: str, key: str) -> int:
    txt = _read(path) or ""
    for line in txt.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == key:
            try:
                return int(parts[1])
            except ValueError:
                return 0
    return 0


def read_mem() -> tuple[float, str]:
    """(مگابایت, منبع) — working set کانتینر از cgroup، در غیر این صورت RSS پروسه."""
    cur = _read("/sys/fs/cgroup/memory.current")  # cgroup v2
    if cur and cur.isdigit() and 0 < int(cur) < _MAX_SANE_BYTES:
        ws = int(cur) - _stat_value("/sys/fs/cgroup/memory.stat", "inactive_file")
        return max(ws, 0) / 1048576.0, "cgroup"
    cur = _read("/sys/fs/cgroup/memory/memory.usage_in_bytes")  # cgroup v1
    if cur and cur.isdigit() and 0 < int(cur) < _MAX_SANE_BYTES:
        ws = int(cur) - _stat_value("/sys/fs/cgroup/memory/memory.stat", "total_inactive_file")
        return max(ws, 0) / 1048576.0, "cgroup"
    try:
        import memguard

        return memguard.rss_mb(), "rss"
    except Exception:
        return 0.0, "rss"


def mem_limit_mb() -> float:
    env = os.environ.get("SERVER_MEMORY_MB")
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    for p in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        v = _read(p)
        if v and v.isdigit() and 0 < int(v) < _MAX_SANE_BYTES:
            return int(v) / 1048576.0
    return 512.0


def _cpu_seconds() -> float:
    v = _stat_value("/sys/fs/cgroup/cpu.stat", "usage_usec")  # cgroup v2
    if v:
        return v / 1e6
    v1 = _read("/sys/fs/cgroup/cpuacct/cpuacct.usage")  # cgroup v1 (نانوثانیه)
    if v1 and v1.isdigit():
        return int(v1) / 1e9
    t = os.times()
    return t.user + t.system + t.children_user + t.children_system


def disk_gb() -> float:
    """فضای اشغال‌شدهٔ Volume (اگر Railway مسیرش را داده) وگرنه حجم فایل‌های دیتابیس."""
    mount = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    if mount and os.path.isdir(mount):
        try:
            return shutil.disk_usage(mount).used / 1024 ** 3
        except Exception:
            pass
    return db_size_mb() / 1024.0


def db_size_mb() -> float:
    try:
        path = db.conn().execute("PRAGMA database_list").fetchone()[2]
    except Exception:
        return 0.0
    total = 0
    for suffix in ("", "-wal", "-shm"):
        try:
            total += os.path.getsize(path + suffix)
        except OSError:
            pass
    return total / 1048576.0


def uptime_sec() -> int:
    return int(time.time() - _START)


# ---------------- هزینه ----------------
def cost_24h(mem_gb: float, vcpu: float, disk: float = 0.0, egress_gb: float | None = None) -> dict:
    """هزینهٔ ۲۴ ساعت به دلار با میانگین مصرف (صورت‌حساب Railway ثانیه‌ای است)."""
    k = 86400 / _MONTH_SEC
    ram = mem_gb * PRICE_RAM_GB_MONTH * k
    cpu = vcpu * PRICE_CPU_MONTH * k
    vol = disk * PRICE_VOLUME_GB_MONTH * k
    eg = (egress_gb or 0.0) * PRICE_EGRESS_GB
    return {"ram": ram, "cpu": cpu, "disk": vol, "egress": eg if egress_gb is not None else None,
            "total": ram + cpu + vol + eg}


# ---------------- نمونه‌برداری ----------------
def sample() -> dict:
    global _prev_cpu
    now = time.time()
    mem, src = read_mem()
    cs = _cpu_seconds()
    cpu = None
    with _lock:
        if _prev_cpu and now - _prev_cpu[0] >= 5:
            cpu = max(0.0, (cs - _prev_cpu[1]) / (now - _prev_cpu[0]))
        _prev_cpu = (now, cs)
        _last.update({"ts": now, "mem_mb": mem, "cpu": cpu, "src": src})
    return dict(_last)


def _store(s: dict) -> None:
    try:
        db.execute("INSERT OR REPLACE INTO server_samples(ts, mem_mb, cpu) VALUES(?,?,?)",
                   (int(s["ts"]), round(s["mem_mb"], 1), None if s["cpu"] is None else round(s["cpu"], 4)))
    except Exception as exc:
        log.warning("server sample store failed: %s", exc)


def prune() -> None:
    try:
        db.execute("DELETE FROM server_samples WHERE ts < ?", (int(time.time() - RETAIN_DAYS * 86400),))
    except Exception as exc:
        log.warning("server samples prune failed: %s", exc)


def local_window(seconds: int = 86400) -> dict | None:
    r = db.row("SELECT COUNT(*) AS n, MIN(mem_mb) AS mn, AVG(mem_mb) AS av, MAX(mem_mb) AS mx, "
               "AVG(cpu) AS cav, MAX(cpu) AS cmx, MIN(ts) AS t0 FROM server_samples WHERE ts >= ?",
               (int(time.time() - seconds),))
    if not r or not r["n"]:
        return None
    return {"n": int(r["n"]), "min": r["mn"], "avg": r["av"], "max": r["mx"],
            "cpu_avg": r["cav"] or 0.0, "cpu_max": r["cmx"] or 0.0,
            "covered_h": min(seconds, int(r["n"]) * SAMPLE_SEC) / 3600.0}


def daily_local(first_day: str, last_day: str) -> dict[str, dict]:
    """میانگین رم/CPU هر روز تهران از نمونه‌های ذخیره‌شده (برای ردیف‌های روند)."""
    out = {}
    for r in db.rows(
            "SELECT strftime('%Y-%m-%d', ts, 'unixepoch', '+210 minutes') AS d, COUNT(*) AS n, "
            "AVG(mem_mb) AS mem, AVG(cpu) AS cpu, MAX(mem_mb) AS mx FROM server_samples "
            "WHERE ts >= ? GROUP BY d", (int(time.time() - (RETAIN_DAYS + 1) * 86400),)):
        if first_day <= r["d"] <= last_day:
            out[r["d"]] = {"n": int(r["n"]), "mem": r["mem"] or 0.0, "cpu": r["cpu"] or 0.0, "max": r["mx"] or 0.0}
    return out


# ---------------- API رسمی Railway ----------------
def _rw_headers() -> dict | None:
    acct = (os.environ.get("RAILWAY_API_TOKEN") or "").strip()
    proj = (os.environ.get("RAILWAY_PROJECT_TOKEN") or "").strip()
    if acct:
        return {"Authorization": f"Bearer {acct}", "Content-Type": "application/json"}
    if proj:
        return {"Project-Access-Token": proj, "Content-Type": "application/json"}
    return None


def _rw_ids() -> tuple[str, str, str] | None:
    p = os.environ.get("RAILWAY_PROJECT_ID")
    s = os.environ.get("RAILWAY_SERVICE_ID")
    e = os.environ.get("RAILWAY_ENVIRONMENT_ID")
    return (p, s, e) if p and s and e else None


def railway_configured() -> bool:
    return bool(_rw_headers() and _rw_ids())


def _gql(query: str, variables: dict) -> dict:
    import requests

    r = requests.post(RAILWAY_GQL, json={"query": query, "variables": variables},
                      headers=_rw_headers(), timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    body = r.json()
    if body.get("errors") and not body.get("data"):
        raise RuntimeError(str(body["errors"][0].get("message", "error"))[:120])
    return body.get("data") or {}


_Q_METRICS = """query fozolDash($p: String!, $s: String!, $e: String!, $start: DateTime!, $end: DateTime!) {
  metrics(projectId: $p, serviceId: $s, environmentId: $e, startDate: $start, endDate: $end,
          sampleRateSeconds: 300, averagingWindowSeconds: 300,
          measurements: [MEMORY_USAGE_GB, CPU_USAGE, MEMORY_LIMIT_GB]) {
    measurement
    values { ts value }
  }
}"""

_Q_USAGE = """query fozolEgress($p: String!, $start: DateTime!, $end: DateTime!) {
  usage(projectId: $p, startDate: $start, endDate: $end, measurements: [NETWORK_TX_GB], groupBy: [SERVICE_ID]) {
    measurement
    value
    tags { serviceId }
  }
}"""


def refresh_railway() -> None:
    """کوئری API رسمی Railway برای ۲۴ ساعت اخیر؛ نتیجه در کش ماژول."""
    ids = _rw_ids()
    if not ids or not _rw_headers():
        return
    p, s, e = ids
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=24)
    fmt = "%Y-%m-%dT%H:%M:%S.000Z"
    try:
        data = _gql(_Q_METRICS, {"p": p, "s": s, "e": e, "start": start.strftime(fmt), "end": end.strftime(fmt)})
        series = {m["measurement"]: [v["value"] for v in (m.get("values") or []) if v.get("value") is not None]
                  for m in (data.get("metrics") or [])}
        mem = series.get("MEMORY_USAGE_GB") or []
        cpu = series.get("CPU_USAGE") or []
        lim = series.get("MEMORY_LIMIT_GB") or []
        if not mem:
            raise RuntimeError("بدون داده")
        out = {
            "mem_min_mb": min(mem) * 1024, "mem_avg_mb": sum(mem) / len(mem) * 1024, "mem_max_mb": max(mem) * 1024,
            "mem_last_mb": mem[-1] * 1024,
            "cpu_avg": (sum(cpu) / len(cpu)) if cpu else 0.0, "cpu_max": max(cpu) if cpu else 0.0,
            "mem_limit_mb": (lim[-1] * 1024) if lim else None,
            "covered_h": min(24.0, len(mem) * 300 / 3600.0),
            "egress_gb": None,
        }
        try:  # ترافیک خروجی — اختیاری (توکن پروژه ممکن است دسترسی usage نداشته باشد)
            u = _gql(_Q_USAGE, {"p": p, "start": start.strftime(fmt), "end": end.strftime(fmt)})
            tx = [x["value"] for x in (u.get("usage") or [])
                  if x.get("measurement") == "NETWORK_TX_GB" and (x.get("tags") or {}).get("serviceId") in (s, None)]
            if tx:
                out["egress_gb"] = float(sum(tx))
        except Exception:
            pass
        with _lock:
            _rw.update({"at": time.time(), "ok_at": time.time(), "data": out, "error": None})
    except Exception as exc:
        with _lock:
            _rw.update({"at": time.time(), "error": str(exc)[:120]})
        log.warning("railway metrics failed: %s", exc)


# ---------------- خروجی برای داشبورد ----------------
def snapshot() -> dict:
    """وضعیت کامل سرور: الان + پنجرهٔ ۲۴ ساعت (Railway یا داخلی) + هزینه."""
    now_mem, src = read_mem()
    with _lock:
        last_cpu = _last.get("cpu")
        rw = dict(_rw)
    limit = mem_limit_mb()
    disk = disk_gb()
    out = {"mem_now_mb": now_mem, "mem_src": src, "mem_limit_mb": limit, "cpu_now": last_cpu,
           "disk_gb": disk, "db_mb": db_size_mb(), "uptime_sec": uptime_sec(),
           "railway_configured": railway_configured(), "railway_error": rw.get("error"),
           "source": "local", "egress_gb": None}
    rd = rw.get("data")
    fresh = rd and (time.time() - rw.get("ok_at", 0)) < RAILWAY_REFRESH_SEC * 3
    if fresh:
        out.update({"source": "railway", "mem_min_mb": rd["mem_min_mb"], "mem_avg_mb": rd["mem_avg_mb"],
                    "mem_max_mb": rd["mem_max_mb"], "cpu_avg": rd["cpu_avg"], "cpu_max": rd["cpu_max"],
                    "covered_h": rd["covered_h"], "egress_gb": rd.get("egress_gb"),
                    "railway_age_sec": int(time.time() - rw["ok_at"])})
        if rd.get("mem_limit_mb"):
            out["mem_limit_mb"] = rd["mem_limit_mb"]
    else:
        w = local_window()
        if w:
            out.update({"mem_min_mb": w["min"], "mem_avg_mb": w["avg"], "mem_max_mb": w["max"],
                        "cpu_avg": w["cpu_avg"], "cpu_max": w["cpu_max"], "covered_h": w["covered_h"]})
        else:
            out.update({"mem_min_mb": now_mem, "mem_avg_mb": now_mem, "mem_max_mb": now_mem,
                        "cpu_avg": last_cpu or 0.0, "cpu_max": last_cpu or 0.0, "covered_h": 0.0})
    c = cost_24h(out["mem_avg_mb"] / 1024.0, out["cpu_avg"] or 0.0, disk, out["egress_gb"])
    out["cost"] = c
    out["cost_month"] = c["total"] * 30
    out["plan_credit"] = PLAN_CREDIT_USD
    try:
        import memguard

        out["soft_mb"], out["hard_mb"] = memguard.SOFT_MB, memguard.HARD_MB
    except Exception:
        out["soft_mb"], out["hard_mb"] = 0, 0
    return out


def _loop() -> None:
    try:
        metrics.bump("boot")
        metrics.seed_today()
    except Exception:
        pass
    sample()  # خط مبنای CPU
    last_prune = 0.0
    last_rw = 0.0
    time.sleep(min(10, SAMPLE_SEC))
    while True:
        t0 = time.time()
        try:
            s = sample()
            _store(s)
        except Exception as exc:
            log.warning("server sample failed: %s", exc)
        try:
            metrics.flush()
        except Exception:
            pass
        if t0 - last_prune > 3600:
            last_prune = t0
            prune()
            metrics.prune()
        if railway_configured() and t0 - last_rw >= RAILWAY_REFRESH_SEC:
            last_rw = t0
            refresh_railway()
        time.sleep(max(5.0, SAMPLE_SEC - (time.time() - t0)))


def start() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="server-stats", daemon=True).start()
