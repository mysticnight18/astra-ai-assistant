"""
Astra Voice Profiles — auto-selects tone based on context,
and applies matching macOS `say` voice settings.
Profiles: professional | friendly | jarvis | minimal
"""

import re

# ─── Profile definitions ──────────────────────────────────────────────────────

PROFILES = {
    "professional": {
        "voice": "Karen",
        "rate": 165,
        "description": "Formal, efficient, work-focused tone.",
        "greeting": "Good day, Ishant. How may I assist you?",
        "filler": ["Understood.", "Right away.", "Certainly.", "Of course."],
    },
    "friendly": {
        "voice": "Samantha",
        "rate": 180,
        "description": "Warm, casual, conversational.",
        "greeting": "Hey Ishant! What do you need?",
        "filler": ["Sure!", "On it!", "No problem!", "Got it!"],
    },
    "jarvis": {
        "voice": "Daniel",
        "rate": 155,
        "description": "JARVIS-style: cool, precise, slightly dramatic.",
        "greeting": "At your service, Ishant.",
        "filler": ["Of course.", "Initiating.", "Processing.", "Done."],
    },
    "minimal": {
        "voice": "Samantha",
        "rate": 200,
        "description": "Ultra-brief responses only.",
        "greeting": "Ready.",
        "filler": ["Done.", "OK.", "Set.", "Yes."],
    },
}

_current_profile = "friendly"   # default

# ─── Intent → profile heuristic ──────────────────────────────────────────────

_INTENT_PROFILE_MAP = {
    "work":         "professional",
    "calendar":     "professional",
    "coding":       "jarvis",
    "video_editing":"jarvis",
    "design":       "jarvis",
    "study":        "friendly",
    "relax":        "friendly",
    "greeting":     "friendly",
    "reminder":     "minimal",
    "battery":      "minimal",
    "system_info":  "minimal",
    "time":         "minimal",
    "date":         "minimal",
    "weather":      "friendly",
    "spotify_play": "minimal",
    "spotify_pause":"minimal",
    "spotify_next": "minimal",
}


def auto_select(intent: str):
    """Auto-switch profile based on intent if user hasn't pinned one."""
    global _current_profile
    if not _profile_pinned:
        _current_profile = _INTENT_PROFILE_MAP.get(intent, "friendly")


_profile_pinned = False   # True = user explicitly chose a profile


def set_profile(name: str):
    global _current_profile, _profile_pinned
    name = name.lower().strip()
    if name in PROFILES:
        _current_profile = name
        _profile_pinned = True
        return True
    return False


def unpin():
    global _profile_pinned
    _profile_pinned = False


def current() -> dict:
    return PROFILES[_current_profile]


def current_name() -> str:
    return _current_profile


def get_say_args() -> list[str]:
    p = current()
    return ["-v", p["voice"], "-r", str(p["rate"])]


def greeting() -> str:
    return current()["greeting"]


def filler() -> str:
    import random
    return random.choice(current()["filler"])


# ─── Parse voice change command ───────────────────────────────────────────────

_SWITCH_PATTERNS = [
    # "switch to jarvis", "go to professional mode", "use jarvis voice"
    r"(?:switch|change|use|set|go)\s+(?:to\s+)?(\w+)(?:\s+(?:mode|voice|profile))?",
    # "switch voice to jarvis", "change profile to minimal"
    r"(?:switch|change|use|set)\s+(?:voice|mode|profile)\s+to\s+(\w+)",
    # "jarvis mode", "friendly voice", "minimal profile"
    r"(\w+)\s+(?:mode|voice|profile)",
    # "sound more professional", "be more jarvis"
    r"(?:sound|be)\s+(?:more\s+)?(\w+)",
]


def try_parse_profile_switch(text: str) -> str | None:
    """Returns profile name if text is a voice-change command, else None."""
    t = text.lower().strip()

    # Quick direct match: if the whole utterance is just a profile name
    if t in PROFILES:
        return t

    for pat in _SWITCH_PATTERNS:
        m = re.search(pat, t)
        if m:
            candidate = m.group(1).strip()
            if candidate in PROFILES:
                return candidate
    return None
