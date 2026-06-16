"""
Astra Memory Manager — Persistent user memory with auto-save and recall.
Stores facts, preferences, dates, and conversation context.
"""

import json
import os
import re
import datetime
import threading

MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "astra_memory.json")

_memory_lock = threading.Lock()

_DEFAULT = {
    "facts": {},          # "favourite_ide": "VS Code"
    "preferences": {},    # "music_genre": "lofi"
    "dates": {},          # "birthday": "July 15"
    "notes": [],          # free-form notes list
    "last_updated": None
}


def _load() -> dict:
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r") as f:
                data = json.load(f)
                # Ensure all keys exist
                for k, v in _DEFAULT.items():
                    data.setdefault(k, type(v)() if not isinstance(v, type(None)) else v)
                return data
    except Exception as e:
        print(f"[Memory] Load error: {e}")
    return {k: (type(v)() if not isinstance(v, type(None)) else v) for k, v in _DEFAULT.items()}


def _save(data: dict):
    try:
        data["last_updated"] = datetime.datetime.now().isoformat()
        with open(MEMORY_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[Memory] Save error: {e}")


# ── Public API ──────────────────────────────────────────────────────────────

def remember(key: str, value: str, category: str = "facts") -> str:
    """Store a memory. category: facts | preferences | dates | notes"""
    with _memory_lock:
        data = _load()
        if category == "notes":
            data["notes"].append({"note": value, "timestamp": datetime.datetime.now().isoformat()})
        else:
            cat = category if category in ("facts", "preferences", "dates") else "facts"
            data[cat][key.lower().replace(" ", "_")] = value
        _save(data)
    return f"Got it, I've noted that {key} is {value}."


def recall(query: str) -> str:
    """Search all memory for a matching key or value."""
    with _memory_lock:
        data = _load()
    query_lower = query.lower().replace(" ", "_")

    # Direct key match across all categories
    for cat in ("facts", "preferences", "dates"):
        store = data.get(cat, {})
        for k, v in store.items():
            if query_lower in k or k in query_lower:
                return f"Your {k.replace('_', ' ')} is {v}."

    # Search notes
    hits = []
    for entry in data.get("notes", []):
        if any(w in entry.get("note", "").lower() for w in query.lower().split()):
            hits.append(entry["note"])
    if hits:
        return "From my notes: " + ". ".join(hits[-3:])

    return None  # Caller handles "I don't know"


def recall_all() -> dict:
    """Return the full memory dict."""
    with _memory_lock:
        return _load()


def forget(key: str) -> str:
    """Remove a memory entry."""
    with _memory_lock:
        data = _load()
        key_norm = key.lower().replace(" ", "_")
        removed = False
        for cat in ("facts", "preferences", "dates"):
            if key_norm in data[cat]:
                del data[cat][key_norm]
                removed = True
        _save(data)
    return f"Forgotten: {key}." if removed else f"I don't have anything stored for {key}."


# ── Auto-extract memory from natural speech ─────────────────────────────────

_REMEMBER_PATTERNS = [
    # "remember my favourite IDE is VS Code"
    (r"remember (?:my |that )?(.+?) is (.+)", lambda m: (m.group(1).strip(), m.group(2).strip(), "facts")),
    # "my favourite colour is blue"
    (r"my (.+?) is (.+)", lambda m: (m.group(1).strip(), m.group(2).strip(), "preferences")),
    # "I prefer X"
    (r"i prefer (.+)", lambda m: ("preference", m.group(1).strip(), "preferences")),
    # "my birthday is July 15"
    (r"my birthday is (.+)", lambda m: ("birthday", m.group(1).strip(), "dates")),
    # "note that ..."
    (r"(?:note|remember) that (.+)", lambda m: ("note", m.group(1).strip(), "notes")),
]

_RECALL_PATTERNS = [
    r"what(?:'s| is) my (.+?)(?:\?|$)",
    r"do you (?:know|remember) my (.+?)(?:\?|$)",
    r"recall (?:my )?(.+?)(?:\?|$)",
]

_FORGET_PATTERNS = [
    r"forget (?:my |about )?(.+?)(?:\?|$)",
    r"don'?t (?:remember|keep) (.+?)(?:\?|$)",
]


def try_auto_remember(text: str):
    """
    Returns (key, value, category) if text contains a memorisable statement,
    else None.
    """
    t = text.lower().strip()
    for pattern, extractor in _REMEMBER_PATTERNS:
        m = re.search(pattern, t)
        if m:
            try:
                return extractor(m)
            except Exception:
                pass
    return None


def try_auto_recall(text: str):
    """Returns query string if text is asking for a recalled fact, else None."""
    t = text.lower().strip()
    for pattern in _RECALL_PATTERNS:
        m = re.search(pattern, t)
        if m:
            return m.group(1).strip()
    return None


def try_auto_forget(text: str):
    """Returns key string if text is asking to forget something, else None."""
    t = text.lower().strip()
    for pattern in _FORGET_PATTERNS:
        m = re.search(pattern, t)
        if m:
            return m.group(1).strip()
    return None
