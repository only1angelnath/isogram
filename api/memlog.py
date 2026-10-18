"""
memlog.py - one log line a minute saying how much memory the API process is using.

Why it exists: Render's free plan hides its Memory graph, so when the instance was restarted
(2026-10-18 04:55 UTC) there was no way to see what it was doing beforehand. This puts the same facts
into the logs, where they can be searched for "MEM" after any future restart.

Line format (every value is "n/a" when the platform does not expose it):
    MEM rss=212.4MB peak=240.1MB cgroup=231.0MB threads=14 inflight=3 snapshots=9

  rss       resident memory of this process now (what Render's 512 MB limit is checked against, roughly)
  peak      the highest rss this process has reached since it started
  cgroup    the container's total usage as the kernel counts it (includes file cache)
  threads   live Python threads (each background refresh and each worker thread counts)
  inflight  requests the app is handling at this moment
  snapshots entries held by the snapshot cache (cache.py)

Above MEMLOG_WARN_MB (default 350) it logs at WARNING and every 10 s instead of every 60 s, so the
last lines before a kill show the climb in detail.

Env (all optional): MEMLOG_SECONDS (default 60, 0 turns it off), MEMLOG_WARN_MB (default 350).
Read-only: it never changes what any endpoint returns.
"""

import logging
import os
import sys
import threading
import time

log = logging.getLogger("isogram.mem")
# uvicorn only configures its own loggers, so INFO from ours would be dropped. Give this one a handler.
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)
    log.propagate = False

_inflight = 0  # only touched from the event loop thread, so a plain int is enough
_started = False
_start_lock = threading.Lock()


def request_started() -> None:
    global _inflight
    _inflight += 1


def request_finished() -> None:
    global _inflight
    _inflight = max(_inflight - 1, 0)


def inflight() -> int:
    return _inflight


def _proc_status_mb(field: str):
    """A kB field from /proc/self/status (Linux), as MB; None where unavailable."""
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith(field + ":"):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        pass
    return None


def rss_mb():
    return _proc_status_mb("VmRSS")


def peak_mb():
    return _proc_status_mb("VmHWM")


def cgroup_mb():
    for path in ("/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory/memory.usage_in_bytes"):
        try:
            with open(path) as fh:
                return int(fh.read().strip()) / (1024.0 * 1024.0)
        except (OSError, ValueError):
            continue
    return None


def _fmt(value) -> str:
    return "n/a" if value is None else f"{value:.1f}MB"


def _snapshot_count() -> str:
    try:
        from cache import snapshots
        return str(len(snapshots._entries))
    except Exception:
        return "n/a"


def describe() -> str:
    return (
        f"MEM rss={_fmt(rss_mb())} peak={_fmt(peak_mb())} cgroup={_fmt(cgroup_mb())} "
        f"threads={threading.active_count()} inflight={_inflight} snapshots={_snapshot_count()}"
    )


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _loop(interval: float, warn_mb: float) -> None:
    while True:
        hot = (rss_mb() or 0.0) >= warn_mb
        try:
            (log.warning if hot else log.info)(describe())
        except Exception:  # a diagnostic must never be able to hurt the app
            pass
        time.sleep(10.0 if hot else interval)


def start() -> bool:
    """Start the logging thread once. Returns False if it is disabled or already running."""
    global _started
    interval = _float_env("MEMLOG_SECONDS", 60.0)
    if interval <= 0:
        return False
    with _start_lock:
        if _started:
            return False
        _started = True
    threading.Thread(target=_loop, args=(interval, _float_env("MEMLOG_WARN_MB", 350.0)),
                     name="memlog", daemon=True).start()
    return True
