"""
Astra Conversation Context — Tracks prior turns so Astra can answer follow-up questions.
e.g. "What's the weather in Mumbai?" → "What about tomorrow?" → Astra knows the city.
"""

import time
import threading
from collections import deque

_CTX_LOCK = threading.Lock()
_MAX_TURNS = 6          # how many turns to keep
_TTL_SECONDS = 120      # context expires after 2 minutes of silence

_turns: deque = deque(maxlen=_MAX_TURNS)
_last_ts: float = 0.0


class Turn:
    __slots__ = ("user", "intent", "result", "ts")

    def __init__(self, user: str, intent: dict, result: str = ""):
        self.user   = user
        self.intent = intent   # the classified dict
        self.result = result   # what Astra said back
        self.ts     = time.time()


# ── Write ────────────────────────────────────────────────────────────────────

def push(user_text: str, intent_dict: dict, astra_response: str = ""):
    global _last_ts
    with _CTX_LOCK:
        _turns.append(Turn(user_text, intent_dict, astra_response))
        _last_ts = time.time()


# ── Read ─────────────────────────────────────────────────────────────────────

def get_recent(n: int = 3) -> list[Turn]:
    """Return up to n most-recent turns (oldest first)."""
    with _CTX_LOCK:
        if time.time() - _last_ts > _TTL_SECONDS:
            _turns.clear()
            return []
        return list(_turns)[-n:]


def last_intent() -> dict:
    with _CTX_LOCK:
        if _turns:
            return _turns[-1].intent
    return {}


def last_city() -> str:
    """Return the city mentioned in the most recent weather query, if any."""
    for t in reversed(list(_turns)):
        if t.intent.get("intent") == "weather":
            return t.intent.get("city", "")
    return ""


def build_context_block() -> str:
    """
    Build a short natural-language context string to prepend to Gemini prompts,
    so follow-up questions are understood correctly.
    """
    recent = get_recent(3)
    if not recent:
        return ""
    lines = []
    for turn in recent:
        lines.append(f"User: {turn.user}")
        if turn.result:
            lines.append(f"Astra: {turn.result}")
    return "Recent conversation:\n" + "\n".join(lines) + "\n\n"


def clear():
    with _CTX_LOCK:
        _turns.clear()
