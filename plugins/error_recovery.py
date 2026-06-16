"""
Astra Error Recovery — internet monitoring, mic reconnect, retry logic,
graceful fallback responses.
"""
import subprocess
import time
import threading
import socket

_internet_ok = True
_internet_lock = threading.Lock()
_on_internet_restore_callbacks: list = []

# ─── Internet ────────────────────────────────────────────────────────────────

def _check_internet() -> bool:
    try:
        socket.setdefaulttimeout(3)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        return True
    except Exception:
        return False


def internet_monitor_loop(speak_fn):
    """Background thread — polls every 10s, speaks on loss/restore."""
    global _internet_ok
    while True:
        ok = _check_internet()
        with _internet_lock:
            was_ok = _internet_ok
            _internet_ok = ok
        if was_ok and not ok:
            speak_fn("Heads up — I've lost internet connection.")
        elif not was_ok and ok:
            speak_fn("Internet is back. I'm fully online again.")
            for cb in _on_internet_restore_callbacks:
                try:
                    cb()
                except Exception:
                    pass
        time.sleep(10)


def is_online() -> bool:
    with _internet_lock:
        return _internet_ok


def on_internet_restore(fn):
    _on_internet_restore_callbacks.append(fn)


# ─── Retry wrapper ────────────────────────────────────────────────────────────

def retry(fn, retries: int = 2, delay: float = 1.5, fallback=None):
    """
    Call fn(). If it raises, retry up to `retries` times.
    If all fail, return fallback value (or re-raise if fallback is None).
    """
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            print(f"[Retry] attempt {attempt+1} failed: {e}")
            if attempt < retries:
                time.sleep(delay)
    if fallback is not None:
        return fallback
    raise last_exc


# ─── Mic reconnect ───────────────────────────────────────────────────────────

_MIC_FAIL_COUNT = 0
_MIC_MAX_FAILS  = 3


def mic_failure(speak_fn=None):
    """Call on each mic failure. Speaks a warning after threshold."""
    global _MIC_FAIL_COUNT
    _MIC_FAIL_COUNT += 1
    if _MIC_FAIL_COUNT >= _MIC_MAX_FAILS:
        _MIC_FAIL_COUNT = 0
        if speak_fn:
            speak_fn("Having trouble with the microphone. Reconnecting…")
        return True   # caller should reinitialise mic
    return False


def mic_ok():
    global _MIC_FAIL_COUNT
    _MIC_FAIL_COUNT = 0


# ─── Graceful fallback responses ─────────────────────────────────────────────

FALLBACK_RESPONSES = [
    "I didn't quite get that — could you say it again?",
    "Sorry, something went wrong on my end. Try again.",
    "I'm having a moment. Let me try that again.",
    "That didn't work as expected. Please try once more.",
]

_fb_idx = 0

def graceful_fallback() -> str:
    global _fb_idx
    msg = FALLBACK_RESPONSES[_fb_idx % len(FALLBACK_RESPONSES)]
    _fb_idx += 1
    return msg
