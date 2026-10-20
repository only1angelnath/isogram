"""
memlog.py - read-only memory diagnostics for the API process. It never changes what an endpoint returns.

Every minute (MEMLOG_SECONDS, 0 = off):
    MEM rss=212.4MB peak=240.1MB cgroup=231.0MB threads=14 inflight=3 snapshots=13
  rss       resident memory of this process now (roughly what Render's 512 MB limit is checked against)
  peak      highest rss since this process started
  cgroup    the container's total usage as the kernel counts it (includes file cache)
  threads   live Python threads;  inflight  requests being handled right now
  snapshots entries held by the snapshot cache (cache.py)
Above MEMLOG_WARN_MB (default 350) the line is a WARNING and repeats every 10 s.

Every 10 minutes (MEMLOG_DETAIL_SECONDS, default 600, 0 = off):
    MEMDETAIL snapshots total=6.4MB: projects=3.1MB stats=1.2MB network daily 30=0.4MB ...
  The deep size of each cached snapshot, largest first. If these add up to a small part of rss, the
  snapshots are not what is holding the memory.

Optional, off by default: MEMLOG_TRACE=1 starts Python's tracemalloc (slower and uses more memory, so
use it for a few hours, then turn it off). Each detail round then also logs:
    MEMTRACE traced=95.2MB traced_peak=130.0MB rss_minus_traced=237.2MB
    MEMTRACE top: api/db.py:55=12.1MB/48213 blocks | ...
  traced = memory held by live Python objects. rss_minus_traced is everything else: C libraries (TLS,
  HTTP/2), allocator fragmentation, and freed memory the allocator has not returned to the system.
  A large rss_minus_traced says "not our Python objects"; a small one says the top lines are the culprits.
"""

import logging
import os
import sys
import threading
import time
import types

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
_tracing = False


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


# ---- detail: how big is each cached snapshot -------------------------------------------------------

_SKIP = (type, types.ModuleType, types.FunctionType, types.BuiltinFunctionType, types.MethodType)


def deep_size(root) -> int:
    """Bytes held by `root` and everything it references, each object counted once."""
    seen = set()
    total = 0
    stack = [root]
    while stack:
        obj = stack.pop()
        oid = id(obj)
        if oid in seen:
            continue
        seen.add(oid)
        if isinstance(obj, _SKIP):
            continue
        total += sys.getsizeof(obj)
        if isinstance(obj, dict):
            stack.extend(obj.keys())
            stack.extend(obj.values())
        elif isinstance(obj, (list, tuple, set, frozenset)):
            stack.extend(obj)
        else:
            d = getattr(obj, "__dict__", None)
            if isinstance(d, dict):
                stack.append(d)
            for cls in type(obj).__mro__:
                slots = getattr(cls, "__slots__", ())
                for name in ((slots,) if isinstance(slots, str) else slots):
                    try:
                        stack.append(getattr(obj, name))
                    except AttributeError:
                        pass
    return total


def describe_snapshots(top: int = 8) -> str:
    try:
        from cache import snapshots
        items = list(snapshots._entries.items())
    except Exception:
        return "MEMDETAIL snapshots unavailable"
    sizes = sorted(((deep_size(value), key) for key, (value, _stamp) in items), reverse=True)
    total = sum(size for size, _ in sizes) / (1024.0 * 1024.0)
    parts = " ".join(f"{key}={size / (1024.0 * 1024.0):.2f}MB" for size, key in sizes[:top])
    return f"MEMDETAIL snapshots total={total:.1f}MB: {parts}"


# ---- optional tracemalloc --------------------------------------------------------------------------

def describe_trace(top: int = 6):
    """Two lines, or None when tracing is off."""
    if not _tracing:
        return None
    import tracemalloc
    current, peak = tracemalloc.get_traced_memory()
    rss = rss_mb()
    gap = "n/a" if rss is None else f"{rss - current / (1024.0 * 1024.0):.1f}MB"
    head = (f"MEMTRACE traced={current / (1024.0 * 1024.0):.1f}MB "
            f"traced_peak={peak / (1024.0 * 1024.0):.1f}MB rss_minus_traced={gap}")
    stats = tracemalloc.take_snapshot().statistics("lineno")[:top]
    sites = " | ".join(
        f"{os.path.relpath(s.traceback[0].filename) if s.traceback[0].filename.startswith('/') else s.traceback[0].filename}"
        f":{s.traceback[0].lineno}={s.size / (1024.0 * 1024.0):.1f}MB/{s.count} blocks"
        for s in stats
    )
    return head, f"MEMTRACE top: {sites}"


# ---- the loop --------------------------------------------------------------------------------------

def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _detail_round() -> None:
    log.info(describe_snapshots())
    trace = describe_trace()
    if trace:
        for line in trace:
            log.info(line)


def _loop(interval: float, warn_mb: float, detail_every: float) -> None:
    next_detail = time.monotonic() + detail_every if detail_every > 0 else None
    while True:
        hot = (rss_mb() or 0.0) >= warn_mb
        try:
            (log.warning if hot else log.info)(describe())
            if next_detail is not None and time.monotonic() >= next_detail:
                _detail_round()
                next_detail = time.monotonic() + detail_every
        except Exception:  # a diagnostic must never be able to hurt the app
            pass
        time.sleep(10.0 if hot else interval)


def start() -> bool:
    """Start the logging thread once. Returns False if it is disabled or already running."""
    global _started, _tracing
    interval = _float_env("MEMLOG_SECONDS", 60.0)
    if interval <= 0:
        return False
    with _start_lock:
        if _started:
            return False
        _started = True
    if os.environ.get("MEMLOG_TRACE", "").lower() in ("1", "true", "yes"):
        import tracemalloc
        tracemalloc.start(1)
        _tracing = True
    threading.Thread(
        target=_loop,
        args=(interval, _float_env("MEMLOG_WARN_MB", 350.0), _float_env("MEMLOG_DETAIL_SECONDS", 600.0)),
        name="memlog", daemon=True,
    ).start()
    return True
